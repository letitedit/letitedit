"""The picture under the words (T349): a camera move the viewer can't read while a line is said, above all a line that
points at something to be seen, and b-roll in the footage that the cut never shows. Measured facts for the review's
code-first pass and for the fine phase's self-checks.

Behind the switch review_craft_checks (craft_checks.enabled, on by default). Off, nothing here runs.

What counts as unreadable (per frame, from the timing map's motion lane, timing_signals 'motion'; on an export the
frames within CUT_GUARD_S of the cut's own cut points are left out, guard_cuts):
  - the lane's own 'whip' label (camera speed over its whip_speed on the short whip window);
  - camera speed of FAST_FW_S frame widths per second or more (on the lane's 0.3 s mean);
  - shake: the lane's camera jitter of SHAKE_FW_S frame widths per second or more.
Measured on the export itself (export_motion: what the viewer sees, covers included), or, before an export, on the
source range each visible shot shows (cut_motion: the topmost picture where the picture under it is seen, the
whole frame or the same window, craft_checks.visible_frames).

findings_from(flags, fps, words, keep=(), duration=None)   pure: findings and facts from per-frame flags and the cut's
                                                            words [{w, t0, t1}] on the timeline.
broll_unused(script, footage, talk_share=None)           pure-ish: the footage's b-roll files (video, little or no talk)
                                                            and whether any is on a shown video track.
review(project, video, brief)                           (findings, facts line, numbers) for the review bundle.
cut(project)                                            {'findings', 'facts'} for the fine phase's self-check (with
                                                            craft_checks.slivers, T361: a shot under 0.3 s between cuts).
floor(findings)                                         a critic's note on the picture at a moment this check measured
                                                            as major is major at least (the measure sets the floor).
"""
from __future__ import annotations

import os
import re

import letitedit.review.craft_checks as craft_checks

FILE = 'picture-words.json'   # the numbers the critic reads beside the gate's (in the review folder)

# A camera move that smears the picture. The direction is [GEN]: the American Cinematographer Manual's panning tables
# keep an object at least about 5-7 s crossing the frame (about 0.15-0.2 frame widths a second) to avoid judder and
# smear; FAST_FW_S is about three times that (the frame crossed in 2 s) [HYP number]. The whip is the timing map's own
# label. SHAKE_FW_S: frame-to-frame camera jitter at which a held object no longer sits still enough to be read [HYP
# number]. It was 0.3, set on four tripod finals. On handheld footage (a walking travel vlog and six phone clips
# narrated while working), jitter between 0.3 and 0.7 is the ordinary sway of a hand-held phone, and the frames
# show what the line names. At 0.7 every look judged unreadable by eye is still found, Run 5's whip among them
# (unchanged at 44%), and 11 of 15 judged readable are no longer flagged.
FAST_FW_S = 0.5
SHAKE_FW_S = 0.7
MERGE_GAP_S = 0.2          # unreadable stretches this close are one
# A line that points at something to be seen: the viewer's eyes go to the thing named within about 0.2 s of the
# word's onset and stay on it through the following second or so [STUDY: Tanenhaus et al. 1995, Science 268;
# Allopenna, Magnuson and Tanenhaus 1998, J. Memory and Language 38 (the visual world paradigm)]. POINT_WINDOW_S is
# that look: the word's onset and 1.5 s after it.
POINT_WINDOW_S = 1.5
# Of the look's frames unreadable, what the line points at isn't there to be seen: 0.6 s of the 1.5 s, longer than the
# 0.2-0.4 s a fixation needs [STUDY for the fixation: Rayner 1998, Psychological Bulletin 124] [HYP number, set
# between the covered cuts of one take (14-29% on export and sources) and the uncovered one (45-54%)].
POINT_SHARE = 0.4
UNDER_WORDS_S = 1.0        # an unreadable stretch this long under any spoken words is a minor fact [HYP]
# On an export, a cut the motion lane doesn't detect (a jump within one take) reads as a camera jump: its camera speed
# is a 0.3 s centred mean (timing_motion smooth_s), so frames this close to one of the cut's own cut points are not
# read as camera motion.
CUT_GUARD_S = 0.15
POINT_WORDS = re.compile(r"^(this|these|those|here|see|look|looking|watch|notice|show|shows|showing)$")
NOT_POINTING_BEFORE = {"we'll", 'well', "let's", 'lets', 'will'}      # "we'll see", "let's see": find out, not look
# b-roll in the footage: a video file whose talk share is at most this (log.json's talk_share, else its words)
BROLL_TALK_SHARE = 0.2
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.mpg', '.mpeg', '.wmv'}


def enabled():
    return craft_checks.enabled()


def options(check):
    """What a review finding of this check can be answered with: the options, never a choice made for the editor."""
    if check == 'broll_unused':
        return ('The b-roll files are listed with what they show in the footage log (log.json) and '
                'letitedit_footage; a cutaway goes on a video track above the speaker ({op: insert, track, at}).')
    return ('Options: a steady shot of what the line names over these seconds on a track above (a cover), a steadier '
            'stretch of the same take, a held frame of it, or the line moved to a steadier picture; '
            'letitedit_check_frames at these times shows what is on screen.')


def _clock(s):
    m, sec = divmod(float(s), 60)
    return f'{int(m)}:{sec:04.1f}'


# ---------------------------------------------------------------------------- per-frame flags

def flags_from_lane(motion):
    """[bool per frame] from a timing motion lane: whip, fast or shaking."""
    labels = motion.get('camera_label') or []
    speed = motion.get('camera_speed') or []
    jitter = motion.get('camera_jitter') or []
    out = []
    for i, lab in enumerate(labels):
        s = speed[i] if i < len(speed) else None
        j = jitter[i] if i < len(jitter) else None
        out.append(lab == 'whip' or (s is not None and s >= FAST_FW_S) or (j is not None and j >= SHAKE_FW_S))
    return out


def export_motion(video):
    """(flags, fps) measured on the export itself (the timing map's motion lane, cached by the file's content)."""
    import letitedit.timing.timing_signals as timing_signals
    sig = timing_signals.signals(str(video), lanes=['motion'])
    return flags_from_lane(sig['lanes']['motion']), float(sig['fps'])


def guard_cuts(flags, fps, cuts):
    """The flags with the frames within CUT_GUARD_S of each cut point (seconds) cleared: a jump cut is no camera move."""
    out = list(flags)
    for c in cuts or ():
        for f in range(max(0, int((float(c) - CUT_GUARD_S) * fps)), min(len(out), int(round((float(c) + CUT_GUARD_S) * fps)))):
            out[f] = False
    return out


def cut_motion(script):
    """(flags, fps) on the timeline before an export: each frame's topmost full-frame picture, measured on the source
    range that shot shows (the same lane, on the source file). Stills, colours and held frames don't move."""
    import letitedit.timing.timing_signals as timing_signals
    fps, top = craft_checks.visible_frames(script)
    flags = [False] * len(top)
    runs = {}
    for f, rec in enumerate(top):
        if rec is None or rec.get('in_s') is None or os.path.splitext(str(rec['file']).lower())[1] not in VIDEO_EXT:
            continue
        runs.setdefault(id(rec), (rec, []))[1].append(f)
    for rec, frames in runs.values():
        speed = float(rec.get('speed') or 1.0)
        a = float(rec['in_s']) + (frames[0] - rec['f0']) * speed / fps
        b = float(rec['in_s']) + (frames[-1] + 1 - rec['f0']) * speed / fps
        sig = timing_signals.signals(str(rec['file']), start=max(0.0, a), end=b, lanes=['motion'])
        src_flags, src_fps = flags_from_lane(sig['lanes']['motion']), float(sig['fps'])
        for f in frames:
            k = int(round((float(rec['in_s']) + (f - rec['f0']) * speed / fps) * src_fps))
            flags[f] = 0 <= k < len(src_flags) and bool(src_flags[k])
    return flags, fps


# ---------------------------------------------------------------------------- the facts

def stretches(flags, fps):
    """[(t0, t1)] of unreadable frames, joined across gaps under MERGE_GAP_S."""
    out = []
    f = 0
    while f < len(flags):
        if not flags[f]:
            f += 1
            continue
        g = f
        while g < len(flags) and flags[g]:
            g += 1
        if out and f / fps - out[-1][1] < MERGE_GAP_S:
            out[-1][1] = g / fps
        else:
            out.append([f / fps, g / fps])
        f = g
    return [(round(a, 3), round(b, 3)) for a, b in out]


def _share(flags, fps, t0, t1):
    a, b = max(0, int(round(t0 * fps))), min(len(flags), int(round(t1 * fps)))
    return (sum(1 for x in flags[a:b] if x) / (b - a), (b - a) / fps) if b > a else (0.0, 0.0)


def pointing_words(words):
    """The words that point at something to be seen ("this", "here", "you can see"), not "we'll see"."""
    out = []
    for i, w in enumerate(words):
        word = str(w.get('w') or '').lower().strip('.,!?;:"\'')
        if not POINT_WORDS.match(word):
            continue
        before = str(words[i - 1].get('w') or '').lower().strip('.,!?;:"') if i else ''
        if word == 'see' and before in NOT_POINTING_BEFORE:
            continue
        out.append(i)
    return out


def _line(words, i0, i1):
    return ' '.join(str(w.get('w') or '') for w in words[max(0, i0 - 3):i1 + 6])


def findings_from(flags, fps, words, keep=(), duration=None):
    """(findings, facts): the pointing lines and must-keep lines whose picture is mostly unreadable (major), and
    unreadable stretches of UNDER_WORDS_S or more under other spoken words (minor). words: [{w, t0, t1}] on the
    timeline, in order; keep: [(t0, t1, label)] must-keep spans on the timeline."""
    words = sorted((w for w in words or [] if w.get('t0') is not None), key=lambda w: float(w['t0']))
    end = duration if duration is not None else len(flags) / fps
    out, looks = [], []
    # each pointing word's look, joined when they overlap (one line, one finding)
    for i in pointing_words(words):
        t0 = float(words[i]['t0'])
        t1 = min(end, t0 + POINT_WINDOW_S)
        if looks and t0 <= looks[-1]['t1']:
            looks[-1].update(t1=max(looks[-1]['t1'], t1), i1=i)
        else:
            looks.append({'t0': t0, 't1': t1, 'i0': i, 'i1': i})
    worst = None
    for lk in looks:
        share, secs = _share(flags, fps, lk['t0'], lk['t1'])
        lk['share'] = share
        if worst is None or share > worst['share']:
            worst = lk
        if share >= POINT_SHARE and secs > 0:
            text = _line(words, lk['i0'], lk['i1'])
            out.append({'at': round(lk['t0'], 2), 't1': round(lk['t1'], 2), 'severity': 'major',
                        'check': 'picture_under_pointing_line',
                        'what': f"under \"{text}\" ({_clock(lk['t0'])}-{_clock(lk['t1'])}), a line that points at "
                                f"something to be seen, the picture is a whip, a fast camera move or shake for "
                                f"{share:.0%} of the {secs:.1f} s after the pointing word (camera faster than "
                                f"{FAST_FW_S:g} frame widths a second, the timing map's whip, or shake over "
                                f"{SHAKE_FW_S:g}): what the line names can't be read while it is said"})
    for t0, t1, label in keep or ():
        share, secs = _share(flags, fps, t0, t1)
        if share >= POINT_SHARE and secs > 0 and not any(f['at'] < t1 and f['t1'] > t0 for f in out):
            out.append({'at': round(t0, 2), 't1': round(t1, 2), 'severity': 'major', 'check': 'picture_under_must_keep',
                        'what': f"the must-keep line {label} ({_clock(t0)}-{_clock(t1)}) plays over a whip, a fast "
                                f"camera move or shake for {share:.0%} of it: the picture under it can't be read"})
    spans = stretches(flags, fps)
    for a, b in spans:
        if b - a < UNDER_WORDS_S or any(f['at'] < b and f['t1'] > a for f in out):
            continue
        said = [w for w in words if float(w['t0']) < b and float(w.get('t1', w['t0'])) > a]
        if said:
            out.append({'at': round(a, 2), 't1': round(b, 2), 'severity': 'minor', 'check': 'picture_under_words',
                        'what': f"{b - a:.1f} s of whip, fast camera move or shake ({_clock(a)}-{_clock(b)}) under "
                                f"\"{' '.join(str(w['w']) for w in said[:12])}\""})
    facts = (f"{len(spans)} unreadable camera stretch(es) on the picture"
             + (f" ({', '.join(f'{_clock(a)}-{_clock(b)}' for a, b in spans[:6])})" if spans else '')
             + f"; {len(looks)} pointing word look(s)"
             + (f", the most unreadable {worst['share']:.0%} at {_clock(worst['t0'])}" if worst else ''))
    return out, facts


# ---------------------------------------------------------------------------- b-roll

def _same(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _talk_share(path, log_shares):
    for f, share in (log_shares or {}).items():
        if _same(f, path) or os.path.basename(str(f)).lower() == os.path.basename(str(path)).lower():
            return share
    try:
        import letitedit.footage.speech as speech
        from letitedit.core import media
        ws = speech.cached_words(path)
        if ws is None:
            return None
        dur = float((media.probe(str(path)).get('format') or {}).get('duration') or 0)
        talk = sum(max(0.0, float(w['e']) - float(w['s'])) for w in ws)
        return round(talk / dur, 3) if dur > 0 else None
    except Exception:  # noqa: BLE001 - unknown
        return None


def broll_unused(script, footage, log_shares=None):
    """{'broll': [files], 'used': [files], 'unknown': [files]}: the footage's video files with little or no talk
    (talk share at most BROLL_TALK_SHARE: log.json's, else the cached words'), and which of them any shown video track
    of the cut uses."""
    shown = []
    for t in script.get('tracks') or []:
        if t.get('kind', 'video') != 'video' or t.get('hide') in ('video', 'both'):
            continue
        for it in t.get('items') or []:
            freeze = it.get('freeze')
            clip = it.get('clip') or (freeze.get('clip') if isinstance(freeze, dict) else None)
            if clip:
                shown.append(str(clip))
    out = {'broll': [], 'used': [], 'unknown': []}
    for f in footage or []:
        f = f.get('file') or f.get('path') if isinstance(f, dict) else f       # a brief may give {file, use}
        if not f or os.path.splitext(str(f).lower())[1] not in VIDEO_EXT:
            continue
        share = _talk_share(f, log_shares)
        if share is None:
            out['unknown'].append(str(f))
            continue
        if share <= BROLL_TALK_SHARE:
            out['broll'].append(str(f))
            if any(_same(s, f) for s in shown):
                out['used'].append(str(f))
    return out


def broll_finding(b):
    """The fact, when the footage has b-roll and the cut shows none of it."""
    if not b['broll'] or b['used']:
        return None
    names = ', '.join(os.path.basename(f) for f in b['broll'][:6])
    return {'at': None, 't1': None, 'severity': 'minor', 'check': 'broll_unused',
            'what': f"the footage has {len(b['broll'])} b-roll file(s) (video with little or no talk: {names}) and the "
                    "cut shows none of them"}


def _log_shares(project):
    """{file: talk_share} from the video's log.json, when there is one."""
    import json
    from pathlib import Path
    try:
        import letitedit.timeline.project_journal as project_journal
        log = project_journal.folder(Path(project).resolve()) / 'log.json'
        data = json.loads(log.read_text(encoding='utf-8-sig'))
        return {f['file']: f['talk_share'] for f in data.get('files') or [] if f.get('talk_share') is not None}
    except Exception:  # noqa: BLE001 - no log: the words say
        return {}


def keep_spans(script, brief):
    """[(t0, t1, label)] on the timeline: the brief's must_keep source ranges ({source, from, to}) where the cut
    plays them."""
    from letitedit.timeline.edit_sync import layout
    out = []
    for req in (brief or {}).get('must_keep') or []:
        if not (isinstance(req, dict) and req.get('source') and req.get('from') is not None and req.get('to') is not None):
            continue
        a, b = float(req['from']), float(req['to'])
        for t in script.get('tracks') or []:
            for it, s, e in layout(t):
                clip = it.get('clip')
                if not clip or not (_same(clip, req['source']) or os.path.basename(str(clip)).lower()
                                    == os.path.basename(str(req['source'])).lower()):
                    continue
                lo, hi = max(a, float(it['in'])), min(b, float(it['out']))
                if hi > lo:
                    sp = float(it.get('speed') or 1.0)
                    out.append((s + (lo - float(it['in'])) / sp, s + (hi - float(it['in'])) / sp,
                                f"{os.path.basename(str(req['source']))} {a:g}-{b:g} s"))
    return out


# ---------------------------------------------------------------------------- the floor

FLOOR_CHECKS = ('picture_under_pointing_line', 'picture_under_must_keep')
FLOOR_KINDS = ('shots', 'story', 'pacing')
FLOOR_SLACK_S = 0.5


def floor(findings):
    """A critic's finding about the picture (its kind shots, story or pacing) inside a span this check measured as
    major is raised to major, with the measure named. Returns the findings raised."""
    spans = [(float(f['at_s']), float(f.get('until_s') or f['at_s'])) for f in findings
             if f.get('source') == 'project' and f.get('check') in FLOOR_CHECKS and f.get('severity') in ('major', 'critical')
             and f.get('at_s') is not None]
    raised = []
    for f in findings:
        if f.get('source') != 'critic' or f.get('severity') not in ('minor',) or f.get('at_s') is None:
            continue
        kind = str(f.get('what') or '').split(':', 1)[0].strip().lower()
        at = float(f['at_s'])
        if kind in FLOOR_KINDS and any(a - FLOOR_SLACK_S <= at <= b + FLOOR_SLACK_S for a, b in spans):
            f['severity'] = 'major'
            f['evidence'] = (str(f.get('evidence') or '') + ' At least major here: the picture under these words is '
                             'measured as unreadable (picture under the words).').strip()
            raised.append(f)
    return raised


# ---------------------------------------------------------------------------- callers

def _words(script):
    import letitedit.timeline.timeline_speech as timeline_speech
    missing = []
    ws = timeline_speech.timeline_words(script, cached_only=True, missing=missing)
    return ws, missing


def review(project, video, brief):
    """(findings, facts line, numbers) for the review bundle, measured on the export."""
    import letitedit.timeline.edit_script as es
    script = es.read(project)
    words, missing = _words(script)
    flags, fps = export_motion(video)
    cuts, note = craft_checks.visible_cuts(script, len(flags) / fps)
    flags = guard_cuts(flags, fps, cuts)
    out, facts = findings_from(flags, fps, words, keep_spans(script, brief), len(flags) / fps)
    if missing:
        facts += f"; words not transcribed for {len(missing)} clip(s), so lines over them weren't read"
    if note:
        facts += f'; {note}, so its cut points were not left out of the camera motion'
    b = broll_unused(script, (brief or {}).get('footage') or [], _log_shares(project))
    f = broll_finding(b)
    if f:
        out.append(f)
    facts += (f"; b-roll in the footage: {len(b['broll'])} file(s), {len(b['used'])} in the cut"
              + (f", {len(b['unknown'])} not yet known" if b['unknown'] else ''))
    numbers = {'unreadable_picture_s': [[a, b_] for a, b_ in stretches(flags, fps)],
               'broll_files_in_footage': len(b['broll']), 'broll_files_in_cut': len(b['used'])}
    return out, facts, numbers


def cut(project, brief=None):
    """{'findings', 'facts'} for the fine phase's self-check, measured on the cut's own sources (no render)."""
    import letitedit.timeline.edit_script as es
    script = es.read(project)
    if brief is None:
        try:
            import letitedit.review.brief_check as brief_check
            brief = brief_check.load(None, project) or {}
        except Exception:  # noqa: BLE001 - no brief: no must-keep spans, no footage list
            brief = {}
    words, missing = _words(script)
    flags, fps = cut_motion(script)
    out, facts = findings_from(flags, fps, words, keep_spans(script, brief), len(flags) / fps if fps else None)
    if missing:
        facts += f"; words not transcribed for {len(missing)} clip(s)"
    f = broll_finding(broll_unused(script, (brief or {}).get('footage') or [], _log_shares(project)))
    if f:
        out.append(f)
    slim = craft_checks.slivers(script, craft_checks.project_markers(project))
    out += slim
    facts += f"; {len(slim)} shot(s) under {craft_checks.SLIVER_S:g} s between two cuts"
    return {'findings': [{k: v for k, v in x.items() if k not in ('t1', 'fix')} for x in out], 'facts': facts,
            'measured_by': 'the timing map\'s motion lane on the source range of each visible shot, the cut\'s '
                           'cached words, and the visible shots\' lengths'}
