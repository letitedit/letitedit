"""Reference video measuring: numbers that describe how any finished video is made (B3).

    measure(video, every_s=2.0, frames=24, ...) -> report dict (cached per file content and settings)

What is measured (every number comes with the settings that produced it):
  duration           ffprobe
  shots              cuts where ffmpeg's scene score passes cut_above (same method as checks.picture_change); count,
                     median / quartile lengths, longest shots, cuts per minute
  speech             speech.words (Whisper transcript with word times): words, words per minute over the whole video
                     and over the time with speech; time with speech = word spans joined across gaps under pause_s
  sound kinds        model_tools.hear (CLAP, default labels, a window_s window every every_s): each window's softmax
                     highest label put in a group (speech / music / effects / other, grouped from the default label
                     list) -> share of windows per group; also the softmax summed per group and averaged (that sum
                     grows with the number of labels in a group: 7 speech, ~58 music labels)
  loudness           checks.sound_change: integrated LUFS, loudness range, true peak, louder / quieter stretches
  colour             `frames` frames sampled evenly: average brightness (Rec.709 luma 0-255), saturation (HSV S 0-255),
                     dominant colours (k-means over the pooled pixels, `colours` clusters, share of pixels each)
  on-screen text     text-like regions per sampled frame, found with OpenCV (see _text_regions: morphological gradient,
                     Otsu threshold, horizontal closing, boxes shaped like lines of text with high contrast). This
                     measures high-contrast line-shaped regions, which includes some non-text (signs, stripes, grilles).
                     When a footage log (shot_log) is already cached for the file, its 'text' field is reported too.
  contact sheets     the sampled frames as PNG sheets (per_sheet frames each), labelled with their times
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import math
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'reference'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
VERSION = 2


def clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:04.1f}'


def _ff():
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def duration(video):
    import letitedit.footage.speech as speech
    return float(speech._duration(str(video)))


def grab(video, t, out_png, width=None):
    """One frame at t seconds (fast seek) as a PNG; width None = full size."""
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    args = [_ff(), '-v', 'error', '-y', '-ss', f'{max(0.0, float(t)):.3f}', '-i', str(video), '-frames:v', '1']
    if width:
        args += ['-vf', f'scale={int(width)}:-2']
    subprocess.run(args + [str(out_png)], capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return Path(out_png) if Path(out_png).exists() else None


def grab_many(video, times, folder, width=None, workers=4):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda it: grab(video, it[1], folder / f'f_{it[0]:04d}_{it[1]:.2f}.png', width),
                           enumerate(times)))


def scene_cuts(video, cut_above=0.15, start_s=None, end_s=None):
    """Times (s) where ffmpeg's scene score passes cut_above."""
    import re
    args = [_ff(), '-hide_banner']
    if start_s is not None:
        args += ['-ss', f'{float(start_s):.3f}']
    args += ['-i', str(video)]
    if end_s is not None:
        args += ['-t', f'{float(end_s) - float(start_s or 0):.3f}']
    args += ['-vf', f"scale=320:-2,select='gt(scene,{float(cut_above):.3f})',showinfo", '-an', '-f', 'null', '-']
    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    t0 = float(start_s or 0)
    return [t0 + float(x) for x in re.findall(r'pts_time:([\d.]+)', r.stderr)]


def _q(vals, p):
    return round(float(np.percentile(vals, p)), 2) if len(vals) else None


def _shots(video, dur, cut_above):
    cuts = [c for c in scene_cuts(video, cut_above) if 0 < c < dur]
    edges = [0.0] + cuts + [dur]
    spans = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.05]
    lengths = [b - a for a, b in spans]
    return {'count': len(spans), 'cuts_per_minute': round(max(0, len(spans) - 1) / (dur / 60), 2) if dur else None,
            'median_s': _q(lengths, 50), 'quartiles_s': [_q(lengths, 25), _q(lengths, 75)],
            'shortest_s': round(min(lengths), 2) if lengths else None,
            'longest': [{'from': clock(a), 'to': clock(b), 's': round(b - a, 2)}
                        for a, b in sorted(spans, key=lambda r: r[0] - r[1])[:6]],
            'cuts_s': [round(c, 2) for c in cuts],
            'settings': {'cut_above': cut_above, 'method': 'ffmpeg scene score on a 320 px wide copy'}}


def _speech(video, dur, pause_s):
    import letitedit.footage.speech as speech
    ws = speech.words(str(video))
    spans = []
    for w in ws:
        s, e = float(w['s']), float(w.get('e', w['s']))
        if spans and s - spans[-1][1] < pause_s:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    talk = sum(b - a for a, b in spans)
    return {'words': len(ws), 'words_per_minute': round(len(ws) / (dur / 60), 1) if dur else None,
            'words_per_minute_while_talking': round(len(ws) / (talk / 60), 1) if talk > 0 else None,
            'speech_s': round(talk, 1), 'speech_share': round(talk / dur, 3) if dur else None,
            'engine': speech.engine() if hasattr(speech, 'engine') else None,
            'settings': {'pause_s': pause_s, 'what': 'time with speech = word spans joined across gaps under pause_s'}}


def label_groups():
    """The default CLAP labels grouped as speech / music / effects / other (from the sections of DEFAULT_LABELS)."""
    import letitedit.sound.model_tools as model_tools
    labels = list(model_tools.DEFAULT_LABELS)
    i_vehicle = labels.index('a car engine idling')
    i_music = labels.index('funk music')
    i_energy = labels.index('loud')
    groups = {}
    for i, lab in enumerate(labels):
        if i < i_vehicle:
            g = 'speech' if lab in ('a man speaking', 'a woman speaking', 'a child speaking', 'people talking',
                                    'whispering', 'shouting', 'singing') else 'effects'
        elif i < i_music:
            g = 'effects'
        elif i < i_energy:
            g = 'music'
        else:
            g = 'other'
        if lab in ('silence', 'a quiet room', 'room tone'):
            g = 'other'
        groups[lab] = g
    return groups


def _sound_kinds(video, every_s, window_s):
    import letitedit.sound.model_tools as model_tools
    rep = model_tools.hear(str(video), every_s=every_s, window_s=window_s, top='all')
    groups = label_groups()
    names = ['speech', 'music', 'effects', 'other']
    sums, wins, timeline = {g: 0.0 for g in names}, {g: 0 for g in names}, []
    for seg in rep['segments']:
        tot = {g: 0.0 for g in names}
        for lab, v in seg['labels']:
            tot[groups.get(lab, 'other')] += v
        lab0, v0 = seg['labels'][0]
        top = groups.get(lab0, 'other')
        wins[top] += 1
        for g in names:
            sums[g] += tot[g]
        timeline.append(f"{clock(seg['start'])} {top}: {lab0} {v0:.2f}")
    n = max(1, len(rep['segments']))
    return {'share_of_windows_by_top_label': {g: round(wins[g] / n, 3) for g in names},
            'summed_score_share': {g: round(sums[g] / n, 3) for g in names},
            'windows': timeline, 'model': rep.get('model'),
            'settings': {'every_s': every_s, 'window_s': window_s, 'labels': 'model_tools.DEFAULT_LABELS',
                         'score': 'softmax over all labels; share_of_windows_by_top_label: the group of each '
                                  "window's highest label; summed_score_share: softmax summed per group and averaged "
                                  '(grows with the number of labels in a group)',
                         'groups': {g: sum(1 for v in groups.values() if v == g) for g in names}}}


def _text_regions(grey, min_h=0.012, max_h=0.15, min_aspect=2.0, min_fill=0.45, min_contrast=50.0):
    """Boxes (x0, y0, x1, y1 as fractions) of line-shaped high-contrast regions in a grey uint8 image."""
    import cv2
    H, W = grey.shape
    grad = cv2.morphologyEx(grey, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, W // 70), 1)))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (min_h * H <= h <= max_h * H) or w < min_aspect * h:
            continue
        if cv2.countNonZero(joined[y:y + h, x:x + w]) / float(w * h) < min_fill:
            continue
        patch = grey[y:y + h, x:x + w]
        if float(np.percentile(patch, 95)) - float(np.percentile(patch, 5)) < min_contrast:
            continue
        out.append((x / W, y / H, (x + w) / W, (y + h) / H))
    return out


TEXT_SETTINGS = {'width': 640, 'min_h': 0.012, 'max_h': 0.15, 'min_aspect': 2.0, 'min_fill': 0.45,
                 'min_contrast': 50.0, 'min_area': 0.002}


def text_of(png, settings=None):
    import cv2
    st = {**TEXT_SETTINGS, **(settings or {})}
    img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    if img.shape[1] != st['width']:
        img = cv2.resize(img, (st['width'], round(img.shape[0] * st['width'] / img.shape[1])))
    return _text_regions(img, st['min_h'], st['max_h'], st['min_aspect'], st['min_fill'], st['min_contrast'])


def _picture(pngs, times, colours, text_settings):
    import cv2
    st = {**TEXT_SETTINGS, **(text_settings or {})}
    lum, sat, pool, per_frame = [], [], [], []
    grid = np.zeros((3, 3), int)
    with_text = 0
    for p, t in zip(pngs, times):
        if p is None:
            continue
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        small = cv2.resize(bgr, (160, max(1, round(bgr.shape[0] * 160 / bgr.shape[1]))))
        rgb = small[:, :, ::-1].astype(np.float32)
        lum.append(float((0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]).mean()))
        sat.append(float(cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[:, :, 1].mean()))
        pool.append(rgb.reshape(-1, 3)[::4])
        boxes = text_of(p, st)
        area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
        has = area >= st['min_area']
        with_text += has
        if has:
            for b in boxes:
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                grid[min(2, int(cy * 3)), min(2, int(cx * 3))] += 1
        per_frame.append({'t': round(t, 2), 'brightness': round(lum[-1], 1), 'saturation': round(sat[-1], 1),
                          'text_regions': len(boxes), 'text_area': round(area, 4)})
    dominant = []
    if pool:
        px = np.concatenate(pool).astype(np.float32)
        k = max(1, min(int(colours), len(px)))
        _, lab, centres = cv2.kmeans(px, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0), 3,
                                     cv2.KMEANS_PP_CENTERS)
        counts = np.bincount(lab.ravel(), minlength=k)
        for i in np.argsort(-counts):
            r, g, b = (int(round(v)) for v in centres[i])
            dominant.append({'hex': f'#{r:02x}{g:02x}{b:02x}', 'share': round(float(counts[i]) / len(px), 3)})
    n = max(1, len(per_frame))
    rows = ('top', 'middle', 'bottom')
    cols = ('left', 'centre', 'right')
    where = {f'{rows[r]}-{cols[c]}': int(grid[r, c]) for r in range(3) for c in range(3) if grid[r, c]}
    return ({'frames_measured': len(per_frame), 'brightness_mean': round(float(np.mean(lum)), 1) if lum else None,
             'brightness_quartiles': [_q(lum, 25), _q(lum, 75)], 'saturation_mean': round(float(np.mean(sat)), 1) if sat else None,
             'saturation_quartiles': [_q(sat, 25), _q(sat, 75)], 'dominant_colours': dominant,
             'settings': {'colours': colours, 'brightness': 'Rec.709 luma 0-255 of a 160 px copy',
                          'saturation': 'HSV S 0-255', 'dominant': 'k-means (k=colours) over pooled pixels'}},
            {'frames_with_text_share': round(with_text / n, 3), 'frames_with_text': with_text,
             'where_boxes_are': where, 'method': 'opencv text-like regions (morphological gradient, Otsu, horizontal '
             'closing, line-shaped boxes with high contrast); counts line-shaped high-contrast non-text too',
             'settings': st},
            per_frame)


def _log_text(video):
    try:
        import letitedit.footage.shot_log as shot_log
        entry = shot_log.log(str(video), build=False)
    except Exception:  # noqa: BLE001
        return None
    if not entry:
        return None
    spans = [s for s in entry['shots'] if s.get('text') and not shot_log._nothing(s['text'])]
    total = sum(s['to'] - s['from'] for s in entry['shots']) or 1
    return {'source': 'footage log (shot_log, default settings, cached)', 'stretches_with_text': len(spans),
            'stretches': len(entry['shots']),
            'time_share_with_text': round(sum(s['to'] - s['from'] for s in spans) / total, 3),
            'text': [{'from': clock(s['from']), 'to': clock(s['to']), 'text': s['text'][:160]} for s in spans[:20]]}


def sheets(pngs, times, folder, per_sheet=24, cols=6, tile_w=320, prefix='sheet'):
    import letitedit.review.checks as checks
    out = []
    items = [(p, t) for p, t in zip(pngs, times) if p is not None]
    for k in range(0, len(items), per_sheet):
        chunk = items[k:k + per_sheet]
        im = checks.contact_sheet([p for p, _ in chunk], [clock(t) for _, t in chunk], cols=min(cols, len(chunk)),
                                  tile_w=tile_w)
        path = Path(folder) / f'{prefix}_{k // per_sheet + 1:02d}.png'
        im.save(path)
        out.append(str(path))
    return out


def measure(video, every_s=2.0, frames=24, per_sheet=24, sheet=True, words=True, hear=True, window_s=None,
            cut_above=0.15, pause_s=0.75, colours=5, text_settings=None, refresh=False):
    """Measure a video file (see module doc). every_s: CLAP window spacing and loudness reading spacing (s);
    window_s: CLAP window length (default = every_s); frames: frames sampled evenly for colour, text and sheets;
    words / hear False skip the transcript / CLAP parts. Returns the report; cached by file content + settings."""
    import letitedit.footage.footage_notes as footage_notes
    video = Path(video).resolve()
    if not video.is_file():
        raise FileNotFoundError(f'No file at {video}')
    every_s = float(every_s)
    window_s = float(window_s) if window_s else every_s
    settings = {'every_s': every_s, 'frames': int(frames), 'per_sheet': int(per_sheet), 'sheet': bool(sheet),
                'words': bool(words), 'hear': bool(hear), 'window_s': window_s, 'cut_above': float(cut_above),
                'pause_s': float(pause_s), 'colours': int(colours), 'text_settings': {**TEXT_SETTINGS, **(text_settings or {})}}
    h = hashlib.sha256(json.dumps({**settings, 'v': VERSION}, sort_keys=True).encode()).hexdigest()[:10]
    key = f'{footage_notes.key(str(video))}-{h}'
    cfile = CACHE / f'{key}.json'
    if cfile.exists() and not refresh:
        rep = json.loads(cfile.read_text(encoding='utf-8-sig'))
        if all(Path(p).exists() for p in rep.get('sheets', [])):
            rep['cached'] = True
            return rep
    t0 = time.monotonic()
    folder = CACHE / key
    folder.mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    rep = {'file': str(video), 'duration_s': round(dur, 2), 'duration': clock(dur), 'settings': settings}

    def part(name, fn):
        try:
            rep[name] = fn()
        except Exception as e:  # noqa: BLE001
            rep[name] = {'error': f'{type(e).__name__}: {e}'[:400]}

    part('shots', lambda: _shots(video, dur, settings['cut_above']))
    if words:
        part('speech', lambda: _speech(video, dur, settings['pause_s']))
    if hear:
        part('sound_kinds', lambda: _sound_kinds(video, every_s, window_s))

    def loud():
        import letitedit.review.checks as checks
        r = checks.sound_change(str(video), every_s=every_s)
        return r if r.get('integrated_lufs') is not None else {**r, 'note': 'no measurable audio'}
    part('loudness', loud)
    n = max(1, int(frames))
    times = [round((i + 0.5) * dur / n, 2) for i in range(n)]
    pngs = grab_many(video, times, folder / 'frames', width=TEXT_SETTINGS['width'])
    try:
        rep['colour'], rep['on_screen_text'], rep['per_frame'] = _picture(pngs, times, colours, text_settings)
    except Exception as e:  # noqa: BLE001
        rep['colour'] = {'error': f'{type(e).__name__}: {e}'[:400]}
    lt = _log_text(video)
    if lt and isinstance(rep.get('on_screen_text'), dict):
        rep['on_screen_text']['footage_log'] = lt
    rep['frame_times_s'] = times
    rep['frames_folder'] = str(folder / 'frames')
    rep['sheets'] = sheets(pngs, times, folder, per_sheet=per_sheet) if sheet else []
    rep['took_s'] = round(time.monotonic() - t0, 1)
    CACHE.mkdir(parents=True, exist_ok=True)
    cfile.write_text(json.dumps(rep, indent=1), encoding='utf-8')
    rep['cached'] = False
    return rep
