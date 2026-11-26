"""The shape of a video's sound: its opening, its level through the body, its ending and its rate of sharp hits.

One meter reads both sides: the EBU R128 momentary loudness of the whole mix every 0.1 s (ffmpeg's ebur128 filter).
A Look's reference is read when Learn measures its sound (the `shape` of its sound.json); a Look saved before that has
its shape worked out from its stored report when read (look_shape); a cut is read on its export.

measure(path, cuts, text)   the shape of a file: letitedit-sound-shape/1.
look_shape(recipe)          the Look's reference shape: its sound.json's, else worked out from its stored report (the
                            reference file it names when it is still there, unchanged; else the report's 1 s levels,
                            which tell the levels but not the hits), or None.
check(ref, cut)             (summary, problems): the cut's shape against the reference's.

The shape:
- body_lufs: the median of the 5 s windows' median momentary loudness, the first and last windows left out.
- windows: each 5 s window's median, and its level against the body (dB, negative = quieter).
- opening: the first window under the body (dB, positive = quieter), and the second the sound first holds within
  REACH_DB of the body for a second.
- ending: the last ENDING_S seconds under the body (dB), and what it is: silent (under SILENT_LUFS), a drop (over
  DROP_DB under), a fade (over FADE_DB) or held.
- body_spread_db: the spread of the body's windows (90th minus 10th percentile): how much the level dips and rises.
- hits: sudden peaks, a 0.1 s step at least HIT_LU louder than the loudest of the second before it and over
  HIT_FLOOR (hits, whooshes, impacts, a drum, a shout: a count, not a list of sound effects); per minute, their times
  and the share on a cut or a text arrival (within ANCHOR_S); from version 2 also the median level of the second
  before each (dB under the body: a hit over steady talk or music is rare, since the step is measured from that second's
  loudest) and of its first half second (dB against the body).

The bars (each reference read as a cut against itself must pass): hits, the
cut under HIT_SHORT of the reference's rate (a reference with at least HIT_MIN a minute), or a cut with HIT_NONE a
minute or more against a reference with none; the opening, against a reference that opens quiet (its first window at
least QUIET_OPENING_DB under its body) over OPENING_DB less under the cut's body, else over SHAPE_DB louder or quieter; the ending, the reference's last seconds a drop or silence and the cut's over SHAPE_DB less under its body;
the body, the reference's spread at least SPREAD_MIN_DB and the cut's under SPREAD_SHARE of it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows)

FORMAT = 'letitedit-sound-shape/1'
VERSION = 2                 # 2: the hits' second before and their level against the body
STEP_S = 0.1
WINDOW_S = 5.0
ENDING_S = 3.0
SILENT_LUFS = -40.0
DROP_DB = 8.0
FADE_DB = 3.0
REACH_DB = 3.0
HIT_LU = 9.0
HIT_FLOOR = -35.0
HIT_GAP_S = 0.3             # two steps closer than this are one hit
ANCHOR_S = 0.25
HIT_MIN = 1.0               # a reference with this many hits a minute or more has hits to match
HIT_SHORT = 0.5             # a cut under this share of the reference's rate is short of hits
HIT_NONE = 1.0              # a cut with this many a minute against a reference with none (under 0.5 a minute)
SHAPE_DB = 6.0
QUIET_OPENING_DB = 4.0
OPENING_DB = 2.5
SPREAD_MIN_DB = 6.0
SPREAD_SHARE = 0.6


def _ffmpeg():
    import letitedit.core.media as media
    return str(media.ffmpeg())


def momentary(path):
    """[(t, momentary LUFS)] every 0.1 s of a file's mixed sound ([] without sound)."""
    run = subprocess.run([_ffmpeg(), '-v', 'info', '-nostats', '-threads', '4', '-i', str(path), '-map', '0:a:0',
                          '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8',
                         errors='replace', stdin=subprocess.DEVNULL, timeout=900)
    return [(float(t), float(m)) for t, m in re.findall(r't:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-inf)', run.stderr)
            if m != '-inf']


def _median(values):
    return float(np.median(values)) if values else None


def _near(times, anchors):
    if not times or not anchors:
        return None
    anchors = np.asarray(sorted(anchors), float)
    return round(sum(1 for t in times if float(np.min(np.abs(anchors - t))) <= ANCHOR_S) / len(times), 3)


def hits(rows):
    """Times of the sudden peaks in momentary rows (HIT_LU over the loudest of the second before, on the momentary loudness meter)."""
    values = [m for _, m in rows]
    times = []
    back = int(round(1 / STEP_S))
    for index in range(back, len(values)):
        if values[index] - max(values[index - back:index - 1]) >= HIT_LU and values[index] > HIT_FLOOR:
            # momentary loudness reads 0.4 s: the step it jumps on is where the sound arrived
            t = round(rows[index][0], 2)
            if not times or t - times[-1] >= HIT_GAP_S:
                times.append(t)
    return times


def _hit_levels(rows, times, body):
    """(median dB the second before each hit sits under the body, median dB its first half second sits against it)."""
    if not times:
        return None, None
    before, level = [], []
    for at in times:
        prior = [m for t, m in rows if at - 1 <= t < at - STEP_S / 2]
        after = [m for t, m in rows if at - STEP_S / 2 <= t < at + .5]
        if prior:
            before.append(body - max(max(prior), -70.))
        if after:
            level.append(max(after) - body)
    return (round(_median(before), 1) if before else None), (round(_median(level), 1) if level else None)


def from_momentary(rows, duration, cuts=(), text=()):
    """The shape from momentary rows [(t, LUFS)] of a file `duration` seconds long; None without enough sound."""
    if not rows or duration <= 0:
        return None
    windows = []
    start = 0.0
    while start < duration - 1e-6:
        end = min(duration, start + WINDOW_S)
        values = [m for t, m in rows if start <= t < end and m > -70]
        windows.append({'from_s': round(start, 2), 'to_s': round(end, 2), 'lufs': round(_median(values), 1)
                        if values else None})
        start = end
    inner = [w['lufs'] for w in windows[1:-1] if w['lufs'] is not None] or [w['lufs'] for w in windows
                                                                             if w['lufs'] is not None]
    if not inner:
        return None
    body = _median(inner)
    for window in windows:
        window['vs_body_db'] = None if window['lufs'] is None else round(window['lufs'] - body, 1)
    first = windows[0]['lufs']
    reach = None
    for t, _ in rows:
        second = [m for u, m in rows if t <= u < t + 1]
        if second and _median(second) >= body - REACH_DB:
            reach = round(t, 1)
            break
    tail = [m for t, m in rows if t >= duration - ENDING_S]
    tail_level = _median([max(m, -70.) for m in tail]) if tail else -70.
    under = round(body - tail_level, 1)
    kind = ('silent' if tail_level < SILENT_LUFS else 'drop' if under > DROP_DB else 'fade' if under > FADE_DB
            else 'held')
    times = hits(rows)
    spread = (float(np.percentile(inner, 90) - np.percentile(inner, 10)) if len(inner) > 1 else 0.)
    quiet_before, level = _hit_levels(rows, times, body)
    return {'format': FORMAT, 'version': VERSION, 'duration_s': round(float(duration), 2),
            'body_lufs': round(body, 1), 'windows': windows, 'body_spread_db': round(spread, 1),
            'opening': {'under_body_db': None if first is None else round(body - first, 1), 'reaches_body_s': reach},
            'ending': {'seconds': ENDING_S, 'lufs': round(tail_level, 1), 'under_body_db': under, 'kind': kind},
            'hits': {'count': len(times), 'per_minute': round(len(times) * 60 / duration, 2), 'times_s': times,
                     'on_cuts': _near(times, cuts), 'on_text': _near(times, text),
                     'before_under_body_db': quiet_before, 'level_vs_body_db': level},
            'method': 'EBU R128 momentary loudness of the whole mix every 0.1 s (ffmpeg ebur128)'}


def _duration(path):
    import letitedit.core.media as media
    info = media.probe(str(path))
    return float((info.get('format') or {}).get('duration') or 0)


def measure(path, cuts=(), text=(), duration=None):
    """The shape of a file's sound (cuts, text: its cut and text-arrival times, for the hits' anchors)."""
    rows = momentary(path)
    return from_momentary(rows, duration or _duration(path), cuts, text)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_folder():
    from letitedit.core import paths as _paths
    return Path(os.environ.get('LETITEDIT_SOUND_SHAPE_CACHE') or Path(_paths.install_root()) / 'cache' / 'sound-shape')


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _report_anchors(report):
    cuts = [float(c['t']) for c in report.get('cuts') or [] if isinstance(c, dict) and c.get('t') is not None]
    text = []
    for event in report.get('text_events') or []:
        if isinstance(event, dict):
            at = event.get('start_s', event.get('t', event.get('start')))
            if isinstance(at, (int, float)):
                text.append(float(at))
    return cuts, text


def from_report(report):
    """A reference's shape from its stored report: the reference file it names when it is still there unchanged
    (measured, cached by its digest), else its mix's 1 s levels (no hits). None when neither is there."""
    file = report.get('file')
    cuts, text = _report_anchors(report)
    if file and Path(file).is_file():
        try:
            digest = _sha256(file)
            cache = _cache_folder() / f'{digest}-v{VERSION}.json'
            if cache.is_file():
                return _read(cache)
            shape = measure(file, cuts, text, duration=float(report.get('duration_s') or 0) or None)
            if shape:
                shape['from'] = 'the reference file, measured when read'
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(shape, indent=1), encoding='utf-8')
            return shape
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            pass
    curve = (((report.get('sound') or {}).get('mix_energy') or {}).get('curve')) or []
    if not curve:
        return None
    # 1 s RMS levels of the mix stand in for loudness (dBFS, not LUFS: the levels against each other hold, not the
    # number); with one reading a second the 0.1 s hits can't be told
    rows = []
    for row in curve:
        value = row.get('rms_dbfs')
        if isinstance(value, (int, float)):
            for k in range(10):
                rows.append((float(row.get('t', 0)) + k * STEP_S, float(value)))
    shape = from_momentary(rows, float(report.get('duration_s') or (rows[-1][0] + STEP_S)), cuts, text)
    if shape:
        shape['hits'] = None
        shape['from'] = "the stored report's 1 s levels (the reference file was not found): no hits"
    return shape


def look_shape(recipe):
    """The Look's reference shape: its sound.json's `shape`, else worked out from the stored report its evidence.json
    names (the first reference that gives one), or None. The saved revision is never rewritten."""
    recipe = Path(recipe)
    sound = recipe.with_name('sound.json')
    if sound.is_file():
        try:
            shape = _read(sound).get('shape')
            if isinstance(shape, dict) and shape.get('format') == FORMAT:
                return shape
        except (OSError, ValueError):
            pass
    evidence = recipe.with_name('evidence.json')
    if not evidence.is_file():
        return None
    try:
        references = _read(evidence).get('references') or []
    except (OSError, ValueError):
        return None
    for reference in references:
        report_path = (reference or {}).get('report')
        report = None
        if report_path and Path(report_path).is_file():
            try:
                report = _read(report_path)
            except (OSError, ValueError):
                report = None
        if report is None and reference.get('file'):
            report = {'file': reference['file'], 'duration_s': reference.get('duration_s')}
        if report:
            shape = from_report(report)
            if shape:
                return shape
    return None


def _clock(seconds):
    return f'{int(seconds // 60)}:{int(seconds % 60):02d}'


def check(ref, cut):
    """(summary, problems) for the cut's sound shape against the reference's."""
    if not ref or not cut:
        return None, []
    summary = {'format': FORMAT, 'reference': {k: ref.get(k) for k in ('body_lufs', 'body_spread_db', 'opening',
                                                                         'ending', 'from')},
               'cut': {k: cut.get(k) for k in ('body_lufs', 'body_spread_db', 'opening', 'ending')}}
    problems = []
    ref_hits, cut_hits = ref.get('hits'), cut.get('hits') or {}
    if ref_hits:
        summary['hits'] = {'reference_per_minute': ref_hits['per_minute'], 'cut_per_minute': cut_hits.get('per_minute'),
                           'reference_on_cuts': ref_hits.get('on_cuts'), 'reference_on_text': ref_hits.get('on_text'),
                           'reference_before_under_body_db': ref_hits.get('before_under_body_db'),
                           'reference_level_vs_body_db': ref_hits.get('level_vs_body_db')}
        theirs, mine = ref_hits['per_minute'], cut_hits.get('per_minute') or 0.
        where = [f'{share:.0%} on {name}' for name, share in (('cuts', ref_hits.get('on_cuts')),
                                                              ('text arrivals', ref_hits.get('on_text')))
                 if isinstance(share, (int, float)) and share > 0]
        if theirs >= HIT_MIN and mine < HIT_SHORT * theirs:
            wanted = max(1, round((theirs - mine) * cut['duration_s'] / 60))
            quiet = ref_hits.get('before_under_body_db')
            level = ref_hits.get('level_vs_body_db')
            how = ''
            if isinstance(quiet, (int, float)) and isinstance(level, (int, float)):
                how = (f"; the second before each sits about {quiet:.0f} dB under the body and the hit "
                       f"{abs(level):.0f} dB {'over' if level >= 0 else 'under'} it")
            problems.append(f"the reference has about {theirs:.1f} sudden peaks a minute (hits, whooshes, impacts"
                            + (f"; {', '.join(where)}" if where else '') + how + f"); the cut has {mine:.1f}: about "
                            f"{wanted} more over its {cut['duration_s']:.0f} s")
        elif theirs < 0.5 and mine >= HIT_NONE:
            problems.append(f"the reference has no sudden peaks ({theirs:.1f} a minute); the cut has {mine:.1f} a "
                            f"minute (at {', '.join(f'{t:.1f}' for t in cut_hits.get('times_s', [])[:6])} s)")
    opening_ref, opening_cut = (ref.get('opening') or {}).get('under_body_db'), (cut.get('opening') or {}).get('under_body_db')
    bar = OPENING_DB if (opening_ref or 0) >= QUIET_OPENING_DB else SHAPE_DB
    if opening_ref is not None and opening_cut is not None and abs(opening_ref - opening_cut) > bar and (
            opening_cut < opening_ref or abs(opening_ref - opening_cut) > SHAPE_DB):
        louder = opening_cut < opening_ref
        problems.append(f"the reference's first {WINDOW_S:g} s sit {opening_ref:.0f} dB under its body; the cut's "
                        f"{opening_cut:.0f} dB: it opens {abs(opening_ref - opening_cut):.0f} dB "
                        f"{'louder' if louder else 'quieter'} than the reference does")
    end_ref, end_cut = ref.get('ending') or {}, cut.get('ending') or {}
    if (end_ref.get('kind') in ('silent', 'drop') and end_cut.get('under_body_db') is not None
            and end_ref['under_body_db'] - end_cut['under_body_db'] > SHAPE_DB):
        problems.append(f"the reference's last {ENDING_S:g} s are {'silent' if end_ref['kind'] == 'silent' else 'a drop'}"
                        f" ({end_ref['under_body_db']:.0f} dB under its body, {end_ref['lufs']:.0f} LUFS); the cut's "
                        f"are {end_cut['under_body_db']:.0f} dB under its body ({end_cut['lufs']:.0f} LUFS, "
                        f"{end_cut.get('kind')})")
    spread_ref, spread_cut = ref.get('body_spread_db'), cut.get('body_spread_db')
    if (spread_ref is not None and spread_cut is not None and spread_ref >= SPREAD_MIN_DB
            and spread_cut < SPREAD_SHARE * spread_ref):
        problems.append(f"the reference's level dips and rises {spread_ref:.0f} dB through its body (5 s windows, "
                        f"10th to 90th percentile); the cut's {spread_cut:.0f} dB: flatter")
    summary['problems'] = len(problems)
    return summary, problems
