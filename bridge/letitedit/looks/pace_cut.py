"""A Look's shot lengths cut into a timeline by code: each clip of a stretch of the main picture track takes a length
from the reference's shots at the same place in its body, so the cut carries the reference's pattern (its quick runs,
its held shots, its slowing) rather than one even beat, as a pattern and not a template: within each section of the
stretch (SECTIONS by count) the reference's lengths for that section come in a new order, so each section keeps the
reference's mix of lengths, its spread and its pace, while the cuts don't fall on the reference's own cut times (a
cut whose cuts land on its reference's reads as a remake of it). The order is seeded by the stretch's clips (the same
timeline gives the same cut) and, of SEED_TRIES orders, the one with the fewest cuts within ALIGN_S of the
reference's at the same place is kept; a stretch that starts where the cut's body starts keeps the reference's opening
shot first; the reply gives that share (aligned_share; by chance it is about 2 x ALIGN_S
over the median shot length).

{op: fx, pace: true | {from?, to?, keep?, anchor?, beat_s?, lengths?}}
    from, to   timeline seconds of the stretch [the main track's footage clips, after its first clip when that one is
               held longer than the reference's longest body shot (an opening hold)]
    keep       ids of clips left as they are (a title shot, a held reveal)
    anchor     in (each clip keeps its start in the source and ends earlier or later) [in], or middle (keeps the middle
               of what it shows)
    beat_s     a beat in seconds: lengths become whole half-beats (at least one), so the cuts keep to the music's grid
    lengths    explicit lengths in seconds, in order, instead of the Look's (a story plan's section lengths)

The pattern: the reference's body shots (its end hold and its last camera_language.ENDING_SHOTS shots set apart, as
pace.py reads them) from the Look's visual.json camera block. The stretch's place in the cut's body (as a share of its
time) is the place read in the reference's body; its clips take the reference's shots from there on, one each, going on
past the place's end (and from the body's start again) when the stretch has more clips than that part of the reference,
each section's lengths then put in a new order as above. Explicit lengths are kept in the order given.
A clip can't run past the end of its file (or before its start): it keeps the longest it has, and is named.
The ending: when the stretch runs to the main track's last footage clip and the lengths are the Look's, its last clips
take the reference's ending in order (its last camera_language.ENDING_SHOTS shots, then its end hold when it has one),
so the cut slows into its close as the reference does rather than ending on the body's beat.

apply(script, spec) -> {'clips', 'before_s', 'after_s', 'lengths', 'short_of_source', 'kept', 'reference_s',
'ending', 'aligned_share'} (the timeline's main track changed in place); describe(result) -> one reply line.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

MIN_LEN = 0.2       # no clip is cut shorter than this
FPS = 25.0
SECTIONS = 4        # the stretch's sections (by count of clips) whose lengths are re-ordered within themselves
ALIGN_S = 0.1       # a cut this close to the reference's cut at the same place reads as copied
SEED_TRIES = 40     # orders tried; the one with the fewest copied cuts is kept


def _to_s(value):
    from letitedit.timeline.edit_sync import to_seconds
    return float(to_seconds(value))


def look_ending(script):
    """The chosen Look's first reference's ending: its last ENDING_SHOTS shot lengths then its end hold (when it has
    one), in order, from its visual.json; [] without."""
    import letitedit.looks.pace as pace
    for shots in _look_rows(script):
        _, ending, hold = pace._picture(shots)
        tail = [round(r['end_s'] - r['start_s'], 3) for r in ending] + ([round(hold, 3)] if hold > 0 else [])
        if tail:
            return tail
    return []


def _look_rows(script):
    """The chosen Look's references' camera shot rows (a list per reference) from its visual.json; [] without."""
    import letitedit.looks.grade as grade
    import letitedit.looks.looks as looks
    look = grade.chosen_look(script)
    if not look:
        return []
    try:
        visual = Path(looks.read(look)['recipe']).with_name('visual.json')
        refs = json.loads(visual.read_text(encoding='utf-8-sig'))['references']
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [((ref or {}).get('camera') or {}).get('shots') or [] for ref in refs or [] if isinstance(ref, dict)]


def look_shots(script):
    """The chosen Look's reference body shot lengths ([[lengths]] per reference) from its visual.json; [] without."""
    import letitedit.looks.pace as pace
    out = []
    for shots in _look_rows(script):
        body = pace.profile_rows(shots)
        lengths = [round(r['end_s'] - r['start_s'], 3) for r in body if r['end_s'] > r['start_s']]
        if len(lengths) >= pace.MIN_SHOTS:
            out.append(lengths)
    return out


def pattern(lengths, start_share, count):
    """count lengths from the reference's body lengths, starting at the shot at start_share (0-1) of its time."""
    if not lengths or count <= 0:
        return []
    total = sum(lengths)
    at, t = 0, 0.
    for k, length in enumerate(lengths):
        if (t + length / 2) / total >= start_share:
            at = k
            break
        t += length
    else:
        at = len(lengths) - 1
    return [lengths[(at + k) % len(lengths)] for k in range(count)]


def _cuts(lengths):
    out, t = [], 0.
    for length in lengths[:-1]:
        t += length
        out.append(t)
    return out


def aligned_share(lengths, reference):
    """The share of the cuts of lengths (from a common start) within ALIGN_S of a cut of reference (from the same
    start)."""
    mine, theirs = _cuts(lengths), _cuts(reference)
    if not mine:
        return 0.
    return sum(1 for c in mine if any(abs(c - r) <= ALIGN_S for r in theirs)) / len(mine)


def reorder(lengths, seed, sections=SECTIONS, tries=SEED_TRIES, opening=False):
    """lengths (the reference's, in its order) put in a new order within each of `sections` runs of them, so each run
    keeps its lengths and the cuts move off the reference's: of `tries` seeded orders the one with the fewest cuts
    within ALIGN_S of the reference's (ties: the first). opening: the first length is the reference's opening shot
    (the stretch starts where its body starts) and stays first, so the cut opens as the reference does. Returns
    (lengths, aligned_share)."""
    if opening and len(lengths) > 1:
        rest, share = reorder(lengths[1:], seed, sections, tries)
        out = [lengths[0]] + rest
        return out, aligned_share(out, lengths)
    n = len(lengths)
    if n < 3:
        return list(lengths), aligned_share(lengths, lengths)
    bounds = [round(n * k / sections) for k in range(sections + 1)]
    best = None
    for k in range(tries):
        rng = random.Random(f'{seed}:{k}')
        out = []
        for a, b in zip(bounds, bounds[1:]):
            part = list(lengths[a:b])
            rng.shuffle(part)
            out += part
        share = aligned_share(out, lengths)
        if best is None or share < best[1] - 1e-9:
            best = (out, share)
    return best


def _source_len(item):
    """The clip's file length in its own seconds, or None when it can't be read."""
    import letitedit.looks.style_import as style_import
    try:
        return float(style_import.probe(item['clip'])['duration'])
    except Exception:  # noqa: BLE001 - unreadable: the clip keeps at most its current out point
        return None


def _snap(length, beat_s):
    half = beat_s / 2
    return max(half, round(length / half) * half)


def apply(script, spec):
    from letitedit.timeline.edit_sync import layout, main_track
    spec = {} if spec is True else dict(spec or {})
    unknown = sorted(set(spec) - {'from', 'to', 'keep', 'anchor', 'beat_s', 'lengths'})
    if unknown:
        raise ValueError(f"fx pace: unknown {', '.join(unknown)}; the settings are from, to, keep, anchor, beat_s, lengths")
    anchor = spec.get('anchor', 'in')
    if anchor not in ('in', 'middle'):
        raise ValueError('fx pace: anchor is in or middle')
    beat_s = spec.get('beat_s')
    if beat_s is not None and (type(beat_s) not in (int, float) or not .2 <= beat_s <= 2):
        raise ValueError('fx pace: beat_s is a beat in seconds (0.2 to 2)')
    keep = set(spec.get('keep') or [])
    track = main_track(script)
    if track is None:
        raise ValueError('fx pace: the timeline has no picture track')
    fps = float((script.get('profile') or {}).get('fps') or FPS)
    placed = [(it, a, b) for it, a, b in layout(track, fps) if 'clip' in it]
    if len(placed) < 2:
        raise ValueError('fx pace: the main picture track needs footage clips')
    refs = None
    if spec.get('lengths') is not None:
        given = spec['lengths']
        if not isinstance(given, list) or not given or not all(type(x) in (int, float) and x > 0 for x in given):
            raise ValueError('fx pace: lengths is a list of seconds')
        reference = [float(x) for x in given]
    else:
        refs = look_shots(script)
        if not refs:
            raise ValueError("fx pace: the project's Look has no measured shots (a learned Look measures them from its "
                             "reference); give lengths instead")
        reference = refs[0]
    body_start, body_end = placed[0][1], placed[-1][2]
    first = placed[0]
    if spec.get('from') is None and len(placed) > 2 and first[2] - first[1] > max(reference) + 1e-6:
        body_start = first[2]      # an opening hold stays as it is
    start = _to_s(spec['from']) if spec.get('from') is not None else body_start
    end = _to_s(spec['to']) if spec.get('to') is not None else body_end
    if end <= start:
        raise ValueError('fx pace: to is after from')
    chosen = [(it, a, b) for it, a, b in placed if a >= start - 1e-3 and (a + b) / 2 < end and it.get('id') not in keep]
    kept = [it.get('id') for it, a, b in placed if a >= start - 1e-3 and (a + b) / 2 < end and it.get('id') in keep]
    if not chosen:
        raise ValueError('fx pace: no footage clips in that stretch')
    span = (body_end - placed[0][1]) or 1.
    share = min(1., max(0., (chosen[0][1] - placed[0][1]) / span))
    ending = []
    if spec.get('lengths') is None and chosen[-1][0] is placed[-1][0]:
        ending = look_ending(script)[-len(chosen):]          # the stretch runs to the end: the reference's ending
    body_count = len(chosen) - len(ending)
    aligned = None
    if spec.get('lengths') is not None:
        targets = reference[:len(chosen)] + [reference[-1]] * max(0, len(chosen) - len(reference))
    else:
        body = pattern(reference, share, body_count)
        seed = hashlib.sha256(json.dumps([it.get('id') for it, _, _ in chosen]).encode()).hexdigest()[:12]
        body, aligned = reorder(body, seed, opening=share <= 1e-6)
        targets = body + ending
    before = sum(b - a for _, a, b in chosen)
    result = {'clips': [], 'short_of_source': [], 'kept': kept}
    for (it, a, b), target in zip(chosen, targets):
        if beat_s:
            target = _snap(target, float(beat_s))
        target = max(MIN_LEN, round(target * fps) / fps)
        speed = float(it.get('speed', 1.0)) or 1.
        src_in, src_out = _to_s(it.get('in', 0)), _to_s(it['out'])
        want = target * speed
        if anchor == 'middle':
            middle = (src_in + src_out) / 2
            new_in, new_out = middle - want / 2, middle + want / 2
        else:
            new_in, new_out = src_in, src_in + want
        if new_out > src_out + 1e-6:       # longer than it is: the file must hold it
            full = _source_len(it)
            limit = full if full is not None else src_out
            if new_out > limit:
                new_out = limit
                new_in = max(0., min(new_in, new_out - want))
                if new_out - new_in < want - 1e-3:
                    result['short_of_source'].append(it.get('id'))
        new_in = max(0., new_in)
        it['in'], it['out'] = round(new_in, 3), round(new_out, 3)
        it.pop('len', None)
        result['clips'].append({'id': it.get('id'), 'before_s': round(b - a, 3),
                                'after_s': round((new_out - new_in) / speed, 3)})
    after = sum(c['after_s'] for c in result['clips'])
    result.update(before_s=round(before, 3), after_s=round(after, 3),
                  lengths=[c['after_s'] for c in result['clips']], reference_s=round(sum(reference), 3),
                  start_share=round(share, 3), ending=ending, **({'beat_s': beat_s} if beat_s else {}),
                  **({'aligned_share': round(aligned, 3)} if aligned is not None else {}))
    return result


def describe(result):
    """One reply line for an applied pace."""
    n = len(result['clips'])
    line = (f"pace: {n} clip{'s' if n != 1 else ''} cut to the Look's shot lengths, "
            f"{result['before_s']:.1f} s -> {result['after_s']:.1f} s")
    if result.get('aligned_share') is not None:
        line += (f" (each section's lengths in a new order: {result['aligned_share']:.0%} of the cuts within "
                 f"{ALIGN_S:g} s of the reference's)")
    if result['short_of_source']:
        line += f"; too short in their files for the length asked: {', '.join(result['short_of_source'])}"
    if result.get('ending'):
        line += (f"; the last {len(result['ending'])} take the reference's ending "
                 f"({', '.join(f'{x:.2f}' for x in result['ending'])} s)")
    if result['kept']:
        line += f"; kept as they were: {', '.join(result['kept'])}"
    if result['after_s'] < result['before_s'] - 1:
        line += (f"; the stretch is {result['before_s'] - result['after_s']:.1f} s shorter: at this pace about "
                 f"{round((result['before_s'] - result['after_s']) / max(.2, result['after_s'] / max(1, n)))} more "
                 "shots fill the time it had")
    return line
