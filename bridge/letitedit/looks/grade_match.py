"""One grade across a cut: a Look's measured colour (grade.json samples) against the colour of a cut's shots.

The grade's samples are frames of the Look's reference; a cut's shots are measured the same way (grade.stats on a few
frames of each shot), so both sides are read by one instrument. Colour strength is HSV saturation p50; the colour lean
is the picture's mean colour minus its luma, read as a point on the Cb/Cr plane (Cr up: warmer, red-orange; Cb up:
bluer); brightness is the median luma. From version 2 the tone and the hue of each brightness band are read too: the
black level (luma p05), the highlights (p95) and the tonal range between them in stops; the lean of the shadows (the
darkest quarter of each picture) and of the highlights (its brightest tenth: in outdoor shots mostly the sky).

reference(grade, shots)       the reference's centre and spread over its samples: the median and the 10th-90th
                              percentiles of colour strength, brightness (in stops) and lean, its tone, each band's
                              lean and range, whether the reference is itself uneven (its colour strength or lean
                              varies widely from shot to shot) and, with its shots ({reference index: [(start, end)]}),
                              how far each band's lean moves from one shot to the next.
shot_rows(video, rows, script) every picture shot of an export (camera_language.measure's rows) with its grade
                              statistics and, with the timeline, the footage clips under it.
check(ref, shots, reach)      (summary, problems): the cut's centre against the reference's (colour strength, lean,
                              brightness, tonal range, the shadows' and highlights' lean), its spread from shot to
                              shot against the reference's, and the shots outside the reference's range by clip id.
                              With the grade's reach (grade.last_reach: what each clip's fit aimed at and reached), a
                              gap the fit itself could not close on those shots' clips is a footage limit
                              (summary['footage_limits'], per shot and measure), not a problem. A clip whose
                              picture grade the face checks took part of the way (the reach's picture_share under 1)
                              is named in summary['held_back'] (how many, at which share, which ids, and the gaps it
                              explains), neither the footage's limit nor a problem; one left under half the grade is
                              an outlier.

The bars (each reference read as a cut against itself must pass): a cut's median colour strength over LEVEL_RATIO times the reference's (or under
its inverse); its median lean over LEAN_OFF away from the reference's on the Cb/Cr plane; its median brightness over
LEVEL_STOPS from the reference's; a spread (the interquartile range from shot to shot) over SPREAD_RATIO times the
reference's own and at least SPREAD_MIN wider. Shots whose colour strength sits OUT_RATIO outside the reference's
5th-95th percentiles, or whose lean is OUT_LEAN further from the reference's centre than its own 95th percentile
sample, are named with any of those, and on their own when they hold over OUT_SHARE of the cut's measured time.
From version 2: the cut's tonal range (log2 of p95 over p05, each with BLACK_FLOOR added) over CONTRAST_STOPS
flatter or harder than the reference's; its shadows' or highlights' median lean over SHADOW_LEAN_OFF or
HIGHLIGHT_LEAN_OFF from the reference's; a band's lean moving from one shot to the next (the 75th percentile of
neighbouring shots' distance) over JUMP_RATIO times the reference's and at least JUMP_MIN more. A shot is also named
when a band's lean sits outside the reference's 2.5th-97.5th percentiles on either axis by that band's BAND_MARGIN, or
its black level over BLACK_OUT stops outside the reference's 5th-95th.
A reference is itself uneven when its colour strength's middle half spans over UNEVEN_SAT (log2: about 3x) or its
lean's middle half sits over UNEVEN_LEAN from its centre: none of the measured single-grade references comes near.
Colour strength under SAT_FLOOR on both sides (black and white against black and white) is a match. A gap is the
footage's limit when the clips under the shots missed their own fit's aim by as much, in the same direction (the
median over the shots, within the bar; per shot, by at least the shot's excess): the fit took them as far as its own
bounds allow, so regrading cannot close it.
Display RGB statistics, not the light or the camera: a scene the reference never showed (night against day) moves the
brightness on purpose; colour strength and lean are what one grade holds.
"""
from __future__ import annotations

import math
import statistics

import numpy as np

FORMAT = 'letitedit-grade-match/2'
LEVEL_RATIO = 1.25          # the cut's median colour strength this many times the reference's (or its inverse)
LEVEL_STOPS = 0.5           # the cut's median brightness this far from the reference's, in stops
SAT_FLOOR = .03             # colour strength under this on both sides reads as a match (black and white)
REACH_MIN = .05             # a clip's fit missing its aim by this much (stops, or log2 of colour strength) is named
LEAN_OFF = 0.008            # the cut's median lean this far from the reference's (Cb/Cr distance)
SPREAD_RATIO = 1.5          # the cut's shot-to-shot spread this many times the reference's ...
SPREAD_MIN = 0.25           # ... and at least this much wider (colour strength in log2 units)
OUT_RATIO = 1.5             # a shot this many times outside the reference's 5th-95th colour strength
OUT_LEAN = 0.02             # a shot's lean this much further from the centre than the reference's 95th percentile
OUT_SHARE = 0.25            # outlying shots over this share of the cut's measured time are a finding of their own
UNEVEN_SAT = 1.6            # a reference whose colour strength spread (p75/p25, log2) is over this ...
UNEVEN_LEAN = 0.05          # ... or whose lean's 75th percentile distance from its centre is over this is itself
                            # uneven: one shared grade would not be its look
BLACK_FLOOR = 0.02          # added to luma before blacks are read in stops (a black at 0 is not infinitely deep)
CONTRAST_STOPS = 0.5        # the cut's tonal range (p05 to p95) this many stops flatter or harder than the reference's
SHADOW_LEAN_OFF = 0.008     # the shadows' median lean this far from the reference's (Cb/Cr distance) ...
HIGHLIGHT_LEAN_OFF = 0.02   # ... and the highlights'
JUMP_RATIO = 1.4            # a band's lean moving between neighbouring shots this many times the reference's ...
JUMP_MIN = 0.01             # ... and at least this much more (75th percentile, Cb/Cr distance)
BAND_MARGIN = {'all': .01, 'shadows': .008, 'highlights': .015}   # a shot's band lean this far outside the reference's
BLACK_OUT = 0.3             # a shot's black level this many stops outside the reference's 5th-95th percentiles
BANDS = ('all', 'shadows', 'highlights')
BAND_WORDS = {'all': 'mid-tones', 'shadows': 'shadows', 'highlights': 'highlights'}
MIN_SHOT_S = 0.4           # shots shorter than this are not measured (too few frames, often a flash)
FRAMES = 3                  # frames per shot, spread over its middle
WIDTH = 240
MIN_SHOTS = 4               # fewer measured shots than this tell nothing


def _lean_point(cast, band='all'):
    """A band's colour lean (an RGB offset from luma) as (Cb, Cr): the whole picture's by default (else its mid-tones')."""
    vec = (cast or {}).get(band) or ((cast or {}).get('mids') if band == 'all' else None)
    if not vec:
        return None
    r, g, b = (float(c) for c in vec)
    y = .2126 * r + .7152 * g + .0722 * b
    return ((b - y) / 1.8556, (r - y) / 1.5748)


def _q(values, p):
    return float(np.percentile(values, p)) if values else None


def _log2(value):
    return math.log2(max(1e-3, float(value)))


def _summary(points):
    """Centre and spread of rows with 'saturation', 'luma' and 'lean' (Cb, Cr)."""
    sat = [p['saturation'] for p in points]
    lum = [p['luma'] for p in points]
    leans = [p['lean'] for p in points if p.get('lean') is not None]
    centre = (float(np.median([l[0] for l in leans])), float(np.median([l[1] for l in leans]))) if leans else None
    distances = [math.dist(l, centre) for l in leans] if centre else []
    log_sat = [_log2(s) for s in sat]
    log_lum = [_log2(v) for v in lum]
    return {'count': len(points),
            'saturation_p50': round(float(np.median(sat)), 4) if sat else None,
            'saturation_p05_p95': [round(_q(sat, 5), 4), round(_q(sat, 95), 4)] if sat else None,
            'saturation_spread': round(_q(log_sat, 75) - _q(log_sat, 25), 3) if sat else None,
            'luma_p50': round(float(np.median(lum)), 4) if lum else None,
            'luma_p10_p90': [round(_q(lum, 10), 4), round(_q(lum, 90), 4)] if lum else None,
            'luma_spread_stops': round(_q(log_lum, 75) - _q(log_lum, 25), 3) if lum else None,
            'lean': [round(c, 4) for c in centre] if centre else None,
            'lean_spread': round(_q(distances, 95), 4) if distances else None,
            'lean_middle': round(_q(distances, 75), 4) if distances else None,
            **_tone(points)}


def _contrast(black, white):
    return math.log2((white + BLACK_FLOOR) / (black + BLACK_FLOOR))


def _tone(points):
    """The tone and each band's lean of rows that carry them: medians, and each band's 2.5th-97.5th range per axis."""
    out = {}
    pairs = [(p['black'], p['white']) for p in points if p.get('black') is not None and p.get('white') is not None]
    if pairs:
        blacks = [b for b, _ in pairs]
        out['black_p50'] = round(float(np.median(blacks)), 4)
        out['black_p05_p95'] = [round(_q(blacks, 5), 4), round(_q(blacks, 95), 4)]
        out['white_p50'] = round(float(np.median([w for _, w in pairs])), 4)
        out['contrast_stops'] = round(float(np.median([_contrast(b, w) for b, w in pairs])), 3)
    bands = {}
    for band in BANDS:
        leans = [p['bands'][band] for p in points if (p.get('bands') or {}).get(band)]
        if len(leans) < 3:
            continue
        bands[band] = {'lean': [round(float(np.median([l[i] for l in leans])), 4) for i in (0, 1)],
                       'range': [[round(_q([l[i] for l in leans], 2.5), 4), round(_q([l[i] for l in leans], 97.5), 4)]
                                 for i in (0, 1)]}
    if bands:
        out['bands'] = bands
    return out


def _row(stats):
    """A row from grade.stats: colour strength, median luma, lean, black level (p05), highlights (p95), band leans."""
    luma = stats['luma']
    return {'saturation': float(stats['saturation']['p50']), 'luma': float(luma['p50']),
            'lean': _lean_point(stats.get('cast')), 'black': luma.get('p05'), 'white': luma.get('p95'),
            'bands': {band: _lean_point(stats.get('cast'), band) for band in BANDS}}


def _jumps(rows, band):
    """Distances between neighbouring rows' band leans (rows without the band are skipped)."""
    leans = [(r.get('bands') or {}).get(band) for r in rows]
    leans = [lean for lean in leans if lean]
    return [math.dist(a, b) for a, b in zip(leans, leans[1:])]


def reference(grade, shots=None):
    """The reference's centre and spread from a letitedit-grade/1 profile, or None with too few samples. With shots
    ({reference index: [(start_s, end_s)]}: the reference's own shots, as the Look's camera measures them) the samples
    are gathered into those shots in order, and each band's movement from one shot to the next is kept (jump_p75)."""
    points, kept = [], []
    for sample in (grade or {}).get('samples') or []:
        if sample.get('role') == 'graphics':
            continue
        try:
            points.append(_row(sample))
            kept.append(sample)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    if len(points) < 3:
        return None
    out = _summary(points)
    if shots:
        grouped = []
        for index in sorted(shots, key=str):
            for start, end in sorted(shots[index]):
                members = [p for p, s in zip(points, kept) if s.get('reference', 0) == index
                           and start <= float(s.get('at_s', -1)) < end]
                bands = {}
                for band in BANDS:
                    leans = [m['bands'][band] for m in members if m['bands'].get(band)]
                    if leans:
                        bands[band] = [float(np.mean([l[i] for l in leans])) for i in (0, 1)]
                if bands:
                    grouped.append({'bands': bands})
        jumps = {band: round(_q(_jumps(grouped, band), 75), 4) for band in BANDS if len(_jumps(grouped, band)) >= 3}
        if jumps:
            out['jump_p75'] = jumps
            out['shots'] = len(grouped)
    out['uneven'] = bool(out['saturation_spread'] > UNEVEN_SAT
                         or (out['lean_middle'] is not None and out['lean_middle'] > UNEVEN_LEAN))
    return out


def uneven(grade):
    """True when the Look's reference is itself uneven from shot to shot (its colour strength or lean varies widely)."""
    ref = reference(grade)
    return bool(ref and ref['uneven'])


def _frames(path, start, end, frames=FRAMES, width=WIDTH):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        out = []
        span = end - start
        for i in range(frames):
            t = start + span * (.25 + .5 * i / max(1, frames - 1))
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


def shot_rows(video, rows, script=None):
    """Each picture shot of an export (rows: camera_language.measure's shots) at least MIN_SHOT_S long, with its
    grade statistics and the footage clips under it. With the timeline, a shot with no footage under it (a drawn
    card, a made scene) is left out; a black or flat frame (no picture to grade) too."""
    import letitedit.looks.camera_language as camera_language
    import letitedit.looks.grade as grade
    out = []
    for row in sorted(rows or [], key=lambda r: r['start_s']):
        start, end = float(row['start_s']), float(row['end_s'])
        if end - start < MIN_SHOT_S:
            continue
        ids = camera_language._items(script, start + .05, end - .05) if script else []
        if script and not ids:
            continue
        stats = grade.stats(_frames(video, start, end))
        if not stats or stats['luma']['p95'] < .03 or stats['luma']['p95'] - stats['luma']['p05'] < .02:
            continue
        out.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'items': ids, 'length_s': round(end - start, 3),
                    **_row(stats)})
    return out


def _clock(seconds):
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def _where(shot):
    return f"{_clock(shot['start_s'])}-{_clock(shot['end_s'])}" + (f" ({', '.join(shot['items'][:3])})"
                                                                   if shot.get('items') else '')


def _lean_words(mine, theirs):
    """How one lean differs from another, in plain words: warmer or cooler (Cr), bluer or yellower (Cb)."""
    words = []
    if abs(mine[1] - theirs[1]) >= .004:
        words.append('warmer (more red-orange)' if mine[1] > theirs[1] else 'cooler (more teal-green)')
    if abs(mine[0] - theirs[0]) >= .004:
        words.append('bluer' if mine[0] > theirs[0] else 'yellower')
    return ' and '.join(words) or 'a little off'


def _shot_reach(shot, reach, held=False):
    """How far the fit of the clip under a shot missed its own aim, per measure (stops; log2 for colour strength;
    positive is brighter, harder or stronger): None without the grade's reach for any of its clips. A clip graded at a
    strength under 1 explains nothing: its gap is the strength chosen, which a full-strength grade would close. Nor
    does a clip whose picture grade the face checks took part of the way (picture_share under 1): with `held`, only
    such clips are read, and the share comes along ('share')."""
    for item in shot.get('items') or []:
        got = (reach or {}).get(item)
        if not got or float(got.get('strength', 1.)) < 1.:
            continue
        share = float(got.get('picture_share', 1.))
        if (share < 1.) != held:
            continue
        out = {}

        def pair(name):
            value = got.get(name) or [None, None]
            return (value[0], value[1]) if None not in value else None
        if pair('median'):
            out['median'] = math.log2((pair('median')[1] + .001) / (pair('median')[0] + .001))
        if pair('blacks'):
            out['blacks'] = math.log2((pair('blacks')[1] + BLACK_FLOOR) / (pair('blacks')[0] + BLACK_FLOOR))
        if pair('blacks') and pair('highlights'):
            out['contrast'] = (_contrast(pair('blacks')[1], pair('highlights')[1])
                               - _contrast(pair('blacks')[0], pair('highlights')[0]))
        if pair('saturation'):
            out['saturation'] = math.log2((pair('saturation')[1] + .01) / (pair('saturation')[0] + .01))
        return {'item': item, **{k: round(v, 3) for k, v in out.items()}, **({'share': share} if held else {})}
    return None


HELD_NOTE = ("the room held back to keep faces clean: the face checks took the picture grade part of the way on these "
             "clips (a LUT can't hold a face far from a room of the same brightness without blotches); neither the "
             "footage's limit nor a fault to fix by regrading")


def _limit(shots, rows, measure, gap, bar, words, held=False):
    """A cut-level gap the clips' own fits missed by as much, in the same direction: a footage-limit entry (with
    `held`, the rows of the clips whose room was held back, and an entry saying so), else None."""
    residuals = [(row or {}).get(measure, 0.) for row in rows]
    explained = float(np.median(residuals)) if residuals else 0.
    if gap * explained <= 0 or abs(gap) - abs(explained) > bar or abs(explained) < REACH_MIN:
        return None, explained
    named = [{'at_s': round(shot['start_s'], 2), 'clip': row['item'], 'missed': row[measure]}
             for shot, row in zip(shots, rows) if row and abs(row.get(measure, 0.)) >= REACH_MIN]
    return {'measure': measure, 'gap': round(gap, 3), 'explained': round(explained, 3), 'shots': named[:12],
            'note': (f"{words}: the fits of the clips under these shots missed their own aim by as much (median "
                     f"{explained:+.2f}), " + (HELD_NOTE if held else "as far as the grade's bounds take them; the "
                                               "footage's limit, not a fault to fix by regrading"))}, explained


def check(ref, shots, reach=None):
    """(summary, problems): the cut's shots (shot_rows) against the reference (reference(grade)). reach (the grade's
    reach, grade.last_reach: {clip id: {measure: [aimed, reached]}}): a gap the clips' own fits missed by as much is
    named in summary['footage_limits'], per shot and measure, not as a problem."""
    if not ref or len(shots or []) < MIN_SHOTS:
        return ({'not_measured': f'{len(shots or [])} picture shots of footage measured (at least {MIN_SHOTS} needed)'}
                if ref else None), []
    cut = _summary(shots)
    summary = {'format': FORMAT, 'reference': ref, 'cut': cut, 'outliers': []}
    problems = []
    reached = [_shot_reach(shot, reach) for shot in shots]
    holding = [_shot_reach(shot, reach, held=True) for shot in shots]
    limits, held_back = [], []

    def missed(measure, gap, bar, words, problem):
        entry, explained = _limit(shots, reached, measure, gap, bar, words)
        kept, _ = (None, 0.) if entry else _limit(shots, holding, measure, gap, bar, words, held=True)
        if entry:
            limits.append(entry)
        elif kept:
            held_back.append(kept)
        else:
            problems.append(problem + (f"; the clips' own fits missed their aim by {explained:+.2f} of it"
                                       if abs(explained) >= REACH_MIN else ''))
    grey = cut['saturation_p50'] < SAT_FLOOR and ref['saturation_p50'] < SAT_FLOOR
    ratio = 1. if grey else cut['saturation_p50'] / max(1e-3, ref['saturation_p50'])
    summary['saturation_ratio'] = round(ratio, 3)
    if ratio > LEVEL_RATIO or ratio < 1 / LEVEL_RATIO:
        missed('saturation', math.log2(max(1e-3, ratio)), math.log2(LEVEL_RATIO), "the cut's colour strength",
               f"the cut's colour strength (saturation p50, median over its {cut['count']} shots) is "
               f"{cut['saturation_p50']:.2f}, {ratio:.2f}x the reference's {ref['saturation_p50']:.2f}")
    stops = _log2(cut['luma_p50']) - _log2(ref['luma_p50'])
    summary['brightness_stops'] = round(stops, 3)
    if abs(stops) > LEVEL_STOPS:
        missed('median', stops, LEVEL_STOPS, "the cut's brightness",
               f"the cut is {abs(stops):.1f} stops {'brighter' if stops > 0 else 'darker'} than the "
               f"reference (median luma {cut['luma_p50']:.2f} against {ref['luma_p50']:.2f})")
    if cut['lean'] and ref['lean']:
        off = math.dist(cut['lean'], ref['lean'])
        summary['lean_off'] = round(off, 4)
        if off > LEAN_OFF:
            problems.append(f"the cut's colour leans {_lean_words(cut['lean'], ref['lean'])} than the reference's "
                            f"(mean Cb/Cr {cut['lean'][0]:+.3f}, {cut['lean'][1]:+.3f} against "
                            f"{ref['lean'][0]:+.3f}, {ref['lean'][1]:+.3f}; {off:.3f} apart)")
    if ref.get('contrast_stops') is not None and cut.get('contrast_stops') is not None:
        harder = cut['contrast_stops'] - ref['contrast_stops']
        summary['contrast_stops'] = round(harder, 3)
        if abs(harder) > CONTRAST_STOPS:
            missed('contrast', harder, CONTRAST_STOPS, "the cut's tonal range", f"the cut's tonal range is {abs(harder):.1f} stops {'harder' if harder > 0 else 'flatter'} "
                            f"than the reference's: its blacks sit at {cut['black_p50']:.3f} against "
                            f"{ref['black_p50']:.3f} (luma p05) and its highlights at {cut['white_p50']:.2f} against "
                            f"{ref['white_p50']:.2f} (p95), medians over the shots")
    for band, bar in (('shadows', SHADOW_LEAN_OFF), ('highlights', HIGHLIGHT_LEAN_OFF)):
        mine, theirs = (cut.get('bands') or {}).get(band), (ref.get('bands') or {}).get(band)
        if mine and theirs:
            off = math.dist(mine['lean'], theirs['lean'])
            summary[f'{band}_lean_off'] = round(off, 4)
            if off > bar:
                problems.append(f"the cut's {band} lean {_lean_words(mine['lean'], theirs['lean'])} than the "
                                f"reference's (Cb/Cr {mine['lean'][0]:+.3f}, {mine['lean'][1]:+.3f} against "
                                f"{theirs['lean'][0]:+.3f}, {theirs['lean'][1]:+.3f}; {off:.3f} apart)")
    for band, theirs in (ref.get('jump_p75') or {}).items():
        jumps = _jumps(shots, band)
        if len(jumps) < 3:
            continue
        mine = _q(jumps, 75)
        summary.setdefault('jump_p75', {})[band] = round(mine, 4)
        if mine > JUMP_RATIO * theirs and mine - theirs > JUMP_MIN:
            leans = [(s, (s.get('bands') or {}).get(band)) for s in shots if (s.get('bands') or {}).get(band)]
            steps = sorted(((math.dist(a[1], b[1]), b[0]) for a, b in zip(leans, leans[1:])), key=lambda x: -x[0])
            problems.append(f"the {BAND_WORDS[band]}' colour changes from one shot to the next "
                            f"{mine / max(1e-4, theirs):.1f}x as much as the reference's (75th percentile between "
                            f"neighbouring shots {mine:.3f} against {theirs:.3f}); the biggest changes into "
                            + '; '.join(_where(s) for _, s in steps[:5]))
    if not ref.get('uneven'):
        wider = cut['saturation_spread'] - ref['saturation_spread']
        if cut['saturation_spread'] > SPREAD_RATIO * ref['saturation_spread'] and wider > SPREAD_MIN:
            problems.append(f"the cut's colour strength varies from shot to shot "
                            f"{cut['saturation_spread'] / max(1e-3, ref['saturation_spread']):.1f}x as much as the "
                            f"reference's (interquartile range {cut['saturation_spread']:.2f} against "
                            f"{ref['saturation_spread']:.2f}, in log2): the reference holds one grade")
    low, high = ref['saturation_p05_p95']
    lean_reach = (ref.get('lean_spread') or 0) + OUT_LEAN
    for shot, got, holds in zip(shots, reached, holding):
        why, kept, holding_kept = [], [], []
        if holds and holds['share'] < .5:
            why.append(f"left without most of the Look's grade (the picture grade at {holds['share']:g} of the way, "
                       "to keep faces clean)")

        def name(text, measure, excess):
            # a shot's excess the fit of its clip missed by at least as much, the same way, is the footage's limit; on a
            # clip whose room the face checks held back (at half the grade or more) it is that, named on its own
            residual = (got or {}).get(measure, 0.)
            held = (holds or {}).get(measure, 0.) if holds and holds['share'] >= .5 else 0.
            if residual * excess > 0 and abs(residual) >= abs(excess):
                kept.append(text)
            elif held * excess > 0 and abs(held) >= abs(excess):
                holding_kept.append(text)
            else:
                why.append(text)
        coloured = max(shot['saturation'], high) >= SAT_FLOOR
        if coloured and shot['saturation'] > high * OUT_RATIO:
            name(f"{shot['saturation'] / max(1e-3, ref['saturation_p50']):.1f}x the reference's colour strength",
                 'saturation', math.log2((shot['saturation'] + .01) / (high * OUT_RATIO + .01)))
        elif coloured and shot['saturation'] < low / OUT_RATIO:
            name(f"{shot['saturation'] / max(1e-3, ref['saturation_p50']):.1f}x the reference's colour "
                 "strength (greyer)", 'saturation', math.log2((shot['saturation'] + .01) / (low / OUT_RATIO + .01)))
        if shot.get('lean') and ref['lean'] and math.dist(shot['lean'], ref['lean']) > lean_reach:
            why.append(f"leans {_lean_words(shot['lean'], ref['lean'])}")
        for band in BANDS:
            lean, theirs = (shot.get('bands') or {}).get(band), (ref.get('bands') or {}).get(band)
            if not lean or not theirs or (band == 'all' and any(w.startswith('leans') for w in why)):
                continue
            words = []
            for axis, (more, less) in ((0, ('bluer', 'yellower')), (1, ('warmer', 'greener'))):
                least, most = theirs['range'][axis]
                if lean[axis] > most + BAND_MARGIN[band]:
                    words.append(more)
                elif lean[axis] < least - BAND_MARGIN[band]:
                    words.append(less)
            if words:
                why.append(f"its {BAND_WORDS[band]} lean {' and '.join(words)} than any of the reference's")
        if shot.get('black') is not None and ref.get('black_p05_p95'):
            deep, light = ref['black_p05_p95']
            lifted = math.log2((shot['black'] + BLACK_FLOOR) / (light + BLACK_FLOOR))
            crushed = math.log2((deep + BLACK_FLOOR) / (shot['black'] + BLACK_FLOOR))
            if lifted > BLACK_OUT:
                name(f"its blacks lifted ({shot['black']:.3f} against the reference's {deep:.3f}-{light:.3f})",
                     'blacks', lifted - BLACK_OUT)
            elif crushed > BLACK_OUT:
                name(f"its blacks crushed ({shot['black']:.3f} against the reference's {deep:.3f}-{light:.3f})",
                     'blacks', -(crushed - BLACK_OUT))
        if holding_kept:
            held_back.append({'measure': 'shot', 'shots': [{'at_s': round(shot['start_s'], 2), 'clip': holds['item'],
                                                            'share': holds['share'],
                                                            'missed': {k: v for k, v in holds.items()
                                                                       if k not in ('item', 'share')}}],
                              'note': f"{_where(shot)} {', '.join(holding_kept)}: {HELD_NOTE}"})
        if kept:
            limits.append({'measure': 'shot', 'shots': [{'at_s': round(shot['start_s'], 2), 'clip': got['item'],
                                                         'missed': {k: v for k, v in got.items() if k != 'item'}}],
                           'note': (f"{_where(shot)} {', '.join(kept)}: the fit of its clip missed its own aim by as "
                                    "much; the footage's limit, not a fault to fix by regrading")})
        if why:
            summary['outliers'].append({**shot, 'why': why})
    named = summary['outliers']
    total = sum(s.get('length_s') or (s['end_s'] - s['start_s']) for s in shots) or 1.
    share = sum(s.get('length_s') or (s['end_s'] - s['start_s']) for s in named) / total
    summary['outlier_share'] = round(share, 3)
    if named and (problems or share > OUT_SHARE):
        problems.append(f"{len(named)} of {cut['count']} shots ({share:.0%} of their time) sit furthest outside the "
                        "reference's range: "
                        + '; '.join(f"{_where(s)} {', '.join(s['why'])}" for s in named[:8])
                        + (f'; and {len(named) - 8} more' if len(named) > 8 else ''))
    if limits:
        summary['footage_limits'] = limits
    shares = {}
    for row in holding:
        if row:
            shares[row['item']] = row['share']
    if shares:
        counts = {}
        for share in shares.values():
            counts[share] = counts.get(share, 0) + 1
        ids = sorted(shares)
        summary['held_back'] = {
            'clips': len(shares), 'shares': {f'{k:g}': v for k, v in sorted(counts.items(), reverse=True)},
            'ids': ids,
            'note': (f"the room held back to keep faces clean on {len(shares)} clip(s) under these shots (the picture "
                     "grade at " + ', '.join(f"{k:g} of the way on {v}" for k, v in sorted(counts.items(), reverse=True))
                     + f": {', '.join(ids[:8])}" + (f' and {len(ids) - 8} more' if len(ids) > 8 else '')
                     + "); a gap that explains is named here, neither the footage's limit nor a fault to fix by "
                     "regrading"),
            **({'explains': held_back} if held_back else {})}
    summary['problems'] = len(problems)
    return summary, problems
