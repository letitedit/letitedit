"""Vision worker for letitedit's footage log (runs in C:\\LetItEdit\\envs\\models, not the bridge's Python).

Started by model_tools.py and kept alive so the model loads once. Model: Qwen/Qwen3.5-4B (reads images), loaded with
4-bit weights (bitsandbytes nf4, fp16 compute) so it takes about half of an 8 GB GPU. Weights live under HF_HOME.

Protocol: one JSON request per stdin line, one JSON reply per stdout line, matched by "id".
    {"id": 1, "op": "describe", "items": [{"images": ["a.jpg", ...], "prompt": "..."}, ...],
     "max_new_tokens": 320, "batch": 2}
        -> {"texts": [...], "tokens_out": [...], "load_s", "run_s", "peak_mb"}
    {"id": 2, "op": "release"}     the model off the GPU and out of memory (4-bit weights can't wait in RAM)
    {"id": 3, "op": "memory"}      GPU memory in use by this process
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

REPO = os.environ.get('LETITEDIT_VISION_MODEL', 'Qwen/Qwen3.5-4B')
S = {'model': None, 'proc': None, 'on_gpu': False, 'device': 'cpu'}


def send(obj):
    OUT.write(json.dumps(obj) + '\n')
    OUT.flush()


def _torch():
    import torch
    return torch


def _load():
    if S['model'] is not None:
        return 0.0
    t0 = time.time()
    torch = _torch()
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    kw = {}
    if S['device'] == 'cuda':
        kw['quantization_config'] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True, llm_int8_skip_modules=['visual', 'lm_head'])
        kw['device_map'] = 'cuda:0'
        kw['dtype'] = torch.float16
    else:
        kw['dtype'] = torch.float32
    try:
        model = AutoModelForImageTextToText.from_pretrained(REPO, local_files_only=True, **kw)
        proc = AutoProcessor.from_pretrained(REPO, local_files_only=True)
    except OSError:                       # first use: fetch it
        model = AutoModelForImageTextToText.from_pretrained(REPO, **kw)
        proc = AutoProcessor.from_pretrained(REPO)
    proc.tokenizer.padding_side = 'left'
    S['model'], S['proc'] = model.eval(), proc
    S['on_gpu'] = S['device'] == 'cuda'
    return time.time() - t0


def op_describe(req):
    torch = _torch()
    from PIL import Image
    load_s = _load()
    model, proc = S['model'], S['proc']
    items = req['items']
    bs = max(1, int(req.get('batch', 2)))
    max_new = int(req.get('max_new_tokens', 320))
    if S['device'] == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    texts, outs = [], []
    for k in range(0, len(items), bs):
        chunk = items[k:k + bs]
        msgs = []
        for it in chunk:
            content = [{'type': 'image', 'image': Image.open(p).convert('RGB')} for p in it['images']]
            content.append({'type': 'text', 'text': it['prompt']})
            msgs.append([{'role': 'user', 'content': content}])
        inputs = proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_dict=True,
                                          return_tensors='pt', padding=True, enable_thinking=False)
        inputs = inputs.to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new, do_sample=False, repetition_penalty=1.05)
        new = out[:, inputs['input_ids'].shape[1]:]
        for row in new:
            texts.append(proc.decode(row, skip_special_tokens=True).strip())
            outs.append(int((row != proc.tokenizer.pad_token_id).sum()))
        del inputs, out, new
    peak = torch.cuda.max_memory_allocated() / 2**20 if S['device'] == 'cuda' else 0
    if S['device'] == 'cuda':
        torch.cuda.empty_cache()
    return {'texts': texts, 'tokens_out': outs, 'load_s': round(load_s, 2), 'run_s': round(time.time() - t0, 2),
            'peak_mb': round(peak), 'model': REPO}


def op_release(req):
    torch = _torch()
    S['model'] = S['proc'] = None
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    S['on_gpu'] = False
    return {'released': True}


def op_memory(req):
    torch = _torch()
    if S['device'] != 'cuda':
        return {'allocated_mb': 0, 'reserved_mb': 0}
    free, total = torch.cuda.mem_get_info()
    return {'allocated_mb': round(torch.cuda.memory_allocated() / 2**20), 'reserved_mb': round(torch.cuda.memory_reserved() / 2**20),
            'free_mb': round(free / 2**20), 'total_mb': round(total / 2**20), 'loaded': [REPO] if S['model'] else []}


OPS = {'describe': op_describe, 'release': op_release, 'memory': op_memory, 'ping': lambda req: {'pong': True}}


def tool_server_gone():
    """The tool server that started this worker has gone (Stop in the app): no one is waiting for the job in hand."""
    pid = int(os.environ.get('LETITEDIT_TOOL_SERVER_PID') or 0)
    if not pid or os.name != 'nt':
        return False
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0x102  # WAIT_TIMEOUT: still running
    finally:
        kernel.CloseHandle(handle)


def main():
    torch = _torch()
    S['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
    send({'ready': True, 'device': S['device'], 'torch': torch.__version__, 'pid': os.getpid(), 'model': REPO,
          'gpu': torch.cuda.get_device_name(0) if S['device'] == 'cuda' else None})
    last = [time.time()]
    busy = [False]

    def watchdog():
        while True:
            time.sleep(15)
            if tool_server_gone() or (not busy[0] and time.time() - last[0] > IDLE):
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
