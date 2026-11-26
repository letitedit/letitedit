r"""Footage archive: every clip letitedit has already indexed, in one local SQLite database, searchable by meaning.

    update(files=None, span_words=40, pause_s=1.5, device='cpu', batch=64, progress=None, check=None)
        reads the caches (transcripts, footage log, footage scan probe, GPS) and adds new or changed clips
    search(query, count=12, kind='any', folder=None, exclude_folder=None, date_from=None, date_to=None, hours=None,
           place=None, camera=None, talking=None, words_weight=0.15, min_score=None, min_gap_s=5.0, per_file=3,
           prefer=None, frame_height=320, sheet_per_row=6, sheet=True, out_dir=None, device='cpu')
    status(roots=None, max_depth=4, time_limit_s=60.0, list_limit=50)
    not_indexed(roots=None, ...)   media files under the roots that are not in the archive

What is read (never computed here): speech transcripts (cache\transcripts, speech.py), footage log entries
(cache\shot_log, shot_log.py), the footage scan's probe (cache\probe3, core_tools.probe: length, recording time,
camera, picture size) and GPS (cache\geo\files, geo.py; place = nearest GeoNames place). A file none of these caches
know is not in the archive (indexing is the 'index' job's work); status() lists such files under the roots.

Database: <cache>\archive\archive.sqlite. Tables: files (one row per path: content key, folder, length, recording
time, camera, place), contents (one row per file content: copies of a clip share it), spans (per content: 'speech'
spans = transcript words split at pauses over pause_s or at span_words words; 'log' spans = one footage log entry
each, its action/things/place/framing/text/quality), each span with a 384-value text embedding of
BAAI/bge-small-en-v1.5 (MIT, C:\LetItEdit\models\bge-small-en-v1.5). Content key = file size + SHA-1 of the first
2 MB (the key perception.py and geo.py use), so copies of a clip in several folders are one content.

Incremental: a file whose size and modification time are unchanged and whose content's sources (transcript and
footage log cache files, span settings, model) are unchanged is skipped; every content is committed on its own, so
an interrupted update continues where it stopped.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import atexit
import base64
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
ARCHIVE_DIR = Path(os.environ.get('LETITEDIT_ARCHIVE', str(CACHE / 'archive')))
MODELS_PY = os.environ.get('LETITEDIT_MODELS_PYTHON', (_SAI_ROOT + '\\envs\\models\\Scripts\\python.exe'))
MODEL_DIR = Path(os.environ.get('LETITEDIT_ARCHIVE_MODEL', (_SAI_ROOT + '\\models\\bge-small-en-v1.5')))
MODEL = 'BAAI/bge-small-en-v1.5'
QUERY_PREFIX = 'Represent this sentence for searching relevant passages: '
WORKER = HERE / 'embed_worker.py'
IDLE_S = float(os.environ.get('LETITEDIT_ARCHIVE_IDLE', 600))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SCHEMA = 1
MEDIA = {'video', 'audio'}
VIDEO_EXT = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf', '.3gp'}
AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aiff', '.aif'}

BUILD_DEFAULTS = {
    'span_words': 40,     # a speech span ends after this many words
    'pause_s': 1.5,       # ... or at a pause longer than this (seconds)
    'device': 'cpu',      # 'cpu' or 'cuda' (cuda waits for the PC's model GPU lock)
    'batch': 64,          # texts per embedding batch
}
SEARCH_DEFAULTS = {
    'count': 12,          # hits returned
    'kind': 'any',        # 'speech', 'log' or 'any'
    'words_weight': 0.15,  # score = meaning + words_weight * share of the query's words found in the span's text
    'min_score': None,    # hits under this score are left out (None: no limit)
    'min_words': 3,       # speech spans with fewer words are left out
    'min_gap_s': 5.0,     # hits in one clip (content) at least this far apart (start to start)
    'per_file': 3,        # at most this many hits per clip (content); 0 = no limit
    'copies': 'recording',  # 'recording': files of one recording are one clip (same content, or same file name
                          # and same recording time tag, or same file name and sizes within same_size_frac);
                          # 'content': only files with the same content (size + first 2 MB) are one clip
    'same_size_frac': 0.001,
    'frame_height': 320,  # frame images and sheet tiles, px
    'sheet_per_row': 6,
    'sheet': True,
    'device': 'cpu',
}


def _setting_folders(key):
    """The folders settings.json names under key (one folder or a list); none when it names none."""
    from letitedit.core import hardware
    value = hardware.settings().get(key) or []
    return [str(v) for v in ([value] if isinstance(value, str) else value) if v]


def default_prefer():
    """Folders whose copy of a clip a search prefers when the call names none: settings.json 'archive_prefer'."""
    return _setting_folders('archive_prefer')


def default_roots():
    """Folders not_indexed() looks in when the call names none: settings.json 'archive_roots'."""
    return _setting_folders('archive_roots')


STATUS_DEFAULTS = {'max_depth': 4, 'time_limit_s': 60.0, 'list_limit': 50}
STOP = set('a an the and or of to in on at for with by from is are was were be it this that these those i you he '
           'she we they my your his her our their me him us them as do does did so if then than there here what '
           'when where who how into out up down over just'.split())
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def _db_path():
    return ARCHIVE_DIR / 'archive.sqlite'


def _norm_path(p):
    return os.path.normcase(os.path.normpath(str(p)))


def _tokens(text):
    return _TOKEN.findall(str(text).lower().replace('\u2019', "'"))


# ------------------------------------------------------------------ database

def connect(path=None):
    p = Path(path) if path else _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript("""
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY, npath TEXT, content TEXT, size INTEGER, mtime_ns INTEGER, folder TEXT, name TEXT,
        kind TEXT, duration REAL, recorded TEXT, rec_local TEXT, rec_utc REAL, utc_offset_min INTEGER, camera TEXT,
        place TEXT, lat REAL, lon REAL, width INTEGER, height INTEGER, scanned INTEGER, present INTEGER,
        updated REAL);
    CREATE INDEX IF NOT EXISTS files_content ON files(content);
    CREATE TABLE IF NOT EXISTS contents (
        content TEXT PRIMARY KEY, duration REAL, words INTEGER, log_entries INTEGER, transcript_src TEXT,
        log_src TEXT, sig TEXT, updated REAL);
    CREATE TABLE IF NOT EXISTS spans (
        id INTEGER PRIMARY KEY, content TEXT, kind TEXT, start REAL, "end" REAL, text TEXT, detail TEXT, emb BLOB);
    CREATE INDEX IF NOT EXISTS spans_content ON spans(content);
    CREATE TABLE IF NOT EXISTS sources (
        src TEXT PRIMARY KEY, type TEXT, mtime_ns INTEGER, size INTEGER, path TEXT, npath TEXT);
    CREATE INDEX IF NOT EXISTS sources_npath ON sources(npath);
    """)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
    con.execute("INSERT OR IGNORE INTO meta VALUES ('model', ?)", (MODEL,))
    con.commit()
    return con


def _meta(con, key, value=None):
    if value is None:
        r = con.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return r['value'] if r else None
    con.execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (key, str(value)))
    return value


# ------------------------------------------------------------------ embedding worker

class _Embedder:
    def __init__(self):
        self.proc = None
        self.device = None
        self.lock = threading.Lock()
        self.next = 1
        self.hello = None

    def _start(self, device):
        if self.proc is not None and self.proc.poll() is None and self.device == device:
            return
        self.stop()
        import letitedit.core.first_use as first_use                            # first use: the models environment + bge-small (128 MB)
        first_use.need_for_python(MODELS_PY, ['bge-small-en-v1.5'] if 'LETITEDIT_ARCHIVE_MODEL' not in os.environ
                                  else [], feature='archive search (letitedit_archive)')
        if not os.path.exists(MODELS_PY):
            raise RuntimeError(f'model Python not found: {MODELS_PY}')
        if not (MODEL_DIR / 'model.safetensors').exists():
            raise RuntimeError(f'embedding model not found: {MODEL_DIR}')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1', TRANSFORMERS_VERBOSITY='error', TQDM_DISABLE='1')
        env.pop('PYTHONPATH', None)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVE_DIR / 'embed_worker.log', 'a', encoding='utf-8') as err:
            import letitedit.core.render_lock as render_lock
            self.proc = render_lock.popen_worker([MODELS_PY, '-I', str(WORKER), str(MODEL_DIR), device, str(IDLE_S)],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
                                                 encoding='utf-8', creationflags=NO_WINDOW, env=env)
        hello = json.loads(self.proc.stdout.readline() or '{}')
        if not hello.get('ready'):
            self.proc = None
            raise RuntimeError('embedding worker did not start; see ' + str(ARCHIVE_DIR / 'embed_worker.log'))
        self.device, self.hello = device, hello

    def embed(self, texts, prefix='', device='cpu', batch=64):
        if not texts:
            return np.zeros((0, 384), np.float32)
        turn = contextlib.nullcontext()
        if device == 'cuda':
            import letitedit.sound.model_tools as model_tools
            import letitedit.core.render_lock as render_lock
            turn = contextlib.ExitStack()
            turn.enter_context(render_lock.model_slot('search index (GPU)'))     # the render lock before the GPU turn
            turn.enter_context(model_tools._gpu_turn())
        with self.lock, turn:
            for attempt in (0, 1):
                self._start(device)
                rid = self.next
                self.next += 1
                try:
                    self.proc.stdin.write(json.dumps({'id': rid, 'texts': list(texts), 'prefix': prefix,
                                                      'batch': int(batch)}) + '\n')
                    self.proc.stdin.flush()
                    line = self.proc.stdout.readline()
                except OSError:
                    line = ''
                if line:
                    break
                self.proc = None          # it exited (idle) or died: start again once
            if not line:
                raise RuntimeError('embedding worker stopped; see ' + str(ARCHIVE_DIR / 'embed_worker.log'))
            rep = json.loads(line)
            if rep.get('error'):
                raise RuntimeError('embedding worker: ' + rep['error'])
            a = np.frombuffer(base64.b64decode(rep['emb']), dtype=np.float32)
            return a.reshape(len(texts), int(rep['dim']))

    def stop(self):
        p = self.proc
        self.proc = None
        if p is None:
            return
        try:
            if p.poll() is None:
                p.stdin.close()
                p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                p.kill()
        for fh in (p.stdin, p.stdout):
            with contextlib.suppress(Exception):
                fh.close()


_embedder = _Embedder()
atexit.register(_embedder.stop)


def embed(texts, query=False, device='cpu', batch=64):
    """Normalised bge-small vectors [len(texts), 384] (query=True adds the model's query instruction)."""
    return _embedder.embed(texts, QUERY_PREFIX if query else '', device=device, batch=batch)


# ------------------------------------------------------------------ cache readers

def _transcript_dir():
    return CACHE / 'transcripts'


def _shot_log_dir():
    return CACHE / 'shot_log'


def _probe_dir():
    return CACHE / 'probe3'


def _scan_sources(con):
    """Bring the sources table up to date with the cache files: {type: {npath: [src, ...]}}; parses only new or
    changed cache files."""
    known = {r['src']: r for r in con.execute('SELECT * FROM sources')}
    seen = set()
    for typ, folder, field in (('words', _transcript_dir(), 'path'), ('log', _shot_log_dir(), 'file'),
                               ('probe', _probe_dir(), 'file')):
        if not folder.is_dir():
            continue
        with os.scandir(folder) as it:
            for e in it:
                if not e.name.endswith('.json') or not e.is_file():
                    continue
                src = e.path
                seen.add(src)
                st = e.stat()
                k = known.get(src)
                if k is not None and k['mtime_ns'] == st.st_mtime_ns and k['size'] == st.st_size:
                    continue
                try:
                    with open(src, encoding='utf-8-sig') as fh:
                        p = json.load(fh).get(field)
                except (OSError, ValueError):
                    p = None
                con.execute('INSERT OR REPLACE INTO sources VALUES (?, ?, ?, ?, ?, ?)',
                            (src, typ, st.st_mtime_ns, st.st_size, p, _norm_path(p) if p else None))
    gone = [s for s in known if s not in seen]
    con.executemany('DELETE FROM sources WHERE src=?', [(s,) for s in gone])
    con.commit()
    out = {'words': {}, 'log': {}, 'probe': {}}
    for r in con.execute('SELECT src, type, path, npath, mtime_ns FROM sources WHERE path IS NOT NULL'):
        out[r['type']].setdefault(r['npath'], []).append((r['src'], r['path'], r['mtime_ns']))
    return out


def _transcript(path):
    """(words, [cache file names]) from the transcript cache only (whole-file transcript, or every cached 5-minute
    window of a long file), or (None, [])."""
    import letitedit.footage.speech as speech
    try:
        ident = speech._identity(path)
    except OSError:
        return None, []
    f = speech._cached(ident)
    if f is not None:
        try:
            return json.loads(f.read_text(encoding='utf-8-sig'))['words'], [f.name]
        except (OSError, ValueError, KeyError):
            return None, []
    wins = []
    for g in _transcript_dir().glob(f'{ident}-*.json'):
        tail = g.stem.rsplit('-', 1)[-1]
        if tail.isdigit():
            wins.append((int(tail), g))
    if not wins:
        return None, []
    ws, names = [], []
    for _, g in sorted(wins):
        try:
            ws += json.loads(g.read_text(encoding='utf-8-sig'))['words']
            names.append(g.name)
        except (OSError, ValueError, KeyError):
            pass
    ws.sort(key=lambda w: w['s'])
    return ws, names


def _probe_cached(path):
    """The footage scan's probe of the file (core_tools.probe cache) or None; never runs ffprobe."""
    import letitedit.server.core_tools as core_tools
    try:
        f = _probe_dir() / f'{core_tools._identity(path)}.json'
    except OSError:
        return None
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _place_cached(content):
    """(place text, lat, lon) from geo.py's per-content GPS cache (no file reading), or (None, None, None)."""
    try:
        import letitedit.footage.geo as geo
        f = geo.CACHE / 'files' / f'{content}-v{geo.COORD_VERSION}.json'
        if not f.exists():
            return None, None, None
        c = json.loads(f.read_text(encoding='utf-8-sig')).get('coords')
        if not c:
            return None, None, None
        text = None
        if geo.available():
            with contextlib.suppress(Exception):
                text = geo.place_text(geo.nearest(c['lat'], c['lon'], 1, 0)[0])
        return text, c['lat'], c['lon']
    except Exception:  # noqa: BLE001 - the place is extra
        return None, None, None


def _content_key(path):
    import letitedit.footage.footage_notes as footage_notes
    return footage_notes.key(path)


def _rec(info):
    """(recorded as given, local 'YYYY-MM-DD HH:MM:SS', UTC epoch, offset minutes) of a probe, or Nones."""
    import letitedit.server.core_tools as core_tools
    if not info or not info.get('created'):
        return None, None, None, None
    dt = core_tools.rec_start(info)
    if dt is None:
        return info.get('created'), None, None, None
    off = dt.utcoffset() or timedelta(0)
    return info.get('created'), dt.strftime('%Y-%m-%d %H:%M:%S'), dt.timestamp(), int(off.total_seconds() // 60)


def _kind_of(path, info):
    if info and info.get('kind'):
        return info['kind']
    ext = Path(path).suffix.lower()
    return 'video' if ext in VIDEO_EXT else 'audio' if ext in AUDIO_EXT else 'other'


# ------------------------------------------------------------------ spans

def speech_spans(ws, span_words=40, pause_s=1.5):
    """[(start, end, text, n words)] of a transcript: split at a pause longer than pause_s or after span_words."""
    out, cur = [], []
    for w in ws or []:
        if cur and (w['s'] - cur[-1]['e'] > pause_s or len(cur) >= span_words):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    spans = []
    for g in out:
        text = ' '.join(str(w['w']).strip() for w in g).strip()
        if text:
            spans.append((round(float(g[0]['s']), 3), round(float(g[-1]['e']), 3), text, len(g)))
    return spans


LOG_FIELDS = (('action', 'Action'), ('things', 'Things'), ('place', 'Place'), ('framing', 'Framing'),
              ('text', 'Text'), ('quality', 'Quality'))


def log_spans(entry):
    """[(start, end, text, fields)] of a footage log entry, one per stretch."""
    out = []
    for s in (entry or {}).get('shots', []):
        fields = {k: str(s.get(k) or '').strip() for k, _ in LOG_FIELDS if str(s.get(k) or '').strip()}
        if not fields and s.get('raw'):
            fields = {'action': str(s['raw']).strip()}
        if not fields:
            continue
        text = ' '.join(f'{label}: {fields[k]}' for k, label in LOG_FIELDS if k in fields)
        out.append((round(float(s.get('from', 0)), 3), round(float(s.get('to', 0)), 3), text, fields))
    return out


# ------------------------------------------------------------------ update

def _settings(defaults, given):
    out, defaulted = {}, []
    for k, v in defaults.items():
        if given.get(k) is None:
            out[k] = v
            defaulted.append(k)
        else:
            out[k] = given[k]
    return out, defaulted


def update(files=None, span_words=None, pause_s=None, device=None, batch=None, progress=None, check=None,
           db=None):
    """Add new or changed clips from the caches to the archive (see the module doc). files: None (everything the
    caches know) or a folder / file / list of them (only those paths; a folder is not searched below).
    progress(fraction, message) and check() (raises to stop) are optional callbacks (the job runner's)."""
    t0 = time.time()
    st, defaulted = _settings(BUILD_DEFAULTS, dict(span_words=span_words, pause_s=pause_s, device=device,
                                                   batch=batch))
    con = connect(db)
    try:
        srcs = _scan_sources(con)
        candidates = {}
        for typ in ('words', 'log', 'probe'):
            for npath, rows in srcs[typ].items():
                candidates.setdefault(npath, rows[0][1])
        if files is not None:
            want = set()
            items = [files] if isinstance(files, (str, Path)) else list(files)
            for it in items:
                p = Path(it)
                if p.is_dir():
                    want |= {_norm_path(x) for x in p.iterdir() if x.is_file()}
                else:
                    want.add(_norm_path(p))
            candidates = {k: v for k, v in candidates.items() if k in want}
        old = {r['path']: r for r in con.execute('SELECT path, size, mtime_ns, content FROM files')}
        rep = {'files_seen': len(candidates), 'files_new_or_changed': 0, 'files_missing': 0, 'contents_built': 0,
               'contents_unchanged': 0, 'spans_added': 0, 'errors': []}
        by_content = {}
        paths_of = {}
        n = len(candidates)
        for i, (npath, path) in enumerate(sorted(candidates.items())):
            if check:
                check()
            if progress and i % 50 == 0:
                progress(0.3 * i / max(1, n), f'archive: checking files {i + 1}-{min(n, i + 50)} of {n}')
            try:
                stt = os.stat(path)
            except OSError:
                if path in old:
                    con.execute('UPDATE files SET present=0 WHERE path=?', (path,))
                rep['files_missing'] += 1
                continue
            o = old.get(path)
            if o is not None and o['size'] == stt.st_size and o['mtime_ns'] == stt.st_mtime_ns and o['content']:
                content = o['content']
                con.execute('UPDATE files SET present=1 WHERE path=?', (path,))
            else:
                info = _probe_cached(path)
                kind = _kind_of(path, info)
                if kind not in MEDIA:
                    continue
                try:
                    content = _content_key(path)
                except OSError as e:
                    rep['errors'].append({'file': path, 'error': f'{type(e).__name__}: {e}'[:200]})
                    continue
                rec, rec_local, rec_utc, off = _rec(info)
                place, lat, lon = _place_cached(content)
                con.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (path, npath, content, stt.st_size, stt.st_mtime_ns, str(Path(path).parent), Path(path).name,
                             kind, (info or {}).get('duration'), rec, rec_local, rec_utc, off, (info or {}).get('camera'),
                             place, lat, lon, (info or {}).get('width'), (info or {}).get('height'),
                             1 if info else 0, 1, time.time()))
                rep['files_new_or_changed'] += 1
            by_content.setdefault(content, []).append(path)
            paths_of[npath] = path
        con.commit()
        # every copy of a content contributes its transcript and footage log (the newest of each)
        nc = len(by_content)
        for j, (content, paths) in enumerate(sorted(by_content.items())):
            if check:
                check()
            if progress:
                progress(0.3 + 0.7 * j / max(1, nc), f'archive: clip {j + 1} of {nc} ({Path(paths[0]).name})')
            try:
                tr, tr_src = None, []
                for p in paths:
                    ws, names = _transcript(p)
                    if ws is not None and (tr is None or len(ws) > len(tr)):
                        tr, tr_src = ws, names
                logs = []
                for p in paths:
                    logs += srcs['log'].get(_norm_path(p), [])
                log_src = max(logs, key=lambda r: r[2])[0] if logs else None
                sig = hashlib.sha1(json.dumps({'tr': tr_src, 'log': [log_src, max((r[2] for r in logs), default=0)],
                                               'w': st['span_words'], 'p': st['pause_s'], 'm': MODEL, 'v': SCHEMA},
                                              sort_keys=True).encode()).hexdigest()[:16]
                row = con.execute('SELECT sig FROM contents WHERE content=?', (content,)).fetchone()
                if row is not None and row['sig'] == sig:
                    rep['contents_unchanged'] += 1
                    continue
                items = []
                for a, b, text, nw in speech_spans(tr, int(st['span_words']), float(st['pause_s'])):
                    items.append(('speech', a, b, text, {'words': nw}))
                entry = None
                if log_src:
                    with contextlib.suppress(OSError, ValueError):
                        entry = json.loads(Path(log_src).read_text(encoding='utf-8-sig'))
                    for a, b, text, fields in log_spans(entry):
                        items.append(('log', a, b, text, {**fields, 'model': (entry or {}).get('model')}))
                vecs = embed([it[3] for it in items], device=st['device'], batch=int(st['batch'])) if items else None
                dur = next((con.execute('SELECT duration FROM files WHERE path=?', (p,)).fetchone()['duration']
                            for p in paths), None)
                con.execute('DELETE FROM spans WHERE content=?', (content,))
                con.executemany('INSERT INTO spans (content, kind, start, "end", text, detail, emb) VALUES (?,?,?,?,?,?,?)',
                                [(content, k, a, b, text, json.dumps(d), vecs[i].astype(np.float16).tobytes())
                                 for i, (k, a, b, text, d) in enumerate(items)])
                con.execute('INSERT OR REPLACE INTO contents VALUES (?,?,?,?,?,?,?,?)',
                            (content, dur, len(tr or []), len((entry or {}).get('shots', [])) if entry else 0,
                             json.dumps(tr_src), log_src, sig, time.time()))
                con.commit()
                rep['contents_built'] += 1
                rep['spans_added'] += len(items)
            except Exception as e:  # noqa: BLE001 - one bad clip must not stop the rest
                if type(e).__name__ == 'Cancelled':
                    raise
                con.rollback()
                rep['errors'].append({'content': content, 'file': paths[0], 'error': f'{type(e).__name__}: {e}'[:300]})
        _meta(con, 'last_update', time.strftime('%Y-%m-%d %H:%M:%S'))
        _meta(con, 'build_settings', json.dumps(st))
        con.commit()
    finally:
        con.close()
    _VEC.clear()
    rep.update(seconds=round(time.time() - t0, 1), settings=st, defaults=defaulted, model=MODEL,
               db=str(Path(db) if db else _db_path()))
    return rep


# ------------------------------------------------------------------ search

_VEC = {}


def _vectors(con, dbfile):
    """(ids array, matrix [n, 384] float32, rows by id) for every span; cached until the database changes."""
    stamp = (str(dbfile), os.path.getmtime(dbfile), _meta(con, 'last_update'))
    if _VEC.get('stamp') == stamp:
        return _VEC['ids'], _VEC['mat'], _VEC['rows']
    ids, vecs, rows = [], [], {}
    for r in con.execute('SELECT id, content, kind, start, "end", text, detail, emb FROM spans'):
        ids.append(r['id'])
        vecs.append(np.frombuffer(r['emb'], dtype=np.float16))
        rows[r['id']] = {'content': r['content'], 'kind': r['kind'], 'start': r['start'], 'end': r['end'],
                         'text': r['text'], 'detail': r['detail'],
                         'nwords': len(r['text'].split()) if r['kind'] == 'speech' else None}
    mat = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, 384), np.float32)
    _VEC.update(stamp=stamp, ids=np.array(ids), mat=mat, rows=rows)
    return _VEC['ids'], mat, rows


def _as_list(x):
    if x is None:
        return []
    return [x] if isinstance(x, (str, Path)) else list(x)


def _file_ok(f, folder, exclude, date_from, date_to, place, camera):
    np_ = f['npath'] or ''
    if folder and not any(np_.startswith(_norm_path(d).rstrip('\\') + '\\') or np_ == _norm_path(d)
                          for d in folder):
        return False
    if exclude and any(np_.startswith(_norm_path(d).rstrip('\\') + '\\') for d in exclude):
        return False
    day = (f['rec_local'] or '')[:10]
    if date_from and (not day or day < str(date_from)[:10]):
        return False
    if date_to and (not day or day > str(date_to)[:10]):
        return False
    if place and place.lower() not in (f['place'] or '').lower():
        return False
    if camera and camera.lower() not in (f['camera'] or '').lower():
        return False
    return True


_SUFFIX = re.compile(r'\s*\(\d+\)$')


def _groups(files, rule='recording', size_frac=0.001):
    """{content: clip id}. 'content': one clip per content. 'recording': contents are joined when two of their files
    have the same name (case and a ' (2)' suffix ignored) and the same recording time tag, or the same name and sizes
    within size_frac of each other. The files of a clip lend each other the recording time, camera, place and
    length a file's own caches lack (the dicts in `files` are filled in)."""
    parent = {f['content']: f['content'] for f in files}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    if rule == 'recording':
        by_name = {}
        for f in files:
            n = Path(f['name'])
            by_name.setdefault(_SUFFIX.sub('', n.stem).lower() + n.suffix.lower(), []).append(f)
        for fs in by_name.values():
            for i, a in enumerate(fs):
                for b in fs[i + 1:]:
                    same_rec = bool(a['recorded']) and a['recorded'] == b['recorded']
                    near = bool(a['size'] and b['size']) and abs(a['size'] - b['size']) <= size_frac * max(
                        a['size'], b['size'])
                    if same_rec or near:
                        ra, rb = find(a['content']), find(b['content'])
                        if ra != rb:
                            parent[rb] = ra
    gid = {c: find(c) for c in parent}
    groups = {}
    for f in files:
        groups.setdefault(gid[f['content']], []).append(f)
    keys = ('recorded', 'rec_local', 'rec_utc', 'utc_offset_min', 'camera', 'place', 'lat', 'lon', 'duration')
    for fs in groups.values():
        if len(fs) < 2:
            continue
        for k in keys:
            v = next((f[k] for f in fs if f[k] is not None), None)
            if v is not None:
                for f in fs:
                    if f[k] is None:
                        f[k] = v
    return gid


def _pick_copy(paths, prefer):
    for pref in prefer:
        pp = _norm_path(pref).rstrip('\\') + '\\'
        for p in sorted(paths, key=len):
            if _norm_path(p).startswith(pp):
                return p
    return sorted(paths, key=lambda p: (len(p), p))[0]


def _clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:04.1f}'


def search(query, count=None, kind=None, folder=None, exclude_folder=None, date_from=None, date_to=None, hours=None,
           place=None, camera=None, talking=None, words_weight=None, min_score=None, min_gap_s=None, per_file=None,
           prefer=None, frame_height=None, sheet_per_row=None, sheet=None, out_dir=None, device=None,
           copies=None, same_size_frac=None, min_words=None, db=None):
    """Spans of the whole archive by meaning plus filters. See SEARCH_DEFAULTS and the tool text."""
    t0 = time.time()
    if not query or not str(query).strip():
        raise ValueError('give a query (text)')
    st, defaulted = _settings(SEARCH_DEFAULTS, dict(count=count, kind=kind, words_weight=words_weight,
                                                    min_score=min_score, min_gap_s=min_gap_s, per_file=per_file,
                                                    frame_height=frame_height, copies=copies,
                                                    same_size_frac=same_size_frac, min_words=min_words,
                                                    sheet_per_row=sheet_per_row, sheet=sheet, device=device))
    prefer_l = _as_list(prefer) if prefer is not None else default_prefer()
    if prefer is None:
        defaulted.append('prefer')
    if st['copies'] not in ('recording', 'content'):
        raise ValueError("copies must be 'recording' or 'content'")
    if st['kind'] not in ('any', 'speech', 'log'):
        raise ValueError("kind must be 'speech', 'log' or 'any'")
    dbfile = Path(db) if db else _db_path()
    if not dbfile.exists():
        return {'hits': [], 'text': f'No archive yet ({dbfile}): run the archive update first.', 'settings': st}
    con = connect(dbfile)
    files = [dict(r) for r in con.execute('SELECT * FROM files WHERE present=1')]
    gid = _groups(files, st['copies'], float(st['same_size_frac']))
    folder_l, excl_l = _as_list(folder), _as_list(exclude_folder)
    ok = [f for f in files if _file_ok(f, folder_l, excl_l, date_from, date_to, place, camera)]
    copies = {}
    for f in files:
        copies.setdefault(gid[f['content']], []).append(f)
    ok_contents = {}
    for f in ok:
        ok_contents.setdefault(f['content'], []).append(f)
    talk = {r['content']: (r['words'] or 0) for r in con.execute('SELECT content, words FROM contents')}
    if talking is not None:
        gtalk = {}
        for c, n in talk.items():
            if c in gid:
                gtalk[gid[c]] = gtalk.get(gid[c], 0) + n
        ok_contents = {c: v for c, v in ok_contents.items() if (gtalk.get(gid[c], 0) > 0) == bool(talking)}
    ok_groups = {}
    for c, v in ok_contents.items():
        ok_groups.setdefault(gid[c], []).extend(v)
    ids, mat, rows = _vectors(con, dbfile)
    qv = embed([str(query)], query=True, device=st['device'])[0]
    meaning = mat @ qv if len(ids) else np.zeros(0, np.float32)
    qwords = [w for w in _tokens(query) if w not in STOP] or _tokens(query)
    cands = []
    for k, sid in enumerate(ids.tolist()):
        r = rows[sid]
        if r['content'] not in ok_contents:
            continue
        if st['kind'] != 'any' and r['kind'] != st['kind']:
            continue
        if r['nwords'] is not None and r['nwords'] < int(st['min_words']):
            continue
        toks = set(_tokens(r['text']))
        found = [w for w in qwords if w in toks]
        share = len(found) / len(qwords) if qwords else 0.0
        score = float(meaning[k]) + float(st['words_weight']) * share
        if st['min_score'] is not None and score < float(st['min_score']):
            continue
        cands.append((score, float(meaning[k]), found, sid))
    # time-of-day filter: the local hour of the span's start (recording start + offset)
    if hours is not None:
        h0, h1 = float(hours[0]), float(hours[1])
        keep = []
        for c in cands:
            r = rows[c[3]]
            f = ok_groups[gid[r['content']]][0]
            if not f['rec_local']:
                continue
            t = datetime.strptime(f['rec_local'], '%Y-%m-%d %H:%M:%S') + timedelta(seconds=float(r['start']))
            h = t.hour + t.minute / 60
            if (h0 <= h <= h1) if h0 <= h1 else (h >= h0 or h <= h1):
                keep.append(c)
        cands = keep
    cands.sort(key=lambda c: -c[0])
    picked, per = [], {}
    gap = float(st['min_gap_s'])
    limit = int(st['per_file'])
    for c in cands:
        r = rows[c[3]]
        group = per.setdefault(gid[r['content']], [])
        if limit and len(group) >= limit:
            continue
        if any(abs(g['start'] - r['start']) < gap for g in group):
            continue
        group.append(r)
        picked.append(c)
        if len(picked) >= int(st['count']):
            break
    hits = []
    for score, mscore, found, sid in picked:
        r = rows[sid]
        g = gid[r['content']]
        cps = [f['path'] for f in ok_groups[g]]
        allp = [f['path'] for f in copies[g]]
        path = _pick_copy(cps, prefer_l)
        f = next(x for x in ok_groups[g] if x['path'] == path)
        detail = json.loads(r['detail'] or '{}')
        if r['kind'] == 'speech':
            why = f'said in the clip; meaning {mscore:.3f} (bge cosine)'
        else:
            why = f"footage log entry ({detail.get('model') or 'footage log'}); meaning {mscore:.3f} (bge cosine)"
        if found:
            why += f"; query words in the text: {', '.join(found)}"
        rec_at = None
        if f['rec_local']:
            rec_at = (datetime.strptime(f['rec_local'], '%Y-%m-%d %H:%M:%S')
                      + timedelta(seconds=float(r['start']))).strftime('%Y-%m-%d %H:%M:%S')
        hits.append({'file': path, 'start': r['start'], 'end': r['end'], 'kind': r['kind'],
                     'score': round(score, 4), 'meaning': round(mscore, 4), 'words_found': found,
                     'text': r['text'], 'why': why, 'detail': {k: v for k, v in detail.items() if k != 'model'},
                     'recorded_at': rec_at, 'utc_offset_min': f['utc_offset_min'], 'place': f['place'],
                     'camera': f['camera'], 'clip_length': f['duration'], 'content': r['content'], 'clip': g,
                     'copies': [p for p in allp if p != path]})
    con.close()
    out = {'hits': hits, 'query': query, 'candidates': len(cands), 'clips_searched': len(ok_groups),
           'spans_total': int(len(ids)), 'model': MODEL,
           'filters': {'folder': folder_l or None, 'exclude_folder': excl_l or None, 'date_from': date_from,
                       'date_to': date_to, 'hours': hours, 'place': place, 'camera': camera, 'talking': talking},
           'settings': {**st, 'prefer': prefer_l}, 'defaults': defaulted,
           'score': 'meaning (cosine of bge-small-en-v1.5 vectors, query with its retrieval instruction) + '
                    'words_weight x share of the query words (stop words left out) found in the span text'}
    if st['sheet'] and hits:
        out.update(_frames(hits, query, out_dir, int(st['frame_height']), int(st['sheet_per_row'])))
    out['seconds'] = round(time.time() - t0, 2)
    out['text'] = _text(out)
    return out


def _frames(hits, query, out_dir, height, per_row):
    import letitedit.footage.index_tools as index_tools
    from concurrent.futures import ThreadPoolExecutor
    od = index_tools._out_dir(out_dir, 'archive')

    def grab(kh):
        k, h = kh
        if Path(h['file']).suffix.lower() in AUDIO_EXT or not os.path.exists(h['file']):
            return None
        at = (h['start'] + h['end']) / 2
        return index_tools._grab(h['file'], at, od / f'{k + 1:02d}-{Path(h["file"]).stem}-{at:.1f}s.jpg', height)
    with ThreadPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(grab, enumerate(hits)))
    tiles = []
    for k, (h, fr) in enumerate(zip(hits, frames)):
        h['frame'] = fr
        h['frame_at'] = round((h['start'] + h['end']) / 2, 3)
        lab = [f"{k + 1}. {h['kind']}  {_clock(h['start'])}-{_clock(h['end'])}  score {h['score']:.3f}",
               f"{Path(h['file']).name}" + (f"  {h['recorded_at'][:16]}" if h['recorded_at'] else ''),
               '"' + (h['detail'].get('action') or h['text'])[:160] + '"']
        tiles.append((fr, lab))
    sheet = index_tools._sheet(tiles, od / 'archive-hits.jpg', per_row, f'archive: {query!r}')
    return {'sheet': sheet, 'out_dir': str(od)}


def _text(out):
    lines = [f"archive search {out['query']!r}: {len(out['hits'])} hits from {out['candidates']} spans "
             f"({out['clips_searched']} clips after filters, {out['spans_total']} spans in the archive)"]
    for k, h in enumerate(out['hits']):
        lines.append(f"{k + 1}. {h['file']}  {_clock(h['start'])}-{_clock(h['end'])}  {h['kind']}  "
                     f"score {h['score']:.3f}" + (f"  recorded {h['recorded_at']}" if h['recorded_at'] else '')
                     + (f"  place {h['place']}" if h['place'] else '')
                     + (f"  (+{len(h['copies'])} copies)" if h['copies'] else ''))
        txt = h['detail'].get('action') if h['kind'] == 'log' else h['text']
        lines.append(f'    "{(txt or "")[:240]}"')
        lines.append(f"    why: {h['why']}")
    if out.get('sheet'):
        lines.append(f"sheet: {out['sheet']}")
    s = out['settings']
    lines.append('settings: ' + ', '.join(f'{k}={s[k]!r}' for k in s) + f"  (defaults used: {', '.join(out['defaults'])})")
    return '\n'.join(lines)


# ------------------------------------------------------------------ status

def _walk(roots, max_depth, time_limit_s):
    """[(path, root)] media files under the roots, down to max_depth folder levels, within time_limit_s."""
    t_end = time.time() + float(time_limit_s)
    out, partial = [], False
    for root in roots:
        stack = [(Path(root), 0)]
        while stack:
            if time.time() > t_end:
                partial = True
                break
            d, depth = stack.pop()
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if depth < max_depth:
                                    stack.append((Path(e.path), depth + 1))
                            elif Path(e.name).suffix.lower() in VIDEO_EXT | AUDIO_EXT:
                                out.append((e.path, root))
                        except OSError:
                            pass
            except OSError:
                continue
    return out, partial


def not_indexed(roots=None, max_depth=None, time_limit_s=None, db=None):
    """Media files under the roots that are not in the archive, by folder: {'folders': {folder: [names]}, ...}."""
    roots = _as_list(roots) or default_roots()
    md = STATUS_DEFAULTS['max_depth'] if max_depth is None else int(max_depth)
    tl = STATUS_DEFAULTS['time_limit_s'] if time_limit_s is None else float(time_limit_s)
    dbfile = Path(db) if db else _db_path()
    known = set()
    if dbfile.exists():
        con = connect(dbfile)
        known = {r['npath'] for r in con.execute('SELECT npath FROM files WHERE present=1')}
        con.close()
    found, partial = _walk(roots, md, tl)
    folders, total_in = {}, 0
    for p, _ in found:
        if _norm_path(p) in known:
            total_in += 1
            continue
        folders.setdefault(str(Path(p).parent), []).append(Path(p).name)
    return {'roots': roots, 'media_files_found': len(found), 'in_archive': total_in,
            'not_in_archive': sum(len(v) for v in folders.values()), 'folders': folders, 'partial': partial,
            'max_depth': md, 'time_limit_s': tl}


def status(roots=None, max_depth=None, time_limit_s=None, list_limit=None, db=None):
    """Archive size (files, clips, spans), last update, and media files under the roots not in it yet."""
    dbfile = Path(db) if db else _db_path()
    ll = STATUS_DEFAULTS['list_limit'] if list_limit is None else int(list_limit)
    out = {'db': str(dbfile), 'model': MODEL}
    if dbfile.exists():
        con = connect(dbfile)
        q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
        out.update(files=q('SELECT COUNT(*) FROM files WHERE present=1'),
                   files_missing=q('SELECT COUNT(*) FROM files WHERE present=0'),
                   clips=q('SELECT COUNT(DISTINCT content) FROM files WHERE present=1'),
                   clips_with_words=q('SELECT COUNT(*) FROM contents WHERE words > 0'),
                   clips_with_log=q('SELECT COUNT(*) FROM contents WHERE log_entries > 0'),
                   spans=q('SELECT COUNT(*) FROM spans'),
                   speech_spans=q("SELECT COUNT(*) FROM spans WHERE kind='speech'"),
                   log_spans=q("SELECT COUNT(*) FROM spans WHERE kind='log'"),
                   footage_hours=round((q('SELECT SUM(duration) FROM contents') or 0) / 3600, 2),
                   last_update=_meta(con, 'last_update'),
                   build_settings=json.loads(_meta(con, 'build_settings') or '{}'),
                   db_mb=round(dbfile.stat().st_size / 1e6, 2))
        fold = {}
        for r in con.execute('SELECT folder, COUNT(*) n FROM files WHERE present=1 GROUP BY folder ORDER BY n DESC'):
            fold[r['folder']] = r['n']
        out['folders'] = fold
        con.close()
    else:
        out['files'] = 0
    ni = not_indexed(roots, max_depth, time_limit_s, db)
    out['not_indexed'] = {**ni, 'folders': {k: (v[:ll] + ([f'... +{len(v) - ll} more'] if len(v) > ll else []))
                                            for k, v in ni['folders'].items()}}
    out['list_limit'] = ll
    lines = [f"archive {out['db']}: {out.get('files', 0)} files ({out.get('clips', 0)} clips by content), "
             f"{out.get('spans', 0)} spans ({out.get('speech_spans', 0)} speech, {out.get('log_spans', 0)} footage "
             f"log), {out.get('footage_hours', 0)} h of footage; last update {out.get('last_update')}; model {MODEL}"]
    lines.append(f"under {len(ni['roots'])} roots (max_depth={ni['max_depth']}, time_limit_s={ni['time_limit_s']}"
                 f"{', walk stopped at the time limit' if ni['partial'] else ''}): {ni['media_files_found']} media "
                 f"files, {ni['in_archive']} in the archive, {ni['not_in_archive']} not")
    for k, v in sorted(ni['folders'].items()):
        lines.append(f'  not indexed: {k} ({len(v)} files)')
    out['text'] = '\n'.join(lines)
    return out


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    fn = {'update': update, 'search': search, 'status': status, 'not_indexed': not_indexed}[cmd]
    res = fn(**args)
    print(res.get('text') if isinstance(res, dict) and 'text' in res else json.dumps(res, indent=1, default=str))
