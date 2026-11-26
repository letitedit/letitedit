"""Emotion graph of footage: mood and energy per sentence (or per shot where nobody talks), as numbers and a
picture, with its turning points. The timing view 'emotion' (letitedit_timing(source, view='emotion')).

    graph(source, build=None, refresh=False, settings=None, progress=None) -> the file's emotion graph (cached)
    build(files, progress=None, check=None)  -> graphs for many files (the index job's 'emotion' step)
    labeller(settings=None)                  -> {'engine': 'claude'|'codex'|None, 'model', 'cli', 'why'}
    units(words, duration_s)                 -> the stretches that get one score each
    turning_points(units, source)            -> where the mood changes (crossovers, rises, drops, peaks)
    add_moods(source, {name: meaning})       -> the graph with more moods scored (kept with it)

The moods are chosen for editing decisions, 14 of them (MOODS): tension, relief, surprise, excitement, joy, humor,
warmth, sincerity, awkwardness, frustration, sadness, awe, peaceful, satisfaction, plus a 'neutral' baseline for
explaining or routine stretches (version p1 had curiosity and calm instead: on a 9-min repair vlog they led 87% of
the stretches and made most of its turning points, i.e. they worked as 'nothing much is felt'). More moods: the
setting emotion_extra_moods ({name: what it means}, scored on every graph built) or add_moods / the view's
options.moods (scored on the existing graphs, about the cost of one build). Each stretch may also carry up to two
'other' moods in the AI's own words (outside the list, felt at 2 or more); the view counts them so the editing model
can add one as a mood and get its whole curve. Faces: where the faces are small in the frame, each row of the
contact sheet gets a close-up crop of them (OpenCV YuNet) so the AI can read expressions.

Who scores the mood: the AI the user connected (Claude Code or Codex), on its fast model, run headless by this module
(`claude -p --model sonnet` / `codex exec -m gpt-6.1-terra` at low effort), a batch of stretches per call: the
stretch's frames as one contact sheet plus what is said in it. Measured on 91 stretches of the test footage
(loops/rounds/20261028-emotion-test, 28 Oct 2026): the main mood GPT-6.1-Terra picked matched full Codex 93% and
full Claude 78% of the time, Sonnet 78% / 64% (full Codex and full Claude agree 81%). Free local models (SigLIP 2,
CLAP) were at chance (14-29%), so none is used. Mood scores are an AI's judgement, not measurements: every result
says so. Measured per stretch (facts): loudness (dB), picture motion (mean frame difference) and speech rate.
The 4 s ups and downs between neighbours are not reliable even between full models (49% agreement), so the graph
works per sentence, and each turning point names the exact words around it plus the call that shows it frame by
frame (view 'slow'), for the editing model to pick the frame.

Settings (C:\\LetItEdit\\settings.json, hardware.py): emotion_graph (false: the index job leaves it out and the view
only shows graphs already built; options.build = true builds one anyway), emotion_engine ('auto' | 'claude' |
'codex'; auto = the AI this server was started by, else whichever CLI is installed), emotion_model ('auto' = sonnet
for Claude, gpt-6.1-terra for Codex; or a model name), emotion_effort (Codex reasoning effort, 'low'),
emotion_extra_moods ({name: what it means} scored on top of MOODS on every graph built; default none).
The environment variable LETITEDIT_VIEWS_OFF=emotion turns the view off (the without side of an A/B test).
Cache: cache\\emotion\\<file key>-<engine>-<model>-v<VERSION>.json, contact sheets in cache\\emotion\\sheets.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

VERSION = 1
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'emotion'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf'}

MOODS = ['tension', 'relief', 'surprise', 'excitement', 'joy', 'humor', 'warmth', 'sincerity', 'awkwardness',
         'frustration', 'sadness', 'awe', 'peaceful', 'satisfaction']
MOOD_TEXT = {
    'tension': 'tension / suspense: will it work, risk, something could go wrong',
    'relief': 'relief: a worry or an effort let go (often right after a payoff)',
    'surprise': 'surprise: something unexpected, a reveal, a reaction to one',
    'excitement': 'excitement / hype: eager, energetic, enthusiastic',
    'joy': 'joy / delight: happy, laughing with pleasure',
    'humor': 'humor / playfulness: funny, teasing, a joke or a gag',
    'warmth': 'warmth / affection: closeness between people (or with a pet), tenderness',
    'sincerity': 'sincerity / vulnerability: heartfelt, honest, personal, speaking from the heart',
    'awkwardness': 'awkwardness: uncomfortable, fumbling, cringe, a moment that falls flat',
    'frustration': 'frustration / setback: annoyed, stuck, something went wrong',
    'sadness': 'sadness / disappointment: loss, regret, melancholy',
    'awe': 'awe / wonder: beauty, scale, a striking sight',
    'peaceful': 'peaceful / serene: quiet, relaxed, restful',
    'satisfaction': 'satisfaction / pride: accomplished, it works, a job well done'}
NEUTRAL_TEXT = 'explaining, routine or matter-of-fact: no particular feeling'
MAX_EXTRA_MOODS = 8
DEFAULT_MODELS = {'claude': 'sonnet', 'codex': 'gpt-6.1-terra'}

DEFAULTS = {
    'max_unit_s': 8.0,        # a sentence longer than this is split
    'min_unit_s': 1.5,        # a sentence end closes a stretch only once it is this long
    'pause_s': 0.6,           # a silence this long between words closes a stretch
    'picture_unit_s': 5.0,    # stretches without talking are cut into pieces of about this length
    'units_per_call': 10,     # stretches per AI call (one contact sheet)
    'calls_parallel': 3,      # AI calls at once
    'frames_per_unit': 3,
    'tile_px': 220,
    'call_timeout_s': 600,
    'turn_delta': 1.5,        # a mood that moves this much (0-3 scale) between neighbours is a turning point
    'energy_delta': 2.0,      # ... energy (1-5)
    'positivity_delta': 1.5,  # ... positivity (-2..+2)
    'curve_step_s': 0.5,      # measured curves: one value per this many seconds
    'face_tiles': True,       # a close-up crop of small faces at the end of each contact-sheet row
    'face_min_px': 70,        # ... when the largest face would be shorter than this in a normal tile
}
PROMPT_VERSION = 'p3'


# ------------------------------------------------------------------ settings and the labeller

def _settings(given=None):
    st = dict(DEFAULTS)
    try:
        import letitedit.core.hardware as hardware
        hs = hardware.settings()
        hs = hs.get('settings', hs) if isinstance(hs, dict) else {}
    except Exception:  # noqa: BLE001
        hs = {}
    for k in ('emotion_graph', 'emotion_engine', 'emotion_model', 'emotion_effort', 'emotion_extra_moods'):
        if k in hs:
            st[k] = hs[k]
    st.setdefault('emotion_graph', False)
    st.setdefault('emotion_engine', 'auto')
    st.setdefault('emotion_model', 'auto')
    st.setdefault('emotion_effort', 'low')
    st.setdefault('emotion_extra_moods', {})
    st.update(given or {})
    return st


def norm_moods(moods):
    """{name: what it means} from a dict, a list of names or 'a=meaning; b' text; names lower case, at most
    MAX_EXTRA_MOODS, the core MOODS and 'neutral' left out."""
    if isinstance(moods, str):
        moods = dict((s.split('=', 1) + [''])[:2] for s in re.split(r'[;\n]', moods) if s.strip())
    elif isinstance(moods, (list, tuple)):
        moods = {m: '' for m in moods}
    out = {}
    for k, v in (moods or {}).items():
        name = re.sub(r'[^a-z0-9 _-]', '', str(k).lower()).strip()[:30]
        if name and name not in MOODS and name != 'neutral' and len(out) < MAX_EXTRA_MOODS:
            out[name] = str(v or name).strip()[:160]
    return out


def enabled(settings=None):
    import letitedit.app.ai_clis as ai_clis
    return bool(_settings(settings).get('emotion_graph')) and ai_clis.background_allowed()


def _claude_cli():
    import letitedit.app.ai_clis as ai_clis
    return ai_clis.find('claude')


def _codex_cli():
    import letitedit.app.ai_clis as ai_clis
    return ai_clis.find('codex')


def _process_chain():
    """Names of this process's ancestors, nearest first (Windows: one process snapshot; else /proc)."""
    names = []
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes

            class PE(ctypes.Structure):
                _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                            ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                            ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                            ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                            ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_char * 260)]
            k32 = ctypes.windll.kernel32
            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            snap = k32.CreateToolhelp32Snapshot(2, 0)
            table = {}
            e = PE()
            e.dwSize = ctypes.sizeof(PE)
            ok = k32.Process32First(snap, ctypes.byref(e))
            while ok:
                table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.decode('utf-8', 'replace').lower())
                ok = k32.Process32Next(snap, ctypes.byref(e))
            k32.CloseHandle(snap)
            pid, seen = os.getpid(), set()
            while pid in table and pid not in seen and len(names) < 12:
                seen.add(pid)
                pid = table[pid][0]
                if pid in table:
                    names.append(table[pid][1])
        else:
            pid = os.getppid()
            while pid > 1 and len(names) < 12:
                names.append(Path(f'/proc/{pid}/comm').read_text().strip().lower())
                pid = int(Path(f'/proc/{pid}/stat').read_text().split(')')[1].split()[1])
    except Exception:  # noqa: BLE001
        pass
    return names


def labeller(settings=None):
    """Which AI scores the mood, on which model, and why."""
    st = _settings(settings)
    import letitedit.app.ai_clis as ai_clis
    if not ai_clis.background_allowed():
        return {'engine': None, 'model': None, 'cli': None, 'why': 'background runs of your AI are off (Connect Your AI)',
                'effort': st.get('emotion_effort') or 'low'}
    eng, why = str(st.get('emotion_engine') or 'auto').lower(), 'settings emotion_engine'
    if eng not in ('claude', 'codex'):
        chain = _process_chain()
        env = os.environ
        if any(n.startswith('codex') for n in chain) or any(k.startswith('CODEX_') for k in env):
            eng, why = 'codex', 'this server was started by Codex'
        elif any(n.startswith('claude') for n in chain) or env.get('CLAUDECODE'):
            eng, why = 'claude', 'this server was started by Claude Code'
        elif _codex_cli():
            eng, why = 'codex', 'Codex CLI found (no AI found above this server)'
        elif _claude_cli():
            eng, why = 'claude', 'Claude Code CLI found (no AI found above this server)'
        else:
            eng, why = None, 'neither the Claude Code nor the Codex CLI was found'
    cli = _claude_cli() if eng == 'claude' else _codex_cli() if eng == 'codex' else None
    if eng and not cli:
        why += f'; but the {eng} CLI was not found'
    model = st.get('emotion_model') or 'auto'
    if model == 'auto':
        model = DEFAULT_MODELS.get(eng)
    return {'engine': eng if cli else None, 'model': model, 'cli': cli, 'why': why,
            'effort': st.get('emotion_effort') or 'low'}


# ------------------------------------------------------------------ media helpers

def _tools():
    import letitedit.review.checks as checks
    return str(checks.FFMPEG), str(checks.FFPROBE)


def duration_s(path):
    ff, fp = _tools()
    r = subprocess.run([fp, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def file_key(path):
    import letitedit.footage.footage_notes as footage_notes
    return footage_notes.key(path)


def _words(path):
    """[{w, t0, t1}] of the file (cached transcript; transcribed when the voice detector hears talking)."""
    try:
        import letitedit.timing.prosody as prosody
        ws, how, warns = prosody.words_for(str(path), 'video', transcribe=True)
        return [w for w in ws if w.get('w')], how, list(warns or [])
    except Exception as e:  # noqa: BLE001
        return [], f'no words ({type(e).__name__}: {e})', [f'no transcript: {e}']


def measured_curves(path, dur, step=0.5):
    """Loudness (dB, RMS of the mono mix) and picture motion (mean absolute difference of 64x36 grey frames at 4 fps,
    0-255) every `step` seconds."""
    ff, _ = _tools()
    n = max(1, int(np.ceil(dur / step)))
    loud = np.full(n, np.nan)
    motion = np.full(n, np.nan)
    try:
        r = subprocess.run([ff, '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
                           capture_output=True, creationflags=NO_WINDOW, timeout=600)
        x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        hop = int(16000 * step)
        for i in range(min(n, int(np.ceil(len(x) / hop)))):
            seg = x[i * hop:(i + 1) * hop]
            if seg.size:
                loud[i] = 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)
    except Exception:  # noqa: BLE001
        pass
    try:
        w, h, fps = 64, 36, 4
        r = subprocess.run([ff, '-v', 'error', '-i', str(path), '-an', '-vf', f'fps={fps},scale={w}:{h},format=gray',
                            '-f', 'rawvideo', '-'], capture_output=True, creationflags=NO_WINDOW, timeout=900)
        fr = np.frombuffer(r.stdout, dtype=np.uint8)
        fr = fr[:len(fr) // (w * h) * (w * h)].reshape(-1, h, w).astype(np.float32)
        if len(fr) > 1:
            d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
            t = (np.arange(len(d)) + 1) / fps
            for i in range(n):
                m = (t >= i * step) & (t < (i + 1) * step)
                if m.any():
                    motion[i] = float(d[m].mean())
    except Exception:  # noqa: BLE001
        pass
    return {'step_s': step, 'loudness_db': [None if np.isnan(v) else round(float(v), 1) for v in loud],
            'motion': [None if np.isnan(v) else round(float(v), 2) for v in motion]}


# ------------------------------------------------------------------ stretches

def units(words, dur, settings=None):
    """Stretches that get one score each: sentences of talk (closed by a pause >= pause_s, a sentence end once
    min_unit_s long, or max_unit_s), and the time without talk cut into ~picture_unit_s pieces."""
    st = _settings(settings)
    out, cur = [], []

    def close():
        if cur:
            out.append({'t0': float(cur[0]['t0']), 't1': float(cur[-1]['t1']), 'kind': 'speech',
                        'said': ' '.join(w['w'].strip() for w in cur)})
            cur.clear()

    for w in sorted(words, key=lambda w: float(w['t0'])):
        if cur:
            gap = float(w['t0']) - float(cur[-1]['t1'])
            length = float(cur[-1]['t1']) - float(cur[0]['t0'])
            ends = re.search(r'[.!?]["\')\]]*$', cur[-1]['w'].strip()) is not None
            if gap >= st['pause_s'] or (ends and length >= st['min_unit_s']) or \
                    float(w['t1']) - float(cur[0]['t0']) > st['max_unit_s']:
                close()
        cur.append(w)
    close()
    # time without talk -> picture stretches; talk stretches grow to meet the next one when the gap is short
    full, t = [], 0.0
    for u in out + [{'t0': dur, 't1': dur, 'kind': 'end'}]:
        gap = u['t0'] - t
        if gap >= 1.0:
            k = max(1, int(round(gap / st['picture_unit_s'])))
            for j in range(k):
                full.append({'t0': t + gap * j / k, 't1': t + gap * (j + 1) / k, 'kind': 'picture', 'said': ''})
        elif full and gap > 0:
            full[-1]['t1'] = u['t0']
        elif gap > 0 and u['kind'] != 'end':
            u['t0'] = t
        if u['kind'] != 'end':
            full.append(u)
        t = max(t, u['t1'])
    for i, u in enumerate(full):
        u['i'] = i + 1
        u['t0'], u['t1'] = round(u['t0'], 3), round(min(u['t1'], dur), 3)
    return [u for u in full if u['t1'] - u['t0'] > 0.05]


# ------------------------------------------------------------------ the AI's scores

def _frames(path, u, n, px, out_dir):
    ff, _ = _tools()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for j in range(n):
        t = u['t0'] + (u['t1'] - u['t0']) * (j + 0.5) / n
        p = out_dir / f"u{u['i']:04d}-{j}.jpg"
        if not p.exists():
            subprocess.run([ff, '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(path), '-frames:v', '1',
                            '-vf', f'scale={px}:{px}:force_original_aspect_ratio=decrease', '-q:v', '4', str(p)],
                           capture_output=True, creationflags=NO_WINDOW)
        if p.exists():
            paths.append(p)
    return paths


def _clock(s):
    return f'{int(s // 60)}:{s % 60:04.1f}'


def _face_tile(path, u, st, out_dir):
    """A close-up crop of the faces at the middle of the stretch (PIL image, yellow frame), or None when there are
    none or they are big enough in a normal tile."""
    try:
        import letitedit.review.checks as checks
        from PIL import Image, ImageOps
    except ImportError:
        return None
    ff, _ = _tools()
    px = st['tile_px']
    p = out_dir / f"u{u['i']:04d}-big.jpg"
    if not p.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, '-v', 'error', '-y', '-ss', f"{(u['t0'] + u['t1']) / 2:.3f}", '-i', str(path),
                        '-frames:v', '1', '-vf', "scale='min(1280,iw)':-2", '-q:v', '3', str(p)],
                       capture_output=True, creationflags=NO_WINDOW)
    if not p.exists():
        return None
    try:
        boxes = checks.faces_in(p)
    except Exception:  # noqa: BLE001
        return None
    if not boxes:
        return None
    im = Image.open(p).convert('RGB')
    W, H = im.size
    boxes = sorted(boxes, key=lambda b: -(b[3] - b[1]))[:3]
    if (boxes[0][3] - boxes[0][1]) * px / max(W, H) >= st['face_min_px']:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    pad = 0.6 * max(b[3] - b[1] for b in boxes)
    crop = im.crop((max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(W, int(x1 + pad)), min(H, int(y1 + pad))))
    crop.thumbnail((px, px))
    return ImageOps.expand(crop, border=4, fill=(255, 210, 0))


def contact_sheet(path, batch, out_png, st):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype('arial.ttf', 20)
    except OSError:
        font = ImageFont.load_default()
    px = st['tile_px']
    rows = []
    for u in batch:
        ims = [Image.open(p).convert('RGB') for p in _frames(path, u, st['frames_per_unit'], px, out_png.parent / 'f')]
        face = _face_tile(path, u, st, out_png.parent / 'f') if st.get('face_tiles') else None
        if face is not None:
            ims.append(face)
        h = max([im.height for im in ims] or [px // 2])
        row = Image.new('RGB', (170 + len(ims) * (px + 14), h + 8), 'white')
        d = ImageDraw.Draw(row)
        d.text((6, 6), f"U{u['i']:02d}", fill='black', font=font)
        d.text((6, 34), f"{_clock(u['t0'])}-", fill='black', font=font)
        d.text((6, 60), _clock(u['t1']), fill='black', font=font)
        for j, im in enumerate(ims):
            row.paste(im, (170 + j * (px + 14), 4))
        rows.append(row)
    sheet = Image.new('RGB', (max(r.width for r in rows), sum(r.height for r in rows)), 'white')
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def _mood_items(moods):
    """[(name, what it means)] for a list of names and/or a {name: meaning} dict."""
    if isinstance(moods, dict):
        return [(m, MOOD_TEXT.get(m) or moods[m]) for m in moods]
    return [(m, MOOD_TEXT.get(m, m)) for m in (moods or MOODS)]


def prompt_for(batch, sheet_ref, clip_name, before='', n_frames=3, moods=None, only=False):
    """The labelling prompt. moods: names or {name: meaning} (default MOODS). only=True: just those moods (adding
    moods to a graph), without neutral, energy, positivity and 'other'."""
    items = _mood_items(moods)
    lines = '\n'.join(f"U{u['i']:02d} ({_clock(u['t0'])}-{_clock(u['t1'])}, {u['kind']}): said: "
                      f"\"{u['said'] or '(no talking)'}\"" for u in batch)
    mood_lines = '\n'.join(f'- {m}: {t}' for m, t in items)
    keys = ', '.join(f'"U{u["i"]:02d}"' for u in batch)
    names = [m for m, _ in items]
    head = (f"You are labelling raw footage for a video editor (clip {clip_name}). The image {sheet_ref} shows "
            f"consecutive stretches of the clip in time order, one row each (U.., with its time), "
            f"{n_frames} frames per row left to right; a row may end with one more picture framed in yellow: a "
            f"close-up of the faces at the middle of that stretch, to read their expressions. What is said in each "
            f"stretch:\n{lines}\n{before}\n")
    example = ', '.join(f'"{m}": 0' for m in names[:2]) + (', ...' if len(names) > 2 else '')
    if only:
        return (head + f"For EACH stretch, rate how strongly a viewer would feel each of these moods, 0 (not at all) "
                f"to 3 (strongly):\n{mood_lines}\nJudge from the faces, the pictures and the words together, as an "
                f"editor would, and keep the scale consistent across stretches.\n\n"
                f"Answer with JSON only, keys {keys}: {{\"U01\": {{{example}}}, ...}}")
    return (head + f"For EACH stretch, rate how strongly a viewer would feel each mood, 0 (not at all) to 3 "
            f"(strongly):\n{mood_lines}\n- neutral: {NEUTRAL_TEXT}\n"
            f"Score neutral on its own: how much of the stretch is plain explaining or routine. It does not lower the "
            f"moods: give each mood what a viewer would feel, even when mild (1 = a hint, 2 = clearly felt, 3 = "
            f"strong, 0 = not there). Also: energy 1 (very calm) to 5 (very intense), positivity -2 (very "
            f"negative) to +2 (very positive). If a stretch "
            f"clearly carries a feeling none of these names fits (2 or more), add up to two under \"other\" in your "
            f"own words, e.g. \"other\": {{\"nostalgia\": 2}}; otherwise leave \"other\" out.\n"
            f"Judge from the faces, the pictures and the words together, as an editor would. Keep the scale "
            f"consistent across stretches so changes between neighbours show.\n\n"
            f"Answer with JSON only, keys {keys}: {{\"U01\": {{{example}, \"neutral\": 0, \"energy\": 3, "
            f"\"positivity\": 0}}, ...}}")


def parse_scores(text, batch, moods=None, base=True):
    """{unit index: {mood: 0-3, neutral: 0-3, energy: 1-5, positivity: -2..2, other: {name: 0-3}}} from an AI's
    answer (bad values dropped). base=False: only the moods asked for (adding moods)."""
    names = [m for m, _ in _mood_items(moods)]
    data = None
    for cand in reversed(re.findall(r'\{.*\}', text or '', re.S)):
        try:
            data = json.loads(cand)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return {}
    out = {}
    extra = [('neutral', 0, 3), ('energy', 1, 5), ('positivity', -2, 2)] if base else []
    for u in batch:
        row = data.get(f"U{u['i']:02d}") or data.get(f"U{u['i']}")
        if not isinstance(row, dict):
            continue
        sc = {}
        for k, lo, hi in [(m, 0, 3) for m in names] + extra:
            v = row.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                sc[k] = float(min(hi, max(lo, v)))
        if sum(1 for m in names if m in sc) < len(names):
            continue
        other = row.get('other')
        if base and isinstance(other, dict):
            o = {}
            for k, v in other.items():
                name = re.sub(r'[^a-z0-9 _-]', '', str(k).lower()).strip()[:30]
                if len(o) < 2 and name and name not in names and name != 'neutral' and \
                        isinstance(v, (int, float)) and not isinstance(v, bool):
                    o[name] = float(min(3, max(0, v)))
            if o:
                sc['other'] = o
        out[u['i']] = sc
    return out


def _ask(lab, prompt, sheet, cwd, timeout):
    import letitedit.app.ai_clis as ai_clis
    t = time.time()
    usage = {}
    if lab['engine'] == 'codex':
        cmd = [lab['cli'], 'exec', '--skip-git-repo-check', '--sandbox', 'read-only', '-m', lab['model'],
               '-c', f'model_reasoning_effort="{lab["effort"]}"', '-i', str(sheet), '-']
        r = ai_clis.run_with_speed(cmd, 'codex', lab['model'], input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           cwd=cwd, timeout=timeout, creationflags=NO_WINDOW)
        text = r.stdout
        m = re.search(r'tokens used\s*\n\s*([\d,]+)', (r.stdout or '') + (r.stderr or ''))
        usage['tokens'] = int(m.group(1).replace(',', '')) if m else None
    else:
        cmd = [lab['cli'], '-p', '--model', lab['model'], '--output-format', 'json', '--setting-sources', 'local',
               '--strict-mcp-config', '--allowedTools', 'Read', '--add-dir', str(Path(sheet).parent)]
        cmd += ai_clis.claude_instruction_args()
        r = ai_clis.run_with_speed(cmd, 'claude', lab['model'], input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           cwd=cwd, timeout=timeout, creationflags=NO_WINDOW)
        text = r.stdout
        try:
            j = json.loads(r.stdout)
            text = j.get('result') or ''
            u = j.get('usage') or {}
            usage['tokens'] = int(u.get('input_tokens') or 0) + int(u.get('output_tokens') or 0)
            usage['cached_tokens'] = int(u.get('cache_read_input_tokens') or 0) + \
                int(u.get('cache_creation_input_tokens') or 0)
            usage['cost_usd_api'] = j.get('total_cost_usd')
        except ValueError:
            pass
    usage['seconds'] = round(time.time() - t, 1)
    usage['exit'] = r.returncode
    return text, usage, (r.stderr or '')[-1500:]


# ------------------------------------------------------------------ turning points

def _top(sc, moods=None):
    best = max(moods or MOODS, key=lambda m: sc.get(m, 0))
    return best, sc.get(best, 0)


def turning_points(us, source=None, settings=None, words=None, moods=None):
    """Where the mood changes between neighbouring stretches: 'crossover' (the leading mood changes, one leader
    at least 2 of 3 and the other at least 1, each ahead of the other in its own stretch: no ties), 'rise' / 'drop' (a mood moves >= turn_delta, or by 1 to or from 2 or
    more), 'energy' and 'positivity' jumps, and 'peak'
    (a mood at 3 that its neighbours don't have). Each names the boundary time, the words either side, and the call
    that shows it frame by frame. moods: the mood names to look at (default MOODS; never 'neutral')."""
    st = _settings(settings)
    moods = [m for m in (moods or MOODS) if m != 'neutral']
    pts = []
    scored = [u for u in us if u.get('scores')]
    for a, b in zip(scored, scored[1:]):
        if b['i'] != a['i'] + 1:
            continue
        sa, sb = a['scores'], b['scores']
        t = b['t0']
        found = []
        (ma, va), (mb, vb) = _top(sa, moods), _top(sb, moods)
        if ma != mb and max(va, vb) >= 2 and min(va, vb) >= 1 and sa.get(ma, 0) > sa.get(mb, 0) and \
                sb.get(mb, 0) > sb.get(ma, 0):
            found.append({'kind': 'crossover', 'mood': f'{ma} -> {mb}', 'from': va, 'to': vb,
                          'strength': round((vb - sb.get(ma, 0)) + (va - sa.get(mb, 0)), 2)})
        for m in moods:
            d = sb.get(m, 0) - sa.get(m, 0)
            if abs(d) >= st['turn_delta'] or (abs(d) >= 1 and max(sa.get(m, 0), sb.get(m, 0)) >= 2):
                found.append({'kind': 'rise' if d > 0 else 'drop', 'mood': m, 'from': sa.get(m), 'to': sb.get(m),
                              'strength': round(abs(d), 2)})
        for k, thr in (('energy', st['energy_delta']), ('positivity', st['positivity_delta'])):
            d = sb.get(k, 0) - sa.get(k, 0)
            if abs(d) >= thr:
                found.append({'kind': f'{k} ' + ('up' if d > 0 else 'down'), 'mood': k, 'from': sa.get(k),
                              'to': sb.get(k), 'strength': round(abs(d), 2)})
        for f in found:
            f.update(t=round(t, 3), between=[a['i'], b['i']],
                     said_before=' '.join(a.get('said', '').split()[-8:]),
                     said_after=' '.join(b.get('said', '').split()[:8]))
            if source:
                f['hone'] = {'tool': 'letitedit_timing', 'source': str(source), 'view': 'slow',
                             'start_s': round(max(0.0, t - 1.0), 2), 'end_s': round(t + 1.0, 2)}
            pts.append(f)
    for i, u in enumerate(scored):
        for m in moods:
            if u['scores'].get(m, 0) >= 3:
                nb = [scored[j]['scores'].get(m, 0) for j in (i - 1, i + 1) if 0 <= j < len(scored)]
                if nb and max(nb) <= 1.5:
                    p = {'kind': 'peak', 'mood': m, 't': round((u['t0'] + u['t1']) / 2, 3), 't0': u['t0'],
                         't1': u['t1'], 'unit': u['i'], 'strength': round(3 - max(nb), 2), 'said': u.get('said', '')}
                    if source:
                        p['hone'] = {'tool': 'letitedit_timing', 'source': str(source), 'view': 'slow',
                                     'start_s': u['t0'], 'end_s': round(min(u['t1'], u['t0'] + 3.0), 2)}
                    pts.append(p)
    if words:
        _word_edges(pts, words)
    pts.sort(key=lambda p: (p['t'], -p['strength']))
    return pts


def _word_edges(pts, words):
    """The last word before and the first word after each boundary, with their exact times (cut candidates)."""
    ws = sorted(words, key=lambda w: float(w['t0']))
    for p in pts:
        if p['kind'] == 'peak':
            continue
        before = [w for w in ws if float(w['t1']) <= p['t'] + 0.05]
        after = [w for w in ws if float(w['t0']) >= p['t'] - 0.05]
        if before:
            p['last_word'] = {'w': before[-1]['w'].strip(), 't1': round(float(before[-1]['t1']), 3)}
        if after:
            p['next_word'] = {'w': after[0]['w'].strip(), 't0': round(float(after[0]['t0']), 3)}


# ------------------------------------------------------------------ the graph of one file

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _cache_path(key, lab):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', f"{lab['engine']}-{lab['model']}")
    return CACHE / f'{key}-{safe}-v{VERSION}{PROMPT_VERSION}.json'


def cached(path, settings=None):
    """The newest cached graph of the file by any labeller, or None."""
    try:
        key = file_key(path)
    except OSError:
        return None
    found = sorted(CACHE.glob(f'{key}-*-v{VERSION}{PROMPT_VERSION}.json'), key=lambda p: p.stat().st_mtime)
    if not found:
        return None
    try:
        return json.loads(found[-1].read_text(encoding='utf-8-sig'))
    except ValueError:
        return None


def graph(source, build=None, refresh=False, settings=None, progress=None, check=None, add=None):
    """The emotion graph of one video file. build: None = build when the emotion_graph setting is on, True = build
    anyway, False = cached only (None returned when there is none). add: {name: meaning} moods to score on top
    (an explicit request: scored on an existing graph even when build is False); the setting emotion_extra_moods is
    scored when building is allowed."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f'no such video file: {path}')
    st = _settings(settings)
    allowed = build is True or (build is None and bool(st.get('emotion_graph')))
    extra = {**(norm_moods(st.get('emotion_extra_moods')) if allowed else {}), **norm_moods(add)}
    g = _graph(path, allowed, refresh, st, progress, check, extra)
    if g is not None:
        missing = {k: v for k, v in extra.items() if k not in g.get('moods', [])}
        if missing:
            g = _add(path, g, missing, st, progress, check)
    return g


def _graph(path, allowed, refresh, st, progress, check, extra):
    lab = labeller(st)
    key = file_key(path)
    cp = _cache_path(key, lab) if lab['engine'] else None
    if cp and cp.exists() and not refresh:
        try:
            return json.loads(cp.read_text(encoding='utf-8-sig'))
        except ValueError:
            pass
    if not refresh:
        old = cached(path, st)
        if old:
            return old
    if not allowed:
        return None
    if not lab['engine']:
        raise RuntimeError(f"no AI to score the mood: {lab['why']}")
    with _LOCKS_GUARD:
        lk = _LOCKS.setdefault(key, threading.Lock())
    with lk:
        if cp.exists() and not refresh:
            return json.loads(cp.read_text(encoding='utf-8-sig'))
        return _build(path, key, lab, st, cp, progress, check, extra)


def add_moods(source, moods, settings=None, progress=None, check=None, build=None):
    """Score more moods ({name: what it means}, a list of names, or 'a=meaning; b') on the file's graph and keep
    them with it. -> the graph (None when there is no graph and building is not allowed)."""
    return graph(source, build=build, settings=settings, progress=progress, check=check, add=moods)


def _save(g, cp):
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix('.tmp')
    tmp.write_text(json.dumps(g, indent=1), encoding='utf-8')
    os.replace(tmp, cp)


def _add(path, g, extra, st, progress, check):
    """Score the moods in extra on every stretch of an existing graph (same AI and model as the graph)."""
    lab = labeller({**st, 'emotion_engine': g['labeller']['engine'], 'emotion_model': g['labeller']['model']})
    if not lab['engine']:
        raise RuntimeError(f"no AI to score the added moods: {lab['why']}")
    key = g['file_key']
    with _LOCKS_GUARD:
        lk = _LOCKS.setdefault(key, threading.Lock())
    with lk:
        t_start = time.time()
        us = g['units']
        work = CACHE / 'sheets' / key
        batches = [us[i:i + st['units_per_call']] for i in range(0, len(us), st['units_per_call'])]
        calls, lock = [], threading.Lock()

        def one(bi):
            if check:
                check()
            batch = batches[bi]
            sheet = contact_sheet(path, batch, work / f'b{bi:03d}.png', st)
            ref = 'attached' if lab['engine'] == 'codex' else f'at {sheet} (open it with the Read tool)'
            sc, usage, err, text = {}, {}, '', ''
            for attempt in range(2):
                text, usage, err = _ask(lab, prompt_for(batch, ref, path.name, '', st['frames_per_unit'], extra,
                                                        only=True), sheet, str(work), st['call_timeout_s'])
                sc = parse_scores(text, batch, extra, base=False)
                if len(sc) == len(batch):
                    break
            with lock:
                calls.append({'batch': bi, 'units': [u['i'] for u in batch], 'scored': len(sc), 'added': list(extra),
                              **usage, **({'stderr_tail': err[-300:], 'answer_tail': (text or '')[-300:]} if len(sc) < len(batch) else {})})
                for u in batch:
                    if u['i'] in sc and u.get('scores'):
                        u['scores'].update(sc[u['i']])
                if progress:
                    progress(len(calls) / max(1, len(batches)), f'emotion graph {path.name}: adding '
                             f'{", ".join(extra)} ({len(calls)} of {len(batches)} AI calls)')

        with ThreadPoolExecutor(max(1, int(st['calls_parallel']))) as ex:
            list(ex.map(one, range(len(batches))))
        g['moods'] = list(g.get('moods') or MOODS) + [m for m in extra if m not in (g.get('moods') or [])]
        g.setdefault('custom_moods', {}).update(extra)
        g.setdefault('mood_text', {}).update(extra)
        g['calls'] = list(g.get('calls', [])) + sorted(calls, key=lambda c: c['batch'])
        g['tokens'] = int(g.get('tokens') or 0) + sum(c.get('tokens') or 0 for c in calls)
        g['seconds_added'] = round(float(g.get('seconds_added') or 0) + time.time() - t_start, 1)
        missed = sum(1 for u in us if u.get('scores') and any(m not in u['scores'] for m in extra))
        if missed:
            g.setdefault('warnings', []).append(f'{missed} stretches got no score for the added moods '
                                                f'{", ".join(extra)}')
        g['turning_points'] = turning_points(us, path, st, _words(path)[0], g['moods'])
        _save(g, _cache_path(key, lab))
    return g


def _build(path, key, lab, st, cp, progress, check, extra=None):
    t_start = time.time()
    extra = dict(extra or {})
    mood_map = {**{m: MOOD_TEXT[m] for m in MOODS}, **extra}
    dur = duration_s(path)
    words, how, warnings = _words(path)
    us = units(words, dur, st)
    work = CACHE / 'sheets' / key
    batches = [us[i:i + st['units_per_call']] for i in range(0, len(us), st['units_per_call'])]
    calls = []
    lock = threading.Lock()

    def one(bi):
        if check:
            check()
        batch = batches[bi]
        sheet = contact_sheet(path, batch, work / f'b{bi:03d}.png', st)
        prev = batches[bi - 1][-1] if bi else None
        before = (f"(The stretch just before U{batch[0]['i']:02d} said: \"{prev['said'][-200:]}\")"
                  if prev and prev.get('said') else '')
        ref = 'attached' if lab['engine'] == 'codex' else f'at {sheet} (open it with the Read tool)'
        sc, usage, err, text = {}, {}, '', ''
        for attempt in range(2):
            text, usage, err = _ask(lab, prompt_for(batch, ref, path.name, before, st['frames_per_unit'], mood_map),
                                    sheet, str(work), st['call_timeout_s'])
            sc = parse_scores(text, batch, mood_map)
            if len(sc) == len(batch):
                break
        with lock:
            calls.append({'batch': bi, 'units': [u['i'] for u in batch], 'scored': len(sc), **usage,
                          **({'stderr_tail': err[-300:], 'answer_tail': (text or '')[-300:]} if len(sc) < len(batch) else {})})
            for u in batch:
                if u['i'] in sc:
                    other = sc[u['i']].pop('other', None)
                    u['scores'] = sc[u['i']]
                    if other:
                        u['other'] = other
            if progress:
                progress(len(calls) / max(1, len(batches)), f'emotion graph {path.name}: {len(calls)} of '
                         f'{len(batches)} AI calls')

    with ThreadPoolExecutor(max(1, int(st['calls_parallel']))) as ex:
        list(ex.map(one, range(len(batches))))
    curves = measured_curves(path, dur, st['curve_step_s'])
    step = curves['step_s']
    for u in us:
        i0, i1 = int(u['t0'] // step), max(int(u['t0'] // step) + 1, int(np.ceil(u['t1'] / step)))
        ld = [v for v in curves['loudness_db'][i0:i1] if v is not None]
        mo = [v for v in curves['motion'][i0:i1] if v is not None]
        n_words = len(u['said'].split()) if u.get('said') else 0
        u['measured'] = {'loudness_db': round(float(np.mean(ld)), 1) if ld else None,
                         'motion': round(float(np.mean(mo)), 2) if mo else None,
                         'words_per_s': round(n_words / max(0.1, u['t1'] - u['t0']), 2)}
    missing = [u['i'] for u in us if 'scores' not in u]
    if missing:
        warnings.append(f'{len(missing)} of {len(us)} stretches got no scores from the AI: {missing[:20]}')
    res = {
        'schema': 'emotion_graph', 'version': VERSION, 'prompt_version': PROMPT_VERSION, 'source': str(path),
        'file_key': key, 'duration_s': round(dur, 3), 'labeller': {k: lab[k] for k in ('engine', 'model', 'why')},
        'words': how, 'moods': list(mood_map), 'custom_moods': extra, 'mood_text': mood_map,
        'neutral': NEUTRAL_TEXT,
        'scales': {'moods': '0-3', 'neutral': '0-3', 'energy': '1-5', 'positivity': '-2..+2', 'other': '0-3'},
        'units': us, 'turning_points': turning_points(us, path, st, words, list(mood_map)), 'curves': curves,
        'calls': sorted(calls, key=lambda c: c['batch']), 'warnings': warnings,
        'trust': ('Mood, energy and positivity scores are the judgement of the AI named in labeller (its fast model), '
                  'not measurements: on the test footage its main mood matched the full models 78-93% of the time; '
                  'loudness, motion and words per second are measured.'),
        'built': time.strftime('%Y-%m-%d %H:%M:%S'), 'seconds': round(time.time() - t_start, 1),
        'tokens': sum(c.get('tokens') or 0 for c in calls),
    }
    _save(res, cp)
    return res


def build(files, progress=None, check=None, settings=None):
    """Graphs for many files (videos only), built when missing. -> {file: 'cached'|'built'|'error: ...'}"""
    vids = [str(f) for f in files if Path(f).suffix.lower() in VIDEO_EXT]
    out = {}
    for i, f in enumerate(vids):
        if check:
            check()
        try:
            had = cached(f, settings) is not None
            g = graph(f, build=True, settings=settings, check=check,
                      progress=(lambda fr, m, i=i: progress((i + fr) / max(1, len(vids)), m)) if progress else None)
            out[f] = 'cached' if had else f"built ({g.get('seconds')} s, {len(g.get('calls', []))} calls)"
        except Exception as e:  # noqa: BLE001
            out[f] = f'error: {type(e).__name__}: {e}'[:300]
    return out


# ------------------------------------------------------------------ the picture

COLORS = {'tension': (230, 70, 70), 'relief': (110, 220, 190), 'surprise': (200, 110, 255),
          'excitement': (255, 140, 30), 'joy': (250, 210, 60), 'humor': (255, 130, 190), 'warmth': (210, 150, 100),
          'sincerity': (150, 190, 255), 'awkwardness': (170, 170, 90), 'frustration': (170, 30, 30),
          'sadness': (90, 110, 220), 'awe': (60, 200, 210), 'peaceful': (140, 200, 140),
          'satisfaction': (80, 230, 90)}
EXTRA_COLORS = [(240, 240, 120), (120, 240, 240), (240, 120, 240), (200, 200, 200), (255, 190, 150),
                (150, 255, 150), (190, 150, 255), (255, 255, 255)]


def _color(m, g):
    if m in COLORS:
        return COLORS[m]
    custom = [k for k in (g.get('moods') or []) if k not in COLORS]
    return EXTRA_COLORS[custom.index(m) % len(EXTRA_COLORS)] if m in custom else (220, 220, 220)


def draw(g, out_png, start_s=None, end_s=None, width=1600, max_moods=6):
    """The graph as a picture: the leading moods as lines (0-3), positivity (white, dashed centre = 0), measured
    energy (grey area: loudness and motion), stretch borders, turning points (yellow, numbered)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype('arial.ttf', 15)
        big = ImageFont.truetype('arialbd.ttf', 18)
    except OSError:
        font = big = ImageFont.load_default()
    us = [u for u in g['units'] if u.get('scores')]
    t0 = float(start_s if start_s is not None else 0.0)
    t1 = float(end_s if end_s is not None else g['duration_s'])
    us = [u for u in us if u['t1'] > t0 and u['t0'] < t1]
    moods = list(g.get('moods') or MOODS)
    peaks = {m: max([u['scores'].get(m, 0) for u in us] or [0]) for m in moods}
    shown = [m for m in sorted(moods, key=lambda m: -peaks[m]) if peaks[m] >= 1.5][:max_moods]
    L, R, H_m, H_p, H_e = 60, 20, 260, 90, 70
    H = 40 + H_m + 20 + H_p + 20 + H_e + 50
    im = Image.new('RGB', (width, H), (24, 24, 28))
    d = ImageDraw.Draw(im)

    def x(t):
        return L + (t - t0) / max(1e-6, t1 - t0) * (width - L - R)

    title = f"{Path(g['source']).name}  {_clock(t0)}-{_clock(t1)}   moods by {g['labeller']['engine']} " \
            f"{g['labeller']['model']} (judgement), energy measured"
    d.text((L, 8), title, fill=(235, 235, 235), font=big)
    ym0 = 40
    for v in range(4):
        y = ym0 + H_m - v / 3 * H_m
        d.line([(L, y), (width - R, y)], fill=(50, 50, 58))
        d.text((10, y - 8), str(v), fill=(150, 150, 160), font=font)
    for u in us:
        d.line([(x(u['t0']), ym0), (x(u['t0']), ym0 + H_m)], fill=(44, 44, 52))
    for k, m in enumerate(shown):
        pts = []
        for u in us:
            y = ym0 + H_m - u['scores'].get(m, 0) / 3 * H_m - (k - len(shown) / 2) * 1.5
            pts += [(x(max(u['t0'], t0)), y), (x(min(u['t1'], t1)), y)]
        if len(pts) >= 2:
            d.line(pts, fill=_color(m, g), width=3)
        d.text((L + 10 + k * 170, ym0 + 4), m, fill=_color(m, g), font=big)
    pts = []
    for u in us:
        y = ym0 + H_m - u['scores'].get('neutral', 0) / 3 * H_m
        pts += [(x(max(u['t0'], t0)), y), (x(min(u['t1'], t1)), y)]
    for a, b in zip(pts[::2], pts[1::2]):
        for xx in range(int(a[0]), int(b[0]), 10):
            d.line([(xx, a[1]), (min(xx + 4, b[0]), a[1])], fill=(120, 120, 130), width=1)
    yp0 = ym0 + H_m + 20
    d.text((10, yp0), 'pos', fill=(150, 150, 160), font=font)
    for xx in range(L, width - R, 12):
        d.line([(xx, yp0 + H_p / 2), (xx + 5, yp0 + H_p / 2)], fill=(70, 70, 80))
    pts = []
    for u in us:
        y = yp0 + H_p / 2 - u['scores'].get('positivity', 0) / 2 * (H_p / 2)
        pts += [(x(max(u['t0'], t0)), y), (x(min(u['t1'], t1)), y)]
    if len(pts) >= 2:
        d.line(pts, fill=(240, 240, 240), width=2)
    ye0 = yp0 + H_p + 20
    d.text((10, ye0), 'energy', fill=(150, 150, 160), font=font)
    c = g.get('curves') or {}
    step = c.get('step_s', 0.5)
    for i, (ld, mo) in enumerate(zip(c.get('loudness_db', []), c.get('motion', []))):
        t = i * step
        if t < t0 or t > t1:
            continue
        lv = 0 if ld is None else min(1, max(0, (ld + 50) / 40))
        mv = 0 if mo is None else min(1, mo / 25)
        v = (lv + mv) / 2
        d.rectangle([x(t), ye0 + H_e - v * H_e, x(t + step), ye0 + H_e], fill=(110, 110, 125))
    for u in us:
        e = u['scores'].get('energy')
        if e:
            y = ye0 + H_e - (e - 1) / 4 * H_e
            d.line([(x(max(u['t0'], t0)), y), (x(min(u['t1'], t1)), y)], fill=(255, 170, 60), width=2)
    n = 0
    for p in g.get('turning_points', []):
        if not (t0 <= p['t'] <= t1) or p['kind'] in ('rise', 'drop') and p['strength'] < 2:
            continue
        n += 1
        xx = x(p['t'])
        d.line([(xx, ym0), (xx, ye0 + H_e)], fill=(255, 220, 0), width=1)
        d.text((xx + 3, ym0 + H_m - 18 - (n % 3) * 16), f"{n} {p['kind']}", fill=(255, 220, 0), font=font)
    for s in range(int(t0) - int(t0) % 10, int(t1) + 1, 10 if t1 - t0 <= 300 else 30):
        if s >= t0:
            d.text((x(s) - 14, H - 40), _clock(s)[:-2], fill=(150, 150, 160), font=font)
    d.text((L, H - 22), 'dotted grey: neutral; orange line: AI energy 1-5; grey area: measured loudness + motion; '
           'yellow: turning points',
           fill=(150, 150, 160), font=font)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_png)
    return str(out_png)


# ------------------------------------------------------------------ the view

def _summary_lines(g, start_s=None, end_s=None, limit=80):
    t0 = start_s or 0.0
    t1 = end_s if end_s is not None else g['duration_s']
    out = []
    for u in g['units']:
        if u['t1'] <= t0 or u['t0'] >= t1:
            continue
        sc = u.get('scores')
        if not sc:
            out.append(f"U{u['i']:02d} {_clock(u['t0'])}-{_clock(u['t1'])}  (no scores)")
            continue
        top = sorted(g.get('moods') or MOODS, key=lambda m: -sc.get(m, 0))
        moods = ', '.join(f'{m} {sc[m]:g}' for m in top[:3] if sc.get(m, 0) >= 1) or 'flat'
        if sc.get('neutral', 0) >= 2:
            moods += f", neutral {sc['neutral']:g}"
        if u.get('other'):
            moods += ' | other: ' + ', '.join(f'{k} {v:g}' for k, v in u['other'].items())
        me = u.get('measured') or {}
        en, po = sc.get('energy'), sc.get('positivity')
        out.append(f"U{u['i']:02d} {_clock(u['t0'])}-{_clock(u['t1'])}  {moods} | energy "
                   f"{'?' if en is None else format(en, 'g')} pos {'?' if po is None else format(po, '+g')} | "
                   f"{me.get('loudness_db')} dB, motion {me.get('motion')}, "
                   f"{me.get('words_per_s')} w/s | \"{(u.get('said') or '')[:70]}\"")
    if len(out) > limit:
        out = out[:limit] + [f'... {len(out) - limit} more stretches in result_file']
    return out


def _files_of(source):
    p = Path(source)
    if p.is_dir():
        return sorted(str(f) for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT)
    if p.is_file() and p.suffix.lower() in VIDEO_EXT:
        return [str(p)]
    return []


def view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """letitedit_timing(source, view='emotion'): a video file or a folder of them."""
    import letitedit.timing.timing_views as timing_views
    if 'emotion' in [v.strip() for v in os.environ.get('LETITEDIT_VIEWS_OFF', '').split(',')]:
        res = timing_views.common_fields(source=str(source), view='emotion', inputs=[start_s, end_s, None, detail],
                                         warnings=[], unsupported=['the emotion view is turned off on this computer'])
        res.update({'view': 'emotion', 'files': [], 'note': 'no emotion graph here: judge the feeling yourself'})
        return res
    opts = dict(options or {})
    st = _settings(opts.get('settings'))
    build_opt = opts.get('build')
    add = norm_moods(opts.get('moods'))
    files = _files_of(source)
    warnings, unsupported, images, out_files = [], [], [], []
    if not files:
        unsupported.append('the emotion view reads video files or a folder of them (raw footage); for a project, '
                           'look at its source files')
    lab = labeller(st)
    out_dir = CACHE / 'views'
    for f in files:
        try:
            g = graph(f, build=build_opt if build_opt is not None else None, refresh=bool(opts.get('refresh')),
                      settings=st, add=add)
        except Exception as e:  # noqa: BLE001
            warnings.append(f'{Path(f).name}: {type(e).__name__}: {e}'[:300])
            continue
        if g is None:
            out_files.append({'file': f, 'graph': None})
            continue
        s0 = start_s if len(files) == 1 else None
        s1 = end_s if len(files) == 1 else None
        png = draw(g, out_dir / f"{g['file_key']}-{int((s0 or 0) * 10)}-{int((s1 or g['duration_s']) * 10)}.png",
                   s0, s1)
        images.append(png)
        tps = [p for p in g['turning_points'] if (s0 is None or p['t'] >= s0) and (s1 is None or p['t'] <= s1)]
        seen = {}
        for u in g['units']:
            for k, v in (u.get('other') or {}).items():
                seen.setdefault(k, []).append(v)
        entry = {'file': f, 'duration_s': g['duration_s'], 'labeller': g['labeller'], 'image': png,
                 'custom_moods': g.get('custom_moods') or {},
                 'other_moods_seen': {k: {'stretches': len(v), 'max': max(v)}
                                      for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1]))[:12]},
                 'stretches': _summary_lines(g, s0, s1, 80 if detail == 'brief' else 10 ** 6),
                 'turning_points': tps if detail == 'full' else sorted(tps, key=lambda p: -p['strength'])[:25],
                 'cache_file': str(_cache_path(g['file_key'], {'engine': g['labeller']['engine'],
                                                                'model': g['labeller']['model']}))}
        if detail == 'full':
            entry['units'] = g['units']
            entry['curves'] = g['curves']
        warnings += [f"{Path(f).name}: {w}" for w in g.get('warnings', [])]
        out_files.append(entry)
    missing = [e['file'] for e in out_files if e.get('graph', 1) is None]
    note = None
    if missing:
        n = len(missing)
        state = 'on' if st.get('emotion_graph') else 'off'
        note = (f"{n} file(s) have no emotion graph yet (setting emotion_graph is {state}). "
                f"options={{'build': true}} builds them now: {lab['engine'] or 'no AI found'} "
                f"{lab['model'] or ''} scores about 10 stretches per call (~10-15 s and ~9-13K tokens per call "
                f"measured with Codex); the index job builds them when the setting is on.")
    res = timing_views.common_fields(source=str(source), view='emotion',
                                     inputs=[start_s, end_s, opts.get('build'), detail],
                                     warnings=warnings, unsupported=unsupported)
    res.update({
        'view': 'emotion', 'images': images[:12], 'files': out_files, 'note': note,
        'labeller': {k: lab[k] for k in ('engine', 'model', 'why')}, 'setting_emotion_graph': bool(st.get('emotion_graph')),
        'how_to_read': ('Each stretch is a sentence (or ~5 s without talking) scored by an AI: moods 0-3 (MOODS plus '
                        'custom_moods), neutral 0-3 (explaining or routine), energy 1-5, positivity -2..+2 '
                        '(judgement, not measurement); loudness/motion/words per second are measured. '
                        'turning_points: crossover (the leading mood changes), rise/drop (a mood moves 1.5, or 1 to or from 2+), '
                        'energy/positivity jumps, peak. Each turning point gives the last word before and the next '
                        'word after the boundary (exact times) and a hone call: letitedit_timing(view=\'slow\') around '
                        'it, to pick the exact frame yourself. other_moods_seen: feelings the AI named outside the '
                        'list; options={\'moods\': {name: what it means}} scores any mood you need on every stretch '
                        '(kept with the graph; about the cost of one build).'),
        'moods': MOODS,
        'options_used': {'build': build_opt, 'refresh': bool(opts.get('refresh')), 'moods': add},
    })
    return res


def _register():
    try:
        import letitedit.timing.timing_views as timing_views
        timing_views.register_view(
            'emotion', view,
            "mood and energy of raw footage per sentence (an AI's judgement on its fast model, cached; measured "
            "loudness/motion), with turning points (crossovers, rises, drops, peaks) and the words and 'slow' call "
            "to hone in on each; video file or folder; options.build = true builds missing graphs; options.moods = "
            "{name: meaning} scores your own moods too")
    except Exception:  # noqa: BLE001
        pass


_register()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('python emotion_graph.py <video or folder> [--build] [--refresh] [--engine claude|codex] '
              '[--model m] [--effort low] [--moods "name=meaning; name"]')
        raise SystemExit(2)
    fs = _files_of(sys.argv[1])
    given = {f'emotion_{k}': sys.argv[sys.argv.index(f'--{k}') + 1]
             for k in ('engine', 'model', 'effort') if f'--{k}' in sys.argv[:-1]}
    for f in fs:
        g = graph(f, build=True if '--build' in sys.argv else None, refresh='--refresh' in sys.argv,
                  settings=given, add=sys.argv[sys.argv.index('--moods') + 1] if '--moods' in sys.argv[:-1] else None)
        if g is None:
            print(f, 'no graph (use --build)')
            continue
        print(f, g['seconds'], 's', len(g['calls']), 'calls', g['tokens'], 'tokens')
        print('\n'.join(_summary_lines(g)))
        for p in g['turning_points'][:15]:
            print('  TP', p['t'], p['kind'], p['mood'], p.get('said_before', p.get('said', ''))[-40:], '|',
                  p.get('said_after', '')[:40])
