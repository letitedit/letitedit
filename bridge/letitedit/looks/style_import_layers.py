"""Overlays for style_import: things laid on top of the footage (stickers, emoji, pictures, icons, text pops, arrows,
circles, progress bars, lower thirds), found in the grey analysis frames, with when / where / how big / how they come
in and go out, and what was being said when they came in.

How an overlay is found: a part of the picture changes a lot within about 0.3 s (against the frame just before), is
then steady for a while, and the rest of the frame does not change the same way (that would be a cut or a camera
move). Its box is the joined blocks that did that; it lasts while those blocks keep the look they had once it was in.
Captions are left out (they are reported as captions); other text read by OCR in the same place makes the overlay a
text pop. What can fool it: a hand or object moved into a still shot and held there (marked with a lower confidence
when it is on the person), an animated sticker that never holds still (missed).
"""
from __future__ import annotations

import math
import re

import numpy as np

from letitedit.looks.style_import_stats import _iou
from letitedit.looks.style_import_text import face_at as _face_at

STOP = set('''a an the and or but so if then than that this these those there here it its it's i i'm me my we our
you your he she they them their is are was were be been am do does did have has had to of in on at by for with from
up down out over under just very really like um uh yeah oh okay ok so what which who how when where because as all
any some more most other just also not no can could would should will get got go going gonna want need know think
one thing things kind sort right well let let's see look'''.split())
NUM_WORDS = {'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven',
             'twelve', 'fifteen', 'twenty', 'thirty', 'forty', 'fifty', 'hundred', 'thousand', 'million', 'billion',
             'half', 'dozen', 'percent'}


def _zone(cx, cy):
    col = 'left' if cx < 0.36 else 'right' if cx > 0.64 else 'centre'
    row = 'upper' if cy < 0.36 else 'lower' if cy > 0.64 else 'middle'
    return 'centre' if (row, col) == ('middle', 'centre') else f'{row}_{col}' if col != 'centre' else row


def detect(frames, feat, fps, cuts, text_events=(), face_track=(), words=(), settings=None, spans=(), add_ocr=True):
    """Overlay events: [{t, end, box, area, size, zone, entry, exit, conf, on_person, kind?, text?, said?,
    trigger?}]."""
    import cv2
    from scipy.ndimage import maximum_filter1d, label as cc_label
    import letitedit.looks.style_import as si
    st = {'k_in_s': 0.3, 'calm_s': 0.35, 'change': 20.0, 'calm': 6.0, 'calm_long': 5.0, 'min_blocks': 4,
          'max_share': 0.35, 'gone': 12.0, 'min_len_s': 0.4, 'max_area': 0.3, 'min_texture': 18.0, 'abrupt': 0.2,
          'cam_px': 1.5, **(settings or {})}
    n, H, W = frames.shape
    bd = feat['blocks'].astype(np.float32)
    hb, wb = bd.shape[1], bd.shape[2]
    B = 8
    K = max(3, int(round(st['k_in_s'] * fps)))
    L = max(3, int(round(st['calm_s'] * fps)))
    cut_f = np.array(sorted(int(c['frame']) for c in cuts)) if cuts else np.array([], int)
    # gradual transitions: every frame of them counts as a cut here (the whole picture changes)
    extra = [f for a, b in spans for f in range(max(0, int(a * fps) - 1), min(n, int(math.ceil(b * fps)) + 2))]
    if extra:
        cut_f = np.array(sorted(set(cut_f.tolist()) | set(extra)))
    # steadiness after: the largest frame-to-frame block change over the L frames starting K frames later
    calm_after = maximum_filter1d(bd, size=L, axis=0, origin=-(L // 2), mode='nearest')
    caption_spans = [(e['t'], e['end'], e['box']) for e in text_events if e.get('role') == 'caption']

    def caption_mask(t):
        m = np.zeros((hb, wb), bool)
        for a, b, box in caption_spans:
            if a - 0.2 <= t <= b + 0.2:
                r0, r1 = max(0, int((box[1] - 0.015) * hb)), min(hb, int(math.ceil((box[3] + 0.015) * hb)))
                c0, c1 = max(0, int((box[0] - 0.02) * wb)), min(wb, int(math.ceil((box[2] + 0.02) * wb)))
                m[r0:r1, c0:c1] = True
        return m

    def near_cut(i, lo, hi):
        if not len(cut_f):
            return False
        k = np.searchsorted(cut_f, i - lo)
        return k < len(cut_f) and cut_f[k] <= i + hi

    def bmean(a):
        return a[:hb * B, :wb * B].reshape(hb, B, wb, B).mean(axis=(1, 3))

    cand = []
    grad_cache = {}
    for i in range(2, n - K - L):
        if near_cut(i, 2, K + L):
            continue
        pre = frames[i - 2]
        post = frames[i + K]
        later = frames[i + K + L]
        A = bmean(np.abs(post.astype(np.int16) - pre.astype(np.int16)))
        if (A > st['change']).sum() < st['min_blocks']:
            continue
        # still on the screen afterwards: the same look L frames later (a slow camera move drifts away from it)
        C = bmean(np.abs(later.astype(np.int16) - post.astype(np.int16)))
        S = calm_after[min(n - 1, i + K + L // 2)]
        hit = (A > st['change']) & (C < st['calm_long']) & (S < st['calm'])
        hit &= ~caption_mask(i / fps)
        if hit.sum() < st['min_blocks']:
            continue
        # the camera's own move between pre and post taken out before judging how local the change is
        m = si.align(pre, post)
        if m['response'] > 0.15 and math.hypot(m['dx'], m['dy']) > 0.4:
            M = np.float32([[1, 0, m['dx']], [0, 1, m['dy']]])
            pre_w = cv2.warpAffine(pre, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            A = bmean(np.abs(post.astype(np.int16) - pre_w.astype(np.int16)))
            hit &= A > st['change']
            if hit.sum() < st['min_blocks']:
                continue
        # a change all over the picture is a cut, a transition or a camera move, not an overlay
        if (A > st['change']).mean() > st['max_share']:
            continue
        # did the camera move after it came in (then a box that stays put is laid on top)?
        m2 = si.align(post, later)
        cam_after = math.hypot(m2['dx'], m2['dy']) if m2['response'] > 0.1 else 0.0
        lab, k = cc_label(hit, structure=np.ones((3, 3)))
        for j in range(1, k + 1):
            comp = lab == j
            if comp.sum() < st['min_blocks']:
                continue
            rows = np.where(comp.any(1))[0]
            cols = np.where(comp.any(0))[0]
            r0, c0, r1, c1 = rows[0], cols[0], rows[-1] + 1, cols[-1] + 1
            # an overlay is a thing, not half the picture
            if (r1 - r0) * (c1 - c0) > st['max_area'] * hb * wb:
                continue
            # it has edges of its own (a flat patch of sky or wall that a moving edge crossed is not one)
            g = grad_cache.get(i + K)
            if g is None:
                gf = post.astype(np.float32)
                g = grad_cache[i + K] = cv2.magnitude(cv2.Sobel(gf, cv2.CV_32F, 1, 0), cv2.Sobel(gf, cv2.CV_32F, 0, 1))
                if len(grad_cache) > 8:
                    grad_cache.pop(min(grad_cache))
            tex = float(g[r0 * B:r1 * B, c0 * B:c1 * B].mean())
            if tex < st['min_texture']:
                continue
            inside = float(A[comp].mean())
            ring = np.zeros_like(comp)
            ring[max(0, r0 - 3):r1 + 3, max(0, c0 - 3):c1 + 3] = True
            ring &= ~comp
            ring &= ~caption_mask(i / fps)
            around = float(A[ring].mean()) if ring.any() else 0.0
            local = around < 0.45 * inside
            locked = cam_after > st['cam_px'] and float(C[comp].mean()) < 0.5 * st['calm_long'] and (
                float(C[ring].mean()) if ring.any() else 0.0) > 2.0 * st['calm_long']
            if not (local or locked):
                continue
            # it comes in, it does not drift in: one step of the way is a good part of the whole change
            steps = [float(np.abs(frames[q, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)
                                  - frames[q - 1, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)).mean())
                     for q in range(i - 1, i + K + 1)]
            total = float(np.abs(post[r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)
                                 - pre[r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)).mean())
            abrupt = max(steps) / max(1e-6, total) if steps else 0.0
            if abrupt < st['abrupt']:
                continue
            cand.append({'i': i, 'blocks': comp, 'box_b': (r0, c0, r1, c1), 'strength': inside, 'texture': tex,
                         'local': local, 'locked': locked, 'abrupt': round(abrupt, 2)})
    # one event per overlay: candidates on consecutive frames whose boxes overlap
    events = []
    for c in cand:
        r0, c0, r1, c1 = c['box_b']
        hit = None
        for ev in events:
            if c['i'] - ev['last_i'] > K + 2:
                continue
            er0, ec0, er1, ec1 = ev['box_b']
            if min(r1, er1) > max(r0, er0) and min(c1, ec1) > max(c0, ec0):
                hit = ev
                break
        if hit is None:
            events.append({'first_i': c['i'], 'last_i': c['i'], 'box_b': c['box_b'], 'blocks': c['blocks'].copy(),
                           'strength': c['strength'], 'locked': bool(c['locked']), 'local': bool(c['local']),
                           'abrupt': c['abrupt']})
        else:
            hit['last_i'] = c['i']
            er0, ec0, er1, ec1 = hit['box_b']
            hit['box_b'] = (min(r0, er0), min(c0, ec0), max(r1, er1), max(c1, ec1))
            hit['blocks'] |= c['blocks']
            hit['strength'] = max(hit['strength'], c['strength'])
            hit['locked'] = hit['locked'] or bool(c['locked'])
            hit['local'] = hit['local'] or bool(c['local'])
            hit['abrupt'] = max(hit['abrupt'], c['abrupt'])
    out = []
    for ev in events:
        r0, c0, r1, c1 = ev['box_b']
        i0 = ev['first_i']
        ref_i = min(n - 1, ev['last_i'] + K)
        ref = frames[ref_i, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)
        # start: the first frame where the box starts changing (within the K frames before the first candidate)
        j0 = max(1, i0 - 2)
        series = [float(np.abs(frames[j, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16) -
                               frames[max(0, j - 1), r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)).mean())
                  for j in range(j0, min(n, ev['last_i'] + K + 2))]
        peak = max(series) if series else 0.0
        start_i = j0 + next((k for k, v in enumerate(series) if v > max(4.0, 0.4 * peak)), 0)
        # end: while the box keeps the look it had once in
        j = ref_i
        miss = 0
        end_i = n
        while j < n:
            dd = float(np.abs(frames[j, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16) - ref).mean())
            if dd > st['gone']:
                miss += 1
                if miss >= 3:
                    end_i = j - 2
                    break
            else:
                miss = 0
            j += 1
        if (end_i - start_i) / fps < st['min_len_s']:
            continue
        # how it came in: frames from start to fully in (the box's change against the frame before it)
        in_frames = 0
        for k in range(start_i, min(n, start_i + K + 3)):
            dd = float(np.abs(frames[k, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16) -
                              frames[k - 1, r0 * B:r1 * B, c0 * B:c1 * B].astype(np.int16)).mean())
            if dd > max(3.0, 0.25 * peak):
                in_frames = k - start_i + 1
        x0, y0, x1, y1 = c0 / wb, r0 / hb, c1 / wb, r1 / hb
        area = (x1 - x0) * (y1 - y0)
        out.append({'t': round(start_i / fps, 3), 'end': round(end_i / fps, 3), 'len': round((end_i - start_i) / fps, 3),
                    'box': [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)], 'area': round(area, 4),
                    'size': round(max(x1 - x0, (y1 - y0) * H / W) * (W / min(W, H)), 3),
                    'zone': _zone((x0 + x1) / 2, (y0 + y1) / 2), 'in_frames': in_frames,
                    'entry': 'cut' if in_frames <= 1 else 'quick (2-4 frames)' if in_frames <= 4 else 'animated',
                    'strength': round(ev['strength'], 1), 'conf': 0.6,
                    'evidence': {'screen_locked': ev['locked'], 'local_change': ev['local'],
                                 'abrupt': ev['abrupt']}})
    # relation to the face and the captions, text inside, what was said
    for o in out:
        f = _face_at(face_track, o['t'] + 0.3)
        if f:
            fb = f['box']
            fx, fy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
            ox, oy = (o['box'][0] + o['box'][2]) / 2, (o['box'][1] + o['box'][3]) / 2
            person = [fb[0] - 0.6 * (fb[2] - fb[0]), fb[1] - 0.2 * (fb[3] - fb[1]), fb[2] + 0.6 * (fb[2] - fb[0]), 1.0]
            inside = _overlap_share(o['box'], person)
            o['on_person'] = round(inside, 2)
            o['from_face'] = ('over the face' if _overlap_share(o['box'], fb) > 0.3 else
                              ('above' if oy < fy - 0.1 else 'below' if oy > fy + 0.15 else 'beside') +
                              ('' if abs(ox - fx) < 0.12 else ', left' if ox < fx else ', right'))
            if inside > 0.7:
                o['conf'] = 0.35
        txt = [e for e in text_events if e.get('role') != 'caption' and _overlap_share(e['box'], o['box']) > 0.5
               and e['t'] - 0.6 <= o['t'] <= e['end']]
        if txt:
            o['kind'] = 'text'
            o['text'] = txt[0]['text']
            o['conf'] = max(o['conf'], 0.8)
        caps = [e for e in text_events if e.get('role') == 'caption' and e['t'] - 0.5 <= o['t'] <= e['end'] + 0.5]
        if caps:
            cy = (caps[0]['box'][1] + caps[0]['box'][3]) / 2
            oy = (o['box'][1] + o['box'][3]) / 2
            o['from_captions'] = 'above' if oy < cy else 'below'
        trig = trigger(o['t'], words, cuts, fps)
        if trig:
            o.update(trig)
    # text pops and labels OCR read that the picture test did not find: overlays of kind text (the older way;
    # elements() joins text and picture finds into one event per thing on screen instead)
    for e in (text_events if add_ocr else ()):
        if e.get('role') in ('title', 'label', 'text_pop') and not any(
                _overlap_share(e['box'], o['box']) > 0.3 and abs(o['t'] - e['t']) < 0.6 for o in out):
            o = {'t': e['t'], 'end': e['end'], 'len': round(e['end'] - e['t'], 3), 'box': e['box'],
                 'area': round((e['box'][2] - e['box'][0]) * (e['box'][3] - e['box'][1]), 4),
                 'zone': _zone((e['box'][0] + e['box'][2]) / 2, (e['box'][1] + e['box'][3]) / 2),
                 'kind': 'text', 'text': e['text'], 'role': e['role'], 'conf': 0.7, 'found_by': 'ocr'}
            trig = trigger(o['t'], words, cuts, fps)
            if trig:
                o.update(trig)
            out.append(o)
    return sorted(out, key=lambda o: o['t'])


def _overlap_share(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def trigger(t, words, cuts, fps, before=0.7, after=0.35):
    """What was being said when something came in at t: the word under t (or just before), the phrase around it,
    and the kind of trigger: number, word mentioned (a content word), sentence start, punchline (after the end of a
    sentence, before a pause), at a cut, or nothing said."""
    out = {}
    at_cut = any(abs(c['t'] - t) <= 2.0 / fps for c in cuts)
    if not words:
        out['trigger'] = 'at a cut' if at_cut else 'no speech'
        return out
    near = [w for w in words if t - before <= float(w['s']) <= t + after or float(w['s']) <= t <= float(w.get('e', w['s']))]
    idx = [k for k, w in enumerate(words) if w in near]
    if not near:
        out['trigger'] = 'at a cut' if at_cut else 'between phrases'
        return out
    k0 = idx[0]
    phrase = words[max(0, k0 - 3):min(len(words), idx[-1] + 4)]
    out['said'] = ' '.join(w['w'].strip() for w in phrase)
    cw = min(near, key=lambda w: abs(float(w['s']) - t))
    out['word'] = cw['w'].strip()
    out['word_offset_s'] = round(t - float(cw['s']), 3)
    tok = re.sub(r"[^0-9a-z$%']", '', cw['w'].lower())
    content = [re.sub(r"[^0-9a-z$%']", '', w['w'].lower()) for w in near]
    if any(re.search(r'\d|\$|%', c) or c in NUM_WORDS for c in content):
        kind = 'number'
    elif k0 > 0 and float(words[k0]['s']) - float(words[k0 - 1].get('e', words[k0 - 1]['s'])) > 0.6:
        kind = 'sentence start'
    elif re.search(r'[.!?]$', words[max(0, k0 - 1)]['w'].strip()) and k0 > 0 and t - float(words[k0 - 1]['s']) < 0.8:
        kind = 'punchline'
    elif any(c and c not in STOP and len(c) > 2 for c in content):
        kind = 'word mentioned'
    else:
        kind = 'during speech'
    if at_cut:
        kind += ' + at a cut'
    out['trigger'] = kind
    return out


def kind_of(crop_bgr):
    """What an overlay looks like, from its crop: 'sticker / emoji / icon' (few strong colours, a clean edge),
    'picture' (many colours and smooth shading), 'shape / arrow' (thin strokes, little fill), 'bar' (long and thin).
    A rough guess for the AI to check against the crop."""
    import cv2
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    h, w = crop_bgr.shape[:2]
    if w > 6 * h or h > 6 * w:
        return 'bar'
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    sat = float(hsv[:, :, 1].mean())
    q = (crop_bgr // 32).reshape(-1, 3)
    colours = len({tuple(x) for x in q[::max(1, len(q) // 4000)]})
    edges = cv2.Canny(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY), 80, 160)
    edge_share = float((edges > 0).mean())
    if edge_share > 0.12 and sat < 60:
        return 'shape / arrow / text'
    if colours < 60 and sat > 70:
        return 'sticker / emoji / icon'
    if colours >= 120:
        return 'picture'
    return 'graphic'


def summarise(events, duration, kind='short'):
    if not events:
        return {'count': 0, 'per_minute': 0.0}
    good = [o for o in events if o.get('conf', 0) >= 0.5]
    mins = max(1e-6, duration / 60)
    zones = {}
    for o in good:
        zones[o['zone']] = zones.get(o['zone'], 0) + 1
    trig = {}
    for o in good:
        k = (o.get('trigger') or 'unknown').split(' + ')[0]
        trig[k] = trig.get(k, 0) + 1
    kinds = {}
    for o in good:
        k = o.get('kind') or o.get('looks_like') or 'graphic'
        kinds[k] = kinds.get(k, 0) + 1
    entries = {}
    for o in good:
        if o.get('entry'):
            entries[o['entry']] = entries.get(o['entry'], 0) + 1
    gaps = [b['t'] - a['t'] for a, b in zip(good, good[1:])]
    return {'count': len(good), 'per_minute': round(len(good) / mins, 2), 'unsure': len(events) - len(good),
            'zones': dict(sorted(zones.items(), key=lambda kv: -kv[1])), 'triggers': trig, 'kinds': kinds,
            'entries': entries,
            'on_screen_s': {'median': round(float(np.median([o['len'] for o in good])), 2)} if good else None,
            'size_median': round(float(np.median([o.get('size') or math.sqrt(o['area']) for o in good])), 3),
            'gap_s_median': round(float(np.median(gaps)), 2) if gaps else None,
            'first_at_s': round(good[0]['t'], 2) if good else None}


def graphic_score(crop_bgr):
    """How much a crop looks like something drawn (a sticker, emoji, icon, text, shape) rather than photographed:
    {colours90: how many of 64 coarse colours cover 90% of it, flat: share of pixels with no local detail,
    graphic: True when drawn-looking (few colours, or large flat areas with crisp edges)}."""
    import cv2
    if crop_bgr is None or crop_bgr.size == 0 or min(crop_bgr.shape[:2]) < 6:
        return None
    q = (crop_bgr // 64).reshape(-1, 3)
    codes = q[:, 0] * 16 + q[:, 1] * 4 + q[:, 2]
    counts = np.sort(np.bincount(codes, minlength=64))[::-1]
    c90 = int(np.searchsorted(np.cumsum(counts) / max(1, counts.sum()), 0.9) + 1)
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    flat = float((lap < 2.0).mean())
    edges = float((cv2.Canny(g, 100, 200) > 0).mean())
    # drawn things have crisp edges and flat fills together (measured on letitedit's own labels and pop-ups against
    # hands, close-ups and out-of-focus patches that the picture test also finds)
    graphic = bool(edges >= 0.05 and flat >= 0.45)
    return {'colours90': c90, 'flat': round(flat, 3), 'edges': round(edges, 3), 'graphic': graphic}


def check_looks(overlays, video, info):
    """Sharp-frame appearance check; photographic candidates remain low confidence."""
    import letitedit.looks.style_import as si
    todo = [o for o in overlays if o.get('found_by') != 'ocr' and o.get('kind') != 'text']
    if not todo:
        return overlays
    W, H = info['width'], info['height']
    width = 540 if W <= H else 960
    times = [min(o['end'] - 0.05, o['t'] + 0.45) for o in todo]
    fr = si.frames_at(video, times, width, info)
    if not fr:
        return overlays
    for o, t in zip(todo, times):
        k = min(fr, key=lambda q: abs(q - t))
        f = fr[k]
        h, w = f.shape[:2]
        x0, y0, x1, y1 = o['box']
        crop = f[max(0, int(y0 * h)):min(h, int(y1 * h)), max(0, int(x0 * w)):min(w, int(x1 * w))]
        gs = graphic_score(crop)
        if gs is None:
            continue
        o['graphic'] = gs
        o['looks_like'] = kind_of(crop)
        o['conf'] = 0.6 if gs['graphic'] else 0.35
    return overlays


# ------------------------------------------------------------------ elements: one event per thing on screen

ELEMENT_SETTINGS = {'reread_gap_s': 1.5, 'line_gap': 1.6, 'together': 0.4, 'start_within_s': 0.6,
                    'pic_before_s': 0.45, 'min_seen': 3, 'watermark_share': 0.6, 'caption_pop_s': 0.5}


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def caption_band(captions):
    """(y0, y1) of the band the captions sit in (10th to 90th percentile of their tops and bottoms, half a line of
    margin), or None with fewer than two captions."""
    if len(captions) < 2:
        return None
    lh = float(np.median([e.get('line_h') or (e['box'][3] - e['box'][1]) for e in captions]))
    y0 = float(np.percentile([e['box'][1] for e in captions], 10)) - 0.5 * lh
    y1 = float(np.percentile([e['box'][3] for e in captions], 90)) + 0.5 * lh
    return (y0, y1)


def _in_band(box, band):
    if band is None:
        return False
    cy = (box[1] + box[3]) / 2
    return band[0] <= cy <= band[1]


def _scene_texts(cand):
    """Text that shows up in different places with the same words (a sign or a sticker on a thing the camera passes,
    read from several angles): the indices of those events. Whole readings must match (a partial reading of a label
    sits off its centre and is not 'another place'), at least 6 letters, with boxes apart."""
    import difflib
    import letitedit.looks.style_import_text as T

    def squash(x):
        return ''.join(T.norm_words(x)).replace("'", '')
    out = set()
    for i, a in enumerate(cand):
        for j in range(i + 1, len(cand)):
            b = cand[j]
            sa, sb = squash(a['text']), squash(b['text'])
            if min(len(sa), len(sb)) < 8:
                continue
            # spacing aside, the shorter reading inside the longer ('YourChannelNa' / 'Y ourChannelName')
            short, long_ = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
            m = difflib.SequenceMatcher(None, short, long_).find_longest_match(0, len(short), 0, len(long_))
            if m.size < 0.8 * len(short):
                continue
            ca = ((a['box'][0] + a['box'][2]) / 2, (a['box'][1] + a['box'][3]) / 2)
            cb = ((b['box'][0] + b['box'][2]) / 2, (b['box'][1] + b['box'][3]) / 2)
            if math.hypot(ca[0] - cb[0], ca[1] - cb[1]) > 0.15 and _iou(a['box'], b['box']) == 0.0:
                out |= {i, j}
    return out


_IMG = {}


def _sample_img(path):
    import cv2
    img = _IMG.get(path)
    if img is None:
        img = cv2.imread(str(path))
        if len(_IMG) > 48:
            _IMG.clear()
        _IMG[path] = img
    return img


def glyph_overlap(path_a, path_b, box):
    """How much the text pixels in box agree between two sampled frames (the same label shows the same letters
    whatever the footage behind it; a new label in the same place does not): the text mask of the first frame
    (style_import_text._glyph_mask: light, coloured or dark letters) and the same kind of mask on the second, matched
    within a pixel. 0-1, or None when no text-like mask is found."""
    import cv2
    import letitedit.looks.style_import_text as T
    a, b = _sample_img(path_a), _sample_img(path_b)
    if a is None or b is None or a.shape != b.shape:
        return None
    h, w = a.shape[:2]
    y0, y1 = max(0, int(box[1] * h)), min(h, int(math.ceil(box[3] * h)))
    x0, x1 = max(0, int(box[0] * w)), min(w, int(math.ceil(box[2] * w)))
    if y1 - y0 < 5 or x1 - x0 < 5:
        return None
    ma, kind = T._glyph_mask(a[y0:y1, x0:x1])
    if ma is None:
        return None
    hsv = cv2.cvtColor(b[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    s_, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    mb = {'light': (v > 195) & (s_ < 75), 'colour': (v > 160) & (s_ >= 100), 'dark': (v < 70)}[kind]
    pa, pb = ma > 0, mb
    if pa.sum() < 15 or pb.sum() < 15:
        return 0.0 if (pa.sum() >= 15) != (pb.sum() >= 15) else None
    k = np.ones((3, 3), np.uint8)
    da = cv2.dilate(pa.astype(np.uint8), k) > 0
    db = cv2.dilate(pb.astype(np.uint8), k) > 0
    return round(float(((pa & db).sum() + (pb & da).sum()) / (pa.sum() + pb.sum())), 3)


def moves_with_camera(frames, fps, box, t0, t1, step_s=0.3):
    """Does text in box move with the footage (a sign the camera pans past) or stay put while the footage moves (laid
    on top)? Over the stretch, frames step_s apart: the whole frame's shift (phase correlation) against the box's own.
    'scene' when the camera moved at least 3% of the width and the box went with it, 'overlay' when the box stayed
    put, None when the camera hardly moved (then the two look the same) or nothing could be measured."""
    import cv2
    import letitedit.looks.style_import as si
    n, H, W = frames.shape
    k = max(2, int(round(step_s * fps)))
    i0, i1 = max(0, int((t0 + 0.05) * fps)), min(n - 1, int((t1 - 0.05) * fps))
    if i1 - i0 < k:
        return None
    x0, y0 = max(0, int((box[0] - 0.03) * W)), max(0, int((box[1] - 0.02) * H))
    x1, y1 = min(W, int(math.ceil((box[2] + 0.03) * W))), min(H, int(math.ceil((box[3] + 0.02) * H)))
    if x1 - x0 < 8 or y1 - y0 < 6:
        return None
    g_tot = l_tot = d_tot = 0.0
    for j in range(i0, i1 - k + 1, k):
        a, b = frames[j], frames[j + k]
        g = si.align(a, b)
        if g['response'] < 0.12:
            continue
        ca, cb = a[y0:y1, x0:x1].astype(np.float32), b[y0:y1, x0:x1].astype(np.float32)
        if ca.std() < 4:
            continue
        (lx, ly), resp = cv2.phaseCorrelate(ca, cb, si._hann(ca.shape))
        if resp < 0.08:
            continue
        g_tot += math.hypot(g['dx'], g['dy'])
        l_tot += math.hypot(lx, ly)
        d_tot += math.hypot(lx - g['dx'], ly - g['dy'])
    if g_tot < 0.03 * W:
        return None
    if d_tot < 0.4 * g_tot:
        return 'scene'
    if l_tot < 0.3 * g_tot:
        return 'overlay'
    return None


def card_shots(shots, samples, min_flat=0.75, max_colours=5, min_edges=0.02):
    """Shots that are a full-screen graphic (a title or end card: flat fills, few colours and crisp edges over the whole
    frame, measured on the sampled JPEG frames; footage measured 0.18-0.60 flat with 7-13 colours, dark out-of-focus
    footage 0.77-0.81 flat with 4 colours but soft edges (0.008-0.017), a drawn end card 0.79-0.85 flat, 3-4 colours,
    edges 0.028-0.036): [(start, end)]. Text on them belongs to the card, not to something laid on top."""
    import cv2
    out = []
    for s in shots:
        inside = [p for t, p in samples if s['start'] + 0.05 <= t <= s['end'] - 0.05]
        if not inside:
            continue
        pick = [inside[len(inside) // 4], inside[(3 * len(inside)) // 4]] if len(inside) > 1 else inside
        ok = 0
        for p in pick:
            img = cv2.imread(str(p))
            gs = graphic_score(img) if img is not None else None
            ok += bool(gs and gs['flat'] >= min_flat and gs['colours90'] <= max_colours and gs['edges'] >= min_edges)
        if ok == len(pick):
            out.append((s['start'], s['end']))
    return out


def _sample_near(samples, t, after):
    """The sampled frame's path just after t (after=True) or just before it."""
    if not samples:
        return None
    ts = [s[0] for s in samples]
    import bisect
    k = bisect.bisect_left(ts, t)
    if after:
        return samples[min(k, len(samples) - 1)][1]
    return samples[max(0, k - 1)][1]


def elements(pic, text_events, words, cuts, fps, duration, face_track=(), settings=None, cards=(), frames=None,
             samples=None):
    """One event per thing laid on the footage: OCR text events and picture-test finds joined into elements.

    - Re-reads: the same words (style_import_text.same_text: a partial or misread reading counts, a different number
      does not) in the same place within reread_gap_s are one element (OCR misses a label on some frames).
    - Lines: text lines stacked one under the other (gap up to line_gap lines, sharing a centre or overlapping) and on
      screen together are one element (a two-line label, a title and its subtitle typed on).
    - A picture find (a sudden local change that then holds: detect()) inside or around a text element is that
      element (its start, to the frame, when it comes up to pic_before_s earlier than the text was first read); one
      on the captions (in their band, within caption_pop_s of a caption) is a caption word popping in, not a pop-up;
      the rest are graphics (stickers, emoji, pictures), kept with the look test's confidence.
    - Dropped: captions (they are reported as captions), scene text (moves with the camera, or the same words in
      several places), fragments (unreadable bits), caption pieces read on their own.
    - Roles: watermark (on screen most of the video), title, label (2 s and more or across a cut), text_pop, graphic;
      card for text on a full-screen graphic shot (cards: card_shots()), kept but not counted as an overlay.
    Confidence 0.8 for text read 3+ times or confirmed by the picture, 0.4 (unsure: not counted) otherwise.
    Returns [{t, end, len, box, area, size, zone, kind, role, text, lines, conf, found_by, members, ...}]."""
    import letitedit.footage.ocr as _ocr
    import letitedit.looks.style_import_text as T
    st = {**ELEMENT_SETTINGS, **(settings or {})}
    cut_t = [c['t'] for c in cuts]
    caps = [e for e in text_events if e.get('role') == 'caption']
    band = caption_band(caps)
    # text that sits where the captions sit and looks like them (style_import_text.classify_text's second look)
    caption_like = caps + [e for e in text_events if e.get('role') == 'fragment' and e.get('by_position')]
    cap_lh = float(np.median([e.get('line_h') or 0.03 for e in caps])) if caps else None
    cand = [e for e in text_events if e.get('role') in ('title', 'label', 'text_pop', 'watermark')]
    scene = _scene_texts(cand)
    dropped = [{**cand[i], 'why': 'scene text (the same words in several places)'} for i in sorted(scene)]
    cand = [e for k, e in enumerate(cand) if k not in scene]
    # caption pieces read on their own: in the captions' band, said or unreadable or seen once
    keep = []
    for e in cand:
        if _in_band(e['box'], band) and (e.get('said_share', 0) >= 0.25 or _ocr.quality(e['text']) < 4
                                          or e.get('seen', 1) < 2):
            dropped.append({**e, 'why': 'a piece of a caption'})
            continue
        keep.append(e)
    cand = keep
    n = len(cand)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[find(i)] = find(j)
    for i in range(n):
        a = cand[i]
        for j in range(i + 1, n):
            b = cand[j]
            gap = max(b['t'] - a['end'], a['t'] - b['end'])
            both = min(a['end'], b['end']) - max(a['t'], b['t'])
            shorter = max(1e-3, min(a['end'] - a['t'], b['end'] - b['t']))
            together = both >= max(0.1, st['together'] * shorter)
            # the same words in the same place again (OCR missed it for a moment)
            near = _iou(a['box'], b['box']) >= 0.3 or _ocr._inside(a['box'], b['box']) >= 0.6 or \
                _ocr._inside(b['box'], a['box']) >= 0.6
            if near and gap <= st['reread_gap_s'] and T.same_text(a['text'], b['text'], 0.75):
                # the letters themselves must match too: a new label in the same place can share a phrase with the
                # one it replaces (measured: the same label 0.94-1.0, a new one 0.0-0.69)
                first, second = (a, b) if a['t'] <= b['t'] else (b, a)
                ib = [max(a['box'][0], b['box'][0]), max(a['box'][1], b['box'][1]), min(a['box'][2], b['box'][2]),
                      min(a['box'][3], b['box'][3])]
                g = None
                if samples and ib[2] > ib[0] and ib[3] > ib[1]:
                    g = glyph_overlap(_sample_near(samples, first['end'] - 0.03, False),
                                      _sample_near(samples, second['t'] + 0.03, True), ib)
                if g is None or g >= 0.8:
                    join(i, j)
                    continue
            # two readings of one thing at the same moment (a garbled piece and the whole line)
            if together and (_ocr._inside(a['box'], b['box']) >= 0.5 or _ocr._inside(b['box'], a['box']) >= 0.5):
                join(i, j)
                continue
            # lines of one block on screen together
            lh = max(a.get('line_h') or 0.02, b.get('line_h') or 0.02)
            top, bot = (a, b) if a['box'][1] <= b['box'][1] else (b, a)
            vgap = bot['box'][1] - top['box'][3]
            cxa, cxb = (a['box'][0] + a['box'][2]) / 2, (b['box'][0] + b['box'][2]) / 2
            stacked = (-0.5 * lh <= vgap <= st['line_gap'] * lh and
                       (min(a['box'][2], b['box'][2]) > max(a['box'][0], b['box'][0]) or abs(cxa - cxb) < 0.15))
            # (on screen together: one coming in just as the other goes is the next title, not its second line)
            if stacked and together:
                join(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cand[i])
    out = []
    for g in groups.values():
        g.sort(key=lambda e: e['t'])
        box = g[0]['box']
        for e in g[1:]:
            box = _union(box, e['box'])
        t0, t1 = min(e['t'] for e in g), max(e['end'] for e in g)
        # its text: the best reading of each line, top to bottom
        lines = []
        for e in sorted(g, key=lambda e: (e['box'][1], -len(e['text']))):
            if not any(T.same_text(e['text'], x, 0.6) for x in lines):
                lines.append(e['text'])
        seen = sum(e.get('seen', 1) for e in g)
        lh = float(np.median([e.get('line_h') or 0.02 for e in g]))
        out.append({'t': round(t0, 3), 'end': round(t1, 3), 'box': [round(v, 4) for v in box], 'kind': 'text',
                    'text': ' / '.join(lines)[:200], 'lines': len(lines), 'line_h': round(lh, 4), 'seen': seen,
                    'members': len(g), 'found_by': 'ocr', 'said_share': max(e.get('said_share', 0) for e in g),
                    'quality': max(_ocr.quality(e['text']) for e in g)})
    # picture finds: part of a text element, a caption word popping in, or a graphic of their own
    texts = list(out)
    for p in sorted(pic, key=lambda o: o['t']):
        host = None
        for e in texts:
            if (_overlap_share(p['box'], e['box']) >= 0.3 or _overlap_share(e['box'], p['box']) >= 0.5) and \
                    e['t'] - st['pic_before_s'] <= p['t'] <= e['end']:
                host = e
                break
        if host is not None:
            if p['t'] < host['t']:
                host['t'] = p['t']
            if _overlap_share(host['box'], p['box']) >= 0.5:
                host['box'] = [round(v, 4) for v in _union(host['box'], p['box'])]
            host['found_by'] = 'ocr+picture'
            host['picture'] = {k: p[k] for k in ('t', 'box', 'entry', 'in_frames') if k in p}
            continue
        on_caption = any(_overlap_share(p['box'], c['box']) >= 0.3 and c['t'] - st['caption_pop_s'] <= p['t'] <= c['end']
                         for c in caption_like)
        # word-by-word captions: a caption-sized find in the captions' band while captions run (OCR misses some
        # single words, so there need not be a caption event right there)
        word_sized = cap_lh and (p['box'][3] - p['box'][1]) <= 2.5 * cap_lh
        # text read inside it that was said just then, where captions can be: a caption word
        spoken = bool(p.get('text') and words and (band is None or _in_band(p['box'], band)) and
                      T.spoken_match({'text': p['text'], 't': p['t'] - 0.3, 'end': p['end']}, words, pad=0.7)[0] >= 0.5)
        if on_caption or spoken or (_in_band(p['box'], band) and (
                any(abs(p['t'] - c['t']) <= st['caption_pop_s'] or c['t'] <= p['t'] <= c['end'] for c in caps) or
                (word_sized and any(c['t'] - 1.5 <= p['t'] <= c['end'] + 1.5 for c in caps)))):
            dropped.append({**p, 'why': 'a caption word popping in'})
            continue
        # the same graphic found again while it is on screen (it moved or changed a little): one element
        same = next((o for o in out if o.get('found_by') == 'picture' and _iou(o['box'], p['box']) >= 0.3
                     and o['t'] <= p['t'] <= o['end'] + 0.2), None)
        if same is not None:
            same['end'] = max(same['end'], p['end'])
            same['box'] = [round(v, 4) for v in _union(same['box'], p['box'])]
            same['conf'] = max(same.get('conf', 0), p.get('conf', 0))
            continue
        q = dict(p)
        q['kind'] = 'graphic' if q.get('kind') != 'text' else 'text'
        q['found_by'] = 'picture'
        out.append(q)
    # text only OCR found: laid on top stays put while the footage moves; a sign the camera passes moves with it
    if frames is not None:
        kept = []
        for e in out:
            if e.get('found_by') == 'ocr' and e['end'] - e['t'] >= 0.4:
                mv = moves_with_camera(frames, fps, e['box'], e['t'], e['end'])
                if mv == 'scene':
                    dropped.append({**e, 'why': 'moves with the footage (text in the scene)'})
                    continue
                if mv == 'overlay':
                    e['stays_put'] = True
            kept.append(e)
        out = kept
    for e in out:
        e['len'] = round(e['end'] - e['t'], 3)
        e['area'] = round((e['box'][2] - e['box'][0]) * (e['box'][3] - e['box'][1]), 4)
        e['zone'] = _zone((e['box'][0] + e['box'][2]) / 2, (e['box'][1] + e['box'][3]) / 2)
        crosses = sum(1 for c in cut_t if e['t'] + 0.05 < c < e['end'] - 0.05)
        card = next(((a, b) for a, b in cards if a - 0.1 <= e['t'] and e['end'] <= b + 0.35), None)
        if card is not None:
            e['role'] = 'card'
        elif e['len'] >= st['watermark_share'] * duration and duration > 6:
            e['role'] = 'watermark'
        elif e['kind'] == 'text':
            e['role'] = ('title' if e.get('line_h', 0) >= 0.035 and (e['box'][1] + e['box'][3]) / 2 < 0.5 and e['len'] >= 1.5
                         else 'label' if e['len'] >= 2.0 or crosses else 'text_pop')
        else:
            e['role'] = 'graphic'
        if e['found_by'] != 'picture':
            sure = e['seen'] >= st['min_seen'] or e['found_by'] == 'ocr+picture'
            e['conf'] = 0.8 if sure and e.get('quality', 0) >= 2 else 0.4
        if e['role'] == 'card':
            # part of a full-screen graphic shot: the card's own text, kept for the record, not an overlay
            e['card_conf'] = e.get('conf')
            e['conf'] = 0.3
        f = _face_at(face_track, e['t'] + 0.3)
        if f:
            fb = f['box']
            fx, fy = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
            ox, oy = (e['box'][0] + e['box'][2]) / 2, (e['box'][1] + e['box'][3]) / 2
            e['from_face'] = ('over the face' if _overlap_share(e['box'], fb) > 0.3 else
                              ('above' if oy < fy - 0.1 else 'below' if oy > fy + 0.15 else 'beside') +
                              ('' if abs(ox - fx) < 0.12 else ', left' if ox < fx else ', right'))
        trig = trigger(e['t'], words, cuts, fps)
        if trig:
            e.update(trig)
    elements.dropped = dropped
    return sorted(out, key=lambda o: o['t'])
