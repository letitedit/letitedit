"""Learn's sound-effect devices (style_import_sound.find_devices; T198 2d): the model steps, in the models
environment, isolated (python -I sfx_devices_worker.py JOB.json). JOB.json: {"ffmpeg": ..., "steps": [...]} with steps
  {"op": "dnr", "code_dir", "weights_dir", "in", "out_dir"}  film-sound separation with DBS-TIGER-DnR (Apache-2.0):
      music.wav, sfx.wav, speech.wav (44.1 kHz mono, 16-bit), 6 s windows every 3 s as in its training recipe;
  {"op": "sed", "model_file", "jobs": [{"in", "out"}]}  frame-level sound events, PANNs Cnn14_DecisionLevelMax on
      AudioSet (weights CC BY 4.0, Zenodo 3987831); out .npz: times (a 40 ms grid), probs (float16, the kept
      classes), classes;
  {"op": "clap", "hf_home", "jobs": [{"audio", "windows": [[a, b], ...], "out"}]}  CLAP audio embeddings
      (laion/clap-htsat-unfused, already on the PC; never downloaded here), unit length, in order (.npy).
The clap_text operation embeds texts to a unit-length matrix in out. The panns_names operation scores all 527
AudioSet classes for each audio window, padding short windows to two seconds. Both use already installed models.
Prints one JSON line at the end: what each step took. Every model is released before the next loads.

The sound-event network below is Cnn14_DecisionLevelMax from qiuqiangkong/audioset_tagging_cnn (MIT, Copyright (c)
2018-2020 Qiuqiang Kong), copied without training-only parts; its STFT and mel layers are rebuilt in plain torch from
the weights the checkpoint stores, so no new package is needed.
"""
import gc
import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

SED_SR = 32000
HOP = 320
SEG = HOP * 32                 # one output segment: 10240 samples, 0.32 s
SHIFTS = 8                     # 8 x 40 ms
CTX = 6                        # segments of context on each side of a chunk
CHUNK = 94                     # segments a chunk keeps (about 30 s)
KEEP = [0, 137, 205, 215, 319, 356, 378, 384, 385, 407, 416, 417, 434, 445, 449, 459, 460, 461, 462, 463, 464, 465,
        466, 467, 468, 469, 470, 471, 472, 473, 474, 475, 476, 477, 478, 479, 480, 481, 482, 483, 484, 485, 486, 487,
        488, 489, 490, 491, 492, 493, 494, 495, 496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506, 507, 508, 509,
        510, 511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521, 522, 523, 524, 525, 526]
# 0 Speech, 137 Music, then the effect-like classes (chime, scratching, beeps, ding-dong, zipper, typing, typewriter,
# tick, camera, SLR camera, burst/pop, splash, pour, and the generic sounds block 459-526: whoosh, thump, bang, slap,
# smash, breaking, bouncing, whip, flap, scratch, scrape, rub, roll, crushing, crumpling, tearing, beep, ping, ding,
# clang, squeal, creak, rustle, whir, clatter, sizzle, clicking, clickety-clack, rumble, plop, jingle, hum, zing,
# boing, crunch, silence, sine wave, harmonic, chirp tone, sound effect, pulse, inside/outside, reverberation, echo,
# noise, environmental noise, static, mains hum, distortion, sidetone, cacophony, white/pink noise, throbbing,
# vibration, television, radio, field recording)


class ConvBlock(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, 3, 1, 1, bias=False)
        self.conv2 = nn.Conv2d(cout, cout, 3, 1, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(cout)
        self.bn2 = nn.BatchNorm2d(cout)

    def forward(self, x, pool):
        x = F.relu_(self.bn1(self.conv1(x)))
        x = F.relu_(self.bn2(self.conv2(x)))
        return F.avg_pool2d(x, kernel_size=pool)


class STFT(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv_real = nn.Conv1d(1, 513, 1024, stride=HOP, bias=False)
        self.conv_imag = nn.Conv1d(1, 513, 1024, stride=HOP, bias=False)


class Spectrogram(nn.Module):
    def __init__(self):
        super().__init__()
        self.stft = STFT()

    def forward(self, x):                               # (B, samples) -> (B, 1, frames, 513) power
        x = F.pad(x[:, None, :], (512, 512), mode='reflect')
        re = self.stft.conv_real(x)
        im = self.stft.conv_imag(x)
        return (re ** 2 + im ** 2)[:, None, :, :].transpose(2, 3)


class Logmel(nn.Module):
    def __init__(self):
        super().__init__()
        self.melW = nn.Parameter(torch.zeros(513, 64), requires_grad=False)

    def forward(self, x):
        return 10.0 * torch.log10(torch.clamp(torch.matmul(x, self.melW), min=1e-10))


class Cnn14DecisionLevelMax(nn.Module):
    def __init__(self):
        super().__init__()
        self.spectrogram_extractor = Spectrogram()
        self.logmel_extractor = Logmel()
        self.bn0 = nn.BatchNorm2d(64)
        ch = [1, 64, 128, 256, 512, 1024, 2048]
        for i in range(6):
            setattr(self, f'conv_block{i + 1}', ConvBlock(ch[i], ch[i + 1]))
        self.fc1 = nn.Linear(2048, 2048)
        self.fc_audioset = nn.Linear(2048, 527)

    def forward(self, wav):                             # -> (B, segments, 527)
        x = self.logmel_extractor(self.spectrogram_extractor(wav))
        x = self.bn0(x.transpose(1, 3)).transpose(1, 3)
        for i in range(5):
            x = getattr(self, f'conv_block{i + 1}')(x, (2, 2))
        x = self.conv_block6(x, (1, 1))
        x = torch.mean(x, dim=3)
        x = F.max_pool1d(x, 3, 1, 1) + F.avg_pool1d(x, 3, 1, 1)
        x = F.relu_(self.fc1(x.transpose(1, 2)))
        return torch.sigmoid(self.fc_audioset(x))


def load_sed(model_file, dev):
    m = Cnn14DecisionLevelMax()
    ck = torch.load(model_file, map_location='cpu', weights_only=True)
    sd = {k: v for k, v in ck['model'].items() if not k.startswith('spec_augmenter')}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    if missing or unexpected:
        raise RuntimeError(f'checkpoint mismatch: missing {missing[:5]}, unexpected {unexpected[:5]}')
    return m.eval().to(dev)


def decode(ffmpeg, path, sr):
    r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-vn', '-ac', '1', '-ar', str(sr), '-f',
                        'f32le', '-'], capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return np.frombuffer(r.stdout, np.float32).copy()


@torch.no_grad()
def run_sed(model, x, dev):
    """[(t, probs over KEEP)] on the 40 ms grid."""
    rows = []
    keep = torch.tensor(KEEP, device=dev)
    for s in range(SHIFTS):
        off = s * SEG // SHIFTS
        y = x[off:]
        n_seg = max(1, int(np.ceil(len(y) / SEG)))
        y = np.r_[y, np.zeros(n_seg * SEG - len(y), np.float32)]
        for k0 in range(0, n_seg, CHUNK):
            a = max(0, k0 - CTX)
            b = min(n_seg, k0 + CHUNK + CTX)
            seg = torch.from_numpy(y[a * SEG:b * SEG]).to(dev)[None]
            p = model(seg)[0][:, keep]                  # (b - a, kept)
            lo = k0 - a
            hi = lo + min(CHUNK, n_seg - k0)
            p = p[lo:hi].float().cpu().numpy()
            for i in range(len(p)):
                rows.append(((off + (k0 + i) * SEG) / SED_SR, p[i]))
    rows.sort(key=lambda r: r[0])
    return np.array([r[0] for r in rows]), np.stack([r[1] for r in rows]).astype(np.float16)


DNR_SR = 44100
CLAP_SR = 48000
CLAP_REPO = 'laion/clap-htsat-unfused'


def dnr(step, ffmpeg, dev):
    out = Path(step['out_dir'])
    if (out / 'sfx.wav').exists():
        return 0.0
    import soundfile as sf
    sys.path.insert(0, str(step['code_dir']))
    # dbs.models also imports the RoFormer models, which need rotary_embedding_torch (not installed); TIGER doesn't
    stub = types.ModuleType('rotary_embedding_torch')
    stub.RotaryEmbedding = object
    sys.modules.setdefault('rotary_embedding_torch', stub)
    from dbs.models import DBSTIGER
    from dbs.engine import separate
    model = DBSTIGER.from_pretrained(str(step['weights_dir'])).eval().to(dev)
    x = decode(ffmpeg, step['in'], DNR_SR)
    mix = torch.from_numpy(x).view(1, 1, -1).to(dev)
    with torch.inference_mode():
        y = separate(model, mix, {'mode': 'chunked', 'chunk_seconds': 6.0, 'hop_seconds': 3.0}, sample_rate=DNR_SR)[0]
    y = y.float().cpu().numpy().reshape(3, -1)
    out.mkdir(parents=True, exist_ok=True)
    for name, s in zip(('music', 'sfx', 'speech'), y):
        tmp = out / f'{name}.part.wav'
        sf.write(tmp, np.clip(s, -1, 1), DNR_SR, subtype='PCM_16')
        os.replace(tmp, out / f'{name}.wav')
    del model
    return len(x) / DNR_SR


def sed(step, ffmpeg, dev):
    model = load_sed(step['model_file'], dev)
    secs = 0.0
    for j in step['jobs']:
        out = Path(j['out'])
        if out.exists():
            continue
        x = decode(ffmpeg, j['in'], SED_SR)
        secs += len(x) / SED_SR
        t, p = run_sed(model, x, dev)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, times=t, probs=p, classes=np.array(KEEP))
    del model
    return secs


def clap(step, ffmpeg, dev):
    os.environ['HF_HOME'] = step['hf_home']
    os.environ['HF_HUB_OFFLINE'] = '1'
    from transformers import ClapFeatureExtractor, ClapModel
    from huggingface_hub import snapshot_download
    folder = snapshot_download(CLAP_REPO, local_files_only=True)
    model = ClapModel.from_pretrained(folder).eval().to(dev)
    fe = ClapFeatureExtractor.from_pretrained(folder)
    n = 0
    for j in step['jobs']:
        out = Path(j['out'])
        if out.exists():
            continue
        y = decode(ffmpeg, j['audio'], CLAP_SR)
        embs = []
        wins = j['windows']
        for k in range(0, len(wins), 32):
            chunk = []
            for a, b in wins[k:k + 32]:
                seg = y[max(0, int(a * CLAP_SR)):max(0, int(b * CLAP_SR))]
                chunk.append(seg if len(seg) > 480 else np.zeros(480, np.float32))
            feats = {kk: v.to(dev) for kk, v in fe(chunk, sampling_rate=CLAP_SR, return_tensors='pt').items()}
            with torch.no_grad():
                e = model.get_audio_features(**feats)
            e = getattr(e, 'pooler_output', e)
            embs.append(torch.nn.functional.normalize(e.float(), dim=-1).cpu().numpy())
        out.parent.mkdir(parents=True, exist_ok=True)
        np.save(out, np.concatenate(embs) if embs else np.zeros((0, 512), np.float32))
        n += len(wins)
    del model
    return n


def panns_names(step, ffmpeg, dev):
    model = load_sed(step['model_file'], dev)
    count = 0
    for job in step['jobs']:
        audio = decode(ffmpeg, job['audio'], SED_SR)
        embeddings = []
        for start, end in job['windows']:
            segment = audio[max(0, int(start * SED_SR)):max(0, int(end * SED_SR))]
            segment = np.pad(segment, (0, max(0, 2 * SED_SR - len(segment))))
            with torch.no_grad():
                probabilities = model(torch.from_numpy(segment).to(dev)[None])[0].amax(dim=0)
            embeddings.append(probabilities.float().cpu().numpy())
        output = Path(job['out'])
        output.parent.mkdir(parents=True, exist_ok=True)
        np.save(output, np.stack(embeddings) if embeddings else np.zeros((0, 527), np.float32))
        count += len(embeddings)
    del model
    return count


def clap_text(step, ffmpeg, dev):
    os.environ['HF_HOME'] = step['hf_home']
    os.environ['HF_HUB_OFFLINE'] = '1'
    from transformers import AutoTokenizer, ClapModel
    from huggingface_hub import snapshot_download
    folder = snapshot_download(CLAP_REPO, local_files_only=True)
    model = ClapModel.from_pretrained(folder).eval().to(dev)
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    embeddings = []
    for start in range(0, len(step['texts']), 32):
        tokens = tokenizer(step['texts'][start:start + 32], padding=True, truncation=True, return_tensors='pt')
        with torch.no_grad():
            features = model.get_text_features(**{key: value.to(dev) for key, value in tokens.items()})
        features = getattr(features, 'pooler_output', features)
        embeddings.append(F.normalize(features.float(), dim=-1).cpu().numpy())
    output = Path(step['out'])
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, np.concatenate(embeddings))
    del model
    return len(step['texts'])


def main(job_file):
    spec = json.loads(Path(job_file).read_text(encoding='utf-8-sig'))
    # the hub reads its folder once, at import (the DnR step imports it first): set it before any step
    hf = next((s['hf_home'] for s in spec['steps'] if s.get('hf_home')), None)
    if hf:
        os.environ['HF_HOME'] = hf
        os.environ['HF_HUB_OFFLINE'] = '1'
    torch.set_num_threads(4)
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    took = []
    for step in spec['steps']:
        t0 = time.monotonic()
        amount = {'dnr': dnr, 'sed': sed, 'clap': clap, 'clap_text': clap_text,
                  'panns_names': panns_names}[step['op']](step, spec['ffmpeg'], dev)
        took.append({'op': step['op'], 'amount': round(float(amount), 1), 'took_s': round(time.monotonic() - t0, 1)})
        gc.collect()
        if dev == 'cuda':
            torch.cuda.empty_cache()
    print(json.dumps({'device': dev, 'steps': took}))


if __name__ == '__main__':
    main(sys.argv[1])
