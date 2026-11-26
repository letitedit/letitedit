r"""What this PC can run locally, and which engine each letitedit feature uses.

    check(refresh=False, torch=False, ttl_s=300, gpu8_mb=None, gpu4_mb=None)
        -> {'gpu': [...], 'gpu_total_mb', 'gpu_free_mb', 'cpu_cores', 'ram_gb', 'ram_free_gb', 'disk', 'tier',
            'cutoffs', 'features': {feature: {'runs': 'local GPU' | 'local CPU' | 'llm' ..., ...}}, 'settings', ...}
    tier(gpu_total_mb, nvidia=True, gpu8_mb=7600, gpu4_mb=3800) -> 'gpu8' | 'gpu4' | 'cpu'
    settings()                  the settings file (created with the defaults on first use; never rewritten)
    footage_log_engine()        -> {'engine': 'local' | 'llm', 'model': repo or None, 'why': ...}
    vision_model()              -> the local vision model repo the footage log uses (None when the engine is 'llm')
    speech_engine()             -> 'gpu' | 'cpu'
    vision_unavailable()        -> None, or the plain fact why the local vision model is not started on this PC
                                   (no NVIDIA card of tier gpu4 or better); model_tools.describe raises
                                   LocalModelUnavailable with it, at once
    slow_here()                 -> plain lines: what this PC can't do quickly (empty with a supported card)

Settings file: C:\LetItEdit\settings.json (LETITEDIT_SETTINGS overrides). Keys and defaults in DEFAULTS; a key
missing from the file takes its default. 'auto' values are decided from the tier:
  footage_log_engine 'auto': gpu8 -> 'local' with vision_models['gpu8'] (Qwen/Qwen3.5-4B); gpu4 -> 'local' with
    vision_models['gpu4'] (Qwen/Qwen3.5-2B) when its weights are on this PC, else 'llm'; cpu -> 'llm'. A local model
    whose weights are not on this PC means 'llm' (nothing is downloaded).
  speech_engine 'auto': 'gpu' when an NVIDIA GPU has at least whisper_gpu_mb MB in total (default 6000) and the
    GPU whisper environment exists, else 'cpu'.
  disk_keep_free_gb (default 5, not in DEFAULTS): the disk room letitedit leaves free on a drive it writes to
    (exports, work folders, playback caches); short of it a job says how much to free. Read by
    cache_budget.reserve_bytes, also from settings.local.json beside this file; LETITEDIT_DISK_KEEP_FREE_GB overrides.
  emotion_graph (default false): when true the index job (first import) also builds each video's emotion graph
    with the connected AI's fast model (emotion_engine / emotion_model / emotion_effort; emotion_graph.py);
    emotion_extra_moods {name: what it means} adds your own moods to every graph built.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import ctypes
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SETTINGS = Path(os.environ.get('LETITEDIT_SETTINGS', (_SAI_ROOT + '\\settings.json')))
MODELS_HOME = Path(os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models')))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

DEFAULTS = {
    'footage_log_engine': 'auto',            # 'auto' | 'local' | 'llm'
    'vision_model': 'auto',                  # 'auto' (by tier) or a Hugging Face repo id
    'vision_models': {'gpu8': 'Qwen/Qwen3.5-4B', 'gpu4': 'Qwen/Qwen3.5-2B'},
    'speech_engine': 'auto',                 # 'auto' | 'gpu' | 'cpu'
    'whisper_gpu_mb': 6000,                  # GPU total MB for speech_engine 'auto' to pick the GPU
    'tier_gpu8_mb': 7600,                    # GPU total MB from which the tier is 'gpu8' (an 8 GB card reports ~8192)
    'tier_gpu4_mb': 3800,                    # ... 'gpu4'
    'hardware_ttl_s': 300,                   # how long a hardware reading is reused
    'emotion_graph': False,                  # emotion graph (emotion_graph.py) built on first import; uses AI usage
    'emotion_engine': 'auto',                # 'auto' | 'claude' | 'codex' (auto: the AI this server was started by)
    'emotion_model': 'auto',                 # 'auto' (sonnet / gpt-6.1-terra) or a model name
    'emotion_effort': 'low',                 # Codex reasoning effort for the emotion graph
    'emotion_extra_moods': {},               # {name: what it means}: your own moods, scored on top of the built-in ones
    'new_video_stage_sessions': True,        # New video's fresh review conversation and slimmer replies (new_video_stages.py)
}

_cache = {'at': 0.0, 'data': None, 'key': None}


# ------------------------------------------------------------------ settings

def settings(path=None):
    """The settings: the file's values over DEFAULTS. The file is written with the defaults when it does not exist;
    an existing file is never rewritten. A file that is not valid JSON counts as empty (the reply says so)."""
    p = Path(path or SETTINGS)
    out = json.loads(json.dumps(DEFAULTS))
    note = None
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(DEFAULTS, indent=2) + '\n', encoding='utf-8')
            note = 'created with the defaults'
        except OSError as e:
            note = f'could not be created: {e}'
    else:
        try:
            user = json.loads(p.read_text(encoding='utf-8-sig') or '{}')
            if isinstance(user, dict):
                for k, v in user.items():
                    if isinstance(v, dict) and isinstance(out.get(k), dict):
                        out[k].update(v)
                    else:
                        out[k] = v
            else:
                note = 'not a JSON object; defaults used'
        except (OSError, ValueError) as e:
            note = f'not readable ({type(e).__name__}); defaults used'
    # settings.local.json beside it (git-ignored, never shipped): this PC's own folders, read over the file
    local = p.with_name(p.stem + '.local' + p.suffix)
    if local.is_file():
        try:
            mine = json.loads(local.read_text(encoding='utf-8-sig') or '{}')
            if isinstance(mine, dict):
                for k, v in mine.items():
                    if isinstance(v, dict) and isinstance(out.get(k), dict):
                        out[k].update(v)
                    else:
                        out[k] = v
                out['_local'] = str(local)
        except (OSError, ValueError) as e:
            note = (note + '; ' if note else '') + f'{local.name} not readable ({type(e).__name__})'
    out['_file'] = str(p)
    if note:
        out['_note'] = note
    return out


# ------------------------------------------------------------------ readings

def _nvidia_smi():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free,driver_version',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=15,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(',')]
        if len(p) >= 3:
            try:
                out.append({'name': p[0], 'total_mb': int(float(p[1])), 'free_mb': int(float(p[2])),
                            'driver': p[3] if len(p) > 3 else None, 'vendor': 'nvidia', 'source': 'nvidia-smi'})
            except ValueError:
                pass
    return out


def _torch_cuda():
    """CUDA as torch in the models environment sees it (a few seconds: starts that Python)."""
    import letitedit.sound.model_tools as model_tools
    py = model_tools.MODELS_PYTHON
    if not Path(py).exists():
        return {'available': False, 'error': f'models environment missing: {py}'}
    code = ('import json,torch;ok=torch.cuda.is_available();'
            'print(json.dumps({"available":ok,"torch":torch.__version__,"cuda":torch.version.cuda,'
            '"name":torch.cuda.get_device_name(0) if ok else None,'
            '"total_mb":round(torch.cuda.get_device_properties(0).total_memory/2**20) if ok else None}))')
    try:
        r = subprocess.run([str(py), '-I', '-c', code], capture_output=True, text=True, timeout=120,
                           creationflags=NO_WINDOW)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        return {'available': False, 'error': f'{type(e).__name__}: {e}'[:200]}


def _ram():
    class MS(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    try:
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 1024 ** 3, 1), round(m.ullAvailPhys / 1024 ** 3, 1)
    except Exception:  # noqa: BLE001 - not Windows
        return None, None


def _disks(paths):
    out = []
    seen = set()
    for p in paths:
        drive = os.path.splitdrive(str(p))[0] + '\\' if os.path.splitdrive(str(p))[0] else str(p)
        if drive in seen:
            continue
        seen.add(drive)
        try:
            u = shutil.disk_usage(drive)
            out.append({'drive': drive, 'free_gb': round(u.free / 1024 ** 3, 1), 'total_gb': round(u.total / 1024 ** 3, 1)})
        except OSError as e:
            out.append({'drive': drive, 'error': str(e)})
    return out


def model_present(repo):
    """True when a Hugging Face repo's weights are under MODELS_HOME\\hf\\hub (or MODELS_HOME\\hf)."""
    if not repo:
        return False
    name = 'models--' + str(repo).replace('/', '--')
    for hub in (MODELS_HOME / 'hf' / 'hub', MODELS_HOME / 'hf'):
        d = hub / name / 'snapshots'
        if d.is_dir() and any(d.iterdir()):
            return True
    return False


def tier(gpu_total_mb, nvidia=True, gpu8_mb=7600, gpu4_mb=3800):
    """'gpu8' for an NVIDIA GPU with at least gpu8_mb MB, 'gpu4' for at least gpu4_mb MB, else 'cpu'."""
    if not nvidia or not gpu_total_mb:
        return 'cpu'
    if gpu_total_mb >= gpu8_mb:
        return 'gpu8'
    if gpu_total_mb >= gpu4_mb:
        return 'gpu4'
    return 'cpu'


# ------------------------------------------------------------------ decisions

def _decide(reading, s):
    """footage log engine + model and speech engine for a reading (dict with tier, gpu_total_mb) and settings s."""
    t = reading['tier']
    eng = str(s.get('footage_log_engine', 'auto')).lower()
    vm = s.get('vision_model', 'auto')
    models = s.get('vision_models') or {}
    present = reading.get('_present', model_present)
    if eng == 'llm':
        log = {'engine': 'llm', 'model': None, 'why': "settings footage_log_engine = 'llm'"}
    else:
        repo = vm if vm and vm != 'auto' else models.get(t)
        if eng == 'local':
            if repo is None:
                repo = models.get('gpu8')
            log = {'engine': 'local', 'model': repo, 'why': "settings footage_log_engine = 'local'"}
            if not present(repo):
                log['note'] = f'{repo} is not on this PC (the worker would download it on first use)'
        elif repo is None:
            log = {'engine': 'llm', 'model': None, 'why': f"tier {t}: no local vision model for this tier"}
        elif not present(repo):
            log = {'engine': 'llm', 'model': None, 'why': f'tier {t}: {repo} is not on this PC'}
        else:
            log = {'engine': 'local', 'model': repo, 'why': f'tier {t}: {repo} is on this PC'}
    sp = str(s.get('speech_engine', 'auto')).lower()
    if sp in ('gpu', 'cpu'):
        speech = {'engine': sp, 'why': f"settings speech_engine = '{sp}'"}
    else:
        need = float(s.get('whisper_gpu_mb', 6000))
        tot = reading.get('gpu_total_mb') or 0
        env = reading.get('_whisper_env')
        if env is None:
            import letitedit.footage.speech as _sp
            env = os.path.exists(_sp.GPU_PYTHON)
        if reading.get('nvidia') and tot >= need and env:
            speech = {'engine': 'gpu', 'why': f'GPU {tot} MB >= whisper_gpu_mb {need:g} and the GPU whisper environment exists'}
        else:
            speech = {'engine': 'cpu', 'why': ('no GPU whisper environment' if not env else
                                               f'GPU {tot} MB < whisper_gpu_mb {need:g}')}
    return log, speech


def _features(reading, log, speech):
    t = reading['tier']
    gpu = t != 'cpu'
    vram = reading.get('gpu_total_mb') or 0
    import letitedit.sound.model_tools as mt
    f = {
        'footage log (shot_log)': {'runs': 'local GPU' if log['engine'] == 'local' else 'llm',
                                   'model': log['model'] or 'the agent (letitedit_log_frames / letitedit_log_write)',
                                   'why': log['why']},
        'speech to text (speech)': {'runs': 'local GPU' if speech['engine'] == 'gpu' else 'local CPU',
                                    'model': 'whisper large-v3-turbo' if speech['engine'] == 'gpu'
                                    else 'faster-whisper medium.en int8', 'why': speech['why']},
    }
    for name, (worker, op), model in (('stems (separate)', ('models', 'separate'), 'htdemucs'),
                                      ('sound labels (hear)', ('models', 'clap'), 'CLAP'),
                                      ('voice (voice)', ('voice', 'speak'), 'Chatterbox')):
        need = mt.NEED_MB.get((worker, op), 1500)
        on_gpu = gpu and vram >= need
        f[name] = {'runs': 'local GPU' if on_gpu else 'local CPU (slower)', 'model': model,
                   'gpu_need_mb': need}
    return f


def check(refresh=False, torch=False, ttl_s=None, gpu8_mb=None, gpu4_mb=None, _reading=None):
    """The hardware reading, tier and per-feature engines (see the module doc). Reused for ttl_s seconds (default
    settings hardware_ttl_s, 300) unless refresh. torch=True also asks torch in the models environment (a few s).
    gpu8_mb / gpu4_mb override the settings' tier cutoffs (defaults 7600 / 3800)."""
    s = settings()
    ttl = float(ttl_s if ttl_s is not None else s.get('hardware_ttl_s', 300))
    g8 = float(gpu8_mb if gpu8_mb is not None else s.get('tier_gpu8_mb', 7600))
    g4 = float(gpu4_mb if gpu4_mb is not None else s.get('tier_gpu4_mb', 3800))
    key = (bool(torch), g8, g4, json.dumps({k: v for k, v in s.items() if not k.startswith('_')}, sort_keys=True))
    if (_reading is None and not refresh and _cache['data'] is not None and _cache['key'] == key
            and time.time() - _cache['at'] < ttl):
        return _cache['data']
    if _reading is not None:
        r = dict(_reading)
    else:
        gpus = _nvidia_smi()
        ram, ram_free = _ram()
        r = {'gpu': gpus, 'nvidia': bool(gpus), 'cpu_cores': os.cpu_count(), 'ram_gb': ram, 'ram_free_gb': ram_free,
             'disk': _disks([MODELS_HOME, os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))])}
        best = max(gpus, key=lambda g: g['total_mb']) if gpus else None
        r['gpu_total_mb'] = best['total_mb'] if best else None
        r['gpu_free_mb'] = best['free_mb'] if best else None
        if torch:
            r['torch'] = _torch_cuda()
            if not gpus and r['torch'].get('available'):
                r.update(nvidia=True, gpu_total_mb=r['torch'].get('total_mb'))
    r['tier'] = tier(r.get('gpu_total_mb'), r.get('nvidia'), g8, g4)
    r['cutoffs'] = {'gpu8_mb': g8, 'gpu4_mb': g4}
    log, speech = _decide(r, s)
    r['footage_log'] = log
    r['speech'] = speech
    r['features'] = _features(r, log, speech)
    r['settings'] = s
    r['ttl_s'] = ttl
    r['read_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    for k in [k for k in r if k.startswith('_')]:
        r.pop(k)
    if _reading is None:
        _cache.update(at=time.time(), data=r, key=key)
    return r


def footage_log_engine():
    return check()['footage_log']


def vision_model():
    """The local vision model for the footage log (None when the engine is 'llm')."""
    return footage_log_engine().get('model')


class LocalModelUnavailable(RuntimeError):
    """A local model this PC can't run in a sane time or memory, so it was not started. str(e) and e.fact are the
    plain fact (what is missing and what can be used instead); e.feature names the model ('vision')."""

    def __init__(self, fact, feature='vision'):
        super().__init__(fact)
        self.fact, self.feature = fact, feature


VISION_ON_CPU_ENV = 'LETITEDIT_VISION_ON_CPU'    # '1': the vision model may start without a graphics card (measuring)
VISION_INSTEAD = ('the frames themselves come from letitedit_check_frames, letitedit_stills or letitedit_footage '
                  '(times / every_s / frames), as pictures')


def vision_unavailable(reading=None):
    """None when this PC can run the local vision model on its graphics card (tier gpu8 or gpu4); else the plain
    fact why it is not started, with what gives the frames instead. Without a usable NVIDIA card the model would run
    on the processor in full precision: over an hour for a few answers and about 12-16 GB of memory on a 4-core,
    16 GB PC (tests/t355/REPORT.md). When nvidia-smi finds no card, torch in the models environment is asked too
    before the answer is no. LETITEDIT_VISION_ON_CPU=1 lets it start anyway."""
    if os.environ.get(VISION_ON_CPU_ENV) == '1':
        return None
    r = reading or check()
    if r.get('tier') != 'cpu':
        return None
    if reading is None and not r.get('nvidia'):
        try:
            r = check(torch=True)            # a card nvidia-smi missed counts if torch sees it
        except Exception:  # noqa: BLE001 - no second reading: the first stands
            pass
        if r.get('tier') != 'cpu':
            return None
    total = r.get('gpu_total_mb')
    need = (r.get('cutoffs') or {}).get('gpu4_mb', 3800)
    if r.get('nvidia') and total:
        why = (f"this PC's graphics card has {int(total)} MB of its own memory and the local picture model needs "
               f"at least {int(need)} MB")
    else:
        why = 'the local picture model needs an NVIDIA graphics card and this PC has none'
    return (f'{why}. On the processor it would take an hour or more and fill the memory, so it was not started. '
            f'{VISION_INSTEAD[0].upper()}{VISION_INSTEAD[1:]}.')


def slow_here(reading=None):
    """What this PC can't do quickly, as plain lines (empty on a PC whose graphics card runs the local models)."""
    r = reading or check()
    if vision_unavailable(r) is None:
        return []
    out = ["The picture model (questions about what is in a frame, and the shot-by-shot log of what each clip "
           "shows) needs an NVIDIA graphics card with about 4 GB of its own memory. This PC has none, so letitedit "
           "doesn't run it, and the AI looks at the frames itself instead."]
    if (r.get('speech') or {}).get('engine') == 'cpu':
        out.append('Turning speech into words runs on the processor: English only, and slower.')
    out.append('Separating voices from music, naming sounds and making spoken voices run on the processor: slower.')
    return out


def better_speech_fits(reading=None):
    """This PC can run the better speech model: an NVIDIA card with whisper_gpu_mb MB, whether or not its environment is built yet (T76)."""
    r = reading or check()
    s = settings()
    if str(s.get('speech_engine', 'auto')).lower() == 'cpu':
        return False
    return bool(r.get('nvidia')) and float(r.get('gpu_total_mb') or 0) >= float(s.get('whisper_gpu_mb', 6000))


def speech_engine():
    return check()['speech']['engine']


def text(r):
    """The reading as text lines."""
    out = []
    if r.get('gpu'):
        for g in r['gpu']:
            out.append(f"GPU: {g['name']}, {g['total_mb']} MB total, {g['free_mb']} MB free (driver {g.get('driver')})")
    else:
        out.append('GPU: no NVIDIA GPU found (nvidia-smi)')
    if r.get('torch'):
        out.append(f"torch (models env): {r['torch']}")
    out.append(f"CPU: {r.get('cpu_cores')} logical cores; RAM: {r.get('ram_gb')} GB ({r.get('ram_free_gb')} GB free)")
    for d in r.get('disk') or []:
        out.append(f"Disk {d['drive']}: " + (f"{d['free_gb']} GB free of {d['total_gb']} GB" if 'free_gb' in d else d.get('error', '')))
    c = r['cutoffs']
    out.append(f"Tier: {r['tier']} (gpu8 >= {c['gpu8_mb']:g} MB, gpu4 >= {c['gpu4_mb']:g} MB NVIDIA GPU memory, else cpu)")
    out.append('Features:')
    for name, f in r['features'].items():
        extra = f" ({f['why']})" if f.get('why') else (f" (needs ~{f['gpu_need_mb']} MB GPU)" if f.get('gpu_need_mb') else '')
        out.append(f"  {name}: {f['runs']}, {f['model']}{extra}")
    slow = slow_here(r)
    if slow:
        out.append("What this PC can't do quickly:")
        out.extend('  ' + line for line in slow)
    s = r['settings']
    out.append(f"Settings file: {s.get('_file')}" + (f" ({s['_note']})" if s.get('_note') else ''))
    out.append('  ' + json.dumps({k: v for k, v in s.items() if not k.startswith('_')}))
    out.append(f"Read at {r['read_at']}; reused for {r['ttl_s']:g} s")
    return out


if __name__ == '__main__':
    import sys
    print('\n'.join(text(check(refresh=True, torch='--torch' in sys.argv))))
