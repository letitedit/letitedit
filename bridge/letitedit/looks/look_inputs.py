"""What the person gave a Look up front (T64): the answers New video's one screen of boxes collected.

New video writes the answers as a record (format letitedit-inputs/1) when the person goes ahead, and keeps a copy beside
the video once the video exists: `<video>.letitedit/inputs.json`. The person's own files are only read (the record holds
their paths, never copies and never moves). Every round of revision, the review and any new chat read the same record.

Roles (the manifest's `asks[].role`; a Look may add its own):
    about       what the video is about: the brief's content, in the person's words
    show        files that may appear on screen (photos, documents, clips)
    style       pictures to LOOK AT for the feel the person wants; they never appear in the video
    voiceover   the person's own spoken track; empty means a voice on this PC reads the script the AI writes
    product     the thing being shown (a picture, a screen recording)
    person      who the video is about or for (a picture, a name)

    python look_inputs.py facts <ffprobe> <cache.json> <path>...   JSON lines for New video's file tiles
    python look_inputs.py read <project>                           the record beside a video
    python look_inputs.py attach <record> <project>                keep a record beside a video
    python look_inputs.py check <project> [<export.mp4>]           the review's measured part
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows, so nothing takes the keyboard focus)
except ImportError:  # pragma: no cover
    pass

FORMAT = 'letitedit-inputs/1'
NAME = 'inputs.json'
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = _paths.CODE_ROOT
VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf'}
AUDIO = {'.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg'}
PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp'}
CANT_CATCH = ('This check compares each "style" picture, whole or fitted into the frame, with a frame every few '
              'seconds of the export. It does not see a style picture that was cropped, tinted, shrunk into a corner, '
              'drawn over, redrawn by hand or in code, or that shows for less than the gap between samples; it does '
              'not judge whether the video copies the style\'s feel too closely, only whether the picture itself '
              'appears. A "show" file counts as used when the project or its scenes name it (by path, or by file name '
              'and size for a copy); it does not see whether the file is on screen long enough to read.')


# ---------------------------------------------------------------- the record beside a video
def side_folder(project) -> Path:
    p = Path(project)
    return p.with_name(p.stem + '.letitedit')


def record_path(project) -> Path:
    return side_folder(project) / NAME


def read(project) -> dict | None:
    """The record beside a video, or None (looking never makes a folder)."""
    p = record_path(project)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('format') == FORMAT else None


def _write(project, data: dict) -> Path:
    p = record_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, p)
    return p


def attach(record, project, unused: dict | None = None) -> dict:
    """Keep a New video record beside `project`. An existing record is kept as it is (its `unused` reasons are merged);
    `unused` is {file path: why it was left out}. Returns the record now beside the video."""
    data = json.loads(Path(record).read_text(encoding='utf-8-sig')) if record else (read(project) or {})
    if data.get('format') != FORMAT:
        raise ValueError(f'{record}: not a {FORMAT} record')
    now = read(project)
    if now:
        data = now
    reasons = dict(data.get('unused') or {})
    reasons.update({str(k): str(v) for k, v in (unused or {}).items()})
    if reasons:
        data['unused'] = reasons
    _write(project, data)
    return data


def no_footage(project) -> bool:
    """Is this video from a Look that draws everything? Then there is no footage to log, and nothing to cut out of it."""
    data = read(project) if project else None
    if not data or not data.get('look'):
        return False
    import letitedit.looks.looks as looks
    card = looks.offered(data['look'])
    return bool(card) and card.get('works_with') == 'no-footage'


def has_voiceover(data: dict | None) -> bool:
    return any(b.get('role') == 'voiceover' and b.get('files') for b in (data or {}).get('inputs') or [])


def about_text(data: dict | None) -> str:
    """What the person wrote about the video, in their words."""
    return ' '.join(str(b.get('text') or '') for b in (data or {}).get('inputs') or [] if b.get('role') == 'about').strip()


def by_role(data: dict | None) -> dict:
    """{role: {'text': [..], 'files': [paths]}} for the boxes that were filled."""
    out: dict = {}
    for box in (data or {}).get('inputs') or []:
        role = box.get('role') or box.get('id')
        slot = out.setdefault(role, {'text': [], 'files': []})
        if box.get('kind') == 'text':
            if str(box.get('text') or '').strip():
                slot['text'].append(str(box['text']).strip())
        else:
            slot['files'] += [f['path'] if isinstance(f, dict) else str(f) for f in box.get('files') or []]
    return {k: v for k, v in out.items() if v['text'] or v['files']}


def missing_required(data: dict | None) -> list:
    return [b.get('label') or b.get('id') for b in (data or {}).get('inputs') or []
            if b.get('need') == 'required' and not (str(b.get('text') or '').strip() or b.get('files'))]


def describe(data: dict | None) -> str:
    """The record in plain lines, for the AI and the critic."""
    if not data:
        return ''
    lines = [f"Look: {data.get('look') or 'none'}"]
    for box in data.get('inputs') or []:
        role, label = box.get('role'), box.get('label')
        if box.get('kind') == 'text':
            t = str(box.get('text') or '').strip()
            lines.append(f"- {role} ({label}): {t if t else 'not given'}")
        else:
            files = [f['path'] if isinstance(f, dict) else str(f) for f in box.get('files') or []]
            lines.append(f"- {role} ({label}): " + ('; '.join(files) if files else 'not given'))
    return '\n'.join(lines)


# ---------------------------------------------------------------- the review's measured part
def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def _project_names(project) -> tuple[set, list]:
    """Every file the project (and its scenes) names: normalised paths, and (file name, size) pairs for copies."""
    paths, texts = set(), []
    project = Path(project)
    try:
        text = project.read_text(encoding='utf-8', errors='replace')
    except OSError:
        text = ''
    texts.append(text)
    here = project.parent
    for m in re.finditer(r'<property name="(?:resource|shotcut:resource|\w*[Ff]ile\w*|\w*path\w*)"[^>]*>([^<]+)<', text):
        raw = m.group(1).strip().replace('&amp;', '&')
        if not raw:
            continue
        paths.add(_norm(raw))
        paths.add(_norm(here / raw))
    scenes = side_folder(project) / 'scenes'
    if scenes.is_dir():
        for f in scenes.rglob('*'):
            if f.suffix.lower() in ('.html', '.js', '.json', '.css', '.txt') and f.stat().st_size < 4_000_000:
                texts.append(f.read_text(encoding='utf-8', errors='replace'))
    return paths, texts


def _named(path, names: set, texts: list) -> bool:
    if _norm(path) in names:
        return True
    base = Path(path).name
    size = _size(path)
    for n in names:                       # a copy the project made of the file: same name and size
        if os.path.basename(n) == os.path.normcase(base) and size is not None and _size(n) == size:
            return True
    needle = base.casefold()
    return any(needle in t.casefold() for t in texts[1:])     # a scene's own code names the file


def _dhash(gray: bytes) -> int:
    """64-bit difference hash of a 9x8 greyscale picture."""
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if gray[y * 9 + x] > gray[y * 9 + x + 1] else 0)
    return bits


def _style_hashes(path, size) -> list:
    """The style picture's hashes as the export would show it: stretched to the frame, and fitted inside it."""
    from PIL import Image
    w, h = size
    img = Image.open(path).convert('L')
    out = [_dhash(img.resize((9, 8)).tobytes())]
    scale = min(w / img.width, h / img.height)
    fitted = Image.new('L', (w, h), 0)
    fitted.paste(img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale)))),
                 ((w - round(img.width * scale)) // 2, (h - round(img.height * scale)) // 2))
    out.append(_dhash(fitted.resize((9, 8)).tobytes()))
    return out


def _export_hashes(video, gap_s) -> list:
    """(time, dhash) for a frame every gap_s seconds of the export, with its size."""
    ffmpeg = ROOT / 'app' / 'ffmpeg.exe'
    probe = ROOT / 'app' / 'ffprobe.exe'
    r = subprocess.run([str(probe), '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                        '-of', 'csv=p=0', str(video)], capture_output=True, text=True, timeout=60)
    w, h = (int(x) for x in r.stdout.strip().split(',')[:2])
    r = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(video), '-an', '-vf',
                        f'fps=1/{gap_s},scale=9:8:flags=area,format=gray', '-f', 'rawvideo', '-'],
                       capture_output=True, timeout=900)
    raw = r.stdout
    frames = [(i * gap_s, _dhash(raw[i * 72:(i + 1) * 72])) for i in range(len(raw) // 72)]
    return [((w, h)), frames]


def check(project, video=None, gap_s=None) -> dict:
    """The measured part of the review for a video made from a Look's boxes. Nothing here judges taste."""
    data = read(project) if project else None
    out = {'has_inputs': bool(data), 'look': (data or {}).get('look'), 'roles': {}, 'style_in_project': [],
           'style_in_export': [], 'show_used': [], 'show_unused': [], 'missing_required': [], 'cant_catch': CANT_CATCH}
    if not data:
        return out
    out['roles'] = {r: v['files'] for r, v in by_role(data).items() if v['files']}
    out['missing_required'] = missing_required(data)
    names, texts = _project_names(project) if Path(project).is_file() else (set(), [''])
    reasons = data.get('unused') or {}
    for role, files in out['roles'].items():
        for f in files:
            used = _named(f, names, texts)
            if role == 'style' and used:
                out['style_in_project'].append(f)
            elif role == 'show':
                (out['show_used'] if used else out['show_unused']).append(
                    f if used else {'path': f, 'reason': reasons.get(f) or reasons.get(Path(f).name) or ''})
    style = [f for f in out['roles'].get('style', []) if Path(f).suffix.lower() in PHOTO and Path(f).is_file()]
    if video and style and Path(video).is_file():
        try:
            dur = float(subprocess.run([str(ROOT / 'app' / 'ffprobe.exe'), '-v', 'error', '-show_entries',
                                        'format=duration', '-of', 'default=nw=1:nk=1', str(video)],
                                       capture_output=True, text=True, timeout=60).stdout.strip())
            gap = gap_s or max(1, round(dur / 240))
            size, frames = _export_hashes(video, gap)
            for f in style:
                try:
                    wanted = _style_hashes(f, size)
                except Exception:  # noqa: BLE001 - a picture that can't be read can't be compared
                    continue
                best = min(((bin(a ^ b).count('1'), t) for t, a in frames for b in wanted), default=None)
                if best and best[0] <= 6:
                    out['style_in_export'].append({'path': f, 'at_s': best[1], 'distance': best[0]})
            out['sampled_every_s'] = gap
        except Exception as exc:  # noqa: BLE001
            out['export_check_error'] = f'{type(exc).__name__}: {exc}'
    return out


def findings(result: dict, make) -> list:
    """The review's findings from check(): `make(source, severity, what, at, evidence, fix)` builds one."""
    out = []
    for f in result.get('style_in_project', []):
        out.append(make('look inputs', 'major', f'a "style" picture is in the project: {Path(f).name}', None, f,
                        'Style pictures are for looking at only; take it out of the video.'))
    for s in result.get('style_in_export', []):
        out.append(make('look inputs', 'major', f'a "style" picture shows in the export: {Path(s["path"]).name}',
                        s['at_s'], f'matches the frame at {s["at_s"]:g} s (difference {s["distance"]} of 64)',
                        'Style pictures never appear in the video; take it out.'))
    for u in result.get('show_unused', []):
        if u['reason']:
            continue                     # listed in the coverage, with the AI's reason
        out.append(make('look inputs', 'minor', f'a "show" file was not used and no reason was given: {Path(u["path"]).name}',
                        None, u['path'], 'Use it, or record why not with letitedit_looks(action="inputs", project=project, inputs=inputs, unused={path: reason}).'))
    return out


def coverage_detail(result: dict) -> str:
    """One plain sentence for the review's coverage list."""
    bits = []
    for role, files in result.get('roles', {}).items():
        bits.append(f'{len(files)} {role}')
    unused = result.get('show_unused', [])
    s = 'given: ' + (', '.join(bits) or 'text only')
    if unused:
        s += '; "show" files not used: ' + '; '.join(f'{Path(u["path"]).name} ({u["reason"] or "no reason given"})' for u in unused)
    return s


# ---------------------------------------------------------------- New video's file tiles
def facts(ffprobe, cache_file, paths):
    """JSON lines for New video: each file at once (name, kind), then its length and a small picture as they come, so a
    file that is slow to open (a Google Drive file not yet downloaded) never holds the others up."""
    import hashlib
    try:
        cache = json.loads(Path(cache_file).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        cache = {}
    changed = False
    ffmpeg = str(Path(ffprobe).with_name('ffmpeg.exe'))
    thumbs = Path(cache_file).with_suffix('.thumbnails')
    paths = list(paths)
    for path in paths:
        ext = Path(path).suffix.lower()
        kind = 'video' if ext in VIDEO else 'audio' if ext in AUDIO else 'photo' if ext in PHOTO else 'other'
        print(json.dumps({'file': {'name': Path(path).name, 'path': path, 'kind': kind}}, ensure_ascii=False), flush=True)
    for path in paths:
        ext = Path(path).suffix.lower()
        try:
            st = os.stat(path)
        except OSError:
            print(json.dumps({'missing': path}, ensure_ascii=False), flush=True)
            continue
        key = f'{path}|{st.st_size}|{st.st_mtime_ns}'
        if ext in VIDEO | AUDIO:
            try:
                if key not in cache:
                    r = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of',
                                        'default=noprint_wrappers=1:nokey=1', path], capture_output=True, text=True,
                                       timeout=20)
                    cache[key] = round(float(r.stdout.strip()), 1) if r.returncode == 0 else None
                    changed = True
                if cache[key] is not None:
                    print(json.dumps({'length': {'path': path, 'duration_s': cache[key]}}, ensure_ascii=False), flush=True)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        if ext in VIDEO | PHOTO:
            try:
                thumb = thumbs / (hashlib.sha256(key.encode('utf-8')).hexdigest() + '.png')
                if not thumb.is_file():
                    thumbs.mkdir(parents=True, exist_ok=True)
                    tmp = thumb.with_suffix('.part.png')
                    r = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', path, '-an', '-frames:v', '1',
                                        '-vf', 'scale=96:66:force_original_aspect_ratio=decrease', '-y', str(tmp)],
                                       capture_output=True, timeout=30)
                    if r.returncode == 0 and tmp.is_file():
                        os.replace(tmp, thumb)
                    else:
                        tmp.unlink(missing_ok=True)
                if thumb.is_file():
                    print(json.dumps({'thumbnail': {'path': path, 'image': str(thumb)}}, ensure_ascii=False), flush=True)
            except (OSError, subprocess.TimeoutExpired):
                pass
    if changed:
        try:
            tmp = Path(cache_file).with_suffix('.tmp')
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, cache_file)
        except OSError:
            pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    if a[:1] == ['facts'] and len(a) >= 3:
        facts(a[1], a[2], a[3:])
    elif a[:1] == ['read'] and len(a) > 1:
        print(json.dumps(read(a[1]), ensure_ascii=False, indent=1))
    elif a[:1] == ['attach'] and len(a) > 2:
        print(json.dumps(attach(a[1], a[2]), ensure_ascii=False, indent=1))
    elif a[:1] == ['check'] and len(a) > 1:
        print(json.dumps(check(a[1], a[2] if len(a) > 2 else None), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
