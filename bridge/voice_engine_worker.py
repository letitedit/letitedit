"""Worker for the extra voice engines of letitedit's voice tool (model_tools.voice(engine=...)).

Runs in the engine's own Python environment (see model_tools.VOICE_ENGINES), never the bridge's Python. The engine
is named by the environment variable LETITEDIT_VOICE_ENGINE; its weights folder by LETITEDIT_VOICE_ENGINE_DIR.

    chatterbox-turbo  Resemble AI Chatterbox-Turbo (MIT)            envs\\voice         models\\chatterbox-turbo
    qwen3-tts         Qwen3-TTS-12Hz-1.7B-Base (Apache-2.0)         envs\\voice_qwen3   models\\qwen3-tts-1.7b-base
    voxcpm2           OpenBMB VoxCPM2 (Apache-2.0)                  envs\\voice_voxcpm  models\\voxcpm2
    dots-tts          dots.tts SOAR (Apache-2.0)                    envs\\voice_dots    models\\dots-tts-soar

Only dots-tts is offered (model_tools.VOICE_ENGINES): the owner dropped the other three from the voice tool and the model
manifest on 2026-10-29, so customers are never asked to download them. Their code stays here; their files stay on the
PC they were tested on.

Protocol (same as voice_worker.py): one JSON request per stdin line, one JSON reply per stdout line, matched by "id".
    {"id": 1, "op": "speak", "sentences": [...], "reference": "ref.wav" | null, "reference_text": "..." | null,
     "out": "...wav", "pause_s": 0.3, "seed": 123, "settings": {...engine settings...}}
    {"id": 2, "op": "release"}   the model is unloaded (GPU and RAM); the next speak loads it again
    {"id": 3, "op": "memory"}
The first line written is {"ready": true, "device", "engine", ...}. Exits on EOF or after IDLE seconds idle.
"""
import json
import os
import random
import sys
import threading
import time
import types

IDLE = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
OUT = sys.stdout
sys.stdout = sys.stderr            # anything a library prints goes to the log, never into the protocol

ENGINE = os.environ.get('LETITEDIT_VOICE_ENGINE', '')
DIR = os.environ.get('LETITEDIT_VOICE_ENGINE_DIR', '')
S = {'model': None, 'ref': None, 'prompt': None, 'device': 'cpu', 'dtype': None}


def send(obj):
    OUT.write(json.dumps(obj) + '\n')
    OUT.flush()


def _half():
    """float16 on GPUs without native bfloat16 (before Ampere), else bfloat16."""
    import torch
    if S['device'] != 'cuda':
        return torch.float32
    major, _ = torch.cuda.get_device_capability(0)
    return torch.bfloat16 if major >= 8 else torch.float16


def _dtype(settings):
    import torch
    name = (settings or {}).get('dtype') or 'auto'
    return {'auto': _half(), 'float16': torch.float16, 'bfloat16': torch.bfloat16,
            'float32': torch.float32}[name]


# ------------------------------------------------------------------ engines: load / prepare / say

def _load(settings):
    import torch
    dtype = _dtype(settings)
    S['dtype'] = str(dtype).replace('torch.', '')
    if ENGINE == 'chatterbox-turbo':
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        S['dtype'] = 'float32'                       # the Chatterbox loader keeps float32 weights
        return ChatterboxTurboTTS.from_local(DIR, S['device'])
    if ENGINE == 'qwen3-tts':
        from qwen_tts import Qwen3TTSModel
        return Qwen3TTSModel.from_pretrained(DIR, device_map='cuda:0' if S['device'] == 'cuda' else 'cpu',
                                             dtype=dtype, attn_implementation='sdpa')
    if ENGINE == 'voxcpm2':
        from voxcpm import VoxCPM
        import voxcpm.model.voxcpm2 as vm2
        vm2.pick_runtime_dtype = lambda device, configured: S['dtype']     # the checkpoint says bfloat16
        # built in the run dtype (the library builds float32 and converts after: 2x the RAM, over this PC's commit)
        before = torch.get_default_dtype()
        torch.set_default_dtype(dtype)
        try:
            m = VoxCPM(voxcpm_model_path=DIR, zipenhancer_model_path=None, enable_denoiser=False, optimize=False,
                       device=S['device'])
        finally:
            torch.set_default_dtype(before)
        return m
    if ENGINE == 'dots-tts':
        # dots_tts.utils.text imports WeTextProcessing (needs pynini, which does not build on Windows) for its
        # optional text normalisation; it is only used with normalize_text=True, which this worker never passes.
        for name in ('tn', 'tn.chinese', 'tn.chinese.normalizer', 'tn.english', 'tn.english.normalizer'):
            mod = sys.modules.setdefault(name, types.ModuleType(name))
            if name.endswith('normalizer'):
                class Normalizer:  # noqa: D401 - stand-in
                    def __init__(self, *a, **k):
                        raise RuntimeError('text normalisation (WeTextProcessing) is not installed')
                mod.Normalizer = Normalizer
        from dots_tts.runtime import DotsTtsRuntime
        return DotsTtsRuntime.from_pretrained(DIR, precision=S['dtype'], optimize=False)
    raise ValueError(f'unknown voice engine {ENGINE!r}')


def _sr(m):
    if ENGINE == 'chatterbox-turbo':
        return m.sr
    if ENGINE == 'voxcpm2':
        return int(m.tts_model.sample_rate)
    return None


def _prepare(m, ref, ref_text, settings):
    """Point the model at the reference voice once per (file, text, mode)."""
    key = (ref, os.stat(ref).st_mtime_ns if ref else None, ref_text, settings.get('mode'))
    if S['ref'] == key:
        return
    if ENGINE == 'chatterbox-turbo':
        m.prepare_conditionals(ref, norm_loudness=True)
    elif ENGINE == 'qwen3-tts':
        xvec = settings.get('mode') == 'xvector' or not ref_text
        S['prompt'] = m.create_voice_clone_prompt(ref_audio=ref, ref_text=None if xvec else ref_text,
                                                  x_vector_only_mode=xvec)
    S['ref'] = key


def _say(m, text, ref, ref_text, settings):
    import numpy as np
    import torch
    if ENGINE == 'chatterbox-turbo':
        kw = {k: settings[k] for k in ('temperature', 'top_p', 'top_k', 'repetition_penalty') if k in settings}
        wav = m.generate(text, **kw)
        return wav.squeeze(0).cpu().numpy().astype(np.float32), m.sr
    if ENGINE == 'qwen3-tts':
        kw = {k: settings[k] for k in ('temperature', 'top_p', 'top_k', 'repetition_penalty', 'max_new_tokens',
                                       'subtalker_temperature', 'subtalker_top_p', 'subtalker_top_k')
              if k in settings}
        wavs, sr = m.generate_voice_clone(text=text, language=settings.get('language', 'English'),
                                          voice_clone_prompt=S['prompt'], **kw)
        return np.asarray(wavs[0], dtype=np.float32), int(sr)
    if ENGINE == 'voxcpm2':
        mode = settings.get('mode', 'continuation')
        kw = dict(cfg_value=float(settings.get('cfg_value', 2.0)),
                  inference_timesteps=int(settings.get('inference_timesteps', 10)))
        if mode in ('continuation', 'continuation+reference') and ref_text:
            kw.update(prompt_wav_path=ref, prompt_text=ref_text)
        if mode in ('reference', 'continuation+reference') or not ref_text:
            kw.update(reference_wav_path=ref)
        wav = m.generate(text=text, **kw)
        return np.asarray(wav, dtype=np.float32).reshape(-1), int(m.tts_model.sample_rate)
    if ENGINE == 'dots-tts':
        kw = {k: settings[k] for k in ('num_steps', 'guidance_scale', 'speaker_scale') if k in settings}
        res = m.generate(text=text, prompt_audio_path=ref, prompt_text=ref_text if ref_text else None,
                         language=settings.get('language'), **kw)
        audio = res['audio'].float().cpu().squeeze().numpy()
        return audio.astype(np.float32).reshape(-1), int(res['sample_rate'])
    raise ValueError(ENGINE)


# ------------------------------------------------------------------ ops

def op_speak(req):
    import numpy as np
    import soundfile as sf
    import torch
    settings = dict(req.get('settings') or {})
    load_s = 0.0
    if S['model'] is None:
        t = time.time()
        S['model'] = _load(settings)
        S['ref'] = None
        load_s = time.time() - t
    m = S['model']
    ref, ref_text = req.get('reference'), req.get('reference_text')
    if not ref:
        raise ValueError(f'{ENGINE} needs a reference voice (a clip of someone speaking)')
    t0 = time.time()
    _prepare(m, ref, ref_text, settings)
    seed = int(req['seed'])
    if S['device'] == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    pieces, spans, t, sr = [], [], 0.0, None
    for k, sentence in enumerate(req['sentences']):
        random.seed(seed + k)
        np.random.seed((seed + k) % 2**32)
        torch.manual_seed(seed + k)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed + k)
        with torch.inference_mode():
            wav, sr = _say(m, sentence, ref, ref_text, settings)
        if k:
            gap = np.zeros(int(round(float(req.get('pause_s', 0.3)) * sr)), dtype=np.float32)
            pieces.append(gap)
            t += len(gap) / sr
        pieces.append(wav)
        spans.append({'text': sentence, 'start': round(t, 3), 'end': round(t + len(wav) / sr, 3)})
        t += len(wav) / sr
    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
    os.makedirs(os.path.dirname(os.path.abspath(req['out'])), exist_ok=True)
    sf.write(req['out'], np.clip(audio, -1.0, 1.0), sr, subtype='PCM_16')
    peak = torch.cuda.max_memory_allocated() / 2**20 if S['device'] == 'cuda' else 0
    return {'file': req['out'], 'seconds': round(len(audio) / sr, 3), 'sample_rate': sr, 'sentences': spans,
            'settings': settings, 'seed': seed, 'load_s': round(load_s, 2), 'run_s': round(time.time() - t0, 2),
            'gpu_peak_mb': round(peak), 'dtype': S['dtype'], 'engine': ENGINE}


def op_release(req):
    import gc
    import torch
    S['model'] = None
    S['ref'] = S['prompt'] = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return {'released': True}


def op_memory(req):
    import torch
    if S['device'] != 'cuda':
        return {'allocated_mb': 0, 'reserved_mb': 0}
    free, total = torch.cuda.mem_get_info()
    return {'allocated_mb': round(torch.cuda.memory_allocated() / 2**20),
            'reserved_mb': round(torch.cuda.memory_reserved() / 2**20), 'free_mb': round(free / 2**20),
            'total_mb': round(total / 2**20), 'loaded': [ENGINE] if S['model'] is not None else []}


OPS = {'speak': op_speak, 'release': op_release, 'memory': op_memory, 'ping': lambda req: {'pong': True}}


def main():
    import torch
    S['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
    send({'ready': True, 'device': S['device'], 'engine': ENGINE, 'torch': torch.__version__, 'pid': os.getpid(),
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
                    S['model'] = None
                    import gc
                    gc.collect()
                    torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
            reply = {'id': req.get('id'), 'error': f'{type(e).__name__}: {e}', 'oom': oom}
        reply['on_gpu'] = S['model'] is not None and S['device'] == 'cuda'
        send(reply)
        last[0] = time.time()
        busy[0] = False


if __name__ == '__main__':
    main()
