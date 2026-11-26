"""Start a project for the person to edit with the AI themselves: New video's "Edit with the AI myself" and Home's
"Start with an empty timeline".

    start(folder, kind='short', files=())   -> {project, width, height, fps, clips, skipped}
    python start_project.py --folder <project folder> --kind short|long [<file> ...]   one JSON line on stdout

The project is written in `folder` (a folder of its own in the person's Projects folder, made by the editor) as
`<folder name>.mlt`, at the format's size: a Short is 1080x1920, a YouTube video 1920x1080. Its frame rate is the
first video's (halved when over 31 fps, so 60 and 59.94 fps phone clips make a 30 or 29.97 fps timeline), else 30.
The files go on the timeline whole, one after another in the order given, and into the project's bin: videos and
pictures on V1 (a picture for 4 s), sound files on A1. A file that can't be read is left out and listed under
`skipped`. With no files the project is empty. Footage stays where it is: nothing is copied or moved, nothing is
transcribed, and no AI runs. The project's edit lease is released at once, so the AI can edit straight away.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from letitedit.core import long_paths  # noqa: E402
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)

ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
FFPROBE = ROOT / 'app' / 'ffprobe.exe'
SIZES = {'short': (1080, 1920), 'long': (1920, 1080)}
PHOTO_S = 4.0
VIDEO = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf'}
AUDIO = {'.wav', '.mp3', '.m4a', '.flac', '.aac', '.ogg'}
PHOTO = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
LABEL = 'letitedit: the clips you chose'


def _probe(path):
    """{'video': fps or None, 'audio': bool} of a media file, or None when ffprobe can't read it."""
    try:
        r = subprocess.run([str(FFPROBE), '-v', 'error', '-show_entries', 'stream=codec_type,avg_frame_rate,r_frame_rate',
                            '-of', 'json', str(path)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        streams = json.loads(r.stdout or '{}').get('streams') or []
    except ValueError:
        return None
    out = {'video': None, 'audio': False}
    for s in streams:
        if s.get('codec_type') == 'audio':
            out['audio'] = True
        elif s.get('codec_type') == 'video' and out['video'] is None:
            for key in ('avg_frame_rate', 'r_frame_rate'):
                try:
                    rate = float(Fraction(s.get(key) or '0/1'))
                except (ValueError, ZeroDivisionError):
                    rate = 0.0
                if rate > 0:
                    out['video'] = rate
                    break
            else:
                out['video'] = 0.0
    return out if (out['video'] is not None or out['audio']) else None


def timeline_fps(rate):
    """The project's frame rate for a first clip at `rate` fps: kept up to 31 fps, halved above (60 -> 30)."""
    if not rate or rate <= 0:
        return 30
    while rate > 31:
        rate /= 2
    for standard in (23.976, 24, 25, 29.97, 30):
        if abs(rate - standard) < 0.02:
            return standard
    return round(rate)


def _sort(files):
    """(items for V1, items for A1, skipped, first video's rate) in the order given."""
    pictures, sounds, skipped, first_rate = [], [], [], None
    for f in files:
        p = Path(f)
        suffix = p.suffix.lower()
        if not p.is_file():
            skipped.append({'file': str(f), 'why': 'not found'})
            continue
        if suffix in PHOTO:
            pictures.append({'clip': str(p), 'len': PHOTO_S})
            continue
        facts = _probe(p)
        if facts is None or (suffix not in VIDEO | AUDIO and not facts.get('video') and not facts.get('audio')):
            skipped.append({'file': str(p), 'why': "can't be read"})
            continue
        if facts.get('video') and suffix not in AUDIO:
            pictures.append({'clip': str(p)})
            if first_rate is None:
                first_rate = facts['video']
        else:
            sounds.append({'clip': str(p)})
    return pictures, sounds, skipped, first_rate


def _add_to_bin(project):
    """Every clip on the timeline also in the project's bin (Shotcut's playlist, `main_bin`), in timeline order, each
    as a producer of its own so trimming one never trims the other."""
    tree = ET.parse(project)
    root = tree.getroot()
    main_bin = root.find("playlist[@id='main_bin']")
    if main_bin is None:
        return 0
    services = {e.get('id'): e for e in root if e.tag in ('producer', 'chain') and e.get('id')}
    tractor = root.find('tractor')
    added, seen, position = 0, set(), list(root).index(main_bin)
    for track in (tractor.findall('track') if tractor is not None else []):
        playlist = root.find(f"playlist[@id='{track.get('producer')}']")
        if playlist is None or track.get('producer') == 'background':
            continue
        for entry in playlist.findall('entry'):
            source = services.get(entry.get('producer'))
            if source is None or entry.get('producer') in seen:
                continue
            seen.add(entry.get('producer'))
            copy = ET.fromstring(ET.tostring(source))
            copy.set('id', f'bin{added}')
            for prop in copy.findall('property'):
                if prop.get('name') in ('shotcut:uuid',):
                    copy.remove(prop)
            root.insert(position, copy)
            position += 1
            ET.SubElement(main_bin, 'entry', {'producer': copy.get('id'), 'in': entry.get('in', '0'),
                                              'out': entry.get('out', '0')})
            added += 1
    if added:
        ET.indent(tree, space='  ')
        tree.write(project, encoding='utf-8', xml_declaration=True)
    return added


def start(folder, kind='short', files=()) -> dict:
    """Write the project (module doc). Raises FileExistsError when the folder already holds its project."""
    if kind not in SIZES:
        raise ValueError("kind is 'short' or 'long'")
    folder = Path(folder)
    project = folder / f'{folder.name}.mlt'
    long_paths.check(*long_paths.project_files(project))
    folder.mkdir(parents=True, exist_ok=True)
    width, height = SIZES[kind]
    pictures, sounds, skipped, rate = _sort(list(files or []))
    fps = timeline_fps(rate)
    from letitedit.timeline.letitedit_extras import new_project
    new_project(str(project), width=width, height=height, fps=fps, claim=False)
    clips = 0
    if pictures or sounds:
        import letitedit.timeline.edit_script as es
        script = es.read(project)
        for track in script['tracks']:
            if track['name'] == 'V1' and pictures:
                track['items'] = [dict(item) for item in pictures]
                clips += len(pictures)
            elif track['name'] == 'A1' and sounds:
                track['items'] = [dict(item) for item in sounds]
                clips += len(sounds)
        es.apply_changes(project, script=script, keep_history=False, actor='letitedit', label=LABEL, lease_s=0)
        _add_to_bin(project)
    return {'project': str(project), 'width': width, 'height': height, 'fps': fps, 'clips': clips, 'skipped': skipped}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    args = sys.argv[1:]
    options = {}
    for flag in ('--folder', '--kind'):
        if flag in args:
            i = args.index(flag)
            options[flag] = args[i + 1]
            del args[i:i + 2]
    try:
        out = start(options.get('--folder'), options.get('--kind', 'short'), args)
    except long_paths.PathTooLong as error:
        out = {'error': str(error)}                 # already the person's own words
    except Exception as error:  # noqa: BLE001 - the editor shows the reason
        out = {'error': f'{type(error).__name__}: {error}'}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
