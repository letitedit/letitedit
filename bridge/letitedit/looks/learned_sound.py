"""Measured, reusable sound evidence and licensed-library audition plans."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

FORMAT = 'letitedit-learned-sound/1'
SOUND_ROLES = {
    'whoosh': 'a short soft whoosh transition sound effect',
    'hit': 'a short soft impact pop sound effect',
    'riser': 'a rising swoosh sound effect building to a reveal',
    'click': 'a short dry click sound effect',
    'ambience': 'quiet continuous room tone background ambience',
}


def role_eligible(path, role):
    name = Path(path).stem.lower()
    if re.search(r'voice|footstep', name):
        return False
    patterns = {
        'whoosh': r'whoosh|swoosh|swish|transition',
        'hit': r'impact|hit|punch|bonk|pop|thump|slam|tap|knock',
        'riser': r'riser|rise|swoosh|whoosh|swell',
        'click': r'click|switch|tick|tap|key|mouse|button|snap',
        'ambience': r'ambience|ambient|room.?tone|rain|crowd|water|wind',
    }
    return bool(re.search(patterns[role], name))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)
    return str(path)


def validate(profile):
    if not isinstance(profile, dict) or profile.get('format') != FORMAT:
        raise ValueError('sound must be a measured learned-sound/1 profile')
    if not isinstance(profile.get('music'), dict) or not isinstance(profile.get('effects'), dict):
        raise ValueError('sound needs music and effects evidence')
    duration = profile.get('duration_s')
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('sound needs positive finite duration_s')
    matching = profile['music'].get('matching', {})
    if not isinstance(matching, dict):
        raise ValueError('sound music matching must be an object')
    events = profile['effects'].get('events', [])
    ranked = matching.get('ranked', [])
    if not isinstance(events, list) or not isinstance(ranked, list):
        raise ValueError('sound events and ranked music must be lists')
    shape = profile.get('shape')
    if shape is not None and (not isinstance(shape, dict) or shape.get('format') != 'letitedit-sound-shape/1'):
        raise ValueError('sound shape must be a measured letitedit-sound-shape/1')
    design = profile['effects'].get('design', {})
    if (not isinstance(design, dict) or any(role not in SOUND_ROLES or not isinstance(matches, list)
                                          for role, matches in design.items())):
        raise ValueError('sound design needs known roles and asset lists')
    validation_events = events + [{'t': 0, 'nonvoice_under_voice_db': -12, 'matches': matches}
                                 for matches in design.values()]
    for event in validation_events:
        if (not isinstance(event, dict) or type(event.get('t')) not in (int, float)
                or not 0 <= event['t'] < duration or not isinstance(event.get('matches', []), list)
                or type(event.get('confirmed', False)) is not bool):
            raise ValueError('sound events need source t, matches and boolean confirmed')
        for asset in event.get('matches', []):
            if not isinstance(asset, dict) or not isinstance(asset.get('facts'), dict):
                raise ValueError('sound effect matches need asset facts')
            facts = asset['facts']
            energy = asset.get('energy', {})
            values = [facts.get('duration_s'), facts.get('peak_s'), facts.get('peak_db'),
                      energy.get('rms_dbfs') if isinstance(energy, dict) else None,
                      asset.get('cosine'), asset.get('above_context'), event.get('nonvoice_under_voice_db')]
            if 'rms_db' in facts:
                values.append(facts['rms_db'])
            if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
                raise ValueError('sound effect levels, similarity and timing must be finite numbers')
            if not 0 <= facts['peak_s'] < facts['duration_s'] <= 12:
                raise ValueError('sound effect peak must fall inside its positive duration (up to 12 s)')
    for asset in ranked + [asset for event in validation_events for asset in event.get('matches', [])]:
        if (not isinstance(asset, dict) or not isinstance(asset.get('file'), str)
                or not isinstance(asset.get('sha256'), str) or len(asset['sha256']) != 64
                or any(character not in '0123456789abcdef' for character in asset['sha256'])
                or not any(token in str(asset.get('license', '')).lower() for token in ('cc0', 'public domain'))):
            raise ValueError('sound matches need file, SHA256 and CC0/public-domain licence')
    devices = profile['effects'].get('devices', [])
    if not isinstance(devices, list):
        raise ValueError('sound effect devices must be a list')
    for device in devices:
        lands = device.get('lands_on') if isinstance(device, dict) else None
        if (not isinstance(lands, dict) or lands.get('kind') not in ('cut', 'picture', 'word', 'nothing')
                or not (lands.get('offset_ms') is None or type(lands['offset_ms']) is int)
                or not str(device.get('sfx', '')).startswith('sfx:') or type(device.get('finds')) is not int
                or not isinstance(device.get('sha256'), str) or len(device['sha256']) != 64
                or not any(token in str(device.get('license', '')).lower() for token in ('cc0', 'public domain'))):
            raise ValueError('sound effect devices need sfx, finds, lands_on {kind, offset_ms}, SHA256 and a CC0 licence')
    if profile.get('synced') is not None:
        import letitedit.looks.sound_sync as sound_sync
        sound_sync.validate(profile['synced'])
    json.dumps(profile, allow_nan=False)
    return profile


def fingerprint(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def embedding(path, start, end, cache):
    import letitedit.footage.index_tools as index_tools
    identity = fingerprint(path)
    key = hashlib.sha256(f'{identity}:{start:.3f}:{end:.3f}:clap-htsat-unfused:2'.encode()).hexdigest()
    target = Path(cache) / (key + '.json')
    if target.exists():
        return np.asarray(read(target)['emb'], dtype=float)
    answer = index_tools._worker.ask('clap_span', ffmpeg=str(index_tools.FFMPEG), path=str(path),
                                    start=float(start), end=float(end), win_s=2.0, hop_s=2.0)
    vector = answer.get('emb')
    if not vector:
        raise ValueError(f'no CLAP audio windows: {path}')
    write(target, {'sha256': identity, 'emb': vector})
    return np.asarray(vector, dtype=float)


def audio_features(path, start=0, duration=None):
    import letitedit.looks.style_import_sound as sound
    signal = sound.decode_audio(path, start=start, duration=duration)
    envelope = sound.envelope_db(signal)
    active = envelope[envelope > -90]
    return {'energy': sound.energy_profile(envelope, sound.HOP / sound.SR),
            'rms_dbfs': round(float(np.median(active)), 2) if len(active) else -120.0,
            'dynamic_db': round(float(np.percentile(active, 90) - np.percentile(active, 10)), 2) if len(active) else 0,
            'sample_peak_dbfs': round(20 * math.log10(max(float(np.max(np.abs(signal))), 1e-6)), 2)}


def tempo_distance(left, right):
    if not left or not right:
        return 1.0
    return min(abs(math.log2(float(left) / float(right)) - octave) for octave in (-2, -1, 0, 1, 2))


def music_candidates(vector, tempo, dynamics, cache, limit=48, checkpoint=None):
    import letitedit.sound.audio_library as audio_library
    root = Path(audio_library.audio_settings().get('music_folder') or '')
    facts = audio_library._music_facts(root)
    eligible = []
    for relative, entry in facts.items():
        if not any(token in entry.get('License', '').lower() for token in ('cc0', 'public domain')):
            continue
        path = root / entry['File']
        if not path.is_file():
            continue
        try:
            bpm = float(entry.get('BPM') or 0)
        except ValueError:
            bpm = 0
        eligible.append((path, entry, bpm))
    nearest = sorted(eligible, key=lambda item: (tempo_distance(tempo, item[2]), str(item[0])))
    diverse = sorted(eligible, key=lambda item: hashlib.sha256(str(item[0]).encode()).hexdigest())
    shortlist = nearest[:limit // 2]
    for candidate in diverse:
        if len(shortlist) >= limit:
            break
        if candidate not in shortlist:
            shortlist.append(candidate)
    ranked, errors = [], []
    for path, entry, bpm in shortlist:
        try:
            from letitedit.core import media
            duration = float(media.probe(path)['format']['duration'])
            start = min(15.0, max(0, duration / 3))
            end = min(duration, start + 8)
            measured = audio_features(path, start, end - start)
            similarity = float(vector @ embedding(path, start, end, cache))
            tempo_score = max(0, 1 - 2 * tempo_distance(tempo, bpm)) if tempo and bpm else 0
            energy_score = math.exp(-abs(measured['dynamic_db'] - dynamics) / 10)
            ranked.append({'file': str(path), 'sha256': fingerprint(path), 'title': entry.get('Title'),
                           'library_relative': path.relative_to(root).as_posix(),
                           'license': entry['License'], 'tempo_bpm': bpm or None,
                           'cosine': round(similarity, 5), 'energy': measured,
                           'score': round(.8 * similarity + .15 * tempo_score + .05 * energy_score, 5),
                           'sample_s': [start, end]})
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            errors.append({'file': str(path), 'error': str(error)[:200]})
        if checkpoint:
            checkpoint()
    return {'ranked': sorted(ranked, key=lambda item: item['score'], reverse=True),
            'eligible': len(eligible), 'measured': len(ranked), 'errors': errors,
            'method': '0.80 audio cosine + 0.15 octave-tolerant tempo + 0.05 RMS dynamic-range similarity',
            'coverage': 'whole eligible library' if len(shortlist) == len(eligible) else 'shortlist, not whole-library optimum'}


def effect_candidates(stem, events, voice_dbfs, cache, limit=96, checkpoint=None):
    import letitedit.catalogs.assets as assets
    import letitedit.footage.index_tools as index_tools
    from letitedit.core import paths as _paths
    root = Path(_paths.install_root()) / 'assets/sfx'
    from letitedit.sound.audio_library import AUDIO
    files = sorted(path for folder in ('library', 'kenney', 'synth')
                   for path in (root / folder).rglob('*') if path.suffix.lower() in AUDIO)
    files.sort(key=lambda path: hashlib.sha256(str(path).encode()).hexdigest())
    measured, errors = [], []
    for path in files[:limit]:
        try:
            facts = assets.measure_sound(path)
            if not 0 < facts['duration_s'] <= 12:
                continue
            features = audio_features(path)
            vector = embedding(path, 0, min(4, facts['duration_s']), cache)
            measured.append((path, facts, features, vector))
        except (OSError, ValueError, RuntimeError) as error:
            errors.append({'file': str(path), 'error': str(error)[:200]})
        if checkpoint:
            checkpoint()
    results = []
    event_vectors = []
    for event in events:
        at = event['t']
        start, end = max(0, at - .25), at + .75
        vector = embedding(stem, start, end, cache)
        context = embedding(stem, max(0, at - 2.5), max(.1, at - .5), cache)
        event_vectors.append((vector, context))
        local = audio_features(stem, start, end - start)
        matches = sorted(({'file': str(path), 'sha256': fingerprint(path), 'license': 'CC0',
                           'library_relative': path.relative_to(root).as_posix(),
                           'cosine': round(float(vector @ asset_vector), 5),
                           'above_context': round(float((vector - context) @ asset_vector), 5),
                           'facts': facts, 'energy': features}
                          for path, facts, features, asset_vector in measured),
                         key=lambda item: item['cosine'], reverse=True)
        results.append({**event, 'matches': matches[:3], 'confirmed': False,
                        'nonvoice_under_voice_db': round(local['rms_dbfs'] - voice_dbfs, 2),
                        'level_scope': 'whole local nonvoice stem, music contamination included; not isolated effect level'})
    design = {}
    if measured and event_vectors:
        role_vectors = index_tools._worker.ask('clap_text', texts=list(SOUND_ROLES.values()))['emb']
        for role, role_vector in zip(SOUND_ROLES, role_vectors):
            ranked = []
            for path, facts, features, asset_vector in measured:
                if not role_eligible(path, role):
                    continue
                role_cosine = float(np.asarray(role_vector) @ asset_vector)
                reference_cosine, contrast = max((float(vector @ asset_vector),
                                                 float((vector - context) @ asset_vector))
                                                for vector, context in event_vectors)
                if role_cosine < .2 or contrast <= 0:
                    continue
                ranked.append({'file': str(path), 'sha256': fingerprint(path), 'license': 'CC0',
                               'library_relative': path.relative_to(root).as_posix(),
                               'facts': facts, 'energy': features, 'cosine': round(reference_cosine, 5),
                               'above_context': round(contrast, 5), 'role_cosine': round(role_cosine, 5),
                               'score': round(.75 * role_cosine + .25 * reference_cosine, 5)})
            design[role] = sorted(ranked, key=lambda asset: asset['score'], reverse=True)[:3]
    return {'events': results, 'design': design, 'confirmed_count': None, 'candidate_count': len(results),
            'library_eligible': len(files), 'library_measured': len(measured), 'errors': errors,
            'method': 'audio-to-audio CLAP against bundled CC0 sounds; design proposals also require catalog-name role '
                      'and CLAP text agreement. Cosine and context contrast are hypotheses, not event truth'}


def sound_devices(report, stems, measured, lock=None):
    """The reference's sound-effect devices (style_import_sound.find_devices; the importer setting
    SOUND_DEVICES_ON, or options sound_devices): {'devices': [...], 'devices_checked': {...}}, or a devices_error.
    Each device carries its library sound (sfx, library_relative, sha256, license) and what it lands on."""
    import letitedit.looks.style_import_sound as sound
    try:
        if lock is not None:
            lock.maybe_yield()
        sfx = sound.gate_sfx(dict(measured.get('sfx') or {}),
                             [float(c['t']) for c in report.get('cuts', [])] + sound.device_pictures(report), None,
                             picture_events=sound.picture_event_times(report))
        found = sound.find_devices(report['file'], report, stems['files'], sfx.get('events') or [])
    except Exception as error:  # noqa: BLE001 - the rest of the sound profile stands without devices
        return {'devices_error': f'{type(error).__name__}: {error}'[:300]}
    from letitedit.core import paths as _paths
    root = Path(_paths.install_root())
    devices = []
    for d in found['devices']:
        path = root / d['file']
        devices.append({**d, 'library_relative': path.relative_to(root / 'assets/sfx').as_posix(),
                        'sha256': fingerprint(path)})
    return {'devices': devices, 'devices_checked': {**found['checked'], 'finds': len(found['finds']),
                                                    'method': found['method']}}


def sound_shape(report, arrivals=()):
    """The reference's sound shape (letitedit.looks.sound_shape: its opening, its level through the body, its ending,
    its rate of sharp hits and what they land on), measured on its whole mix; None when it can't be read."""
    import letitedit.looks.sound_shape as shape_module
    try:
        cuts, text = shape_module._report_anchors(report)
        return shape_module.measure(report['file'], cuts, list(arrivals) or text,
                                    duration=float(report.get('duration_s') or 0) or None)
    except Exception:  # noqa: BLE001 - the rest of the sound profile stands without its shape
        return None


def analyse(report_path, out, options=None):
    import letitedit.footage.index_tools as index_tools
    import letitedit.sound.model_tools as model_tools
    import letitedit.core.render_lock as render_lock
    from letitedit.core import paths as _paths
    import letitedit.looks.style_import_sound as sound
    options = options or {}
    report = read(report_path)
    duration = float(report['duration_s'])
    output = Path(out)
    cache = Path(_paths.install_root()) / 'cache/learned-sound'
    music_limit = int(options.get('music_limit', 48))
    effect_limit = int(options.get('effect_limit', 96))
    if not 1 <= music_limit <= 1000 or not 1 <= effect_limit <= 1000:
        raise ValueError('library limits must be between 1 and 1000')
    def release_models(_info=None):
        index_tools.stop_worker()
        model_tools.release()

    with render_lock.Yielder('learned sound reference', timeout_s=1800, hold_s=240,
                             caller_pids=render_lock.ancestors(), on_pause=release_models) as lock:
        try:
            stems = model_tools.separate(report['file'], parts=['vocals', 'music', 'drums', 'bass', 'other'])
            measured, _ = sound.analyse(report['file'], {'duration': duration, 'has_audio': True},
                                        cuts=report.get('cuts', []), words=report.get('words', []),
                                        separate=True, classify=False,
                                        picture_events=sound.picture_event_times(report))
            stem = stems['files']['music']
            features = audio_features(stem)
            voice = audio_features(stems['files']['vocals'])
            windows = [[max(0, duration * fraction - 4), min(duration, duration * fraction + 4)]
                       for fraction in (.2, .5, .8)]
            vector = np.mean([embedding(stem, start, end, cache) for start, end in windows], axis=0)
            vector /= max(float(np.linalg.norm(vector)), 1e-9)
            music = measured['music']
            music['matching'] = music_candidates(vector, music.get('tempo_bpm'), features['dynamic_db'], cache,
                                                 music_limit, checkpoint=lock.maybe_yield)
            music['matching']['ranked'] = music['matching']['ranked'][:8]
            music['key'] = None
            music['key_limit'] = 'not measured; no key or instrument identity inferred from a mixed Demucs stem'
            music['features'] = features
            music['embedding'] = vector.round(6).tolist()
            music['sample_windows_s'] = windows
            descriptions = ['slow cinematic ambient music with sustained synth pads',
                            'emotional piano and string music', 'dark suspenseful orchestral music',
                            'uplifting acoustic guitar music', 'energetic electronic dance music',
                            'hip hop music with drums and bass', 'gentle lo fi instrumental music',
                            'rock music with electric guitars', 'bright playful plucked instrumental music',
                            'a person speaking with no music']
            labels = index_tools._worker.ask('clap_text', texts=descriptions)['emb']
            music['character_hypotheses'] = sorted(
                [{'description': text, 'cosine': round(float(vector @ np.asarray(label)), 5)}
                 for text, label in zip(descriptions, labels)], key=lambda item: item['cosine'], reverse=True)
            synced = measured.get('synced')
            arrivals = sorted(float(e['start_s'] if 'start_s' in e else e.get('t', e.get('start')))
                              for e in report.get('text_events', []) if isinstance(e, dict)
                              and (e.get('start_s') is not None or e.get('t') is not None or e.get('start') is not None))
            if synced is not None and arrivals:
                import letitedit.looks.sound_sync as sound_sync
                synced = sound_sync.analyse(stem, measured.get('synced', {}).get('voice_dbfs') or voice['rms_dbfs'],
                                            cuts=[c['t'] for c in report.get('cuts', [])], words=report.get('words', []),
                                            arrivals=arrivals, flashes=[g['t'] for g in report.get('transitions', [])
                                                                        if g.get('kind') in ('invert', 'flash')],
                                            duration=duration, stem=True)
            candidates = measured.get('sfx', {}).get('events', [])
            effects = effect_candidates(stem, candidates, voice['rms_dbfs'], cache, effect_limit,
                                        checkpoint=lock.maybe_yield)
            effects['candidate_per_minute'] = round(len(candidates) * 60 / duration, 3)
            if options.get('sound_devices', sound.SOUND_DEVICES_ON):
                effects.update(sound_devices(report, stems, measured, lock))
            shape = sound_shape(report, arrivals)
            profile = {'format': FORMAT, 'reference_sha256': fingerprint(report['file']), 'duration_s': duration,
                       'music': music, 'effects': effects, 'voice_rms_dbfs': voice['rms_dbfs'],
                       **({'synced': synced} if synced is not None else {}),
                       **({'shape': shape} if shape else {}),
                       'loudness': measured.get('loudness'), 'stem_loudness': stems.get('loudness'),
                       'limits': ['Demucs music is all nonvocals, including effects; other is not an isolated effects stem.',
                                  'Effect count, names and isolated levels need human listening; candidates are not confirmed.',
                                  'Tempo may be half/double; RMS dynamics and CLAP similarity are not taste or quality ratings.']}
            profile_path = write(output / 'sound-profile.json', profile)
            report['sound'] = measured
            report['learned_sound'] = profile
            augmented = write(output / 'report.json', report)
            return {'profile': profile_path, 'report': augmented,
                    'music': music['matching'], 'effects': effects, 'limits': profile['limits']}
        finally:
            release_models()


def resolve_asset(entry, kind):
    import letitedit.sound.audio_library as audio_library
    from letitedit.core import paths as _paths
    root = (Path(audio_library.audio_settings().get('music_folder') or '') if kind == 'music'
            else Path(_paths.install_root()) / 'assets/sfx')
    relative = entry.get('library_relative')
    path = (root / relative if relative else Path(entry.get('file', ''))).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'{kind} library asset missing or outside library: {path}')
    if fingerprint(path) != entry.get('sha256'):
        raise ValueError(f'{kind} library asset changed; analyse again: {path}')
    return str(path)


def plan(profile, project, duration_s, anchors, voice_dbfs, audition=False):
    profile = validate(read(profile) if isinstance(profile, (str, Path)) else profile)
    if not all(type(value) in (int, float) and math.isfinite(value) for value in (duration_s, voice_dbfs)):
        raise ValueError('duration_s and voice_dbfs must be finite numbers')
    if duration_s <= 0 or not -90 <= voice_dbfs <= 0:
        raise ValueError('positive duration_s and voice_dbfs in -90..0 required')
    allowed = {'cut', 'broll', 'emphasis', 'reveal', 'swell', 'drop', 'stop'}
    checked = []
    for anchor in anchors:
        if (not isinstance(anchor, dict) or anchor.get('role') not in allowed
                or ('sound' in anchor and anchor['sound'] not in SOUND_ROLES)
                or type(anchor.get('at')) not in (float, int) or not math.isfinite(anchor['at'])
                or not 0 <= anchor['at'] < duration_s):
            raise ValueError('anchors need at inside picture, a story role, and an optional known sound role')
        checked.append(anchor)
    checked.sort(key=lambda item: item['at'])
    music = profile['music']
    ranked = music.get('matching', {}).get('ranked', [])
    soundtrack = None
    warnings = list(profile.get('limits', []))
    import letitedit.looks.sound_opening as sound_opening
    opening = sound_opening.reference(profile)
    quiet = sound_opening.quiet_until(profile)
    # a reference flat out from its opening (no build): the stretch after it is the song's full material, at the
    # main level, not its middling material (a song's mid bars can sit 8 dB under its full part)
    body = ({'energy': 'high', 'level': 'mid'} if sound_opening.full_after_opening(profile) else {'energy': 'mid'})
    for candidate in ranked:
        try:
            song = resolve_asset(candidate, 'music')
        except ValueError as error:
            warnings.append(str(error))
            continue
        import letitedit.sound.soundtrack as soundtrack_module
        offset_lu = None
        stems = profile.get('stem_loudness', {})
        vocal_lu = stems.get('vocals', {}).get('integrated_lufs')
        music_lu = stems.get('music', {}).get('integrated_lufs')
        if vocal_lu is not None and music_lu is not None:
            offset_lu = max(-35, min(-6, music_lu - vocal_lu))
        boundaries = [anchor for anchor in checked if anchor['role'] == 'swell']
        sections, section_start = [], 0.0
        for anchor in boundaries:
            if anchor['at'] > section_start:
                if not sections and quiet is not None and anchor['at'] > quiet + 1:
                    # the reference is at its main level within its first seconds: only those may be quiet
                    if quiet > 0.5:
                        sections.append({'from': 0.0, 'to': quiet, 'energy': 'low'})
                    sections.append({'from': quiet if quiet > 0.5 else 0.0, 'to': anchor['at'], **body})
                else:
                    sections.append({'from': section_start, 'to': anchor['at'],
                                     'energy': 'low' if not sections else 'mid'})
                section_start = anchor['at']
        if not boundaries and quiet is not None and quiet > 0.5 and duration_s > quiet + 1:
            # no swell anchored: the reference's own quiet opening, then the music as it is after it
            sections.append({'from': 0.0, 'to': quiet, 'energy': 'low'})
            sections.append({'from': quiet, 'to': duration_s, **body})
        else:
            sections.append({'from': section_start, 'to': duration_s, 'energy': 'high' if boundaries else 'mid'})
        hits = []
        for anchor in checked:
            if anchor['role'] in ('reveal', 'broll') and (not hits or anchor['at'] - hits[-1]['at'] >= .25):
                hits.append({'at': anchor['at'], 'kind': 'phrase' if anchor['role'] == 'reveal' else 'bar'})
        protect = [{'from': anchor['at'], 'to': min(duration_s, anchor['at'] + 1), 'mode': 'drop_out'}
                   for anchor in checked if anchor['role'] == 'drop']
        stops = [anchor['at'] for anchor in checked if anchor['role'] == 'stop']
        if stops:
            protect.append({'from': min(stops), 'to': duration_s, 'mode': 'drop_out'})
        # the music comes up in the pauses only as far as the reference's own music does there (measured gap level
        # minus its level under speech), at most 3 dB; a reference whose music does not rise in its pauses gets none
        rise = 3.0
        ducking = music.get('ducking_db')
        if type(ducking) in (int, float) and math.isfinite(ducking) and (music.get('gaps_measured_s') or 0) >= 1:
            rise = max(0.0, min(3.0, float(ducking)))
        levels = ({'talk': offset_lu, 'none': offset_lu, 'low': offset_lu - 3,
                   'mid': offset_lu, 'high': min(-6, offset_lu + rise)} if offset_lu is not None else None)
        # matched by the loudness of the song's bars placed, so the bed sits at the reference's offset whichever
        # passages are used
        options = {'match_placed_loudness': True} if levels else None
        soundtrack_module.parse_request(sections, hits, protect, start=0, end=duration_s, levels=levels,
                                        options=options)
        soundtrack = {'project': project, 'song': song, 'sections': sections, 'hits': hits,
                      'protect': protect, 'start': 0, 'end': duration_s, 'levels': levels, 'mode': 'plan',
                      **({'options': options} if options else {})}
        break
    events = profile['effects'].get('events', [])
    available = [event for event in events if event.get('confirmed') or audition]
    rate = len(available) * 60 / profile['duration_s']
    budget = max(0, round(rate * duration_s / 60))
    placements, changes, skipped, lanes, used = [], [], [], [], set()
    priorities = {'reveal': 0, 'broll': 1, 'emphasis': 2, 'cut': 3}
    candidates = sorted((item for item in checked if item['role'] in priorities),
                        key=lambda item: (priorities[item['role']], item['at']))
    for anchor in candidates:
        if len(placements) >= budget:
            break
        if any(abs(anchor['at'] - item['at']) < .35 for item in placements):
            continue
        preferred = [event for event in available if bool(event.get('at_cut')) == (anchor['role'] in ('cut', 'broll'))]
        options = preferred or available
        sound_role = anchor.get('sound') or {'broll': 'whoosh', 'reveal': 'riser',
                                            'emphasis': 'hit', 'cut': 'click'}[anchor['role']]
        placed = False
        for event in options:
            source = (profile['effects'].get('design', {}).get(sound_role, []) if audition else [])
            if not source and audition and profile['effects'].get('design'):
                continue
            matches = sorted(source or event.get('matches', []), key=lambda asset: asset.get('sha256') in used)
            for asset in matches:
                if asset.get('above_context', 0) <= 0 or asset.get('cosine', 0) < .15:
                    continue
                try:
                    path = resolve_asset(asset, 'effects')
                except ValueError as error:
                    skipped.append(str(error))
                    continue
                facts = asset['facts']
                start = anchor['at'] - facts['peak_s']
                end = start + facts['duration_s']
                if start < 0 or end > duration_s:
                    continue
                relative_level = event['nonvoice_under_voice_db']
                if source:
                    relative_level = float(np.median([item['nonvoice_under_voice_db'] for item in available])) - 6
                target = voice_dbfs + min(-6, relative_level)
                source_rms = facts.get('rms_db', asset['energy']['rms_dbfs'])
                gain = min(target - source_rms, -3 - facts['peak_db'])
                lane = next((index for index, until in enumerate(lanes) if until <= start), len(lanes))
                track = 'Learned effects ' + str(lane + 1)
                if lane == len(lanes):
                    changes.append({'op': 'add_track', 'name': track, 'kind': 'audio'})
                    lanes.append(end)
                else:
                    lanes[lane] = end
                changes.append({'op': 'insert', 'track': track, 'at': round(start, 3),
                                 'item': {'clip': path, 'in': 0, 'out': facts['duration_s'],
                                          'sound_target': {'kind': 'story', 'word': anchor['role'], 'at': anchor['at']},
                                          'effects': [{'gain': round(gain, 2)}, {'fade_in_audio': .05},
                                                      {'fade_out_audio': .05}]}})
                used.add(asset['sha256'])
                placements.append({'at': anchor['at'], 'role': anchor['role'], 'file': path,
                                   'sound_role': sound_role, 'role_library_proposal': bool(source),
                                   'start': round(start, 3), 'gain_db': round(gain, 2),
                                   'target_rms_dbfs': round(target, 2), 'confirmed_reference': event.get('confirmed', False)})
                placed = True
                break
            if placed:
                break
    synced = profile.get('synced')
    synced_op = ({'op': 'fx', 'sync_sounds': {'rules': synced, 'voice_dbfs': voice_dbfs}}
                 if synced and (synced.get('transition_click') or synced.get('word_click')) else None)
    opening_fact = None
    if opening and opening['full_s'] is not None:
        full = body['energy'] == 'high'
        opening_fact = {'reference_full_s': opening['full_s'], 'reference_main_dbfs': opening['main_dbfs'],
                        'reference_top_dbfs': opening.get('top_dbfs'), 'quiet_until_s': quiet,
                        'full_after_opening': full,
                        'note': (f"the reference's music is within {sound_opening.FULL_DB:g} dB of its main level from "
                                 f"{opening['full_s']:g} s"
                                 + (': the plan keeps only that long quiet' if quiet is not None else '')
                                 + (" and asks for the song's full part from there, at the main level (the reference "
                                    'holds it within that of its loudest: no build)' if full else ''))}
    return {'status': 'audition' if audition else 'confirmed-events-only', 'soundtrack_request': soundtrack,
            'opening': opening_fact, 'synced_sounds': synced_op,
            'changes': changes, 'placements': placements, 'candidate_budget': budget,
            'placed_per_minute': round(len(placements) * 60 / duration_s, 3), 'skipped': skipped,
            'warnings': warnings + ['Nonvoice RMS sets only an audition ceiling, not an isolated SFX match.',
                                     'Role proposals sit 6 dB below median candidate nonvoice RMS; listen before approval.',
                                     'Listen and measure the rendered mix; this plan is not a quality verdict.']}
