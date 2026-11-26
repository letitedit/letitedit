"""Model worker for letitedit's search and speaker tools (index_tools.py).

Runs in C:\\LetItEdit\\envs\\models (Python 3.12, torch + CUDA), not in the bridge's Python. index_tools starts it and
keeps it alive so each model loads once. Models (Hugging Face cache, HF_HOME):
    OpenCLIP ViT-B-32 laion2B-s34B-b79K   pictures and text (picture search, transcript meaning)
    CLAP laion/clap-htsat-unfused         sound windows and text (sound search)
    SpeechBrain spkrec-ecapa-voxceleb     voice embeddings of speech segments (speakers)
    YuNet + SFace (OpenCV, files in C:\\LetItEdit\\vfx\\models)   faces
Only those exact files are fetched, and only when they are not already in the cache.

Protocol: one JSON request per stdin line, one JSON reply per stdout line, with the request's "id":
    {"id": 1, "op": "...", ...}  ->  {"id": 1, ...}  or  {"id": 1, "error": "..."}
The first line written is {"ready": true, "device": "cuda"|"cpu", "torch": ...}. Exits on EOF or after IDLE s idle.

Ops (arrays go to .npz files whose paths are in the request; small results come back inline):
    video       jobs: [{video, out_w, out_h, every_s, mode: keyframes|exact, clip: npz|null, faces: npz|null}]
                one decode per video (ffmpeg, several videos at once) feeds CLIP and/or the face models.
                clip npz:  times [n], emb [n, V, 512] f16, views [V]
                faces npz: times [m], box [m, 4] (x0 y0 x1 y1, decoded-frame pixels), score [m], emb [m, 128] f16,
                           sampled [n] (every sampled frame time), size [2] (decoded w, h)
    clip_text   texts, out? -> emb [len(texts), 512]
    clip_frames video, times, out_w, out_h -> emb [len(times), V, 512] (exact frames, seeking)
    clip_window video, start, dur, step, out_w, out_h, out -> npz: times [n], emb [n, V, 512] f16, views [V]
                (one decode of a short window, every step-th frame; range_search.py)
    audio       path, win_s, hop_s, out -> start [n], end [n], emb [n, 512] f16 (CLAP, each window repeat-padded to 10 s)
    clap_text   texts -> emb
    clap_span   path, start, end, win_s, hop_s -> emb (mean of the span's windows, normalised)
    ecapa       path, segments [[s, e]], out -> emb [n, 192] f16 (normalised)
"""
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))   # install root: LETITEDIT_ROOT, else the folder above bridge
import os as _os, sys as _sys
_sys.path.append(_os.path.dirname(_os.path.abspath(__file__)))   # started with -I, which leaves this folder off sys.path; last, so it shadows nothing
import quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time

import numpy as np

IDLE = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
VFX_MODELS = os.environ.get('LETITEDIT_VFX_MODELS', (_SAI_ROOT + '\\vfx\\models'))
YUNET = os.path.join(VFX_MODELS, 'yunet_2023mar.onnx')
SFACE = os.path.join(VFX_MODELS, 'face_recognition_sface_2021dec.onnx')
CLIP_REPO = ('laion/CLIP-ViT-B-32-laion2B-s34B-b79K', ['open_clip_config.json', 'open_clip_model.safetensors'])
CLAP_REPO = ('laion/clap-htsat-unfused', ['config.json', 'preprocessor_config.json', 'tokenizer_config.json',
                                          'special_tokens_map.json', 'vocab.json', 'merges.txt', 'tokenizer.json',
                                          'pytorch_model.bin'])
ECAPA_REPO = ('speechbrain/spkrec-ecapa-voxceleb', ['hyperparams.yaml', 'config.json', 'embedding_model.ckpt',
                                                    'mean_var_norm_emb.ckpt', 'classifier.ckpt', 'label_encoder.txt'])
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
SR_CLAP, SR_ECAPA = 48000, 16000

_models = {}
_lock = threading.Lock()


def _all_cached():
    """True when every file above is already in the Hugging Face cache: then the libraries run offline (no hub
    requests at all); otherwise the missing approved files are fetched on first use."""
    import glob
    home = os.environ.get('HF_HOME') or os.path.join(os.path.expanduser('~'), '.cache', 'huggingface')
    for repo, files in (CLIP_REPO, CLAP_REPO, ECAPA_REPO):
        base = os.path.join(home, 'hub', 'models--' + repo.replace('/', '--'), 'snapshots', '*')
        if not all(glob.glob(os.path.join(base, f)) for f in files):
            return False
    return True


if _all_cached():
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'


def _snapshot(repo_files):
    """Local folder holding exactly these files of a Hugging Face repo (fetched once if missing)."""
    from huggingface_hub import hf_hub_download
    repo, files = repo_files
    folder = None
    for f in files:
        try:
            p = hf_hub_download(repo, f, local_files_only=True)
        except Exception:  # noqa: BLE001 - not in the cache yet: fetch this one file
            p = hf_hub_download(repo, f)
        folder = os.path.dirname(p)
    return folder


def _device():
    import torch
    return 'cuda' if torch.cuda.is_available() else 'cpu'


# ------------------------------------------------------------------ models

def clip_model():
    with _lock:
        if 'clip' not in _models:
            import open_clip
            import torch
            folder = _snapshot(CLIP_REPO)
            model, _, _ = open_clip.create_model_and_transforms('local-dir:' + folder)
            dev = _device()
            model = model.to(dev).eval()
            if dev == 'cuda':
                model = model.half()
            tok = open_clip.get_tokenizer('local-dir:' + folder)
            mean = torch.tensor(CLIP_MEAN, device=dev).view(1, 3, 1, 1)
            std = torch.tensor(CLIP_STD, device=dev).view(1, 3, 1, 1)
            _models['clip'] = (model, tok, mean, std, dev)
        return _models['clip']


def clap_model():
    with _lock:
        if 'clap' not in _models:
            from transformers import AutoTokenizer, ClapModel
            from transformers.audio_utils import mel_filter_bank
            import torch
            folder = _snapshot(CLAP_REPO)
            dev = _device()
            model = ClapModel.from_pretrained(folder, local_files_only=True).to(dev).eval()
            tok = AutoTokenizer.from_pretrained(folder, local_files_only=True)
            cfg = json.load(open(os.path.join(folder, 'preprocessor_config.json'), encoding='utf-8-sig'))
            n_fft, hop = int(cfg.get('fft_window_size', 1024)), int(cfg.get('hop_length', 480))
            mel = mel_filter_bank(num_frequency_bins=n_fft // 2 + 1, num_mel_filters=int(cfg.get('feature_size', 64)),
                                  min_frequency=float(cfg.get('frequency_min', 50)),
                                  max_frequency=float(cfg.get('frequency_max', 14000)),
                                  sampling_rate=int(cfg.get('sampling_rate', SR_CLAP)), norm='slaney', mel_scale='slaney')
            fb = torch.tensor(mel, dtype=torch.float32, device=dev)            # [513, 64]
            win = torch.hann_window(n_fft, periodic=True, device=dev)
            _models['clap'] = (model, tok, fb, win, n_fft, hop, int(cfg.get('nb_max_samples', 480000)), dev)
        return _models['clap']


def ecapa_model():
    with _lock:
        if 'ecapa' not in _models:
            import warnings
            warnings.filterwarnings('ignore')
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy
            folder = _snapshot(ECAPA_REPO)
            dev = _device()
            enc = EncoderClassifier.from_hparams(source=folder, savedir=folder,
                                                 run_opts={'device': 'cuda:0' if dev == 'cuda' else dev},
                                                 local_strategy=LocalStrategy.NO_LINK)
            enc.eval()
            _models['ecapa'] = (enc, dev)
        return _models['ecapa']


class FaceModels:
    """YuNet + SFace for one thread (OpenCV objects are not shared between threads)."""

    def __init__(self, w, h):
        import cv2
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        self.det = cv2.FaceDetectorYN.create(YUNET, '', (w, h), 0.5, 0.3, 50)
        self.rec = cv2.FaceRecognizerSF.create(SFACE, '')

    def run(self, bgr):
        _, found = self.det.detect(bgr)
        out = []
        if found is None:
            return out
        for f in found:
            if f[2] < 8 or f[3] < 8:
                continue
            aligned = self.rec.alignCrop(bgr, f)
            feat = self.rec.feature(aligned).reshape(-1).astype(np.float32)
            feat /= (np.linalg.norm(feat) + 1e-9)
            out.append(([float(f[0]), float(f[1]), float(f[0] + f[2]), float(f[1] + f[3])], float(f[14]), feat))
        return out


# ------------------------------------------------------------------ pictures

def clip_views(bgr):
    """(views [V, 224, 224, 3] RGB uint8, names): the whole frame letterboxed, then square tiles along its long side."""
    import cv2
    h, w = bgr.shape[:2]
    s = 224.0 / min(h, w)
    small = cv2.resize(bgr, (max(224, round(w * s)), max(224, round(h * s))), interpolation=cv2.INTER_AREA)
    small = small[:, :, ::-1]
    h2, w2 = small.shape[:2]
    pad = (CLIP_MEAN * 255).astype(np.uint8)
    whole = np.empty((224, 224, 3), dtype=np.uint8)
    whole[:] = pad
    f = 224.0 / max(h2, w2)
    fit = cv2.resize(np.ascontiguousarray(small), (max(1, round(w2 * f)), max(1, round(h2 * f))), interpolation=cv2.INTER_AREA)
    y0, x0 = (224 - fit.shape[0]) // 2, (224 - fit.shape[1]) // 2
    whole[y0:y0 + fit.shape[0], x0:x0 + fit.shape[1]] = fit
    views, names = [whole], ['whole']
    long_ = max(h2, w2)
    if long_ - 224 >= 8:
        k = max(2, math.ceil(long_ / 224) + 1)
        offs = [round(i * (long_ - 224) / (k - 1)) for i in range(k)]
        labels = (['top', 'middle', 'bottom'] if h2 > w2 else ['left', 'center', 'right']) if k == 3 else \
            [f'{"y" if h2 > w2 else "x"}{o}' for o in offs]
        for o, lab in zip(offs, labels):
            views.append(small[o:o + 224, :224] if h2 > w2 else small[:224, o:o + 224])
            names.append(lab)
    return np.stack([np.ascontiguousarray(v) for v in views]), names


def clip_embed_images(arr):
    """arr [N, 224, 224, 3] RGB uint8 -> [N, 512] float32, L2-normalised."""
    import torch
    model, _, mean, std, dev = clip_model()
    out = []
    with torch.no_grad():
        for k in range(0, len(arr), 256):
            x = torch.from_numpy(arr[k:k + 256]).to(dev).permute(0, 3, 1, 2).float().div_(255.0)
            x = (x - mean) / std
            if dev == 'cuda':
                x = x.half()
            e = model.encode_image(x).float()
            e = e / e.norm(dim=-1, keepdim=True).clamp_min(1e-9)
            out.append(e.cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


def clip_embed_texts(texts):
    import torch
    model, tok, _, _, dev = clip_model()
    out = []
    with torch.no_grad():
        for k in range(0, len(texts), 256):
            t = tok(list(texts[k:k + 256])).to(dev)
            e = model.encode_text(t).float()
            e = e / e.norm(dim=-1, keepdim=True).clamp_min(1e-9)
            out.append(e.cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


SHOWINFO = re.compile(r'\bn:\s*(\d+)\b.*?\bpts_time:\s*([-+0-9.eE]+|nan)')


def decode_frames(ffmpeg, video, out_w, out_h, every_s, mode, start=None):
    """Yield (time, bgr frame) of the sampled frames: keyframes nearest a grid of every_s seconds, or exact frames
    every every_s seconds (ffmpeg fps filter)."""
    args = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'info']
    if mode == 'keyframes':
        args += ['-skip_frame', 'nokey']
    args += ['-i', video, '-an', '-sn', '-dn']
    if mode == 'keyframes':
        vf = f'showinfo,scale={out_w}:{out_h}:flags=area'
    else:
        vf = f'fps=1/{every_s:g}:round=near,showinfo,scale={out_w}:{out_h}:flags=area'
    args += ['-vf', vf, '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    times, cond, done = [], threading.Condition(), [False]

    def read_err():
        for raw in p.stderr:
            line = raw.decode('utf-8', 'replace')
            if 'Parsed_showinfo' in line and 'pts_time' in line:
                m = SHOWINFO.search(line)
                if m:
                    with cond:
                        try:
                            times.append(float(m.group(2)))
                        except ValueError:
                            times.append(float('nan'))
                        cond.notify_all()
        with cond:
            done[0] = True
            cond.notify_all()
    th = threading.Thread(target=read_err, daemon=True)
    th.start()
    size = out_w * out_h * 3
    prev = None                 # keyframes mode: the last keyframe seen (t, frame)
    last_t = None               # time of the last frame yielded
    k = 0                       # next grid point: k * every_s
    i = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if not buf or len(buf) < size:
                break
            with cond:
                while len(times) <= i and not done[0]:
                    cond.wait(5)
                t = times[i] if len(times) > i else (i * every_s if mode != 'keyframes' else float('nan'))
            i += 1
            if t != t:                                   # no time for this frame: skip it
                continue
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(out_h, out_w, 3)
            if mode != 'keyframes':
                yield t, frame
                continue
            # keyframes: for each grid time g = k * every_s, the keyframe nearest it (each keyframe at most once)
            while k * every_s <= t:
                g = k * every_s
                cand = (t, frame) if prev is None or abs(t - g) < abs(prev[0] - g) else prev
                if cand[0] != last_t:
                    last_t = cand[0]
                    yield cand
                k += 1
            prev = (t, frame)
        if mode == 'keyframes' and prev is not None and prev[0] != last_t and k * every_s - prev[0] <= every_s / 2:
            yield prev
    finally:
        try:
            p.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        p.wait()
        th.join(timeout=5)


def op_video(req):
    ffmpeg = req['ffmpeg']
    jobs = req['jobs']
    nthreads = max(1, min(int(req.get('threads', 4)), len(jobs)))
    q = queue.Queue(maxsize=96)
    todo = queue.Queue()
    for j, job in enumerate(jobs):
        todo.put(j)
    want_clip = any(job.get('clip') for job in jobs)
    if want_clip:
        clip_model()

    def worker():
        face_models = {}
        while True:
            try:
                j = todo.get_nowait()
            except queue.Empty:
                return
            job = jobs[j]
            t0 = time.time()
            try:
                w, h = int(job['out_w']), int(job['out_h'])
                fm = None
                if job.get('faces'):
                    fm = face_models.get((w, h)) or face_models.setdefault((w, h), FaceModels(w, h))
                for t, frame in decode_frames(ffmpeg, job['video'], w, h, float(job['every_s']), job['mode']):
                    views = names = faces = None
                    if job.get('clip'):
                        views, names = clip_views(frame)
                    if fm is not None:
                        faces = fm.run(frame)
                    q.put(('frame', j, t, views, names, faces))
                q.put(('end', j, time.time() - t0, None, None, None))
            except Exception as e:  # noqa: BLE001
                q.put(('error', j, f'{type(e).__name__}: {e}', None, None, None))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(nthreads)]
    for th in threads:
        th.start()
    state = [{'times': [], 'emb': [], 'names': None, 'faces': [], 'decode_s': 0.0} for _ in jobs]
    pending = []          # (job, frame index, views)
    finished, errors, results = set(), {}, {}

    def flush():
        if not pending:
            return
        arr = np.concatenate([v for _, _, v in pending])
        emb = clip_embed_images(arr)
        k = 0
        for j, idx, v in pending:
            state[j]['emb'][idx] = emb[k:k + len(v)].astype(np.float16)
            k += len(v)
        pending.clear()

    def save(j):
        job, st = jobs[j], state[j]
        times = np.array(st['times'], dtype=np.float64)
        if job.get('clip'):
            v = len(st['names'] or ['whole'])
            emb = np.stack(st['emb']) if st['emb'] else np.zeros((0, v, 512), np.float16)
            _savez(job['clip'], times=times, emb=emb, views=np.array(st['names'] or ['whole']))
        if job.get('faces'):
            ft = np.array([f[0] for f in st['faces']], dtype=np.float64)
            box = np.array([f[1] for f in st['faces']], dtype=np.float32).reshape(-1, 4)
            score = np.array([f[2] for f in st['faces']], dtype=np.float32)
            emb = np.stack([f[3] for f in st['faces']]).astype(np.float16) if st['faces'] else np.zeros((0, 128), np.float16)
            _savez(job['faces'], times=ft, box=box, score=score, emb=emb, sampled=times,
                   size=np.array([int(job['out_w']), int(job['out_h'])]))
        results[j] = {'video': job['video'], 'frames': len(st['times']), 'faces': len(st['faces']),
                      'decode_s': round(st['decode_s'], 2)}

    alive = len(jobs)
    while alive:
        kind, j, a, views, names, faces = q.get()
        if kind == 'frame':
            st = state[j]
            idx = len(st['times'])
            st['times'].append(a)
            if views is not None:
                st['names'] = names
                st['emb'].append(None)
                pending.append((j, idx, views))
            if faces:
                for box, score, feat in faces:
                    st['faces'].append((a, box, score, feat))
            if sum(len(v) for _, _, v in pending) >= 256:
                flush()
        elif kind == 'end':
            state[j]['decode_s'] = a
            finished.add(j)
            alive -= 1
        else:
            errors[j] = a
            alive -= 1
        if finished:
            flush()
            for jj in sorted(finished):
                save(jj)
            finished.clear()
    flush()
    return {'done': [results[j] for j in sorted(results)],
            'errors': [{'video': jobs[j]['video'], 'error': e} for j, e in errors.items()]}


def op_clip_frames(req):
    """Exact frames at the given times (accurate seek), embedded with the same views as the index."""
    out = []
    names = None
    w, h = int(req['out_w']), int(req['out_h'])
    for t in req['times']:
        args = [req['ffmpeg'], '-hide_banner', '-nostdin', '-v', 'error', '-ss', f'{max(0.0, float(t)):.3f}',
                '-i', req['video'], '-frames:v', '1', '-vf', f'scale={w}:{h}:flags=area', '-f', 'rawvideo',
                '-pix_fmt', 'bgr24', '-']
        r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
        if len(r.stdout) < w * h * 3:
            out.append(None)
            continue
        frame = np.frombuffer(r.stdout[:w * h * 3], dtype=np.uint8).reshape(h, w, 3)
        views, names = clip_views(frame)
        out.append(clip_embed_images(views))
    return {'emb': [None if e is None else e.round(5).tolist() for e in out], 'views': names}


# ------------------------------------------------------------------ sound

def decode_audio(ffmpeg, path, sr, start=None, end=None):
    args = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error']
    if start is not None:
        args += ['-ss', f'{max(0.0, float(start)):.3f}']
    if end is not None:
        args += ['-t', f'{max(0.05, float(end) - float(start or 0)):.3f}']
    args += ['-i', path, '-vn', '-sn', '-dn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    data = r.stdout[:len(r.stdout) - len(r.stdout) % 4]
    return np.frombuffer(data, dtype=np.float32).copy()


def clap_mels(wins):
    """CLAP (unfused) input features for a batch of 48 kHz windows, on the GPU: each window repeat-padded to 10 s,
    power spectrogram (hann 1024, hop 480, centred, reflect), slaney mel 64, dB. Matches ClapFeatureExtractor."""
    import torch
    model, tok, fb, win, n_fft, hop, max_len, dev = clap_model()
    batch = np.zeros((len(wins), max_len), dtype=np.float32)
    for i, w in enumerate(wins):
        w = w[:max_len]
        if 0 < len(w) < max_len:
            w = np.tile(w, int(max_len / len(w)))
        batch[i, :len(w)] = w
    x = torch.from_numpy(batch).to(dev)
    spec = torch.stft(x, n_fft, hop_length=hop, window=win, center=True, pad_mode='reflect', return_complex=True)
    power = spec.real ** 2 + spec.imag ** 2                       # [B, 513, frames]
    mel = torch.matmul(power.transpose(1, 2), fb).clamp_min(1e-10)  # [B, frames, 64]
    return (10.0 * torch.log10(mel)).unsqueeze(1)                   # [B, 1, frames, 64]


def clap_embed_windows(wins):
    import torch
    model = clap_model()[0]
    out = []
    with torch.no_grad():
        for k in range(0, len(wins), 32):
            feats = clap_mels(wins[k:k + 32])
            longer = torch.zeros((feats.shape[0], 1), dtype=torch.bool, device=feats.device)
            e = model.get_audio_features(input_features=feats, is_longer=longer).pooler_output.float()
            e = e / e.norm(dim=-1, keepdim=True).clamp_min(1e-9)
            out.append(e.cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


def windows(n_samples, sr, win_s, hop_s, offset=0.0, min_s=0.25):
    """[(start_s, end_s, a, b)] windows of win_s every hop_s over n samples (the last one may be shorter)."""
    out = []
    win, hop = max(1, int(round(win_s * sr))), max(1, int(round(hop_s * sr)))
    a = 0
    while a < n_samples:
        b = min(n_samples, a + win)
        if b - a >= min_s * sr or not out:
            out.append((round(offset + a / sr, 3), round(offset + b / sr, 3), a, b))
        if b >= n_samples:
            break
        a += hop
    return out


def op_audio(req):
    t0 = time.time()
    y = decode_audio(req['ffmpeg'], req['path'], SR_CLAP)
    ws = windows(len(y), SR_CLAP, float(req['win_s']), float(req['hop_s']))
    emb = clap_embed_windows([y[a:b] for _, _, a, b in ws]) if ws else np.zeros((0, 512), np.float32)
    _savez(req['out'], start=np.array([w[0] for w in ws]), end=np.array([w[1] for w in ws]), emb=emb.astype(np.float16))
    return {'windows': len(ws), 'seconds': round(len(y) / SR_CLAP, 3), 'took_s': round(time.time() - t0, 2)}


def op_clap_span(req):
    s, e = float(req['start']), float(req['end'])
    y = decode_audio(req['ffmpeg'], req['path'], SR_CLAP, s, e)
    ws = windows(len(y), SR_CLAP, float(req['win_s']), float(req['hop_s']), offset=s)
    if not ws:
        return {'emb': None}
    emb = clap_embed_windows([y[a:b] for _, _, a, b in ws]).mean(axis=0)
    emb /= (np.linalg.norm(emb) + 1e-9)
    return {'emb': emb.round(6).tolist(), 'windows': len(ws)}


def op_clap_text(req):
    import torch
    model, tok, *_ = clap_model()
    dev = _models['clap'][-1]
    with torch.no_grad():
        t = tok(list(req['texts']), padding=True, return_tensors='pt').to(dev)
        e = model.get_text_features(**t).pooler_output.float()
        e = e / e.norm(dim=-1, keepdim=True).clamp_min(1e-9)
    return {'emb': e.cpu().numpy().round(6).tolist()}


# ------------------------------------------------------------------ voices

def op_ecapa(req):
    import torch
    t0 = time.time()
    enc, dev = ecapa_model()
    y = decode_audio(req['ffmpeg'], req['path'], SR_ECAPA)
    segs = req['segments']
    clips = []
    for s, e in segs:
        a, b = int(max(0.0, float(s)) * SR_ECAPA), int(max(0.0, float(e)) * SR_ECAPA)
        c = y[a:b]
        if len(c) < SR_ECAPA // 4:
            c = np.pad(c, (0, SR_ECAPA // 4 - len(c)))
        clips.append(c)
    out = []
    order = sorted(range(len(clips)), key=lambda i: len(clips[i]))
    emb = [None] * len(clips)
    with torch.no_grad():
        for k in range(0, len(order), 32):
            idx = order[k:k + 32]
            n = max(len(clips[i]) for i in idx)
            batch = np.zeros((len(idx), n), dtype=np.float32)
            lens = np.zeros(len(idx), dtype=np.float32)
            for r, i in enumerate(idx):
                batch[r, :len(clips[i])] = clips[i]
                lens[r] = len(clips[i]) / n
            e = enc.encode_batch(torch.from_numpy(batch).to(dev), torch.from_numpy(lens).to(dev)).squeeze(1).float()
            e = e / e.norm(dim=-1, keepdim=True).clamp_min(1e-9)
            e = e.cpu().numpy()
            for r, i in enumerate(idx):
                emb[i] = e[r]
    arr = np.stack(emb).astype(np.float16) if emb else np.zeros((0, 192), np.float16)
    _savez(req['out'], segments=np.array(segs, dtype=np.float64).reshape(-1, 2), emb=arr)
    return {'segments': len(segs), 'took_s': round(time.time() - t0, 2)}


# ------------------------------------------------------------------ plumbing

def _savez(path, **arrays):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp.npz'
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def op_clip_text(req):
    emb = clip_embed_texts(req['texts'])
    if req.get('out'):
        _savez(req['out'], emb=emb.astype(np.float16), texts=np.array(req['texts']))
        return {'n': len(req['texts'])}
    return {'emb': emb.round(6).tolist()}


def op_clip_window(req):
    """Frames of video[start, start + dur) decoded once (accurate seek), every `step`-th frame kept, embedded with the
    same views as the index. Writes times [n] (presentation seconds), emb [n, V, 512] f16, views [V] to `out`.
    Used by range_search.py to score a few seconds around a search hit densely."""
    ffmpeg, video = req['ffmpeg'], req['video']
    w, h = int(req['out_w']), int(req['out_h'])
    start, dur, step = max(0.0, float(req['start'])), float(req['dur']), max(1, int(req.get('step', 1)))
    args = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'info', '-ss', f'{start:.4f}', '-i', video, '-t', f'{dur:.4f}',
            '-an', '-sn', '-dn', '-vf', f'showinfo,scale={w}:{h}:flags=area', '-fps_mode', 'passthrough',
            '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    times = []
    for line in r.stderr.decode('utf-8', 'replace').splitlines():
        if 'Parsed_showinfo' in line and 'pts_time' in line:
            m = SHOWINFO.search(line)
            if m:
                try:
                    times.append(float(m.group(2)))
                except ValueError:
                    times.append(float('nan'))
    size = w * h * 3
    n = min(len(r.stdout) // size, len(times))
    keep_t, views_all, names = [], [], None
    for i in range(0, n, step):
        t = times[i]
        if t != t:
            continue
        frame = np.frombuffer(r.stdout[i * size:(i + 1) * size], dtype=np.uint8).reshape(h, w, 3)
        views, names = clip_views(frame)
        keep_t.append(start + t)
        views_all.append(views)
    if views_all:
        arr = np.concatenate(views_all)
        emb = clip_embed_images(arr).reshape(len(views_all), len(names), -1)
    else:
        emb = np.zeros((0, 1, 512), np.float32)
    _savez(req['out'], times=np.array(keep_t, dtype=np.float64), emb=emb.astype(np.float16),
           views=np.array(names or ['whole']))
    return {'frames': len(keep_t), 'decoded': n}


OPS = {'video': op_video, 'clip_text': op_clip_text, 'clip_frames': op_clip_frames, 'audio': op_audio,
       'clap_text': op_clap_text, 'clap_span': op_clap_span, 'ecapa': op_ecapa, 'clip_window': op_clip_window,
       'ping': lambda req: {'pong': True, 'loaded': sorted(_models)}}


def main():
    import torch
    dev = _device()
    out = sys.stdout
    out.write(json.dumps({'ready': True, 'device': dev, 'torch': torch.__version__,
                          'gpu': torch.cuda.get_device_name(0) if dev == 'cuda' else None}) + '\n')
    out.flush()
    last = [time.time()]
    busy = [False]

    def watchdog():
        while True:
            time.sleep(15)
            if not busy[0] and time.time() - last[0] > IDLE:
                os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        busy[0] = True
        req = {}
        try:
            req = json.loads(line)
            t0 = time.time()
            reply = OPS[req['op']](req)
            reply['op_s'] = round(time.time() - t0, 3)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc(file=sys.stderr)
            reply = {'error': f'{type(e).__name__}: {e}'}
        reply['id'] = req.get('id')
        out.write(json.dumps(reply) + '\n')
        out.flush()
        sys.stderr.flush()
        busy[0] = False
        last[0] = time.time()


if __name__ == '__main__':
    main()
