"""Model worker for letitedit's model tools (runs in C:\\LetItEdit\\envs\\models, not the bridge's Python).

Started by model_tools.py and kept alive so each model loads once. Models: Demucs (source separation) and
CLAP laion/clap-htsat-unfused (audio-text similarity). Weights live under TORCH_HOME / HF_HOME (set by the bridge).

Protocol: one JSON request per stdin line, one JSON reply per stdout line, matched by "id".
    {"id": 1, "op": "separate", "wav": "...44.1k.wav", "out_dir": "...", "model": "htdemucs", "shifts": 1, "overlap": 0.25}
    {"id": 2, "op": "clap", "wav": "...48k mono.wav", "windows": [[0, 2], [2, 4]], "texts": ["...", ...]}
    {"id": 3, "op": "release"}     models off the GPU (kept in RAM; the next job moves them back)
    {"id": 4, "op": "memory"}      GPU memory in use by this process
Replies carry the op's result, or {"id": n, "error": "...", "oom": true|false}. Every reply has "on_gpu".
The first line written is {"ready": true, "device": ..., ...}. Exits on EOF or after IDLE seconds idle.
"""
import json
import os
import sys
import threading
import time

IDLE = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
OUT = sys.stdout
sys.stdout = sys.stderr            # anything a library prints goes to the log, never into the protocol

CLAP_REPO = 'laion/clap-htsat-unfused'
CLAP_FILES = ['config.json', 'preprocessor_config.json', 'pytorch_model.bin', 'tokenizer.json', 'tokenizer_config.json',
              'vocab.json', 'merges.txt', 'special_tokens_map.json']

S = {'demucs': {}, 'clap': None, 'text_cache': {}, 'on_gpu': False, 'device': 'cpu'}


def send(obj):
    OUT.write(json.dumps(obj) + '\n')
    OUT.flush()


def _torch():
    import torch
    return torch


def _to(device):
    """Move every loaded model to device ('cuda' or 'cpu')."""
    torch = _torch()
    for m in S['demucs'].values():
        m.to(device)
    if S['clap'] is not None:
        S['clap'][0].to(device)
    S['text_cache'] = {k: v.to(device) for k, v in S['text_cache'].items()}
    if device == 'cpu':
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        S['on_gpu'] = False
    else:
        S['on_gpu'] = True


def _acquire():
    if S['device'] == 'cuda' and not S['on_gpu']:
        _to('cuda')


# ------------------------------------------------------------------ demucs

def _demucs(name):
    if name in S['demucs']:
        return S['demucs'][name], 0.0
    t0 = time.time()
    # The legacy repo (dl.fbaipublicfiles.com, weights in TORCH_HOME/hub/checkpoints), never the HuggingFace copy.
    from demucs.pretrained import REMOTE_ROOT, _parse_remote_files
    from demucs.repo import AnyModelRepo, BagOnlyRepo, RemoteRepo
    models = _parse_remote_files(REMOTE_ROOT / 'files.txt')
    model_repo = RemoteRepo(models)
    repo = AnyModelRepo(model_repo, BagOnlyRepo(REMOTE_ROOT, model_repo))
    model = repo.get_model(name)
    model.eval()
    model.to(S['device'])
    S['demucs'][name] = model
    return model, time.time() - t0


def op_separate(req):
    torch = _torch()
    import numpy as np
    import soundfile as sf
    from demucs.apply import apply_model
    _acquire()
    model, load_s = _demucs(req.get('model') or 'htdemucs')
    t0 = time.time()
    wav, sr = sf.read(req['wav'], dtype='float32', always_2d=True)
    if sr != model.samplerate:
        raise ValueError(f'expected {model.samplerate} Hz input, got {sr}')
    x = torch.from_numpy(np.ascontiguousarray(wav.T))            # (channels, samples)
    if x.shape[0] == 1:
        x = x.repeat(2, 1)
    x = x[:2]
    ref = x.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    if S['device'] == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        out = apply_model(model, ((x - mean) / std)[None], device=S['device'], shifts=int(req.get('shifts', 1)),
                          split=True, overlap=float(req.get('overlap', 0.25)), progress=False)[0]
    out = out * std + mean
    sources = list(model.sources)
    os.makedirs(req['out_dir'], exist_ok=True)
    files = {}

    def write(name, data):
        path = os.path.join(req['out_dir'], f'{name}.wav')
        sf.write(path, data.T.numpy(), sr, subtype='FLOAT')
        files[name] = path

    for i, name in enumerate(sources):
        write(name, out[i])
    if 'vocals' in sources:
        v = sources.index('vocals')
        write('music', out[[i for i in range(len(sources)) if i != v]].sum(0))
        write('rest', x - out[v])
    peak = torch.cuda.max_memory_allocated() / 2**20 if S['device'] == 'cuda' else 0
    if S['device'] == 'cuda':
        torch.cuda.empty_cache()
    return {'files': files, 'sources': sources, 'samplerate': sr, 'seconds': x.shape[1] / sr,
            'load_s': round(load_s, 2), 'run_s': round(time.time() - t0, 2), 'gpu_peak_mb': round(peak)}


# ------------------------------------------------------------------ clap

def _clap():
    if S['clap'] is not None:
        return S['clap'], 0.0
    t0 = time.time()
    from huggingface_hub import hf_hub_download
    from transformers import ClapFeatureExtractor, ClapModel, AutoTokenizer
    paths = []
    for f in CLAP_FILES:
        try:
            paths.append(hf_hub_download(CLAP_REPO, f, local_files_only=True))
        except Exception:  # noqa: BLE001 - first use: fetch it
            paths.append(hf_hub_download(CLAP_REPO, f))
    folder = os.path.dirname(paths[0])
    model = ClapModel.from_pretrained(folder).eval().to(S['device'])
    fe = ClapFeatureExtractor.from_pretrained(folder)
    tok = AutoTokenizer.from_pretrained(folder)
    S['clap'] = (model, fe, tok)
    return S['clap'], time.time() - t0


def op_clap(req):
    torch = _torch()
    import numpy as np
    import soundfile as sf
    _acquire()
    (model, fe, tok), load_s = _clap()
    t0 = time.time()
    audio, sr = sf.read(req['wav'], dtype='float32', always_2d=True)
    audio = audio.mean(1)
    if sr != fe.sampling_rate:
        raise ValueError(f'expected {fe.sampling_rate} Hz input, got {sr}')
    texts = list(req['texts'])
    missing = [t for t in dict.fromkeys(texts) if t not in S['text_cache']]
    with torch.no_grad():
        for k in range(0, len(missing), 64):
            batch = missing[k:k + 64]
            enc = tok(batch, padding=True, return_tensors='pt').to(S['device'])
            emb = model.get_text_features(**enc).pooler_output
            for t, e in zip(batch, emb):
                S['text_cache'][t] = e
        T = torch.stack([S['text_cache'][t] for t in texts])
        np.random.seed(0)          # the extractor crops windows over 10 s at random: same crop every run
        sims = []
        windows = req['windows']
        bs = int(req.get('batch', 16))
        for k in range(0, len(windows), bs):
            chunk = [audio[int(a * sr):max(int(a * sr) + 1, int(b * sr))] for a, b in windows[k:k + bs]]
            feats = fe(chunk, sampling_rate=sr, return_tensors='pt')
            feats = {kk: v.to(S['device']) for kk, v in feats.items()}
            emb = model.get_audio_features(**feats).pooler_output
            sims.append(emb @ T.T)
        sims = torch.cat(sims).float().cpu().numpy() if sims else np.zeros((0, len(texts)))
        scale = float(model.logit_scale_a.exp().item())
    if S['device'] == 'cuda':
        torch.cuda.empty_cache()
    return {'cosine': [[round(float(v), 5) for v in row] for row in sims], 'logit_scale': round(scale, 4),
            'sampling_rate': sr, 'padding': fe.padding, 'truncation': fe.truncation, 'max_s': fe.nb_max_samples / sr,
            'load_s': round(load_s, 2), 'run_s': round(time.time() - t0, 2)}


# ------------------------------------------------------------------ misc

def op_release(req):
    _to('cpu')
    return {'released': True}


def op_memory(req):
    torch = _torch()
    if S['device'] != 'cuda':
        return {'allocated_mb': 0, 'reserved_mb': 0}
    free, total = torch.cuda.mem_get_info()
    return {'allocated_mb': round(torch.cuda.memory_allocated() / 2**20), 'reserved_mb': round(torch.cuda.memory_reserved() / 2**20),
            'free_mb': round(free / 2**20), 'total_mb': round(total / 2**20),
            'loaded': list(S['demucs']) + (['clap'] if S['clap'] else [])}


OPS = {'separate': op_separate, 'clap': op_clap, 'release': op_release, 'memory': op_memory,
       'ping': lambda req: {'pong': True}}


def main():
    torch = _torch()
    S['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
    S['on_gpu'] = S['device'] == 'cuda'
    send({'ready': True, 'device': S['device'], 'torch': torch.__version__, 'pid': os.getpid(),
          'gpu': torch.cuda.get_device_name(0) if S['device'] == 'cuda' else None})
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
            if req.get('op') == 'quit':
                send({'id': req.get('id'), 'bye': True})
                break
            reply = OPS[req['op']](req)
            reply['id'] = req.get('id')
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            oom = 'out of memory' in str(e).lower()
            if oom:
                try:
                    torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
            reply = {'id': req.get('id'), 'error': f'{type(e).__name__}: {e}', 'oom': oom}
        reply['on_gpu'] = S['on_gpu']
        send(reply)
        last[0] = time.time()
        busy[0] = False


if __name__ == '__main__':
    main()
