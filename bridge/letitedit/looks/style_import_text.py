"""Text on screen for style_import: faces on the sampled frames, OCR (Windows' own recognizer, bridge/ocr.py), text
events, their roles (caption / title / label / text pop / watermark) and the captions' measured style: words per
caption, timing against the speech, position, size, case, fill / outline / highlight colours, the nearest fonts in
the bundled library and how captions come in.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

import numpy as np

from letitedit.looks.style_import_stats import _r, _stats


# ------------------------------------------------------------------ faces (YuNet, on the sampled frames)

_FACE = {}


def faces(samples, min_score=0.7):
    """([(t, [{box: [x0, y0, x1, y1] fractions, score}])] for every sampled frame (biggest face first), available)."""
    import cv2
    import letitedit.review.checks as checks
    if not checks.faces_available():
        return [(t, []) for t, _ in samples], False
    out = []
    for t, path in samples:
        img = cv2.imread(str(path))
        if img is None:
            out.append((t, []))
            continue
        h, w = img.shape[:2]
        det = _FACE.get((w, h))
        if det is None:
            try:
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            except AttributeError:
                pass
            det = _FACE[(w, h)] = cv2.FaceDetectorYN.create(str(checks.YUNET), '', (w, h), min_score, 0.3, 20)
        _, found = det.detect(img)
        fs = []
        for f in (found if found is not None else []):
            if f[2] < 0.04 * w:
                continue
            fs.append({'box': [round(float(f[0]) / w, 4), round(float(f[1]) / h, 4), round(float(f[0] + f[2]) / w, 4),
                               round(float(f[1] + f[3]) / h, 4)], 'score': round(float(f[-1]), 3)})
        fs.sort(key=lambda x: -(x['box'][2] - x['box'][0]) * (x['box'][3] - x['box'][1]))
        out.append((t, fs))
    return out, True


def face_summary(face_track):
    """Share of sampled frames with a face, the main face's size (height share of the frame) and where it sits."""
    with_face = [(t, fs[0]) for t, fs in face_track if fs]
    n = max(1, len(face_track))
    if not with_face:
        return {'share_with_face': 0.0, 'note': 'no face found in the sampled frames'}
    hs = [f['box'][3] - f['box'][1] for _, f in with_face]
    cx = [(f['box'][0] + f['box'][2]) / 2 for _, f in with_face]
    cy = [(f['box'][1] + f['box'][3]) / 2 for _, f in with_face]
    size = float(np.median(hs))
    framing = 'close-up' if size > 0.28 else 'medium close-up' if size > 0.16 else 'medium' if size > 0.09 else 'wide'
    return {'share_with_face': round(len(with_face) / n, 3), 'face_height': _stats(hs), 'centre_x': _stats(cx),
            'centre_y': _stats(cy), 'typical_framing': framing,
            'two_or_more_faces_share': round(sum(1 for _, fs in face_track if len(fs) >= 2) / n, 3),
            'method': 'OpenCV YuNet on the sampled frames; face height as a share of the frame height'}


def face_at(face_track, t, within=0.6):
    best = None
    for tt, fs in face_track:
        if fs and abs(tt - t) <= within and (best is None or abs(tt - t) < abs(best[0] - t)):
            best = (tt, fs[0])
    return best[1] if best else None


# ------------------------------------------------------------------ OCR and text events

def norm_words(text):
    return [w for w in re.sub(r"[^0-9a-z' ]+", ' ', str(text).lower().replace('’', "'")).split() if w.strip("'")]


def sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, ' '.join(norm_words(a)), ' '.join(norm_words(b))).ratio()


def same_text(a, b, at_least=0.7):
    """Could two readings be the same words on screen, one of them partial or misread? The shorter reading is slid
    over the longer one word by word and the best window is compared letter by letter; a number in the window that
    differs means different text ('STEP 2' is not 'STEP 3 Motor sits on 2 metal tabs', though every word of it is
    there)."""
    import difflib
    ta, tb = norm_words(a), norm_words(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(' '.join(ta)) <= len(' '.join(tb)) else (tb, ta)
    k = len(short)
    s_txt = ' '.join(short)
    best, best_win = -1.0, None
    for i in range(max(1, len(long_) - k + 1)):
        win = long_[i:i + k]
        r = difflib.SequenceMatcher(None, s_txt, ' '.join(win)).ratio()
        if r > best:
            best, best_win = r, win
    if best < at_least:
        return False
    # a number read in both readings at the same place that differs: different text (a number OCR dropped from one
    # reading is not a difference)
    sm = difflib.SequenceMatcher(None, short, best_win)
    for op, i0, i1, j0, j1 in sm.get_opcodes():
        if op != 'replace':
            continue
        for x, y in zip(short[i0:i1], best_win[j0:j1]):
            dx, dy = re.sub(r'\D', '', x), re.sub(r'\D', '', y)
            if dx and dy and dx != dy:
                return False
    return True


def blocks_of(lines):
    """Lines of one frame grouped into blocks (a caption of two lines is one block): lines one under the other, at
    most 0.8 of a line height apart, overlapping or sharing a centre horizontally."""
    import letitedit.footage.ocr as _ocr
    blocks = []
    for ln in sorted(lines, key=lambda l: l['box'][1]):
        x0, y0, x1, y1 = ln['box']
        lh = y1 - y0
        hit = None
        for b in blocks:
            bx0, by0, bx1, by1 = b['box']
            cx, bcx = (x0 + x1) / 2, (bx0 + bx1) / 2
            if -0.2 * lh <= y0 - by1 <= 0.8 * lh and (min(x1, bx1) - max(x0, bx0) > 0 or abs(cx - bcx) < 0.08):
                hit = b
                break
        if hit is None:
            blocks.append({'box': list(ln['box']), 'lines': [ln]})
        else:
            hit['lines'].append(ln)
            hit['box'] = [min(hit['box'][0], x0), min(hit['box'][1], y0), max(hit['box'][2], x1), max(hit['box'][3], y1)]
    for b in blocks:
        b['text'] = ' '.join(l['text'] for l in b['lines'])
        variants = sorted({v for l in b['lines'] for v in (l.get('alts') or {})})
        b['alts'] = sorted({' '.join((l.get('alts') or {}).get(v, l['text']) for l in b['lines']) for v in variants}
                           - {b['text']})
        b['quality'] = sum(_ocr.quality(l['text']) for l in b['lines'])
        b['line_h'] = float(np.median([l['box'][3] - l['box'][1] for l in b['lines']]))
        b['variant'] = b['lines'][0].get('variant')
    return blocks


def read_text(samples, progress=None, check=None, variants=('raw', 'light')):
    """OCR of every sampled frame: ([{t, path, blocks: [{text, box, lines, quality, line_h, variant}]}], status)."""
    import letitedit.footage.ocr as _ocr
    ok, why = _ocr.available()
    if not ok:
        return [], {'available': False, 'why': why}
    out = []
    t0 = time.monotonic()
    with _ocr.Reader() as r:
        for k, (t, path) in enumerate(samples):
            if check:
                check()
            res = _ocr.read([path], variants=variants, reader=r)[0]
            out.append({'t': t, 'path': path, 'blocks': blocks_of(res.get('lines') or [])})
            if progress and k % 10 == 0:
                progress(k / max(1, len(samples)))
    return out, {'available': True, 'lang': why, 'variants': list(variants), 'frames': len(samples),
                 'took_s': round(time.monotonic() - t0, 1), 'engine': 'Windows.Media.Ocr (built into Windows)'}


def text_events(ocr_frames, dt):
    """Text that stays put across sampled frames joined into events: [{t, end, text, box, lines, line_h, seen,
    grows, readings}]. A block continues an event when its box overlaps the event's last box and its text is the
    same (similarity 0.75) or grows from it (words added one at a time)."""
    import letitedit.footage.ocr as _ocr
    events = []
    for fr in ocr_frames:
        t = fr['t']
        for b in fr['blocks']:
            best, best_score = None, 0.0
            for ev in events:
                if t - ev['last_t'] > 1.6 * dt:
                    continue
                ov = _ocr.iou(ev['last_box'], b['box'])
                s = sim(ev['last_text'], b['text'])
                if ov <= 0.15 and not (_ocr._inside(b['box'], ev['last_box']) > 0.6
                                       or _ocr._inside(ev['last_box'], b['box']) > 0.6):
                    # the same words a little further on: text in the scene the camera moves over (a sign)
                    lb, bb = ev['last_box'], b['box']
                    dc = math.hypot((lb[0] + lb[2] - bb[0] - bb[2]) / 2, (lb[1] + lb[3] - bb[1] - bb[3]) / 2)
                    if not (s >= 0.6 and dc <= 0.15):
                        continue
                old, new = ' '.join(norm_words(ev['last_text'])), ' '.join(norm_words(b['text']))
                grows = bool(old) and new.startswith(old) and len(new) > len(old)
                score = s + (0.3 if grows else 0)
                # a label replaced by the next one in the same place can read alike ('STEP 2' -> 'STEP 3'): a
                # different number is different text
                if s >= 0.75 and not grows and not same_text(ev['last_text'], b['text'], 0.6):
                    continue
                if (s >= 0.75 or grows) and score > best_score:
                    best, best_score = ev, score
            wbox = [w['box'] for ln in b['lines'] for w in (ln.get('words') or [])]
            rd = (t, b['text'], b['quality'], b['box'], len(b['lines']), b['line_h'], b.get('variant'), fr.get('path'),
                  wbox, b.get('alts') or [])
            if best is None:
                events.append({'t': t, 'last_t': t, 'last_box': b['box'], 'last_text': b['text'], 'readings': [rd]})
            else:
                best['last_t'] = t
                best['last_box'] = b['box']
                best['last_text'] = b['text']
                best['readings'].append(rd)
    out = []
    for ev in events:
        rd = ev['readings']
        top = max(r[2] for r in rd)
        good = [r for r in rd if r[2] >= top - 2]
        best = max(good, key=lambda r: (len(r[1]), r[2]))
        boxes = np.array([r[3] for r in rd])
        out.append({'t': round(ev['t'], 3), 'end': round(ev['last_t'] + dt, 3), 'text': best[1],
                    'box': [round(float(v), 4) for v in np.median(boxes, 0)],
                    'lines': int(round(float(np.median([r[4] for r in rd])))),
                    'line_h': round(float(np.median([r[5] for r in rd])), 4),
                    'seen': len(rd), 'grows': len(set(len(norm_words(r[1])) for r in rd)) > 1,
                    'variant': best[6], 'best_frame': best[7], 'best_t': best[0],
                    'readings': [{'t': r[0], 'text': r[1], 'box': r[3], 'path': r[7], 'words': r[8],
                                  'lines': r[4], 'alts': r[9]} for r in rd[:16]],
                    'texts': sorted({r[1] for r in rd} | {a for r in rd for a in r[9]})[:40]})
    return sorted(out, key=lambda e: e['t'])


def refine_text_times(events, feat, fps, dt):
    """Each event's start and end moved onto the frame where its box changes most (within one sample period before
    the first / after the last sighting), from the grey frame differences: text times to the frame."""
    bd = feat['blocks']
    n = len(bd)
    hb, wb = bd.shape[1], bd.shape[2]
    for ev in events:
        x0, y0, x1, y1 = ev['box']
        r0, r1 = max(0, int(y0 * hb)), min(hb, int(math.ceil(y1 * hb)))
        c0, c1 = max(0, int(x0 * wb)), min(wb, int(math.ceil(x1 * wb)))
        if r1 <= r0 or c1 <= c0:
            continue
        for key, lo_t, hi_t in (('t', ev['t'] - dt, ev['t'] + 0.5 / fps), ('end', ev['end'] - dt, ev['end'] + 0.5 / fps)):
            lo, hi = max(1, int(lo_t * fps)), min(n - 1, int(math.ceil(hi_t * fps)))
            if hi <= lo:
                continue
            series = bd[lo:hi + 1, r0:r1, c0:c1].astype(np.float32).mean(axis=(1, 2))
            k = int(np.argmax(series))
            if series[k] > 3.0:
                ev[key] = round((lo + k) / fps, 3)
        if ev['end'] <= ev['t']:
            ev['end'] = round(ev['t'] + dt, 3)
    return events


def text_masks(events, feat, fps, pad=0.15):
    """masks(i) -> boolean (hb, wb) array of the blocks covered by any text event live at frame i (with a margin),
    for leaving text out of the cut detector."""
    bd = feat['blocks']
    n, hb, wb = bd.shape
    per = [[] for _ in range(n)]
    for ev in events:
        x0, y0, x1, y1 = ev['box']
        mx, my = 0.02, max(0.01, 0.4 * ev.get('line_h', 0.03))
        r0, r1 = max(0, int((y0 - my) * hb)), min(hb, int(math.ceil((y1 + my) * hb)))
        c0, c1 = max(0, int((x0 - mx) * wb)), min(wb, int(math.ceil((x1 + mx) * wb)))
        f0, f1 = max(0, int((ev['t'] - pad) * fps)), min(n - 1, int(math.ceil((ev['end'] + pad) * fps)))
        for i in range(f0, f1 + 1):
            per[i].append((r0, r1, c0, c1))

    def masks(i):
        if not per[i]:
            return None
        m = np.zeros((hb, wb), bool)
        for r0, r1, c0, c1 in per[i]:
            m[r0:r1, c0:c1] = True
        return m
    return masks


def spoken_match(ev, words, pad=1.0):
    """How much of an event's text was said around it: (share of its words found among the words said in
    [t - pad, end + pad], the matched spoken words in time order)."""
    import difflib
    toks = norm_words(ev['text'])
    if not toks:
        return 0.0, []
    near = [w for w in words if ev['t'] - pad <= float(w['s']) <= ev['end'] + pad]
    spoken = [(norm_words(w['w']) or [''])[0] for w in near]
    used = set()
    matched = []
    sims = []
    for tok in toks:
        best, bj = 0.0, None
        for j, sp in enumerate(spoken):
            if j in used or not sp:
                continue
            r = 1.0 if sp == tok else difflib.SequenceMatcher(None, sp, tok).ratio()
            if r > best or (r == best and bj is not None and abs(float(near[j]['s']) - ev['t']) <
                            abs(float(near[bj]['s']) - ev['t'])):
                best, bj = r, j
        if bj is not None and best >= 0.75:
            used.add(bj)
            matched.append(near[bj])
            sims.append(best)
    spoken_match.last_similarity = float(np.mean(sims)) if sims else 0.0
    return len(matched) / len(toks), sorted(matched, key=lambda w: float(w['s']))


def classify_text(events, words, duration, cuts):
    """Each text event gets a role: caption (what is said, written as it is said), watermark (on screen for most of
    the video), title (large, upper half, 1.5 s or more, not said), label (stays across a cut or 2 s and more, not said),
    text_pop (short, not said)."""
    import letitedit.footage.ocr as _ocr
    cut_t = [c['t'] for c in cuts]
    for ev in events:
        ev['role'] = None
        # text in the scene (a sign, a label on a box) moves or changes size with the camera; text laid on top stays
        # (only readings of the whole text: a partial reading of a label is shorter and sits off its centre, which is
        # not a move; the same words smaller or elsewhere are)
        full = ev['text']
        bx = [r['box'] for r in ev.get('readings') or [] if sim(r.get('text', full), full) >= 0.8
              and len(r.get('text', full)) >= 0.85 * len(full)]
        if len(bx) >= 3:
            cxs = [(b[0] + b[2]) / 2 for b in bx]
            cys = [(b[1] + b[3]) / 2 for b in bx]
            hs = [b[3] - b[1] for b in bx]
            drift = max(max(cxs) - min(cxs), max(cys) - min(cys))
            grow = (max(hs) - min(hs)) / max(1e-6, float(np.median(hs)))
            if (drift > 0.04 or grow > 0.25) and not ev.get('grows'):
                ev['role'] = 'scene'
        import letitedit.footage.ocr as _ocr2
        letters = sum(ch.isalnum() for ch in ev['text'])
        once = ev.get('seen', 1) < 2
        if letters < 3 or (once and _ocr2.quality(ev['text']) < 3) or (
                once and letters < 6 and not ev['text'].strip().isupper()):
            ev['role'] = 'fragment'
    for ev in events:
        if ev['role'] in ('scene', 'fragment'):
            ev['said_share'] = 0.0
            continue
        if words and ev.get('texts'):
            # the reading (of every frame and every OCR variant) that best matches what was said, then the cleanest
            best = None
            for txt in ev['texts']:
                sh, _ = spoken_match({**ev, 'text': txt}, words)
                key = (round(sh, 2), round(spoken_match.last_similarity, 3), _ocr.quality(txt))
                if best is None or key > best[0]:
                    best = (key, txt)
            if best and best[0][0] > 0:
                ev['ocr_text'] = ev['text']
                ev['text'] = best[1]
        share, matched = spoken_match(ev, words) if words else (0.0, [])
        ev['said_share'] = round(share, 2)
        if matched:
            ev['said'] = [{'w': w['w'], 's': round(float(w['s']), 3), 'e': round(float(w.get('e', w['s'])), 3)}
                          for w in matched]
        length = ev['end'] - ev['t']
        crosses = sum(1 for c in cut_t if ev['t'] + 0.05 < c < ev['end'] - 0.05)
        if length >= 0.6 * duration and duration > 6:
            role = 'watermark'
        elif share >= 0.5:
            role = 'caption'
        elif ev['line_h'] >= 0.035 and (ev['box'][1] + ev['box'][3]) / 2 < 0.5 and length >= 1.5:
            role = 'title'
        elif crosses >= 1 or length >= 2.0:
            role = 'label'
        else:
            role = 'text_pop'
        ev['role'] = role
    # where the captions sit: text far from there is a label or a title even when its words are said
    caps = [e for e in events if e['role'] == 'caption']
    if len(caps) >= 3:
        zy = float(np.median([(e['box'][1] + e['box'][3]) / 2 for e in caps]))
        zlh = float(np.median([e['line_h'] for e in caps]))
        for e in caps:
            cy = (e['box'][1] + e['box'][3]) / 2
            if abs(cy - zy) > max(0.12, 3 * zlh):
                crosses = sum(1 for c in cut_t if e['t'] + 0.05 < c < e['end'] - 0.05)
                e['role'] = 'label' if (e['end'] - e['t'] >= 2.0 or crosses) else 'text_pop'
                e['said_text'] = True
    # second look: text that sits where the captions sit and is as big as they are is a caption the reading or the
    # speech match missed (half its words said), or an unreadable piece of one (a fragment), not a text pop
    caps = [e for e in events if e['role'] == 'caption']
    if len(caps) >= 3:
        y0 = float(np.percentile([e['box'][1] for e in caps], 10))
        y1 = float(np.percentile([e['box'][3] for e in caps], 90))
        lh = float(np.median([e['line_h'] for e in caps]))
        for ev in events:
            if ev['role'] not in ('text_pop', 'label') or ev['end'] - ev['t'] > 3.0:
                continue
            cy = (ev['box'][1] + ev['box'][3]) / 2
            if y0 - 0.5 * lh <= cy <= y1 + 0.5 * lh and 0.7 * lh <= ev['line_h'] <= 1.4 * lh:
                ev['role'] = 'caption' if ev.get('said_share', 0) >= 0.25 else 'fragment'
                ev['by_position'] = True
    return merge_captions(events)


def merge_captions(events):
    """One caption per caption: caption events that run on from each other (the next starts before the previous
    ends or within 0.1 s) in the same place (boxes overlapping or one line under the other) and share words (one's
    words inside the other's: words popping in one at a time, a second line coming in) become one event."""
    caps = sorted([e for e in events if e.get('role') == 'caption'], key=lambda e: e['t'])
    rest = [e for e in events if e.get('role') != 'caption']
    out = []
    for e in caps:
        prev = out[-1] if out else None
        if prev is not None and e['t'] <= prev['end'] + 0.1:
            a, b = prev['box'], e['box']
            lh = max(prev.get('line_h', 0.03), e.get('line_h', 0.03))
            close = (min(a[2], b[2]) > max(a[0], b[0]) and (min(a[3], b[3]) > max(a[1], b[1])
                                                            or 0 <= b[1] - a[3] <= 1.2 * lh or 0 <= a[1] - b[3] <= 1.2 * lh))
            wa, wb = norm_words(prev['text']), norm_words(e['text'])
            # one caption: words popping in (one's words inside the other's) or a second line coming in under the
            # first (no shared words, the next one directly below); two different captions back to back stay apart
            grows = bool(wa) and bool(wb) and (set(wa) <= set(wb) or set(wb) <= set(wa))
            below = (0 <= b[1] - a[3] <= 1.2 * lh) and not (set(wa) & set(wb))
            if close and (grows or below):
                prev['end'] = max(prev['end'], e['end'])
                prev['box'] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                if set(wa) <= set(wb):
                    prev['text'] = e['text']
                elif not set(wb) <= set(wa):
                    prev['text'] = prev['text'] + ' ' + e['text']
                prev['lines'] = max(prev.get('lines', 1), e.get('lines', 1),
                                    1 + int(abs(((a[1] + a[3]) - (b[1] + b[3])) / 2) > 0.6 * lh))
                prev['said'] = sorted({(w['w'], w['s'], w['e']) for w in (prev.get('said') or []) + (e.get('said') or [])},
                                      key=lambda w: w[1])
                prev['said'] = [{'w': w[0], 's': w[1], 'e': w[2]} for w in prev['said']]
                prev['readings'] = (prev.get('readings') or []) + (e.get('readings') or [])
                prev['seen'] = prev.get('seen', 1) + e.get('seen', 1)
                prev['grows'] = True
                prev['merged'] = prev.get('merged', 1) + 1
                continue
        out.append(e)
    return sorted(out + rest, key=lambda e: e['t'])


# ------------------------------------------------------------------ caption look

def _glyph_mask(crop):
    """The text pixels of a caption crop: the light, coloured or dark mask whose connected parts look most like
    letters (heights 25-100% of the crop's text height, a few to many of them). (mask uint8, kind)."""
    import cv2
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    cands = {'light': (v > 195) & (s < 75), 'colour': (v > 160) & (s >= 100), 'dark': (v < 70)}
    h = crop.shape[0]
    best, best_score = None, -1
    for kind, m in cands.items():
        m = m.astype(np.uint8) * 255
        share = (m > 0).mean()
        if share < 0.04 or share > 0.7:
            continue
        nlab, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        glyphs = [i for i in range(1, nlab) if 0.2 * h <= st[i, cv2.CC_STAT_HEIGHT] <= 1.05 * h
                  and st[i, cv2.CC_STAT_AREA] >= 6]
        score = len(glyphs) - 3 * max(0, nlab - 1 - 3 * max(1, len(glyphs))) / 10
        if score > best_score:
            best, best_score = (m, kind), score
    return best if best else (None, None)


def _hex(bgr):
    b, g, r = (int(round(float(x))) for x in bgr)
    return f'#{r:02X}{g:02X}{b:02X}'


def caption_look(crop):
    """Fill, outline, shadow and plate of one caption crop (BGR, full resolution, a little margin around the text).
    {fill, fill_kind, outline: {color, width_px} | None, shadow: bool, plate: color | None, stroke_ratio}"""
    import cv2
    mask, kind = _glyph_mask(crop)
    if mask is None:
        return None
    er = cv2.erode(mask, np.ones((2, 2), np.uint8))
    px = crop[er > 0] if (er > 0).sum() > 30 else crop[mask > 0]
    fill = np.median(px, 0)
    out = {'fill': _hex(fill), 'fill_kind': kind}
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # outline: rings around the glyphs, 1 px at a time; dark and even = an outline, its width where that stops
    prev = mask.copy()
    widths = []
    ring_cols = []
    fill_v = float(cv2.cvtColor(np.uint8([[fill]]), cv2.COLOR_BGR2HSV)[0, 0, 2])
    for k in range(1, 16):
        grown = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
        ring = (grown > 0) & (prev == 0)
        prev = grown
        if ring.sum() < 20:
            break
        vv = hsv[:, :, 2][ring].astype(np.float32)
        col = np.median(crop[ring], 0)
        ring_cols.append(col)
        contrast = abs(float(np.median(vv)) - fill_v)
        widths.append((k, float(np.median(vv)), float(np.std(vv)), contrast))
    edge = [w for w in widths if w[3] > 90 and w[2] < 55]
    if edge and edge[0][0] <= 2:
        k_last = edge[0][0]
        for w in widths[edge[0][0]:]:
            if w[3] > 70 and w[2] < 60:
                k_last = w[0]
            else:
                break
        out['outline'] = {'color': _hex(ring_cols[0]), 'width_px': k_last}
    else:
        out['outline'] = None
    # shadow: dark pixels below-right of the glyphs, not above-left
    sh = int(max(2, crop.shape[0] * 0.04))
    down = np.roll(np.roll(mask, sh, 0), sh, 1)
    up = np.roll(np.roll(mask, -sh, 0), -sh, 1)
    grown = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    vd = hsv[:, :, 2][(down > 0) & (grown == 0)]
    vu = hsv[:, :, 2][(up > 0) & (grown == 0)]
    out['shadow'] = bool(len(vd) > 20 and len(vu) > 20 and float(np.median(vd)) + 35 < float(np.median(vu)))
    # plate: an even colour around the text (a box behind it)
    border = np.ones(mask.shape, bool)
    m2 = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
    border &= ~m2
    if border.sum() > 50:
        bp = crop[border].astype(np.float32)
        if float(bp.std(0).mean()) < 18:
            out['plate'] = _hex(np.median(bp, 0))
        else:
            out['plate'] = None
    # stroke thickness against the text height: thin (regular) to heavy (black)
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
    th = float(np.percentile(dist[mask > 0], 90)) * 2 if (mask > 0).any() else 0
    rows = np.where((mask > 0).any(1))[0]
    text_h = (rows[-1] - rows[0] + 1) if len(rows) else crop.shape[0]
    out['stroke_ratio'] = round(th / max(1, text_h), 3)
    out['weight_guess'] = ('black' if out['stroke_ratio'] > 0.2 else 'bold' if out['stroke_ratio'] > 0.14
                           else 'regular')
    return out


def highlight(crop, ocr_words_boxes, box):
    """Is one word set apart (an active-word highlight)? From the word boxes OCR gives (fractions of the frame) and
    the line box: each word's mean saturation and hue over its box; one word far from the others = highlighted.
    Returns {index, color, kind: 'box' | 'text'} or None."""
    import cv2
    H, W = crop.shape[:2]
    x0, y0, x1, y1 = box
    sat, hue, cols, fills = [], [], [], []
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    for wb in ocr_words_boxes:
        a = int((wb[0] - x0) / max(1e-6, x1 - x0) * W)
        b = int((wb[2] - x0) / max(1e-6, x1 - x0) * W)
        c = int((wb[1] - y0) / max(1e-6, y1 - y0) * H)
        d = int((wb[3] - y0) / max(1e-6, y1 - y0) * H)
        a, b = max(0, a), min(W, b)
        c, d = max(0, c), min(H, d)
        if b - a < 3 or d - c < 3:
            sat.append(None)
            continue
        reg = hsv[c:d, a:b]
        sat.append(float(reg[:, :, 1].mean()))
        hue.append(float(np.median(reg[:, :, 0])))
        cols.append(np.median(crop[c:d, a:b].reshape(-1, 3), 0))
        fills.append(float(((reg[:, :, 1] > 110) & (reg[:, :, 2] > 120)).mean()))
    vals = [s for s in sat if s is not None]
    if len(vals) < 2:
        return None
    k = int(np.argmax([s if s is not None else -1 for s in sat]))
    others = [s for j, s in enumerate(sat) if j != k and s is not None]
    if sat[k] - max(others) < 45:
        return None
    j = [i for i, s in enumerate(sat) if s is not None].index(k)
    return {'index': k, 'color': _hex(cols[j]), 'kind': 'box' if fills[j] > 0.45 else 'text'}


def font_candidates(mask_crop, text, limit=5, families=None):
    """Bundled fonts ranked by how closely the same text drawn in them matches the caption's letter shapes: the
    caption mask and each rendering are scaled to the same height and compared (width ratio, overlap after
    stretching to the same width, stroke thickness). An estimate: says which faces look most alike, not the font
    used. [{family, weight, score}]"""
    import cv2
    import letitedit.catalogs.fonts as F
    from PIL import Image, ImageDraw
    text = ' '.join(str(text).split())[:24]
    if len(re.sub(r'\W', '', text)) < 4:
        return []
    rows = np.where(mask_crop.any(1))[0]
    cols = np.where(mask_crop.any(0))[0]
    if not len(rows) or not len(cols):
        return []
    m = mask_crop[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    H = 48
    tgt = cv2.resize(m, (max(8, int(m.shape[1] * H / m.shape[0])), H), interpolation=cv2.INTER_AREA) > 127
    tgt_ar = tgt.shape[1] / H
    tgt_ink = tgt.mean()
    cat = F.catalog()
    out = []
    for fam in cat:
        name = fam['family']
        if families and name not in families:
            continue
        ws = sorted({int(re.sub(r'\D', '', w) or 400) for w in fam.get('weights') or ['400'] if not w.endswith('i')})
        for wgt in [w for w in ws if w in (400, 700, 800, 900)] or ws[:1]:
            try:
                font = F.pil_font(name, 64, weight=wgt)
            except Exception:  # noqa: BLE001
                continue
            img = Image.new('L', (64 * len(text) + 40, 120), 0)
            ImageDraw.Draw(img).text((10, 20), text, fill=255, font=font)
            a = np.array(img)
            r_ = np.where(a.max(1) > 127)[0]
            c_ = np.where(a.max(0) > 127)[0]
            if not len(r_) or not len(c_):
                continue
            g = a[r_[0]:r_[-1] + 1, c_[0]:c_[-1] + 1]
            ren = cv2.resize(g, (max(8, int(g.shape[1] * H / g.shape[0])), H), interpolation=cv2.INTER_AREA) > 127
            ar = ren.shape[1] / H
            ren_s = cv2.resize(ren.astype(np.uint8), (tgt.shape[1], H), interpolation=cv2.INTER_NEAREST) > 0
            inter = (ren_s & tgt).sum()
            union = (ren_s | tgt).sum()
            iou = inter / max(1, union)
            score = iou - 0.6 * abs(math.log(ar / tgt_ar)) - 1.5 * abs(ren.mean() - tgt_ink)
            out.append({'family': name, 'weight': wgt, 'category': fam.get('category'), 'score': round(float(score), 3),
                        'overlap': round(float(iou), 3)})
    out.sort(key=lambda x: -x['score'])
    seen, top = set(), []
    for o in out:
        if o['family'] in seen:
            continue
        seen.add(o['family'])
        top.append(o)
        if len(top) >= limit:
            break
    return top


def entry_motion(frames_bgr, box, fps):
    """How a caption (or any box) comes in over the frames from just before it to ~0.4 s after: the text mask's
    height, width, centre and brightness frame by frame -> 'pop' (grows to full size in 2-9 frames), 'bounce'
    (grows past full size and settles), 'slide' (the centre moves), 'fade' (same size, brightening), 'typewriter'
    (width grows, height steady) or 'cut' (whole in one frame)."""
    import cv2
    if len(frames_bgr) < 4:
        return None
    H, W = frames_bgr[0].shape[:2]
    x0, y0, x1, y1 = box
    mx, my = 0.06 * (x1 - x0) + 0.01, 0.6 * (y1 - y0)
    a, b = max(0, int((x0 - mx) * W)), min(W, int((x1 + mx) * W))
    c, d = max(0, int((y0 - my) * H)), min(H, int((y1 + my) * H))
    final_mask, kind = _glyph_mask(frames_bgr[-1][c:d, a:b])
    if final_mask is None:
        return None
    series = []
    for f in frames_bgr:
        crop = f[c:d, a:b]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        s, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
        m = {'light': (v > 195) & (s < 75), 'colour': (v > 160) & (s >= 100), 'dark': (v < 70)}[kind]
        m = m & (cv2.dilate(final_mask, np.ones((25, 25), np.uint8)) > 0)
        ys, xs = np.where(m)
        if len(ys) < 15:
            series.append(None)
            continue
        series.append({'h': float(np.percentile(ys, 97) - np.percentile(ys, 3)),
                       'w': float(np.percentile(xs, 97) - np.percentile(xs, 3)),
                       'cy': float(ys.mean()), 'cx': float(xs.mean()), 'n': int(len(ys)),
                       'v': float(v[m].mean())})
    full = [x for x in series[-3:] if x]
    if not full:
        return None
    Hf = float(np.median([x['h'] for x in full]))
    Wf = float(np.median([x['w'] for x in full]))
    Nf = float(np.median([x['n'] for x in full]))
    first = next((k for k, x in enumerate(series) if x and x['n'] > 0.15 * Nf), None)
    if first is None:
        return None
    grow = [x['h'] / Hf if x else 0 for x in series[first:]]
    widen = [x['w'] / Wf if x else 0 for x in series[first:]]
    reach = next((k for k, g in enumerate(grow) if g >= 0.95), len(grow))
    over = max(grow) if grow else 1
    moved = max(abs(x['cy'] - series[-1]['cy']) for x in series[first:] if x) / max(1.0, d - c) if series[-1] else 0
    ink = [x['n'] / Nf if x else 0 for x in series[first:]]
    if reach == 0 and (ink[0] > 0.8):
        style = 'cut'
    elif over > 1.08 and reach <= 9:
        style = 'bounce'
    elif reach <= 9 and grow[0] < 0.85:
        style = 'pop'
    elif moved > 0.25:
        style = 'slide'
    elif widen and widen[0] < 0.7 and grow[0] > 0.85:
        style = 'typewriter'
    elif ink[0] < 0.6:
        style = 'fade'
    else:
        style = 'cut'
    return {'style': style, 'frames_to_full': int(reach), 'overshoot': round(over, 3),
            'ms_to_full': int(round(reach / fps * 1000))}


def caption_geometry(events):
    """Per-caption geometry and separated size groups; positions are fractions of the decoded picture."""
    measured, unmeasured = [], 0
    for event in events:
        if event.get('role') != 'caption':
            continue
        height, box = event.get('line_h'), event.get('box')
        if height is None or not math.isfinite(height) or height <= 0 or not box or len(box) != 4:
            unmeasured += 1
            continue
        measured.append({'t': event['t'], 'end': event['end'], 'line_height_share': height,
                         'box': list(box), 'words': len(norm_words(event.get('text', ''))),
                         'grows': bool(event.get('grows'))})
    groups = []
    for event in sorted(measured, key=lambda row: row['line_height_share']):
        if not groups or event['line_height_share'] > 1.6 * np.median(groups[-1]):
            groups.append([])
        groups[-1].append(event['line_height_share'])
    return {'events': measured, 'unmeasured': unmeasured,
            'size_groups': [{'count': len(group), 'line_height_share': _stats(group, 4)} for group in groups],
            'mixed_sizes': sum(len(group) >= 2 for group in groups) > 1,
            'method': 'OCR line heights grouped at a 1.6x gap from the group median; not a font-size recovery'}


def caption_style(events, info, video, words, fps, grab_frames, progress=None, max_look=10, max_motion=10):
    """The captions' measured style from the caption events. grab_frames(times, width) -> {t: BGR} (full
    resolution reads)."""
    import cv2
    caps = [e for e in events if e['role'] == 'caption']
    if not caps:
        return {'present': False}
    W, H = info['width'], info['height']
    wpc = [len(norm_words(e['text'])) for e in caps]
    lines = [e['lines'] for e in caps]
    durs = [e['end'] - e['t'] for e in caps]
    lead = [e['t'] - e['said'][0]['s'] for e in caps if e.get('said')]
    tail = [e['end'] - e['said'][-1]['e'] for e in caps if e.get('said')]
    cx = [(e['box'][0] + e['box'][2]) / 2 for e in caps]
    cy = [(e['box'][1] + e['box'][3]) / 2 for e in caps]
    lh = [e['line_h'] for e in caps]
    widths = [e['box'][2] - e['box'][0] for e in caps]
    letters = ''.join(re.sub(r'[^A-Za-z]', '', e['text']) for e in caps)
    upper = sum(1 for ch in letters if ch.isupper()) / max(1, len(letters))
    words_all = [w for e in caps for w in re.findall(r"[A-Za-z][A-Za-z']*", e['text'])]
    title = sum(1 for w in words_all if w[0].isupper()) / max(1, len(words_all))
    case = 'ALL CAPS' if upper > 0.85 else 'Title Case' if title > 0.8 else 'lower case' if upper < 0.02 else 'sentence case'
    med_w = float(np.median(wpc))
    chunking = ('one word at a time' if med_w <= 1.3 else 'two or three words' if med_w <= 3.4
                else 'short phrases' if med_w <= 6 else 'full sentences')
    out = {'present': True, 'count': len(caps), 'geometry': caption_geometry(events),
           'words_per_caption': _stats(wpc, 2), 'chunking': chunking,
           'lines_per_caption': _stats(lines, 2), 'on_screen_s': _stats(durs),
           'lead_s': _stats(lead), 'tail_s': _stats(tail),
           'timing': ('word-synced (starts with the word)' if lead and abs(float(np.median(lead))) < 0.12 else
                      'early (before the words)' if lead and float(np.median(lead)) < -0.12 else
                      'late (after the words start)' if lead else 'unknown'),
           'position': {'x': _stats(cx), 'y': _stats(cy),
                        'zone': ('top' if np.median(cy) < 0.33 else 'middle' if np.median(cy) < 0.6 else
                                 'lower third' if np.median(cy) < 0.8 else 'bottom')},
           'size': {'line_height_share': _stats(lh, 4), 'line_height_px_at_1080': round(float(np.median(lh)) * 1920 *
                                                                                      (1080 / 1080 if H >= W else 1080 / 1920), 1),
                    'width_share': _stats(widths)},
           'case': case, 'upper_share': round(upper, 3),
           'grows_word_by_word_share': round(sum(1 for e in caps if e['grows']) / len(caps), 3)}
    # the look, on the clearest captions read again at full size
    pick = sorted(caps, key=lambda e: (-len(re.sub(r'\W', '', e['text'])), -e['seen']))[:max_look]
    times = [e.get('best_t', e['t']) for e in pick]
    full = grab_frames(times, W)
    looks, hls, font_votes = [], [], {}
    for e, t in zip(pick, times):
        f = full.get(round(t, 4)) if full else None
        if f is None and full:
            k = min(full, key=lambda q: abs(q - t))
            f = full[k] if abs(k - t) < 0.2 else None
        if f is None:
            continue
        x0, y0, x1, y1 = e['box']
        mx, my = 0.02, 0.35 * e['line_h']
        a, b = max(0, int((x0 - mx) * W)), min(W, int((x1 + mx) * W))
        c, d = max(0, int((y0 - my) * H)), min(H, int((y1 + my) * H))
        crop = f[c:d, a:b]
        if crop.size == 0:
            continue
        lk = caption_look(crop)
        if lk:
            looks.append(lk)
        if len(font_votes) < 4 and lk and e['lines'] == 1 and len(re.sub(r'\W', '', e['text'])) >= 6:
            mask, _ = _glyph_mask(crop)
            if mask is not None:
                for cand in font_candidates(mask, e['text'], limit=5):
                    v = font_votes.setdefault(cand['family'], {'family': cand['family'], 'weight': cand['weight'],
                                                               'category': cand['category'], 'score': 0.0, 'n': 0})
                    v['score'] += cand['score']
                    v['n'] += 1
    hl_events = 0
    hl_moves = 0
    hl_cols, hl_kinds = [], []
    for e in [c for c in caps if len(norm_words(c['text'])) >= 2][:40]:
        seen = []
        for rd in e['readings'][:6]:
            if rd.get('lines') != 1 or len(rd.get('words') or []) < 2 or not rd.get('path'):
                continue
            img = cv2.imread(str(rd['path']))
            if img is None:
                continue
            h_, w_ = img.shape[:2]
            x0, y0, x1, y1 = rd['box']
            crop = img[max(0, int(y0 * h_)):int(math.ceil(y1 * h_)), max(0, int(x0 * w_)):int(math.ceil(x1 * w_))]
            if crop.size == 0:
                continue
            hl = highlight(crop, rd['words'], rd['box'])
            if hl:
                seen.append(hl)
        if seen:
            hl_events += 1
            hl_cols += [h['color'] for h in seen]
            hl_kinds += [h['kind'] for h in seen]
            if len({h['index'] for h in seen}) > 1:
                hl_moves += 1
    multi = sum(1 for c in caps if len(norm_words(c['text'])) >= 2)
    if multi:
        out['highlight'] = {'captions_with_one_word_set_apart': hl_events, 'of_multi_word_captions': min(multi, 40),
                            'moves_word_to_word': hl_moves,
                            'color': _common_colour(hl_cols) if hl_cols else None,
                            'kind': max(set(hl_kinds), key=hl_kinds.count) if hl_kinds else None,
                            'present': hl_events >= max(2, 0.3 * min(multi, 40))}
    if looks:
        def vote(key):
            vals = [lk.get(key) for lk in looks]
            vals = [v for v in vals if v is not None]
            if not vals:
                return None
            return max(set(vals), key=vals.count)
        fills = [lk['fill'] for lk in looks]
        out['look'] = {'fill': _common_colour(fills), 'fill_kind': vote('fill_kind'),
                       'outline': _common_outline([lk.get('outline') for lk in looks]),
                       'shadow_share': round(sum(1 for lk in looks if lk.get('shadow')) / len(looks), 2),
                       'plate': _common_colour([lk['plate'] for lk in looks if lk.get('plate')])
                       if sum(1 for lk in looks if lk.get('plate')) >= 0.5 * len(looks) else None,
                       'weight_guess': vote('weight_guess'),
                       'stroke_ratio': _stats([lk['stroke_ratio'] for lk in looks]),
                       'read_from': len(looks)}
    if font_votes:
        ranked = sorted(font_votes.values(), key=lambda v: -v['score'] / max(1, v['n']) - 0.05 * v['n'])
        out['font_guess'] = [{'family': v['family'], 'weight': v['weight'], 'category': v['category'],
                              'score': round(v['score'] / v['n'], 3), 'votes': v['n']} for v in ranked[:5]]
        out['font_note'] = ('nearest bundled fonts by letter shape (an estimate; similar sans faces score close: look '
                            'at the caption crops before choosing)')
    # how they come in, at full frame rate around the first captions
    motions = []
    for e in caps[:max_motion]:
        fr = grab_window(video, info, e['t'] - 2.0 / fps, 0.45, 540)
        mo = entry_motion(fr, e['box'], fps) if fr else None
        if mo:
            motions.append(mo)
    if motions:
        styles = [m['style'] for m in motions]
        out['entry'] = {'style': max(set(styles), key=styles.count), 'styles': {s: styles.count(s) for s in set(styles)},
                        'ms_to_full': _stats([m['ms_to_full'] for m in motions]),
                        'overshoot': _stats([m['overshoot'] for m in motions])}
    return out


def grab_window(video, info, start, duration, width):
    import letitedit.looks.style_import as si
    try:
        return si.grab_range({**info, 'path': str(video)}, max(0.0, start), duration, width)
    except Exception:  # noqa: BLE001
        return []


def _common_colour(hexes):
    """The most common colour among hex strings, colours within ~40 of each other counted together."""
    if not hexes:
        return None
    rgb = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in hexes]
    best, best_n = rgb[0], 0
    for c in rgb:
        n = sum(1 for o in rgb if sum(abs(a - b) for a, b in zip(c, o)) < 60)
        if n > best_n:
            best, best_n = c, n
    group = [o for o in rgb if sum(abs(a - b) for a, b in zip(best, o)) < 60]
    m = np.median(np.array(group), 0)
    return '#%02X%02X%02X' % tuple(int(round(v)) for v in m)


def _common_outline(outlines):
    have = [o for o in outlines if o]
    if len(have) < 0.5 * max(1, len(outlines)):
        return None
    return {'color': _common_colour([o['color'] for o in have]),
            'width_px': int(round(float(np.median([o['width_px'] for o in have])))), 'share': round(len(have) /
                                                                                                   len(outlines), 2)}
