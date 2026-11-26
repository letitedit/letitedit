"""The rest of New video's bookkeeping in code (T345 C1, on top of T331 P8's why markers in journal_tools): the beat,
loop and cut markers, the licence notes of library files, and markers that follow their clips through an edit.

    plan(project)              {'why', 'beats', 'loops', 'cuts', 'add', 'remove'}: what the markers need, nothing written
    write(project)             the markers plan() finds as one marker change (one undo step in an open window), then
                               the licence notes; returns the receipt (`python -m letitedit.server.journal_tools books`)
    licences(project)          a `licence:` footage note on each library song or sound the timeline plays that has none
    follow(before, after, markers, fps)   (moves, remove) for the markers of an edit from script `before` to `after`
    follow_apply(project, before, after, actor)  follow() written (letitedit.sound.av_tools.retime_markers); None: nothing
    carry(snapshot, before, after)  follow() as the marker list an open window's apply takes in its own undo step
                               (letitedit.app.live_edit.apply's `markers`); None: nothing moves

- **Beats.** story_plan.json's `beats` ([{id, label, selects}], `selects` naming groups of selects.json's `beats`,
  else the beat's own id) give one `beat:<id>:<label>` marker at the start of the first main-track clip that plays one
  of the beat's selects (the same file over at least half of the clip's or the select's source range, as the why
  markers match). A `beat:<id>:` marker already there stays; one elsewhere is moved there with its own text.
- **Loops.** story_plan.json's `loops` ([{id, question, opens, closes}], opens and closes naming beats) give
  `loop:<id>:<question>` at the opening beat's marker and `loop:<id>:answered` at the closing one's.
- **Cuts.** selects.json's `cuts` ([{file, in, out, why}], what was taken out and why, the AI's words) give
  `cut: <why>` at the join where the cut skips that stretch of the file. A `cut:` marker within CUT_NEAR_S of the
  join counts. Every other skip of CUT_GAP_S or more between two clips of one file with no `cut:` marker is listed
  (`uncovered`), for the hand-over.
- **Licences.** A clip whose file is in the asset library (songs from library.csv, sounds from the manifests) gets the
  footage note `licence: <licence> (<artist>, '<title>', from the letitedit <kind> library)`, tag
  `licence:<entry id>`, unless one of its notes already names a licence.
- **Following.** An edit's markers move with the moments they mark, by the main picture track's source times
  (letitedit.timeline.edit_sync.mapper, as other tracks and captions follow their picture): a marker spanning a clip
  keeps spanning it; a `why:` marker whose clip is gone is removed; any other marker whose moment is gone moves to
  where the next surviving part of its clip now starts, or stays where it is.
"""
from __future__ import annotations

import json
from pathlib import Path

import letitedit.timeline.edit_script as es
import letitedit.timeline.edit_sync as edit_sync
import letitedit.timeline.project_journal as pj

CUT_GAP_S = 2.0      # a skip in one file's source this long between two clips is a big removed stretch
CUT_NEAR_S = 0.5     # a cut marker this close to a join marks that join
LABEL_CHARS = 120
SHARE = 0.5          # the why markers' match: the same file over at least this share of the clip or the select
TOL_FRAMES = 1.5     # a marker this close to a clip's edge is on that edge


def _words(text, limit=LABEL_CHARS):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def _json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _docs(path):
    work = pj.folder(path)
    found = {}
    for name in ('story_plan.json', 'selects.json'):
        for candidate in (work / name, path.parent / name):
            doc = _json(candidate)
            if doc:
                found[name] = doc
                break
    return found.get('story_plan.json', {}), found.get('selects.json', {})


def clips(script):
    """The main track's clips: [{id, file, s, e, a, b, speed}] in timeline order (a, b: the source range played)."""
    track = edit_sync.main_track(script) if script else None
    out = []
    for it, s, e in (edit_sync.layout(track) if track else []):
        if 'clip' not in it:
            continue
        speed = float(it.get('speed', 1.0) or 1.0)
        a = float(es.to_seconds(it['in'])) if it.get('in') is not None else 0.0
        b = float(es.to_seconds(it['out'])) if it.get('out') is not None else a + (e - s) * speed
        out.append({'id': it.get('id'), 'file': str(it['clip']), 's': s, 'e': e, 'a': a, 'b': b, 'speed': speed})
    return out


def _same_file(a, b):
    from letitedit.server import journal_tools
    return journal_tools._same_file(a, b)


def _plays(clip, file, i0, i1):
    if not _same_file(file, clip['file']):
        return False
    cover = max(0.0, min(clip['b'], i1) - max(clip['a'], i0))
    return clip['b'] > clip['a'] and i1 > i0 and cover >= SHARE * min(clip['b'] - clip['a'], i1 - i0)


def _select_rows(selects):
    """{group: [(file, in, out)]} from selects.json's `beats`."""
    beats = selects.get('beats')
    groups = beats.items() if isinstance(beats, dict) else enumerate(beats or [])
    out = {}
    for key, group in groups:
        rows = group.get('selects') if isinstance(group, dict) else group
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get('file'):
                continue
            try:
                a, b = es.to_seconds(row.get('in')), es.to_seconds(row.get('out'))
            except (TypeError, ValueError):
                continue
            if a is not None and b is not None and b > a:
                out.setdefault(str(key), []).append((row['file'], float(a), float(b)))
    return out


def _near(markers, prefix, at, within):
    return [m for m in markers if str(m.get('text', '')).startswith(prefix) and abs(float(m['start']) - at) <= within]


def beat_plan(story, selects, rows, markers, frame):
    """{'beats', 'placed': {id: seconds}, 'add', 'remove', 'unmatched'} for the beat markers."""
    groups = _select_rows(selects)
    out = {'beats': 0, 'placed': {}, 'add': [], 'remove': [], 'unmatched': []}
    tol = TOL_FRAMES * frame
    for beat in story.get('beats') or []:
        if not isinstance(beat, dict) or not beat.get('id'):
            continue
        bid = str(beat['id'])
        out['beats'] += 1
        keys = beat.get('selects') if isinstance(beat.get('selects'), list) and beat.get('selects') else [bid]
        wanted = [r for k in keys for r in groups.get(str(k), [])]
        first = next((c for c in rows if any(_plays(c, *r) for r in wanted)), None)
        prefix = f'beat:{bid}:'
        mine = [m for m in markers if str(m.get('text', '')).startswith(prefix)]
        if first is None:
            out['unmatched'].append(bid)
            out['remove'] += [m['id'] for m in mine]     # a beat no clip plays any more has no marker
            continue
        at = round(first['s'], 3)
        out['placed'][bid] = at
        if any(abs(float(m['start']) - at) <= tol for m in mine):
            out['remove'] += [m['id'] for m in mine if abs(float(m['start']) - at) > tol]
            continue
        text = mine[0]['text'] if mine else f"{prefix}{_words(beat.get('label'))}"
        out['remove'] += [m['id'] for m in mine]
        out['add'].append({'at': at, 'text': text})
    return out


def loop_plan(story, placed, markers, frame):
    """{'loops', 'add', 'remove'} for the loop markers, at the beats `placed` (beat id: seconds)."""
    out = {'loops': 0, 'add': [], 'remove': []}
    tol = TOL_FRAMES * frame
    for loop in story.get('loops') or []:
        if not isinstance(loop, dict) or not loop.get('id'):
            continue
        lid = str(loop['id'])
        out['loops'] += 1
        prefix = f'loop:{lid}:'
        mine = [m for m in markers if str(m.get('text', '')).startswith(prefix)]
        closing = f'{prefix}answered'
        wanted = [(placed.get(loop.get('opens')), f"{prefix}{_words(loop.get('question'))}", False),
                  (placed.get(loop.get('closes')), closing, True)]
        for at, text, closes in wanted:
            same = [m for m in mine if (m['text'] == closing) == closes]
            if at is None:                               # its beat isn't on the timeline: no marker
                out['remove'] += [m['id'] for m in same]
                continue
            if any(abs(float(m['start']) - at) <= tol for m in same):
                out['remove'] += [m['id'] for m in same if abs(float(m['start']) - at) > tol]
                continue
            out['remove'] += [m['id'] for m in same]
            out['add'].append({'at': at, 'text': same[0]['text'] if same else text})
    return out


def _join_for(rows, file, i0, i1):
    """Where the cut skips [i0, i1] of `file` on the timeline: the end of the clip before the skip (or the first
    clip's start), None when no join skips it or a clip still plays most of it."""
    mine = [c for c in rows if _same_file(file, c['file'])]
    if not mine or any(max(0.0, min(c['b'], i1) - max(c['a'], i0)) >= SHARE * (i1 - i0) for c in mine):
        return None
    slack = CUT_NEAR_S
    for k, c in enumerate(mine):
        after = mine[k + 1] if k + 1 < len(mine) else None
        if c['b'] <= i0 + slack and (after is None or after['a'] >= i1 - slack):
            return round(c['e'], 3)
    return round(mine[0]['s'], 3) if mine[0]['a'] >= i1 - slack else None


def cut_plan(selects, rows, markers):
    """{'cuts', 'add', 'unplaced', 'uncovered'} for the cut markers."""
    out = {'cuts': 0, 'add': [], 'unplaced': [], 'uncovered': []}
    for row in selects.get('cuts') or []:
        if not isinstance(row, dict) or not row.get('file'):
            continue
        out['cuts'] += 1
        try:
            i0, i1 = float(es.to_seconds(row.get('in'))), float(es.to_seconds(row.get('out')))
        except (TypeError, ValueError):
            out['unplaced'].append({'file': str(row.get('file')), 'why': _words(row.get('why'), 80)})
            continue
        why = ' '.join(str(row.get('why') or '').split())
        why = why[4:].strip() if why.lower().startswith('cut:') else why
        at = _join_for(rows, row['file'], i0, i1) if why and i1 > i0 else None
        if at is None:
            out['unplaced'].append({'file': str(row['file']), 'in': i0, 'out': i1, 'why': _words(why, 80)})
            continue
        if _near(markers, 'cut:', at, CUT_NEAR_S) or any(abs(m['at'] - at) <= CUT_NEAR_S for m in out['add']):
            continue
        out['add'].append({'at': at, 'text': f'cut: {_words(why, 200)}'})
    by_file = {}
    for c in rows:
        by_file.setdefault(c['file'].lower(), []).append(c)
    for group in by_file.values():
        for prev, nxt in zip(group, group[1:]):
            if nxt['a'] - prev['b'] >= CUT_GAP_S:
                at = round(prev['e'], 3)
                if not _near(markers, 'cut:', at, CUT_NEAR_S) and not any(abs(m['at'] - at) <= CUT_NEAR_S
                                                                         for m in out['add']):
                    out['uncovered'].append({'at': at, 'file': prev['file'], 'from': round(prev['b'], 2),
                                             'to': round(nxt['a'], 2)})
    return out


def plan(project):
    """What the beat, loop and cut markers need (nothing written)."""
    import letitedit.app.bookkeeping as bookkeeping
    import letitedit.sound.av_tools as av_tools
    path = Path(project)
    script = bookkeeping.read_script(path)
    rows = clips(script) if script else []
    markers = av_tools.bin(path).get('markers', [])
    fps = float(((script or {}).get('profile') or {}).get('fps') or 0)
    frame = 1 / fps if fps > 0 else 1 / 30
    story, selects = _docs(path)
    beats = beat_plan(story, selects, rows, markers, frame)
    loops = loop_plan(story, beats['placed'], markers, frame)
    cuts = cut_plan(selects, rows, markers)
    return {'beats': beats, 'loops': loops, 'cuts': cuts,
            'add': beats['add'] + loops['add'] + cuts['add'],
            'remove': sorted(set(beats['remove'] + loops['remove']))}


def licences(project):
    """The licence note on each library song or sound the timeline plays that has none: {'written': [files],
    'kept': n}."""
    import letitedit.catalogs.assets as assets
    import letitedit.footage.footage_notes as footage_notes
    path = Path(project)
    import letitedit.app.bookkeeping as bookkeeping
    script = bookkeeping.read_script(path)
    files = []
    for track in (script or {}).get('tracks') or []:
        for it in track.get('items') or []:
            f = it.get('clip') if isinstance(it, dict) else None
            if f and str(f) not in files:
                files.append(str(f))
    out = {'written': [], 'kept': 0}
    for f in files:
        if not Path(f).is_file():
            continue
        try:
            entry = assets.entry_for_file(f)
        except Exception:  # noqa: BLE001 - an unreadable library knows nothing
            entry = None
        if not entry or not entry.get('licence'):
            continue
        try:
            notes = footage_notes.get(f)
        except (OSError, ValueError):
            notes = []
        if any('licen' in str(n.get('text', '')).lower() or any(str(t).startswith('licence')
                                                               for t in n.get('tags') or []) for n in notes):
            out['kept'] += 1
            continue
        who = ', '.join(x for x in (str(entry.get('artist') or '').strip(), f"'{entry.get('name')}'"
                                    if entry.get('name') else '') if x)
        kind = 'music' if entry.get('kind') == 'music' else str(entry.get('kind') or 'asset')
        text = (f"licence: {entry.get('licence_text') or entry['licence']} ({who + ', ' if who else ''}from the "
                f"letitedit {kind} library)" + (f"; credit: {entry['credit']}" if entry.get('credit') else ''))
        footage_notes.add(f, 0, text, tags=[f"licence:{entry.get('id')}"], source='letitedit')
        out['written'].append(f)
    return out


def write(project):
    """The why markers (journal_tools.why_plan), the beat, loop and cut markers as one marker change, then the
    licence notes. Returns {'why', 'beats', 'loops', 'cuts', 'licences', 'written', 'removed'}."""
    import letitedit.sound.av_tools as av_tools
    from letitedit.server import journal_tools
    path = Path(project)
    why = journal_tools.why_plan(path)
    books = plan(path)
    add = why['add'] + books['add']
    remove = sorted(set(why['remove'] + books['remove']))
    if add or remove:
        av_tools.bin(path, markers=add or None, remove=remove or None)
    receipt = {'why': {key: why[key] for key in ('clips', 'covered', 'unmatched')}}
    receipt['why'].update(written=len(why['add']), removed=len(why['remove']))
    receipt['beats'] = {k: books['beats'][k] for k in ('beats', 'unmatched')}
    receipt['beats']['written'] = len(books['beats']['add'])
    receipt['loops'] = {'loops': books['loops']['loops'], 'written': len(books['loops']['add'])}
    receipt['cuts'] = {k: books['cuts'][k] for k in ('cuts', 'unplaced', 'uncovered')}
    receipt['cuts']['written'] = len(books['cuts']['add'])
    receipt.update(written=len(add), removed=len(remove))
    try:
        receipt['licences'] = licences(path)
    except Exception as error:  # noqa: BLE001 - a licence note is bookkeeping: the markers stand without it
        receipt['licences'] = {'error': f'{type(error).__name__}: {error}'}
    return receipt


def follow(before, after, markers, fps):
    """(moves {id: (start, end)}, remove [ids]) that keep `markers` on the moments they marked when the timeline goes
    from script `before` to `after`. Only changes of a frame or more are moved."""
    frame = 1 / fps if fps and fps > 0 else 1 / 30
    tol = TOL_FRAMES * frame
    old, new = clips(before), clips(after)
    if not old:
        return {}, []
    new_by_id = {c['id']: c for c in new if c.get('id') is not None}
    map_t = edit_sync.mapper(before, after)
    if map_t is None:
        return {}, []
    moves, remove = {}, []
    for m in markers:
        s, e = float(m['start']), float(m['end'])
        text = str(m.get('text', ''))
        span = next((c for c in old if e > s and abs(s - c['s']) <= tol
                     and min(abs(e - c['e']), abs(e - (c['e'] - frame))) <= tol), None)
        if span is not None:
            now = new_by_id.get(span['id'])
            if now is None:
                if text.lower().startswith('why:'):
                    remove.append(m['id'])
                    continue
            else:
                ns, ne = now['s'], max(now['s'], now['e'] - (span['e'] - e))
                if abs(ns - s) >= frame / 2 or abs(ne - e) >= frame / 2:
                    moves[m['id']] = (round(ns, 4), round(ne, 4))
                continue
        on_clip = next((c for c in old if c['s'] - 1e-6 <= s < c['e'] - 1e-6), None)
        ns = map_t(s, nearest=True)
        if ns is None and on_clip is not None and text.lower().startswith('why:'):
            remove.append(m['id'])
            continue
        if ns is None:
            continue
        ne = ns if e <= s else map_t(e, end=True, nearest=True)
        if ne is None or ne < ns:
            ne = ns + (e - s)
        if abs(ns - s) >= frame / 2 or abs(ne - e) >= frame / 2:
            moves[m['id']] = (round(ns, 4), round(ne, 4))
    return moves, remove


def follow_apply(project, before, after, actor=None, saved_only=False):
    """The markers of the edit from `before` to `after` (scripts) moved with their clips: av_tools.retime_markers's
    receipt, or None when nothing moved. saved_only: the saved file even when a window has it open (an edit written
    to the file, which the window then reloads). Never raises (the edit stands without it): a failure comes back as
    {'error'}."""
    import letitedit.sound.av_tools as av_tools
    fps = float(((after or {}).get('profile') or {}).get('fps') or 30)
    try:
        return av_tools.retime_markers(project, lambda markers: follow(before, after, markers, fps), actor=actor,
                                       saved_only=saved_only)
    except Exception as error:  # noqa: BLE001 - markers are bookkeeping: the edit stands without them
        return {'error': f'the markers could not follow the edit: {type(error).__name__}: {error}'}


def carry(snapshot, before, after):
    """The markers of the edit from `before` to `after` (scripts) moved with their clips, as the whole marker list the
    open window's apply sets in the edit's own undo step (T356): av_tools.followed_rows's {'rows', 'moved',
    'removed'} for the window's snapshot file, or None when nothing moves. The same follow() as follow_apply, so a
    window and a saved file get the same markers. Never raises (the edit stands without it): a failure comes back as
    {'error'}."""
    import letitedit.sound.av_tools as av_tools
    fps = float(((after or {}).get('profile') or {}).get('fps') or 30)
    try:
        return av_tools.followed_rows(snapshot, lambda markers: follow(before, after, markers, fps))
    except Exception as error:  # noqa: BLE001 - markers are bookkeeping: the edit stands without them
        return {'error': f'the markers could not follow the edit: {type(error).__name__}: {error}'}
