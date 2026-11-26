"""The core tool set: what Claude needs to make and finish a video by script (see GUIDE.md).

footage in -> project -> edit script (read / apply / undo) -> checks -> export, plus fonts, Looks, graphics and
the music/SFX library. Every tool works on saved files; when the project is open in letitedit, edits land
in that window as undoable steps and reads see its unsaved state.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import io
import json
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFPROBE, FFMPEG = APP / 'ffprobe.exe', APP / 'ffmpeg.exe'
VIDEO = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp'}
IMAGE = {'.png', '.jpg', '.jpeg', '.heic', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
AUDIO = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _identity(path):
    st = os.stat(path)
    return hashlib.sha256(f'{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()[:16]


def probe(path):
    """Duration, size, fps, rotation, audio, creation time of a media file (cached)."""
    folder = CACHE / 'probe3'
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f'{_identity(path)}.json'
    if f.exists():
        info = json.loads(f.read_text(encoding='utf-8-sig'))
        # a media file cached with no length was a failed read (an older letitedit cached those): read it again
        if info.get('duration') or info.get('kind') not in ('video', 'audio'):
            return info
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)],
                       capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    data = json.loads(r.stdout or '{}')
    readable = r.returncode == 0 and bool(data.get('format'))      # a failed read is answered but never cached
    v = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    a = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
    fmt = data.get('format', {})
    info = {'file': str(path), 'name': Path(path).name, 'kind': _kind(path),
            'duration': round(float(fmt.get('duration') or 0), 3), 'audio': a is not None,
            'created': _recorded(fmt.get('tags') or {}, (v or {}).get('tags') or {}),
            'camera': _camera(fmt.get('tags') or {}, (v or {}).get('tags') or {})}
    if v:
        w, h = int(v.get('width') or 0), int(v.get('height') or 0)
        rot = 0
        for sd in v.get('side_data_list') or []:
            if 'rotation' in sd:
                rot = int(float(sd['rotation']))
        rot = rot or int(float((v.get('tags') or {}).get('rotate', 0) or 0))
        if abs(rot) % 180 == 90:
            w, h = h, w
        num, den = (v.get('avg_frame_rate') or v.get('r_frame_rate') or '0/1').split('/')
        fps = float(num) / float(den) if float(den or 0) else 0.0
        info.update(width=w, height=h, fps=round(fps, 3), codec=v.get('codec_name'),
                    orientation='vertical' if h > w else 'horizontal' if w > h else 'square')
        if info['kind'] == 'image':
            info['duration'] = 0
    if readable:
        f.write_text(json.dumps(info), encoding='utf-8')
    return info


def _kind(path):
    ext = Path(path).suffix.lower()
    return 'video' if ext in VIDEO else 'image' if ext in IMAGE else 'audio' if ext in AUDIO else 'other'


def _thumb(path, t, width=360):
    from PIL import Image
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-ss', f'{max(0.0, t):.3f}', '-i', str(path), '-frames:v', '1',
                        '-vf', f'scale={width}:-2', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                       capture_output=True, creationflags=NO_WINDOW)
    try:
        return Image.open(io.BytesIO(r.stdout)).convert('RGB')
    except Exception:  # noqa: BLE001
        return None


def _strip(path, duration, n=3):
    """n frames of a video side by side (start, middle, end), one image."""
    from PIL import Image
    shots = [_thumb(path, duration * k, width=240) for k in ((0.1, 0.5, 0.9) if n == 3 else
                                                            [(i + 0.5) / n for i in range(n)])]
    shots = [s for s in shots if s is not None]
    if not shots:
        return None
    h = min(s.height for s in shots)
    shots = [s.resize((round(s.width * h / s.height), h)) for s in shots]
    out = Image.new('RGB', (sum(s.width for s in shots) + 4 * (len(shots) - 1), h), (22, 22, 26))
    x = 0
    for s in shots:
        out.paste(s, (x, 0))
        x += s.width + 4
    return out


def _sheet(tiles, labels, cols=5, tile_w=300):
    from PIL import Image, ImageDraw
    th = int(tile_w * 9 / 16)
    rows = max(1, (len(tiles) + cols - 1) // cols)
    sheet = Image.new('RGB', (cols * tile_w, rows * (th + 22)), (22, 22, 26))
    d = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(zip(tiles, labels)):
        x, y = (i % cols) * tile_w, (i // cols) * (th + 22)
        if tile is not None:
            tile.thumbnail((tile_w - 4, th))
            sheet.paste(tile, (x + (tile_w - tile.width) // 2, y + 22 + (th - tile.height) // 2))
        d.text((x + 4, y + 4), label[:44], fill=(230, 230, 230))
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=84)
    return buf.getvalue()


def _fmt(s):
    return f'{int(s // 60)}:{s % 60:04.1f}'


# Folder mode analyses the sound and picture of uncached videos by itself up to this much new footage (seconds);
# beyond it the reply says how long analyze=True takes. Measured on this PC (16 threads): 53 min of 1080p60 iPhone
# footage (34 clips, 7.5 GB) in 133-138 s uncached, i.e. ~24x real time; so 75 min is about 3 minutes.
AUTO_ANALYZE_S = float(os.environ.get('LETITEDIT_AUTO_ANALYZE_S', 4500))
ANALYZE_RATE = 24.0          # seconds of footage analysed per second of wall time, uncached (measured)


def _collect(path):
    """(files, folders, subfolders) for a folder, a list of paths, or one path. Folders are not searched below."""
    paths = path if isinstance(path, (list, tuple)) else [path]
    files, folders, subdirs = [], [], []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            folders.append(p)
            for x in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                if x.is_dir():
                    subdirs.append(x)
                elif x.is_file():
                    files.append(x)
        elif p.exists():
            files.append(p)
        else:
            raise FileNotFoundError(f'Not found: {p}')
    return files, folders, subdirs


def _recorded(*tag_sets):
    """When the clip was recorded: Apple's creationdate (local time with its offset, kept through copies) before the
    container's creation_time (UTC; on copied phone files often the copy time)."""
    for key in ('com.apple.quicktime.creationdate', 'creation_time'):
        for tags in tag_sets:
            for k, val in tags.items():
                if k.lower() == key and str(val).strip():
                    return str(val).split(';')[0].strip()
    return None


def _camera(*tag_sets):
    """'Apple iPhone 11' from the file's make/model tags (Apple, Android, generic), or None."""
    def tag(*keys):
        for key in keys:
            for tags in tag_sets:
                for k, val in tags.items():
                    if k.lower() == key and str(val).strip():
                        return str(val).split(';')[0].strip()
        return ''
    make = tag('com.apple.quicktime.make', 'com.android.manufacturer', 'make')
    model = tag('com.apple.quicktime.model', 'com.android.model', 'model')
    if model.lower().startswith(make.lower()):
        make = ''
    return ' '.join(x for x in (make, model) if x) or None


def rec_start(info):
    """The recording start as an aware datetime (the camera's own clock and offset; UTC when the file gives none),
    or None."""
    import re
    from datetime import datetime, timedelta, timezone
    c = (info or {}).get('created')
    m = re.match(r'(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?$', str(c or '').strip())
    if not m:
        return None
    day, hms, frac, tz = m.groups()
    dt = datetime.fromisoformat(f'{day}T{hms}') + timedelta(seconds=float(frac or 0))
    if tz and tz != 'Z':
        tz = tz.replace(':', '')
        off = timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5])) * (1 if tz[0] == '+' else -1)
        return dt.replace(tzinfo=timezone(off))
    return dt.replace(tzinfo=timezone.utc)


def rec_text(start, end=None):
    """'2026-09-22 16:14:05-16:16:20 (UTC-7)' (the end's date too when it falls on another day)."""
    off = start.utcoffset()
    mins = round(off.total_seconds() / 60) if off is not None else 0
    zone = 'UTC' if mins == 0 else f"UTC{'+' if mins > 0 else '-'}{abs(mins) // 60}" + (f':{abs(mins) % 60:02d}' if mins % 60 else '')
    text = start.strftime('%Y-%m-%d %H:%M:%S')
    if end is not None:
        text += '-' + end.strftime('%H:%M:%S' if end.date() == start.date() else '%Y-%m-%d %H:%M:%S')
    return f'{text} UTC' if zone == 'UTC' else f'{text} ({zone})'


def _created(info):
    """When a clip was recorded, start-end to the second: '2026-09-22 16:14:05-16:16:20 (UTC-7)'."""
    from datetime import timedelta
    start = rec_start(info)
    if start is None:
        return info.get('created') or ''
    return rec_text(start, start + timedelta(seconds=float(info.get('duration') or 0)))


def same_time(infos, min_s=1.0):
    """{key: [(other key, seconds recorded together)]} for clips whose recording times overlap (several cameras, or
    a clip and a copy of it), from each camera's own clock."""
    from datetime import timedelta
    spans = {}
    for key, info in infos.items():
        start = rec_start(info)
        if start is not None and info.get('duration'):
            spans[key] = (start, start + timedelta(seconds=float(info['duration'])))
    out = {}
    keys = sorted(spans, key=lambda k: spans[k][0])
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if spans[b][0] >= spans[a][1]:
                break
            both = (min(spans[a][1], spans[b][1]) - max(spans[a][0], spans[b][0])).total_seconds()
            if both >= min_s:
                out.setdefault(a, []).append((b, both))
                out.setdefault(b, []).append((a, both))
    return out


def add_recorded(script):
    """Give every video clip on the timeline whose file has a recording time a `recorded` field: the moment that
    shot was filmed, start-end ('2026-09-22 16:15:02-16:15:05 (UTC-7)'), from the clip's in/out points."""
    from datetime import timedelta
    for t in script.get('tracks', []):
        for it in t.get('items', []):
            if 'clip' not in it or 'in' not in it or 'out' not in it:
                continue
            try:
                info = probe(it['clip'])
            except Exception:  # noqa: BLE001 - unreadable file: no recording time
                continue
            start = rec_start(info) if info.get('width') else None
            if start is None:
                continue
            a, b = sorted((float(it['in']), float(it['out'])))
            it['recorded'] = rec_text(start + timedelta(seconds=a), start + timedelta(seconds=b))
    return script


def _record_days(infos):
    """'recorded on 2 days: 2026-09-22 (24 videos), 2026-10-01 (10 videos)' from the clips' recording dates."""
    days = {}
    for info in infos:
        c = _created(info)
        if c[:4].isdigit():
            days[c[:10]] = days.get(c[:10], 0) + 1
    if not days:
        return ''
    bits = ', '.join(f'{d} ({n} video{"s" if n > 1 else ""})' for d, n in sorted(days.items()))
    return f'recorded on {len(days)} day{"s" if len(days) > 1 else ""}: {bits}'


def _fps(v):
    v = float(v or 0)
    return f'{round(v)}' if abs(v - round(v)) < 0.1 else f'{v:.2f}'


import contextvars  # noqa: E402

_SHOW_SEEN = contextvars.ContextVar('show_seen', default=True)
_SEEN_MAX = contextvars.ContextVar('seen_max', default=None)       # entries per reply; None: the defaults below
SEEN_MAX_FOLDER, SEEN_MAX_ONE = 250, 50
SEEN_CHARS_FOLDER = 30000   # characters of footage-log lines in one folder reply (keeps the reply under ~25k tokens)


_FACTS = contextvars.ContextVar('facts', default=None)   # letitedit_footage facts=False leaves the fact log out
SEG_CHARS_FOLDER = 14000   # characters of segment-map lines in a folder reply
FACT_CHARS_ONE = 22000     # characters of fact-log lines (segments + stretches) in a one-video reply


def _fact_map(files):
    """(segment map or None, {file: fact entry}) for the videos and photos among files that have a fact log
    (factlog.py): the map the index job made when it is cached, else one made now without the vision model."""
    if _FACTS.get() is False:
        return None, {}
    try:
        import letitedit.footage.factlog as factlog
        entries = {}
        for f in files:
            if _kind(f) in ('video', 'image') or Path(f).suffix.lower() in factlog.PHOTO:
                e = factlog.facts(f, build=False)
                if e:
                    entries[Path(f)] = e
        if not entries:
            return None, {}
        fs = list(entries)
        m = factlog.segment_map(fs, build=False, cached_only=True) or factlog.segment_map(fs, build=False,
                                                                                            use_model=False)
        return m, entries
    except Exception:  # noqa: BLE001 - the fact log is extra; never a reason to fail the overview
        return None, {}


def _budget(lines, chars):
    """(lines, None) when they fit in chars, else (an evenly spread share of them, (shown, total))."""
    total = sum(len(x) + 3 for x in lines)
    if total <= chars or not lines:
        return lines, None
    k = max(1, int(chars / (total / len(lines))))
    idx = _spread(len(lines), k)
    return [lines[i] for i in idx], (len(idx), len(lines))


def _fact_lines(fmap, entries, one=None):
    """Text lines of the fact log for a reply: the legend, the segment map (budgeted), for one video its stretches
    (neighbours with the same facts joined; budgeted), and the full text file."""
    import letitedit.footage.factlog as factlog
    st = fmap['settings']
    first = next(iter(entries.values()))
    nv = sum(1 for e in entries.values() if e.get('kind') != 'photo')
    npht = len(entries) - nv
    budget = SEG_CHARS_FOLDER
    shown, cut = _budget(factlog.segment_lines(fmap), budget)
    if cut:
        shown, cut = _budget(factlog.segment_lines(fmap, words=False), budget)
    max_s = next((e['settings'].get('max_s') for e in entries.values() if e.get('kind') != 'photo'), None)
    frames = (f"the clearest of up to {st['clear_n']} of its stretches as picked by the vision model"
              if fmap.get('frames_by_model') else 'its middle stretch (no vision model)')
    out = [f"Fact log (local vision model {first.get('model')}; closed-set facts per stretch"
           + (f' of up to {max_s:g} s' if max_s else '') + f") for {nv} video{'s' if nv != 1 else ''}"
           + (f" and {npht} photo{'s' if npht != 1 else ''}" if npht else '')
           + (f"; none yet for: {', '.join(Path(m).name for m in fmap['missing'][:20])}" if fmap.get('missing') else ''),
           '  ' + factlog.legend(st['min_accuracy']),
           f"  Segments: {fmap['stretch_count']} stretches -> {len(fmap['segments'])} segments, in recording order. "
           f"A new segment where the recording has a gap over {st['gap_s']:g} s, GPS moves over {st['place_km']:g} km, "
           f"the facts {', '.join(fmap['split_keys'])} change (each the most common answer over {st['smooth_n']} "
           f"neighbouring stretches), or the words said {st['topic_window_s']:g} s either side share under "
           f"{st['topic_below']:g} overlap; under {st['min_segment_s']:g} s joins a neighbour, over "
           f"{st['max_segment_s']:g} s is cut into equal parts (factlog.SEGMENT_DEFAULTS; the index job's 'segments' "
           f"input sets them). A fact listed for a segment holds for {st['hold_share']:.0%}+ of its time ('a/b' when "
           f"none does). Frame of each segment: {frames}; files in {fmap.get('folder')}"]
    out.append('  ' + (f'{cut[0]} of {cut[1]} segments shown, evenly spread:' if cut else 'Segments:'))
    out += ['    ' + x for x in shown]
    if one is not None and one in entries:
        e = entries[one]
        rows = factlog.compact_stretch_lines(e, st['min_accuracy'])
        rows, cut2 = _budget(rows, max(4000, FACT_CHARS_ONE - sum(len(x) for x in out)))
        out.append(f"  Stretches ({len(e['stretches'])}; neighbours with the same facts joined"
                   + (f'; {cut2[0]} of {cut2[1]} lines shown, evenly spread' if cut2 else '') + '):')
        out += ['    ' + x for x in rows]
    out.append(f"  Every stretch with its facts: {fmap['text_file']}")
    return out


def _spread(n, k):
    """k indices of range(n), evenly spread (all of them when k >= n)."""
    if k >= n:
        return list(range(n))
    return sorted({round(i * (n - 1) / max(1, k - 1)) for i in range(k)}) if k > 1 else [0]


def _seen_share(seens, cap, chars):
    """({file: kept entry indices}, per-video limit or None) for a folder reply: all entries when they fit in `cap`
    entries and `chars` characters of footage-log lines; else the largest per-video limit c that fits, each video
    keeping min(its entries, c), evenly spread."""
    import letitedit.footage.shot_log as shot_log
    sizes = {f: [len(x) + 5 for x in shot_log.brief(e)] for f, e in seens.items()}

    def keep_for(c):
        return {f: _spread(len(e['shots']), min(len(e['shots']), c)) for f, e in seens.items()}

    def fits(k):
        return (sum(len(v) for v in k.values()) <= cap and
                sum(sizes[f][i] for f, v in k.items() for i in v) <= chars)
    longest = max((len(e['shots']) for e in seens.values()), default=0)
    if fits(keep_for(longest)):
        return keep_for(longest), None
    lo, hi = 1, longest
    while lo < hi:                                   # largest per-video limit that fits
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if fits(keep_for(mid)) else (lo, mid - 1)
    return keep_for(lo), lo


def _seen(path):
    """The cached footage log of a video (shot_log.py), or None when it hasn't been written (or log=False)."""
    if not _SHOW_SEEN.get():
        return None
    try:
        import letitedit.footage.shot_log as shot_log
        return shot_log.log(path, build=False)
    except Exception:  # noqa: BLE001 - the log is extra; never a reason to fail the overview
        return None


def _safe_name(name):
    return re.sub(r'[^A-Za-z0-9._ -]+', '_', str(name))[:60] or 'footage'


def _notes(path, limit):
    """Footage notes as short lines, the same text over several spans given once ('0:00-0:45, 1:25-1:48 text')."""
    import letitedit.footage.footage_notes as footage_notes
    groups = {}
    for n in footage_notes.get(str(path)):
        key = (n['text'], tuple(n['tags']))
        groups.setdefault(key, []).append([n['in'], n['out']])
    out = []
    for (text, tags), spans in groups.items():
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 1.0:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        where = ', '.join(_fmt(a) if a == b else f'{_fmt(a)}-{_fmt(b)}' for a, b in merged)
        out.append(f"{where} {text}" + (f" [{', '.join(tags)}]" if tags else ''))
    return out[:limit]


def _video_line(name, info):
    bits = [name, _fmt(info['duration'])]
    if info.get('width'):
        bits.append(f"{info['width']}x{info['height']} {info.get('orientation', '')} {_fps(info.get('fps'))}fps")
    if info.get('created'):
        bits.append(f"recorded {_created(info)}")
    pl = _place_line(info.get('file'))
    if pl:
        bits.append(pl)
    if not info.get('audio'):
        bits.append('no sound')
    return '  '.join(bits)


def _place(path):
    """geo.place(path) (GPS from the file's metadata and the nearest place, cached per file content) or None."""
    if not path:
        return None
    try:
        import letitedit.footage.geo as geo
        return geo.place(path)
    except Exception:  # noqa: BLE001 - the place is extra; never a reason to fail the overview
        return None


def _place_line(path):
    got = _place(path)
    if not got:
        return None
    return f"place: {got['text']}" if got.get('text') else f"gps: {got['lat']:.4f}, {got['lon']:.4f}"


def _place_data(path):
    got = _place(path)
    if not got:
        return None
    out = {k: got[k] for k in ('lat', 'lon', 'alt_m') if got.get(k) is not None}
    if got.get('place'):
        out.update(name=got['place']['name'], region=got['place']['region'],
                   country=got['place']['country_code'], km=got['place']['km'])
    return out


def _frame_times(dur, times, every_s):
    if times:
        return [round(float(t), 2) for t in times]
    if every_s:
        return [round(t, 2) for t in _frange(0.5, max(0.5, dur - 0.2), max(0.1, float(every_s)))]
    n = 12 if dur >= 12 else max(1, int(dur))
    return [round((i + 0.5) * dur / n, 2) for i in range(n)]


def footage(path, speech=True, transcribe=False, sheet=True, offset=0, limit=60, times=None, every_s=None,
            analyze=None, sheet_frames=None, picture_limits=None):
    """(sheet_jpeg_or_None, report) for a folder of footage, a list of files, or one file. report['text'] is the
    compact reading of it (what the tool returns); the other keys hold the same facts as data."""
    files, folders, subdirs = _collect(path)
    if not folders and len(files) == 1:
        return _one_file(files[0], speech, transcribe, sheet, times, every_s, picture_limits)
    return _many(files, folders, subdirs, speech, transcribe, sheet, offset, limit, analyze, sheet_frames,
                 picture_limits)


def footage_sheets(files, every_s=None, count=None, times=None, row_h=None, page_w=1900, page_h=1800, per_row=None):
    """Frames of each video: `count` spread evenly, one every `every_s` seconds, or at `times` (seconds; one clip),
    as many as asked, row_h px tall (default 320 for upright video, 170 for landscape), wrapped into lines of as many
    as fit page_w (or per_row), each labelled with its time, under the clip's name. Clips flow onto pages page_h tall
    (a clip taller than a page gets pages of its own). Returns [jpeg bytes per page]."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw, ImageFont
    import letitedit.footage.perception as pc
    vids = [f for f in files if pc.kind(f) == 'video']
    if not vids:
        return []
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', 14)
        small = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 11)
    except OSError:
        font = small = ImageFont.load_default()

    def frame_times(dur):
        if times:
            return [min(max(0.0, float(t)), max(0.0, dur - 0.05)) for t in times]
        if every_s:
            step = max(0.05, float(every_s))
            n = int(dur // step) + 1
            return [min(dur - 0.05, i * step) for i in range(n)]
        n = max(1, int(count or 3))
        return [dur * (i + 0.5) / n for i in range(n)]

    def grab(f, ts, rh):
        """[PIL image per time] via ffmpeg, 24 seeks per call."""
        out = []
        for k in range(0, len(ts), 24):
            part = ts[k:k + 24]
            cmd = [str(FFMPEG), '-hide_banner', '-v', 'error']
            for t in part:
                cmd += ['-ss', f'{max(0.0, t):.3f}', '-i', str(f)]
            graph = ';'.join(f'[{i}:v]scale=-2:{rh},setsar=1[f{i}]' for i in range(len(part)))
            graph += ';' + ''.join(f'[f{i}]' for i in range(len(part))) + (
                f'hstack={len(part)}[v]' if len(part) > 1 else 'null[v]')
            r = subprocess.run(cmd + ['-filter_complex', graph, '-map', '[v]', '-frames:v', '1', '-f', 'image2pipe',
                                      '-vcodec', 'png', '-'], capture_output=True, creationflags=NO_WINDOW)
            if r.returncode != 0 or not r.stdout:
                out += [None] * len(part)
                continue
            strip = Image.open(io.BytesIO(r.stdout)).convert('RGB')
            fw = strip.width // len(part)
            out += [strip.crop((i * fw, 0, (i + 1) * fw, strip.height)) for i in range(len(part))]
        return out

    def block(f):
        info = probe(f)
        dur = info['duration']
        w, h = info.get('width') or 16, info.get('height') or 9
        rh = int(row_h) if row_h else (320 if h > w else 170)
        ts = frame_times(dur)
        ims = grab(f, ts, rh)
        fw = max(1, round(rh * w / h))
        cols = max(1, int(per_row) if per_row else int((page_w + 2) // (fw + 2)))
        lines = [list(range(k, min(k + cols, len(ts)))) for k in range(0, len(ts), cols)]
        return f, dur, ts, ims, fw, rh, lines

    with ThreadPoolExecutor(max_workers=4) as pool:
        blocks = list(pool.map(block, vids))
    head = 22
    pieces = []          # (clip name text, [(ts, ims) per line], fw, rh)
    for f, dur, ts, ims, fw, rh, lines in blocks:
        title = f'{Path(f).name}  ({_fmt_dur(dur)})'
        per_page = max(1, (page_h - head) // (rh + 2))
        for k in range(0, len(lines), per_page):
            part = lines[k:k + per_page]
            pieces.append((title + ('' if k == 0 else '  (cont.)'), [[(ts[i], ims[i]) for i in ln] for ln in part], fw, rh))
    pages, cur, used = [], [], 0
    for pc_ in pieces:
        hgt = head + len(pc_[1]) * (pc_[3] + 2)
        if cur and used + hgt > page_h:
            pages.append(cur)
            cur, used = [], 0
        cur.append(pc_)
        used += hgt
    if cur:
        pages.append(cur)
    out = []
    for group in pages:
        width = max(max(len(ln) for ln in lines_) * (fw + 2) for _, lines_, fw, _ in group)
        height = sum(head + len(lines_) * (rh + 2) for _, lines_, _, rh in group)
        sheet = Image.new('RGB', (max(width, 600), height), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        y = 0
        for title, lines_, fw, rh in group:
            d.text((4, y + 3), title, fill=(255, 220, 0), font=font)
            y += head
            for ln in lines_:
                for i, (t, im) in enumerate(ln):
                    x = i * (fw + 2)
                    if im is not None:
                        sheet.paste(im.resize((fw, rh)), (x, y))
                    label = f'{int(t // 60)}:{t % 60:04.1f}'
                    d.rectangle((x, y, x + 7 * len(label) + 6, y + 14), fill=(0, 0, 0))
                    d.text((x + 3, y + 1), label, fill=(240, 240, 240), font=small)
                y += rh + 2
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=80)
        out.append(buf.getvalue())
    return out


def _fmt_dur(sec):
    return f'{int(sec // 60)}:{sec % 60:04.1f}'


def _one_file(f, speech, transcribe, sheet, times, every_s, picture_limits=None):
    import letitedit.sound.music as music
    import letitedit.footage.perception as pc
    k = pc.kind(f)
    if k == 'image':
        info = pc.photo(f)
        img = pc.photo_image(f, 1024) if sheet else None
        buf = None
        if img is not None:
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
        lines = [f'{f.name}  {_photo_text(info, f)}', str(f)]
        extra = {'place': _place_data(f)} if _place_data(f) else {}
        return (buf.getvalue() if buf else None), {**info, **extra, 'file': str(f), 'kind': 'image',
                                                   'text': '\n'.join(lines)}
    if k in ('text', 'other', 'system'):
        size = f.stat().st_size
        lines = [f'{f.name}  ({pc.size_text(size)})', str(f)]
        if k == 'text':
            content, total = pc.text(f, limit=20000)
            cut = f' (first {len(content)} of {total} characters)' if total > len(content) else ''
            lines.append(f'--- content{cut}:')
            lines.append(content.rstrip())
        else:
            lines.append('not a media or text file')
        return None, {'file': str(f), 'kind': k, 'bytes': size, 'text': '\n'.join(lines)}
    info = probe(f)
    report = {**info}
    if _place_data(f):
        report['place'] = _place_data(f)
    lines = [_video_line(f.name, info) if k == 'video' else f"{f.name}  {_fmt(info['duration'])}  (audio)", str(f)]
    ex = pc._pool()
    fut_snd = ex.submit(pc._safe, pc.sounds, f) if info.get('audio') else None
    fut_pic = ex.submit(pc._safe, pc.picture, f) if k == 'video' else None
    fut_mus = ex.submit(pc._safe, pc.music, f) if k == 'audio' else None
    img = None
    if k == 'video':
        ts = _frame_times(info['duration'], times, every_s)
        report['frames_at'] = ts
        if sheet:
            tiles = list(ex.map(lambda t: _thumb(f, t, 480), ts))
            img = _sheet(tiles, [f'{_fmt(t)}' for t in ts], cols=4, tile_w=400)
            lines.append('Frames on the sheet at ' + ', '.join(_fmt(t) for t in ts) +
                         ' (other moments: times=[...] or every_s=)')
    talk = []
    if speech and info.get('audio'):
        talk = music.voice_times(str(f))
        report['speech'] = [f'{_fmt(a)}-{_fmt(b)}' for a, b in talk]
        lines.append(f"Talking (voice detection, {sum(b - a for a, b in talk):.1f} s): " +
                     (', '.join(report['speech']) if talk else 'none'))
    mus = fut_mus.result() if fut_mus else None
    music_like = bool(mus and mus.get('bpm') and mus.get('pulse', 0) >= 0.35 and
                      sum(b - a for a, b in talk) < 0.5 * max(1.0, info['duration']))
    if mus and 'error' not in mus:
        report['music'] = {k2: mus.get(k2) for k2 in ('bpm', 'beats', 'pulse', 'sections')}
        if music_like:
            lines.append('Music:')
            lines += ['  ' + x for x in pc.music_lines(mus)]
            report['music'].update(beat_times=mus['beat_times'], downbeats=mus['downbeats'])
        else:
            lines.append(f'Music: {pc.music_brief(mus)}' + ('' if mus.get('pulse', 0) >= 0.35 else
                                                            ' (no clear beat: probably not music)'))
    snd = fut_snd.result() if fut_snd else None
    if snd and not music_like:
        if 'error' in snd:
            lines.append(f"Sounds: could not analyse ({snd['error']})")
        else:
            report['sounds'] = pc.sound_lines(snd)
            lines.append(f'Sounds besides talking: {pc.sound_header(snd)} (dB = A-weighted level re full scale; '
                         '"over room" = above the room tone):')
            lines += ['  ' + x for x in report['sounds']] or ['  nothing but talking and room tone']
    pic = fut_pic.result() if fut_pic else None
    if pic:
        if 'error' in pic:
            lines.append(f"Picture: could not analyse ({pic['error']})")
        else:
            report['picture'] = pc.picture_lines(pc.with_limits(pic, picture_limits))
            lines.append('Picture (camera motion per second, sharpness, exposure, scene changes; '
                         'x/y = where things move, 0-1 from left/top; ' + pc.limits_text(picture_limits) + '):')
            lines += ['  ' + x for x in report['picture']]
    fmap, fentries = _fact_map([f]) if k == 'video' else (None, {})
    if fmap:
        report['facts'] = _fact_lines(fmap, fentries, one=Path(f))
        lines += report['facts']
    seen = _seen(f)
    if seen and fmap:
        import letitedit.footage.shot_log as shot_log
        full = shot_log.text_file([seen], shot_log.CACHE / 'text' / f"{_safe_name(f.stem)}-{len(seen['shots'])}.txt")
        lines.append(f"Older footage log (descriptions by {seen.get('model')}, {len(seen['shots'])} entries): {full}")
    elif seen:
        import letitedit.footage.shot_log as shot_log
        n = len(seen['shots'])
        cap = _SEEN_MAX.get() or SEEN_MAX_ONE
        keep = _spread(n, cap)
        report['seen'] = shot_log.lines({'shots': [seen['shots'][i] for i in keep]}, detail=True)
        full = shot_log.text_file([seen], shot_log.CACHE / 'text' / f'{_safe_name(f.stem)}-{n}.txt')
        lines.append(f"Seen (footage log by {seen.get('model')}, one entry per shot or stretch of up to "
                     f"{seen['settings']['max_s']:g} s; " + (f'all {n} entries' if len(keep) == n else
                     f'{len(keep)} of {n} entries, evenly spread (seen_max={cap})') + f'; all of them: {full}):')
        lines += ['  ' + x for x in report['seen']]
    notes = _notes(f, limit=60)
    if notes:
        report['notes'] = notes
        lines.append('Notes:')
        lines += ['  ' + n for n in notes]
    if transcribe and info.get('audio'):
        import letitedit.footage.speech as sp
        report['words'] = _lines(sp.words(str(f)))
        lines.append('Words (s):')
        lines += ['  ' + w for w in report['words']]
        language = sp.english_only_line(f)
        if language:
            report['speech_language'] = language
            lines.append(language)
    report['text'] = '\n'.join(lines)
    return img, report


def _photo_text(info, path=None):
    bits = []
    if info.get('width'):
        bits.append(f"{info['width']}x{info['height']} {info['orientation']}")
    if info.get('taken'):
        bits.append(f"taken {info['taken']}")
    elif info.get('modified'):
        bits.append(f"file date {info['modified']}")
    if info.get('camera'):
        bits.append(info['camera'])
    pl = _place_line(path)
    if pl:
        bits.append(pl)
    import letitedit.footage.perception as pc
    bits.append(pc.size_text(info['bytes']))
    if info.get('preview') is False:
        bits.append(f"no preview ({info.get('error', 'cannot decode')})")
    return '  '.join(bits)


def _many(files, folders, subdirs, speech, transcribe, sheet, offset, limit, analyze, sheet_frames=None,
          picture_limits=None):
    import letitedit.sound.music as music
    import letitedit.footage.perception as pc
    total = len(files)
    kinds = {f: pc.kind(f) for f in files}
    count = {}
    for k in kinds.values():
        count[k] = count.get(k, 0) + 1
    page = files[offset:offset + limit]
    infos = {f: probe(f) for f in page if kinds[f] in ('video', 'audio')}
    videos = [f for f in page if kinds[f] == 'video']
    audios = [f for f in page if kinds[f] == 'audio']
    durations = {str(f): infos[f]['duration'] for f in videos}
    ex = pc._pool()
    from concurrent.futures import ThreadPoolExecutor
    sheet_pool = ThreadPoolExecutor(max_workers=4)
    clip_sheets = {f: sheet_pool.submit(pc._safe, clip_sheet_file, f, sheet_frames) for f in videos}
    sheet_pool.shutdown(wait=False)

    # sound / picture analysis: cached results always; new ones when asked or when there is little to do
    todo = pc.uncached_seconds(videos, durations)
    run = analyze if analyze is not None else todo <= AUTO_ANALYZE_S
    t0 = time.time()
    if run and videos:
        analysis = pc.analyze_many(videos, durations)
    else:
        analysis = {str(f): {'picture': pc.picture(f) if pc.is_cached('motion', f) else None,
                             'sounds': pc.sounds(f) if pc.is_cached('sounds', f) else None} for f in videos}
    analysed_s = time.time() - t0
    music_f = {f: ex.submit(pc._safe, pc.music, f) for f in audios}
    if speech:      # voice detection for the rest, in parallel
        list(ex.map(lambda f: pc._safe(music.voice_times, str(f)),
                    [f for f in videos + audios if infos[f].get('audio')]))

    head = []
    where = folders[0] if len(folders) == 1 and all(f.parent == folders[0] for f in files) else None
    if where:
        head.append(str(where))
    vid_s = sum(infos[f]['duration'] for f in videos)
    order = [('video', 'video', 'videos'), ('image', 'photo', 'photos'), ('audio', 'audio', 'audio'),
             ('text', 'text', 'text'), ('other', 'other', 'other'), ('system', 'system', 'system')]
    summary = ', '.join(f'{count[k]} {one if count[k] == 1 else many}' for k, one, many in order if count.get(k))
    head.append(f"{total} files: {summary}" + (f"; showing {offset + 1}-{offset + len(page)} (offset/limit for more)"
                                               if len(page) < total else '') +
                (f"; videos here {_fmt(vid_s)} total" if videos else ''))
    days = _record_days([infos[f] for f in videos])
    if days:
        head.append(days[0].upper() + days[1:])
    cams = {}
    for f in videos:
        if infos[f].get('camera'):
            cams[infos[f]['camera']] = cams.get(infos[f]['camera'], 0) + 1
    if cams:
        head.append(f"Camera{'s' if len(cams) > 1 else ''}: " + ', '.join(
            f'{c} ({n} video{"s" if n > 1 else ""})' for c, n in sorted(cams.items(), key=lambda x: -x[1])))
    together = same_time({f: infos[f] for f in videos})
    if together:
        head.append(f'{len(together)} videos were recorded at the same time as another one (by the cameras\' clocks; '
                    'see "same time as")')
    if subdirs:
        head.append('Subfolders (not listed; pass one as path): ' + ', '.join(
            f'{d.name} ({sum(1 for _ in d.iterdir())} items)' for d in subdirs[:20]))
    if videos:
        done = sum(1 for f in videos if analysis[str(f)].get('picture') or analysis[str(f)].get('sounds'))
        if done:
            head.append(pc.limits_text(picture_limits)[0].upper() + pc.limits_text(picture_limits)[1:])
        if run:
            head.append(f'Sound/picture analysis: all {len(videos)} video{"s" if len(videos) > 1 else ""}'
                        + (f' ({analysed_s:.0f} s, now cached)' if todo else ' (cached)'))
        else:
            head.append(f'Sound/picture analysis: {done} of {len(videos)} videos (cached ones). analyze=True analyses '
                        f'the rest ({todo / 60:.0f} min of footage, about {max(1, todo / ANALYZE_RATE / 60):.0f} min '
                        'the first time, then cached); or look at one file: letitedit_footage(<file>).')
    if sheet and any(kinds[f] in ('video', 'image') for f in page):
        head.append('Contact sheet: three frames (near the start, middle and end) per video and each photo, in the '
                    'order listed.')

    rows, tiles, labels, logged = [], [], [], []
    sections = {k: [] for k in ('text', 'video', 'image', 'audio', 'other')}
    thumbs = {}
    # the footage log: every entry when they fit (seen_max entries and SEEN_CHARS_FOLDER characters), else every video
    # up to the same number of entries (shorter videos complete, longer ones evenly spread)
    seens = {f: _seen(f) for f in page if kinds[f] == 'video'}
    seens = {f: e for f, e in seens.items() if e and e.get('shots')}
    seen_cap = _SEEN_MAX.get() or SEEN_MAX_FOLDER
    seen_total = sum(len(e['shots']) for e in seens.values())
    fmap, fentries = _fact_map(page)
    old_logs = {f: e for f, e in seens.items() if Path(f) in fentries}
    seens = {f: e for f, e in seens.items() if Path(f) not in fentries}
    seen_total = sum(len(e['shots']) for e in seens.values())
    seen_keep, seen_per = _seen_share(seens, seen_cap, SEEN_CHARS_FOLDER)
    if sheet:
        for f in page:
            if kinds[f] == 'video':
                thumbs[f] = ex.submit(_strip, f, infos[f]['duration'])
            elif kinds[f] == 'image':
                thumbs[f] = ex.submit(pc.photo_image, f)
    for f in page:
        k = kinds[f]
        name = f.name if where else str(f)
        row = {'file': str(f), 'kind': k}
        if k in ('video', 'audio'):
            info = infos[f]
            row.update({x: info.get(x) for x in ('duration', 'width', 'height', 'fps', 'orientation', 'audio',
                                                  'created') if info.get(x) is not None})
            lines = [_video_line(name, info) if k == 'video' else f'{name}  {_fmt(info["duration"])}']
            if k == 'video' and _place_data(f):
                row['place'] = _place_data(f)
            if k == 'video' and len(cams) > 1 and info.get('camera'):
                lines[0] += f"  {info['camera']}"
            if k == 'video' and f in together:
                row['same_time_as'] = [{'file': o.name, 'seconds': round(s, 1)} for o, s in together[f]]
                lines[0] += '  same time as ' + ', '.join(f'{o.name} ({_fmt(s)} together)' for o, s in together[f])
            extra = []
            if speech and info.get('audio'):
                spans = music.voice_times(str(f))
                row['speech_s'] = round(sum(b - a for a, b in spans), 1)
                extra.append(f"talk {row['speech_s']:g}s")
            if k == 'audio':
                mus = music_f[f].result()
                if mus and mus.get('bpm') and mus.get('pulse', 0) >= 0.35:
                    row['bpm'], row['beats'] = mus['bpm'], mus['beats']
                    extra.append(pc.music_brief(mus))
            if extra:
                lines[0] += '  ' + ', '.join(extra)
            if k == 'video':
                a = analysis.get(str(f), {})
                snd, pic = a.get('sounds'), a.get('picture')
                if snd:
                    row['sounds'] = pc.sound_summary(snd) if 'error' not in snd else f"not readable ({snd['error']})"
                if pic:
                    row['picture'] = (pc.picture_summary(pc.with_limits(pic, picture_limits)) if 'error' not in pic else
                                      f"not readable ({pic['error']})")
                if snd or pic:
                    lines.append('  ' + ' | '.join(x for x in (
                        f"sounds: {row['sounds']}" if 'sounds' in row else '',
                        f"picture: {row['picture']}" if 'picture' in row else '') if x))
                sheet = clip_sheets[f].result() if f in clip_sheets else None
                if isinstance(sheet, str):
                    row['frames'] = sheet
                    lines.append(f"  frames: {sheet} ({sheet_frames or clip_sheet_n(info.get('duration'))} spread "
                                 f"through the clip)")
                seen = seens.get(f)
                if seen:
                    import letitedit.footage.shot_log as shot_log
                    keep = seen_keep[f]
                    row['seen'] = shot_log.brief({'shots': [seen['shots'][i] for i in keep]})
                    n = len(seen['shots'])
                    lines.append('  seen:' if len(keep) == n else f'  seen ({len(keep)} of {n} entries, evenly spread):')
                    lines += ['    ' + x for x in row['seen']]
                    logged.append(seen)
            notes = _notes(f, limit=6)
            if notes:
                row['notes'] = notes
                lines.append('  notes: ' + ' / '.join(notes))
            if transcribe and info.get('audio'):
                import letitedit.footage.speech as sp
                ws = sp.words(str(f))
                row['says'] = ' '.join(w['w'] for w in ws[:25]) + (' ...' if len(ws) > 25 else '')
                lines.append(f"  says: {row['says']}")
            sections[k].append('\n'.join(lines))
        elif k == 'image':
            info = pc.photo(f)
            row.update({x: info[x] for x in ('width', 'height', 'orientation', 'taken', 'camera') if x in info})
            if _place_data(f):
                row['place'] = _place_data(f)
            sections['image'].append(f'{name}  {_photo_text(info, f)}')
        elif k == 'text':
            content, n = pc.text(f)
            size = f.stat().st_size
            row.update(bytes=size, chars=n, content=content)
            cut = f', first {len(content)} of {n} characters' if n > len(content) else ''
            body = '\n'.join('  | ' + ln for ln in content.rstrip().splitlines()) or '  | (empty)'
            sections['text'].append(f'{name} ({pc.size_text(size)}{cut}):\n{body}')
        else:
            size = f.stat().st_size
            row['bytes'] = size
            sections['other'].append(f"{name}  {pc.size_text(size)}{'  (system file)' if k == 'system' else ''}")
        rows.append(row)
        if f in thumbs:
            tiles.append(thumbs[f].result())
            dur = infos[f]['duration'] if f in infos else 0
            labels.append(f"{f.name} {_fmt(dur) if dur else ''}")
    talking = [Path(r['file']) for r in rows if (r.get('speech_s') or 0) > 0.5]
    queued = transcribe_in_background(talking)
    sheets_in_background([p for p in talking if p not in queued])
    if talking:
        import letitedit.footage.speech as sp
        language = sp.english_only_line(talking) or (sp._english_line() if queued and sp.will_read_english_only() else '')
        if language:
            head.append(language)
    if queued:
        mins = sum(infos[f]['duration'] for f in queued if f in infos) / 60
        head.append(f"Transcribing {len(queued)} file{'s' if len(queued) > 1 else ''} with talking in the background "
                    f"({mins:.0f} min of footage); letitedit_words answers at once for files already done.")
    if logged:
        import letitedit.footage.shot_log as shot_log
        nv = sum(1 for f in page if kinds[f] == 'video')
        full = shot_log.text_file(logged, shot_log.CACHE / 'text' / f'{_safe_name(page[0].parent.name)}-{len(logged)}.txt')
        shown = sum(len(k) for k in seen_keep.values())
        head.append(f"Footage log ({logged[0].get('model')}, a local vision model): `seen:` under {len(logged)} of {nv} "
                    f"videos, one line per shot or stretch of up to {logged[0]['settings']['max_s']:g} s"
                    + (f' (all {seen_total} entries)' if shown == seen_total else
                       f' ({shown} of {seen_total} entries: each video up to {seen_per}, shorter videos complete, longer '
                       f'ones evenly spread; seen_max={seen_cap}, {SEEN_CHARS_FOLDER} characters)')
                    + f". Every entry in full (framing, things, place, text in the picture, quality): {full}; one "
                    f"video's: letitedit_footage(<file>).")
    out = head
    if fmap:
        report_facts = _fact_lines(fmap, fentries)
        if old_logs:
            import letitedit.footage.shot_log as shot_log
            full = shot_log.text_file(list(old_logs.values()), shot_log.CACHE / 'text' /
                                      f'{_safe_name(page[0].parent.name)}-old-{len(old_logs)}.txt')
            report_facts.append(f'  Older footage log of these videos (descriptions): {full}')
        out += ['', 'FACT LOG AND SEGMENT MAP'] + report_facts
    titles = {'text': 'TEXT FILES (content inlined)', 'video': 'VIDEOS', 'image': 'PHOTOS', 'audio': 'AUDIO',
              'other': 'OTHER FILES'}
    for k in ('text', 'video', 'image', 'audio', 'other'):
        if sections[k]:
            out += ['', titles[k]] + sections[k]
    report = {'total': total, 'shown': len(rows), 'offset': offset, 'files': rows,
              'seconds': round(sum(r.get('duration') or 0 for r in rows), 1), 'text': '\n'.join(out)}
    return (_sheet(tiles, labels, cols=4, tile_w=420) if sheet and tiles else None), report


_transcribing = set()


def transcribe_in_background(paths):
    """Start transcribing (in this process, one file at a time) the files not transcribed yet; returns those."""
    import threading
    import letitedit.footage.speech as sp
    todo = [p for p in paths if str(p) not in _transcribing and sp.cached_words(str(p), 0, 1) is None]
    if not todo:
        return []
    _transcribing.update(str(p) for p in todo)

    def run():
        for p in todo:
            try:
                sp.words(str(p))
            except Exception:  # noqa: BLE001 - no audio / unreadable: letitedit_words will report it
                pass
            finally:
                _transcribing.discard(str(p))
        sheets_in_background(todo)
    threading.Thread(target=run, daemon=True, name='background-transcription').start()
    return todo


_sheeting = set()


def sheets_in_background(paths):
    """Make the words-with-a-frame-at-each-line image of every transcribed video among paths, one at a time."""
    import threading
    import letitedit.footage.speech as sp
    todo = [p for p in paths if str(p) not in _sheeting and _kind(p) == 'video'
            and sp.cached_words(str(p), 0, 1) is not None]
    if not todo:
        return

    _sheeting.update(str(p) for p in todo)

    def run():
        for p in todo:
            try:
                word_sheet_file(p)
            except Exception:  # noqa: BLE001 - letitedit_words makes it (or reports why) when asked
                pass
            finally:
                _sheeting.discard(str(p))
    threading.Thread(target=run, daemon=True, name='background-word-sheets').start()


def _frange(a, b, step):
    t = a
    while t <= b:
        yield t
        t += step


def _lines(ws):
    lines, cur = [], []
    for w in ws:
        if cur and (w['s'] - cur[-1]['e'] > 0.6 or len(cur) >= 14):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [f"{l[0]['s']:.2f}-{l[-1]['e']:.2f} {' '.join(x['w'] for x in l)}" for l in lines]


def copy_project(source, path):
    """A new version: a copy of a project (never overwrites). Clip ids, graphics and captions carry over."""
    import shutil
    import letitedit.timeline.edit_script as es
    src = es._resolve(source)
    dest = Path(path)
    if dest.suffix.lower() != '.mlt':
        dest = dest / src.name
    import letitedit.core.long_paths as long_paths
    long_paths.check(*long_paths.project_files(dest))
    if dest.exists():
        raise FileExistsError(f'{dest} already exists; choose another name')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    import letitedit.pictures.code_scenes as code_scenes
    code_scenes.copy_scenes(src, dest)      # its markers name scenes kept beside the project: the copy needs its own
    return str(dest)


def new_project(path, like=None, width=None, height=None, fps=None):
    """Write an empty project (V1 + A1) sized like a clip (orientation, size, frame rate) or as given."""
    import letitedit.timeline.letitedit_extras as extras
    if like:
        info = probe(like)
        width = width or info.get('width') or 1920
        height = height or info.get('height') or 1080
        fps = fps or info.get('fps') or 30
        # keep exports sane: up to 4K on the long side, even sizes
        scale = min(1.0, 3840 / max(width, height))
        width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    width, height, fps = int(width or 1920), int(height or 1080), float(fps or 30)
    common = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]
    fps = min(common, key=lambda c: abs(c - fps)) if min(abs(c - fps) for c in common) < 0.6 else fps
    import letitedit.core.long_paths as long_paths
    long_paths.check(*long_paths.project_files(path))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return extras.new_project(str(path), width, height, fps, claim=False)


def show(project):
    """Open a project in letitedit for the user: reuse the window that already has it, else the window this session
    belongs to if nothing is open in it (New video runs from there), else a new window.
    Never replaces what another window has open."""
    import letitedit.app.letitedit_instances as inst
    from letitedit.app.letitedit_client import launch, ShotcutBridge
    path = str(Path(project).resolve())
    if os.environ.get('LETITEDIT_SESSION_RUNNER_RUN'):     # a run with no window (studio/session_runner.py)
        return {'project': path, 'opened': False,
                'note': 'This run has no window: letitedit opens the finished project for the person when the run '
                        'ends. Nothing was opened.'}
    rows = inst.list_instances()
    for row in rows:
        if row.get('project') and Path(row['project']).resolve() == Path(path):
            return {'instance_id': row['instance_id'], 'already_open': True, 'project': path}
    mine = inst.current()
    if any(r['instance_id'] == mine and not r.get('project') and not r.get('modified') for r in rows):
        try:
            with inst.scope(mine), ShotcutBridge(timeout=60) as bridge:
                bridge.call('open', {'path': path})
            return {'instance_id': mine, 'opened_in_this_window': True, 'project': path}
        except Exception:  # noqa: BLE001 - a dialog open in it, say: a window of its own still shows the video
            pass
    stem = re.sub('[^a-z0-9]+', '-', Path(path).stem.lower()).strip('-')[:20] or 'project'
    instance_id = f'show-{stem}-{uuid.uuid4().hex[:6]}'
    with inst.scope(instance_id):
        result = launch(path, quiet=True)
    return {'instance_id': instance_id, 'project': path, **result}


def _settings_file():
    import letitedit.core.hardware as hardware
    return str(hardware.SETTINGS)


def log_build(files, engine=None):
    """log=True of letitedit_footage: with the local engine, writes the footage log of the videos among files that
    have none (None returned); with the 'llm' engine (hardware.py / settings.json), builds nothing and returns a
    note naming the videos without a log and the tools that write it."""
    import letitedit.footage.shot_log as shot_log
    vids = [f for f in files if _kind(f) == 'video']
    if engine is None:
        engine = shot_log._engine()
    elif isinstance(engine, str):
        engine = {'engine': engine, 'why': 'engine argument'}
    if engine.get('engine') != 'llm':
        shot_log.log_folder(vids)
        return None
    missing = [Path(v).name for v in vids if shot_log.log(v, build=False) is None]
    note = (f"\n\nFootage log: engine 'llm' ({engine.get('why')}; settings file "
            f"{_settings_file()}): log=True builds no log on "
            f"this PC; letitedit_log_frames(file) returns a video's stretches with frame sheets and words, "
            f"letitedit_log_write(file, entries) stores the entries.")
    note += (f" Videos without a log ({len(missing)} of {len(vids)}): " + ', '.join(missing[:40]) +
             (' ...' if len(missing) > 40 else '')) if missing else f' Every video here ({len(vids)}) has a log.'
    return note


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_footage(path: str | list[str], speech: bool = True, transcribe: bool = False, sheet: bool = True,
                        offset: int = 0, limit: int = 60, times: list[float] | None = None,
                        every_s: float | None = None, analyze: bool | None = None, frames: int | None = None,
                        size: int | None = None, sheet_frames: int | None = None,
                        picture_limits: dict | None = None, log: bool | None = None,
                        seen_max: int | None = None, facts: bool | None = None) -> list:
        """See and hear source footage: what is in it besides the talking, to choose shots, sounds and music.

        path = a folder (every file in it; subfolders are only named), a list of files, or one file.
        FOLDER / LIST (text reply + contact sheet: three frames per video (start, middle, end), and every photo):
          TEXT FILES (.txt .md .srt .csv .json ..., also extension-less text): content inlined (first 4000
            characters; the reply says how much was cut).
          VIDEOS: length, size, orientation, fps, when recorded (start-end to the second by the camera's clock;
            videos recorded at the same time are named; the camera, when there is more than one), seconds of talking, notes, then
            `sounds:` loud/steady noises with their spans (e.g. 'loud grinding/whirring 0:28-0:34',
            'hum ~140 Hz 0:00-0:07'), repeated hits (hammering), counts of bangs/thuds/clicks/clanks with the
            loudest, beeps, quiet stretches; and `picture:` share of steady / some shake / pans / shaky-or-whip
            time, the longest steady stretch, dark / blown-out spans, seconds of blur, cuts, scene changes.
            `frames:` the path of an image of frames spread evenly through the video, each with its time
            (sheet_frames of them; default one every ~6 s, 6-24).
            `seen:` the footage log, when it has been written: one line per shot (or stretch of up to 8 s of a
            longer shot) of what a local vision model (Qwen3.5-4B) saw in three of its frames, given the words
            said in it: the framing and camera movement, what happens, and any text in the picture, e.g.
            '0:21.7-0:28.9  [extreme close-up, handheld, tilt] A left hand holds a white fan blade while ...'.
            The header names a text file with every entry in full (framing, things, place, text, quality); ONE
            VIDEO gives its entries in full, and its own text file. seen_max: how many entries one reply shows
            (default 250 lines for a folder, 50 full entries for one video); past that each video shows its share,
            evenly spread, and the reply says so. A model's reading of a few frames: it can misname things.
            log=True writes the log for the videos that don't have one yet (about 5 s of GPU per entry, roughly
            an hour per hour of footage; cached per file content); False leaves `seen:` out. When the
            footage log engine is 'llm' (letitedit_hardware, settings.json), log=True builds nothing and the reply
            names the videos without a log; letitedit_log_frames / letitedit_log_write write it.
          FACT LOG AND SEGMENT MAP, for the videos and photos that have a fact log (factlog.py; written by the
            index job, letitedit_jobs, or facts=True): closed-set facts per stretch read by the local vision model
            (people 0/1/2/3+, face, facing or talking to the camera, hands only, shot size, indoors/outdoors,
            day/night/low light, place type, main subject, text in the picture, moments: thumbs-up, pointing, waving,
            laughing/smiling, holding up; subject cut off, lens blocked), each with its measured accuracy (facts
            under 85% are marked ~). The segment map joins stretches into segments in recording order (splits at
            recording gaps, GPS moves, changes of the reliable facts, changes of what is said), one line each:
            'S03 IMG_0447 0:00.0 - IMG_0453 0:01.4 (3:10.0, 6 files, 41 stretches) 1 person, hands only, ...
            | thumbs-up IMG_0453 0:00.7 | text "MAX AIR" | says "first words..." | seg003.jpg' (a frame of the
            segment). Up to SEG_CHARS_FOLDER (14000) characters; the full text file (every stretch) is named. Videos
            with a fact log leave out their older `seen:` lines (the older log's text file is named).
            facts=True writes the fact log for the videos and photos that have none (about 6 s of GPU per
            stretch of up to 8 s); False leaves the fact log out; None (default) shows it where it exists.
            ('112 bpm, 352 beats (strong beat)'). OTHER FILES: name and size.
          Sound/picture analysis is cached per file content (a copy of a clip shares it). A folder with up to
          ~75 min of new footage is analysed on the first call (about 24x real time: 53 min of 1080p took
          ~2.5 min; later calls ~3 s). Above that only cached results are shown and the reply says how long
          analyze=True takes. analyze=False never analyses.
        ONE VIDEO (always analysed): its fact log when it has one (legend, its segments, its stretches with
          neighbours of the same facts joined, up to FACT_CHARS_ONE (22000) characters, segments first, and the
          full text file),
          12 frames over time (or times=[s, ...] / every_s), when people talk,
          every sound event besides talking, one per line, e.g. '0:04.2 bang (loud, -9 dB, +31 over room)',
          '0:27.8-0:33.9 loud machine-like noise, pitch wandering (grinding/whirring motor?) (-27 dB, +26 over
          room)', '0:00.0-0:06.9 steady machine-like noise, humming ~140 Hz', '0:11.9-0:16.4 repeated hits
          (hammering/knocking?): 8 hits', '0:14.0-0:17.0 loud tone ~1000 Hz, steady', '0:09.4-0:13.9 quiet'
          (dB = A-weighted level re full scale; 'over room' = above the clip's quiet floor; 'talking over it'
          when someone speaks during it); and the picture: a summary line, then spans per second labelled
          steady / slight drift / handheld, some shake / [slow] pan left|right / tilt up|down / shaky handheld /
          fast whip, e.g. '0:08-0:11 steady, action bottom-right (x 0.70, y 0.80)' where action = where things
          move in that steady shot (0-1 from left/top: use it to reframe vertical <-> horizontal); then dark /
          blown-out / blurry spans (motion blur or out of focus?), cuts and big scene changes (camera now on
          something else). Plus notes; transcribe=True adds full word timing.
        ONE AUDIO FILE: talking; for music: tempo, energy sections (intro / build / peak / breakdown / outro,
          dB vs the loudest part), every downbeat (bar start) and beat time in seconds, to cut on the music.
        ONE PHOTO: the photo and its details. ONE TEXT FILE: up to 20000 characters.
        transcribe=True in folder mode adds the first words said; letitedit_words gives every word's timing.
        Choosing the frames (folder, list or one video): frames = how many spread evenly through each video,
          every_s = one every that many seconds, times = those seconds (one video), size = frame height in px
          (default 320 for upright video, 170 for landscape). Any number: the frames wrap into lines and pages, each
          with its time. Without any of these, the default sheet above.
        picture_limits: the cutoffs behind the picture labels, any of dark_luma (40), bright_luma (215),
          bright_clipped (0.25), blur_near (0.4), blur_median (0.6); the reply says which were used."""
        files, folders, _ = _collect(path)
        many = bool(folders) or len(files) > 1
        llm_note = log_build(files[offset:offset + limit] if many else files) if log else None
        if facts:
            import letitedit.core.hardware as hardware
            import letitedit.footage.factlog as factlog
            for f in (files[offset:offset + limit] if many else files):
                if _kind(f) in ('video', 'image'):
                    try:
                        factlog.facts(f)
                    except hardware.LocalModelUnavailable as e:
                        llm_note = (llm_note or '') + factlog.unavailable_note(e.fact)
                        break
        facts_token = _FACTS.set(facts)
        token = _SHOW_SEEN.set(log is not False)
        cap_token = _SEEN_MAX.set(int(seen_max) if seen_max else None)
        try:
            if every_s or frames or size or (times and not many):
                _, report = footage(path, speech, transcribe, False, offset, limit, None if many else times,
                                    None if many else every_s, analyze, sheet_frames, picture_limits)
                vids = files[offset:offset + limit] if many else files
                pages = footage_sheets(vids, every_s=every_s, count=frames, times=None if many else times, row_h=size)
                return [Image(data=pg, format='jpeg') for pg in pages] + [report['text'] + (llm_note or '')]
            img, report = footage(path, speech, transcribe, sheet, offset, limit, times, every_s, analyze,
                                  sheet_frames, picture_limits)
            return ([Image(data=img, format='jpeg')] if img else []) + [report['text'] + (llm_note or '')]
        finally:
            _SHOW_SEEN.reset(token)
            _SEEN_MAX.reset(cap_token)
            _FACTS.reset(facts_token)

    @mcp.tool()
    def letitedit_project_new(path: str, like: str | None = None, width: int | None = None, height: int | None = None,
                            fps: float | None = None, copy_of: str | None = None) -> dict:
        """Create a project file (.mlt). Empty (tracks V1 and A1), sized like a source clip (`like`: its orientation,
        size and frame rate) or as given; or, with copy_of=<project>, a copy (another version of a video). Never overwrites. letitedit_timeline_apply
        changes it; letitedit_show opens it in letitedit."""
        if copy_of:
            return {'project': copy_project(copy_of, path), 'copied_from': str(copy_of)}
        return {'project': new_project(path, like, width, height, fps)}

    @mcp.tool()
    def letitedit_quality_gate(video: str, kind: str | None = None, target_s: float | None = None,
                             project: str | None = None, expect_text: str | None = None, out: str | None = None,
                             mode: str | None = None, driver: str | None = None, deliverable: str | None = None,
                             platforms: list[str] | str | None = None, limits: dict | None = None,
                             reference: str | None = None) -> dict:
        """Measure a rendered video against the letitedit quality gate: length vs target, size, loudness and true
        peak, cuts per minute, longest shot, the first 3 s, silences, when speech starts, audible share of the
        expected words. kind 'short'|'long' (default from shape), target_s, project (for waive: and hold: markers),
        out (folder for checks.json and report.md; default next to the video). The limits come from the kind of
        video and the format: mode story|tutorial|interview|documentary|product|travel|montage|creative [story],
        driver dialogue|narration|music|visual|sound [the mode's usual one], deliverable web|podcast|broadcast
        [web: -14 LUFS; podcast -16; broadcast -23; true peak <= -1 dBTP for all], platforms (e.g. ['tiktok'] turns
        on TikTok's 57-60 s check). Pace checks are advisory (reported, never blocking) unless limits {check: value |
        'on' | 'off'} from the brief or a reference video set the tempo. Returns the verdict, the blocking and
        advisory failures, the checks that are off for this kind of video, and every check. letitedit_review_bundle
        runs this with the brief's settings plus everything else; your final word on quality is that review, not
        your own summary."""
        import subprocess, sys as _sys
        script = _paths.CODE_ROOT / 'skills' / 'letitedit-gate' / 'scripts' / 'gate.py'
        args = [_sys.executable, str(script), str(video)]
        if isinstance(platforms, (list, tuple)):
            platforms = ','.join(str(p) for p in platforms)
        for flag, value in (('--kind', kind), ('--target-s', target_s), ('--project', project),
                            ('--expect-text', expect_text), ('--out', out), ('--mode', mode), ('--driver', driver),
                            ('--deliverable', deliverable), ('--platforms', platforms), ('--reference', reference)):
            if value is not None:
                args += [flag, str(value)]
        for check, value in (limits or {}).items():
            args += ['--limit', f'{check}={value}']
        r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        folder = Path(out) if out else Path(video).parent
        checks = folder / 'checks.json'
        if not checks.exists() or checks.stat().st_mtime < time.time() - 600:
            raise RuntimeError('the gate did not run: ' + (r.stderr or r.stdout)[-800:])
        data = json.loads(checks.read_text(encoding='utf-8-sig'))
        fails = [c for c in data['checks'] if c['state'] == 'fail']
        return {'verdict': data['verdict'], 'report': str(folder / 'report.md'), 'mode': data.get('mode'),
                'failed': [c for c in fails if c.get('severity', 'blocking') == 'blocking'],
                'advisory': [c for c in fails if c.get('severity') == 'advisory'],
                'off': [o.get('check') for o in data.get('off') or []],
                'checks': {c['check']: [c['value'], c['state']] for c in data['checks']}}

    @mcp.tool()
    def letitedit_critic(video: str, kind: str, brief: str, out: str | None = None, engine: str | None = None) -> dict:
        """A picky second opinion on a rendered video from a separate run of an AI on this PC: one other than the AI
        editing when it is available, else the same AI as a fresh session (engine: 'claude' or 'codex' to try first). It
        sees a contact sheet, the transcript, the brief (a brief.json path) and the gate's numbers, never your
        reasoning, and returns a verdict, whether it can retell the story, and ranked problems with timecodes and fixes
        (also saved as review.json in out). 'engine' and 'same_vendor' say who reviewed; when no AI could, 'error' says
        why in plain words."""
        import sys as _sys
        import letitedit.review.review_bundle as review_bundle
        script = _paths.CODE_ROOT / 'skills' / 'letitedit-review' / 'scripts' / 'critic.py'
        folder = Path(out) if out else Path(video).parent
        cmd = [_sys.executable, str(script), str(video), '--kind', kind, '--brief', str(brief), '--out', str(folder)]
        review = review_bundle.run_critic(cmd + (['--engine', engine] if engine else []), folder)
        if not review.exists():
            raise RuntimeError('The review could not finish: the reviewer stopped without an answer. Run it again.')
        return json.loads(review.read_text(encoding='utf-8-sig'))

    @mcp.tool()
    def letitedit_transcript(file: str, words: list[dict] | None = None, srt: str | None = None,
                           srt_file: str | None = None, source: str | None = None, remove: bool = False) -> dict:
        """Give a source file your own transcript (from a stronger transcriber, or corrected by hand) instead of the
        local one: words = [{w, s, e}] in source seconds, or srt / srt_file = SRT or WebVTT (cue times are shared
        across each cue's words). From then on letitedit_words, search, cuts by words, captions and every other tool
        that reads what is said use it. remove=True goes back to the local transcript. Without words/srt: which
        transcript the file uses now."""
        import letitedit.footage.speech as speech
        if remove:
            speech.attach(file)
            return {'file': file, 'transcript': 'local (yours removed)'}
        if srt_file:
            srt = Path(srt_file).read_text(encoding='utf-8-sig')
        if words is None and srt is None:
            f = speech._cached(speech._identity(str(file)))
            model = json.loads(f.read_text(encoding='utf-8-sig'))['model'] if f else None
            return {'file': file, 'transcript': model or 'not transcribed yet'}
        ws = speech.attach(file, words=words, srt=srt, source=source or ('srt' if srt else 'words'))
        return {'file': file, 'transcript': 'yours', 'words': len(ws),
                'first': ' '.join(w['w'] for w in ws[:12]), 'span_s': [ws[0]['s'], ws[-1]['e']]}

    @mcp.tool()
    def letitedit_note(file: str, at: str | float | list | None = None, text: str | None = None,
                     tags: list[str] | None = None, remove: str | None = None) -> dict:
        """Remember what happens in a source file, for later (yours or another session's): at = seconds, 'm:ss' or
        'm:ss-m:ss', text = what happens there, tags = a list of short labels. remove = delete notes
        containing that text. Without at/text: the file's notes. Notes follow the file when it is copied or moved,
        and letitedit_footage shows them. Optional: nothing requires notes."""
        import letitedit.footage.footage_notes as footage_notes
        if remove:
            return {'removed': footage_notes.remove(file, remove), 'notes': footage_notes.brief(file, limit=200)}
        if at is not None and text:
            return {'added': footage_notes.add(file, at, text, tags=tags), 'notes': footage_notes.brief(file, limit=200)}
        return {'notes': footage_notes.brief(file, limit=200)}

    @mcp.tool()
    def letitedit_show(project: str) -> dict:
        """Open a project in the letitedit editor so the user can watch and edit it with you: the window that already
        has it, else this session's own window if nothing is open in it, else a new window (never replaces another
        window's project). The editor program started any other way has no link to this session. While it is open, your edits land in
        that window as undoable steps and letitedit_timeline_read sees the user's unsaved changes. If the result has
        waiting_on_dialog, letitedit is asking the person something; tell them."""
        return show(project)

    @mcp.tool()
    def letitedit_library(kind: Literal['music', 'sfx'], query: str = '', offset: int = 0, limit: int = 40,
                        beats: bool = False, bpm_min: float | None = None, bpm_max: float | None = None,
                        min_length_s: float | None = None, max_length_s: float | None = None,
                        fetch: str | None = None, with_whistle_tones: bool = False) -> dict:
        """Search the music or sound-effect library on this PC (folders set in letitedit). query is words: files with
        the most of them come first, and partial_match says when no file has them all. Put a result on a track
        with {op: insert, track: 'Music 1', item: {clip: <path>, in: 0, out: <s>}}; {op: score} sets music levels under speech.
        Each result is one line: the file's path inside `folder`, then its length; for music, its tempo: bpm, beat
        count, beat strength (strong / clear / weak) and length, e.g. '112 bpm, 352 beats (strong beat), 3:08.0'. Tempo is measured once per song and cached; a first search
        measures for up to ~6 s and marks the rest 'measuring...' (they finish in the background: search again
        in ~20 s, or pass beats=True to wait for all, ~0.5 s per song). letitedit_footage(<song>) gives that song's
        beat and downbeat times and its energy sections (intro / build / peak / breakdown / outro).
        Songs with a catalogue (library.csv) also show genre, mood, artist and licence on their line; query matches
        those words too. bpm_min / bpm_max / min_length_s / max_length_s keep only songs whose catalogue tempo and length
        are in range (a catalogue tempo can be half or double the felt one: the measured tempo on the line is the
        beat finder's). Music also searches the library that came with the install, when the person's own folder is another
        folder: a line's path is then a full path, not inside `folder`.
        Songs that hold a pure, sustained, howl- or whistle-like tone (measured once per song, kept in tonal.json) are left
        out of music results; with_whistle_tones=True lists them too (their line says how much), and whistle_tones_hidden
        counts the ones left out.
        With an active supporter key, music also lists the on-demand songs under `on_demand` ({total, files, note}), with the same words, ranges, offset and limit: a line is
        'ondemand:<id>  |  catalogue tempo, length  |  genre; mood  |  artist  |  licence  |  where it is'. They aren't on this PC until used:
        the fit tools (song=) take ondemand:<id> as it is, and fetch='ondemand:<id>' gives the path to put on a track and where it came from. It
        comes down once and stays. With no internet, on_demand's note says so and the rest of the search is unchanged."""
        if fetch:
            import letitedit.sound.media_server as media_server
            try:
                return media_server.fetch_song(fetch)
            except media_server.Unavailable as ex:
                return {'available': False, 'ref': fetch, 'note': str(ex)}
        return _library_lines(library(kind, query, offset, limit, beats, bpm_min=bpm_min, bpm_max=bpm_max,
                                      min_length_s=min_length_s, max_length_s=max_length_s,
                                      with_whistle_tones=with_whistle_tones))


def _library_lines(result):
    """The library search as one line per file: its path inside `folder`, then length (and tempo for music)."""
    out = {k: v for k, v in result.items() if k not in ('items',)}
    if out.get('folder'):              # forward slashes: folder + '/' + a line's path is the file, in any language
        out['folder'] = str(out['folder']).replace(chr(92), '/')
    lines = []
    for it in result.get('items') or []:
        rel = str(it.get('path') if it.get('other_folder') else (it.get('relative') or it.get('path'))).replace(chr(92), '/')
        if it.get('tempo'):
            facts = ''.join(f'  |  {v}' for v in (
                '; '.join(x for x in (it.get('genre'), it.get('mood')) if x), it.get('artist'), it.get('licence'),
                it.get('whistle_tones') and 'whistle-like tones: ' + it['whistle_tones']) if v)
            lines.append(f"{rel}  |  {it['tempo']}{facts}")
        else:
            try:
                dur = probe(it['path'])['duration']
                lines.append(f"{rel}  |  {_fmt(dur)}")
            except Exception:  # noqa: BLE001 - unreadable file: listed without a length
                lines.append(str(rel))
    out['files'] = lines
    return out


def library(kind, query='', offset=0, limit=40, beats=False, budget_s=6.0, bpm_min=None, bpm_max=None,
            min_length_s=None, max_length_s=None, with_whistle_tones=False):
    """The music / SFX library search, with tempo for music results (cached; measured within budget_s unless
    beats=True). Music also searches the library shipped with the install when the person's folder is another one."""
    import letitedit.sound.audio_library as audio_library
    import letitedit.footage.perception as pc
    result = audio_library.audio_library(kind, query, offset, limit, None, also_shipped=True, bpm_min=bpm_min,
                                         bpm_max=bpm_max, min_length_s=min_length_s, max_length_s=max_length_s,
                                         with_whistle_tones=with_whistle_tones)
    if kind == 'music':
        try:
            import letitedit.sound.media_server as media_server
            on_demand = media_server.search_songs(query, offset, limit, bpm_min, bpm_max, min_length_s, max_length_s)
            if on_demand is not None:         # None: no active supporter key, and nothing was contacted
                result['on_demand'] = on_demand
        except Exception as ex:  # noqa: BLE001 - the on-demand list must never stop a search of what's on this PC
            result['on_demand'] = {'total': 0, 'files': [], 'note': f'On-demand songs could not be listed: {type(ex).__name__}'}
    items = result.get('items') or []
    if kind != 'music' or not items:
        return result
    found = pc.library_beats([it['path'] for it in items], budget_s=None if beats else budget_s)
    pending = 0
    for it in items:
        m = found.get(it['path'])
        if m is None:
            it['tempo'] = 'measuring...'
            pending += 1
        elif 'error' in m:
            it['tempo'] = 'unknown (could not read)'
        else:
            it['tempo'] = f"{pc.music_brief(m)}, {_fmt(m['duration'])}"
            if m.get('bpm'):
                it['bpm'] = m['bpm']
    if pending:
        result['tempo_note'] = (f'{pending} songs are still being measured (cached when done): search again in '
                                f'~{max(5, pending)} s, or pass beats=True to wait for all.')
    return result


def word_lines(path, start=None, end=None, pause=0.6, max_words=14, heard=False):
    """[(start, end, text)]: what is said in a file, words grouped into lines at pauses (as letitedit_words shows);
    times are where the sound of the line's first word starts and its last word's ends (speech.sound_words)."""
    import letitedit.footage.speech as speech
    ws = speech.sound_words(str(path), start, end, heard=heard)
    lines, cur = [], []
    for w in ws:
        if cur and (w['s'] - cur[-1]['e'] > pause or len(cur) >= max_words):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [(round(l[0]['s'], 2), round(l[-1]['e'], 2), ' '.join(speech.shown_in(x, path) for x in l)) for l in lines]


def picture_tags(path, spans, limits=None):
    """For each (start, end) in a video: what the footage analysis found in the picture there, as 'dark', 'blown out',
    'blurry', 'whip' (each when it covers half the span or more); '' for nothing found, or when the file hasn't been
    analysed."""
    import letitedit.footage.perception as pc
    try:
        res = pc.picture(path) if pc.kind(path) == 'video' and pc.is_cached('motion', path) else None
        res = pc.with_limits(res, limits)
    except Exception:  # noqa: BLE001 - tags are an extra
        res = None
    if not res or res.get('none') or 'error' in res:
        return [''] * len(spans)
    kinds = [('dark', [(a, b) for a, b, *_ in res.get('dark', [])]),
             ('blown out', [(a, b) for a, b, *_ in res.get('bright', [])]),
             ('blurry', [(a, b) for a, b, *_ in res.get('blurry', [])]),
             ('whip', [(sp[0], sp[1]) for sp in res.get('spans', []) if sp[2] == 'fast whip'])]
    out = []
    for a, b in spans:
        need = 0.5 * max(b - a, 0.2)
        out.append(', '.join(name for name, runs in kinds
                             if sum(max(0.0, min(b, y) - max(a, x)) for x, y in runs) >= need - 1e-6))
    return out


CLIP_SHEET_MAX = 24


def clip_sheet_n(duration):
    """How many frames a clip's sheet has: one every ~6 s, at least 6, at most CLIP_SHEET_MAX."""
    return int(min(CLIP_SHEET_MAX, max(6, math.ceil((duration or 0) / 6))))


def clip_sheet_file(path, n=None):
    """Path of an image of frames spread evenly through a whole video, each labelled with its time (made once, then
    cached), or None for a file without a picture."""
    from PIL import Image, ImageDraw, ImageFont
    info = probe(path)
    dur = info.get('duration') or 0
    if _kind(path) != 'video' or dur <= 0:
        return None
    w, h = info.get('width') or 16, info.get('height') or 9
    th = 240 if h > w else 150
    tw = int(round(th * w / h / 2)) * 2
    n = max(1, int(n)) if n else clip_sheet_n(dur)
    key = hashlib.sha1(json.dumps([_identity(path), n, th, 1]).encode()).hexdigest()[:16]
    cache = CACHE / 'clip_sheets' / f'{key}.png'
    if cache.exists():
        return str(cache)
    ts = [dur * (i + 0.5) / n for i in range(n)]
    cmd = [str(FFMPEG), '-hide_banner', '-v', 'error']
    for t in ts:
        cmd += ['-ss', f'{max(0.0, t):.2f}', '-i', str(path)]
    graph = ';'.join(f'[{i}:v]scale={tw}:{th},setsar=1[f{i}]' for i in range(n))
    graph += ';' + ''.join(f'[f{i}]' for i in range(n)) + f'hstack={n}[v]'
    r = subprocess.run(cmd + ['-filter_complex', graph, '-map', '[v]', '-frames:v', '1', '-f', 'image2pipe',
                              '-vcodec', 'png', '-'], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        return None
    strip = Image.open(io.BytesIO(r.stdout)).convert('RGB')
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', 15)
        small = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', 13)
    except OSError:
        font = small = ImageFont.load_default()
    per_row = 8 if h > w else 6
    rows = math.ceil(n / per_row)
    gap, head = 4, 24
    img = Image.new('RGB', (min(n, per_row) * (tw + gap), head + rows * (th + gap)), (24, 24, 28))
    d = ImageDraw.Draw(img)
    rec = f"  recorded {_created(info)}" if info.get('created') else ''
    d.text((4, 4), f"{Path(path).name}  ({_fmt(dur)}){rec}", fill=(255, 220, 0), font=font)
    for i, t in enumerate(ts):
        x, y = (i % per_row) * (tw + gap), head + (i // per_row) * (th + gap)
        img.paste(strip.crop((i * tw, 0, (i + 1) * tw, th)), (x, y))
        label = _fmt(t)
        d.rectangle((x, y + th - 20, x + 8 + 8 * len(label), y + th), fill=(0, 0, 0))
        d.text((x + 4, y + th - 18), label, fill=(255, 255, 255), font=small)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f'{cache.stem}.{uuid.uuid4().hex[:6]}.tmp.png')
    img.save(tmp)
    os.replace(tmp, cache)
    return str(cache)


def _word_section_cache(path, lines):
    info = probe(path)
    w, h = info.get('width') or 16, info.get('height') or 9
    tw = 150 if h > w else 267
    key = hashlib.sha1(json.dumps([_identity(path), lines, tw, 2]).encode()).hexdigest()[:16]
    return CACHE / 'word_sheets' / f'{key}.png'


def word_sheet_file(path, lines=None):
    """Path of the image of one video's lines with a frame of the footage at each (made once, then cached), or
    None for a file without a picture or without talking."""
    if _kind(path) != 'video':
        return None
    lines = word_lines(path) if lines is None else lines
    if not lines:
        return None
    cache = _word_section_cache(path, lines)
    if not cache.exists():
        _word_section(path, lines)
    return str(cache)


def _word_section(path, lines, page_w=1800):
    """One file's part of a words sheet: a header, then a frame at the start of every line with its time and words."""
    import textwrap
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw, ImageFont
    info = probe(path)
    w, h = info.get('width') or 16, info.get('height') or 9
    tw, th = (150, 267) if h > w else (267, 150)
    cache = _word_section_cache(path, lines)
    if cache.exists():
        return Image.open(cache).convert('RGB')
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 12)
        bold = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', 15)
    except OSError:
        font = bold = ImageFont.load_default()
    times = [min(max(0.0, (info.get('duration') or 0) - 0.1), a + min(0.4, (b - a) / 2)) for a, b, _ in lines]
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(lambda t: _thumb(path, t, width=tw), times))
    gap, label_h, head_h = 6, 46, 26
    per_row = max(1, (page_w + gap) // (tw + gap))
    rows = max(1, (len(lines) + per_row - 1) // per_row)
    img = Image.new('RGB', (max(520, min(page_w, min(per_row, len(lines)) * (tw + gap))), head_h + rows * (th + label_h)),
                    (24, 24, 28))
    d = ImageDraw.Draw(img)
    rec = f"  recorded {_created(info)}" if info.get('created') else ''
    d.text((4, 5), f"{Path(path).name}  ({_fmt(info.get('duration') or 0)}){rec}", fill=(255, 220, 0), font=bold)
    for k, ((a, b, text), fr) in enumerate(zip(lines, frames)):
        x, y = (k % per_row) * (tw + gap), head_h + (k // per_row) * (th + label_h)
        if fr is not None:
            fr = fr.resize((tw, th))
            img.paste(fr, (x, y))
        wrapped = textwrap.wrap(f'{_fmt(a)} {text}', width=max(12, tw // 7))[:3]
        if len(textwrap.wrap(f'{_fmt(a)} {text}', width=max(12, tw // 7))) > 3:
            wrapped[-1] = wrapped[-1][:-3] + '...'
        d.multiline_text((x + 2, y + th + 2), '\n'.join(wrapped), fill=(235, 235, 235), font=font, spacing=1)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f'{cache.stem}.{uuid.uuid4().hex[:6]}.tmp.png')
    img.save(tmp)
    os.replace(tmp, cache)
    return img


def word_sheets(items, page_w=1800, page_h=1800):
    """[jpeg bytes per page] for [(path, lines)]: each file's lines with a frame of the footage at each line."""
    import io
    from PIL import Image
    sections = [_word_section(p, lines, page_w) for p, lines in items if lines and _kind(p) == 'video']
    pages, cur, used = [], [], 0
    for sec in sections:
        if cur and used + sec.height > page_h:
            pages.append(cur)
            cur, used = [], 0
        cur.append(sec)
        used += sec.height + 8
    if cur:
        pages.append(cur)
    out = []
    for group in pages:
        sheet = Image.new('RGB', (max(s.width for s in group), sum(s.height + 8 for s in group)), (12, 12, 14))
        y = 0
        for s in group:
            sheet.paste(s, (0, y))
            y += s.height + 8
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=80)
        out.append(buf.getvalue())
    return out
