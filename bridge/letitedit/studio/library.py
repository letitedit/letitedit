"""The `index` kind: a library of footage folders, written into the job folder (CONTRACT.md section 6, "index").

Read only on the footage: nothing is written into a footage folder. Transcripts and other analyses go to letitedit's
own caches, the library's files to the job folder, and the moment ledger to the Studio home.

    files        every media file under the folders: its content id (file_id), every path with that content, the
                 probe (length, size, fps, recorded time, camera, HDR), the place from its GPS when it has one
    transcripts  the words of each file with talking (letitedit's speech model, cached by content), as
                 transcripts/<file_id>.json
    moments      each file split into moments: a talking file at its pauses (lines grouped into stretches of about
                 4-25 s), a file with no talking at its picture changes (letitedit's shot log); ids from the ledger
    photos       each photo's sharpness
    (moments)    each moment's fields (contract 1.2: shot, sound, subjects, setting, energy, b_roll_fit,
                 best_frame_s; moment_facets.py): the cheap ones on every index, the vision pass's when the file's fact
                 log is on the PC or `steps` asks for `vision`
    flags        place_revealing, licence_plate, faces, kids: no detector yet, so `unknown` (`not_checked`), said in
                 steps_skipped
    write        library/files.jsonl, moments.jsonl, photos.jsonl and changes.jsonl against the last index job of
                 the same folders

Files are read one at a time, in each stage in turn (files, then transcripts, then moments). A stage started again
after a stop, a crash or a restart carries on after the last file it finished: files, transcripts and moments keep
their place in the job's working notes after every file, and the analyses themselves are cached by file. While a
stage works through the files, status.json's `counts` (contract 1.2) says how many it has done of how many, with the
minutes of footage, and `progress` moves within the stage.

`vision` (contract 1.2) asks for the vision pass's fields; it brings `transcripts` and `moments` with it, so a file
already indexed is split into the same moments from its cached words and keeps its moment ids.

Moment ids (CONTRACT.md "Moment ids"). The ledger (<home>/library/<file_id>.json) keeps every moment ever minted for a
file's content. An id is minted once, from the file id, in and out ('m_' + a hash of them), and never recomputed,
reused or given to another moment. A re-index of an unchanged file with the same settings gives the same moments,
so the same ids. When a re-index splits a file differently (a new speech model, new settings), each new moment whose
in and out are both within MATCH_S of a current moment keeps that id (its in and out are updated); every other new
moment gets a new id; a current moment left with no match is retired, with replaced_by naming the new moments that
overlap it and by how many seconds. A retired moment stays in moments.jsonl for ever.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import letitedit.studio.files as files
import letitedit.studio.state as state

VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.3gp'}
AUDIO = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus'}
PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tif', '.tiff'}
SKIP_DIRS = {'cache', '__pycache__'}
MATCH_S = 0.5                    # a re-split moment within this of an old one (both ends) keeps its id
PAUSE_S = 0.6                    # words further apart than this end a line
MOMENT_MIN_S, MOMENT_MAX_S = 4.0, 25.0
SETTINGS = {'pause_s': PAUSE_S, 'moment_min_s': MOMENT_MIN_S, 'moment_max_s': MOMENT_MAX_S, 'shots': [8.0, 5.0, 30.0],
            'version': 2}             # 2: the moment fields of contract 1.2
FLAGS = ('place_revealing', 'licence_plate', 'faces', 'kids')
MOMENT_FIELDS = ('shot', 'sound', 'subjects', 'setting', 'energy', 'b_roll_fit', 'best_frame_s')   # contract 1.2
NO_DETECTOR = {'value': 'unknown', 'how': 'not_checked', 'note': 'letitedit has no detector for this yet.'}
STEPS = ('files', 'transcripts', 'moments', 'photos', 'flags')     # `vision` (1.2) runs only when asked


def settings_hash():
    return hashlib.sha1(json.dumps(SETTINGS, sort_keys=True).encode()).hexdigest()[:12]


def file_id(path):
    """The contract's file_id: letitedit's content key (size + a hash of the first 2 MB, footage_notes.key), as
    'f_' + 20 hex characters."""
    import letitedit.footage.footage_notes as footage_notes
    return 'f_' + hashlib.sha1(footage_notes.key(path).encode()).hexdigest()[:20]


def kind_of(path):
    s = Path(path).suffix.lower()
    return 'video' if s in VIDEO else 'audio' if s in AUDIO else 'photo' if s in PHOTO else None


def media_files(folders, only=None, recursive=True):
    """Every media file under the folders (letitedit's own side folders and hidden ones left out), sorted."""
    only = {os.path.normcase(os.path.abspath(p)) for p in only} if only else None
    found = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        walker = os.walk(folder) if recursive else [(str(folder), [], [p.name for p in folder.iterdir() if p.is_file()])]
        for root, dirs, names in walker:
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not d.endswith('.letitedit')
                             and d.lower() not in SKIP_DIRS)
            for name in sorted(names):
                p = Path(root) / name
                if kind_of(p) and not name.startswith('.') and (only is None or os.path.normcase(str(p)) in only):
                    found.append(p)
    return sorted(set(found), key=lambda p: str(p).lower())


# ------------------------------------------------------------------ the ledger

def ledger_dir(home):
    return Path(home) / 'library'


def read_ledger(home, fid):
    return files.read_json(ledger_dir(home) / f'{fid}.json') or {'file_id': fid, 'moments': []}


def write_ledger(home, fid, ledger):
    ledger_dir(home).mkdir(parents=True, exist_ok=True)
    files.write_json(ledger_dir(home) / f'{fid}.json', ledger)


def _mint(fid, a, b, taken):
    n = 0
    while True:
        mid = 'm_' + hashlib.sha1(f'{fid}|{a:.2f}|{b:.2f}|{n}'.encode()).hexdigest()[:20]
        if mid not in taken:
            return mid
        n += 1


def assign_ids(ledger, spans, when):
    """The ledger brought up to date with this index's moments of the file. spans: [{in, out, ...fields}] in order.
    Returns (ledger, added ids, retired ids). Rules: module doc, 'Moment ids'."""
    fid = ledger['file_id']
    taken = {m['moment_id'] for m in ledger['moments']}
    current = [m for m in ledger['moments'] if m.get('state', 'current') == 'current']
    used, added, kept = set(), [], []
    for s in spans:
        match = next((m for m in current if m['moment_id'] not in used
                      and abs(m['in'] - s['in']) <= MATCH_S and abs(m['out'] - s['out']) <= MATCH_S), None)
        if match:
            used.add(match['moment_id'])
            match.update({k: v for k, v in s.items()})
            match['state'] = 'current'
            kept.append(match)
        else:
            mid = _mint(fid, s['in'], s['out'], taken)
            taken.add(mid)
            new = {'moment_id': mid, 'file_id': fid, **s, 'state': 'current', 'first_indexed': when}
            ledger['moments'].append(new)
            added.append(mid)
            kept.append(new)
    retired = []
    for m in current:
        if m['moment_id'] in used:
            continue
        overlaps = []
        for k in kept:
            o = min(m['out'], k['out']) - max(m['in'], k['in'])
            if o > 0:
                overlaps.append({'moment_id': k['moment_id'], 'overlap_s': round(o, 2)})
        m['state'] = 'retired'
        m['replaced_by'] = overlaps
        m['retired_at'] = when
        retired.append(m['moment_id'])
    return ledger, added, retired


# ------------------------------------------------------------------ splitting a file into moments

def word_lines(words, pause=PAUSE_S):
    lines, cur = [], []
    for w in words:
        if cur and w['s'] - cur[-1]['e'] > pause:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [{'in': ln[0]['s'], 'out': ln[-1]['e'], 'words': ' '.join(str(w['w']).strip() for w in ln)} for ln in lines]


def talk_moments(words, duration):
    """Lines grouped into moments of MOMENT_MIN_S to MOMENT_MAX_S, cut at the longest pauses first."""
    lines = word_lines(words)
    out, cur = [], []
    for ln in lines:
        if cur and (ln['out'] - cur[0]['in'] > MOMENT_MAX_S or
                    (cur[-1]['out'] - cur[0]['in'] >= MOMENT_MIN_S and ln['in'] - cur[-1]['out'] > 1.2)):
            out.append(cur)
            cur = []
        cur.append(ln)
    if cur:
        if out and cur[-1]['out'] - cur[0]['in'] < MOMENT_MIN_S and cur[-1]['out'] - out[-1][0]['in'] <= MOMENT_MAX_S:
            out[-1] += cur
        else:
            out.append(cur)
    moments = []
    for group in out:
        a = max(0.0, group[0]['in'] - 0.15)
        b = min(duration or group[-1]['out'] + 0.3, group[-1]['out'] + 0.3)
        text = ' '.join(g['words'] for g in group)
        moments.append({'in': round(a, 2), 'out': round(b, 2), 'words': text,
                        'what': 'Talking: "' + (text[:90] + ('...' if len(text) > 90 else '')) + '"'})
    return moments


def shot_moments(path, duration):
    """A file with no talking: its picture's own stretches (letitedit's shot log: cuts, long shots split at 8 s,
    short ones merged), read under the PC lock."""
    import letitedit.core.render_lock as render_lock
    import letitedit.footage.shot_log as shot_log
    a, b, c = SETTINGS['shots']
    with render_lock.render_slot(f'index: the shots of {Path(path).name}'):
        spans = shot_log.segments(str(path), max_s=a, merge_below=b, merge_max_s=c)
    out = []
    for s, e in spans or [(0.0, duration or 0.0)]:
        if e - s <= 0.05:
            continue
        out.append({'in': round(float(s), 2), 'out': round(float(e), 2),
                    'what': f'Picture: a {e - s:.1f} s stretch with no talking'})
    return out


def photo_sharpness(path):
    """0-1: how much fine detail the photo holds (edge strength at a fixed size), or None when it can't be read."""
    try:
        from PIL import Image, ImageFilter, ImageStat
        with Image.open(path) as im:
            g = im.convert('L')
            g.thumbnail((1024, 1024))
            v = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).var[0]
        return round(min(1.0, (v ** 0.5) / 40.0), 3)
    except Exception:  # noqa: BLE001 - HEIC and damaged pictures: unknown
        return None


# ------------------------------------------------------------------ the stages

def _work(ctx):
    """The index's working notes between stages: in core/jobs.py's own folder for this job, never the caller's."""
    return Path(ctx.dir) / 'index-work.json'


def _load(ctx):
    return files.read_json(_work(ctx)) or {}


def _save(ctx, work):
    _work(ctx).parent.mkdir(parents=True, exist_ok=True)
    files.write_json(_work(ctx), work)


def _skip(work, step, why):
    """A steps_skipped entry, once per step (a stage run again after a stop says it once)."""
    work['skipped'] = [x for x in work.get('skipped') or [] if x.get('step') != step] + [{'step': step, 'why': why}]


def _steps(job):
    asked = (job.get('inputs') or {}).get('steps')
    steps = set(asked) if asked else set(STEPS)
    if 'vision' in steps:                    # the vision fields belong to moments, split from the words as always
        steps |= {'transcripts', 'moments'}
    return steps


_REPORTED = {}
REPORT_EVERY_S = 1.0


def _counts(job_dir, job, stage, done, total, min_done=None, min_total=None, force=False):
    """status.json's `counts` while a stage works through the files (contract 1.2), and `progress` within the
    stage. Written at most once a second, and always at a stage's end (force)."""
    key = str(job_dir)
    now = time.monotonic()
    if not force and now - _REPORTED.get(key, -REPORT_EVERY_S) < REPORT_EVERY_S:
        return
    _REPORTED[key] = now
    c = {'stage': stage, 'files_done': int(done), 'files_total': int(total)}
    if min_total is not None:
        c['footage_min_done'] = round(float(min_done or 0) / 60, 1)
        c['footage_min_total'] = round(float(min_total) / 60, 1)
    change = {'counts': c}
    try:
        st = state.read_status(job_dir)
        i, n = st.get('stage_index'), st.get('stages_total')
        if isinstance(i, int) and n and total and st.get('stage') == stage:
            change['progress'] = round((i + min(1.0, done / total)) / n, 4)
        state.write_status(job_dir, job, **change)
    except OSError:
        pass                                 # the counts are a courtesy: never a reason to stop the library


def _seconds(recs):
    return sum(float(r.get('duration_s') or 0) for r in recs)


def _vision_key(job):
    return 'vision' in _steps(job)


def stage_files(ctx, job_dir, job, attempt, check=lambda: None):
    """Every media file, grouped by content: probe, recorded time, camera, HDR, place."""
    import letitedit.server.core_tools as core_tools
    import letitedit.studio.delivery as delivery
    inp = job.get('inputs') or {}
    folders = [str(Path(f)) for f in inp.get('folders') or []]
    missing = [f for f in folders if not Path(f).is_dir()]
    if missing:
        raise state.StudioError('source_missing', 'A folder to index is not there (moved, renamed, or on a drive that '
                                'is not connected): ' + '; '.join(missing), stage='files')
    paths = media_files(folders, inp.get('files'), inp.get('recursive', True))
    part = _load(ctx).get('files_partial') or {}         # a stage started again carries on after its last file
    by_id, unreadable, seen = dict(part.get('by_id') or {}), list(part.get('unreadable') or []), set(part.get('seen')
                                                                                                    or [])
    for n, p in enumerate(paths):
        check()
        if str(p) in seen:
            continue
        _one_file(p, by_id, unreadable, core_tools, delivery)
        seen.add(str(p))
        _save(ctx, {'files_partial': {'by_id': by_id, 'unreadable': unreadable, 'seen': sorted(seen)}})
        _counts(job_dir, job, 'files', n + 1, len(paths))
    _counts(job_dir, job, 'files', len(paths), len(paths), force=True)
    work = {'files': list(by_id.values()), 'unreadable': unreadable, 'skipped': []}
    _save(ctx, work)
    return None


def _one_file(p, by_id, unreadable, core_tools, delivery):
    """One media file into by_id (grouped by content) or unreadable: its first 2 MB for the content id, its
    container's own description (ffprobe), its recorded time, camera and GPS."""
    try:
        fid = file_id(p)
    except OSError as e:
        unreadable.append({'path': str(p), 'why': f'It could not be read: {e.strerror or e}.'})
        return
    if fid in by_id:
        by_id[fid]['paths'].append(str(p))
        return
    kind = kind_of(p)
    rec = {'file_id': fid, 'paths': [str(p)], 'kind': kind, 'bytes': p.stat().st_size, 'duration_s': None,
           'recorded_at': None, 'camera': None, 'place': None, 'analysed': settings_hash()}
    info = delivery.probe(p)
    if kind in ('video', 'audio') and not (info and info.get('duration_s')):
        unreadable.append({'path': str(p), 'why': 'Its picture or sound could not be read (damaged, or a format '
                                                  'letitedit does not read).'})
        return
    if info:
        if kind != 'photo':
            rec['duration_s'] = info.get('duration_s')
        for k in ('width', 'height', 'fps'):
            if info.get(k):
                rec[k] = int(info[k]) if k != 'fps' else round(float(info[k]), 3)
        if kind == 'video':
            rec['hdr'] = info.get('hdr') or 'unknown'
    try:
        cinfo = core_tools.probe(p)
        start = core_tools.rec_start(cinfo)
        rec['recorded_at'] = start.isoformat() if start is not None else None
        rec['camera'] = cinfo.get('camera') or None
    except Exception:  # noqa: BLE001 - the times and camera are extra
        pass
    try:
        import letitedit.footage.geo as geo
        got = geo.place(str(p))
        rec['place'] = (got or {}).get('text') or None
    except Exception:  # noqa: BLE001 - the place is extra
        pass
    by_id[fid] = rec


def stage_transcripts(ctx, job_dir, job, attempt, check=lambda: None):
    """The words of each video or sound file with talking, as transcripts/<file_id>.json."""
    work = _load(ctx)
    if 'transcripts' not in _steps(job):
        _skip(work, 'transcripts', 'Not asked for (steps).')
        _save(ctx, work)
        return None
    import letitedit.footage.speech as speech
    import letitedit.sound.music as music
    out = Path(job_dir) / 'transcripts'
    todo = [r for r in work['files'] if r['kind'] in ('video', 'audio')]
    done = set(work.get('transcripts_done') or [])      # a stage started again carries on after its last file
    total_s = _seconds(todo)
    for rec in todo:
        check()
        if rec['file_id'] in done:
            continue
        p = rec['paths'][0]
        try:
            talking = bool(music.voice_times(p))
            words = [{'w': w['w'], 's': round(w['s'], 3), 'e': round(w['e'], 3), 'p': round(w.get('p', 1.0), 3)}
                     for w in speech.words(p)] if talking else []
        except Exception as e:  # noqa: BLE001 - one file's words never stop the library
            rec['talking'] = False
            work.setdefault('notes', []).append({'path': p, 'why': f'Its words could not be read: {str(e)[:200]}'})
            words = None
        if words is not None:
            rec['talking'] = bool(words)
            if words:
                out.mkdir(parents=True, exist_ok=True)
                files.write_json(out / f"{rec['file_id']}.json", {'file_id': rec['file_id'], 'words': words})
                rec['transcript'] = f"transcripts/{rec['file_id']}.json"
        done.add(rec['file_id'])
        work['transcripts_done'] = sorted(done)
        _save(ctx, work)
        finished = [r for r in todo if r['file_id'] in done]
        _counts(job_dir, job, 'transcripts', len(finished), len(todo), _seconds(finished), total_s)
    _counts(job_dir, job, 'transcripts', len(todo), len(todo), total_s, total_s, force=True)
    _save(ctx, work)
    return None


def stage_moments(ctx, job_dir, job, attempt, check=lambda: None):
    """Each video or sound file's moments, their ids from the ledger (module doc)."""
    import letitedit.studio.delivery as delivery
    import letitedit.studio.moment_facets as moment_facets
    import letitedit.studio.service as service
    work = _load(ctx)
    if 'moments' not in _steps(job):
        _skip(work, 'moments', 'Not asked for (steps).')
        _save(ctx, work)
        return None
    home = service.home()
    changed_only = (job.get('inputs') or {}).get('changed_only', True)
    # a stage started again after a stop or a crash carries on after the files it finished (saved after each one)
    progress = work.get('moment_progress') or {'done': [], 'counts': {'analysed': 0, 'skipped_unchanged': 0},
                                               'log': [], 'no_vision': 0, 'when': files.now_iso()}
    when = progress['when']
    counts, log = progress['counts'], progress['log']
    vision = _vision_key(job)
    todo = [r for r in work['files'] if r['kind'] in ('video', 'audio')]
    total_s = _seconds(todo)

    def report(force=False):
        finished = [r for r in todo if r['file_id'] in progress['done']]
        _counts(job_dir, job, 'moments', len(finished), len(todo), _seconds(finished), total_s, force=force)

    for rec in work['files']:
        check()
        if rec['kind'] not in ('video', 'audio') or rec['file_id'] in progress['done']:
            continue
        ledger = read_ledger(home, rec['file_id'])
        if (changed_only and ledger.get('analysed') == rec['analysed'] and ledger['moments']
                and (not vision or ledger.get('vision'))):
            counts['skipped_unchanged'] += 1
            progress['no_vision'] += rec['kind'] == 'video' and not ledger.get('vision')
            progress['done'].append(rec['file_id'])
            work['moment_progress'] = progress
            _save(ctx, work)
            report()
            continue
        words = None
        if rec.get('transcript'):
            words = (files.read_json(Path(job_dir) / rec['transcript']) or {}).get('words') or []
            spans = talk_moments(words, rec.get('duration_s'))
        elif rec['kind'] == 'video':
            spans = shot_moments(rec['paths'][0], rec.get('duration_s'))
        else:
            spans = [{'in': 0.0, 'out': round(rec.get('duration_s') or 0.0, 2), 'what': 'Sound with no talking'}]
        ff = moment_facets.file_facts(rec['paths'][0], rec['kind'], delivery.probe(rec['paths'][0]), vision)
        for sp in spans:
            check()
            sp.update(moment_facets.for_moment(ff, sp['in'], sp['out'], words))
        has_vision = bool((ff.get('facts') or {}).get('stretches'))
        progress['no_vision'] += rec['kind'] == 'video' and not has_vision
        check()                                        # a cancel here leaves this file's ledger as it was
        ledger, added, retired = assign_ids(ledger, spans, when)
        ledger['analysed'] = rec['analysed']
        ledger['paths'] = rec['paths']
        ledger['vision'] = has_vision
        write_ledger(home, rec['file_id'], ledger)
        counts['analysed'] += 1
        log.append({'file_id': rec['file_id'], 'added': added, 'retired': retired})
        progress['done'].append(rec['file_id'])
        work['moment_progress'] = progress
        _save(ctx, work)
        report()
    report(force=True)
    work['moment_counts'], work['moment_log'] = counts, log
    if progress['no_vision']:
        try:
            import letitedit.core.hardware as hardware
            no_card = hardware.vision_unavailable()
        except Exception:  # noqa: BLE001
            no_card = None
        _skip(work, 'vision', f"{progress['no_vision']} video file(s) have no vision pass yet, so their moments have no "
                              'subjects or setting, and framing wide, detail and screen and the moving-vehicle '
                              'camera only where a face or the motion tells them. '
                              + (f'This PC has no vision pass: {no_card}' if no_card else
                                 "Ask for steps: ['vision'] (about 6 s of graphics card time per 8 s of video)."))
    _skip(work, 'moment_fields', "Not told yet: the drone camera and music_source (whether music is the scene's own "
                                 'or added), so they are absent.')
    _save(ctx, work)
    return None


def stage_photos(ctx, job_dir, job, attempt, check=lambda: None):
    work = _load(ctx)
    photos = []
    for rec in work['files']:
        check()
        if rec['kind'] != 'photo':
            continue
        sharp = photo_sharpness(rec['paths'][0]) if 'photos' in _steps(job) else None
        photos.append({'file_id': rec['file_id'], 'sharpness': sharp, 'faces': None, 'kids': dict(NO_DETECTOR),
                       'subjects': [], 'place_revealing': dict(NO_DETECTOR), 'licence_plate': dict(NO_DETECTOR)})
    work['photos'] = photos
    if 'photos' not in _steps(job):
        _skip(work, 'photos', 'Not asked for (steps).')
    _save(ctx, work)
    return None


def stage_flags(ctx, job_dir, job, attempt, check=lambda: None):
    work = _load(ctx)
    _skip(work, 'flags', 'letitedit has no detector yet for places, licence plates, faces or children, so every flag '
                         "is unknown (not_checked). A Short's rules are checked by its review.")
    _save(ctx, work)
    return None


def _previous_job(job, home):
    """The newest finished index job of the same folders (since_job when given), as (job_id, its job folder)."""
    want = sorted(os.path.normcase(str(Path(f))) for f in (job.get('inputs') or {}).get('folders') or [])
    asked = (job.get('inputs') or {}).get('since_job')
    best = None
    for f in sorted((Path(home) / 'registry').glob('*.json')):
        entry = files.read_json(f) or {}
        if entry.get('job_id') == job.get('job_id') or not entry.get('job_dir'):
            continue
        if asked and entry.get('job_id') != asked:
            continue
        folder = Path(entry['job_dir'])
        other = files.read_json(folder / 'job.json') or {}
        r = files.read_json(folder / 'result.json') or {}
        if other.get('kind') != 'index' or r.get('state') != 'done':
            continue
        if not asked and sorted(os.path.normcase(str(Path(x))) for x in (other.get('inputs') or {}).get('folders') or []) != want:
            continue
        if best is None or (r.get('finished') or '') > best[2]:
            best = (entry['job_id'], folder, r.get('finished') or '')
    return (best[0], best[1]) if best else (None, None)


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def _read_jsonl(path):
    out = []
    try:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                out.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return out


def stage_write(ctx, job_dir, job, attempt, check=lambda: None):
    """The snapshot (files, moments current and retired, photos) and its changes; returns the kind's output."""
    import letitedit.studio.service as service
    work = _load(ctx)
    home = service.home()
    lib = Path(job_dir) / 'library'
    file_rows = []
    for rec in work['files']:
        row = {k: v for k, v in rec.items() if v is not None or k in ('duration_s', 'recorded_at', 'camera', 'place')}
        if rec['kind'] in ('video', 'audio'):
            row.setdefault('talking', False)
        file_rows.append(row)
    moments = []
    for rec in work['files']:
        if rec['kind'] not in ('video', 'audio'):
            continue
        for m in read_ledger(home, rec['file_id'])['moments']:
            row = {k: m[k] for k in ('moment_id', 'file_id', 'in', 'out', 'state', 'what') if k in m}
            for k in ('replaced_by', 'words', 'first_indexed') + MOMENT_FIELDS:
                if m.get(k):
                    row[k] = m[k]
            row['flags'] = {f: dict(NO_DETECTOR) for f in FLAGS}
            moments.append(row)
    _jsonl(lib / 'files.jsonl', file_rows)
    _jsonl(lib / 'moments.jsonl', moments)
    _jsonl(lib / 'photos.jsonl', work.get('photos') or [])
    since, before = _previous_job(job, home)
    changes = []
    if before is not None:
        old_files = {r['file_id']: r for r in _read_jsonl(before / 'library' / 'files.jsonl')}
        old_moments = {r['moment_id']: r for r in _read_jsonl(before / 'library' / 'moments.jsonl')}
        old_paths = {p: r['file_id'] for r in old_files.values() for p in r.get('paths') or []}
        new_ids = {r['file_id'] for r in file_rows}
        for r in file_rows:
            if r['file_id'] in old_files:
                continue
            was = {old_paths[p] for p in r['paths'] if p in old_paths}
            changes.append({'what': 'file', 'id': r['file_id'], 'change': 'changed' if was else 'added',
                            **({'was': sorted(was)} if was else {})})
        for fid in old_files:
            if fid not in new_ids:
                changes.append({'what': 'file', 'id': fid, 'change': 'removed'})
        for m in moments:
            old = old_moments.get(m['moment_id'])
            if old is None and m['state'] == 'current':
                changes.append({'what': 'moment', 'id': m['moment_id'], 'change': 'added'})
            elif old and old.get('state') == 'current' and m['state'] == 'retired':
                changes.append({'what': 'moment', 'id': m['moment_id'], 'change': 'retired'})
            elif old and (old.get('in'), old.get('out')) != (m['in'], m['out']):
                changes.append({'what': 'moment', 'id': m['moment_id'], 'change': 'changed'})
    else:
        changes = ([{'what': 'file', 'id': r['file_id'], 'change': 'added'} for r in file_rows]
                   + [{'what': 'moment', 'id': m['moment_id'], 'change': 'added'} for m in moments
                      if m['state'] == 'current'])
    _jsonl(lib / 'changes.jsonl', changes)
    mc = work.get('moment_counts') or {'analysed': 0, 'skipped_unchanged': 0}
    analysed = mc['analysed'] + sum(1 for r in work['files'] if r['kind'] == 'photo')
    output = {'files': 'library/files.jsonl', 'moments': 'library/moments.jsonl', 'photos': 'library/photos.jsonl',
              'changes': 'library/changes.jsonl', 'since_job': since,
              'counts': {'files': len(file_rows), 'analysed': analysed,
                         'skipped_unchanged': mc['skipped_unchanged'], 'unreadable': len(work.get('unreadable') or []),
                         'moments_current': sum(1 for m in moments if m['state'] == 'current'),
                         'moments_retired': sum(1 for m in moments if m['state'] == 'retired'),
                         'photos': len(work.get('photos') or [])},
              'unreadable': work.get('unreadable') or [],
              'steps_skipped': work.get('skipped') or []}
    return {'__result__': True, 'output': output, 'outputs': outputs(job_dir)}


STAGES = [('files', stage_files), ('transcripts', stage_transcripts), ('moments', stage_moments),
          ('photos', stage_photos), ('flags', stage_flags), ('write', stage_write)]


def outputs(job_dir):
    """The index's outputs entries (role index), for result.json."""
    return [files.output_entry(job_dir, f'library/{n}.jsonl', 'index') for n in ('files', 'moments', 'photos', 'changes')
            if (Path(job_dir) / 'library' / f'{n}.jsonl').is_file()]
