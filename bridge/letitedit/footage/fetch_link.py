"""Fetch a video from a link (T177), for "Match a video I like" and Learn only: the reference video a Look is learned from. The
downloader is yt-dlp (Unlicense), fetched on first use from its GitHub release, pinned (bridge/ytdlp_pin.json: version, size,
SHA-256) and checked. It runs as a child of this process (no console window, below-normal priority, the bundled ffmpeg), never
through an AI's shell or web tools, so no AI asks the person to allow it. There is no song or sound-only fetching (10 Nov).

    fetch_reference(url, name, folder, start, end, seconds)
                                               a video file (mp4, up to 1080p) + record.json in <My Looks>/.imports/references/<name>/;
                                               start/end/seconds fetch only that part of a longer video
    history()                                  the reference videos fetched so far, with their records
    status()                                   the downloader: version, where, whether it is on this PC

Limits (constants below): one video only (no playlist, channel or search page), no live streams, no sign-in, no cookies, no
accounts, only the sites yt-dlp has its own extractor for (not "any address"), a length cap (on the whole video, or on the part
asked for: a longer video is fetched a part at a time) and a size cap, nothing
downloaded is run, and files are written only in the folders named above. Every refusal comes back as {ok: False, error,
reason}; nothing is saved.

When a fetch fails in a way a site change explains (a signature or player that no longer extracts), the newest yt-dlp
release is looked up once, checked against that release's SHA2-256SUMS, installed beside the pinned one, and the fetch is
tried again.

    python fetch_link.py status
    python fetch_link.py reference <url> [name] [start] [end]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows)

from letitedit.core import paths as _paths

ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
PIN_FILE = Path(_paths.BRIDGE) / 'ytdlp_pin.json'
USER_AGENT = 'letitedit-fetch/1 (+https://letitedit.app)'

MAX_VIDEO_S = 30 * 60              # a reference: up to 30 minutes
MAX_VIDEO_BYTES = 800 * 1024 * 1024
MAX_HEIGHT = 1080
RUN_TIMEOUT_S = 1500
INFO_TIMEOUT_S = 180

NOTICE_REFERENCE = ("This is a private working copy of someone else's video, kept in the person's own folders for learning its "
                    "way of editing. It is never shipped, never put in a library and never used as footage.")

_SITE_CHANGED = re.compile(r'unable to extract|nsig|signature|n challenge|player[_ ]response|unable to download.*(player|api)|'
                           r'requested format is not available|http error 403|sabr|po token|challenge', re.I)
_OFFLINE = re.compile(r'getaddrinfo|name or service|temporary failure|network is unreachable|timed out|connection (refused|reset)|'
                      r'no address associated|unable to download webpage.*(urlopen|ssl)|failed to resolve|no route to host|'
                      r'winerror 100(4|5)\d|winerror 1005', re.I)
_SIGN_IN = re.compile(r'sign in|log in|login|private video|members[- ]only|age[- ]restricted|confirm your age|'
                      r'this video is available to|cookies|authentication|premium', re.I)
_UNSUPPORTED = re.compile(r'unsupported url|is not a valid url|no suitable extractor', re.I)

_playlist_path = re.compile(r'^/(playlist|channel|c|user|results|feed|hashtag|search|tag|explore|browse)(/|$)|^/@[^/]+/?$|^/@[^/]+/(videos|shorts|streams|playlists|featured|live|community)/?$', re.I)


class Refused(Exception):
    """Something this tool will not or cannot fetch; reason is a short code, the message is plain words."""

    def __init__(self, reason, message, **extra):
        super().__init__(message)
        self.reason = reason
        self.extra = extra


def _fail(reason, message, **extra):
    return dict({'ok': False, 'reason': reason, 'error': message}, **extra)


# ---------------------------------------------------------------- the downloader (pinned, checked, updated)

def tool_dir():
    import letitedit.core.first_use as first_use
    return Path(first_use.ROOT) / 'models' / 'yt-dlp' if os.environ.get('LETITEDIT_YTDLP_HOME') is None \
        else Path(os.environ['LETITEDIT_YTDLP_HOME'])


def pin():
    return json.loads(PIN_FILE.read_text(encoding='utf-8-sig'))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _exe_for(version):
    return tool_dir() / version / 'yt-dlp.exe'


def _current():
    """(version, sha256, bytes) of the updated release in use when one was installed, else the pinned one."""
    p = pin()
    try:
        cur = json.loads((tool_dir() / 'current.json').read_text(encoding='utf-8-sig'))
        if cur.get('version') and _exe_for(cur['version']).is_file() and cur.get('sha256') and cur.get('bytes'):
            return cur['version'], cur['sha256'], int(cur['bytes']), 'updated'
    except (OSError, ValueError):
        pass
    return p['version'], p['sha256'], int(p['bytes']), 'pinned'


def _download_checked(url, target, nbytes, sha256):
    """Download url to target and check size and SHA-256 (nothing is left behind on a mismatch)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, 'wb') as out:
            for b in iter(lambda: r.read(1 << 20), b''):
                out.write(b)
                h.update(b)
                got += len(b)
                if nbytes and got > nbytes + (1 << 20):
                    raise ValueError('larger than expected')
    except Exception as ex:  # noqa: BLE001
        part.unlink(missing_ok=True)
        raise Refused('offline' if isinstance(ex, (urllib.error.URLError, OSError)) else 'downloader_missing',
                      f"Couldn't download the video downloader from {url}: {type(ex).__name__}: {ex}") from ex
    if (nbytes and got != nbytes) or (sha256 and h.hexdigest() != sha256):
        part.unlink(missing_ok=True)
        raise Refused('downloader_missing', f'The downloaded video downloader did not match its pinned size and SHA-256 '
                                            f'({got} bytes, {h.hexdigest()[:12]}...); it was thrown away.')
    os.replace(part, target)


def _setting():
    try:
        import letitedit.core.model_fetch as model_fetch
        return model_fetch._setting()
    except Exception:  # noqa: BLE001
        return 'auto'


def ensure_downloader():
    """The path of yt-dlp.exe, fetched now when it is missing (settings.json model_downloads 'auto'; 'ask' / 'never' refuse
    with the size)."""
    version, sha, nbytes, source = _current()
    exe = _exe_for(version)
    if exe.is_file() and exe.stat().st_size == nbytes:
        return exe
    p = pin()
    if _setting() != 'auto':
        raise Refused('downloader_missing', f"The video downloader (yt-dlp {p['version']}, {nbytes / 1048576:.0f} MB, "
                                            f"{p['origin']}) is not on this PC and settings.json model_downloads is not 'auto'.")
    try:
        import letitedit.core.first_use as first_use
        first_use._tell('the video downloader (yt-dlp, Unlicense)', f'{nbytes / 1048576:.0f} MB')
    except Exception:  # noqa: BLE001
        pass
    _download_checked(p['url'], exe, nbytes, sha)
    _record_install(version, p['url'], nbytes, sha, 'pinned')
    return exe


def _record_install(version, url, nbytes, sha, how):
    d = tool_dir()
    d.mkdir(parents=True, exist_ok=True)
    line = {'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'version': version, 'url': url, 'bytes': nbytes, 'sha256': sha, 'how': how}
    with open(d / 'installs.log', 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(line) + '\n')
    try:
        import letitedit.core.first_use as first_use
        first_use._log({'event': 'yt-dlp installed', **line})
    except Exception:  # noqa: BLE001
        pass


def _version_key(v):
    return tuple(int(x) for x in re.findall(r'\d+', v))


def update_downloader():
    """Look up the newest yt-dlp release, check its exe against that release's SHA2-256SUMS, install it beside the pinned one
    and use it from now on. Returns {updated, version, was} (updated False when already the newest or on any trouble)."""
    p = pin()
    was = _current()[0]
    try:
        req = urllib.request.Request(p['releases_api'], headers={'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.load(r)
        tag = str(rel['tag_name'])
        if _version_key(tag) <= _version_key(was):
            return {'updated': False, 'version': was, 'was': was, 'note': 'already the newest release'}
        assets = {a['name']: a for a in rel['assets']}
        exe_asset, sums_asset = assets[p['file']], assets[p['sums_name']]
        with urllib.request.urlopen(urllib.request.Request(sums_asset['browser_download_url'],
                                                           headers={'User-Agent': USER_AGENT}), timeout=30) as r:
            sums = r.read().decode('utf-8', 'replace')
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.split()[-1:] == [p['file']]), None)
        if not want or not re.fullmatch(r'[0-9a-f]{64}', want):
            return {'updated': False, 'version': was, 'was': was, 'note': 'the release has no checksum for the program'}
        digest = str(exe_asset.get('digest') or '')
        if digest.startswith('sha256:') and digest[7:] != want:
            return {'updated': False, 'version': was, 'was': was, 'note': "the release's two checksums disagree: not installed"}
        _download_checked(exe_asset['browser_download_url'], _exe_for(tag), int(exe_asset['size']), want)
        (tool_dir() / 'current.json').write_text(json.dumps({'version': tag, 'sha256': want, 'bytes': int(exe_asset['size']),
                                                              'installed': time.strftime('%Y-%m-%d %H:%M:%S')}), encoding='utf-8')
        _record_install(tag, exe_asset['browser_download_url'], int(exe_asset['size']), want, 'update after a failed fetch')
        return {'updated': True, 'version': tag, 'was': was}
    except Refused as ex:
        return {'updated': False, 'version': was, 'was': was, 'note': str(ex)}
    except Exception as ex:  # noqa: BLE001
        return {'updated': False, 'version': was, 'was': was, 'note': f'update check failed: {type(ex).__name__}: {ex}'}


def status():
    version, sha, nbytes, source = _current()
    exe = _exe_for(version)
    p = pin()
    return {'program': 'yt-dlp', 'licence': 'Unlicense', 'origin': p['origin'], 'pinned_version': p['version'],
            'version': version, 'source': source, 'path': str(exe), 'present': exe.is_file() and exe.stat().st_size == nbytes,
            'size_bytes': nbytes, 'sha256': sha, 'model_downloads': _setting()}


# ---------------------------------------------------------------- running it

def _node():
    try:
        import letitedit.pictures.motion as motion
        return motion.node_exe()
    except Exception:  # noqa: BLE001
        return shutil.which('node')


def _base_args(exe):
    args = [str(exe), '--ignore-config', '--no-plugin-dirs', '--no-cookies-from-browser', '--no-playlist',
            '--use-extractors', 'default,-generic', '--no-warnings', '--no-color', '--socket-timeout', '30', '--retries', '3',
            '--ffmpeg-location', str(Path(_paths.install_root()) / 'app')]
    node = _node()
    if node:
        args += ['--js-runtimes', f'node:{node}']
    return args


def _flags():
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return flags | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)


def _run(args, timeout, cwd):
    """Run the downloader (no window, below-normal priority) from an empty working folder; returns (code, stdout, stderr)."""
    try:
        p = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', timeout=timeout, cwd=cwd,
                           creationflags=_flags(), env=dict(os.environ, PYTHONUTF8='1'))
    except subprocess.TimeoutExpired:
        raise Refused('failed', f'The downloader took longer than {timeout // 60} minutes and was stopped.') from None
    return p.returncode, p.stdout, p.stderr


def _explain(stderr):
    """(reason, plain words) for a downloader failure."""
    text = (stderr or '').strip()
    last = ' | '.join(ln for ln in text.splitlines() if ln.strip())[-500:]
    if _OFFLINE.search(text):
        return 'offline', "This PC can't reach the site right now (offline or blocked). Carry on without it."
    if _UNSUPPORTED.search(text):
        return 'unsupported_site', f"letitedit can't fetch from that address: it takes a link to one video on a site the downloader knows. ({last})"
    if _SIGN_IN.search(text):
        return 'private_or_signin', ("That video needs a sign-in (private, members-only, age-checked or asking for cookies), "
                                     f"and letitedit never signs in. Try another upload of it. ({last})")
    if re.search(r'video unavailable|removed|no longer available|does not exist|copyright|blocked it|not available in your country', text, re.I):
        return 'not_a_video', f'That video is not available (removed, blocked in this country or copyright-blocked). ({last})'
    return 'failed', f'The downloader could not fetch it: {last or "no message"}'


# ---------------------------------------------------------------- what a link may be

def parse_time(value, what='start'):
    """Seconds from a number or a clock time ('90', '1:30', '1:02:03', '75.5'); None stays None. Raises Refused."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise Refused('bad_section', f'{what} is a time: seconds or a clock time such as 1:30 or 1:02:03.')
    if isinstance(value, (int, float)):
        secs = float(value)
    else:
        parts = str(value).strip().lower().rstrip('s').split(':')
        try:
            if len(parts) > 3 or any(not p.strip() for p in parts):
                raise ValueError
            nums = [float(p) for p in parts]
        except ValueError:
            raise Refused('bad_section', f"{what} '{value}' is not a time: give seconds or a clock time such as 1:30 or 1:02:03.") from None
        if any(n < 0 for n in nums) or any(n >= 60 for n in nums[1:]):
            raise Refused('bad_section', f"{what} '{value}' is not a time: minutes and seconds after a colon run 0-59.")
        secs = 0.0
        for n in nums:
            secs = secs * 60 + n
    if secs != secs or secs < 0 or secs > 100 * 3600:
        raise Refused('bad_section', f'{what} must be a time from 0 on.')
    return secs


def clock(seconds):
    """1:02:03 or 2:03 (whole seconds)."""
    s = int(round(seconds))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def section_asked(start=None, end=None, seconds=None):
    """The part asked for, before the video's length is known: None (the whole video) or (start, end or None). Raises Refused."""
    a, b, n = parse_time(start, 'start'), parse_time(end, 'end'), parse_time(seconds, 'seconds')
    if a is None and b is None and n is None:
        return None
    if b is not None and n is not None:
        raise Refused('bad_section', 'Give end or seconds (a length from start), not both.')
    a = a or 0.0
    if n is not None:
        if n <= 0:
            raise Refused('bad_section', 'seconds is the length of the part: more than 0.')
        b = a + n
    if b is not None and b <= a:
        raise Refused('bad_section', f'end ({clock(b)}) must come after start ({clock(a)}).')
    return a, b


def _too_long_whole(info, dur):
    chapters = [{'start_s': round(float(c.get('start_time') or 0), 1), 'end_s': round(float(c.get('end_time') or 0), 1),
                 'title': c.get('title')} for c in (info.get('chapters') or []) if isinstance(c, dict)]
    raise Refused('too_long', f'That video is {clock(dur)} long; a whole video is fetched up to {MAX_VIDEO_S // 60} minutes. '
                              f'Ask for part of it instead, up to {MAX_VIDEO_S // 60} minutes: start and end (or start and seconds), '
                              f"for example start='0:00', end='5:00'.",
                  duration_s=dur, max_part_s=MAX_VIDEO_S, chapters=chapters)


def check_url(url):
    """The link tidied up, or Refused. One video on a public site; no playlist, channel or search page."""
    url = str(url or '').strip()
    if not url:
        raise Refused('not_a_video', 'Give the link to a video.')
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise Refused('not_a_video', 'The link must be an http or https address.')
    if u.username or u.password:
        raise Refused('private_or_signin', 'A link with a name or password in it is refused: letitedit never signs in.')
    host = u.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')) or re.fullmatch(r'[\d.]+|[0-9a-f:]+', host):
        raise Refused('unsupported_site', 'Only public websites by name are fetched (no local or numeric addresses).')
    path = u.path or '/'
    if _playlist_path.match(path) or (path in ('/', '') and not u.query):
        raise Refused('playlist', 'That link is a playlist, channel or search page: give the link to one video.')
    if re.search(r'youtube\.com$|youtu\.be$', host) and 'v=' not in u.query and not re.match(r'^/(shorts|embed|live|v)/[\w-]{6,}', path) \
            and 'youtu.be' not in host:
        raise Refused('playlist', 'That YouTube link is not one video (a video link has ?v=... or /shorts/...).')
    return url


def format_choice(short_side=MAX_HEIGHT):
    """yt-dlp's format choice: up to 1080p on the picture's short side, so a vertical video (1080x1920) comes at 1080x1920
    rather than the 480x854 a plain height<=1080 leaves it; H.264 with m4a sound first."""
    s = short_side
    return (f'bv*[aspect_ratio<1][width<={s}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={s}][vcodec^=avc1]+ba[ext=m4a]/'
            f'bv*[aspect_ratio<1][width<={s}]+ba/bv*[height<={s}]+ba/b[height<={s}]/b')


def _info(exe, url, work):
    """The downloader's description of the one video (no download), checked against what this tool takes."""
    code, out, err = _run(_base_args(exe) + ['-J', '--skip-download', url], INFO_TIMEOUT_S, work)
    if code != 0 or not out.strip():
        return None, err
    try:
        info = json.loads(out)
    except ValueError:
        return None, 'the downloader returned something that is not a description of a video'
    return info, err


def _judge(info, section=None):
    """Check the one video against what this tool takes; returns the part to fetch, (start, end), or None for all of it."""
    if info.get('_type') in ('playlist', 'multi_video', 'url'):
        entries = info.get('entries') or []
        raise Refused('playlist', f'That link is a collection ({len(entries)} items), not one video: give the link to one video.')
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise Refused('live', "That is a live stream (or one that hasn't started): only finished videos are fetched.")
    dur = info.get('duration')
    cap = MAX_VIDEO_S
    if not dur:
        raise Refused('not_a_video', "The site did not say how long it is, so it can't be checked against the length limit.")
    if info.get('availability') in ('needs_auth', 'subscriber_only', 'premium_only', 'private'):
        raise Refused('private_or_signin', 'That video needs a sign-in (private, members-only or paid), and letitedit never signs in.')
    dur = float(dur)
    if section is None:
        if dur > cap:
            _too_long_whole(info, dur)
        return None
    a, b = section
    if a >= dur - 1:
        raise Refused('bad_section', f'start ({clock(a)}) is past the end of the video ({clock(dur)}).', duration_s=dur)
    b = dur if b is None or b > dur else b
    if b - a > cap:
        raise Refused('too_long', f'That part is {clock(b - a)} long; a part is fetched up to {cap // 60} minutes. '
                                  f'Ask for a shorter part (the video is {clock(dur)} long).', duration_s=dur, max_part_s=cap)
    if a <= 0 and b >= dur:
        return None
    return round(a, 3), round(b, 3)


def _meta(info, url):
    return {'url': url, 'webpage_url': info.get('webpage_url') or url, 'id': info.get('id'),
            'site': info.get('extractor_key') or info.get('extractor'), 'title': info.get('title'),
            'uploader': info.get('uploader') or info.get('channel'), 'channel': info.get('channel'),
            'channel_url': info.get('channel_url'), 'duration_s': info.get('duration'), 'upload_date': info.get('upload_date'),
            'view_count': info.get('view_count'), 'license': info.get('license'), 'fetched_at': time.strftime('%Y-%m-%d %H:%M:%S')}


# ---------------------------------------------------------------- folders

def _slug(text, fallback='video'):
    s = re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-')[:48].strip('-')
    return s or fallback


def references_root():
    import letitedit.looks.learned_looks as learned_looks
    return Path(learned_looks.root()) / '.imports' / 'references'


def _probe(path):
    from letitedit.core import media
    return media.probe(path)


# ---------------------------------------------------------------- fetching

def _download(url, work, section=None):
    """Fetch the checked video (or the part asked for) into work; returns (file, info, downloader version, the part fetched
    or None). Raises Refused."""
    exe = ensure_downloader()
    attempts = 0
    while True:
        attempts += 1
        info, err = _info(exe, url, work)
        if info is not None:
            part = _judge(info, section)
            args = _base_args(exe) + ['--no-part', '--no-mtime', '--newline', '-o', str(Path(work) / 'file.%(ext)s'),
                                      '--max-filesize', str(MAX_VIDEO_BYTES)]
            if part is None:
                args += ['--match-filters', 'duration<=%d & !is_live' % MAX_VIDEO_S]
            else:
                # the part only (copied, so it starts on the nearest key frame at or before start: a moment early at most)
                args += ['--match-filters', '!is_live', '--download-sections', f'*{part[0]:g}-{part[1]:g}']
            args += ['-f', format_choice(), '--merge-output-format', 'mp4']
            args.append(url)
            code, out, err = _run(args, RUN_TIMEOUT_S, work)
            files = [p for p in Path(work).glob('file.*') if p.suffix.lower() in ('.mp4', '.mkv', '.webm')]
            if code == 0 and files:
                return max(files, key=lambda p: p.stat().st_size), info, _current()[0], part
            if code == 0 and not files:
                raise Refused('too_big', 'The file was over the 800 MB limit, so it was not fetched.')
        if attempts == 1 and _SITE_CHANGED.search(err or ''):
            upd = update_downloader()
            if upd.get('updated'):
                exe = ensure_downloader()
                continue
        reason, msg = _explain(err)
        raise Refused(reason, msg)


def _finish_file(src, dest, slack_s=5):
    """Check what was downloaded (a real video or audio file within the caps) and move it to dest."""
    info = _probe(src)
    streams = info.get('streams') or []
    need = 'video'
    if not any(s.get('codec_type') == need for s in streams):
        raise Refused('not_a_video', f'The fetched file has no {need} in it, so it was thrown away.')
    cap_bytes, cap_s = MAX_VIDEO_BYTES, MAX_VIDEO_S
    size = Path(src).stat().st_size
    dur = float((info.get('format') or {}).get('duration') or 0)
    if size > cap_bytes:
        raise Refused('too_big', f'The file is {size / 1048576:.0f} MB, over the {cap_bytes // 1048576} MB limit.')
    if dur > cap_s + slack_s:
        raise Refused('too_long', f'The file is {dur / 60:.1f} minutes, over the {cap_s // 60} minute limit.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return {'bytes': dest.stat().st_size, 'sha256': _sha256(dest), 'file_duration_s': round(dur, 3),
            'video': next(({'width': s.get('width'), 'height': s.get('height'), 'codec': s.get('codec_name')}
                           for s in streams if s.get('codec_type') == 'video'), None),
            'audio_codec': next((s.get('codec_name') for s in streams if s.get('codec_type') == 'audio'), None)}


def fetch_reference(url, name=None, folder=None, start=None, end=None, seconds=None):
    """A video from a link, as the reference a Look is learned from: <My Looks>\\.imports\\references\\<name>\\reference.mp4 (or
    <folder>\\reference.mp4) with record.json beside it. start and end (or start and seconds: a length) fetch
    only that part of the video, up to the same cap; a whole video over the cap is refused with its length and chapters."""
    work = tempfile.mkdtemp(prefix='letitedit-fetch-')
    try:
        try:
            url = check_url(url)
            if folder:
                dest_dir = Path(folder)
                if not dest_dir.is_absolute():
                    raise Refused('not_a_video', 'folder is a full folder path.')
            section = section_asked(start, end, seconds)
            file, info, version, part = _download(url, work, section)
            if not folder:
                base = _slug(name or info.get('title'), 'reference')
                if part and not name:
                    base = f"{base}-{clock(part[0]).replace(':', '.')}-{clock(part[1]).replace(':', '.')}"
                dest_dir = references_root() / base
                n = 2
                while (dest_dir / 'reference.mp4').exists():
                    dest_dir = references_root() / f'{base}-{n}'
                    n += 1
            dest = dest_dir / 'reference.mp4'
            if dest.exists():
                raise Refused('failed', f'{dest} already exists; give another name or folder.')
            facts = _finish_file(file, dest, slack_s=30 if part else 5)
        except Refused as ex:
            return _fail(ex.reason, str(ex), **ex.extra)
        except Exception as ex:  # noqa: BLE001
            return _fail('failed', f'{type(ex).__name__}: {ex}')
        rec = dict(_meta(info, url), kind='reference', file=dest.name, yt_dlp_version=version, **facts)
        if part:
            rec['section'] = {'start_s': part[0], 'end_s': part[1], 'start': clock(part[0]), 'end': clock(part[1]),
                              'note': 'only this part of the video was fetched; it may start a moment early, on a key frame'}
        rec_path = dest_dir / 'record.json'
        rec_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding='utf-8')
        return {'ok': True, 'kind': 'reference', 'path': str(dest), 'folder': str(dest_dir), 'record': rec,
                'record_path': str(rec_path), 'notice': NOTICE_REFERENCE, 'downloader': status()}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def history():
    """The reference videos fetched so far (newest last), each with its record."""
    rows = []
    root = references_root()
    for rec in sorted(root.glob('*/record.json')) if root.is_dir() else []:
        try:
            row = json.loads(rec.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        rows.append(dict(row, path=str(rec.with_name(row.get('file', 'reference.mp4')))))
    return rows


def main(argv):
    if not argv or argv[0] not in ('status', 'reference'):
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    res = status() if cmd == 'status' else fetch_reference(rest[0], rest[1] if len(rest) > 1 and rest[1] else None,
                                                           start=rest[2] if len(rest) > 2 else None,
                                                           end=rest[3] if len(rest) > 3 else None)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0 if res.get('ok', True) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
