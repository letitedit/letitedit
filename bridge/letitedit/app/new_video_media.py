"""Stream a folder's media facts to New video without blocking the editor window."""
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.webm', '.mxf'}
AUDIO = {'.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg'}
PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp'}


def orientation(width, height, rotation=0):
    """'vertical', 'wide' or 'square' as the picture plays: a phone's upright clip is often stored wide and turned by
    its rotation (90 or -90), so the stored width and height swap."""
    if not width or not height:
        return None
    if round(abs(float(rotation or 0))) % 180 == 90:
        width, height = height, width
    if height > width * 1.05:
        return 'vertical'
    if width > height * 1.05:
        return 'wide'
    return 'square'


def probe(ffprobe, path, kind):
    """A media file's length ('d', seconds) and, for a video, the shape it plays in ('o')."""
    entries = 'format=duration' if kind != 'video' else 'format=duration:stream=width,height:stream_tags=rotate:stream_side_data=rotation'
    command = [ffprobe, '-v', 'error', '-show_entries', entries, '-of', 'json']
    if kind == 'video':
        command += ['-select_streams', 'v:0']
    result = subprocess.run(command + [path], capture_output=True, text=True, timeout=4)
    facts = {'d': None}
    if result.returncode != 0:
        return facts
    data = json.loads(result.stdout or '{}')
    try:
        facts['d'] = round(float(data.get('format', {}).get('duration')), 1)
    except (TypeError, ValueError):
        pass
    streams = data.get('streams') or []
    if kind == 'video' and streams:
        stream = streams[0]
        rotation = (stream.get('tags') or {}).get('rotate') or 0
        for side in stream.get('side_data_list') or []:
            if 'rotation' in side:
                rotation = side['rotation']
        try:
            facts['o'] = orientation(int(stream.get('width') or 0), int(stream.get('height') or 0), float(rotation))
        except (TypeError, ValueError):
            pass
    return facts


def scan(folder, ffprobe, cache_file):
    try:
        cache = json.loads(Path(cache_file).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        cache = {}
    changed = False
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.casefold())
        entries = [e for e in entries if e.is_file() and Path(e.name).suffix.lower() in VIDEO | AUDIO | PHOTO]
    except OSError as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
        return
    print(json.dumps({'count': len(entries)}), flush=True)
    for entry in entries:
        suffix = Path(entry.name).suffix.lower()
        kind = 'video' if suffix in VIDEO else 'audio' if suffix in AUDIO else 'photo'
        item = {'name': entry.name, 'path': entry.path, 'kind': kind}
        if kind != 'photo':
            try:
                stat = entry.stat()
                key = f'{entry.path}|{stat.st_size}|{stat.st_mtime_ns}'
                facts = cache.get(key)
                if not isinstance(facts, dict):     # not seen yet, or seen before the picture's shape was kept
                    facts = probe(ffprobe, entry.path, kind)
                    cache[key] = facts
                    changed = True
                if facts.get('d') is not None:
                    item['duration_s'] = facts['d']
                if facts.get('o'):
                    item['orientation'] = facts['o']
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        print(json.dumps({'file': item}, ensure_ascii=False), flush=True)
        if kind != 'audio':
            try:
                stat = entry.stat()
                token = f'{entry.path}|{stat.st_size}|{stat.st_mtime_ns}'.encode('utf-8')
                thumbnails = Path(cache_file).with_suffix('.thumbnails')
                thumbnail = thumbnails / (hashlib.sha256(token).hexdigest() + '.png')
                if not thumbnail.is_file():
                    thumbnails.mkdir(parents=True, exist_ok=True)
                    temporary = thumbnail.with_suffix('.part.png')
                    ffmpeg = str(Path(ffprobe).with_name('ffmpeg.exe'))
                    result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', entry.path,
                                             '-an', '-frames:v', '1', '-vf',
                                             'scale=64:44:force_original_aspect_ratio=decrease', '-y', str(temporary)],
                                            capture_output=True, timeout=8)
                    if result.returncode == 0 and temporary.is_file():
                        os.replace(temporary, thumbnail)
                    else:
                        temporary.unlink(missing_ok=True)
                if thumbnail.is_file():
                    print(json.dumps({'thumbnail': {'path': entry.path, 'image': str(thumbnail)}},
                                     ensure_ascii=False), flush=True)
            except (OSError, subprocess.TimeoutExpired):
                pass
    if changed:
        try:
            target = Path(cache_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, target)
        except OSError:
            pass


if __name__ == '__main__':
    scan(*sys.argv[1:4])
