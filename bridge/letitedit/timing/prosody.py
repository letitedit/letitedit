"""Speech rhythm for the timing layer: the 'speech' lane and the 'speech' view (builder B3, TIMING-SPEC.md).

    analyse(source, start=None, end=None, settings=None, refresh=False) -> the speech lane plus the contract fields
    lane(ctx)                     -> the 'speech' lane for timing_signals (registered at import when available)
    view(source, start_s, end_s, items, cuts, options, detail) -> {'images': [...], ...}  (view 'speech')
    analyse_audio(x16, words, start_s=0, settings=None, cuts=None) -> the same lane data from a 16 kHz mono signal

What the lane measures (every 10 ms unless said otherwise), from the sound the viewer gets (a project: a melt render
of the timeline's speech tracks, or of the whole mix when no music/effects track is heard; a video: its own sound)
and the cached word times (speech.words / timeline_speech.timeline_words):
- `f0` (Hz, None where unvoiced): Praat's autocorrelation pitch (parselmouth, Boersma 1993) in two passes: the
  speaker's floor and ceiling come from the first pass (0.75 x first quartile, 2 x third quartile; Hirst 2011, De
  Looze & Hirst 2008); octave jumps against the running median are folded back. Without parselmouth: YIN (de
  Cheveigne & Kawahara 2002) in numpy.
- `energy` (dB re full scale): RMS of the 80-5000 Hz band in 30 ms Hann windows.
- `words` [{t0, t1, w, stress 0-1, ...}]: the transcript's words with their edges moved onto the sound (voiced or
  above the local speech-activity threshold): turbo-whisper word times run on across pauses (a word can 'last' 1.4 s),
  so pauses are measured from the sound, not from word gaps. `asr_t0`/`asr_t1` keep the transcript's times.
- `pauses` [{t0, t1, dur}]: silences between words (>= pause_min_s).
- `speech_rate` per word: syllables per second over the word and its neighbours inside the same run of speech.
- `thought_ends` [{t, f, strength, cues, measures}]: prosodic boundaries. Cues: `pause` (silent pause >= 0.3 s:
  Biron et al. 2021 found about 300 ms the best single pause threshold for intonation-unit boundaries), `slowing`
  (pre-boundary lengthening of the last word against the speaker's syllable time, or a slower local rate; Wightman
  et al. 1992), `pitch_reset` (the next unit starts higher than this one ended; Swerts 1997), `final_lowering` (the
  unit ends low in the speaker's range). strength = weighted sum of graded cue scores (weights in the thresholds).
  `text_end` says whether the transcript has sentence punctuation there (not used by the detector).
- `stress` per word (0-1): pitch peak and excursion, energy peak and lengthening against the speaker's local range
  (+-2.5 s), robust z-scores combined and squashed; fillers are 0; function words are damped (`stress_acoustic`
  keeps the score without that prior).
- `breaths` [{t0, t1}]: inhalation noise inside pauses: unvoiced stretches 0.1-1.2 s whose 400-4000 Hz bands stand
  above the local noise floor spectrum (and not only in the low bands, where rumble lives).
- `stats`: gaps at thought ends (mean, sd, cv), long pauses inside a thought, the longest stretch without a thought
  end or breath, and, for each thought end, the space after it.

Every number names its unit; every decision names its threshold (bridge/timing_thresholds.json, keys 'speech.*').
Nothing here can listen: breath and stress calls are measurements, and the result says so.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_ROOT = os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)
CACHE = Path(os.environ.get('LETITEDIT_CACHE', os.path.join(_ROOT, 'cache')))
AUDIO_CACHE = CACHE / 'timing-audio'
APP = Path(os.environ.get('LETITEDIT_APP', os.path.join(_ROOT, 'app')))
FFMPEG, FFPROBE, MELT = APP / 'ffmpeg.exe', APP / 'ffprobe.exe', APP / 'melt.exe'
THRESHOLDS = _paths.BRIDGE / 'timing_thresholds.json'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

SCHEMA_VERSION = 1
LANE = 'speech'
LANE_VERSION = 5
try:        # standalone caches also key on this file's content, so a code change never serves stale numbers
    _CODE_KEY = hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:10]
except OSError:
    _CODE_KEY = 'nocode'
HOP = 0.01                  # every series is on a 10 ms grid
SR = 48000                  # sound is decoded / rendered at this rate
SR16 = 16000                # prosody works at this rate
LOCK_OVER_S = 30.0          # renders of more timeline than this hold the PC render lock (TIMING-SPEC)
NOT_SPEECH = re.compile(r'music|song|score|bed|sfx|effect|sound|foley|ambien', re.I)   # as timeline_speech

# Defaults of every threshold this module uses ('speech.' keys of timing_thresholds.json override them).
DEFAULTS = {
    'speech.pause_min_s': 0.15,             # a silence between words this long is a pause
    'speech.thought_end.pause_s': 0.30,     # pause cue (Biron et al. 2021: ~300 ms best single threshold)
    'speech.thought_end.pause_full_s': 0.50,  # a pause this long scores the full pause cue
    'speech.thought_end.lengthening': 1.40,   # slowing cue: last word lasts this x its syllables' usual time
    'speech.thought_end.rate_ratio': 0.80,    # ... or the last words' rate is under this x the speaker's
    'speech.thought_end.reset_st': 2.0,       # pitch reset cue: next unit starts this many semitones higher
    'speech.thought_end.fall_st': -2.0,       # final lowering cue: the last word ends this far under the unit's
                                              # level (median pitch of the 1.5 s before)
    # cue weights in the strength (sum is normalised). Tuned 28 Oct 2026 on the quick clips against weak text labels
    # (tests/fixtures/speech-joins); on held-out story clips pitch reset, final lowering and breath added nothing, so
    # their weight is 0 (they are still measured and listed as cues)
    'speech.thought_end.w_pause': 0.55,
    'speech.thought_end.w_slowing': 0.30,
    'speech.thought_end.w_pitch_reset': 0.0,
    'speech.thought_end.w_final_lowering': 0.0,
    'speech.thought_end.w_breath': 0.0,
    'speech.thought_end.min_strength': 0.55,  # a boundary with this strength or more is a thought end
    'speech.thought_end.lexical': 1,          # 1: a boundary after a word that can't end a phrase ("the", "and",
    'speech.thought_end.incomplete_penalty': 0.50,  # "of"...) loses this much strength; 0: acoustic cues only
    'speech.stress.min': 0.50,                # a word with stress at least this is listed as stressed (~12% of words)
    'speech.stress.w_f0': 0.35,               # prominence weights (robust z-scores)
    'speech.stress.w_f0_range': 0.15,
    'speech.stress.w_energy': 0.35,
    'speech.stress.w_duration': 0.15,
    'speech.stress.center_z': 0.80,           # prominence (z) that maps to stress 0.5
    'speech.stress.scale_z': 0.45,            # logistic width
    'speech.stress.function_word_factor': 0.6,  # function words' stress is multiplied by this
    'speech.breath.min_pause_s': 0.20,        # pauses shorter than this are not searched for breaths
    'speech.breath.excess_db': 4.0,           # 400-4000 Hz bands this far above the local noise floor spectrum
    'speech.breath.min_s': 0.10,
    'speech.breath.max_s': 1.20,
    'speech.breath.max_jitter_db': 1.5,       # median frame-to-frame change of that excess (knocks and clicks jump)
    'speech.breath.min_breadth': 0.0,         # share of the 400-4000 Hz bands raised >= 3 dB (hum is narrow; 0 = off:
                                              # it did not separate breaths from noise in our footage)
    'speech.breath.min_plateau': 0.20,        # share of the run's frames within 6 dB of its peak (a knock is one peak)
    'speech.long_pause_s': 1.0,               # a pause this long inside a thought is drag (letitedit-fine FINE-1)
    'speech.key_line_space_s': 0.60,          # space after a key line under this is noted (P4: hold after the line)
    'speech.no_reset_s': 30.0,                # craft P5: no 30 s without a breath or reset
    'speech.activity_db': 6.0,                # speech activity: at least this far above the local floor ...
    'speech.activity_share': 0.30,            # ... and this share of the way from the floor to the speech level
    'speech.activity_anchor_s': 0.12,         # ... and (unvoiced sound) within this of voicing
}

# unit and meaning of every key, for timing_thresholds.json ({value, unit, about})
INFO = {
    'speech.pause_min_s': ('s', 'a silence between words this long is listed as a pause'),
    'speech.thought_end.pause_s': ('s', 'pause cue of a thought end (Biron et al. 2021: about 300 ms is the best '
                                        'single pause threshold for intonation-unit boundaries)'),
    'speech.thought_end.pause_full_s': ('s', 'a pause this long scores the full pause cue (0 at 100 ms)'),
    'speech.thought_end.lengthening': ('x', 'slowing cue: the last word lasts this many times its syllables\' usual '
                                            'time (pre-boundary lengthening)'),
    'speech.thought_end.rate_ratio': ('x', "slowing cue: the last three words' rate under this share of the "
                                           "speaker's median rate"),
    'speech.thought_end.reset_st': ('semitones', 'pitch reset cue: the next words start this much higher'),
    'speech.thought_end.fall_st': ('semitones', 'final lowering cue: the last word ends this far under the median '
                                                'pitch of the 1.5 s before'),
    'speech.thought_end.w_pause': ('weight', 'pause cue weight in the thought-end strength (tuned 28 Oct 2026 on '
                                             'weak text labels of the quick clips)'),
    'speech.thought_end.w_slowing': ('weight', 'slowing cue weight'),
    'speech.thought_end.w_pitch_reset': ('weight', 'pitch reset cue weight (0: added nothing on held-out clips)'),
    'speech.thought_end.w_final_lowering': ('weight', 'final lowering cue weight (0: added nothing on held-out clips)'),
    'speech.thought_end.w_breath': ('weight', 'breath-in-the-pause cue weight (0: added nothing on held-out clips)'),
    'speech.thought_end.min_strength': ('0-1', 'a word boundary with this strength or more is a thought end'),
    'speech.thought_end.lexical': ('0/1', '1: a boundary after a word that cannot end a phrase (the, and, of, I, to '
                                          '...) loses incomplete_penalty; 0: acoustic cues only'),
    'speech.thought_end.incomplete_penalty': ('0-1', 'strength taken off after such a word'),
    'speech.stress.min': ('0-1', 'a word with stress at least this is listed as stressed (about 12% of words)'),
    'speech.stress.w_f0': ('weight', 'pitch peak over the local median (robust z) in the prominence'),
    'speech.stress.w_f0_range': ('weight', 'pitch movement within the word'),
    'speech.stress.w_energy': ('weight', 'energy peak over the local speech level'),
    'speech.stress.w_duration': ('weight', 'lengthening against the syllables\' usual time'),
    'speech.stress.center_z': ('z', 'prominence that maps to stress 0.5 (logistic)'),
    'speech.stress.scale_z': ('z', 'logistic width'),
    'speech.stress.function_word_factor': ('x', "function words' stress is multiplied by this"),
    'speech.breath.min_pause_s': ('s', 'pauses shorter than this are not searched for breaths'),
    'speech.breath.excess_db': ('dB', 'a breath raises the 400-4000 Hz bands this far over the local noise floor '
                                      'spectrum, unvoiced'),
    'speech.breath.min_s': ('s', 'shortest breath'),
    'speech.breath.max_s': ('s', 'longest breath'),
    'speech.breath.max_jitter_db': ('dB', 'median frame-to-frame change of that excess; more is a knock or clicks '
                                          '(fitted on spectrogram labels, 28 Oct 2026)'),
    'speech.breath.min_breadth': ('0-1', 'share of the 400-4000 Hz bands raised 3 dB or more (0 = off)'),
    'speech.breath.min_plateau': ('0-1', "share of the run's frames within 6 dB of its peak; less is one knock"),
    'speech.long_pause_s': ('s', 'a pause this long inside a thought is listed as drag (letitedit-fine FINE-1)'),
    'speech.key_line_space_s': ('s', 'space after a key line under this is noted (craft P4: hold after the line)'),
    'speech.no_reset_s': ('s', 'craft P5: no stretch this long without a thought end or breath'),
    'speech.activity_db': ('dB', 'speech activity: unvoiced sound at least this far over the local floor ...'),
    'speech.activity_share': ('0-1', '... and this share of the way from the floor to the speech level ...'),
    'speech.activity_anchor_s': ('s', '... and within this of voicing (machines and wind far from voice are not '
                                      'speech)'),
}


def threshold_entries():
    """This module's keys for timing_thresholds.json as {key: {value, unit, about}}."""
    return {k: {'value': DEFAULTS[k], 'unit': INFO.get(k, ('', ''))[0], 'about': INFO.get(k, ('', ''))[1]}
            for k in DEFAULTS}


FILLERS = {'um', 'uh', 'umm', 'uhh', 'er', 'erm', 'hmm', 'mm', 'mhm', 'ah', 'eh'}
# words after which an English phrase is (almost) never complete: articles, possessives, coordinators, "of"
CANT_END = {'the', 'a', 'an', 'and', 'or', 'but', 'because', 'cause', 'my', 'your', 'our', 'their', 'its', 'his',
            'of', 'than', 'whether', 'if', 'some', 'every', 'each', 'these', "it's", "that's", "there's", "i'm",
            "we're", "you're", "they're", "i've", "we've", "i'll", "we'll", "i'd", 'is', 'are', 'was', 'were',
            'gonna', 'wanna', 'gotta', 'kind', 'sort', 'i', 'we', 'he', 'she', 'they', 'to', 'can', 'could', 'would',
            'will', 'should', 'might', 'must', 'just', 'like', 'so', 'where', 'when', 'what', 'which', 'who', 'how',
            'with', 'from', 'into', 'onto', 'at', 'by', 'for', 'about', 'really', 'very', 'actually', 'literally',
            'basically', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'not', "don't", "can't",
            "won't", "didn't", "doesn't", 'then'}
FUNCTION_WORDS = set("""a an the and or but nor so yet if then than that this these those there here it its it's
i i'm i've i'll i'd me my mine we we're we've we'll us our you you're you've your yours he him his she her hers they
them their theirs who whom whose which what when where why how is am are was were be been being do does did doing
have has had having will would shall should can could may might must of to in on at by for with from up down out
off over under into onto about as like just also too very really kind sort gonna wanna gotta let's let
not no yes yeah okay ok oh well all some any each every both either neither such own same other another more most
much many few little lot lots one ones thing things get got go goes going went come came make made""".split())


# ------------------------------------------------------------------ thresholds and settings

_TH_CACHE = {'mtime': None, 'data': {}}


def thresholds():
    """The shared thresholds file (bridge/timing_thresholds.json) as a dict; {} when missing."""
    try:
        m = THRESHOLDS.stat().st_mtime_ns
    except OSError:
        return {}
    if _TH_CACHE['mtime'] != m:
        try:
            _TH_CACHE['data'] = json.loads(THRESHOLDS.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            _TH_CACHE['data'] = {}
        _TH_CACHE['mtime'] = m
    return _TH_CACHE['data']


def _value(v):
    return v.get('value') if isinstance(v, dict) else v


def settings_for(prefix_defaults, given=None):
    """Defaults < thresholds file < `given` (keys with or without the 'speech.' / 'joins.' prefix)."""
    out = dict(prefix_defaults)
    th = thresholds()
    for k in out:
        if k in th and _value(th[k]) is not None:
            out[k] = _value(th[k])
    for k, v in (given or {}).items():
        if v is None:
            continue
        if k in out:
            out[k] = v
        else:
            for full in out:
                if full.split('.', 1)[-1] == k:
                    out[full] = v
    return out


def _hash(obj, n=12):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:n]


def merge_thresholds(entries, path=None):
    """Add or update the given keys in timing_thresholds.json without touching any other key (re-read just before
    the atomic write, so a concurrent writer's keys survive)."""
    path = Path(path or THRESHOLDS)
    for _ in range(20):
        try:
            before = path.read_text(encoding='utf-8-sig') if path.exists() else '{}'
            data = json.loads(before or '{}')
        except ValueError:
            raise RuntimeError(f'{path} is not valid JSON; not overwriting it')
        data.update(entries)
        tmp = path.with_name(f'{path.name}.{os.getpid()}-{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        now = path.read_text(encoding='utf-8') if path.exists() else '{}'
        if now != before:          # someone wrote in between: merge again
            tmp.unlink(missing_ok=True)
            continue
        try:
            os.replace(tmp, path)
            return data
        except PermissionError:
            tmp.unlink(missing_ok=True)
            time.sleep(0.05)
    raise RuntimeError(f'could not update {path}')


# ------------------------------------------------------------------ small helpers

def clock(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:05.2f}'


def frame(t, fps):
    return int(math.floor(float(t) * float(fps) + 1e-6))


def _r(x, nd=3):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def kind_of(source):
    return 'project' if str(source).lower().endswith('.mlt') else 'video'


def fingerprint(path):
    """Content key of a media file (size + first 2 MB, as footage_notes) or of a project (its file hash)."""
    path = str(path)
    if kind_of(path) == 'project':
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    try:
        import letitedit.footage.footage_notes as footage_notes
        return footage_notes.key(path)
    except Exception:  # noqa: BLE001
        st = os.stat(path)
        h = hashlib.sha1()
        with open(path, 'rb') as fh:
            h.update(fh.read(2 * 1024 * 1024))
        return f'{st.st_size}-{h.hexdigest()[:16]}'


def contract(source, kind, checked=None, unchecked=None, warnings=None, unsupported=None, artifacts=None, extra=None):
    """The common contract fields every timing result carries (TIMING-SPEC: Principles)."""
    out = {'schema_version': SCHEMA_VERSION, 'result_id': uuid.uuid4().hex[:16],
           'project_revision': fingerprint(source) if kind == 'project' and os.path.exists(str(source)) else None,
           'source_fingerprints': {}, 'checked_ranges': checked or [], 'unchecked_ranges': unchecked or [],
           'warnings': list(warnings or []), 'unsupported': list(unsupported or []),
           'preview_artifacts': list(artifacts or []), 'changes': []}
    try:
        out['source_fingerprints'][str(source)] = fingerprint(source)
    except OSError:
        pass
    out.update(extra or {})
    return out


def _font(size, bold=False):
    from PIL import ImageFont
    for name in (('arialbd.ttf', 'segoeuib.ttf') if bold else ('arial.ttf', 'segoeui.ttf')):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', name), size)
        except OSError:
            continue
    return ImageFont.load_default()


# ------------------------------------------------------------------ sound

def _probe_starts(path):
    """(video start_time, audio start_time) of a media file in seconds (0 when absent)."""
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-show_entries', 'stream=codec_type,start_time', '-of', 'json',
                        str(path)], capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW)
    v = a = None
    for s in (json.loads(r.stdout or '{}').get('streams') or []):
        try:
            st = float(s.get('start_time') or 0.0)
        except ValueError:
            st = 0.0
        if s.get('codec_type') == 'video' and v is None:
            v = st
        elif s.get('codec_type') == 'audio' and a is None:
            a = st
    return (v or 0.0), a


def decode(path, channels=2, sr=SR):
    """A file's whole sound as float32 [n, channels] at `sr`, sample 0 at the file's first picture: the audio
    stream's own start offset against the picture is applied (zero-padded or trimmed), so a cut at frame f lands on
    sample f/fps*sr. None when the file has no sound."""
    v0, a0 = _probe_starts(path)
    if a0 is None:
        return None
    args = [str(FFMPEG), '-v', 'error', '-threads', '4', '-i', str(path), '-vn', '-ac', str(channels), '-ar', str(sr),
            '-f', 'f32le', '-']
    raw = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW).stdout
    step = 4 * channels
    y = np.frombuffer(raw[:len(raw) - len(raw) % step], dtype=np.float32).reshape(-1, channels)
    k = int(round((a0 - v0) * sr))                    # the sound starts this many samples after the picture
    if k > 0:
        y = np.concatenate([np.zeros((k, channels), np.float32), y])
    elif k < 0:
        y = y[-k:]
    return np.ascontiguousarray(y)


def _melt_audio(project, wav, seconds, name):
    """melt render of a project's sound (48 kHz 16-bit stereo); holds the PC render lock over LOCK_OVER_S."""
    import contextlib
    long_render = seconds > LOCK_OVER_S
    tmp = Path(str(wav) + '.part.wav')
    args = [str(MELT), '-quiet', str(project), '-consumer', f'avformat:{tmp}', 'vn=1', 'video_off=1',
            'acodec=pcm_s16le', 'ar=48000', 'channels=2', 'real_time=-1']
    timeout = max(180, 6 * seconds)
    for attempt in (1, 2):
        if long_render:
            import letitedit.core.render_lock as render_lock
            lock = render_lock.slot(f'timing speech/joins audio {Path(project).name}', timeout_s=7200, poll_s=2,
                                    caller_pids=render_lock.ancestors())
        else:
            lock = contextlib.nullcontext()
        try:
            with lock:
                r = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=timeout,
                                   creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            if attempt == 2:
                raise
            continue
        break
    if r.returncode != 0 or not tmp.exists():
        raise RuntimeError(f'melt failed ({r.returncode}): {(r.stderr or r.stdout)[-600:]}')
    os.replace(tmp, wav)
    return wav


def _variant(project, keep_names):
    """Copy of the project (in the cache, never next to the user's files) where only the named tracks are heard;
    relative media paths still resolve against the original folder."""
    import xml.etree.ElementTree as ET
    import letitedit.timeline.timeline_model as tm
    tl = tm.load(project)
    keep = {t.index for t in tl.tracks if t.name in set(keep_names)}
    tree = ET.parse(project)
    root = tree.getroot()
    tractors = [e for e in root if e.tag == 'tractor']
    marked = [t for t in tractors if tm.props(t).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    for i, tr in enumerate(main.findall('track')):
        if tr.get('producer') == 'background' or i in keep:
            continue
        hide = tr.get('hide', '')
        tr.set('hide', 'both' if hide in ('video', 'both') else 'audio' if hide == '' else 'both')
    root.set('root', str(Path(project).resolve().parent))
    folder = AUDIO_CACHE / 'variants'
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f'{Path(project).stem}-{os.getpid()}-{threading.get_ident()}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


def speech_tracks(project):
    """(speech track names, other audible track names, timeline) of a project: tracks heard by the viewer whose names
    don't say music/sfx/ambience are speech (timeline_speech's rule)."""
    import letitedit.timeline.timeline_model as tm
    tl = tm.load(project)
    speech_, other = [], []
    for t in tl.tracks:
        if t.hide in ('audio', 'both') or not t.items:
            continue
        (other if NOT_SPEECH.search(t.name) else speech_).append(t.name)
    return speech_, other, tl


_AUDIO_MEMO = {}
_AUDIO_LOCK = threading.Lock()


def project_audio(project, basis='mix', preview=None, refresh=False):
    """(stereo float32 at 48 kHz, description, wav path or None) of a project's sound in timeline time.
    basis 'mix': what the viewer hears (the preview render's sound when given, else a melt render);
    'dialogue': only the speech tracks (music, effects and ambience tracks off), rendered by melt."""
    project = str(Path(project).resolve())
    sp, other, tl = speech_tracks(project)
    if basis == 'dialogue' and not other:
        basis = 'mix'
    if basis == 'mix' and preview and os.path.exists(str(preview)):
        y = decode(preview)
        return y, f'mix (preview render {Path(preview).name})', str(preview)
    fp = tl.range_fingerprint(0, max(1, tl.frames), video=True, audio=True)
    folder = AUDIO_CACHE / fp
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f'{basis}.wav'
    key = (str(wav), basis)
    with _AUDIO_LOCK:
        if not refresh and key in _AUDIO_MEMO:
            return _AUDIO_MEMO[key]
    if refresh or not wav.exists():
        if basis == 'dialogue':
            var = _variant(project, sp)
            try:
                _melt_audio(var, wav, tl.seconds, name='dialogue')
            finally:
                Path(var).unlink(missing_ok=True)
        else:
            _melt_audio(project, wav, tl.seconds, name='mix')
    import soundfile
    y, sr = soundfile.read(str(wav), dtype='float32', always_2d=True)
    if sr != SR:
        raise RuntimeError(f'{wav}: {sr} Hz')
    desc = ('dialogue stem: melt render with only ' + ', '.join(sp) + ' heard (off: ' + ', '.join(other) + ')'
            if basis == 'dialogue' else 'mix: melt render of the timeline')
    out = (y, desc, str(wav))
    with _AUDIO_LOCK:
        _AUDIO_MEMO.clear() if len(_AUDIO_MEMO) > 6 else None
        _AUDIO_MEMO[key] = out
    _prune_audio_cache()
    return out


def _prune_audio_cache(keep=24):
    try:
        dirs = sorted((d for d in AUDIO_CACHE.iterdir() if d.is_dir() and d.name != 'variants'),
                      key=lambda d: d.stat().st_mtime, reverse=True)
        for d in dirs[keep:]:
            for f in d.iterdir():
                f.unlink(missing_ok=True)
            d.rmdir()
    except OSError:
        pass


_VIDEO_MEMO = {}


def video_audio(path, channels=2, sr=SR):
    """(float32 [n, channels] at sr, description) of a video file's own sound (memoised per process)."""
    key = (str(path), os.path.getsize(path), os.path.getmtime(path), channels, sr)
    with _AUDIO_LOCK:
        if key in _VIDEO_MEMO:
            return _VIDEO_MEMO[key]
    y = decode(path, channels=channels, sr=sr)
    with _AUDIO_LOCK:
        if len(_VIDEO_MEMO) > 4:
            _VIDEO_MEMO.clear()
        _VIDEO_MEMO[key] = (y, "the file's own sound")
    return _VIDEO_MEMO[key]


def to16(y):
    """Mono 16 kHz float64 from stereo/mono 48 kHz."""
    from scipy.signal import resample_poly
    mono = y.mean(axis=1) if y.ndim > 1 else y
    return resample_poly(mono.astype(np.float64), 1, 3)


# ------------------------------------------------------------------ measuring: pitch, energy, spectra

def _grid(n_samples, sr, hop=HOP):
    return int(n_samples / sr / hop) + 1


def _octave_clean(f0):
    """Fold octave jumps back onto the running median of the voiced frames (semitones), drop what doesn't fit and
    voiced runs shorter than 40 ms."""
    f = f0.copy()
    v = np.isfinite(f)
    if v.sum() < 10:
        return f
    st = np.full(len(f), np.nan)
    st[v] = 12 * np.log2(f[v] / 100.0)
    idx = np.flatnonzero(v)
    vals = st[idx]
    from scipy.ndimage import median_filter
    med = median_filter(vals, size=31, mode='nearest')
    d = vals - med
    for k in np.flatnonzero(np.abs(d) > 7.0):
        for shift in (-12.0, 12.0):
            if abs(d[k] + shift) < 3.0:
                vals[k] += shift
                break
        else:
            vals[k] = np.nan
    st[idx] = vals
    out = np.where(np.isfinite(st), 100.0 * 2 ** (st / 12.0), np.nan)
    # short voiced runs
    good = np.isfinite(out)
    run_start = None
    for k in range(len(out) + 1):
        if k < len(out) and good[k]:
            if run_start is None:
                run_start = k
        elif run_start is not None:
            if k - run_start < 4:
                out[run_start:k] = np.nan
            run_start = None
    return out


def _pitch_praat(x16, n, floor, ceiling):
    import parselmouth
    snd = parselmouth.Sound(x16, sampling_frequency=SR16)
    p = snd.to_pitch_ac(time_step=HOP, pitch_floor=float(floor), pitch_ceiling=float(ceiling))
    freq = p.selected_array['frequency']
    xs = np.asarray(p.xs())
    f0 = np.full(n, np.nan)
    if len(xs):
        idx = np.round((np.arange(n) * HOP - xs[0]) / HOP).astype(int)
        ok = (idx >= 0) & (idx < len(freq))
        f0[ok] = freq[idx[ok]]
    f0[~(f0 > 0)] = np.nan
    return f0


def _pitch_yin(x16, n, floor, ceiling, thr=0.15):
    """YIN (cumulative mean normalised difference) on the 10 ms grid, vectorised with FFTs."""
    W = int(0.025 * SR16)
    tmax = min(int(SR16 / floor) + 1, 2 * W)
    tmin = max(2, int(SR16 / ceiling))
    pad = np.concatenate([np.zeros(W // 2), x16, np.zeros(W + tmax + SR16 // 10)])
    f0 = np.full(n, np.nan)
    hop = int(HOP * SR16)
    L = W + tmax
    m = 1 << int(np.ceil(np.log2(L + W)))
    for b0 in range(0, n, 1500):
        ks = np.arange(b0, min(n, b0 + 1500))
        segs = np.stack([pad[k * hop:k * hop + L] for k in ks])
        if not segs.size:
            continue
        a = segs[:, :W]
        r = np.fft.irfft(np.fft.rfft(segs, m, axis=1) * np.conj(np.fft.rfft(a, m, axis=1)), m, axis=1)[:, :tmax]
        cs = np.cumsum(np.concatenate([np.zeros((len(ks), 1)), segs ** 2], axis=1), axis=1)
        e1 = cs[:, W:W + 1] - cs[:, 0:1]
        e2 = cs[:, W:W + tmax] - cs[:, 0:tmax]
        d = np.maximum(e1 + e2 - 2 * r, 0.0)
        d[:, 0] = 0.0
        cm = np.cumsum(d[:, 1:], axis=1)
        dn = np.ones_like(d)
        dn[:, 1:] = d[:, 1:] * np.arange(1, tmax) / np.maximum(cm, 1e-12)
        for j, k in enumerate(ks):
            row = dn[j]
            below = np.flatnonzero(row[tmin:] < thr)
            if not below.size:
                continue
            t = tmin + below[0]
            while t + 1 < tmax and row[t + 1] < row[t]:
                t += 1
            if 1 <= t < tmax - 1:
                a_, b_, c_ = row[t - 1], row[t], row[t + 1]
                den = a_ - 2 * b_ + c_
                t = t + (0.5 * (a_ - c_) / den if abs(den) > 1e-12 else 0.0)
            if e1[j, 0] > 1e-7:
                f0[k] = SR16 / t
    f0[(f0 < floor) | (f0 > ceiling)] = np.nan
    return f0


def pitch(x16, n=None, floor=None, ceiling=None, method='auto'):
    """(f0 Hz with nan where unvoiced on the 10 ms grid, info). Two passes: the second uses the speaker's own floor
    and ceiling from the first (0.75 x Q1, 2 x Q3)."""
    n = n or _grid(len(x16), SR16)
    use = method
    if method == 'auto':
        try:
            import parselmouth  # noqa: F401
            use = 'praat'
        except ImportError:
            use = 'yin'
    fn = _pitch_praat if use == 'praat' else _pitch_yin
    lo, hi = (floor or 60.0), (ceiling or 600.0)
    f0 = fn(x16, n, lo, hi)
    v = f0[np.isfinite(f0)]
    if floor is None and ceiling is None and v.size >= 50:
        q1, q3 = np.percentile(v, [25, 75])
        lo = max(50.0, math.floor(0.75 * q1 / 5) * 5)
        hi = min(800.0, max(lo * 3, math.ceil(2.0 * q3 / 5) * 5))
        f0 = fn(x16, n, lo, hi)
    f0 = _octave_clean(f0)
    v = f0[np.isfinite(f0)]
    info = {'method': ('Praat autocorrelation pitch via parselmouth' if use == 'praat'
                       else 'YIN (numpy) - parselmouth not installed'),
            'floor_hz': lo, 'ceiling_hz': hi, 'voiced_share': _r(float(np.isfinite(f0).mean()) if n else 0.0),
            'median_hz': _r(float(np.median(v)), 1) if v.size else None,
            'q1_hz': _r(float(np.percentile(v, 25)), 1) if v.size else None,
            'q3_hz': _r(float(np.percentile(v, 75)), 1) if v.size else None}
    return f0, info


def band_energy(x16, n=None, lo=80.0, hi=5000.0, win=0.03):
    """RMS level (dB re full scale) of the lo-hi band in Hann windows of `win` s centred on the 10 ms grid."""
    from scipy.signal import butter, sosfiltfilt
    n = n or _grid(len(x16), SR16)
    if len(x16) < 64:
        return np.full(n, -120.0)
    sos = butter(4, [lo, min(hi, SR16 / 2 - 100)], btype='band', fs=SR16, output='sos')
    y = sosfiltfilt(sos, x16)
    L = int(win * SR16)
    hop = int(HOP * SR16)
    pad = np.concatenate([np.zeros(L // 2), y, np.zeros(L + hop * 2)])
    w = np.hanning(L)
    frames = np.lib.stride_tricks.sliding_window_view(pad, L)[::hop][:n]
    rms = np.sqrt(np.mean((frames * w) ** 2, axis=1) / np.mean(w ** 2))
    out = 20 * np.log10(rms + 1e-10)
    if len(out) < n:
        out = np.concatenate([out, np.full(n - len(out), -120.0)])
    return out


def mel_bands(n_bands, fmin, fmax, nfft, sr):
    """Triangular mel filterbank [n_bands, nfft//2+1] and its centre frequencies."""
    def mel(f):
        return 2595 * np.log10(1 + f / 700.0)

    def imel(m):
        return 700 * (10 ** (m / 2595.0) - 1)
    pts = imel(np.linspace(mel(fmin), mel(fmax), n_bands + 2))
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    fb = np.zeros((n_bands, len(freqs)))
    for b in range(n_bands):
        l, c, r = pts[b], pts[b + 1], pts[b + 2]
        fb[b] = np.clip(np.minimum((freqs - l) / max(c - l, 1e-9), (r - freqs) / max(r - c, 1e-9)), 0, None)
    return fb, pts[1:-1]


def band_spectra(x16, n=None, n_bands=24, nfft=512):
    """Mel band levels (dB) every 10 ms (32 ms Hann windows), [n, n_bands], and the band centres (Hz)."""
    n = n or _grid(len(x16), SR16)
    hop = int(HOP * SR16)
    pad = np.concatenate([np.zeros(nfft // 2), x16, np.zeros(nfft + hop * 2)])
    frames = np.lib.stride_tricks.sliding_window_view(pad, nfft)[::hop][:n]
    spec = np.abs(np.fft.rfft(frames * np.hanning(nfft), axis=1)) ** 2
    fb, centres = mel_bands(n_bands, 60.0, 7600.0, nfft, SR16)
    out = 10 * np.log10(spec @ fb.T + 1e-12)
    if len(out) < n:
        out = np.concatenate([out, np.full((n - len(out), n_bands), -120.0)])
    return out, centres


def _rolling_percentile(x, q, half_s, step_s=0.5, mask=None):
    """Percentile q of x (10 ms grid) over +-half_s, computed every step_s and interpolated."""
    n = len(x)
    if not n:
        return x.copy()
    step = max(1, int(step_s / HOP))
    half = max(1, int(half_s / HOP))
    centres = np.arange(0, n, step)
    vals = []
    for c in centres:
        seg = x[max(0, c - half):c + half]
        if mask is not None:
            m = mask[max(0, c - half):c + half]
            seg = seg[m] if m.sum() >= 10 else seg
        vals.append(np.percentile(seg, q) if len(seg) else np.nan)
    vals = np.asarray(vals, dtype=float)
    good = np.isfinite(vals)
    if not good.any():
        return np.full(n, np.nan)
    return np.interp(np.arange(n), centres[good], vals[good])


# ------------------------------------------------------------------ words

_ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
         'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _number_words(k):
    if k < 20:
        return _ONES[k]
    if k < 100:
        return _TENS[k // 10] + ('' if k % 10 == 0 else ' ' + _ONES[k % 10])
    if k < 1000:
        return _ONES[k // 100] + ' hundred' + ('' if k % 100 == 0 else ' ' + _number_words(k % 100))
    if k < 10000 and 1100 <= k <= 2099 and k % 100:       # years: nineteen ninety
        return _number_words(k // 100) + ' ' + _number_words(k % 100)
    if k < 1000000:
        return _number_words(k // 1000) + ' thousand' + ('' if k % 1000 == 0 else ' ' + _number_words(k % 1000))
    return 'a big number'


def syllables(word):
    """Estimated English syllables of a transcript word (numbers spoken out; at least 1 for any word)."""
    w = re.sub(r"[^a-z0-9$%']", '', str(word).lower())
    if not w:
        return 0
    digits = re.sub(r'[^0-9]', '', w)
    if digits and len(digits) >= len(w.replace("'", '')) - 2:
        try:
            text = _number_words(int(digits[:7]))
        except ValueError:
            text = 'number'
        extra = (' dollars' if '$' in w else '') + (' percent' if '%' in w else '')
        return sum(syllables(p) for p in (text + extra).split())
    w = w.replace("'", '')
    n = len(re.findall(r'[aeiouy]+', w))
    if n > 1 and w.endswith('e') and not w.endswith(('le', 'ee', 'ye', 'ie')):
        n -= 1
    if n > 1 and w.endswith('ed') and not w.endswith(('ted', 'ded')):
        n -= 1
    if n > 1 and w.endswith('es') and not re.search(r'(s|z|x|ch|sh|ce|ge|se|ze)es$', w):
        n -= 1
    return max(1, n)


def _core(w):
    return re.sub(r"^[^\w']+|[^\w']+$", '', str(w)).lower()


def words_for(source, kind, script=None, transcribe=True):
    """([{w, t0, t1, p, id?, clip?}] in source/timeline seconds, how, warnings)."""
    warnings = []
    if kind == 'project':
        import letitedit.timeline.timeline_speech as tls
        if script is None:
            import letitedit.timeline.edit_script as es
            script = es.read(source)
        ws = tls.timeline_words(script)
        out = [{'w': w['w'].strip(), 't0': float(w['t0']), 't1': float(w['t1']), 'p': float(w.get('p', 1.0)),
                'id': w.get('id'), 'track': w.get('track')} for w in ws if w['w'].strip()]
        return out, 'timeline_speech.timeline_words (cached source transcripts mapped to the timeline)', warnings
    import letitedit.footage.speech as speech
    ws = speech.cached_words(source)
    how = 'speech.cached_words (cached transcript of the file)'
    if ws is None:
        if not transcribe:
            return [], 'no transcript cached (transcribe=False)', ['no cached transcript: words, stress and thought '
                                                                    'ends need one (speech.words)']
        # transcribing is the costly part (minutes on the CPU): only when a voice detector hears enough voice
        voice_s, dur = None, None
        try:
            import letitedit.sound.music as music
            voice_s = sum(b - a for a, b in music.voice_times(source))     # Silero VAD, cached per file
            dur = speech._duration(source)
        except Exception:  # noqa: BLE001 - no voice detector: transcribe as before
            voice_s = None
        if transcribe != 'force' and voice_s is not None and voice_s < max(1.0, 0.03 * (dur or 0.0)):
            return [], f'not transcribed: the voice detector hears {voice_s:.1f} s of voice', [
                f'little or no voice (Silero VAD: {voice_s:.1f} s of {dur or 0:.1f} s): not transcribed; pitch and '
                'energy only (settings transcribe: "force" transcribes anyway)']
        return _transcribed(speech, source)
    out = [{'w': w['w'].strip(), 't0': float(w['s']), 't1': float(w['e']), 'p': float(w.get('p', 1.0))}
           for w in ws if w['w'].strip()]
    return out, how, warnings


def _transcribed(speech, source):
    t = time.monotonic()
    ws = speech.words(source)
    how = f'speech.words (transcribed now in {time.monotonic() - t:.0f} s: {speech.engine()}; cached from now on)'
    out = [{'w': w['w'].strip(), 't0': float(w['s']), 't1': float(w['e']), 'p': float(w.get('p', 1.0))}
           for w in ws if w['w'].strip()]
    return out, how, []


def _join_pieces(ws):
    """Join transcriber pieces of one word ("two" "-hand", "it" "'s") as timeline_speech does."""
    out = []
    for w in ws:
        piece = w['w']
        if out and piece[:1] in "-'" and len(piece) > 1 and w['t0'] - out[-1]['t1'] < 0.15:
            out[-1] = dict(out[-1], w=out[-1]['w'] + piece, t1=w['t1'])
            continue
        out.append(dict(w))
    return out


# ------------------------------------------------------------------ the analysis

def _runs(mask):
    """[(start, end)] index runs where mask is true (end exclusive)."""
    if not len(mask):
        return []
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(np.int8))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def _close(mask, k):
    """Fill false runs shorter than k frames that sit between true runs."""
    out = mask.copy()
    for a, b in _runs(~mask):
        if b - a < k and a > 0 and b < len(mask):
            out[a:b] = True
    return out


def _open(mask, k, keep=None):
    """Drop true runs shorter than k frames (unless `keep` is true somewhere inside them)."""
    out = mask.copy()
    for a, b in _runs(mask):
        if b - a < k and not (keep is not None and keep[a:b].any()):
            out[a:b] = False
    return out


def activity(energy, f0, st):
    """Speech activity on the 10 ms grid: voiced, or at least activity_db over the local floor and activity_share of
    the way to the local speech level AND within activity_anchor_s of voicing (consonants sit next to vowels; a
    running machine, wind or a breath far from any voicing is not speech). Returns (mask, floor, speech_level,
    threshold)."""
    from scipy.ndimage import binary_dilation
    voiced = np.isfinite(f0)
    floor = _rolling_percentile(energy, 10, half_s=5.0)
    lvl_src = np.where(voiced, energy, np.nan)
    if voiced.sum() >= 20:
        level = _rolling_percentile(np.nan_to_num(lvl_src, nan=-120.0), 50, half_s=10.0, mask=voiced)
    else:
        level = _rolling_percentile(energy, 90, half_s=10.0)
    span = np.maximum(level - floor, 0.0)
    thr = floor + np.maximum(float(st['speech.activity_db']), float(st['speech.activity_share']) * span)
    k = max(1, int(round(float(st['speech.activity_anchor_s']) / HOP)))
    near_voice = binary_dilation(voiced, structure=np.ones(2 * k + 1, bool)) if voiced.any() else voiced
    act = voiced | ((energy >= thr) & near_voice)
    act = _open(_close(act, 5), 3, keep=voiced)
    return act, floor, level, thr


def refine_words(words, act, t_start, n, energy=None, floor=None, gap_s=0.15, grow_s=0.25, cuts=None, voiced=None):
    """Move each word's edges onto its sound. Transcript word spans often run over the pause after (or before) the
    word and touch the neighbour's span, so: inside the word's own span, sound islands (activity with gaps under
    gap_s closed) are found and the one with the most energy above the floor is the word; then each word grows over
    contiguous sound outside its island, up to grow_s and never into a neighbour's island nor across a cut (the
    sound on the other side of a cut is another recording). A word with no sound in its span keeps its transcript
    times and gets quiet=True."""
    k = lambda t: int(round((t - t_start) / HOP))  # noqa: E731
    gap = max(1, int(round(gap_s / HOP)))
    cut_k = sorted(k(float(c)) for c in (cuts or []))

    def walls(a, b):
        """The nearest cut frames at or before a and at or after b."""
        lo_w = max([c for c in cut_k if c <= a] or [0])
        hi_w = min([c for c in cut_k if c >= b] or [n])
        return lo_w, hi_w
    out = []
    for i, w in enumerate(words):
        a, b = k(w['t0']), max(k(w['t0']) + 1, k(w['t1']))
        wl, wh = walls(a, b)
        lo, hi = max(0, a, wl), min(n, b, wh)
        nw = dict(w, asr_t0=round(w['t0'], 3), asr_t1=round(w['t1'], 3), quiet=True)
        if hi > lo:
            seg = _close(act[lo:hi], gap)
            isl = _runs(seg)
            if isl:
                if energy is not None and floor is not None:
                    # voiced sound decides which island is the word (noise or a knock in a long transcript span
                    # must not win): unvoiced frames count a quarter
                    wv = np.where(voiced[lo:hi], 1.0, 0.25) if voiced is not None else np.ones(hi - lo)
                    mass = [float((np.maximum(energy[lo + s:lo + e] - floor[lo + s:lo + e], 0) * wv[s:e]).sum())
                            for s, e in isl]
                else:
                    mass = [e - s for s, e in isl]
                s, e = isl[int(np.argmax(mass))]
                nw['_a'], nw['_b'] = lo + s, lo + e
                nw['quiet'] = False
        out.append(nw)
    grow = int(round(grow_s / HOP))
    for i, w in enumerate(out):
        if w['quiet']:
            continue
        prev_b = next((out[j]['_b'] for j in range(i - 1, -1, -1) if not out[j]['quiet']), -1)
        next_a = next((out[j]['_a'] for j in range(i + 1, len(out)) if not out[j]['quiet']), n)
        a, b = w['_a'], w['_b']
        wl, wh = walls(a, b)
        a_lim = max(prev_b, a - grow, 0, wl)
        while a - 1 >= a_lim and act[a - 1]:
            a -= 1
        b_lim = min(next_a, b + grow, n, wh)
        while b < b_lim and act[b]:
            b += 1
        w['_a'], w['_b'] = a, b
        w['t0'], w['t1'] = t_start + a * HOP, t_start + b * HOP
    # keep order: no overlap with the neighbour (the boundary goes to the middle of the overlap)
    for i in range(1, len(out)):
        p, c = out[i - 1], out[i]
        if c['t0'] < p['t1']:
            mid = 0.5 * (max(c['t0'], p['t0']) + min(p['t1'], c['t1']))
            mid = min(max(mid, p['t0'] + HOP), c['t1'] - HOP) if c['t1'] - p['t0'] > 2 * HOP else mid
            p['t1'], c['t0'] = mid, mid
    for w in out:
        w.pop('_a', None)
        w.pop('_b', None)
        if w['t1'] <= w['t0']:
            w['t1'] = w['t0'] + HOP
        w['t0'], w['t1'] = round(w['t0'], 3), round(w['t1'], 3)
    return out


def _st(f0hz, ref=100.0):
    return 12 * np.log2(f0hz / ref)


def _robust_z(x, mask=None):
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x) if mask is None else (np.isfinite(x) & mask)
    if m.sum() < 3:
        return np.zeros_like(x)
    med = np.median(x[m])
    mad = np.median(np.abs(x[m] - med)) * 1.4826
    sd = mad if mad > 1e-6 else (np.std(x[m]) or 1.0)
    z = (x - med) / sd
    return np.where(np.isfinite(z), z, 0.0)


def _clip01(x):
    return min(1.0, max(0.0, float(x)))


def boundary_strength(m, incomplete=False, breath=False, settings=None):
    """(strength 0-1, cues present) of a word boundary from its measures m: pause_s, lengthening (last word's
    duration / its syllables' usual time), rate_ratio (last words' rate / the speaker's), reset_st (pitch after minus
    before, semitones), fall_st (last word's end pitch minus the unit's median, semitones). Graded cue scores:
    pause 0 at 100 ms to 1 at pause_full_s; slowing from lengthening 1-2x or rate ratio 1-0.5; reset 0-4 st;
    final lowering 0 to -3 st; breath 0/1. strength = weighted mean, minus incomplete_penalty after a word that
    can't end a phrase (when lexical is on)."""
    st = settings if settings and 'speech.thought_end.w_pause' in settings else settings_for(DEFAULTS, settings)
    g = float(m.get('pause_s') or 0.0)
    L = m.get('lengthening')
    rr = m.get('rate_ratio')
    rs = m.get('reset_st')
    fl = m.get('fall_st')
    s_pause = _clip01((g - 0.10) / max(1e-3, float(st['speech.thought_end.pause_full_s']) - 0.10))
    s_slow = max(_clip01(((L or 1.0) - 1.0) / 1.0), _clip01((1.0 - rr) / 0.5) if rr is not None else 0.0)
    s_reset = _clip01(rs / 4.0) if rs is not None else 0.0
    s_fall = _clip01(-fl / 3.0) if fl is not None else 0.0
    w = {k: float(st[f'speech.thought_end.w_{k}']) for k in ('pause', 'slowing', 'pitch_reset', 'final_lowering',
                                                              'breath')}
    tot = sum(w.values()) or 1.0
    strength = (w['pause'] * s_pause + w['slowing'] * s_slow + w['pitch_reset'] * s_reset
                + w['final_lowering'] * s_fall + w['breath'] * (1.0 if breath else 0.0)) / tot
    if incomplete and float(st['speech.thought_end.lexical']):
        strength = max(0.0, strength - float(st['speech.thought_end.incomplete_penalty']))
    cues = []
    if g >= float(st['speech.thought_end.pause_s']):
        cues.append('pause')
    if (L or 0) >= float(st['speech.thought_end.lengthening']) or (
            rr is not None and rr <= float(st['speech.thought_end.rate_ratio'])):
        cues.append('slowing')
    if rs is not None and rs >= float(st['speech.thought_end.reset_st']):
        cues.append('pitch_reset')
    if fl is not None and fl <= float(st['speech.thought_end.fall_st']):
        cues.append('final_lowering')
    if breath:
        cues.append('breath')
    return round(strength, 3), cues


def _analyse_breaths(act, bands, centres, energy, fps, k_of, n, pauses, st, start_s, voiced):
    # ---- breaths inside pauses
    breaths = []
    quiet_frames = ~act & ~voiced
    lo_b = centres < 250
    mid_b = (centres >= 400) & (centres <= 4000)
    for pi, p in enumerate(pauses):
        if p['dur'] < st['speech.breath.min_pause_s']:
            continue
        ka, kb = k_of(p['t0']) + 3, k_of(p['t1']) - 2
        if kb - ka < int(st['speech.breath.min_s'] / HOP):
            continue
        lo, hi = max(0, ka - 600), min(n, kb + 600)
        qm = quiet_frames[lo:hi]
        if qm.sum() < 20:
            continue
        qe = energy[lo:hi][qm]
        cutoff = np.percentile(qe, 25)
        ref_frames = bands[lo:hi][qm & (energy[lo:hi] <= cutoff)]
        if len(ref_frames) < 5:
            continue
        noise = np.median(ref_frames, axis=0)
        exc = bands[ka:kb] - noise
        ex_mid = exc[:, mid_b].mean(axis=1)
        ex_lo = exc[:, lo_b].mean(axis=1)
        cand = (ex_mid >= st['speech.breath.excess_db']) & (ex_mid >= ex_lo - 1.0) & ~voiced[ka:kb]
        cand = _close(cand, 4)
        best = None
        for a, b in _runs(cand):
            d = (b - a) * HOP
            if st['speech.breath.min_s'] <= d <= st['speech.breath.max_s']:
                strength = float(ex_mid[a:b].mean())
                if best is None or strength * d > best[2] * best[3]:
                    best = (a, b, strength, d)
        if not best:
            p['breath_check'] = {'found': False, 'why': 'no unvoiced 400-4000 Hz excess of '
                                 f"{st['speech.breath.excess_db']} dB lasting {st['speech.breath.min_s']}-"
                                 f"{st['speech.breath.max_s']} s"}
            continue
        a, b, strength, d = best
        run = ex_mid[a:b]
        jitter = float(np.median(np.abs(np.diff(run)))) if len(run) > 2 else 0.0
        breadth = float((exc[a:b][:, mid_b].mean(axis=0) >= 3.0).mean())
        plateau = float((run >= run.max() - 6.0).mean())
        ok = (jitter <= st['speech.breath.max_jitter_db'] and breadth >= st['speech.breath.min_breadth']
              and plateau >= st['speech.breath.min_plateau'])
        t0, t1 = start_s + (ka + a) * HOP, start_s + (ka + b) * HOP
        check = {'found': ok, 't0': round(t0, 3), 't1': round(t1, 3), 'excess_db': round(strength, 1),
                 'jitter_db': round(jitter, 2), 'breadth': round(breadth, 2), 'plateau': round(plateau, 2)}
        if not ok:
            check['why'] = ', '.join(w for w, bad in (
                ('impulsive (envelope jitter %.1f dB > %.1f)' % (jitter, st['speech.breath.max_jitter_db']),
                 jitter > st['speech.breath.max_jitter_db']),
                ('narrow-band (%.0f%% of 400-4000 Hz bands raised < %.0f%%)' % (100 * breadth,
                                                                              100 * st['speech.breath.min_breadth']),
                 breadth < st['speech.breath.min_breadth']),
                ('peaky (%.0f%% of frames near the peak < %.0f%%)' % (100 * plateau, 100 * st['speech.breath.min_plateau']),
                 plateau < st['speech.breath.min_plateau'])) if bad)
        p['breath_check'] = check
        if ok:
            breaths.append({'t0': round(t0, 3), 't1': round(t1, 3), 'dur': round(d, 3), 'f0': frame(t0, fps),
                            'f1': frame(t1, fps), 'excess_db': round(strength, 1), 'jitter_db': round(jitter, 2),
                            'breadth': round(breadth, 2), 'pause': pi, 'before_next_word_s': round(p['t1'] - t1, 3)})
            p['breath'] = len(breaths) - 1
    return breaths


def _analyse_boundaries(act, breaths, core, cut_ts, dur, dur_ratio, end_s, filler, fps, gaps_after, k_of, n,
        rate_med, st, st_all, syl, v_st, voiced, ws):
    # ---- thought ends: every word boundary scored on its cues
    ends = []
    vst = v_st if v_st.size else np.array([0.0])
    boundaries = []
    for i in range(len(ws)):
        last = i == len(ws) - 1
        g = gaps_after[i] if not last else (end_s - ws[i]['t1'])
        if filler[i] and not last:
            continue
        a = k_of(ws[i]['t1'])
        # pitch before: last 200 ms of voicing inside the last word (back to 0.5 s)
        seg_b = st_all[max(0, a - 50):a]
        vb = seg_b[np.isfinite(seg_b)][-20:]
        f_before = float(np.median(vb)) if vb.size >= 3 else None
        f_after = None
        if not last:
            b = k_of(ws[i + 1]['t0'])
            seg_a = st_all[b:min(n, b + 50)]
            va = seg_a[np.isfinite(seg_a)][:20]
            f_after = float(np.median(va)) if va.size >= 3 else None
        reset = (f_after - f_before) if (f_after is not None and f_before is not None) else None
        end_pct = float((vst < f_before).mean()) if f_before is not None else None
        # the unit's own level: voiced pitch over the 1.5 s before the boundary (declination-aware references)
        seg_u = st_all[max(0, a - 150):a]
        vu = seg_u[np.isfinite(seg_u)]
        unit_med = float(np.median(vu)) if vu.size >= 10 else None
        fall = (f_before - unit_med) if (f_before is not None and unit_med is not None) else None
        reset_unit = (f_after - unit_med) if (f_after is not None and unit_med is not None) else None
        end_pct_local = float((vu < f_before).mean()) if (f_before is not None and vu.size >= 10) else None
        # the word's last 150 ms: share of its sound (active frames) with no pitch (creak or devoicing)
        tail_a = max(k_of(ws[i]['t0']), a - 15)
        tail = act[tail_a:a]
        unvoiced_end = float((tail & ~voiced[tail_a:a]).sum() / max(1, tail.sum())) if tail.size and tail.sum() else None
        prev3 = [k for k in range(max(0, i - 2), i + 1) if not filler[k]] or [i]
        r3 = sum(syl[k] for k in prev3) / max(HOP, sum(dur[k] for k in prev3))
        rate_ratio = r3 / rate_med if rate_med > 0 else None
        lengthening = float(dur_ratio[i])
        incomplete = core[i] in CANT_END
        has_breath = any(not last and br['t0'] >= ws[i]['t1'] - 1e-3 and br['t1'] <= ws[i + 1]['t0'] + 1e-3
                         for br in breaths)
        m = {'pause_s': g, 'lengthening': lengthening, 'rate_ratio': rate_ratio, 'reset_st': reset, 'fall_st': fall}
        strength, cues = boundary_strength(m, incomplete, has_breath, st)
        t = ws[i]['t1']
        rec = {'t': round(t, 3), 'f': frame(t, fps), 'strength': round(strength, 3), 'cues': cues, 'word': i,
               'after': ws[i]['w'], 'text_end': ws[i]['w'][-1:] in '.?!',
               'space_after_s': None if last else round(g, 3),
               'incomplete_syntax': incomplete, 'end_of_speech': last,
               'measures': {'pause_s': _r(g), 'lengthening': _r(lengthening, 2),
                            'rate_ratio': _r(rate_ratio, 2), 'reset_st': _r(reset, 2), 'end_pct': _r(end_pct, 2),
                            'fall_st': _r(fall, 2), 'reset_unit_st': _r(reset_unit, 2),
                            'end_pct_local': _r(end_pct_local, 2), 'unvoiced_end': _r(unvoiced_end, 2)}}
        if not last:
            rec['next'] = ws[i + 1]['w']
            at = [c for c in cut_ts if ws[i]['t1'] - 1e-3 <= c <= ws[i + 1]['t0'] + 1e-3]
            if at:
                rec['cut'] = round(at[0], 3)
        brs = [k for k, br in enumerate(breaths) if not last and br['t0'] >= ws[i]['t1'] - 1e-3
               and br['t1'] <= ws[i + 1]['t0'] + 1e-3]
        if brs:
            rec['breath'] = brs[0]
        boundaries.append(rec)
        if strength >= st['speech.thought_end.min_strength'] or last:
            ends.append(rec)
    return ends, boundaries


def _analyse_speech_stats(boundaries, breaths, ends, filler, func, pauses, st, stress, ws):
    # ---- the stats the fine cut checks
    te_gaps = [e['space_after_s'] for e in ends if e['space_after_s'] is not None]
    long_inside = []
    for p in pauses:
        i = p['after_word']
        b = next((x for x in boundaries if x['word'] == i), None)
        if p['dur'] >= st['speech.long_pause_s'] and not ws[i]['w'][-1:] in '.?!,' and (
                func[i] or filler[i] or (b is not None and 'final_lowering' not in b['cues'])):
            long_inside.append({'t0': p['t0'], 't1': p['t1'], 'dur': p['dur'], 'after': ws[i]['w'],
                                'next': ws[i + 1]['w'], 'why': ('after a function word' if func[i] else
                                                                'after a filler' if filler[i] else
                                                                'no sentence punctuation and no final lowering')})
    resets = sorted([e['t'] for e in ends] + [b['t0'] for b in breaths])
    longest, at_ = 0.0, None
    if ws:
        marks = [ws[0]['t0']] + resets + [ws[-1]['t1']]
        for x, y in zip(marks, marks[1:]):
            if y - x > longest:
                longest, at_ = y - x, x
    stats = {'thought_end_gaps': {'n': len(te_gaps), 'mean_s': _r(np.mean(te_gaps)) if te_gaps else None,
                                  'sd_s': _r(np.std(te_gaps)) if te_gaps else None,
                                  'cv': _r(np.std(te_gaps) / np.mean(te_gaps), 2) if te_gaps and np.mean(te_gaps) > 0
                                  else None},
             'long_pauses_inside_thought': long_inside,
             'longest_without_end_or_breath_s': _r(longest), 'longest_starts_at': _r(at_),
             'no_reset_limit_s': st['speech.no_reset_s'],
             'words': len(ws), 'stressed': int((stress >= st['speech.stress.min']).sum()),
             'thought_ends': len(ends), 'pauses': len(pauses), 'breaths': len(breaths)}
    return stats


def _analyse_word_records(acoustic, dur_ratio, e_peak, f0_peak, f0_rng, filler, fps, func, k_of, rate,
        start_s, stress, syl, voiced, ws):
    words_out = []
    for i, w in enumerate(ws):
        ka_, kb_ = k_of(w['t0']), max(k_of(w['t0']) + 1, k_of(w['t1']))
        vv = np.flatnonzero(voiced[ka_:kb_])
        rec = {'t0': w['t0'], 't1': w['t1'], 'f0': frame(w['t0'], fps), 'f1': frame(w['t1'], fps), 'w': w['w'],
               'v0': round(start_s + (ka_ + vv[0]) * HOP, 3) if vv.size else None,
               'v1': round(start_s + (ka_ + vv[-1] + 1) * HOP, 3) if vv.size else None,
               'stress': round(float(stress[i]), 3), 'stress_acoustic': round(float(acoustic[i]), 3),
               'syll': syl[i], 'rate': round(float(rate[i]), 2),
               'measures': {'f0_peak_st': _r(f0_peak[i], 2), 'f0_range_st': _r(f0_rng[i], 2),
                            'energy_peak_db': _r(e_peak[i], 1), 'dur_ratio': _r(dur_ratio[i], 2)},
               'asr_t0': w['asr_t0'], 'asr_t1': w['asr_t1']}
        if filler[i]:
            rec['filler'] = True
        if func[i]:
            rec['function_word'] = True
        if w.get('quiet'):
            rec['quiet'] = True
        if (w['asr_t1'] - w['asr_t0']) > 1.5 + 0.3 * max(1, syl[i]):
            rec['timing'] = 'unreliable'       # the transcript stretched it over seconds: its edges are a guess
        for k in ('id', 'track', 'p'):
            if w.get(k) is not None:
                rec[k] = w[k]
        words_out.append(rec)
    return words_out


def analyse_audio(x16, words, start_s=0.0, settings=None, cuts=None, fps=30.0, with_series=True, pitch_method='auto',
                  walls=None):
    """The speech lane from a mono 16 kHz signal whose first sample is at `start_s` (timeline/file seconds) and words
    [{w, t0, t1}] in the same seconds. cuts: [{t, ...}] edit points to note on pauses (a project's cuts); walls:
    times where the sound changes recording (word edges never grow across them; default: the cuts)."""
    st = settings_for(DEFAULTS, settings)
    n = _grid(len(x16), SR16)
    f0, pinfo = pitch(x16, n, method=pitch_method)
    energy = band_energy(x16, n)
    bands, centres = band_spectra(x16, n)
    act, floor, level, thr = activity(energy, f0, st)
    voiced = np.isfinite(f0)
    end_s = start_s + len(x16) / SR16
    warnings = []
    ws = _join_pieces(sorted((w for w in words if w['t1'] > start_s and w['t0'] < end_s), key=lambda w: w['t0']))
    wall_src = walls if walls is not None else (cuts or [])
    cut_times = [float(c['t'] if isinstance(c, dict) else c) for c in wall_src]
    ws = refine_words(ws, act, start_s, n, energy=energy, floor=floor, cuts=cut_times, voiced=voiced)
    quiet = sum(1 for w in ws if w['quiet'])
    if quiet:
        warnings.append(f'{quiet} word(s) have no voiced or loud sound inside their transcript times '
                        '(kept at the transcript times; quiet=True)')

    def k_of(t):
        return int(min(n - 1, max(0, round((t - start_s) / HOP))))

    st_all = np.where(voiced, _st(np.where(voiced, f0, 100.0)), np.nan)
    v_st = st_all[voiced]
    sp_median = float(np.median(v_st)) if v_st.size else None

    # ---- per word measures
    syl = [syllables(w['w']) for w in ws]
    dur = np.array([max(HOP, w['t1'] - w['t0']) for w in ws])
    core = [_core(w['w']) for w in ws]
    filler = np.array([c in FILLERS for c in core], dtype=bool)
    func = np.array([c in FUNCTION_WORDS for c in core], dtype=bool)
    gaps_after = np.array([(ws[i + 1]['t0'] - ws[i]['t1']) if i + 1 < len(ws) else np.inf for i in range(len(ws))])
    gaps_before = np.array([(ws[i]['t0'] - ws[i - 1]['t1']) if i > 0 else np.inf for i in range(len(ws))])
    inner = (gaps_after < st['speech.pause_min_s']) & (gaps_before < st['speech.pause_min_s']) & ~filler
    syl_t = np.array([d / max(1, s) for d, s in zip(dur, syl)])
    syl_med = float(np.median(syl_t[inner])) if inner.sum() >= 5 else (float(np.median(syl_t[~filler])) if
                                                                        (~filler).sum() else 0.2)
    syl_med = min(max(syl_med, 0.08), 0.5)

    f0_peak, f0_rng, e_peak, f0_ref = [], [], [], []
    for i, w in enumerate(ws):
        a, b = k_of(w['t0']), max(k_of(w['t0']) + 1, k_of(w['t1']))
        lo, hi = max(0, a - 250), min(n, b + 250)
        loc = st_all[lo:hi]
        loc = loc[np.isfinite(loc)]
        ref = float(np.median(loc)) if loc.size >= 20 else sp_median
        seg = st_all[a:b]
        seg = seg[np.isfinite(seg)]
        f0_ref.append(ref)
        if seg.size >= 3 and ref is not None:
            f0_peak.append(float(np.percentile(seg, 90)) - ref)
            f0_rng.append(float(np.percentile(seg, 95) - np.percentile(seg, 5)))
        else:
            f0_peak.append(np.nan)
            f0_rng.append(np.nan)
        e_loc = energy[lo:hi][act[lo:hi]]
        e_ref = float(np.median(e_loc)) if e_loc.size >= 10 else float(np.median(energy[lo:hi]))
        e_peak.append(float(np.max(energy[a:b])) - e_ref if b > a else np.nan)
    f0_peak, f0_rng, e_peak = np.array(f0_peak), np.array(f0_rng), np.array(e_peak)
    dur_ratio = dur / (np.maximum(1, syl) * syl_med)
    # prominence: robust z-scores over the non-filler words, missing pitch counts as average
    ok = ~filler
    z = (st['speech.stress.w_f0'] * _robust_z(f0_peak, ok) + st['speech.stress.w_f0_range'] * _robust_z(f0_rng, ok)
         + st['speech.stress.w_energy'] * _robust_z(e_peak, ok)
         + st['speech.stress.w_duration'] * _robust_z(np.log(np.maximum(dur_ratio, 1e-3)), ok))
    wsum = (st['speech.stress.w_f0'] + st['speech.stress.w_f0_range'] + st['speech.stress.w_energy']
            + st['speech.stress.w_duration']) or 1.0
    prom = z / wsum
    acoustic = 1.0 / (1.0 + np.exp(-(prom - st['speech.stress.center_z']) / max(1e-3, st['speech.stress.scale_z'])))
    acoustic = np.where(filler, 0.0, acoustic)
    stress = np.where(func, acoustic * st['speech.stress.function_word_factor'], acoustic)

    # ---- runs of speech (split at pauses >= the thought-end pause) and the local rate
    runs, cur = [], [0] if ws else []
    for i in range(1, len(ws)):
        if gaps_after[i - 1] >= st['speech.thought_end.pause_s']:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    rate = np.zeros(len(ws))
    for r in runs:
        for j, i in enumerate(r):
            win = [r[k] for k in range(max(0, j - 2), min(len(r), j + 3)) if not filler[r[k]]] or [i]
            rate[i] = sum(syl[k] for k in win) / max(HOP, sum(dur[k] for k in win))
    rate_med = float(np.median(rate[~filler])) if (~filler).sum() else float(np.median(rate)) if len(rate) else 0.0

    # ---- pauses
    cut_ts = sorted(float(c['t'] if isinstance(c, dict) else c) for c in (cuts or []))
    pauses = []
    for i in range(len(ws) - 1):
        g = gaps_after[i]
        if g >= st['speech.pause_min_s']:
            a, b = ws[i]['t1'], ws[i + 1]['t0']
            ka, kb = k_of(a), k_of(b)
            inact = float(1.0 - act[ka:kb].mean()) if kb > ka else 1.0
            p = {'t0': round(a, 3), 't1': round(b, 3), 'dur': round(b - a, 3), 'f0': frame(a, fps), 'f1': frame(b, fps),
                 'after_word': i, 'silent_share': round(inact, 2)}
            at = [c for c in cut_ts if a - 1e-3 <= c <= b + 1e-3]
            if at:
                p['cut'] = round(at[0], 3)
            pauses.append(p)

    breaths = _analyse_breaths(act, bands, centres, energy, fps, k_of, n, pauses, st, start_s, voiced)

    ends, boundaries = _analyse_boundaries(act, breaths, core, cut_ts, dur, dur_ratio, end_s, filler, fps,
        gaps_after, k_of, n, rate_med, st, st_all, syl, v_st, voiced, ws)

    stats = _analyse_speech_stats(boundaries, breaths, ends, filler, func, pauses, st, stress, ws)

    words_out = _analyse_word_records(acoustic, dur_ratio, e_peak, f0_peak, f0_rng, filler, fps, func, k_of,
        rate, start_s, stress, syl, voiced, ws)

    out = {'method': (f"f0: {pinfo['method']} (10 ms, floor {pinfo['floor_hz']:.0f} Hz, ceiling "
                      f"{pinfo['ceiling_hz']:.0f} Hz from a first pass); energy: RMS dB of 80-5000 Hz, 30 ms Hann; "
                      'word edges moved onto voiced/active sound; thought ends: pause/slowing/pitch reset/final '
                      'lowering cues; stress: robust z of pitch peak, pitch range, energy peak, lengthening; breaths: '
                      '400-4000 Hz excess over the local noise spectrum inside pauses'),
           'version': LANE_VERSION, 'settings': st, 'warnings': warnings, 'unsupported': [],
           'hop_s': HOP, 't0': round(start_s, 3), 'n': n, 'fps': fps,
           'words': words_out, 'pauses': pauses, 'thought_ends': ends, 'boundaries': boundaries,
           'breaths': breaths, 'speech_rate': [round(float(x), 2) for x in rate],
           'stressed': [i for i in range(len(ws)) if stress[i] >= st['speech.stress.min']],
           'speaker': {'f0_median_hz': pinfo['median_hz'], 'f0_q1_hz': pinfo['q1_hz'], 'f0_q3_hz': pinfo['q3_hz'],
                       'f0_floor_hz': pinfo['floor_hz'], 'f0_ceiling_hz': pinfo['ceiling_hz'],
                       'voiced_share': pinfo['voiced_share'], 'rate_median_sps': _r(rate_med, 2),
                       'syllable_s': _r(syl_med, 3),
                       'speech_level_db': _r(float(np.median(level)), 1) if n else None,
                       'noise_floor_db': _r(float(np.median(floor)), 1) if n else None},
           'stats': stats}
    if with_series:
        out['f0'] = [None if not np.isfinite(v) else round(float(v), 1) for v in f0]
        out['energy'] = [round(float(v), 1) for v in energy]
        out['active'] = ''.join('1' if a else '0' for a in act)
        out['activity_threshold_db'] = [round(float(v), 1) for v in thr[::10]]     # every 100 ms
    return out


# ------------------------------------------------------------------ sources: projects and videos

def _cuts_of(source, kind, script=None, ctx_lanes=None):
    """(picture cuts to note on pauses, walls: times where the sound changes recording). Cuts: the store's edit lane
    when given, else a project's picture cuts. Walls: a project's speech-track sound joins, starts and ends (a J or L
    cut moves them off the picture cut); a video's cuts."""
    cuts = None
    if ctx_lanes and isinstance(ctx_lanes.get('edit'), dict) and ctx_lanes['edit'].get('cuts') is not None:
        cuts = ctx_lanes['edit']['cuts']
    if kind == 'project':
        try:
            import letitedit.timing.joins as joins
            pts = joins.project_edit_points(source, script)
            walls = [j['t'] for j in pts['sound_joins'] if j['speech']]
            return (cuts if cuts is not None else pts['cuts']), walls
        except Exception:  # noqa: BLE001
            return (cuts or []), None
    return (cuts or []), None


def _fps_of(source, kind):
    if kind == 'project':
        import letitedit.timeline.timeline_model as tm
        return float(tm.load(source).fps)
    try:
        import letitedit.footage.shots as shots
        return float(shots.probe(source)['fps'])
    except Exception:  # noqa: BLE001
        return 30.0


def speech_audio(source, kind, preview=None, basis='auto'):
    """(mono float64 at 16 kHz, description, path) for the speech lane: a project's dialogue stem when a
    music/effects track is heard (pitch and energy of speech under music are unreliable), else its mix; a video's
    own sound."""
    if kind == 'project':
        if basis == 'auto':
            sp, other, _ = speech_tracks(source)
            basis = 'dialogue' if other else 'mix'
        y, desc, path = project_audio(source, basis=basis, preview=preview if basis == 'mix' else None)
        return (None if y is None else to16(y)), desc, path
    y, desc = video_audio(source, channels=1, sr=SR16)
    return (None if y is None else y[:, 0].astype(np.float64)), desc + ' (16 kHz mono)', str(source)


def _wav16(wav, offset_s=0.0):
    """Mono 16 kHz of a 48 kHz WAV (the store's preview sound), zero-padded by offset_s at the start."""
    import soundfile
    y, sr = soundfile.read(str(wav), dtype='float32', always_2d=True)
    if sr != SR:
        from scipy.signal import resample_poly
        y = resample_poly(y, SR, sr, axis=0).astype(np.float32)
    x = to16(y)
    if offset_s > 0:
        x = np.concatenate([np.zeros(int(round(offset_s * SR16))), x])
    return x


def lane(ctx):
    """The 'speech' lane for timing_signals (TIMING-SPEC: register_lane(name, compute)). Settings: the store's
    merged 'speech.*' settings (short keys) and the caller's overrides; basis 'auto' | 'mix' | 'dialogue';
    transcribe (True)."""
    kind = ctx.get('kind') or kind_of(ctx['source'])
    source = ctx.get('project') or ctx['source']
    s_all = ctx.get('settings') if isinstance(ctx.get('settings'), dict) else {}
    settings = {k: v for k, v in s_all.items() if not isinstance(v, dict)}
    settings.update(s_all.get('speech') or {})
    basis = settings.pop('basis', 'auto')
    transcribe = settings.pop('transcribe', True)
    fps = float(ctx.get('fps') or _fps_of(source, kind))
    timings = {}
    t = time.monotonic()
    # words first: a project with no words on the timeline (a montage of muted clips) needs no dialogue stem, a
    # video with no voice needs no transcription
    ws, how, w_warn = words_for(source, kind, script=ctx.get('script'), transcribe=transcribe)
    timings['words_s'] = round(time.monotonic() - t, 2)
    t = time.monotonic()
    if kind == 'project' and basis == 'auto':
        basis = 'dialogue' if (ws and speech_tracks(source)[1]) else 'mix'
    if kind == 'project' and basis == 'mix' and ctx.get('audio') and os.path.exists(str(ctx['audio'])):
        f0 = int((ctx.get('range') or [0])[0] or 0)
        y = _wav16(ctx['audio'], f0 / fps)
        desc = f"mix: the timing store's preview render ({Path(str(ctx['audio'])).name})"
    else:
        y, desc, _ = speech_audio(source, kind, preview=None, basis=basis)
    timings['sound_s'] = round(time.monotonic() - t, 2)
    warnings = list(w_warn)
    if y is None or not len(y):
        return {'method': 'no sound', 'version': LANE_VERSION, 'settings': settings, 'warnings': ['no sound'],
                'unsupported': ['speech: the source has no sound'], 'words': [], 'pauses': [], 'f0': [], 'energy': [],
                'thought_ends': [], 'breaths': [], 'speech_rate': [], 'hop_s': HOP, 't0': 0.0, 'timings': timings}
    t = time.monotonic()
    cuts, walls = _cuts_of(source, kind, ctx.get('script'), ctx.get('lanes'))
    out = analyse_audio(y, ws, 0.0, settings, cuts=cuts, fps=fps, walls=walls)
    timings['analysis_s'] = round(time.monotonic() - t, 2)
    out['timings'] = timings
    out['audio_basis'] = desc
    out['words_from'] = how
    out['warnings'] = warnings + out['warnings']
    if not ws:
        out['unsupported'].append('speech: no words with times (no transcript): pitch and energy only')
    return out


lane.defaults = {k.split('.', 1)[1]: v for k, v in DEFAULTS.items()}     # the store reads these (cache identity)


def analyse(source, start=None, end=None, settings=None, refresh=False, transcribe=True, basis='auto'):
    """The speech lane for a project (.mlt) or video, standalone (no store needed), with the contract fields.
    start/end (seconds) limit what is reported; the whole source is measured once and cached."""
    source = str(Path(source).resolve())
    kind = kind_of(source)
    t_begin = time.monotonic()
    st = settings_for(DEFAULTS, settings)
    if kind == 'project':
        import letitedit.timeline.timeline_model as tm
        tl = tm.load(source)
        key = tl.range_fingerprint(0, max(1, tl.frames), video=True, audio=True)
        fps, duration = float(tl.fps), tl.seconds
    else:
        key = fingerprint(source)
        fps = _fps_of(source, kind)
        duration = None
    cache = AUDIO_CACHE / key / f'speech-v{LANE_VERSION}-{_hash([st, basis, transcribe, _CODE_KEY])}.json'
    data = None
    if not refresh and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding='utf-8-sig'))
        except ValueError:
            data = None
    if data is None:
        ctx = {'source': source, 'kind': kind, 'video': None if kind == 'project' else source, 'fps': fps,
               'project': source if kind == 'project' else None, 'script': None, 'lanes': {},
               'settings': {'speech': dict(settings or {}, basis=basis, transcribe=transcribe)}}
        data = lane(ctx)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        os.replace(tmp, cache)
    if duration is None:
        duration = data.get('n', 0) * HOP
    out = clip_lane(data, start, end)
    checked = [[_r(start or 0.0), _r(end if end is not None else duration)]]
    res = contract(source, kind, checked=checked, warnings=out.get('warnings'), unsupported=out.get('unsupported'),
                   extra={'kind': kind, 'fps': fps, 'duration_s': _r(duration), 'seconds': _r(time.monotonic() - t_begin, 2),
                          'cache': str(cache)})
    res['lane'] = out
    return res


def clip_lane(data, start=None, end=None):
    """The lane limited to start-end seconds (series sliced, events kept when they overlap)."""
    if start is None and end is None:
        return data
    lo = float(start or 0.0)
    hi = float(end) if end is not None else float('inf')
    out = dict(data)
    t0 = float(data.get('t0', 0.0))
    if data.get('f0') is not None:
        a = max(0, int(round((lo - t0) / HOP)))
        b = len(data['f0']) if hi == float('inf') else max(a, int(round((hi - t0) / HOP)))
        for k in ('f0', 'energy'):
            if data.get(k) is not None:
                out[k] = data[k][a:b]
        if data.get('active'):
            out['active'] = data['active'][a:b]
        out['t0'] = round(t0 + a * HOP, 3)
    keep = [i for i, w in enumerate(data.get('words', [])) if w['t1'] > lo and w['t0'] < hi]
    out['words'] = [data['words'][i] for i in keep]
    out['speech_rate'] = [data['speech_rate'][i] for i in keep] if data.get('speech_rate') else []
    idx = {i: j for j, i in enumerate(keep)}
    out['stressed'] = [idx[i] for i in data.get('stressed', []) if i in idx]
    for k in ('pauses', 'breaths'):
        out[k] = [x for x in data.get(k, []) if x['t1'] > lo and x['t0'] < hi]
    for k in ('thought_ends', 'boundaries'):
        out[k] = [x for x in data.get(k, []) if lo <= x['t'] <= hi]
    out['range'] = [lo, None if hi == float('inf') else hi]
    return out


# ------------------------------------------------------------------ the view

def _key_lines(lane_data, key_lines):
    """Match key lines (phrases, or {t}/{at} times) to thought ends: [{line, t, space_after_s, end}]."""
    out = []
    ws = lane_data.get('words', [])
    texts = [_core(w['w']) for w in ws]
    ends = lane_data.get('thought_ends', [])
    for kl in key_lines or []:
        t = None
        label = kl
        if isinstance(kl, dict):
            t = kl.get('t', kl.get('at'))
            label = kl.get('text') or kl.get('line') or str(t)
            if t is None and label:
                kl = label
        if t is None and isinstance(kl, str):
            want = [_core(x) for x in kl.split() if _core(x)]
            for i in range(len(texts) - len(want) + 1):
                if want and texts[i:i + len(want)] == want:
                    t = ws[i + len(want) - 1]['t1']
                    break
        if t is None:
            out.append({'line': label, 'found': False})
            continue
        t = float(t)
        e = min(ends, key=lambda e: abs(e['t'] - t)) if ends else None
        nxt = next((w for w in ws if w['t0'] >= t - 1e-3), None)
        space = (nxt['t0'] - t) if nxt else None
        out.append({'line': label, 'found': True, 't': round(t, 3), 'space_after_s': _r(space),
                    'thought_end': e if e and abs(e['t'] - t) < 0.4 else None})
    return out


CUE_LETTERS = {'pause': 'P', 'slowing': 'S', 'pitch_reset': 'R', 'final_lowering': 'L', 'breath': 'B'}


def _speech_header(d, title, sp, med, lane_data, fT, fS):
    """Draws the title, the legend and the speaker's measured levels at the top of the speech view."""
    d.text((10, 6), title or 'speech', fill=(0, 0, 0), font=fT)
    legend = ('pitch: black line (Hz, log scale, dashed = speaker median {:.0f} Hz) | energy: grey area (dB) | '
              'STRESSED word = bold red | grey box = pause (ms) | blue line = thought end (strength; P pause, '
              'S slowing, R pitch reset, L final lowering, B breath; lower case = seen but weight 0; ->s = space '
              'after) | green "br" = breath | magenta dashes = cut').format(med)
    d.text((10, 30), legend, fill=(60, 60, 60), font=fS)
    d.text((10, 45), (f"rate median {sp.get('rate_median_sps')} syll/s, pitch {sp.get('f0_q1_hz')}-"
                      f"{sp.get('f0_q3_hz')} Hz (Q1-Q3), noise floor {sp.get('noise_floor_db')} dB, speech "
                      f"{sp.get('speech_level_db')} dB; {lane_data.get('audio_basis', '')}")[:230],
           fill=(60, 60, 60), font=fS)


def _speech_pauses(d, pauses, a, b, X, P0, W0, E1, fS):
    """Draws the row's pauses as grey boxes, with their length in ms from a quarter second up."""
    for p in pauses:
        if p['t1'] < a or p['t0'] > b:
            continue
        x0, x1 = X(max(a, p['t0'])), X(min(b, p['t1']))
        d.rectangle((x0, P0 + 1, x1, W0 + 92), fill=(238, 238, 238))
        if p['dur'] >= 0.25:
            d.text((x0 + 2, E1 - 14), f"{int(round(p['dur'] * 1000))}ms", fill=(90, 90, 90), font=fS)


def _speech_energy(d, en, a, b, t0, X, L, E0, E1, fS):
    """Draws the row's energy as a grey area scaled to the 99th percentile and 50 dB below it."""
    if en:
        ka, kb = max(0, int((a - t0) / HOP)), min(len(en), int((b - t0) / HOP) + 1)
        seg = np.asarray(en[ka:kb], dtype=float)
        if seg.size:
            top = float(np.percentile(np.asarray(en), 99)) if en else -10.0
            bot = top - 50.0
            pts = [(X(t0 + (ka + k) * HOP), E1 - (min(max(v, bot), top) - bot) / (top - bot) * (E1 - E0))
                   for k, v in enumerate(seg)]
            d.polygon([(pts[0][0], E1)] + pts + [(pts[-1][0], E1)], fill=(190, 190, 190))
            d.text((L + 2, E0), f'{top:.0f} dB', fill=(120, 120, 120), font=fS)


def _speech_pitch(d, f0, n, a, b, t0, X, Yp, fmin, fmax):
    """Draws the row's pitch as a black line, broken where there is no pitch or it is out of range."""
    if f0:
        ka, kb = max(0, int((a - t0) / HOP)), min(n, int((b - t0) / HOP) + 1)
        prev = None
        for k in range(ka, kb):
            v = f0[k]
            if v is None or not (fmin <= v <= fmax * 1.05):
                prev = None
                continue
            pt = (X(t0 + k * HOP), Yp(min(max(v, fmin), fmax)))
            if prev is not None:
                d.line((prev, pt), fill=(0, 0, 0), width=3)
            prev = pt


def _speech_breaths(d, breaths, a, b, X, E0, E1, fWb):
    """Draws the row's breaths as green boxes marked br."""
    for br in breaths:
        if br['t1'] < a or br['t0'] > b:
            continue
        x0, x1 = X(max(a, br['t0'])), X(min(b, br['t1']))
        d.rectangle((x0, E0 + 2, x1, E1 - 2), outline=(0, 150, 0), width=3)
        d.text((x0 + 2, E0 + 16), 'br', fill=(0, 130, 0), font=fWb)


def _speech_cuts(d, cut_ts, a, b, X, P0, W0, fps, fS):
    """Draws the row's cuts as magenta dashes with their frame numbers."""
    for c in cut_ts:
        if a <= c <= b:
            xx = X(c)
            for yy in range(int(P0), int(W0 + 100), 10):
                d.line((xx, yy, xx, yy + 5), fill=(220, 0, 220), width=2)
            d.text((xx + 3, W0 + 78), f'cut f{frame(c, fps)}', fill=(200, 0, 200), font=fS)


def _speech_words(d, words, a, b, X, W0, stress_min, fW, fWb):
    """Writes the row's words on two lines (stressed ones bold red and underlined, fillers grey)."""
    line_end = [-1e9, -1e9]
    for i, w in enumerate(words):
        if w['t1'] < a or w['t0'] > b:
            continue
        strong = w['stress'] >= stress_min
        font = fWb if strong else fW
        txt = w['w']
        tw = d.textlength(txt, font=font)
        x = X(max(a, w['t0']))
        lane_i = 0 if x > line_end[0] + 4 else 1 if x > line_end[1] + 4 else (0 if line_end[0] < line_end[1] else 1)
        yy = W0 + 6 + lane_i * 24
        col = (200, 0, 0) if strong else (110, 110, 110) if w.get('filler') else (0, 0, 0)
        d.line((X(w['t0']), W0 + 2, X(w['t1']), W0 + 2), fill=(col if strong else (160, 160, 160)), width=3)
        d.text((x, yy), txt, fill=col, font=font)
        if strong:
            d.line((x, yy + 19, x + tw, yy + 19), fill=col, width=2)
        line_end[lane_i] = x + tw


def _speech_thought_ends(d, ends, a, b, X, P0, W0, keyed, lane_data, fWb, fS):
    """Draws the row's thought ends as blue lines with strength, cues, the space after and KEY for key
    lines."""
    for e in ends:
        if not (a <= e['t'] <= b):
            continue
        xx = X(e['t'])
        heavy = round(e['t'], 2) in keyed
        d.line((xx, P0, xx, W0 + 70), fill=(0, 70, 220), width=4 if heavy else 2)
        sts = lane_data.get('settings') or {}
        cue = ''.join(CUE_LETTERS.get(c, '?') if float(sts.get(f'speech.thought_end.w_{c}', 1) or 0) > 0
                      else CUE_LETTERS.get(c, '?').lower() for c in e['cues'])
        lab = f"{e['strength']:.2f} {cue}"
        d.text((xx + 3, P0 + 2), lab, fill=(0, 70, 220), font=fWb)
        if e.get('space_after_s') is not None:
            d.text((xx + 3, P0 + 20), f"->{e['space_after_s']:.2f}s", fill=(0, 70, 220), font=fS)
        if heavy:
            d.text((xx + 3, P0 + 34), 'KEY', fill=(0, 70, 220), font=fWb)


def _speech_time_axis(d, a, b, X, L, R, W0, width, fps, fS):
    """Draws the row's time axis with a tick, clock time and frame number every second."""
    ty = W0 + 96
    d.line((L, ty, width - R, ty), fill=(0, 0, 0))
    k0 = int(math.ceil(a))
    for s in range(k0, int(b) + 1):
        xx = X(s)
        d.line((xx, ty, xx, ty + 6), fill=(0, 0, 0))
        d.text((xx - 18, ty + 7), f'{clock(s)[:-3]} f{frame(s, fps)}', fill=(0, 0, 0), font=fS)


def render(lane_data, out_png, start_s=None, end_s=None, row_s=10.0, cuts=None, title='', key_lines=None, width=1600):
    """Draw the speech view: per row (row_s seconds) pitch (semitones, labelled in Hz), energy, the words (stressed
    ones bold red), pauses (grey, ms), thought ends (blue lines with strength and cues), breaths (green), cuts
    (magenta dashes) and the space after each thought end."""
    from PIL import Image, ImageDraw
    t0 = float(lane_data.get('t0', 0.0))
    f0 = lane_data.get('f0') or []
    en = lane_data.get('energy') or []
    n = len(f0)
    lo = float(start_s) if start_s is not None else t0
    hi = float(end_s) if end_s is not None else t0 + n * HOP
    hi = max(hi, lo + 1.0)
    rows = max(1, int(math.ceil((hi - lo) / row_s - 1e-6)))
    L, R = 70, 20
    ROW_H = 300
    HEAD = 64
    im = Image.new('RGB', (width, HEAD + rows * ROW_H + 30), (255, 255, 255))
    d = ImageDraw.Draw(im)
    fT, fW, fWb, fS = _font(17, True), _font(15), _font(15, True), _font(12)
    sp = lane_data.get('speaker', {})
    med = sp.get('f0_median_hz') or 120.0
    _speech_header(d, title, sp, med, lane_data, fT, fS)
    fmin = max(40.0, (sp.get('f0_floor_hz') or 60.0))
    fmax = max(fmin * 2, (sp.get('f0_ceiling_hz') or 400.0))
    words = lane_data.get('words', [])
    pauses = lane_data.get('pauses', [])
    ends = lane_data.get('thought_ends', [])
    breaths = lane_data.get('breaths', [])
    cut_ts = sorted(float(c['t'] if isinstance(c, dict) else c) for c in (cuts or []))
    stress_min = (lane_data.get('settings') or {}).get('speech.stress.min', 0.6)
    fps = lane_data.get('fps') or 30.0
    keyed = {round(k['t'], 2) for k in (key_lines or []) if k.get('found')}
    for r in range(rows):
        a = lo + r * row_s
        b = min(hi, a + row_s)
        y0 = HEAD + r * ROW_H
        P0, P1 = y0 + 8, y0 + 128           # pitch panel
        E0, E1 = y0 + 132, y0 + 182         # energy panel
        W0 = y0 + 188                       # words strip
        X = lambda t: L + (t - a) / row_s * (width - L - R)  # noqa: E731

        def Yp(hz):
            return P1 - (math.log(hz / fmin) / math.log(fmax / fmin)) * (P1 - P0)
        d.rectangle((L, P0, width - R, E1), outline=(200, 200, 200))
        for hz in (60, 80, 100, 120, 150, 200, 250, 300, 400, 500):
            if fmin <= hz <= fmax:
                yy = Yp(hz)
                d.line((L, yy, width - R, yy), fill=(235, 235, 235))
                d.text((L - 34, yy - 7), f'{hz}', fill=(120, 120, 120), font=fS)
        if fmin <= med <= fmax:
            yy = Yp(med)
            for xx in range(L, width - R, 12):
                d.line((xx, yy, xx + 6, yy), fill=(150, 150, 150))
        d.text((4, P0), 'Hz', fill=(120, 120, 120), font=fS)
        d.text((4, E0 + 14), 'dB', fill=(120, 120, 120), font=fS)
        _speech_pauses(d, pauses, a, b, X, P0, W0, E1, fS)          # first: behind everything
        _speech_energy(d, en, a, b, t0, X, L, E0, E1, fS)
        _speech_pitch(d, f0, n, a, b, t0, X, Yp, fmin, fmax)
        _speech_breaths(d, breaths, a, b, X, E0, E1, fWb)
        _speech_cuts(d, cut_ts, a, b, X, P0, W0, fps, fS)
        _speech_words(d, words, a, b, X, W0, stress_min, fW, fWb)
        _speech_thought_ends(d, ends, a, b, X, P0, W0, keyed, lane_data, fWb, fS)
        _speech_time_axis(d, a, b, X, L, R, W0, width, fps, fS)
    im.save(out_png)
    return str(out_png)


def view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'speech' view (timing_views.register_view): images of the words with pitch and energy, thought ends,
    stressed words, breaths and the space after key lines, plus the numbers. options: row_s (10), rows_per_image (3),
    max_images (4), key_lines (phrases or {t}), settings, out_dir, basis ('auto'|'mix'|'dialogue')."""
    options = dict(options or {})
    source = str(Path(source).resolve())
    kind = kind_of(source)
    lane_data, base = None, None
    try:
        import letitedit.timing.timing_signals as timing_signals
        sset = options.get('settings')
        if sset and 'speech' not in sset:
            sset = {'speech': sset}
        sig = timing_signals.signals(source, start_s, end_s, lanes=['speech'], settings=sset,
                                     refresh=['speech'] if options.get('refresh') else False)
        lane_data = sig['lanes']['speech']
        if lane_data.get('error'):
            raise RuntimeError(lane_data['error'])
        base = {k: sig.get(k) for k in ('fps', 'duration_s', 'project_revision', 'source_fingerprints')}
        if cuts is None:
            cuts = (sig['lanes'].get('edit') or {}).get('cuts')
    except Exception:  # noqa: BLE001 - no store (yet) or it failed: measure here
        lane_data = None
    if lane_data is None:
        flat = options.get('settings') or {}
        flat = flat.get('speech', flat) if isinstance(flat, dict) else None
        res = analyse(source, start_s, end_s, settings=flat, basis=options.get('basis', 'auto'),
                      refresh=bool(options.get('refresh')))
        lane_data = res['lane']
        base = {'fps': res['fps'], 'duration_s': res['duration_s']}
    else:
        lane_data = clip_lane(lane_data, start_s, end_s)
    if cuts is None and kind == 'project':
        cuts = _cuts_of(source, kind)[0]
    if items:
        try:
            import letitedit.timing.joins as joins
            pts = joins.project_edit_points(source)
            spans = [(it['t0'], it['t1']) for it in pts['items'] if it.get('id') in set(items)]
            if spans:
                start_s = min(s for s, _ in spans) if start_s is None else start_s
                end_s = max(e for _, e in spans) if end_s is None else end_s
                lane_data = clip_lane(lane_data, start_s, end_s)
        except Exception:  # noqa: BLE001
            pass
    out_dir = Path(options.get('out_dir') or (CACHE / 'views' / 'timing-speech'))
    out_dir.mkdir(parents=True, exist_ok=True)
    row_s = float(options.get('row_s', 10.0))
    per = int(options.get('rows_per_image', 3))
    t_lo = float(start_s) if start_s is not None else float(lane_data.get('t0', 0.0))
    t_hi = float(end_s) if end_s is not None else t_lo + len(lane_data.get('f0') or []) * HOP
    kl = _key_lines(lane_data, options.get('key_lines'))
    images = []
    span = row_s * per
    nimg = max(1, int(math.ceil((t_hi - t_lo) / span - 1e-6)))
    limit = int(options.get('max_images', 4))
    if options.get('images') == 0:              # numbers only
        limit = 0
    stem = f'{Path(source).stem}-{_hash([source, t_lo, t_hi, row_s, per])}'
    for k in range(min(nimg, limit)):
        a = t_lo + k * span
        b = min(t_hi, a + span)
        png = out_dir / f'{stem}-{k + 1}.png'
        render(lane_data, png, a, b, row_s=row_s, cuts=cuts,
               title=f'speech | {Path(source).name} | {clock(a)}-{clock(b)} ({k + 1}/{nimg})', key_lines=kl)
        images.append(str(png))
    unchecked = ([{'t0': _r(t_lo + limit * span), 't1': _r(t_hi), 'why': 'not drawn (max_images); the numbers cover it'}]
                 if nimg > limit and limit > 0 else [])
    data = {'view': 'speech', 'images': images, 'key_lines': kl, 'stats': lane_data.get('stats'),
            'options_used': {'row_s': row_s, 'rows_per_image': per, 'max_images': limit,
                             'key_lines': options.get('key_lines'), 'basis': options.get('basis', 'auto'),
                             'settings': options.get('settings') or {}},
            'speaker': lane_data.get('speaker'), 'audio_basis': lane_data.get('audio_basis'),
            'method': lane_data.get('method'), 'thresholds': {k: v for k, v in (lane_data.get('settings') or {}).items()}}
    if detail == 'full':
        data['lane'] = {k: v for k, v in lane_data.items() if k not in ('f0', 'energy', 'active')}
    else:
        data['thought_ends'] = [{k: e[k] for k in ('t', 'f', 'strength', 'cues', 'after', 'space_after_s', 'text_end')
                                 if k in e} for e in lane_data.get('thought_ends', [])]
        data['stressed_words'] = [{'w': w['w'], 't': w['t0'], 'f': w['f0'], 'stress': w['stress']}
                                  for w in lane_data.get('words', []) if w['stress'] >= (lane_data.get('settings') or
                                                                                       {}).get('speech.stress.min', 0.6)]
        data['breaths'] = lane_data.get('breaths', [])
        data['long_pauses'] = [p for p in lane_data.get('pauses', []) if p['dur'] >= 0.6]
    res = contract(source, kind, checked=[[_r(t_lo), _r(t_hi)]], unchecked=unchecked,
                   warnings=lane_data.get('warnings'), unsupported=lane_data.get('unsupported'),
                   artifacts=images, extra=base)
    res.update(data)
    return res


# ------------------------------------------------------------------ registration

VIEW_SUMMARY = ('words along time with pitch and energy curves, thought ends (pause, slowing, pitch reset), stressed '
                'words, breaths and the space after key lines')
_REGISTERED = {'lane': False, 'view': False}


def register():
    """Register the 'speech' lane and view with the store and the view registry when they are importable (called at
    import; safe to call again)."""
    if not _REGISTERED['lane']:
        try:
            import letitedit.timing.timing_signals as timing_signals
            if hasattr(timing_signals, 'register_lane'):
                try:      # the edit lane's cuts are used when they are there anyway (never computed just for this)
                    timing_signals.register_lane(LANE, lane, depends=(), version=LANE_VERSION, optional=('edit',))
                except TypeError:
                    timing_signals.register_lane(LANE, lane, depends=(), version=LANE_VERSION)
                _REGISTERED['lane'] = True
        except Exception:  # noqa: BLE001 - no store yet: analyse() works on its own
            pass
    if not _REGISTERED['view']:
        try:
            import letitedit.timing.timing_views as timing_views
            if hasattr(timing_views, 'register_view'):
                timing_views.register_view('speech', view, VIEW_SUMMARY)
                _REGISTERED['view'] = True
        except Exception:  # noqa: BLE001
            pass
    return dict(_REGISTERED)


register()
