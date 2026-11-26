"""Contrast of burned-in (native subtitle) captions against the picture around them, frame by frame.

    measure(project, video=None, width=640, per_cue=2) -> {'passed', 'hard_to_read', 'cues', ...}

Two sets of frames with the export engine: the project as it is (or the delivered video), and the project with every
subtitle burn-in removed. Their difference is the caption's own ink (fill, outline, shadow). The fill is the ink near
the burn-in's fill colour. Around it, two rings are read on the captioned frame: the edge (the first pixel out, where
an outline sits) and the halo (the next HALO_PX pixels: the picture just outside a thin outline). Each ring pixel's
WCAG contrast with the fill colour is measured; the share under FLOOR (3:1, the large-text floor) is reported. A cue
is hard to read when more than WASH_SHARE of its halo is under WASH (2.5:1: close to the letters' lightness, so the
outline alone separates them) on its worst measured frame. keep=<folder> keeps the frames.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

FLOOR = 3.0          # WCAG large-text contrast: reported
WASH = 2.5           # a halo pixel under this contrast with the fill: the letters lean on their outline alone there
HALO_PX = 2          # at the measuring width: the ring just outside the edge
WASH_SHARE = 0.30    # a cue whose halo is that low this much (on its worst frame) is hard to read
_W = np.array([.2126, .7152, .0722], np.float32)


def _lin(rgb):
    c = np.asarray(rgb, np.float32) / 255
    return np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)


def _hex_rgb(colour):
    s = str(colour or '').lstrip('#')
    if len(s) == 8:        # #AARRGGBB
        s = s[2:]
    if len(s) != 6:
        return (255, 255, 255)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def without_burns(src, dst):
    """A copy of the project with every subtitle burn-in (and shadow copy) removed; the feeds stay."""
    tree = ET.parse(src)
    for parent in tree.iter():
        for f in list(parent):
            if f.tag == 'filter' and any(p.get('name') == 'mlt_service' and (p.text or '') == 'subtitle' for p in f):
                parent.remove(f)
    tree.write(dst, encoding='utf-8', xml_declaration=True)


def _video_frames(video, times, out_dir):
    import letitedit.timeline.cutpoints as cutpoints
    paths = []
    for k, t in enumerate(times):
        p = out_dir / f'v_{k:04d}.png'
        subprocess.run([cutpoints.FFMPEG, '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1', str(p)],
                       capture_output=True, creationflags=cutpoints.NO_WINDOW)
        paths.append(p)
    return paths


def frame_rows(a, b, fill, width=640):
    """(edge ratios, halo ratios) for one captioned frame `a` and its caption-free twin `b` (BGR arrays), or None."""
    fill_l = float(_lin(fill) @ _W)
    h = int(round(a.shape[0] * width / a.shape[1]))
    a = cv2.resize(a, (width, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(b, (width, h), interpolation=cv2.INTER_AREA)
    ink = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 24
    near_fill = np.abs(a.astype(np.int16) - np.array(fill[::-1], np.int16)).max(axis=2) < 48
    core = ink & near_fill
    if core.sum() < 20:
        return None
    k3 = np.ones((3, 3), np.uint8)
    d1 = cv2.dilate(core.astype(np.uint8), k3).astype(bool)
    dh = cv2.dilate(d1.astype(np.uint8), k3, iterations=HALO_PX).astype(bool)
    edge, halo = d1 & ~core, dh & ~d1
    lum = _lin(a[..., ::-1]) @ _W
    ratio = lambda m: (np.maximum(lum[m], fill_l) + .05) / (np.minimum(lum[m], fill_l) + .05)
    return ratio(edge), ratio(halo)


def measure(project, video=None, width=640, per_cue=2, cues_max=None, keep=None):
    import letitedit.review.checks as checks
    import letitedit.core.render_lock as render_lock
    timeline, path = checks.resolve(project)
    burns = list(timeline.burn_filters)
    if not burns:
        return {'passed': None, 'reason': 'no burned-in caption track'}
    main = [fp for fp in burns if fp.get('letitedit_ai:role') != 'shadow'] or burns
    fill = _hex_rgb(main[-1].get('fgcolour'))
    feed_names = {fp.get('feed', 'Subtitles') for fp in burns}
    cues = sorted({(round(s, 3), round(e, 3), text) for name, cs in timeline.subtitle_feeds.items()
                   if name in feed_names for s, e, text in cs})
    if cues_max:
        cues = cues[:cues_max]
    picks = []
    for s, e, text in cues:
        for j in range(per_cue):
            t = s + (e - s) * (j + 1) / (per_cue + 1)
            picks.append((int(round(t * timeline.fps)), t, text))
    work = Path(tempfile.mkdtemp(prefix='caption-contrast-'))
    try:
        plain = work / 'plain.mlt'
        without_burns(path, plain)
        t_plain, _ = checks.resolve(plain)
        (work / 'a').mkdir()
        (work / 'b').mkdir()
        with render_lock.slot('caption contrast', timeout_s=3600):
            plain_png = checks.render_frames(t_plain, plain, [f for f, _, _ in picks], work / 'b')
            with_png = (_video_frames(video, [t for _, t, _ in picks], work / 'a') if video
                        else checks.render_frames(timeline, path, [f for f, _, _ in picks], work / 'a'))
        rows = {}
        for (frame, t, text), pa, pb in zip(picks, with_png, plain_png):
            a, b = cv2.imread(str(pa)), cv2.imread(str(pb))
            if a is None or b is None or a.shape != b.shape:
                continue
            got = frame_rows(a, b, fill, width)
            if got is None:
                continue
            re_, rh = got
            r = rows.setdefault(text, {'at_s': round(t, 2), 'edge': [], 'halo': [], 'wash': [], 'median': []})
            r['edge'].append(float((re_ < FLOOR).mean()))
            r['halo'].append(float((rh < FLOOR).mean()))
            r['wash'].append(float((rh < WASH).mean()))
            r['median'].append(float(np.median(rh)))
        out = []
        for text, r in rows.items():
            out.append({'text': text.replace('\n', ' / ')[:90], 'at_s': r['at_s'], 'frames': len(r['halo']),
                        'edge_under_floor': round(max(r['edge']), 3), 'halo_under_floor': round(max(r['halo']), 3),
                        'halo_washed_out': round(max(r['wash']), 3),
                        'halo_median_ratio': round(min(r['median']), 2), 'hard_to_read': max(r['wash']) > WASH_SHARE})
        hard = [c for c in out if c['hard_to_read']]
        return {'passed': not hard, 'cues_measured': len(out), 'cues_total': len(cues), 'hard_to_read_count': len(hard),
                'hard_to_read': sorted(hard, key=lambda c: -c['halo_washed_out']), 'cues': out,
                'width': width, 'floor': FLOOR, 'wash': WASH, 'wash_share': WASH_SHARE, 'halo_px': HALO_PX,
                'source': 'delivered video' if video else 'export engine render',
                'method': 'captioned and caption-free frames from the export engine; their difference is the caption '
                          f'ink; fill = ink near the fill colour; edge = 1 px around it, halo = the next {HALO_PX} px '
                          f'(at {width} px wide); WCAG contrast with the fill colour (the share under {FLOOR:g}:1 '
                          f'is reported); hard to read when over {WASH_SHARE:.0%} of the halo is under {WASH:g}:1 (close '
                          "to the letters' lightness, so the outline alone separates them) on a cue's worst frame"}
    finally:
        if keep:
            shutil.copytree(work, keep, dirs_exist_ok=True)
        shutil.rmtree(work, ignore_errors=True)
