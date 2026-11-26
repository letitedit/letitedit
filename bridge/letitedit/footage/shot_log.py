r"""Footage log: what is seen in every shot of a video, written once by a local vision model and cached.

    log(video, max_s=8.0, frames=3, width=448, merge_below=5.0, merge_max_s=30.0, cut_above=0.3, words=True,
        build=True)
        -> {'file', 'duration', 'shots': [{'from', 'to', 'action', 'things', 'place', 'framing', 'text', 'quality',
            'best'}], 'model', 'settings', 'seconds'}  (None when build=False and it isn't cached)
    log_folder(paths, **same)          every video, one after another (the GPU runs one job at a time)
    lines(entry, detail=False)         the log as text lines ('0:00-0:08  close-up, handheld: action ...')

How a video is split: the picture cuts (ffmpeg scene score over cut_above) make shots; a shot longer than max_s is
split into equal parts; neighbouring parts whose middle frames look nearly the same (mean difference of a 64x64 grey
copy under merge_below, 0-255) are joined, up to merge_max_s. Each part is shown to the model as `frames` frames
`width` px wide, with the words said in it (words=True, from the cached transcript), and the model writes labelled
lines: Action, Things, Place, Framing, Text, Quality. Cached per file content and settings in <cache>\shot_log.
topic(videos) can sum up what a folder is about from its words and log(context=...) passes that along; it is off by
default (on YT-002 the 4B model's summary turned a roof vent fan into an "AC unit" and the error spread).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'shot_log'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
VIDEO = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.webm'}
LABELS = {'action': 'action', 'things': 'things', 'place': 'place', 'framing': 'framing', 'text': 'text',
          'quality': 'quality', 'best moment': 'best'}
PROMPT = """These {n} frames come in order from one stretch of raw phone footage ({clip}, {a} to {b}).{said}
Describe it for a video editor who cannot see it. Be specific and concrete and say only what you can see. When you
are not sure what an object is, describe its shape, colour and material instead of guessing a name or a purpose.
Write exactly these six lines, plain text, no markdown, each line one or two sentences:
Action: what happens from the first frame to the last (who or what does it, with which hand or tool).
Things: the people and objects in view, described specifically (parts, tools, materials, colours, labels).
Place: where this is.
Framing: wide, medium, close-up or extreme close-up; the angle; the camera movement (steady, handheld, pan, tilt, zoom, whip).
Text: readable words or numbers in the picture, exactly as written, or none.
Quality: focus, exposure, shake, or anything blocking the view."""
VERSION = 3


def _ff(name):
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe()) if name == 'ffmpeg' else str(made.ffmpeg_exe()).replace('ffmpeg', name)


def _clock(s):
    return f'{int(s // 60)}:{s % 60:04.1f}'


def _duration(path):
    import letitedit.server.core_tools as core_tools
    return float(core_tools.probe(str(path)).get('duration') or 0)


def _cuts(video, cut_above):
    r = subprocess.run([_ff('ffmpeg'), '-hide_banner', '-i', str(video), '-an', '-vf',
                        f"scale=160:-2,select='gt(scene,{float(cut_above):.3f})',showinfo", '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    return [float(x) for x in re.findall(r'pts_time:([\d.]+)', r.stderr)]


def _grey(video, t):
    r = subprocess.run([_ff('ffmpeg'), '-v', 'error', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1', '-vf',
                        'scale=64:64,format=gray', '-f', 'rawvideo', '-'], capture_output=True, creationflags=NO_WINDOW)
    a = np.frombuffer(r.stdout, np.uint8)
    return a[:4096].astype(np.float32) if a.size >= 4096 else None


def segments(video, max_s=8.0, merge_below=5.0, merge_max_s=30.0, cut_above=0.3):
    """[(from, to), ...] the stretches the log describes (see the module doc)."""
    dur = _duration(video)
    if dur <= 0:
        return []
    edges = [0.0] + [c for c in _cuts(video, cut_above) if 0.5 < c < dur - 0.5] + [dur]
    parts = []
    for a, b in zip(edges, edges[1:]):
        n = max(1, int(np.ceil((b - a) / float(max_s))))
        parts += [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n, len(edges)) for i in range(n)]
    folded = []
    for a, b, n in parts:
        if folded and b - a < 1.0:
            folded[-1] = (folded[-1][0], b, n)
        elif folded and folded[-1][1] - folded[-1][0] < 1.0:
            folded[-1] = (folded[-1][0], b, n)
        else:
            folded.append((a, b, n))
    parts = folded
    if merge_below is None or len(parts) < 2:
        return [(a, b) for a, b, _ in parts]
    with ThreadPoolExecutor(4) as ex:
        greys = list(ex.map(lambda p: _grey(video, (p[0] + p[1]) / 2), parts))
    shot_of = []
    k = 0
    for a, b, _ in parts:
        while k + 1 < len(edges) and a >= edges[k + 1] - 1e-6:
            k += 1
        shot_of.append(k)
    out = [[parts[0][0], parts[0][1], greys[0], shot_of[0]]]
    for (a, b, _), g, sh in zip(parts[1:], greys[1:], shot_of[1:]):
        cur = out[-1]
        same = (g is not None and cur[2] is not None and sh == cur[3]
                and float(np.abs(g - cur[2]).mean()) < float(merge_below) and b - cur[0] <= float(merge_max_s))
        if same:
            cur[1] = b
        else:
            out.append([a, b, g, sh])
    return [(round(a, 2), round(b, 2)) for a, b, _, _ in out]


def checked_frames(video, spans, imgs, n, width, folder):
    """The frame grabs of a footage log, checked before anything is cached: a log with no stretches (the length
    couldn't be read) or grabs that failed while the file can't be read raises UnreadableMedia; grabs that failed
    while the file reads are tried once more, and more than a tenth still missing raises too."""
    from letitedit.core import media
    if not spans:
        raise media.unreadable(video, 'the picture', 'no length could be read')
    missing = [i for i, im in enumerate(imgs) if not im]
    if not missing:
        return imgs
    media.audio_streams(video)                      # raises when the file can't be read just now
    for i in missing:
        imgs[i] = _frames(video, spans[i][0], spans[i][1], n, width, folder)
    still = [i for i in missing if not imgs[i]]
    if len(still) > max(1, len(spans) // 10):
        raise media.unreadable(video, 'the picture', f'{len(still)} of {len(spans)} stretches gave no frame')
    return imgs


def _frames(video, a, b, n, width, folder):
    paths = []
    for i in range(n):
        t = a + (b - a) * (i + 0.5) / n
        jpg = folder / f'{a:09.2f}_{i}.jpg'
        subprocess.run([_ff('ffmpeg'), '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1',
                        '-vf', f'scale={int(width)}:-2', '-q:v', '3', str(jpg)], creationflags=NO_WINDOW)
        if jpg.exists():
            paths.append(str(jpg))
    return paths


def _said(video, a, b):
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(str(video), a, b)
    except Exception:  # noqa: BLE001 - words are context, never required
        ws = None
    if not ws:
        return ''
    text = ' '.join(w['w'].strip() for w in ws)
    return f'\nWhat is said in it: "{text[:600]}"'


def parse(text):
    """The model's labelled lines as a dict (unknown lines join the previous field)."""
    out, key = {}, None
    for line in text.splitlines():
        line = line.strip().lstrip('-*• ').strip()
        if not line:
            continue
        m = re.match(r'\**([A-Za-z ]{3,12})\**\s*:\s*(.*)', line)
        if m and m.group(1).strip().lower() in LABELS:
            key = LABELS[m.group(1).strip().lower()]
            out[key] = m.group(2).strip()
        elif key:
            out[key] = (out[key] + ' ' + line).strip()
        else:
            out['action'] = (out.get('action', '') + ' ' + line).strip()
    return out


def _key(video, settings):
    import letitedit.sound.model_tools as model_tools
    h = hashlib.sha256(json.dumps({**settings, 'v': VERSION}, sort_keys=True).encode()).hexdigest()[:10]
    return f'{model_tools._fingerprint(str(video))}-{h}'


TOPIC_PROMPT = """Here is what is said across a folder of raw footage, file by file:
{said}

In one or two sentences, say what this footage is about: the project or event, the place, and the main objects and
parts involved. Use the speaker's own words for things. Plain text, no preamble."""


def topic(videos, engine=None):
    """One or two sentences on what a folder of footage is about, from what is said in it (cached transcripts only),
    written by the same model; None when nothing is said, or when the footage log engine (engine argument, else
    _engine()) is 'llm' and no topic is cached. Cached per words."""
    import letitedit.sound.model_tools as model_tools
    eng = {'engine': engine} if isinstance(engine, str) else (engine or _engine())
    said = []
    for v in videos:
        try:
            import letitedit.footage.speech as speech
            ws = speech.cached_words(str(v))
        except Exception:  # noqa: BLE001
            ws = None
        if ws:
            said.append(f'{Path(v).name}: ' + ' '.join(w['w'].strip() for w in ws))
    if not said:
        return None
    text = '\n'.join(said)
    words = text.split()
    if len(words) > 1500:
        text = ' '.join(words[:1500]) + ' ...'
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    f = CACHE / 'topics' / f'{key}.json'
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8-sig'))['topic']
    if eng.get('engine') == 'llm':
        return None
    rep = model_tools.describe([{'images': [], 'prompt': TOPIC_PROMPT.format(said=text)}], max_new_tokens=120, batch=1)
    out = rep['texts'][0].strip()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'topic': out, 'model': rep.get('model')}), encoding='utf-8')
    return out


class LlmEngine(RuntimeError):
    """The footage log engine is 'llm': this PC doesn't build the log with a local model."""


def _engine():
    try:
        import letitedit.core.hardware as hardware
        return hardware.footage_log_engine()
    except Exception as e:  # noqa: BLE001 - no reading: the local model, as before
        return {'engine': 'local', 'model': None, 'why': f'no hardware reading ({type(e).__name__})'}


def log(video, max_s=8.0, frames=3, width=448, merge_below=5.0, merge_max_s=30.0, cut_above=0.3, words=True,
        build=True, max_new_tokens=260, batch=4, context=None, engine=None):
    """The footage log of one video (see the module doc); cached. context: what the whole footage is about (one or two
    sentences, e.g. from topic()), given to the model with every stretch. engine: 'local' or 'llm' (default: the
    footage_log_engine of hardware.py / settings.json); with 'llm' a missing log is not built here (LlmEngine is
    raised): the agent writes it through llm_log.py (letitedit_log_frames / letitedit_log_write)."""
    import time
    import letitedit.sound.model_tools as model_tools
    video = Path(video)
    settings = {'max_s': max_s, 'frames': frames, 'width': width, 'merge_below': merge_below,
                'merge_max_s': merge_max_s, 'cut_above': cut_above, 'words': bool(words)}
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{_key(video, settings)}.json'
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8-sig'))
    if not build:
        return None
    eng = {'engine': engine, 'why': 'engine argument'} if isinstance(engine, str) else (engine or _engine())
    if eng['engine'] == 'llm':
        raise LlmEngine(f"the footage log engine is 'llm' ({eng.get('why')}): the log of {video.name} is written "
                        f"through letitedit_log_frames / letitedit_log_write (llm_log.py)")
    t0 = time.time()
    spans = segments(video, max_s, merge_below, merge_max_s, cut_above)
    tmp = Path(tempfile.mkdtemp(prefix='shotlog-'))
    with ThreadPoolExecutor(4) as ex:
        imgs = list(ex.map(lambda s: _frames(video, s[0], s[1], frames, width, tmp), spans))
    imgs = checked_frames(video, spans, imgs, frames, width, tmp)
    items = []
    for (a, b), im in zip(spans, imgs):
        about = f'\nWhat the whole footage is about (from what is said in it): {context}' if context else ''
        items.append({'images': im, 'prompt': PROMPT.format(
            n=len(im), clip=video.name, a=_clock(a), b=_clock(b), said=about + (_said(video, a, b) if words else ''))})
    shots, model, run_s = [], None, 0.0
    step = 24                                           # a reply every few shots, so a long clip shows progress
    for k in range(0, len(items), step):
        rep = model_tools.describe(items[k:k + step], max_new_tokens=max_new_tokens, batch=batch)
        model, run_s = rep.get('model'), run_s + rep.get('run_s', 0)
        for (a, b), text in zip(spans[k:k + step], rep['texts']):
            shots.append({'from': a, 'to': b, **parse(text), 'raw': text})
    for p in tmp.glob('*'):
        p.unlink(missing_ok=True)
    tmp.rmdir()
    entry = {'file': str(video), 'duration': round(_duration(video), 2), 'shots': shots, 'model': model,
             'settings': settings, 'context': context, 'seconds': round(time.time() - t0, 1),
             'model_s': round(run_s, 1)}
    f.write_text(json.dumps(entry, indent=1), encoding='utf-8')
    return entry


def log_folder(paths, **kw):
    """{file: entry} for every video in paths (a folder, a list of files or one file)."""
    if isinstance(paths, (str, Path)):
        p = Path(paths)
        paths = sorted(x for x in p.iterdir() if x.suffix.lower() in VIDEO) if p.is_dir() else [p]
    vids = [Path(v) for v in paths if Path(v).suffix.lower() in VIDEO]
    return {str(v): log(v, **kw) for v in vids}


def _nothing(text):
    t = text.strip().lower().rstrip('.')
    return t in ('none', 'no', 'n/a', '') or bool(re.match(r'(there (is|are) )?(no|none) .*(text|words|numbers|legible|readable|visible)', t))


def _framing(text):
    """'close-up, handheld, tilt' from the model's framing sentence."""
    t = text.lower()
    size = next((name for key, name in (('extreme close', 'extreme close-up'), ('close', 'close-up'),
                                        ('medium', 'medium'), ('wide', 'wide')) if key in t), '')
    moves = [name for key, name in (('static', 'steady'), ('steady', 'steady'), ('handheld', 'handheld'),
                                    ('pan', 'pan'), ('tilt', 'tilt'), ('zoom', 'zoom'), ('whip', 'whip')) if key in t]
    return ', '.join(dict.fromkeys(([size] if size else []) + moves))


def _first(text, words=25):
    s = re.split(r'(?<=[.!?])\s', text.strip(), maxsplit=1)[0]
    w = s.split()
    return ' '.join(w[:words]) + (' ...' if len(w) > words else '')


def brief(entry):
    """One short line per shot: '0:00.0-0:08.0  [close-up, handheld] <first sentence of the action>  Text: ...'."""
    out = []
    for s in entry.get('shots', []):
        frame = _framing(s.get('framing', ''))
        line = f"{_clock(s['from'])}-{_clock(s['to'])}  " + (f'[{frame}] ' if frame else '') + _first(
            s.get('action', '') or s.get('raw', ''))
        txt = s.get('text', '')
        if txt and not _nothing(txt):
            line += f'  Text: {_first(txt, 20)}'
        out.append(line)
    return out


def lines(entry, detail=False):
    """Text lines of a log entry: brief(entry) without detail; with detail, per shot '0:00.0-0:08.0  <action>' then
    the framing, things, place, text seen, quality and best moment, one per line."""
    if not detail:
        return brief(entry)
    out = []
    for s in entry.get('shots', []):
        out.append(f"{_clock(s['from'])}-{_clock(s['to'])}  {s.get('action', '') or s.get('raw', '')}")
        for k, label in (('framing', 'Framing'), ('things', 'Things'), ('place', 'Place'), ('text', 'Text'),
                         ('quality', 'Quality')):
            if s.get(k) and not (k == 'text' and _nothing(s[k])):
                out.append(f'    {label}: {s[k]}')
    return out


def text_file(entries, out):
    """Every entry's detailed log in one text file (a heading per video); returns its path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for e in entries:
        parts.append(f"== {Path(e['file']).name}  ({_clock(e['duration'])}, {len(e['shots'])} entries)")
        parts += lines(e, detail=True)
        parts.append('')
    out.write_text('\n'.join(parts), encoding='utf-8')
    return str(out)


if __name__ == '__main__':
    import sys
    e = log(sys.argv[1], **(json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}))
    print('\n'.join(lines(e, detail=True)))
    print({k: e[k] for k in ('model', 'seconds', 'model_s', 'settings')})
