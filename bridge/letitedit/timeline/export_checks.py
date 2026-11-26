import functools
import hashlib
import html
import json
import os
import re
import stat as _stat
from pathlib import Path

import letitedit.looks.look_check as look_check


def receipt_path(project):
    return Path(project).with_suffix('.export-checks.json')


# ---------------------------------------------------------------------------- what a video is made of
# T347: the record checks (this receipt, the review's freshness and its mix check) compare what the video is made of,
# so a project that is only moved, or saved with markers or notes added, still matches its export.

CONTENT_PREFIX = 'c1-'      # a content measure (content_digest); a receipt or record without one is from before it
HEAD_BYTES = 1 << 16        # a source file is known by its name, its size and a hash of its first 64 KiB
# project_look's record of every export and the exact timeline it was made from, in the project's side folder (read
# here by name: that module sits above this one)
EXPORTS_RECORD = 'exports.json'
EXPORT_TIMELINES = 'exports'
_ROOT = re.compile(rb'<mlt\b[^>]*?\sroot="([^"]*)"')
_PATHY = re.compile(r'^(?:[A-Za-z]:[\\/]|[\\/]{2})|[\\/]|\.[A-Za-z][A-Za-z0-9]{1,4}$')
# what a script holds that doesn't change the render: an item's id (the timeline's own bookkeeping) and its name
# (the label on the timeline); markers, notes, the Look's and hook's names and the journal are not in these keys at all
RENDER_KEYS = ('profile', 'tracks', 'captions', 'master')
LABEL_KEYS = ('id', 'name')


def project_folder(path):
    """The folder a timeline file's paths belong to: its <mlt root="..."> (an export's snapshot keeps the project's
    folder there), else the folder it is in."""
    path = Path(path)
    try:
        with open(path, 'rb') as handle:
            match = _ROOT.search(handle.read(4096))
    except OSError:
        match = None
    if match and match.group(1).strip():
        return Path(html.unescape(match.group(1).decode('utf-8', errors='replace')))
    return path.resolve().parent


def _norm(path):
    return os.path.normcase(os.path.normpath(str(path))).replace('\\', '/')


def _inside(path, folder):
    """path relative to folder (normalised, '/'), or None when it isn't inside it."""
    p, f = _norm(path), _norm(folder).rstrip('/')
    return p[len(f) + 1:] if f and p.startswith(f + '/') else None


@functools.lru_cache(maxsize=4096)
def _head(path, size, modified_ns):      # the file's time only keys this cache: it is never part of the measure
    try:
        with open(path, 'rb') as handle:
            return hashlib.sha256(handle.read(HEAD_BYTES)).hexdigest()[:16]
    except OSError:
        return 'unreadable'


def file_identity(value, folder, moved=()):
    """A source named by what it is, not where it is: 'file:<name>:<bytes>:<hash of its start>' when the file is
    there (a relative path is read from `folder`; one inside a folder `then` of `moved` [(then, now)] that is gone
    from there is looked for at the same place inside `now`: a project moved with its files), 'gone:<the path inside
    the project, or as written>' for an absolute path to no file, None for a string that names no file."""
    if not isinstance(value, str) or not value or len(value) > 1024 or '\n' in value or not _PATHY.search(value):
        return None
    raw = Path(value)
    try:
        absolute = raw.is_absolute() or value.startswith(('\\\\', '//'))
        path = raw if absolute else Path(folder) / raw
    except (TypeError, ValueError):
        return None
    inside = _inside(path, folder)
    candidates = [path]
    for then, now in moved:
        tail = _inside(path, then)
        if tail is not None:
            candidates.append(Path(now) / tail)
            inside = tail if inside is None else inside
    for candidate in candidates:
        try:
            st = os.stat(candidate)
        except (OSError, ValueError):
            continue
        if _stat.S_ISREG(st.st_mode):
            return f'file:{candidate.name.casefold()}:{st.st_size}:{_head(str(candidate), st.st_size, st.st_mtime_ns)}'
    if not absolute:
        return None
    return 'gone:' + ('<project>/' + inside if inside is not None else _norm(path))


def _folder_pattern(folder, in_json=True):
    """The folder as written in a JSON text (in_json) or in a plain string: any slash, an escaped drive colon, any
    case; never the start of a longer name."""
    parts = [p for p in re.split(r'[\\/]+', str(folder)) if p]
    if not parts:
        return None
    sep = r'(?:\\\\|/)+' if in_json else r'[\\/]+'          # in JSON a backslash is written as two
    colon = r'(?:\\\\)*:' if in_json else r'\\?:'            # a drive colon escaped for an ffmpeg graph
    # what may follow the folder: a slash, the end of the text or a quote or bracket, never more of a name (a space
    # included: "Fan video 2" is another folder)
    end = r'(?=\\\\|/|\\"|["\'),;:\]}|]|$)' if in_json else r'(?=[\\/"\'),;:\]}|]|$)'
    first = re.escape(parts[0][:-1]) + colon if parts[0].endswith(':') else re.escape(parts[0])
    return re.compile((sep if str(folder).startswith(('\\', '/')) else '') + first +
                      ''.join(sep + re.escape(p) for p in parts[1:]) + end, re.I)


def _canon(value, folder, moved):
    if isinstance(value, dict):
        return {k: _canon(v, folder, moved) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon(v, folder, moved) for v in value]
    if isinstance(value, str):
        return file_identity(value, folder, moved) or value
    return value


def render_content(script, folder, moved=()):
    """What the video is made of, from an edit script (edit_script.read): the size and rate, every track's clips,
    gaps, cut points, effects and levels, the captions and their style, the master effects. Each source is named by
    what it is (file_identity); a path written inside a longer text is written relative to the project. Left out:
    the items' ids and names, the markers, notes, the Look's and hook's names (none of which a render shows)."""
    tracks = [{**t, 'items': [{k: v for k, v in item.items() if k not in LABEL_KEYS} if isinstance(item, dict) else item
                              for item in t.get('items') or []]} for t in script.get('tracks') or []]
    for t in tracks:      # a track of gaps alone shows nothing (an open window writes one on an empty track)
        if all(isinstance(item, dict) and set(item) == {'gap'} for item in t['items']):
            t['items'] = []
    content = {key: script.get(key) for key in RENDER_KEYS if key != 'tracks'}
    content['tracks'] = tracks
    return located_text(content, folder, moved)


def located_text(value, folder, moved=()):
    """value as JSON text with each source named by what it is (file_identity) and the project's folder (and each
    folder of `moved`) written as <project> inside any longer text: the same text wherever the project is."""
    text = json.dumps(_canon(value, folder, moved), sort_keys=True, ensure_ascii=False, default=str)
    places = sorted({str(f) for f in [folder] + [f for pair in moved for f in pair] if f}, key=len, reverse=True)
    for place in places:
        pattern = _folder_pattern(place)
        if pattern:
            text = pattern.sub('<project>', text)
    return text


def content_digest(script, folder, moved=()):
    """A short hash of render_content: equal for the same video whatever folder the project is in."""
    return CONTENT_PREFIX + hashlib.sha256(render_content(script, folder, moved).encode('utf-8')).hexdigest()[:32]


def sources_digest(script, folder, moved=()):
    """A short hash of the source files alone (each file_identity a script names): whether a source was replaced,
    apart from how the timeline is read."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            identity = file_identity(value, folder, moved)
            if identity:
                found.add(identity)
    walk([t.get('items') for t in script.get('tracks') or []] + [script.get('master'), script.get('captions')])
    return hashlib.sha256('\n'.join(sorted(found)).encode('utf-8')).hexdigest()[:32]


def project_content(path, moved=()):
    """content_digest of a saved timeline file (a project, or an export's kept timeline, whose own folder is its
    <mlt root>), `moved` as in file_identity."""
    import letitedit.timeline.edit_script as edit_script
    return content_digest(edit_script.read(path), project_folder(path), moved)


def project_moves(project):
    """[(folder then, folder now)] for a project's own content: each folder it was in when a kept export was made,
    with the one it is in now (a project moved with its files, whose saved paths still name the old folder)."""
    here = Path(project).resolve().parent
    return [(folder, here) for folder in former_folders(project)]


def kept_exports(project):
    """[(record, kept timeline path or None)] of exports.json in the project's side folder, oldest first."""
    import letitedit.timeline.project_journal as project_journal
    try:
        side = project_journal.folder(Path(project).resolve())
        record = json.loads((side / EXPORTS_RECORD).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return []
    out = []
    for row in (record or {}).get('exports') or []:
        if isinstance(row, dict):
            kept = side / EXPORT_TIMELINES / str(row.get('timeline') or '') if row.get('timeline') else None
            out.append((row, kept if kept and kept.is_file() else None))
    return out


def export_record(project, video):
    """(record, kept timeline or None) of this video's export in exports.json: the same file, else the newest
    export of the same name (a moved project's records name the folder it was in); (None, None) when none is kept."""
    rows = kept_exports(project)
    here = _norm(Path(video).resolve())
    same = [r for r in rows if r[0].get('output') and _norm(r[0]['output']) == here]
    if not same:
        name = Path(video).name.casefold()
        same = [r for r in rows if r[0].get('output') and
                re.split(r'[\\/]', str(r[0]['output']))[-1].casefold() == name]
    return same[-1] if same else (None, None)


def changed_since_export(project, video):
    """(changed, how) of the saved project against what this video was exported from, by what the video is made of
    (content_digest): True or False, or None when it can't be compared (how says why; 'no record' when exports.json
    keeps no export of this video)."""
    row, kept = export_record(project, video)
    if row is None:
        return None, 'no record'
    return _changed_against(project, row, kept)


def _changed_against(project, row, kept):
    import letitedit.timeline.edit_script as edit_script
    here = Path(project).resolve().parent
    try:
        script, moved = edit_script.read(project), project_moves(project)
        now = content_digest(script, project_folder(project), moved)
        recorded = row.get('content_sha256')
        if recorded and now == recorded:
            return False, 'against what its export recorded'
        if kept is None:
            return (True, 'against what its export recorded') if recorded else \
                (None, 'not compared: its export record keeps no timeline')
        then = [(project_folder(kept), here)]
        kept_script = edit_script.read(kept)
        if row.get('sources_sha256') and sources_digest(kept_script, project_folder(kept), then) != row['sources_sha256']:
            return True, 'a source file is not what it was at the export'
        if now == content_digest(kept_script, project_folder(kept), then):
            return False, 'against the timeline its export kept'
        # the editor's window writes settings a saved file leaves out (its defaults: an export from an open window
        # keeps them); the same timeline but for settings on one side only, with no edit since, is no change
        if (relaxed_equal(render_content(script, project_folder(project), moved),
                          render_content(kept_script, project_folder(kept), then))
                and not edits_since(project, row.get('started'))):
            return False, 'against the timeline its export kept (settings the editor fills in aside)'
        return True, 'against the timeline its export kept'
    except Exception as error:  # noqa: BLE001 - not compared: said so
        return None, f'not compared ({type(error).__name__}: {error})'


EDIT_KINDS = ('apply', 'undo', 'hand_edit', 'version')     # journal entries that change the cut


def _moment(text):
    import datetime
    try:
        moment = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def edits_since(project, when):
    """The journal's edits (an apply that only wrote markers is none) from `when` (an ISO time) on; every edit when
    `when` can't be read."""
    import datetime
    import letitedit.timeline.project_journal as project_journal
    start = _moment(when)
    start = start - datetime.timedelta(seconds=1) if start else None    # the journal keeps whole seconds
    return [e for e in project_journal.entries(project, limit=None)
            if e.get('kind') in EDIT_KINDS and not e.get('markers_only') and e.get('changes_total', 1) not in (0, '0')
            and (start is None or (_moment(e.get('time')) or start) >= start)]


def relaxed_equal(a, b):
    """Two render_content texts equal but for an effect's settings present on one side only (its `params`)."""
    def same(x, y, key=None):
        if isinstance(x, dict) and isinstance(y, dict):
            keys = x.keys() & y.keys() if key == 'params' else x.keys()
            return (key == 'params' or x.keys() == y.keys()) and all(same(x[k], y[k], k) for k in keys)
        if isinstance(x, list) and isinstance(y, list):
            return len(x) == len(y) and all(same(p, q) for p, q in zip(x, y))
        return x == y
    return same(json.loads(a), json.loads(b))


def changed_since_newest_export(project):
    """(changed, how) of the project against its newest export (the one its pre-export receipt was written for), as
    changed_since_export."""
    rows = kept_exports(project)
    return _changed_against(project, *rows[-1]) if rows else (None, 'no record')


def former_folders(project):
    """The folders the project was in when its kept exports were made (each kept timeline's <mlt root>), other than
    the one it is in now: where its older records' absolute paths point."""
    here = _norm(Path(project).resolve().parent)
    seen = []
    for _, kept in kept_exports(project):
        if kept is not None:
            folder = project_folder(kept)
            if _norm(folder) != here and all(_norm(folder) != _norm(f) for f in seen):
                seen.append(folder)
    return seen


def rebased(script, folder, former):
    """The script with every path inside `folder` written inside `former` instead (as the project's older records
    saw it), the slashes as they were."""
    pattern = _folder_pattern(folder, in_json=False)
    parts = [p for p in re.split(r'[\\/]+', str(former)) if p]

    def swap(match):
        sep = '/' if '/' in match.group(0) and '\\' not in match.group(0) else '\\'
        return sep.join(parts)

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return pattern.sub(swap, value) if isinstance(value, str) else value
    return walk(script)


def legacy_match(project, script, digest, measure):
    """An older record's hash (made by `measure` from a script, with the project's paths as they were then) compared
    with the project now: True when it matches as it is, or with the paths put back in a folder the project was in
    (each kept export's <mlt root>); None when it doesn't: the hash can't tell a move from an edit, so the caller
    asks what the video is made of instead."""
    try:
        if measure(script) == digest:
            return True
    except Exception:  # noqa: BLE001 - an unreadable record is compared no further
        return None
    former = former_folders(project)
    for now, then in moves(project, script, former) if former else ():
        try:
            if measure(rebased(script, now, then)) == digest:
                return True
        except Exception:  # noqa: BLE001 - try the next folder
            continue
    return None


def _strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value


def moves(project, script, former):
    """[(folder now, folder then)]: each folder the project was in (`former`), with the folder its files are in now:
    the project's own, or the one its paths point to when it was copied without them (found from a kept export's
    timeline: the same file name under both)."""
    import letitedit.timeline.edit_script as edit_script
    here = Path(project).resolve().parent
    pairs = [(here, f) for f in former]
    now_paths = {_norm(s): s for s in _strings(script) if _PATHY.search(s) and len(s) < 1024}
    for _, kept in kept_exports(project):
        if kept is None:
            continue
        then = project_folder(kept)
        if all(_norm(then) != _norm(f) for f in former):
            continue
        try:
            tails = {t for t in (_inside(s, then) for s in _strings(edit_script.read(kept))
                                 if _PATHY.search(s) and len(s) < 1024) if t}
        except Exception:  # noqa: BLE001 - this kept timeline gives no folder
            continue
        for low, raw in now_paths.items():
            for tail in tails:
                if low.endswith('/' + tail) and len(low) > len(tail) + 1:
                    folder = raw[:len(raw) - len(tail) - 1]
                    if all(_norm(folder) != _norm(a) or _norm(then) != _norm(b) for a, b in pairs):
                        pairs.append((Path(folder), then))
                    break
    return pairs


CANT_COMPARE = ('the pre-export receipt was written before letitedit recorded what the video is made of, and its '
                'hash no longer matches the project (a moved project\'s paths, or an older reading of the timeline), so '
                'it can\'t be compared; the video matches its newest export by what it is made of, or no export kept '
                'its timeline, so this is not counted as a change')


def kit_required(project, script=None):
    import letitedit.review.brief_check as brief_check
    import letitedit.looks.look_inputs as look_inputs
    import letitedit.looks.looks as looks
    if any(item.get('graphic', {}).get('params', {}).get('_look_kit')
           for track in (script or {}).get('tracks', []) for item in track.get('items', [])):
        return True
    chosen = ((look_inputs.read(project) or {}).get('look') or
              (brief_check.load(project=project) or {}).get('look'))
    if not chosen:
        return False
    try:
        return Path(looks.read(chosen)['recipe']).with_name('graphic-kit.json').is_file()
    except Exception:
        return True


def cached_measure(project, name, script, measure, extra=None, version=None):
    """A whole-timeline measurement kept beside the project (<project>.<name>.json), keyed by everything it reads: the
    timeline, its source files' size and dates, `extra` (a decisions file the measurement also reads) and `version`
    (how it measures: a new one measures again). Every export ran it again on an unchanged timeline (a render of the
    whole video); now only a change measures again. A measurement that raised or was refused is not kept."""
    import hashlib
    import letitedit.looks.graphic_kit as graphic_kit
    extra_text = Path(extra).read_text(encoding='utf-8', errors='replace') if extra and Path(extra).is_file() else ''
    parts = (name, graphic_kit.timeline_digest(script), graphic_kit.source_fingerprint(script), extra_text)
    if version is not None:
        parts += (f'version {version}',)
    key = hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()
    path = Path(project).with_suffix(f'.{name}.json')
    try:
        saved = json.loads(path.read_text(encoding='utf-8-sig'))
        if saved.get('key') == key and isinstance(saved.get('result'), dict):
            return {**saved['result'], 'reused': 'measured earlier on this same timeline'}
    except (OSError, ValueError):
        pass
    result = measure()
    if isinstance(result, dict) and 'error' not in result:
        try:
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps({'key': key, 'result': result}, default=str), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            pass
    return result


def word_caption_summary(measured):
    """'; <reason>' or '; lowest word captions: "WORD" 1.8:1 at 12.3 s (caption-003), ...' for the major's text."""
    if measured.get('reason'):
        return f"; {measured['reason']}"
    found = (measured.get('word_captions') or {}).get('findings') or []
    if not found:
        return ''
    shown = []
    for finding in found[:3]:
        where = f" at {finding['worst_at']:.2f} s" if finding.get('worst_at') is not None else ''
        what = (finding['shown'] if finding.get('shown') else
                f"{finding['minimum']:.1f}:1" if not finding.get('unmeasured') or finding.get('below_floor_frames')
                else 'unmeasured (' + ', '.join(finding['unmeasured']) + ')')
        shown.append(f"\"{finding.get('word') or '?'}\" {what}{where} ({finding['item']})")
    more = f', and {len(found) - 3} more' if len(found) > 3 else ''
    return '; lowest word captions: ' + ', '.join(shown) + more


def unavailable_line(unavailable):
    """The delivery warning for checks that could not run: the export is not checked by them."""
    return ('Exported without these checks (they could not run, so this export is not checked by them): '
            + '; '.join(f"{u['check']} ({u['reason']})" for u in unavailable))


def unavailable_result(error):
    """The receipt when the pre-export checks could not run at all."""
    unavailable = [{'device': 'checks', 'check': 'pre-export checks', 'reason': str(error)}]
    return {'checks': {}, 'findings': [], 'notes': [], 'unavailable': unavailable, 'checked': False, 'passed': False,
            'blocks_export': False, 'delivery_warning': unavailable_line(unavailable)}


def run(project, source=None):
    from letitedit.looks.look_check import current_project
    script = current_project(source or project)[2]
    findings = []
    notes = []      # what was not checked, and the receipt's record: never a fault in the video
    unavailable = []  # a check that could not run at all: no finding in the video, and the export is not checked by it
    checks = {}
    try:
        checks['look'] = look_check.check(project)
        for finding in checks['look'].get('findings', []):
            (findings if finding.get('severity') in ('critical', 'major') else notes).append(finding)
        if checks['look'].get('project_sha256', look_check.project_digest(script)) != look_check.project_digest(script):
            findings.append({'severity': 'major', 'device': 'look', 'problem': 'Look evidence predates the live export snapshot'})
    except Exception as error:
        checks['look'] = {'passed': False, 'unavailable': True, 'error': str(error)}
        unavailable.append({'device': 'look', 'check': 'Look check', 'reason': str(error)})
    try:
        import letitedit.pictures.caption_readability as caption_readability
        import letitedit.looks.caption_colour as caption_colour
        captions = [item for track in script['tracks'] for item in track['items']
                    if caption_readability.caption_item(item)]
        if captions:
            requirements = json.dumps(checks.get('look', {}).get('requirements', {})).lower()
            inverted = 'inverted-then-white' in requirements or 'inverted_then_white' in requirements
            if inverted:
                choice = caption_colour.choice_status(project, script)
                checks['caption_choice'] = choice
                if not choice['passed']:
                    findings.append({'severity': 'major', 'device': 'captions', 'problem': choice['reason']})
            # its own file: '<project>.caption-colour.json' is the colour choice's receipt, which this must never overwrite
            measured = cached_measure(project, 'caption-colour-check' if inverted else 'caption-readability', script,
                                      lambda: (caption_colour if inverted else caption_readability).measure(source or project),
                                      extra=caption_colour.receipt_path(project) if inverted else None,
                                      version=None if inverted else caption_readability.MEASURE_VERSION)
            checks['captions'] = measured
            if not measured.get('passed'):
                findings.append({'severity': 'major', 'device': 'captions',
                                 'problem': (f"Pre-export caption check: {measured['reason']}" if measured.get('unsupported')
                                             else 'Pre-export caption contrast has unresolved findings; see caption '
                                                  'measurements' + word_caption_summary(measured))})
        else:
            checks['captions'] = {'applicable': False, 'reason': 'No supported kinetic captions on the export snapshot'}
    except Exception as error:
        checks['captions'] = {'passed': False, 'unavailable': True, 'error': str(error)}
        unavailable.append({'device': 'captions', 'check': 'caption check', 'reason': str(error)})
    try:
        import letitedit.sound.tonal_check as tonal_check
        tones = tonal_check.scan_script_music(script)
        checks['music_tones'] = tones
        if tones['flagged']:
            findings.append({'severity': 'major', 'device': 'sound',
                             'problem': tonal_check.summary_line(tones, 'the music the cut uses') + '; a different song or '
                             'section avoids a howl-like lead unless the Look or the person wants that sound'})
    except Exception as error:
        checks['music_tones'] = {'error': str(error)}
    kit = checks.get('look', {}).get('graphic_kit')
    required = kit is not None or kit_required(project, script)
    stale = kit is not None and kit.get('timeline_sha256') != __import__('letitedit.looks.graphic_kit', fromlist=["*"]).timeline_digest(script)
    if stale:
        findings.append({'severity': 'major', 'device': 'graphic_kit',
                         'problem': 'Kit evidence predates the exact live export snapshot'})
    if required and kit is None:
        notes.append({'severity': 'note', 'kind': 'note', 'device': 'graphic_kit',
                      'problem': 'The Look kit check did not run, so its graphics are not checked'})
    elif required and not kit.get('passed', False) and not kit.get('findings'):
        findings.append({'severity': 'major', 'device': 'graphic_kit',
                         'problem': 'The Look kit check failed; video exports with this unresolved style finding'})
    # a failed kit check with findings: they are in the Look check's findings already, said once
    warning = ' '.join(x for x in ('Video delivered with unresolved checks; see findings.' if findings else '',
                                   unavailable_line(unavailable) if unavailable else '') if x) or None
    result = {'project_sha256': look_check.project_digest(script), 'checks': checks, 'findings': findings, 'notes': notes,
              'unavailable': unavailable, 'checked': not unavailable, 'passed': not findings and not unavailable,
              'blocks_export': False, 'delivery_warning': warning}
    try:
        result['content_sha256'] = content_digest(script, project_folder(project))
    except Exception:  # noqa: BLE001 - the review then compares the receipt's project hash as before
        pass
    try:
        path = receipt_path(project)
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
        temporary.replace(path)
    except OSError as error:
        findings.append({'severity': 'major', 'device': 'checks', 'problem': f'Could not save pre-export findings: {error}'})
        result['passed'] = False
    return result


def read(project):
    from letitedit.looks.look_check import current_project
    try:
        result = json.loads(receipt_path(project).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'findings': [{'severity': 'major', 'device': 'checks', 'problem': 'Pre-export check receipt is missing or unreadable'}]}
    script = current_project(project)[2]
    stale = 'Pre-export check receipt predates the current edit'
    if result.get('content_sha256'):
        # what the video is made of (T347): a move or a save of markers or notes alone is no change
        if (result['content_sha256'] != content_digest(script, project_folder(project), project_moves(project))
                # the newest export (this receipt's) says whether the difference is only how a timeline was written
                and changed_since_newest_export(project)[0] is not False):
            result['findings'] = result.get('findings', []) + [{'severity': 'major', 'device': 'checks', 'problem': stale}]
        return result
    if legacy_match(project, script, result.get('project_sha256'), look_check.project_digest):
        return result
    # an older receipt whose hash differs: the newest export's own timeline (which this receipt was written for)
    # says whether the video changed, by what it is made of; with none to compare, never a change
    changed, _ = changed_since_newest_export(project)
    if changed:
        result['findings'] = result.get('findings', []) + [{'severity': 'major', 'device': 'checks', 'problem': stale}]
    else:
        result['notes'] = result.get('notes', []) + [{'severity': 'note', 'kind': 'note', 'device': 'checks',
                                                      'problem': CANT_COMPARE}]
        result['not_compared'] = CANT_COMPARE
    return result
