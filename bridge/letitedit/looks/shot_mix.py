"""What a video's shots show, as a mix: people up close, people in a wider frame, close details of things, transport
and the road, and places (buildings, landscape, a street without a person as its subject). Read by the fact log's
vision model on three frames of each shot, the same instrument on a Look's reference and on a cut, and on the logged
stretches of the footage (the fact log's own facts), so the footage's own supply of each kind is known.

classify(facts)                 -> one kind (KINDS) from a shot's or stretch's facts (shot, people, subject, place)
from_camera(rows)               -> the same from a camera measure's own rows (its vision facts and face sizes), or None
measure(video, rows, ask=None)  -> [{start_s, end_s, kind, candid, facts}] for each shot row at least MIN_SHOT_S long
                                   (cached by the file's content); ask(image_lists) -> [(facts, raw)] replaces the model
profile(rows)                   -> {'format', 'shots', 'shares': {kind: share of shots}, 'candid_share'}
check(ref, cut_rows, log=None)  -> (summary, problems): each kind the cut has much less (or much more) of than the
                                   reference, with, from the footage log, unused stretches of the kind it lacks (or the
                                   footage's own limit when it holds too few)
footage_supply(log)             -> each kind's count among the footage's logged stretches, and how many the cut leaves
near_repeats(script)            -> clips of the main picture track whose file comes back after another shot within
                                   REPEAT_S, or at any distance to the same setup (a moment of the file within SETUP_S
                                   of one the cut already showed); consecutive clips of one file are one continuing
                                   scene; a file that holds over A_ROLL_SHARE of the track's time, an A-roll, is left out
replacement(log, kind, script, at_s, taken=()) -> the logged stretch of a kind for a clip at at_s that makes no
                                   repeat: unused, from a file the cut doesn't show within REPEAT_S of it, its middle
                                   not within SETUP_S of a moment of that file the cut shows anywhere

The bar: a kind's share of the cut's shots TOLERANCE (a share of the shots) under or over the reference's, for a kind
that holds at least MIN_SHARE of either. Candid: a person in view who doesn't look or talk to the camera.
Closed-set facts from a small local model (measured accuracy in the fact log): a guide to the mix, not a shot list.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

FORMAT = 'letitedit-shot-mix/1'
KINDS = ('people_close', 'people_wide', 'detail', 'transit', 'place')
WORDS = {'people_close': 'people up close (a person the subject, medium or closer)',
         'people_wide': 'people in a wider frame (street life, a crowd)',
         'detail': 'close details of things (food, an animal, an object, a sign)',
         'transit': 'transport and the road (trains, traffic, boats, a road)',
         'place': 'places (buildings, landscape, a street with nobody as its subject)'}
TOLERANCE = 0.12
MIN_SHARE = 0.10
MIN_SHOT_S = 0.3
MIN_SHOTS = 6
FROM_CAMERA_SHARE = 0.8
CANDIDATES = 6
REPEAT_S = 6.0          # one file shown twice with under this many seconds between the clips' starts reads as a repeat
A_ROLL_SHARE = 0.25     # ... unless that file holds over this share of the main track's time (a talk, an A-roll)
SETUP_S = 10.0          # two pieces of one file whose middles are under this many seconds apart in the file show one
                        # setup (the same place from the same camera): shown again anywhere in the cut it is a repeat
WIDTH = 448
VERSION = 1


def classify(facts):
    """A shot's kind from its facts ({shot, people, subject, place, ...}); None without a shot size or subject."""
    facts = facts or {}
    shot, subject = facts.get('shot'), facts.get('subject')
    people = str(facts.get('people') or '0') != '0'
    if not shot and not subject:
        return None
    if subject == 'person' and people:
        return 'people_close' if shot in ('medium', 'close-up', 'detail') else 'people_wide'
    if shot in ('close-up', 'detail') and subject not in ('vehicle', 'building', 'landscape'):
        return 'detail'
    if subject == 'vehicle' or facts.get('place') in ('road', 'inside a vehicle'):
        return 'transit'
    if subject in ('animal', 'food', 'object held up') and shot == 'medium':
        return 'detail'
    return 'place'


def from_camera(rows):
    """Shot rows with kinds from a camera measure's own rows (camera_language.measure, a Look's visual.json camera
    shots): a shot the vision model judged by its facts, one sized by a face as people (close or wide); None when under
    FROM_CAMERA_SHARE of the shots get a kind that way (the camera measure ran without the vision model, or before it
    kept facts)."""
    wanted = [r for r in rows or [] if r['end_s'] - r['start_s'] >= MIN_SHOT_S]
    out = []
    for row in wanted:
        facts = row.get('facts')
        kind = classify(facts) if facts else None
        if kind is None and row.get('size_by') == 'face':
            kind = 'people_close' if row.get('size') in ('close', 'medium') else 'people_wide'
            facts = {'people': '1', 'subject': 'person', 'shot': row.get('size')}
        elif kind is None and row.get('size_by') == 'small_face':
            kind, facts = 'people_wide', {'people': '1', 'subject': 'person', 'shot': 'wide'}
        out.append({'start_s': row['start_s'], 'end_s': row['end_s'], 'kind': kind,
                    'candid': bool(facts) and str((facts or {}).get('people') or '0') != '0'
                    and (facts or {}).get('camera') != 'yes', 'facts': facts or {}})
    if not wanted or sum(1 for r in out if r['kind']) < FROM_CAMERA_SHARE * len(wanted):
        return None
    return out


def _times(row):
    a, b = row['start_s'], row['end_s']
    return [round(a + (b - a) * f, 3) for f in (.25, .5, .75)]


def _cache_file(video):
    import letitedit.footage.footage_notes as footage_notes
    import letitedit.looks.style_import as style_import
    folder = Path(os.environ.get('LETITEDIT_CAMERA_CACHE') or (Path(style_import.CACHE).parent / 'camera'))
    return folder / f'{footage_notes.key(str(video))}-shot-mix-v{VERSION}.json'


def measure(video, rows, ask=None, cache=True):
    """Each shot row's kind from the vision model's facts on three frames of it (the model under the PC lock)."""
    import cv2
    import letitedit.looks.style_import as style_import
    wanted = [r for r in rows or [] if r['end_s'] - r['start_s'] >= MIN_SHOT_S]
    key = hashlib.sha256(json.dumps([[r['start_s'], r['end_s']] for r in wanted]).encode()).hexdigest()[:16]
    target = _cache_file(video) if cache and ask is None else None
    if target is not None and target.exists():
        try:
            saved = json.loads(target.read_text(encoding='utf-8-sig'))
            if saved.get('rows_key') == key:
                return saved['rows']
        except ValueError:
            pass
    info = style_import.probe(video)
    times = sorted({t for r in wanted for t in _times(r)})
    folder = Path(tempfile.mkdtemp(prefix='shotmix-'))
    try:
        frames = style_import.frames_at(video, times, WIDTH, info)
        paths = {}
        for t, frame in frames.items():
            path = folder / f'{t:010.3f}.jpg'
            cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            paths[t] = str(path)
        lists = [[paths[t] for t in _times(r) if t in paths] for r in wanted]
        pairs = [(r, ims) for r, ims in zip(wanted, lists) if ims]
        if ask is None:
            import letitedit.core.render_lock as render_lock
            import letitedit.footage.factlog as factlog
            with render_lock.slot('Look shot mix', timeout_s=3600):
                answers, _ = factlog.ask([ims for _, ims in pairs])
        else:
            answers = ask([ims for _, ims in pairs])
        out = []
        for (row, _), (facts, _raw) in zip(pairs, answers):
            facts = {k: facts.get(k) for k in ('shot', 'people', 'subject', 'place', 'camera', 'face')}
            out.append({'start_s': row['start_s'], 'end_s': row['end_s'], 'kind': classify(facts),
                        'candid': (str(facts.get('people') or '0') != '0' and facts.get('camera') == 'no'),
                        'facts': facts})
    finally:
        for path in folder.glob('*'):
            path.unlink(missing_ok=True)
        folder.rmdir()
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps({'format': FORMAT, 'rows_key': key, 'rows': out}, indent=1), encoding='utf-8')
        temporary.replace(target)
    return out


def profile(rows):
    """The mix over shot rows: each kind's share of the shots with a kind, and the candid share of those with people."""
    known = [r for r in rows or [] if r.get('kind')]
    shares = {k: round(sum(1 for r in known if r['kind'] == k) / len(known), 3) if known else 0. for k in KINDS}
    peopled = [r for r in known if str((r.get('facts') or {}).get('people') or '0') != '0']
    return {'format': FORMAT, 'shots': len(known), 'shares': shares,
            'candid_share': round(sum(1 for r in peopled if r.get('candid')) / len(peopled), 3) if peopled else None}


def footage_supply(log):
    """Each kind's logged stretches in the footage ({kind: {'stretches', 'unused'}}) from camera_language.footage_log."""
    out = {k: {'stretches': 0, 'unused': 0} for k in KINDS}
    for stretch in (log or {}).get('stretches') or []:
        kind = classify(stretch)
        if kind:
            out[kind]['stretches'] += 1
            out[kind]['unused'] += 0 if stretch.get('used') else 1
    return out


def _clock(seconds):
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def _candidates(log, kind):
    found = [s for s in (log or {}).get('stretches') or [] if classify(s) == kind and not s.get('used')]
    found.sort(key=lambda s: (s.get('used_s') or 0, -(s['to'] - s['from']), s['file'], s['from']))
    out, per_file = [], {}
    for s in found:
        if per_file.get(s['file'], 0) >= 2:
            continue
        per_file[s['file']] = per_file.get(s['file'], 0) + 1
        out.append(f"{s['file']} {_clock(s['from'])}-{_clock(s['to'])}")
        if len(out) >= CANDIDATES:
            break
    return out


def _main_clips(script):
    """[(item, start_s, end_s, normalised file)] for the footage clips of the main picture track, in order."""
    from letitedit.timeline.edit_sync import layout, main_track
    track = main_track(script or {'tracks': []})
    if track is None:
        return []
    fps = float(((script or {}).get('profile') or {}).get('fps') or 25.)
    return [(it, a, b, os.path.normcase(os.path.abspath(str(it['clip']))))
            for it, a, b in layout(track, fps) if 'clip' in it]


def _middle(item, a, b):
    """The moment of its file a clip shows at its middle (seconds in the file)."""
    from letitedit.timeline.edit_sync import to_seconds
    speed = abs(float(item.get('speed') or 1.)) or 1.
    return float(to_seconds(item.get('in') or 0)) + (b - a) * speed / 2


def _a_rolls(placed):
    total = sum(b - a for _, a, b, _ in placed) or 1.
    held = {}
    for _, a, b, path in placed:
        held[path] = held.get(path, 0.) + (b - a)
    return {path for path, s in held.items() if s / total > A_ROLL_SHARE}


def near_repeats(script, window_s=REPEAT_S, setup_s=SETUP_S):
    """[{'file', 'ids', 'at_s'}]: each run of main-track clips from one file that comes back after another clip with its
    start within window_s of the run's previous clip, or at any distance to the same setup (its middle within setup_s,
    in the file, of the middle of a clip of the run); two or more clips. A clip straight after one of its own file
    continues that scene and isn't counted; A-roll files (over A_ROLL_SHARE of the track's time) left out."""
    placed = _main_clips(script)
    skip = _a_rolls(placed)
    runs, last, previous = [], {}, None
    for it, a, b, path in placed:
        follows, previous = previous == path, path
        if path in skip or follows:
            if follows and last.get(path):
                last[path][-1]['at_s'][-1] = round(a, 2)  # the scene goes on: measure the next return from here
                last[path][-1]['middles'].append(_middle(it, a, b))     # ... and it shows this setup too
            continue
        middle = _middle(it, a, b)
        mine = last.setdefault(path, [])
        run = next((r for r in reversed(mine) if a - r['at_s'][-1] < window_s), None) or next(
            (r for r in mine if any(abs(middle - m) < setup_s for m in r['middles'])), None)
        if run is not None:
            run['ids'].append(it.get('id'))
            run['at_s'].append(round(a, 2))
            run['middles'].append(middle)
            mine.remove(run)
            mine.append(run)                              # the latest return measures the next near one
            continue
        run = {'file': Path(str(it['clip'])).name, 'ids': [it.get('id')], 'at_s': [round(a, 2)], 'middles': [middle]}
        runs.append(run)
        mine.append(run)
    return [{k: v for k, v in r.items() if k != 'middles'} for r in runs if len(r['ids']) > 1]


def repeats_text(runs):
    """One sentence naming the near repeats, or ''."""
    if not runs:
        return ''
    named = '; '.join(f"{r['file']} at {', '.join(_clock(s) for s in r['at_s'])}" for r in runs[:6])
    more = f" and {len(runs) - 6} more" if len(runs) > 6 else ''
    return (f"repeats (one file shown again within {REPEAT_S:g} s, or the same setup of it again anywhere, which "
            f"reads as the same place twice): {named}{more}")


def replacement(log, kind, script, at_s, window_s=REPEAT_S, taken=(), setup_s=SETUP_S):
    """The logged stretch (camera_language.footage_log's) of kind for a clip placed at at_s with no repeat: unused by
    the cut, from a file no main-track clip shows within window_s of at_s and not in taken (paths already picked
    nearby), its middle not within setup_s of the middle of any main-track clip of its file (the same setup), the file
    the cut uses least first, then the longest stretch; None when the footage has none."""
    placed = _main_clips(script)
    near = {path for _, a, b, path in placed if abs(a - at_s) < window_s}
    near |= {os.path.normcase(os.path.abspath(str(x))) for x in taken}
    used, shown = {}, {}
    for it, a, b, path in placed:
        used[path] = used.get(path, 0.) + (b - a)
        shown.setdefault(path, []).append(_middle(it, a, b))
    found = []
    for s in (log or {}).get('stretches') or []:
        path = os.path.normcase(os.path.abspath(str(s.get('path') or '')))
        if classify(s) != kind or s.get('used') or path in near:
            continue
        if any(abs((s['from'] + s['to']) / 2 - m) < setup_s for m in shown.get(path, ())):
            continue
        found.append((used.get(path, 0.), -(s['to'] - s['from']), str(s.get('file') or ''), s['from'], s))
    return min(found, key=lambda f: f[:4])[4] if found else None


def check(ref, cut_rows, log=None):
    """(summary, problems): the cut's mix against the reference's (profile dicts or rows), each kind under or over the
    reference's share by more than TOLERANCE; a kind it lacks names unused logged stretches of that kind, or says the
    footage holds too few of it (its limit, not a fault in the cut)."""
    ref = ref if isinstance(ref, dict) and 'shares' in ref else profile(ref)
    cut = profile(cut_rows)
    summary = {'format': FORMAT, 'reference': ref, 'cut': cut}
    problems = []
    if ref['shots'] < MIN_SHOTS or cut['shots'] < MIN_SHOTS:
        summary['not_measured'] = 'too few shots with a kind on one side'
        return summary, problems
    supply = footage_supply(log) if log else None
    if supply:
        summary['footage'] = supply
    limits = []
    for kind in KINDS:
        theirs, mine = ref['shares'][kind], cut['shares'][kind]
        if max(theirs, mine) < MIN_SHARE or abs(mine - theirs) <= TOLERANCE:
            continue
        if mine < theirs:
            want = round((theirs - mine) * cut['shots'])
            text = (f"{WORDS[kind]}: {mine:.0%} of the cut's shots against the reference's {theirs:.0%} (about {want} "
                    f"more of {cut['shots']})")
            if supply is not None:
                spare = supply[kind]['unused']
                picks = _candidates(log, kind)
                if spare < want:
                    limits.append(f"{WORDS[kind]}: the footage's log holds {spare} unused stretch(es) of it, under the "
                                  f"{want} the reference's share asks for (the footage's limit)")
                if picks:
                    text += '; unused in the footage: ' + '; '.join(picks)
            problems.append(text)
        else:
            problems.append(f"{WORDS[kind]}: {mine:.0%} of the cut's shots against the reference's {theirs:.0%}")
    if limits:
        summary['footage_limits'] = limits
    summary['problems'] = problems
    return summary, problems
