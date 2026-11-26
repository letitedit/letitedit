"""Real pictures of named things (a logo or app, a person, a place, a book, a product, an animal, a food), found in
open sources that need no key or sign-up and fetched into the video's own folder, each with a record of where it came
from. T173.

Sources (each asked politely: one request at a time, a User-Agent naming letitedit, a pause between requests to one
host, Retry-After honoured):
  wikipedia    the page image of a Wikipedia article (people, places, logos, products), with the file's licence
  commons      Wikimedia Commons files (most logos as SVG, drawn to PNG by Wikimedia's own thumbnailer)
  openverse    openly licensed pictures indexed by Openverse (Flickr, museums...), with the attribution it gives
  openlibrary  book covers from Open Library, by cover id
  url          a page or picture address the AI found itself: a picture is taken as is; a page gives its
               og:image / twitter:image picture

What it never does: download anything but a picture (the bytes are checked: JPEG, PNG, GIF, WebP, BMP, TIFF; SVG only
through Wikimedia's PNG drawing), more than MAX_BYTES, a picture over MAX_PIXELS, or write anywhere but
<project stem>.letitedit/pictures beside the project (or <folder>/.letitedit/pictures). It asks only public addresses
(no localhost or private network) and runs nothing it downloads.

    python real_pictures.py search "Google Chrome" [kind]
    python real_pictures.py fetch <ref or url> <project.mlt>
    python real_pictures.py credits <project.mlt>
"""
from __future__ import annotations

import html
import io
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = 'letitedit/1.0 (+https://letitedit.app; reference pictures on a user request)'
MAX_BYTES = 25 * 1024 * 1024          # one picture file
MAX_PAGE_BYTES = 2 * 1024 * 1024      # a web page read only for its picture address
MAX_THUMB_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 60_000_000
TIMEOUT_S = 20
WIDTH = 2048                          # Wikimedia drawing width for SVG and very large files
GAP_S = {'openlibrary.org': 1.0, 'covers.openlibrary.org': 0.5, 'api.openverse.org': 1.0}
DEFAULT_GAP_S = 0.35                   # Wikimedia: at most ~170 requests a minute, under its 200 for a named client
SIDE = 'pictures'
PREFIX = 'real-picture-'
KINDS = ('any', 'logo', 'app', 'brand', 'person', 'place', 'book', 'product', 'animal', 'food', 'thing')
OFFLINE_NOTE = "This PC can't reach the picture sources right now (offline or blocked): carry on without the picture."

_lock = threading.Lock()
_last = {}


class Offline(Exception):
    """The network can't be reached."""


class NotAPicture(ValueError):
    """The bytes are not a picture letitedit takes."""


# ---------------------------------------------------------------- polite, guarded HTTP

def _host_ok(host):
    """True when every address the host resolves to is a public one (no localhost, private or link-local network)."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise Offline(f'{host}: {e}') from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split('%')[0])
        if not ip.is_global:
            return False
    return True


class _Guard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https'):
        raise ValueError(f'only http and https addresses are fetched, not {p.scheme or "this"}: {url}')
    if not _host_ok(p.hostname):
        raise ValueError(f'{p.hostname} is not a public address')
    return p


def _pace(host):
    gap = GAP_S.get(host, DEFAULT_GAP_S)
    with _lock:
        wait = _last.get(host, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()


def _http(url, max_bytes=MAX_BYTES, accept='*/*'):
    """(bytes, final url, content type). Raises Offline when the network can't be reached."""
    host = _check_url(url).hostname
    opener = urllib.request.build_opener(_Guard)
    for attempt in range(3):
        _pace(host)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})
        try:
            with opener.open(req, timeout=TIMEOUT_S) as r:
                size = r.headers.get('Content-Length')
                if size and size.isdigit() and int(size) > max_bytes:
                    raise NotAPicture(f'{url} is {int(size) // 1024} KB, over the {max_bytes // 1024} KB limit')
                data = r.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise NotAPicture(f'{url} is over the {max_bytes // 1024} KB limit')
                return data, r.geturl(), (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                retry = e.headers.get('Retry-After')
                time.sleep(min(30, float(retry)) if retry and retry.isdigit() else 5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as e:
            raise Offline(f'{host}: {getattr(e, "reason", e)}') from e
    raise Offline(f'{host}: no answer')


def _json(url, params=None):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    data, _, _ = _http(url, max_bytes=8 * 1024 * 1024, accept='application/json')
    return json.loads(data.decode('utf-8'))


# ---------------------------------------------------------------- picture bytes

_MAGIC = ((b'\xff\xd8\xff', 'jpeg'), (b'\x89PNG\r\n\x1a\n', 'png'), (b'GIF87a', 'gif'), (b'GIF89a', 'gif'),
          (b'BM', 'bmp'), (b'II*\x00', 'tiff'), (b'MM\x00*', 'tiff'))


def picture_kind(data):
    """'jpeg' | 'png' | 'gif' | 'webp' | 'bmp' | 'tiff' | 'svg' from the bytes themselves, or None."""
    head = bytes(data[:64])
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    text = head.lstrip(b'\xef\xbb\xbf \t\r\n').lower()
    if text.startswith(b'<svg') or (text.startswith(b'<?xml') and b'<svg' in bytes(data[:4096]).lower()):
        return 'svg'
    return None


def check_picture(data):
    """(kind, width, height, normalised bytes, extension) for a raster picture; raises NotAPicture otherwise.
    JPEG and PNG are kept as they came; other formats are saved as PNG (the first frame of an animation)."""
    kind = picture_kind(data)
    if kind is None:
        raise NotAPicture('the file is not a picture (its bytes are not JPEG, PNG, GIF, WebP, BMP or TIFF)')
    if kind == 'svg':
        raise NotAPicture('an SVG drawing: give its Wikimedia Commons page (drawn to PNG there) or a PNG or JPEG address')
    if len(data) > MAX_BYTES:
        raise NotAPicture(f'over the {MAX_BYTES // 1024 // 1024} MB limit')
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w * h > MAX_PIXELS:
                raise NotAPicture(f'{w}x{h} is over the {MAX_PIXELS // 1_000_000} megapixel limit')
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if kind in ('jpeg', 'png'):
                return kind, w, h, bytes(data), '.jpg' if kind == 'jpeg' else '.png'
            out = io.BytesIO()
            frame = im.convert('RGBA') if im.mode in ('P', 'LA', 'RGBA', 'PA') or 'transparency' in im.info else im.convert('RGB')
            frame.save(out, 'PNG')
            return kind, w, h, out.getvalue(), '.png'
    except NotAPicture:
        raise
    except Exception as e:  # noqa: BLE001 - Pillow's many ways of saying "not a picture"
        raise NotAPicture(f'the picture could not be read ({type(e).__name__})') from e


# ---------------------------------------------------------------- sources

_TAG = re.compile(r'<[^>]+>')


def _plain(value):
    return html.unescape(_TAG.sub('', str(value or ''))).strip() or None


def _wiki_file(file_title, api='https://commons.wikimedia.org/w/api.php'):
    """The record of a file on Wikimedia Commons (or a Wikipedia's own file): addresses, size, licence, author."""
    name = file_title if file_title.lower().startswith('file:') else 'File:' + file_title
    d = _json(api, {'action': 'query', 'format': 'json', 'formatversion': 2, 'titles': name, 'prop': 'imageinfo',
                    'iiprop': 'url|extmetadata|size|mime', 'iiurlwidth': WIDTH,
                    'iiextmetadatafilter': 'LicenseShortName|LicenseUrl|Artist|Credit|UsageTerms|AttributionRequired|'
                                           'NonFree|Restrictions|ObjectName|ImageDescription'})
    page = (d.get('query', {}).get('pages') or [{}])[0]
    info = (page.get('imageinfo') or [None])[0]
    if not info:
        return None
    meta = {k: (v or {}).get('value') for k, v in (info.get('extmetadata') or {}).items()}
    big = info.get('width', 0) * info.get('height', 0) > 16_000_000 or info.get('size', 0) > MAX_BYTES
    use_thumb = bool(info.get('thumburl')) and (info.get('mime') == 'image/svg+xml' or big)
    restrictions = _plain(meta.get('Restrictions'))
    return {'title': _plain(meta.get('ObjectName')) or page.get('title', name)[5:],
            'image_url': info.get('thumburl') if use_thumb else info.get('url'),
            'original_url': info.get('url'), 'original_mime': info.get('mime'),
            'page_url': info.get('descriptionurl'), 'licence': _plain(meta.get('LicenseShortName')) or 'not stated',
            'licence_url': _plain(meta.get('LicenseUrl')), 'author': _plain(meta.get('Artist')),
            'credit': _plain(meta.get('Credit')), 'usage_terms': _plain(meta.get('UsageTerms')),
            'attribution_required': str(meta.get('AttributionRequired')).lower() == 'true',
            'non_free': str(meta.get('NonFree')).lower() == 'true',
            'restrictions': restrictions.replace('|', ', ') if restrictions else None,
            'what': (_plain(meta.get('ImageDescription')) or '')[:200] or None,
            'width': info.get('thumbwidth') if use_thumb else info.get('width'),
            'height': info.get('thumbheight') if use_thumb else info.get('height')}


def _wikipedia_search(query, limit, lang='en'):
    api = f'https://{lang}.wikipedia.org/w/api.php'
    d = _json(api, {'action': 'query', 'format': 'json', 'formatversion': 2, 'generator': 'search',
                    'gsrsearch': query, 'gsrlimit': max(3, limit), 'prop': 'pageimages|description|info',
                    'piprop': 'name|thumbnail', 'pithumbsize': 320, 'inprop': 'url', 'redirects': 1})
    pages = sorted(d.get('query', {}).get('pages', []), key=lambda p: p.get('index', 99))
    out = []
    for p in pages:
        if not p.get('pageimage'):
            continue
        out.append({'ref': f'wikipedia:{lang}:{p["title"]}', 'source': 'wikipedia', 'title': p['title'],
                    'what': p.get('description'), 'page_url': p.get('fullurl'),
                    'thumb_url': (p.get('thumbnail') or {}).get('source'), 'file': 'File:' + p['pageimage']})
    out = out[:limit]
    if out:                                             # the pictures' licences, in one more request
        try:
            m = _json(api, {'action': 'query', 'format': 'json', 'formatversion': 2,
                            'titles': '|'.join(c['file'] for c in out), 'prop': 'imageinfo', 'iiprop': 'extmetadata',
                            'iiextmetadatafilter': 'LicenseShortName|Artist|NonFree|Restrictions'})
            names = {n['from']: n['to'] for n in m.get('query', {}).get('normalized', [])}
            meta = {pg['title']: {k: (v or {}).get('value') for k, v in ((pg.get('imageinfo') or [{}])[0].get('extmetadata') or {}).items()}
                    for pg in m.get('query', {}).get('pages', [])}
            for c in out:
                info = meta.get(names.get(c['file'], c['file'])) or {}
                c.update({k: v for k, v in {'licence': _plain(info.get('LicenseShortName')), 'author': _plain(info.get('Artist')),
                                            'restrictions': _plain(info.get('Restrictions')),
                                            'non_free': str(info.get('NonFree')).lower() == 'true' or None}.items() if v})
        except Exception:  # noqa: BLE001 - the licence is read again on fetch
            pass
    return out


def _wikipedia_resolve(ref):
    _, lang, title = ref.split(':', 2)
    api = f'https://{lang}.wikipedia.org/w/api.php'
    d = _json(api, {'action': 'query', 'format': 'json', 'formatversion': 2, 'titles': title, 'redirects': 1,
                    'prop': 'pageimages|info|description', 'piprop': 'name', 'inprop': 'url'})
    page = (d.get('query', {}).get('pages') or [{}])[0]
    if not page.get('pageimage'):
        raise LookupError(f'the Wikipedia article "{title}" has no page picture')
    rec = _wiki_file(page['pageimage'], api)        # a Wikipedia API answers for its own files and Commons ones
    if not rec:
        raise LookupError(f'the picture of "{title}" could not be read')
    rec.update({'source': 'wikipedia', 'article': page.get('title'), 'article_url': page.get('fullurl'),
                'what': page.get('description') or rec.get('what')})
    return rec


def _commons_search(query, limit):
    d = _json('https://commons.wikimedia.org/w/api.php',
              {'action': 'query', 'format': 'json', 'formatversion': 2, 'generator': 'search', 'gsrnamespace': 6,
               'gsrsearch': f'{query} filetype:bitmap|drawing', 'gsrlimit': limit, 'prop': 'imageinfo',
               'iiprop': 'url|extmetadata|mime|size', 'iiurlwidth': 320,
               'iiextmetadatafilter': 'LicenseShortName|Artist|Restrictions|NonFree'})
    out = []
    for p in sorted(d.get('query', {}).get('pages', []), key=lambda p: p.get('index', 99)):
        info = (p.get('imageinfo') or [None])[0]
        if not info:
            continue
        meta = {k: (v or {}).get('value') for k, v in (info.get('extmetadata') or {}).items()}
        out.append({'ref': 'commons:' + p['title'], 'source': 'commons', 'title': p['title'][5:],
                    'page_url': info.get('descriptionurl'), 'thumb_url': info.get('thumburl'),
                    'licence': _plain(meta.get('LicenseShortName')), 'author': _plain(meta.get('Artist')),
                    'restrictions': _plain(meta.get('Restrictions')), 'svg': info.get('mime') == 'image/svg+xml',
                    'width': info.get('width'), 'height': info.get('height')})
    return out


def _commons_resolve(ref):
    rec = _wiki_file(ref.split(':', 1)[1])
    if not rec:
        raise LookupError(f'{ref} is not a file on Wikimedia Commons')
    rec['source'] = 'commons'
    return rec


def _openverse_row(r):
    lic = (r.get('license') or '').upper()
    lic = ('CC0' if lic == 'CC0' else 'Public Domain Mark' if lic == 'PDM' else f'CC {lic} {r.get("license_version") or ""}'.strip()) if lic else 'not stated'
    return {'ref': 'openverse:' + r['id'], 'source': 'openverse', 'title': r.get('title'),
            'page_url': r.get('foreign_landing_url'), 'thumb_url': r.get('thumbnail'), 'image_url': r.get('url'),
            'licence': lic, 'licence_url': r.get('license_url'), 'author': r.get('creator'),
            'attribution': r.get('attribution'), 'provider': r.get('provider'),
            'width': r.get('width'), 'height': r.get('height')}


def _openverse_search(query, limit):
    d = _json('https://api.openverse.org/v1/images/', {'q': query, 'page_size': max(1, min(limit, 20)), 'mature': 'false'})
    return [_openverse_row(r) for r in d.get('results', [])]


def _openverse_resolve(ref):
    r = _json(f'https://api.openverse.org/v1/images/{urllib.parse.quote(ref.split(":", 1)[1])}/')
    rec = _openverse_row(r)
    rec['source'] = 'openverse'
    return rec


def _openlibrary_search(query, limit):
    d = _json('https://openlibrary.org/search.json', {'q': query, 'limit': limit,
                                                       'fields': 'key,title,author_name,cover_i,first_publish_year'})
    out = []
    for doc in d.get('docs', []):
        if not doc.get('cover_i'):
            continue
        work = doc['key'].rsplit('/', 1)[-1]
        out.append({'ref': f'openlibrary:{doc["cover_i"]}:{work}', 'source': 'openlibrary', 'title': doc.get('title'),
                    'author': ', '.join(doc.get('author_name') or []) or None, 'year': doc.get('first_publish_year'),
                    'page_url': 'https://openlibrary.org' + doc['key'],
                    'thumb_url': f'https://covers.openlibrary.org/b/id/{doc["cover_i"]}-M.jpg'})
    return out


def _openlibrary_resolve(ref):
    parts = ref.split(':')
    cover = parts[1]
    if not cover.isdigit():
        raise ValueError(f'{ref}: an Open Library cover id is a number')
    work = parts[2] if len(parts) > 2 else None
    title = author = None
    if work and re.fullmatch(r'OL\d+[WM]', work):
        try:
            d = _json('https://openlibrary.org/search.json', {'q': f'key:/works/{work}', 'fields': 'title,author_name'})
            doc = (d.get('docs') or [{}])[0]
            title, author = doc.get('title'), ', '.join(doc.get('author_name') or []) or None
        except Exception:  # noqa: BLE001 - the cover still has its record without the title
            pass
    return {'source': 'openlibrary', 'title': title or f'Open Library cover {cover}', 'book_author': author,
            'image_url': f'https://covers.openlibrary.org/b/id/{cover}-L.jpg',
            'page_url': f'https://openlibrary.org/works/{work}' if work else f'https://covers.openlibrary.org/b/id/{cover}.json',
            'licence': 'not stated (cover art belongs to its publisher or artist)', 'author': None}


_OG = re.compile(r'<meta[^>]+(?:property|name)\s*=\s*["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]*>', re.I)
_CONTENT = re.compile(r'content\s*=\s*["\']([^"\']+)["\']', re.I)


def _from_url(url, page=None):
    """A record for an address the AI found: Wikipedia, Commons, Openverse and Open Library pages go through their
    own APIs (for the licence); any other page gives its og:image picture; a picture address is taken as is."""
    p = urllib.parse.urlparse(url)
    host = (p.hostname or '').lower()
    path = urllib.parse.unquote(p.path)
    if host.endswith('.wikipedia.org') and path.startswith('/wiki/'):
        title = path[6:]
        if re.match(r'(File|Image):', title, re.I):
            rec = _wiki_file(title, f'https://{host}/w/api.php')
            if rec:
                return dict(rec, source='wikipedia')
        return _wikipedia_resolve(f'wikipedia:{host.split(".")[0]}:{title.replace("_", " ")}')
    if host == 'commons.wikimedia.org' and path.startswith('/wiki/File:'):
        return _commons_resolve('commons:' + path[6:].replace('_', ' '))
    if host == 'upload.wikimedia.org':
        name = path.rsplit('/', 1)[-1]
        if '/thumb/' in path:
            name = path.split('/')[-2]
        rec = _wiki_file(name)
        if rec:
            return dict(rec, source='commons')
    m = re.match(r'^/(?:\w+/)?image/([0-9a-f-]{36})', path) if host.endswith('openverse.org') else None
    if m:
        return _openverse_resolve('openverse:' + m.group(1))
    m = re.match(r'^/b/id/(\d+)(?:-[SML])?\.jpg$', path) if host == 'covers.openlibrary.org' else None
    if m:
        rec = _openlibrary_resolve(f'openlibrary:{m.group(1)}')
        rec['page_url'] = page or rec['page_url']
        return rec
    if host == 'openlibrary.org' and re.match(r'^/(works|books)/OL\d+[WM]', path):
        key = re.match(r'^/(works|books)/(OL\d+[WM])', path)
        d = _json(f'https://openlibrary.org/{key.group(1)}/{key.group(2)}.json')
        covers = [c for c in d.get('covers', []) if isinstance(c, int) and c > 0]
        if not covers:
            raise LookupError(f'{url} has no cover on Open Library')
        rec = _openlibrary_resolve(f'openlibrary:{covers[0]}:{key.group(2) if key.group(1) == "works" else ""}')
        rec['title'] = d.get('title') or rec['title']
        rec['page_url'] = url
        return rec
    data, final, ctype = _http(url, max_bytes=MAX_BYTES, accept='text/html,image/*;q=0.9,*/*;q=0.5')
    if picture_kind(data):
        return {'source': 'url', 'title': Path(path).stem or Path(urllib.parse.unquote(urllib.parse.urlparse(final).path)).stem or host,
                'image_url': final, 'page_url': page or url, 'licence': 'not stated', 'author': None, '_data': data}
    if 'html' not in ctype and not data[:2048].lstrip().lower().startswith((b'<!doctype html', b'<html')):
        raise NotAPicture(f'{url} is neither a picture nor a web page ({ctype or "unknown type"})')
    text = data[:MAX_PAGE_BYTES].decode('utf-8', errors='replace')
    found = None
    for tag in _OG.findall(text):
        c = _CONTENT.search(tag)
        if c:
            found = urllib.parse.urljoin(final, html.unescape(c.group(1)))
            break
    if not found:
        raise LookupError(f'{url} names no picture of itself (no og:image): give the picture\'s own address')
    title = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
    return {'source': 'url', 'title': _plain(title.group(1))[:120] if title else host, 'image_url': found,
            'page_url': page or url, 'licence': 'not stated', 'author': None}


RESOLVE = {'wikipedia': _wikipedia_resolve, 'commons': _commons_resolve, 'openverse': _openverse_resolve,
           'openlibrary': _openlibrary_resolve}
SEARCH = {'wikipedia': _wikipedia_search, 'commons': _commons_search, 'openverse': _openverse_search,
          'openlibrary': _openlibrary_search}
ORDER = {'logo': ('commons', 'wikipedia'), 'app': ('commons', 'wikipedia'), 'brand': ('commons', 'wikipedia'),
         'book': ('openlibrary', 'wikipedia'), 'person': ('wikipedia', 'commons'),
         'place': ('wikipedia', 'commons', 'openverse'), 'animal': ('wikipedia', 'openverse', 'commons'),
         'food': ('wikipedia', 'openverse', 'commons'), 'product': ('wikipedia', 'commons', 'openverse'),
         'thing': ('wikipedia', 'commons', 'openverse'), 'any': ('wikipedia', 'commons', 'openverse')}


def search(query, kind='any', sources=None, limit=8):
    """Candidates for a named thing from the sources (in the order `kind` suggests, or `sources`): each with ref,
    source, title, what, page_url, thumb_url, licence and author where the source states them. Never raises for one
    source failing: notes say which didn't answer; offline is said once."""
    query = str(query or '').strip()
    if not query:
        raise ValueError('say what to find (query): "Google Chrome", "Eiffel Tower", "The Hobbit"')
    kind = (kind or 'any').lower()
    if kind not in ORDER:
        raise ValueError(f'kind is one of {", ".join(KINDS)}')
    order = [s for s in (sources or ORDER[kind]) if s in SEARCH]
    if not order:
        raise ValueError(f'sources are from {", ".join(SEARCH)}')
    per = max(2, min(12, int(limit or 8)))
    out, notes, offline = [], [], 0
    for s in order:
        q = f'{query} logo' if s == 'commons' and kind in ('logo', 'app', 'brand') and 'logo' not in query.lower() else query
        try:
            out += SEARCH[s](q, per)
        except Offline:
            offline += 1
            notes.append(f'{s}: no answer (offline?)')
        except Exception as e:  # noqa: BLE001
            notes.append(f'{s}: {type(e).__name__}: {str(e)[:120]}')
    if offline == len(order):
        return {'query': query, 'kind': kind, 'offline': True, 'candidates': [], 'note': OFFLINE_NOTE}
    for i, c in enumerate(out):
        c['n'] = i + 1
    return {'query': query, 'kind': kind, 'sources': order, 'candidates': out, 'notes': notes}


def sheet(candidates, cols=4, tile=260):
    """JPEG bytes: each candidate's small picture with its number, source and licence (pictures read into memory only)."""
    from PIL import Image, ImageDraw
    rows = max(1, (len(candidates) + cols - 1) // cols)
    img = Image.new('RGB', (cols * tile, rows * (tile + 34)), (28, 28, 32))
    d = ImageDraw.Draw(img)
    for i, c in enumerate(candidates):
        x, y = (i % cols) * tile, (i // cols) * (tile + 34)
        try:
            data, _, _ = _http(c['thumb_url'], max_bytes=MAX_THUMB_BYTES, accept='image/*')
            if picture_kind(data) in (None, 'svg'):
                raise NotAPicture('thumbnail')
            th = Image.open(io.BytesIO(data))
            th.thumbnail((tile - 8, tile - 8))
            bg = Image.new('RGB', th.size, (200, 200, 200))
            bg.paste(th.convert('RGBA'), mask=th.convert('RGBA'))
            img.paste(bg, (x + (tile - th.width) // 2, y + (tile - th.height) // 2))
        except Exception:  # noqa: BLE001 - a missing thumbnail leaves its tile empty
            d.text((x + 10, y + tile // 2), 'no preview', fill=(160, 160, 160))
        d.text((x + 6, y + tile + 2), f'{c.get("n")}. {c["source"]}  {str(c.get("licence") or "")[:22]}', fill=(240, 240, 240))
        d.text((x + 6, y + tile + 17), str(c.get('title') or '')[:40], fill=(170, 170, 180))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=85)
    return buf.getvalue()


# ---------------------------------------------------------------- saving beside the project

def side_folder(project=None, folder=None):
    """<project stem>.letitedit/pictures beside a project (.mlt), or <folder>/.letitedit/pictures. The only place
    pictures are written."""
    if project:
        p = Path(project)
        if p.suffix.lower() != '.mlt':
            raise ValueError('project is a letitedit project file (.mlt)')
        if not p.parent.is_dir():
            raise ValueError(f'the project\'s folder {p.parent} does not exist')
        return p.parent / (p.stem + '.letitedit') / SIDE
    if folder:
        f = Path(folder)
        if not f.is_dir():
            raise ValueError(f'{folder} is not a folder')
        return f / '.letitedit' / SIDE
    raise ValueError('say where the picture goes: project (the .mlt) or folder (the video\'s folder)')


def _slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', str(text or 'picture').lower()).strip('-')
    return (s or 'picture')[:40].strip('-') or 'picture'


def _reserve(side, slug, ext):
    side.mkdir(parents=True, exist_ok=True)
    n = 1 + max([int(m.group(1)) for p in side.glob(PREFIX + '*') if (m := re.match(PREFIX + r'(\d+)-', p.name))] or [0])
    while True:
        path = side / f'{PREFIX}{n}-{slug}{ext}'
        try:
            with open(path, 'xb'):
                return path
        except FileExistsError:
            n += 1


def credit_line(rec):
    """The facts a description would carry for this picture, in one line."""
    who = f' by {rec["author"]}' if rec.get('author') else ''
    book = f' ({rec["book_author"]})' if rec.get('book_author') else ''
    bits = [f'Picture: {rec.get("title")}{book}{who}', f'licence: {rec.get("licence") or "not stated"}']
    if rec.get('restrictions'):
        bits.append(f'restrictions: {rec["restrictions"]}')
    if rec.get('non_free'):
        bits.append('marked non-free by its source')
    return '; '.join(bits) + f' ({rec.get("source_page") or rec.get("page_url") or rec.get("image_url")})'


_UTM = re.compile(r'([?&])utm_[a-z]+=[^&]*')


def _tidy(url):
    """An address without the utm_ tracking parameters Wikimedia's API adds."""
    if not url:
        return url
    out = _UTM.sub(r'', str(url))
    return re.sub(r'[?&]+$', '', re.sub(r'([?&])&+', r'', out))


def fetch(ref=None, url=None, page=None, project=None, folder=None, name=None):
    """Fetch one picture (a search ref, or an address) into the video's pictures folder with its record.
    Returns {path, record_path, record}; offline gives {'offline': True, 'note'} and writes nothing."""
    side = side_folder(project, folder)
    if not ref and not url:
        raise ValueError('give ref (from a search) or url (a page or picture address)')
    try:
        if ref:
            src = str(ref).split(':', 1)[0]
            if src not in RESOLVE:
                raise ValueError(f'{ref}: a ref starts with one of {", ".join(RESOLVE)}')
            rec = RESOLVE[src](str(ref))
        else:
            rec = _from_url(str(url), page)
        data = rec.pop('_data', None)
        if data is None:
            if not rec.get('image_url'):
                raise LookupError('the source gave no picture address')
            data, final, _ = _http(rec['image_url'], accept='image/*')
            rec['image_url'] = final
    except Offline as e:
        return {'offline': True, 'note': OFFLINE_NOTE, 'detail': str(e)}
    kind, w, h, data, ext = check_picture(data)
    import hashlib
    path = _reserve(side, _slug(name or rec.get('title')), ext)
    path.write_bytes(data)
    record = {'id': path.stem, 'file': path.name, 'query_ref': ref, 'asked_url': url,
              'source': rec.get('source'), 'title': rec.get('title'), 'what': rec.get('what'),
              'source_page': _tidy(rec.get('page_url')), 'image_url': _tidy(rec.get('image_url')),
              'original_url': _tidy(rec.get('original_url')), 'licence': rec.get('licence') or 'not stated',
              'licence_url': rec.get('licence_url'), 'author': rec.get('author'), 'book_author': rec.get('book_author'),
              'attribution': rec.get('attribution'), 'credit': rec.get('credit'), 'usage_terms': rec.get('usage_terms'),
              'restrictions': rec.get('restrictions'), 'non_free': rec.get('non_free', False),
              'article_url': rec.get('article_url'), 'format': kind, 'width': w, 'height': h, 'bytes': len(data),
              'sha256': hashlib.sha256(data).hexdigest(),
              'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'by': USER_AGENT}
    record = {k: v for k, v in record.items() if v not in (None, '')}
    record['credit_line'] = credit_line(record)
    car = path.with_suffix('.json')
    car.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding='utf-8')
    with open(side / 'pictures.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'id': record['id'], 'file': path.name, 'title': record.get('title'),
                            'licence': record['licence'], 'source_page': record.get('source_page'),
                            'fetched_at': record['fetched_at']}, ensure_ascii=False) + '\n')
    return {'path': str(path), 'record_path': str(car), 'record': record}


def history(project=None, folder=None):
    """Every real picture fetched for this video: its record (newest last)."""
    side = side_folder(project, folder)
    out = []
    for car in sorted(side.glob(PREFIX + '*.json'), key=lambda p: (int(re.match(PREFIX + r'(\d+)', p.name).group(1)), p.name)):
        try:
            row = json.loads(car.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        out.append(dict(row, path=str(car.with_name(row.get('file', car.stem)))))
    return out


# ---------------------------------------------------------------- what a video uses

_REF = re.compile(r"real-picture-\d+-[a-z0-9-]*\.(?:jpg|png)", re.I)
ORIGIN_SUFFIX = '.origin'              # <file>.origin beside any file made from a real picture (T178)
_ORIGIN_KEYS = ('id', 'title', 'source', 'source_page', 'licence', 'author', 'book_author', 'restrictions', 'non_free')
_MEDIA = r'png|jpe?g|gif|webp|bmp|tiff?|mov|mp4|webm|mkv|avi|m4v'
_PATHISH = re.compile(r"file:///[^'\"\s)`<>]+|[A-Za-z]:[\\/][^'\"\r\n<>|?*]+?\.(?:" + _MEDIA + r")(?![A-Za-z0-9])", re.I)
_MEDIA_NAME = re.compile(r'[^\\/]+\.(?:' + _MEDIA + r')$', re.I)


def _record_of(path):
    """The record beside a fetched real picture, or None."""
    p = Path(str(path))
    if not os.path.isabs(str(path)) or not p.name.lower().startswith(PREFIX):
        return None
    try:
        return json.loads(p.with_suffix('.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def _origin(row):
    out = {k: row[k] for k in _ORIGIN_KEYS if row.get(k) not in (None, '')}
    out['credit_line'] = row.get('credit_line') or credit_line(row)
    return out


def origins_of(path, _seen=None):
    """The real pictures a file is or was made from, as small records [{id, title, licence, credit_line, ...}]: the
    file's own record when it is a fetched picture; else what its <file>.origin names (kept whole inside that file, so
    the originals can be gone); for a project (.mlt) everything it uses. [] for any other file."""
    text = str(path or '')
    if not text or not os.path.isabs(text):
        return []
    rec = _record_of(text)
    if rec is not None:
        return [_origin(rec)]
    if text.lower().endswith('.mlt'):
        seen = _seen if _seen is not None else set()
        key = os.path.normcase(os.path.normpath(text))
        if key in seen or not os.path.isfile(text):
            return []
        seen.add(key)
        out = []
        try:
            for f in project_inputs(text):
                out += origins_of(f, seen)
        except Exception:  # noqa: BLE001 - an unreadable project owes nothing here
            return []
        return _merge(out)
    try:
        row = json.loads(Path(text + ORIGIN_SUFFIX).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return []
    return _merge([o for o in (row.get('origins') or []) if isinstance(o, dict) and o.get('credit_line')])


def _merge(origins):
    """Each original once (by its credit line), in the order met."""
    seen, out = set(), []
    for o in origins:
        k = o.get('credit_line')
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return out


def _same(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def made_from(new_path, sources, tool=None, note=None, strict=False):
    """Record that a file was made from these files, so the credit lines of any real pictures among them follow it
    (T178). Writes <new_path>.origin holding each original's record in full: it works through chains (a source made
    from a real picture hands its originals on), after the originals are deleted, and wherever the file is saved.
    A file made from nothing credited gets no record (and loses an old one: the file was made again without them).
    Returns the record, or None. Unless strict, a failure to write is swallowed: a line of credit never stops a tool."""
    try:
        new = Path(str(new_path))
        side = Path(str(new) + ORIGIN_SUFFIX)
        origins, used = [], []
        for s in sources or []:
            if not s or not os.path.isabs(str(s)) or _same(s, new):
                continue
            found = origins_of(str(s))
            if found:
                origins += found
                used.append(os.path.normpath(str(s)))
        origins = _merge(origins)
        if not origins:
            if side.exists():
                side.unlink()
            return None
        row = {'format': 1, 'file': new.name, 'made_from': used, 'tool': tool, 'note': note,
               'made_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'origins': origins}
        row = {k: v for k, v in row.items() if v not in (None, '')}
        side.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding='utf-8')
        return row
    except Exception:  # noqa: BLE001
        if strict:
            raise
        return None


def files_in(value, base=None):
    """The file paths a recipe, a script or a page names: every absolute path, file:// address and relative media
    file name in its strings (a nested dict or list is walked; long texts are searched)."""
    from urllib.request import url2pathname
    found, todo = [], [value]
    while todo:
        v = todo.pop()
        if isinstance(v, dict):
            todo += list(v.values())
        elif isinstance(v, (list, tuple)):
            todo += list(v)
        elif isinstance(v, str) and v:
            if len(v) <= 1024 and '\n' not in v:
                if os.path.isabs(v) and not v.lower().startswith('file:'):
                    found.append(v)
                elif base and _MEDIA_NAME.search(v) and not re.match(r'^[a-z][a-z0-9+.-]*:', v, re.I):
                    found.append(str(Path(base) / v))
            for m in _PATHISH.finditer(v):
                t = m.group(0)
                found.append(url2pathname(urllib.parse.urlparse(t).path) if t.lower().startswith('file:') else t)
    return [os.path.normpath(f) for f in found]


def made_from_recipe(new_path, recipe, tool=None, base=None):
    """made_from() for a file drawn from a recipe (a motion spec, a graphic's params): the files the recipe names."""
    return made_from(new_path, files_in(recipe, base), tool=tool)


def scene_files(project):
    """Files a project's code scenes load that are real pictures or made from one (named in their sources)."""
    p = Path(project)
    found = set()
    for page in (p.parent / (p.stem + '.letitedit') / 'scenes').glob('*/revisions/*/scene.json'):
        try:
            text = page.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for f in files_in(text):
            if origins_of(f):
                found.add(f)
    return sorted(found)


def recipe_files(project):
    """Files named inside the recipes a project keeps on its clips (letitedit_ai:* properties: graphics, motion, shot
    effects, pop-ups, freezes): a picture a graphic draws or a motion clip shows is used even though no clip names it."""
    import xml.etree.ElementTree as ET
    root = ET.parse(str(project)).getroot()
    base = Path(root.get('root') or Path(project).parent)
    found = []
    for prop in root.iter('property'):
        if not (prop.get('name') or '').startswith('letitedit_ai:'):
            continue
        text = (prop.text or '').strip()
        if not text:
            continue
        try:
            value = json.loads(text)
        except ValueError:
            value = text
        found += files_in(value, base)
    return found


def project_inputs(project):
    """Everything a project uses that can carry a credit: its clips' files, the files its recipes and code scenes name."""
    import letitedit.catalogs.assets as assets
    return assets.project_files(project) + recipe_files(project) + scene_files(project)


def owes(paths):
    """Lines for the real pictures among these files, and for what was made from them, as assets.credits gives them:
    [{line, assets: [id]}]. Every real picture gets its line (source, licence as stated, author, restrictions), once
    however many files were made from it; the person decides what to publish."""
    lines = {}
    for p in paths or []:
        for o in origins_of(str(p)):
            lines.setdefault(o['credit_line'], set()).add(o.get('id') or o['credit_line'])
    return [{'line': k, 'assets': sorted(v)} for k, v in lines.items()]


def project_credits(project):
    """owes() for everything a project uses, its recipes and code scenes included."""
    return owes(project_inputs(project))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'search':
        print(json.dumps(search(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'any'), indent=1, ensure_ascii=False))
    elif cmd == 'fetch':
        arg = sys.argv[2]
        kw = {'url': arg} if arg.startswith(('http://', 'https://')) else {'ref': arg}
        print(json.dumps(fetch(project=sys.argv[3], **kw), indent=1, ensure_ascii=False))
    elif cmd == 'credits':
        print(json.dumps(project_credits(sys.argv[2]), indent=1, ensure_ascii=False))
    else:
        print(__doc__)
