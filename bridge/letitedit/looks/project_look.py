"""A Look's exact values from a finished letitedit project: the timeline it was exported from, the AI's route through
it (the project's journal) and who chose each value that is in the finished video (the person, the AI or both).

The finished video as it stands decides: values come from the timeline the chosen export was made from (its snapshot
in the project's history, matched by hash, or the saved timeline when that is what was exported). Edits tried and later
undone or changed again leave nothing. Provenance is worked out per value along the project's history: a value the
person's own hand last brought to what the export shows is theirs ('person'), one the person put back to a value the
AI had chosen is 'both', the rest is the AI's ('ai'). Hand edits weigh more; they are never rules. The person's own
words to the AI ("always ...", "never ...", journalled as kind 'said') are the only source of rules, and only those
the AI judges to be about style.

Also here: the journalling that makes this exact from now on (the state as the AI last left it, `seen-last.mlt`, and
the person's own edits found against it, actor 'person', kind 'hand_edit'), the export-to-timeline pointer kept when
an export is made (`exports.json`), and the person's instructions (kind 'said')."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import statistics
from pathlib import Path

FORMAT = 'letitedit-look-project/1'
SEEN = 'seen-last.mlt'              # in <stem>.letitedit\: the timeline as the AI (or the last check) left it
EXPORTS = 'exports.json'            # in <stem>.letitedit\: every export and the exact timeline it was made from
EXPORT_TIMELINES = 'exports'        # in <stem>.letitedit\: copies of those timelines
WEIGHT = {'ai': 1, 'both': 2, 'person': 3}
VALUES_KEPT = 400                   # values listed in one hand_edit journal entry
VALUE_CHARS = 160
VIDEO_SUFFIXES = ('.mp4', '.mov', '.mkv', '.webm')
NOT_FINAL = re.compile(r'(?i)(?:^|[\s_-])(preview|rough|assembly|excerpt|clip|test)(?:$|[\s_.-])')
RULE_WORDS = re.compile(r"(?i)\b(always|never|don['’]?t ever|do not ever|every time|from now on)\b")


# ---------------------------------------------------------------------------- small helpers

def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _side(project):
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(project).resolve())


def _seconds(value):
    import letitedit.timeline.edit_script as es
    try:
        return float(es.to_seconds(value))
    except (TypeError, ValueError):
        return None


def _digest(script):
    import letitedit.looks.look_check as look_check
    return look_check.project_digest(script)


def _short(value, chars=VALUE_CHARS):
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return text if len(text) <= chars else text[:chars] + '...'


def _quartiles(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    if len(values) == 1:
        return [round(values[0], 3)] * 3
    q = statistics.quantiles(values, n=4, method='inclusive')
    return [round(q[0], 3), round(statistics.median(values), 3), round(q[2], 3)]


def _weighted_median(pairs):
    """Median of (value, weight) pairs: the person's values count WEIGHT['person'] times."""
    pairs = sorted((v, w) for v, w in pairs if v is not None)
    if not pairs:
        return None
    half, running = sum(w for _, w in pairs) / 2, 0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return round(value, 3)
    return round(pairs[-1][0], 3)


# ---------------------------------------------------------------------------- the values of a timeline

def _effect_kind(effect):
    if isinstance(effect, dict):
        if 'filter' in effect:
            return 'filter:' + str(effect['filter'])
        return next(iter(effect), 'effect')
    return str(effect)


EDITOR_PARAMS = {'mask_apply': ('transition', 'mlt_image_format')}      # the editor's save rewrites these itself
EDITOR_ZERO = {'lift_gamma_gain': ('lift_r', 'lift_g', 'lift_b')}      # and writes these out at their default


def _plain(value):
    """A value as the person would see it: paths by file name, numbers to 4 places (the editor's save writes a
    relative path for an absolute one and reformats numbers; neither is anybody's edit)."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str) and ('/' in value or '\\' in value) and re.search(r'\.[A-Za-z0-9]{2,5}$', value):
        return value.replace('\\', '/').rsplit('/', 1)[-1]
    return value


def _effect_value(effect):
    """An effect as it reads to a person: the parameters the editor's own save rewrites are left out."""
    if not isinstance(effect, dict) or not isinstance(effect.get('params'), dict):
        return _plain(effect)
    name = str(effect.get('filter') or '')
    params = {k: v for k, v in effect['params'].items() if k not in EDITOR_PARAMS.get(name, ())
              and not (k in EDITOR_ZERO.get(name, ()) and v in (0, 0.0, '0'))}
    return _plain({**effect, 'params': params})


def values(script):
    """Every value of a timeline that a person or the AI can set, keyed (owner, field): an item's source, in, out,
    length, speed, track, transition, recipe and each kind of effect; each caption track's cues and style fields; the
    tracks. Positions on the timeline ('at') are left out: they follow from everything before them."""
    out = {}
    for track in script.get('tracks') or []:
        out[('track:' + track['name'], 'kind')] = track.get('kind')
        for item in track.get('items') or []:
            iid = item.get('id')
            if not iid:
                continue
            out[(iid, 'track')] = track['name']
            for key in ('clip', 'in', 'out', 'speed', 'transition', 'graphic', 'ffmpeg', 'color', 'scene', 'vfx',
                        'freeze', 'voice', 'ass', 'reverse', 'multicam'):
                if key in item:
                    out[(iid, key)] = _seconds(item[key]) if key in ('in', 'out') else _plain(item[key])
            if 'len' in item and 'in' not in item:
                out[(iid, 'len')] = _seconds(item['len'])
            kinds = {}
            for effect in item.get('effects') or []:
                kinds.setdefault(_effect_kind(effect), []).append(_effect_value(effect))
            for kind, effects in kinds.items():
                out[(iid, 'effect:' + kind)] = effects
    for caption in script.get('captions') or []:
        owner = 'captions:' + caption['track']
        out[(owner, 'cues')] = hashlib.sha256(json.dumps(caption.get('cues'), sort_keys=True,
                                                         ensure_ascii=False).encode()).hexdigest()[:16]
        out[(owner, 'burn_in')] = caption.get('burn_in', True)
        for field, value in (caption.get('style') or {}).items():
            out[(owner, 'style:' + field)] = value
    if script.get('master'):
        out[('master', 'effects')] = script['master']
    return out


def changed(before, after):
    """{key: (old, new)} for values that differ between two value maps (missing is None)."""
    keys = set(before) | set(after)
    return {key: (before.get(key), after.get(key)) for key in keys
            if json.dumps(before.get(key), sort_keys=True, default=str) != json.dumps(after.get(key), sort_keys=True,
                                                                                     default=str)}


# ---------------------------------------------------------------------------- journalling hand edits from now on

def remember(project, state_file=None):
    """Keeps the timeline as the AI (or the last check) left it, for the next check to find the person's own edits."""
    try:
        side = _side(project)
        side.mkdir(parents=True, exist_ok=True)
        temporary = side / (SEEN + '.tmp')
        shutil.copy2(state_file or project, temporary)
        os.replace(temporary, side / SEEN)
    except OSError:
        pass


def note_hand_edits(project, state_file=None, script=None):
    """Journals what changed since the AI (or the last check) left the timeline: the person's own edits, actor
    'person', kind 'hand_edit', with each value before and after. Then remembers the state as seen. Never raises: it
    is a record, not a gate. Returns the entry or None."""
    try:
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.project_journal as pj
        side = _side(project)
        seen = side / SEEN
        state_file = Path(state_file or project)
        if not seen.is_file():
            remember(project, state_file)
            return None
        last = es.read(seen)
        current = script if script is not None else es.read(state_file)
        found = changed(values(last), values(current))
        if not found:
            return None
        listed = [{'id': key[0], 'field': key[1], 'before': _short(old), 'after': _short(new)}
                  for key, (old, new) in sorted(found.items(), key=lambda pair: (str(pair[0][0]), pair[0][1]))]
        entry = pj.record(Path(project), 'hand_edit', 'person', "the person's own edits", es.diff(last, current),
                          values=listed[:VALUES_KEPT], values_total=len(listed))
        remember(project, state_file)
        return entry
    except Exception:  # noqa: BLE001 - finding hand edits is a record; it never stops an edit or a read
        return None


SAID_FILE = 'said.jsonl'             # in a New video's folder: the person's own words in its request (no project yet)


def said(project, text, where='chat', folder=None):
    """Journals the person's own instruction to the AI (actor 'person', kind 'said'): their words and the time. With
    folder instead of a project (New video's request, sent before its project exists), the entry goes in that folder's
    said.jsonl, which the project made there reads as its own."""
    import letitedit.timeline.project_journal as pj
    text = ' '.join(str(text or '').split())
    if not text:
        raise ValueError('nothing was said')
    if folder:
        entry = {'time': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'actor': 'person', 'kind': 'said', 'text': text[:4000], 'where': where}
        with open(Path(folder) / SAID_FILE, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return entry
    return pj.record(Path(project), 'said', 'person', text=text[:4000], where=where)


def _said_entries(project):
    """The person's recorded words for a project, oldest first: its folder's said.jsonl (New video's request) and its
    journal's said entries."""
    out = []
    try:
        for line in (Path(project).parent / SAID_FILE).read_text(encoding='utf-8-sig', errors='replace').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    out += [e for e in _journal(_side(project)) if e.get('kind') == 'said']
    return sorted((e for e in out if e.get('actor') == 'person' and e.get('text')), key=lambda e: str(e.get('time')))


# ---------------------------------------------------------------------------- exports and their timelines

def note_export(project, output, snapshot, job_id=None, preview=False):
    """Records which exact timeline an export was made from: a copy of its snapshot beside the project and a line in
    exports.json. Called when an export is started; never raises."""
    try:
        import letitedit.timeline.edit_script as es
        side = _side(project)
        folder = side / EXPORT_TIMELINES
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        copy = folder / f'{stamp}.mlt'
        shutil.copy2(snapshot, copy)
        record = _read_json(side / EXPORTS, {}) or {}
        record.setdefault('format', 'letitedit-exports/1')
        exports = record.setdefault('exports', [])
        row = {'output': str(Path(output).resolve()), 'timeline': copy.name,
               'project_sha256': _digest(es.read(copy)), 'job_id': job_id, 'preview': bool(preview),
               'started': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        try:            # what the video is made of, wherever the project is later (T347)
            import letitedit.timeline.export_checks as export_checks
            copied = es.read(copy)
            row['content_sha256'] = export_checks.content_digest(copied, export_checks.project_folder(copy))
            row['sources_sha256'] = export_checks.sources_digest(copied, export_checks.project_folder(copy))
        except Exception:  # noqa: BLE001 - the review then measures the kept timeline itself
            pass
        exports.append(row)
        temporary = side / (EXPORTS + '.tmp')
        temporary.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, side / EXPORTS)
    except Exception:  # noqa: BLE001 - the pointer is a convenience for Learn; an export never fails for it
        pass


def _recorded_digests(project):
    """{export file (lower-case resolved): project_sha256} that the export and review records already hold."""
    project = Path(project)
    found = {}
    checks = _read_json(project.with_name(project.stem + '.export-checks.json'), {}) or {}
    newest = checks.get('project_sha256')
    for folder in project.parent.glob(project.stem + '*review'):
        bundle = _read_json(folder / 'review_bundle.json', {}) or {}
        video = bundle.get('video') or bundle.get('export')
        video = video.get('file') if isinstance(video, dict) else video
        if isinstance(video, str) and (project.parent / Path(video.replace('\\', '/')).name).is_file():
            video = str(project.parent / Path(video.replace('\\', '/')).name)   # a moved or copied project
        elif not isinstance(video, str):
            video = None
        checks_here = _read_json(folder / 'pre-export-checks.json', {}) or {}
        digest = checks_here.get('project_sha256') or ((checks_here.get('checks') or {}).get('look') or {}).get(
            'project_sha256')
        name = folder.name[:-len(' review')] if folder.name.endswith(' review') else None
        if not video and name:
            video = next((str(project.parent / (name + s)) for s in VIDEO_SUFFIXES
                          if (project.parent / (name + s)).is_file()), None)
        if video and digest:
            found[str(Path(video).resolve()).lower()] = digest
    return found, newest


def versions(project):
    """The finished videos of a project, newest first: [{file, made, final, timeline, matched_by, note}]. A version's
    timeline is the exact one it was exported from when letitedit knows it (exports.json, or a recorded hash that
    matches the saved timeline or a history snapshot); otherwise timeline is None and it is learned from its video."""
    import letitedit.timeline.edit_script as es
    project = Path(project).resolve()
    side = _side(project)
    # a project beside it whose name starts with this one's ("Trip v2" beside "Trip") owns the videos named after it
    longer = [p.stem for p in project.parent.glob('*.mlt') if len(p.stem) > len(project.stem) and p.stem.startswith(project.stem)]
    files = [f for f in project.parent.iterdir() if f.suffix.lower() in VIDEO_SUFFIXES and f.is_file()
             and f.stem.startswith(project.stem) and not any(f.stem.startswith(s) for s in longer)]
    pointers = {str(Path(e.get('output', '')).resolve()).lower(): e
                for e in ((_read_json(side / EXPORTS, {}) or {}).get('exports') or []) if isinstance(e, dict)}
    digests, newest = _recorded_digests(project)
    states = None

    def by_hash(digest):
        nonlocal states
        if states is None:
            states = []
            for candidate in [project] + sorted((side / 'history').glob('*.mlt'), reverse=True):
                try:
                    states.append((candidate, _digest(es.read(candidate))))
                except Exception:  # noqa: BLE001 - an unreadable snapshot just doesn't match
                    continue
        return next((path for path, value in states if value == digest), None)

    files = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    newest_final = next((f for f in files if not NOT_FINAL.search(f.stem[len(project.stem):])), None)
    out = []
    for f in files:
        row = {'file': str(f), 'made': datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec='seconds'),
               'final': not NOT_FINAL.search(f.stem[len(project.stem):]), 'timeline': None, 'matched_by': None}
        pointer = pointers.get(str(f).lower())
        if pointer and (side / EXPORT_TIMELINES / pointer['timeline']).is_file():
            row.update(timeline=str(side / EXPORT_TIMELINES / pointer['timeline']), matched_by='export record')
        else:
            digest = digests.get(str(f).lower())
            if digest is None and newest and f == newest_final:
                digest = newest            # export-checks.json describes the newest export
            if digest:
                match = by_hash(digest)
                if match is not None:
                    row.update(timeline=str(match), matched_by='hash of the timeline at export')
                    row['note'] = ('the saved timeline' if Path(match) == project
                                   else 'a history snapshot of the timeline')
            if row['timeline'] is None and f == newest_final:
                match = _saved_before_export(project, side)
                if match is not None:
                    row.update(timeline=str(match), matched_by='time: saved just before the export started, no edit '
                                                                'between (its hash was taken by an older letitedit)')
        if row['timeline'] is None:
            row['note'] = 'no matching timeline is kept for this version: it is learned from its video'
        out.append(row)
    return out


def _saved_before_export(project, side):
    """The newest export's timeline by time, for a project whose recorded hash no longer matches (the timeline reader
    changed since): the newest of the saved timeline, its .bak and the history snapshots written before the export
    started (export-checks.json's time), when the journal shows no edit between that state and the export."""
    checks = project.with_name(project.stem + '.export-checks.json')
    if not checks.is_file():
        return None
    start = checks.stat().st_mtime
    candidates = [project, project.with_name(project.name + '.bak')] + list((side / 'history').glob('*.mlt'))
    candidates = [c for c in candidates if c.is_file() and c.stat().st_mtime <= start]
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c.stat().st_mtime)
    since = best.stat().st_mtime + 2
    for entry in _journal(side):
        if entry.get('kind') not in ('apply', 'undo'):
            continue
        try:
            when = datetime.datetime.strptime(entry['time'], '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.timezone.utc).timestamp()
        except (KeyError, ValueError):
            continue
        if since < when <= start:
            return None
    return best


def choose_version(project, export=None):
    """(the version row, every version): the given export, else the newest final one, else the newest video."""
    rows = versions(project)
    if export:
        wanted = str(Path(export).resolve()).lower()
        row = next((r for r in rows if str(Path(r['file']).resolve()).lower() == wanted), None)
        if row is None:
            if not Path(export).is_file():
                raise ValueError(f'{export} is not on this PC')
            row = {'file': str(Path(export).resolve()), 'final': True, 'timeline': None, 'matched_by': None,
                   'note': 'not an export of this project that letitedit knows: learned from its video'}
        return row, rows
    finals = [r for r in rows if r['final']]
    return (finals or rows or [None])[0], rows


# ---------------------------------------------------------------------------- who chose each value

def _journal(side):
    out = []
    try:
        for line in (side / 'journal.jsonl').read_text(encoding='utf-8-sig', errors='replace').splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _history_file(side, entry):
    name = Path(str(entry.get('history') or '').replace('\\', '/')).name
    if not name:
        return None
    path = side / 'history' / name
    return path if path.is_file() else None


def provenance(project, final_file=None):
    """{key: 'person'|'ai'|'both'} for every value of the final timeline, plus how sure the walk was.

    The walk goes along the history: the snapshot kept before each AI edit, then the final timeline. Between two
    snapshots, the AI's edits are the journal's own change lines for the edits in between (the ids they name); the
    person's are the values a 'hand_edit' entry lists, or (for a project from before those were kept) the changed values
    of items no AI edit in between names, when the journal listed every change of those edits."""
    import letitedit.timeline.edit_script as es
    project = Path(project).resolve()
    side = _side(project)
    final_file = Path(final_file or project)
    journal = _journal(side)
    chain = []          # (journal index, state file)
    for index, entry in enumerate(journal):
        if entry.get('kind') == 'apply' and entry.get('actor') != 'person':
            path = _history_file(side, entry)
            if path is not None:
                chain.append((index, path))
    final_values = values(es.read(final_file))
    if not chain:
        return {'values': {key: 'ai' for key in final_values}, 'steps': 0, 'unsure_values': 0, 'person_values': 0,
                'note': 'no history kept: every value is counted as the AI\'s'}
    # the final timeline: when it is a history snapshot, the walk stops there
    names = [path.name for _, path in chain]
    stop = names.index(final_file.name) if final_file.name in names else None
    states = [(index, path) for index, path in chain] if stop is None else chain[:stop + 1]
    ends = [path for _, path in states[1:]] + ([final_file] if stop is None else [])
    cache = {}

    def state(path):
        if path not in cache:
            cache[path] = values(es.read(path))
        return cache[path]

    timeline_of = {}        # key -> [(step, actor, value)]
    unsure = 0
    previous = None
    for step, ((start_index, start_path), end_path) in enumerate(zip(states, ends)):
        end_index = states[step + 1][0] if step + 1 < len(states) else len(journal)
        between = journal[start_index:end_index]
        ai_edits = [e for e in between if e.get('kind') in ('apply', 'undo') and e.get('actor') != 'person']
        hand = [e for e in between if e.get('kind') == 'hand_edit']
        # an AI undo after a hand edit can take the person's edit away: the next state is what it is either way
        a, b = state(start_path), state(end_path)
        diff = changed(a, b)
        lines = ' '.join(str(line) for e in ai_edits for line in (e.get('changes') or []))
        # the journal keeps the first lines of an edit's changes, each cut at its length limit (' ...'): an edit whose
        # list or a line of it was cut may have changed more than its lines name
        complete = all(int(e.get('changes_total') or 0) <= len(e.get('changes') or [])
                       and not any(str(line).endswith(' ...') for line in e.get('changes') or []) for e in ai_edits)
        listed = {(v.get('id'), v.get('field')) for e in hand for v in e.get('values') or []}
        exact = any(e.get('kind') == 'hand_edit' for e in hand) or any(e.get('hand_checked') for e in ai_edits)
        for key, (_, new) in diff.items():
            owner = str(key[0])
            if exact:
                actor = 'person' if key in listed else 'ai'
            elif owner.startswith('captions:'):
                track = owner.split(':', 1)[1]
                named = f'captions "{track}"' in lines or f'caption style "{track}"' in lines
                actor = 'ai' if named or not complete else 'person'
            elif owner.startswith('track:') or owner == 'master':
                actor = 'ai' if (ai_edits and not complete) or re.search(r'track|master|whole-video', lines) else 'person'
            else:
                mentioned = bool(re.search(r'(?<![\w-])' + re.escape(owner) + r'(?![\w-])', lines))
                actor = 'ai' if mentioned or not complete else 'person'
                if not mentioned and not complete:
                    unsure += 1         # values counted as the AI's because the journal can't say
            timeline_of.setdefault(key, []).append((step, actor, new))
        previous = b
    del previous
    out, person_values = {}, 0
    for key, value in final_values.items():
        steps = timeline_of.get(key) or []
        if not steps:
            out[key] = 'ai'
            continue
        same = lambda left, right: json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True,
                                                                                               default=str)
        # the last step that brought the value to what it is now (later steps left it there)
        last = steps[-1]
        actor = last[1]
        if actor == 'person':
            ai_values = [new for _, who, new in steps[:-1] if who == 'ai'] + (
                [state(states[0][1]).get(key)] if key in state(states[0][1]) else [])
            actor = 'both' if any(same(v, value) for v in ai_values) else 'person'
            person_values += 1
        out[key] = actor
    return {'values': out, 'steps': len(ends), 'unsure_values': unsure, 'person_values': person_values,
            'hand_edit_entries': sum(1 for e in journal if e.get('kind') == 'hand_edit')}


# ---------------------------------------------------------------------------- the exact facts

def _kind_of_source(path, track):
    p = '/' + str(path or '').replace('\\', '/').lower()
    name = (track or '').lower()
    if '/assets/sfx/' in p or '/sound effects/' in p or re.search(r'sfx|effect|foley|whoosh|hit', name):
        return 'sound_effect'
    if '/music-library/' in p or '/starter-music/' in p or '/written-music' in p or re.search(r'music|song|score|bed', name):
        return 'music'
    if '/assets/' in p and re.search(r'emoji|anim|sticker|icon', p):
        return 'sticker'
    if 'pixabay' in p or '/stock/' in p:
        return 'stock'
    if '/made/' in p or '/cache/image' in p or '/generated' in p:
        return 'made'
    return 'filmed'


def _by(prov, keys):
    """'person', 'both' or 'ai' for a group of values: the weightiest of them."""
    seen = [prov.get(key, 'ai') for key in keys]
    return 'person' if 'person' in seen else 'both' if 'both' in seen else 'ai'


def _scale(effect, width):
    try:
        x, y, w, h = [float(v) for v in str(effect).split()[:4]]
        return round(w / float(width), 3) if width else None
    except (TypeError, ValueError):
        return None


def facts(script, prov=None):
    """The exact values of a finished timeline, part by part, each with who chose it (person / ai / both) and counts
    weighted by that (the person's values count 3, both 2, the AI's 1). No words said, names, paths or text shown."""
    import letitedit.timeline.edit_sync as edit_sync
    prov = prov or {}
    profile = script.get('profile') or {}
    width, height = float(profile.get('width') or 1920), float(profile.get('height') or 1080)
    length = _seconds(script.get('length')) or 0.0
    minutes = max(length / 60.0, 1e-6)
    main = edit_sync.main_track(script)
    parts = {'basis': 'exact', 'length_s': round(length, 3), 'shape': 'tall' if height > width else 'wide',
             'size': [int(width), int(height)], 'fps': profile.get('fps')}

    def weight(iid, *fields):
        return WEIGHT[_by(prov, [(iid, f) for f in fields])]

    # pacing: the main picture track
    shots = [(it, it.get('len')) for it in (main or {}).get('items', []) if it.get('id') and 'gap' not in it]
    lengths = [_seconds(l) for _, l in shots]
    parts['pacing'] = {
        'track': (main or {}).get('name'), 'shots': len(shots),
        'cuts_per_min': round(max(len(shots) - 1, 0) / minutes, 2),
        'shot_s_quartiles': _quartiles(lengths),
        'shot_s_weighted_median': _weighted_median([(_seconds(l), weight(it['id'], 'in', 'out', 'len'))
                                                    for it, l in shots]),
        'by': {who: sum(1 for it, _ in shots if _by(prov, [(it['id'], 'in'), (it['id'], 'out')]) == who)
               for who in WEIGHT}}
    # every other item, by what it is
    broll, splits, speed, sfx, music, stickers, graphics, angles, transitions = [], [], [], [], [], [], [], [], {}
    effects, punch, grade, lighting = {}, [], 0, 0
    for track in script.get('tracks') or []:
        video = track.get('kind', 'video') == 'video'
        for it in track.get('items') or []:
            iid = it.get('id')
            if not iid:
                continue
            seconds = _seconds(it.get('len')) or 0.0
            kind = _kind_of_source(it.get('clip'), track['name']) if it.get('clip') else None
            if it.get('transition'):
                tr = it['transition']
                name = tr.get('type', 'dissolve') if isinstance(tr, dict) else str(tr)
                transitions[name] = transitions.get(name, 0) + 1
            for effect in it.get('effects') or []:
                ek = _effect_kind(effect)
                effects[ek] = effects.get(ek, 0) + 1
                if ek == 'size_position':
                    punch.append((_scale(effect['size_position'], width), WEIGHT[prov.get((iid, 'effect:' + ek), 'ai')]))
                if ek == 'filter:avfilter.lut3d' or (isinstance(effect, dict) and 'grade' in json.dumps(effect)):
                    grade += 1
                if ek in ('filter:mask_start', 'filter:frei0r.alphaspot') or 'alphaspot' in json.dumps(effect):
                    lighting += 1
            if it.get('multicam'):
                angles.append((it, seconds))
            if abs(float(it.get('speed', 1) or 1) - 1) > 0.01:
                speed.append({'speed': float(it['speed']), 'seconds': round(seconds, 3),
                              'by': _by(prov, [(iid, 'speed')])})
            if 'ffmpeg' in it and len((it['ffmpeg'] or {}).get('inputs') or []) > 1 and 'overlay' in str(
                    (it['ffmpeg'] or {}).get('video', '')):
                splits.append({'panes': len(it['ffmpeg']['inputs']), 'seconds': round(seconds, 3),
                               'track': track['name'], 'by': _by(prov, [(iid, 'ffmpeg')])})
                continue
            if 'graphic' in it or 'scene' in it or 'ass' in it:
                params = ((it.get('graphic') or {}).get('params') or {})
                kit = params.get('_look_kit') or {}
                graphics.append({'family': kit.get('family') or (it.get('graphic') or {}).get('template')
                                 or ('code scene' if 'scene' in it else 'text layer'),
                                 'seconds': round(seconds, 3), 'at_share': round((_seconds(it.get('at')) or 0) / max(length, 1e-6), 3),
                                 'centre': [params.get('centre_x'), params.get('centre_y')]
                                 if params.get('centre_x') is not None else None,
                                 'fonts': (kit.get('style') or {}).get('fonts'),
                                 'colours': (kit.get('style') or {}).get('colors'),
                                 'animated': params.get('animated'), 'by': _by(prov, [(iid, 'graphic'), (iid, 'scene')])})
                continue
            if kind == 'sound_effect':
                sfx.append({'sound': Path(str(it['clip'])).stem[:60], 'seconds': round(seconds, 3),
                            'by': _by(prov, [(iid, 'clip'), (iid, 'in')])})
            elif kind == 'music':
                gains = [g for e in it.get('effects') or [] if isinstance(e, dict) and 'gain' in e
                         for g in ([k[1] for k in e['gain'].get('keys', [])] if isinstance(e['gain'], dict)
                                   else [e['gain']])]
                fades = {k: e[k] for e in it.get('effects') or [] if isinstance(e, dict)
                         for k in ('fade_in_audio', 'fade_out_audio') if k in e}
                music.append({'source': 'written' if 'written' in str(it['clip']).lower() else 'library',
                              'seconds': round(seconds, 3), 'gain_db_median': round(statistics.median(gains), 2)
                              if gains else None, 'gain_points': len(gains), 'fades_s': fades,
                              'by': _by(prov, [(iid, 'effect:gain'), (iid, 'in'), (iid, 'out'), (iid, 'clip')])})
            elif kind == 'sticker':
                stickers.append({'seconds': round(seconds, 3), 'by': _by(prov, [(iid, 'clip')])})
            elif video and track is not main and it.get('clip') and not it.get('multicam'):
                broll.append({'seconds': round(seconds, 3), 'source': kind or 'filmed',
                              'treatments': sorted({_effect_kind(e) for e in it.get('effects') or []} - {'mute'}),
                              'by': _by(prov, [(iid, 'in'), (iid, 'out'), (iid, 'clip')]),
                              'w': weight(iid, 'in', 'out', 'clip')})
    parts['broll'] = {
        'count': len(broll), 'per_min': round(len(broll) / minutes, 2),
        'share_of_time': round(sum(b['seconds'] for b in broll) / max(length, 1e-6), 3),
        'seconds_quartiles': _quartiles([b['seconds'] for b in broll]),
        'seconds_weighted_median': _weighted_median([(b['seconds'], b['w']) for b in broll]),
        'sources': _count(b['source'] for b in broll), 'treatments': _count(t for b in broll for t in b['treatments']),
        'by': _count(b['by'] for b in broll)}
    if angles:
        holds = [s for _, s in angles]
        names = {str(angle[3] if len(angle) > 3 else angle[0]) for it, _ in angles
                 for angle in (it.get('multicam') or {}).get('angles') or [] if isinstance(angle, (list, tuple))}
        names |= {str((it.get('multicam') or {}).get('angle')) for it, _ in angles}
        parts['angles'] = {'shots': len(angles), 'angles': len(names), 'switches_per_min': round(len(angles) / minutes, 2),
                           'hold_s_quartiles': _quartiles(holds),
                           'by': _count(_by(prov, [(it['id'], 'multicam'), (it['id'], 'in')]) for it, _ in angles)}
    parts['framing'] = {'scaled_items': len(punch), 'scale_quartiles': _quartiles([s for s, _ in punch]),
                        'scale_weighted_median': _weighted_median(punch)}
    parts['captions'] = _captions(script, prov, height, width, minutes)
    parts['graphics'] = {'count': len(graphics), 'families': _count(g['family'] for g in graphics),
                         'items': [{k: v for k, v in g.items()} for g in graphics[:40]],
                         'fonts': sorted({f for g in graphics for f in (g.get('fonts') or {}).values()}),
                         'by': _count(g['by'] for g in graphics)}
    parts['stickers'] = {'count': len(stickers), 'per_min': round(len(stickers) / minutes, 2),
                         'by': _count(s['by'] for s in stickers)}
    parts['splits'] = {'count': len(splits), 'seconds': [s['seconds'] for s in splits],
                       'panes': _count(s['panes'] for s in splits), 'by': _count(s['by'] for s in splits)}
    parts['speed'] = {'count': len(speed), 'changes': speed[:40]}
    parts['sound_effects'] = {'count': len(sfx), 'per_min': round(len(sfx) / minutes, 2),
                              'sounds': _count(s['sound'] for s in sfx), 'by': _count(s['by'] for s in sfx)}
    parts['music'] = {'pieces': len(music), 'share_of_time': round(sum(m['seconds'] for m in music) / max(length, 1e-6), 3),
                      'items': music[:20]}
    parts['transitions'] = transitions
    parts['grade'] = {'graded_items': grade, 'lighting_items': lighting,
                      'master': [_effect_kind(e) for e in script.get('master') or []]}
    parts['effects'] = dict(sorted(effects.items(), key=lambda kv: -kv[1]))
    return parts


def _count(values):
    out = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _captions(script, prov, height, width, minutes):
    out = []
    for caption in script.get('captions') or []:
        owner = 'captions:' + caption['track']
        cues = caption.get('cues') or []
        texts = [str(q.get('text') or '') for q in cues]
        durations = [(_seconds(q.get('end')) or 0) - (_seconds(q.get('start')) or 0) for q in cues]
        style = dict(caption.get('style') or {})
        row = {'track': caption['track'], 'drawn': caption.get('burn_in', True) is not False, 'cues': len(cues),
               'per_min': round(len(cues) / minutes, 2),
               'cue_s_quartiles': _quartiles(durations),
               'words_per_cue_quartiles': _quartiles([len(t.split()) for t in texts]),
               'lines_per_cue_max': max((t.count('\n') + 1 for t in texts), default=0),
               'chars_per_line_max': max((len(line) for t in texts for line in t.split('\n')), default=0),
               'upper_case_share': round(sum(1 for t in texts if t and t.upper() == t and t.lower() != t)
                                         / max(len(texts), 1), 3),
               'cues_by': prov.get((owner, 'cues'), 'ai')}
        if style:
            try:
                row['size_share_of_height'] = round(float(style.get('size')) / height, 4)
            except (TypeError, ValueError):
                pass
            try:
                x, y, w, h = [float(v) for v in str(style.get('geometry')).split()[:4]]
                row['box'] = [round(x / width, 3), round(y / height, 3), round((x + w) / width, 3),
                              round((y + h) / height, 3)]
            except (TypeError, ValueError):
                pass
            row['style'] = {k: v for k, v in style.items() if k != 'geometry'}
            row['style_by'] = {field: prov.get((owner, 'style:' + field), 'ai') for field in style}
        out.append(row)
    return out


# ---------------------------------------------------------------------------- the route and the person's words

def route(project):
    """How the AI made the video, from its journal: stages finished, edits by whom, undos, review rounds. No labels or
    words (they name this video's content)."""
    side = _side(project)
    journal = _journal(side)
    stages = [e['text'].split(':')[1] for e in journal if str(e.get('text', '')).startswith('stage:')
              and e['text'].endswith(':done')]
    edits = _count(e.get('actor') for e in journal if e.get('kind') == 'apply')
    reviews = len(list(Path(project).parent.glob(Path(project).stem + '*review')))
    return {'stages': stages, 'edits_by': edits, 'undos': sum(1 for e in journal if e.get('kind') == 'undo'),
            'hand_edit_entries': sum(1 for e in journal if e.get('kind') == 'hand_edit'),
            'review_folders': reviews, 'sound_checks': sum(1 for e in journal if e.get('kind') == 'sound_check'),
            'journal_entries': len(journal)}


def instructions(project):
    """The person's own instructions recorded for the project (kind 'said': typed in the chat, or New video's request),
    with the always/never sentences picked out, oldest first. Which of them are about style (and which a later one
    contradicts) is the AI's call; only these sentences may become rules, in the person's words."""
    out = []
    for e in _said_entries(project):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', e['text']) if RULE_WORDS.search(s)]
        out.append({'time': e.get('time'), 'where': e.get('where'), 'words': e['text'][:1000],
                    'always_never': sentences})
    return out


def check_rules(project, rules):
    """The rules a Look may carry from a project: each is the person's own words, recorded (kind 'said'), and an
    always/never sentence. Returns them cleaned; raises on one that wasn't said."""
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise ValueError('rules must be a list of {words, said_at}')
    recorded = [(e.get('time'), ' '.join(str(e.get('text') or '').split()).lower()) for e in _said_entries(project)]
    out = []
    for rule in rules:
        words = ' '.join(str((rule or {}).get('words') or '').split()) if isinstance(rule, dict) else ''
        if not words or not RULE_WORDS.search(words):
            raise ValueError('a rule is an "always ..." or "never ..." sentence in the person\'s own words')
        if not any(words.lower().strip('."\'') in text for _, text in recorded):
            raise ValueError(f'not recorded as said by the person in this project: {words[:80]}')
        out.append({'words': words, 'said_at': rule.get('said_at') or next(
            (time for time, text in recorded if words.lower().strip('."\'') in text), None)})
    return out


# ---------------------------------------------------------------------------- the Look it was made with

def made_with(project, parts):
    """The Look (and Style, Theme) the video was made with, from its brief, and where the finished video differs
    from that Look's own graphic kit (fonts, colours, families)."""
    side = _side(project)
    brief = _read_json(side / 'brief.json', {}) or {}
    out = {key: brief.get(key) for key in ('look', 'style', 'theme') if brief.get(key)}
    if not out.get('look'):
        return out
    entry = None
    try:        # the person's own Looks first (their record names the graphic kit), then the installed catalogue
        import letitedit.looks.learned_looks as learned_looks
        entry = next((e for e in learned_looks.catalog().get('looks', []) if e.get('id') == out['look']), None)
    except Exception:  # noqa: BLE001 - a test profile may have none
        entry = None
    if entry is None:
        try:
            import letitedit.looks.looks as looks
            entry = next((e for e in looks.catalog().get('looks', []) if e.get('id') == out['look']), None)
        except Exception:  # noqa: BLE001 - the catalogue may not load in a test profile
            entry = None
    if not entry:
        out['note'] = 'that Look is not installed on this PC, so the differences were not worked out'
        return out
    out['title'] = entry.get('title') or entry.get('label')
    differences = []
    kit = _read_json(entry['graphic_kit'], {}) if entry.get('graphic_kit') else {}
    if kit:
        families = {f.get('id') for f in kit.get('families') or []}
        used = set((parts.get('graphics') or {}).get('families') or {})
        if families - used:
            differences.append('kit families not used: ' + ', '.join(sorted(str(f) for f in families - used)))
        fonts = set(((kit.get('style') or {}).get('fonts') or {}).values())
        if parts['graphics']['fonts'] and set(parts['graphics']['fonts']) != fonts:
            differences.append(f"graphics fonts {sorted(parts['graphics']['fonts'])} (the Look's: {sorted(fonts)})")
    for caption in parts.get('captions') or []:
        changed_fields = [f for f, who in (caption.get('style_by') or {}).items() if who in ('person', 'both')]
        if changed_fields:
            differences.append(f"caption track {caption['track']}: the person set {', '.join(changed_fields)}")
    out['differences'] = differences
    return out


# ---------------------------------------------------------------------------- the whole evidence, and its recipe text

def evidence(project, export=None, out=None):
    """Everything Learn reads from a finished project: the version chosen (an export and the exact timeline it was
    made from), the other versions, the exact values part by part with who chose each, the route, the Look it was made
    with and the person's recorded instructions. Writes project-evidence.json in out when given."""
    import letitedit.timeline.edit_script as es
    project = Path(project).resolve()
    if project.suffix.lower() != '.mlt' or not project.is_file():
        raise ValueError(f'{project} is not a letitedit project (.mlt) on this PC')
    note_hand_edits(project)                # anything the person changed since the AI's last edit is recorded first
    version, rows = choose_version(project, export)
    reply = {'format': FORMAT, 'project': str(project), 'version': version,
             'other_versions': [r for r in rows if version is None or r['file'] != version['file']],
             'made': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if version is None:
        reply['no_export'] = True
        reply['next'] = ('this project has no exported video yet: export it first (letitedit_export), then make the '
                         'Look from that export')
    timeline = Path(version['timeline']) if version and version.get('timeline') else None
    if timeline is None and version is not None:
        reply['exact'] = None
        reply['note'] = ('no timeline matching this version is kept, so nothing about it is exact: learn it from its '
                         'video the usual way (importer, then letitedit_learn prepare and save)')
    else:
        source = timeline or project
        prov = provenance(project, source)
        script = es.read(source)
        parts = facts(script, prov['values'])
        reply['exact'] = parts
        reply['provenance'] = {k: v for k, v in prov.items() if k != 'values'}
        reply['provenance']['counts'] = _count(prov['values'].values())
        reply['made_with'] = made_with(project, parts)
    reply['route'] = route(project)
    reply['instructions'] = instructions(project)
    reply['measured'] = ('the export is measured the usual way (letitedit_learn(action=measure) on the version\'s video): '
                         'motion, colour, loudness and what the picture looks like are measured; everything in exact '
                         'is read from the timeline')
    if out:
        folder = Path(out)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'project-evidence.json'
        path.write_text(json.dumps(reply, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        reply['evidence'] = str(path)
    return reply


def _pct(value):
    return f'{value * 100:.0f}%' if isinstance(value, (int, float)) else '?'


def _who(by):
    """'set by the person' / 'partly by the person' for a {person, both, ai} count, or ''."""
    if not isinstance(by, dict):
        return ''
    person, both = by.get('person', 0), by.get('both', 0)
    total = sum(by.values())
    if not total or not (person or both):
        return ''
    return f' (the person set {person + both} of {total} by hand: lean toward those)'


def recipe_section(evidence_or_parts):
    """The recipe's "Exact values from the finished video" section: compact numbers, who chose them, preferences
    (never rules) for the person's own choices. The AI keeps it, edits it or writes its own."""
    parts = evidence_or_parts.get('exact') if 'exact' in evidence_or_parts else evidence_or_parts
    if not parts:
        return ''
    lines = ['## Exact values from the finished video',
             'Read from the timeline the video was exported from (exact), not measured from its pictures. Values the '
             "person set by hand weigh more than the AI's own choices; they are preferences, not rules."]
    p = parts['pacing']
    lines.append(f"- Cutting: {p['shots']} shots on the main picture, {p['cuts_per_min']} cuts a minute, shot length "
                 f"quartiles {p['shot_s_quartiles']} s (weighted median {p['shot_s_weighted_median']} s)" + _who(p['by']) + '.')
    if parts.get('angles'):
        a = parts['angles']
        lines.append(f"- Camera angles: {a['angles']} angles of one talk, {a['switches_per_min']} switches a minute, holds "
                     f"{a['hold_s_quartiles']} s" + _who(a['by']) + '.')
    b = parts['broll']
    if b['count']:
        lines.append(f"- Cutaways: {b['count']} ({b['per_min']} a minute, {_pct(b['share_of_time'])} of the time), "
                     f"{b['seconds_quartiles']} s long (weighted median {b['seconds_weighted_median']} s); sources "
                     f"{b['sources']}; treatments {b['treatments'] or 'none'}" + _who(b['by']) + '.')
    else:
        lines.append('- Cutaways: none.')
    f = parts['framing']
    if f['scaled_items']:
        lines.append(f"- Framing: {f['scaled_items']} clips scaled, scale {f['scale_quartiles']} of the frame width "
                     f"(weighted median {f['scale_weighted_median']}).")
    for c in parts['captions']:
        if not c['drawn']:
            lines.append(f"- Subtitle track {c['track']} (not drawn on the picture): {c['cues']} cues.")
            continue
        s = c.get('style') or {}
        person = [k for k, who in (c.get('style_by') or {}).items() if who in ('person', 'both')]
        lines.append(
            f"- Captions ({c['track']}): {s.get('family')} {s.get('style') or ''} {s.get('weight') or ''}, size "
            f"{_pct(c.get('size_share_of_height'))} of the frame height, fill {s.get('fgcolour')}, outline "
            f"{s.get('outline')} {s.get('olcolour')}, background {s.get('bgcolour')}, shadow {s.get('shadow')}, "
            f"{s.get('halign')}/{s.get('valign')} in box {c.get('box')}; {c['per_min']} cues a minute, "
            f"{c['words_per_cue_quartiles']} words and {c['cue_s_quartiles']} s each, up to {c['lines_per_cue_max']} "
            f"lines" + (f"; the person set {', '.join(person)} by hand (lean toward them)" if person else '') + '.')
    g = parts['graphics']
    if g['count']:
        lines.append(f"- Graphics: {g['count']} ({g['families']}), fonts {g['fonts'] or 'not recorded'}" + _who(g['by']) + '.')
    if parts['stickers']['count']:
        lines.append(f"- Stickers: {parts['stickers']['count']} ({parts['stickers']['per_min']} a minute).")
    sp = parts['splits']
    lines.append(f"- Split screens: {sp['count']}" + (f", {sp['panes']} panes, {sp['seconds']} s" if sp['count'] else '') + '.')
    lines.append(f"- Speed changes: {parts['speed']['count']}" + (
        ', ' + ', '.join(f"{c['speed']:g}x for {c['seconds']:g} s" for c in parts['speed']['changes'][:6])
        if parts['speed']['count'] else '') + '.')
    se = parts['sound_effects']
    lines.append(f"- Sound effects: {se['count']} ({se['per_min']} a minute)" + _who(se['by']) + '.')
    for m in parts['music']['items'][:3]:
        lines.append(f"- Music: {m['source']} piece, {m['seconds']:g} s, level {m['gain_db_median']} dB, fades "
                     f"{m['fades_s'] or 'none'}" + (' (set by the person)' if m['by'] in ('person', 'both') else '') + '.')
    if not parts['music']['pieces']:
        lines.append('- Music: none.')
    lines.append(f"- Transitions: {parts['transitions'] or 'straight cuts only'}.")
    gr = parts['grade']
    lines.append(f"- Colour and light: {gr['graded_items']} clips carry a colour grade, {gr['lighting_items']} live "
                 f"lighting windows" + (f", whole video: {gr['master']}" if gr['master'] else '') + '.')
    return '\n'.join(lines)


def rules_section(rules):
    """The person's own rules, in their words."""
    if not rules:
        return ''
    return '## Your own rules\nThe person said these while editing; they hold for every video in this Look.\n' + ''.join(
        f'- "{rule["words"]}"\n' for rule in rules)


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="A Look's exact values from a finished project, and the records "
                                                 "that make them exact.")
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('said', help="journal the person's own instruction to the AI")
    one.add_argument('project', nargs='?')
    one.add_argument('--folder', help="a New video's folder (its project doesn't exist yet)")
    one.add_argument('text', nargs='?')
    one.add_argument('--file', help='read the words from this UTF-8 file')
    one.add_argument('--where', default='chat')
    two = commands.add_parser('versions', help="a project's finished videos and their timelines")
    two.add_argument('project')
    three = commands.add_parser('evidence', help='the exact evidence of one version')
    three.add_argument('project')
    three.add_argument('--export')
    three.add_argument('--out')
    args = parser.parse_args(argv)
    try:
        if args.command == 'said':
            text = Path(args.file).read_text(encoding='utf-8-sig') if args.file else args.text
            if args.folder and text is None and not args.file:
                args.project, text = None, args.project      # said --folder <folder> "<words>"
            if not args.project and not args.folder:
                raise ValueError('said needs a project or --folder')
            reply = {'ok': True, 'entry': said(args.project, text, args.where, folder=args.folder)}
        elif args.command == 'versions':
            reply = {'ok': True, 'versions': versions(args.project)}
        else:
            reply = {'ok': True, **evidence(args.project, args.export, args.out)}
    except (OSError, ValueError) as error:
        reply = {'ok': False, 'error': str(error)}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False, default=str) + '\n')
    return 0 if reply['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
