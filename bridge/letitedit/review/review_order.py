"""The order of a review: the code checks first, then one critic, a second critic round only for a real defect, and no
critic on a video that hasn't changed. review_bundle.bundle follows it while the switch is on (the default); off,
the bundle runs exactly as before.

The switch: settings.json `review_code_first` (default true; the environment variable LETITEDIT_REVIEW_CODE_FIRST,
1 or 0, wins).

enabled()                      the switch.
code_checks(...)               two measured checks that only run with the switch on: captions in the picture when the
                               video should have them, and caption text inside a named platform's covered areas.
code_failures(checks, findings) the measured problems that hold the critic back: the mechanical gate checks (loudness,
                               true peak, black frames, silences, the words heard), words cut at clip edges, a project
                               changed after its export, captions missing from the picture, text under an app's buttons,
                               and (with review_craft_checks on too, T361) a shot under 0.3 s between two cuts.
decide(...)                    what the critic does on this call: 'run', 'held' (a code check failed: no critic, no round
                               used), 'reuse' (the last review stands: the video is unchanged, or only mechanical fixes
                               followed a review that found no real defect) or 'as_asked' (critic='again', the round
                               limit, or no critic asked: the bundle's own rules).
same_cut(...)                  plain words when this call's cut is identical to the last full round's (the same project
                               state, or the same export of the same cut, against the same brief), else None.
unchanged(...)                 the one piece of the order that is always on, whatever the switch: a critic round is
                               never spent on a cut identical to the last round's ('reuse', no round counted).
settle(order, may_look)        a reuse with mechanical notes to close: 'look' (one targeted look checks those notes) or,
                               when that look is spent, 'run'. A note is never closed unchecked.
after_failed_look(order, why)  the look didn't answer: the reviewer reads the export ('run').
round_facts(...)               what a full round records, so the next call can tell what changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SETTING = 'review_code_first'
ENV = 'LETITEDIT_REVIEW_CODE_FIRST'

# gate.py checks that measure the file itself: a failure is fixed in the mix or the timeline, never a matter of taste
MECHANICAL_GATE = ('loudness_lufs', 'true_peak_dbtp', 'black_tail_s', 'frame0_not_black', 'tail_silence_s',
                   'silence_first3s_s', 'silent_share', 'expected_words_audible')
HOLDING = ('critical', 'major')
# a critic's kinds (letitedit-review): these are about picture, story or sound; 'text' and 'technical' are mechanical
REAL_KINDS = ('story', 'pacing', 'shots', 'sound', 'brief')
NO_CAPTIONS = ('none', 'no', 'off', 'false', '0', 'srt', 'srt only', 'srt_only', 'file', 'upload')
CAPTION_TRACK = re.compile(r'caption|subtitle', re.I)
COVERED_SHARE = 0.25          # of a caption's text box inside a covered area: the app's buttons or description hide it


def enabled():
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


# ---------------------------------------------------------------------------- fingerprints

def export_hash(video):
    """sha256 of the whole export: the same file is the same video, wherever and whenever it was written."""
    h = hashlib.sha256()
    with open(video, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def brief_hash(brief):
    return hashlib.sha256(json.dumps(brief or {}, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]


def cut_signature(timeline):
    """The cut, without its filters: every track's clips (source, in, out, place, speed), in order. A level, a grade, a
    caption's style or a position changes filters and leaves this alone; a trim, an insert, a move, a cutaway or a music
    placement changes it. None when there is no timeline."""
    if timeline is None:
        return None
    h = hashlib.sha256()
    for t in timeline.tracks:
        h.update(f'|{t.kind}:{t.hide}'.encode())
        for it in t.items:
            if it.service == 'blank' or not it.producer_id:
                continue
            h.update(f'#{it.service}:{it.resource}:{it.in_}:{it.out}:{it.start}:{it.speed:g}'.encode('utf-8', 'replace'))
    return h.hexdigest()[:24]


def round_facts(video_hash, brief, timeline):
    return {'export_sha256': video_hash, 'brief_hash': brief_hash(brief), 'cut': cut_signature(timeline)}


# ---------------------------------------------------------------------------- the two new code checks

def wants_captions(brief, kind, timeline):
    """True / False from the brief's `captions` (or `captions.enabled`); with the brief silent, a Short whose project
    has caption cues wants them drawn (an upload-only caption file is said with captions: "srt"); else None."""
    value = (brief or {}).get('captions') if isinstance(brief, dict) else None
    if isinstance(value, dict):
        value = value.get('enabled', value.get('burn_in', value.get('mode')))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in NO_CAPTIONS
    if kind == 'short' and timeline is not None and any(timeline.subtitle_feeds.values()):
        return True
    return None


def drawn_captions(timeline):
    """What draws captions into the picture: a burn filter on a feed with cues, word-by-word caption graphics or a
    caption text layer on a shown video track. [] when nothing does."""
    out = []
    for fp in timeline.burn_filters:
        feed = fp.get('feed', 'Subtitles')
        if timeline.subtitle_feeds.get(feed):
            out.append(f'subtitles {feed} burned in')
    import letitedit.timeline.timeline_model as tm
    for t in timeline.video_tracks():
        if 'video' in (t.hide or ''):
            continue
        items = [it for it in t.items if it.service != 'blank' and it.producer_id]
        words = layers = 0
        for it in items:
            p = tm.props(it.elem) if it.elem is not None else {}
            try:
                raw = p.get('letitedit_ai:graphic')
                words += (json.loads(raw).get('template') == 'word_captions') if raw else 0
                raw = p.get('letitedit_ai:made')
                layers += (json.loads(raw).get('kind') == 'ass') if raw else 0
            except (ValueError, AttributeError):
                pass
        if words:
            out.append(f'{words} word caption(s) on {t.name}')
        elif layers:
            out.append(f'{layers} subtitle layer(s) on {t.name}')
        elif items and CAPTION_TRACK.search(t.name or ''):
            out.append(f'{len(items)} item(s) on the caption track {t.name}')
    return out


def captions_finding(brief, kind, timeline):
    """A major finding when the video should have captions and nothing draws them, else None (and why, for coverage)."""
    if timeline is None:
        return None, 'no project read'
    want = wants_captions(brief, kind, timeline)
    if not want:
        return None, ('the brief asks for none' if want is False else 'not asked for')
    drawn = drawn_captions(timeline)
    if drawn:
        return None, '; '.join(drawn)
    cues = sum(len(c) for c in timeline.subtitle_feeds.values())
    what = ('captions missing from the picture: the project has ' + (f'{cues} caption cue(s) in a subtitle track that '
            'no burn filter draws' if cues else 'no captions') + ', and nothing else draws captions')
    fix = ('Burn the captions in with {op: captions} (a track the export draws), or say they are a caption file only '
           'with the brief\'s captions: "srt"; then export again.')
    return {'severity': 'major', 'what': what, 'fix': fix, 'check': 'captions_present'}, 'missing'


def platform_zones(platform, width, height):
    """[(x0, y0, x1, y1, name)] fractions: a platform's covered areas, for a frame of its own shape. Areas from ad
    guidance ('official-ads') are left out: the apps' organic viewer leaves more room, and caption placement uses
    them only as a preference."""
    import letitedit.catalogs.platforms as platforms
    prof = platforms.load(platform)
    zones = prof.get('safe_zones') or {}
    try:
        pw, ph = prof['export_preset']['width']['value'], prof['export_preset']['height']['value']
    except (KeyError, TypeError):
        pw = ph = None
    if not pw or not ph or abs(pw / ph - width / height) > 0.02 or zones.get('status') == 'official-ads':
        return []
    return [(z['x'], z['y'], z['x'] + z['w'], z['y'] + z['h'], f"{prof['id']}: {z['name']}")
            for z in zones.get('value') or []]


def covered_findings(boxes, platforms_, width, height):
    """Findings for caption text boxes [(start_s, end_s, (x0, y0, x1, y1) fractions, text)] that sit inside a named
    platform's covered areas: one major per platform area, at the first caption there."""
    out = []
    for pid in platforms_ or []:
        try:
            zones = platform_zones(pid, width, height)
        except Exception:  # noqa: BLE001 - an unknown platform: the gate notes it
            continue
        for x0, y0, x1, y1, name in zones:
            hits = []
            for s, e, (a0, b0, a1, b1), text in boxes:
                area = max(0.0, a1 - a0) * max(0.0, b1 - b0)
                inside = max(0.0, min(a1, x1) - max(a0, x0)) * max(0.0, min(b1, y1) - max(b0, y0))
                if area and inside / area > COVERED_SHARE:
                    hits.append((s, text))
            if hits:
                s, text = hits[0]
                out.append({'severity': 'major', 'at': s, 'check': 'covered_areas',
                            'what': f'caption text under {name} ({len(hits)} caption(s), the first "{str(text)[:40]}")',
                            'fix': 'Move the captions clear of the app\'s covered areas: letitedit_caption_fit(project, '
                                   f"platform='{pid}') plans it; apply the plan, then export again."})
    return out


def code_checks(project, brief, kind, platforms_, timeline, cover):
    """Run the two new checks; returns their findings as review_bundle findings (source 'project')."""
    found = []
    try:
        f, detail = captions_finding(brief, kind, timeline)
        if f:
            found.append(f)
        cover('captions in the picture', 'done' if timeline is not None else 'not done', detail)
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        cover('captions in the picture', 'failed', f'{type(e).__name__}: {e}'[:300])
    if not platforms_:
        cover('covered areas', 'not done', 'no platform named in the brief')
    elif not project or timeline is None:
        cover('covered areas', 'not done', 'no project read')
    else:
        try:
            import letitedit.review.checks as checks
            boxes = checks.caption_text_boxes(project)
            hits = covered_findings(boxes, platforms_, timeline.profile['width'], timeline.profile['height'])
            found += hits
            cover('covered areas', 'done', f"{len(boxes)} caption(s) against {', '.join(platforms_)}'s covered areas: "
                  + (f'{len(hits)} area(s) with captions under them' if hits else 'all clear'))
        except Exception as e:  # noqa: BLE001
            cover('covered areas', 'failed', f'{type(e).__name__}: {e}'[:300])
    return [{'source': 'project', 'severity': f['severity'], 'at_s': f.get('at') if f.get('at') is None else
             round(float(f['at']), 2), 'at': _clock(f.get('at')), 'what': f['what'], 'evidence': '', 'fix': f['fix'],
             'check': f['check']} for f in found]


def _clock(s):
    if s is None:
        return ''
    m, sec = divmod(float(s), 60)
    return f'{int(m)}:{sec:04.1f}'


# ---------------------------------------------------------------------------- the order

def code_failures(checks, findings):
    """The measured problems the AI fixes before any critic reads the video (critical or major, the AI's)."""
    from letitedit.review.review_bundle import gate_severity     # the bundle's own rule: advisory -> minor
    out = []
    for c in (checks or {}).get('checks') or []:
        if c.get('state') == 'fail' and c.get('check') in MECHANICAL_GATE and gate_severity(c) in HOLDING:
            out.append({'check': c['check'], 'what': f"{c['check']} = {c.get('value')} (wanted {c.get('threshold')})",
                        'at': c.get('at_s')})
    for f in findings:
        if f.get('severity') not in HOLDING or f.get('owner') == 'person':
            continue
        if f.get('check') in ('captions_present', 'covered_areas', 'cut_words', 'sliver_shot'):
            out.append({'check': f['check'], 'what': f['what'], 'at': f.get('at_s')})
        elif f.get('source') == 'freshness':
            out.append({'check': 'freshness', 'what': f['what'], 'at': None})
    return out


def kind_of(item):
    return str(item.get('what') or '').split(':', 1)[0].strip().lower()


def is_real(item):
    """A critic's finding about picture, story or sound (or any critical one): the kind a second round looks at."""
    if item.get('source') != 'critic' or item.get('owner') == 'person':
        return False
    return item.get('severity') == 'critical' or (item.get('severity') == 'major' and kind_of(item) in REAL_KINDS)


def is_mechanical(item):
    return (item.get('source') == 'critic' and item.get('owner') != 'person' and item.get('severity') == 'major'
            and kind_of(item) not in REAL_KINDS)


def same_cut(memory, project_hash, brief, video_hash=None, timeline=None):
    """Plain words when the cut this call reviews is identical to the last full round's, else None: the same project
    state (project_hash: what the review read, an open window's state included), or the same export file of the same
    cut; either against the same brief (a round that recorded no brief is taken as the same one). A changed brief, a
    changed project, or a round with nothing to compare is never identical."""
    last = (memory.get('rounds') or [None])[-1]
    if not last:
        return None
    if last.get('brief_hash') and last['brief_hash'] != brief_hash(brief):
        return None
    done = len(memory.get('rounds') or [])
    if project_hash and last.get('project_hash') == project_hash:
        return f'nothing in the project has changed since review round {done}'
    cut = cut_signature(timeline)
    if video_hash and last.get('export_sha256') == video_hash and cut and last.get('cut') == cut:
        return f'this is the same export of the same cut as review round {done}'
    return None


def unchanged(critic, memory, round_limit, project_hash, brief, last_review, video_hash=None, timeline=None):
    """Always on: a critic='run' within the round limit on a cut identical to the last round's (same_cut) reuses that
    round's review and counts no round. {'critic': 'reuse', 'why', 'close': [], 'code_failures': [], 'unchanged': True},
    or None (anything else: the bundle's own rules)."""
    import letitedit.review.review_memory as review_memory
    if critic != 'run' or review_memory.rounds_done(memory) >= round_limit:
        return None
    if not last_review or not Path(last_review).is_file():
        return None
    why = same_cut(memory, project_hash, brief, video_hash, timeline)
    if not why:
        return None
    return {'critic': 'reuse', 'close': [], 'code_failures': [], 'unchanged': True,
            'why': f'{why}, so no reviewer ran again and no review round was used: that round\'s review stands'}


def decide(critic, memory, round_limit, failures, video_hash, brief, timeline, project_hash, last_review):
    """{'critic': run | held | reuse | as_asked, 'why': plain words, 'close': [ids], 'code_failures': [...]}."""
    import letitedit.review.review_memory as review_memory
    done = review_memory.rounds_done(memory)
    base = {'code_failures': failures, 'close': []}
    if critic != 'run' or done >= round_limit:
        return {**base, 'critic': 'as_asked', 'why': ''}
    if failures:
        return {**base, 'critic': 'held',
                'why': f'{len(failures)} measured problem(s) to fix first ({", ".join(sorted({f["check"] for f in failures}))}): '
                       'no reviewer was called and no review round was used'}
    last = (memory.get('rounds') or [None])[-1]
    if not last or not last_review or not Path(last_review).is_file():
        return {**base, 'critic': 'run', 'why': 'the first review of this video'}
    if last.get('export_sha256') == video_hash and last.get('brief_hash') == brief_hash(brief):
        return {**base, 'critic': 'reuse',
                'why': f'the video is the same file review round {done} judged: that review stands'}
    same = unchanged(critic, memory, round_limit, project_hash, brief, last_review, video_hash, timeline)
    if same:
        return {**base, **same}
    items = [i for i in memory.get('items') or [] if i.get('status') == 'open']
    real = [i for i in items if is_real(i)]
    changed = project_hash is None or last.get('project_hash') != project_hash
    cut = cut_signature(timeline)
    if real and changed:
        return {**base, 'critic': 'run',
                'why': f'review round {done} found {len(real)} picture, story or sound problem(s) and the project changed'}
    if cut is None or last.get('cut') is None or last['cut'] != cut:
        return {**base, 'critic': 'run', 'why': f'the cut changed since review round {done}'}
    close = [i['id'] for i in items if is_mechanical(i)] if changed else []
    return {**base, 'critic': 'reuse', 'close': close,
            'why': (f'the cut is the same as at review round {done}, which found no picture, story or sound problem: the '
                    'measured checks ran again on this export and that review stands'
                    + (f'; {len(close)} mechanical note(s) it raised were worked on since: a targeted look checks '
                       'them' if close else ''))}


def settle(order, may_look):
    """A reuse with mechanical notes to close ({'close': [ids]}): one targeted look at those notes ('look'), or, when
    that look can't be taken (one per video), the reviewer reads this export ('run'). A note is never closed by
    assumption; anything else is returned as it is."""
    if not order or order.get('critic') != 'reuse' or not order.get('close'):
        return order
    if may_look:
        return {**order, 'critic': 'look'}
    return {**order, 'critic': 'run', 'close': [],
            'why': f"{len(order['close'])} note(s) from the last review were worked on and the one targeted look at "
                   'this video is spent: a reviewer reads this export'}


def after_failed_look(order, why=''):
    """The targeted look gave no answer: the reviewer reads this export instead."""
    return {**order, 'critic': 'run', 'close': [],
            'why': "the targeted look at the last review's notes didn't answer"
                   + (f' ({str(why)[:120]})' if why else '') + ': a reviewer reads this export'}


def next_line(order):
    if order['critic'] == 'held':
        return ('Fix the measured problems first (review_order.code_failures), export again and run the bundle again: the '
                'reviewer reads the video once these pass. No review round was used.')
    if order['critic'] == 'reuse' and order.get('unchanged'):
        return ("Nothing changed since the last review, so its findings stand and no round was used. Fix what it lists, "
                'export and run the bundle again: the next reviewer reads the changed cut. Hand over only when it '
                'lists nothing left to fix.')
    if order['critic'] == 'reuse':
        return ("The last review stands for this video: no new reviewer ran. Hand over, or change the edit and review "
                'the new export.')
    if order['critic'] == 'look':
        return ("A targeted look checked the last review's open notes instead of a full review. Hand over if the "
                'verdict is ready; otherwise fix what is still open and review the new export.')
    return None
