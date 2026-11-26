"""A Look's colour grade: measured from its reference shots and put on every clip of footage as a LUT the editor shows.

The grade is the Look's colour, apart from any light on a speaker's face: how dark its blacks sit, how bright its
highlights reach, how strong its colours are and which way its shadows, mid-tones and highlights lean. It goes on any
footage, with or without a face: faces take the grade too, aimed at the reference's own faces (from grade-fit/11,
below); the live face lighting (`lighting.py`) only lifts a face, by design.

    profile(lighting_profiles)          -> letitedit-grade/1: one entry per usable reference sample
    look_grade(script)                  -> {'look', 'grade', 'from'} for the project's chosen Look, or {}
    fit(pixels, target, strength)       -> a transform: tone curve, colour strength, colour lean by brightness
    transform(rgb, params)              -> the transform on N x 3 display RGB (0-1); the LUT is this on a grid
    cover_footage(script, spec)         -> {op: fx, grade: true | {strength?, remove?}}: a LUT (3D) filter on every clip
    ungraded_footage(script)            -> ids of footage clips still without the Look's grade

Each clip is matched to the reference samples closest to it in brightness (its median and highlights), so a dark shot
takes the reference's dark shots and a bright one its bright shots; the median moves at most MAX_STOPS, or FAR_STOPS
for a clip whose median sits over FAR_OUTSIDE stops outside the reference's own range (its samples' 10th to 90th
percentile). From grade-fit/6, a reference that holds one grade from shot to shot (grade_match.uneven is False) gives
every clip one shared colour: the colour strength and lean of all its samples (their median), not of the nearest
ones, so saturated clips come down (to SHARED_SATURATION_LOW) as grey ones come up; a reference that is itself uneven
keeps the nearest samples' colour. With one shared colour the lean reaches colourful pixels as well (a warm light
takes the grade's lean, not only its greys: lean_full). The skin rule holds there too, for skin: a pixel far more colourful than skin
(SKIN_SATURATION: a warm lamp, sodium street light, an orange sign) takes the grade. From grade-fit/8, with one shared
colour the black point is shared too (the median of all samples' p01, p05 and p10, kept under the clip's own p25
target), colour strength is scaled around the clip's own cast in each brightness band (neutral: a boost no longer
deepens a sodium-orange or blue-sky cast the lean then has to undo; skin keeps its share as before), the highlights
(an open sky) may lean as far as SHARED_HIGHLIGHT_LEAN, and a grey clip's lean meets the grade's rather than overshooting
it (no CAST_GAIN). From grade-fit/9, with one shared colour the cut's spread of brightness is matched to the
reference's (brightness_plan, as pace matches the reference's spread of shot lengths): in stops, the cut's middle
moves to the reference's and a spread wider than the reference's shrinks to it (a narrower one is left), each clip at
most SPREAD_STOPS, so order holds; when the reference's shot medians split into a dark group and a bright one (a gap of GAP_STOPS or more with at least
GAP_SHARE on each side: a night or dark stretch against day), each clip is matched within its own group, so a dark
stretch keeps its place below the day shots by the reference's own gap. The move is made on the fitted curve's
midtones (_midtone, a gentle bow between the curve's black at the clip's p05 and its white), so the median lands
where planned while the black point and the top of the highlights hold; the colour is then solved for that curve. A clip far
flatter than the grade (an overcast sky) may take a steeper curve (FLAT_SLOPE), and one that stays much greyer than
the grade leans further in the grade's own colour direction (CAST_GAIN, GREY_LEAN), since colour strength scaled up
from grey stays grey. Skin-tone hues (the vectorscope's skin line, which also holds orange and red) keep most of their
hue and colour strength, and keep their own colour strength where the curve darkens or brightens them; the graded
pixels are measured, and the protection raised (SKIN_PROTECT) until skin's colour strength and hue hold (SKIN_RISE,
SKIN_TURN).
From grade-fit/11, with a measured reference skin (grade_skin.reference_skin: the face and skin metrics of the Look's
lighting.json) skin is graded to the reference's skin, in either direction: inside the LUT, pixels whose colour and
brightness read as skin (a qualifier: grade_skin.key) take a skin grade (a tone curve from the clip's skin brightness
to the reference's, colour gains to its skin colour, a colour-strength scale toward its skin saturation) in proportion
to how much they read as skin, so a face lands where the Look's faces sit and the room where its pictures sit. Only a
clip with a detected face (YuNet, after the clip's live face light) takes a skin grade, fitted on its faces' skin (or,
with too little skin in them, on the cut's faces); a clip without one takes the picture grade alone, so sand, wood or a
sunset is never graded as skin. Each face is then checked on the LUT's own result (tetrahedral interpolation, after the
live face light), and three checks gate the steps: at most CLIP_NEW of its skin newly clipped; and, on the clip as a
whole (its faces' skin pooled with the pixels the key takes), camera noise grown at most SPREAD_MAX times what the grade
itself makes of it, in brightness and in colour (a key's soft edge otherwise turns grey-ish skin's noise into
blotches), and each keyed pixel at most SPLIT_STOPS from the same pixel under the picture grade alone. A check that
can't be measured (too few pixels) never passes: such a clip takes skin at its own tones at most. Where skin lands
against the reference's skin, and its hue and colour strength against the reference's range, are measured and named,
not gated. The steps, in order, until the checks hold: the skin grade (aimed at the reference's skin) mixed in at
SKIN_MIXES, then skin held at its own tones; then the same with the picture grade at PICTURE_SHARES of the way, except
that a clip keeps the full picture grade with its skin following the room rather than drop the whole grade (share 0)
to keep some skin grade. The written LUT is checked once more. The share each clip took is kept in its reach, so a gap
it leaves is named as the room held back to keep faces clean, not as the footage's limit.
Measurements are display RGB, not scene light; a grade is a match of the picture's statistics, not proof of the same
camera or light.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

import letitedit.looks.grade_skin as grade_skin

FORMAT = 'letitedit-grade/1'
VERSION = 'grade-fit/11'         # the fitting; a clip's LUT is made again when it changes (5: flat and grey clips,
                                 # skin measured on the result; 6: one shared colour for a reference with one grade;
                                 # 7: with one shared colour, colourful pixels take the lean too; 8: with one shared
                                 # colour, a shared black point, colour scaled around the clip's own cast, no cast
                                 # gain; 9: with one shared colour, the cut's spread of brightness matched to the
                                 # reference's; 10: a face never made darker; 11: skin graded to the reference's
                                 # skin, a face the same way as everything else). The LUT's file name carries it,
                                 # the clip's planned brightness, the reference's skin and the face guard's state, so
                                 # an export never reuses a picture rendered with an older fitting or plan
SPREAD_STOPS = .5               # with one shared colour a clip's median moves at most this far to match the spread
GAP_STOPS, GAP_SHARE = .75, .1  # a gap this wide in the reference's medians, this share on each side: a dark group
STATS = 'grade-stats/3'         # the cached statistics and faces of a clip's own frames (cover_footage's first pass),
                                # found again when the face guard's state changes (face_guard_state)
FACE_FRAME_WIDTH = 640          # faces are found (lighting.face_boxes, YuNet) and read on frames this wide
FACE_BOX_PIXELS = 1500          # at most this many pixels kept of each face box
SKIN_MIXES = (1., .75, .5, .25)     # how much of the skin grade replaces the picture grade, tried until its checks hold
PICTURE_SHARES = (1., .5, .25, 0.)  # the picture grade's share tried on a clip until its skin's clipping holds
SKIN_STEPS = ('mixes, held, picture shares (never none for a skin grade); clipping, noise growth over the grade\'s own in '
              'luma and colour pooled per clip, split per keyed pixel against the picture grade, unmeasured never passes')   # the steps and their checks; in the LUT's name
SHARED_HIGHLIGHT_LEAN = .09    # with one shared colour the highlights (an open sky) may lean this far per channel
SHARED_BLACK = {'p01': .5, 'p05': .7, 'p10': .85}   # with one shared colour these come from all samples, at most
                                                     # this share of the clip's p25 target
TAG = 'letitedit_ai:grade'
WEIGHTS = np.array([.2126, .7152, .0722])
QUANTS = (1, 5, 10, 25, 50, 75, 90, 95, 99)
# colour lean measured in bands of the picture's own brightness ranks: (name, low %, high %)
BANDS = (('shadows', 0, 25), ('mids', 25, 75), ('highlights', 90, 100))
MAX_STOPS = 1.0                 # the clip's median moves at most this far ...
FAR_STOPS, FAR_OUTSIDE = 1.5, .5     # ... or this far when it sits this many stops outside the reference's range
SHARED_SATURATION_LOW = .4      # with one shared colour, colour strength may come down to this scale
SKIN_SATURATION = (.55, .75)    # with one shared colour, skin protection fades out between these HSV saturations
SLOPE = (.4, 2.)                # the tone curve's flattest and steepest parts
FLAT_SLOPE = 3.                 # the steepest part on a clip far flatter than the grade (its p05-p95 spread under half
                                # the grade's): half the spread ratio, at least SLOPE's and at most this
SATURATION = (.6, 2.2)          # colour strength scale
MAX_LEAN = .06                  # colour lean per channel, 0-1 display RGB
GREY = .8                       # a clip whose graded colour strength (p50) stays under this share of the grade's ...
CAST_GAIN = (1., 3.)            # ... leans up to this many times the grade's own lean, in its direction ...
GREY_LEAN = .09                 # ... at most this far per channel: colour scaled up from grey stays grey, a lean does not
LEAN_CHROMA, LEAN_COLOURED = .10, .3   # from grade-fit/5 the lean is a tint of the greys: a pixel with this much colour
                                # (Cb/Cr distance) or more takes this share of it, so red smoke or a yellow suit
                                # keeps its own colour while grey sky and concrete take the grade's
PROTECT = .75                   # share of the lean and colour-strength change kept off skin-tone hues
SKIN_PROTECT = (PROTECT, .9, 1.)     # tried in turn until skin holds on the graded pixels
SKIN_RISE = .05                 # skin-tone pixels' colour strength (HSV saturation p90) may move at most this much ...
SKIN_TURN = 6.                  # ... and their hue turn at most this many degrees (median)
FOLLOW = 1.5                    # skin's colour follows its brightness at most this far up (and all the way down)
SKIN_MIN = .002                 # share of the picture that must be skin-tone for skin to be measured
SKIN_ANGLE, SKIN_WIDTH = 123., 28.   # degrees in the Cb/Cr plane: the skin-tone line and the half-width kept
LUT_SIZE = 33
# A source compressed this hard (its video stream's bits per pixel per frame: bit rate over width x height x frame
# rate) holds faint blocks in flat areas (sky, walls); the grade's steeper tone curve on a flat clip makes them visible
# patches. A deband filter goes before its LUT there, smoothing only steps this small (the av thresholds) within its
# range. 1080p60 from a camera is about 0.4, a phone's 1080p30 about 0.25, a streaming site's 1080p30 about 0.06.
DEBAND_BPP = 0.05
DEBAND = {'av.1thr': 0.02, 'av.2thr': 0.02, 'av.3thr': 0.02, 'av.range': 16, 'av.blur': 1}
FRAMES = 5
WIDTH = 320
FIT_PIXELS = 40000          # pixels the colour strength is solved on
LIMITS = ['Display-RGB statistics of the reference, not its camera, light or the grade that made it.',
          'Each clip takes the brightness of the reference samples nearest its own; a scene the reference never '
          'showed takes the nearest one there was. Its colour is the whole reference\'s when the reference holds one '
          'grade, else the nearest samples\'.',
          "With a measured reference skin, skin is graded to the reference's skin, checked per face on the LUT's own "
          'result; without one, skin-tone hues keep most of their colour. The live face lighting is separate '
          '(lighting.py).']


def luma(rgb):
    return np.asarray(rgb, float) @ WEIGHTS


def _saturation(rgb):
    top = rgb.max(axis=1)
    return np.where(top > 1e-6, (top - rgb.min(axis=1)) / np.maximum(top, 1e-6), 0.)


def _bands(y):
    """Boolean masks of each band of the pixels' brightness ranks."""
    order = np.argsort(y, kind='stable')
    ranks = np.empty(len(y))
    ranks[order] = np.arange(len(y)) / max(1, len(y) - 1) * 100
    return {name: (ranks >= low) & (ranks <= high) for name, low, high in BANDS}


def _skin(rgb):
    """0-1 per pixel: how close its hue is to the skin-tone line (weighted by how much colour it has)."""
    y = luma(rgb)
    cb = (rgb[:, 2] - y) / 1.8556
    cr = (rgb[:, 0] - y) / 1.5748
    angle = np.degrees(np.arctan2(cr, cb))
    off = np.abs((angle - SKIN_ANGLE + 180) % 360 - 180)
    near = np.clip(1 - off / SKIN_WIDTH, 0, 1)
    chroma = np.hypot(cb, cr)
    return near * np.clip((chroma - .015) / .045, 0, 1)


def stats(rgb):
    """The grade's statistics of a picture (N x 3 display RGB, 0-1): brightness percentiles, colour strength (HSV
    saturation p50 and p90), the colour lean of each brightness band (mean RGB minus its luma) and the share of
    strong warm pixels (skin-tone hues at saturation 0.35 or more)."""
    rgb = np.asarray(rgb, float).reshape(-1, 3)
    if len(rgb) < 64:
        return None
    y = luma(rgb)
    q = np.percentile(y, QUANTS)
    sat = _saturation(rgb)
    chroma = rgb - y[:, None]
    cast = {'all': chroma.mean(axis=0)}
    for name, mask in _bands(y).items():
        if mask.any():
            cast[name] = chroma[mask].mean(axis=0)
    warm = float(((_skin(rgb) > .5) & (sat >= .35) & (y > .08)).mean())
    return {'luma': {f'p{n:02d}': round(float(v), 4) for n, v in zip(QUANTS, q)},
            'saturation': {'p50': round(float(np.median(sat)), 4), 'p90': round(float(np.percentile(sat, 90)), 4)},
            'cast': {k: [round(float(c), 4) for c in v] for k, v in cast.items()},
            'warm_share': round(warm, 4)}


def _lean(rgb):
    rgb = np.asarray(rgb, float)
    return [round(float(c), 4) for c in rgb - float(rgb @ WEIGHTS)]


def sample_from_lighting(scene, sample):
    """A grade sample from one lighting.json sample: its full grade statistics when Learn measured them, else what the
    picture region holds (black p05, median and p95, saturation p50, the whole picture's lean and the brightest
    tenth's). None for a sample that is not a picture of the Look: a graphic, a native effect, a black or flat frame."""
    if scene.get('role') == 'graphics' or sample.get('native_effects_at_sample'):
        return None
    metrics = sample.get('metrics') or {}
    graded = metrics.get('grade')
    picture = metrics.get('picture') or {}
    if graded:
        out = {key: graded[key] for key in ('luma', 'saturation', 'cast', 'warm_share') if key in graded}
    elif picture:
        out = {'luma': {'p05': picture['luma_p05'], 'p50': picture['luma_p50'], 'p95': picture['luma_p95']},
               'saturation': {'p50': picture['saturation_p50']},
               'cast': {'all': _lean(picture['mean_rgb'])}}
        if picture.get('bright_rgb_proxy'):
            out['cast']['highlights'] = _lean(picture['bright_rgb_proxy'])
    else:
        return None
    lum = out['luma']
    if lum['p95'] < .03 or lum['p95'] - lum['p05'] < .02:
        return None
    return {'at_s': round(float(sample.get('at_s', 0)), 3), 'role': scene.get('role', 'unknown'), **out}


def profile(profiles):
    """letitedit-grade/1 from a Look's lighting profiles (one or a list); None with fewer than three usable samples."""
    if profiles is None:
        return None
    profiles = [profiles] if isinstance(profiles, dict) else list(profiles)
    samples, skipped, measured = [], 0, True
    for index, item in enumerate(profiles):
        for scene in item.get('scenes') or []:
            for sample in scene.get('samples') or []:
                got = sample_from_lighting(scene, sample)
                if got is None:
                    skipped += 1
                    continue
                measured = measured and bool((sample.get('metrics') or {}).get('grade'))
                samples.append({'reference': index, **got})
    if len(samples) < 3:
        return None
    return {'format': FORMAT, 'from': 'measured' if measured else 'lighting.json picture regions',
            'samples': samples, 'skipped_samples': skipped, 'limits': LIMITS}


def digest(grade):
    return hashlib.sha256(json.dumps(grade, sort_keys=True).encode()).hexdigest()[:16]


def look_grade(script=None, look=None):
    """The chosen Look's grade: {'look', 'grade', 'from': 'grade.json' | 'lighting.json', 'skin': the reference's skin
    (grade_skin.reference_skin) or None}; {} when the project has no Look or its Look measured none. A Look saved before grades were kept has its grade worked out from its
    lighting.json when it is read (its saved revision is never rewritten)."""
    try:
        import letitedit.looks.looks as looks
        if look is None:
            import letitedit.looks.look_inputs as look_inputs
            import letitedit.review.brief_check as brief_check
            project = (script or {}).get('project')
            look = ((look_inputs.read(project) or {}).get('look') or (brief_check.load(project=project) or {}).get('look'))
        if not look or str(look).strip().lower() in ('none', 'auto', 'freestyle'):
            return {}
        recipe = Path(looks.read(look)['recipe'])
    except Exception:  # noqa: BLE001 - no Look, or one that is not offered: no grade
        return {}
    light = recipe.with_name('lighting.json')
    try:
        profiles = json.loads(light.read_text(encoding='utf-8-sig')) if light.is_file() else None
    except (OSError, ValueError):
        profiles = None
    skin = grade_skin.reference_skin(profiles) if profiles else None
    saved = recipe.with_name('grade.json')
    if saved.is_file():
        grade = json.loads(saved.read_text(encoding='utf-8-sig'))
        if grade.get('format') == FORMAT and len(grade.get('samples') or []) >= 3:
            return {'look': look, 'grade': grade, 'from': 'grade.json', 'skin': skin}
    if profiles:
        grade = profile(profiles)
        if grade:
            return {'look': look, 'grade': grade, 'from': 'lighting.json', 'skin': skin}
    return {}


def target(grade, clip, shared=None):
    """The grade to reach for a clip: the median of the reference samples nearest it in brightness (its median and
    p95 luma, in stops), at least three and a fifth of them. With shared (default: the reference holds one grade,
    grade_match.uneven is False) its colour strength and lean are every sample's median instead, and the colour may
    come down further (saturation_low) with skin protection kept to skin (skin_only). A clip whose median sits over
    FAR_OUTSIDE stops outside the reference's range may move FAR_STOPS (max_stops)."""
    samples = grade['samples']
    lum = clip['luma']
    if shared is None:
        import letitedit.looks.grade_match as grade_match
        shared = not grade_match.uneven(grade)

    def distance(sample):
        return math.hypot(math.log2(max(.01, lum['p50']) / max(.01, sample['luma']['p50'])),
                          math.log2(max(.01, lum['p95']) / max(.01, sample['luma']['p95'])))
    near = sorted(samples, key=distance)[:max(3, math.ceil(len(samples) / 5))]
    out = {'luma': {}, 'saturation': {}, 'cast': {}, 'samples': [s['at_s'] for s in near]}
    colour = samples if shared else near
    for part, rows in (('luma', near), ('saturation', colour)):
        for key in sorted({k for s in rows for k in s.get(part, {})}):
            values = [s[part][key] for s in rows if key in s.get(part, {})]
            out[part][key] = float(np.median(values))
    for key in sorted({k for s in colour for k in s.get('cast', {})}):
        values = np.array([s['cast'][key] for s in colour if key in s.get('cast', {})], float)
        out['cast'][key] = np.median(values, axis=0).tolist()
    if not shared:
        return out          # an uneven reference: the nearest samples' grade, as fitted before grade-fit/6
    out.update(shared=True, saturation_low=SHARED_SATURATION_LOW, skin_only=True, lean_full=True)
    # one grade has one black point: the blacks of every sample, kept under the clip's own p25 target so a dark scene's
    # blacks are never lifted past its shadows
    for key, share in SHARED_BLACK.items():
        values = [s['luma'][key] for s in samples if key in s.get('luma', {})]
        if values and key in out['luma']:
            ceiling = out['luma'].get('p25', 1.) * share
            out['luma'][key] = float(min(np.median(values), ceiling))
    medians = [s['luma']['p50'] for s in samples if s.get('luma', {}).get('p50')]
    if medians:
        low, high = np.percentile(medians, (10, 90))
        outside = max(math.log2(max(.01, low) / max(.01, lum['p50'])), math.log2(max(.01, lum['p50']) / max(.01, high)))
        if outside > FAR_OUTSIDE:
            out['max_stops'] = FAR_STOPS
    return out


# ------------------------------------------------------------------ the transform

def _curve(knots, steepest=SLOPE[1]):
    """A monotone tone curve on 0-1 through [(x, y)] knots (luma in, luma out), its slopes kept between SLOPE's
    flattest and `steepest`, ends extended at the nearest knot's slope; returned as 257 samples of the curve."""
    xs = np.array([k[0] for k in knots], float)
    ys = np.array([k[1] for k in knots], float)
    keep = np.concatenate([[True], np.diff(xs) > 2e-3])
    xs, ys = xs[keep], ys[keep]
    middle = int(np.argmin(np.abs(xs - np.median(xs))))
    low, high = SLOPE[0], steepest
    for i in range(middle + 1, len(xs)):
        dx = xs[i] - xs[i - 1]
        ys[i] = ys[i - 1] + min(max(ys[i] - ys[i - 1], low * dx), high * dx)
    for i in range(middle - 1, -1, -1):
        dx = xs[i + 1] - xs[i]
        ys[i] = ys[i + 1] - min(max(ys[i + 1] - ys[i], low * dx), high * dx)
    first = (ys[1] - ys[0]) / (xs[1] - xs[0]) if len(xs) > 1 else 1.
    last = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if len(xs) > 1 else 1.
    x = np.concatenate([[0.], xs, [1.]])
    y = np.concatenate([[ys[0] - xs[0] * min(max(first, low), high)], ys,
                        [ys[-1] + (1 - xs[-1]) * min(max(last, low), high)]])
    grid = np.linspace(0, 1, 257)
    curve = np.interp(grid, x, np.clip(y, 0, 1))
    soft = np.convolve(np.pad(curve, 2, mode='edge'), np.ones(5) / 5, mode='valid')     # knees softened by 1/128
    return np.maximum.accumulate(np.clip(soft, 0, 1))


def transform(rgb, params):
    """The grade on N x 3 display RGB (0-1): luma through the tone curve (each channel moved by the same amount, so
    the colour differences hold), colour strength scaled, then the colour lean for the new brightness added; skin-tone
    hues keep PROTECT of their colour. With params' `skin` (grade-fit/5 on) skin-tone hues keep that share of the lean
    and of the colour-strength change, and where the curve darkens or brightens them their colour follows their
    brightness (their own colour strength holds rather than deepening or washing out). The same function makes the LUT and measures what it does."""
    rgb = np.clip(np.asarray(rgb, float).reshape(-1, 3), 0, 1)
    y = luma(rgb)
    curve = np.asarray(params['curve'], float)
    toned = np.interp(y, np.linspace(0, 1, len(curve)), curve)
    chroma = rgb - y[:, None]
    skin = _skin(rgb)
    if 'skin' in params:
        protect = float(params['skin']) * np.clip(2 * skin, 0, 1)    # whole within half the skin-tone width
        if params.get('skin_only'):
            # grade-fit/6: a pixel far more colourful than skin (a warm lamp, sodium light) takes the grade
            low, high = SKIN_SATURATION
            protect = protect * np.clip((high - _saturation(rgb)) / (high - low), 0, 1)
        follow = np.clip(toned / np.maximum(y, 1e-3), 0., FOLLOW)   # how much darker or brighter the curve makes it
        scale = (1 + (params['saturation'] - 1) * (1 - protect)) * (1 + protect * (follow - 1))
        colour = np.hypot((rgb[:, 2] - y) / 1.8556, (rgb[:, 0] - y) / 1.5748)
        coloured = 0. if params.get('lean_full') else 1 - LEAN_COLOURED      # one shared colour: colourful pixels too
        keep = (1 - protect) * (1 - coloured * np.clip(colour / LEAN_CHROMA, 0, 1))
        if params.get('neutral'):
            # grade-fit/8: colour strength scaled around the clip's own cast at this brightness, so a boost doesn't
            # deepen the cast; skin keeps its protected share exactly as before
            at = np.array([p[0] for p in params['neutral']], float)
            vec = np.array([p[1] for p in params['neutral']], float)
            own = np.stack([np.interp(y, at, vec[:, c]) for c in range(3)], axis=1) * (1 - protect)[:, None]
            chroma = (chroma - own) * scale[:, None] + own
            scale = np.ones_like(scale)
    else:                       # a LUT fitted before grade-fit/5, measured as it was made
        keep = 1 - PROTECT * skin
        scale = 1 + (params['saturation'] - 1) * (1 - (1 - keep) * .6)
    lean = np.zeros_like(rgb)
    if params.get('lean'):
        at = np.array([p[0] for p in params['lean']], float)
        vec = np.array([p[1] for p in params['lean']], float)
        for c in range(3):
            lean[:, c] = np.interp(toned, at, vec[:, c])
    out = toned[:, None] + chroma * scale[:, None] + lean * keep[:, None]
    if params.get('skin_tone'):
        # grade-fit/11: skin (a qualifier on its colour and tones) takes the skin grade aimed at the reference's skin
        weight = grade_skin.key(rgb, params['skin_tone'])[:, None] * float(params['skin_tone'].get('mix', 1.))
        out = (1 - weight) * out + weight * grade_skin.apply(rgb, params['skin_tone'])
    return np.clip(out, 0, 1)


def _lean_points(graded, aim, limit=MAX_LEAN, highlights=None):
    """The colour lean to add at each band's brightness: the target's lean minus the graded picture's, kept to
    `limit` per channel (the highlights to `highlights` when given) and to no change in brightness; [(luma, [r, g, b])]
    in order of luma."""
    y = luma(graded)
    chroma = graded - y[:, None]
    masks = _bands(y)
    points = []
    for name in ('shadows', 'mids', 'highlights'):
        if name not in aim or not masks[name].any():
            continue
        points.append((float(np.median(y[masks[name]])), np.asarray(aim[name], float) - chroma[masks[name]].mean(0),
                       highlights if name == 'highlights' and highlights else limit))
    if 'all' in aim and not any(name in aim for name in ('shadows', 'mids')):
        # a grade measured from lighting.json knows the whole picture's lean and the brightest tenth's: the whole
        # picture's lean goes at the median of the rest
        rest = ~masks['highlights'] if 'highlights' in aim else np.ones(len(y), bool)
        points.append((float(np.median(y[rest])), np.asarray(aim['all'], float) - chroma.mean(0), limit))
    out = []
    for at, vec, most in sorted(points, key=lambda p: p[0]):
        vec = np.clip(vec, -most, most)
        vec = vec - float(vec @ WEIGHTS)
        out.append([round(at, 4), [round(float(c), 4) for c in vec]])
    return out


def _tone_curve(own, aim, strength=1.):
    """The tone curve from a clip's brightness percentiles to the target's (the median moved at most max_stops)."""
    have = sorted(set(own['luma']) & set(aim['luma']), key=lambda k: int(k[1:]))
    if 'p50' not in have or len(have) < 2:
        raise ValueError('the grade needs the median and one more brightness percentile')
    x50, y50 = own['luma']['p50'], aim['luma']['p50']
    stops = aim.get('max_stops', MAX_STOPS)
    bound = min(max(y50, x50 * 2 ** -stops), x50 * 2 ** stops)
    ratio = bound / y50 if y50 > 1e-4 else 1.
    knots = []
    for key in have:
        x, y = own['luma'][key], min(1., aim['luma'][key] * ratio)
        knots.append((x, x + strength * (y - x)))
    # no part of the picture moves away from its target: where the highlights are to rise (or the blacks to fall),
    # the median moves no further than the curve's steepest slope lets them keep their place
    middle = have.index('p50')
    steep = steepest(own, aim)
    knots = _ends_first(knots, middle, steep, have)
    room = steep * .97          # a little short of the steepest, which the curve's softened knees can't quite keep
    floor = max([x - room * (x - x50) for x, y in knots[middle + 1:] if y >= x] + [0.])
    ceiling = min([x + room * (x50 - x) for x, y in knots[:middle] if y <= x] + [1.])
    if floor <= ceiling:
        knots[middle] = (x50, min(max(knots[middle][1], floor), ceiling))
    return _curve(knots, steep).round(4).tolist()


def fit(pixels, aim, strength=1.):
    """The transform that takes a clip's pixels (N x 3, 0-1) to the target grade: knots from the clip's brightness
    percentiles to the target's (the median moved at most MAX_STOPS), colour strength solved so the graded HSV
    saturation meets the target's p50 (and p90 when measured), the lean per band; all scaled by strength (0-1). With
    the target's median_move (stops) the fitted curve's midtones move that far first (_midtone), and the colour is
    solved for the moved curve. The skin grade is added after (skin_grade)."""
    pixels = np.clip(np.asarray(pixels, float).reshape(-1, 3), 0, 1)
    if not 0 <= strength <= 1:
        raise ValueError('grade strength is 0 to 1')
    own = stats(pixels)
    if len(pixels) > FIT_PIXELS:
        pixels = pixels[np.random.default_rng(0).choice(len(pixels), FIT_PIXELS, replace=False)]
    if own is None:
        raise ValueError('too few pixels to grade from')
    curve = _tone_curve(own, aim, strength)
    if aim.get('median_move'):
        curve = _midtone(curve, own['luma']['p50'], aim['median_move'], own['luma'].get('p05'))
    only = bool(aim.get('skin_only'))
    neutral = _band_cast(pixels) if aim.get('shared') else []
    for protect in SKIN_PROTECT:
        params = _colour({'curve': curve, 'saturation': 1., 'lean': [], 'skin': protect,
                          **({'skin_only': True} if only else {}),
                          **({'lean_full': True} if aim.get('lean_full') else {}),
                          **({'neutral': neutral} if neutral else {})}, pixels, aim, strength)
        graded = transform(pixels, params)
        skin = skin_change(pixels, graded, cap=SKIN_SATURATION[0] if only else None)
        if skin is None or skin['held']:
            break
    after = stats(graded)
    after['skin'] = skin
    return params, own, after


def lut_table(params, size=LUT_SIZE):
    """The LUT's table as write_cube writes it (N x 3, red changing fastest)."""
    axis = np.linspace(0, 1, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
    return transform(np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1), params)


def _held_passes(result):
    """Skin at its own tones passes on clipping, and on the spread and split where they were measured (with too few
    pixels to measure them, skin at its own tones is the furthest a clip goes)."""
    return (result['clip_ok'] and (result['spread'] is None or result['spread_ok'])
            and (result['split_stops'] is None or result['split_ok']))


def _unmeasured(result):
    return [name for name, value in (('noise', result['spread']), ('split', result['split_stops'])) if value is None]


def skin_grade(params, sample, reference, faces=None, light=None, strength=1., pixels=None):
    """The picture grade's params with the skin grade added (grade_skin), aimed at the reference's skin from `sample`
    (('faces' | 'cut', skin pixels)), for a clip with detected `faces` (face-box pixels, before the live face light
    `light`). Mixed in at SKIN_MIXES (how much of it replaces the picture grade on the pixels the key takes), each
    checked on the LUT's own table against the picture grade alone (grade_skin.check: clipping per face; with the
    clip's `pixels`, the clip's noise growth and split); the largest mix that passes is kept, else skin held at its own
    tones (also where the noise or split can't be measured), else the picture grade alone, and the result says so.
    Returns (params, result: the check, kind, mix, held, not_measured and fallback when it fell back); (params, None)
    without faces."""
    if not reference or not sample or not faces:
        return params, None
    kind, skin = sample
    checked = list(faces)
    base = lut_table(params)
    aimed = grade_skin.fit_skin(skin, reference, strength)
    unmeasured = []
    for mix in SKIN_MIXES:
        tone = {**aimed, 'mix': mix}
        trial = {**params, 'skin_tone': tone}
        result = grade_skin.check(checked, LUT_SIZE, lut_table(trial), reference, light, pixels, tone, base)
        if result['ok']:
            return trial, {**result, 'kind': kind, 'mix': mix}
        unmeasured = _unmeasured(result)
        if unmeasured and result['clip_ok']:
            break                       # not measurable on this clip: no lower mix would be either
    # none of the way: skin keyed back to its own tones and colour (the picture grade can clip skin on its own)
    tone = grade_skin.fit_skin(skin, reference, 0.)
    held = {**params, 'skin_tone': tone}
    result = grade_skin.check(checked, LUT_SIZE, lut_table(held), reference, light, pixels, tone, base)
    if _held_passes(result):
        missing = _unmeasured(result) or unmeasured
        why = (f"the {' and '.join(missing)} check{'s' if len(missing) > 1 else ''} couldn't be measured on this clip "
               '(too few skin pixels), so skin keeps its own tones' if missing else
               'no skin grade toward the reference passed its checks, so skin keeps its own tones')
        return held, {**result, 'ok': True, 'kind': kind, 'mix': 1., 'held': True, 'fallback': why,
                      **({'not_measured': missing} if missing else {})}
    result = grade_skin.check(checked, LUT_SIZE, base, reference, light)
    return params, {**result, 'kind': kind, 'mix': 0.,
                    'fallback': 'no skin grade passed its checks, so skin takes the picture grade'}


def _band_cast(pixels):
    """The clip's own cast in each brightness band (shadows, mids, highlights): [(median luma, mean RGB offset from
    luma)] in order of luma, the points colour strength is scaled around with one shared colour."""
    y = luma(pixels)
    chroma = pixels - y[:, None]
    out = []
    for name, mask in _bands(y).items():
        if mask.any():
            out.append([round(float(np.median(y[mask])), 4), [round(float(c), 4) for c in chroma[mask].mean(0)]])
    return sorted(out, key=lambda p: p[0])


def _ends_first(knots, middle, steep, keys=None):
    """Knots between the median and the grade's blacks and highlights (p05 and p95, else the outermost knots) give way
    to them: walking from the blacks toward the median (and from the highlights down), a knot that would make the
    curve steeper than `steep` (or flatter than SLOPE's flattest) from its outer neighbour moves toward it. Without
    this the curve keeps the inner targets and lets the blacks rise (or the highlights fall) wherever a picture's
    brightness is split between dark and bright parts. The knots outside them (p01, p99: often clipped) follow the
    curve's own limits from the middle out."""
    out = [list(knot) for knot in knots]
    low = SLOPE[0]
    keys = list(keys or [])
    first = keys.index('p05') if 'p05' in keys and keys.index('p05') < middle else 0
    last = keys.index('p95') if 'p95' in keys and keys.index('p95') > middle else len(out) - 1
    for i in range(first + 1, middle):
        dx = out[i][0] - out[i - 1][0]
        if dx > 2e-3:
            out[i][1] = min(max(out[i][1], out[i - 1][1] + low * dx), out[i - 1][1] + steep * dx)
    for i in range(last - 1, middle, -1):
        dx = out[i + 1][0] - out[i][0]
        if dx > 2e-3:
            out[i][1] = max(min(out[i][1], out[i + 1][1] - low * dx), out[i + 1][1] - steep * dx)
    return [tuple(knot) for knot in out]


def steepest(own, aim):
    """The tone curve's steepest slope for a clip: SLOPE's, or on a clip far flatter than the grade (its p05-p95
    spread under half the grade's) half the ratio of the spreads, at most FLAT_SLOPE."""
    try:
        mine = own['luma']['p95'] - own['luma']['p05']
        theirs = aim['luma']['p95'] - aim['luma']['p05']
    except KeyError:
        return SLOPE[1]
    if mine <= 1e-3:
        return FLAT_SLOPE
    return round(float(min(FLAT_SLOPE, max(SLOPE[1], .5 * theirs / mine))), 3)


def _colour(params, pixels, aim, strength):
    """The colour strength and lean of a transform whose curve is set: the strength solved so the graded HSV
    saturation meets the target's p50 (and p90 when measured), the lean per band; a clip still much greyer than the
    target leans further in the target's own direction (CAST_GAIN, GREY_LEAN); all scaled by strength (0-1)."""
    goals = [(key, aim['saturation'][key]) for key in ('p50', 'p90') if key in aim.get('saturation', {})]
    cast = aim.get('cast') or {}

    def lean_at(scale, gain=1.):
        # the lean that brings each band to the target's at this colour strength (the clip's own cast is scaled too)
        limit = MAX_LEAN if gain <= 1 else GREY_LEAN
        return _lean_points(transform(pixels, {**params, 'saturation': scale, 'lean': []}),
                            {key: [c * gain for c in vec] for key, vec in cast.items()}, limit,
                            SHARED_HIGHLIGHT_LEAN if aim.get('shared') else None)

    def got(scale, gain=1.):
        sat = _saturation(transform(pixels, {**params, 'saturation': scale, 'lean': lean_at(scale, gain)}))
        return {'p50': float(np.median(sat)), 'p90': float(np.percentile(sat, 90))}

    def error(scale, gain=1.):
        have = got(scale, gain)
        return sum(math.log(max(1e-3, have[key]) / max(1e-3, want)) ** 2 for key, want in goals)
    gain = 1.
    if goals:
        want = dict(goals).get('p50')
        # a clip less colourful than the grade at its median never loses colour strength
        low = 1. if want and got(1.)['p50'] < want else aim.get('saturation_low', SATURATION[0])
        coarse = min(np.arange(low, SATURATION[1] + 1e-9, .05), key=error)
        fine = np.clip(np.arange(coarse - .04, coarse + .041, .01), low, SATURATION[1])
        params['saturation'] = float(min(fine, key=error))
        if cast and want and not aim.get('shared') and got(params['saturation'])['p50'] < GREY * want:
            # colour scaled up from grey stays grey: lean further toward the grade's own colour, to its median colour
            # strength (a lean moves every grey alike, so it can't make the grade's spread of colour strengths)
            gains = np.arange(CAST_GAIN[0], CAST_GAIN[1] + 1e-9, .25)
            gain = float(min(gains, key=lambda g: abs(math.log(max(1e-3, got(params['saturation'], g)['p50']) / want))))
    lean = lean_at(params['saturation'], gain)
    params['saturation'] = round(1 + strength * (params['saturation'] - 1), 3)
    params['lean'] = [[at, [round(strength * c, 4) for c in vec]] for at, vec in lean]
    if gain > 1:
        params['cast_gain'] = round(gain, 2)
    return params


def _hue(rgb):
    y = luma(rgb)
    return np.degrees(np.arctan2((rgb[:, 0] - y) / 1.5748, (rgb[:, 2] - y) / 1.8556))


def skin_change(before, after, cap=None):
    """What a grade did to the skin-tone pixels of a picture (before and after, N x 3): their colour strength (HSV
    saturation p50 and p90) and the median turn of their hue in degrees, and whether skin held (SKIN_RISE,
    SKIN_TURN). Skin-tone pixels are hues on the skin line with some colour, neither near black nor near white (orange
    and red things count too). None when under SKIN_MIN of the picture is skin-tone."""
    before, after = np.asarray(before, float).reshape(-1, 3), np.asarray(after, float).reshape(-1, 3)
    y = luma(before)
    sat = _saturation(before)
    mask = (_skin(before) > .5) & (y > .12) & (y < .92) & (sat >= .12)
    if cap is not None:
        mask &= sat <= cap          # with one shared colour, skin is what is no more colourful than skin
    if not len(before) or mask.mean() < SKIN_MIN or mask.sum() < 50:
        return None
    graded = _saturation(after)[mask]
    turn = float(np.median(np.abs((_hue(after[mask]) - _hue(before[mask]) + 180) % 360 - 180)))
    p90 = [float(np.percentile(sat[mask], 90)), float(np.percentile(graded, 90))]
    return {'share': round(float(mask.mean()), 4),
            'saturation_p50': [round(float(np.median(sat[mask])), 4), round(float(np.median(graded)), 4)],
            'saturation_p90': [round(p90[0], 4), round(p90[1], 4)], 'hue_turn': round(turn, 2),
            'held': bool(abs(p90[1] - p90[0]) <= SKIN_RISE and turn <= SKIN_TURN)}


def write_cube(path, params, size=LUT_SIZE, title='letitedit grade'):
    """The transform as a .cube 3D LUT (red changes fastest), the file the engine's LUT (3D) filter reads."""
    axis = np.linspace(0, 1, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
    grid = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)
    out = transform(grid, params)
    lines = [f'TITLE "{title}"', f'LUT_3D_SIZE {size}', 'DOMAIN_MIN 0 0 0', 'DOMAIN_MAX 1 1 1']
    lines += [f'{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}' for v in out]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')
    return path


def read_cube(path):
    """(size, N x 3 table) of a .cube file written by write_cube."""
    size, rows = None, []
    for line in Path(path).read_text(encoding='ascii').splitlines():
        if line.startswith('LUT_3D_SIZE'):
            size = int(line.split()[1])
        elif line and (line[0].isdigit() or line[0] == '-'):
            rows.append([float(v) for v in line.split()])
    return size, np.array(rows)


# ------------------------------------------------------------------ the timeline

def clip_faces(path, start, end, frames=FRAMES):
    """The faces on the same frames clip_pixels reads: [face box pixels (N x 3, 0-1)], one array per face per frame,
    found with the face guard lighting uses (lighting.face_boxes, YuNet) on frames FACE_FRAME_WIDTH wide. [] when no
    face is found; raises ValueError when the face guard isn't installed."""
    import cv2
    import letitedit.looks.lighting as lighting
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if end is None:
            end = count / fps if count else start + 1.
        span = max(0., end - start)
        out = []
        rng = np.random.default_rng(0)
        for i in range(frames):
            t = start + span * (i + .5) / frames
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            width = min(w, FACE_FRAME_WIDTH)
            small = cv2.cvtColor(cv2.resize(frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2RGB)
            for box in lighting.face_boxes(small):
                try:
                    y0, y1, x0, x1 = lighting._box_pixels(small, box)
                except ValueError:
                    continue
                px = small[y0:y1, x0:x1].reshape(-1, 3).astype(float) / 255
                if len(px) > FACE_BOX_PIXELS:
                    px = px[rng.choice(len(px), FACE_BOX_PIXELS, replace=False)]
                if len(px) >= 16:
                    out.append(px)
        return out
    finally:
        cap.release()


def face_guard_state():
    """What the face guard is right now (its model file's size and time, and whether OpenCV has YuNet), so a clip's
    cached faces, or its cached lack of them, are found again when it changes."""
    try:
        import cv2
        import letitedit.pictures.vfx_items as vfx_items
        model = vfx_items.VFX_DIR / 'models' / 'yunet_2023mar.onnx'
        stat = model.stat()
        return f'yunet:{stat.st_size}:{stat.st_mtime_ns}:{int(hasattr(cv2, "FaceDetectorYN"))}'
    except (OSError, ImportError):
        return 'missing'


def clip_pixels(path, start, end, frames=FRAMES, width=WIDTH):
    """Display RGB pixels (N x 3, 0-1) of `frames` frames spread over a stretch of a video file."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if end is None:
            end = count / fps if count else start + 1.
        span = max(0., end - start)          # in and out are the file's own seconds
        out = []
        for i in range(frames):
            t = start + span * (i + .5) / frames
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
            out.append(cv2.cvtColor(small, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(float) / 255)
        return np.concatenate(out) if out else np.zeros((0, 3))
    finally:
        cap.release()


def chosen_look(script):
    """The project's chosen Look id (its inputs, else its brief), or None."""
    try:
        import letitedit.looks.look_inputs as look_inputs
        import letitedit.review.brief_check as brief_check
        project = (script or {}).get('project')
        look = ((look_inputs.read(project) or {}).get('look') or (brief_check.load(project=project) or {}).get('look'))
    except Exception:  # noqa: BLE001 - no brief, or one that can't be read: no Look
        return None
    return None if not look or str(look).strip().lower() in ('none', 'auto', 'freestyle') else str(look)


def own_intro(script):
    """The chosen Look's own intro file (own_media.intro, played whole and unchanged), normalised, or None."""
    look = chosen_look(script)
    if not look:
        return None
    try:
        import letitedit.looks.looks as looks
        intro = ((looks.read(look) or {}).get('own_media') or {}).get('intro') or {}
    except Exception:  # noqa: BLE001 - a Look that is not offered has no own media
        return None
    return os.path.normcase(os.path.abspath(intro['file'])) if intro.get('file') else None


def is_own_intro(clip, intro):
    return bool(intro and clip) and os.path.normcase(os.path.abspath(str(clip))) == intro


def _footage(script):
    """(track, item) for every clip of footage on a picture track: a video file the person filmed or brought, not a
    picture, graphic, colour, text, adjustment layer or made clip, nor the Look's own intro (played unchanged)."""
    import letitedit.server.core_tools as core_tools
    import letitedit.timeline.made as made
    intro = own_intro(script)
    for track in script['tracks']:
        if track.get('kind', 'video') != 'video':
            continue
        for item in track['items']:
            clip = item.get('clip')
            if (clip and 'id' in item and core_tools._kind(clip) == 'video' and not made.is_made(item)
                    and not ({'graphic', 'color', 'adjust', 'text'} & set(item)) and not is_own_intro(clip, intro)):
                yield track, item


def is_graded(item):
    return any(isinstance(e, dict) and (e.get('params') or {}).get(TAG) for e in item.get('effects') or [])


def ungraded_footage(script):
    """Ids of footage clips without the Look's grade."""
    return [str(item['id']) for _, item in _footage(script) if not is_graded(item)]


def bits_per_pixel(path):
    """The video stream's bits per pixel per frame (its bit rate, or the file's, over width x height x frame rate),
    or None when the file doesn't say."""
    import letitedit.core.media as media
    try:
        info = media.probe(str(path))
    except Exception:  # noqa: BLE001 - unknown: graded as before
        return None
    for stream in info.get('streams') or []:
        if stream.get('codec_type') != 'video':
            continue
        try:
            rate = float(stream.get('bit_rate') or (info.get('format') or {}).get('bit_rate') or 0)
            num, _, den = str(stream.get('avg_frame_rate') or stream.get('r_frame_rate') or '0/1').partition('/')
            fps = float(num) / float(den or 1) if float(den or 1) else 0.
            pixels = float(stream.get('width') or 0) * float(stream.get('height') or 0)
        except (TypeError, ValueError):
            return None
        return round(rate / (pixels * fps), 4) if rate and pixels and fps else None
    return None


def _place(effects, grade_effect):
    """The effect list with our grade replaced or put in: after the face lighting's mask trios (light, then grade).
    grade_effect: one effect or a list of them (a deband filter, then the LUT)."""
    import letitedit.looks.lighting as lighting
    kept = [e for e in effects if not (isinstance(e, dict) and (e.get('params') or {}).get(TAG))]
    if grade_effect is None:
        return kept
    spans = lighting._live_pieces(kept)
    at = spans[-1][1] if spans else 0
    added = list(grade_effect) if isinstance(grade_effect, (list, tuple)) else [grade_effect]
    return kept[:at] + added + kept[at:]


def _groups(values):
    """The reference's medians (log2, sorted) as one group or two, [(low, high)]: two when a gap of GAP_STOPS or more
    has at least GAP_SHARE of them on each side (the widest such gap)."""
    n = len(values)
    best = None
    for i in range(1, n):
        if i / n >= GAP_SHARE and (n - i) / n >= GAP_SHARE and values[i] - values[i - 1] >= GAP_STOPS:
            if best is None or values[i] - values[i - 1] > values[best] - values[best - 1]:
                best = i
    if best is None:
        return [(values[0], values[-1])], None
    return [(values[0], values[best - 1]), (values[best], values[-1])], (values[best - 1] + values[best]) / 2


def brightness_plan(grade, planned):
    """With one shared colour: the cut's planned medians (one per clip, in luma) brought inside the reference's spread
    across its shots. Per group (one, or a dark group and a bright one when the reference has both), in stops: the
    cut's middle moves to the reference's middle, and the cut's spread (p10-p90) shrinks to the reference's when it is
    wider (a narrower cut is never spread out), kept within the reference's range; each clip moves at most
    SPREAD_STOPS, so the order of the clips holds and a dark group stays below the bright one by the reference's gap.
    Returns the medians in the same order; unchanged when the reference is uneven, or with too few clips or samples."""
    import letitedit.looks.grade_match as grade_match
    medians = sorted(math.log2(max(.005, s['luma']['p50'])) for s in grade.get('samples') or []
                     if s.get('role') != 'graphics' and (s.get('luma') or {}).get('p50'))
    if len(medians) < 5 or len(planned) < 3 or grade_match.uneven(grade):
        return list(planned)
    groups, split = _groups(medians)
    logs = [math.log2(max(.005, v)) for v in planned]
    side = [0 if split is None or v < split else 1 for v in logs]
    out = list(logs)
    for g, (low, high) in enumerate(groups):
        theirs = [m for m in medians if low <= m <= high]
        mine = [i for i, s in enumerate(side) if s == g]
        if not mine:
            continue
        ours = [logs[i] for i in mine]
        middle, centre = float(np.median(ours)), float(np.median(theirs))
        spread = float(np.subtract(*np.percentile(ours, (90, 10))))
        room = float(np.subtract(*np.percentile(theirs, (90, 10))))
        shrink = min(1., room / spread) if spread > 1e-6 else 1.
        for i in mine:
            aim = min(max(centre + (logs[i] - middle) * shrink, low), high)
            out[i] = logs[i] + float(np.clip(aim - logs[i], -SPREAD_STOPS, SPREAD_STOPS))
    return [round(2 ** v, 4) for v in out]


def _midtone(curve, x50, stops, x05=None):
    """The fitted tone curve with its midtones moved so the clip's median lands `stops` from where the curve puts it
    (as near as a gentle bow allows): between the curve's black (its output at the clip's own p05, else its lowest)
    and its white, t -> t + a t (1 - t), as a Levels midtone control bows the curve. Below that black the curve is left,
    so the black point and the top of the highlights hold (nothing is clipped, lifted or crushed); with |a| at most 1
    the curve stays rising and never more than twice as steep, so the order of every brightness holds and the shadows
    just above the black open or close smoothly."""
    c = np.asarray(curve, float)
    grid = np.linspace(0, 1, len(c))
    b = float(c[0] if x05 is None else np.interp(x05, grid, c))
    w = float(c[-1])
    m = float(np.interp(x50, grid, c))
    if w - b < .05:
        return list(curve)
    t_m = (m - b) / (w - b)
    t_g = (min(w - .01, m * 2 ** stops) - b) / (w - b)
    if not (.01 < t_m < .99 and 0 < t_g < 1):
        return list(curve)
    a = float(np.clip((t_g - t_m) / (t_m * (1 - t_m)), -1, 1))
    above = c > b
    x = np.clip((c[above] - b) / (w - b), 0, 1)
    c[above] = b + (w - b) * (x + a * x * (1 - x))
    return c.round(4).tolist()


def fitted_median(own, aim, strength=1.):
    """The median luma the fit's tone curve gives the clip (its curve is monotone, so the graded median is the curve
    at the clip's own median)."""
    curve = _tone_curve(own, aim, strength)
    return float(np.interp(own['luma']['p50'], np.linspace(0, 1, len(curve)), curve))


def cover_footage(script, spec):
    """{op: fx, grade: true | {strength?, remove?}}: the chosen Look's measured grade on every clip of footage (any
    picture track, faces or not), one LUT (3D) filter per clip fitted to that clip, its skin graded to the reference's
    skin when the Look measured it. Returns {'graded', 'skipped', 'look', 'from', 'clips': [per-clip figures]}."""
    from letitedit.timeline.edit_sync import to_seconds
    import letitedit.looks.lighting as lighting
    spec = {} if spec is True else dict(spec or {})
    strength = spec.pop('strength', 1.)
    remove = bool(spec.pop('remove', False))
    if spec:
        raise ValueError(f"fx grade: unknown {', '.join(sorted(spec))}; the settings are strength (0-1) and remove")
    if type(strength) not in (int, float) or not 0 <= strength <= 1:
        raise ValueError('fx grade: strength is 0 to 1')
    report = {'graded': [], 'removed': [], 'skipped': [], 'clips': [], 'notes': []}
    if remove:
        for _, item in _footage(script):
            if is_graded(item):
                item['effects'] = _place(item.get('effects') or [], None)
                report['removed'].append(item['id'])
        return report
    found = look_grade(script)
    if not found:
        raise ValueError("fx grade: the project's Look has no measured grade (a learned Look measures one from its "
                         "reference; a library Look's colour is in its recipe and Theme)")
    grade = found['grade']
    reference_skin = found.get('skin')
    report.update(look=found['look'], **{'from': found['from']}, reference_skin=reference_skin)
    if (reference_skin or {}).get('skipped'):
        report['notes'].append(f"{reference_skin['skipped']} of the reference's face samples were skipped: their skin "
                               "colour is malformed in the Look's lighting.json")
    import letitedit.timeline.project_journal as project_journal
    folder = project_journal.folder(script['project']) / 'grade'
    key = digest(grade)
    guard_state = face_guard_state() if reference_skin else 'unused'
    skin_key = hashlib.sha256(json.dumps(reference_skin, sort_keys=True).encode()).hexdigest()[:12] \
        if reference_skin else None
    # first pass: every clip's own statistics and faces (cached by the clip, its file, its range and the face guard's
    # state) and its target
    rows = []
    for _, item in _footage(script):
        clip = Path(item['clip'])
        a = to_seconds(item.get('in') or 0)
        b = None if item.get('out') is None else to_seconds(item['out'])
        try:
            stamp = clip.stat().st_mtime_ns
        except OSError:
            report['skipped'].append(f"{item['id']}: its file is missing")
            continue
        base = folder / (hashlib.sha256(json.dumps([str(clip), stamp, a, b, STATS]).encode()).hexdigest()[:20]
                         + '.stats.json')
        saved = base.with_name(base.name.replace('.stats.json', '.faces.npz'))
        own, faces = None, None
        if base.is_file():
            try:
                cached = json.loads(base.read_text(encoding='utf-8-sig'))
                if cached.get('format') == STATS:
                    own = cached.get('stats')
                    if cached.get('face_guard') == guard_state:
                        if cached.get('faces') and saved.is_file():
                            with np.load(saved) as held:
                                faces = [held[k] for k in sorted(held.files, key=lambda k: int(k[1:]))]
                        elif not cached.get('faces'):
                            faces = []
            except (OSError, ValueError):
                own = None
        if own is None:
            own = stats(clip_pixels(clip, a, b))
        if faces is None:
            faces = []
            if reference_skin and guard_state != 'missing':
                try:
                    faces = clip_faces(clip, a, b)
                except ValueError:
                    guard_state = 'missing'
            if own is not None:
                base.parent.mkdir(parents=True, exist_ok=True)
                if faces:
                    np.savez_compressed(saved, **{f'f{i}': px.astype(np.float32) for i, px in enumerate(faces)})
                base.write_text(json.dumps({'format': STATS, 'stats': own, 'faces': len(faces),
                                            'face_guard': guard_state}), encoding='utf-8')
        if own is None or own['luma']['p95'] - own['luma']['p05'] < .02:
            report['skipped'].append(f"{item['id']}: too dark, flat or unreadable to grade from")
            continue
        rows.append([item, clip, a, b, stamp, own, target(grade, own), [np.asarray(px, float) for px in faces],
                     lighting.live_face_light(item)])
    if reference_skin and guard_state == 'missing':
        report['notes'].append("faces weren't measured (the face guard, YuNet, isn't installed): no clip took a skin "
                               "grade, and skin took the picture grade")
    # the cut's skin, for a clip whose detected faces hold too little skin of their own
    cut_skin = None
    if reference_skin:
        pooled = [grade_skin.skin_sample([lighting.live_face_pixels(px, row[8]) for px in row[7]]) for row in rows]
        pooled = [s[1] for s in pooled if s]
        if pooled:
            joined = np.concatenate(pooled)
            if len(joined) > FIT_PIXELS:
                joined = joined[np.random.default_rng(0).choice(len(joined), FIT_PIXELS, replace=False)]
            cut_skin = ('cut', joined)
    # with one shared colour, the cut's spread of brightness brought inside the reference's
    if rows and all(row[6].get('shared') for row in rows):
        planned = [fitted_median(row[5], row[6], strength) for row in rows]
        for row, before, median in zip(rows, planned, brightness_plan(grade, planned)):
            move = round(math.log2(max(1e-4, median) / max(1e-4, before)) * strength, 3)
            if move:
                row[6] = {**row[6], 'median_move': move}
    # second pass: each clip's LUT, named by everything its fit reads (the plan's move, the reference's skin, the face
    # guard's state), its skin graded and each face checked on the written LUT
    reach = {}
    for item, clip, a, b, stamp, own, aim, faces, light in rows:
        move = aim.get('median_move', 0.)
        # the skin grade's sample: the clip's detected faces' skin (after its live face light), else the cut's when
        # its faces hold too little skin; none without a detected face
        lit = [lighting.live_face_pixels(px, light) for px in faces]
        sample = (grade_skin.skin_sample(lit) or cut_skin) if reference_skin and faces else None
        sampled = (hashlib.sha256(np.ascontiguousarray(sample[1], np.float32).tobytes()).hexdigest()[:12]
                   if sample and sample[0] == 'cut' else None)
        name = hashlib.sha256(json.dumps([str(clip), stamp, a, b, key, strength, VERSION, move, skin_key,
                                          guard_state, SKIN_STEPS, light, sampled]).encode()).hexdigest()[:20]
        cube, notes = folder / f'{name}.cube', folder / f'{name}.json'
        if cube.is_file() and notes.is_file():
            figures = json.loads(notes.read_text(encoding='utf-8-sig'))
        else:
            pixels = clip_pixels(clip, a, b)
            # the picture grade can clip skin, or split it from its room, on its own: then part of the way. A share
            # (over none) whose skin grade toward the reference passes wins over the full picture grade with the skin
            # following its room; the full picture grade with skin following its room (or at its own tones) wins over
            # dropping the whole grade to keep some skin grade; with nothing passing, the first share that does, else
            # the last tried
            def toward(result):
                return result['ok'] and result.get('mix', 1.) > 0 and not result.get('held')
            tried = []
            for share in PICTURE_SHARES:
                fitted = fit(pixels, aim, strength * share)
                graded, result = skin_grade(fitted[0], sample, reference_skin, faces, light, strength, pixels)
                tried.append((share, fitted, graded, result))
                if result is None or not result['checked'] or (toward(result) and share > 0):
                    break
            share, (_, own, after), params, skin = tried[-1]
            if skin is not None and skin['checked'] and not (toward(skin) and share > 0):
                passing = [t for t in tried if t[3]['ok']]
                share, (_, own, after), params, skin = passing[0] if passing else tried[-1]
            if skin is not None and share < 1:
                skin = {**skin, 'picture_share': share}
            elif skin is not None:
                skin.pop('picture_share', None)
            if skin is not None:
                after = stats(transform(pixels, params))
                after['skin'] = None
            write_cube(cube, params)
            if skin is not None and skin['faces']:
                # the final check: the LUT as written and read back, each face as the engine will draw it
                size, table = read_cube(cube)
                checked = list(faces)
                picture = {k: v for k, v in params.items() if k != 'skin_tone'}
                base = lut_table(picture, size)
                tone = params.get('skin_tone')
                final = grade_skin.check(checked, size, table, reference_skin, light, pixels, tone, base)
                passed = _held_passes(final) if skin.get('held') else final['ok']
                if not passed and 'skin_tone' in params:
                    held = grade_skin.fit_skin(sample[1], reference_skin, 0.)
                    tries = [({**picture, 'skin_tone': held}, held,
                              "the written LUT didn't pass its checks, so skin keeps its own tones"),
                             (picture, None, "the written LUT didn't pass its checks, so skin takes the picture grade")]
                    for params, tone, why in tries[1 if skin.get('held') else 0:]:
                        write_cube(cube, params)
                        size, table = read_cube(cube)
                        final = grade_skin.check(checked, size, table, reference_skin, light, pixels, tone, base)
                        passed = _held_passes(final) if tone else final['ok']
                        if passed:
                            break
                    skin = {**skin, 'mix': 1. if tone else 0., 'held': bool(tone), 'fallback': why}
                    skin.pop('not_measured', None)
                    after = stats(transform(pixels, params))
                    after['skin'] = None
                missing = _unmeasured(final) if tone else []
                skin = {**skin, **{k: final[k] for k in ('faces', 'checked', 'clip_ok', 'spread', 'spread_ok',
                                                         'split_stops', 'split_ok', 'measured', 'inside', 'landed',
                                                         'rows')},
                        'ok': passed, **({'not_measured': missing} if missing else {}), 'on': 'the written LUT'}
                if not missing:
                    skin.pop('not_measured', None)
            figures = {'clip': str(clip), 'in': a, 'out': b, 'look': found['look'], 'grade': key,
                       'nearest_samples_s': aim['samples'], 'target': {k: aim[k] for k in ('luma', 'saturation', 'cast')},
                       'shared': bool(aim.get('shared')), 'max_stops': aim.get('max_stops', MAX_STOPS),
                       'spread_move_stops': move, 'before': own, 'after': after, 'params': params,
                       'skin_grade': skin}
            notes.write_text(json.dumps(figures, indent=1, default=float), encoding='utf-8')
        effect = {'filter': 'lut3d', 'params': {'av.file': cube.as_posix(), 'av.interp': 'tetrahedral', TAG: key}}
        if 'bpp' not in figures:
            figures['bpp'] = bits_per_pixel(clip)
        deband = figures['bpp'] is not None and figures['bpp'] < DEBAND_BPP
        if deband:
            effect = [{'filter': 'avfilter.deband', 'params': {**DEBAND, TAG: key}}, effect]
        item['effects'] = _place(item.get('effects') or [], effect)
        report['graded'].append(item['id'])
        before, after = figures['before'], figures['after']
        wanted = figures['target']['luma']
        move = figures.get('spread_move_stops', 0.) or 0.
        clip_reach = {'median': [round(wanted['p50'] * 2 ** move, 4), after['luma']['p50']],
                      'blacks': [wanted.get('p05'), after['luma'].get('p05')],
                      'highlights': [wanted.get('p95'), after['luma']['p95']],
                      'saturation': [figures['target']['saturation'].get('p50'), after['saturation']['p50']]}
        share = float((figures.get('skin_grade') or {}).get('picture_share', 1.))
        reach[cube.stem] = {'id': item['id'], 'in': a, 'out': b, 'strength': strength, 'picture_share': share,
                            'reach': clip_reach}
        report['clips'].append({'id': item['id'], 'median': [before['luma']['p50'], after['luma']['p50']],
                                'blacks': [before['luma'].get('p05'), after['luma'].get('p05')],
                                'highlights': [before['luma']['p95'], after['luma']['p95']],
                                'saturation': [before['saturation']['p50'], after['saturation']['p50']],
                                'target': {'median': wanted.get('p50'), 'blacks': wanted.get('p05'),
                                           'highlights': wanted.get('p95'),
                                           'saturation': figures['target']['saturation'].get('p50')},
                                'reach': clip_reach,
                                'skin': after.get('skin'), 'skin_grade': figures.get('skin_grade'),
                                'cast_gain': figures['params'].get('cast_gain'),
                                'shared': figures.get('shared', False),
                                'spread_move_stops': figures.get('spread_move_stops', 0.),
                                'skin_protect': figures['params'].get('skin'),
                                **({'deband': {'bits_per_pixel': figures['bpp']}} if deband else {})})
    # what each clip's fit reached against what it aimed at, beside the LUTs, by LUT name: the Look check reads it for
    # the clips whose LUT is still on the timeline
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'reach.json').write_text(json.dumps({'format': VERSION, 'look': found['look'], 'clips': reach}),
                                           encoding='utf-8')
    except OSError:
        pass
    return report


def last_reach(script):
    """{clip id: {measure: [aimed, reached], 'strength': the grade's strength, 'picture_share': the share of the
    picture grade the face checks left the clip}} from the project's last grade, for the
    clips whose LUT is still on the timeline over the same range (a regraded clip has a new LUT; a trimmed one keeps its
    LUT but not its range, and drops out); {} without one."""
    from letitedit.timeline.edit_sync import to_seconds
    try:
        import letitedit.timeline.project_journal as project_journal
        saved = json.loads((project_journal.folder(script['project']) / 'grade' / 'reach.json')
                           .read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    clips = saved.get('clips') or {}
    out = {}
    for _, item in _footage(script):
        for effect in item.get('effects') or []:
            if isinstance(effect, dict) and effect.get('filter') == 'lut3d':
                stem = Path(str((effect.get('params') or {}).get('av.file', ''))).stem
                entry = clips.get(stem) or {}
                if entry.get('id') != item['id']:
                    continue
                a = to_seconds(item.get('in') or 0)
                b = None if item.get('out') is None else to_seconds(item['out'])
                if 'in' in entry and (abs(entry['in'] - a) > 1e-3 or (entry.get('out') is None) != (b is None)
                                      or (b is not None and abs(entry['out'] - b) > 1e-3)):
                    continue                       # trimmed since the grade: its reach was for another range
                out[item['id']] = {**entry['reach'], 'strength': entry.get('strength', 1.),
                                   'picture_share': entry.get('picture_share', 1.)}
    return out


def _ids(ids, most=8):
    """'N clip(s): a, b, ... and M more'."""
    ids = list(ids)
    return (f"{len(ids)} clip{'s' if len(ids) != 1 else ''}: {', '.join(ids[:most])}"
            + (f' and {len(ids) - most} more' if len(ids) > most else ''))


def _describe_skin(report):
    """The reply's words on skin: what the skin grade aimed at, and what was checked on the written LUT."""
    rows, ref = report['clips'], report.get('reference_skin')
    if not ref:
        return ''
    graded = [r for r in rows if r.get('skin_grade')]
    text = (f"; skin graded to the reference's skin (skin luma p50 {ref['luma']['p50']:.2f}, its faces' "
            f"{ref['face_luma_p50'][1]:.2f}, from {ref['samples']} reference samples with a face) on {len(graded)} "
            "clip(s)")
    faced = [r for r in graded if r['skin_grade'].get('checked')]
    if faced:
        luma_before = [row['face_luma_p50'][0] for r in faced for row in r['skin_grade']['rows']]
        luma_after = [row['face_luma_p50'][1] for r in faced for row in r['skin_grade']['rows']]
        failing = [r['id'] for r in faced if not r['skin_grade'].get('ok', r['skin_grade']['clip_ok'])]
        unmeasured = [r for r in faced if r['skin_grade'].get('not_measured')]
        measured = [r for r in faced if not r['skin_grade'].get('not_measured')
                    and 'spread' in r['skin_grade'] and r['skin_grade'].get('mix', 0.) > 0]
        outside = [r['id'] for r in faced if not r['skin_grade']['inside']]
        short = [r['id'] for r in faced if not r['skin_grade'].get('landed', True)]
        text += (f"; faces checked on the written LUT on {len(faced)} clip(s) "
                 f"({sum(r['skin_grade']['checked'] for r in faced)} faces, face luma p50 {np.median(luma_before):.2f} -> "
                 f"{np.median(luma_after):.2f} median): "
                 + ('skin newly clipped at most 1% on every checked face' if not failing else
                    f"those checks still fail on {_ids(failing)}")
                 + (f"; on {len(measured)} clip(s) with a skin grade, measured over each clip's skin: camera noise "
                    f"grown at most {grade_skin.SPREAD_MAX:g}x the grade's own, in brightness and colour, and each "
                    f"keyed pixel at most {grade_skin.SPLIT_STOPS:g} stop from the picture grade alone" if measured
                    else '')
                 + (f"; noise or split not measured (too few skin pixels) on {_ids(r['id'] for r in unmeasured)}: "
                    "skin keeps its own tones there" if unmeasured else '')
                 + (f"; measured, not enforced: skin lands within {grade_skin.LANDED_STOPS:g} stop of the reference's "
                    "skin on every face clip" if not short else
                    f"; measured, not enforced: skin lands over {grade_skin.LANDED_STOPS:g} stop from the reference's "
                    f"skin on {_ids(short)}")
                 + ("; its hue and colour strength inside the reference's own range on every face" if not outside
                    else f"; its hue or colour strength outside the reference's own range on {_ids(outside)}"))
    partial = [f"{r['id']} ({r['skin_grade']['mix']:g})" for r in graded
               if 0 < r['skin_grade'].get('mix', 1.) < 1.]
    if partial:
        text += f"; the skin grade mixed in part of the way (to pass those checks) on {_ids(partial)}"
    held = [r['id'] for r in graded if r['skin_grade'].get('held') and not r['skin_grade'].get('not_measured')]
    if held:
        text += f"; skin keeps its own tones on {_ids(held)} (no skin grade toward the reference passed)"
    shared = [r for r in graded if r['skin_grade'].get('picture_share') is not None]
    if shared:
        listed = [f"{r['id']} ({r['skin_grade']['picture_share']:g})" for r in shared]
        text += (f"; the room held back to keep faces clean, the picture grade taken part of the way on "
                 f"{_ids(listed)} (at full strength it failed those checks)")
        most = [r['id'] for r in shared if r['skin_grade']['picture_share'] < .5]
        if most:
            text += f"; left without most of the Look's grade (outliers): {_ids(most)}"
    fell = [r['id'] for r in graded if 'picture grade' in r['skin_grade'].get('fallback', '')]
    if fell:
        text += f"; skin takes the picture grade on {_ids(fell)} (no skin grade passed)"
    faceless = [r['id'] for r in rows if not r.get('skin_grade')]
    if faceless:
        text += f"; no face detected on {len(faceless)} clip(s): the picture grade alone, no skin grade"
    return text


def describe(report):
    """One line for the fx op's reply."""
    if report.get('removed') is not None and not report.get('look'):
        return f"grade taken off {len(report['removed'])} clip(s)"
    rows = report['clips']
    text = (f"the Look's grade ({report['look']}, from its {report['from']}) on {len(report['graded'])} footage "
            f"clip{'s' if len(report['graded']) != 1 else ''}: LUT (3D) filters fitted per clip")
    if rows and all(r.get('shared') for r in rows):
        text += (", each toward one shared colour (the colour strength and lean of all the reference's samples: it "
                 "holds one grade from shot to shot)")
    if rows:
        def med(index, part):
            return float(np.median([r[part][index] for r in rows]))
        text += (f"; median luma {med(0, 'median'):.2f} -> {med(1, 'median'):.2f}, highlights (p95) "
                 f"{med(0, 'highlights'):.2f} -> {med(1, 'highlights'):.2f}, saturation {med(0, 'saturation'):.2f} -> "
                 f"{med(1, 'saturation'):.2f} (median over clips)")
        moved = [r for r in rows if abs(r.get('spread_move_stops') or 0.) >= .05]
        if moved:
            text += (f"; brightness spread matched to the reference's across its shots: {len(moved)} clip(s) moved "
                     f"(at most {max(abs(r['spread_move_stops']) for r in moved):.2f} stop)")
        text += _describe_skin(report)
        grey = [r['id'] for r in rows if r.get('cast_gain')]
        if grey:
            text += (f"; {len(grey)} clip(s) much greyer than the grade lean further toward its colour "
                     f"({', '.join(grey[:8])})")
        skin = [r for r in rows if r.get('skin')]
        if skin:
            loose = [r['id'] for r in skin if not r['skin']['held']]
            rise = float(np.median([r['skin']['saturation_p90'][1] - r['skin']['saturation_p90'][0] for r in skin]))
            text += (f"; skin-tone colour measured on {len(skin)} clip(s): "
                     + (f"held on all (colour strength p90 {rise:+.2f} median)" if not loose else
                        f"held on {len(skin) - len(loose)}, still stronger on {', '.join(loose[:8])} with full "
                        "protection"))
    if report['skipped']:
        text += '; not graded: ' + '; '.join(report['skipped'][:8])
    for note in report.get('notes') or []:
        text += '; ' + note
    return text
