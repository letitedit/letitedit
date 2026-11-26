"""How fast a video's sound reaches its main level: a Look's measured opening against an export's.

reference(profile)          from a learned-sound/1 profile's music energy curve (1 s RMS bins): {'main_dbfs', 'top_dbfs',
                            'full_s', 'levels'}, or None when the curve is missing or too short to tell.
measure(video)              the same 1 s RMS curve of an export's whole mix.
check(reference, measured)  (summary, problems): the cut reaching its main level later than the reference's opening
                            allows names the stretch, with how far under its main level it is; a cut at its main level
                            well before a reference that opens quiet names that too, with how much quieter the
                            reference's opening seconds are.
quiet_until(profile)        where a sound plan's quiet first section may end: the reference's full_s when it opens
                            fast (within OPENING_MAX_S), else None.
full_after_opening(profile) True when the reference opens fast and then holds its main level within FULL_DB of its
                            loudest (a flat-out montage, no build): the music after the opening is the song's full part.

The main level is the median of the second-long bins with sound in them, the top their 90th percentile; reached is the
first second from which the bin and the median of the next REACH_BINS are within FULL_DB of the main level. A cut's
main level is not its own median (a cut quiet up to a late swell has a quiet median and would pass itself): it is the
level as far under the cut's top as the reference's main level is under the reference's top. The reference's curve is
its music (its music stem when someone talks in it); the export's is everything in the mix, so a voice over quiet music
reads as reached: it never names a cut late for talking, only a quiet start.

Both ways: a reference that opens quiet (at its main level only from QUIET_OPENING_S or later) is matched too. Over the
reference's quiet seconds, each second's shortfall under the main level (at most QUIET_CAP_DB: silence and quiet
music both count as quiet) is averaged on both sides; a cut that reaches its main level sooner and whose opening is
over EARLY_DB less under it than the reference's opens too loud. 6 dB: a cut that opened the way its reference did
(the same rise by the same second) measured 2.7 dB from it, and one at its main level from the first second, which
both blind judges named, 13.6 dB. The export's curve is the whole mix, so a voice reads as loud: a cut is judged early
only when nobody talks in the reference's opening (its voice stem) and the cut has no speech there (talk_s).
"""
from __future__ import annotations

import math
import subprocess

import numpy as np

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (no console windows)

FULL_DB = 3.0             # within this many dB of the main level counts as reached
SILENT_DBFS = -60.0       # a bin under this has no sound in it (black, silence)
REACH_BINS = 3            # reached means held: the median of this many bins from there is within FULL_DB too
OPENING_MAX_S = 10.0      # a reference reaching its main level later than this opens slowly on purpose
OPENING_SLACK_S = 3.0     # the cut may take this much longer than the reference
MIN_BINS = 8              # fewer seconds of sound than this tell nothing
QUIET_OPENING_S = 2.0     # a reference at its main level only from this second or later opens quiet
QUIET_CAP_DB = 20.0       # a second counts at most this far under the main level (silence is as quiet as it gets)
EARLY_DB = 6.0            # a cut's opening this much louder (less under its main level) than the reference's
VOICE_QUIET_LUFS = -40.0  # a reference's voice stem under this through its opening: nobody talks there
TALK_S = 0.5              # a cut with more speech than this in the reference's opening seconds is not judged early
RATE = 8000


def _clock(seconds):
    return f'{int(seconds // 60)}:{int(seconds % 60):02d}'


def _reached(levels, threshold):
    """The first second from which the bin and the median of the next REACH_BINS are at or over threshold, or None."""
    for index, value in enumerate(levels):
        ahead = [v for v in levels[index:index + REACH_BINS] if v is not None]
        if value is not None and value >= threshold and ahead and float(np.median(ahead)) >= threshold:
            return float(index)
    return None


def _shape(levels):
    """{'main_dbfs', 'top_dbfs', 'full_s', 'levels'} from second-long levels in dBFS (None for a bin with no sound)."""
    sounding = [value for value in levels if value is not None and value > SILENT_DBFS]
    if len(sounding) < MIN_BINS:
        return None
    main = float(np.median(sounding))
    return {'main_dbfs': round(main, 2), 'top_dbfs': round(float(np.percentile(sounding, 90)), 2),
            'full_s': _reached(levels, main - FULL_DB),
            'levels': [None if v is None else round(v, 2) for v in levels]}


def _talks_in_opening(profile, seconds):
    """True when the reference's voice stem is over VOICE_QUIET_LUFS in its first seconds (its short-term loudness,
    else its integrated loudness), False when quiet or not separated."""
    vocals = ((profile or {}).get('stem_loudness') or {}).get('vocals') or {}
    rows = [value for t, value in vocals.get('short_term') or [] if isinstance(value, (int, float)) and t <= seconds + 1]
    if rows:
        return max(rows) > VOICE_QUIET_LUFS
    level = vocals.get('integrated_lufs')
    return isinstance(level, (int, float)) and level > VOICE_QUIET_LUFS


def reference(profile):
    """The reference's opening from its sound.json profile (dict), or None."""
    music = (profile or {}).get('music') or {}
    curve = ((music.get('energy') or {}).get('curve')) or []
    if not curve or float((music.get('energy') or {}).get('bin_s') or 1.0) != 1.0:
        return None
    spans = music.get('music_spans') or []
    if spans and float(spans[0][0]) > 1.0:
        return None          # the music comes in later: its opening is not the video's opening
    levels = []
    for row in sorted(curve, key=lambda r: float(r.get('t', 0))):
        value = row.get('rms_dbfs')
        levels.append(float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None)
    shape = _shape(levels)
    if shape and shape['full_s'] is not None:
        shape['talks_in_opening'] = _talks_in_opening(profile, shape['full_s'])
    return shape


def quiet_until(profile):
    """Seconds a sound plan's first section may stay quiet: the reference's own opening, when it is fast."""
    shape = reference(profile)
    if not shape or shape['full_s'] is None or shape['full_s'] > OPENING_MAX_S:
        return None
    return shape['full_s']


def full_after_opening(profile):
    """True when the reference opens fast and holds its main level within FULL_DB of its loudest from there."""
    shape = reference(profile)
    return bool(quiet_until(profile) is not None and shape['top_dbfs'] - shape['main_dbfs'] <= FULL_DB)


def measure(video):
    """The export's whole mix as second-long RMS levels (dBFS)."""
    import letitedit.core.media as media
    run = subprocess.run([str(media.ffmpeg()), '-v', 'error', '-i', str(video), '-vn', '-ac', '1', '-ar', str(RATE),
                          '-f', 'f32le', '-'], capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
    if run.returncode:
        raise RuntimeError('ffmpeg could not read the sound: ' + run.stderr.decode('utf-8', 'replace')[-300:])
    samples = np.frombuffer(run.stdout, dtype=np.float32)
    levels = []
    for start in range(0, len(samples) - RATE // 2, RATE):
        chunk = samples[start:start + RATE].astype(np.float64)
        rms = math.sqrt(float(np.mean(chunk * chunk))) if len(chunk) else 0.0
        levels.append(20 * math.log10(rms) if rms > 1e-9 else None)
    return _shape(levels) or {'main_dbfs': None, 'top_dbfs': None, 'full_s': None, 'levels': levels}


def _under(levels, main, seconds):
    """The mean shortfall under main (dB, each second at most QUIET_CAP_DB, a louder second 0) over the first seconds."""
    rows = [min(QUIET_CAP_DB, max(0.0, main - (SILENT_DBFS if v is None else v))) for v in levels[:int(seconds)]]
    return float(np.mean(rows)) if rows else 0.0


def _early(ref, levels, main, cut_full, summary, talk_s):
    """The problem for a cut at its main level well before a reference that opens quiet, or None."""
    if ref['full_s'] < QUIET_OPENING_S or cut_full is None or cut_full >= ref['full_s']:
        return None
    if ref.get('talks_in_opening') or (talk_s or 0) > TALK_S:
        summary['early_not_judged'] = 'speech in the opening: the mix is loud with the voice, whatever the music does'
        return None
    ref_under = _under(ref.get('levels') or [], ref['main_dbfs'], ref['full_s'])
    cut_under = _under(levels, main, ref['full_s'])
    summary.update({'reference_opening_under_db': round(ref_under, 1), 'cut_opening_under_db': round(cut_under, 1)})
    if ref_under - cut_under <= EARLY_DB:
        return None
    summary['direction'] = 'early'
    return (f"the reference's music opens quiet and reaches its main level only at {_clock(ref['full_s'])} (its first "
            f"{ref['full_s']:g} s on average {ref_under:.0f} dB under it); the cut's sound is at its main level from "
            f"{_clock(cut_full)} (its first {ref['full_s']:g} s on average {cut_under:.0f} dB under it, "
            f"{ref_under - cut_under:.0f} dB louder): open as quietly as the reference (the song's quiet opening, or the "
            f"music brought up over the first {ref['full_s']:g} s) and reach the main level at "
            f"{_clock(ref['full_s'])}")


def check(ref, measured, talk_s=0.0):
    """(summary, problems) for the cut's opening against the reference's: late, or early against a quiet opening
    (talk_s: seconds of speech in the cut over the reference's opening seconds)."""
    if not ref or ref.get('full_s') is None or ref['full_s'] > OPENING_MAX_S:
        return None, []
    if not measured or measured.get('main_dbfs') is None:
        return None, []
    levels = measured['levels']
    spread = max(0.0, float(ref.get('top_dbfs', ref['main_dbfs'])) - ref['main_dbfs'])
    top = measured.get('top_dbfs')
    if top is None:
        top = float(np.percentile([v for v in levels if v is not None and v > SILENT_DBFS], 90))
    main = round(top - spread, 2)
    cut_full = _reached(levels, main - FULL_DB)
    summary = {'reference_full_s': ref['full_s'], 'reference_main_dbfs': ref['main_dbfs'],
               'reference_top_dbfs': ref.get('top_dbfs'), 'cut_full_s': cut_full, 'cut_main_dbfs': main,
               'cut_top_dbfs': round(top, 2), 'full_db': FULL_DB,
               'cut_opening_levels': levels[:int(max(cut_full or 0, ref['full_s']) + 2)], 'direction': None}
    allowed = ref['full_s'] + OPENING_SLACK_S
    if cut_full is not None and cut_full <= allowed:
        early = _early(ref, levels, main, cut_full, summary, talk_s)
        return summary, [early] if early else []
    summary['direction'] = 'late'
    end = cut_full if cut_full is not None else len(levels)
    under = [main - v for v in levels[int(allowed):int(end)] if v is not None]
    gap = f', on average {float(np.mean(under)):.0f} dB under it' if under else ''
    reached = f'reaches its main level only at {_clock(cut_full)}' if cut_full is not None else 'never holds its main level'
    return summary, [f"the reference's music is at its main level by {_clock(ref['full_s'])}; the cut's sound {reached} "
                     f"({_clock(allowed)}-{_clock(end)}{gap}): bring the music to its main level as fast (a part of "
                     "the song that is already full there, an opening section no quieter than the reference's)"]
