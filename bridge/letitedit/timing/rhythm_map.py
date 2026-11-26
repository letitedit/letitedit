"""The rhythm map (timing view 'map'): one picture per page of an edit's timing, plus the numbers behind it.

Lanes, top to bottom, on one time axis: thumbnails; cuts (each flagged with its offset in frames from the nearest
music beat when a music lane exists, and whether it lands on action); shots (size: CU closeup, MS medium, WS wide,
? unknown; length); motion energy with the camera's own move removed, the camera's labels, bursts of motion and
visual beats; where the eye likely is (attention x and y); speech (words, pauses, thought ends); music (beats,
downbeats, sections); graphics and captions; loudness with sound onsets. Under them, the sections (chapter: or
beat: markers, else automatic from changes of pace) with their numbers: cut rate, median shot length, motion
energy, share of cuts on action, holds.

Every number comes from timing_signals (the shared store) and is also in the result; thresholds come from
timing_thresholds.json ('map.*') and are reported.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import math
import os
import re
import time
from pathlib import Path

import numpy as np

import letitedit.timing.timing_signals as ts
import letitedit.timing.timing_views as timing_views

MAPS = ts.CACHE / 'maps'
FONT_DIR = Path(_SAI_ROOT) / 'fonts' / 'library'

MAP_DEFAULTS = {
    'width': 1560,              # image width (px)
    'page_s': 60.0,             # seconds per page for edits longer than one_page_s
    'one_page_s': 75.0,         # edits up to this long fit on one page
    'action_px': 1.0,           # a side of a cut 'moves' when its mean motion energy is at least this (px/frame)
    'action_frames': 4,         # ... measured over this many frames before / after the cut (not the cut frame)
    'beat_tolerance_frames': 2,  # a cut within this many frames of a beat is on the beat
    'hold_s': 4.0,              # a shot at least this long is a hold
    'pause_s': 0.3,             # gaps between words at least this long are pauses
    'auto_min_section_s': 8.0,  # automatic sections: at least this long ...
    'auto_max_sections': 6,     # ... at most this many
    'auto_penalty': 6.0,        # ... cost of one more section (higher: fewer)
    'thumb_h': 104,             # thumbnail height (px)
}

LABEL_COL = 96
CAM_COLORS = {'static': (190, 190, 190), 'pan': (66, 133, 244), 'tilt': (0, 172, 193), 'zoom': (156, 39, 176),
              'handheld': (255, 152, 0), 'whip': (229, 57, 53), None: (240, 240, 240)}
SIZE_COLORS = {'closeup': (171, 71, 188), 'medium': (66, 133, 244), 'wide': (67, 160, 71), 'unknown': (158, 158, 158)}
SIZE_CODE = {'closeup': 'CU', 'medium': 'MS', 'wide': 'WS', 'unknown': '?'}
GFX_COLORS = {'caption': (255, 213, 79), 'text': (255, 167, 38), 'graphic': (141, 110, 99)}


# ============================================================================ fonts

_FONTS = {}


def font(size, bold=False):
    from PIL import ImageFont
    key = (size, bold)
    if key in _FONTS:
        return _FONTS[key]
    f = None
    for cand in (FONT_DIR / 'Inter' / 'Inter[opsz,wght].ttf', Path(r'C:\Windows\Fonts\segoeui.ttf'),
                 Path(r'C:\Windows\Fonts\arial.ttf')):
        if cand.exists():
            try:
                f = ImageFont.truetype(str(cand), size)
                if 'Inter' in cand.name:
                    try:
                        f.set_variation_by_axes([14 if size < 20 else 24, 700 if bold else 450])
                    except Exception:  # noqa: BLE001 - older PIL / static font
                        pass
                elif bold:
                    b = cand.with_name(cand.stem + 'b.ttf')
                    if b.exists():
                        f = ImageFont.truetype(str(b), size)
                break
            except OSError:
                f = None
    if f is None:
        f = ImageFont.load_default()
    _FONTS[key] = f
    return f


def text_w(draw, s, f):
    try:
        return draw.textlength(s, font=f)
    except Exception:  # noqa: BLE001
        return len(s) * f.size * 0.55


# ============================================================================ data helpers

def wanted_lanes(extra=()):
    base = ['edit', 'frame_features', 'motion', 'visual_beats', 'motion_events', 'attention', 'shots', 'audio']
    reg = ts.lanes()
    for n in ('speech', 'music'):
        if n in reg:
            base.append(n)
    return base + [e for e in extra if e not in base and e in reg]


def cached_words(sig):
    """Words already transcribed (never transcribes): [{'w', 't0', 't1'}] in source seconds."""
    import letitedit.footage.speech as speech
    out = []
    if sig['kind'] == 'video':
        try:
            ws = speech.cached_words(sig['source'])
        except Exception:  # noqa: BLE001
            ws = None
        for w in ws or []:
            out.append({'w': w['w'], 't0': float(w['s']), 't1': float(w['e'])})
        return out, ('cached transcript of the file' if ws else None)
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.edit_sync as edit_sync
    try:
        from letitedit.timeline.timeline_speech import NOT_SPEECH
    except Exception:  # noqa: BLE001
        NOT_SPEECH = re.compile(r'music|song|score|bed|sfx|effect|sound|foley|ambien', re.I)
    script = es.read(sig['project'])
    found = False
    seen = set()
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in edit_sync.layout(t):
            if 'clip' not in it or it.get('reverse') or 'mute' in (it.get('effects') or []):
                continue
            speed = float(it.get('speed', 1.0))
            if speed > 1.5:
                continue
            a, b = float(it['in']), float(it['out'])
            try:
                ws = speech.cached_words(it['clip'], a, b)
            except Exception:  # noqa: BLE001
                ws = None
            if ws is None:
                continue
            found = True
            for w in ws:
                ws_, we_ = float(w['s']), float(w['e'])
                if max(0.0, min(we_, b) - max(ws_, a)) < 0.5 * max(1e-3, we_ - ws_):
                    continue
                t0 = s + (ws_ - a) / speed
                t1 = min(e, s + (we_ - a) / speed)
                key = (round(t0, 1), w['w'].lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append({'w': w['w'].strip(), 't0': round(t0, 3), 't1': round(t1, 3), 'id': it.get('id')})
    out.sort(key=lambda w: w['t0'])
    return out, ('cached transcripts of the clips' if found else None)


def speech_data(sig, st):
    """Words, pauses, thought ends and breaths: the speech lane (B3) when present, else cached transcripts."""
    sp = (sig['lanes'] or {}).get('speech')
    if sp and not sp.get('error') and sp.get('words') is not None:
        words = [{'w': w.get('w', ''), 't0': float(w['t0']), 't1': float(w['t1']), 'stress': w.get('stress')}
                 for w in sp.get('words') or [] if w.get('t0') is not None and w.get('t1') is not None]
        pauses = [{'t0': float(p['t0']), 't1': float(p['t1'])} for p in sp.get('pauses') or []
                  if p.get('t0') is not None]
        return {'words': words, 'pauses': pauses, 'thought_ends': sp.get('thought_ends') or [],
                'breaths': sp.get('breaths') or [],
                'source': 'speech lane (prosody)' if words else 'speech lane (prosody): no words heard'}
    words, src = cached_words(sig)
    pauses = []
    for a, b in zip(words, words[1:]):
        if b['t0'] - a['t1'] >= float(st['pause_s']):
            pauses.append({'t0': a['t1'], 't1': b['t0']})
    note = src or 'no transcript cached (letitedit_words transcribes; the speech lane adds pitch and pauses)'
    if sp and sp.get('error'):
        note += f'; speech lane failed: {sp["error"]}'
    return {'words': words, 'pauses': pauses, 'thought_ends': [], 'breaths': [], 'source': note}


def music_data(sig):
    mu = (sig['lanes'] or {}).get('music')
    if not mu or mu.get('error'):
        return None
    beats = [b for b in mu.get('beats') or [] if b.get('t') is not None]
    return {'beats': beats, 'sections': mu.get('sections') or [], 'tempo_bpm': mu.get('tempo_bpm'),
            'confidence': mu.get('beat_confidence'), 'stem': mu.get('stem')}


def cut_table(sig, st, music):
    """Every cut with its beat offset (frames) and whether it lands on action."""
    fps, F = float(sig['fps']), int(sig['frames'])
    edit = sig['lanes']['edit']
    mot = sig['lanes'].get('motion') or {}
    energy = np.array([np.nan if v is None else v for v in mot.get('energy') or [None] * F], dtype=float)
    shots = (sig['lanes'].get('shots') or {}).get('shots') or []
    k = int(st['action_frames'])
    thr = float(st['action_px'])
    beat_f = np.array([int(b.get('f', ts.fr(b['t'], fps))) for b in (music or {}).get('beats') or []], dtype=int)
    down = np.array([bool(b.get('downbeat')) for b in (music or {}).get('beats') or []], dtype=bool)
    out = []
    for c in edit.get('cuts') or []:
        f = int(c['f'])
        a0, a1 = int(c.get('f0', f)), int(c.get('f1', f))
        lo_end = min(f, a0)
        hi_start = max(f, a1) + 1 if a1 > a0 else f + 1
        before = energy[max(0, lo_end - k):lo_end]
        after = energy[hi_start:min(F, hi_start + k)]
        eb = float(np.nanmean(before)) if np.isfinite(before).any() else None
        ea = float(np.nanmean(after)) if np.isfinite(after).any() else None
        mb, ma = (eb is not None and eb >= thr), (ea is not None and ea >= thr)
        action = 'on action' if mb and ma else 'out of action' if mb else 'into action' if ma else 'still'
        rec = {'f': f, 't': ts.tsec(f, fps), 'kind': c.get('kind'), 'from_item': c.get('from_item'),
               'to_item': c.get('to_item'), 'motion_before': ts.clean(eb, 2), 'motion_after': ts.clean(ea, 2),
               'action': action}
        if c.get('detail'):
            rec['detail'] = c['detail']
        sb = next((s for s in shots if s['f0'] <= f - 1 < s['f1']), None)
        sa = next((s for s in shots if s['f0'] <= f < s['f1']), None)
        if sb and sa:
            rec['size_change'] = f'{SIZE_CODE.get(sb["size"], "?")}>{SIZE_CODE.get(sa["size"], "?")}'
        if beat_f.size:
            j = int(np.argmin(np.abs(beat_f - f)))
            rec['beat_offset_frames'] = int(f - beat_f[j])
            rec['beat_t'] = ts.tsec(int(beat_f[j]), fps)
            rec['on_downbeat'] = bool(down[j]) if down.size else False
            jd = np.flatnonzero(down)
            if jd.size:
                kd = jd[int(np.argmin(np.abs(beat_f[jd] - f)))]
                rec['downbeat_offset_frames'] = int(f - beat_f[kd])
        out.append(rec)
    return out


def _auto_sections(sig, st, cuts):
    """Sections from changes of pace: 1-second bins of cut count and motion energy, split by optimal partitioning
    (least squares per section + a penalty per section, at least auto_min_section_s each)."""
    fps, F = float(sig['fps']), int(sig['frames'])
    dur = F / fps
    nb = max(1, int(math.ceil(dur)))
    cut_n = np.zeros(nb)
    for c in cuts:
        cut_n[min(nb - 1, int(c['t']))] += 1
    mot = sig['lanes'].get('motion') or {}
    e = np.array([np.nan if v is None else v for v in mot.get('energy') or [None] * F], dtype=float)
    em = np.array([np.nanmean(e[int(i * fps):int((i + 1) * fps)]) if np.isfinite(e[int(i * fps):int((i + 1) * fps)]).any()
                   else 0.0 for i in range(nb)])
    # pace: cuts per 5 s around each second, energy; both scaled to unit spread
    k = np.ones(5) / 5.0
    rate = np.convolve(cut_n, k, mode='same') * 60.0
    X = np.stack([rate / (np.std(rate) + 1e-6), em / (np.std(em) + 1e-6)], 1)
    m = max(2, int(round(float(st['auto_min_section_s']))))
    if nb < 2 * m:
        return [{'f0': 0, 'f1': F, 'label': 'whole', 'source': 'automatic (too short to split)'}]
    cs = np.vstack([np.zeros((1, 2)), np.cumsum(X, 0)])
    cs2 = np.vstack([np.zeros((1, 2)), np.cumsum(X * X, 0)])

    def cost(a, b):
        n = b - a
        s = cs[b] - cs[a]
        return float(((cs2[b] - cs2[a]) - s * s / n).sum())
    pen = float(st['auto_penalty'])
    best = [0.0] + [math.inf] * nb
    prev = [0] * (nb + 1)
    count = [0] * (nb + 1)
    for b in range(m, nb + 1):
        for a in range(0, b - m + 1):
            if a != 0 and a < m:
                continue
            if best[a] == math.inf:
                continue
            v = best[a] + cost(a, b) + pen
            if v < best[b] and count[a] + 1 <= int(st['auto_max_sections']):
                best[b], prev[b], count[b] = v, a, count[a] + 1
    edges = [nb]
    b = nb
    while b > 0:
        b = prev[b]
        edges.append(b)
    edges = sorted(set(edges))
    # inner edges move to the nearest cut within 3 s (a section starts with a shot)
    cut_f = sorted(int(c['f']) for c in cuts)
    fedges = [min(F, int(round(x * fps))) for x in edges]
    for k in range(1, len(fedges) - 1):
        half = 0.5 * m * fps          # a snap never leaves a section under half the minimum length
        near = [c for c in cut_f if abs(c - fedges[k]) <= 3 * fps and fedges[k - 1] + half <= c <= fedges[k + 1] - half]
        if near:
            fedges[k] = min(near, key=lambda c: abs(c - fedges[k]))
    out = []
    for i, (a, b) in enumerate(zip(fedges, fedges[1:])):
        if b <= a:
            continue
        out.append({'f0': a, 'f1': b, 'label': f'part {len(out) + 1}',
                    'source': 'automatic (changes of cut rate and motion; inner edges on the nearest cut within 3 s)'})
    if out:
        out[-1]['f1'] = F
    return out


def sections(sig, st, cuts):
    """Sections: chapter: markers (two or more), else beat:/hook: markers, else automatic from pace changes. A
    story_plan.json next to the project adds each matching section's label, gear and feel (by marker name)."""
    fps, F = float(sig['fps']), int(sig['frames'])
    marks = (sig['lanes'].get('edit') or {}).get('markers') or []
    chapters = [m for m in marks if m['kind'] == 'chapter']
    beats = [m for m in marks if m['kind'] in ('beat', 'hook')]
    use, source = None, None
    if len(chapters) >= 2:
        use, source = chapters, 'chapter: markers'
        hook = next((m for m in marks if m['kind'] == 'hook' and m['f'] < chapters[0]['f']), None)
        if hook is not None:
            use = [hook] + use
    elif len(beats) >= 2:
        use, source = beats, 'beat: markers'
    out = []
    if use:
        use = sorted(use, key=lambda m: m['f'])
        dedup = []
        for m in use:
            if dedup and m['f'] - dedup[-1]['f'] < max(1, int(0.5 * fps)):
                continue
            dedup.append(m)
        starts = [m['f'] for m in dedup]
        if starts[0] > 0:
            out.append({'f0': 0, 'f1': starts[0], 'label': 'opening', 'source': source})
        for m, nxt in zip(dedup, starts[1:] + [F]):
            out.append({'f0': m['f'], 'f1': nxt, 'label': m['label'], 'name': m.get('name') or m['kind'],
                        'source': source})
    else:
        out = _auto_sections(sig, st, cuts)
    plan = None
    if sig.get('project'):
        p = Path(sig['project']).parent / 'story_plan.json'
        if p.exists():
            try:
                plan = json.loads(p.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                plan = None
    if plan:
        by_id = {str(s.get('id')): s for s in plan.get('sections') or [] if isinstance(s, dict)}
        for s in out:
            ps = by_id.get(str(s.get('name')))
            if ps:
                s['plan'] = {k: ps.get(k) for k in ('label', 'gear', 'feel', 'driver', 'target_s') if k in ps}
    for s in out:
        s['t0'], s['t1'] = ts.tsec(s['f0'], fps), ts.tsec(s['f1'], fps)
    return [s for s in out if s['f1'] > s['f0']]


def section_numbers(sig, st, secs, cuts, speech):
    fps, F = float(sig['fps']), int(sig['frames'])
    mot = sig['lanes'].get('motion') or {}
    e = np.array([np.nan if v is None else v for v in mot.get('energy') or [None] * F], dtype=float)
    labels = mot.get('camera_label') or [None] * F
    shots = (sig['lanes'].get('shots') or {}).get('shots') or []
    events = (sig['lanes'].get('motion_events') or {}).get('events') or []
    hold = float(st['hold_s'])
    for s in secs:
        a, b = s['f0'], s['f1']
        dur = (b - a) / fps
        cs = [c for c in cuts if a <= c['f'] < b]
        sh = [x for x in shots if a <= x['f0'] < b]
        lens = [x['seconds'] for x in sh]
        seg = e[a:b]
        lab = [x for x in labels[a:b] if x]
        n_act = sum(1 for c in cs if c['action'] == 'on action')
        holds = [x for x in sh if x['seconds'] >= hold]
        num = {'seconds': round(dur, 2), 'cuts': len(cs),
               'cut_rate_per_min': round(len(cs) / dur * 60.0, 1) if dur > 0 else None,
               'median_shot_s': round(float(np.median(lens)), 2) if lens else None,
               'motion_energy': ts.clean(float(np.nanmean(seg)), 2) if np.isfinite(seg).any() else None,
               'camera_moving_share': round(sum(1 for x in lab if x != 'static') / max(1, len(lab)), 2),
               'motion_events_per_min': round(sum(1 for x in events if a <= x['f_peak'] < b) / dur * 60.0, 1)
               if dur > 0 else None,
               'cuts_on_action_share': round(n_act / len(cs), 2) if cs else None,
               'holds': len(holds), 'longest_shot_s': round(max(lens), 2) if lens else None}
        if speech and speech.get('words') is not None:
            t0, t1 = a / fps, b / fps
            talk = sum(max(0.0, min(w['t1'], t1) - max(w['t0'], t0)) for w in speech['words'])
            num['speech_share'] = round(talk / dur, 2) if dur > 0 else None
        if any('beat_offset_frames' in c for c in cs):
            tol = int(st['beat_tolerance_frames'])
            on = [c for c in cs if abs(c.get('beat_offset_frames', 99)) <= tol]
            num['cuts_on_beat_share'] = round(len(on) / len(cs), 2) if cs else None
        s['numbers'] = num
    return secs


# ============================================================================ thumbnails

def thumbnails(video, frames_wanted, fps, height, offset=0):
    """{frame: PIL image} for the wanted frames of the analysed file (decoded at thumbnail size)."""
    from PIL import Image
    import letitedit.footage.shots as shots
    if not frames_wanted:
        return {}
    info = shots.probe(video)
    h = int(height)
    w = max(16, int(round(info['w'] * h / info['h'] / 2)) * 2)
    want = sorted(set(int(f) for f in frames_wanted))
    lo, hi = want[0] - offset, want[-1] - offset
    start = max(0.0, lo / fps - 0.2)
    dur = (hi - lo) / fps + 0.6
    out = {}
    got = []
    t_start = float(info.get('start_time') or 0.0)
    for t, Y, U, V in shots.decode(video, w, h, start if start > 0 else None, dur):
        f = int(round((t - (0.0 if start > 0 else t_start)) * fps)) + offset
        got.append((f, Y.copy(), U.copy(), V.copy()))
    if not got:
        return {}
    import cv2
    fs = np.array([g[0] for g in got])
    for f in want:
        j = int(np.argmin(np.abs(fs - f)))
        _, Y, U, V = got[j]
        yuv = np.concatenate([Y.ravel(), U.ravel(), V.ravel()]).reshape(h * 3 // 2, w)
        rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
        out[f] = Image.fromarray(rgb)
    return out


# ============================================================================ drawing

class Page:
    def __init__(self, t0, t1, W):
        self.t0, self.t1, self.W = t0, t1, W
        self.x0, self.x1 = LABEL_COL, W - 14

    def x(self, t):
        return self.x0 + (float(t) - self.t0) / max(1e-6, self.t1 - self.t0) * (self.x1 - self.x0)


def _lane_label(d, y, h, text, sub=None):
    d.rectangle([0, y, LABEL_COL - 6, y + h], fill=(246, 246, 246))
    d.text((6, y + 3), text, fill=(30, 30, 30), font=font(14, True))
    if sub:
        d.text((6, y + 20), sub, fill=(100, 100, 100), font=font(11))


def _tick_step(span):
    for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
        if span / s <= 16:
            return s
    return 600


def _draw_motion_lanes(d, data, P, fps, span, y, H_MOT, H_EYE):
    _lane_label(d, y, H_MOT - 4, 'motion', 'camera removed')
    e = data['energy']
    f0, f1 = max(0, int(P.t0 * fps)), min(len(e), int(math.ceil(P.t1 * fps)) + 1)
    top = max(3.0, float(np.nanpercentile(e, 99)) if np.isfinite(e).any() else 3.0)
    top = math.ceil(top)
    base_y = y + H_MOT - 30
    hgt = H_MOT - 36
    for gv in range(0, int(top) + 1, max(1, int(top) // 3)):
        yy = base_y - gv / top * hgt
        d.line([P.x0, yy, P.x1, yy], fill=(232, 232, 232))
        d.text((P.x0 - 22, yy - 7), f'{gv}', fill=(130, 130, 130), font=font(10))
    pts = []
    for f in range(f0, f1):
        v = e[f]
        if not np.isfinite(v):
            if pts:
                d.polygon([(pts[0][0], base_y)] + pts + [(pts[-1][0], base_y)], fill=(144, 202, 249))
                d.line(pts, fill=(21, 101, 192), width=1)
                pts = []
            continue
        pts.append((P.x(f / fps), base_y - min(v, top) / top * hgt))
    if len(pts) > 1:
        d.polygon([(pts[0][0], base_y)] + pts + [(pts[-1][0], base_y)], fill=(144, 202, 249))
        d.line(pts, fill=(21, 101, 192), width=1)
    d.text((P.x1 - 150, y + 2), f'px/frame (0-{int(top)})', fill=(110, 110, 110), font=font(10))
    # visual beats
    for bt in data['visual_beats']:
        if P.t0 <= bt['t'] <= P.t1:
            xx = P.x(bt['t'])
            d.line([xx, y + 2, xx, y + 10], fill=(0, 105, 92), width=2)
    # events
    for ev in data['events']:
        if ev['t1'] < P.t0 or ev['t0'] > P.t1:
            continue
        xa, xb, xp = P.x(max(ev['t0'], P.t0)), P.x(min(ev['t1'], P.t1)), P.x(ev['t_peak'])
        d.rectangle([xa, base_y + 2, max(xa + 1, xb), base_y + 8], fill=(255, 112, 67))
        d.line([xp, base_y + 1, xp, base_y + 9], fill=(150, 30, 0), width=2)
    # camera band
    labs = data['camera_label']
    cy = base_y + 12
    runs = []
    for f in range(f0, f1):
        lab = labs[f] if f < len(labs) else None
        if runs and runs[-1][2] == lab and runs[-1][1] == f:
            runs[-1][1] = f + 1
        else:
            runs.append([f, f + 1, lab])
    for a, b, lab in runs:
        xa, xb = P.x(a / fps), P.x(b / fps)
        d.rectangle([xa, cy, max(xa + 1, xb), cy + 10], fill=CAM_COLORS.get(lab, (240, 240, 240)))
        if lab and lab != 'static' and xb - xa > text_w(d, lab, font(10)) + 4:
            d.text((xa + 2, cy - 1), lab, fill=(255, 255, 255), font=font(10, True))
    y += H_MOT
    # attention
    _lane_label(d, y, H_EYE - 4, 'eye', 'x red, y blue')
    ax, ay = data['att_x'], data['att_y']
    for arr, col in ((ax, (229, 57, 53)), (ay, (30, 136, 229))):
        pts = []
        for f in range(f0, f1, 1 if span < 100 else 2):
            v = arr[f] if f < len(arr) else np.nan
            if not np.isfinite(v):
                if len(pts) > 1:
                    d.line(pts, fill=col, width=1)
                pts = []
                continue
            pts.append((P.x(f / fps), y + 4 + v * (H_EYE - 12)))
        if len(pts) > 1:
            d.line(pts, fill=col, width=1)
    d.line([P.x0, y + 4 + 0.5 * (H_EYE - 12), P.x1, y + 4 + 0.5 * (H_EYE - 12)], fill=(225, 225, 225))
    y += H_EYE
    return y


def _draw_speech_lane(d, data, P, y, H_SPEECH):
    sp = data['speech']
    _lane_label(d, y, H_SPEECH - 4, 'speech', 'words, pauses')
    if sp['words']:
        for p in sp['pauses']:
            if p['t1'] < P.t0 or p['t0'] > P.t1:
                continue
            xa, xb = P.x(max(p['t0'], P.t0)), P.x(min(p['t1'], P.t1))
            d.rectangle([xa, y + 2, xb, y + H_SPEECH - 6], fill=(238, 238, 238))
            ln = p['t1'] - p['t0']
            if ln >= 0.5 and xb - xa > 26:
                d.text((xa + 2, y + H_SPEECH - 19), f'{ln:.1f}s', fill=(120, 120, 120), font=font(10))
        last_end = -1e9
        for w in sp['words']:
            if w['t1'] < P.t0 or w['t0'] > P.t1:
                continue
            xa, xb = P.x(max(w['t0'], P.t0)), P.x(min(w['t1'], P.t1))
            st_ = w.get('stress')
            col = (255, 202, 40) if (st_ is not None and st_ >= 0.6) else (129, 199, 132)
            d.rectangle([xa, y + 4, max(xa + 1, xb - 1), y + 14], fill=col)
            tw = text_w(d, w['w'], font(11))
            if xa > last_end + 2:
                d.text((xa, y + 16), w['w'], fill=(30, 30, 30), font=font(11))
                last_end = xa + tw
        for te in sp['thought_ends']:
            tt = te.get('t')
            if tt is not None and P.t0 <= tt <= P.t1:
                xx = P.x(tt)
                d.line([xx, y + 2, xx, y + H_SPEECH - 6], fill=(106, 27, 154), width=2)
    else:
        d.text((P.x0 + 4, y + 12), sp['source'], fill=(150, 150, 150), font=font(12))
    y += H_SPEECH
    return y


def _draw_music_lane(d, data, P, y, H_MUSIC):
    mu = data['music']
    _lane_label(d, y, H_MUSIC - 4, 'music', 'beats, sections')
    if mu:
        for i, s in enumerate(mu['sections']):
            a, b = s.get('t0'), s.get('t1')
            if a is None or b is None or b < P.t0 or a > P.t1:
                continue
            xa, xb = P.x(max(a, P.t0)), P.x(min(b, P.t1))
            d.rectangle([xa, y + 22, xb, y + H_MUSIC - 6], fill=(225, 190, 231) if i % 2 else (206, 147, 216))
            lab = str(s.get('label', ''))
            if xb - xa > text_w(d, lab, font(11)) + 4:
                d.text((xa + 2, y + 23), lab, fill=(40, 0, 50), font=font(11))
        for b in mu['beats']:
            tt = b.get('t')
            if tt is None or not (P.t0 <= tt <= P.t1):
                continue
            xx = P.x(tt)
            if b.get('downbeat'):
                d.line([xx, y + 2, xx, y + 20], fill=(74, 20, 140), width=2)
            else:
                d.line([xx, y + 10, xx, y + 20], fill=(149, 117, 205), width=1)
        if mu.get('tempo_bpm'):
            d.text((P.x1 - 110, y + 2), f'{float(mu["tempo_bpm"]):.0f} bpm', fill=(74, 20, 140), font=font(11))
    else:
        d.text((P.x0 + 4, y + 12), 'no music lane', fill=(150, 150, 150), font=font(12))
    y += H_MUSIC
    return y


def _draw_graphics_lane(d, data, P, y, H_GFX):
    _lane_label(d, y, H_GFX - 4, 'text', 'captions, graphics')
    rows_end = [-1e9, -1e9]
    for g in data['graphics']:
        if g['t1'] < P.t0 or g['t0'] > P.t1 or not g.get('visible', True):
            continue
        xa, xb = P.x(max(g['t0'], P.t0)), P.x(min(g['t1'], P.t1))
        row = 0 if xa >= rows_end[0] else 1
        rows_end[row] = xb + 1
        yy = y + 2 + row * 20
        col = GFX_COLORS.get(g['kind'], (200, 200, 200))
        d.rectangle([xa, yy, max(xa + 1, xb - 1), yy + 17], fill=col, outline=tuple(int(c * 0.7) for c in col))
        txt = (g.get('text') or '').replace('\n', ' ')
        if xb - xa > 20 and txt:
            room = int((xb - xa - 4) / 6.2)
            if room >= 3:
                d.text((xa + 2, yy + 2), txt[:room], fill=(30, 30, 30), font=font(11))
    y += H_GFX
    return y


def _draw_loudness_lane(d, data, P, y, H_LOUD):
    _lane_label(d, y, H_LOUD - 4, 'loudness', 'LUFS 0.4 s')
    L = data['loudness']
    hop = data['hop_s']
    if L is not None and len(L):
        lo_db, hi_db = -60.0, 0.0
        for gv in (-50, -30, -14):
            yy = y + 4 + (hi_db - gv) / (hi_db - lo_db) * (H_LOUD - 12)
            d.line([P.x0, yy, P.x1, yy], fill=(232, 232, 232))
            d.text((P.x0 - 26, yy - 7), f'{gv}', fill=(130, 130, 130), font=font(10))
        i0, i1 = max(0, int(P.t0 / hop)), min(len(L), int(P.t1 / hop) + 1)
        stride = max(1, (i1 - i0) // 1500)
        pts = [(P.x(i * hop), y + 4 + (hi_db - max(lo_db, min(hi_db, L[i]))) / (hi_db - lo_db) * (H_LOUD - 12))
               for i in range(i0, i1, stride) if np.isfinite(L[i])]
        if len(pts) > 1:
            d.line(pts, fill=(56, 142, 60), width=1)
        for o in data['onsets']:
            if P.t0 <= o['t'] <= P.t1:
                xx = P.x(o['t'])
                d.line([xx, y + H_LOUD - 10, xx, y + H_LOUD - 4], fill=(46, 125, 50))
    else:
        d.text((P.x0 + 4, y + 12), 'no sound', fill=(150, 150, 150), font=font(12))
    y += H_LOUD
    return y


def _draw_rhythm_footer(d, data, P, fps, secs, W, y, H_SEC, y_cuts, plot_bottom):
    for c in data['cuts']:
        if not (P.t0 <= c['t'] <= P.t1):
            continue
        xx = P.x(c['f'] / fps)
        if c['kind'] == 'dissolve' and c.get('f1', c['f']) > c.get('f0', c['f']):
            xa, xb = P.x(c['f0'] / fps), P.x(c['f1'] / fps)
            for yy in range(y_cuts + 36, plot_bottom, 6):
                d.line([xa, yy, xb, yy], fill=(255, 183, 77))
        col = (211, 47, 47) if c['kind'] == 'cut' else (245, 124, 0) if c['kind'] == 'dissolve' else (90, 90, 90)
        for yy in range(y_cuts + 36, plot_bottom, 4):
            d.line([xx, yy, xx, yy + 2], fill=col)
    # sections band
    _lane_label(d, y, H_SEC - 4, 'sections', None)
    for i, s in enumerate(secs):
        xa, xb = P.x(max(s['t0'], P.t0)), P.x(min(s['t1'], P.t1))
        d.rectangle([xa, y + 2, max(xa + 1, xb - 1), y + H_SEC - 6], fill=(207, 216, 220) if i % 2 else (176, 190, 197))
        lab = f'S{data["sections"].index(s) + 1} {s["label"]}'
        if xb - xa > 30:
            room = int((xb - xa - 6) / 6.5)
            d.text((xa + 3, y + 5), lab[:max(3, room)], fill=(20, 20, 20), font=font(12, True))
    y += H_SEC
    # numbers table
    cols = [('section', 290), ('time', 120), ('cuts', 50), ('cut rate /min', 100), ('median shot s', 105),
            ('motion px/f', 90), ('camera moving', 105), ('on action', 80), ('holds', 55), ('longest s', 80),
            ('speech', 65), ('on beat', 70), ('plan gear', 75)]
    xx = 8
    for name, wcol in cols:
        d.text((xx, y + 4), name, fill=(60, 60, 60), font=font(12, True))
        xx += wcol
    y += 24
    for s in secs:
        n = s['numbers']
        k = data['sections'].index(s) + 1
        vals = [f'S{k} {s["label"]}'[:38], f'{ts.clock(s["t0"])[:-4]}-{ts.clock(s["t1"])[:-4]}', n['cuts'],
                n['cut_rate_per_min'], n['median_shot_s'], n['motion_energy'],
                f'{n["camera_moving_share"]:.0%}' if n.get('camera_moving_share') is not None else '-',
                f'{n["cuts_on_action_share"]:.0%}' if n.get('cuts_on_action_share') is not None else '-',
                n['holds'], n['longest_shot_s'],
                f'{n["speech_share"]:.0%}' if n.get('speech_share') is not None else '-',
                f'{n["cuts_on_beat_share"]:.0%}' if n.get('cuts_on_beat_share') is not None else '-',
                (s.get('plan') or {}).get('gear', '-')]
        xx = 8
        for (name, wcol), v in zip(cols, vals):
            d.text((xx, y + 2), '-' if v is None else str(v), fill=(20, 20, 20), font=font(12))
            xx += wcol
        y += 20
    y += 8
    # legend
    leg = ('cut flags: filled triangle = motion on both sides of the cut (on action), half = one side moves, hollow '
           '= still; +Nf = frames after the nearest music beat (green: within tolerance).  shots: CU closeup, MS '
           'medium, WS wide, ? no face.  motion: blue area = energy, green ticks = visual beats, orange bars = '
           'motion events (dark tick = peak); band = camera: grey static, blue pan, teal tilt, purple zoom, orange '
           'handheld, red whip.  red dashed lines = cuts, orange = dissolves.')
    words_ = leg.split(' ')
    line, ly = '', y
    for wd in words_:
        if text_w(d, line + ' ' + wd, font(11)) > W - 20:
            d.text((8, ly), line, fill=(90, 90, 90), font=font(11))
            ly += 14
            line = wd
        else:
            line = (line + ' ' + wd).strip()
    d.text((8, ly), line, fill=(90, 90, 90), font=font(11))


def draw_page(sig, data, page, idx, n_pages, st, thumbs):
    from PIL import Image, ImageDraw
    W = int(st['width'])
    fps = float(sig['fps'])
    P = Page(page['t0'], page['t1'], W)
    lanes = data['lanes_drawn']
    H_HEAD, H_RULER, H_CUTS = 50, 22, 40
    H_THUMB = int(st['thumb_h']) + 6
    H_SHOT, H_MOT, H_EYE, H_SPEECH, H_MUSIC, H_GFX, H_LOUD, H_SEC = 34, 120, 46, 50, 44, 46, 72, 26
    secs = [s for s in data['sections'] if s['f1'] / fps > P.t0 and s['f0'] / fps < P.t1]
    H_TABLE = 26 + 20 * max(1, len(secs)) + 8
    H_LEG = 40
    H = (H_HEAD + H_RULER + H_CUTS + H_THUMB + H_SHOT + H_MOT + H_EYE + H_SPEECH + H_MUSIC + H_GFX + H_LOUD + H_SEC
         + H_TABLE + H_LEG)
    img = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    name = Path(sig.get('project') or sig['source']).name
    title = f'{name}   {ts.clock(P.t0)} - {ts.clock(P.t1)}   (page {idx + 1}/{n_pages})'
    d.text((8, 6), title, fill=(20, 20, 20), font=font(20, True))
    w_ = sig['size']
    sub = (f'{sig["kind"]}  {w_[0]}x{w_[1]} @ {fps:g} fps  {sig["duration_s"]:.2f} s  {len(data["cuts"])} cuts  '
           f'{len(data["shots"])} shots  median shot {data["summary"].get("median_shot_s")} s  '
           f'cut rate {data["summary"].get("cut_rate_per_min")}/min  motion {data["summary"].get("motion_energy")} '
           f'px/frame')
    d.text((8, 30), sub, fill=(80, 80, 80), font=font(13))
    y = H_HEAD
    # ruler
    span = P.t1 - P.t0
    step = _tick_step(span)
    t = math.ceil(P.t0 / step) * step
    d.line([P.x0, y + H_RULER - 1, P.x1, y + H_RULER - 1], fill=(120, 120, 120))
    while t <= P.t1 + 1e-6:
        xx = P.x(t)
        d.line([xx, y + H_RULER - 7, xx, y + H_RULER - 1], fill=(80, 80, 80))
        lab = ts.clock(t)[:-4] if step >= 1 else ts.clock(t)[:-2]
        d.text((xx + 2, y + 2), lab, fill=(60, 60, 60), font=font(12))
        t += step
    minor = step / 5 if step >= 1 else 0.1
    t = math.ceil(P.t0 / minor) * minor
    while t <= P.t1:
        xx = P.x(t)
        d.line([xx, y + H_RULER - 4, xx, y + H_RULER - 1], fill=(170, 170, 170))
        t += minor
    _lane_label(d, y, H_RULER - 2, 'time', None)
    y += H_RULER
    plot_top = y
    # cut flags
    y_cuts = y
    _lane_label(d, y, H_CUTS - 2, 'cuts', 'beat / action')
    last_x = [-999, -999]
    for c in data['cuts']:
        if not (P.t0 <= c['t'] <= P.t1):
            continue
        xx = P.x(c['t'])
        row = 0 if xx - last_x[0] > 44 else 1 if xx - last_x[1] > 44 else 0
        last_x[row] = xx
        yy = y + 2 + row * 18
        act = c['action']
        col = (198, 40, 40) if act == 'on action' else (230, 120, 0) if act in ('into action', 'out of action') \
            else (120, 120, 120)
        # triangle: filled = on action, half = one side moves, hollow = still
        tri = [(xx - 5, yy + 12), (xx + 5, yy + 12), (xx, yy + 3)]
        if act == 'on action':
            d.polygon(tri, fill=col)
        elif act in ('into action', 'out of action'):
            d.polygon(tri, outline=col, fill=(255, 224, 178))
        else:
            d.polygon(tri, outline=col)
        if 'beat_offset_frames' in c:
            off = c['beat_offset_frames']
            s_ = f'{off:+d}f' if off else '0f'
            colb = (27, 94, 32) if abs(off) <= int(st['beat_tolerance_frames']) else (90, 90, 90)
            d.text((xx + 6, yy), s_, fill=colb, font=font(12, abs(off) <= int(st['beat_tolerance_frames'])))
    y += H_CUTS
    # thumbnails
    _lane_label(d, y, H_THUMB - 4, 'picture', None)
    xs_used = []
    for f, im in sorted(thumbs.items()):
        tt = f / fps
        if not (P.t0 <= tt <= P.t1):
            continue
        tw = im.width
        xx = int(P.x(tt) - tw / 2)
        xx = max(P.x0, min(P.x1 - tw, xx))
        img.paste(im, (xx, y + 2))
        xs_used.append(xx)
    y += H_THUMB
    # shots
    _lane_label(d, y, H_SHOT - 4, 'shots', 'size, length')
    for i, s in enumerate(data['shots']):
        a, b = s['t0'], s['t1']
        if b < P.t0 or a > P.t1:
            continue
        xa, xb = P.x(max(a, P.t0)), P.x(min(b, P.t1))
        col = (30, 30, 30) if s.get('black') else SIZE_COLORS.get(s['size'], (158, 158, 158))
        light = tuple(int(c_ + (255 - c_) * (0.55 if i % 2 else 0.35)) for c_ in col)
        d.rectangle([xa, y + 2, max(xa + 1, xb - 1), y + H_SHOT - 6], fill=light, outline=col)
        lab = f'{SIZE_CODE.get(s["size"], "?")} {s["seconds"]:.1f}s'
        if s.get('black'):
            lab = f'black {s["seconds"]:.1f}s'
        if xb - xa > text_w(d, lab, font(12)) + 6:
            d.text((xa + 3, y + 7), lab, fill=(20, 20, 20), font=font(12))
        elif xb - xa > text_w(d, SIZE_CODE.get(s['size'], '?'), font(11)) + 3:
            d.text((xa + 2, y + 8), SIZE_CODE.get(s['size'], '?'), fill=(20, 20, 20), font=font(11))
    y += H_SHOT
    # motion
    y = _draw_motion_lanes(d, data, P, fps, span, y, H_MOT, H_EYE)
    # speech
    y = _draw_speech_lane(d, data, P, y, H_SPEECH)
    # music
    y = _draw_music_lane(d, data, P, y, H_MUSIC)
    # graphics
    y = _draw_graphics_lane(d, data, P, y, H_GFX)
    # loudness
    y = _draw_loudness_lane(d, data, P, y, H_LOUD)
    plot_bottom = y
    # cut lines through every lane
    _draw_rhythm_footer(d, data, P, fps, secs, W, y, H_SEC, y_cuts, plot_bottom)
    return img


# ============================================================================ the view

def build(source, start_s=None, end_s=None, options=None):
    """All the map's data (no drawing): signals, cut table, sections with numbers, page ranges."""
    options = dict(options or {})
    st = ts.lane_settings('map', MAP_DEFAULTS, {k: v for k, v in options.items() if k in MAP_DEFAULTS})
    lanes = options.get('lanes') or wanted_lanes()
    sig = ts.signals(source, start_s, end_s, lanes=lanes, refresh=bool(options.get('refresh')),
                     settings=options.get('settings'))
    sig = ts.add_cuts(sig, options.get('cuts_at'))
    fps, F = float(sig['fps']), int(sig['frames'])
    music = music_data(sig)
    cuts = cut_table(sig, st, music)
    speech = speech_data(sig, st)
    secs = sections(sig, st, cuts)
    secs = section_numbers(sig, st, secs, cuts, speech)
    shots = (sig['lanes'].get('shots') or {}).get('shots') or []
    mot = sig['lanes'].get('motion') or {}
    energy = np.array([np.nan if v is None else v for v in mot.get('energy') or [None] * F], dtype=float)
    att = sig['lanes'].get('attention') or {}
    aud = sig['lanes'].get('audio') or {}
    L = np.array([np.nan if v is None else v for v in aud.get('loudness_db') or []], dtype=float)
    dur = F / fps
    lens = [s['seconds'] for s in shots]
    summary = {'cuts': len(cuts), 'shots': len(shots),
               'cut_rate_per_min': round(len(cuts) / dur * 60.0, 1) if dur else None,
               'median_shot_s': round(float(np.median(lens)), 2) if lens else None,
               'motion_energy': ts.clean(float(np.nanmean(energy)), 2) if np.isfinite(energy).any() else None,
               'cuts_on_action_share': round(sum(1 for c in cuts if c['action'] == 'on action') / len(cuts), 2)
               if cuts else None,
               'holds': sum(1 for s in shots if s['seconds'] >= float(st['hold_s'])),
               'sizes': {k: sum(1 for s in shots if s['size'] == k) for k in ('closeup', 'medium', 'wide', 'unknown')}}
    if any('beat_offset_frames' in c for c in cuts):
        tol = int(st['beat_tolerance_frames'])
        summary['cuts_on_beat_share'] = round(sum(1 for c in cuts if abs(c.get('beat_offset_frames', 99)) <= tol)
                                              / max(1, len(cuts)), 2)
    t_lo = 0.0 if start_s is None else max(0.0, float(start_s))
    t_hi = dur if end_s is None else min(dur, float(end_s))
    span = t_hi - t_lo
    if span <= float(st['one_page_s']):
        pages = [(t_lo, t_hi)]
    else:
        n = int(math.ceil(span / float(st['page_s']) - 1e-6))
        pages = [(t_lo + span * i / n, t_lo + span * (i + 1) / n) for i in range(n)]
    return {'sig': sig, 'st': st, 'cuts': cuts, 'sections': secs, 'speech': speech, 'music': music,
            'shots': shots, 'energy': energy, 'summary': summary, 'pages': pages,
            'camera_label': mot.get('camera_label') or [None] * F,
            'visual_beats': (sig['lanes'].get('visual_beats') or {}).get('beats') or [],
            'events': (sig['lanes'].get('motion_events') or {}).get('events') or [],
            'graphics': (sig['lanes'].get('edit') or {}).get('graphics') or [],
            'att_x': np.array([np.nan if v is None else v for v in att.get('x') or [None] * F], dtype=float),
            'att_y': np.array([np.nan if v is None else v for v in att.get('y') or [None] * F], dtype=float),
            'loudness': L, 'hop_s': float(aud.get('hop_s') or 0.01), 'onsets': aud.get('onsets') or [],
            'lanes_drawn': lanes}


def map_view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The rhythm map: one image per page and the numbers behind it."""
    t_start = time.time()
    options = dict(options or {})
    data = build(source, start_s, end_s, options)
    sig, st = data['sig'], data['st']
    fps = float(sig['fps'])
    rid = timing_views.result_id('map', sig['key'], start_s, end_s, {k: v for k, v in options.items()
                                                                       if k != 'refresh'})
    out_dir = MAPS / rid
    out_dir.mkdir(parents=True, exist_ok=True)
    images = []
    want_pages = options.get('pages')
    th = int(st['thumb_h'])
    for i, (a, b) in enumerate(data['pages']):
        if want_pages and (i + 1) not in want_pages:
            continue
        # thumbnails: as many as fit side by side
        W = int(st['width'])
        aspect = sig['size'][0] / float(sig['size'][1])
        tw = th * aspect
        n_th = max(2, int((W - LABEL_COL - 14) / (tw + 4)))
        fr_th = [int(round((a + (b - a) * (k + 0.5) / n_th) * fps)) for k in range(n_th)]
        offset = 0
        if sig['kind'] == 'project' and (sig.get('render_info') or {}).get('frames') and sig['range']['f0']:
            offset = sig['range']['f0']
        try:
            thumbs = thumbnails(sig['render'] or sig['source'], fr_th, fps, th, offset=offset)
        except Exception:  # noqa: BLE001 - a map without pictures is still a map
            thumbs = {}
        img = draw_page(sig, data, {'t0': a, 't1': b}, i, len(data['pages']), st, thumbs)
        p = out_dir / f'map-p{i + 1}.jpg'
        img.save(p, 'JPEG', quality=88)
        images.append(str(p))
    res = timing_views.common_fields(source=str(source), sig=sig, view='map',
                                     inputs=[start_s, end_s, options], preview_artifacts=[
                                         {'kind': 'map_page', 'path': p} for p in images])
    res['result_id'] = rid
    res.update({'view': 'map', 'images': images,
                'pages': [{'t0': round(a, 3), 't1': round(b, 3), 'image': images[k] if k < len(images) else None}
                          for k, (a, b) in enumerate(data['pages'])],
                'summary': data['summary'], 'sections': data['sections'], 'cuts': data['cuts'],
                'shots': [{k: s.get(k) for k in ('f0', 'f1', 't0', 't1', 'seconds', 'kind_in', 'size', 'size_basis',
                                                  'item', 'black') if k in s} for s in data['shots']],
                'speech_source': data['speech']['source'],
                'music': ({k: data['music'][k] for k in ('tempo_bpm', 'confidence', 'stem')} if data['music']
                          else None),
                'thresholds': {k: st[k] for k in ('action_px', 'action_frames', 'beat_tolerance_frames', 'hold_s',
                                                  'pause_s')},
                'measures': {'action': f'mean motion energy (camera removed, px/frame) over {st["action_frames"]} '
                                       f'frames before and after the cut; a side moves at >= {st["action_px"]}',
                             'beat_offset_frames': 'cut frame minus the nearest music beat frame (positive: the cut '
                                                   'comes after the beat)',
                             'holds': f'shots of {st["hold_s"]} s or more',
                             'sections': (data['sections'][0]['source'] if data['sections'] else None)},
                'options_used': {k: st[k] for k in MAP_DEFAULTS},
                'lanes': {n: {'method': d.get('method'), 'seconds': d.get('seconds'), 'error': d.get('error')}
                          for n, d in sig['lanes'].items()},
                'render': sig.get('render'), 'analysis_seconds': sig['seconds'],
                'seconds': round(time.time() - t_start, 2)})
    res['warnings'] = list(sig.get('warnings') or [])
    for n, d in sig['lanes'].items():
        for w in d.get('warnings') or []:
            res['warnings'].append(f'{n}: {w}')
    res['unsupported'] = ['judgment: the map measures; whether a pace or a cut is right is the editor\'s call',
                          'cuts inside a pre-rendered clip are not in a project\'s cut list (compare with the cuts '
                          'view or shots.detect on the render)']
    if not data['music']:
        res['unsupported'].append('beat offsets: no music lane registered or no music found')
    if detail != 'full':
        res['cuts'] = [{k: c.get(k) for k in ('f', 't', 'kind', 'action', 'motion_before', 'motion_after',
                                               'beat_offset_frames', 'size_change', 'detail') if k in c}
                       for c in data['cuts']]
    return res


timing_views.register_view('map', map_view, 'the rhythm map: thumbnails, shots and sizes, motion (camera removed) '
                                            'with camera labels, motion events and visual beats, eye position, '
                                            'speech and pauses, music beats and sections, captions and graphics, '
                                            'loudness; every cut flagged by its offset from the nearest beat and '
                                            'whether it lands on action; numbers per section (cut rate, median '
                                            'shot, motion, cuts on action, holds). Long edits come in pages')
