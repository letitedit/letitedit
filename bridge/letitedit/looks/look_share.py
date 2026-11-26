"""Sharing learned Looks with letitedit: each Look's settings and recipe, sent in the background to letitedit.app.

A Look saved with share false (its look.json says "share": false) is never sent. What is sent: look.json (without
its own_media: the person's own footage folders and intro) and the current revision's .md and .json files, with every
absolute path, the Windows user name, embedded pictures, file fingerprints and the reference's speech removed first;
plus an install id (random), the app version and the Look's id and revision. Never sent: the example clips, .imports, the reference video, or any other file.

The setting ("share_looks" in sharing.json, on unless turned off) and this install's id, secret and record of what was
sent (state.json) live in the sharing folder: LETITEDIT_SHARING_DIR, else %LOCALAPPDATA%\\letitedit\\sharing for the
main profile, else the test profile's appdata\\sharing. The editor reads and writes the same files.

Where it sends: LETITEDIT_SHARE_URL when set ("off" sends nothing); otherwise the real server only for the main profile
with its own Documents\\letitedit\\My Looks, and nothing for a test profile, a named Looks folder or a named sharing
folder (tests and test windows never reach the real server).

    python look_share.py sync   [--root <My Looks>] [--folder <sharing folder>]   send what hasn't been sent (background)
    python look_share.py kick   [--root ...] [--folder ...]   start a background sync and return at once
    python look_share.py status [--root ...] [--folder ...]   the setting, the target and what was sent
    python look_share.py set on|off [--folder ...]            the setting
    python look_share.py remove [--root ...] [--folder ...]   delete what this install sent, and turn sharing off
    python look_share.py preview <Look folder>                the exact package a Look would send, as JSON
"""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REAL_URL = 'https://looks.letitedit.app'
FORMAT = 'letitedit-shared-look/1'
MAX_COMPRESSED = 2 * 1024 * 1024        # the server refuses a bigger body
RETRY_WAITS = (30, 120, 600, 1800)      # seconds between tries while offline, in one background run
LOG_LINES = 200
USER_AGENT = 'letitedit-look-share/1'
FILE_NAME = re.compile(r'[a-z0-9][a-z0-9_.-]{0,60}\.(?:md|json)')
LOOK_ID = re.compile(r'mine-[a-z0-9]+(?:-[a-z0-9]+)*')
REVISION = re.compile(r'[0-9a-f]{32}')

# the reference's speech: caption and on-screen words, quoted lines (a recipe's own text is kept)
SPEECH_KEYS = {'said', 'transcript', 'spoken', 'quote', 'quotes', 'text', 'word', 'words_said', 'speech_text',
               'lines_said'}
# the on-screen words read from the reference at one moment (its one-off text events)
READ_KEYS = {'one_offs': {'what'}}
# file fingerprints of the person's videos, and the list of frame pictures on this PC
DROP_KEYS = {'sha256', 'reference_sha256', 'pictures', 'md5', 'hash'}
# An absolute path: its start (a drive, a network share, a home or drive folder), then folders that may hold spaces
# (each followed by another separator), then a last part: a file name with an extension (spaces allowed) or a word.
_PATH = re.compile(r'''(?:[A-Za-z]:|\\\\[^\\/\s"'<>|]+|(?=/(?:Users|home|mnt|tmp|var|private|Volumes|[a-zA-Z])/))'''
                   r'''(?:[\\/][^\\/\n"'<>|*?]*(?=[\\/]))*'''
                   r'''[\\/](?:[^\\/\n"'<>|*?]*?\.[A-Za-z0-9]{1,5}(?![A-Za-z0-9])|[^\s\\/"'<>|*?]*)''')
_COLOUR = re.compile(r'#[0-9A-Fa-f]{3,8}')


# ----------------------------------------------------------------------------------------------- where things live

def _instance():
    try:
        import letitedit.app.letitedit_instances as instances
        return instances.current(), instances
    except Exception:
        return os.environ.get('LETITEDIT_INSTANCE', 'main'), None


def folder(explicit=None):
    """The sharing folder: the setting, this install's id and what was sent."""
    if explicit:
        return Path(explicit)
    named = os.environ.get('LETITEDIT_SHARING_DIR')
    if named:
        return Path(named)
    name, instances = _instance()
    if name == 'main':
        local = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(local) / 'letitedit' / 'sharing'
    if instances is not None:
        try:
            profile = json.loads((instances.ROOT / name / 'editor.json').read_text(encoding='utf-8-sig'))
            appdata = profile.get('appdata') if profile.get('instance_id') == name else None
            if isinstance(appdata, str) and Path(appdata).is_absolute():
                return Path(appdata) / 'sharing'
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return instances.ROOT / name / 'appdata' / 'sharing'
    return Path.home() / '.letitedit-test-sharing'


def _default_looks_root():
    import letitedit.looks.learned_looks as learned_looks
    return learned_looks._documents() / 'letitedit' / 'My Looks'


def _looks_root(explicit=None):
    if explicit:
        return Path(explicit)
    import letitedit.looks.learned_looks as learned_looks
    return learned_looks.root()


def target(looks_root=None, sharing_folder=None):
    """The server address to send to, or None when nothing may be sent from here (see the module's text)."""
    named = os.environ.get('LETITEDIT_SHARE_URL')
    if named is not None and named.strip():
        named = named.strip()
        return None if named.lower() in ('off', '0', 'no', 'none', 'false') else named.rstrip('/')
    if os.environ.get('LETITEDIT_SHARING_DIR') or os.environ.get('LETITEDIT_MY_LOOKS') or _instance()[0] != 'main':
        return None
    try:
        if looks_root is not None and Path(looks_root).resolve() != _default_looks_root().resolve():
            return None
        if sharing_folder is not None and Path(sharing_folder).resolve() != folder().resolve():
            return None
    except OSError:
        return None
    return REAL_URL


def _read_json(path, fallback):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, type(fallback)) else fallback
    except (OSError, ValueError):
        return fallback


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def enabled(sharing_folder=None):
    """On unless the person turned it off."""
    return _read_json(folder(sharing_folder) / 'sharing.json', {}).get('share_looks', True) is not False


def set_enabled(on, sharing_folder=None):
    path = folder(sharing_folder) / 'sharing.json'
    settings = _read_json(path, {})
    settings['share_looks'] = bool(on)
    _write_json(path, settings)
    return settings


def _state(sharing_folder=None, create=True):
    path = folder(sharing_folder) / 'state.json'
    state = _read_json(path, {})
    changed = False
    if create and not (isinstance(state.get('install_id'), str) and re.fullmatch(r'[0-9a-f]{32}', state['install_id'])):
        state['install_id'] = uuid.uuid4().hex
        changed = True
    if create and not (isinstance(state.get('secret'), str) and len(state['secret']) >= 32):
        state['secret'] = secrets.token_urlsafe(32)
        changed = True
    for key in ('sent', 'refused'):
        if not isinstance(state.get(key), dict):
            state[key] = {}
            changed = True
    if changed and create:
        _write_json(path, state)
    return state


def _save_state(state, sharing_folder=None):
    _write_json(folder(sharing_folder) / 'state.json', state)


def log(line, sharing_folder=None):
    """One line per problem in share.log (the last LOG_LINES kept); nothing on screen."""
    try:
        path = folder(sharing_folder) / 'share.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        old = path.read_text(encoding='utf-8').splitlines()[-(LOG_LINES - 1):] if path.exists() else []
        path.write_text('\n'.join(old + [f'{stamp} {" ".join(str(line).split())}']) + '\n', encoding='utf-8')
    except OSError:
        pass


def app_version():
    named = os.environ.get('LETITEDIT_APP_VERSION')
    if named:
        return named[:40]
    try:
        from letitedit.core import paths
        pointer = Path(paths.ROOT_TEXT) / 'app' / 'ai-assist-executable.txt'
        stem = Path(pointer.read_text(encoding='utf-8-sig').strip()).stem
        match = re.search(r'(\d{8}\.\d+)', stem)
        return match.group(1) if match else 'unknown'
    except Exception:
        return 'unknown'


# ----------------------------------------------------------------------------------------------- what is sent

def _display_name():
    """The Windows account's full name (\"First Last\"), when Windows has one."""
    if os.name != 'nt':
        return ''
    try:
        import ctypes
        size = ctypes.c_ulong(256)
        buffer = ctypes.create_unicode_buffer(256)
        if ctypes.windll.secur32.GetUserNameExW(3, buffer, ctypes.byref(size)):     # NameDisplay
            return buffer.value
    except Exception:
        pass
    return ''


def _user_names():
    """The Windows user name and the words of the account's full name, each of three letters or more."""
    names = set()
    for value in (os.environ.get('USERNAME'), os.environ.get('USER'), Path.home().name):
        if value and len(value) >= 3:
            names.add(value)
    for word in re.findall(r'[^\W\d_]{3,}', _display_name()):
        names.add(word)
    return sorted(names, key=len, reverse=True)


def _clean_text(text, users):
    text = _PATH.sub('<path>', text)
    for name in users:
        text = re.sub(r'(?i)(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', '<user>', text)
    return text


def _looks_like_picture(text):
    if text.startswith('data:'):
        return True
    if len(text) >= 256 and re.fullmatch(r'[A-Za-z0-9+/=_\-\s]+', text) and not re.search(r'\s\S+\s\S+\s', text):
        return True
    return False


def sanitize(value, users=None, key=None):
    """A copy with paths, the user name, embedded pictures, fingerprints and the reference's speech removed."""
    users = _user_names() if users is None else users
    if isinstance(value, dict):
        out = {}
        for name, item in value.items():
            lowered = str(name).lower()
            if lowered in DROP_KEYS:
                continue
            if (lowered in SPEECH_KEYS or lowered in READ_KEYS.get(key, ())) and isinstance(item, (str, list)) and not (
                    isinstance(item, str) and _COLOUR.fullmatch(item.strip())):
                continue
            out[_clean_text(str(name), users)] = sanitize(item, users, lowered)
        return out
    if isinstance(value, list):
        return [sanitize(item, users, key) for item in value]
    if isinstance(value, str):
        if _looks_like_picture(value):
            return '<removed picture>'
        return _clean_text(value, users)
    return value


def _strip_markdown(text, users):
    text = re.sub(r'!\[[^\]]*\]\(data:[^)]*\)', '', text)               # an embedded picture
    text = re.sub(r'data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+', '<removed picture>', text)
    return _clean_text(text, users)


def package(look_dir, install_id='', version=None):
    """The package a Look sends: look.json and its current revision's .md and .json files, cleaned. Raises ValueError
    for a folder that isn't a learned Look."""
    look_dir = Path(look_dir)
    pointer = _read_json(look_dir / 'look.json', {})
    identity, revision = pointer.get('id'), pointer.get('revision')
    if not (isinstance(identity, str) and LOOK_ID.fullmatch(identity)
            and isinstance(revision, str) and REVISION.fullmatch(revision)):
        raise ValueError(f'{look_dir.name}: not a learned Look (no id and revision in look.json)')
    if private(pointer):
        raise ValueError(f'{identity}: kept private (share false), never sent')
    users = _user_names()
    files = {'look.json': sanitize({key: value for key, value in pointer.items() if key != 'own_media'}, users)}
    version_dir = look_dir / 'revisions' / revision
    if not version_dir.is_dir():
        raise ValueError(f'{identity}: revision {revision} is missing')
    lighting_file = (version_dir / 'lighting.json').is_file()
    for path in sorted(version_dir.iterdir()):
        if not (path.is_file() and FILE_NAME.fullmatch(path.name)):
            continue
        if path.suffix == '.md':
            files[path.name] = _strip_markdown(path.read_text(encoding='utf-8-sig', errors='replace'), users)
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except ValueError:
            continue
        if path.name == 'evidence.json' and isinstance(data, dict) and lighting_file:
            # the same measurements as lighting.json, twice over: sent once
            data.pop('lighting', None)
            for reference in data.get('references') or []:
                if isinstance(reference, dict):
                    reference.pop('lighting', None)
        files[path.name] = sanitize(data, users)
    return {'format': FORMAT, 'install_id': install_id, 'app_version': version or app_version(),
            'look_id': identity, 'revision': revision, 'files': files}


def encode(payload):
    """The body sent: the package as gzip-compressed JSON. When it is over the size cap, evidence.json (the
    measurements the recipe was written from) is left out first; None when it is still too big."""
    body = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9)
    if len(body) > MAX_COMPRESSED and 'evidence.json' in payload['files']:
        smaller = {**payload, 'files': {k: v for k, v in payload['files'].items() if k != 'evidence.json'}}
        return encode(smaller)
    return body if len(body) <= MAX_COMPRESSED else None


# ----------------------------------------------------------------------------------------------- sending

class Offline(Exception):
    """The server couldn't be reached, or asked to try later."""


def _request(url, body, headers, timeout=30):
    request = urllib.request.Request(url, data=body, method='POST',
                                     headers={'User-Agent': USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, _read_json_bytes(reply.read())
    except urllib.error.HTTPError as error:
        return error.code, _read_json_bytes(error.read())
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise Offline(str(getattr(error, 'reason', error))) from None


def _read_json_bytes(data):
    try:
        value = json.loads(data.decode('utf-8'))
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError, AttributeError):
        return {}


def send(url, state, body, identity, revision):
    """'sent', 'refused' (the server said no to this package: not tried again) or raises Offline."""
    status, reply = _request(url + '/v1/looks', body, {
        'Content-Type': 'application/gzip', 'X-Install-Id': state['install_id'], 'X-Install-Secret': state['secret'],
        'X-Look-Id': identity, 'X-Look-Revision': revision})
    if status in (200, 201):
        return 'sent'
    if status == 429 or status >= 500:
        raise Offline(f'server {status} {reply.get("error", "")}'.strip())
    return 'refused:' + f'{status} {reply.get("error", "")}'.strip()


def _lock(sharing_folder):
    path = folder(sharing_folder) / 'sync.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if time.time() - path.stat().st_mtime > 3 * 3600:      # a run that died
            path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return path
    except FileExistsError:
        return None


def _pending(sharing_folder):
    return folder(sharing_folder) / 'pending'


def private(data):
    """A Look saved with share false (look.json "share": false) is the person's alone: it is never sent."""
    return isinstance(data, dict) and data.get('share') is False


def _looks(root):
    for pointer in sorted(Path(root).glob('mine-*/look.json')):
        data = _read_json(pointer, {})
        if isinstance(data.get('id'), str) and isinstance(data.get('revision'), str) and not private(data):
            yield pointer.parent, data['id'], data['revision']


def _one_pass(url, root, sharing_folder):
    """Sends every Look whose current revision hasn't been sent. Raises Offline to stop the pass."""
    done = []
    for look_dir, identity, revision in _looks(root):
        if not enabled(sharing_folder):
            return done
        state = _state(sharing_folder)
        if state['sent'].get(identity) == revision or state['refused'].get(identity) == revision:
            continue
        try:
            body = encode(package(look_dir, state['install_id']))
        except (ValueError, OSError) as error:
            log(f'{identity}: not sent, {error}', sharing_folder)
            state['refused'][identity] = revision
            _save_state(state, sharing_folder)
            continue
        if body is None:
            log(f'{identity}: not sent, over {MAX_COMPRESSED // 1024 // 1024} MB even without evidence.json',
                sharing_folder)
            state['refused'][identity] = revision
            _save_state(state, sharing_folder)
            continue
        if not enabled(sharing_folder):
            return done
        outcome = send(url, state, body, identity, revision)
        state = _state(sharing_folder)
        if outcome == 'sent':
            state['sent'][identity] = revision
            done.append(identity)
        else:
            state['refused'][identity] = revision
            log(f'{identity}: refused by the server, {outcome[8:]}', sharing_folder)
        _save_state(state, sharing_folder)
    return done


def sync(looks_root=None, sharing_folder=None, waits=RETRY_WAITS, sleep=time.sleep):
    """Sends what hasn't been sent, in this process. Offline: waits and tries again (waits), then stops until the next
    save, rename or start-up. Returns a summary; never raises."""
    root = _looks_root(looks_root)
    url = target(looks_root if looks_root else None, sharing_folder)
    if url is None:
        return {'ok': True, 'sent': [], 'skipped': 'sharing is not available here'}
    if not enabled(sharing_folder):
        return {'ok': True, 'sent': [], 'skipped': 'sharing is off'}
    lock = _lock(sharing_folder)
    if lock is None:
        _pending(sharing_folder).touch()
        return {'ok': True, 'sent': [], 'skipped': 'another sync is running; it will send this too'}
    sent = []
    try:
        try:
            import letitedit.core.render_lock as render_lock
            render_lock.below_normal()
        except Exception:
            pass
        tries = 0
        while True:
            _pending(sharing_folder).unlink(missing_ok=True)
            try:
                sent += _one_pass(url, root, sharing_folder)
            except Offline as error:
                if tries >= len(waits) or not enabled(sharing_folder):
                    log(f'offline, will try again at the next start: {error}', sharing_folder)
                    return {'ok': False, 'sent': sent, 'error': str(error)}
                sleep(waits[tries])
                tries += 1
                continue
            except Exception as error:     # never on screen: one line in the log
                log(f'sync stopped: {type(error).__name__}: {error}', sharing_folder)
                return {'ok': False, 'sent': sent, 'error': str(error)}
            if not _pending(sharing_folder).exists():
                return {'ok': True, 'sent': sent}
    finally:
        lock.unlink(missing_ok=True)


def kick(looks_root=None, sharing_folder=None):
    """Starts a background sync (below-normal priority, no window) and returns at once; nothing when sharing is off or
    not available here. Never raises: a save never waits on sharing."""
    try:
        root = Path(looks_root) if looks_root else None
        if target(root, sharing_folder) is None or not enabled(sharing_folder):
            return False
        script = Path(__file__).resolve().parents[2] / 'look_share.py'
        args = [sys.executable, str(script), 'sync']
        if root is not None:
            args += ['--root', str(root)]
        if sharing_folder:
            args += ['--folder', str(sharing_folder)]
        flags = 0
        if os.name == 'nt':
            flags = 0x00000008 | 0x08000000 | 0x00004000 | 0x00000200   # detached, no window, below normal, own group
        import letitedit.core.render_lock as render_lock
        render_lock.start_independent(args, creationflags=flags)
        return True
    except Exception as error:
        log(f'could not start sharing: {error}', sharing_folder)
        return False


def remove(looks_root=None, sharing_folder=None):
    """Deletes everything this install sent (proven by its secret), turns sharing off and starts a new install id."""
    url = target(looks_root, sharing_folder)
    set_enabled(False, sharing_folder)
    state = _state(sharing_folder)
    if url is None:
        return {'ok': False, 'error': 'sharing is not available here, so nothing was sent from this install'}
    body = json.dumps({'install_id': state['install_id'], 'secret': state['secret']}).encode('utf-8')
    try:
        status, reply = _request(url + '/v1/remove', body, {'Content-Type': 'application/json'})
    except Offline as error:
        return {'ok': False, 'error': f"couldn't reach letitedit.app ({error}); try again when you're online"}
    if status != 200:
        return {'ok': False, 'error': reply.get('error') or f'the server said {status}'}
    _save_state({'sent': {}, 'refused': {}}, sharing_folder)
    _state(sharing_folder)       # a new install id and secret, so nothing links the old to the new
    return {'ok': True, 'removed': int(reply.get('removed', 0)), 'sharing': 'off'}


def status(looks_root=None, sharing_folder=None):
    state = _state(sharing_folder, create=False)
    root = _looks_root(looks_root)
    looks = [{'id': identity, 'revision': revision,
              'sent': (state.get('sent') or {}).get(identity) == revision} for _, identity, revision in _looks(root)]
    return {'ok': True, 'share_looks': enabled(sharing_folder), 'target': target(looks_root, sharing_folder),
            'folder': str(folder(sharing_folder)), 'install_id': state.get('install_id'), 'looks': looks,
            'private': [pointer.parent.name for pointer in sorted(Path(root).glob('mine-*/look.json'))
                        if private(_read_json(pointer, {}))]}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Share learned Looks with letitedit')
    parser.add_argument('action', choices=['sync', 'kick', 'status', 'set', 'remove', 'preview'])
    parser.add_argument('value', nargs='?')
    parser.add_argument('--root')
    parser.add_argument('--folder')
    args = parser.parse_args(argv)
    if args.action == 'sync':
        reply = sync(args.root, args.folder)
    elif args.action == 'kick':
        reply = {'ok': True, 'started': kick(args.root, args.folder)}
    elif args.action == 'status':
        reply = status(args.root, args.folder)
    elif args.action == 'set':
        if args.value not in ('on', 'off'):
            parser.error('set takes on or off')
        reply = {'ok': True, **set_enabled(args.value == 'on', args.folder)}
    elif args.action == 'remove':
        reply = remove(args.root, args.folder)
    else:
        if not args.value:
            parser.error('preview takes a Look folder')
        reply = package(args.value, '<install id>')
    print(json.dumps(reply, indent=2, ensure_ascii=False))
    return 0 if reply.get('ok', True) else 1


if __name__ == '__main__':
    sys.exit(main())
