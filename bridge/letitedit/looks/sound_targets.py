"""Picture-bound effect sounds and caption clocks used by the export renderers."""
from __future__ import annotations

import math

PROPERTY = 'letitedit_ai:sound_target'
LIMIT_S = 0.125


def caption_events(script):
    from letitedit.timeline.edit_sync import layout
    import letitedit.timeline.edit_script as es

    fps = float((script.get('profile') or {}).get('fps') or 30)
    events = []
    for track in script['tracks']:
        if track.get('kind', 'video') != 'video' or track.get('hide') in ('video', 'both'):
            continue
        for item, start, end in layout(track, fps):
            motion, graphic = item.get('motion') or {}, item.get('graphic') or {}
            params = motion.get('params') or graphic.get('params') or {}
            if params.get('readability') == 'edge-layer':
                continue
            block = motion.get('block') or graphic.get('template')
            rows = []
            shift = es.to_seconds(item.get('skip', 0))
            if motion:
                shift += float(params.get('offset') or 0)
            if block == 'kinetic_type':
                rows = list(params.get('words') or [])
                if params.get('phrases'):
                    rows = [word for phrase in params['phrases'] for word in phrase.get('words', [])]
            elif graphic.get('template') == 'word_captions':
                grouped = params.get('style', 'pop') not in ('pop', 'typewriter')
                rows = [{'text': word[0], 'start': 0 if grouped else word[1], 'end': word[2]}
                        for word in params.get('words', []) if isinstance(word, (list, tuple)) and len(word) >= 3]
            elif motion.get('block') == 'word_captions':
                rows = _motion_caption_rows(params)
            elif (item.get('text') or item.get('caption')) and any(
                    name in track.get('name', '').lower() for name in ('caption', 'subtitle')):
                text = item.get('text') or item.get('caption')
                rows = [{'text': text.get('text', '') if isinstance(text, dict) else str(text), 'start': 0}]
            for index, word in enumerate(rows):
                if not isinstance(word, dict):
                    continue
                onset = float(word.get('start', word.get('s', 0))) - shift
                finish = float(word.get('end', word.get('e', end - start + shift))) - shift
                if finish <= 0 or onset >= end - start:
                    continue
                settings = {**(params.get('roles') or {}).get(word.get('role'), {}), **word}
                if params.get('readability') in ('edge', 'solid'):
                    settings.update(fade_in=False, reveal='none')
                if block == 'kinetic_type' and settings.get('reveal') == 'runs' and settings.get('runs'):
                    onset = max(onset, min(float(run.get('start', word['start'])) - shift
                                           for run in settings['runs']))
                entry = float(settings.get('entry', .15))
                strict = block == 'kinetic_type' and settings.get('fade_in', True) and entry > 0
                strict = strict or (block == 'kinetic_type' and settings.get('reveal') == 'wipe' and entry > 0)
                frame = math.floor(onset * fps + 1e-7) + 1 if strict else math.ceil(onset * fps - 1e-7)
                at = start + max(0, frame) / fps
                if at >= end or at >= start + finish:
                    continue
                text = str(word.get('text', word.get('w', '')))
                events.append({'kind': 'caption_word', 'id': item.get('id'), 'word': text, 'index': index,
                               't': round(at, 6), 'what': f'caption "{text}"', 'track': track['name']})
    return sorted(events, key=lambda event: event['t'])


def _motion_caption_rows(params):
    words = params.get('words') or []
    if not words:
        pace, offset = float(params.get('pace', .32)), float(params.get('offset') or 0)
        words = [{'text': word, 'start': offset + .1 + index * pace, 'end': offset + .1 + (index + 1) * pace}
                 for index, word in enumerate(str(params.get('text') or '').split())]
    groups, group, chars, previous = [], [], 0, None
    for word in words:
        text = str(word.get('text', word.get('word', word.get('w', '')))).strip()
        if not text:
            continue
        onset = float(word.get('start', word.get('s', 0)))
        finish = float(word.get('end', word.get('e', onset)))
        if group and (len(group) >= int(params.get('max_words', 4))
                      or chars + len(text) > int(params.get('max_chars', 22)) or onset - previous > .6):
            groups.append(group)
            group, chars = [], 0
        group.append({'text': text, 'start': onset, 'end': finish})
        chars += len(text) + 1
        previous = finish
        if text.endswith(('.', '!', '?')):
            groups.append(group)
            group, chars = [], 0
    if group:
        groups.append(group)
    rows = []
    for index, group in enumerate(groups):
        until = group[-1]['end'] + .8
        if index + 1 < len(groups):
            until = min(until, groups[index + 1][0]['start'])
        rows.extend({'text': word['text'], 'start': group[0]['start'] - .04, 'end': until} for word in group)
    return rows


def target_for(event):
    return {key: event[key] for key in ('id', 'word', 'index') if event.get(key) is not None} | {
        'kind': event['kind'], 'at': event['t']}


def follow_captions(before, after):
    import difflib
    from letitedit.timeline.edit_sync import item_len, layout
    from letitedit.timeline.timeline_speech import _letters

    fps = float(after['profile']['fps'])
    old_events, new_events = caption_events(before), caption_events(after)
    mapping = {}
    old_ids = {event['id'] for event in old_events}
    new_ids = {event['id'] for event in new_events}
    for track in {event['track'] for event in old_events}:
        pairs = [([event for event in old_events if event['id'] == caption_id],
                  [event for event in new_events if event['id'] == caption_id])
                 for caption_id in old_ids & new_ids
                 if any(event['id'] == caption_id and event['track'] == track for event in old_events)]
        for old, new in pairs + [(None, None)]:
            if old is None:
                used = {(event['id'], event['index']) for event in mapping.values()}
                old = [event for event in old_events if event['track'] == track
                       and (event['id'], event['index']) not in mapping]
                new = [event for event in new_events if event['track'] == track
                       and (event['id'], event['index']) not in used]
            matcher = difflib.SequenceMatcher(None, [_letters(event['word']) for event in old],
                                            [_letters(event['word']) for event in new], autojunk=False)
            for block in matcher.get_matching_blocks():
                for offset in range(block.size):
                    event = old[block.a + offset]
                    mapping[(event['id'], event['index'])] = new[block.b + offset]
    previous = {item.get('id'): (item, start) for track in before['tracks']
                for item, start, end in layout(track, fps) if item.get('id')}
    notes = []
    for track in after['tracks']:
        placed, moved = [], False
        for item, start, end in layout(track, fps):
            record = item.get('sound_target') or {}
            old_item, old_start = previous.get(item.get('id'), ({}, start))
            old_record = old_item.get('sound_target') or {}
            if old_record.get('kind') == 'caption_word' and record.get('kind') != 'caption_word':
                raise ValueError(f'{item.get("id")}: caption_word anchor cannot be rewritten as a fixed story time')
            if old_record.get('kind') == 'caption_word':
                old_event = resolve(old_record, old_events, fps)
                new_event = mapping.get((old_event['id'], old_event['index'])) if old_event else None
                if new_event is None:
                    notes.append(f'{item.get("id")}: caption_word target missing; anchored sound needs a caption')
                else:
                    item['sound_target'] = target_for(new_event)
                    if new_event['t'] != old_event['t'] or old_start != start:
                        start = round((old_start + new_event['t'] - old_event['t']) * fps) / fps
                        item['at'], item['pin'], moved = max(0, start), True, True
            if 'gap' not in item:
                placed.append((item, start))
        if moved:
            rebuilt, position = [], 0.0
            for item, start in sorted(placed, key=lambda row: row[1]):
                if start > position + 1e-6:
                    rebuilt.append({'gap': round(start - position, 6)})
                rebuilt.append(item)
                position = max(position, start) + item_len(item, fps)
            track['items'] = rebuilt
    return notes


def effect_events(script):
    from letitedit.timeline.edit_sync import layout

    fps = float((script.get('profile') or {}).get('fps') or 30)
    clips = {item.get('id'): (item, start, end) for track in script['tracks']
             if track.get('kind', 'video') == 'video' and track.get('hide') not in ('video', 'both')
             for item, start, end in layout(track, fps)}
    events = []
    for track in script['tracks']:
        for item in track['items']:
            record = item.get('sound_target') or {}
            if record.get('kind') != 'effect' or record.get('id') not in clips:
                continue
            clip, start, end = clips[record['id']]
            keys = record.get('effect_keys')
            if keys and not any(isinstance(effect, dict) and set(keys).issubset(effect)
                                for effect in clip.get('effects', [])):
                continue
            at = start + float(record.get('offset', 0))
            if start <= at < end:
                events.append({**record, 't': at, 'what': f'{record.get("word", "effect")} on {record["id"]}'})
    return events


def resolve(record, events, fps):
    if record.get('kind') == 'story':
        return {'t': float(record['at']), 'what': str(record.get('word') or 'story moment')}
    candidates = [event for event in events if event['kind'] == record.get('kind')]
    if record.get('id'):
        candidates = [event for event in candidates if event.get('id') == record['id']]
    if record.get('index') is not None:
        candidates = [event for event in candidates if event.get('index') == record['index']]
    if record.get('word'):
        candidates = [event for event in candidates if event.get('word') == record['word']]
    if record.get('offset') is not None:
        candidates = [event for event in candidates if event.get('offset') == record['offset']]
    if record.get('id'):
        return min(candidates, key=lambda event: abs(event['t'] - record['at']), default=None)
    return min((event for event in candidates if abs(event['t'] - record['at']) <= 1 / fps + 1e-6),
               key=lambda event: abs(event['t'] - record['at']), default=None)


def measure(event, events, fps):
    import letitedit.catalogs.assets as assets
    import letitedit.timeline.edit_script as es

    item = event['sound']
    record = item.get('sound_target')
    if record and record.get('kind') == 'caption_word' and resolve(record, events, fps) is None:
        return {'status': 'no_target', 'target': record, 'reason': 'recorded caption_word target is missing'}
    try:
        facts = assets.measure_sound(item['clip'])
        source_peak = facts['peak_s']
    except Exception as error:
        return {'status': 'unmeasured', 'reason': str(error), 'target': record}
    speed = float(item.get('speed', 1))
    source_in = round(es.to_seconds(item.get('in') or 0) * fps / speed) / fps
    peak = event['t'] + source_peak / speed - source_in
    if not event['t'] <= peak < event['end']:
        return {'status': 'unmeasured', 'reason': 'the source peak is outside the audible trim', 'target': record}
    pictures = [candidate for candidate in events if candidate['kind'] in ('cut', 'in', 'out', 'caption_word', 'effect')]
    if record:
        target = resolve(record, pictures, fps)
        method = 'recorded'
    else:
        own = str(event.get('id') or '').removesuffix('-sfx')
        target = next((candidate for candidate in pictures if candidate.get('id') == own
                       and candidate['kind'] == 'in'), None)
        target = target or min((candidate for candidate in pictures if candidate['kind'] != 'effect'
                               and abs(candidate['t'] - peak) <= .5),
                               key=lambda candidate: abs(candidate['t'] - peak), default=None)
        method = 'legacy nearest event'
    if target is None:
        return {'status': 'no_target', 'peak_at': round(peak, 6), 'target': record,
                'reason': 'recorded target is missing' if record else 'no picture or caption event within 0.5 s'}
    offset = peak - target['t']
    return {'status': 'pass' if abs(offset) <= LIMIT_S + 1e-6 else 'off_target', 'moment': 'peak',
            'peak_at': round(peak, 6), 'picture': target['what'], 'picture_at': target['t'],
            'off_s': round(offset, 6), 'target': record or target_for(target), 'match': method}


def receipts(script, records):
    from letitedit.review import dense

    events, _ = dense.events(script)
    fps = float((script.get('profile') or {}).get('fps') or 30)
    sounds = {event['id']: event for event in events if event['kind'] == 'sound'}
    lines = []
    for record in records:
        sound_id = record.get('sfx_id')
        if not sound_id:
            continue
        result = measure(sounds[sound_id], events, fps) if sound_id in sounds else {
            'status': 'unmeasured', 'reason': 'sound is not audible on the timeline'}
        record['sound_sync'] = result
        if 'off_s' in result:
            lines.append(f'{sound_id}: peak {result["off_s"] * 1000:+.0f} ms from '
                         f'{result["picture"]} at {result["picture_at"]:.3f}s ({result["status"]})')
        else:
            lines.append(f'{sound_id}: {result["status"]}: {result["reason"]}; what is the sound for?')
    return '; '.join(lines)
