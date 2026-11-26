"""Voice worker for letitedit's voice tool (runs in C:\\LetItEdit\\envs\\voice, not the bridge's Python).

Chatterbox (Resemble AI, MIT; English model ResembleAI/chatterbox) zero-shot voice cloning, loaded once and kept
alive by model_tools.py. Weights live under HF_HOME (set by the bridge).

Protocol: one JSON request per stdin line, one JSON reply per stdout line, matched by "id".
    {"id": 1, "op": "speak", "sentences": ["...", ...], "reference": "ref.wav" | null, "out": "...wav",
     "pause_s": 0.3, "seed": 123, "settings": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8,
     "repetition_penalty": 1.2, "min_p": 0.05, "top_p": 1.0}}
    {"id": 2, "op": "release"}     model off the GPU (kept in RAM; the next job moves it back)
    {"id": 3, "op": "memory"}
Replies carry the op's result, or {"id": n, "error": "...", "oom": true|false}. Every reply has "on_gpu".
The first line written is {"ready": true, "device": ..., ...}. Exits on EOF or after IDLE seconds idle.
"""
import json
import os
import random
import sys
import threading
import time

IDLE = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
OUT = sys.stdout
sys.stdout = sys.stderr            # anything a library prints goes to the log, never into the protocol

REPO = 'ResembleAI/chatterbox'
FILES = ['ve.safetensors', 't3_cfg.safetensors', 's3gen.safetensors', 'tokenizer.json', 'conds.pt']
DEFAULTS = {'exaggeration': 0.5, 'cfg_weight': 0.5, 'temperature': 0.8, 'repetition_penalty': 1.2, 'min_p': 0.05,
            'top_p': 1.0}

S = {'tts': None, 'default_conds': None, 'ref': None, 'on_gpu': False, 'device': 'cpu'}


def send(obj):
    OUT.write(json.dumps(obj) + '\n')
    OUT.flush()


def _move(device):
    import torch
    tts = S['tts']
    if tts is not None:
        for m in (tts.t3, tts.s3gen, tts.ve):
            m.to(device)
            for sub in m.modules():           # tensors kept as plain attributes (positional tables) move too
                for k, v in list(vars(sub).items()):
                    if torch.is_tensor(v) and v.device.type != device:
                        setattr(sub, k, v.to(device))
        tts.device = device
        for conds in (tts.conds, S['default_conds'], S.get('ref_conds')):
            if conds is not None:
                conds.to(device)
    if device == 'cpu':
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        S['on_gpu'] = False
    else:
        S['on_gpu'] = True


def _tts():
    if S['tts'] is not None:
        return S['tts'], 0.0
    t0 = time.time()
    from huggingface_hub import hf_hub_download
    from chatterbox.tts import ChatterboxTTS
    path = None
    for f in FILES:
        try:
            path = hf_hub_download(REPO, f, local_files_only=True)
        except Exception:  # noqa: BLE001 - first use: fetch it
            path = hf_hub_download(REPO, f)
    tts = ChatterboxTTS.from_local(os.path.dirname(path), S['device'])
    S['tts'] = tts
    S['default_conds'] = tts.conds
    return tts, time.time() - t0


def _conditionals(tts, reference, exaggeration):
    """Point the model at the reference voice (or its built-in one); a reference is analysed once per file."""
    import copy
    if not reference:
        tts.conds = copy.copy(S['default_conds'])
        S['ref'] = None
        return
    st = os.stat(reference)
    key = (reference, st.st_size, st.st_mtime_ns)
    if S['ref'] != key:
        tts.prepare_conditionals(reference, exaggeration=exaggeration)
        S['ref'] = key
        S['ref_conds'] = tts.conds
    tts.conds = copy.copy(S['ref_conds'])


def op_speak(req):
    import numpy as np
    import soundfile as sf
    import torch
    if S['device'] == 'cuda' and not S['on_gpu']:
        _move('cuda')
    tts, load_s = _tts()
    t0 = time.time()
    settings = {**DEFAULTS, **{k: v for k, v in (req.get('settings') or {}).items() if v is not None}}
    _conditionals(tts, req.get('reference'), settings['exaggeration'])
    seed = int(req['seed'])
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats()
    sr = tts.sr
    gap = np.zeros(int(round(float(req.get('pause_s', 0.3)) * sr)), dtype=np.float32)
    pieces, spans, t = [], [], 0.0
    for k, sentence in enumerate(req['sentences']):
        wav = tts.generate(sentence, **settings).squeeze(0).cpu().numpy().astype(np.float32)
        if k:
            pieces.append(gap)
            t += len(gap) / sr
        pieces.append(wav)
        spans.append({'text': sentence, 'start': round(t, 3), 'end': round(t + len(wav) / sr, 3)})
        t += len(wav) / sr
    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
    os.makedirs(os.path.dirname(os.path.abspath(req['out'])), exist_ok=True)
    sf.write(req['out'], np.clip(audio, -1.0, 1.0), sr, subtype='PCM_16')
    peak = torch.cuda.max_memory_allocated() / 2**20 if S['device'] == 'cuda' else 0
    if S['device'] == 'cuda':
        torch.cuda.empty_cache()
    return {'file': req['out'], 'seconds': round(len(audio) / sr, 3), 'sample_rate': sr, 'sentences': spans,
            'settings': settings, 'seed': seed, 'load_s': round(load_s, 2), 'run_s': round(time.time() - t0, 2),
            'gpu_peak_mb': round(peak)}


def op_release(req):
    _move('cpu')
    return {'released': True}


def op_memory(req):
    import torch
    if S['device'] != 'cuda':
        return {'allocated_mb': 0, 'reserved_mb': 0}
    free, total = torch.cuda.mem_get_info()
    return {'allocated_mb': round(torch.cuda.memory_allocated() / 2**20), 'reserved_mb': round(torch.cuda.memory_reserved() / 2**20),
            'free_mb': round(free / 2**20), 'total_mb': round(total / 2**20), 'loaded': ['chatterbox'] if S['tts'] else []}


OPS = {'speak': op_speak, 'release': op_release, 'memory': op_memory, 'ping': lambda req: {'pong': True}}


def main():
    import torch
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
