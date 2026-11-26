"""Measure a rendered video and write checks.json + report.md. The editor never grades itself: this does.

python gate.py <video.mp4> [--kind short|long] [--mode story|tutorial|interview|documentary|product|travel|montage|
               creative] [--driver dialogue|narration|music|visual|sound] [--deliverable web|podcast|broadcast]
               [--platforms tiktok,youtube_shorts,instagram_reels] [--target-s 45] [--tolerance-s 2]
               [--allow-black-tail] [--project edit.mlt]
               [--expect-text transcript.txt] [--limit CHECK=VALUE|on|off ...] [--reference ref.mp4] [--out <folder>]

Measures the file, not the timeline: duration, size, frame rate, loudness and true peak, shot changes (cuts per
minute, longest static shot, a change in the first 3 s; found by bridge/shots.py, so camera moves are not cuts while
punch-ins, dissolves, fades and cuts between clips framed over a blurred copy of themselves are), black or faded
first frame and contiguous black through the final decoded frame, silences (in the first 3 s,
the share overall, the tail), when speech starts (local whisper), and optionally how much of an expected transcript
is still audible.

Where the limits come from (letitedit ARCHITECTURE.md, "Gate settings by mode"; one table, `rules()`):
- Pace checks (cuts_per_min, longest_static_s, visual_change_first3s, first_speech_s, silence_first3s_s,
  silent_share) take their limit from PACE[mode][kind]. None = off for that mode: music-led edits and cinematic or
  poetic openings (documentary, travel) are not held to a talk-video tempo. first_speech_s runs only when the driver
  is dialogue; a music driver turns every pace check off. Pace checks are advisory: they become blocking only when
  the brief sets the number (--limit CHECK=12) or a reference does (--reference: cuts per minute >= 0.8x the
  reference's, measured the same way). --limit CHECK=on asks for a check a mode leaves off; =off drops one.
- Loudness from the deliverable: web -14, podcast -16, broadcast -23 LUFS; one true-peak ceiling, -1 dBTP.
- TikTok's 57-60 s warning only when tiktok is among --platforms. A black first frame is advisory.
- Requested length allows +/- max(5% of target, 2 s), unless --tolerance-s sets an explicit window.
  Official maximum lengths from the named platform profiles have no overrun allowance.
Every check records its evidence tag (OFF official, EXP practitioner, HYP our default, BRIEF the person's own number
or reference) and its severity: 'blocking' (only OFF/EXP/BRIEF checks can be) or 'advisory'. Checks that are off
are listed under 'off', with the value where it was measured anyway.
Waivers: `waive:<check>:<reason>` text in the project turns that check's fail into 'waived'. `hold:<reason>` markers
on the timeline waive longest_static_s for the shots inside their range (a point marker holds the shot it sits in);
a static shot outside every hold range still counts.
Verdict: red (a blocking check failed), amber (only advisory checks failed), green. Exit code 1 only when red.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(os.environ.get('LETITEDIT_ROOT', Path(__file__).resolve().parents[3]))
APP = ROOT / 'app'
FFMPEG, FFPROBE, WHISPER = APP / 'ffmpeg.exe', APP / 'ffprobe.exe', APP / 'whisper-cli.exe'
MODEL = next(iter(sorted((ROOT / 'models').glob('ggml-*.bin'), key=lambda p: p.stat().st_size)), None)
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# ---------------------------------------------------------------- the table (one source of truth)

MODES = ('story', 'tutorial', 'interview', 'documentary', 'product', 'travel', 'montage', 'creative')
DRIVERS = ('dialogue', 'narration', 'music', 'visual', 'sound')
KINDS = ('short', 'long')
MODE_ALIASES = {'vlog': 'story', 'repair': 'story', 'diy': 'story', 'day': 'story', 'day_in_the_life': 'story',
                'how_to': 'tutorial', 'howto': 'tutorial', 'explainer': 'tutorial', 'education': 'tutorial',
                'podcast': 'interview', 'podcast_excerpt': 'interview', 'doc': 'documentary',
                'commercial': 'product', 'ad': 'product', 'brand': 'product', 'business': 'product',
                'event': 'travel', 'transformation': 'montage', 'before_after': 'montage', 'music_video': 'montage',
                'stylised': 'creative', 'stylized': 'creative'}
DEFAULT_DRIVER = {'story': 'dialogue', 'tutorial': 'dialogue', 'interview': 'dialogue', 'documentary': 'dialogue',
                  'product': 'visual', 'travel': 'visual', 'montage': 'music', 'creative': 'visual'}
PACE_CHECKS = ('cuts_per_min', 'longest_static_s', 'visual_change_first3s', 'first_speech_s', 'silence_first3s_s',
               'silent_share')
CHECK_ALIASES = {'cuts': 'cuts_per_min', 'longest_static': 'longest_static_s', 'longest_shot': 'longest_static_s',
                 'visual_change': 'visual_change_first3s', 'first_speech': 'first_speech_s',
                 'silence_first3s': 'silence_first3s_s', 'opening_silence': 'silence_first3s_s'}
OFF = None


def _pace(cuts, longest, change, speech, quiet, share):
    return dict(zip(PACE_CHECKS, (cuts, longest, change, speech, quiet, share)))


# mode -> kind -> cuts_per_min >=, longest_static_s <=, a visual change by (s), first_speech_s <=,
# silence_first3s_s <=, silent_share <=. All [HYP] defaults (advisory) to tune in loop rounds. Grounds:
# story: our earlier defaults, shorts relaxed (not frantic by default: YouTube Shorts rewarded slower, story-led
# pieces, JH 29:13); tutorial: how-to 8-15 changes a minute, complexity needs room (ITE pRpaqx_5jD8 05:12);
# interview: stay on the face while the eyes carry it (AOTC Greatest Night in Pop), keep breaths (ITE xiJmwycUxTY);
# documentary and travel: poetic openings with pictures and sound before the first line (ITE esNXgCJh-yk 10:52,
# KAO0n3C0kAg 33:22), 7-14 s holds in reflective scenes (ITE 5G2wGolpXxE), silence used on purpose (AOTC Porcelain
# War, Hamnet); product: the first ~5 s carry the promise (ITE how-to-start-a-scene); montage and creative:
# music-led or stylised, the track or the brief sets the pace (FEP edit drivers, AOTC Porcelain War).
PACE = {
    'story':       {'short': _pace(12, 4.0, 3.0, 1.0, 0.5, 0.15), 'long': _pace(8, 8.0, 3.0, 2.0, 1.0, 0.15)},
    'tutorial':    {'short': _pace(10, 6.0, 3.0, 1.0, 0.5, 0.15), 'long': _pace(6, 15.0, 3.0, 3.0, 1.0, 0.15)},
    'interview':   {'short': _pace(OFF, OFF, OFF, 1.0, 0.5, 0.20), 'long': _pace(OFF, OFF, OFF, 2.0, 1.0, 0.20)},
    'documentary': {'short': _pace(6, 8.0, OFF, OFF, OFF, 0.25), 'long': _pace(4, 15.0, OFF, OFF, OFF, 0.25)},
    'product':     {'short': _pace(15, 4.0, 3.0, 1.5, 0.5, 0.15), 'long': _pace(10, 8.0, 3.0, 3.0, 1.0, 0.15)},
    'travel':      {'short': _pace(8, 6.0, OFF, OFF, OFF, 0.25), 'long': _pace(4, 12.0, OFF, OFF, OFF, 0.25)},
    'montage':     {'short': _pace(OFF, OFF, OFF, OFF, OFF, OFF), 'long': _pace(OFF, OFF, OFF, OFF, OFF, OFF)},
    'creative':    {'short': _pace(OFF, OFF, OFF, OFF, OFF, OFF), 'long': _pace(OFF, OFF, OFF, OFF, OFF, OFF)},
}
OFF_WHY = {'interview': 'interviews stay on the face while the eyes and voice carry it',
           'documentary': 'cinematic or poetic opening: pictures and sound may come before the first line',
           'travel': 'cinematic or poetic opening: pictures and sound may come before the first line',
           'montage': 'music-led: the track sets the cuts, holds and silences',
           'creative': 'stylised: the brief or a reference sets the pace'}
# deliverable -> (integrated LUFS target, tolerance LU, tag, source)
DELIVERABLES = {'web': (-14.0, 1.0, 'EXP', 'web/social normalisation level (YouTube publishes no number)'),
                'podcast': (-16.0, 1.0, 'OFF', 'Apple Podcasts'),
                'broadcast': (-23.0, 0.5, 'OFF', 'EBU R128')}
TRUE_PEAK_MAX = -1.0      # one ceiling for every deliverable [OFF: EBU R128, Spotify]; letitedit_export's default
TAIL_SILENCE_MAX = {'short': 0.6, 'long': 2.0}     # [HYP] end right after the payoff (JH 0:42, 7:07)
PLATFORM_ALIASES = {'tiktok': 'tiktok', 'tik_tok': 'tiktok', 'shorts': 'youtube_shorts', 'yt_shorts': 'youtube_shorts',
                    'youtube_shorts': 'youtube_shorts', 'reels': 'instagram_reels', 'instagram': 'instagram_reels',
                    'ig': 'instagram_reels', 'instagram_reels': 'instagram_reels', 'ig_reels': 'instagram_reels',
                    'facebook_reels': 'facebook_reels', 'fb_reels': 'facebook_reels', 'youtube': 'youtube',
                    'yt': 'youtube'}
BLOCKING_TAGS = ('OFF', 'EXP', 'BRIEF')


def _key(value):
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')


def norm_mode(value):
    """'Story' / 'vlog' / ['travel', 'story'] -> 'story' / 'story' / 'travel' (the first mode leads); None when
    unknown."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    k = _key(value)
    return k if k in MODES else MODE_ALIASES.get(k)


def norm_driver(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    k = _key(value)
    k = {'speech': 'dialogue', 'talk': 'dialogue', 'voiceover': 'narration', 'voice_over': 'narration',
         'vo': 'narration', 'pictures': 'visual', 'action': 'visual', 'visual_action': 'visual', 'process': 'visual',
         'ambient': 'sound', 'ambient_sound': 'sound'}.get(k, k)
    return k if k in DRIVERS else None


def norm_deliverable(value):
    k = _key(value)
    return k if k in DELIVERABLES else None


def norm_platforms(value):
    """'TikTok, shorts' or ['reels'] -> ['tiktok', 'youtube_shorts'] / ['instagram_reels'] (unknown names kept)."""
    items = value.split(',') if isinstance(value, str) else list(value or [])
    out = []
    for item in items:
        k = _key(item)
        if k and PLATFORM_ALIASES.get(k, k) not in out:
            out.append(PLATFORM_ALIASES.get(k, k))
    return out


def norm_check(name):
    k = _key(name)
    k = CHECK_ALIASES.get(k, k)
    return k if k in PACE_CHECKS else None


def parse_limits(items):
    """['cuts_per_min=12', 'first_speech=on', 'silent_share=off'] -> {'cuts_per_min': 12.0, 'first_speech_s': 'on',
    'silent_share': 'off'}. A dict passes through the same checks. Raises ValueError on an unknown check or value."""
    pairs = items.items() if isinstance(items, dict) else [str(i).split('=', 1) if '=' in str(i) else (i, '')
                                                          for i in (items or [])]
    out = {}
    for name, value in pairs:
        check = norm_check(name)
        if not check:
            raise ValueError(f'--limit: {name!r} is not a pace check ({", ".join(PACE_CHECKS)})')
        if value is True or str(value).strip().lower() in ('on', 'true', 'yes'):
            out[check] = 'on'
        elif value is False or value is None or str(value).strip().lower() in ('off', 'false', 'no', 'none'):
            out[check] = 'off'
        else:
            text = str(value).strip().lstrip('<>= ')
            try:
                number = float(text.rstrip('%s ').strip())
            except ValueError:
                raise ValueError(f'--limit {name}: {value!r} is not a number, on or off') from None
            if check == 'silent_share' and (text.endswith('%') or number > 1):
                number /= 100            # '15%' or 15 -> 0.15
            out[check] = number
    return out


def rules(kind, mode='story', driver=None, deliverable='web', platforms=(), limits=None, reference_cpm=None):
    """The settings of every check for one export: {check: {'on', 'limit', 'severity', 'tag', 'why'}}.
    kind short|long; mode/driver/deliverable as for the command line (None = the defaults); platforms a list or a
    comma string; limits as parse_limits takes them (the brief's own numbers, or on/off); reference_cpm the
    reference's cuts per minute."""
    if kind not in KINDS:
        raise ValueError(f'kind is short or long, not {kind!r}')
    mode = norm_mode(mode) or 'story'
    driver = norm_driver(driver) or DEFAULT_DRIVER[mode]
    deliverable = norm_deliverable(deliverable) or 'web'
    platforms = norm_platforms(platforms)
    limits = parse_limits(limits or {})          # idempotent: parsed limits pass through unchanged
    out = {}

    def put(name, limit, severity, tag, why='', on=True):
        if severity == 'blocking' and tag not in BLOCKING_TAGS:
            raise AssertionError(f'{name}: a {tag} default can never block')
        out[name] = {'on': bool(on and limit is not None), 'limit': limit, 'severity': severity, 'tag': tag,
                     'why': why}

    put('duration_vs_target', .05, 'blocking', 'BRIEF', 'the requested length window (+/- max(5% of target, 2 s))')
    maximums = []
    if platforms:
        if str(ROOT / 'bridge') not in sys.path:
            sys.path.insert(0, str(ROOT / 'bridge'))
        import platforms as platform_profiles
        for platform in platforms:
            try:
                profile = platform_profiles.load(platform)
            except KeyError:
                continue
            maximum = profile['video'].get('max_length_s') or {}
            if maximum.get('status') == 'official' and isinstance(maximum.get('value'), (int, float)):
                maximums.append((maximum['value'], profile['id'], maximum['source']))
    maximum, platform, source = min(maximums) if maximums else (None, '', '')
    put('platform_max_length_s', maximum, 'blocking', 'OFF', f'{platform} maximum length ({source})')
    put('black_tail_s', 0.0, 'blocking', 'EXP', 'no black tail unless the ending deliberately calls for it')
    put('vertical_1080x1920', (1080, 1920), 'blocking', 'OFF', 'the 9:16 delivery size', on=kind == 'short')
    tiktok = 'tiktok' in platforms
    put('tiktok_just_under_60s', (57.0, 60.0), 'advisory', 'OFF',
        'TikTok Creator Rewards counts videos of at least 60 s: a warning, not a rule' if tiktok
        else 'off: tiktok is not among the platforms', on=tiktok)
    target, tol, tag, source = DELIVERABLES[deliverable]
    put('loudness_lufs', (target, tol), 'blocking', tag, f'{deliverable} delivery ({source})')
    put('true_peak_dbtp', TRUE_PEAK_MAX, 'blocking', 'OFF', 'one ceiling for every deliverable (EBU R128, Spotify)')
    put('frame0_not_black', 0.08, 'advisory', 'EXP',
        'a short\'s first frame is its hook; a fade up from black is ordinary long-form grammar')
    craft = _craft_checks()
    put('tail_silence_s', TAIL_SILENCE_MAX[kind], 'advisory', 'HYP',
        craft.gate_tail_note() if craft else 'end soon after the payoff')
    put('expected_words_audible', 0.85, 'advisory', 'HYP', 'words lost under music, cut off at edges, or dropped')

    for check in PACE_CHECKS:
        limit, severity, tag = PACE[mode][kind][check], 'advisory', 'HYP'
        why = (f'a {mode} {kind} default; pace is advisory unless the brief or a reference sets it' if limit is not None
               else f'off for {mode}: {OFF_WHY.get(mode, "not a pace this mode is held to")}')
        if driver == 'music' and limit is not None:
            limit, why = None, 'off: music-led (driver music), the track sets the pace'
        if check == 'first_speech_s' and driver != 'dialogue' and limit is not None:
            limit, why = None, f'off: the driver is {driver}, not dialogue'
        if check == 'cuts_per_min' and reference_cpm is not None:
            limit, severity, tag = round(0.8 * float(reference_cpm), 1), 'blocking', 'BRIEF'
            why = f"set by the reference: at least 0.8x its {float(reference_cpm):.1f} cuts per minute"
        asked = limits.get(check)
        if asked == 'off':
            limit, severity, tag, why = None, 'advisory', 'HYP', 'off: the brief turned it off'
        elif asked == 'on' and limit is None:
            limit = PACE[mode][kind][check] if PACE[mode][kind][check] is not None else PACE['story'][kind][check]
            why = 'asked for by the brief; the default limit, advisory'
        elif isinstance(asked, float):
            limit, severity, tag, why = asked, 'blocking', 'BRIEF', 'set by the brief'
        put(check, limit, severity, tag, why)
    return out


def verdict_of(checks):
    """red: a blocking check failed; amber: only advisory checks failed; green: nothing failed."""
    fails = [c for c in checks if c['state'] == 'fail']
    if any(c.get('severity') == 'blocking' for c in fails):
        return 'red'
    return 'amber' if fails else 'green'


# ---------------------------------------------------------------- measuring

def run(args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=NO_WINDOW)


def probe(path):
    out = json.loads(run([FFPROBE, '-v', 'error', '-show_entries',
                          'format=duration:stream=codec_type,width,height,r_frame_rate', '-of', 'json', path]).stdout)
    v = next((s for s in out['streams'] if s['codec_type'] == 'video'), {})
    num, den = (v.get('r_frame_rate') or '0/1').split('/')
    return {'duration': float(out['format']['duration']), 'width': v.get('width'), 'height': v.get('height'),
            'fps': float(num) / float(den or 1), 'has_audio': any(s['codec_type'] == 'audio' for s in out['streams'])}


def loudness(path):
    err = run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128=peak=true', '-f', 'null', '-']).stderr
    tail = err[err.rfind('Summary:'):]
    i = re.search(r'I:\s+(-?[\d.]+) LUFS', tail)
    p = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', tail)
    return (float(i.group(1)) if i else None, float(p.group(1)) if p and p.group(1) != '-inf' else None)


def scene_changes(path, threshold=0.3):
    """The older measure, used when the shot detector can't run: scene changes on the whole frame, plus on the
    centre third: a vertical clip shown over a blurred copy of itself in a wide frame (or the reverse) changes only in
    the middle, which the whole-frame score dilutes."""
    def detect(crop):
        err = run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-an', '-vf',
                   f"{crop}scale=320:-2,select='gt(scene,{threshold})',showinfo", '-f', 'null', '-']).stderr
        return [float(t) for t in re.findall(r'pts_time:([\d.]+)', err)]
    times = sorted(detect('') + detect('crop=iw/3:ih:iw/3:0,') + detect('crop=iw:ih/3:0:ih/3,'))
    merged = []
    for t in times:   # the same cut seen by two detectors counts once
        if not merged or t - merged[-1] > 0.2:
            merged.append(t)
    return merged


def shot_changes(path, detail=False):
    """Shot boundaries (seconds) from the camera-move-aware detector (bridge/shots.py): hard cuts, punch-ins (a
    reframe of the same picture), dissolves and fades. A pan, a whip or a hand near the lens is not a cut; a change in
    part of the frame (footage over a blurred copy of itself, a graphic panel beside it) still is. detail=True also
    returns {method, kinds}. Falls back to scene_changes when the detector can't run (no OpenCV, no bridge folder)."""
    try:
        if str(ROOT / 'bridge') not in sys.path:
            sys.path.insert(0, str(ROOT / 'bridge'))
        import shots
        # the whole frame, and the picture alone when the rest of the frame is bars or a blurred copy of it;
        # 2 pieces x 2 decode threads keep it light on the PC
        res = shots.detect(str(path), settings={'workers': 2, 'picture_area': 'auto'})
        kinds = {}
        for c in res['cuts']:
            kinds[c['kind']] = kinds.get(c['kind'], 0) + 1
        times = sorted(c['t'] for c in res['cuts'])
        how = {'method': 'shots.detect: camera moves are not cuts; punch-ins, dissolves and fades count', 'kinds': kinds,
               'picture_area': res.get('picture_area')}
    except Exception as e:  # noqa: BLE001
        times = scene_changes(path)
        how = {'method': f'ffmpeg scene score > 0.3 on the frame and its centre thirds (the shot detector did not '
                         f'run: {type(e).__name__}: {str(e)[:120]})', 'kinds': {}}
    return (times, how) if detail else times


def black_tail(video, info):
    """Black picture through the last decoded frame, capped to a three-second sample. Near-black means
    all pixels below luma 20 (limited-range black is 16); dark but detailed shots are not black tails."""
    frame_s = 1 / (info.get('fps') or 30.0)
    offset = max(0.0, float(info['duration']) - 3.0)
    result = run([FFMPEG, '-v', 'info', '-threads', '4', '-ss', str(offset), '-i', video, '-an',
                  '-vf', 'blackframe=amount=100:threshold=20,showinfo', '-threads', '4', '-f', 'null', '-'])
    frames = re.findall(r'\bn:\s*(\d+)\s+pts:.*?pts_time:([\d.e+-]+)', result.stderr)
    if result.returncode or not frames:
        raise RuntimeError('black-tail decode failed: ' + result.stderr[-1000:])
    black = {int(index) for index in re.findall(r'\bframe:(\d+)\s+pblack:', result.stderr)}
    last = int(frames[-1][0])
    if last in black:
        first = last
        while first - 1 in black:
            first -= 1
        start = float(next(moment for index, moment in frames if int(index) == first))
        end = float(frames[-1][1]) + frame_s
        return round(end - start, 6), round(offset + start, 6)
    return 0.0, None


def _craft_checks():
    """letitedit.review.craft_checks while its switch (review_craft_checks) is on, else None."""
    try:
        if str(ROOT / 'bridge') not in sys.path:
            sys.path.insert(0, str(ROOT / 'bridge'))
        import letitedit.review.craft_checks as craft_checks
        return craft_checks if craft_checks.enabled() else None
    except Exception:  # noqa: BLE001 - not there (an older bridge) or unreadable: the checks as before
        return None


def project_cuts(project, duration):
    """(cut times, note): where the project's main picture track jumps to another clip or another place in one. The picture
    detector doesn't see a jump cut on a person who stays in frame, and a project knows where its cuts are. Empty, with why,
    when there is no project to read or it isn't this export's length."""
    if not project:
        return [], ''
    try:
        if str(ROOT / 'bridge') not in sys.path:
            sys.path.insert(0, str(ROOT / 'bridge'))
        import edit_script as es
        from edit_sync import layout, main_track
        script = es.read(project)
        craft_checks = _craft_checks()
        if craft_checks:        # T346, behind its switch: the cuts a viewer sees (an edge under a full-frame cover is none)
            return craft_checks.visible_cuts(script, duration)
        pieces = list(layout(main_track(script)))
    except Exception as e:  # noqa: BLE001 - measured on the picture alone, and it says so
        return [], f'the project could not be read for its cuts ({type(e).__name__})'
    if not pieces:
        return [], ''
    length = max(float(e) for _, _, e in pieces)
    if abs(length - duration) > 1.0:
        return [], f"the project's picture ({length:.1f} s) isn't this export's length ({duration:.1f} s), so its cuts weren't used"
    cuts = []
    for (a, _, _), (b, start, _) in zip(pieces, pieces[1:]):
        same = a.get('clip') and a.get('clip') == b.get('clip') and abs(float(b.get('in', 0)) - float(a.get('out', 0))) <= 0.05
        if not same and 0 < float(start) < duration:
            cuts.append(round(float(start), 3))
    return cuts, ''


def merged_cuts(found, project_times, within=0.15):
    """The detector's times plus the project's cuts it didn't see."""
    return sorted(list(found) + [t for t in project_times if not any(abs(t - f) <= within for f in found)])


def silences(path, db=-35, d=0.25):
    err = run([FFMPEG, '-hide_banner', '-nostats', '-i', path, '-vn', '-af', f'silencedetect=noise={db}dB:d={d}',
               '-f', 'null', '-']).stderr
    starts = [float(x) for x in re.findall(r'silence_start: (-?[\d.]+)', err)]
    ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def first_frame_luma(path):
    err = run([FFMPEG, '-hide_banner', '-i', path, '-frames:v', '1', '-vf', 'signalstats,metadata=print',
               '-f', 'null', '-']).stderr
    m = re.search(r'lavfi.signalstats.YAVG=([\d.]+)', err)
    return float(m.group(1)) / 255 if m else None


def whisper_model():
    """The whisper.cpp model; on first use (a new install has none) it is fetched (141 MB), else None."""
    if MODEL and MODEL.exists():
        return MODEL
    if not WHISPER.exists():
        return None
    try:
        if str(ROOT / 'bridge') not in sys.path:
            sys.path.insert(0, str(ROOT / 'bridge'))
        import letitedit.core.first_use as first_use
        if not first_use.optional(models=['whisper-cpp-base-en'], feature="the gate's transcript (whisper.cpp base.en)"):
            return None
    except ImportError:
        return None
    return next(iter(sorted((ROOT / 'models').glob('ggml-*.bin'), key=lambda p: p.stat().st_size)), None)


def transcript(path):
    model = whisper_model()
    if not (WHISPER.exists() and model):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wav, base = Path(tmp) / 'a.wav', Path(tmp) / 'a'
        run([FFMPEG, '-v', 'error', '-y', '-i', path, '-ar', '16000', '-ac', '1', wav])
        run([WHISPER, '-m', model, '-f', wav, '-osrt', '-of', base, '-np'])
        srt = base.with_suffix('.srt')
        if not srt.exists():
            return None
        text = srt.read_text(encoding='utf-8', errors='replace')
    cues = re.findall(r'(\d\d):(\d\d):(\d\d),(\d{3}) -->[^\n]*\n(.*?)(?:\n\n|\Z)', text, re.S)
    if not cues:
        return {'first_speech_s': None, 'text': ''}
    h, m, s, ms, _ = cues[0]
    words = ' '.join(c[4].replace('\n', ' ') for c in cues)
    return {'first_speech_s': int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000, 'text': words}


def words_of(text):
    return re.findall(r"[a-z0-9']+", text.lower())


# ---------------------------------------------------------------- the project: waivers and hold markers

def clock_s(value, fps):
    """An MLT time ("123" frames, "HH:MM:SS.mmm", "HH:MM:SS:FF", "MM:SS.s") in seconds; None when empty or
    unreadable."""
    if value is None or str(value).strip() == '':
        return None
    text = str(value).strip()
    try:
        if ':' not in text and ';' not in text:
            return float(text) / fps
        parts = re.split(r'[:;]', text)
        if len(parts) == 4:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / fps
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return None
    return None


def project_markers(text):
    """[(start_s, end_s, text)] of the timeline markers (Shotcut's shotcut:markers) in a project's XML text."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    prof = root.find('profile')
    fps = 30.0
    if prof is not None:
        fps = int(prof.get('frame_rate_num', 30)) / (int(prof.get('frame_rate_den', 1)) or 1)
    out = []
    for group in root.iter('properties'):
        if group.get('name') != 'shotcut:markers':
            continue
        for m in group.findall('properties'):
            vals = {p.get('name'): (p.text or '') for p in m.findall('property')}
            s, e = clock_s(vals.get('start'), fps), clock_s(vals.get('end'), fps)
            if s is not None:
                out.append((s, e if e is not None and e >= s else s, vals.get('text', '')))
    return out


def hold_ranges(markers):
    """[(start_s, end_s, reason)] of the markers whose text is hold:<reason>."""
    return [(s, e, t.split(':', 1)[1].strip() or 'hold') for s, e, t in markers
            if t.strip().lower().startswith('hold:')]


def _minus(ps, pe, cs, ce):
    """The parts of [ps, pe] outside [cs, ce]."""
    if ce <= ps or cs >= pe:
        return [(ps, pe)]
    return [q for q in ((ps, cs), (ce, pe)) if q[1] - q[0] > 1e-9]


def longest_unheld(shots, holds, pad=0.25):
    """(seconds, start_s) of the longest stretch of any shot that no hold range covers. shots: [(start, end)] in
    order; holds: [(start, end, reason)], each range widened by pad for scene-detection jitter; a point marker
    (start == end) holds the whole shot it sits in."""
    best = (0.0, 0.0)
    last_end = shots[-1][1] if shots else 0.0
    for a, b in shots:
        cover = []
        for hs, he, _ in holds:
            if he - hs < 0.05:
                if a <= hs < b or (hs >= b and b == last_end):
                    cover.append((a, b))
            else:
                cover.append((hs - pad, he + pad))
        pieces = [(a, b)]
        for cs, ce in cover:
            pieces = [q for ps, pe in pieces for q in _minus(ps, pe, cs, ce)]
        for ps, pe in pieces:
            if pe - ps > best[0]:
                best = (pe - ps, ps)
    return best


def judge_longest(spans, holds, limit, hold_note=''):
    """(value_s, at_s, note, waive_reason) of the longest-static check. spans: the shots [(start, end)]. The value is
    the longest shot; when hold: ranges cover every shot over the limit the check is waived; when they cover the
    longest shot but not another one over the limit, the value is the longest stretch outside the holds."""
    note = 'shot detection: a long take with movement counts as one shot; a hold:<reason> marker holds it'
    if not spans:
        return 0.0, 0.0, note, None
    shots = [b - a for a, b in spans]
    i = max(range(len(shots)), key=shots.__getitem__)
    longest, at = shots[i], spans[i][0]
    if longest <= limit or not holds:
        return longest, at, note, None
    free, free_at = longest_unheld(spans, holds)
    reasons = '; '.join(sorted({r for _, _, r in holds}))[:160]
    if free <= limit:
        return longest, at, note, f'held by hold: markers ({reasons})' + (f'; {hold_note}' if hold_note else '')
    if free < longest - 0.05:
        return free, free_at, (f'the longest shot outside hold ranges; the longest overall ({longest:.1f} s) is '
                               f'held ({reasons})'), None
    return longest, at, f'outside every hold range (held: {reasons}); a long take with movement counts as one shot', \
        None


def read_project(path):
    """(waivers {check: reason}, hold ranges, note) from a project file (.mlt or any text with markers)."""
    waived, holds, note = {}, [], ''
    if not path or not Path(path).exists():
        return waived, holds, note
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    for check, reason in re.findall(r'waive:([a-z0-9_]+):([^<"\n]+)', text):
        waived[check] = reason.strip()
    try:
        holds = hold_ranges(project_markers(text))
    except Exception as e:  # noqa: BLE001  (not XML, or not a Shotcut project)
        if re.search(r'hold:', text):
            holds = [(0.0, 1e9, 'hold marker without a readable time')]
            note = f'hold: markers found but not their times ({type(e).__name__}); every static shot is held'
    return waived, holds, note


# ---------------------------------------------------------------- the gate

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--kind', choices=KINDS, default=None)
    ap.add_argument('--mode', default='story', help=' | '.join(MODES))
    ap.add_argument('--driver', default=None, help=' | '.join(DRIVERS) + ' (default: the mode\'s usual driver)')
    ap.add_argument('--deliverable', default='web', help=' | '.join(DELIVERABLES))
    ap.add_argument('--platforms', default='', help='comma list, e.g. tiktok,youtube_shorts,instagram_reels')
    ap.add_argument('--target-s', type=float)
    ap.add_argument('--tolerance-s', type=float,
                    help='explicit requested length tolerance in seconds (default: max(5%% of target, 2 s))')
    ap.add_argument('--allow-black-tail', action='store_true', help='the brief or Look explicitly requests black at the end')
    ap.add_argument('--project')
    ap.add_argument('--expect-text')
    ap.add_argument('--limit', action='append', default=[], metavar='CHECK=VALUE',
                    help='the brief\'s own pace limit (blocking), or CHECK=on / CHECK=off')
    ap.add_argument('--reference', help='a reference video whose cut rate sets the tempo')
    ap.add_argument('--out')
    ap.add_argument('--full-size', help='WxH: the video is a reduced preview of a render at this size (the size '
                    'checks judge that size; everything else is measured on the preview)')
    a = ap.parse_args()
    mode, driver, deliverable = norm_mode(a.mode), norm_driver(a.driver), norm_deliverable(a.deliverable)
    if not mode:
        ap.error(f'--mode: {a.mode!r} is not one of {", ".join(MODES)}')
    if a.driver and not driver:
        ap.error(f'--driver: {a.driver!r} is not one of {", ".join(DRIVERS)}')
    if not deliverable:
        ap.error(f'--deliverable: {a.deliverable!r} is not one of {", ".join(DELIVERABLES)}')
    try:
        limits = parse_limits(a.limit)
    except ValueError as e:
        ap.error(str(e))
    driver = driver or DEFAULT_DRIVER[mode]
    platforms = norm_platforms(a.platforms)
    video = Path(a.video)
    out = Path(a.out) if a.out else video.parent
    info = probe(video)
    preview_of = None
    if a.full_size:
        width, height = (int(part) for part in a.full_size.lower().split('x'))
        preview_of = {'preview_size': f"{info['width']}x{info['height']}", 'full_size': f'{width}x{height}'}
        info = {**info, 'width': width, 'height': height}
    kind = a.kind or ('short' if (info['height'] or 0) > (info['width'] or 0) and info['duration'] <= 180 else 'long')
    reference = None
    if a.reference:
        if Path(a.reference).is_file():
            r_info = probe(Path(a.reference))
            r_cuts = shot_changes(Path(a.reference))
            r_cpm = len(r_cuts) / (r_info['duration'] / 60) if r_info['duration'] else 0.0
            reference = {'file': str(a.reference), 'duration_s': round(r_info['duration'], 2),
                         'cuts_per_min': round(r_cpm, 1)}
        else:
            reference = {'file': str(a.reference), 'error': 'not a local file: not measured'}
    rule = rules(kind, mode, driver, deliverable, platforms, limits,
                 reference.get('cuts_per_min') if reference and 'error' not in reference else None)
    waived, holds, hold_note = read_project(a.project)
    checks, off = [], []

    def add(name, value, ok, threshold, note='', at=None, waive=None):
        r = rule[name]
        state = 'pass' if ok else ('waived' if name in waived or waive else 'fail')
        c = {'check': name, 'value': value, 'threshold': threshold, 'tag': r['tag'], 'severity': r['severity'],
             'state': state, 'note': (waived.get(name) or waive) if state == 'waived' else (note or r['why'])}
        if at is not None:
            c['at_s'] = round(at, 2)
        checks.append(c)

    def skip(name, value=None):
        off.append({'check': name, 'value': value, 'why': rule[name]['why']})

    def on(name):
        return rule[name]['on']

    dur = info['duration']
    if a.target_s and on('duration_vs_target'):
        tolerance = a.tolerance_s if a.tolerance_s is not None else max(2.0, rule['duration_vs_target']['limit'] * a.target_s)
        within_window = a.target_s - tolerance <= dur <= a.target_s + tolerance
        add('duration_vs_target', dur, within_window,
            f'target {a.target_s:g} s; window {a.target_s - tolerance:g}-{a.target_s + tolerance:g} s',
            note='length within the requested window' if within_window else 'length outside the requested window')
    if on('platform_max_length_s'):
        maximum = rule['platform_max_length_s']['limit']
        add('platform_max_length_s', dur, dur <= maximum, f'platform maximum {maximum:g} s')
    if on('black_tail_s'):
        tail_s, tail_at = black_tail(video, info)
        add('black_tail_s', tail_s, tail_s <= rule['black_tail_s']['limit'],
            f"<= {rule['black_tail_s']['limit']:g} s", at=tail_at,
            waive='the brief or Look explicitly requests black at the end' if a.allow_black_tail else None)
    if on('vertical_1080x1920'):
        add('vertical_1080x1920', f"{info['width']}x{info['height']}",
            (info['width'], info['height']) == (1080, 1920), '1080x1920')
    if on('tiktok_just_under_60s'):
        add('tiktok_just_under_60s', round(dur, 2), not (57.0 <= dur < 60.0),
            'not 57-59.9 s (Creator Rewards needs >= 60 s)')
    else:
        skip('tiktok_just_under_60s', round(dur, 2))
    integrated, peak = loudness(video) if info['has_audio'] else (None, None)
    target, tol = rule['loudness_lufs']['limit']
    add('loudness_lufs', integrated, integrated is not None and abs(integrated - target) <= tol, f'{target} +-{tol:g}')
    add('true_peak_dbtp', peak, peak is not None and peak <= TRUE_PEAK_MAX, f'<= {TRUE_PEAK_MAX}')

    cuts, shot_method = shot_changes(video, detail=True)
    in_project, why_not = project_cuts(a.project, dur)
    merged = merged_cuts(cuts, in_project)
    shot_method.update(in_picture=len(cuts), in_project=len(in_project), added_from_project=len(merged) - len(cuts),
                       project_cuts=in_project)
    if why_not:
        shot_method['project_note'] = why_not
    cuts = merged
    bounds = [0.0] + cuts + [dur]
    spans = list(zip(bounds, bounds[1:]))
    shots = [b - a_ for a_, b in spans]
    cpm = len(cuts) / (dur / 60) if dur else 0
    if on('cuts_per_min'):
        lim = rule['cuts_per_min']['limit']
        add('cuts_per_min', round(cpm, 1), cpm >= lim, f'>= {lim:g}')
    else:
        skip('cuts_per_min', round(cpm, 1))
    longest = max(shots) if shots else dur
    if on('longest_static_s'):
        lim = rule['longest_static_s']['limit']
        value, at, note, waive = judge_longest(spans, holds, lim, hold_note)
        add('longest_static_s', round(value, 1), value <= lim, f'<= {lim:g}', note, at=at, waive=waive)
    else:
        skip('longest_static_s', round(longest, 1))
    first_cut = cuts[0] if cuts else None
    if on('visual_change_first3s'):
        lim = rule['visual_change_first3s']['limit']
        add('visual_change_first3s', round(first_cut, 2) if first_cut is not None else None,
            first_cut is not None and first_cut <= lim, f'a change by {lim:g} s')
    else:
        skip('visual_change_first3s', round(first_cut, 2) if first_cut is not None else None)
    luma = first_frame_luma(video)
    add('frame0_not_black', round(luma, 3) if luma is not None else None, luma is not None and luma > 0.08,
        'mean luma > 0.08')
    sil = silences(video) if info['has_audio'] else []
    first3 = sum(max(0.0, min(e if e is not None else dur, 3.0) - max(s, 0.0)) for s, e in sil if s < 3.0)
    if on('silence_first3s_s'):
        lim = rule['silence_first3s_s']['limit']
        add('silence_first3s_s', round(first3, 2), first3 <= lim, f'<= {lim:g}')
    else:
        skip('silence_first3s_s', round(first3, 2))
    total_sil = sum((e if e is not None else dur) - max(s, 0.0) for s, e in sil)
    share = round(total_sil / dur, 3) if dur else None
    if on('silent_share'):
        lim = rule['silent_share']['limit']
        add('silent_share', share, bool(dur) and total_sil / dur <= lim, f'<= {lim:.0%}')
    else:
        skip('silent_share', share)
    tail = next(((dur - max(s, 0.0)) for s, e in sil if e is None or e >= dur - 0.05), 0.0)
    lim = rule['tail_silence_s']['limit']
    add('tail_silence_s', round(tail, 2), tail <= lim, f'<= {lim:g}', at=dur - tail if tail > lim else None)
    want_words = bool(a.expect_text and Path(a.expect_text).exists())
    tr = transcript(video) if info['has_audio'] and (on('first_speech_s') or want_words) else None
    start = None
    if tr and tr['first_speech_s'] is not None:
        # whisper's first cue often starts at 0; an opening silence says when sound really starts
        lead = next((e for s, e in sil if s <= 0.05 and e is not None), 0.0)
        start = round(max(tr['first_speech_s'], lead), 2)
    if on('first_speech_s') and start is not None:
        lim = rule['first_speech_s']['limit']
        add('first_speech_s', start, start <= lim, f'<= {lim:g}', 'whisper cue start or end of opening silence')
    elif on('first_speech_s'):
        off.append({'check': 'first_speech_s', 'value': None,
                    'why': 'not measured: local whisper heard no speech (or is not installed)'})
    else:
        skip('first_speech_s', start)
    if tr and want_words:
        want = words_of(Path(a.expect_text).read_text(encoding='utf-8', errors='replace'))
        got = words_of(tr['text'])
        ratio = SequenceMatcher(None, want, got).ratio() if want else 1.0
        add('expected_words_audible', round(ratio, 3), ratio >= 0.85, '>= 0.85 match')

    verdict = verdict_of(checks)
    result = {'video': str(video), 'kind': kind, 'mode': mode, 'driver': driver, 'deliverable': deliverable,
              'platforms': platforms, 'limits': {k: v for k, v in limits.items()}, 'reference': reference,
              'holds': [{'from_s': round(s, 2), 'to_s': round(e, 2), 'reason': r} for s, e, r in holds],
              'info': info, 'shots': len(shots), 'shot_changes': shot_method, 'checks': checks, 'off': off,
              'verdict': verdict, **({'preview_of': preview_of} if preview_of else {})}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'checks.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    (out / 'report.md').write_text(report(result) + '\n', encoding='utf-8')
    print(report(result))
    sys.exit(1 if verdict == 'red' else 0)


def report(r):
    info, kind = r['info'], r['kind']
    target, tol, _, _ = DELIVERABLES[r['deliverable']]
    setting = [f"Judged as a {r['mode']} {kind}, driver {r['driver']}, {r['deliverable']} delivery ({target:g} LUFS "
               f"+-{tol:g}, true peak <= {TRUE_PEAK_MAX:g} dBTP), platforms: "
               f"{', '.join(r['platforms']) or 'not given'}."]
    if r['limits']:
        setting.append('Brief limits: ' + ', '.join(f'{k}={v:g}' if isinstance(v, float) else f'{k}={v}'
                                                    for k, v in r['limits'].items()) + '.')
    ref = r.get('reference')
    if ref:
        setting.append(f"Reference: {Path(ref['file']).name} ("
                       + (f"{ref['cuts_per_min']} cuts per minute" if 'error' not in ref else ref['error']) + ').')
    if r['holds']:
        setting.append('Hold markers: ' + ', '.join(
            ('whole video' if h['to_s'] >= 1e8 else f"{h['from_s']:g}-{h['to_s']:g} s") + f" ({h['reason']})"
            for h in r['holds'][:8]) + '.')
    lines = [f"# Checks for {Path(r['video']).name}", '',
             f"Verdict: **{r['verdict']}** ({kind}, {info['duration']:.1f} s, {info['width']}x{info['height']} at "
             f"{info['fps']:.2f} fps, {r['shots']} shots)", '', ' '.join(setting), '',
             '| Check | Value | Threshold | Tag | Severity | Result |', '|---|---|---|---|---|---|']
    for c in r['checks']:
        lines.append(f"| {c['check']} | {c['value']} | {c['threshold']} | {c['tag']} | {c['severity']} | {c['state']}"
                     f"{' - ' + c['note'] if c['state'] != 'pass' and c['note'] else ''} |")
    blocking = [c['check'] for c in r['checks'] if c['state'] == 'fail' and c['severity'] == 'blocking']
    advisory = [c['check'] for c in r['checks'] if c['state'] == 'fail' and c['severity'] == 'advisory']
    lines += ['', 'Blocking issues: ' + (', '.join(blocking) or 'none measured.'),
              'Advisory (a default for this kind of video, not a rule; change it if it helps the video, or say why '
              'not): ' + (', '.join(advisory) or 'none.')]
    if r['off']:
        lines.append('Not judged for this video: ' + '; '.join(
            f"{o['check']}{' (' + str(o['value']) + ')' if o['value'] is not None else ''}: {o['why']}"
            for o in r['off']))
    lines.append('This report covers what can be measured. Story quality needs the critic review and the retell test.')
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
