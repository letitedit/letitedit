"""On-demand songs and stock video and photos, with a personal Pixabay key or the supporter server.

    key_status() / save_key(key)      the keys on this PC, a free account's and a supporter's: which tier, and adding one (the Settings line calls these)
    catalogue()                       the on-demand songs: a copy kept on this PC, refreshed at most once a day
    search_songs(query, ...)          lines for letitedit_library, marked as on demand; None when no key is active
    song_path('ondemand:<id>')        the song on this PC: downloaded once, checked against its SHA-256, kept
    stock_search / stock_fetch / stock_preview     what letitedit_stock runs; a chosen file comes straight from its source
    owes(paths)                       what a video owes for what came from here, as assets.credits gives it

With a personal Pixabay key, stock requests go directly to Pixabay, with results cached for 24 hours. The supporter
server remains the source for on-demand songs and other stock. With no applicable key, nothing contacts a service.
What's already on this PC stays usable whatever happens to the key. Everything is
kept under on-demand/ in the install. With no internet or the server down, nothing here raises in a search: it says so in a note and the
tools carry on with what's on the PC. The server is told a key (when its pass runs low), search words and which song or item, and nothing else.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
DEFAULT_SERVER = 'https://media.letitedit.app'
USER_AGENT = 'letitedit/1.0 (+https://letitedit.app)'
CHUNK = 1 << 20
ASK_TIMEOUT_S = 8
FILE_TIMEOUT_S = 60
CATALOGUE_AGE_S = 86400
PASS_RENEW_S = 2 * 86400                         # a pass lasts 7 days, or 90 for a free key: ask for a new one when under 2 are left
KEY_RECHECK_S = 86400                            # a key the server refused isn't asked about again for a day
RETRY_AFTER_FAIL_S = 300
MAX_STOCK_BYTES = 2 * 1024 ** 3
SONG_REF = re.compile(r'^ondemand:([0-9a-f]{16})$')
STOCK_REF = re.compile(r'^(pexels|pixabay):(photo|video):([0-9]{1,20})$')
STOCK_HOSTS = ('pexels.com', 'pixabay.com')     # where a stock file may come from, redirects included
LOCAL_FILES_OK = False                          # the tests' stand-in server only
LICENCE = {'pexels': ('Pexels License', 'https://www.pexels.com/license/'),
           'pixabay': ('Pixabay Content License', 'https://pixabay.com/service/license-summary/')}
NOT_ACTIVE = "Stock search and on-demand songs are part of the supporter subscription and aren't active here."
STILL_WORKS = 'Written music, the songs on this PC, code-drawn scenes and the person\'s own files all still work.'

_down_until = 0.0


class Unavailable(RuntimeError):
    """The server, or a file it named, can't be had just now; the message is in plain words."""


class NotActive(Unavailable):
    """No supporter's key on this PC that's active: none at all, only a free one, or one that has ended."""


def home():
    return Path(os.environ.get('LETITEDIT_ON_DEMAND') or ROOT / 'on-demand')


def server():
    return (os.environ.get('LETITEDIT_MEDIA_SERVER') or DEFAULT_SERVER).rstrip('/')


def _key_file():
    return Path(os.environ.get('LETITEDIT_ACCOUNT_FILE') or ROOT / 'appdata' / 'account.json')


def _keys():
    """The keys on this PC. A supporter keeps their free key too, so when a subscription ends the free set still opens."""
    return [str(k).strip() for k in (_read_json(_key_file()) or {}).get('keys') or [] if str(k).strip()]


def save_key(key):
    """Adds a key and says what it opens: 'free', 'supporter', 'not active' (and it isn't kept) or 'cannot check' (kept, to try later). An empty one clears them all.
    Kept in its own file: never in a project or a log."""
    key = (key or '').strip()
    if not key:
        _write_json(_key_file(), {'keys': []})
        _pass_file().unlink(missing_ok=True)
        return 'none'
    _forget(key)
    try:
        tier = _row(key).get('tier') or 'not active'
    except NotActive:
        return 'not active'
    except Unavailable:
        tier = 'cannot check'
    _write_json(_key_file(), {'keys': [k for k in _keys() if k != key] + [key]})
    return tier


def key_status():
    """'none' (no key, and nothing was contacted), 'supporter', 'free', 'not active' or 'cannot check' (no connection and no pass; nothing's wrong with what's on this PC)."""
    keys = _keys()
    if not keys:
        return 'none'
    found = set()
    for key in keys:
        try:
            found.add(_row(key).get('tier'))
        except NotActive:
            found.add('not active')
        except Unavailable:
            found.add('cannot check')
    return next(t for t in ('supporter', 'free', 'cannot check', 'not active') if t in found)


def _pass_file():
    return home() / 'pass.json'


def _mark(key):
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _save_row(key, row):
    rows = _read_json(_pass_file()) or {}
    _write_json(_pass_file(), {**rows, _mark(key): row})


def _forget(key):
    rows = _read_json(_pass_file()) or {}
    if rows.pop(_mark(key), None) is not None:
        _write_json(_pass_file(), rows)


def _row(key):
    """This key's pass, {pass, expires, tier}, asked for when the one here is near its end. If the check can't be made, the pass here is used while it lasts, so
    an outage stops nobody. NotActive when the server refuses the key, and that's remembered for a day."""
    row = (_read_json(_pass_file()) or {}).get(_mark(key)) or {}
    if time.time() - (row.get('refused') or 0) < KEY_RECHECK_S:
        raise NotActive(NOT_ACTIVE)
    left = (row.get('expires') or 0) - time.time()
    if left > PASS_RENEW_S:
        return row
    try:
        status, _h, body = _ask('/v1/pass', data=json.dumps({'key': key}).encode(), headers={'Content-Type': 'application/json'})
        answer = json.loads(body) if status in (200, 403) else {}
    except (Unavailable, ValueError):
        status, answer = 0, {}
    if status == 200 and answer.get('pass'):
        row = {'pass': answer['pass'], 'expires': answer.get('expires') or 0, 'tier': answer.get('tier')}
        _save_row(key, row)
        return row
    if status == 403:
        _save_row(key, {'refused': time.time()})
        raise NotActive(NOT_ACTIVE)
    if left > 0:
        return row
    raise Unavailable('The account key could not be checked just now.')


def _pass():
    """A current supporter's pass. Everything this module fetches needs one; a free key's pass opens only the free set, so it's never sent here."""
    waiting = None
    for key in _keys():
        try:
            row = _row(key)
        except NotActive:
            continue
        except Unavailable as ex:
            waiting = ex
            continue
        if row.get('tier') == 'supporter':
            return row['pass']
    if waiting:
        raise waiting
    raise NotActive(NOT_ACTIVE)


def _gated(path, params=None, headers=None):
    """_ask with the pass. A pass the server no longer takes is dropped, and a new one asked for once."""
    answer = _ask(path, params, {**(headers or {}), 'Authorization': 'Bearer ' + _pass()})
    if answer[0] in (401, 403):
        _pass_file().unlink(missing_ok=True)
        answer = _ask(path, params, {**(headers or {}), 'Authorization': 'Bearer ' + _pass()})
    return answer


def _ask(path, params=None, headers=None, timeout=ASK_TIMEOUT_S, data=None):
    """(status, headers, body) from our server. An HTTP error comes back as its status; no connection raises Unavailable,
    and after that the server isn't tried again for five minutes, so a long job doesn't wait on it each time."""
    global _down_until
    if time.time() < _down_until:
        raise Unavailable('The letitedit server could not be reached a moment ago.')
    url = server() + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as ex:
        body = ex.read()
        ex.close()
        if (ex.code >= 500 and path != '/v1/pass') or (ex.code == 429 and b'{' not in body[:1]):   # not our Worker's answer: Cloudflare's own daily limit page, say
            _down_until = time.time() + RETRY_AFTER_FAIL_S
        return ex.code, dict(ex.headers.items()), body
    except (OSError, ValueError) as ex:
        _down_until = time.time() + RETRY_AFTER_FAIL_S
        raise Unavailable('The letitedit server could not be reached.') from ex


def _ask_json(path, params=None):
    status, _h, body = _gated(path, params)
    try:
        data = json.loads(body)
    except ValueError as ex:
        raise Unavailable(f'The letitedit server gave an answer that could not be read (status {status}).') from ex
    return status, data


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- the catalogue

def catalogue():
    """(songs, note): the copy on this PC, refreshed when over a day old. note says when the list is old or missing."""
    copy, meta = home() / 'catalogue.json', home() / 'catalogue.meta.json'
    known = _read_json(meta) or {}
    data = _read_json(copy)
    if data and time.time() - known.get('checked', 0) < CATALOGUE_AGE_S:
        return data.get('songs') or [], None
    try:
        status, headers, body = _gated('/v1/music/catalogue', headers={'If-None-Match': known['etag']} if data and known.get('etag') else None)
        if status == 304 and data:
            _write_json(meta, {**known, 'checked': time.time()})
            return data.get('songs') or [], None
        if status != 200:
            raise Unavailable(f'The letitedit server has no song list just now (status {status}).')
        fresh = json.loads(body)
        _write_json(copy, fresh)
        _write_json(meta, {'etag': next((v for k, v in headers.items() if k.lower() == 'etag'), ''), 'checked': time.time()})
        return fresh.get('songs') or [], None
    except NotActive:
        raise
    except (Unavailable, ValueError) as ex:
        if data:
            return data.get('songs') or [], f'{ex} This is the list from the last time it was reached; a song not yet on this PC can\'t come down until it is back.'
        return [], f'{ex} On-demand songs can\'t be listed. {STILL_WORKS}'


def _song_file(sid):
    return home() / 'music' / f'ondemand-song-{sid}.mp3'


def _song_line(s):
    bpm = f"{s['bpm']} bpm (catalogue), " if s.get('bpm') else ''
    facts = '; '.join(x for x in (s.get('genre'), s.get('mood')) if x)
    here = _song_file(s['id'])
    where = f'on this PC: {here.as_posix()}' if here.is_file() else f"on demand, {s.get('bytes', 0) / 1e6:.1f} MB, comes down when used"
    return f"ondemand:{s['id']}  |  {bpm}{s.get('length') or '?'}  |  {facts}  |  {s.get('artist') or ''}  |  {s.get('licence') or ''}  |  {where}"


def search_songs(query='', offset=0, limit=40, bpm_min=None, bpm_max=None, min_length_s=None, max_length_s=None):
    """The on-demand songs that match, with letitedit_library's rules: the most of the query's words first, and a song with no
    tempo or length is left out of a range on it. {'total', 'files': [lines]} and 'note' when there's something to say. None, having
    contacted nothing, when there's no key; None too with only a free key, or once a supporter's has ended."""
    if not _keys():
        return None
    try:
        _pass()
    except NotActive:
        return None
    except Unavailable:
        pass                                # offline: the copy here, with a note, below
    songs, note = catalogue()
    words = [w for w in (query or '').casefold().split() if w]
    found = []
    for s in songs:
        text = ' '.join(str(s.get(k) or '') for k in ('title', 'artist', 'album', 'genre', 'mood')).casefold()
        hits = sum(w in text for w in words)
        if words and not hits:
            continue
        b, d = s.get('bpm'), s.get('duration_s')
        if ((bpm_min is not None or bpm_max is not None) and not b) or (bpm_min is not None and b < bpm_min) or \
           (bpm_max is not None and b > bpm_max) or ((min_length_s is not None or max_length_s is not None) and d is None) or \
           (min_length_s is not None and d < min_length_s) or (max_length_s is not None and d > max_length_s):
            continue
        found.append((hits, s))
    found.sort(key=lambda x: -x[0])
    offset, limit = max(0, offset), max(1, min(100, limit))
    out = {'total': len(found), 'files': [_song_line(s) for _h, s in found[offset:offset + limit]]}
    if note:
        out['note'] = note
    return out


# ---------------------------------------------------------------- getting a file

class _HostCheck(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _stock_url_ok(newurl):
            raise Unavailable('A stock file pointed somewhere other than its source, so it was not downloaded.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _stock_url_ok(url):
    u = urllib.parse.urlparse(url)
    host = (u.hostname or '').lower()
    if LOCAL_FILES_OK and host == '127.0.0.1':
        return True
    return u.scheme == 'https' and any(host == h or host.endswith('.' + h) for h in STOCK_HOSTS)


def _download(url, target, opener=None, sha256=None, nbytes=None, max_bytes=None, check=None, headers=None):
    """url into target, whole or not at all: size, hash and first bytes are checked before it takes the name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    h, got = hashlib.sha256(), 0
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    try:
        with (opener.open if opener else urllib.request.urlopen)(req, timeout=FILE_TIMEOUT_S) as r, open(part, 'wb') as out:
            head = b''
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                head = head or b[:32]
                got += len(b)
                if max_bytes and got > max_bytes:
                    raise Unavailable(f'That file is over {max_bytes / 1e9:.0f} GB, so it was not kept.')
                out.write(b)
                h.update(b)
        if (nbytes is not None and got != nbytes) or (sha256 and h.hexdigest() != sha256):
            raise Unavailable('The download did not match what the server said it would be, so it was not kept.')
        if check and not check(head):
            raise Unavailable('The download was not the kind of file expected, so it was not kept.')
        os.replace(part, target)
        return got
    except (OSError, ValueError) as ex:
        raise Unavailable('The download did not finish, so nothing was kept. Try again when the connection is back.') from ex
    finally:
        part.unlink(missing_ok=True)


def _is_video(head):
    return head[4:8] == b'ftyp'


def _is_picture(head):
    return head[:3] == b'\xff\xd8\xff' or head[:8] == b'\x89PNG\r\n\x1a\n' or (head[:4] == b'RIFF' and head[8:12] == b'WEBP')


# ---------------------------------------------------------------- songs

def fetch_song(ref):
    """A song from the catalogue, on this PC: {path, title, artist, licence, credit, downloaded_bytes (when it came down now)}.
    Raises Unavailable, in plain words, when it can't be had."""
    m = SONG_REF.match(str(ref or ''))
    if not m:
        raise ValueError('An on-demand song is named as letitedit_library lists it: ondemand:<id>')
    sid = m.group(1)
    target = _song_file(sid)
    car = target.with_name(target.name + '.json')
    reply = {}
    if not target.is_file():
        _pass()
        songs, note = catalogue()
        s = next((x for x in songs if x.get('id') == sid), None)
        if not s:
            raise Unavailable((note or 'That song is not in the catalogue.') + ' ' + STILL_WORKS)
        try:
            got = _download(server() + f'/v1/music/song/{sid}', target, sha256=s.get('sha256'), nbytes=s.get('bytes'), headers={'Authorization': 'Bearer ' + _pass()})
        except NotActive:
            raise
        except (Unavailable, OSError) as ex:
            raise Unavailable(f"Song '{s.get('title')}' could not be downloaded: {ex} {STILL_WORKS}") from ex
        _write_json(car, {'ref': ref, 'kind': 'song', 'title': s.get('title'), 'artist': s.get('artist'), 'licence': s.get('licence'),
                          'licence_url': s.get('licence_url'), 'origin_url': s.get('origin_url'), 'beats_key': s.get('beats_key')})
        reply = {'downloaded_bytes': got, 'download_note': f'This song came down once ({got / 1e6:.1f} MB) and stays on this PC.'}
        _fetch_beats(sid, target)
    row = _read_json(car) or {'ref': ref}
    return {'ref': ref, 'path': str(target), **{k: row.get(k) for k in ('title', 'artist', 'licence', 'licence_url', 'origin_url')},
            'came_from': 'letitedit\'s on-demand music', **reply}


def _fetch_beats(sid, target):
    """The beat finder's answer for this song, when the server has it, put where music_sync.beat_this looks: then the first use takes no
    measuring. A song without one is measured on this PC, about 10 seconds, as any song is."""
    try:
        status, _h, body = _gated(f'/v1/music/beats/{sid}')
        if status != 200:
            return
        data = json.loads(body)
        import letitedit.sound.beat_finder as beat_finder
        import letitedit.timing.music_sync as music_sync
        if data.get('beat_act') and data.get('model') == beat_finder.MODEL_NAME:
            _write_json(music_sync.CACHE / 'beat-finder' / f'{music_sync._file_key(str(target))}-{beat_finder.MODEL_NAME}.json', data)
    except Exception:  # noqa: BLE001 - the beats are a head start; a song never fails for want of them
        pass


def song_path(ref):
    return fetch_song(ref)['path']


# ---------------------------------------------------------------- stock

def _pixabay_key():
    path = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'letitedit' / 'stock-keys.json'
    value = (_read_json(path) or {}).get('pixabay')
    if not value:
        return None
    try:
        from letitedit.pictures.image_gen import _dpapi
        return _dpapi(base64.b64decode(value), False).decode('utf-8').strip() or None
    except Exception:
        raise Unavailable('The saved Pixabay key could not be unlocked on this Windows account.') from None


def _pixabay_request(kind, params):
    key = _pixabay_key()
    if not key:
        raise Unavailable('No personal Pixabay key is saved on this PC.')
    digest = hashlib.sha256(json.dumps({'kind': kind, **params}, sort_keys=True).encode()).hexdigest()
    folder = home() / 'pixabay-api'
    cached = folder / (digest + '.json')
    row = _read_json(cached) or {}
    if time.time() - row.get('checked', 0) < 86400:
        return row['data']
    folder.mkdir(parents=True, exist_ok=True)
    guard = folder / 'request.lock'
    deadline = time.monotonic() + ASK_TIMEOUT_S
    while True:
        handle = None
        try:
            import msvcrt
            handle = open(guard, 'a+b')
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if handle is not None:
                handle.close()
            if time.monotonic() >= deadline:
                raise Unavailable('Another Pixabay request is still finishing; try again shortly.') from None
            time.sleep(0.1)
    try:
        row = _read_json(cached) or {}
        if time.time() - row.get('checked', 0) < 86400:
            return row['data']
        rate_file = folder / 'requests.json'
        recent = [stamp for stamp in (_read_json(rate_file) or {}).get('times', []) if time.time() - stamp < 60]
        if len(recent) >= 95:
            raise Unavailable('Pixabay is resting for a minute (the personal API allowance).')
        _write_json(rate_file, {'times': [*recent, time.time()]})
        endpoint = 'https://pixabay.com/api/videos/' if kind == 'video' else 'https://pixabay.com/api/'
        request = urllib.request.Request(endpoint + '?' + urllib.parse.urlencode({**params, 'key': key}),
                                         headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=ASK_TIMEOUT_S) as response:
                data = json.loads(response.read(8 * 1024 * 1024))
            if not isinstance(data, dict) or not isinstance(data.get('hits'), list):
                raise ValueError('Malformed Pixabay answer')
        except urllib.error.HTTPError as error:
            raise Unavailable(f'Pixabay refused the request (HTTP {error.code}); check the saved key or try later.') from None
        except (OSError, ValueError):
            raise Unavailable('Pixabay could not be reached or returned an unreadable answer.') from None
        _write_json(cached, {'checked': time.time(), 'data': data})
        return data
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def _pixabay_row(hit, kind):
    creator = str(hit.get('user') or '')
    if kind == 'video':
        files = [{key: value.get(key) for key in ('url', 'width', 'height')} for value in (hit.get('videos') or {}).values()]
        thumb = next((value.get('thumbnail') for value in (hit.get('videos') or {}).values() if value.get('thumbnail')), None)
    else:
        files = [{'url': hit.get('largeImageURL') or hit.get('webformatURL'),
                  'width': hit.get('imageWidth'), 'height': hit.get('imageHeight')}]
        thumb = hit.get('previewURL')
    largest = max(files, key=lambda value: (value.get('width') or 0) * (value.get('height') or 0), default={})
    return {'ref': f'pixabay:{kind}:{hit["id"]}', 'kind': kind, 'title': hit.get('tags') or '',
            'width': largest.get('width'), 'height': largest.get('height'), 'duration_s': hit.get('duration'),
            'creator': creator, 'creator_url': f'https://pixabay.com/users/{creator}-{hit.get("user_id", "")}/',
            'credit': f'{creator} / Pixabay', 'page_url': hit.get('pageURL'), 'thumb': thumb, 'files': files}


def _pixabay_search(query, kind, orientation, page, limit):
    params = {'q': query, 'page': max(1, int(page)), 'per_page': max(3, min(200, int(limit)))}
    if kind != 'video':
        params['image_type'] = 'photo'
        if orientation:
            params['orientation'] = orientation
    data = _pixabay_request(kind, params)
    rows = [_pixabay_row(hit, kind) for hit in data.get('hits', [])]
    if orientation:
        rows = [row for row in rows if (row['width'] >= row['height']) == (orientation == 'horizontal')]
    return 200, {'query': query, 'results': rows[:limit], 'sources': [
        {'name': 'Pixabay', 'line': 'Results from Pixabay', 'url': 'https://pixabay.com/'}]}

def _sources_note(sources):
    waits = []
    for s in sources:
        if s.get('status') == 'resting':
            waits.append(f"{s.get('name')} is resting for about {max(1, round((s.get('retry_after_s') or 60) / 60))} min (the shared allowance)")
        elif s.get('status') == 'unavailable':
            waits.append(f"{s.get('name')} can't be asked just now")
    return '; '.join(waits)


def _stock_line(r):
    size = f"{r.get('width')}x{r.get('height')}"
    what = f"video, {r.get('duration_s')} s, {size}" if r.get('kind') == 'video' else f'photo, {size}'
    if r.get('ai_generated'):
        what += ', AI-made'
    return f"{r.get('ref')}  |  {what}  |  {r.get('title') or ''}  |  {r.get('credit') or ''}  |  {r.get('page_url') or ''}"


def stock_search(query, kind='video', source='all', orientation=None, min_seconds=None, max_seconds=None, page=1, limit=15):
    params = {'kind': kind, 'q': query, 'source': source, 'page': page, 'per_page': limit}
    if orientation:
        params['orientation'] = orientation
    try:
        if source in ('all', 'pixabay') and _pixabay_key():
            status, data = _pixabay_search(query, kind, orientation, page, limit)
        else:
            status, data = _ask_json('/v1/stock/search', params)
    except NotActive:
        return {'available': False, 'results': [], 'note': NOT_ACTIVE}
    except Unavailable as ex:
        return {'available': False, 'results': [], 'note': f'{ex} Nothing was searched. {STILL_WORKS}'}
    if status != 200:
        return {'available': False, 'results': [], 'note': f"{data.get('message') or 'Stock search said no.'} {STILL_WORKS}"}
    rows = data.get('results') or []
    if kind == 'video':
        rows = [r for r in rows if (min_seconds is None or (r.get('duration_s') or 0) >= min_seconds) and
                (max_seconds is None or (r.get('duration_s') or 0) <= max_seconds)]
    sources = data.get('sources') or []
    if not sources:
        return {'available': False, 'results': [], 'note': f'Stock search has nothing to ask just now. {STILL_WORKS}'}
    out = {'available': True, 'query': data.get('query'), 'kind': kind, 'page': page, 'results': [_stock_line(r) for r in rows],
           'provided_by': [{'line': s.get('line'), 'url': s.get('url')} for s in sources if s.get('line')]}
    said = _sources_note(sources)
    if said:
        out['note'] = said + ('' if rows else f'. {STILL_WORKS}')
    return out


def _stock_item(ref):
    m = STOCK_REF.match(str(ref or ''))
    if not m:
        raise ValueError('A stock item is named as letitedit_stock lists it: pixabay:video:123')
    source, kind, sid = m.groups()
    if source == 'pixabay' and _pixabay_key():
        hits = _pixabay_request(kind, {'id': sid}).get('hits') or []
        if not hits:
            raise Unavailable('That Pixabay item is no longer available.')
        return source, kind, sid, _pixabay_row(hits[0], kind)
    status, data = _ask_json('/v1/stock/item', {'source': source, 'kind': kind, 'id': sid})
    if status != 200 or not data.get('item'):
        raise Unavailable(data.get('message') or 'That item can\'t be had just now.')
    return source, kind, sid, data['item']


def _pick_file(files, short_side):
    """The smallest file at least short_side on its short side, else the largest there is."""
    def side(f):
        sizes = [v for v in (f.get('width'), f.get('height')) if v]
        return min(sizes) if sizes else 0
    usable = [f for f in files if f.get('url') and _stock_url_ok(f['url'])]
    big = sorted((f for f in usable if side(f) >= short_side), key=side)
    return big[0] if big else max(usable, key=side, default=None)


def stock_fetch(ref, short_side=1080):
    """One stock item on this PC, once: {path, credit, ...}. A dict with available False and a note when it can't be had."""
    try:
        m = STOCK_REF.match(str(ref or ''))
        if not m:
            raise ValueError('A stock item is named as letitedit_stock lists it: pixabay:video:123')
        source, kind, sid = m.groups()
        folder = home() / 'stock'
        stem = f'stock-{source}-{kind}-{sid}'
        have = next((f for f in sorted(folder.glob(stem + '.*')) if f.suffix != '.json'), None) if folder.is_dir() else None
        car = folder / (stem + '.json')
        if have and car.is_file():
            return {**(_read_json(car) or {}), 'path': str(have), 'already_on_this_pc': True}
        source, kind, sid, item = _stock_item(ref)
        chosen = _pick_file(item.get('files') or [], short_side)
        if not chosen:
            raise Unavailable('That item has no file that can be downloaded.')
        suffix = '.mp4' if kind == 'video' else (Path(urllib.parse.urlparse(chosen['url']).path).suffix.lower() if Path(urllib.parse.urlparse(chosen['url']).path).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg')
        target = folder / (stem + suffix)
        opener = urllib.request.build_opener(_HostCheck)
        got = _download(chosen['url'], target, opener=opener, max_bytes=MAX_STOCK_BYTES, check=_is_video if kind == 'video' else _is_picture)
        name, url = LICENCE[source]
        row = {'ref': ref, 'kind': 'stock', 'source': source, 'media': kind, 'title': item.get('title') or '', 'creator': item.get('creator') or '',
               'creator_url': item.get('creator_url') or '', 'page_url': item.get('page_url') or '', 'credit': item.get('credit') or '',
               'licence': name, 'licence_url': url, 'width': chosen.get('width'), 'height': chosen.get('height'), 'duration_s': item.get('duration_s'), 'ai_generated': bool(item.get('ai_generated'))}
        _write_json(car, row)
        return {**row, 'path': str(target), 'downloaded_bytes': got, 'download_note': f'This came down once ({got / 1e6:.1f} MB) straight from its source and stays on this PC.'}
    except NotActive:
        return {'available': False, 'ref': ref, 'note': NOT_ACTIVE}
    except Unavailable as ex:
        return {'available': False, 'ref': ref, 'note': f'{ex} {STILL_WORKS}'}


def stock_preview(refs):
    """The small pictures of these items, on this PC, to look at before choosing: {ref: path}, and a note for any that couldn't be had."""
    try:
        if not _pixabay_key():
            _pass()
    except NotActive:
        return {'previews': {}, 'note': NOT_ACTIVE}
    except Unavailable as ex:
        return {'previews': {}, 'note': str(ex)}
    out, missed = {}, []
    for ref in (refs or [])[:12]:
        try:
            _source, _kind, _sid, item = _stock_item(ref)
            if not item.get('thumb') or not _stock_url_ok(item['thumb']):
                raise Unavailable('no small picture')
            target = home() / 'previews' / (str(ref).replace(':', '-') + '.jpg')
            if not target.is_file():
                _download(item['thumb'], target, opener=urllib.request.build_opener(_HostCheck), max_bytes=20 * 1024 ** 2, check=_is_picture)
            out[ref] = str(target)
        except (Unavailable, ValueError):
            missed.append(ref)
    reply = {'previews': out}
    if missed:
        reply['note'] = 'No small picture for: ' + ', '.join(map(str, missed))
    return reply


# ---------------------------------------------------------------- what a video owes

def owes(paths):
    """Lines for each on-demand song and stock item among these files, as assets.credits gives them: [{line, assets: [ref]}]."""
    lines = {}
    for p in paths or []:
        text = str(p)
        name = Path(text).name
        if not os.path.isabs(text) or not name.startswith(('ondemand-song-', 'stock-')):
            continue
        car = Path(text).with_name(name + '.json') if name.startswith('ondemand-song-') else Path(text).with_suffix('.json')
        row = _read_json(car)
        if not row or not row.get('ref'):
            continue
        if row.get('kind') == 'song':
            line = f"Music: {row.get('title')} by {row.get('artist')}, {row.get('licence')}: no credit required ({row.get('origin_url')})"
        else:
            line = f"{row.get('credit')}, {row.get('licence')}: credit not required, appreciated ({row.get('page_url')})"
        lines.setdefault(line, set()).add(row['ref'])
    return [{'line': k, 'assets': sorted(v)} for k, v in lines.items()]


# ---------------------------------------------------------------- the tool

DOC = """Search and download stock video and photos. Works with an active supporter key; without one, each action returns available False and a note, and contacts nothing.

action:
- search: query (words), kind ('video' or 'photo'), orientation ('landscape', 'portrait', 'square'), min_seconds and max_seconds (video, applied to this page), page,
  limit (up to 40). Each line: ref, kind with length and size ('AI-made' when the source marks it so), words about it, credit, its page.
  provided_by names the sources shown. note says when a source is resting or can't be asked; available False means nothing was searched.
- preview: refs (up to 12). The small picture of each on this PC, for letitedit_look or reading.
- fetch: ref, short_side (pixels on the short side, default 1080: the smallest file at least that big, else the largest). The file comes down once,
  straight from the source, and stays on this PC. Returns path (usable as a clip), credit, licence, page_url. available False and a note when it can't be had.

Licence facts. Free for commercial use inside an edited work; credit isn't required. Not allowed: selling or giving the file away unaltered, or implying that a person or
brand shown endorses something. letitedit_export_job and letitedit_review_bundle list what a video used."""


def register(mcp):
    @mcp.tool()
    def letitedit_stock(action: str = 'search', query: str = '', kind: str = 'video', orientation: str | None = None,
                        min_seconds: float | None = None, max_seconds: float | None = None, page: int = 1, limit: int = 15,
                        ref: str | None = None, refs: list[str] | None = None, short_side: int = 1080) -> dict:
        if action == 'search':
            if kind not in ('video', 'photo'):
                raise ValueError("kind is 'video' or 'photo'")
            if not query.strip():
                raise ValueError('Say what to search for (query)')
            return stock_search(query, kind, 'all', orientation, min_seconds, max_seconds, page, limit)
        if action == 'preview':
            return stock_preview(refs or ([ref] if ref else []))
        if action == 'fetch':
            return stock_fetch(ref, short_side)
        raise ValueError("action is 'search', 'preview' or 'fetch'")

    letitedit_stock.__doc__ = DOC
