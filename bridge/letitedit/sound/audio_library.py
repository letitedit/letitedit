"""The person's music and sound-effects folders, and the search letitedit_library runs over them.

    audio_settings(sfx_folder=None, music_folder=None)  the chosen folders (appdata\\ai-audio-libraries.json, which the
                                                          editor reads too); given a folder, it is checked and saved
    audio_library(kind, query, offset, limit, asset_id)  files in that folder whose relative path holds the query (any
                                                          case), or one file by its id (with its sha256 and length)

With no sound-effects folder chosen, the asset library's CC0 sounds (assets\\sfx, bridge/assets.py) are searched.
The settings file and the ids are the ones managed episodes used.
"""
from __future__ import annotations

import hashlib
import csv
from pathlib import Path

from letitedit.core import media, store
from letitedit.core import paths as _paths

ROOT = Path(_paths.install_root())
CONFIG = ROOT / 'appdata/ai-audio-libraries.json'
AUDIO = {'.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.aiff', '.aif', '.wma'}


def audio_settings(sfx_folder=None, music_folder=None):
    current = store.read_json(CONFIG) if CONFIG.exists() else {'sfx_folder': '', 'music_folder': ''}
    if sfx_folder is not None or music_folder is not None:
        with store.file_lock(CONFIG.with_suffix('.lock')):
            current = store.read_json(CONFIG) if CONFIG.exists() else current
            for kind, folder in [('sfx', sfx_folder), ('music', music_folder)]:
                if folder is not None:
                    path = Path(folder).resolve(strict=True)
                    if not path.is_dir():
                        raise ValueError('Choose an existing audio folder')
                    current[kind + '_folder'] = str(path)
            store.write_json(CONFIG, current)
    # The local CC0 collection works without a first-run folder choice. An explicitly
    # chosen folder still wins, and an install without the collection stays unconfigured.
    if not current.get('music_folder') and (ROOT / 'music-library').is_dir():
        current = {**current, 'music_folder': str(ROOT / 'music-library')}
    return current


def _music_facts(root):
    if not (root / 'library.csv').is_file():
        return {}
    with (root / 'library.csv').open(encoding='utf-8-sig', newline='') as fh:
        return {r['File'].replace('\\', '/').casefold(): r for r in csv.DictReader(fh)}


def song_file(song):
    """A song named as letitedit_library lists it: a path that exists as given, or a line's path inside the music folder or the
    library that came with the install (T76: the AI passed a line's path to letitedit_soundtrack and got "No song at").
    Anything else comes back unchanged, for the caller's own "no such song" message. An on-demand song (ondemand:<id>, T89) comes
    down once and is kept; if it can't, the plain reason is raised."""
    if isinstance(song, str) and song.startswith('ondemand:'):
        import letitedit.sound.media_server as media_server
        try:
            return media_server.song_path(song)
        except media_server.Unavailable as ex:
            raise ValueError(str(ex)) from ex
    if not song or Path(song).is_file() or Path(song).is_absolute():
        return song
    for base in (audio_settings().get('music_folder'), ROOT / 'music-library'):
        if base and (Path(base) / song).is_file():
            return str((Path(base) / song).resolve())
    return song


def audio_library(kind, query='', offset=0, limit=40, asset_id=None, also_shipped=False,
                  bpm_min=None, bpm_max=None, min_length_s=None, max_length_s=None, with_whistle_tones=False):
    """also_shipped: for music, also search the music-library folder that comes with the install (the starter songs) when
    the person's chosen folder is another one. bpm_min / bpm_max / min_length_s / max_length_s keep only songs whose
    catalogue (library.csv) tempo and length are in range; a song with no catalogue tempo or length is left out.
    Music: a song whose scan (tonal_check; tonal.json beside the songs) found a held, pure, howl- or whistle-like tone is
    left out unless with_whistle_tones is True; result['whistle_tones_hidden'] counts them."""
    if kind not in ('sfx', 'music'):
        raise ValueError('Choose sfx or music')
    folder = audio_settings().get(kind + '_folder')
    if not folder and kind == 'sfx' and (ROOT / 'assets' / 'sfx').is_dir():
        folder = str(ROOT / 'assets' / 'sfx')   # no folder chosen: the asset library's CC0 sounds (bridge/assets.py)
    if not folder:
        return {'items': [], 'total': 0, 'configured': False}
    root = Path(folder)
    if not root.is_dir():
        raise ValueError('Audio library unavailable: ' + folder)
    roots = [root]
    shipped = ROOT / 'music-library'
    if kind == 'music' and also_shipped and shipped.is_dir():
        mine, theirs = root.resolve(), shipped.resolve()
        if mine != theirs and theirs not in mine.parents and mine not in theirs.parents:
            roots.append(shipped)
    ranged = any(v is not None for v in (bpm_min, bpm_max, min_length_s, max_length_s))
    items = []
    words = [w for w in query.casefold().split() if w]
    hidden = 0
    for base in roots:
        music_facts = _music_facts(base) if kind == 'music' else {}
        tones = {}
        if kind == 'music':
            import letitedit.sound.tonal_check as tonal_check
            tones = tonal_check.library_facts(base)
        for f in sorted(base.rglob('*')):
            if not (f.is_file() and f.suffix.lower() in AUDIO and store.inside(f, base)):
                continue
            relative = f.relative_to(base).as_posix()
            identity = hashlib.sha256((kind + ':' + str(base.resolve()) + ':' + relative).encode()).hexdigest()[:20]
            facts = music_facts.get(relative.casefold(), {})
            searchable = ' '.join((relative, facts.get('Title', ''), facts.get('Artist', ''),
                                   facts.get('Genre', ''), facts.get('Mood', '')))
            found = sum(w in searchable.casefold() for w in words)
            tone = tones.get(relative.casefold()) or {}
            if tone.get('flagged') and not with_whistle_tones and not asset_id and (found or not words):
                hidden += 1
                continue
            if not ((asset_id and identity == asset_id) or (not asset_id and (found or not words))):
                continue
            st = f.stat()
            item = {'id': identity, 'kind': kind, 'name': facts.get('Title') or f.stem,
                    'relative': relative, 'path': str(f.resolve()), 'bytes': st.st_size}
            if base is not root:
                item['other_folder'] = True     # its relative path is inside the shipped music-library, not `folder`
            if tone.get('flagged'):
                item['whistle_tones'] = (f"{tone.get('seconds_flagged'):g} s of held pure tones, longest "
                                         f"{tone.get('longest_s'):g} s")
            if facts:
                item.update(artist=facts.get('Artist') or '', genre=facts.get('Genre') or '',
                            mood=facts.get('Mood') or '', length=facts.get('Length') or '',
                            bpm=int(facts['BPM']) if facts.get('BPM', '').isdigit() else None)
                lic = facts.get('License') or ''
                if lic:
                    item['licence'] = 'CC0' if 'CC0' in lic else 'public domain' if 'ublic' in lic else lic
                try:
                    item['duration_s'] = sum(float(v) * 60**i for i, v in enumerate(reversed(item['length'].split(':'))))
                except ValueError:
                    pass
            if ranged and not asset_id:
                b, d = item.get('bpm'), item.get('duration_s')
                if ((bpm_min is not None or bpm_max is not None) and not b) or \
                   (bpm_min is not None and b < bpm_min) or (bpm_max is not None and b > bpm_max) or \
                   ((min_length_s is not None or max_length_s is not None) and d is None) or \
                   (min_length_s is not None and d < min_length_s) or (max_length_s is not None and d > max_length_s):
                    continue
            item['_found'] = found
            items.append(item)
    if asset_id:
        if len(items) != 1:
            raise ValueError('Audio asset missing or library changed; refresh the list')
        item = items[0]
        item.pop('_found', None)
        info = media.probe(item['path'])
        if not any(s['codec_type'] == 'audio' for s in info['streams']):
            raise ValueError('File has no audio stream')
        return {**item, 'sha256': store.digest(item['path']), 'duration_s': float(info['format']['duration'])}
    # Files with the most of the query's words come first (a search is words, not one phrase); when no file has them
    # all the reply says so.
    most = max((it['_found'] for it in items), default=0)
    items.sort(key=lambda it: -it['_found'])
    for it in items:
        del it['_found']
    offset = max(0, offset)
    limit = max(1, min(100, limit))
    result = {'items': items[offset:offset + limit], 'total': len(items), 'configured': True, 'folder': str(root)}
    if hidden:
        result['whistle_tones_hidden'] = hidden
        result['whistle_tones_note'] = (f'{hidden} matching song(s) left out: they hold a pure, howl- or whistle-like tone '
                                        '(with_whistle_tones=True lists them)')
    if items and most < len(words):
        result['partial_match'] = f'no file has all {len(words)} words; the most any has is {most}'
    return result
