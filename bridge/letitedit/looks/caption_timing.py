"""Keep timed caption words on edited speech without changing their layout or grouping."""
from __future__ import annotations

import math


def follow_words(before, after):
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import _letters, timeline_words

    old = {item.get('id'): item for track in before['tracks'] for item in track['items'] if item.get('id')}
    speech_changed = [[item for item in track['items'] if item.get('clip')]
                      for track in before['tracks'] if track.get('kind', 'video') == 'video'] != [
                          [item for item in track['items'] if item.get('clip')]
                          for track in after['tracks'] if track.get('kind', 'video') == 'video']
    changed = speech_changed or any(item.get('motion', {}).get('block') == 'kinetic_type'
                                    and old.get(item.get('id')) != item
                                    for track in after['tracks'] for item in track['items'])
    if not changed:
        return []
    captions = []
    for track in after['tracks']:
        for item, start, end in layout(track, float(after['profile']['fps'])):
            motion = item.get('motion') or {}
            if motion.get('block') != 'kinetic_type':
                continue
            params = motion.get('params') or {}
            rows = ([word for phrase in params['phrases'] for word in phrase['words']]
                    if params.get('phrases') else params.get('words') or [])
            shift = es.to_seconds(item.get('skip', 0)) + float(params.get('offset') or 0)
            captions.append((rows, start, end, shift, params))
    if not captions:
        return []
    heard = timeline_words(after, cached_only=True)
    if not heard:
        return ['Word-pop timing unverified: no cached timeline words']
    fps = float(after['profile']['fps'])
    notes = []
    for rows, start, end, shift, params in captions:
        cursor = 0
        for word in rows:
            tokens = [_letters(token) for token in str(word.get('text', '')).split()]
            onset = start + float(word['start']) - shift
            candidates = [index for index in range(cursor, len(heard) - len(tokens) + 1)
                          if abs(heard[index]['t0'] - onset) <= 2 and
                          [_letters(row['w']) for row in heard[index:index + len(tokens)]] == tokens]
            if not tokens or not candidates:
                notes.append(f'Word-pop timing unverified: "{word.get("text", "")}" has no nearby spoken match')
                continue
            index = min(candidates, key=lambda candidate: abs(heard[candidate]['t0'] - onset))
            target = math.ceil((heard[index]['t0'] - start) * fps - 1e-7) / fps + shift
            hold = float(word['end']) - float(word['start'])
            if target < shift or target - shift >= end - start:
                notes.append(f'Word-pop timing unverified: "{word["text"]}" lies outside its caption clip')
                continue
            settings = {**(params.get('roles') or {}).get(word.get('role'), {}), **word}
            if (settings.get('fade_in', True) or settings.get('reveal') == 'wipe') and float(settings.get('entry', .15)) > 0:
                target -= 1 / fps
            # from the rounded start, rounded: a word already on its speech keeps exactly its times, so an edit
            # elsewhere doesn't change the caption's recipe (which would make its clip again and redraw every frame)
            arrive = round(target, 9)
            word['start'] = arrive
            word['end'] = round(max(float(word['end']), arrive + hold), 9)
            for run in word.get('runs') or []:
                run['start'] = round(float(run.get('start', onset - start + shift)) + arrive - (onset - start + shift), 9)
            notes.append(f'Word-pop "{word["text"]}" on its timeline word ({heard[index]["t0"]:.3f} s)')
            cursor = index + len(tokens)
    return notes
