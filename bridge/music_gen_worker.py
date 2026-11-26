"""Music generation worker for music_gen.py (runs in C:\\LetItEdit\\envs\\music_acestep, not the bridge's Python).

ACE-Step 1.5 (ACE Studio + StepFun, MIT; code at a fixed commit in models\\ace-step-1.5-code, weights in
models\\ace-step-1.5: the 2B 'turbo' DiT, the VAE and Qwen3-Embedding-0.6B as text encoder). The 5 Hz planning LM is
not installed: text2music runs DiT-only from the caption and the metadata given (bpm, key, time signature, length).
Nothing is downloaded at run time (HF_HUB_OFFLINE=1; the LM presence check is answered locally).

Protocol: one JSON request per stdin line, one JSON reply per stdout line, matched by "id".
    {"id": 1, "op": "generate", "caption": "...", "duration": 30, "bpm": 110 | null, "key": "C major" | "",
     "time_signature": "4" | "", "seed": 7, "steps": 8, "shift": 3.0, "out": "...wav", "offload": false}
    {"id": 2, "op": "release"}   model unloaded (GPU and RAM)
    {"id": 3, "op": "memory"}
The first line written is {"ready": true, ...}. Exits on EOF or after IDLE seconds idle.
"""
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))   # install root: LETITEDIT_ROOT, else the folder above bridge
import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import time

IDLE = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
OUT = sys.stdout
sys.stdout = sys.stderr

MODELS = os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models'))
CKPT = os.environ.get('LETITEDIT_ACESTEP_DIR', os.path.join(MODELS, 'ace-step-1.5'))
CODE = os.environ.get('LETITEDIT_ACESTEP_CODE') or (
    sorted(glob.glob(os.path.join(MODELS, 'ace-step-1.5-code', 'ACE-Step-1.5-*', '')))[:1] or [''])[0]
CONFIG = 'acestep-v15-turbo'
NEEDED = ['vae', 'Qwen3-Embedding-0.6B', CONFIG]
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['ACESTEP_CHECKPOINTS_DIR'] = CKPT
S = {'h': None, 'device': 'cpu', 'offload': None}


def send(obj):
    OUT.write(json.dumps(obj) + '\n')
    OUT.flush()


def _handler(offload):
    if S['h'] is not None and S['offload'] == offload:
        return S['h'], 0.0
    t = time.time()
    if CODE not in sys.path:
        sys.path.insert(0, CODE)
    import acestep.model_downloader as md
    import acestep.core.generation.handler.init_service_downloads as isd

    def present(d=None):
        return all((md.get_checkpoints_dir() / c).exists() for c in NEEDED)
    md.check_main_model_exists = present
    isd.check_main_model_exists = present
    from acestep.handler import AceStepHandler
    S['h'] = None
    _free()
    h = AceStepHandler()
    status, ok = h.initialize_service(project_root=CODE, config_path=CONFIG, device=S['device'],
                                      offload_to_cpu=bool(offload))
    if not ok:
        raise RuntimeError(f'ACE-Step did not start: {status}')
    S['h'], S['offload'] = h, offload
    return h, time.time() - t


def _free():
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _generate(req, offload):
    import torch
    h, load_s = _handler(offload)
    from acestep.inference import GenerationParams, GenerationConfig, generate_music
    seed = int(req['seed'])
    p = GenerationParams(task_type='text2music', caption=req['caption'], lyrics='[Instrumental]', instrumental=True,
                         duration=float(req['duration']), bpm=int(round(req['bpm'])) if req.get('bpm') else None,
                         keyscale=req.get('key') or '', timesignature=str(req.get('time_signature') or ''),
                         inference_steps=int(req.get('steps', 8)), shift=float(req.get('shift', 3.0)), seed=seed,
                         thinking=False, use_cot_metas=False, use_cot_caption=False, use_cot_language=False,
                         enable_normalization=True, normalization_db=float(req.get('peak_db', -1.0)))
    c = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format='wav')
    tmp = tempfile.mkdtemp(prefix='acestep_')
    if S['device'] == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    try:
        r = generate_music(h, None, p, c, save_dir=tmp)
        if not r.success or not r.audios:
            raise RuntimeError(f'ACE-Step: {r.error or r.status_message}')
        os.makedirs(os.path.dirname(os.path.abspath(req['out'])), exist_ok=True)
        shutil.move(r.audios[0]['path'], req['out'])
        sr = int(r.audios[0]['sample_rate'])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    peak = torch.cuda.max_memory_allocated() / 2**20 if S['device'] == 'cuda' else 0
    return {'file': req['out'], 'sample_rate': sr, 'seed': seed, 'load_s': round(load_s, 2),
            'run_s': round(time.time() - t0, 2), 'gpu_peak_mb': round(peak), 'offload_to_cpu': bool(offload),
            'dtype': str(getattr(h, 'dtype', '')).replace('torch.', '')}


def op_generate(req):
    offload = bool(req.get('offload', False))
    try:
        return _generate(req, offload)
    except Exception as e:  # noqa: BLE001
        if offload or 'out of memory' not in str(e).lower():
            raise
        S['h'] = None
        _free()
        reply = _generate(req, True)          # out of GPU memory: once more with the models offloaded to RAM
        reply['note'] = 'ran out of GPU memory; repeated with offload_to_cpu'
        return reply


def op_release(req):
    S['h'] = None
    S['offload'] = None
    _free()
    return {'released': True}


def op_memory(req):
    import torch
    if S['device'] != 'cuda':
        return {'allocated_mb': 0, 'reserved_mb': 0}
    free, total = torch.cuda.mem_get_info()
    return {'allocated_mb': round(torch.cuda.memory_allocated() / 2**20),
            'reserved_mb': round(torch.cuda.memory_reserved() / 2**20), 'free_mb': round(free / 2**20),
            'total_mb': round(total / 2**20), 'loaded': ['ace-step-1.5'] if S['h'] is not None else []}


OPS = {'generate': op_generate, 'release': op_release, 'memory': op_memory, 'ping': lambda req: {'pong': True}}


def main():
    import torch
    S['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
    send({'ready': True, 'device': S['device'], 'torch': torch.__version__, 'pid': os.getpid(), 'code': CODE,
          'checkpoints': CKPT, 'gpu': torch.cuda.get_device_name(0) if S['device'] == 'cuda' else None})
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
            reply = {'id': req.get('id'), 'error': f'{type(e).__name__}: {e}', 'oom': 'out of memory' in str(e).lower()}
        reply['on_gpu'] = S['h'] is not None and S['device'] == 'cuda'
        send(reply)
        last[0] = time.time()
        busy[0] = False


if __name__ == '__main__':
    main()
