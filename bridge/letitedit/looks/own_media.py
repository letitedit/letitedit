"""A personal Look's own media: the person's footage folders its cutaways come from first, their own intro and logo.

Kept in the Look's look.json as `own_media` (letitedit_learn save, package.own_media), never in its recipe (a recipe
holds no paths) and never sent anywhere (look_share leaves `own_media` out of a shared Look):

    own_media = {
      'broll': [{'folder': <an absolute folder>, 'skip': [names of folders under it left out], 'what': plain words}],
      'intro': {'file': <an absolute video file>, 'where': plain words, 'reference_at_s': s, 'seconds': s,
                'loudness_lufs': LUFS, 'notes': plain words},
      'logo': {'file': <an absolute picture or video file>, 'where': plain words, 'notes': plain words},
    }

The b-roll folders are read with their subfolders (letitedit_search reads one folder level, so `folders()` lists every
folder that holds a video, for its `files`). The picture index of those videos (the one letitedit_search builds: OpenCLIP,
a frame every SEARCH_DEFAULTS['every_s'] seconds, cached under the install's cache\\index keyed by file content, never
beside the footage) is built in the background: one file per PC-lock turn, at below-normal priority, stopping while the
cache's drive has less than MIN_FREE_GB free, shortest first; recordings over MAX_FILE_S are left for a search to index
when it reads them (so no PC-lock turn runs long). Its progress is kept in cache\\own-media\\<look id>.json.

    python own_media.py files  <look id> [--root <My Looks>]               the videos and folders, as JSON
    python own_media.py index  <look id> [--root ...] [--limit N]          build the picture index (resumable)
    python own_media.py status <look id> [--root ...]                      how far the index is
    python own_media.py kick   <look id> [--root ...]                      start index in the background, return at once
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

VIDEO = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp'}
MIN_FREE_GB = 40.0
MAX_FILE_S = 600.0       # longer recordings are left for a search to index (a PC-lock turn stays short)
TEXT_LIMIT = 400
INTRO_NUMBERS = ('reference_at_s', 'seconds', 'loudness_lufs')
PICTURE = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.tif', '.tiff', '.bmp'}


def _text(value, name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f'own_media {name} is plain words')
    value = ' '.join(value.split())
    if len(value) > TEXT_LIMIT:
        raise ValueError(f'own_media {name} is at most {TEXT_LIMIT} characters')
    return value or None


def validate(value):
    """The own_media record as save stores it, or ValueError. Paths must exist on this PC when saved."""
    if value is None:
        return None
    if not isinstance(value, dict) or not set(value) <= {'broll', 'intro', 'logo'}:
        raise ValueError('own_media is {broll: [{folder, skip?, what?}], intro: {file, where, ...}, '
                         'logo: {file, where, notes?}}')
    out = {}
    broll = value.get('broll')
    if broll is not None:
        if not isinstance(broll, list) or not broll:
            raise ValueError('own_media broll is a list of {folder, skip?, what?}')
        folders = []
        for item in broll:
            if not isinstance(item, dict) or not set(item) <= {'folder', 'skip', 'what'}:
                raise ValueError('each own_media broll item is {folder, skip?, what?}')
            folder = item.get('folder')
            if not isinstance(folder, str) or not Path(folder).is_absolute() or not Path(folder).is_dir():
                raise ValueError(f'own_media broll folder must be an existing absolute folder: {folder!r}')
            skip = item.get('skip') or []
            if not isinstance(skip, list) or not all(isinstance(name, str) and name.strip() for name in skip):
                raise ValueError('own_media broll skip is a list of folder names')
            entry = {'folder': str(Path(folder)), 'skip': [name.strip() for name in skip]}
            what = _text(item.get('what'), 'broll what')
            if what:
                entry['what'] = what
            folders.append(entry)
        out['broll'] = folders
    intro = value.get('intro')
    if intro is not None:
        if not isinstance(intro, dict) or not set(intro) <= {'file', 'where', 'notes', *INTRO_NUMBERS}:
            raise ValueError('own_media intro is {file, where, reference_at_s?, seconds?, loudness_lufs?, notes?}')
        file = intro.get('file')
        if (not isinstance(file, str) or not Path(file).is_absolute() or not Path(file).is_file()
                or Path(file).suffix.lower() not in VIDEO):
            raise ValueError(f'own_media intro file must be an existing video file: {file!r}')
        where = _text(intro.get('where'), 'intro where')
        if not where:
            raise ValueError('own_media intro needs where: plain words saying where the intro goes')
        entry = {'file': str(Path(file)), 'where': where}
        for key in INTRO_NUMBERS:
            number = intro.get(key)
            if number is None:
                continue
            if type(number) not in (int, float) or number != number or abs(number) > 36000:
                raise ValueError(f'own_media intro {key} is a number')
            entry[key] = round(float(number), 3)
        notes = _text(intro.get('notes'), 'intro notes')
        if notes:
            entry['notes'] = notes
        out['intro'] = entry
    logo = value.get('logo')
    if logo is not None:
        if not isinstance(logo, dict) or not set(logo) <= {'file', 'where', 'notes'}:
            raise ValueError('own_media logo is {file, where, notes?}')
        file = logo.get('file')
        if (not isinstance(file, str) or not Path(file).is_absolute() or not Path(file).is_file()
                or Path(file).suffix.lower() not in PICTURE | VIDEO):
            raise ValueError(f'own_media logo file must be an existing picture or video file: {file!r}')
        where = _text(logo.get('where'), 'logo where')
        if not where:
            raise ValueError('own_media logo needs where: plain words saying where the logo goes')
        entry = {'file': str(Path(file)), 'where': where}
        notes = _text(logo.get('notes'), 'logo notes')
        if notes:
            entry['notes'] = notes
        out['logo'] = entry
    return out or None


def files(media):
    """Every video under the b-roll folders (subfolders too, skipped names left out), in name order."""
    found = []
    for item in (media or {}).get('broll') or []:
        skip = {name.lower() for name in item.get('skip') or []}
        for directory, subfolders, names in os.walk(item['folder']):
            subfolders[:] = sorted((name for name in subfolders if name.lower() not in skip and not name.startswith('.')),
                                   key=str.lower)
            for name in sorted(names, key=str.lower):
                if Path(name).suffix.lower() in VIDEO and not name.startswith(('._', '~$')):
                    found.append(str(Path(directory) / name))
    return list(dict.fromkeys(found))


def folders(media):
    """Every folder that directly holds one of files(): what letitedit_search takes as `files`."""
    return list(dict.fromkeys(str(Path(path).parent) for path in files(media)))


# ------------------------------------------------------------------------------------------------- the Look's record

def _looks_root(looks_root=None):
    if looks_root:
        return Path(looks_root)
    import letitedit.looks.learned_looks as learned_looks
    return learned_looks.root()


def read(identity, looks_root=None):
    """The Look's own_media record (None when it has none)."""
    pointer = _looks_root(looks_root) / identity / 'look.json'
    return json.loads(pointer.read_text(encoding='utf-8-sig')).get('own_media')


def _cache():
    import letitedit.footage.index_tools as index_tools
    return Path(index_tools.CACHE)


def status_path(identity):
    return _cache() / 'own-media' / f'{identity}.json'


def _record(identity):
    path = status_path(identity)
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'state': 'not started'}
    if data.get('state') == 'running' and not _alive(data.get('pid')):
        # its process ended without finishing (stopped, the PC restarted): a later save or kick goes on from here
        data['state'] = 'stopped'
    return data


def status(identity, looks_root=None):
    path = status_path(identity)
    data = _record(identity)
    try:
        media = read(identity, looks_root)
        data['videos'] = len(files(media))
    except (OSError, ValueError):
        pass
    data['status_file'] = str(path)
    return data


def _write_status(identity, data):
    path = status_path(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.stem}.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data, indent=1), encoding='utf-8')
    os.replace(temporary, path)


def _free_gb(path):
    try:
        return shutil.disk_usage(path.anchor or str(path)).free / 1e9
    except OSError:
        return None


def index(identity, looks_root=None, limit=None, min_free_gb=MIN_FREE_GB, max_file_s=MAX_FILE_S, log=None):
    """Builds the picture index letitedit_search reads for the Look's b-roll videos, shortest first, one file per PC-lock
    turn (so no hold runs long): videos longer than max_file_s (None: no limit) are left for a search to index when it
    reads them, and counted in left_long. Resumable: files already indexed are only counted. Returns the status."""
    import letitedit.footage.index_tools as index_tools
    try:
        import letitedit.core.render_lock as render_lock
        render_lock.below_normal()
    except Exception:
        pass
    media = read(identity, looks_root)
    every_s = float(index_tools.SEARCH_DEFAULTS['every_s'])
    frames = index_tools.SEARCH_DEFAULTS['frames']
    started = time.time()
    data = {'state': 'running', 'look': identity, 'videos': 0, 'every_s': every_s, 'frames': frames,
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'done': 0, 'built': 0, 'cached': 0, 'errors': [],
            'footage_s': 0.0, 'index_bytes': 0, 'build_s': 0.0, 'pid': os.getpid()}
    lengths = {}
    for video in files(media):
        try:
            lengths[video] = float(index_tools._probe(video).get('duration') or 0)
        except Exception as error:     # unreadable: listed, never indexed
            data['errors'].append({'file': video, 'error': f'{type(error).__name__}: {error}'[:300]})
    videos = sorted(lengths, key=lambda video: lengths[video])
    long = [video for video in videos if max_file_s is not None and lengths[video] > max_file_s]
    videos = [video for video in videos if video not in long]
    data.update(videos=len(videos), left_long=len(long), left_long_s=round(sum(lengths[video] for video in long), 1),
                max_file_s=max_file_s)
    _write_status(identity, data)
    for count, video in enumerate(videos):
        if limit is not None and count >= limit:
            break
        free = _free_gb(_cache())
        if free is not None and free < min_free_gb:
            data.update(state='paused', why=f'{free:.0f} GB free on the cache drive, under {min_free_gb:.0f} GB')
            break
        t0 = time.time()
        try:
            result = index_tools.build_video_index([video], every_s, frames)
        except Exception as error:     # one file that can't be read never stops the rest
            data['errors'].append({'file': video, 'error': f'{type(error).__name__}: {error}'[:300]})
            data['done'] += 1
            _write_status(identity, data)
            continue
        took = time.time() - t0
        data['errors'] += [{'file': video, 'error': str(error)[:300]} for error in result.get('errors') or []]
        if result.get('built'):
            data['built'] += 1
            data['build_s'] = round(data['build_s'] + took, 1)
            data['footage_s'] = round(data['footage_s'] + float(result['built'][0].get('footage_s') or 0), 1)
        elif result.get('cached'):
            data['cached'] += 1
        mode = (result.get('modes') or {}).get(video)
        if mode:
            picture = index_tools._picture_file(video, every_s, mode)
            if picture.is_file():
                data['index_bytes'] += picture.stat().st_size
        data['done'] += 1
        data['elapsed_s'] = round(time.time() - started, 1)
        _write_status(identity, data)
        if log:
            log(f'{data["done"]}/{len(videos)} {Path(video).name} {took:.1f}s')
    else:
        data['state'] = 'done'
    if data['state'] == 'running':
        data['state'] = 'stopped' if limit is not None else 'done'
    data['elapsed_s'] = round(time.time() - started, 1)
    data['finished_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    data.pop('pid', None)
    _write_status(identity, data)
    return data


def kick(identity, looks_root=None):
    """Starts index() in the background (below-normal priority, no window) and returns at once; False when the Look
    has no b-roll folders or a run for it is already going. Never raises: a save never waits on it."""
    try:
        if not (read(identity, looks_root) or {}).get('broll'):
            return False
        current = status(identity, looks_root)
        if current.get('state') == 'running' and _alive(current.get('pid')):
            return False
        script = Path(__file__).resolve().parents[2] / 'own_media.py'
        args = [sys.executable, str(script), 'index', identity]
        if looks_root:
            args += ['--root', str(looks_root)]
        flags = 0
        if os.name == 'nt':
            flags = 0x00000008 | 0x08000000 | 0x00004000 | 0x00000200   # detached, no window, below normal, own group
        import letitedit.core.render_lock as render_lock
        render_lock.start_independent(args, creationflags=flags)
        return True
    except Exception:
        return False


def _alive(pid):
    if not isinstance(pid, int):
        return False
    try:
        import letitedit.core.render_lock as render_lock
        return bool(render_lock.pid_alive(pid))
    except Exception:
        return False


def describe(media, identity=None, looks_root=None):
    """What a Look's card shows of its own media: the folders for letitedit_search, how many videos, the intro and how
    far the index is."""
    if not media:
        return None
    out = {}
    if media.get('broll'):
        videos = files(media)
        out['broll'] = {'folders': [item['folder'] for item in media['broll']],
                        'what': [item['what'] for item in media['broll'] if item.get('what')],
                        'skip': sorted({name for item in media['broll'] for name in item.get('skip') or []}),
                        'videos': len(videos), 'search_files': folders(media)}
        if identity:
            state = _record(identity)
            out['broll']['index'] = {key: state[key] for key in ('state', 'done', 'videos', 'footage_s', 'index_bytes',
                                                                 'elapsed_s', 'left_long', 'why') if key in state}
    for key in ('intro', 'logo'):
        if media.get(key):
            out[key] = {**media[key], 'present': Path(media[key]['file']).is_file()}
    return out


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('files', 'index', 'status', 'kick'))
    parser.add_argument('look')
    parser.add_argument('--root')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--all', action='store_true', help='index long recordings too (long PC-lock turns)')
    args = parser.parse_args(argv)
    if args.action == 'files':
        media = read(args.look, args.root)
        result = {'videos': files(media), 'search_files': folders(media)}
    elif args.action == 'index':
        result = index(args.look, args.root, args.limit, max_file_s=None if args.all else MAX_FILE_S,
                       log=lambda line: print(line, flush=True))
    elif args.action == 'kick':
        result = {'started': kick(args.look, args.root)}
    else:
        result = status(args.look, args.root)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
