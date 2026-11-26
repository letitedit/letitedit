"""Obstacles, placement and violations.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import os
import subprocess
from dataclasses import dataclass, field
import letitedit.timeline.timeline_model as tm
from letitedit.pictures.caption_layout_frame import (  # noqa: E402
    FFMPEG, INF, NO_WINDOW, SEVERITY, _area, _fmt, _inter, _rbox, _union
)
from letitedit.pictures.caption_layout_words import (  # noqa: E402
    sentence_end, suspected_join
)
from letitedit.pictures.caption_layout_cues import (  # noqa: E402
    cue_issues
)


# ============================================================================ obstacles

@dataclass
class Obstacle:
    kind: str                     # zone | protected | face | text
    name: str
    start: float
    end: float
    boxes: list                   # [(t, box)] samples; [(None, box)] is static
    hard: bool = False

    def box_in(self, s, e):
        """Where it is between s and e (the union of its samples then), or None when it isn't there."""
        if e <= self.start or s >= self.end:
            return None
        if len(self.boxes) == 1 and self.boxes[0][0] is None:
            return self.boxes[0][1]
        inside = [b for t, b in self.boxes if s - 0.05 <= t <= e + 0.05]
        if not inside:
            near = min(self.boxes, key=lambda tb: min(abs(tb[0] - s), abs(tb[0] - e)))
            if min(abs(near[0] - s), abs(near[0] - e)) <= 1.0:
                inside = [near[1]]
        return _union(inside)

    def times_over(self, box, s, e):
        return [t for t, b in self.boxes if t is not None and s - 0.05 <= t <= e + 0.05 and _inter(box, b) > 0]


def protected_obstacles(protected, frame, total_s):
    """Explicit regions: [{box: [x0, y0, x1, y1] (0-1 fractions or pixels), start?, end?, hard? (true), name?}], or a
    moving one {keys: [[t, [x0, y0, x1, y1]], ...], ...} (straight-line movement between keys, there only between the
    first and last key)."""
    out = []
    W, H = frame.width, frame.height

    def px(b):
        b = [float(v) for v in b]
        if len(b) != 4:
            raise ValueError(f'a protected box is [x0, y0, x1, y1]; got {b}')
        if max(abs(v) for v in b) <= 1.0:
            b = [b[0] * W, b[1] * H, b[2] * W, b[3] * H]
        return (min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3]))
    for n, p in enumerate(protected or []):
        if not isinstance(p, dict):
            raise ValueError(f'protected[{n}] is {{box, start?, end?, hard?}} or {{keys: [[t, box], ...]}}; got {p!r}')
        name = str(p.get('name') or f'protected region {n + 1}')
        hard = bool(p.get('hard', True))
        if p.get('keys'):
            keys = sorted(((float(t), px(b)) for t, b in p['keys']), key=lambda k: k[0])
            samples = []
            for (t0, b0), (t1, b1) in zip(keys, keys[1:]):
                steps = max(1, int((t1 - t0) / 0.1))
                for s in range(steps):
                    f = s / steps
                    samples.append((t0 + f * (t1 - t0), tuple(b0[i] + f * (b1[i] - b0[i]) for i in range(4))))
            samples.append(keys[-1])
            out.append(Obstacle('protected', name, keys[0][0], keys[-1][0] + 1e-3, samples, hard))
        elif p.get('box') is not None:
            s = float(p.get('start', 0.0))
            e = float(p.get('end', total_s + 1))
            out.append(Obstacle('protected', name, s, e, [(None, px(p['box']))], hard))
        else:
            raise ValueError(f'protected[{n}] needs box or keys')
    return out


def zone_obstacles(frame, hard=True):
    return [Obstacle('zone', z['name'], -1.0, 1e9, [(None, z['box'])], hard) for z in frame.zones]


def _alpha_boxes(path, start_s, dur_s, every_s, frame):
    """[(t from start_s, box)] of the visible pixels of an overlay file (alpha .mov or .png), one ffmpeg pass. With
    caption_fit_reuse on (T362), read back for a file (size and time), stretch and frame size measured before."""
    import letitedit.pictures.caption_reuse as caption_reuse
    if not caption_reuse.enabled():
        return _measure_alpha_boxes(path, start_s, dur_s, every_s, frame)
    try:
        key = caption_reuse.alpha_key(path, start_s, dur_s, every_s, frame)
    except Exception:  # noqa: BLE001
        return _measure_alpha_boxes(path, start_s, dur_s, every_s, frame)
    got = caption_reuse.read_alpha(key)
    if got is None:
        got = _measure_alpha_boxes(path, start_s, dur_s, every_s, frame)
        caption_reuse.write_alpha(key, got)
    return got


def _measure_alpha_boxes(path, start_s, dur_s, every_s, frame):
    import numpy as np
    k = 4
    w, h = max(2, frame.width // k), max(2, frame.height // k)
    if str(path).lower().endswith('.png'):
        args = [FFMPEG, '-v', 'error', '-i', str(path)]
        rate = []
    else:
        args = [FFMPEG, '-v', 'error', '-ss', f'{max(0.0, start_s):.3f}', '-t', f'{max(0.05, dur_s):.3f}', '-i', str(path)]
        rate = [f'fps=1/{every_s:g}']
    vf = ','.join(rate + [f'scale={w}:{h}', 'format=rgba'])
    r = subprocess.run([str(a) for a in args] + ['-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                       capture_output=True, creationflags=NO_WINDOW, timeout=120)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(a) // (w * h * 4)
    out = []
    if n == 0:
        return out
    a = a[:n * w * h * 4].reshape(n, h, w, 4)
    for i in range(n):
        m = a[i, :, :, 3] > 24
        ys, xs = np.nonzero(m)
        if len(xs):
            sx, sy = frame.width / w, frame.height / h
            out.append((0.0 if not rate else i * every_s,
                        (xs.min() * sx, ys.min() * sy, (xs.max() + 1) * sx, (ys.max() + 1) * sy)))
    return out


def overlay_text_obstacles(timeline, frame, skip_tracks, every_s=0.5):
    """Other text drawn over the picture: Python graphics and .ass text clips on video tracks not being laid out,
    where their rendered files have visible pixels (sampled every every_s seconds)."""
    out = []
    fps = timeline.fps
    for t in timeline.video_tracks():
        if t.name in skip_tracks or 'video' in (t.hide or ''):
            continue
        for it in t.items:
            if it.elem is None or not it.resource or not os.path.exists(it.resource):
                continue
            p = tm.props(it.elem)
            kind = None
            if p.get('letitedit_ai:graphic'):
                try:
                    kind = 'graphic ' + str(json.loads(p['letitedit_ai:graphic']).get('template', ''))
                except ValueError:
                    kind = 'graphic'
            elif p.get('letitedit_ai:made'):
                try:
                    if json.loads(p['letitedit_ai:made']).get('kind') == 'ass':
                        kind = 'ass text'
                except ValueError:
                    pass
            if not kind:
                continue
            s, e = it.start / fps, it.end / fps
            samples = [(s + dt, b) for dt, b in _alpha_boxes(it.resource, it.in_ / fps, e - s, every_s, frame)]
            if samples and samples[0][0] is not None and len(samples) == 1 and str(it.resource).lower().endswith('.png'):
                samples = [(None, samples[0][1])]
            if samples:
                out.append(Obstacle('text', f'{kind} on {t.name}', s, e, samples, False))
    return out


# ============================================================================ placement

@dataclass
class Weights:
    face: float = 12.0
    face_any: float = 3.0
    text: float = 30.0
    soft_protected: float = 10.0
    soft_zone: float = 20.0
    pref: float = 0.4
    move: float = 0.6             # leaving the current place at all
    switch_shot: float = 3.0
    switch_phrase: float = 2.0
    switch_cut: float = 0.4
    shrink: float = 6.0
    unsafe: float = 4.0           # ink outside the safe area (margins, platform bands)


def placement_cost(box, s, e, obstacles, frame, w):
    """(cost, hard) for a caption ink box shown from s to e: faces covered, other text overlapped, soft regions; hard
    when it leaves the frame, enters a hard region or a hard platform overlay."""
    if box is None:
        return 0.0, False
    W, H = frame.width, frame.height
    if box[0] < -0.5 or box[1] < -0.5 or box[2] > W + 0.5 or box[3] > H + 0.5:
        return INF, True
    cost, hard = 0.0, False
    a_box = max(1.0, _area(box))
    out_of_safe = 1.0 - _inter(box, frame.safe) / a_box
    if out_of_safe > 0.002:
        cost += w.unsafe * (0.5 + out_of_safe)
    for ob in obstacles:
        ob_box = ob.box_in(s, e)
        if not ob_box:
            continue
        i = _inter(box, ob_box)
        if i <= 0:
            continue
        if ob.kind == 'face':
            share = i / max(1.0, _area(ob_box))
            if share > 0:
                if ob.hard:
                    hard = True
                cost += w.face_any + w.face * share   # over a speaker's mouth or eyes at all is what matters
        elif ob.kind == 'text':
            cost += w.text * (0.5 + i / max(1.0, min(a_box, _area(ob_box))))
            hard = hard or ob.hard
        elif ob.kind == 'zone':
            hard = hard or ob.hard
            cost += w.soft_zone * i / a_box
        else:
            hard = hard or ob.hard
            cost += w.soft_protected * i / a_box
    return (INF if hard else cost), hard


def solve_places(unary, cues, cuts, weights):
    """Viterbi over cues x candidate places. unary[i][k] = cost of cue i at place k (INF: not allowed). Changing place
    costs more inside a shot or a phrase (hysteresis) than at a cut. Returns the place index per cue, and whether a
    cue had no allowed place (it then takes the least bad)."""
    n = len(cues)
    if n == 0:
        return []
    m = len(unary[0])
    BIG = 1e9
    dp = [[min(u, BIG) for u in unary[0]]]
    bk = [[0] * m]
    for i in range(1, n):
        a, b = cues[i - 1], cues[i]
        cut = any(a.start + 0.01 < c <= b.end - 0.01 for c in cuts)
        phrase = b.start - a.end < 0.4 and not (a.tokens and sentence_end(a.tokens[-1]))
        sw = weights.switch_cut if cut else weights.switch_shot
        if phrase and not cut:
            sw = max(sw, weights.switch_phrase)
        row, brow = [], []
        for k in range(m):
            u = min(unary[i][k], BIG)
            best, arg = INF, 0
            for q in range(m):
                v = dp[-1][q] + (0.0 if q == k else sw)
                if v < best:
                    best, arg = v, q
            row.append(best + u)
            brow.append(arg)
        dp.append(row)
        bk.append(brow)
    k = min(range(m), key=lambda q: dp[-1][q])
    path = [k]
    for i in range(n - 1, 0, -1):
        k = bk[i][k]
        path.append(k)
    return list(reversed(path))


# ============================================================================ violations

def _violation(kind, layer, cue, detail, stage, at=None, box=None, measured=None, limit=None, evidence='measured',
               other=None, start=None, end=None):
    s = cue.start if cue is not None else (start or 0.0)
    e = cue.end if cue is not None else (end or 0.0)
    v = {'kind': kind, 'severity': SEVERITY.get(kind, 'warning'), 'stage': stage, 'layer': layer,
         'cue': cue.key if cue is not None else None, 'start': round(s, 3), 'end': round(e, 3),
         'start_clock': _fmt(s), 'end_clock': _fmt(e), 'detail': detail, 'evidence': evidence}
    if at is not None:
        v['at'] = round(at, 3)
        v['at_clock'] = _fmt(at)
    if box is not None:
        v['box'] = _rbox(box)
    if measured is not None:
        v['measured'] = measured
    if limit is not None:
        v['limit'] = limit
    if other:
        v['other'] = other
    return v


def _place_violations(layer_name, cue, box, s, e, obstacles, frame, stage, evidence='measured'):
    out = []
    if box is None:
        return out
    W, H = frame.width, frame.height
    zone_hit = False
    for ob in obstacles:
        ob_box = ob.box_in(s, e)
        if not ob_box:
            continue
        i = _inter(box, ob_box)
        if i <= 0:
            continue
        times = ob.times_over(box, s, e)
        at = times[0] if times else None
        if ob.kind == 'face':
            share = i / max(1.0, _area(ob_box))
            if share > 0:
                out.append(_violation('covers_face', layer_name, cue, f'covers {share:.0%} of a face', stage, at=at,
                                      box=box, measured=round(share, 3), limit=0,
                                      evidence=f'{evidence}; face box from a detector model (OpenCV YuNet, not '
                                               f'calibrated here) on frames rendered by melt',
                                      other={'face': _rbox(ob_box)}))
        elif ob.kind == 'text':
            out.append(_violation('covers_text', layer_name, cue, f'overlaps {ob.name}', stage, at=at, box=box,
                                  evidence=evidence, other={'text': ob.name, 'text_box': _rbox(ob_box)}))
        elif ob.kind == 'zone':
            zone_hit = True
            out.append(_violation('platform_overlay', layer_name, cue, f'under the platform overlay "{ob.name}"', stage,
                                  box=box, evidence=evidence, other={'zone': ob.name, 'zone_box': _rbox(ob_box)}))
        else:
            out.append(_violation('protected_region', layer_name, cue, f'covers {ob.name}', stage, at=at, box=box,
                                  evidence=evidence, other={'region': ob.name, 'region_box': _rbox(ob_box),
                                                            'hard': ob.hard}))
    if box[0] < -0.5 or box[1] < -0.5 or box[2] > W + 0.5 or box[3] > H + 0.5:
        out.append(_violation('outside_frame', layer_name, cue, 'the caption runs off the frame', stage, box=box,
                              evidence=evidence))
    elif not zone_hit:
        sx0, sy0, sx1, sy1 = frame.safe
        if box[0] < sx0 - 2 or box[2] > sx1 + 2 or box[1] < sy0 - 2 or box[3] > sy1 + 2:
            out.append(_violation('outside_safe', layer_name, cue, 'the caption reaches outside the safe area', stage,
                                  box=box, evidence=evidence, other={'safe': _rbox(frame.safe)}))
    return out


def _timing_violations(layer_name, cue, rules, stage, check_cps=True):
    out = []
    d = cue.end - cue.start
    chars = len(' '.join(cue.tokens))
    if check_cps and d > 0 and chars / d > rules.max_cps:
        out.append(_violation('reading_speed', layer_name, cue, f'{chars / d:.0f} characters a second (at most '
                              f'{rules.max_cps:g})', stage, measured=round(chars / d, 1), limit=rules.max_cps))
    if d < rules.min_dur - 0.01:
        out.append(_violation('too_short', layer_name, cue, f'on screen {d:.2f} s (at least {rules.min_dur:g} s)',
                              stage, measured=round(d, 2), limit=rules.min_dur))
    if d > rules.max_dur + 0.01:
        out.append(_violation('too_long', layer_name, cue, f'on screen {d:.1f} s (at most {rules.max_dur:g} s)', stage,
                              measured=round(d, 2), limit=rules.max_dur))
    times = cue.times if cue.times and all(cue.times) else None
    for issue in cue_issues(cue.tokens, times, rules):
        if 'sentence' in issue or 'ends on' in issue:
            out.append(_violation('bad_break', layer_name, cue, issue, stage,
                                  evidence='linguistic heuristic (an editorial judgement, not a measurement)'))
    for tok in cue.tokens:
        if suspected_join(tok):
            out.append(_violation('suspected_missing_space', layer_name, cue, f'"{tok}" looks like two words without a '
                                  f'space (left as written: no transcript evidence; spelling is corrected separately)',
                                  stage))
    return out
