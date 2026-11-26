"""Overlay words over the video's own text (T352): words a caller has letitedit add to each delivered file after the
export (the Studio's `overlay_text`, contract section 6), measured against the text and graphics the video draws
itself under the place each one goes. Measured facts for the review and for the Studio's check of its delivered files.

Behind a switch, on by default: settings.json `studio_overlay_facts` (the environment variable
LETITEDIT_STUDIO_OVERLAY_FACTS, 1 or 0, wins). Off, nothing here runs and nothing is written.

The overlay boxes come from the Studio, which writes them beside the project (BOXES_FILE in `<project>.letitedit`)
when it starts the job, laid out as the delivered files lay them out (delivery.overlay_layout) with no face known yet:
[{text, from, placement, platform, box: {x, y, w, h} fractions of the frame, if}]. An item with conditions (`if`)
is added only when they hold on the finished video, so the review states it and leaves it unmeasured; the Studio's
check after the export measures only the items it applied, in the boxes it drew.

What counts as the video's own text or graphics in a box (both, at a frame):
  - the project draws something there: an item on a shown video track that isn't footage or a still (a code scene,
    a graphic, a title, a word-caption block: craft_checks._source is None) whose rectangle reaches the box, with no
    opaque footage on a higher track over the whole box; or a burned-in caption whose text box reaches it;
  - and the export's frame shows drawn ink in the box: crisp edges (EDGE_STEP between neighbouring pixels at the
    project's size, which a camera's soft picture almost never has) on at least EDGE_SHARE of the box, and INK_SHARE
    of its pixels far from the box's own main colour.
The box is grown by PAD (a fraction of the frame) on each side: text that touches the overlay's panel reads as one
with it.

boxes_file(project)                     the Studio's overlay boxes beside the project, or None.
write_boxes(project, items, note)       writes them (the Studio).
platform_name, plain_where, plain_overlaps, no_paths   the words a person reads (T357): the overlay line, the platform,
                                        roughly where, from when to when; never pixels or file paths. The numbers stay
                                        in the boxes file, the finding's structured fields and the critic's facts.
measure(project, video, items)          {'spans': {key: [[t0, t1], ...]}, 'seconds': {key: s}} per measured item.
findings(project, video)                (findings, facts line, numbers) for the review bundle.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

SETTING = 'studio_overlay_facts'
ENV = 'LETITEDIT_STUDIO_OVERLAY_FACTS'
BOXES_FILE = 'overlay-boxes.json'
FACTS_FILE = 'overlay-facts.json'      # the critic's numbers beside the gate's (in the review folder)
FORMAT = 'letitedit-overlay-boxes/1'
EVERY_S = 0.25                         # one frame each quarter second
PAD = 0.01                             # the box grown by 1% of the frame on each side [HYP: touching reads as one]
EDGE_STEP = 40.0                       # grey step between horizontal neighbours that counts as a crisp edge (0-255)
# On T305's, Run 5's and Run 6's exports (T352): drawn headings in the box gave 0.005-0.03 of the box as crisp edges and
# 0.035-0.22 as ink; footage under the same box gave 0.000 edges at every frame. [HYP thresholds, set between them]
EDGE_SHARE = 0.002
INK_SHARE = 0.01
INK_STEP = 60                          # a pixel this far (largest channel difference) from the box's main colour is ink
MAJOR_S = 1.0                          # covered this long in all: major [HYP: a covered word on screen for a second
#                                        is long enough to be looked for; letitedit-captions' reading floor is 1 s]


def enabled():
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


# ---------------------------------------------------------------------------- the boxes

def _work(project):
    p = Path(str(project))
    return p.with_suffix('.letitedit')


def boxes_file(project):
    """The Studio's overlay boxes for this project ({format, frame, items, note}), or None."""
    if not project:
        return None
    path = _work(project) / BOXES_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('format') == FORMAT else None


def write_boxes(project, items, frame=(1080, 1920), note=''):
    """Write the overlay boxes beside the project (the Studio, when it starts a job with overlay words)."""
    work = _work(project)
    work.mkdir(parents=True, exist_ok=True)
    data = {'format': FORMAT, 'frame': list(frame), 'items': list(items), 'note': note}
    (work / BOXES_FILE).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return work / BOXES_FILE


def plain_box(box, frame=(1080, 1920)):
    """'x 336-648, y 158-243' in pixels of the frame."""
    w, h = frame
    return (f"x {round(box['x'] * w)}-{round((box['x'] + box['w']) * w)}, "
            f"y {round(box['y'] * h)}-{round((box['y'] + box['h']) * h)}")


def key_of(item):
    return f"{item.get('text', '')} ({item.get('platform') or 'file'})"


# ---------------------------------------------------------------------------- the words a person reads (T357)
# Channel shows the review's plain words on the person's phone: which overlay line, which platform, roughly where, from
# when to when. No pixels, no x/y, no file names or paths: those stay in the boxes file, the finding's structured
# fields and the critic's facts.

def platform_name(pid):
    """A platform's own name ('YouTube Shorts'); its id with spaces when the catalogue doesn't know it."""
    try:
        import letitedit.catalogs.platforms as platforms
        return str(platforms.load(pid)['name'])
    except Exception:  # noqa: BLE001 - an unknown platform is said by its id
        return str(pid or 'delivered').replace('_', ' ')


def plain_where(box):
    """Roughly where a box (fractions of the frame) lies: 'at the top', 'near the bottom, on the left', 'in the middle'."""
    cx, cy = box['x'] + box['w'] / 2, box['y'] + box['h'] / 2
    up_down = 'at the top' if cy < 0.33 else 'near the bottom' if cy > 0.67 else 'in the middle'
    side = 'on the left' if cx < 0.33 else 'on the right' if cx > 0.67 else ''
    return up_down + (', ' + side if side else '')


_EXT = r'(?:mlt|jsonl|json|mp4|mov|wav|mp3|png|jpe?g|md|txt|srt|ya?ml|xml)'
# a path up to the file's extension (folder and file names may hold spaces and dots), else a file name, else a bare path
_PATH = re.compile(rf"[A-Za-z]:[\\/].*?\.{_EXT}\b|(?:/[\w.\- ]+)+?\.{_EXT}\b|(?:[\w\-]+ ){{0,3}}[\w\-]+\.{_EXT}\b"
                   r"|[A-Za-z]:[\\/][^\s'\"<>|]*|(?:/[\w.\-]+){2,}", re.I)


def no_paths(text):
    """The text with any file path or file name taken out (an error message may name one)."""
    return _PATH.sub('a file', str(text))


def plain_overlaps(items, result):
    """['"@contract" on YouTube Shorts, at the top, from 0:03.0 to 0:06.5 (4.5 s)'] for each measured item (measure's
    result) whose box lies over the video's own text or graphics."""
    out = []
    for it in items:
        k = key_of(it)
        secs = (result.get('seconds') or {}).get(k) or 0
        spans = (result.get('spans') or {}).get(k) or []
        if not secs or not spans:
            continue
        when = ', '.join(f'from {_clock(a)} to {_clock(b)}' for a, b in spans[:3]) + (' and more' if len(spans) > 3 else '')
        out.append(f'"{it.get("text")}" on {platform_name(it.get("platform"))}, {plain_where(it["box"])}, '
                   f'{when} ({secs:g} s)')
    return out


# ---------------------------------------------------------------------------- what the project draws there

def _rect_at(item, t, width, height):
    """(x0, y0, x1, y1) fractions where the item draws at t seconds into it: its size_position (the key in force),
    else the whole frame. Unreadable: the whole frame."""
    for e in item.get('effects') or []:
        if not (isinstance(e, dict) and 'size_position' in e):
            continue
        value = e['size_position']
        if isinstance(value, dict):
            keys = value.get('keys') or []
            pick = None
            for k in keys:
                if float(k[0]) <= t + 1e-6 or pick is None:
                    pick = k[1]
            value = pick
        parts = str(value or '').replace('%', '').split()
        try:
            x, y, w, h = (float(q) for q in parts[:4])
        except ValueError:
            return (0.0, 0.0, 1.0, 1.0)
        if '%' in str(value):
            return (x / 100, y / 100, (x + w) / 100, (y + h) / 100)
        return (x / width, y / height, (x + w) / width, (y + h) / height)
    return (0.0, 0.0, 1.0, 1.0)


def _meets(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _holds(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]


def drawn_spans(project, box):
    """[(t0, t1)] seconds where the project draws text or graphics that reach the box (x0, y0, x1, y1 fractions):
    a drawn item with no opaque footage over the whole box above it, or a burned-in caption's text box."""
    import letitedit.review.craft_checks as craft_checks
    import letitedit.timeline.edit_script as es
    script = es.read(str(project))
    prof = script.get('profile') or {}
    fps = float(prof.get('fps') or 30)
    width, height = float(prof.get('width') or 1080), float(prof.get('height') or 1920)
    total = int(round(float(es.to_seconds(script.get('length') or 0)) * fps))
    tracks = [t for t in script.get('tracks') or [] if t.get('kind', 'video') == 'video'
              and t.get('hide') not in ('video', 'both')]
    drawn = [False] * total
    for order, t in enumerate(tracks):
        for it in t.get('items') or []:
            if 'at' not in it or 'len' not in it:
                continue
            f0 = int(round(float(es.to_seconds(it['at'])) * fps))
            f1 = min(total, f0 + int(round(float(it['len']) * fps)))
            footage = craft_checks._source(it) is not None
            for f in range(max(0, f0), f1):
                rect = _rect_at(it, (f - f0) / fps, width, height)
                if not _meets(rect, box):
                    continue
                if not footage:
                    drawn[f] = True
                elif order > 0 and drawn[f] and _holds(rect, box) and \
                        craft_checks._opaque(it, width, height, whole=False):
                    drawn[f] = False       # opaque footage over the whole box hides what is drawn under it
    try:
        import letitedit.review.checks as checks
        for s, e, cbox, _ in checks.caption_text_boxes(str(project)):
            if _meets(cbox, box):
                for f in range(max(0, int(s * fps)), min(total, int(round(e * fps)))):
                    drawn[f] = True
    except Exception:  # noqa: BLE001 - no caption boxes read: the drawn items stand
        pass
    out, f = [], 0
    while f < total:
        if not drawn[f]:
            f += 1
            continue
        g = f
        while g < total and drawn[g]:
            g += 1
        out.append((f / fps, g / fps))
        f = g
    return out


# ---------------------------------------------------------------------------- what the export shows there

def _ffmpeg():
    try:
        import letitedit.review.checks as checks
        return str(checks.FFMPEG)
    except Exception:  # noqa: BLE001
        return 'ffmpeg'


def ink_frames(video, box, size=(1080, 1920), every_s=EVERY_S):
    """[(t, ink share, crisp edge share)] of the box in the video's frames, one each every_s, at the project's size."""
    import numpy as np
    w, h = size
    x0, y0 = max(0, int(box[0] * w)), max(0, int(box[1] * h))
    cw, ch = max(2, int((box[2] - box[0]) * w)), max(2, int((box[3] - box[1]) * h))
    cw, ch = min(cw, w - x0), min(ch, h - y0)
    r = subprocess.run([_ffmpeg(), '-v', 'error', '-i', str(video), '-vf',
                        f'fps={1 / every_s:g},scale={w}:{h},crop={cw}:{ch}:{x0}:{y0}', '-f', 'rawvideo',
                        '-pix_fmt', 'rgb24', '-'], capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b'').decode('utf-8', 'replace').strip()[-300:] or 'ffmpeg failed')
    frames = np.frombuffer(r.stdout, np.uint8)
    n = frames.size // (cw * ch * 3)
    frames = frames[:n * cw * ch * 3].reshape(n, ch, cw, 3).astype(np.int16)
    out = []
    for i, fr in enumerate(frames):
        main = np.median(fr.reshape(-1, 3), axis=0)
        ink = float((np.abs(fr - main).max(axis=2) > INK_STEP).mean())
        edges = float((np.abs(np.diff(fr.mean(axis=2), axis=1)) > EDGE_STEP).mean())
        out.append((round(i * every_s, 3), ink, edges))
    return out


def padded(box):
    return (max(0.0, box['x'] - PAD), max(0.0, box['y'] - PAD), min(1.0, box['x'] + box['w'] + PAD),
            min(1.0, box['y'] + box['h'] + PAD))


def covered(video, project, box, size=(1080, 1920), every_s=EVERY_S, start=0.0, end=None):
    """[[t0, t1]] seconds where the overlay's box (grown by PAD) lies over the video's own drawn text or graphics."""
    area = padded(box)
    spans = drawn_spans(project, area)
    if not spans:
        return []
    hits = []
    for t, ink, edges in ink_frames(video, area, size, every_s):
        if end is not None and not (start - 1e-6 <= t < end):
            continue
        if ink >= INK_SHARE and edges >= EDGE_SHARE and any(a - 1e-6 <= t < b for a, b in spans):
            hits.append(t)
    out = []
    for t in hits:
        if out and t - out[-1][1] <= every_s + 1e-6:
            out[-1][1] = round(t + every_s, 3)
        else:
            out.append([t, round(t + every_s, 3)])
    return out


def measure(project, video, items, size=(1080, 1920)):
    """{'spans': {key: [[t0, t1], ...]}, 'seconds': {key: s}} for each item (its box, its platform)."""
    spans, seconds = {}, {}
    for it in items:
        if not it.get('box'):
            continue
        k = key_of(it)
        spans[k] = covered(video, project, it['box'], size, start=float(it.get('start') or 0),
                           end=it.get('end') or None)
        seconds[k] = round(sum(b - a for a, b in spans[k]), 2)
    return {'spans': spans, 'seconds': seconds}


def _clock(s):
    return f'{int(s // 60)}:{s % 60:04.1f}'


def _name_of(key, data):
    """A measured key ('@contract (youtube_shorts)') as the person reads it ('"@contract" on YouTube Shorts')."""
    for it in data.get('items') or []:
        if key_of(it) == key:
            return f'"{it.get("text")}" on {platform_name(it.get("platform"))}'
    return key


def findings(project, video):
    """(findings, facts line, numbers) for the review bundle: each overlay item whose box lies over the video's own
    text or graphics, as a finding (major from MAJOR_S in all), and the boxes as facts. ([], None, {}) without the
    Studio's boxes."""
    data = boxes_file(project)
    if not data:
        return [], None, {}
    frame = tuple(data.get('frame') or (1080, 1920))
    try:
        import letitedit.timeline.edit_script as es
        prof = es.read(str(project)).get('profile') or {}
        size = (int(prof.get('width') or frame[0]), int(prof.get('height') or frame[1]))
    except Exception:  # noqa: BLE001
        size = frame
    plain = [i for i in data.get('items') or [] if not i.get('if') and i.get('box')]
    later = [i for i in data.get('items') or [] if i.get('if')]
    result = measure(project, video, plain, size)
    out = []
    for it in plain:
        k = key_of(it)
        spans = result['spans'].get(k) or []
        secs = result['seconds'].get(k) or 0
        if not spans:
            continue
        where = ', '.join(f'from {_clock(a)} to {_clock(b)}' for a, b in spans[:6]) + (' and more' if len(spans) > 6 else '')
        line, platform, here = f'"{it.get("text")}"', platform_name(it.get('platform')), plain_where(it['box'])
        out.append({'check': 'overlay_over_own_text', 'severity': 'major' if secs >= MAJOR_S else 'minor',
                    'at': spans[0][0], 't1': spans[-1][1],
                    # what a person reads (T357): the line, the platform, roughly where, when, over what; no numbers
                    'what': f'letitedit adds the overlay words {line} to the {platform} file after the export, {here} '
                            f"and the video's own text or graphics sit under them {where} "
                            f'({secs:g} s in all): the overlay covers them in the file the person posts',
                    'plain': f"The overlay words {line} that letitedit adds to the {platform} file lie over the "
                             f"video's own text or graphics {here}, {where}.",
                    'fix': f'keep titles, headings, panels and graphics out of the place the {line} overlay words go '
                           f'({here}), or put nothing drawn there',
                    # the numbers stay in structured fields, which only code and the critic read
                    'overlay': {'text': it.get('text'), 'platform': it.get('platform'), 'box': it['box'],
                                'box_px': plain_box(it['box'], size), 'spans': spans, 'seconds': secs}})
    parts, said = [], []
    for it in data.get('items') or []:
        if not it.get('box'):
            continue
        cond = ' (added only when the video has AI-made picture or sound; not measured here)' if it.get('if') else ''
        parts.append(f'"{it.get("text")}" on {it.get("platform") or "every file"} at {plain_box(it["box"], size)} '
                     f'({it.get("placement")}){cond}')
        said.append(f'"{it.get("text")}" on {platform_name(it["platform"]) if it.get("platform") else "every file"} '
                    f'{plain_where(it["box"])}{cond}')
    facts = ('overlay words letitedit adds after the export: ' + '; '.join(said) if said else
             'overlay words: none placed') + \
        (f"; over the video's own text or graphics: " + ', '.join(
            f'{_name_of(k, data)} {v:g} s' for k, v in result['seconds'].items())
         if result['seconds'] else '')
    # the critic reads the numbers (the boxes in pixels); what a person reads says the line, the platform and roughly where
    numbers = {'overlay_words_after_export': parts,
               'overlay_over_own_text_s': result['seconds'],
               'overlay_words_note': 'the boxes are for your own reading: anything the person reads says the overlay '
                                     'line, the platform and roughly where (top, bottom), never pixel numbers'}
    if later:
        numbers['overlay_words_if'] = [f'"{i.get("text")}" if {", ".join(i.get("if"))}' for i in later]
    return out, facts, numbers
