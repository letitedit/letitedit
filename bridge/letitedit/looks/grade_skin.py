"""The skin of a Look's grade: the reference's own faces, and each clip's skin graded toward them.

A colourist grades the picture to the Look and lands skin where the Look's skin sits, keying skin by its hue and tone
(a qualifier) and grading it on its own. The grade does the same inside its LUT: the picture is graded as before, and
pixels whose colour and brightness read as skin take a skin grade instead, in proportion to how much they read as
skin. The skin grade is a tone curve from the clip's skin brightness to the reference's skin brightness (its luma p05,
p50 and p95), colour gains from the clip's skin colour to the reference's (its mean chromaticity), and a colour-strength
scale toward the reference's skin saturation, in either direction. Only a clip with a detected face takes a skin grade
(a clip without one, sand or wood or a sunset, keeps the picture grade alone); within such a clip the key is the pixel's
own colour, so a second face the detector misses still takes it.
A 3D LUT has no spatial smoothing, so the skin grade is held close to the picture grade where the key is uncertain:
each pixel the key takes lands within SPLIT_STOPS of the same pixel under the picture grade alone (split), and
camera noise on skin, in brightness and in colour, grows at most SPREAD_MAX times what the grade itself makes of it
(spread: grey-ish skin on the key's soft edge otherwise turns its noise into blotches). Both are measured on the clip as
a whole (its faces' skin pooled with the pixels the key takes), and a check that can't be measured never passes.

    reference_skin(lighting_profiles)       -> the reference's faces and skin, or None (under MIN_SAMPLES)
    skin_sample(faces)                      -> ('faces', skin pixels of the detected faces) or None
    fit_skin(sample, reference, amount)     -> the skin grade (a dict kept in the LUT's params as skin_tone; its
                                               'mix' says how much of it replaces the picture grade)
    key(rgb, tone), apply(rgb, tone)        -> how much of the skin grade a pixel takes; the skin grade on pixels
    check(faces, size, table, reference)    -> each face on the LUT's own result (apply_cube): skin newly clipped,
                                               where skin lands against the reference's, skin hue and colour strength
                                               against the reference's own range; with the skin grade, the picture
                                               grade alone and the clip's pixels, the clip's spread and split
    apply_cube(size, table, rgb)            -> a .cube applied by tetrahedral interpolation, as the engine's LUT (3D) does

Skin is measured as lighting measures it: lighting.skin_mask on the face box (8-bit YCrCb: Y over 25, Cr 130-180,
Cb 75-135), so the clip's skin and the reference's skin are read the same way. Hue is CIELAB h of the mean skin colour;
colour strength is HSV saturation p50. Measurements are display RGB, not scene light.
"""
from __future__ import annotations

import math

import numpy as np

WEIGHTS = np.array([.2126, .7152, .0722])
MIN_SAMPLES = 3                 # reference samples with a face and skin needed to aim skin at them
SKIN_STOPS = 1.5                # skin's median moves at most this far
EDGE_STOPS = 2.                 # skin's p05 moves at most this far
SLOPES = (.25, 3.)              # the skin tone curve's flattest and steepest parts
CHROMA = (.5, 2.)               # the skin colour-strength scale
GAIN = (.75, 1.33)              # each channel's skin colour gain
RAMP = 6.                       # the key's soft edge, in 8-bit Cr and Cb
TONE_RAMP = .04                 # the key's soft edge in luma
CLIP_AT, CLIP_NEW = .98, .01    # a channel at or over CLIP_AT is clipped; skin may gain at most CLIP_NEW of it
HUE_MARGIN, SATURATION_MARGIN = 2., .03   # skin is inside the reference's range within these margins
MIN_SKIN = 50                   # skin pixels a face needs to be checked
MIDDLE_SHARE = 1 / 3            # the share of reference samples nearest its median skin hue its skin colour is taken from
KEY_SATURATION = (.03, .20)     # the key fades in between these HSV saturations: a grey a little warm is not skin
                                # (skin sits near 0.3-0.5); lighting's skin box alone takes in warm greys. Wide, so
                                # skin near the edge doesn't flip between the two grades on its own noise
SPLIT_STOPS = .5                # keyed and unkeyed pixels of one input brightness land at most this far apart
SPLIT_BIN, SPLIT_MIN = .04, 40  # the split's input-brightness bins and the pixels each side needs in one
SPREAD_MAX = 2.                 # camera noise on skin may grow at most this many times through the LUT
NOISE, SPREAD_MIN = .004, 30    # the noise added to measure it (about one 8-bit level) and the pixels a group needs
SPREAD_GROUPS = (.04, .1)       # the groups' steps in colour strength (HSV saturation) and luma
LANDED_STOPS = .5               # skin's median within this of the reference's is named as landed


def luma(rgb):
    return np.asarray(rgb, float) @ WEIGHTS


def _ycrcb(rgb):
    """8-bit-scale Y, Cr, Cb as OpenCV's RGB2YCrCb gives them."""
    v = np.asarray(rgb, float) * 255
    y = v @ np.array([.299, .587, .114])
    return y, (v[:, 0] - y) * .713 + 128, (v[:, 2] - y) * .564 + 128


def _inside(v, low, high, ramp):
    return np.clip(1 - np.maximum(np.maximum(low - v, v - high), 0) / ramp, 0, 1)


def skin_hue(rgb):
    """0-1 per pixel: lighting.skin_mask's skin colour, with soft edges."""
    y, cr, cb = _ycrcb(rgb)
    return _inside(cr, 130, 180, RAMP) * _inside(cb, 75, 135, RAMP) * np.clip((y - 15) / 20, 0, 1)


def is_skin(rgb):
    """lighting.skin_mask's own skin pixels (hard edges)."""
    y, cr, cb = _ycrcb(np.round(np.clip(rgb, 0, 1) * 255) / 255)
    return (y > 25) & (cr >= 130) & (cr <= 180) & (cb >= 75) & (cb <= 135)


def lab(rgb):
    import cv2
    return cv2.cvtColor(np.asarray(rgb, np.float32).reshape(1, -1, 3), cv2.COLOR_RGB2Lab).reshape(-1, 3)


def hue(mean_rgb):
    """CIELAB hue angle in degrees of one colour."""
    _, a, b = lab(np.asarray(mean_rgb, float).reshape(1, 3))[0]
    return float(math.degrees(math.atan2(b, a)))


def saturation(rgb):
    rgb = np.asarray(rgb, float)
    top = rgb.max(axis=1)
    return np.where(top > 1e-6, (top - rgb.min(axis=1)) / np.maximum(top, 1e-6), 0.)


def chromaticity(mean_rgb):
    v = np.asarray(mean_rgb, float)
    return v / max(1e-6, float(v.sum()))


def reference_skin(profiles):
    """The reference's faces and skin from its lighting.json (lighting.measure's face and skin metrics on every
    sample with a face, graphics left out): skin luma p05, p50 and p95 (medians over the samples), its chromaticity
    (the samples nearest its median hue), its hue and colour strength (median and the samples' p05-p95 range), and
    the face box's luma p50, and how many samples were skipped for a malformed colour ('skipped', when any). None
    with under MIN_SAMPLES samples."""
    rows, skipped = [], 0
    for ref in profiles or []:
        for scene in (ref or {}).get('scenes') or []:
            if scene.get('role') == 'graphics':
                continue
            for sample in scene.get('samples') or []:
                metrics = sample.get('metrics') or {}
                face, skin = metrics.get('face'), metrics.get('skin')
                needed = ('luma_p05', 'luma_p50', 'luma_p95', 'saturation_p50')
                if (isinstance(face, dict) and isinstance(skin, dict) and skin.get('mean_rgb')
                        and (skin.get('pixels') or 0) >= MIN_SKIN and face.get('luma_p50') is not None
                        and all(skin.get(k) is not None for k in needed)):
                    if _colour_ok(skin['mean_rgb']):
                        rows.append((face, skin))
                    else:
                        skipped += 1
    if len(rows) < MIN_SAMPLES:
        return None

    def spread(values):
        return [round(float(np.percentile(values, 5)), 4), round(float(np.median(values)), 4),
                round(float(np.percentile(values, 95)), 4)]
    hues = [hue(skin['mean_rgb']) for _, skin in rows]
    return {'samples': len(rows),
            'luma': {key: round(float(np.median([skin[f'luma_{key}'] for _, skin in rows])), 4)
                     for key in ('p05', 'p50', 'p95')},
            'chromaticity': [round(float(v), 4) for v in _middle_colour(rows, hues)],
            'hue_deg': spread(hues), 'saturation': spread([skin['saturation_p50'] for _, skin in rows]),
            'face_luma_p50': spread([face['luma_p50'] for face, _ in rows]),
            **({'skipped': skipped} if skipped else {})}


def _colour_ok(value):
    """True for a mean colour of three finite numbers."""
    try:
        v = np.asarray(value, float).reshape(-1)
    except (TypeError, ValueError):
        return False
    return v.shape == (3,) and bool(np.isfinite(v).all())


def _middle_colour(rows, hues):
    """The reference's skin colour (chromaticity): the mean over the samples whose hue sits nearest the median hue
    (the closest MIDDLE_SHARE). A median taken channel by channel is no sample's colour: its hue can sit degrees from
    the samples' median hue."""
    hues = np.asarray(hues, float)
    off = np.abs(hues - np.median(hues))
    near = off <= np.percentile(off, MIDDLE_SHARE * 100)
    return np.mean([chromaticity(skin['mean_rgb']) for (_, skin), keep in zip(rows, near) if keep], axis=0)


def skin_sample(faces):
    """A clip's skin to grade from: the skin pixels of its detected faces ('faces'), or None (too little skin in them,
    or no face: a clip without a detected face takes no skin grade)."""
    found = [px[is_skin(px)] for px in faces or [] if len(px)]
    found = [px for px in found if len(px)]
    if found and sum(len(px) for px in found) >= MIN_SKIN * 4:
        return 'faces', np.concatenate(found)
    return None


def _monotone(knots):
    xs, ys = [k[0] for k in knots], [k[1] for k in knots]
    for i in range(1, len(xs)):
        run = max(1e-4, xs[i] - xs[i - 1])
        ys[i] = min(max(ys[i], ys[i - 1] + SLOPES[0] * run), ys[i - 1] + SLOPES[1] * run)
    return [[round(x, 5), round(min(1., y), 5)] for x, y in zip(xs, ys)]


def fit_skin(sample, reference, amount=1.):
    """The skin grade taking `sample` (skin pixels, N x 3) `amount` (0-1) of the way to the reference's skin: a tone
    curve through the skin's luma p05, p50 and p95 (the median at most SKIN_STOPS away, p05 at most EDGE_STOPS), colour
    gains from its mean chromaticity to the reference's, and a colour-strength scale solved so the skin's HSV saturation
    p50 lands the same share of the way to the reference's. The key's tones are the sample's own (p02 to p98,
    widened)."""
    sample = np.clip(np.asarray(sample, float).reshape(-1, 3), 0, 1)
    y = luma(sample)
    x05, x50, x95, x02, x98 = (float(v) for v in np.percentile(y, (5, 50, 95, 2, 98)))
    r = reference['luma']
    a = float(np.clip(amount, 0, 1))

    def toward(x, goal, stops):
        moved = x * (max(1e-3, goal) / max(1e-3, x)) ** a
        return float(min(max(moved, x * 2 ** -stops), x * 2 ** stops))
    knots = _monotone([[0., 0.], [x05, toward(x05, r['p05'], EDGE_STOPS)], [x50, toward(x50, r['p50'], SKIN_STOPS)],
                       [x95, x95 + a * (r['p95'] - x95)], [1., 1.]])
    gain = np.clip((np.asarray(reference['chromaticity']) / chromaticity(sample.mean(0))) ** a, *GAIN)
    tone = {'knots': knots, 'gain': [round(float(g), 5) for g in gain], 'chroma': 1.,
            'tones': [round(max(0., x02 * .6), 4), round(min(1.01, x98 * 1.3 + .02), 4)], 'amount': round(a, 3)}
    goal = float(np.median(saturation(sample)))
    goal += a * (reference['saturation'][1] - goal)
    low, high = math.log(CHROMA[0]), math.log(CHROMA[1])
    for _ in range(14):
        mid = (low + high) / 2
        got = float(np.median(saturation(apply(sample, {**tone, 'chroma': math.exp(mid)}))))
        low, high = (mid, high) if got < goal else (low, mid)
    tone['chroma'] = round(math.exp((low + high) / 2), 4)
    return tone


def key(rgb, tone):
    """0-1 per pixel: how much of the skin grade it takes (skin colour with skin's colour strength, within the skin's
    own tones)."""
    lo, hi = tone['tones']
    y = luma(rgb)
    strength = np.clip((saturation(rgb) - KEY_SATURATION[0]) / (KEY_SATURATION[1] - KEY_SATURATION[0]), 0, 1)
    return skin_hue(rgb) * strength * _inside(y, lo, hi, TONE_RAMP)


def apply(rgb, tone):
    """The skin grade on pixels (N x 3): brightness through the skin's tone curve (each channel scaled alike, so the
    colour holds), then the colour gains and the colour-strength scale around the new brightness."""
    rgb = np.clip(np.asarray(rgb, float).reshape(-1, 3), 0, 1)
    y = luma(rgb)
    k = np.asarray(tone['knots'], float)
    target = np.interp(y, k[:, 0], k[:, 1])
    out = rgb * np.clip(target / np.maximum(y, 1e-3), 0, 4)[:, None]
    out = out * np.asarray(tone['gain'], float)
    out += (target - luma(out))[:, None]
    out = target[:, None] + float(tone['chroma']) * (out - target[:, None])
    return np.clip(out, 0, 1)


def apply_cube(size, table, rgb):
    """A .cube's N x 3 table (red changing fastest, as write_cube writes and read_cube reads) applied to N x 3 display
    RGB by tetrahedral interpolation, the engine's LUT (3D) filter with interp tetrahedral."""
    t = np.asarray(table, float).reshape(size, size, size, 3)          # [blue][green][red]
    p = np.clip(np.asarray(rgb, float).reshape(-1, 3), 0, 1) * (size - 1)
    i0 = np.minimum(np.floor(p).astype(int), size - 2)
    f = p - i0
    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]

    def c(dr, dg, db):
        return t[b0 + db, g0 + dg, r0 + dr]
    c000, c111 = c(0, 0, 0), c(1, 1, 1)
    out = np.empty_like(p)
    done = np.zeros(len(p), bool)
    for mask, value in (
            ((fr >= fg) & (fg >= fb), lambda: (1 - fr) * c000 + (fr - fg) * c(1, 0, 0) + (fg - fb) * c(1, 1, 0) + fb * c111),
            ((fr >= fb) & (fb > fg), lambda: (1 - fr) * c000 + (fr - fb) * c(1, 0, 0) + (fb - fg) * c(1, 0, 1) + fg * c111),
            ((fb > fr) & (fr >= fg), lambda: (1 - fb) * c000 + (fb - fr) * c(0, 0, 1) + (fr - fg) * c(1, 0, 1) + fg * c111),
            ((fg > fr) & (fr >= fb), lambda: (1 - fg) * c000 + (fg - fr) * c(0, 1, 0) + (fr - fb) * c(1, 1, 0) + fb * c111),
            ((fg >= fb) & (fb > fr), lambda: (1 - fg) * c000 + (fg - fb) * c(0, 1, 0) + (fb - fr) * c(0, 1, 1) + fr * c111),
            ((fb > fg) & (fg > fr), lambda: (1 - fb) * c000 + (fb - fg) * c(0, 0, 1) + (fg - fr) * c(0, 1, 1) + fr * c111)):
        m = mask[:, 0] & ~done
        if m.any():
            out[m] = value()[m]
            done |= m
    return np.clip(out, 0, 1)


def _held(size, base, tone, weight, rgb):
    """The grade with the key held at `weight` (per pixel): the picture grade (`base`, a LUT table) and the skin grade
    mixed as the key mixes them at the clean pixel."""
    return (1 - weight) * apply_cube(size, base, rgb) + weight * apply(rgb, tone)


def _colour(d):
    """Each row's colour part (the RGB difference less its luma), as one length."""
    d = np.asarray(d, float)
    return np.sqrt(((d - luma(d)[:, None]) ** 2).sum(axis=1))


def _rms(v):
    return float(np.sqrt(np.mean(np.asarray(v, float) ** 2)))


def spread(size, table, skin, base=None, tone=None):
    """How much the LUT grows camera noise on skin beyond the grade itself: a fixed small noise (NOISE, per channel,
    seeded) added to the skin pixels, both through the LUT's own table, in groups of skin by colour strength and
    brightness (SPREAD_GROUPS; the key follows colour strength, so a greyer part of a face is its own group) with
    SPREAD_MIN pixels; the worst group of two measures:
      luma: the output's luma noise over what the grade itself makes of that noise with the key held where it is
            (the picture grade `base` and the skin grade `tone` mixed at each clean pixel's key), or the input's when
            that is smaller: a contrast curve's own slope isn't read as noise;
      colour: the output's colour noise over the picture grade's own (`base` alone), or the input's when that is
            smaller.
    Without `base` and `tone` (no skin grade) each is over the input's. A key that flips pixels between two grades on
    their own noise gives many times 1. Returns {'luma', 'colour', 'worst'} or None with too few pixels."""
    skin = np.clip(np.asarray(skin, float).reshape(-1, 3), 0, 1)
    if len(skin) < SPREAD_MIN:
        return None
    noisy = np.clip(skin + np.random.default_rng(7).normal(0, NOISE, skin.shape), 0, 1)
    moved = noisy - skin
    grown = apply_cube(size, table, noisy) - apply_cube(size, table, skin)
    if base is not None and tone:
        weight = (key(skin, tone) * float(tone.get('mix', 1.)))[:, None]
        expected = _held(size, base, tone, weight, noisy) - _held(size, base, tone, weight, skin)
        picture = apply_cube(size, base, noisy) - apply_cube(size, base, skin)
    else:
        expected = picture = moved
    sat_step, luma_step = SPREAD_GROUPS
    groups = np.floor(saturation(skin) / sat_step).astype(int) * 1000 + np.floor(luma(skin) / luma_step).astype(int)
    worst = None
    for g in np.unique(groups):
        m = groups == g
        if m.sum() < SPREAD_MIN or float(luma(moved[m]).std()) < 1e-6:
            continue
        lum = float(luma(grown[m]).std()) / max(float(luma(expected[m]).std()), float(luma(moved[m]).std()))
        col = _rms(_colour(grown[m])) / max(_rms(_colour(picture[m])), _rms(_colour(moved[m])), 1e-6)
        if worst is None or max(lum, col) > worst['worst']:
            worst = {'luma': round(lum, 3), 'colour': round(col, 3), 'worst': round(max(lum, col), 3)}
    return worst


def split(size, table, rgb, tone, base=None):
    """The largest gap in stops, over bins of input luma (SPLIT_BIN) holding SPLIT_MIN pixels the key takes (over
    0.8; all of them pooled when no bin holds that many), between each such pixel's output and the same pixel under the
    picture grade alone (`base`, a LUT table): the median per bin, the worst bin. Without `base`, against the median
    output of the pixels the key leaves (under 0.05) at the same input brightness, where a bin holds SPLIT_MIN of each.
    None with under SPLIT_MIN keyed pixels (not measured)."""
    rgb = np.clip(np.asarray(rgb, float).reshape(-1, 3), 0, 1)
    weight = key(rgb, tone)
    y_in, y_out = luma(rgb), luma(apply_cube(size, table, rgb))
    keyed = weight > .8
    if keyed.sum() < SPLIT_MIN:
        return None
    bins = np.floor(y_in / SPLIT_BIN).astype(int)
    if base is not None:
        gap = np.abs(np.log2(np.maximum(y_out, 1e-3) / np.maximum(luma(apply_cube(size, base, rgb)), 1e-3)))
        found = [float(np.median(gap[keyed & (bins == b)])) for b in np.unique(bins[keyed])
                 if (keyed & (bins == b)).sum() >= SPLIT_MIN]
        return round(max(found) if found else float(np.median(gap[keyed])), 3)
    worst = None
    for b in np.unique(bins):
        m = bins == b
        took, left = m & keyed, m & (weight < .05)
        if took.sum() >= SPLIT_MIN and left.sum() >= SPLIT_MIN:
            gap = abs(math.log2(max(1e-4, float(np.median(y_out[took]))) /
                                max(1e-4, float(np.median(y_out[left])))))
            worst = gap if worst is None else max(worst, gap)
    return None if worst is None else round(worst, 3)


def check(faces, size, table, reference, light=None, pixels=None, tone=None, base=None):
    """Each face (N x 3 face-box pixels; the clip's live face light applied first with `light`) through the LUT's own
    table: its skin's newly clipped share (at most CLIP_NEW, gating); and, measured and named, where its skin's median
    lands against the reference's (landed_stops) and its skin's hue and colour strength against the reference's own
    range (p05-p95 of its samples, within HUE_MARGIN and SATURATION_MARGIN). With the skin grade `tone` and the picture
    grade alone `base` (a LUT table), on the clip as a whole (its faces' skin pooled, with the clip's `pixels` the key
    takes): how much camera noise grows (spread, at most SPREAD_MAX) and the split between each keyed pixel and the same
    pixel under the picture grade alone (at most SPLIT_STOPS), both gating; either is None (not measured) with too few
    pixels, and a check not measured never passes. Without `tone` (the picture grade alone, no key) neither applies.
    Returns {'faces', 'checked', 'clip_ok', 'spread', 'spread_ok', 'split_stops', 'split_ok', 'measured', 'ok',
    'inside', 'landed', 'rows'}; a face with under MIN_SKIN skin pixels is listed, not checked."""
    import letitedit.looks.lighting as lighting
    rows, pooled, lit = [], [], []
    for px in faces or []:
        before = lighting.live_face_pixels(px, light)
        lit.append(before)
        after = apply_cube(size, table, before)
        skin = is_skin(before)
        row = {'face_luma_p50': [round(float(np.median(luma(before))), 4), round(float(np.median(luma(after))), 4)]}
        if skin.sum():
            pooled.append(before[skin])
        if skin.sum() >= MIN_SKIN:
            b, s = before[skin], after[skin]
            new_clip = float((s.max(axis=1) >= CLIP_AT).mean() - (b.max(axis=1) >= CLIP_AT).mean())
            row.update(skin_luma_p50=[round(float(np.median(luma(b))), 4), round(float(np.median(luma(s))), 4)],
                       hue_deg=[round(hue(b.mean(0)), 2), round(hue(s.mean(0)), 2)],
                       saturation_p50=[round(float(np.median(saturation(b))), 4),
                                       round(float(np.median(saturation(s))), 4)],
                       newly_clipped=round(new_clip, 4), clip_ok=new_clip <= CLIP_NEW)
            if reference:
                h, sat = row['hue_deg'][1], row['saturation_p50'][1]
                row['inside'] = bool(reference['hue_deg'][0] - HUE_MARGIN <= h <= reference['hue_deg'][2] + HUE_MARGIN
                                     and reference['saturation'][0] - SATURATION_MARGIN <= sat
                                     <= reference['saturation'][2] + SATURATION_MARGIN)
                row['landed_stops'] = round(math.log2(max(1e-4, row['skin_luma_p50'][1]) /
                                                      max(1e-4, reference['luma']['p50'])), 3)
        rows.append(row)
    checked = [r for r in rows if 'clip_ok' in r]
    spreading, gap = None, None
    if tone:
        clip = [np.clip(np.asarray(pixels, float).reshape(-1, 3), 0, 1)] if pixels is not None else []
        taken = [c[key(c, tone) > .02] for c in clip]
        spreading = spread(size, table, np.concatenate(pooled + taken) if pooled or taken else np.zeros((0, 3)),
                           base, tone)
        gap = split(size, table, np.concatenate(clip + lit) if clip or lit else np.zeros((0, 3)), tone, base)
    out = {'faces': len(rows), 'checked': len(checked), 'clip_ok': all(r['clip_ok'] for r in checked),
           'spread': spreading, 'spread_ok': (spreading['worst'] <= SPREAD_MAX) if spreading else not tone,
           'split_stops': gap, 'split_ok': (gap <= SPLIT_STOPS) if gap is not None else not tone,
           'measured': not tone or (spreading is not None and gap is not None),
           'inside': all(r.get('inside', True) for r in checked),
           'landed': all(abs(r.get('landed_stops', 0.)) <= LANDED_STOPS for r in checked), 'rows': rows}
    out['ok'] = out['clip_ok'] and out['spread_ok'] and out['split_ok']
    return out
