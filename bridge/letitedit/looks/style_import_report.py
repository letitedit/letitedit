"""Look, structure and pictures for style_import: colour and finish (contrast, saturation, warmth, skin, grain,
vignette, bars), the pace curve, sections, the hook and the ending, and the sheets and breakdown a person or the AI
reads (hook and ending filmstrips, overlay crops, transitions, an annotated timeline).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

CTA = re.compile(r"\b(subscribe|follow( me| us| for)?|like (and|&) (subscribe|follow)|comment|let me know|link in "
                 r"(the )?(bio|description)|check out|part (two|2)|watch (the )?(full|next)|turn on|hit the|smash|"
                 r"share this|save this|tag (a|someone)|see you (next|in the))\b", re.I)


def clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:05.2f}'


def _stats(vals, nd=3):
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return None
    return {'median': round(float(np.median(vals)), nd), 'p25': round(float(np.percentile(vals, 25)), nd),
            'p75': round(float(np.percentile(vals, 75)), nd)}


# ------------------------------------------------------------------ look

def look(samples, face_track, full_frames=()):
    """Colour and finish over the sampled frames. full_frames: a few full-size BGR frames for grain."""
    import cv2
    lum, con, sat, warm, tint, vign, top_bar, bot_bar, blur_bands = [], [], [], [], [], [], [], [], []
    skin_h, skin_s, skin_v = [], [], []
    pool, curve = [], []
    faces = dict(face_track)
    for t, p in samples:
        img = cv2.imread(str(p))
        if img is None:
            continue
        h, w = img.shape[:2]
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lum.append(float(g.mean()))
        con.append(float(g.std()))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        sat.append(float(hsv[:, :, 1].mean()))
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        warm.append(float(lab[:, :, 2].mean() - 128))
        tint.append(float(lab[:, :, 1].mean() - 128))
        curve.append({'t': round(float(t), 3), 'brightness': round(lum[-1], 1),
                      'contrast_std': round(con[-1], 1), 'saturation': round(sat[-1], 1),
                      'warmth_lab_b': round(warm[-1], 1), 'tint_lab_a': round(tint[-1], 1)})
        cy, cx = h // 2, w // 2
        centre = g[cy - h // 6:cy + h // 6, cx - w // 6:cx + w // 6].mean()
        corners = np.mean([g[:h // 8, :w // 8].mean(), g[:h // 8, -w // 8:].mean(), g[-h // 8:, :w // 8].mean(),
                           g[-h // 8:, -w // 8:].mean()])
        if centre > 20:
            vign.append(float(corners / centre))
        # bars: rows at the top / bottom that are near black and even
        rows_dark = (g.mean(1) < 18) & (g.std(1) < 6)
        k = 0
        while k < h // 3 and rows_dark[k]:
            k += 1
        top_bar.append(k / h)
        k = 0
        while k < h // 3 and rows_dark[h - 1 - k]:
            k += 1
        bot_bar.append(k / h)
        # blurred bands (a blurred copy of the picture behind a smaller one): top and bottom fifths much softer than
        # the middle
        lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
        mid = lap[2 * h // 5:3 * h // 5].mean()
        edges = (lap[:h // 6].mean() + lap[-h // 6:].mean()) / 2
        blur_bands.append(float(edges / (mid + 1e-3)))
        fs = faces.get(t) or []
        if fs:
            x0, y0, x1, y1 = fs[0]['box']
            fx = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            if fx.size:
                ycc = cv2.cvtColor(fx, cv2.COLOR_BGR2YCrCb)
                m = (ycc[:, :, 1] > 135) & (ycc[:, :, 1] < 180) & (ycc[:, :, 2] > 85) & (ycc[:, :, 2] < 135)
                if m.sum() > 50:
                    fh = cv2.cvtColor(fx, cv2.COLOR_BGR2HSV)
                    skin_h.append(float(np.median(fh[:, :, 0][m])) * 2)
                    skin_s.append(float(np.median(fh[:, :, 1][m])))
                    skin_v.append(float(np.median(fh[:, :, 2][m])))
        small = cv2.resize(img, (64, max(1, round(64 * h / w))))
        pool.append(small[:, :, ::-1].reshape(-1, 3)[::3])
    out = {'brightness': _stats(lum, 1), 'contrast_std': _stats(con, 1), 'saturation': _stats(sat, 1),
           'warmth_b': _stats(warm, 2), 'tint_a': _stats(tint, 2)}
    if warm:
        wb = float(np.median(warm))
        out['warmth'] = 'warm' if wb > 6 else 'cool' if wb < -3 else 'neutral'
    if sat:
        s = float(np.median(sat))
        out['saturation_word'] = 'punchy' if s > 115 else 'rich' if s > 85 else 'natural' if s > 50 else 'muted'
    if con:
        c = float(np.median(con))
        out['contrast_word'] = 'high' if c > 68 else 'medium' if c > 45 else 'low (flat)'
    if vign:
        v = float(np.median(vign))
        out['vignette'] = {'corner_to_centre': round(v, 3), 'likely': bool(v < 0.72),
                           'note': 'dark corners can also be the scene; look at the frames'}
    tb, bb = float(np.median(top_bar)) if top_bar else 0, float(np.median(bot_bar)) if bot_bar else 0
    out['bars'] = {'top': round(tb, 3), 'bottom': round(bb, 3), 'letterbox': bool(tb > 0.03 and bb > 0.03)}
    if blur_bands:
        bbr = float(np.median(blur_bands))
        out['blurred_bands'] = {'edge_to_middle_detail': round(bbr, 3), 'likely': bool(bbr < 0.35)}
    if skin_h:
        out['skin'] = {'hue_deg': round(float(np.median(skin_h)), 1), 'saturation': round(float(np.median(skin_s)), 1),
                       'value': round(float(np.median(skin_v)), 1), 'frames': len(skin_h),
                       'note': 'natural skin sits around 10-30 degrees hue'}
    if full_frames:
        noise = []
        for f in full_frames:
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
            resid = g - cv2.medianBlur(g.astype(np.uint8), 3).astype(np.float32)
            grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
            flat = grad < np.percentile(grad, 30)
            if flat.sum() > 1000:
                noise.append(float(resid[flat].std()))
        if noise:
            nz = float(np.median(noise))
            out['grain'] = {'noise_std': round(nz, 2), 'word': 'visible grain' if nz > 3.0 else 'some' if nz > 1.8
                            else 'clean'}
    if pool:
        import cv2 as _cv
        px = np.concatenate(pool).astype(np.float32)
        k = 5
        _, lab_, centres = _cv.kmeans(px, k, None, (_cv.TERM_CRITERIA_EPS + _cv.TERM_CRITERIA_MAX_ITER, 30, 1.0), 3,
                                      _cv.KMEANS_PP_CENTERS)
        counts = np.bincount(lab_.ravel(), minlength=k)
        out['palette'] = [{'hex': '#%02X%02X%02X' % tuple(int(round(v)) for v in centres[i]),
                           'share': round(float(counts[i]) / len(px), 3)} for i in np.argsort(-counts)]
    out['curve'] = curve
    out['colour_note'] = ('sampled decoded-pixel statistics include scene content, lighting and graphics; '
                          'not recovered colour-grading settings or a LUT; unsampled times are unknown')
    return out


# ------------------------------------------------------------------ structure

def pace_curve(cuts, duration, window_s):
    """Cuts per minute in consecutive windows: [{t0, t1, cuts, per_minute}]."""
    out = []
    t = 0.0
    while t < duration - 1e-6:
        t1 = min(duration, t + window_s)
        n = sum(1 for c in cuts if t <= c['t'] < t1)
        out.append({'t0': round(t, 2), 't1': round(t1, 2), 'cuts': n, 'per_minute': round(n / max(1e-6, (t1 - t)) * 60, 1)})
        t = t1
    return out


def sections(curve, words, duration, min_s):
    """Stretches of similar pace and talk: neighbouring windows joined while their cut rate stays within a factor 2
    and talk / no talk does not change; short stretches folded into the one before."""
    if not curve:
        return []
    talk = []
    for w in curve:
        n = sum(1 for x in words if w['t0'] <= float(x['s']) < w['t1'])
        talk.append(n / max(1e-6, w['t1'] - w['t0']) > 0.8)
    secs = []
    for w, tk in zip(curve, talk):
        if secs:
            s = secs[-1]
            rate = s['cuts'] / max(1e-6, s['t1'] - s['t0']) * 60
            r2 = w['per_minute']
            similar = (max(rate, r2) + 6) / (min(rate, r2) + 6) < 2.0
            if similar and tk == s['talk']:
                s['t1'] = w['t1']
                s['cuts'] += w['cuts']
                continue
        secs.append({'t0': w['t0'], 't1': w['t1'], 'cuts': w['cuts'], 'talk': tk})
    merged = []
    for s in secs:
        if merged and s['t1'] - s['t0'] < min_s:
            merged[-1]['t1'] = s['t1']
            merged[-1]['cuts'] += s['cuts']
        else:
            merged.append(s)
    if len(merged) > 1 and merged[0]['t1'] - merged[0]['t0'] < min_s:
        merged[1]['t0'] = merged[0]['t0']
        merged[1]['cuts'] += merged[0]['cuts']
        merged = merged[1:]
    for s in merged:
        s['per_minute'] = round(s['cuts'] / max(1e-6, s['t1'] - s['t0']) * 60, 1)
        s['len'] = round(s['t1'] - s['t0'], 2)
    return merged


def hook(rep, words, hook_s=3.0):
    """The first hook_s seconds: what is shown, said and written and how it moves."""
    w = [x for x in words if float(x['s']) < hook_s]
    said = ' '.join(x['w'].strip() for x in w)
    text = [e for e in rep.get('text_events', []) if e['t'] < hook_s]
    cuts = [c for c in rep.get('cuts', []) if c['t'] < hook_s]
    zooms = [z for z in rep.get('zooms', []) if z['t'] < hook_s]
    ovs = [o for o in rep.get('overlays', {}).get('events', []) if o['t'] < hook_s]
    sfx = [s for s in ((rep.get('sound') or {}).get('sfx') or {}).get('events', []) if s['t'] < hook_s]
    first_word = float(words[0]['s']) if words else None
    q = said.strip().endswith('?') or bool(re.match(r'^(what|why|how|who|did|do|have|is|are|can|would|ever)\b',
                                                    said.strip(), re.I))
    nums = bool(re.search(r'\d|\$|percent|hundred|thousand|million', said, re.I))
    out = {'seconds': hook_s, 'said': said, 'speech_measured': bool(words),
           'first_word_s': round(first_word, 2) if first_word is not None else None,
           'talks_from_the_first_second': bool(first_word is not None and first_word < 0.6),
           'question': q, 'number': nums,
           'text_on_screen': [{'t': round(e['t'], 2), 'text': e['text'], 'role': e.get('role')} for e in text],
           'text_in_first_second': any(e['t'] < 1.0 for e in text),
           'cuts': len(cuts), 'zooms': len(zooms), 'overlays': len(ovs), 'sfx': len(sfx),
           'face_at_start': bool(rep.get('_face0')),
           'music_from_start': rep.get('_music0'),
           'music_start_note': 'unknown: whole-video music share does not locate music at the start'}
    kinds = []
    if out['text_in_first_second']:
        kinds.append('text on screen at once')
    if out['talks_from_the_first_second']:
        kinds.append('talks straight away')
    if q:
        kinds.append('opens with a question')
    if nums:
        kinds.append('a number in the first line')
    if cuts or zooms:
        kinds.append(f'{len(cuts)} cut(s) and {len(zooms)} zoom(s) in {hook_s:g} s')
    if sfx:
        kinds.append('a sound effect in the opening')
    out['devices'] = kinds
    return out


def ending(rep, words, duration, frames=None, end_s=4.0):
    """The last end_s seconds: what is said and written, a call to action, and whether it loops back to the start
    (last frame like the first, or the last sentence running into the first)."""
    end_s = min(end_s, max(0.0, duration))
    t0 = duration - end_s
    w = [x for x in words if float(x['s']) >= t0]
    said = ' '.join(x['w'].strip() for x in w)
    text = [e for e in rep.get('text_events', []) if e['end'] >= t0]
    cta = sorted({m.group(0).lower() for m in CTA.finditer(said + ' ' + ' '.join(e['text'] for e in text))})
    out = {'seconds': end_s, 'said': said, 'speech_measured': bool(words),
           'text_on_screen': [e['text'] for e in text][:8], 'call_to_action': cta,
           'inference_note': 'word-pattern and sampled-frame heuristics; not an editorial meaning or loop verdict'}
    if words:
        last = words[-1]['w'].strip()
        first = words[0]['w'].strip()
        out['last_word_ends_sentence'] = bool(re.search(r'[.!?]["\']?$', last))
        out['ends_mid_sentence'] = not out['last_word_ends_sentence']
        out['speech_until_end'] = bool(float(words[-1].get('e', words[-1]['s'])) > duration - 0.6)
        out['first_word_capitalised'] = first[:1].isupper()
    if frames is not None and len(frames) > 10:
        a = frames[1].astype(np.float32)
        b = frames[-2].astype(np.float32)
        diff = float(np.abs(a - b).mean())
        out['last_frame_vs_first_diff'] = round(diff, 1)
        out['loops_visually'] = bool(diff < 12)
    out['loop_guess'] = bool(out.get('loops_visually') or (out.get('ends_mid_sentence') and out.get('speech_until_end')
                                                           and not out.get('first_word_capitalised', True)))
    return out


# ------------------------------------------------------------------ pictures

def _font(size=14):
    from PIL import ImageFont
    for name in ('arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def strip(frames_with_labels, tile_w=180, title=None):
    """A row of frames with a label under each: [(BGR, label)] -> PIL image."""
    from PIL import Image, ImageDraw
    tiles = []
    for f, lab in frames_with_labels:
        im = Image.fromarray(f[:, :, ::-1])
        th = round(im.height * tile_w / im.width)
        im = im.resize((tile_w, th))
        canvas = Image.new('RGB', (tile_w, th + 34), (20, 20, 20))
        canvas.paste(im, (0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((4, th + 3), str(lab)[:60], fill=(255, 220, 90), font=_font(12))
        tiles.append(canvas)
    if not tiles:
        return None
    W = sum(t.width for t in tiles) + 4 * (len(tiles) - 1)
    H = max(t.height for t in tiles) + (26 if title else 0)
    out = Image.new('RGB', (W, H), (12, 12, 12))
    x = 0
    y0 = 26 if title else 0
    if title:
        ImageDraw.Draw(out).text((6, 5), title[:140], fill=(240, 240, 240), font=_font(15))
    for t in tiles:
        out.paste(t, (x, y0))
        x += t.width + 4
    return out


def stack(images, gap=8):
    from PIL import Image
    images = [i for i in images if i is not None]
    if not images:
        return None
    W = max(i.width for i in images)
    H = sum(i.height for i in images) + gap * (len(images) - 1)
    out = Image.new('RGB', (W, H), (12, 12, 12))
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height + gap
    return out


def boxed(frame, box, colour=(0, 255, 255), label=None):
    import cv2
    f = frame.copy()
    h, w = f.shape[:2]
    x0, y0, x1, y1 = box
    cv2.rectangle(f, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), colour, max(2, w // 200))
    if label:
        cv2.putText(f, label[:28], (max(2, int(x0 * w)), max(14, int(y0 * h) - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.4, w / 1100), colour, max(1, w // 500))
    return f


def timeline_image(rep, width=1400):
    """One picture of the whole video: lanes for shots and cuts (by kind), transitions, zooms, captions, other text,
    overlays, sound effects, music beats and speech, on a shared time axis."""
    from PIL import Image, ImageDraw
    dur = float(rep['duration_s'])
    lanes = ['cuts', 'transitions', 'zooms', 'captions', 'text', 'overlays', 'sfx', 'beats', 'speech']
    lh = 22
    left = 90
    H = 30 + lh * len(lanes) + 20
    im = Image.new('RGB', (width, H), (18, 18, 22))
    d = ImageDraw.Draw(im)
    f = _font(12)
    span = width - left - 10

    def x(t):
        return left + int(span * max(0.0, min(1.0, t / max(1e-6, dur))))
    for k, name in enumerate(lanes):
        y = 30 + k * lh
        d.text((6, y + 4), name, fill=(200, 200, 200), font=f)
        d.line((left, y + lh - 2, width - 10, y + lh - 2), fill=(40, 40, 48))
    step = 1 if dur <= 20 else 5 if dur <= 90 else 30 if dur <= 900 else 60
    t = 0.0
    while t <= dur:
        d.line((x(t), 24, x(t), H - 18), fill=(35, 35, 42))
        d.text((x(t) + 2, 8), clock(t)[:-3], fill=(150, 150, 150), font=f)
        t += step
    col = {'cut': (240, 240, 240), 'jump': (120, 200, 255), 'punch': (255, 170, 40), 'jump?': (110, 110, 140)}

    def lane_y(name):
        return 30 + lanes.index(name) * lh
    for c in rep.get('cuts', []):
        y = lane_y('cuts')
        d.line((x(c['t']), y + 2, x(c['t']), y + lh - 4), fill=col.get(c.get('kind'), (200, 200, 200)), width=2)
    for g in rep.get('transitions', []):
        y = lane_y('transitions')
        d.rectangle((x(g.get('start', g['t'])), y + 4, max(x(g.get('end', g['t'])), x(g.get('start', g['t'])) + 3),
                     y + lh - 6), fill=(200, 120, 255))
    for z in rep.get('zooms', []):
        y = lane_y('zooms')
        if z['kind'] in ('push_in', 'pull_out'):
            d.rectangle((x(z['t']), y + 8, x(z.get('end', z['t'] + 0.5)), y + lh - 8), fill=(255, 200, 80))
        else:
            d.polygon([(x(z['t']), y + 3), (x(z['t']) + 5, y + lh - 5), (x(z['t']) - 5, y + lh - 5)], fill=(255, 140, 0))
    for e in rep.get('text_events', []):
        y = lane_y('captions' if e.get('role') == 'caption' else 'text')
        d.rectangle((x(e['t']), y + 5, max(x(e['end']), x(e['t']) + 2), y + lh - 7),
                    fill=(90, 200, 120) if e.get('role') == 'caption' else (80, 160, 230))
    for o in rep.get('overlays', {}).get('events', []):
        y = lane_y('overlays')
        d.rectangle((x(o['t']), y + 4, max(x(o['end']), x(o['t']) + 2), y + lh - 6),
                    fill=(255, 90, 120) if o.get('conf', 0) >= 0.5 else (120, 60, 70))
    for s in ((rep.get('sound') or {}).get('sfx') or {}).get('events', []):
        y = lane_y('sfx')
        d.ellipse((x(s['t']) - 4, y + 6, x(s['t']) + 4, y + lh - 8), fill=(255, 230, 60))
    for b in rep.get('_beats', [])[:2000]:
        y = lane_y('beats')
        d.line((x(b), y + 7, x(b), y + lh - 7), fill=(110, 110, 160))
    for a, b in rep.get('_speech_spans', []):
        y = lane_y('speech')
        d.rectangle((x(a), y + 7, max(x(b), x(a) + 1), y + lh - 9), fill=(150, 150, 150))
    return im
