"""A Look's pace section by section: how long its shots are over each stretch of the reference, and of a cut.

The same shot rows the camera language uses (camera_language.measure on an export; a Look's visual.json camera shots
for its reference), so both sides are read by one instrument. Sections: the body (every picture shot before the
ending, the opening included) is read over overlapping stretches of camera_language.window_seconds (eight median
shots, 8-30 s); the ending is the last camera_language.ENDING_SHOTS picture shots; an end hold (black, a held card)
is set apart as camera_language.ending does.

profile(rows)              the pace of one video: its median shot, and over each stretch of the body its shots,
                           median, range and evenness (the spread of the lengths over their mean: 0 when every shot
                           is as long); the slowest stretch's median, the least even stretch's evenness and the
                           ending's median; the spread of its stretch medians (their 25th and 75th percentiles) and
                           its cuts a minute.
targets(references)        each section's shot-length target from the references: the band of their stretch medians,
                           the overall median shot and cuts a minute (what a story plan's sections are built to).
check(references, rows)    the stretches of a cut slower than the reference's stretches, those more even than any of
                           them, the whole cut's cuts a minute against the reference's, and an ending slower than the
                           reference's: (summary, problems), each problem naming the stretch, its shots and (with the
                           timeline) its clips.

The bar, stretch by stretch: a stretch led by the picture (speech under less than SPEECH_LED of it) is slow when its
median is over TOLERANCE_BAND above the 75th percentile of the reference's stretch medians (the reference's own spread
of pace through its body, not only its slowest stretch); a stretch led by speech keeps the speech's own rate and is slow
only over TOLERANCE_SLOW above the reference's slowest stretch outside its ending (a cut on another song's beat grid
lands its shots up to about a quarter off: two beats are 0.96 s at 125 BPM and 1.2 s at 100). A cut may spend as much of its body in picture-led stretches over that bar as the reference spends in its own, and
SLOW_SHARE more; past that, each of them is named. A stretch is even when
it holds MIN_EVEN_SHOTS shots or more at the reference's median or slower and its evenness is under EVEN_FRACTION of
the reference's most even stretch (eight shots of one length read as a metronome against a reference that varies; a
rush of shorter shots is left to the opening's own device). A cut led by the picture (speech under less than
SPEECH_LED of it) has its body's cuts a minute within TOLERANCE_RATE of the reference's, and spends at most LONG_SHARE
more of its body's time than the reference in shots longer than the reference's LONG_PERCENTILE shot (long holds).
"""
from __future__ import annotations

import statistics

FORMAT = 'letitedit-pace/1'
TOLERANCE_SLOW = 0.25        # a speech-led stretch's median this share over the reference's slowest body stretch is slow
TOLERANCE_BAND = 0.15        # a picture-led stretch's median this share over the reference's 75th percentile is slow
TOLERANCE_RATE = 0.15        # a picture-led cut's body cuts a minute this share under (or over) the reference's
SPEECH_LED = 0.5             # speech under this share of a stretch (or of the cut): the picture leads it
LONG_PERCENTILE = 90         # a picture-led cut's shots longer than the reference's shot at this percentile ...
LONG_SHARE = 0.15            # ... may hold this much more of its body's time than the reference's do
SLOW_SHARE = 0.1             # a cut's body may spend this much more of its time over the band's bar than the reference's
MIN_SHOTS = 3                # a stretch is judged for pace with at least this many shots in it
MIN_EVEN_SHOTS = 6           # ... and for evenness with at least this many
EVEN_FRACTION = 0.5          # a stretch more even than this share of the reference's most even stretch is even


def _clock(seconds):
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def _picture(rows):
    """(body rows, ending rows, hold seconds): the end hold set apart, then the last ENDING_SHOTS picture shots."""
    import letitedit.looks.camera_language as camera_language
    rows = sorted((row for row in rows or [] if row['end_s'] > row['start_s']), key=lambda row: row['start_s'])
    hold = 0.0
    if len(rows) > 1 and rows[-1].get('move') in ('static', 'unknown', None) and not rows[-1].get('plain'):
        hold, rows = rows[-1]['end_s'] - rows[-1]['start_s'], rows[:-1]
    count = camera_language.ENDING_SHOTS
    if len(rows) <= count + MIN_SHOTS:
        return rows, [], hold
    return rows[:-count], rows[-count:], hold


def _lengths(rows):
    return [row['end_s'] - row['start_s'] for row in rows]


def _pct(values, p):
    """The p-th percentile (0-100) of values, linear between them."""
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    at = (len(values) - 1) * p / 100
    low = int(at)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (at - low)


def speech_spans(script):
    """(start, end) of every spoken word on the timeline, from cached words only: [] when every audible clip is
    transcribed and none speaks (or nothing on the timeline has sound); None when an audible clip isn't transcribed yet,
    or the words can't be read (whether speech or the picture leads isn't known then)."""
    if not script:
        return []
    try:
        from letitedit.timeline.timeline_speech import timeline_words
        missing = []
        words = timeline_words(script, cached_only=True, missing=missing)
        if missing:
            return None
        return [(float(w['t0']), float(w['t1'])) for w in words
                if w.get('t1') is not None and w.get('t0') is not None and w['t1'] > w['t0']]
    except Exception:  # noqa: BLE001 - words unreadable: pace's picture-led checks are left out
        return None


def _speech_share(spans, start, end):
    """The share of start-end with a word spoken in it (overlapping words counted once)."""
    if end <= start or not spans:
        return 0.0
    covered, cursor = 0.0, start
    for a, b in sorted(spans):
        a, b = max(a, cursor), min(b, end)
        if b > a:
            covered += b - a
            cursor = b
    return covered / (end - start)


def profile_rows(rows):
    """The body rows of a video's shots (its end hold and ending set apart)."""
    body, _, _ = _picture(rows)
    return body


def _share_over(body, bar, found=None, picture_only=False):
    """The share of the body's time in stretches whose median is over bar (overlapping stretches counted once);
    picture_only: only stretches led by the picture (speech under SPEECH_LED)."""
    import letitedit.looks.camera_language as camera_language
    if not body or bar is None:
        return 0.0
    if found is None:
        found = stretches(body, camera_language.window_seconds(body))
    spans = sorted((s['start_s'], s['end_s']) for s in found if s['shots'] >= 1 and s['median_s'] > bar
                   and not (picture_only and s.get('speech', 0) >= SPEECH_LED))
    covered, cursor = 0.0, None
    for a, b in spans:
        a = a if cursor is None else max(a, cursor)
        if b > a:
            covered += b - a
            cursor = b
    total = body[-1]['end_s'] - body[0]['start_s']
    return covered / total if total > 0 else 0.0


def _long_holds(references, body, script, summary):
    """A picture-led cut's long holds: the share of its body's time in shots longer than the reference's LONG_PERCENTILE
    shot, against the reference's own share; the problem naming the longest of them, or None."""
    bodies = [profile_rows(ref.get('shots')) for ref in references or [] if ref and ref.get('shots')]
    lengths = [x for rows in bodies for x in _lengths(rows)]
    if len(lengths) < MIN_SHOTS or not body:
        return None
    bar = _pct(lengths, LONG_PERCENTILE)

    def share(rows):
        total = sum(_lengths(rows))
        return sum(x for x in _lengths(rows) if x > bar) / total if total else 0.0
    theirs = max(share(rows) for rows in bodies if rows)
    mine = share(body)
    summary['long_holds'] = {'over_s': round(bar, 3), 'reference_share': round(theirs, 3), 'cut_share': round(mine, 3)}
    if mine <= theirs + LONG_SHARE:
        return None
    longest = sorted((row for row in body if row['end_s'] - row['start_s'] > bar),
                     key=lambda row: row['start_s'] - row['end_s'])[:8]
    named = []
    for row in sorted(longest, key=lambda r: r['start_s']):
        ids = _items(script, row['start_s'], row['end_s'])
        named.append(f"{_clock(row['start_s'])} {row['end_s'] - row['start_s']:.2f} s"
                     + (f" ({', '.join(ids[:3])})" if ids else ''))
    summary['stretches'].append({'kind': 'long_holds', 'over_s': round(bar, 3), 'shots': [
        {'start_s': round(r['start_s'], 3), 'end_s': round(r['end_s'], 3)} for r in longest]})
    return (f"{mine:.0%} of the body's time is in shots longer than {bar:.2f} s (the reference's "
            f"{LONG_PERCENTILE}th percentile shot), against the reference's {theirs:.0%}: the longest at "
            + '; '.join(named))


def targets(references):
    """Each section's shot-length target from the references' visual.json camera blocks: {'median_s' (the shot),
    'stretch_band_s' [25th, 75th percentile of their stretch medians], 'slowest_stretch_s', 'cuts_per_minute',
    'stretch_s', 'ending_median_s'}; None without measured shots."""
    refs = [profile(ref.get('shots')) for ref in references or [] if ref and ref.get('shots')]
    refs = [ref for ref in refs if ref]
    if not refs:
        return None
    low = [ref['stretch_median_p25'] for ref in refs if ref['stretch_median_p25'] is not None]
    high = [ref['stretch_median_p75'] for ref in refs if ref['stretch_median_p75'] is not None]
    rates = [ref['cuts_per_minute'] for ref in refs if ref['cuts_per_minute']]
    endings = [ref['ending_median_s'] for ref in refs if ref['ending_median_s'] is not None]
    return {'median_s': round(statistics.median(ref['median_s'] for ref in refs), 3),
            'stretch_band_s': [round(min(low), 3), round(max(high), 3)] if low and high else None,
            'slowest_stretch_s': max((ref['stretch_median_max'] for ref in refs
                                      if ref['stretch_median_max'] is not None), default=None),
            'cuts_per_minute': round(statistics.median(rates), 2) if rates else None,
            'stretch_s': max(ref['stretch_s'] for ref in refs),
            'ending_median_s': max(endings) if endings else None}


def _evenness(lengths):
    mean = statistics.mean(lengths) if lengths else 0
    return statistics.pstdev(lengths) / mean if len(lengths) > 1 and mean else None


def _in(rows, start, end):
    """The shots of a stretch: those whose middle is inside it."""
    return [row for row in rows if start - 1e-6 <= (row['start_s'] + row['end_s']) / 2 < end + 1e-6]


def stretches(rows, seconds):
    """Each overlapping stretch of the rows with its shots' median, range and evenness."""
    import letitedit.looks.camera_language as camera_language
    out = []
    for start, end in camera_language.windows(rows, seconds):
        shots = _in(rows, start, end)
        if len(shots) < MIN_SHOTS:
            # fewer shots than that in a stretch of eight median shots: they are long, and they are its pace
            shots = [row for row in rows if row['start_s'] < end and row['end_s'] > start]
        lengths = _lengths(shots)
        if not lengths:
            continue
        out.append({'start_s': start, 'end_s': end, 'shots': len(lengths),
                    'median_s': round(statistics.median(lengths), 3),
                    'range_s': [round(min(lengths), 3), round(max(lengths), 3)],
                    'evenness': round(_evenness(lengths), 3) if _evenness(lengths) is not None else None,
                    'rows': shots})
    return out


def profile(rows):
    """The pace of one video from its shot rows."""
    import letitedit.looks.camera_language as camera_language
    body, ending, hold = _picture(rows)
    if len(body) < MIN_SHOTS:
        return None
    seconds = camera_language.window_seconds(body)
    found = stretches(body, seconds)
    timed = [s for s in found if s['shots'] >= MIN_SHOTS]
    even = [s['evenness'] for s in found if s['shots'] >= MIN_EVEN_SHOTS and s['evenness'] is not None]
    lengths = _lengths(body + ending)
    medians = [s['median_s'] for s in timed]
    span = body[-1]['end_s'] - body[0]['start_s']
    return {'format': FORMAT, 'shots': len(lengths), 'median_s': round(statistics.median(lengths), 3),
            'stretch_s': seconds, 'end_hold_s': round(hold, 3),
            'cuts_per_minute': round(len(body) * 60 / span, 2) if span > 0 else None,
            'stretch_median_p25': round(_pct(medians, 25), 3) if medians else None,
            'stretch_median_p75': round(_pct(medians, 75), 3) if medians else None,
            'stretch_median_max': round(max(s['median_s'] for s in timed), 3) if timed else None,
            'stretch_evenness_min': round(min(even), 3) if even else None,
            'ending_median_s': round(statistics.median(_lengths(ending)), 3) if ending else None,
            'ending_shots': [round(x, 3) for x in _lengths(ending)],
            'stretches': [{k: v for k, v in s.items() if k != 'rows'} for s in found]}


def _merge(flagged):
    """Overlapping flagged stretches joined, each as its shots (in time order, no repeats)."""
    out = []
    for stretch in sorted(flagged, key=lambda s: s['start_s']):
        if out and stretch['start_s'] <= out[-1]['end_s'] + 1e-6:
            last = out[-1]
            last['end_s'] = max(last['end_s'], stretch['end_s'])
            seen = {id(row) for row in last['rows']}
            last['rows'] += [row for row in stretch['rows'] if id(row) not in seen]
        else:
            out.append({'start_s': stretch['start_s'], 'end_s': stretch['end_s'], 'rows': list(stretch['rows'])})
    for stretch in out:
        stretch['rows'].sort(key=lambda row: row['start_s'])
    return out


def _lengths_words(lengths):
    lengths = [round(x, 2) for x in lengths]
    if len(set(lengths)) == 1:
        return f"{len(lengths)} shots of {lengths[0]:.2f} s"
    return (f"{len(lengths)} shots, median {statistics.median(lengths):.2f} s ({min(lengths):.2f}-{max(lengths):.2f} s"
            + (f", evenness {_evenness(lengths):.2f}" if _evenness(lengths) is not None else '') + ')')


def _items(script, start, end):
    """The footage clips under a stretch, leaving out those that only touch its edges (a frame of rounding)."""
    import letitedit.looks.camera_language as camera_language
    return camera_language._items(script, start + 0.05, end - 0.05)


def check(references, measured, script=None, speech=None):
    """The cut's pace (measured: camera_language.measure's result on its export) against its references' (each a
    visual.json 'camera' block with shots). speech: (start, end) spans of the cut's spoken words (default: the
    timeline's cached words). Returns (summary, problems)."""
    refs = [profile(ref.get('shots')) for ref in references or [] if ref and ref.get('shots')]
    refs = [ref for ref in refs if ref]
    cut_rows = measured.get('shots') or []
    cut = profile(cut_rows)
    if not refs or not cut:
        return None, []
    body, ending, _ = _picture(cut_rows)
    ceiling = max((ref['stretch_median_max'] for ref in refs if ref['stretch_median_max'] is not None), default=None)
    band = targets(references)['stretch_band_s']
    evens = [ref['stretch_evenness_min'] for ref in refs if ref['stretch_evenness_min'] is not None]
    floor = min(evens) if evens else None
    overall = statistics.median([ref['median_s'] for ref in refs])
    seconds = max(ref['stretch_s'] for ref in refs)
    spans = speech_spans(script) if speech is None else list(speech)
    # an audible clip not transcribed yet: whether speech or the picture leads isn't known, so the picture-led checks
    # (the reference's band, long holds, the cutting rate) are left out and the summary says so. Every audible clip
    # transcribed and none speaking is no speech, and the picture leads
    unknown = spans is None
    spans = spans or []
    total = (body[-1]['end_s'] - body[0]['start_s']) if body else 0
    cut_speech = _speech_share(spans, body[0]['start_s'], body[-1]['end_s']) if body else 0.0
    summary = {'reference': [{k: v for k, v in ref.items() if k != 'stretches'} for ref in refs],
               'cut': {k: v for k, v in cut.items() if k != 'stretches'}, 'stretch_s': seconds,
               'slow_over_s': round(ceiling * (1 + TOLERANCE_SLOW), 3) if ceiling else None,
               'picture_led_slow_over_s': round(band[1] * (1 + TOLERANCE_BAND), 3) if band else None,
               'speech_share': None if unknown else round(cut_speech, 3),
               **({'speech': 'not measured (a clip with sound on the timeline is not transcribed yet): the '
                             'picture-led pace checks are left out'} if unknown else {}),
               'even_under': round(floor * EVEN_FRACTION, 3) if floor else None, 'stretches': []}
    found = stretches(body, seconds)
    for stretch in found:
        stretch['speech'] = _speech_share(spans, stretch['start_s'], stretch['end_s'])
    problems = []

    old_bar = ceiling * (1 + TOLERANCE_SLOW) if ceiling else None
    band_bar = min(band[1] * (1 + TOLERANCE_BAND), old_bar) if band and old_bar else None
    # a cut may spend as much of its body over the band's bar as its reference does (its own slower stretches), and
    # SLOW_SHARE more: past that, its picture-led stretches over the bar are slow
    ref_share = max((_share_over(profile_rows(ref.get('shots')), band_bar) for ref in references or []
                     if ref and ref.get('shots')), default=0.0) if band_bar else 0.0
    cut_share = _share_over(body, band_bar, found, picture_only=True) if band_bar else 0.0
    summary.update(band_share={'reference': round(ref_share, 3), 'cut': round(cut_share, 3)})
    use_band = band_bar is not None and cut_share > ref_share + SLOW_SHARE and not unknown

    def limit_of(stretch):
        # a stretch led by speech keeps the speech's own rate; one led by the picture is held to the reference's
        # spread of pace through its body
        if stretch.get('speech', 0) >= SPEECH_LED or not use_band:
            return old_bar
        return band_bar
    if ceiling:
        slow = [s for s in found if s['shots'] >= 1 and limit_of(s) is not None and s['median_s'] > limit_of(s)]
        for stretch in _merge(slow):
            # the stretch as the shots that make it slow: from the first shot over the limit to the last
            limit = min(limit_of(s) for s in slow if s['start_s'] >= stretch['start_s'] - 1e-6
                        and s['end_s'] <= stretch['end_s'] + 1e-6)
            over = [row for row in stretch['rows'] if row['end_s'] - row['start_s'] > limit]
            if not over:
                continue
            shots = [row for row in stretch['rows'] if over[0]['start_s'] <= row['start_s'] <= over[-1]['start_s']]
            start, end = shots[0]['start_s'], shots[-1]['end_s']
            lengths = _lengths(shots)
            ids = _items(script, start, end)
            wanted = max(len(shots) + 1, round((end - start) / overall)) if overall else None
            summary['stretches'].append({'kind': 'slow', 'start_s': round(start, 3), 'end_s': round(end, 3),
                                         'shots': len(shots), 'median_s': round(statistics.median(lengths), 3),
                                         'lengths_s': [round(x, 3) for x in lengths], 'items': ids,
                                         'shots_at_reference_pace': wanted})
            picture_led = band and limit < ceiling * (1 + TOLERANCE_SLOW) - 1e-9
            problems.append(
                f"{_clock(start)}-{_clock(end)}: {_lengths_words(lengths)}, against the reference's median of "
                + (f"{overall:.2f} s and its stretches' medians of {band[0]:.2f}-{band[1]:.2f} s over {seconds:g} s "
                   "through its body (the picture leads this stretch)" if picture_led else
                   f"{overall:.2f} s and at most {ceiling:.2f} s over any {seconds:g} s before its ending")
                + (f" ({', '.join(ids[:10])})" if ids else '')
                + (f": at the reference's pace these {end - start:.1f} s hold about {wanted} shots of uneven "
                   "lengths, or the stretch is shorter" if wanted else ''))
    if floor:
        limit = floor * EVEN_FRACTION
        # a rush of very short shots faster than the reference's median is its own device; evenness is judged where
        # the cut runs at the reference's pace or slower
        even = [s for s in found if s['shots'] >= MIN_EVEN_SHOTS and s['evenness'] is not None
                and s['evenness'] < limit and s['median_s'] >= overall]
        for stretch in _merge(even):
            shots = stretch['rows']
            start, end = shots[0]['start_s'], shots[-1]['end_s']
            lengths = _lengths(shots)
            ids = _items(script, start, end)
            summary['stretches'].append({'kind': 'even', 'start_s': round(start, 3), 'end_s': round(end, 3),
                                         'shots': len(shots), 'evenness': round(_evenness(lengths), 3),
                                         'lengths_s': [round(x, 3) for x in lengths], 'items': ids})
            problems.append(
                f"{_clock(start)}-{_clock(end)}: {_lengths_words(lengths)}, more even than any {seconds:g} s of the "
                f"reference (its most even stretch {floor:.2f}): vary the lengths as the reference does"
                + (f" ({', '.join(ids[:10])})" if ids else ''))
    if cut_speech < SPEECH_LED and not unknown:
        long_problem = _long_holds(references, body, script, summary)
        if long_problem:
            problems.append(long_problem)
    rate = targets(references)['cuts_per_minute']
    mine = cut.get('cuts_per_minute')
    summary['cuts_per_minute'] = {'reference': rate, 'cut': mine}
    if rate and mine and total > 0 and cut_speech < SPEECH_LED and not unknown and abs(mine - rate) > TOLERANCE_RATE * rate:
        # a cut led by the picture runs at the reference's rate through its body (a talking head keeps its speech's)
        wanted = round(rate * total / 60)
        problems.append(f"the body cuts {mine:.0f} times a minute against the reference's {rate:.0f} "
                        f"({_clock(body[0]['start_s'])}-{_clock(body[-1]['end_s'])}: {len(body)} shots, about "
                        f"{wanted} at the reference's rate)")
    ending_refs = [ref['ending_median_s'] for ref in refs if ref['ending_median_s'] is not None]
    if ending and ending_refs:
        theirs = max(ending_refs)
        lengths = _lengths(ending)
        mine = statistics.median(lengths)
        if mine > theirs * (1 + TOLERANCE_SLOW):
            start, end = ending[0]['start_s'], ending[-1]['end_s']
            ids = _items(script, start, end)
            summary['stretches'].append({'kind': 'slow_ending', 'start_s': round(start, 3), 'end_s': round(end, 3),
                                         'median_s': round(mine, 3), 'lengths_s': [round(x, 3) for x in lengths],
                                         'items': ids})
            problems.append(
                f"the ending's last {len(lengths)} picture shots ({_clock(start)}-{_clock(end)}) are "
                f"{', '.join(f'{x:.2f}' for x in lengths)} s, median {mine:.2f} s, against the reference's ending "
                f"median of {theirs:.2f} s" + (f" ({', '.join(ids)})" if ids else ''))
    return summary, problems
