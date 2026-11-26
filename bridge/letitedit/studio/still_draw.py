"""Deterministic still geometry and typography. Coordinates here are pixels, result boxes are fractions."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

import letitedit.catalogs.fonts as fonts
import letitedit.catalogs.platforms as platforms
import letitedit.studio.state as state

SIZE = {'story_9x16': (1080, 1920)}
LAYOUTS = {
    'photo': {'id': 'photo', 'name': 'Photo Story', 'photos': '1', 'motion': False,
              'fields': {'title': 'optional single short line, at most 48 characters'}},
    'photo_dump': {'id': 'photo_dump', 'name': 'Photo dump', 'photos': '1-10', 'motion': False,
                   'fields': {'title': 'optional single short line on each photo'}},
    'before_after': {'id': 'before_after', 'name': 'Before and after', 'photos': '2', 'motion': False,
                     'fields': {'before': 'short before label', 'after': 'short after label'}},
    'this_or_that': {'id': 'this_or_that', 'name': 'This or that', 'photos': '2', 'motion': False,
                     'fields': {'question': 'short question', 'left': 'first option', 'right': 'second option'}},
    'quote': {'id': 'quote', 'name': 'Quote', 'photos': '0-1', 'motion': False,
              'fields': {'quote': 'quotation, up to 180 characters', 'attribution': 'optional attribution'}},
    'fact_card': {'id': 'fact_card', 'name': 'Fact card', 'photos': '0-1', 'motion': False,
                  'fields': {'title': 'short title', 'lines': 'list of 1-3 supplied facts'}}}


def overlap(a, b):
    return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]


def contains(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3]


def clear_zone(targets, width, height):
    """Largest axis-aligned rectangle clear of the union of all requested platforms' covered areas."""
    covered = []
    for target in targets:
        pid = target['id'] if isinstance(target, dict) else target
        try:
            profile = platforms.load(pid)
        except (OSError, KeyError, ValueError) as exc:
            raise state.StudioError('platform_unknown', f'Unknown platform {pid}.', retry='after_change') from exc
        if not profile or not (profile.get('safe_zones') or {}).get('value'):
            raise state.StudioError('platform_unknown', f'No covered-area profile for {pid}.', retry='after_change')
        for r in profile['safe_zones']['value']:
            covered.append((r['x'] * width, r['y'] * height, r['w'] * width, r['h'] * height))
    # Conservative generic Story zone when no platform was requested.
    if not targets:
        covered = [(0, 0, width, height * .14), (0, height * .86, width, height * .14)]
    margin = round(width * .055)
    xs = sorted({margin, width - margin, *[v for r in covered for v in (r[0], r[0] + r[2])
                                         if margin <= v <= width - margin]})
    ys = sorted({margin, height - margin, *[v for r in covered for v in (r[1], r[1] + r[3])
                                          if margin <= v <= height - margin]})
    options = [(x, y, right - x, bottom - y) for x in xs for right in xs if right > x
               for y in ys for bottom in ys if bottom > y
               if not any(overlap((x, y, right - x, bottom - y), r) for r in covered)]
    if not options:
        raise state.StudioError('render_failed', 'The requested platforms leave no clear text zone.', retry='after_change')
    x, y, w, h = max(options, key=lambda r: r[2] * r[3])
    return (math.ceil(x), math.ceil(y + 20), math.floor(w), math.floor(h - 40))


def normal_box(value):
    if not isinstance(value, list) or len(value) != 4 or any(not isinstance(v, (float, int)) or
                                                           not math.isfinite(v) for v in value):
        raise state.StudioError('ai_failed', 'The AI returned an invalid picture box.', retry='yes')
    x, y, w, h = value
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.001 or y + h > 1.001:
        raise state.StudioError('ai_failed', 'The AI returned an out-of-range picture box.', retry='yes')
    return value


def crop_geometry(source_size, target, subject, faces):
    """Full bleed, subject centre retained, and every observed face retained in full (or refuse)."""
    sw, sh = source_size
    tx, ty, tw, th = target
    scale = max(tw / sw, th / sh)
    cw, ch = tw / scale, th / scale
    normal_box(subject)
    for face in faces:
        normal_box(face)
    px, py, pw, ph = subject
    cx, cy = (px + pw / 2) * sw, (py + ph / 2) * sh
    left, top = max(0, min(sw - cw, cx - cw / 2)), max(0, min(sh - ch, cy - ch / 2))
    if faces:
        x1 = min(f[0] for f in faces) * sw
        y1 = min(f[1] for f in faces) * sh
        x2 = max(f[0] + f[2] for f in faces) * sw
        y2 = max(f[1] + f[3] for f in faces) * sh
        if x2 - x1 > cw or y2 - y1 > ch:
            raise state.StudioError('render_failed', 'This full-bleed crop cannot keep every face. Send another photo.',
                                    retry='after_change')
        left = max(0, min(sw - cw, max(x2 - cw, min(left, x1))))
        top = max(0, min(sh - ch, max(y2 - ch, min(top, y1))))
    source_box = (left, top, cw, ch)
    actual_faces = [(tx + (f[0] * sw - left) * scale, ty + (f[1] * sh - top) * scale,
                     f[2] * sw * scale, f[3] * sh * scale) for f in faces]
    if any(not contains(target, f) for f in actual_faces):
        raise state.StudioError('render_failed', 'A face would be cropped.', retry='after_change')
    return source_box, actual_faces


def font_family(requested):
    # family() never fetches a font. Downloads are not a prerequisite for a still.
    if requested and fonts.family(requested):
        return requested
    if requested:
        raise state.StudioError('invalid_job', f'The font {requested} is not installed. Choose a bundled font.',
                                retry='after_change')
    return 'Noto Sans'


def text_block(text, width, family, one_line=False):
    """Fit without clipping/truncation. At least 48 px at 1080 width = 16 px at phone width 360."""
    if not isinstance(text, str) or not text.strip():
        raise state.StudioError('invalid_job', 'A still text field is empty.', retry='after_change')
    if one_line and ('\n' in text or len(text) > 48):
        raise state.StudioError('invalid_job', 'A photo Story takes one short line of at most 48 characters.',
                                retry='after_change')
    for size in range(78, 47, -2):
        font = fonts.pil_font(family, size, weight=700)
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        lines = []
        for paragraph in text.splitlines():
            line = ''
            for word in paragraph.split():
                candidate = (line + ' ' + word).strip()
                if draw.textlength(candidate, font=font) <= width:
                    line = candidate
                else:
                    if line:
                        lines.append(line)
                    line = word
            lines.append(line)
        if any(draw.textlength(line, font=font) > width for line in lines):
            continue
        if len(lines) > (1 if one_line else 5):
            continue
        line_height = math.ceil(size * 1.42)
        return '\n'.join(lines), font, size, len(lines) * line_height, line_height
    raise state.StudioError('invalid_job', 'The words do not fit at a readable phone size. Shorten them.',
                            retry='after_change')


def place_text(canvas, item, zone, faces, family, prefer='bottom', one_line=False, occupied=()):
    x, y, w, h = zone
    padding = 24
    lines, font, size, text_h, line_h = text_block(item['text'], w - 2 * padding, family, one_line)
    block_h = text_h + 2 * padding
    if block_h > h:
        raise state.StudioError('invalid_job', 'The words do not fit in the clear zone.', retry='after_change')
    # A grid of valid positions, ordered by the selected top/bottom preference; all are checked geometrically.
    ys = list(range(y, y + h - block_h + 1, 12)) + [y + h - block_h]
    if prefer == 'bottom':
        ys.reverse()
    elif prefer == 'centre':
        ys.sort(key=lambda v: abs(v + block_h / 2 - (y + h / 2)))
    box = next(((x, yy, w, block_h) for yy in ys
                if not any(overlap((x, yy, w, block_h), f) for f in [*faces, *occupied])), None)
    if box is None:
        raise state.StudioError('render_failed', 'Text cannot fit clear of faces. Shorten it or choose another photo.',
                                retry='after_change')
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((box[0], box[1], box[0] + box[2], box[1] + box[3]), radius=18, fill='#101820')
    for n, line in enumerate(lines.split('\n')):
        draw.text((box[0] + padding, box[1] + padding + n * line_h), line, font=font, fill='white', anchor='lt')
    item['box'] = dict(zip(('x', 'y', 'w', 'h'), (box[0] / canvas.width, box[1] / canvas.height,
                                                 box[2] / canvas.width, box[3] / canvas.height)))
    return box, {'font_px': size, 'phone_px': size / 3, 'contrast_ratio': 17.9}


def paste(canvas, picture, target, judgment):
    with Image.open(picture) as image:
        source_box, faces = crop_geometry(image.size, target, judgment['subject'], judgment['faces'])
        x, y, w, h = source_box
        crop = image.convert('RGB').resize((target[2], target[3]), Image.Resampling.LANCZOS,
                                           box=(x, y, x + w, y + h))
        canvas.paste(crop, (target[0], target[1]))
    return faces
