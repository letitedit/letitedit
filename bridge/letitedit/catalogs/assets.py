"""The asset library: one searchable index of the pictures and sounds letitedit can place in a video.

Kinds: emoji (Microsoft Fluent Emoji, still; Google's Noto animated emoji from Shotcut's Elements), icon (Tabler),
sticker / graphic / transition (Shotcut's Elements Lottie animations), sfx (a CC0 sound library, Kenney packs,
letitedit's own synthesised sounds, the Elements panel's CC0 set) and music (the CC0 music library). Every entry has
an id, kind, name, tags, file, duration (sounds and animations), licence, source, whether it may ship in the installer
(`ship`) and the credit line a video that uses it owes (`credit`, None for most).

    search(query, kinds, limit)       ranked entries (all query words must match a name, tag or synonym)
    resolve(ref)                      one entry plus `file`, ready to place: pictures as PNG (SVGs drawn by the export
                                      engine at the size asked), sounds as they are, animations as their Lottie file
    popup_asset(ref, **look)          what a pop-up's `asset` takes: {image: png} or {graphic: asset_sticker recipe}
    sfx_file(ref)                     the path of a sound effect
    preview(entries)                  a contact sheet (pictures) and waveform rows (sounds), as a JPEG
    credits(files)                    the credit lines a video owes for the assets it uses
    stats()                           counts per kind and source, sizes, licences, shipping

Refs: 'emoji:fire' (or the emoji character), 'anim:fire' (animated emoji), 'icon:wrench', 'sticker:gold star',
'graphic:lower third', 'transition:barn door', 'sfx:whoosh', 'music:chill', an id ('fluent/fire', 'tabler/tool',
'library/whoosh_fast_03'), a {query, kind} dict or a file path (the person's own file: passed through).
The index is built from assets/manifest/*.json and music-library/library.csv and cached in cache/assets/index.json
until one of them changes. STYLES.md section 7 describes the library; assets/README.md how it was made.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import base64
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT)
ASSETS = ROOT / 'assets'
MANIFESTS = ASSETS / 'manifest'
MUSIC_CSV = ROOT / 'music-library' / 'library.csv'
CACHE = Path(os.environ.get('LETITEDIT_ASSET_CACHE') or ROOT / 'cache' / 'assets')
APP = ROOT / 'app'
INDEX_VERSION = 1

KINDS = ('emoji', 'sticker', 'icon', 'graphic', 'sfx', 'transition', 'music')
VISUAL = ('emoji', 'sticker', 'icon', 'graphic', 'transition')
SOUND = ('sfx', 'music')
# 'kind:' prefixes of a ref -> (kind, animated wanted: True / False / None = either)
PREFIXES = {'emoji': ('emoji', False), 'anim': ('emoji', True), 'animoji': ('emoji', True),
            'animated': ('emoji', True), 'icon': ('icon', None), 'sticker': ('sticker', None),
            'graphic': ('graphic', None), 'transition': ('transition', None), 'sfx': ('sfx', None),
            'sound': ('sfx', None), 'music': ('music', None), 'song': ('music', None)}
# where a placed animation sits by default (asset_sticker's fit)
DEFAULT_FIT = {'emoji': 'sticker', 'sticker': 'sticker', 'icon': 'sticker', 'graphic': 'width', 'transition': 'cover'}
# a source listed earlier wins a tie (still emoji before animated ones, the curated sounds before the rest)
SOURCE_ORDER = ('fluent', 'tabler', 'elements-sfx', 'library', 'kenney', 'synth', 'elements', 'noto-anim', 'music')


@lru_cache(maxsize=1)
def _popular_order():
    """Curated browse order lives in assets/popular.json, separate from search relevance."""
    path = ASSETS / 'popular.json'
    if not path.exists():
        return {}
    groups = json.loads(path.read_text(encoding='utf-8-sig'))
    return {asset_id: rank for rank, asset_id in enumerate(
        asset_id for group in groups.values() for asset_id in group)}

# query words that mean the same thing (a synonym counts a little less than the word itself)
SYNONYMS = [
    {'whoosh', 'woosh', 'swoosh', 'swish', 'swoop', 'swipe', 'zip'},
    {'pop', 'bloop', 'pluck', 'plop', 'blip', 'bubble'},
    {'boom', 'impact', 'hit', 'thud', 'slam', 'bang', 'explosion', 'punch', 'bonk'},
    {'riser', 'rise', 'uplifter', 'build', 'buildup', 'swell', 'tension'},
    {'downlifter', 'drop', 'fall', 'down'},
    {'glitch', 'digital', 'static', 'distortion', 'stutter', 'computer'},
    {'zap', 'laser', 'phaser', 'electric'},
    {'cash', 'money', 'coins', 'coin', 'register', 'dollar', 'chaching', 'pay', 'price', 'rich'},
    {'laugh', 'laughter', 'haha', 'lol', 'giggle', 'funny'},
    {'cheer', 'applause', 'clap', 'clapping', 'yay', 'celebrate', 'celebration', 'party'},
    {'ding', 'chime', 'bell', 'notification', 'ping', 'alert'},
    {'click', 'tap', 'ui', 'button', 'switch', 'tick'},
    {'scratch', 'record', 'dj', 'vinyl'},
    {'fail', 'wrong', 'buzzer', 'error', 'trombone', 'lose', 'loser'},
    {'win', 'victory', 'success', 'winner', 'levelup', 'tada', 'achievement'},
    {'camera', 'shutter', 'photo', 'snapshot'},
    {'wow', 'amazing', 'amazed', 'omg', 'surprise', 'surprised', 'shock', 'shocked', 'gasp', 'astonished'},
    {'fire', 'flame', 'flames'},
    {'heart', 'love'},
    {'tool', 'tools', 'wrench', 'spanner', 'repair', 'fix', 'mechanic'},
    {'arrow', 'pointer', 'point'},
    {'star', 'sparkle', 'sparkles', 'twinkle', 'magic', 'shine'},
    {'idea', 'lightbulb', 'bulb'},
    {'think', 'thinking', 'hmm', 'question', 'wonder'},
    {'check', 'done', 'correct', 'yes', 'tick'},
    {'transition', 'wipe'},
    {'speech', 'talk', 'says', 'dialog'},
    {'clock', 'time', 'timer'},
    {'typing', 'keyboard', 'type', 'typewriter'},
    {'heartbeat', 'pulse'},
    {'bus', 'van', 'rv', 'camper', 'motorhome'},
    {'car', 'vehicle', 'auto'},
    {'sad', 'cry', 'crying', 'tears'},
    {'happy', 'smile', 'smiling', 'joy', 'grin'},
    {'angry', 'mad', 'rage', 'furious'},
    {'cool', 'sunglasses'},
    {'scary', 'scared', 'fear', 'horror', 'spooky'},
    {'suspense', 'tense', 'dramatic', 'drama'},
    {'chill', 'relaxed', 'calm', 'mellow', 'lofi'},
    {'energetic', 'upbeat', 'energy', 'hype'},
]

_lock = threading.Lock()
_index = None
_syn = None


# ------------------------------------------------------------------ small helpers

def slug(text):
    """'Party popper' -> 'party-popper' (ASCII, lowercase, hyphens)."""
    t = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-') or 'x'


def words(text):
    """Lowercase words of a name or query; emoji characters are words of their own."""
    out = []
    for w in re.split(r'[\s_\-/,;:.()\[\]{}!?"\'+&]+', str(text).lower()):
        if not w:
            continue
        if any(ord(c) > 0x2000 for c in w) and not w.isalnum():
            out.append(w)
        else:
            out.extend(x for x in re.split(r'[^0-9a-z\u00c0-\u024f]+', w) if x)
    return out


def _rel(path):
    """A path inside ROOT as 'assets/...' (forward slashes); others unchanged."""
    p = Path(path)
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def abspath(rel):
    """The absolute path of a file named in a manifest (relative to C:\\LetItEdit) or an absolute path."""
    if not rel:
        return None
    p = Path(rel)
    return str(p if p.is_absolute() else ROOT / p)


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def _no_window():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def melt_exe():
    exe = APP / ('melt.exe' if os.name == 'nt' else 'melt')
    if not exe.exists():
        raise RuntimeError(f'the export engine is missing ({exe})')
    return str(exe)


# ------------------------------------------------------------------ measuring sounds

def measure_sound(path, env_points=48):
    """{duration_s, peak_s, onset_s, peak_db, rms_db, env} of a sound file: peak_s = where its loudest 10 ms is (land
    that on the moment), onset_s = where it first gets loud, rms_db = loudness of its loud part, env = its loudness
    curve in env_points steps (base64 of 0-255 values) for waveform pictures."""
    import numpy as np
    import soundfile as sf
    data, sr = sf.read(str(path), dtype='float32', always_2d=True)
    if not len(data):
        return {'duration_s': 0.0, 'peak_s': 0.0, 'onset_s': 0.0, 'peak_db': -120.0, 'rms_db': -120.0, 'env': ''}
    mono = data.mean(axis=1)
    hop = max(1, int(sr * 0.01))
    n = max(1, len(mono) // hop)
    frames = mono[:n * hop].reshape(n, hop) if len(mono) >= hop else mono.reshape(1, -1)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    top = float(rms.max())
    peak = float(np.abs(data).max())
    loud = rms[rms > top * 0.1]
    onset = int(np.argmax(rms > top * 0.1))
    pts = np.array_split(rms, min(env_points, len(rms)))
    env = bytes(int(round(255 * float(c.max()) / top)) if top > 0 else 0 for c in pts)
    return {'duration_s': round(len(mono) / sr, 3), 'peak_s': round((int(np.argmax(rms)) + 0.5) * hop / sr, 3),
            'onset_s': round(onset * hop / sr, 3), 'peak_db': round(20 * math.log10(max(peak, 1e-6)), 1),
            'rms_db': round(20 * math.log10(max(float(np.sqrt(np.mean(loud ** 2))), 1e-6)), 1),
            'env': base64.b64encode(env).decode()}


def text_slots(path):
    """The texts a Glaxnimate (.rawr) graphic draws, in file order (e.g. ['Description', 'Sample title'])."""
    if Path(path).suffix.lower() != '.rawr':
        return []
    out = []

    def walk(o):
        if isinstance(o, dict):
            if o.get('__type__') == 'TextShape' and isinstance(o.get('text'), str):
                out.append(o['text'])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    return out


def with_texts(path, texts):
    """A copy of a .rawr graphic with its texts replaced (texts: {old text: new text}, or a list in the order
    title first, then the other slots), cached in cache/assets/text/. Returns the copy's path (or path itself)."""
    if not texts or Path(path).suffix.lower() != '.rawr':
        return str(path)
    slots = text_slots(path)
    if isinstance(texts, (list, tuple)):
        order = sorted(range(len(slots)), key=lambda i: (0 if re.search(r'title|name', slots[i], re.I) else 1, i))
        texts = {slots[i]: str(t) for i, t in zip(order, texts)}
    unknown = [k for k in texts if k not in slots]
    if unknown:
        raise ValueError(f"{Path(path).name} has texts {slots}; not {unknown}")
    key = hashlib.sha1(json.dumps([_rel(path), _stamp(path), texts], ensure_ascii=False).encode()).hexdigest()[:20]
    dst = CACHE / 'text' / f'{key}.rawr'
    if not dst.exists():
        d = json.loads(Path(path).read_text(encoding='utf-8-sig'))

        def walk(o):
            if isinstance(o, dict):
                if o.get('__type__') == 'TextShape' and o.get('text') in texts:
                    o['text'] = texts[o['text']]
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
        _atomic_write(dst, json.dumps(d, ensure_ascii=False))
    return str(dst)


def lottie_info(path):
    """{w, h, fps, frames, duration_s} of a Lottie (.json/.tgs) or Glaxnimate (.rawr) file."""
    import gzip
    raw = Path(path).read_bytes()
    d = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    if 'assets' in d and isinstance(d['assets'], dict) and 'compositions' in d['assets']:      # .rawr
        c = d['assets']['compositions']['values'][0]
        a = c.get('animation') or {}
        fps = float(c.get('fps') or 60)
        frames = int(a.get('last_frame', 0)) - int(a.get('first_frame', 0))
        return {'w': int(c['width']), 'h': int(c['height']), 'fps': fps, 'frames': frames,
                'duration_s': round(frames / fps, 3)}
    fps = float(d.get('fr') or 30)
    frames = int(round(float(d.get('op', 0)) - float(d.get('ip', 0))))
    return {'w': int(d.get('w') or 512), 'h': int(d.get('h') or 512), 'fps': fps, 'frames': frames,
            'duration_s': round(frames / fps, 3)}


# ------------------------------------------------------------------ the index

def _signature():
    files = sorted(MANIFESTS.glob('*.json')) if MANIFESTS.is_dir() else []
    if MUSIC_CSV.exists():
        files.append(MUSIC_CSV)
    sig = [INDEX_VERSION, str(ROOT)]
    for f in files:
        try:
            st = f.stat()
            sig.append([f.name, st.st_size, int(st.st_mtime)])
        except OSError:
            pass
    return sig


def _entries_from_manifest(m):
    """Index entries of one manifest (assets/manifest/<source>.json; header fields apply to every item)."""
    src = m['source']
    head = {k: m[k] for k in ('kind', 'licence', 'ship', 'credit', 'animated', 'format') if k in m}
    styles = m.get('styles') or {}
    out = []
    for it in m.get('items', []):
        e = dict(head)
        e.update(it)
        e['source'] = src
        if 'id' not in e:
            e['id'] = f"{m.get('id_prefix', src)}/{e['slug']}"
        if styles and 'styles' not in it:
            have = it.get('has') or list(styles)
            e['styles'] = {k: v.format(slug=e.get('slug', '')) for k, v in styles.items() if k in have}
        e.pop('has', None)
        if 'file' not in e and e.get('styles'):
            e['file'] = next(iter(e['styles'].values()))
        e.setdefault('name', e.get('slug', e['id']).replace('-', ' ').replace('_', ' '))
        e.setdefault('tags', [])
        e.setdefault('animated', False)
        out.append(e)
    return out


def _music_entries():
    import csv
    out = []
    try:
        with MUSIC_CSV.open(encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return out
    seen = set()
    for r in rows:
        f = (r.get('File') or '').strip()
        if not f:
            continue
        if not (ROOT / 'music-library' / f).is_file():
            continue
        sid = 'music/' + slug(Path(f).stem)[:80]
        while sid in seen:
            sid += '-2'
        seen.add(sid)
        try:
            dur = sum(int(part) * 60**n for n, part in
                      enumerate(reversed((r.get('Length') or '0:0').split(':'))))
        except ValueError:
            dur = None
        lic = (r.get('License') or '').strip()
        out.append({'id': sid, 'kind': 'music', 'source': 'music', 'name': (r.get('Title') or Path(f).stem).strip(),
                    'tags': [t for t in (r.get('Genre'), r.get('Mood'), r.get('Artist'), r.get('Album')) if t],
                    'group': r.get('Genre') or '', 'genre': r.get('Genre') or '', 'mood': r.get('Mood') or '',
                    'file': 'music-library/' + f.replace('\\', '/'),
                    'duration_s': dur, 'bpm': int(r['BPM']) if (r.get('BPM') or '').isdigit() else None,
                    'licence': 'CC0-1.0' if 'CC0' in lic else 'Public domain' if lic else 'unknown',
                    'licence_text': lic, 'origin_url': r.get('Source') or '', 'artist': (r.get('Artist') or '').strip(),
                    'ship': bool(lic), 'credit': None, 'animated': False})
    return out


MUSIC_SOURCE = {'source': 'music', 'title': 'letitedit CC0 music library (Internet Archive albums)',
                'url': 'music-library/library.csv', 'licence': 'CC0 1.0 / Public Domain Mark (per song, library.csv)',
                'licence_file': 'music-library/LICENSE.txt', 'ship': True, 'credit': None,
                'notes': 'Each song: its album page on the Internet Archive (library.csv Source column).'}


def build_index():
    """Read every manifest and the music list into one index (not cached; index() caches it)."""
    entries, sources = [], {}
    for f in sorted(MANIFESTS.glob('*.json')) if MANIFESTS.is_dir() else []:
        try:
            m = json.loads(f.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            sources[f.stem] = {'source': f.stem, 'error': f'{type(exc).__name__}: {exc}'}
            continue
        if not isinstance(m, dict) or 'source' not in m:
            continue
        sources[m['source']] = {k: v for k, v in m.items() if k not in ('items', 'styles')}
        sources[m['source']]['count'] = len(m.get('items', []))
        entries.extend(_entries_from_manifest(m))
    music = _music_entries()
    if music:
        sources['music'] = dict(MUSIC_SOURCE, count=len(music))
        entries.extend(music)
    seen, unique = set(), []
    for e in entries:
        if e['id'] in seen or e.get('same_as'):
            continue
        seen.add(e['id'])
        unique.append(e)
    # a copy of another entry (the Elements panel's FLACs) is listed once: on the entry it copies, as alt_files, with
    # its panel name as a name of that entry (a curated pick ranks a little higher)
    by_id = {e['id']: e for e in unique}
    for e in entries:
        target = by_id.get(e.get('same_as'))
        if target is None:
            continue
        target.setdefault('alt_files', []).append(e['file'])
        target['tags'] = list(target.get('tags') or []) + [e['name']]
        target['pick'] = e['name']
    return {'version': INDEX_VERSION, 'sources': sources, 'entries': unique}


class Index:
    def __init__(self, data):
        self.data = data
        self.sources = data['sources']
        self.entries = data['entries']
        self.by_id = {e['id']: e for e in self.entries}
        for e in self.entries:
            n = set(words(e['name'])) | set(words(e.get('slug', '')))
            t = set()
            for tag in list(e.get('tags') or []) + [e.get('group') or '', e.get('category') or '', e['kind']]:
                t.update(words(tag))
            if e['kind'] == 'emoji':
                t.add('emoji')
            if e.get('animated'):
                t.update(('animated', 'anim'))
            e['_n'], e['_t'] = n, t - n
            e['_s'] = ' '.join(words(e['name']))
            e['_rank'] = SOURCE_ORDER.index(e['source']) if e['source'] in SOURCE_ORDER else len(SOURCE_ORDER)


def index(refresh=False):
    """The index (built once, cached in cache/assets/index.json, rebuilt when a manifest or the music list changes)."""
    global _index
    with _lock:
        sig = _signature()
        if not refresh and _index is not None and _index.data.get('signature') == sig:
            return _index
        cached = CACHE / 'index.json'
        if not refresh and cached.exists():
            try:
                d = json.loads(cached.read_text(encoding='utf-8-sig'))
                if d.get('signature') == sig:
                    _index = Index(d)
                    return _index
            except (OSError, ValueError):
                pass
        d = build_index()
        d['signature'] = sig
        try:
            _atomic_write(cached, json.dumps(d, ensure_ascii=False, separators=(',', ':')))
        except OSError:
            pass
        _index = Index(d)
        return _index


def public(e, full=False):
    """An entry as tools show it (search fields and the waveform data left out)."""
    keys = ('id', 'kind', 'name', 'glyph', 'group', 'genre', 'mood', 'tags', 'file', 'styles', 'animated', 'duration_s', 'bpm', 'peak_s',
            'onset_s', 'peak_db', 'rms_db', 'w', 'h', 'licence', 'source', 'origin', 'artist', 'ship', 'credit', 'pick')
    out = {k: e[k] for k in keys if k in e and e[k] not in (None, '', [], {})}
    if 'animated' in e:
        out['animated'] = bool(e['animated'])
    if 'file' in out:
        out['file'] = abspath(out['file'])
    if 'styles' in out:
        out['styles'] = {k: abspath(v) for k, v in out['styles'].items()}
    if not full:
        out['tags'] = out.get('tags', [])[:12]
    else:
        for k in ('origin_url', 'origin_title', 'licence_text', 'folder', 'category', 'pack', 'recipe'):
            if e.get(k):
                out[k] = e[k]
        if e.get('alt_files'):
            out['alt_files'] = [abspath(f) for f in e['alt_files']]
    return out


# ------------------------------------------------------------------ search

def _synonyms():
    global _syn
    if _syn is None:
        _syn = {}
        for group in SYNONYMS:
            for w in group:
                _syn.setdefault(w, set()).update(group - {w})
    return _syn


def _score(e, groups):
    total = 0.0
    for t, alts in groups:
        best = 0.0
        for a, w in alts:
            if a == e.get('glyph'):
                s = 12
            elif a in e['_n']:
                s = 6
            elif a in e['_t']:
                s = 4
            elif w < 0.9:                   # a synonym counts only as a whole word
                continue
            elif len(a) >= 3 and any(x.startswith(a) for x in e['_n']):
                s = 3
            elif len(a) >= 3 and any(x.startswith(a) for x in e['_t']):
                s = 2
            elif len(a) >= 4 and a in e['_s']:
                s = 1
            else:
                continue
            best = max(best, s * w)
        if not best:
            return 0.0
        total += best
    if groups and ' '.join(t for t, _ in groups) == e['_s']:
        total += 5
    if e.get('credit'):
        total -= 0.5
    if e.get('pick'):                   # in the Elements panel's curated set
        total += 1.0
    return total - 0.05 * len(e['_n'])


def _query_groups(query):
    syn = _synonyms()
    groups = []
    for t in words(query):
        alts = [(t, 1.0)] + [(s, 0.7) for s in sorted(syn.get(t, ()))]
        if len(t) > 3 and t.endswith('s') and t[:-1] not in dict(alts):
            alts.append((t[:-1], 0.95))           # plurals: 'coins' finds 'coin'
        groups.append((t, alts))
    return groups


def _kinds(kinds):
    if kinds is None or kinds == [] or kinds == 'all':
        return set(KINDS)
    if isinstance(kinds, str):
        kinds = [kinds]
    alias = {'emojis': 'emoji', 'icons': 'icon', 'stickers': 'sticker', 'graphics': 'graphic', 'sound': 'sfx',
             'sounds': 'sfx', 'transitions': 'transition', 'song': 'music', 'songs': 'music'}
    out = {alias.get(k.lower(), k.lower()) for k in kinds}
    bad = out - set(KINDS)
    if bad:
        raise ValueError(f"kinds are {', '.join(KINDS)}; got {', '.join(sorted(bad))}")
    return out


def search(query='', kinds=None, limit=24, offset=0, animated=None, source=None, ship_only=False,
           credit_ok=True, max_duration=None, exclude_sources=None, groups=None, popular=False):
    """{total, results: [entries], by_kind: {kind: count}, partial}. Every query word must match a name, a tag or
    a synonym (partial=True: nothing matched every word, so entries matching most words are shown). Empty query: the
    entries of the kinds asked, in source order. animated: True/False keeps only animated/still emoji and stickers;
    credit_ok=False leaves out assets whose videos owe a credit line; max_duration (s) for sounds."""
    idx = index()
    ks = _kinds(kinds)
    gs = {g for g in groups.split(',') if g} if isinstance(groups, str) else set(groups or [])
    pool = [e for e in idx.entries if e['kind'] in ks
            and (not gs or e.get('group') in gs)
            and (animated is None or bool(e.get('animated')) == bool(animated))
            and (source is None or e['source'] == source)
            and (not exclude_sources or e['source'] not in exclude_sources)
            and (not ship_only or e.get('ship'))
            and (credit_ok or not e.get('credit'))
            and (max_duration is None or e['kind'] not in SOUND or (e.get('duration_s') or 0) <= max_duration)]
    groups = _query_groups(query)
    partial = False
    if groups:
        scored = [(s, e) for e in pool if (s := _score(e, groups)) > 0]
        if not scored and len(groups) > 1:          # nothing matches every word: the best partial matches
            partial = True
            for e in pool:
                s = sum(_score(e, [g]) for g in groups)
                if s > 0:
                    scored.append((s - 6 * len(groups), e))
        scored.sort(key=lambda se: (-se[0], se[1]['_rank'], se[1]['name']))
        hits = [e for _, e in scored]
    else:
        hits = sorted(pool, key=lambda e: (e['_rank'], e['name']))
        if popular:
            order = _popular_order()
            hits.sort(key=lambda e: (0, order[e['id']]) if e['id'] in order
                      else (1, e['_rank'], e['name']))
    by_kind = {}
    for e in hits:
        by_kind[e['kind']] = by_kind.get(e['kind'], 0) + 1
    offset = max(0, int(offset))
    limit = max(1, min(200, int(limit)))
    return {'query': query, 'total': len(hits), 'by_kind': by_kind, 'partial': partial,
            'results': hits[offset:offset + limit]}


def suggestions(query, kinds=None, n=8):
    """Names close to a query that found nothing (for error messages)."""
    idx = index()
    ks = _kinds(kinds)
    names = sorted({e['name'] for e in idx.entries if e['kind'] in ks})
    return difflib.get_close_matches(str(query).lower(), names, n=n, cutoff=0.5)


# ------------------------------------------------------------------ resolve

def parse_ref(ref):
    """(kind, animated, query, id) of a ref string."""
    s = str(ref).strip()
    m = re.match(r'^([a-z]+):(.*)$', s, re.I)
    if m and m.group(1).lower() in PREFIXES:
        kind, anim = PREFIXES[m.group(1).lower()]
        return kind, anim, m.group(2).strip(), None
    if m and m.group(1).lower() == 'id':
        return None, None, None, m.group(2).strip()
    return None, None, s, None


def find(ref, kind=None, animated=None, variant=0):
    """The entry a ref names (LookupError with close names when nothing matches)."""
    idx = index()
    if isinstance(ref, dict):
        if ref.get('id'):
            ref = 'id:' + ref['id']
        else:
            kind = ref.get('kind', kind)
            animated = ref.get('animated', animated)
            ref = ref.get('query') or ref.get('name') or ''
    k, anim, query, eid = parse_ref(ref)
    if eid or (query and query in idx.by_id):
        e = idx.by_id.get(eid or query)
        if e is None:
            raise LookupError(f'no asset with id {eid!r}')
        return e
    kind = kind or k
    animated = anim if animated is None else animated
    res = search(query or '', kinds=[kind] if kind else None, limit=max(1, int(variant) + 1) if variant else 40,
                 animated=animated)
    hits = res['results']
    if not hits and kind == 'emoji' and animated is False:      # no still one: an animated one will do
        hits = search(query or '', kinds=['emoji'], limit=40)['results']
    if not hits:
        near = suggestions(query or '', [kind] if kind else None)
        raise LookupError(f"no {kind or 'asset'} matches {query!r}" + (f"; close: {', '.join(near)}" if near else '')
                          + " (letitedit_assets searches the library)")
    if res['partial']:
        raise LookupError(f"no {kind or 'asset'} matches every word of {query!r}; closest: "
                          + ', '.join(e['id'] for e in hits[:5]))
    if variant:
        total = res['total']
        if total > len(hits):
            hits = search(query or '', kinds=[kind] if kind else None, limit=min(200, total), animated=animated)['results']
        return hits[int(variant) % len(hits)]
    return hits[0]


def resolve(ref, kind=None, style=None, size_px=None, color=None, animated=None, variant=0, raster=True):
    """One asset, ready to place: the entry (public fields) plus
      file      pictures: a PNG (Fluent 3D as it is; SVGs drawn by the export engine at size_px, default 512, Tabler
                icons in `color`, default white); sounds: the sound file; animations: the Lottie file
      path      the original file
      style     the picture style used (Fluent: 3d | color | flat; Tabler: outline | filled)
      graphic   animations only: the graphic recipe that places it (template asset_sticker)
    A file path that exists is the person's own file: returned as it is with licence 'own'. 'mine:<id>' is an item of
    the person's My assets (my_assets.py), resolved the same way: their file, licence 'own', no credit line."""
    if isinstance(ref, str) and ref.strip().lower().startswith('mine:'):
        import letitedit.catalogs.my_assets as my_assets
        it = my_assets.get(ref)
        out = resolve(it['path'], kind=kind)
        if Path(it['path']).suffix.lower() in ('.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf'):
            out['kind'] = 'video'
        out.update({'id': it['ref'], 'name': it['id'], 'mine': {'id': it['id'], 'kind': it['kind'], 'text': it['text']}})
        if it.get('duration_s'):
            out['duration_s'] = it['duration_s']
        if it.get('peak_s') is not None:
            out['peak_s'] = it['peak_s']
        return out
    if isinstance(ref, (str, os.PathLike)) and not str(ref).startswith(('id:',)) and os.path.isfile(str(ref)):
        p = os.path.abspath(str(ref))
        ext = Path(p).suffix.lower()
        sound = ext in ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.opus')
        out = {'id': 'file:' + p, 'kind': kind or ('sfx' if sound else 'image'), 'name': Path(p).stem, 'file': p,
               'path': p, 'licence': 'own', 'source': 'own', 'ship': False, 'credit': None,
               'animated': ext in ('.tgs', '.rawr', '.lottie') or (ext == '.json')}
        if out['animated']:
            out['graphic'] = {'template': 'asset_sticker', 'params': {'asset': p, 'asset_stamp': _stamp(p)}}
        return out
    e = find(ref, kind=kind, animated=animated, variant=variant)
    out = public(e, full=True)
    out['path'] = abspath(e['file'])
    if e['kind'] in VISUAL:
        if e.get('animated'):
            out['file'] = out['path']
            out['graphic'] = {'template': 'asset_sticker', 'params': {
                'asset': e['id'], 'fit': DEFAULT_FIT.get(e['kind'], 'sticker'), 'asset_stamp': _stamp(out['path'])}}
        elif raster:
            st, src = _pick_style(e, style, size_px)
            out['style'] = st
            out['file'] = rasterize(src, size_px or 512, color=color if e['source'] == 'tabler' else None) \
                if src.lower().endswith('.svg') else src
        else:
            st, src = _pick_style(e, style, size_px)
            out['style'], out['file'] = st, src
    else:
        out['file'] = out['path']
    return out


def _stamp(path):
    try:
        st = os.stat(path)
        return f'{st.st_size}-{int(st.st_mtime)}'
    except OSError:
        return ''


def _pick_style(e, style, size_px):
    """(style, absolute file) of a still picture: Fluent 3D up to ~320 px (its PNGs are 256 px), the colour
    drawing above that; Tabler outline unless filled is asked."""
    styles = {k: abspath(v) for k, v in (e.get('styles') or {}).items()}
    if not styles:
        return None, abspath(e['file'])
    if style and style in styles:
        return style, styles[style]
    if style and style not in styles:
        raise LookupError(f"{e['id']} has styles {', '.join(styles)}; not {style!r}")
    if e['source'] == 'fluent':
        if size_px and size_px > 320 and 'color' in styles:
            return 'color', styles['color']
        return ('3d', styles['3d']) if '3d' in styles else next(iter(styles.items()))
    return next(iter(styles.items()))


def popup_asset(ref, **look):
    """What a pop-up's `asset` takes for a library asset: {image: <png>} for a still picture, or {graphic: {template:
    asset_sticker, params}} for an animation (look keys - x, y, size, in, out, in_s, out_s, wiggle, tilt, shadow,
    outline, outline_color, fit, loop, speed - go into its params; a still picture's look stays with the pop-up)."""
    r = resolve(ref, size_px=look.pop('size_px', None), style=look.pop('style', None), color=look.pop('color', None))
    if r.get('graphic'):
        g = {'template': 'asset_sticker', 'params': dict(r['graphic']['params'])}
        g['params'].update({k: v for k, v in look.items() if v is not None})
        return {'graphic': g}
    if r['kind'] in SOUND:
        raise ValueError(f"{r['id']} is a sound; a pop-up's sound goes in sfx")
    return {'image': r['file']}


def sfx_file(ref, variant=0):
    """The file of a sound effect named by a ref ('whoosh', 'sfx:pop', an id or a path)."""
    if isinstance(ref, str) and os.path.isfile(ref):
        return os.path.abspath(ref)
    r = resolve(ref if ':' in str(ref) else f'sfx:{ref}', variant=variant)
    if r['kind'] not in SOUND:
        raise LookupError(f"{r['id']} is not a sound")
    return r['file']


def entry_for_file(path):
    """The library entry whose file (or a style of it) is this file, or None."""
    idx = index()
    rel = _rel(path)
    for e in idx.entries:
        if e.get('file') == rel or rel in (e.get('styles') or {}).values() or rel in (e.get('alt_files') or []):
            return e
    return None


def credits(files):
    """The credit lines a video owes for these files (asset files or rendered graphics' asset ids), deduplicated:
    [{line, assets: [ids]}]. Most assets owe none (CC0, MIT, Lottie Simple License)."""
    idx = index()
    lines = {}
    for f in files or []:
        e = idx.by_id.get(f) if isinstance(f, str) and f in idx.by_id else entry_for_file(f)
        if e and e.get('credit'):
            lines.setdefault(e['credit'], []).append(e['id'])
    return [{'line': k, 'assets': sorted(set(v))} for k, v in lines.items()]


def _file_map(idx):
    """{file as the manifests name it: entry} for every file an entry names (its file, styles, other files)."""
    m = getattr(idx, '_files', None)
    if m is None:
        m = {}
        for e in idx.entries:
            for f in [e.get('file'), *(e.get('styles') or {}).values(), *(e.get('alt_files') or [])]:
                if f:
                    m.setdefault(f, e)
        idx._files = m
    return m


def project_files(project):
    """What a project (.mlt) uses that can be a library asset: every file its clips name (resource, relative ones
    against the project's root) and every asset named in a graphic recipe's params (asset_sticker and pop-ups)."""
    import xml.etree.ElementTree as ET
    root = ET.parse(str(project)).getroot()
    base = Path(root.get('root') or Path(project).parent)
    refs = []
    for prop in root.iter('property'):
        name, text = prop.get('name') or '', (prop.text or '').strip()
        if not text:
            continue
        if name in ('resource', 'warp_resource'):
            m = re.match(r'^-?[0-9.]+:(.+)$', text)          # a timewarp clip: 'speed:file'
            p = Path(m.group(1) if m and not re.match(r'^[A-Za-z]:[\\/]', text) else text)
            refs.append(str(p if p.is_absolute() else base / p))
        elif name == 'letitedit:asset':
            refs.append(text)       # the library entry a sticker or sound placed by the app came from (id or file)
        elif name == 'letitedit_ai:graphic':
            try:
                params = (json.loads(text) or {}).get('params') or {}
            except ValueError:
                continue
            refs += [v for k, v in params.items() if k in ('asset', 'image', 'emoji') and isinstance(v, str) and v]
    return refs


def _elements_copies(idx):
    """{file name: entry} for the Elements panel's files (the animated emoji and stickers), whose copies the panel
    puts in the project's folder (<project folder>/Emojis/167-fire.tgs); names two entries share are left out."""
    m = getattr(idx, '_copies', None)
    if m is None:
        seen = {}
        for e in idx.entries:
            if str(e.get('file') or '').startswith('app/share/shotcut/elements/'):
                seen.setdefault(Path(e['file']).name.lower(), []).append(e)
        m = {k: v[0] for k, v in seen.items() if len(v) == 1}
        idx._copies = m
    return m


def entry_of_ref(ref, idx=None):
    """The library entry a project's reference names, or None: an entry id, a file of the library (or one of its
    styles), a copy the Elements panel made in the project's folder, or a reference such as 'anim:party'."""
    idx = idx or index()
    e = idx.by_id.get(ref) or _file_map(idx).get(_rel(ref))
    if e is None and os.path.isabs(ref):          # a copy the Elements panel made in the project's folder
        e = _elements_copies(idx).get(Path(ref).name.lower())
    if e is None and ':' in ref and not os.path.isabs(ref) and not os.path.exists(ref):
        try:                                              # a library reference such as 'anim:party'
            e = idx.by_id.get(resolve(ref).get('id'))
        except Exception:  # noqa: BLE001 - not a reference the library knows
            e = None
    return e


def project_credits(project):
    """The credit lines a project owes for the library assets it uses (project_files), as credits() gives them:
    [{line, assets: [ids]}], [] when it owes none. Google's Noto animated emoji owe one (CC BY 4.0), and AI-made pictures have a line to say so."""
    idx = index()
    lines = {}
    for ref in project_files(project):
        e = entry_of_ref(ref, idx)
        if e and e.get('credit'):
            lines.setdefault(e['credit'], set()).add(e['id'])
    out = [{'line': k, 'assets': sorted(v)} for k, v in lines.items()]
    try:                                                      # AI-made pictures (letitedit_image): clips and code scenes
        import letitedit.pictures.image_gen as image_gen
        out += image_gen.owes(project_files(project) + image_gen.scene_images(project))
    except Exception:  # noqa: BLE001 - a line of credit must never stop an export
        pass
    try:                                                      # on-demand songs and stock video and photos (T89)
        import letitedit.sound.media_server as media_server
        out += media_server.owes(project_files(project))
    except Exception:  # noqa: BLE001 - a line of credit must never stop an export
        pass
    try:                                                      # real pictures of named things (T173) and what is made from
        import letitedit.pictures.real_pictures as real_pictures                                  # them (T178): clips, recipes on clips, code scenes
        out += real_pictures.project_credits(project)
    except Exception:  # noqa: BLE001 - a line of credit must never stop an export
        pass
    return out


# ------------------------------------------------------------------ drawing with the export engine

def _profile(path, w, h, fps=30):
    g = math.gcd(int(w), int(h))
    Path(path).write_text(
        f'description=letitedit assets {w}x{h}\nframe_rate_num={int(round(fps * 1000))}\nframe_rate_den=1000\n'
        f'width={int(w)}\nheight={int(h)}\nprogressive=1\nsample_aspect_num=1\nsample_aspect_den=1\n'
        f'display_aspect_num={int(w) // g}\ndisplay_aspect_den={int(h) // g}\ncolorspace=709\n', encoding='utf-8')


def _sized_svg(src, px, color=None):
    """SVG text with its drawing size set to px (keeping the viewBox's shape) and currentColor set to color."""
    svg = Path(src).read_text(encoding='utf-8')
    m = re.search(r'<svg\b[^>]*>', svg, re.S)
    if not m:
        raise ValueError(f'not an SVG file: {src}')
    tag = m.group(0)
    vb = re.search(r'viewBox="\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)[\s,]+([-\d.]+)\s*"', tag)
    w, h = (float(vb.group(3)), float(vb.group(4))) if vb else (1.0, 1.0)
    s = px / max(w, h)
    new = re.sub(r'\s(width|height)="[^"]*"', '', tag)
    new = new.replace('<svg', f'<svg width="{round(w * s)}" height="{round(h * s)}"', 1)
    svg = svg.replace(tag, new, 1)
    if color:
        svg = svg.replace('currentColor', color)
    return svg, (round(w * s), round(h * s))


def _melt_frames(jobs, w, h, fps=30, timeout=240):
    """Render [(file, frame, destination png)] at w x h in one engine run, in order. The glaxnimate reader ignores a
    clip's in point (it always starts at the animation's first frame), so a later frame is reached by drawing the
    frames up to it and keeping the last. Raises when the engine fails or a file gave fewer frames."""
    tmp = Path(tempfile.mkdtemp(prefix='lie-assets-'))
    try:
        prof = tmp / 'p.profile'
        _profile(prof, w, h, fps)
        args = [melt_exe(), '-quiet', '-profile', str(prof)]
        for f, frame, _ in jobs:
            args += [str(f), 'in=0', f'out={max(0, int(frame))}']
        args += ['-consumer', f'avformat:{tmp / "f_%05d.png"}', 'vcodec=png', 'pix_fmt=rgba', 'mlt_image_format=rgba']
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=_no_window())
        outs = sorted(tmp.glob('f_*.png'))
        need = sum(max(0, int(fr)) + 1 for _, fr, _ in jobs)
        if len(outs) != need:
            raise RuntimeError(f'the export engine drew {len(outs)} of {need} frames '
                               f'({(r.stderr or r.stdout or "").strip()[-300:]})')
        k = -1
        for _, fr, dst in jobs:
            k += max(0, int(fr)) + 1
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            os.replace(outs[k], dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def rasterize(svg, px=512, color=None):
    """A PNG of an SVG drawn by the export engine (Qt's SVG renderer) at px on its longer side, transparent outside
    the drawing; color replaces currentColor (Tabler icons). Cached in cache/assets/raster."""
    return rasterize_many([svg], px, color)[0]


def rasterize_many(svgs, px=512, color=None):
    out, todo = [], []
    for s in svgs:
        key = hashlib.sha1(f'{_rel(s)}|{_stamp(s)}|{px}|{color}'.encode()).hexdigest()[:20]
        dst = CACHE / 'raster' / f'{key}.png'
        out.append(dst)
        if not dst.exists():
            todo.append((s, dst))
    if todo:
        tmp = Path(tempfile.mkdtemp(prefix='lie-svg-'))
        try:
            groups = {}
            for i, (s, dst) in enumerate(todo):
                text, size = _sized_svg(s, px, color)
                f = tmp / f's{i:05d}.svg'
                f.write_text(text, encoding='utf-8')
                groups.setdefault(size, []).append((f, dst))
            for (w, h), items in groups.items():
                for k in range(0, len(items), 120):
                    _melt_frames([(f, 0, dst) for f, dst in items[k:k + 120]], w, h)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return [str(p) for p in out]


def lottie_frames(path, fps=30.0, px=512, count=None, start=0, aspect=None):
    """PNG frames of a Lottie/Glaxnimate animation drawn by the export engine (glaxnimate) at the project's frame
    rate; the canvas keeps the animation's own shape with px on its longer side (or aspect=(w, h) to draw it at a
    given size). start > 0 draws from the first frame and drops the frames before start (the reader ignores in
    points). Cached in cache/assets/lottie/<key>/; returns the frame paths."""
    info = lottie_info(path)
    if aspect:
        w, h = int(aspect[0]), int(aspect[1])
    else:
        s = px / max(info['w'], info['h'])
        w, h = max(2, round(info['w'] * s / 2) * 2), max(2, round(info['h'] * s / 2) * 2)
    n = int(count) if count else max(1, int(round(info['duration_s'] * fps)))
    key = hashlib.sha1(f'{_rel(path)}|{_stamp(path)}|{fps:.4f}|{w}x{h}|{n}|{start}'.encode()).hexdigest()[:20]
    d = CACHE / 'lottie' / key
    done = d / 'done.json'
    if done.exists():
        return [str(p) for p in sorted(d.glob('f_*.png'))]
    tmp = Path(tempfile.mkdtemp(prefix='lie-lottie-'))
    try:
        prof = tmp / 'p.profile'
        _profile(prof, w, h, fps)
        r = subprocess.run([melt_exe(), '-quiet', '-profile', str(prof), str(path), 'in=0',
                            f'out={int(start) + n - 1}', '-consumer', f'avformat:{tmp / "f_%05d.png"}', 'vcodec=png',
                            'pix_fmt=rgba', 'mlt_image_format=rgba'], capture_output=True, text=True, timeout=600,
                           creationflags=_no_window())
        frames = sorted(tmp.glob('f_*.png'))[int(start):]
        if not frames:
            raise RuntimeError(f'the export engine drew no frames of {path} ({(r.stderr or "").strip()[-300:]})')
        d.mkdir(parents=True, exist_ok=True)
        for f in frames:
            os.replace(f, d / f.name)
        _atomic_write(done, json.dumps({'file': str(path), 'w': w, 'h': h, 'fps': fps, 'frames': len(frames)}))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [str(p) for p in sorted(d.glob('f_*.png'))]


def _still_frame(info, at):
    """The animation frame shown as a still: `at` of its length, but no later than 1.2 s in (drawing a still means
    drawing every frame before it)."""
    want = round(info['frames'] * at)
    if at > 0:
        want = min(want, round(info['fps'] * 1.2))
    return int(max(0, min(info['frames'] - 1, want)))


def lottie_still(path, px=256, at=0.5):
    """One frame (at = fraction of its length) of an animation as a PNG (cached)."""
    info = lottie_info(path)
    frame = _still_frame(info, at)
    s = px / max(info['w'], info['h'])
    w, h = max(2, round(info['w'] * s / 2) * 2), max(2, round(info['h'] * s / 2) * 2)
    key = hashlib.sha1(f'{_rel(path)}|{_stamp(path)}|{w}x{h}|{frame}'.encode()).hexdigest()[:20]
    dst = CACHE / 'stills' / f'{key}.png'
    if not dst.exists():
        _melt_frames([(path, round(frame * 30.0 / info['fps']), dst)], w, h, fps=30)
    return str(dst)


def _stills_many(paths, px=256, at=0.5):
    """lottie_still for many files, in as few engine runs as there are canvas shapes; `at` may be a {path: at} map."""
    out, todo = {}, {}
    ats = at if isinstance(at, dict) else {}
    for p in paths:
        at = ats.get(p, 0.5) if ats else at
        info = lottie_info(p)
        frame = _still_frame(info, at)
        s = px / max(info['w'], info['h'])
        w, h = max(2, round(info['w'] * s / 2) * 2), max(2, round(info['h'] * s / 2) * 2)
        key = hashlib.sha1(f'{_rel(p)}|{_stamp(p)}|{w}x{h}|{frame}'.encode()).hexdigest()[:20]
        dst = CACHE / 'stills' / f'{key}.png'
        out[p] = str(dst)
        if not dst.exists():
            todo.setdefault((w, h), []).append((p, round(frame * 30.0 / info['fps']), dst))
    for (w, h), items in todo.items():
        for k in range(0, len(items), 120):
            _melt_frames(items[k:k + 120], w, h, fps=30)
    return out


# ------------------------------------------------------------------ previews

def _font(px, bold=False):
    from PIL import ImageFont
    win = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for name in (('segoeuib.ttf', 'arialbd.ttf') if bold else ('segoeui.ttf', 'arial.ttf')):
        try:
            return ImageFont.truetype(str(win / name), px)
        except OSError:
            continue
    return ImageFont.load_default()


def _thumbs(entries, px):
    """{id: RGBA image} thumbnails of visual entries (engine runs batched)."""
    from PIL import Image
    out = {}
    svgs = {e['id']: abspath(_pick_style(e, None, None)[1]) for e in entries
            if not e.get('animated') and str(e.get('file', '')).lower().endswith('.svg')}
    svg_png = dict(zip(svgs, rasterize_many(list(svgs.values()), px, color='#FFFFFF'))) if svgs else {}
    # animated emoji show their first frame (Noto marks it as the resting pose); other animations their middle
    anims = {abspath(e['file']): (0.0 if e['kind'] == 'emoji' else 0.5) for e in entries if e.get('animated')}
    still_png = _stills_many(list(anims), max(px, 320), anims) if anims else {}
    for e in entries:
        try:
            if e['id'] in svg_png:
                f = svg_png[e['id']]
            elif e.get('animated'):
                f = still_png[abspath(e['file'])]
            else:
                f = _pick_style(e, None, None)[1]
            with Image.open(f) as src:
                im = src.convert('RGBA')
            box = im.getchannel('A').getbbox()
            if box:                          # what is drawn, not the empty canvas around it
                im = im.crop(box)
            im.thumbnail((px, px), Image.LANCZOS)
            out[e['id']] = im
        except Exception:  # noqa: BLE001 - a broken file shows as an empty tile
            out[e['id']] = None
    return out


def _env_of(e):
    if e.get('env'):
        return list(base64.b64decode(e['env']))
    f = abspath(e['file'])
    key = hashlib.sha1(f'{_rel(f)}|{_stamp(f)}'.encode()).hexdigest()[:20]
    c = CACHE / 'env' / f'{key}.json'
    if c.exists():
        try:
            return json.loads(c.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            pass
    try:
        env = list(base64.b64decode(measure_sound(f, 96)['env']))
    except Exception:  # noqa: BLE001 - unreadable: a flat line
        env = []
    _atomic_write(c, json.dumps(env))
    return env


def _fmt_s(s):
    if s is None:
        return ''
    s = float(s)
    return f'{s:.1f} s' if s < 60 else f'{int(s // 60)}:{int(round(s % 60)):02d}'


def preview(entries, path=None, title=None, tile=168, cols=6):
    """A JPEG of the entries: pictures as a contact sheet (still frame of animations, marked), sounds as rows with
    their loudness curve, length and where the peak is. Returns its path (cache/assets/sheets/<key>.jpg)."""
    from PIL import Image, ImageDraw
    entries = [index().by_id.get(e, e) if isinstance(e, str) else e for e in entries]
    entries = [e for e in entries if isinstance(e, dict) and 'kind' in e]
    key = hashlib.sha1(json.dumps([[e['id'], e.get('file')] for e in entries] + [title, tile, cols],
                                  ensure_ascii=False).encode()).hexdigest()[:20]
    out = Path(path) if path else CACHE / 'sheets' / f'{key}.jpg'
    if out.exists() and not path:
        return str(out)
    vis = [e for e in entries if e['kind'] in VISUAL]
    snd = [e for e in entries if e['kind'] in SOUND]
    cols = max(1, min(cols, len(vis))) if vis else cols
    width = max(cols * tile, 760 if snd else 0, 300)
    cap = 34
    rows_v = (len(vis) + cols - 1) // cols if vis else 0
    row_h = 58
    head = 30 if title else 0
    height = head + rows_v * (tile + cap) + len(snd) * row_h + 8
    sheet = Image.new('RGB', (width, max(height, 60)), (34, 38, 44))
    d = ImageDraw.Draw(sheet)
    f_cap, f_small, f_head = _font(13), _font(11), _font(16, bold=True)
    if title:
        d.text((10, 6), str(title)[:110], font=f_head, fill=(240, 236, 228))
    if vis:
        thumbs = _thumbs(vis, tile - 16)
        for i, e in enumerate(vis):
            x, y = (i % cols) * tile, head + (i // cols) * (tile + cap)
            d.rectangle([x + 3, y + 3, x + tile - 4, y + tile - 4], fill=(60, 70, 80))
            im = thumbs.get(e['id'])
            if im is not None:
                sheet.paste(im, (x + (tile - im.width) // 2, y + (tile - im.height) // 2), im)
            if e.get('animated'):
                d.polygon([(x + tile - 26, y + 9), (x + tile - 26, y + 25), (x + tile - 12, y + 17)],
                          fill=(200, 101, 59))
            if e.get('credit'):
                d.text((x + 8, y + 6), 'credit', font=f_small, fill=(255, 210, 120))
            label = e['id'] if len(e['id']) <= 26 else e['id'][:25] + '…'
            d.text((x + 6, y + tile - 2), label, font=f_cap, fill=(236, 232, 224))
            sub = ' · '.join(x for x in (e.get('group') or e.get('category') or '',
                                         _fmt_s(e.get('duration_s')) if e.get('animated') else '') if x)
            d.text((x + 6, y + tile + 14), str(sub)[:30], font=f_small, fill=(160, 170, 180))
    y0 = head + rows_v * (tile + cap)
    for j, e in enumerate(snd):
        y = y0 + j * row_h
        d.rectangle([4, y + 3, width - 5, y + row_h - 3], fill=(48, 54, 62))
        d.text((12, y + 7), (e['id'] if len(e['id']) <= 48 else e['id'][:47] + '…'), font=f_cap,
               fill=(236, 232, 224))
        info = _fmt_s(e.get('duration_s'))
        if e.get('peak_s') is not None:
            info += f"  peak {e['peak_s']:.2f} s"
        if e['kind'] == 'music' and e.get('group'):
            info += f"  {e.get('group')}"
        d.text((12, y + 29), info, font=f_small, fill=(160, 170, 180))
        env = _env_of(e)
        wx0, wx1, mid, amp = 330, width - 14, y + row_h // 2, row_h // 2 - 8
        d.line([wx0, mid, wx1, mid], fill=(80, 90, 100))
        if env:
            step = (wx1 - wx0) / max(1, len(env))
            for k, v in enumerate(env):
                hh = max(1, v * amp / 255)
                xx = wx0 + k * step
                d.rectangle([xx, mid - hh, xx + max(1.0, step - 1), mid + hh], fill=(42, 133, 151))
            if e.get('peak_s') is not None and e.get('duration_s'):
                px_ = wx0 + (wx1 - wx0) * float(e['peak_s']) / float(e['duration_s'])
                d.line([px_, y + 6, px_, y + row_h - 6], fill=(200, 101, 59), width=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return str(out)


def strip(ref, count=6, px=200):
    """A filmstrip of an animated asset (count frames across its length) as a JPEG; a still asset as one tile."""
    from PIL import Image, ImageDraw
    e = find(ref)
    if not e.get('animated'):
        return preview([e])
    f = abspath(e['file'])
    info = lottie_info(f)
    frames = lottie_frames(f, 30.0, px)
    picks = [frames[int(round(k * (len(frames) - 1) / max(1, count - 1)))] for k in range(count)]
    ims = []
    for p in picks:
        with Image.open(p) as src:
            ims.append(src.convert('RGBA'))
    w, h = ims[0].size
    sheet = Image.new('RGB', (w * count, h + 24), (34, 38, 44))
    d = ImageDraw.Draw(sheet)
    for k, im in enumerate(ims):
        bg = Image.new('RGBA', im.size, (60, 70, 80, 255))
        bg.alpha_composite(im)
        sheet.paste(bg.convert('RGB'), (k * w, 0))
        d.text((k * w + 6, h + 4), f"{k * info['duration_s'] / max(1, count - 1):.1f} s", font=_font(12),
               fill=(200, 200, 200))
    out = CACHE / 'sheets' / f"strip-{hashlib.sha1((e['id'] + _stamp(f)).encode()).hexdigest()[:16]}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return str(out)


# ------------------------------------------------------------------ overview

def _dir_size(rels):
    total, seen = 0, set()
    for rel in rels:
        p = abspath(rel)
        if p and p not in seen:
            seen.add(p)
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


def stats(sizes=False):
    """What is in the library: per kind and per source the count, licence, whether it may ship, the credit owed
    (and with sizes=True the bytes on disk)."""
    idx = index()
    kinds, srcs = {}, {}
    for e in idx.entries:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        s = srcs.setdefault(e['source'], {'count': 0, 'kinds': {}})
        s['count'] += 1
        s['kinds'][e['kind']] = s['kinds'].get(e['kind'], 0) + 1
    for name, s in srcs.items():
        meta = idx.sources.get(name, {})
        s.update({k: meta[k] for k in ('title', 'licence', 'ship', 'credit', 'url', 'version') if k in meta})
        if sizes:
            files = []
            for e in idx.entries:
                if e['source'] == name:
                    files.extend((e.get('styles') or {}).values() or [e.get('file')])
            s['bytes'] = _dir_size(files)
    return {'total': len(idx.entries), 'kinds': kinds, 'sources': srcs}


if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # the app reads UTF-8 whatever the code page
    if sys.argv[1:2] == ['credits'] and len(sys.argv) == 3:
        print(json.dumps(project_credits(sys.argv[2]), ensure_ascii=False))
        sys.exit(0)
    print('usage: python assets.py credits <project.mlt>   the credit lines a project owes, as JSON [{line, assets}]')
    sys.exit(2)
