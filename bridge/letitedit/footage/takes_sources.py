"""The sources: transcripts and media loaded, with the text and time helpers.

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
from datetime import timedelta
from pathlib import Path
import letitedit.footage.speech as speech  # noqa: E402
from letitedit.footage.takes_words import (  # noqa: E402
    DISCOURSE, _content, _is_filler, tokenize
)


# ------------------------------------------------------------------ sources

class _Doc:
    """One source file (or an in-memory transcript): its words and what is known about it."""

    def __init__(self, fi, file, ws, exists, info=None):
        info = info or {}
        self.fi = fi
        self.file = file
        self.name = Path(file).name
        self.ws = ws
        self.exists = exists
        self.duration = info.get('duration')
        self.rec = info.get('rec')
        self.media = info.get('media')
        self.width, self.height = info.get('width'), info.get('height')
        self.ident = info.get('ident') or hashlib.sha1(str(file).encode()).hexdigest()[:16]
        self.names = []
        self.units = []
        self.speakers_known = any('speaker' in w for w in ws)


class _Unit:
    """A line: words ws[w0:w1] of one source, with comparison tokens."""

    def __init__(self, doc, w0, w1):
        self.doc, self.w0, self.w1 = doc, w0, w1
        self.toks, self.tw0, self.tw1 = tokenize(doc.ws, w0, w1)
        self.tname = [bool(doc.names[k]) if doc.names else False for k in self.tw0]
        self.order = 0
        self.uid = 0
        self.speaker = doc.ws[w0].get('speaker') if w0 < len(doc.ws) else None

    @property
    def start(self):
        return float(self.doc.ws[self.w0]['s'])

    @property
    def end(self):
        return float(self.doc.ws[self.w1 - 1]['e'])


def _runs(ws, split_pause_s, by_speaker):
    out, a = [], 0
    for k in range(1, len(ws) + 1):
        if (k == len(ws) or float(ws[k]['s']) - float(ws[k - 1]['e']) >= split_pause_s
                or (by_speaker and ws[k].get('speaker') != ws[k - 1].get('speaker'))):
            out.append((a, k))
            a = k
    return out


def _skip_discourse(toks, lo=0):
    i = lo
    while i < len(toks) and toks[i] in DISCOURSE:
        i += 1
    return i


def _leading_restart(u):
    """Token index where a line starts over (its opening, 2+ words with a content word, said again within 12 words;
    or 3+ words within 40), or None. Only when the first try ends at a pause of 0.5 s or more or without a full stop:
    'So the blower, so the blower wheel is...' splits; 'You can see here. You can see the shaft.' does not."""
    T = u.toks
    i0 = _skip_discourse(T)
    if len(T) - i0 < 4:
        return None
    for k in range(i0 + 2, min(len(T) - 1, i0 + 40)):
        n = 0
        while k + n < len(T) and i0 + n < k and T[k + n] == T[i0 + n]:
            n += 1
        if n < 2 or not any(_content(t) for t in T[i0:i0 + n]):
            continue
        if not (n >= 3 or k - i0 <= 12):
            continue
        cut = k
        while cut - 1 > i0 and T[cut - 1] in DISCOURSE:
            cut -= 1
        ws = u.doc.ws
        prev_w = u.tw1[cut - 1]
        next_w = u.tw0[cut]
        gap = float(ws[next_w]['s']) - float(ws[prev_w]['e'])
        stop = str(ws[prev_w]['w']).rstrip()[-1:] in '.?!'
        if gap >= 0.5 or not stop:
            return cut
    return None


def _units(doc, st):
    units = []
    for a, b in _runs(doc.ws, st['split_pause_s'], doc.speakers_known):
        pending = [(a, b)]
        while pending:
            w0, w1 = pending.pop(0)
            u = _Unit(doc, w0, w1)
            if not u.toks:
                continue
            cut = _leading_restart(u)
            if cut is not None:
                wcut = u.tw0[cut]
                while wcut > w0 and _is_filler(doc.ws[wcut - 1]['w']):
                    wcut -= 1
                if w0 < wcut < w1:
                    first = _Unit(doc, w0, wcut)
                    if first.toks:
                        units.append(first)
                    pending.insert(0, (wcut, w1))
                    continue
            units.append(u)
    return units


# ------------------------------------------------------------------ helpers for text and times

def clock(s, nd=1):
    s = max(0.0, float(s))
    m = int(s // 60)
    return f'{m}:{s - 60 * m:0{3 + nd}.{nd}f}'


def _words_text(ws, k0, k1):
    return re.sub(r'\s+', ' ', ' '.join(str(ws[k]['w']).strip() for k in range(k0, k1 + 1))).strip()


def _tok_text(unit, lo, hi):
    if hi <= lo:
        return ''
    return _words_text(unit.doc.ws, unit.tw0[lo], unit.tw1[hi - 1])


def _short_id(*parts, n=8):
    return hashlib.sha1('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:n]


class _Progress:
    def __init__(self, progress=None, check=None):
        self.fn, self.chk = progress, check

    def __call__(self, frac, msg):
        if self.fn:
            try:
                self.fn(frac, msg)
            except Exception:  # noqa: BLE001 - progress is a courtesy
                pass

    def check(self):
        if self.chk:
            self.chk()


# ------------------------------------------------------------------ loading sources

def _transcript(path):
    """(words, {'variant', 'cache', 'sha'}) from the transcript cache only, or (None, None). A long file's cached
    5-minute windows are joined (the windows not cached are reported as unchecked)."""
    try:
        ident = speech._identity(path)
    except OSError:
        return None, None
    f = speech._cached(ident)
    files = [f] if f is not None else []
    if f is None:
        wins = []
        for g in speech.CACHE.glob(f'{ident}-*.json'):
            tail = g.stem.rsplit('-', 1)[-1]
            if tail.isdigit():
                wins.append((int(tail), g))
        files = [g for _, g in sorted(wins)]
    if not files:
        return None, None
    ws, model, h = [], None, hashlib.sha1()
    for g in files:
        try:
            data = g.read_bytes()
            d = json.loads(data)
        except (OSError, ValueError):
            continue
        h.update(data)
        model = model or d.get('model')
        ws += d.get('words') or []
    ws.sort(key=lambda w: float(w['s']))
    return ws, {'variant': model, 'cache': [g.name for g in files], 'sha': h.hexdigest()[:12],
                'windows': [int(g.stem.rsplit('-', 1)[-1]) for g in files] if f is None else None}


def _archive_files(spec):
    """One copy per recording, with talking, from the archive database (read only), by archive.search's filters:
    folder, exclude_folder, date_from, date_to, place, camera; max_files (default 200), in recording order."""
    import sqlite3
    import letitedit.footage.archive as ar
    spec = dict(spec or {})
    db = Path(spec.pop('db', None) or ar._db_path())
    if not db.exists():
        raise ValueError(f'no archive database yet ({db}): letitedit_archive builds it')
    allowed = {'folder', 'exclude_folder', 'date_from', 'date_to', 'place', 'camera', 'max_files'}
    bad = sorted(set(spec) - allowed)
    if bad:
        raise ValueError(f"archive takes {', '.join(sorted(allowed))}; not {', '.join(bad)}")
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute('SELECT * FROM files WHERE present=1')]
        talk = {r['content']: (r['words'] or 0) for r in con.execute('SELECT content, words FROM contents')}
    finally:
        con.close()
    gid = ar._groups(rows, 'recording')
    folder, excl = ar._as_list(spec.get('folder')), ar._as_list(spec.get('exclude_folder'))
    ok = [f for f in rows if ar._file_ok(f, folder, excl, spec.get('date_from'), spec.get('date_to'),
                                        spec.get('place'), spec.get('camera')) and talk.get(f['content'], 0) > 0]
    by_clip = {}
    for f in ok:
        by_clip.setdefault(gid[f['content']], []).append(f)
    picked = []
    prefer = ar.default_prefer()
    for fs in by_clip.values():
        path = ar._pick_copy([f['path'] for f in fs], prefer)
        f = next(x for x in fs if x['path'] == path)
        if os.path.exists(path):
            picked.append((f.get('rec_utc') or 0, path))
    picked.sort()
    limit = int(spec.get('max_files') or 200)
    return [p for _, p in picked[:limit]], len(picked)


def _given_words(v):
    """Words given in memory ([{w|word|text, s|start, e|end, p, speaker}]) as the transcript format."""
    out = []
    for w in v or []:
        text = str(w.get('w', w.get('word', w.get('text', '')))).strip()
        s, e = w.get('s', w.get('start')), w.get('e', w.get('end'))
        if not text or s is None or e is None:
            continue
        x = {'w': text, 's': round(float(s), 3), 'e': round(float(e), 3)}
        if w.get('p') is not None:
            x['p'] = float(w['p'])
        if w.get('speaker') is not None:
            x['speaker'] = str(w['speaker'])
        out.append(x)
    out.sort(key=lambda w: w['s'])
    return out


def _media_info(path):
    import letitedit.server.core_tools as core_tools
    try:
        info = core_tools.probe(path)
    except Exception:  # noqa: BLE001
        return {}
    return {'duration': info.get('duration'), 'rec': core_tools.rec_start(info), 'media': info.get('kind'),
            'audio': info.get('audio'), 'width': info.get('width'), 'height': info.get('height')}


def _speaker_words(path, ws, mode):
    """ws with 'speaker' (and 'speaker_name') from a cached letitedit_speakers assignment; mode 'run' makes one
    (voice model) when there is none. Returns (words, how)."""
    if mode == 'off':
        return ws, 'off'
    try:
        import letitedit.footage.index_tools as it
        f = str(Path(path).resolve())
        p = it._assign_file(f)
        if not p.exists():
            if mode != 'run':
                return ws, 'none cached'
            it.speakers([f], faces=False)
        data = json.loads(p.read_text(encoding='utf-8-sig'))
        names = {k: v.get('name') for k, v in it._registry()['speakers'].items()}
        lab = it._words_with_speakers(ws, data['segments'])
    except Exception as e:  # noqa: BLE001 - speakers are an extra
        return ws, f'unavailable ({type(e).__name__}: {e})'[:200]
    out = []
    for w, x in zip(ws, lab):
        y = dict(w)
        if x.get('speaker'):
            y['speaker'] = x['speaker']
            if names.get(x['speaker']):
                y['speaker_name'] = names[x['speaker']]
        out.append(y)
    return out, 'cached' if mode != 'run' else 'run'


def _cached_flags(path):
    flags = {'sounds': False, 'motion': False, 'voice': False}
    try:
        import letitedit.footage.perception as pc
        flags['sounds'] = pc.is_cached('sounds', path)
        flags['motion'] = pc.is_cached('motion', path)
    except Exception:  # noqa: BLE001
        pass
    try:
        import letitedit.sound.music as music
        flags['voice'] = (music.CACHE / 'voice' / f'{music._identity(path)}.json').exists()
    except Exception:  # noqa: BLE001
        pass
    return flags


def _load(files, archive, words, ranges, speaker, speakers, transcribe, st, prog, warnings, unchecked):
    """[_Doc], fingerprints."""
    paths = []
    if files is not None:
        import letitedit.footage.index_tools as it
        paths += it._media_files(files)
    if archive is not None:
        got, total = _archive_files(archive)
        if total > len(got):
            warnings.append(f'archive: {total} recordings match; the first {len(got)} (max_files) were checked')
        paths += [p for p in got if p.lower() not in {x.lower() for x in paths}]
    mem = {str(k): _given_words(v) for k, v in (words or {}).items()}
    if not paths and not mem:
        raise ValueError('give files (a folder, a file or a list), archive (filters) or words ({file: [{w, s, e}]})')
    rng = None
    if ranges:
        import letitedit.footage.index_tools as it
        rng = it._ranges(ranges, paths + list(mem))
    docs, prints, seen_keys = [], [], {}
    total = len(paths) + len(mem)
    for n, p in enumerate(paths):
        prog.check()
        prog(0.02 + 0.18 * n / max(1, total), f'reading transcripts ({n + 1}/{total})')
        info = _media_info(p)
        try:
            import letitedit.footage.perception as pc
            ck = pc.content_key(p)
        except Exception:  # noqa: BLE001
            ck = None
        if ck and ck in seen_keys:
            warnings.append(f'{Path(p).name} is the same file as {Path(seen_keys[ck]).name} (same content): left out')
            continue
        if ck:
            seen_keys[ck] = p
        ws, src = _transcript(p)
        if ws is None and transcribe:
            prog(0.02 + 0.18 * n / max(1, total), f'transcribing {Path(p).name}')
            try:
                ws = speech.words(p)
                ws, src = _transcript(p)
            except Exception as e:  # noqa: BLE001
                warnings.append(f'{Path(p).name}: could not transcribe ({type(e).__name__}: {e})'[:300])
        fp = {'file': p, 'size': None, 'mtime_ns': None, 'identity': None, 'content_key': ck,
              'transcript': src, 'analysis': _cached_flags(p)}
        try:
            stt = os.stat(p)
            fp.update(size=stt.st_size, mtime_ns=stt.st_mtime_ns, identity=speech._identity(p))
        except OSError:
            pass
        prints.append(fp)
        dur = info.get('duration')
        if ws is None:
            unchecked.append({'file': p, 'ranges': [[0.0, dur]] if dur else None,
                              'reason': 'no cached transcript (transcribe=True, or letitedit_words on the file, makes one)'})
            continue
        if src and src.get('windows') is not None and dur:
            have = set(src['windows'])
            miss = [[float(w0), float(min(dur, w0 + 300))] for w0 in range(0, int(math.ceil(dur / 300.0)) * 300, 300)
                    if w0 not in have]
            if miss:
                unchecked.append({'file': p, 'ranges': miss, 'reason': 'long file: these 5-minute windows have no '
                                                                     'cached transcript'})
        if rng is not None:
            spans = rng.get(p)
            if not spans:
                continue
            ws = [w for w in ws if any(a - 1e-6 <= (float(w['s']) + float(w['e'])) / 2 <= b + 1e-6 for a, b in spans)]
        ws, how = _speaker_words(p, ws, speakers)
        fp['speakers'] = how
        if speaker:
            want = str(speaker).strip().lower()
            if not any('speaker' in w for w in ws):
                warnings.append(f'{Path(p).name}: no speaker assignment ({how}); speaker={speaker!r} could not be '
                                'applied, so the file was left out (letitedit_speakers, or speakers="run", makes one)')
                unchecked.append({'file': p, 'ranges': [[0.0, dur]] if dur else None,
                                  'reason': f'speaker filter: no speaker assignment ({how})'})
                continue
            ws = [w for w in ws if str(w.get('speaker', '')).lower() == want
                  or str(w.get('speaker_name', '')).lower() == want]
        docs.append(_Doc(len(docs), p, [dict(w) for w in ws if str(w.get('w', '')).strip()], True,
                         {**info, 'ident': fp.get('identity')}))
    for name, ws in mem.items():
        exists = os.path.exists(name)
        info = _media_info(name) if exists else {}
        ws = [dict(w) for w in (ws or []) if str(w.get('w', '')).strip()]
        if rng is not None and rng.get(name):
            spans = rng[name]
            ws = [w for w in ws if any(a - 1e-6 <= (float(w['s']) + float(w['e'])) / 2 <= b + 1e-6 for a, b in spans)]
        if speaker:
            want = str(speaker).strip().lower()
            ws = [w for w in ws if str(w.get('speaker', '')).lower() == want]
        ws.sort(key=lambda w: float(w['s']))
        sha = hashlib.sha1(json.dumps([[w['w'], w['s'], w['e'], w.get('speaker')] for w in ws]).encode()).hexdigest()
        prints.append({'file': name, 'transcript': {'variant': 'given words', 'sha': sha[:12]}, 'exists': exists})
        docs.append(_Doc(len(docs), name, ws, exists, {**info, 'ident': sha[:16]}))
    return docs, prints


def _abs_time(doc, t):
    return None if doc.rec is None else doc.rec + timedelta(seconds=float(t))
