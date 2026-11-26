"""Picture stickers and split screens in a reference video, marked by the person's AI on contact sheets.

Three steps:
1. moments(): cheap moment picking from the importer's grey analysis frames: each cut, each sudden change in one region
   while the rest of the picture carries on, each layout change (long straight edges that appear and stay), and a frame
   every ~1 s in long shots, within a budget of tiles per minute.
2. sheets(): contact sheets of those moments with a 0.1 grid drawn on, every tile numbered; QUESTION asks the AI to
   mark each sticker or split-screen part with a box and its first and last tile. parse() reads the answer.
3. timed(): each marked item's start and end from the frame differences inside its box at the file's own frame
   rate, between the last tile without it and the first tile with it; split parts snapped to straight edges.

to_overlays() turns the timed items into the shot-source overlay inventory (style_import_sources: sticker and pip).
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from letitedit.looks.style_import_stats import _iou

FORMAT = 'letitedit-picture-marks/1'
TILES_PER_MIN = 90          # 10 sheets of 9 tiles a minute
FILL_S = 1.0                # a tile at least this often inside long shots (raised when over budget)
FILL_MAX_S = 2.0
WALK_CAP = 3                # faint frames added at most beyond what the tracker followed (a moving background)
CALM_CAP = 12               # ... where the picture around the box is still
CONFIRM = 0.8               # the match that carries an item past the tile the AI saw it gone on
REACQUIRE_S = 2.5           # how long a lost item is looked for over the whole picture
REACQUIRE = 0.85            # the match that counts as the same item found again there
REACQUIRE_MIN = 16          # pixels a side (at the follower's size) for a picture found again to count
LOST_EARLY_S = 0.0          # an item lost this long before the AI's last tile is followed again from that tile
SAME_SHOT = 30.0            # mean difference (0-255) above which two small frames are different shots
GRID = 10                   # grid lines every 1/GRID of the tile
QUESTION = """These contact sheets show moments of one video, in order. Each tile is one frame, numbered (#) with its
time. A grid divides every tile into tenths (lines at 0.1, 0.2 ... 0.9, numbered 1-9 along the top and left edges).

Mark every picture sticker and every split screen you can see.
- Sticker: a picture laid over the shot: an emoji, icon, logo (a lettering-only wordmark included), cut-out photo, UI
  card or a collage of still cards. Each separately placed picture is one sticker (two icons side by side are two); one
  coordinated graphic (an app bar with its icon and text) is one. Cut-out photos, drawn charts and cards count only when
  they sit over another picture; on a plain or graphic background they are not stickers. Words alone (captions, titles)
  are not stickers.
- Split screen: separate pictures shown at once in their own parts of the frame: side by side, top and bottom, a
  framed picture inset over another picture or over a graphic page (picture-in-picture), or a grid or carousel of
  picture cards on a canvas. One
  layout sequence is one split, even if a panel arrives late or the main picture cuts underneath. Still cards laid over
  a filmed shot are stickers, not a split. One picture on a plain canvas is not a split.
- Not these: text printed inside the filmed picture (a screen, a paper, a can's label), objects in the scene, a
  picture's own letterbox bars.

Answer with JSON only, no other text:
{"items": [
  {"kind": "sticker", "first": 12, "last": 15, "box": [x0, y0, x1, y1], "end_box": [x0, y0, x1, y1],
   "what": "one line", "sure": true},
  {"kind": "split", "first": 20, "last": 31, "parts": [[x0, y0, x1, y1], ...], "end_parts": [[...], ...],
   "what": "one line", "sure": true}
]}
- first / last: the first and last tile numbers it is visible in (the same item in consecutive tiles is one item).
  Follow each sticker until it leaves the frame, even when it moves, shrinks, changes size or joins other pictures in
  a group; it is still the same sticker.
- box: where it is in its first tile, as fractions of the tile (0-1, left-top to right-bottom), read off the grid;
  end_box: where it is in its last tile. parts: every separate picture of the split in its first tile, the main
  picture included: the main picture of a picture-in-picture is the whole frame, [0, 0, 1, 1], even where the inset
  covers it; end_parts: the same in its last tile.
- sure: false when you can't tell (say why in "why"). Never guess to fill the list: an empty list means you looked at
  every tile and saw none."""


# ------------------------------------------------------------------ 1. moments

def _block_means(a, grid=6):
    h, w = a.shape[-2:]
    ys = np.linspace(0, h, grid + 1).astype(int)
    xs = np.linspace(0, w, grid + 1).astype(int)
    return np.stack([a[..., ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean(axis=(-2, -1))
                     for i in range(grid) for j in range(grid)], axis=-1)


def region_events(frames, fps, cut_times=(), lag_s=0.2, hi=20.0, lo=4.0, near_cut_s=0.3):
    """Times where one region of the picture changes suddenly while the rest carries on (a sticker or panel arriving or
    leaving): (time, strength) pairs, cuts left out."""
    n = len(frames)
    k = max(1, int(round(lag_s * fps)))
    if n <= k:
        return []
    out = []
    step = max(1, k // 2)
    cuts = np.array(sorted(cut_times), float)
    last = -1e9
    for i in range(k, n, step):
        d = np.abs(frames[i].astype(np.int16) - frames[i - k].astype(np.int16)).astype(np.float32)
        b = _block_means(d)
        top, mid = float(b.max()), float(np.median(b))
        if top < hi or mid > lo:
            continue
        t = i / fps
        if len(cuts) and np.min(np.abs(cuts - t)) < near_cut_s + lag_s:
            continue
        if t - last < 0.5:
            if out and top > out[-1][1]:
                out[-1] = (t, top)
            continue
        out.append((t, top))
        last = t
    return out


def _lines(f, thresh=40.0, share=0.45, bins=48):
    """The long straight vertical and horizontal edges of one grey frame, as quantised positions."""
    a = f.astype(np.float32)
    gx = np.abs(a[:, 2:] - a[:, :-2])
    gy = np.abs(a[2:, :] - a[:-2, :])
    h, w = a.shape
    cols = np.nonzero((gx > thresh).mean(axis=0) >= share)[0]
    rows = np.nonzero((gy > thresh).mean(axis=1) >= share)[0]
    vs = {int((c + 1) * bins / w) for c in cols if 2 < c < w - 4}
    hs = {int((r + 1) * bins / h) for r in rows if 2 < r < h - 4}
    return frozenset(('v', v) for v in vs) | frozenset(('h', v) for v in hs)


def layout_events(frames, fps, cut_times=(), every_s=0.2, hold=2, near_cut_s=0.3):
    """Times where long straight edges appear (or go) and stay: a split or an inset arriving or leaving."""
    step = max(1, int(round(every_s * fps)))
    idx = list(range(0, len(frames), step))
    sigs = [_lines(frames[i]) for i in idx]
    cuts = np.array(sorted(cut_times), float)
    out = []
    for j in range(1, len(idx) - hold):
        if sigs[j] == sigs[j - 1] or not (sigs[j] ^ sigs[j - 1]):
            continue
        if any(sigs[j + q] != sigs[j] for q in range(1, hold + 1)):
            continue
        t = idx[j] / fps
        if len(cuts) and np.min(np.abs(cuts - t)) < near_cut_s:
            continue
        out.append((t, float(len(sigs[j] ^ sigs[j - 1]))))
    return out


def moments(frames, fps, cut_times, duration, per_min=TILES_PER_MIN, fill_s=FILL_S):
    """The moments to show the AI: [{'t', 'why'}] in time order, at most per_min a minute (at least one per cut)."""
    duration = float(duration)
    end = max(0.0, duration - 0.5 / max(fps, 1.0))
    cuts = sorted(float(c) for c in cut_times if 0 < c < duration)
    keep = [(0.0, 'start', 9e9)]
    keep += [(min(end, c + 0.12), 'cut', 1e9) for c in cuts]
    ev = [(min(end, t + 0.25), 'region change', s) for t, s in region_events(frames, fps, cuts)]
    ev += [(min(end, t + 0.2), 'layout change', s) for t, s in layout_events(frames, fps, cuts)]
    budget = max(4, int(math.ceil(per_min * duration / 60.0)))

    def merged(rows, gap=0.3):
        rows = sorted(rows)
        out = []
        for r in rows:
            if out and r[0] - out[-1][0] < gap:
                if r[2] > out[-1][2]:
                    out[-1] = r
                continue
            out.append(r)
        return out

    def with_fill(rows, every):
        rows = merged(rows)
        bounds = [r[0] for r in rows] + [end]
        fill = []
        for a, b in zip(bounds, bounds[1:]):
            n = int(math.floor((b - a) / every))
            fill += [(a + (b - a) * q / (n + 1), 'every %.1f s' % every, 0.0) for q in range(1, n + 1)] if n > 0 else []
        return merged(rows + fill)

    fixed = keep + ev
    every = fill_s
    rows = with_fill(fixed, every)
    while len(rows) > budget and every < FILL_MAX_S:
        every = min(FILL_MAX_S, every * 1.25)
        rows = with_fill(fixed, every)
    if len(rows) > budget:
        # still over: the weakest region/layout events go first, then cuts that sit closest to another moment
        events = sorted(ev, key=lambda r: r[2])
        while events and len(rows) > budget:
            drop = events.pop(0)
            fixed = [r for r in fixed if r is not drop]
            rows = with_fill(fixed, every)
        while len(rows) > budget and len(rows) > 2:
            gaps = [(rows[i + 1][0] - rows[i - 1][0], i) for i in range(1, len(rows) - 1) if rows[i][1] != 'start']
            if not gaps:
                break
            rows.pop(min(gaps)[1])
    return [{'t': round(r[0], 3), 'why': r[1]} for r in rows]


# ------------------------------------------------------------------ 2. sheets

def layout(width, height):
    """(cols, rows, tile_w, tile_h) of a sheet about 1536 px wide: 3 x 3 for wide frames, 5 x 2 for tall ones."""
    if width >= height:
        cols, rows = 3, 3
    else:
        cols, rows = 5, 2
    tw = 1536 // cols
    th = int(round(tw * height / max(1, width)))
    return cols, rows, tw, th


def draw_tile(img, number, t):
    """One tile (PIL RGB image) with the grid and its label strip under it."""
    from PIL import Image, ImageDraw
    tw, th = img.size
    tile = Image.new('RGB', (tw, th + 18), (24, 24, 24))
    over = img.convert('RGBA')
    lay = Image.new('RGBA', over.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    for k in range(1, GRID):
        x, y = tw * k / GRID, th * k / GRID
        d.line([(x, 0), (x, th)], fill=(255, 0, 255, 120), width=1)
        d.line([(0, y), (tw, y)], fill=(255, 0, 255, 120), width=1)
        d.text((x + 2, 1), str(k), fill=(255, 255, 0, 230))
        d.text((2, y + 1), str(k), fill=(255, 255, 0, 230))
    tile.paste(Image.alpha_composite(over, lay).convert('RGB'), (0, 0))
    mm, ss = divmod(t, 60)
    ImageDraw.Draw(tile).text((4, th + 3), f'#{number}  {int(mm)}:{ss:04.1f}', fill=(255, 255, 255))
    return tile


def sheets(video, info, rows, folder, frames_at=None):
    """Contact sheets of the moments (rows from moments()), tiles numbered from 1 in time order. Writes sheet-NN.jpg
    and marks-request.json in folder; returns the request {format, question, tiles: [{n, t, why, sheet}], sheets}."""
    from PIL import Image
    if frames_at is None:
        from letitedit.looks.style_import import frames_at
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cols, nrows, tw, th = layout(info['width'], info['height'])
    per = cols * nrows
    got = frames_at(video, [r['t'] for r in rows], tw, info)
    keys = sorted(got)
    tiles, files = [], []
    for s in range(0, len(rows), per):
        chunk = rows[s:s + per]
        sheet = Image.new('RGB', (cols * tw + (cols - 1) * 4, nrows * (th + 18) + (nrows - 1) * 4), (60, 60, 60))
        for q, r in enumerate(chunk):
            n = s + q + 1
            if keys:
                k = min(keys, key=lambda x: abs(x - r['t']))
                img = Image.fromarray(got[k][:, :, ::-1].copy())
            else:
                img = Image.new('RGB', (tw, th))
            img = img.resize((tw, th))
            sheet.paste(draw_tile(img, n, r['t']), ((q % cols) * (tw + 4), (q // cols) * (th + 18 + 4)))
            tiles.append({'n': n, 't': r['t'], 'why': r['why'], 'sheet': len(files) + 1})
        path = folder / f'sheet-{len(files) + 1:02d}.jpg'
        sheet.save(path, quality=88)
        files.append(str(path))
    req = {'format': FORMAT, 'video': str(video), 'duration_s': info['duration'], 'fps': info['fps'],
           'size': [info['width'], info['height']], 'tiles': tiles, 'sheets': files, 'question': QUESTION}
    (folder / 'marks-request.json').write_text(json.dumps(req, indent=1), encoding='utf-8')
    return req


# ------------------------------------------------------------------ the AI's answer

def _box(b):
    if not isinstance(b, (list, tuple)) or len(b) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in b)
    except (TypeError, ValueError):
        return None
    if max(x0, y0, x1, y1) > 1.5:          # given in grid cells
        x0, y0, x1, y1 = (v / GRID for v in (x0, y0, x1, y1))
    x0, x1 = sorted((min(1.0, max(0.0, x0)), min(1.0, max(0.0, x1))))
    y0, y1 = sorted((min(1.0, max(0.0, y0)), min(1.0, max(0.0, y1))))
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)] if x1 - x0 > 0.003 and y1 - y0 > 0.003 else None


def parse(answer, tiles=None):
    """The items of one answer (text holding JSON, or the parsed dict / list). Bad items are dropped and counted."""
    if isinstance(answer, str):
        m = re.search(r'\{.*\}', answer, re.S)
        try:
            answer = json.loads(m.group(0)) if m else {}
        except ValueError:
            answer = {}
    items = answer.get('items', []) if isinstance(answer, dict) else answer if isinstance(answer, list) else []
    numbers = {t['n'] for t in tiles} if tiles else None
    out, bad = [], 0
    for it in items:
        if not isinstance(it, dict):
            bad += 1
            continue
        kind = {'pip': 'split', 'inset': 'split', 'split_screen': 'split'}.get(it.get('kind'), it.get('kind'))
        try:
            first, last = int(it.get('first')), int(it.get('last', it.get('first')))
        except (TypeError, ValueError):
            bad += 1
            continue
        first, last = min(first, last), max(first, last)
        if kind not in ('sticker', 'split') or (numbers and (first not in numbers or last not in numbers)):
            bad += 1
            continue
        row = {'kind': kind, 'first': first, 'last': last, 'what': str(it.get('what', ''))[:200],
               'sure': it.get('sure', True) is not False, 'why': str(it.get('why', ''))[:200]}
        if kind == 'sticker':
            row['box'] = _box(it.get('box'))
            row['end_box'] = _box(it.get('end_box')) or row['box']
            if not row['box']:
                bad += 1
                continue
        else:
            parts = [p for p in (_box(b) for b in (it.get('parts') or [])) if p]
            end_parts = [p for p in (_box(b) for b in (it.get('end_parts') or [])) if p] or parts
            if not parts:
                bad += 1
                continue
            row.update(parts=parts, end_parts=end_parts)
        out.append(row)
    return out, bad


def _region(item, end=False):
    if item['kind'] == 'sticker':
        return item['end_box' if end else 'box']
    return _focus(item['end_parts' if end else 'parts'])


def _focus(parts):
    """The part of a split whose arrival times it: the union of its parts that aren't the full frame (an inset), else
    the whole frame."""
    small = [p for p in parts if (p[2] - p[0]) * (p[3] - p[1]) < 0.8]
    if not small:
        return [0.0, 0.0, 1.0, 1.0]
    return [min(p[0] for p in small), min(p[1] for p in small), max(p[2] for p in small), max(p[3] for p in small)]


def join(batches):
    """One item list from several answers (each a list of parsed items, in tile order): an item that ends on a batch's
    last tile and one of the same kind starting on the next batch's first tile in the same place become one."""
    out = []
    for items, (lo, hi) in batches:
        for it in sorted(items, key=lambda r: r['first']):
            prev = next((p for p in out if p['kind'] == it['kind'] and p['last'] == lo - 1 and p['last_batch_end']
                         and _iou(_region(p, True), _region(it)) >= 0.4), None)
            if prev and it['first'] == lo:
                prev['last'] = it['last']
                prev['last_batch_end'] = it['last'] == hi
                if it['kind'] == 'sticker':
                    prev['end_box'] = it['end_box']
                else:
                    prev['end_parts'] = it['end_parts']
                prev['sure'] = prev['sure'] and it['sure']
                continue
            out.append({**it, 'last_batch_end': it['last'] == hi})
    for it in out:
        it.pop('last_batch_end', None)
    return out


# ------------------------------------------------------------------ 3. times by pixels

def decode_span(video, start, end, width, info):
    """Colour frames (BGR, `width` wide) at the file's own rate from start to end: (first frame index, frames)."""
    from letitedit.looks.style_import import _ff, NO_WINDOW, THREADS
    fps = float(info['fps'] or 30.0)
    i0 = max(0, int(math.floor(start * fps + 1e-6)))
    i1 = int(math.ceil(end * fps - 1e-6))
    h = int(round(info['height'] * width / info['width'] / 2) * 2)
    # input seeking decodes up to the time and starts at the first frame at or after it: frame i0
    args = [_ff(), '-v', 'error', '-nostdin', '-threads', str(THREADS), '-ss', f'{max(0.0, (i0 - 0.5) / fps):.5f}',
            '-i', str(video), '-frames:v', str(max(1, i1 - i0 + 1)),
            '-vf', f'scale={width}:{h}:flags=area', '-fps_mode', 'passthrough',   # never a repeated first frame
            '-an', '-sn', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, timeout=120)
    n = width * h * 3
    k = len(r.stdout) // n
    return i0, np.frombuffer(r.stdout[:k * n], np.uint8).reshape(k, h, width, 3)


def _roi(box, shape, pad=0.01):
    h, w = shape[:2]
    x0 = max(0, int((box[0] - pad) * w))
    y0 = max(0, int((box[1] - pad) * h))
    x1 = min(w, int(math.ceil((box[2] + pad) * w)))
    y1 = min(h, int(math.ceil((box[3] + pad) * h)))
    return slice(y0, max(y0 + 1, y1)), slice(x0, max(x0 + 1, x1))


def change_point(frames, box, arriving, cuts=()):
    """Index (into frames) where the item in box arrives (arriving: frames[0] without it, frames[-1] with it) or leaves
    (frames[0] with it, frames[-1] without): for an arrival the first frame that shows it, for a leaving the first frame
    that no longer does. Measured on the pixels that differ between the two ends, as each frame's progress from the
    frame without it toward the frame with it (a moving background averages out; a fade climbs step by step). cuts:
    frame indices (into frames) of cuts, preferred within 2 frames. Returns (index, how) or (None, why)."""
    n = len(frames)
    if n < 2:
        return None, 'no frames'
    ys, xs = _roi(box, frames[0].shape)
    seq = np.stack([f[ys, xs] for f in frames]).astype(np.float32)
    without, with_ = (seq[0], seq[-1]) if arriving else (seq[-1], seq[0])
    d = with_ - without
    mask = np.abs(d).max(axis=2) > 30
    if mask.sum() < 6:
        return None, 'no change inside the box between the two tiles'
    dm = d[mask]
    prog = ((seq[:, mask] - without[mask]) * dm).sum(axis=(1, 2)) / float((dm * dm).sum())
    up = prog if arriving else prog[::-1]          # rising from without (0) to with (1) either way
    # the step: the split into a low and a high run that fits best
    c = np.cumsum(up)
    c2 = np.cumsum(up * up)
    best, k = None, 1
    for j in range(1, n):
        lo_n, hi_n = j, n - j
        sse = (c2[j - 1] - c[j - 1] ** 2 / lo_n) + ((c2[-1] - c2[j - 1]) - (c[-1] - c[j - 1]) ** 2 / hi_n)
        if best is None or sse < best:
            best, k = sse, j
    # a fade or an animation: the run of steady climbing around the step
    steps = np.diff(up)
    calm = np.abs(steps[:max(1, k - 1)]) if k > 1 else np.abs(steps)
    noise = 3 * float(np.median(calm)) + 0.02
    first = k
    while first > 1 and steps[first - 2] > noise:
        first -= 1
    # a faint start (a fade from a dark or still picture): when the frames before it hold still, the first frame that
    # rises clearly above them
    before = up[:first]
    if len(before) >= 4 and float(before[:max(2, len(before) // 2)].std()) < 0.01:
        level = float(np.median(before[:max(2, len(before) // 2)]))
        while first > 1 and up[first - 1] > level + 0.04:
            first -= 1
    last = k
    while last < n - 1 and steps[last - 1] > noise and up[last] < 0.9:
        last += 1
    how = 'abrupt' if last - first <= 1 else f'over {last - first + 1} frames'
    # arriving: the first frame that shows it; leaving: the first frame (in time) without it
    idx = first if arriving else n - first
    near = [c for c in cuts if abs(c - idx) <= 2 and 0 < c < n]
    if near:
        idx, how = min(near, key=lambda c: abs(c - idx)), 'on a cut'
    return int(min(n - 1, max(0, idx))), how


def several_pictures(frame, parts, framed=0.5, colourful=15.0):
    """Whether the parts on frame make a layout of several pictures: at least two parts, no inner part covering more
    than `framed` of the picture inside a whole-picture part (that is one picture in a frame, a page around a video),
    and at least two parts with a picture's spread of colour (not flat cards or page)."""
    if len(parts) < 2:
        return False
    whole = [p for p in parts if (p[2] - p[0]) * (p[3] - p[1]) >= 0.9]
    inner = [p for p in parts if p not in whole]
    if whole and any((p[2] - p[0]) * (p[3] - p[1]) > framed for p in inner):
        return False
    h, w = frame.shape[:2]
    pictures = 0
    for p in parts:
        x0, y0 = int(p[0] * w), int(p[1] * h)
        x1, y1 = max(x0 + 2, int(p[2] * w)), max(y0 + 2, int(p[3] * h))
        if float(frame[y0:y1, x0:x1].astype(np.float32).std(axis=(0, 1)).mean()) > colourful:
            pictures += 1
    return pictures >= 2


def snap_edges(frame, box, reach=0.03):
    """Each edge of a split part moved to the strongest straight edge within reach (frame edges stay put)."""
    g = frame.astype(np.float32).mean(axis=2)
    h, w = g.shape
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = np.abs(g[:, 2:] - g[:, :-2])
    gy[1:-1, :] = np.abs(g[2:, :] - g[:-2, :])
    x0, y0, x1, y1 = box
    ya, yb = int((y0 + 0.1 * (y1 - y0)) * h), max(int((y0 + 0.1 * (y1 - y0)) * h) + 1, int((y1 - 0.1 * (y1 - y0)) * h))
    xa, xb = int((x0 + 0.1 * (x1 - x0)) * w), max(int((x0 + 0.1 * (x1 - x0)) * w) + 1, int((x1 - 0.1 * (x1 - x0)) * w))
    col = gx[ya:yb].mean(axis=0)
    row = gy[:, xa:xb].mean(axis=1)
    out = list(box)
    for i, (v, prof, n) in enumerate(((x0, col, w), (y0, row, h), (x1, col, w), (y1, row, h))):
        if v <= 0.01 or v >= 0.99:
            out[i] = float(round(v))
            continue
        lo, hi = max(1, int((v - reach) * n)), min(n - 2, int((v + reach) * n))
        if hi <= lo:
            continue
        k = lo + int(np.argmax(prof[lo:hi + 1]))
        if prof[k] > 2.5 * float(np.median(prof[lo:hi + 1])) + 4:
            out[i] = k / n
    return [round(v, 4) for v in out]


def _nested(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def _inside(a, b):
    """The centre of box a lies in box b."""
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def group(items, nest=0.6, together=2):
    """Sure sticker marks that arrive together (first tiles at most `together` apart) where one sits inside the other
    (an icon inside its label pill) become one item: one coordinated graphic is one sticker. Separately placed pictures
    stay apart, also when a later one arrives where an earlier one was."""
    out = []
    for it in sorted(items, key=lambda r: r['first']):
        if it['kind'] == 'sticker' and it.get('sure', True):
            host = next((o for o in out if o['kind'] == 'sticker' and o.get('sure', True)
                         and abs(o['first'] - it['first']) <= together and it['first'] <= o['last']
                         and _nested(o['box'], it['box']) >= nest), None)
            if host:
                if it['first'] == host['first']:
                    host['box'] = _union(host['box'], it['box'])
                if it['last'] >= host['last']:
                    host['end_box'] = _union(host['end_box'], it['end_box']) if it['last'] == host['last'] else it['end_box']
                host['last'] = max(host['last'], it['last'])
                host['what'] = (host.get('what') or '') + ' + ' + (it.get('what') or '')
                host['grouped'] = host.get('grouped', 1) + 1
                continue
        out.append(dict(it))
    return out


def walk_out(frames, box, idx, arriving, cap=None, calm_cap=CALM_CAP, calm=0.03):
    """Move an arrival earlier (or a leaving later) while the box still clearly differs from the picture without the
    item: the faint first or last frames of a fade, a pop or a slide. frames[0] is without it for an arrival, frames[-1]
    for a leaving; idx comes from change_point (an arrival's first frame, a leaving's first frame without it). Measured
    on the item's own pixels (those that differ between the two ends), against the box's unchanged pixels. cap: at most
    this many frames, or up to calm_cap while the picture around the box stays still (under `calm` of it changing)."""
    n = len(frames)
    if idx is None or n < 4:
        return idx
    ys, xs = _roi(box, frames[0].shape, pad=0.005)
    seq = np.stack([f[ys, xs] for f in frames]).astype(np.int16)
    plate, full = (seq[0], seq[-1]) if arriving else (seq[-1], seq[0])
    contrast = np.abs(full - plate).max(axis=2)
    mask = contrast > 25
    if mask.sum() < 6:
        return idx
    d = np.abs(seq - plate).max(axis=3)
    dep = (d[:, mask] >= np.maximum(8, 0.12 * contrast[mask])).mean(axis=1)
    # the picture just around the box carries the background's own motion
    oy, ox = _roi(box, frames[0].shape, pad=0.04)
    around = np.stack([f[oy, ox] for f in frames]).astype(np.int16)
    keep = np.ones(around.shape[1:3], bool)
    keep[ys.start - oy.start:ys.stop - oy.start, xs.start - ox.start:xs.stop - ox.start] = False
    ref = around[-1] if not arriving else around[0]
    bg = (np.abs(around - ref).max(axis=3)[:, keep] > 12).mean(axis=1) if keep.sum() >= 20 else np.ones(n)
    base = float(np.median(dep[:3] if arriving else dep[-3:]))
    span = float(dep.max()) - base
    if span < 0.2:
        return idx
    thr = base + max(0.03, 0.12 * span)
    def allowed(k, steps):
        return cap is None or steps < cap or (steps < calm_cap and bg[k] < calm)
    if arriving:
        i = idx
        while (i - 1 >= 1 and dep[i - 1] > thr and dep[i - 1] - bg[i - 1] > 0.15 and dep[i - 1] < dep[i] - 0.02
               and allowed(i - 1, idx - i)):
            i -= 1                                  # a fade climbs frame by frame; a moving background doesn't
        return i
    j = idx
    while (j <= n - 2 and dep[j] > thr and dep[j] - bg[j] > 0.15 and dep[j] < dep[j - 1] - 0.02
           and allowed(j, j - idx)):
        j += 1
    return j


class Coarse:
    """The reference read once, small, every k-th frame (about 6 a second): for following items over long spans."""

    def __init__(self, video, info, per_s=6.0, width=360, frames=None):
        self.fps = float(info['fps'] or 30.0)
        self.k = max(1, int(round(self.fps / per_s)))
        if frames is not None:                      # given (tests): already every k-th frame
            self.frames = frames
            return
        from letitedit.looks.style_import import _ff, NO_WINDOW, THREADS
        h = int(round(info['height'] * width / info['width'] / 2) * 2)
        select = "select='not(mod(n\\," + str(self.k) + "))'"
        args = [_ff(), '-v', 'error', '-nostdin', '-threads', str(THREADS), '-i', str(video),
                '-vf', f'{select},scale={width}:{h}:flags=area', '-fps_mode', 'passthrough',
                '-an', '-sn', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
        r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, timeout=1800)
        size = width * h * 3
        n = len(r.stdout) // size
        self.frames = np.frombuffer(r.stdout[:n * size], np.uint8).reshape(n, h, width, 3)

    def index(self, t):
        return int(min(len(self.frames) - 1, max(0, round(t * self.fps / self.k))))

    def time(self, j):
        return j * self.k / self.fps


def _match(img, tpl, mask):
    import cv2
    if tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1] or min(tpl.shape[:2]) < 4:
        return -1.0, (0, 0)
    try:
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
    except cv2.error:
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    _, top, _, loc = cv2.minMaxLoc(res)
    return float(top), loc


def _search(img, tpl, mask, scales, smallest=10):
    """The best place for tpl anywhere in img over the scales: (score, [x, y, w, h])."""
    import cv2
    best = (-1.0, None)
    for s in scales:
        tw, th = int(round(tpl.shape[1] * s)), int(round(tpl.shape[0] * s))
        if min(tw, th) < smallest:
            continue
        t2 = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
        m2 = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST) if mask is not None else None
        score, loc = _match(img, t2, m2)
        if score > best[0]:
            best = (score, [loc[0], loc[1], tw, th])
    return best


def follow(coarse, box, t_from, t_before=None, found=0.6, misses=2, t_after=None, track=False):
    """Follow the item in box (fractions, at t_from) from t_from on, by its own look (template matched with moves and
    scale changes allowed), until it is missing on `misses` samples in a row. t_before: a time without it (the pixels
    that differ there make the template's mask, and a spot that looks more like it than like the item counts as
    missing). t_after: a later time without it, used instead when t_before is another shot and t_after is the same
    shot with the item's look not in the box there. Returns (last time found, first time
    missing or None when it lasts to the end, box at the last time found). A lost item is looked for over the whole
    picture for REACQUIRE_S (it may fly into a list or a corner), at a seventh to 1.2 times its size. track: also return
    {time: (the first look's match score, box)} of every sample it was found on."""
    import cv2
    fr = coarse.frames
    H, W = fr.shape[1:3]
    j0 = coarse.index(t_from)
    x0, y0 = int(box[0] * W), int(box[1] * H)
    x1, y1 = min(W, max(x0 + 4, int(math.ceil(box[2] * W)))), min(H, max(y0 + 4, int(math.ceil(box[3] * H))))
    tpl = fr[j0][y0:y1, x0:x1].copy()
    mask = plate = None
    sure_plate = False
    def same_shot(t):
        return t is not None and np.abs(fr[coarse.index(t)].astype(np.int16) - fr[j0].astype(np.int16)).mean() <= SAME_SHOT
    without = [(t_before, True)]
    if t_after is not None and not same_shot(t_before):
        ja = coarse.index(t_after)
        if ja > j0 and same_shot(t_after) and _match(fr[ja][y0:y1, x0:x1], tpl, None)[0] < found:
            without.insert(0, (t_after, False))      # the same shot, and its look isn't there
    for t, before in without:
        jb = coarse.index(t) if t is not None else j0
        if jb == j0:
            continue
        diff = np.abs(tpl.astype(np.int16) - fr[jb][y0:y1, x0:x1].astype(np.int16)).max(axis=2) > 25
        if diff.mean() < 0.05:
            if before:                               # nothing new in the box: not the item, nothing to follow
                return (t_from, t_from, [round(v, 4) for v in box]) + (({},) if track else ())
            continue                                 # still there after: no use as the picture without it
        plate = fr[jb]
        sure_plate = same_shot(t)                    # a picture of this very place without it: losing it means gone
        if 0.15 <= diff.mean() <= 0.95:
            mask = np.repeat(cv2.dilate(diff.astype(np.uint8), np.ones((3, 3), np.uint8))[..., None], 3, axis=2)
        break
    base_w, base_h = tpl.shape[1], tpl.shape[0]
    templates = [(tpl, mask)]
    cur = [x0, y0, base_w, base_h]
    scale = 1.0
    last_j, miss_j, run = j0, None, 0
    scores = {}
    j = j0
    while j + 1 < len(fr):
        j += 1
        pad = int(max(cur[2], cur[3]) + 0.05 * W)
        rx0, ry0 = max(0, cur[0] - pad), max(0, cur[1] - pad)
        rx1, ry1 = min(W, cur[0] + cur[2] + pad), min(H, cur[1] + cur[3] + pad)
        region = fr[j][ry0:ry1, rx0:rx1]
        best, first = (-1.0, None, None), -1.0
        for n, (tp, mk) in enumerate(templates):
            for f in (0.7, 0.85, 1.0, 1.18, 1.4):
                s = scale * f
                if s < 0.15 or s > 3:
                    continue
                tw, th = max(4, int(round(base_w * s))), max(4, int(round(base_h * s)))
                t2 = cv2.resize(tp, (tw, th), interpolation=cv2.INTER_AREA)
                m2 = cv2.resize(mk, (tw, th), interpolation=cv2.INTER_NEAREST) if mk is not None else None
                score, loc = _match(region, t2, m2)
                if n == 0:
                    first = max(first, score)
                if score > best[0]:
                    best = (score, [rx0 + loc[0], ry0 + loc[1], tw, th], s)
        if best[0] >= found and plate is not None:
            bx, by, bw2, bh2 = best[1]
            crop = fr[j][by:by + bh2, bx:bx + bw2].astype(np.int16)
            back = plate[by:by + bh2, bx:bx + bw2].astype(np.int16)
            look = cv2.resize(tpl, (bw2, bh2), interpolation=cv2.INTER_AREA).astype(np.int16)
            if crop.shape == back.shape == look.shape and np.abs(crop - back).mean() < 0.5 * np.abs(crop - look).mean():
                best = (-1.0, None, None)               # the background seen before it came: it has gone
        if best[0] >= found:
            cur, scale, last_j, run = best[1], best[2], j, 0
            scores[round(coarse.time(j), 4)] = (round(float(first), 3), _frac(cur, W, H))  # the look it had at the start
            if best[0] >= 0.85:
                crop = (fr[j][cur[1]:cur[1] + cur[3], cur[0]:cur[0] + cur[2]].copy(), None)
                crop = (cv2.resize(crop[0], (base_w, base_h), interpolation=cv2.INTER_AREA), None)
                templates = templates[:1] + [crop]
            continue
        run += 1
        if run == 1:
            miss_j = j
        if run >= misses:
            again = None
            for jj in [] if not sure_plate else range(miss_j, min(len(fr), miss_j + int(REACQUIRE_S * coarse.fps / coarse.k) + 1)):
                sc, bb = _search(fr[jj], tpl, mask, np.geomspace(0.15, 1.2, 14), smallest=REACQUIRE_MIN)
                if sc < REACQUIRE:
                    continue
                if plate is not None:
                    crop = fr[jj][bb[1]:bb[1] + bb[3], bb[0]:bb[0] + bb[2]].astype(np.int16)
                    back = plate[bb[1]:bb[1] + bb[3], bb[0]:bb[0] + bb[2]].astype(np.int16)
                    look = cv2.resize(tpl, (bb[2], bb[3]), interpolation=cv2.INTER_AREA).astype(np.int16)
                    if np.abs(crop - back).mean() < max(6.0, 0.5 * np.abs(crop - look).mean()):
                        continue                         # the picture without it there
                was = fr[last_j][bb[1]:bb[1] + bb[3], bb[0]:bb[0] + bb[2]]
                if _match(was, cv2.resize(tpl, (bb[2], bb[3]), interpolation=cv2.INTER_AREA), None)[0] >= found:
                    continue                             # it was already there while the item was elsewhere: a twin
                again = (jj, bb)
                break
            if again is None:
                break
            j, cur = again
            scale = cur[2] / base_w
            last_j, run, miss_j = j, 0, None
            scores[round(coarse.time(j), 4)] = (round(float(sc), 3), _frac(cur, W, H))
            templates = templates[:1]
    if run == 0:
        miss_j = None
    b = [cur[0] / W, cur[1] / H, (cur[0] + cur[2]) / W, (cur[1] + cur[3]) / H]
    out = (coarse.time(last_j), (coarse.time(miss_j) if miss_j is not None else None), [round(v, 4) for v in b])
    return out + ((scores,) if track else ())


def _frac(cur, W, H):
    return [round(cur[0] / W, 4), round(cur[1] / H, 4), round((cur[0] + cur[2]) / W, 4), round((cur[1] + cur[3]) / H, 4)]


def track_native(frames, box, forward, plate=None, found=0.6, misses=2):
    """Follow the item in box (fractions) frame by frame through frames: from frames[0] onward (forward) or from
    frames[-1] backward. plate: a frame without the item (its pixels that differ make the template's mask, and a spot
    that looks more like the plate than like the item counts as missing), or a list of one per frame (each shot's own).
    Returns (index of the last frame it was found on in that direction, its box there)."""
    import cv2
    n = len(frames)
    H, W = frames[0].shape[:2]
    j0 = 0 if forward else n - 1
    plates = plate if isinstance(plate, list) else [plate] * n
    plate = plates[j0]
    x0, y0 = int(box[0] * W), int(box[1] * H)
    x1, y1 = min(W, max(x0 + 4, int(math.ceil(box[2] * W)))), min(H, max(y0 + 4, int(math.ceil(box[3] * H))))
    tpl = frames[j0][y0:y1, x0:x1].copy()
    mask = None
    if plate is not None:
        diff = np.abs(tpl.astype(np.int16) - plate[y0:y1, x0:x1].astype(np.int16)).max(axis=2) > 25
        if diff.mean() < 0.05:                       # nothing new in the box: not the item, nothing to follow
            return j0, [round(v, 4) for v in box]
        if 0.15 <= diff.mean() <= 0.95:
            mask = np.repeat(cv2.dilate(diff.astype(np.uint8), np.ones((3, 3), np.uint8))[..., None], 3, axis=2)
    bw, bh = tpl.shape[1], tpl.shape[0]
    cur, scale, last, run = [x0, y0, bw, bh], 1.0, j0, 0
    step = 1 if forward else -1
    for j in range(j0 + step, n if forward else -1, step):
        pad = int(0.6 * max(cur[2], cur[3]) + 8)
        rx0, ry0 = max(0, cur[0] - pad), max(0, cur[1] - pad)
        rx1, ry1 = min(W, cur[0] + cur[2] + pad), min(H, cur[1] + cur[3] + pad)
        region = frames[j][ry0:ry1, rx0:rx1]
        best = (-1.0, None, None)
        for f in (0.8, 0.9, 1.0, 1.1, 1.25):
            s = scale * f
            if s < 0.1 or s > 3:
                continue
            tw, th = max(4, int(round(bw * s))), max(4, int(round(bh * s)))
            t2 = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
            m2 = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST) if mask is not None else None
            score, loc = _match(region, t2, m2)
            if score > best[0]:
                best = (score, [rx0 + loc[0], ry0 + loc[1], tw, th], s)
        if best[0] >= found and plates[j] is not None:
            bx, by, w2, h2 = best[1]
            crop = frames[j][by:by + h2, bx:bx + w2].astype(np.int16)
            back = plates[j][by:by + h2, bx:bx + w2].astype(np.int16)
            look = cv2.resize(tpl, (w2, h2), interpolation=cv2.INTER_AREA).astype(np.int16)
            if crop.shape == back.shape == look.shape and np.abs(crop - back).mean() < max(6.0, 0.5 * np.abs(crop - look).mean()):
                best = (-1.0, None, None)               # the picture without it there: not the item
        if best[0] >= found:
            cur, scale, last, run = best[1], best[2], j, 0
            continue
        run += 1
        if run >= misses:
            break
    b = [cur[0] / W, cur[1] / H, (cur[0] + cur[2]) / W, (cur[1] + cur[3]) / H]
    return last, [round(v, 4) for v in b]


def shot_plates(frames, box, cuts, clear=0.15):
    """One picture without the item for each frame of a span that ends with the item in box: each shot's first frame
    when the box there clearly differs from the last frame's (the item isn't there yet), else the nearest earlier such
    shot's, else the span's first frame."""
    n = len(frames)
    ys, xs = _roi(box, frames[0].shape, pad=0.0)
    look = frames[-1][ys, xs].astype(np.int16)
    starts = [0] + sorted(c for c in set(cuts) if 0 < c < n)
    plates, good = [None] * n, frames[0]
    for a, b in zip(starts, starts[1:] + [n]):
        cand = frames[a]
        if (np.abs(cand[ys, xs].astype(np.int16) - look).max(axis=2) > 25).mean() >= clear:
            good = cand
        for k in range(a, b):
            plates[k] = good
    return plates


def arrival_in_shot(frames, box, a, b, thr=0.03, pad=0.02):
    """When an item already shows in the last frames of a shot [a, b) (frames[a] without it): the first frame from which
    on its box keeps differing from frames[a] by more than the picture around the box does. None when it isn't there by
    the shot's end."""
    if b - a < 3:
        return None
    ys, xs = _roi(box, frames[0].shape, pad=pad)
    oy, ox = _roi(box, frames[0].shape, pad=pad + 0.04)
    seg = frames[a:b].astype(np.int16)
    keep = np.ones((oy.stop - oy.start, ox.stop - ox.start), bool)
    keep[ys.start - oy.start:ys.stop - oy.start, xs.start - ox.start:xs.stop - ox.start] = False
    inside = (np.abs(seg[:, ys, xs] - seg[0, ys, xs]).max(axis=3) > 25).mean(axis=(1, 2))
    around = (np.abs(seg[:, oy, ox] - seg[0, oy, ox]).max(axis=3)[:, keep] > 25).mean(axis=1) if keep.sum() >= 20 \
        else np.zeros(len(seg))
    there = inside - around > thr
    if not there[-1]:
        return None
    k = len(seg) - 1
    while k - 1 >= 1 and there[k - 1]:
        k -= 1
    return a + k


def _snap_cut(idx, cuts, n):
    near = [c for c in cuts if abs(c - idx) <= 2 and 0 < c < n]
    return min(near, key=lambda c: abs(c - idx)) if near else None


def timed(video, info, request, items, cut_times=(), width=320, decode=None, coarse=None):
    """Each item with start_s (its first visible frame), end_s (its last visible frame) and end_exclusive_s from the
    pixels, and its box(es) refined. Sure sticker marks nested inside each other are grouped first (group()).
    A sticker's start: followed frame by frame backward from its first tile (track_native: its own look, moves and
    scale changes allowed) to the earliest frame it is found on, then any faint frames before it (walk_out). Its end:
    followed through the video (follow(), about 6 frames a second) from its first tile until it is gone, then frame by
    frame forward from its last sighting, then any faint frames after. It is followed past the tile the AI saw it gone
    on only when its first look matches strongly there (CONFIRM) or it went into another mark showing then (a list). A split's start and end come from the change
    inside its parts between neighbouring tiles. request: the sheets' request (its tiles give each tile's time).
    Times that can't be measured keep the tile bracket and say so in 'timing'. coarse: a Coarse reading of the video
    (made on first need)."""
    decode = decode or (lambda a, b: decode_span(video, a, b, width, info))
    fps = float(info['fps'] or 30.0)
    dur = float(info['duration'])
    last_frame = max(0, int(round(dur * fps)) - 1)
    tiles = {t['n']: t['t'] for t in request['tiles']}
    numbers = sorted(tiles)
    cut_frames = [int(round(c * fps)) for c in cut_times]
    state = {'coarse': coarse}

    def get_coarse():
        if state['coarse'] is None:
            state['coarse'] = Coarse(video, info)
        return state['coarse']

    out = []
    marks = group(items)
    for it in marks:
        row = dict(it)
        sticker = it['kind'] == 'sticker'
        t_first, t_last = tiles[it['first']], tiles[it['last']]
        before = [n for n in numbers if n < it['first']]
        after = [n for n in numbers if n > it['last']]
        notes = []
        box0, box1 = _region(it), _region(it, True)
        f_with = None                                     # a split's frames with it (its parts snap to edges there)
        # ---- start: the first visible frame
        if not before:
            start_f = 0
            notes.append('visible from the first frame')
        else:
            t_a = tiles[before[-1]]
            i0, fr = decode(t_a, t_first)
            cuts = [c - i0 for c in cut_frames]
            idx, how = (None, 'no frames')
            if len(fr) >= 2 and sticker:
                plates = shot_plates(fr, box0, cuts)                           # an overlay may go on across a cut
                j, bj = track_native(fr, box0, False, plate=plates)
                if j < len(fr) - 1:
                    idx, how = j, 'followed back'
                    cw = max([c for c in cuts if 0 < c <= j] or [0])
                    w = walk_out(fr[cw:min(len(fr), j + 4)], bj, j - cw, True, cap=WALK_CAP)
                    w = None if w is None else w + cw  # the tracker already saw the clear frames
                    if w is not None and w < j:
                        idx, how = w, how + f', {j - w} faint frames before'
                    c = _snap_cut(idx, cuts, len(fr))
                    if c is not None:
                        k = arrival_in_shot(fr, _union(box0, bj), max([x for x in cuts if 0 < x < c] or [0]), c)
                        idx, how = (k, 'arrived before a cut, from the pixels in its box') if k is not None else (c, 'on a cut')
            if idx is None and len(fr) >= 2:
                idx, how = change_point(fr, box0, True, cuts)
                if idx is not None and how not in ('on a cut', 'abrupt'):
                    w = walk_out(fr, box0, idx, True)
                    how += f', {idx - w} faint frames before' if w < idx else ''
                    idx = w
            if idx is None:
                start_f = int(round((t_a + t_first) / 2 * fps))
                notes.append(f'start not measured ({how}); between {t_a:.2f} and {t_first:.2f} s')
            else:
                start_f = i0 + idx
                notes.append(f'start {how}')
            if len(fr) >= 2 and not sticker:
                f_with = fr[idx:] if idx is not None else fr[-1:]
        # ---- end: the last visible frame
        anchor, b_anchor, gone = t_last, box1, (tiles[after[0]] if after else None)
        if sticker and it.get('sure', True):
            t_seen, t_gone, b_seen, sc = follow(get_coarse(), box0, t_first, tiles[before[-1]] if before else None,
                                                t_after=tiles[after[0]] if after else None, track=True)
            if t_seen < t_last - LOST_EARLY_S:        # lost long before the AI last saw it (it changed shape on the way,
                # joined a list): follow on from the AI's last tile
                t_seen, t_gone, b_seen, sc = follow(get_coarse(), box1, t_last, tiles[before[-1]] if before else None,
                                                    t_after=tiles[after[0]] if after else None, track=True)
            if after and t_seen >= tiles[after[0]]:      # the AI saw it gone at its next tile: followed past it only
                n_after = after[0]                       # on a strong match of its first look there, or into another
                near = [v for k, v in sc.items() if abs(k - tiles[n_after]) <= 1.0 / get_coarse().fps * get_coarse().k]
                joined = any(o is not it and o['kind'] == 'sticker' and o['first'] <= n_after
                             <= o['last'] and _inside(b, _region(o, o['last'] == n_after)) for b in [b for _, b in near] + [b_seen] for o in marks)
                if max([v for v, _ in near] or [0.0]) < CONFIRM and not joined:   # mark showing then, sure or not
                    t_seen, t_gone, b_seen = t_last, tiles[after[0]], box1
                    notes.append('not followed past the tile the AI saw it gone on (no strong match there)')
            if t_seen >= t_last:
                anchor, b_anchor, gone = t_seen, b_seen, t_gone
                if t_seen > t_last + 0.5:
                    notes.append(f'followed past its last tile to {t_seen:.2f} s')
        if gone is None:
            end_f = state.get('last')
            if end_f is None:                            # the file's real last frame (its stated length can run over)
                i_end, f_end = decode(max(0.0, dur - 1.0), dur + 1.0)
                end_f = state['last'] = (i_end + len(f_end) - 1) if len(f_end) else last_frame
            notes.append('visible to the last frame')
        else:
            t_b = max(gone, anchor + 2.0 / fps)
            i0, fr = decode(anchor, t_b)
            cuts = [c - i0 for c in cut_frames]
            idx, how = (None, 'no frames')               # idx: the first frame without it
            if len(fr) >= 2 and sticker:
                c1 = min([c for c in cuts if 1 < c < len(fr)] or [len(fr)])  # the picture without it: before the next cut
                j, bj = track_native(fr[:c1], b_anchor, True, plate=fr[c1 - 1])
                if j > 0 or len(fr) <= 2:
                    idx, how = j + 1, 'followed'
                    w = walk_out(fr[max(0, j - 3):c1], bj, idx - max(0, j - 3), False, cap=WALK_CAP)
                    if w is not None and w + max(0, j - 3) > idx:
                        how += f', {w + max(0, j - 3) - idx} faint frames after'
                        idx = w + max(0, j - 3)
                    c = _snap_cut(idx, cuts, len(fr))
                    if c is not None:
                        idx, how = c, 'on a cut'
                    if idx >= len(fr):                   # still there at the bracket's end: the next tile decides
                        idx, how = None, 'still there at the end of the bracket'
            if idx is None and len(fr) >= 2:
                idx, how = change_point(fr, b_anchor, False, cuts)
                if idx is not None and how not in ('on a cut', 'abrupt'):
                    w = walk_out(fr, b_anchor, idx, False)
                    how += f', {w - idx} faint frames after' if w > idx else ''
                    idx = w
            if idx is None:
                end_f = int(round((anchor + t_b) / 2 * fps))
                notes.append(f'end not measured ({how}); between {anchor:.2f} and {t_b:.2f} s')
            else:
                end_f = i0 + idx - 1
                notes.append(f'end {how}')
            if f_with is None and len(fr) >= 2 and not sticker:
                f_with = fr[:idx] if idx else fr[:1]
        end_f = max(start_f, min(last_frame, end_f))
        row['start_s'], row['end_s'] = round(start_f / fps, 4), round(end_f / fps, 4)
        row['end_exclusive_s'] = round((end_f + 1) / fps, 4)
        if sticker:                                       # the AI's box: pixel boxes cut tilted or moving items short
            notes.append('box as marked')
        elif f_with is not None:
            row['parts'] = [snap_edges(f_with[-1], p) for p in it['parts']]
            notes.append('parts snapped to straight edges')
            if not it.get('sure', True) and several_pictures(f_with[-1], row['parts']):
                row['sure'] = True
                notes.append('made sure: the pixels show several pictures side by side')
        row['timing'] = '; '.join(notes)
        out.append(row)
    return out


# ------------------------------------------------------------------ into the overlay inventory

def to_overlays(items, coverage_complete):
    """Overlay inventory entries (style_import_sources) from timed items, and the coverage of sticker and pip.
    Sure items are reviewed (the AI looked); unsure ones stay candidates with the AI's reason."""
    out = []
    for it in items:
        sure = it.get('sure', True)
        what = it.get('what') or it['kind']
        entry = {'start_s': it['start_s'], 'end_s': it.get('end_exclusive_s', it['end_s']), 'status': 'reviewed' if sure else 'candidate',
                 'evidence': f"marked on contact sheets (tiles {it['first']}-{it['last']}): {what}; {it.get('timing', '')}"
                             + ('' if sure else f"; not sure: {it.get('why') or 'no reason given'}"),
                 'anchor': what}
        if it['kind'] == 'sticker':
            x0, y0, x1, y1 = it['box']
            entry.update(kind='sticker', box=[x0, y0, round(x1 - x0, 4), round(y1 - y0, 4)])
        else:
            entry.update(kind='pip', source_kind='unknown',
                         parts=[[p[0], p[1], round(p[2] - p[0], 4), round(p[3] - p[1], 4)] for p in it['parts']])
        out.append(entry)
    level = 'complete' if coverage_complete else 'partial'
    return out, {'sticker': level, 'pip': level}


# ------------------------------------------------------------------ Learn's two steps

def prepare_report(reference, out):
    """Contact sheets for an importer report's reference video, in out (a private folder): moments from its grey
    analysis frames and its cuts. Returns the request (sheets, tiles, question)."""
    import letitedit.looks.style_import as SI
    rep = json.loads(Path(reference).read_text(encoding='utf-8-sig'))
    video = rep['file']
    info = SI.probe(video)
    info['path'] = str(video)
    frames, _, afps = SI.picture_frames(video, info)
    cuts = [float(c['t']) for c in rep.get('cuts', []) if 't' in c]
    rows = moments(frames, afps, cuts, info['duration'])
    req = sheets(video, info, rows, out)
    req['cuts'] = cuts
    req['report'] = str(Path(reference).resolve())
    Path(out, 'marks-request.json').write_text(json.dumps(req, indent=1), encoding='utf-8')
    return {'request': str(Path(out, 'marks-request.json')), 'sheets': req['sheets'], 'tiles': len(req['tiles']),
            'tiles_per_sheet': max(1, len(req['tiles']) // max(1, len(req['sheets']))), 'question': req['question']}


def apply(request, pages):
    """The marked items timed by pixels, as overlay inventory entries. request: marks-request.json (path or dict).
    pages: the AI's answers, [{tiles: [first, last], items: [...]}] (or {items} for all tiles at once). Coverage is
    complete only when the pages cover every tile."""
    import letitedit.looks.style_import as SI
    req = json.loads(Path(request).read_text(encoding='utf-8-sig')) if not isinstance(request, dict) else request
    numbers = [t['n'] for t in req['tiles']]
    if isinstance(pages, dict):
        pages = [{'tiles': [numbers[0], numbers[-1]], **pages}]
    batches, seen, dropped = [], set(), 0
    for page in pages:
        lo, hi = (int(v) for v in page.get('tiles') or [numbers[0], numbers[-1]])
        items, bad = parse({'items': page.get('items', [])}, [t for t in req['tiles'] if lo <= t['n'] <= hi])
        dropped += bad
        seen.update(n for n in numbers if lo <= n <= hi)
        batches.append((items, (lo, hi)))
    items = join(sorted(batches, key=lambda b: b[1][0]))
    info = SI.probe(req['video'])
    rows = timed(req['video'], info, req, items, req.get('cuts', ()))
    overlays, coverage = to_overlays(rows, seen >= set(numbers))
    return {'overlays': overlays, 'coverage': coverage, 'items': rows, 'dropped_items': dropped,
            'tiles_marked': len(seen), 'tiles': len(numbers)}
