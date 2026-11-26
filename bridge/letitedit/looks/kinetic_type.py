"""Measured, face-safe layout for timed phrases; no transcript or emphasis guessing."""
from __future__ import annotations

import math

import letitedit.catalogs.fonts as fonts

BLEND_MODES = ('normal', 'difference', 'exclusion', 'multiply', 'screen', 'overlay', 'darken',
               'add', 'saturate', 'colordodge', 'colorburn', 'hardlight', 'softlight',
               'hslhue', 'hslsaturatation', 'hslcolor', 'hslluminocity')


def glyph_blend(params):
    mode = params.get('blend', 'normal')
    if params.get('readability') not in (None, 'solid', 'edge', 'edge-layer'):
        raise ValueError('caption readability must be edge, edge-layer, solid or omitted')
    if params.get('readability') in ('solid', 'edge-layer') and mode != 'normal':
        raise ValueError('solid readability aid and edge-layer need normal blend')
    if mode not in BLEND_MODES:
        raise ValueError('caption blend must be one of: ' + ', '.join(BLEND_MODES))
    if mode == 'normal':
        return []
    settings = [params]
    roles = params.get('roles') or {}
    if isinstance(roles, dict):
        settings.extend(value for value in roles.values() if isinstance(value, dict))
    settings.extend(word for word in params.get('words') or [] if isinstance(word, dict))
    for phrase in params.get('phrases') or []:
        if isinstance(phrase, dict):
            settings.extend(word for word in phrase.get('words') or [] if isinstance(word, dict))
    if any(value.get('box') or value.get('shadow') not in (None, False, 'none') or value.get('style') == 'highlight'
           for value in settings):
        raise ValueError('caption blend colours letters only: no box, highlight box or shadow')
    return [{'filter': 'cairoblend_mode', 'params': {'mode': mode}}]


def protected_regions(params):
    regions = params.get('protected') or []
    if not isinstance(regions, list) or any(not isinstance(region, dict) for region in regions):
        raise ValueError('caption protected needs a list of regions')
    for region in regions:
        box = region.get('box', [])
        if not isinstance(box, list) or len(box) != 4 or any(not 0 <= finite(edge, 'protected box') <= 1 for edge in box) or not (box[0] < box[2] and box[1] < box[3]):
            raise ValueError('caption protected box needs ordered frame fractions')
        if finite(region.get('end', 1e10), 'protected end') <= finite(region.get('start', -1e10), 'protected start'):
            raise ValueError('caption protected span must be positive')
    return regions


def finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'kinetic_type {name} must be finite')
    return value


def envelope(word, width, height):
    size = word['size']
    advance = 0
    overhang = 0
    for run in word.get('runs') or [{'text': word['text']}]:
        font = run.get('font') or word['font']
        face = fonts.pil_font(font['family'], max(1, round(size * height)), font.get('weight', 400))
        advance += face.getlength(run['text']) + len(run['text']) * word.get('spacing', 0) * size * height
        if word.get('reveal') == 'letters':
            advance += max(0, sum(face.getlength(character) for character in run['text']) - face.getlength(run['text']))
        glyph_box = face.getbbox(run['text'])
        overhang = max(overhang, abs(min(0, glyph_box[0])), max(0, glyph_box[2] - face.getlength(run['text'])))
    if advance <= 0:
        raise ValueError('kinetic_type spacing produces a nonpositive word width')
    peak = max(1, word.get('from_scale', 1))
    if word.get('ease') == 'backOut':
        peak += abs(1 - word.get('from_scale', 1)) * 0.101
    half_width = (advance / 2 + overhang + 4) * peak / width + word.get('outline', 0) * height / width
    half_height = (size * word.get('line_height', 1.1) / 2 + 4 / height) * peak + word.get('outline', 0)
    travel_x, travel_y = abs(word.get('from_x', 0)) * 1.11, abs(word.get('from_y', 0)) * 1.11
    if word.get('readability') in ('solid', 'edge', 'edge-layer'):
        half_width += .003 * height / width
        half_height += .003
    return [word['x'] - half_width - travel_x, word['y'] - half_height - travel_y,
            word['x'] + half_width + travel_x, word['y'] + half_height + travel_y]


def overlaps(first, second):
    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def compile_phrases(params):
    layout = params.get('layout') or {}
    if not isinstance(layout, dict) or not isinstance(params.get('phrases'), list):
        raise ValueError('kinetic_type needs a layout object and phrases list')
    canvas = layout.get('canvas', [1080, 1920])
    if not isinstance(canvas, list) or len(canvas) != 2 or any(finite(edge, 'canvas') <= 0 for edge in canvas):
        raise ValueError('kinetic_type layout.canvas needs two positive dimensions')
    width, height = canvas
    safe = layout.get('safe', [0.06, 0.08, 0.88, 0.84])
    if not isinstance(safe, list) or len(safe) != 4 or any(not 0 <= finite(edge, 'safe') <= 1 for edge in safe) or not (safe[0] < safe[2] and safe[1] < safe[3]):
        raise ValueError('kinetic_type safe needs ordered frame fractions')
    candidates = layout.get('centres', [0.5, 0.64, 0.74, 0.81])
    if not isinstance(candidates, list) or not candidates or any(not 0 <= finite(value, 'centres') <= 1 for value in candidates):
        raise ValueError('kinetic_type centres needs frame fractions')
    protected = params.get('protected') or []
    if not isinstance(protected, list) or any(not isinstance(region, dict) for region in protected):
        raise ValueError('kinetic_type protected needs a list of regions')
    for region in protected:
        box = region.get('box', [])
        if not isinstance(box, list) or len(box) != 4 or any(not 0 <= finite(edge, 'protected box') <= 1 for edge in box) or not (box[0] < box[2] and box[1] < box[3]):
            raise ValueError('kinetic_type protected box needs ordered frame fractions')
        if finite(region.get('end', 1e10), 'protected end') <= finite(region.get('start', -1e10), 'protected start'):
            raise ValueError('kinetic_type protected span must be positive')
    output = []
    for phrase in params['phrases']:
        if not isinstance(phrase, dict):
            raise ValueError('kinetic_type phrase must be an object')
        words = phrase.get('words') or []
        if not isinstance(words, list) or not words or any(not isinstance(word, dict) for word in words):
            raise ValueError('kinetic_type phrase needs timed words')
        end = finite(phrase.get('end', max(word['end'] for word in words)), 'phrase end')
        rows = {}
        for word in words:
            settings = dict(x=0.5, y=0.5, size=0.04, spacing=0, line_height=1.1,
                            font=params['font'], align='center')
            settings.update((params.get('roles') or {}).get(word.get('role'), {}))
            settings.update(word)
            settings['readability'] = params.get('readability')
            if settings.get('align') != 'center' or settings.get('shadow', 'none') != 'none':
                raise ValueError('kinetic_type automatic layout needs centre alignment and no shadow')
            if type(settings.get('line', 0)) is not int or settings.get('line', 0) < 0:
                raise ValueError('kinetic_type line must be a nonnegative integer')
            if end <= finite(settings['start'], 'word start'):
                raise ValueError('kinetic_type phrase end must follow every onset')
            settings['end'] = end
            if finite(settings['size'], 'size') <= 0:
                raise ValueError('kinetic_type size must be positive')
            rows.setdefault(settings.get('line', 0), []).append(settings)
        line_data = []
        gap = finite(layout.get('gap', 0.008), 'gap')
        row_gap = finite(layout.get('row_gap', 0.012), 'row_gap')
        if gap < 0 or row_gap < 0:
            raise ValueError('kinetic_type layout gaps must be nonnegative')
        for _, row in sorted(rows.items()):
            boxes = [envelope(word, width, height) for word in row]
            widths = [box[2] - box[0] for box in boxes]
            line_data.append((row, widths, max(box[3] - box[1] for box in boxes)))
        if any(sum(widths) + gap * (len(widths) - 1) > safe[2] - safe[0] for _, widths, _ in line_data):
            raise ValueError('kinetic_type phrase is too wide: use explicit lines, shorter groups or a cutaway; no silent shrinking')
        total_height = sum(line[2] for line in line_data) + row_gap * (len(line_data) - 1)
        start = min(word['start'] for word in words)
        obstacles = [region['box'] for region in protected if region.get('start', -1e10) < end and region.get('end', 1e10) > start]
        placed = None
        for centre in candidates:
            top = centre - total_height / 2
            proposal = []
            for row, widths, line_height in line_data:
                left = (safe[0] + safe[2] - sum(widths) - gap * (len(widths) - 1)) / 2
                for word, word_width in zip(row, widths):
                    current = dict(word, x=left + word_width / 2, y=top + line_height / 2)
                    current['layout_bounds'] = envelope(current, width, height)
                    proposal.append(current)
                    left += word_width + gap
                top += line_height + row_gap
            if all(safe[0] <= word['layout_bounds'][0] and word['layout_bounds'][2] <= safe[2]
                   and safe[1] <= word['layout_bounds'][1] and word['layout_bounds'][3] <= safe[3]
                   and not any(overlaps(word['layout_bounds'], box) for box in obstacles) for word in proposal):
                placed = proposal
                break
        if placed is None:
            raise ValueError('kinetic_type no face-safe layout: move emphasis to a cutaway or revise the phrase; no face overlap fallback')
        output.extend(placed)
    return output
