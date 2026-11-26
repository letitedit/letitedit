"""Text embedding worker for the letitedit archive (archive.py).

Runs in C:\\LetItEdit\\envs\\models (torch + transformers), started by archive.py with -I. Model: BAAI/bge-small-en-v1.5
(MIT) from a local folder (C:\\LetItEdit\\models\\bge-small-en-v1.5, SOURCE.md there); never fetched from the internet.
Vectors: the CLS token of the last layer, L2-normalised, 384 values.

argv: model_dir device(cpu|cuda) idle_s
Protocol: one JSON request per stdin line, one JSON reply per stdout line:
    {"id": 1, "texts": [...], "prefix": "", "max_tokens": 512, "batch": 64}
        -> {"id": 1, "dim": 384, "emb": "<base64 float32, len(texts) x dim, row-major>"}
The first line written is {"ready": true, "device": ..., "model": ...}. Exits on EOF or after idle_s seconds idle.
"""
import base64
import json
import os
import sys
import threading
import time

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402

MODEL_DIR = sys.argv[1]
DEVICE = sys.argv[2] if len(sys.argv) > 2 else 'cpu'
IDLE = float(sys.argv[3]) if len(sys.argv) > 3 else 600.0
if DEVICE == 'cuda' and not torch.cuda.is_available():
    DEVICE = 'cpu'

_last = [time.time()]


def _watch():
    while True:
        time.sleep(5)
        if time.time() - _last[0] > IDLE:
            os._exit(0)


def main():
    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
    tok = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL_DIR, local_files_only=True).to(DEVICE).eval()
    print(json.dumps({'ready': True, 'device': DEVICE, 'model': os.path.basename(MODEL_DIR.rstrip('\\/')),
                      'torch': torch.__version__}), flush=True)
    threading.Thread(target=_watch, daemon=True).start()
    for line in sys.stdin:
        _last[0] = time.time()
        line = line.strip()
        if not line:
            continue
        req = {}
        try:
            req = json.loads(line)
            texts = [str(req.get('prefix', '')) + str(t) for t in req['texts']]
            bs = int(req.get('batch', 64))
            mx = int(req.get('max_tokens', 512))
            out = []
            with torch.inference_mode():
                for k in range(0, len(texts), bs):
                    enc = tok(texts[k:k + bs], padding=True, truncation=True, max_length=mx, return_tensors='pt')
                    enc = {a: b.to(DEVICE) for a, b in enc.items()}
                    h = model(**enc).last_hidden_state[:, 0]
                    h = torch.nn.functional.normalize(h, p=2, dim=1)
                    out.append(h.float().cpu().numpy())
            emb = np.concatenate(out, axis=0) if out else np.zeros((0, 384), np.float32)
            reply = {'id': req.get('id'), 'dim': int(emb.shape[1]),
                     'emb': base64.b64encode(emb.astype(np.float32).tobytes()).decode('ascii')}
        except Exception as e:  # noqa: BLE001
            reply = {'id': req.get('id'), 'error': f'{type(e).__name__}: {e}'}
        _last[0] = time.time()
        print(json.dumps(reply), flush=True)


if __name__ == '__main__':
    main()
