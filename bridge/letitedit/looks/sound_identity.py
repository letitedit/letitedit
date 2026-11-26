"""Local sound names, same-kind library retrieval, and small-speaker screening."""
from __future__ import annotations

import re
import hashlib
import json
from pathlib import Path

import numpy as np


KINDS = {
    'camera shutter': ('a camera shutter clicking and taking a photograph', 'an old camera flash firing'),
    'typewriter': ('a mechanical typewriter typing and clacking', 'typewriter keys tapping on paper'),
    'alarm clock': ('an alarm clock ringing repeatedly', 'an electronic alarm clock beeping'),
    'record scratch': ('a vinyl record scratching as a DJ stops it', 'a record scratch sliding down in pitch'),
    'whoosh': ('a quick airy whoosh sound effect', 'a swoosh of air sweeping past'),
    'riser': ('a rising sweep building up to a transition', 'a rising noise sound effect'),
    'hit': ('a deep impact thump or boom sound effect', 'a punchy cinematic impact hit'),
    'pop': ('a short popping bubble sound effect', 'a cartoon pop sound'),
    'click': ('a short interface button click or switch', 'a computer mouse clicking'),
    'keyboard': ('a computer keyboard typing', 'fingers tapping computer keyboard keys'),
    'bell': ('a bicycle bell ringing', 'a small metal bell dinging'),
    'notification': ('an electronic notification ding or chime', 'a short notification ping'),
    'horn': ('a car horn honking', 'a vehicle horn sounding'),
    'spring': ('a cartoon spring boinging', 'a bouncy spring twanging'),
    'drill': ('an electric power drill running', 'a power tool drilling'),
    'glitch': ('a digital glitch or laser zap sound effect', 'an electronic glitch buzzing'),
    'whistle': ('a person whistling', 'a slide whistle blowing'),
    'clap': ('hands clapping', 'a crowd applauding'),
    'foley': ('a cork popping out of a bottle', 'a tin can clattering'),
    'music': ('instrumental music playing', 'a musical note played on an instrument'),
    'speech': ('a person talking', 'human speech'),
    'noise': ('background noise or static', 'silence and faint room noise'),
}
ALIASES = {
    'camera shutter': ('shutter', 'camera', 'photo flash', 'photograph flash'),
    'typewriter': ('typewriter',), 'alarm clock': ('alarm',), 'record scratch': ('record scratch', 'scratch dj'),
    'whoosh': ('whoosh', 'swoosh', 'swipe', 'sweep'), 'riser': ('riser',),
    'hit': ('impact', 'boom', 'thump', 'hit', 'explosion', 'bass drop'), 'pop': ('pop',),
    'click': ('click', 'switch', 'rollover', 'tick', 'tap'), 'keyboard': ('keyboard', 'key'),
    'bell': ('bell',), 'notification': ('notification', 'ding', 'chime', 'ping', 'beep'),
    'horn': ('horn',), 'spring': ('spring', 'boing'), 'drill': ('drill',),
    'glitch': ('glitch', 'laser', 'zap'), 'whistle': ('whistle',), 'clap': ('clap', 'applause'),
    'foley': ('cork', 'tin can'),
}
REJECT_KINDS = {'music', 'speech', 'noise'}
POLICY = {'min_cosine': 0.25, 'min_margin': 0.03, 'peak_dbfs': -30.0, 'active_rms_dbfs': -40.0,
          'speaker_low_hz': 600, 'speaker_high_hz': 8000, 'min_speaker_fraction': 0.2,
          'max_offset_ms': 125, 'panns_min': 0.2}
SLICES = ((0, .18), (.18, .6), (0, .6), (0, 1.2))
PANN_CLASSES = {'camera shutter': (416, 417), 'typewriter': (385,), 'alarm clock': (395,),
                'record scratch': (215,), 'whoosh': (459,), 'hit': (460, 466, 467),
                'pop': (434,), 'click': (491,), 'keyboard': (384,), 'bell': (200, 203),
                'notification': (205, 481, 482, 483), 'horn': (308, 318), 'spring': (498,),
                'drill': (425,), 'whistle': (402, 403), 'clap': (63, 67)}


def prompts():
    return [f'The sound of {description}.' for descriptions in KINDS.values() for description in descriptions]


def prototypes(text_embeddings):
    embeddings = np.asarray(text_embeddings, dtype=np.float64)
    if embeddings.shape[0] != len(prompts()):
        raise ValueError('Sound-name embeddings do not match the prompt vocabulary')
    grouped = embeddings.reshape(len(KINDS), 2, -1).mean(axis=1)
    return grouped / np.maximum(np.linalg.norm(grouped, axis=1, keepdims=True), 1e-9)


def identify(embedding, text_prototypes):
    scores = np.asarray(text_prototypes) @ np.asarray(embedding)
    order = np.argsort(scores)[::-1]
    winner, runner = int(order[0]), int(order[1])
    name = list(KINDS)[winner]
    confidence, margin = float(scores[winner]), float(scores[winner] - scores[runner])
    reason = ('not an added effect' if name in REJECT_KINDS else
              'sound name uncertain' if confidence < POLICY['min_cosine'] or margin < POLICY['min_margin'] else None)
    return {'kind': name, 'cosine': round(confidence, 4), 'margin': round(margin, 4), 'reason': reason}


def library_kinds(item):
    text = ' '.join(str(item.get(field) or '') for field in ('id', 'name', 'category', 'tags')).lower()
    text = re.sub(r'[_/\-]+', ' ', text)
    found = set()
    for kind, aliases in ALIASES.items():
        if any(re.search(r'\b' + re.escape(alias) + r'\b', text) for alias in aliases):
            found.add(kind)
    if 'typewriter' in found:
        found.discard('keyboard')
        found.discard('click')
    if 'camera shutter' in found:
        found.discard('click')
    if 'alarm clock' in found:
        found.discard('notification')
    if 'record scratch' in found:
        found.discard('whoosh')
    return found


def audibility(samples, sample_rate):
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if not audio.size or not np.isfinite(audio).all():
        return {'ok': False, 'reason': 'empty or invalid audio'}
    peak = float(np.max(np.abs(audio)))
    active = audio[np.abs(audio) >= peak * 0.1]
    peak_db = float(20 * np.log10(max(peak, 1e-12)))
    rms_db = float(10 * np.log10(max(float(np.mean(active ** 2)) if active.size else 0, 1e-24)))
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    frequencies = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    band = (frequencies >= POLICY['speaker_low_hz']) & (frequencies <= POLICY['speaker_high_hz'])
    fraction = float(spectrum[band].sum() / max(float(spectrum.sum()), 1e-24))
    reason = ('near-silent library audio' if peak_db < POLICY['peak_dbfs'] or rms_db < POLICY['active_rms_dbfs'] else
              'little energy in the small-speaker band' if fraction < POLICY['min_speaker_fraction'] else None)
    return {'ok': reason is None, 'reason': reason, 'peak_dbfs': round(peak_db, 2),
            'active_rms_dbfs': round(rms_db, 2), 'speaker_fraction': round(fraction, 4)}


def library_measurements(items, root, decode, sample_rate, cache_file):
    root, cache_file = Path(root), Path(cache_file)
    cached = json.loads(cache_file.read_text(encoding='utf-8-sig')) if cache_file.exists() else {}
    previous = cached.get('files', {}) if cached.get('policy') == POLICY else {}
    files, measurements = {}, []
    for item in items:
        path = root / item['file']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = previous.get(digest)
        if entry is None:
            entry = audibility(decode(path), sample_rate)
        files[digest] = entry
        measurements.append(entry)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix('.tmp')
    temporary.write_text(json.dumps({'policy': POLICY, 'files': files}), encoding='utf-8')
    temporary.replace(cache_file)
    return measurements


def choose(embedding, identity, items, library_embeddings, measurements):
    if identity['reason']:
        return {'reason': identity['reason'], 'identity': identity}
    eligible = [index for index, item in enumerate(items) if identity['kind'] in library_kinds(item)
                and measurements[index].get('ok')]
    if not eligible:
        return {'reason': 'no audible library sound of this kind', 'identity': identity}
    similarities = np.asarray(library_embeddings)[eligible] @ np.asarray(embedding)
    position = int(np.argmax(similarities))
    index = eligible[position]
    return {'reason': None, 'identity': identity, 'index': index, 'sfx': f'sfx:{items[index]["id"]}',
            'cosine': round(float(similarities[position]), 4), 'audibility': measurements[index]}


PICTURE_KINDS = {'white flash': ('camera shutter',), 'freeze': ('camera shutter', 'record scratch'),
                 'negative flash': ('camera shutter',), 'camera visible': ('camera shutter',),
                 'alarm clock visible': ('alarm clock',), 'mouse click visible': ('click',),
                 'rewind': ('record scratch',), 'letter typing': ('typewriter',)}


def picture_kinds(cues):
    return set().union(*(set(PICTURE_KINDS.get(cue, ())) for cue in cues)) if cues else set()


def robust_query(windows, sample_rate):
    from scipy.signal import correlate, correlation_lags
    audio = np.asarray(windows, dtype=np.float64)
    if audio.ndim != 2 or len(audio) < 3 or audio.shape[1] < sample_rate // 4:
        raise ValueError('A repeated query needs at least three equal-length audio windows')
    if not np.isfinite(audio).all():
        raise ValueError('Invalid repeated audio')
    scales = np.sqrt(np.mean(audio ** 2, axis=1))
    if np.any(scales < 1e-8):
        raise ValueError('Silent repeat')
    normal = audio / scales[:, None]
    seed = int(np.argmin(np.abs(scales - np.median(scales))))
    bound = round(sample_rate * .06)
    aligned, shifts, agreement = [], [], []
    for window in normal:
        correlations = correlate(normal[seed], window, mode='full', method='fft')
        lags = correlation_lags(audio.shape[1], audio.shape[1])
        allowed = np.flatnonzero(np.abs(lags) <= bound)
        best = allowed[int(np.argmax(correlations[allowed]))]
        shift = int(lags[best])
        padded = np.pad(window, (bound, bound))
        aligned.append(padded[bound - shift:bound - shift + audio.shape[1]])
        shifts.append(shift / sample_rate)
        agreement.append(float(correlations[best] / audio.shape[1]))
    combined = np.median(np.stack(aligned), axis=0)
    combined *= np.median(scales)
    return combined.astype(np.float32), {'occurrences': len(audio), 'alignment_s': shifts,
        'correlation': [round(value, 4) for value in agreement], 'query_only': True}


def name_layers(views, text_prototypes, panns, picture_cues=()):
    views = np.asarray(views)
    probabilities = np.asarray(panns)
    if views.shape[0] != len(SLICES) or probabilities.shape != (527,):
        raise ValueError('Sound names need four audio views and 527 AudioSet scores')
    evidence = [identify(view, text_prototypes) for view in views]
    supported = picture_kinds(picture_cues)
    if supported:
        for index, view in enumerate(views):
            scores = np.asarray(text_prototypes) @ view
            plausible = [(float(scores[position]), kind) for position, kind in enumerate(KINDS)
                         if kind in supported and scores[position] >= POLICY['min_cosine']
                         and scores.max() - scores[position] <= POLICY['min_margin']]
            if plausible:
                score, kind = max(plausible)
                evidence[index] = {'kind': kind, 'cosine': round(score, 4), 'margin': 0,
                                   'reason': None, 'picture_cues': list(picture_cues)}
    layers, rejected = [], []
    for kind in dict.fromkeys(row['kind'] for row in evidence):
        usable = [index for index, row in enumerate(evidence) if row['kind'] == kind and row['reason'] is None]
        if not usable:
            rejected.append({'kind': kind, 'reason': next(row['reason'] for row in evidence if row['kind'] == kind)})
            continue
        score = max((float(probabilities[index]) for index in PANN_CLASSES.get(kind, ())), default=0)
        visual_agreement = any(evidence[index].get('picture_cues') for index in usable)
        if score < POLICY['panns_min'] and not visual_agreement:
            rejected.append({'kind': kind, 'reason': 'name not corroborated by AudioSet', 'panns': round(score, 4)})
            continue
        relative = min(SLICES[index][0] for index in usable)
        if relative > 0:
            rejected.append({'kind': kind, 'reason': 'layer onset not measured'})
            continue
        best = max(usable, key=lambda index: evidence[index]['margin'])
        layers.append({'identity': evidence[best], 'embedding': views[best], 'panns': round(score, 4),
                       'relative_s': relative})
    return layers, {'views': evidence, 'rejected': rejected}


def named_devices(finds, views, panns, text_prototypes, items, library_embeddings, measurements,
                  cluster, min_finds=3, picture_cues=None):
    candidates, omitted = [], []
    for index, find in enumerate(finds):
        layers, evidence = name_layers(views[index], text_prototypes, panns[index],
                                      (picture_cues or {}).get(index, ()))
        omitted.append({'find': index, **evidence})
        for layer in layers:
            offset = find.get('offset_ms')
            offset = None if offset is None else offset + round(layer['relative_s'] * 1000)
            if find.get('land') in (None, 'nothing') or offset is None or abs(offset) > POLICY['max_offset_ms']:
                evidence['rejected'].append({'kind': layer['identity']['kind'], 'reason': 'no target within 0.125 s'})
                continue
            candidates.append({**layer, 'find': index, 'land': find['land'], 'offset_ms': offset})
    devices = []
    keys = sorted({(row['land'], row['identity']['kind']) for row in candidates})
    for land, kind in keys:
        selected = [row for row in candidates if (row['land'], row['identity']['kind']) == (land, kind)]
        embeddings = np.stack([row['embedding'] for row in selected])
        for members in cluster([land] * len(selected), embeddings):
            group = [selected[index] for index in members]
            unique = sorted({row['find'] for row in group})
            moments = {round(float(finds[index]['t']), 4) for index in unique}
            if len(moments) < min_finds:
                omitted.append({'kind': kind, 'members': unique, 'reason': 'not enough named repetitions'})
                continue
            centre = embeddings[members].mean(axis=0)
            centre /= max(float(np.linalg.norm(centre)), 1e-9)
            choice = choose(centre, group[0]['identity'], items, library_embeddings, measurements)
            if choice['reason']:
                omitted.append({'kind': kind, 'members': unique, 'reason': choice['reason']})
                continue
            devices.append({'land': land, 'n': len(moments), 'members': unique, 'kind': kind,
                            'offset_ms': int(np.median([row['offset_ms'] for row in group])),
                            'at_s': [float(finds[row['find']]['t']) + row['relative_s'] for row in group],
                            'sfx': choice['sfx'], 'sfx_sim': choice['cosine'], 'centre': centre,
                            'alike': round(float((embeddings[members] @ embeddings[members].T).min()), 4),
                            'audibility': choice['audibility'], 'name_evidence': [row['identity'] for row in group]})
    for device in devices:
        device['layers'] = [{'kind': other['kind'], 'sfx': other['sfx'], 'offset_ms': other['offset_ms']}
                            for other in devices if other['land'] == device['land']
                            and set(other['members']) & set(device['members'])]
    return devices, omitted


def judge(expected_kinds, picks, measurements, offset_error_ms=None):
    if any(not measurement.get('ok') for measurement in measurements):
        return 'inaudible'
    actual = set().union(*(library_kinds(item) for item in picks)) if picks else set()
    expected = set(expected_kinds)
    if not expected:
        return 'unjudged'
    if not expected <= actual:
        return 'missing layer' if expected & actual else 'wrong sound'
    if actual - expected:
        return 'extra kind'
    if offset_error_ms is not None and abs(offset_error_ms) > POLICY['max_offset_ms']:
        return 'wrong moment'
    return 'same kind'
