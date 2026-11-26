"""Save a Custom mix as a private personal Look in the shared revision store."""
import json
import hashlib
from pathlib import Path
import sys

import letitedit.looks.look_library as look_library

FIELDS = {
    'transitions': ('Transitions', 'transition'),
    'punch_ins': ('Punch-ins and zooms', 'zoom_punch'),
    'emoji': ('Emoji and stickers', 'popup'),
    'captions': ('Captions', None),
    'three_d': ('3D effects', 'effect'),
    'motion': ('Motion graphics', 'motion'),
    'overlays': ('Overlays', 'graphic'),
    'cutting': ('Cutting speed', None),
    'pauses': ('Natural pauses ↔ Jump cuts', None),
    'dialogue': ('Dialogue kept', None),
    'music': ('Music', None),
    'sound': ('Sound effects', 'sfx'),
    'broll': ('B-roll', 'broll'),
    'courage': ('Courage', None),
}
LEVELS = ('None', 'Low', 'Medium', 'High', 'XHigh', 'Very high', 'Max')
DISPLAY_LEVELS = {
    'courage': ('None', 'Curious', 'Bold', 'Daring', 'Wild', 'Unhinged', 'Max'),
    'cutting': ('Snail', 'Turtle', 'Walking', 'Running', 'Driving', 'Rocket', 'Frantic'),
    'pauses': ('Natural', 'Roomy', 'Relaxed', 'Balanced', 'Tight', 'Jump cuts', 'Max jumps'),
    'emoji': ('None', 'A sprinkle', 'Some', 'Lots', 'Everywhere', 'Mind blown', 'Max'),
    'punch_ins': ('None', 'A nudge', 'Some', 'Often', 'Lots', 'Punchy', 'Max'),
    'dialogue': ('Best lines', 'Highlights', 'Selective', 'Balanced', 'Talk-led', 'Almost all', 'Every word'),
}
TWO_SIDED = {'cutting', 'pauses', 'dialogue'}


def write_custom(spec):
    values = {key: max(0, min(6, int(value))) for key, value in spec['sliders'].items()
              if key in FIELDS and int(value) >= 0}
    if not values:
        raise ValueError('Choose at least one Custom slider; an untouched Custom Look is Let the AI decide.')
    name = spec['name']
    title = 'Custom mix' if name.startswith('custom-') else name
    kind = spec.get('kind', 'both')
    if kind not in ('short', 'long', 'both'):
        kind = 'both'
    def level(key):
        return DISPLAY_LEVELS[key][values[key]] if key in TWO_SIDED else LEVELS[values[key]]
    lines = [f'# {title}',
             'Only the settings below were chosen. For every other setting, let the AI decide.',
             'Amounts are ceilings, not quotas. None is a ceiling of zero: do not add that element. Match choices to the story and protect clarity.']
    if 'courage' in values:
        lines += ['Courage controls how adventurous the choices can be. At None, stay familiar and restrained; at Max,',
                  'try bold, surprising arrangements, timings and combinations when they help the story. Review the result.',
                  f'Courage: {level("courage")} ({DISPLAY_LEVELS["courage"][values["courage"]]}).']
    lines += [f'{label}: {level(key)} ({DISPLAY_LEVELS[key][values[key]]}).'
              if key in DISPLAY_LEVELS and key not in TWO_SIDED else f'{label}: {level(key)}.'
              for key, (label, _) in FIELDS.items() if key != 'courage' and key in values]
    if any(value == 0 for key, value in values.items() if key not in TWO_SIDED):
        lines.append('None means do not add that element. It is a ceiling of zero, never a target or a suggestion.')
    if 'dialogue' in values:
        lines.append('Dialogue kept means how much useful talking remains; low favors visuals and high preserves more speech.')
    if 'cutting' in values:
        lines.append('Cutting speed runs from calm and spacious to frantic.')
    if 'pauses' in values:
        lines.append('Natural pauses ↔ Jump cuts controls how talk is tightened. Natural keeps meaningful breaths; Jump cuts removes drag while protecting complete words and thoughts.')
    if 'music' in values or 'sound' in values:
        lines.append('Music and sound effects should support speech.')
    if 'overlays' in values:
        lines.append('Place overlays clear of faces, captions and covered phone areas.')
    effects = {}
    for key, (label, effect_kind) in FIELDS.items():
        if key not in values or effect_kind not in ('transition', 'zoom_punch', 'popup', 'broll') or values[key] == 0:
            continue
        count = [0, 1, 2, 3, 5, 7, 9][values[key]]
        effects[key] = {'kind': effect_kind, 'about': f'{label}: {level(key)}',
                        'rules': {'triggers': ['emphasis', 'reveal', 'topic_change'],
                                  'density': {'per_10s': count, 'min_gap_s': max(0.35, 8 / count)},
                                  'when': f'Use {label.lower()} only where it clarifies or heightens the moment.'}}
    # Only chosen preferences go into v3 fields; omitted choices stay with the AI.
    densities = {key: [0, 1, 2, 3, 5, 7, 9][values[key]] for key in
                 ('transitions', 'punch_ins', 'emoji', 'three_d', 'motion', 'overlays', 'sound', 'broll') if key in values}
    rules = {key: (f'{label}: None. Do not add this element.' if values[key] == 0 and key not in TWO_SIDED
                   else f'{label}: {level(key)}. Use only when it helps the story, kept off faces and key words where it can.')
             for key, (label, _) in FIELDS.items() if key in values}
    data = {'name': name, 'label': 'Custom', 'summary': 'Your own mix of pace, words, music and effects',
            'kind': kind, 'tags': ['custom', 'new video'], 'description': 'Custom New video settings',
            'recipe': 'recipe.md', 'custom': {'sliders': values, 'levels': {key: level(key) for key in values},
                                             'display_levels': {key: DISPLAY_LEVELS.get(key, LEVELS)[values[key]] for key in values},
                                             'density_per_10s': densities, 'rules': rules},
            'effects': effects}
    if 'cutting' in values:
        data['editing'] = {'pace': ['calm', 'calm', 'medium', 'fast', 'fast', 'frantic', 'frantic'][values['cutting']]}
    if 'pauses' in values:
        editing = data.setdefault('editing', {})
        editing['pause_style'] = DISPLAY_LEVELS['pauses'][values['pauses']]
        if values['pauses'] > 0:
            editing['max_pause'] = [None, 1.5, 1.1, .75, .5, .3, .15][values['pauses']]
    if 'punch_ins' in values:
        data['shots'] = {'punch_ins': level('punch_ins').lower()}
    if 'broll' in values:
        data['broll'] = {'amount': level('broll').lower()}
    if 'captions' in values:
        data['captions'] = {'enabled': values['captions'] > 0}
    if 'music' in values:
        data['music'] = {'notes': f'Music level: {level("music")}; respect the spoken voice.'}
    if spec.get('keep_as_my_style'):
        return look_library.create(title, data, '\n'.join(lines) + '\n', kind=kind)
    data.pop('name', None)
    identity = 'mine-custom-' + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]
    directory = look_library.learned_looks.root().parent / 'Custom Looks'
    pointer = directory / identity / 'look.json'
    if pointer.is_file():
        saved = json.loads(pointer.read_text(encoding='utf-8-sig'))
        version = pointer.parent / 'revisions' / saved['revision']
        return {**saved, 'settings': str(version / 'settings.json'), 'recipe': str(version / 'recipe.md')}
    return look_library.create('Custom mix', data, '\n'.join(lines) + '\n', kind=kind,
                               personal_root=directory, identity=identity)


if __name__ == '__main__':
    try:
        with open(sys.argv[1], encoding='utf-8-sig') as stream:
            result = write_custom(json.load(stream))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)
