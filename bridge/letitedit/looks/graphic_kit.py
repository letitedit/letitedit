"""Portable, content-parameterized drawings and rendered evidence for a personal Look."""
from __future__ import annotations

import ast
import collections
import contextvars
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path

import letitedit.core.memory_room as memory_room

FORMAT = 'letitedit-graphic-kit/1'
TAG = '_look_kit'
# How a family's letters meet the picture under them. normal: drawn as painted. difference (or exclusion, the same
# result for white letters): composited by the engine frame by frame, so white letters show the inverse of whatever
# is under them and change with the shot. T242: a reference whose letters follow the picture this way became fixed
# colours chosen per caption, because a family could not carry its blend.
BLENDS = ('normal', 'difference', 'exclusion')
NEAR_INVISIBLE = 1.5        # an inverted letter frame below this median contrast with the picture is near invisible


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def timeline_digest(script):
    return digest({key: value for key, value in script.items()
                   if key not in ('project', 'base') and not key.startswith('_')})


def frame_rate(script):
    return float((script.get('profile') or {}).get('fps') or script.get('fps') or 30)


def source_fingerprint(script):
    paths = {str(item['clip']) for track in script.get('tracks', []) for item in track.get('items', [])
             if item.get('clip')}
    sources = {}
    for path in sorted(paths):
        try:
            details = Path(path).stat()
            sources[path] = [details.st_size, details.st_mtime_ns, details.st_ctime_ns]
        except OSError:
            sources[path] = None
    return digest(sources)


def load(value):
    return validate(json.loads(Path(value).read_text(encoding='utf-8-sig')) if isinstance(value, (str, Path)) else value)


def pair(value, name, minimum=0):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(number) not in (int, float) or not math.isfinite(number) for number in value) or
            not minimum <= value[0] <= value[1]):
        raise ValueError(f'{name} needs [minimum, maximum] finite numbers')
    return value


def validate(value):
    if not isinstance(value, dict) or value.get('format') != FORMAT:
        raise ValueError(f'graphic_kit format must be {FORMAT}')
    result = copy.deepcopy(value)
    families = result.get('families')
    if not isinstance(families, list) or not 1 <= len(families) <= 24:
        raise ValueError('graphic_kit needs 1-24 families')
    seen = set()
    for family in families:
        if not isinstance(family, dict) or set(family) - {'id', 'job', 'rate_per_min', 'count_per_video', 'duration_s', 'placement', 'never_covers', 'slots', 'graphic', 'persistence', 'anchor', 'blend'}:
            raise ValueError('family contains only its reusable spec and drawing')
        if family.get('blend', 'normal') not in BLENDS:
            raise ValueError('family blend is ' + ', '.join(BLENDS))
        if family.get('blend') == 'normal':
            del family['blend']
        if 'anchor' in family:
            anchor(family)
        identity = family.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', identity) or identity in seen:
            raise ValueError('family id must be unique lowercase words with hyphens')
        seen.add(identity)
        if family.get('job') not in ('speech', 'explanation', 'cta'):
            raise ValueError('family job is speech, explanation or cta')
        if ('rate_per_min' in family) == ('count_per_video' in family):
            raise ValueError('family needs exactly one of rate_per_min or count_per_video')
        cadence = 'count_per_video' if 'count_per_video' in family else 'rate_per_min'
        pair(family[cadence], cadence)
        if cadence == 'count_per_video' and any(int(number) != number for number in family[cadence]):
            raise ValueError('count_per_video bounds are whole occurrences')
        pair(family.get('duration_s'), 'duration_s', .001)
        if family.get('persistence', 'transient') not in PERSISTENCE:
            raise ValueError('persistence is transient, stays (on screen to the end) or accumulates (each one stays and the next joins it)')
        if not str(family.get('placement', '')).strip():
            raise ValueError('family needs a placement spec')
        if family.get('never_covers', ['face']) not in (['face'], []):
            raise ValueError('family never_covers is [face] (the default: its pieces are placed clear of faces) or [] '
                             '(its pieces may sit over a face, as the reference\'s do)')
        slots = family.get('slots')
        if (not isinstance(slots, list) or
                any(not isinstance(slot, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', slot) for slot in slots) or
                len(set(slots)) != len(slots) or
                set(slots) & {'code', 'animated', TAG, 'kit_index'}):
            raise ValueError('slots are mutable content parameter names, not code, animated or provenance')
        graphic = family.get('graphic') or {}
        if graphic.get('template') != 'custom' or set(graphic) - {'template', 'params', 'code', 'len'}:
            raise ValueError('portable families use self-contained custom graphic draw(ctx), no sources or assets')
        params = graphic.get('params') or {}
        code = graphic.get('code') or params.get('code')
        if not isinstance(code, str) or len(code) > 50000:
            raise ValueError('family needs self-contained draw(ctx) code')
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            raise ValueError(f'invalid drawing code: {error.msg}') from error
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if any(alias.name not in ('math',) for alias in node.names) or isinstance(node, ast.ImportFrom):
                    raise ValueError('portable drawing imports only math; external assets and files are not portable')
            if isinstance(node, ast.Name) and node.id in ('open', 'exec', 'eval', '__import__', 'compile', 'globals'):
                raise ValueError('portable drawing cannot read files or execute external code')
            if isinstance(node, ast.Attribute) and (node.attr.startswith('__') or node.attr in ('still', 'src', 'matte', 'depth')):
                raise ValueError('portable drawing cannot access runtime internals')
        if not any(isinstance(node, ast.FunctionDef) and node.name == 'draw' for node in tree.body):
            raise ValueError('family code must define draw(ctx)')
        params = {key: item for key, item in params.items() if key not in slots and key not in ('code', TAG)}
        family['graphic'] = {'template': 'custom', 'params': params, 'code': code}
    style = result.get('style', {})
    if not isinstance(style, dict) or set(style) - {'colors', 'fonts'}:
        raise ValueError('kit style contains colors and fonts only')
    if any(not isinstance(group, dict) for group in style.values()):
        raise ValueError('kit colors and fonts are mappings')
    if any('/' in str(value) or '\\' in str(value) for value in style.get('fonts', {}).values()):
        raise ValueError('kit fonts are bundled family names, not file paths')
    canonical = {'format': FORMAT, 'style': style, 'families': families}
    if 'built' in result:
        if result['built'] != {family['id']: digest({'family': family, 'style': style}) for family in families}:
            raise ValueError('kit changed after build; render its comparisons again')
        canonical['built'] = result['built']
    if 'measured' in result:
        measured = result['measured']
        if (not isinstance(measured, dict) or set(measured) - {family['id'] for family in families} or
                any(measured[family['id']] != likeness_digest(family, style) for family in families if family['id'] in measured)):
            raise ValueError('kit changed after its likeness was measured; build it again')
        canonical['measured'] = measured
    return canonical


PERSISTENCE = ('transient', 'stays', 'accumulates')


def blend_effects(family):
    """The placed piece's effects: none for normal letters, the engine's glyph-layer blend for a family whose letters
    follow the picture (the same filter the captions' blend uses)."""
    mode = family.get('blend', 'normal')
    return [] if mode == 'normal' else [{'filter': 'cairoblend_mode', 'params': {'mode': mode}}]


def placed_blend(family, effects):
    """The blend a placed piece shows: the family's own, or 'normal' (plain letters) for a blend family's piece turned
    white because its inverted letters were near invisible. None when the effects are not the kit's."""
    effects = effects or []
    if not effects:
        return 'normal'
    if (family.get('blend', 'normal') != 'normal' and len(effects) == 1 and isinstance(effects[0], dict) and
            effects[0].get('filter') == 'cairoblend_mode' and
            str((effects[0].get('params') or {}).get('mode', '')).lower() == family['blend']):
        return family['blend']
    return None
ANCHOR_KEYS = {'to', 'slot', 'side', 'below_chin', 'above_brow', 'band', 'across', 'half_height', 'face_height',
               'measured', 'why'}
BOTTOM_EDGE = 0.80          # an anchored piece's bottom edge stays above this share of the frame's height (TikTok's
                            # caption and buttons cover from 0.809, YouTube Shorts' from 0.844)
TOP_EDGE = 0.07             # and its top edge below this (the apps' tabs and status bar)
FACE_GAP = 0.015            # the least clear space between an anchored piece and the face


def anchor(family):
    """A family placed relative to the speaker: {to: speaker, slot: <the slot holding the piece's vertical centre as
    a share of the frame's height>}. kit_build adds what it measured on the reference frame: side (below the chin,
    above the brow or over the face), below_chin or above_brow (face heights from the chin down, or from the brow
    up, to the piece's centre), band (the same place as a share of the space between the chin and the frame's
    bottom, or the brow and its top), across (face widths from the face's centre), half_height (the piece's half
    height) and face_height (the reference face), both shares of the frame's height."""
    value = family['anchor']
    if (not isinstance(value, dict) or set(value) - ANCHOR_KEYS or value.get('to') != 'speaker'
            or value.get('slot') not in family.get('slots', [])):
        raise ValueError('anchor is {to: speaker, slot: <a slot of the family holding its vertical centre>}')
    if 'side' in value and value['side'] not in ('below', 'above', 'over'):
        raise ValueError('anchor side is below, above or over')
    for key in ('below_chin', 'above_brow', 'band', 'across', 'half_height', 'face_height'):
        if key in value and (type(value[key]) not in (int, float) or not math.isfinite(value[key])):
            raise ValueError(f'anchor {key} is a measured number')
    return value


def anchored_centre(family, face):
    """The vertical centre (frame share) for an anchored family on a new speaker whose face box is `face`
    ([x0, y0, x1, y1] frame shares), and a note when it couldn't sit where the reference put it. Below the chin: the
    same place on the body (face heights below the chin) when that is inside the uncovered frame; when the body runs
    out of frame first (a closer shot than the reference), the same share of the way down the visible body. Above
    the brow likewise, up to the frame's top. Always clear of the face and inside BOTTOM_EDGE and TOP_EDGE."""
    value = family['anchor']
    if not value.get('measured'):
        raise ValueError(f"{family['id']}: anchor not measured on a reference frame with a face; give its slot")
    if value.get('side') == 'over':
        raise ValueError(f"{family['id']}: on the reference it sits over the face, so it isn't placed by the face; "
                         f"give its slot")
    top, chin = float(face[1]), float(face[3])
    face_height = chin - top
    half = float(value.get('half_height', 0.02))
    note = None
    if value.get('side', 'below') == 'below':
        centre = chin + float(value['below_chin']) * face_height
        if centre + half > BOTTOM_EDGE:
            centre = chin + float(value.get('band', 0.33)) * (1 - chin)
            note = 'closer shot than the reference: the same share of the way down the visible body'
        lowest = BOTTOM_EDGE - half
        clear = chin + half + FACE_GAP
        if centre > lowest:
            centre, note = lowest, 'held above the covered bottom of the frame'
        if centre < clear:
            centre, note = clear, 'moved down to clear the face'
            if centre > lowest:
                centre, note = lowest, 'no room below the face: it meets the chin'
    else:
        centre = top - float(value['above_brow']) * face_height
        if centre - half < TOP_EDGE:
            centre = top - float(value.get('band', 0.5)) * top
            note = 'less room above the head than the reference: the same share of the way up'
        highest = TOP_EDGE + half
        clear = top - half - FACE_GAP
        if centre < highest:
            centre, note = highest, 'held below the covered top of the frame'
        if centre > clear:
            centre, note = clear, 'moved up to clear the face'
            if centre < highest:
                centre, note = highest, 'no room above the head: it meets the brow'
    return round(centre, 4), note


def speaker_box(script, at):
    """The largest face on the main picture at `at` seconds, as [x0, y0, x1, y1] frame shares: the main track's clip
    at that time, its frame decoded and fitted to the project's size (cover), faces found with the YuNet detector.
    None when no clip, no face or no detector. A punch-in or move on the clip is not followed."""
    import subprocess
    import letitedit.timeline.edit_sync as edit_sync
    import numpy as np
    profile = script.get('profile') or {}
    width, height = int(profile.get('width') or 1080), int(profile.get('height') or 1920)
    for track in script.get('tracks', []):
        if track.get('kind', 'video') != 'video':
            continue
        for item, start, end in edit_sync.layout(track):
            clip = item.get('clip')
            if not clip or not start <= at < end:
                continue
            source = float(item.get('in', 0) or 0) + (at - start) * float(item.get('speed', 1) or 1)
            try:
                import letitedit.footage.speech as speech
                ffmpeg = str(speech.FFPROBE).replace('ffprobe', 'ffmpeg')
                frame = subprocess.run([ffmpeg, '-v', 'error', '-ss', f'{source:.3f}', '-i', str(clip), '-frames:v', '1',
                                        '-vf', f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                                               f'crop={width}:{height}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                                       capture_output=True, timeout=60).stdout
                image = np.frombuffer(frame, np.uint8).reshape(height, width, 3)
                faces = detect_faces(image)
            except Exception:  # noqa: BLE001 - unreadable clip or no detector: unknown
                return None
            if not faces:
                return None
            box = max(faces, key=lambda f: (f[2] - f[0]) * (f[3] - f[1]))
            return [round(box[0] / width, 4), round(box[1] / height, 4), round(box[2] / width, 4),
                    round(box[3] / height, 4)]
        return None
    return None


def likeness_digest(family, style):
    return digest({'family': family, 'style': style, 'likeness': 1})


def picture_slots(family):
    return [slot for slot in family['slots'] if slot.endswith('picture')]


def picture_problem(value):
    """Why a picture slot's value can't ship (missing, not a picture, or blank), or None."""
    from PIL import Image, ImageStat
    if not isinstance(value, str) or not Path(value).is_file():
        return 'picture slot needs a real picture file (stock, generated or a frame of the footage)'
    try:
        with Image.open(value) as image:
            spread = ImageStat.Stat(image.convert('L').resize((64, 64))).stddev[0]
    except OSError:
        return 'picture slot file is not a picture'
    if spread < 6:
        return 'picture slot holds a blank placeholder'
    return None


def revision_kit(package, current, directory):
    value = package.get('graphic_kit')
    if 'graphic_kit' not in package and current:
        previous = Path(directory) / 'revisions' / current['revision'] / 'graphic-kit.json'
        value = load(previous) if previous.is_file() else None
    if value is None:
        return None
    kit = load(value)
    if not kit.get('built'):
        raise ValueError('graphic_kit needs rendered build comparisons before saving')
    if 'graphic_kit' in package:
        missing = [family['id'] for family in kit['families'] if family['id'] not in kit.get('measured', {})]
        if missing:
            raise ValueError('graphic_kit families outside measured likeness tolerance can not be saved: ' +
                             ', '.join(missing) + '. Rebuild them inside tolerance, or leave them out of the kit.')
    return kit


def description(kit):
    blended = [family for family in kit['families'] if family.get('blend', 'normal') != 'normal']
    return ('## Graphic kit\nThe sibling graphic-kit.json contains frozen, content-parameterized drawings: ' +
            ', '.join(family['id'] + ' (' + family['job'] + ')' for family in kit['families']) +
            '. kit_plan returns their placement edits; kit_check measures the rendered families and where their ink '
            'touches a face. ' +
            'Content comes from each new video; reference words and topic devices are not defaults.' +
            (' ' + ', '.join(family['id'] for family in blended) + (' are' if len(blended) > 1 else ' is') +
             ' composited with the ' + '/'.join(sorted({family['blend'].capitalize() for family in blended})) +
             ' blend, as measured on the reference: the letters invert whatever is under them, frame by frame, and '
             'change with the shot; kit_plan places the blend. kit_check turns a piece white only when its inverted '
             f'letters are near invisible (median contrast under {NEAR_INVISIBLE:g}:1) on more than half its frames.'
             if blended else ''))


def recipe(kit, family, content, seconds, index=None, check_duration=True):
    if set(content) != set(family['slots']):
        raise ValueError(f"{family['id']}: content must supply exactly {family['slots']}")
    persistence = family.get('persistence', 'transient')
    if check_duration and not (family['duration_s'][0] <= seconds and
                               (persistence != 'transient' or seconds <= family['duration_s'][1])):
        raise ValueError(f"{family['id']}: duration outside family spec")
    graphic = copy.deepcopy(family['graphic'])
    graphic['params'].update(content)
    graphic['params'][TAG] = {'kit': digest(kit), 'family': family['id'], 'style': kit['style']}
    if persistence == 'accumulates':
        graphic['params']['kit_index'] = int(index or 0)
    graphic['len'] = seconds
    return graphic


def build(package, out):
    import letitedit.pictures.graphics as graphics
    import letitedit.core.render_lock as render_lock
    import letitedit.looks.style_pack as style_pack
    from PIL import Image, ImageDraw, ImageOps
    kit = validate(package['kit'])
    examples = package.get('examples', [])
    if len(examples) != len(kit['families']) or {example['family'] for example in examples} != {family['id'] for family in kit['families']}:
        raise ValueError('examples needs one content/reference_frame pair for every family')
    width, height = package.get('size', [360, 640])
    if type(width) is not int or type(height) is not int or not 64 <= width <= 720 or not 64 <= height <= 1280:
        raise ValueError('build size is 64-720 wide, 64-1280 high')
    folder = Path(out).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    import letitedit.looks.kit_likeness as kit_likeness
    pages, likeness = [], []
    for example in examples:
        family = next(item for item in kit['families'] if item['id'] == example['family'])
        for slot in picture_slots(family):
            problem = picture_problem((example.get('content') or {}).get(slot))
            if problem:
                raise ValueError(f"{family['id']}.{slot}: {problem}")
    with render_lock.slot('Look graphic kit comparisons', timeout_s=7200):
        for family in kit['families']:
            example = next(item for item in examples if item['family'] == family['id'])
            seconds = float(example.get('seconds', sum(family['duration_s']) / 2))
            graphic = recipe(kit, family, example['content'], seconds,
                             check_duration=family.get('persistence', 'transient') == 'transient')
            drawing = style_pack.Kit({**copy.deepcopy(style_pack.DEFAULTS), **kit['style']})
            normalized = graphics.normalise(graphic, drawing)
            moments = example.get('times', [min(.1, seconds / 4), seconds / 2, max(0, seconds - .1)])
            if not isinstance(moments, list) or len(moments) != 3 or any(not 0 <= moment < seconds for moment in moments):
                raise ValueError('times are three entry/hold/exit times inside the piece')
            sheet = Image.new('RGB', (width * 4, height + 42), '#555555')
            label = ImageDraw.Draw(sheet)
            with Image.open(example['reference_frame']) as reference:
                cropped = reference.crop(example['crop']) if example.get('crop') else reference
                sheet.paste(ImageOps.contain(cropped.convert('RGB'), (width, height)), (0, 42))
            label.text((8, 8), family['id'] + ' / reference', fill='white')
            ink = []
            for index, (moment, picture) in enumerate(graphics.draw_frames(normalized, drawing, width, height, 30, times=moments)):
                ink.append(picture.getchannel('A').getbbox() is not None)
                background = Image.new('RGBA', picture.size, '#555555')
                background.alpha_composite(picture)
                sheet.paste(background.convert('RGB'), ((index + 1) * width, 42))
                label.text(((index + 1) * width + 8, 8), f'{moment:.3f}s', fill='white')
            if not any(ink):
                raise ValueError(f"{family['id']}: drawing is blank")
            image = folder / (family['id'] + '-comparison-private.png')
            sheet.save(image)
            pages.append(str(image))
            measured = kit_likeness.measure_family(kit, family, example, package.get('reference_video'),
                                                   cache_dir=folder.parent / 'font-measures-private')
            if family.get('anchor'):
                speaker = measured.get('speaker')
                family['anchor'] = {key: family['anchor'][key] for key in ('to', 'slot')}
                if speaker:
                    family['anchor'].update(measured=True, **{key: value for key, value in speaker.items()
                                                             if key in ANCHOR_KEYS})
                else:
                    family['anchor'].update(measured=False, why='no face and text found on the reference frame')
            measured['sheet'] = kit_likeness.sheet(example['reference_frame'], measured, kit, family, example,
                                                   folder / (family['id'] + '-likeness-private.png'))
            likeness.append(measured)
    kit['built'] = {family['id']: digest({'family': family, 'style': kit['style']}) for family in kit['families']}
    kit['measured'] = {result['family']: likeness_digest(family, kit['style'])
                       for result, family in zip(likeness, kit['families']) if result['passed']}
    saved = folder / 'graphic-kit.json'
    saved.write_text(json.dumps(kit, indent=2, allow_nan=False), encoding='utf-8')
    (folder / 'likeness-private.json').write_text(json.dumps(likeness, indent=2, allow_nan=False, default=str),
                                                  encoding='utf-8')
    failed = [result['family'] for result in likeness if not result['passed']]
    return {'kit': kit, 'kit_file': str(saved), 'comparisons': pages,
            'likeness': [{'family': result['family'], 'passed': result['passed'], 'sheet': result.get('sheet'),
                          'outside': [{'part': entry['part'], **row} for entry in result['parts']
                                      for row in entry['rows'] if not row['passed']],
                          'font_matches': {entry['part']: entry['font_matches'] for entry in result['parts']
                                           if entry.get('font_matches')}}
                         for result in likeness],
            'likeness_file': str(folder / 'likeness-private.json'),
            'saveable': not failed,
            'verification': ('Every family inside measured tolerance; it can be saved.' if not failed else
                             'Outside measured tolerance: ' + ', '.join(failed) + '. Save refuses these families: '
                             'change fonts, sizes, colours, plates, places or durations and build again, or leave them out.')}


def plan(reference, package, script=None):
    kit = load(reference)
    if not kit.get('built'):
        raise ValueError('kit needs rendered build comparisons before placement')
    changes = []
    existing = {track['name'] for track in (script or {}).get('tracks', [])}
    placed = []
    lanes = {}
    counts = {}
    for entry in sorted(package['placements'], key=lambda value: float(value['at'])):
        family = next((family for family in kit['families'] if family['id'] == entry['family']), None)
        if family is None:
            raise ValueError('family is not in the Look kit')
        persistence = family.get('persistence', 'transient')
        at = float(entry['at'])
        if persistence != 'transient' and entry.get('seconds') in (None, 'end'):
            end = package.get('video_s') or (video_seconds(script) if script else None)
            if not end:
                raise ValueError(f"{family['id']} stays to the end: give result (the project) or video_s")
            seconds = float(end) - at
        else:
            seconds = float(entry['seconds'])
        if not math.isfinite(at) or at < 0 or not math.isfinite(seconds):
            raise ValueError('placement times must be finite and nonnegative')
        if script:
            fps = frame_rate(script)
            at, seconds = round(at * fps) / fps, round(seconds * fps) / fps
        available = next((lane for lane in lanes.get(family['id'], []) if lane['end'] <= at), None)
        if available is None:
            number = 1
            while f"Kit {family['id']} {number}" in existing:
                number += 1
            name = f"Kit {family['id']} {number}"
            existing.add(name)
            available = {'name': name, 'end': 0}
            lanes.setdefault(family['id'], []).append(available)
            changes.append({'op': 'add_track', 'name': name, 'kind': 'video'})
        name = available['name']
        available['end'] = at + seconds
        index = counts.get(family['id'], 0)
        counts[family['id']] = index + 1
        content = dict(entry['content'])
        placed_note = None
        if family.get('anchor') and family['anchor']['slot'] not in content:
            face = entry.get('face') or (speaker_box(script, at) if script else None)
            if face is None:
                raise ValueError(f"{family['id']} at {at:g}s: no face found to place it by; give face "
                                 f"[x0, y0, x1, y1] (frame shares) or its {family['anchor']['slot']}")
            content[family['anchor']['slot']], placed_note = anchored_centre(family, face)
        entry = {**entry, 'content': content}
        for slot in picture_slots(family):
            problem = picture_problem(entry['content'].get(slot))
            if problem:
                raise ValueError(f"{family['id']}.{slot}: {problem}")
        graphic = recipe(kit, family, entry['content'], seconds, index)
        item = {'graphic': graphic, 'len': seconds}
        if blend_effects(family):
            item['effects'] = blend_effects(family)
        changes.append({'op': 'insert', 'track': name, 'at': at, 'item': item})
        placed.append({'family': family['id'], 'at': at, 'seconds': seconds, 'track': name,
                       **({'anchored': content[family['anchor']['slot']]} if family.get('anchor') else {}),
                       **({'note': placed_note} if placed_note else {})})
    return {'changes': changes, 'placements': placed, 'kit_sha256': digest(kit)}


def video_seconds(script):
    import letitedit.timeline.edit_sync as edit_sync
    ends = [end for track in script.get('tracks', []) if track.get('kind') != 'caption'
            for item, _, end in edit_sync.layout(track) if item.get('clip') and not item.get('graphic')]
    return max(ends) if ends else None


def inventory(kit, script):
    import letitedit.timeline.edit_sync as edit_sync
    import letitedit.pictures.graphics as graphics
    import letitedit.looks.style_pack as style_pack
    drawing = style_pack.Kit({**copy.deepcopy(style_pack.DEFAULTS), **kit['style']})
    families = {family['id']: family for family in kit['families']}
    placed, findings = [], []
    if any(track.get('cues') and track.get('burn_in', False) for track in script.get('captions', [])):
        findings.append({'problem': 'unknown native caption family'})
    for effect in script.get('master', []):
        if isinstance(effect, dict) and any(word in str(effect.get('filter', '')).lower() for word in ('text', 'subtitle', 'caption')):
            findings.append({'problem': 'unknown master text/caption family'})
    for track in script['tracks']:
        for item, start, end in edit_sync.layout(track):
            graphic = item.get('graphic')
            graphical = graphic or item.get('motion') or item.get('text') or item.get('code_scene') or track.get('kind') == 'caption'
            if any(isinstance(effect, dict) and (effect.get('text') or any(word in str(effect.get('filter', '')).lower()
                                                                          for word in ('text', 'subtitle', 'caption')))
                   for effect in item.get('effects', [])):
                findings.append({'problem': 'unknown embedded text/caption family', 'item': item.get('id')})
            if not graphical and Path(item.get('clip', '')).suffix.lower() in ('.png', '.svg', '.webp', '.gif', '.jpg', '.jpeg'):
                graphical = True
            if not graphical:
                continue
            tag = (graphic or {}).get('params', {}).get(TAG, {})
            family = families.get(tag.get('family'))
            if family is None or tag.get('kit') != digest(kit):
                findings.append({'problem': 'unknown or unpinned graphic/caption family', 'item': item.get('id')})
                continue
            try:
                content = {key: graphic['params'][key] for key in family['slots']}
                actual = graphics.normalise({**graphic, 'len': item.get('len', end - start)}, drawing)
                seconds = actual['len']
                if abs(seconds - (end - start)) > .001 + 1 / frame_rate(script):
                    raise ValueError('kit duration and timeline interval disagree')
                expected = graphics.normalise(recipe(kit, family, content, seconds,
                                                     graphic['params'].get('kit_index')), drawing)
                blend = placed_blend(family, item.get('effects'))
                if expected != actual or blend is None or item.get('speed', 1) != 1:
                    raise ValueError('drawing/style/transform differs from the frozen kit')
                for slot in picture_slots(family):
                    problem = picture_problem(content.get(slot))
                    if problem:
                        raise ValueError(f'{slot}: {problem}')
                placed.append({'item': item['id'], 'family': family['id'], 'start': start, 'end': end,
                               'track': track['name'], 'graphic': actual,
                               **({'blend': blend, 'family_blend': family['blend']}
                                  if family.get('blend', 'normal') != 'normal' else {})})
            except (ValueError, KeyError, TypeError) as error:
                findings.append({'problem': str(error), 'item': item.get('id')})
    return placed, findings


def live_lit(script):
    """Ids of base-picture clips carrying letitedit's live lighting."""
    import letitedit.looks.lighting as lighting
    tracks = [track for track in script.get('tracks', []) if track.get('kind') == 'video' and
              any(item.get('clip') and not item.get('graphic') for item in track.get('items', []))]
    return [item.get('id') for item in (tracks[0].get('items', []) if tracks else [])
            if item.get('clip') and lighting.is_live_lit(item)]


def picture_findings(script):
    """What was done to the speaker's picture (the main track's clips, that track and the master), as facts
    [{item, what}]: an inset, a split screen, a blur, a grade or a see-through picture. A Look or the person may call for
    any of them, so they are reported, not refused; letitedit's own live lighting is measured in check() instead."""
    import letitedit.timeline.edit_effects as edit_effects
    findings = []
    profile = script.get('profile') or {}
    width, height = profile.get('width', 1080), profile.get('height', 1920)
    fps = frame_rate(script)
    tracks = [track for track in script.get('tracks', []) if track.get('kind') == 'video' and
              any(item.get('clip') and not item.get('graphic') for item in track.get('items', []))]
    if not tracks:
        return findings
    base = tracks[0]
    import letitedit.looks.lighting as lighting
    scopes = [('master', script.get('master', [])), (base.get('name'), base.get('effects', []))]
    for item in base.get('items', []):
        if item.get('clip'):
            effects = item.get('effects', [])
            # letitedit's own live lighting (tagged mask trios) is measured by lighting.check_live in check(), not listed
            lit = {index for start, stop in lighting._live_pieces(effects) for index in range(start, stop)}
            scopes.append((item.get('id'), [effect for index, effect in enumerate(effects) if index not in lit]))
    for identity, effects in scopes:
        for effect in effects:
            if not isinstance(effect, dict):
                findings.append({'item': identity, 'what': "The speaker's picture has an effect the check can't read"})
                continue
            problem = None
            if 'zoom' in effect or 'size_position' in effect:
                try:
                    rect = edit_effects.motion_rect(effect, width, height, fps)
                    values = [part.split('=', 1)[-1] for part in rect.split(';')]
                    for value in values:
                        left, top, span_x, span_y = [float(number) for number in value.split()[:4]]
                        if left > .5 or top > .5 or left + span_x < width - .5 or top + span_y < height - .5:
                            problem = ("The speaker's picture is smaller than the frame (an inset, picture-in-picture, "
                                       'split screen or letterbox)')
                except (ValueError, TypeError, KeyError):
                    problem = "The speaker's picture has a size or position change the check can't read"
            elif 'ffmpeg' in effect:
                graph = effect['ffmpeg']
                graph = graph if isinstance(graph, str) else str(graph.get('video', ''))
                if re.search(r'\b(scale|pad|overlay|boxblur|gblur|avgblur|blur|eq|colorbalance|colorchannelmixer|lut[a-z0-9]*)\b', graph, re.I):
                    problem = "The speaker's picture is resized, blurred or graded by an ffmpeg graph"
            elif 'opacity' in effect and effect['opacity'] != 1:
                problem = "The speaker's picture is see-through (opacity below 1)"
            elif re.search(r'blur|brightness|contrast|color|tint|affine|crop|vignette|lift_gamma', str(effect.get('filter', '')), re.I):
                problem = ("The speaker's picture has a blur, colour, light, crop or vignette filter (not letitedit's "
                           'live lighting)')
            if problem:
                findings.append({'item': identity, 'what': problem})
    return findings


def face_cover(kit, placed, frames, fps):
    """Where the kit's ink fell inside a detected face box, as measured facts for the whole kit: {frames, seconds,
    first_frame, pieces_on_screen}. The measurement is of all the kit's ink together, so it can't say which piece
    covered the face: pieces_on_screen lists every piece placed at one of those frames ({item, family}), the safe ones
    too. And notes: one line of fact when any of those pieces is of a family placed clear of faces (never_covers
    [face], the default)."""
    frames = sorted(set(frames))
    on_screen = []
    for item in placed:
        a, b = round(item['start'] * fps), round(item['end'] * fps)
        if any(a <= frame < b for frame in frames):
            on_screen.append({'item': item['item'], 'family': item['family']})
    cover = {'frames': len(frames), 'seconds': round(len(frames) / fps, 2), 'first_frame': frames[0] if frames else None,
             'pieces_on_screen': on_screen}
    clear = {family['id'] for family in kit['families'] if 'face' in family.get('never_covers', ['face'])}
    placed_clear = sorted({piece['family'] for piece in on_screen if piece['family'] in clear})
    notes = []
    if frames:
        pieces = ', '.join(f"{piece['item']} ({piece['family']})" for piece in on_screen) or 'none placed'
        notes.append(f"The kit's ink falls inside a detected face box on {len(frames)} frame(s) ({cover['seconds']:g} s) "
                     f"from frame {frames[0]}; the measurement is of all its ink together, not of one piece. On screen "
                     f"at those frames: {pieces}." +
                     (f" {', '.join(placed_clear)} {'is a family' if len(placed_clear) == 1 else 'are families'} "
                      'placed clear of faces (never_covers [face]).' if placed_clear else ''))
    return cover, notes


def summarize(kit, placed, records, seconds):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('rendered video duration must be positive')
    findings, families = [], []
    for family in kit['families']:
        instances = [item for item in placed if item['family'] == family['id']]
        visible = [item for item in instances if records.get(item['item'], {}).get('visible_frames', 0) > 0]
        rate = len(visible) * 60 / seconds
        durations = [records[item['item']]['visible_frames'] / records[item['item']]['fps'] for item in visible]
        cadence = 'count_per_video' if 'count_per_video' in family else 'rate_per_min'
        lo, hi = family[cadence]
        actual = len(visible) if cadence == 'count_per_video' else rate
        count_ok = lo <= actual <= hi
        if not count_ok:
            findings.append({'family': family['id'], 'problem': 'family absent or rendered occurrence rate outside spec'})
        if len(visible) != len(instances):
            findings.append({'family': family['id'], 'problem': 'placed family has no visible rendered ink'})
        if family.get('persistence', 'transient') != 'transient':
            if any(item['end'] < seconds - 2 / records[item['item']]['fps'] for item in instances):
                findings.append({'family': family['id'], 'problem': 'this family stays on screen to the end, and an instance ends early'})
        elif any(duration < family['duration_s'][0] - 2 / records[item['item']]['fps'] or
                 duration > family['duration_s'][1] + 2 / records[item['item']]['fps']
                 for item, duration in zip(visible, durations)):
            findings.append({'family': family['id'], 'problem': 'rendered duration outside spec'})
        families.append({'id': family['id'], 'count': len(visible), 'rate_per_min': rate,
                         'cadence': cadence, 'expected_' + cadence: family[cadence],
                         'visible_duration_s': durations})
    return families, findings


def check(reference, project, video=None):
    import letitedit.core.render_lock as render_lock
    from letitedit.looks.look_check import current_project, project_digest, digest as file_digest
    kit = load(reference)
    _, path, script = current_project(project)
    placed, findings = inventory(kit, script)
    result = {'format': 'letitedit-graphic-kit-check/6', 'kit_sha256': digest(kit),
              'project_sha256': project_digest(script), 'findings': findings, 'passed': False,
              'timeline_sha256': timeline_digest(script),
              'sources_sha256': source_fingerprint(script),
              'picture': picture_findings(script),
              'faces': 'Frames where kit ink falls inside a detected face box are measured for the whole kit '
                       '(face_overlap_frames; face_cover: frames, seconds, first frame and the pieces on screen then, '
                       'not which one covered it) and reported as facts, not failures, with a note of fact when one of '
                       'those pieces is of a family whose never_covers is [face] (the default).',
              'limits': 'Face detection can miss faces. No detection is not proof of no face. Visual likeness is a separate review.'}
    import letitedit.timeline.project_journal as project_journal
    receipt = project_journal.folder(project) / 'graphic-kit-check.json'
    unread = False
    try:
        video_hash = file_digest(video) if video else None
    except OSError:
        # a supplied video that can't be read in full: the whole-result receipt is not reused and the video is not
        # used as the picture; the timeline is measured from the engine, where frames kept from earlier engine
        # renders whose timeline and engine match may still be reused (this video itself is not verified)
        video_hash, unread = None, True
    result['video_sha256'] = video_hash
    # what the script leaves out but the picture depends on (the video's own effects and blends with their windows,
    # every file a clip, effect or blend reads, by content when small), and the checker, engine and face model
    result['picture_sha256'] = picture_digest(path)
    result['checker_sha256'] = piece_base(result['kit_sha256'], 'engine')
    reuse = os.environ.get('LETITEDIT_KIT_REUSE', '1') != '0'      # 0: nothing reused, every frame drawn (comparisons)
    retry = False
    if receipt.is_file():
        try:
            previous = json.loads(receipt.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            previous = {}
        same = (previous.get('format') == result['format'] and
                previous.get('project_sha256') == result['project_sha256'] and
                previous.get('timeline_sha256') == result['timeline_sha256'] and
                previous.get('sources_sha256') == result['sources_sha256'] and
                previous.get('kit_sha256') == result['kit_sha256'] and
                # both computed: a picture digest that failed (None) never stands for "unchanged"
                result['picture_sha256'] is not None and previous.get('picture_sha256') == result['picture_sha256'] and
                previous.get('checker_sha256') == result['checker_sha256'])
        # and the font files its drawings may have used: still the same bytes
        if reuse and same and not unread and not previous.get('unverified') and _fonts_unchanged(previous.get('fonts')):
            # the same timeline, sources and kit give the same frames whether the composite came from the engine or
            # from an export of this timeline: measured once, not again for the export, the review or a preview. A
            # video it hasn't seen is read first: only a whole render of this timeline at the project's size (its rate,
            # its frame count, a seek to its last frame that lands and decodes) stands in. Anything else (unreadable,
            # another size, cut short) is measured, and says what is wrong. Damage inside a complete, decodable file
            # is for the export's own checks
            if video_hash is None or previous.get('video_sha256') == video_hash:
                return previous
            if _native(video, script) and _whole_render(video, path):
                previous['video_sha256'] = video_hash
                temporary = receipt.with_suffix('.tmp')
                temporary.write_text(json.dumps(previous, indent=2), encoding='utf-8')
                temporary.replace(receipt)
                return previous
        # the last try on this same picture waited its full time for memory and found none: this one looks again,
        # waiting only RETRY_WAIT_S (the export's pre-check and the review would each wait MEMORY_WAIT_S again)
        retry = same and bool(previous.get('no_room'))
    if findings:
        # only unpinned or unknown drawings stop the measuring now (the speaker's picture is reported in 'picture');
        # the wording stays as it is because look_check.KIT_NOT_MEASURED matches it
        result['findings'].append({'problem': 'Fix protected-picture or unpinned drawing findings before measuring'})
        return result
    waiting = _WAIT_S.set(min(RETRY_WAIT_S, MEMORY_WAIT_S)) if retry else None
    try:
        with render_lock.slot('Look kit every-frame check', timeout_s=7200):
            import letitedit.review.checks as checks
            # its engine renders, one per mode, run side by side when the memory the PC can promise holds them all, a
            # pair at a time when it doesn't (_measure_streamed): idle model helpers give their memory back first
            room = memory_room.make_room(sum(render_gb(mode) for mode in MODES) + memory_room.RESERVE_GB,
                                         'Look kit every-frame check')
            if room.get('note'):
                result['memory'] = room
            sweep_leftovers(checks.CACHE)
            if any(item.get('family_blend') for item in placed):
                from letitedit.looks.caption_colour import flash_frames
                flashes = flash_frames(script, frame_rate(script))
                for item in placed:
                    item['flash_frames'] = flashes
            native = video if video and not unread and _native(video, script) else None
            kept = None
            if reuse:
                kept = (_KeptFrames(receipt.with_name('graphic-kit-pieces.json')),
                        piece_base(result['kit_sha256'], video_hash if native else 'engine'))
            measured = measure(path, script, placed, native, kept=kept)
            result['measured_frames'] = 'kit stretches'
            if live_lit(script):
                import letitedit.looks.lighting as lighting
                light = lighting.check_live(path)
                result['lighting'] = {key: light.get(key) for key in ('passed', 'frames', 'with_face', 'face', 'room', 'limits', 'problem')}
                if not light.get('passed'):
                    result['findings'].append({'problem': 'Live lighting darkens or tints the face (or was not measured)',
                                               'lighting': result['lighting']})
        families, problems = summarize(kit, placed, measured['items'], measured['seconds'])
        result.update(measured, families=families)
        result['findings'].extend(problems)
        if any(item.get('family_blend') for item in placed):
            result['inversion'], problems = inversion_rows(placed, measured['items'])
            result['findings'].extend(problems)
        result['face_cover'], notes = face_cover(kit, placed, measured['face_overlap_frames'], frame_rate(script))
        if notes:
            result['notes'] = notes
        result['passed'] = not result['findings']
        result['fonts'] = _fonts_used(kept[0].fonts if kept else None)
    except Exception as error:
        result['findings'].append({'problem': f'Rendered kit check unverified: {error}'})
        result['unverified'] = True       # measured again next time: a busy PC lock or a cut-short run is not a finding
        if isinstance(error, NoRoom):
            result['no_room'] = True
    finally:
        if waiting is not None:
            _WAIT_S.reset(waiting)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
    temporary.replace(receipt)
    return result


JOIN_S = 2.0          # kit stretches closer than this are rendered as one (each stretch starts its own engine runs)
MODES = ('background', 'black', 'white', 'composite')


def stretches(placed, fps, frames, join_s=JOIN_S):
    """The frame ranges [a, b) where a kit item is on screen, joined across gaps under join_s: only these are rendered."""
    spans = sorted((max(0, round(item['start'] * fps)), min(frames, round(item['end'] * fps))) for item in placed)
    merged = []
    for a, b in spans:
        if b <= a:
            continue
        if merged and a <= merged[-1][1] + round(join_s * fps):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(span) for span in merged]


def sweep_leftovers(cache):
    """Folders an earlier kit check left when it was cut short (the old check kept a whole-video lossless render per
    mode there, 21 GB a pass on a 15-minute video). Called while holding the PC lock, which every kit check holds, so
    no other kit check is using them. Returns how many were removed."""
    import shutil
    removed = 0
    for folder in Path(cache).glob('look-kit-*'):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            removed += not folder.exists()
    return removed


def _mode_files(tree, path, main, selected, folder):
    """One project file per mode: background (kit tracks hidden), black and white (only the kit tracks, over black and
    over white: their difference is the kit's ink), composite (as it is)."""
    import xml.etree.ElementTree as ET
    import letitedit.timeline.timeline_model as timeline_model
    files = {}
    for mode in MODES:
        root = copy.deepcopy(tree)
        root.set('root', str(Path(path).parent))
        current = next(element for element in root.findall('tractor') if element.get('id') == main.get('id'))
        for index, track in enumerate(current.findall('track')):
            if track.get('producer') == 'background':
                continue
            if (mode == 'background' and index in selected) or (mode in ('black', 'white') and index not in selected):
                track.set('hide', 'both')
        if mode in ('black', 'white'):
            for effect in list(current.findall('filter')):
                current.remove(effect)
            for transition in current.findall('transition'):
                properties = timeline_model.props(transition)
                if properties.get('mlt_service') == 'frei0r.cairoblend' and int(properties.get('b_track', -1)) in selected:
                    for prop in transition.findall('property'):
                        if prop.get('name') == 'a_track':
                            prop.text = '0'
            for producer in list(root.findall('producer')) + list(root.findall('chain')):
                if producer.get('id') in ('black', 'background'):
                    for prop in producer.findall('property'):
                        if prop.get('name') == 'resource':
                            prop.text = '#ffffffff' if mode == 'white' else '#ff000000'
            _plain_letters(root)
        xml = Path(folder) / (mode + '.mlt')
        ET.ElementTree(root).write(xml, encoding='utf-8', xml_declaration=True)
        files[mode] = xml
    return files


def _plain_letters(root):
    """The kit tracks over black and over white measure the drawing's own ink: a piece's glyph-layer blend (its letters
    inverting the picture) comes off there, as the caption checks take it off."""
    import letitedit.timeline.timeline_model as timeline_model
    for parent in root.iter():
        for effect in list(parent.findall('filter')):
            if 'cairoblend_mode' in str(timeline_model.props(effect)):
                parent.remove(effect)


def _luminance(bgr):
    """WCAG relative luminance of BGR pixels (N x 3, 0-255)."""
    import numpy as np
    linear = np.asarray(bgr, dtype=np.float64) / 255
    linear = np.where(linear <= .04045, linear / 12.92, ((linear + .055) / 1.055) ** 2.4)
    return .0722 * linear[..., 0] + .7152 * linear[..., 1] + .2126 * linear[..., 2]


_linear = []


def _lookup_luminance(bgr):
    """_luminance of 8-bit BGR pixels from a table of the 256 linear values _luminance works out (T246: the same numbers,
    without a power per pixel)."""
    import numpy as np
    if not _linear:
        value = np.arange(256, dtype=np.float64) / 255
        _linear.append(np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4))
    linear = _linear[0][np.asarray(bgr, dtype=np.uint8)]
    return .0722 * linear[..., 0] + .7152 * linear[..., 1] + .2126 * linear[..., 2]


def inverted_contrast(background, core):
    """The median contrast of white inverted (Difference) letters with the picture under them on one frame: each glyph
    core pixel's inverse against the pixel itself. None without core pixels."""
    import numpy as np
    if not core.any():
        return None
    under = background[core]
    first, second = _lookup_luminance(255 - under), _lookup_luminance(under)
    ratio = (np.maximum(first, second) + .05) / (np.minimum(first, second) + .05)
    return float(np.median(ratio))


# T238 (6): a mode's engine render that gives no frame for this long is stopped (seen: four renders of an upright 60 fps
# HEVC phone clip at 0.00-0.05 s of CPU a minute, holding the PC lock, the tool call never returning); the check is then
# unverified, measured again next time. The check waiting on its own work (faces, ink) is not counted.
STALL_S = float(os.environ.get('LETITEDIT_KIT_STALL_S', '180'))


class Stalled(RuntimeError):
    """A mode's engine render stopped by the watchdog: no frame for STALL_S."""


def _trimmed(xml, a, b, fps, folder):
    """T249: the mode file with only what frames [a, b) show. Every track's entries outside them become blanks of the
    same length (all of a hidden track's), and the clips and bin entries nothing uses then are left out, so the
    engine opens only these. It used to open every clip of the project for each render: about 20 s before the first
    frame on Pair C (77 caption files and 40 clips of three long phone recordings), whatever the render's length.
    The same frames, byte for byte (tests/t249/REPORT.md). Returns the new file's path."""
    import xml.etree.ElementTree as ET
    import letitedit.timeline.timeline_model as timeline_model
    tree = ET.parse(xml)
    root = tree.getroot()
    elements = {element.get('id'): element for element in root if element.get('id')}
    tractors = [element for element in root if element.tag == 'tractor']
    main = ([tractor for tractor in tractors if timeline_model.props(tractor).get('shotcut') == '1'] or tractors)[-1]
    for track in main.findall('track'):
        playlist = elements.get(track.get('producer'))
        if playlist is None or playlist.tag != 'playlist':
            continue
        hidden = track.get('hide') in ('video', 'both')   # draws no picture (these renders make no sound)
        position = 0
        for index, child in enumerate(list(playlist)):
            if child.tag == 'blank':
                position += timeline_model.clock_to_frames(child.get('length'), fps) or 0
                continue
            if child.tag != 'entry':
                continue
            source = elements.get(child.get('producer'))
            first = timeline_model.clock_to_frames(child.get('in'), fps) or 0
            last = timeline_model.clock_to_frames(child.get('out'), fps)
            if last is None:
                last = timeline_model.clock_to_frames(source.get('out'), fps) or 0 if source is not None else 0
            length = last - first + 1
            if hidden or position >= b or position + length <= a:
                playlist.remove(child)
                playlist.insert(index, ET.Element('blank', {'length': str(length)}))
            position += length
    used, waiting = {main.get('id')}, [main]
    while waiting:
        for child in waiting.pop().iter():
            name = child.get('producer') if child.tag in ('track', 'entry') else None
            if name and name not in used and name in elements:
                used.add(name)
                waiting.append(elements[name])
    bin_name = root.get('producer')
    for element in list(root):
        if element.tag in ('producer', 'chain', 'tractor', 'playlist') and element.get('id') not in used:
            if element.get('id') == bin_name:
                for entry in list(element.findall('entry')):
                    if entry.get('producer') not in used:
                        element.remove(entry)
                continue
            root.remove(element)
    out = Path(folder) / f'{Path(xml).stem}-{a}-{b}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


class _EngineFrames:
    """Frames a..b-1 of one mode file straight from the export engine (melt) as BGR pictures through a pipe: nothing is
    written to disk. Below-normal priority, one engine thread each (the modes run side by side). The pipe is read on its
    own thread, two frames ahead at most, so a render that stops making frames is noticed and stopped. trim: the
    engine reads only what these frames show (_trimmed)."""

    def __init__(self, xml, a, b, timeline, folder, trim=True):
        import queue
        import subprocess
        import threading
        import letitedit.review.checks as checks
        import letitedit.core.render_lock as render_lock
        profile = timeline.profile
        self.size = profile['width'] * profile['height'] * 3
        self.shape = (profile['height'], profile['width'], 3)
        self.mode, self.span, self.fps, self.read_frames = Path(xml).stem, (a, b), timeline.fps, 0
        self.log = open(Path(folder) / f'{Path(xml).stem}-{a}.log', 'wb')
        if trim:
            xml = _trimmed(xml, a, b, timeline.fps, folder)
        command = [str(checks.MELT), '-quiet', str(xml), f'in={a}', f'out={b - 1}', '-consumer',
                   'avformat:pipe:1', 'f=rawvideo', 'vcodec=rawvideo', 'pix_fmt=bgr24', 'an=1', 'real_time=-1',
                   'threads=1', f'width={profile["width"]}', f'height={profile["height"]}',
                   f'frame_rate_num={profile["frame_rate_num"]}', f'frame_rate_den={profile["frame_rate_den"]}',
                   'sample_aspect_num=1', 'sample_aspect_den=1', 'progressive=1', *ENGINE_ARGS]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=self.log, stdin=subprocess.DEVNULL,
                                        bufsize=self.size, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                        | render_lock.background_flags(),
                                        env={**os.environ, **ENGINE_ENV} if ENGINE_ENV else None)
        self.frames = queue.Queue(maxsize=2)
        self.closed = threading.Event()
        self.reader = threading.Thread(target=self._pump, name=f'kit-{self.mode}', daemon=True)
        self.reader.start()

    def _pump(self):
        """The pipe into the queue: each frame's bytes, then b'' at the end."""
        try:
            while not self.closed.is_set():
                data = self.process.stdout.read(self.size)
                if not data:
                    break
                self._put(data)
                if len(data) != self.size:
                    break
        except (OSError, ValueError):
            pass
        finally:
            self._put(b'')

    def _put(self, item):
        import queue
        while not self.closed.is_set():
            try:
                self.frames.put(item, timeout=.5)
                return
            except queue.Full:
                continue

    def _next(self, waited_for):
        import queue
        try:
            return self.frames.get(timeout=STALL_S)
        except queue.Empty:
            self.process.kill()
            a, b = self.span
            raise Stalled(f'the engine stopped making frames for the {self.mode} picture of {a / self.fps:.1f}-'
                          f'{b / self.fps:.1f} s ({waited_for}): nothing new for {STALL_S / 60:g} min, so it was '
                          'stopped') from None

    def read(self):
        import numpy as np
        data = self._next('a frame')
        if len(data) != self.size:
            # T249: say where and how it ended. On Pair C the engine crashed (exit 139) on one version, and the AI,
            # told only that the render ended, guessed a cause and changed the edit
            try:
                code = self.process.wait(timeout=10)
            except Exception:  # noqa: BLE001 - still running: no code to give
                code = None
            a, b = self.span
            raise ValueError('render ended before every native frame was checked' + (
                f': the engine stopped (exit code {code}) at {(a + self.read_frames) / self.fps:.2f} s of the '
                f'{self.mode} picture of {a / self.fps:.1f}-{b / self.fps:.1f} s' if code is not None else ''))
        self.read_frames += 1
        return np.frombuffer(data, np.uint8).reshape(self.shape)

    def finish(self, deadline):
        import time
        extra = self._next('the end of its render')
        code = self.process.wait(timeout=max(1, deadline - time.monotonic()))
        if extra:
            raise ValueError('render gave more frames than the project has in this stretch')
        if code != 0:
            self.log.flush()
            raise RuntimeError(f'melt failed ({code}): ' + Path(self.log.name).read_text(errors='replace')[-1500:])

    def kill(self):
        """Stop the render now (from another thread: the memory watch); the reader then sees its frames end."""
        try:
            if self.process.poll() is None:
                self.process.kill()
        except OSError:
            pass

    def close(self):
        self.closed.set()
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=5)
        self.process.stdout.close()
        self.log.close()


class _FileFrames:
    """Frames of a finished render of the whole timeline (the export), read in order; frames between stretches are
    skipped without being converted."""

    def __init__(self, video, timeline):
        import cv2
        self.video = video
        self.stream = cv2.VideoCapture(str(video))
        self.at = 0
        if (abs(self.stream.get(cv2.CAP_PROP_FPS) - timeline.fps) > .001 or
                int(self.stream.get(cv2.CAP_PROP_FRAME_COUNT)) != timeline.frames):
            self.stream.release()
            raise ValueError('render frame count/rate differs from project')

    def seek(self, frame):
        if frame < self.at:             # a piece drawn again: read from the start, frame by frame, as the first time
            import cv2
            self.stream.release()
            self.stream, self.at = cv2.VideoCapture(str(self.video)), 0
        while self.at < frame:
            if not self.stream.grab():
                raise ValueError('render ended before every native frame was checked')
            self.at += 1

    def read(self):
        success, picture = self.stream.read()
        if not success:
            raise ValueError('render ended before every native frame was checked')
        self.at += 1
        return picture

    def close(self):
        self.stream.release()


def _native(video, script):
    """Whether a render is at the project's own size and rate (an export; a reduced preview is not)."""
    try:
        import cv2
        stream = cv2.VideoCapture(str(video))
        try:
            size = (int(stream.get(cv2.CAP_PROP_FRAME_WIDTH)), int(stream.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        finally:
            stream.release()
        profile = script.get('profile') or {}
        return size == (profile.get('width'), profile.get('height'))
    except Exception:  # noqa: BLE001 - unreadable: measured from the engine instead
        return False


def _whole_render(video, path):
    """Whether a video is a whole render of this timeline: its rate and frame count, and a seek to its last frame
    that lands there and decodes (a file cut short can still name the full count; a seek that fails reads nothing)."""
    try:
        import cv2
        import letitedit.review.checks as checks
        timeline, _ = checks.resolve(path)
        stream = cv2.VideoCapture(str(video))
        try:
            if (abs(stream.get(cv2.CAP_PROP_FPS) - timeline.fps) > .001 or
                    int(stream.get(cv2.CAP_PROP_FRAME_COUNT)) != timeline.frames):
                return False
            if not stream.set(cv2.CAP_PROP_POS_FRAMES, timeline.frames - 1):
                return False
            if round(stream.get(cv2.CAP_PROP_POS_FRAMES)) != timeline.frames - 1:
                return False
            return bool(stream.read()[0])
        finally:
            stream.release()
    except Exception:  # noqa: BLE001 - unreadable: the check measures it and says what is wrong
        return False


def measure(path, script, placed, video=None, kept=None):
    """kept: (a _KeptFrames, the base fingerprint) to reuse and keep each frame's result (T246, T249)."""
    if os.environ.get('LETITEDIT_KIT_STREAMED', '1') == '0':        # the whole-timeline check, for comparison tests
        return _measure_every_frame(path, script, placed, video)
    return _measure_streamed(path, script, placed, video, kept)


def _measure_every_frame(path, script, placed, video=None):
    """The older check (the whole timeline, four lossless files on disk): the comparison test measures the streamed
    check against it on the same project (the same findings), and LETITEDIT_KIT_STREAMED=0 still selects it."""
    import tempfile
    import xml.etree.ElementTree as ET
    import letitedit.review.checks as checks
    import cv2
    import letitedit.pictures.graphics as graphics
    import numpy as np
    import letitedit.looks.style_pack as style_pack
    import letitedit.timeline.timeline_model as timeline_model
    if not checks.YUNET.is_file():
        raise ValueError('local face model missing; no download attempted')
    timeline, path = checks.resolve(path)
    width, height = timeline.profile['width'], timeline.profile['height']
    cv2.setNumThreads(4)
    names = {item['track'] for item in placed}
    records = {item['item']: {'visible_frames': 0, 'fps': timeline.fps} for item in placed}
    overlap, unknown, active_frames = [], [], 0
    tree = ET.parse(path).getroot()
    tractors = tree.findall('tractor')
    main = next((element for element in reversed(tractors) if timeline_model.props(element).get('shotcut') == '1'), tractors[-1])
    selected_ids = {element.get('id') for element in tree.findall('playlist') if timeline_model.props(element).get('shotcut:name') in names}
    selected = {index for index, track in enumerate(main.findall('track')) if track.get('producer') in selected_ids}
    if len(selected) != len(names):
        raise ValueError('kit track routing could not be resolved')
    checks.CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='look-kit-', dir=checks.CACHE) as folder:
        paths = {}
        for mode in ('background', 'black', 'white', 'composite'):
            if mode == 'composite' and video:
                paths[mode] = str(video)
                continue
            root = copy.deepcopy(tree)
            root.set('root', str(Path(path).parent))
            current = next(element for element in root.findall('tractor') if element.get('id') == main.get('id'))
            for index, track in enumerate(current.findall('track')):
                if track.get('producer') == 'background':
                    continue
                if (mode == 'background' and index in selected) or (mode in ('black', 'white') and index not in selected):
                    track.set('hide', 'both')
            if mode in ('black', 'white'):
                for effect in list(current.findall('filter')):
                    current.remove(effect)
                for transition in current.findall('transition'):
                    properties = timeline_model.props(transition)
                    if properties.get('mlt_service') == 'frei0r.cairoblend' and int(properties.get('b_track', -1)) in selected:
                        for prop in transition.findall('property'):
                            if prop.get('name') == 'a_track':
                                prop.text = '0'
                for producer in list(root.findall('producer')) + list(root.findall('chain')):
                    if producer.get('id') in ('black', 'background'):
                        for prop in producer.findall('property'):
                            if prop.get('name') == 'resource':
                                prop.text = '#ffffffff' if mode == 'white' else '#ff000000'
                _plain_letters(root)
            xml = Path(folder) / (mode + '.mlt')
            ET.ElementTree(root).write(xml, encoding='utf-8', xml_declaration=True)
            output = xml.with_suffix('.mkv')
            checks._run([checks.MELT, '-quiet', xml, 'in=0', f'out={timeline.frames - 1}', '-consumer',
                         f'avformat:{output}', 'vcodec=ffv1', 'an=1', 'threads=4', 'real_time=-4',
                         f'width={width}', f'height={height}', f'frame_rate_num={timeline.profile["frame_rate_num"]}',
                         f'frame_rate_den={timeline.profile["frame_rate_den"]}', 'sample_aspect_num=1',
                         'sample_aspect_den=1', 'progressive=1'], timeout=7200)
            paths[mode] = str(output)
        streams = {name: cv2.VideoCapture(value) for name, value in paths.items()}
        try:
            if any(abs(stream.get(cv2.CAP_PROP_FPS) - timeline.fps) > .001 or
                   int(stream.get(cv2.CAP_PROP_FRAME_COUNT)) != timeline.frames for stream in streams.values()):
                raise ValueError('render frame count/rate differs from project')
            import itertools
            frames = {item['item']: iter(graphics.draw_frames(item['graphic'], style_pack.load(), width, height, timeline.fps))
                      if item['graphic']['params'].get('animated', True) else
                      itertools.repeat(next(graphics.draw_frames(item['graphic'], style_pack.load(), width, height, timeline.fps)))
                      for item in placed}
            for frame_index in range(timeline.frames):
                pictures = {name: stream.read() for name, stream in streams.items()}
                if not all(success for success, _ in pictures.values()):
                    raise ValueError('render ended before every native frame was checked')
                pictures = {name: picture for name, (_, picture) in pictures.items()}
                if any(picture.shape[:2] != (height, width) for picture in pictures.values()):
                    raise ValueError('render dimensions differ from project')
                active = [item for item in placed if round(item['start'] * timeline.fps) <= frame_index < round(item['end'] * timeline.fps)]
                if not active:
                    continue
                active_frames += 1
                alpha = 255 - np.max(pictures['white'].astype(np.int16) - pictures['black'].astype(np.int16), axis=2)
                ink = alpha > 0
                delta = np.max(np.abs(pictures['composite'].astype(np.int16) - pictures['background'].astype(np.int16)), axis=2) >= 4
                for item in active:
                    try:
                        _, drawing = next(frames[item['item']])
                    except StopIteration:
                        raise ValueError('kit duration and rendered interval disagree') from None
                    alpha = np.asarray(drawing.getchannel('A'))
                    mask = alpha > 0
                    if np.any(mask & ink & delta):
                        records[item['item']]['visible_frames'] += 1
                    counts = {}
                    _count_inversion(item, frame_index, alpha, pictures['background'], counts)
                    for name, (frames, near) in counts.items():
                        row = records[name].setdefault('inversion', [0, 0])
                        row[0], row[1] = row[0] + frames, row[1] + near
                boxes = detect_faces(pictures['background'])
                if not boxes:
                    unknown.append(frame_index)
                if any(np.any(ink[max(0, y0):min(height, y1), max(0, x0):min(width, x1)]) for x0, y0, x1, y1 in boxes):
                    overlap.append(frame_index)
        finally:
            for stream in streams.values():
                stream.release()
    return {'items': records, 'seconds': timeline.frames / timeline.fps, 'checked_frames': timeline.frames,
            'active_frames': active_frames, 'face_overlap_frames': overlap, 'missing_face_frames': unknown,
            'render_size': [width, height], 'rendered_by': 'melt; native size/rate; every frame, clean-picture YuNet faces'}




# T239: the check's engine renders, one per mode, run only as many at once as the memory the PC can promise holds
# (memory_room), and are stopped when it falls under the reserve while they run.
INK = ('black', 'white')                 # the kit tracks over black and over white: their difference is the kit's ink
PICTURE = ('background', 'composite')    # the picture without the kit, and the finished picture
PIECE_S = float(os.environ.get('LETITEDIT_KIT_PIECE_S', '10'))              # a longer stretch is drawn in pieces
MEMORY_WAIT_S = float(os.environ.get('LETITEDIT_KIT_MEMORY_WAIT_S', '300'))  # the longest it waits for memory
# a check on a picture whose last try waited MEMORY_WAIT_S and found no memory waits this long instead (check sets it)
RETRY_WAIT_S = 30.0
_WAIT_S = contextvars.ContextVar('kit_memory_wait_s', default=None)
MEMORY_POLL_S = 0.25                     # how often the memory watch reads the memory free to promise
# The check's engine renders run with these. Measured one render at a time on a 33 s stretch of an upright 60 fps
# project with 61 clips (tests/t239/REPORT.md): every engine render committed 2 GB it never touched (OpenBLAS, which
# OpenCV's engine plugin loads, keeps a 128 MB buffer per OpenMP thread: 16 here) and kept 4 decoded pictures per
# clip it had opened. With OpenMP at one thread (the renders are one engine thread each anyway) and the clips' picture
# cache off, the same frames came out (every frame's bytes the same) at the same speed, and the four renders' peaks
# went from 4.63 + 3.93 + 3.93 + 4.57 GB to 2.40 + 1.35 + 1.35 + 2.13 GB. The check's renders make no sound, so they
# take the picture renders' settings (memory_room.PICTURE_ENGINE_ENV, which the export's picture chunks use too).
ENGINE_ENV = memory_room.PICTURE_ENGINE_ENV
# The engine draws up to `buffer` frames ahead of the pipe (25 by default), each holding every track's pictures; the
# check reads slower than the engine draws (about 4 frames a second against 9 there), so the queue stays full: a
# picture render's 10 s piece peaked at 2.66 GB read at 4 frames a second and at 1.78 GB with two frames ahead, the
# same frames, and read at full speed it lost no time.
ENGINE_ARGS = ('buffer=2',)
# about what one of the check's renders commits with ENGINE_ENV, in GB: the most measured over a whole 33 s stretch
# (a piece of PIECE_S commits less: 1.6 GB for the picture), plus room for heavier footage
KIT_RENDER_GB = {'background': 3.0, 'composite': 3.0, 'black': 2.0, 'white': 2.0}


class ShortOfMemory(RuntimeError):
    """The memory the PC can promise fell under the reserve while the check's renders ran: they were stopped."""


class NoRoom(RuntimeError):
    """The check could not get memory for even its smallest turn of renders."""


def render_gb(mode):
    """About what one of the check's engine renders commits, in GB (KIT_RENDER_GB; memory_room.RENDER_GB for a mode
    it doesn't name)."""
    return KIT_RENDER_GB.get(mode, memory_room.RENDER_GB)


def turns(modes, free_gb, split=False, reserve_gb=None):
    """The check's engine renders in turns that fit in free_gb GB of memory the PC can promise, with reserve_gb
    (memory_room.RESERVE_GB) kept for everything else: [modes] (all at once), else [ink modes, picture modes] (a pair
    at once each), else None. free_gb None (it can't be read) counts as enough. split: pairs even when all would fit."""
    reserve = memory_room.RESERVE_GB if reserve_gb is None else reserve_gb
    modes = list(modes)
    if not split and (free_gb is None or free_gb >= sum(render_gb(mode) for mode in modes) + reserve):
        return [modes]
    pairs = [group for group in ([m for m in modes if m in INK], [m for m in modes if m in PICTURE]) if group]
    if free_gb is None or free_gb >= _need(pairs, reserve):
        return pairs
    return None


def _need(groups, reserve):
    return max(sum(render_gb(mode) for mode in group) for group in groups) + reserve


def pieces(spans, fps, piece_s=None):
    """The stretches [a, b) cut into pieces of at most piece_s seconds (PIECE_S; 0 keeps whole stretches), each drawn by
    its own engine renders, so no render runs on through more of the video's clips than one piece holds."""
    size = round((PIECE_S if piece_s is None else piece_s) * fps)
    out = []
    for a, b in spans:
        if size <= 0:
            out.append((a, b))
            continue
        # T246: on a fixed grid from the video's start, so a piece an edit didn't touch keeps its frames (and its
        # kept results, _KeptFrames) when a kit item elsewhere moves and the stretches change
        start = a
        while start < b:
            end = min(b, (start // size + 1) * size)
            out.append((start, end))
            start = end
    return out


# T246 kept each 10-second piece's result under a fingerprint of the whole piece. T249 keeps each frame's result under
# a fingerprint of what draws that frame, so a later check draws again only the frames an edit changed. On Pair C
# (18 Nov) no piece was ever reused: the piece fingerprint named every track by its number and every kit item by its
# id, and the AI added or removed a caption track at almost every edit (10 to 25 tracks and back) and rebuilt the
# captions with the same words under new ids. A frame's fingerprint names, bottom to top, only the tracks that draw it
# (an item there, or effects of their own) and the tracks they are blended onto, by their order among those: an empty
# track or one elsewhere draws nothing there (measured byte for byte on Pair C's footage, tests/t249/REPORT.md). For
# each: its own effects, whether it is the kit's, and the item on screen with how far into it this frame is; then the
# blends between them, the video's own effects and the burned subtitles there, and the kit items on screen (drawing,
# timing, blend, flash) in that order. Results name the kit items by their place in that order, not their ids. Every
# effect or blend (on a track, on the whole video, between tracks) adds, beside its own description, whether this
# frame is inside its in and out points and where (a dissolve's progress), keyframed or not; one that may change
# over its life (all but STATIC_SERVICES) adds where the frame is even without in and out points. Every file a clip,
# effect or blend reads at any depth counts, by content when small (CONTENT_HASH_BYTES). A frame depends only on what
# is on screen in it and is judged on its own, so a kept frame gives what drawing it again would.
PIECE_FORMAT = 'letitedit-kit-frame/6'
FRAMES_KEPT = 60000      # frames' results kept per project (the latest check's first, then the ones before, for an undo)
RUN_JOIN_S = 1.0         # frames to draw closer than this are drawn in one run (each run starts its own renders)


SOURCE_PACKAGE = Path(__file__).resolve().parents[1]      # the letitedit package this check runs from
# this check, the kit's drawing code and its styles: (folder in the package, what the file names start with); each is
# required, as every .py file there whose name starts so
CHECKER_SOURCES = (('looks', 'graphic_kit'), ('pictures', 'graphics'), ('looks', 'style_pack'))


def _checker_code(package):
    """{file name: digest of its bytes} for the checker's own source (CHECKER_SOURCES). The folders are listed with
    os.scandir, which raises when a folder can't be listed (a pattern search would find nothing instead). Raises OSError
    when a folder can't be listed, a file can't be read or a required source is missing: the identity is then
    unresolved and nothing is reused."""
    code, listed = {}, {}
    for folder, start in CHECKER_SOURCES:
        if folder not in listed:
            with os.scandir(Path(package) / folder) as entries:
                listed[folder] = sorted(entry.name for entry in entries if entry.is_file())
        names = [name for name in listed[folder] if name.startswith(start) and name.endswith('.py')]
        if not names:
            raise OSError(f'the checker source {folder}/{start}*.py is missing')
        for name in names:
            code[name] = hashlib.sha256((Path(package) / folder / name).read_bytes()).hexdigest()
    return code


def piece_base(kit_sha, composite):
    """What every piece's result depends on besides its own frames: this check's code, the drawing code, the engine and
    the face model, the kit, and where the finished picture comes from ('engine' or an export's digest)."""
    import letitedit.review.checks as checks
    import uuid
    unresolved = 'unresolved ' + uuid.uuid4().hex        # what can't be read matches nothing: no reuse, measured again
    try:
        code = _checker_code(SOURCE_PACKAGE)
    except OSError:
        code = unresolved
    try:              # the engine, the libraries beside it, its modules (lib/mlt) and its frei0r plugins (lib/frei0r-1)
        app = Path(checks.MELT).parent
        modules = sorted(app.glob('lib/mlt/*.dll')) + sorted(app.glob('lib/frei0r-1/*.dll'))
        if not any(path.parent.name == 'mlt' for path in modules):
            raise OSError('no engine modules found')
        engine = [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in
                  sorted({Path(checks.MELT), *app.glob('*.dll'), *modules})]
    except OSError:
        engine = unresolved
    try:
        details = Path(checks.YUNET).stat()
        faces = [str(checks.YUNET), details.st_size, details.st_mtime_ns]
    except OSError:
        faces = unresolved
    return digest({'format': PIECE_FORMAT, 'kit': kit_sha, 'composite': composite, 'code': code, 'engine': engine,
                   'engine_env': dict(ENGINE_ENV or {}), 'engine_args': list(ENGINE_ARGS), 'faces': faces,
                   'inherited': _render_environment(), 'fonts': _font_inventory(unresolved)})


# what a render inherits that changes how it draws: the engine's and its plugins' settings, Qt's and the font
# search's (the renders run with the bridge's own environment plus ENGINE_ENV)
RENDER_ENVIRONMENT = ('MLT_', 'FREI0R', 'LADSPA', 'QT_', 'FONTCONFIG', 'LETITEDIT_FONT')


def _render_environment():
    return sorted((name.upper(), value) for name, value in os.environ.items()
                  if name.upper().startswith(RENDER_ENVIRONMENT) or name.upper() == 'LOCALAPPDATA')


def _font_inventory(unresolved):
    """Every font file the engine's text modules and the kit's drawings could find, by path, size and date: the
    folders a render searches (LETITEDIT_FONT_DIRS, else the bundled library and the per-user Windows fonts, as
    font_env and the engine's qt/common.cpp find them) and the drawings' font index (which file each family resolves
    to). The bytes of the files the drawings actually used are checked with the kept results (_fonts_unchanged)."""
    try:
        import letitedit.catalogs.fonts as fonts
        import letitedit.core.font_env as font_env
        folders = [part for part in (os.environ.get(font_env.ENV) or ';'.join(map(str, font_env.default_dirs())))
                   .split(';') if part]
        files = []

        def failed(error):
            raise error             # a folder that can't be listed: the inventory is unresolved, never partial
        for folder in sorted(set(folders)):
            if not os.path.lexists(folder):
                files.append((folder, 'absent'))      # a search folder this PC doesn't have: part of the inventory
                continue
            for root, _, names in os.walk(folder, onerror=failed):
                for name in names:
                    if name.lower().endswith(('.ttf', '.otf', '.ttc', '.otc')):
                        details = os.stat(os.path.join(root, name))
                        files.append((os.path.join(root, name), details.st_size, details.st_mtime_ns))
        return [folders, sorted(files), digest(fonts.index())]
    except Exception:  # noqa: BLE001 - unresolved: nothing reused
        return unresolved


def _font_mark(path, hashed):
    """A font file's _file_mark, or None when it can't be read (a record holding one is never unchanged)."""
    try:
        return _file_mark(Path(path), hashed)
    except Unreadable:
        return None


def _fonts_used(earlier=None):
    """{font file: _file_mark} for every font the kit's drawings may have drawn with: those this process resolved
    (fonts.RESOLVED) and those an earlier record named. A font that can't be read is recorded as None: such a record is
    incomplete (_fonts_complete) and is never kept or reused."""
    import letitedit.catalogs.fonts as fonts
    record, hashed = dict(earlier or {}), {}
    for path in sorted(fonts.RESOLVED):
        record[path] = _font_mark(path, hashed)
    return record


def _fonts_complete(record):
    """Whether a font record holds a full mark (size, date and, for a small file, its digest) for every font."""
    return isinstance(record, dict) and all(
        isinstance(mark, list) and len(mark) >= 2 and None not in mark for mark in record.values())


def _fonts_unchanged(record):
    """Whether every font file a record names is still there with the same size, date and bytes. No record (an older
    result), or one holding a font that couldn't be read then or can't be read now, is not unchanged."""
    if not _fonts_complete(record):
        return False
    hashed = {}
    return all(_font_mark(path, hashed) == mark for path, mark in record.items())


# A file up to this size (a look-up table, a mask, a picture, a drawing, a caption file) is fingerprinted by its
# content, so new bytes under the same size and date still count. Bigger files (footage) by size and date: reading
# gigabytes of footage at every check would cost more than the check saves.
CONTENT_HASH_BYTES = 20 * 1024 * 1024


class Unreadable(Exception):
    """A file the picture depends on (one the list accepted, a font a drawing used) can't be read in full now: gone,
    no longer a file, or its size, date or bytes unreadable. Nothing that rests on it is reused."""


def _file_mark(path, hashed):
    """[size, date] of a file, and its content's digest when it is small. Raises Unreadable when it isn't a file or
    any of that can't be read: never a stand-in value that could match an earlier failure. `hashed` keeps digests
    within one check (a file named by many clips is read once); a failed read is never kept there."""
    try:
        if not path.is_file():
            raise Unreadable(f'{path} is not a file')
        details = path.stat()
    except (OSError, ValueError) as error:
        raise Unreadable(f'{path}: {error}') from error
    mark = [details.st_size, details.st_mtime_ns]
    if details.st_size <= CONTENT_HASH_BYTES:
        key = (str(path), details.st_size, details.st_mtime_ns)
        if key not in hashed:
            try:
                hashed[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            except (OSError, ValueError) as error:
                raise Unreadable(f'{path}: {error}') from error
        mark.append(hashed[key])
    return mark


# the elements that carry a service with properties on the list (UNDERSTOOD); files are named only in their _file ones
_SERVICE_TAGS = frozenset({'tractor', 'playlist', 'chain', 'producer', 'filter', 'transition'})


def _files_in(timeline, element, folder, out, hashed=None, known=None):
    """Every file the list's typed file properties (_file: a clip's video, a grade's look-up table) name in `element`
    and in what it plays at any depth, by its _file_mark: exactly the files the list accepts, at any length of path.
    A part outside the list names none here (its frames are drawn and never reused, or nothing is). `known` is the
    list check's own answer per element (_outside), so a file that check accepted and that is gone or unreadable now
    raises Unreadable rather than being passed over. No recursion: a deep graph can't overflow."""
    import letitedit.timeline.timeline_model as timeline_model
    hashed = {} if hashed is None else hashed
    known = {} if known is None else known
    seen, stack = set(), [element]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if node.tag in ('entry', 'track'):
            stack.append(timeline.elements.get(node.get('producer')))     # what it plays
        stack.extend(child for child in node if child.tag != 'properties')
        if node.tag not in _SERVICE_TAGS:
            continue
        if id(node) not in known:
            known[id(node)] = _outside_element(node, timeline, folder)
        if known[id(node)]:
            continue
        properties = timeline_model.props(node)
        service = properties.get('mlt_service') if node.tag not in ('tractor', 'playlist') else None
        allowed = UNDERSTOOD[(node.tag, service)][2]
        for name, value in properties.items():
            rule = allowed.get(name)
            if isinstance(rule, tuple) and rule[0] == 'file':
                path = Path(value)
                out[str(path)] = _file_mark(path, hashed)


# What the frame fingerprints (_FrameKeys) and the picture digest (picture_digest) describe completely. Reuse rests on
# this list alone, and the list is what letitedit's own projects use: every element, attribute, property and service
# here appears in that form in the projects New video makes (T249's survey), and nothing else does. Anything outside it
# makes the frames it touches be drawn, never reused, and turns the whole-result receipt off. Each entry says why it
# is described in full.
ANY = 'any'        # any value: it is in the description (canon's text, so in every key that reads it)
LABEL = 'label'    # the editor's or letitedit's own note: no engine module reads shotcut:, letitedit: or letitedit_ai:
                   # names, and xml_retain only keeps a service in memory


def _file(*extensions):
    """An absolute path to an existing file with one of these extensions: its mark (size, date and, up to
    CONTENT_HASH_BYTES, its bytes; above that size and date, the accepted limit) is in every key that reads it. Only
    absolute: the folder a render runs in then changes nothing."""
    return ('file', frozenset(extensions))


UNDERSTOOD_ATTRIBUTES = {          # the attributes of the elements that carry no service
    # numbers read with a point (another locale reads every value another way); a version and a title are labels;
    # `producer` names Shotcut's bin, a label (the engine plays the last element, which must be the main timeline). No
    # `root`: files are named by absolute paths (_file), so a project that names another folder is outside
    'mlt': {'LC_NUMERIC': {'C'}, 'version': ANY, 'title': ANY, 'producer': ANY},
    # the picture's size, rate, scan and aspect: in every key and the picture digest (timeline.profile); exactly one
    'profile': {name: ANY for name in ('width', 'height', 'frame_rate_num', 'frame_rate_den', 'progressive',
                                       'colorspace', 'sample_aspect_num', 'sample_aspect_den', 'display_aspect_num',
                                       'display_aspect_den', 'description')},
    'track': {'producer': ANY, 'hide': ANY},       # what it plays and whether it draws: canon and the keys read both
    'entry': {'producer': ANY, 'in': ANY, 'out': ANY},     # the cut: canon's text and each item's place and digest
    'blank': {'length': ANY},                              # where the items fall
    'property': {'name': ANY},     # a value written as text only: not a `value` attribute, not nested XML
}
UNDERSTOOD_CHILDREN = {            # what each may hold
    'mlt': {'profile', 'producer', 'chain', 'playlist', 'tractor'},
    'profile': set(),
    'tractor': {'property', 'track', 'filter', 'transition'},   # and its Shotcut markers (_markers_outside)
    'track': set(),
    'playlist': {'property', 'entry', 'blank'},    # a track's own effects aren't
    'entry': set(),                # a cut's own effects aren't
    'blank': set(),
    'producer': {'property'},      # a colour, no effects
    'chain': {'property', 'filter'},       # no links
    'filter': {'property'},
    'transition': {'property'},
    'property': set(),             # nested XML is a value the engine writes out
}
_VIDEO = ('id', 'in', 'out')
# (element, its mlt_service or None): (where it may be: 'main' on the main timeline, 'chain' on a clip, None anywhere,
# its attributes, {property: ANY, LABEL, a set of the values allowed, or _file(...)})
UNDERSTOOD = {
    # the main timeline: Shotcut's marks (this is the timeline; the project folder setting; the sound channels)
    ('tractor', None): ('root', ('id', 'in', 'out', 'title'),
                        {'shotcut': LABEL, 'shotcut:projectAudioChannels': LABEL, 'shotcut:projectFolder': LABEL}),
    ('playlist', None): (None, ('id',), {'shotcut:audio': LABEL, 'shotcut:name': LABEL, 'shotcut:video': LABEL,
                                         'xml_retain': LABEL}),
    # one video, picture or sound file (avformat reads only its resource with these settings: no filter graph, look-up
    # table, codec or demuxer option is on the list)
    ('chain', 'avformat-novalidate'): (None, ('id', 'out'), {
        'mlt_service': ANY, 'resource': _file('.mov', '.mp4', '.mp3', '.wav'), 'audio_index': ANY, 'video_index': ANY,
        'eof': ANY, 'seekable': ANY, 'length': ANY, 'letitedit_ai:fx': LABEL, 'letitedit_ai:graphic': LABEL,
        'letitedit_ai:id': LABEL, 'letitedit_ai:sound_target': LABEL, 'shotcut:caption': LABEL}),
    # a colour from its resource (producer_colour.c reads no file)
    ('producer', 'color'): (None, _VIDEO, {
        'mlt_service': ANY, 'resource': ANY, 'aspect_ratio': ANY, 'eof': ANY, 'length': ANY, 'mlt_image_format': ANY,
        'set.test_audio': ANY, 'letitedit_ai:code_scene': LABEL, 'letitedit_ai:id': LABEL, 'shotcut:caption': LABEL}),
    # a size and place over a transparent colour (the background a colour, no file or other project)
    ('filter', 'affine'): ('chain', _VIDEO, {
        'mlt_service': ANY, 'background': {'color:#00000000'}, 'transition.distort': ANY, 'transition.fill': ANY,
        'transition.fix_rotate_x': ANY, 'transition.halign': ANY, 'transition.rect': ANY, 'transition.threads': ANY,
        'transition.valign': ANY, 'shotcut:animIn': LABEL, 'shotcut:animOut': LABEL, 'shotcut:filter': LABEL}),
    # a look-up table from one .cube file
    ('filter', 'avfilter.lut3d'): ('chain', _VIDEO, {
        'mlt_service': ANY, 'av.file': _file('.cube'), 'av.interp': ANY, 'letitedit_ai:grade': LABEL}),
    ('filter', 'invert'): ('chain', _VIDEO, {'mlt_service': ANY, 'letitedit:cutaway_negative': LABEL}),
    ('filter', 'lift_gamma_gain'): ('chain', _VIDEO, {
        'mlt_service': ANY, **{f'{part}_{channel}': ANY for part in ('lift', 'gamma', 'gain') for channel in 'rgb'},
        'letitedit_ai:role': LABEL, 'letitedit_ai:shot_match': LABEL, 'shotcut:filter_version': LABEL}),
    # runs frei0r.alphaspot (a shape from its ten numbered settings), never another effect
    ('filter', 'mask_start'): ('chain', _VIDEO, {
        'mlt_service': ANY, 'filter': {'frei0r.alphaspot'}, **{f'filter.{n}': ANY for n in range(10)},
        'letitedit_ai:lighting': LABEL}),
    # blends with frei0r.cairoblend, never another blend
    ('filter', 'mask_apply'): ('chain', _VIDEO, {
        'mlt_service': ANY, 'transition': {'frei0r.cairoblend'}, 'transition.threads': ANY}),
    ('filter', 'volume'): ('chain', _VIDEO, {      # sound only
        'mlt_service': ANY, 'channel_mask': ANY, 'gain': ANY, 'level': ANY, 'letitedit_ai:floor_db': LABEL,
        'shotcut:animIn': LABEL, 'shotcut:animOut': LABEL, 'shotcut:filter': LABEL}),
    ('filter', 'frei0r.premultiply'): ('main', ('id',), {
        'mlt_service': ANY, 'letitedit_ai:role': LABEL, 'shotcut:hidden': LABEL}),
    # the captions as data, inline only (no resource, window or switch): nothing on this list draws a feed (no subtitle
    # filter), so it adds nothing to a picture
    ('filter', 'subtitle_feed'): ('main', ('id',), {
        'mlt_service': ANY, 'feed': ANY, 'lang': ANY, 'text': ANY, 'shotcut:hidden': LABEL}),
    ('transition', 'frei0r.cairoblend'): ('main', ('id',), {
        'mlt_service': ANY, 'a_track': ANY, 'b_track': ANY, 'disable': ANY, 'threads': ANY, 'version': ANY}),
    ('transition', 'mix'): ('main', ('id',), {     # sound only
        'mlt_service': ANY, 'a_track': ANY, 'always_active': ANY, 'b_track': ANY, 'sum': ANY}),
}
# Shotcut's markers on the main timeline: <properties name="shotcut:markers"> of numbered <properties>, each only these
# text properties. The engine keeps them as labels; no service reads them
MARKER_PROPERTIES = frozenset({'text', 'start', 'end', 'color'})
OUTSIDE = 'outside:'           # the start of a frame key for frames an item outside the list shows in (_FrameKeys.key)


# How the engine's XML loader (modules/xml/producer_xml.c) binds one element to another as it reads the file, against
# how Timeline and these keys read it. Timeline looks every id up among the whole file's top-level elements (the last
# one with that id); the loader keeps one map, filled as it goes: a chain, playlist or tractor is registered when it
# starts, a producer when it ends, a later one with the same id replaces it for what follows, and an entry or a track
# takes whatever the map holds when the loader reaches it (an id not there yet gives no cut and no track). So reuse
# needs every reference to resolve the same way in both: each service id once, every entry and track pointing at a
# service that ended earlier in the file, of the kind Timeline expects. The rest of what binds at load time, and
# where the list stands on it, is in _bindings_outside.
REGISTERED = frozenset({'producer', 'chain', 'playlist', 'tractor'})     # what the loader puts in its id map
# the loader's own names in that map: <mlt>'s attributes and the folder files are found from
RESERVED_IDS = frozenset({'root', 'LC_NUMERIC', 'version', 'title', 'producer'})
# The numbers the key builder reads from a project (every other value is in the keys as its exact text), each in the
# one strict form the engine reads the same way (mlt_property.c): ASCII only, never normalised (Python's int() and \d
# take other scripts' digits, spaces, signs and underscores; the engine's strtol and atoi stop at the first byte that
# isn't an ASCII digit, and its isdigit is ASCII). Anything else is outside the list.
# - a count or a frame number (a time in frames, a transition's track): ASCII digits, at most 9 (the engine's long is
#   32 bits here, so a longer one would overflow there and not in Python)
_FRAMES_FORM = re.compile(r'[0-9]{1,9}', re.ASCII)
# - a clock as letitedit writes it, "HH:MM:SS.mmm" (the engine reads it as a clock only with a point; without one it
#   is a timecode, H:M:S:F)
_CLOCK_FORM = re.compile(r'([0-9]{1,4}):([0-9]{1,2}):([0-9]{1,2}\.[0-9]{1,6})', re.ASCII)
# - the profile's numbers: the engine reads them with strtol base 0 (on_start_profile), where a leading 0 is octal and
#   0x hex, so plain decimal without a leading zero
_PROFILE_FORM = re.compile(r'0|[1-9][0-9]{0,8}', re.ASCII)
PROFILE_NUMBERS = ('width', 'height', 'frame_rate_num', 'frame_rate_den', 'progressive', 'colorspace',
                   'sample_aspect_num', 'sample_aspect_den', 'display_aspect_num', 'display_aspect_den')
_LARGEST_POSITION = 2 ** 31 - 1      # mlt_position is a 32-bit int


def _engine_frames(text, fps):
    """A time value as the engine reads a position (mlt_property_atoi): plain ASCII digits (strtol), or a clock
    "HH:MM:SS.mmm" (floor of the hours' and the minutes' frames plus the seconds' rounded half to even, as
    time_clock_to_frames). None for any other form (a timecode without a point, a comma, hex, a sign, spaces, other
    scripts' digits, a number that doesn't fit a position): those are outside the list."""
    if not isinstance(text, str):
        return None
    if _FRAMES_FORM.fullmatch(text):
        return int(text)
    match = _CLOCK_FORM.fullmatch(text)
    if match is None:
        return None
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), float(match.group(3))
    frames = math.floor(fps * hours * 3600) + math.floor(fps * minutes * 60) + round(fps * seconds)
    return frames if 0 <= frames <= _LARGEST_POSITION else None


def _time_outside(name, text, fps):
    """Why a time value reads differently in the engine and in Timeline (timeline_model.clock_to_frames), or None."""
    import letitedit.timeline.timeline_model as timeline_model
    engine = _engine_frames(text, fps)
    try:
        ours = timeline_model.clock_to_frames(text, fps)
    except (ValueError, TypeError):
        ours = None
    if engine is None or ours != engine:
        return f'{name}={text[:24]} read another way by the engine'
    return None


def _bindings_outside(timeline):
    """Why the engine's loader would bind this file's parts differently from Timeline and these keys, or None. Checked
    once per file with the root (both picture_digest and _FrameKeys check the root). What binds at load time
    (producer_xml.c), and how each is held:
    - ids: one map filled in document order (above). Each service id once, none of the loader's own names
      (RESERVED_IDS), and every entry and track pointing at a service that ended before it, the same element Timeline
      finds: an entry at a clip (chain or producer), a track at a playlist, and a playlist on several tracks only
      when they hide the same (the loader writes a track's hide onto the playlist itself, so the tracks share it).
    - a cut's in and out: the engine reads a time its own way (_engine_frames) and clamps a cut to its clip's length;
      every in, out and length must read the same in both, and every entry must name both, inside its clip's length.
    - transitions' tracks: indexes into the tracks in document order (every track resolves, above): plain numbers
      below the number of tracks.
    - filters attach to the element around them, or to a track by a `track` setting: the list keeps each filter on a
      clip or the main timeline, with no `track` setting (UNDERSTOOD).
    - chains: a source made from mlt_service and resource, the chain's settings copied onto it; links: none on the
      list. mlt_service: trimmed by the engine, matched exactly by the list.
    - settings: an element's attributes and properties are one set of names in the engine, the last one written wins;
      no name appears twice in an element on the list (checked here), and no element on the list allows an attribute
      and a property of the same name.
    - profile and consumer: the loader reads every <profile>, <profileinfo> and <mlt> element's profile settings, even
      inside a value, and counts <consumer> elements; the list has one profile, no profile settings on <mlt>, no
      consumer and no nested XML. Any value starting glsl. or movit. switches the loader to a GPU consumer, and a
      DOCTYPE brings entities (the loader also fills them from the file's URL): neither is on the list."""
    cached = getattr(timeline, '_kit_bindings', False)
    if cached is not False:
        return cached
    reason = _bindings_reason(timeline)
    timeline._kit_bindings = reason
    return reason


def _bindings_reason(timeline):
    import letitedit.timeline.timeline_model as timeline_model
    try:
        raw = Path(timeline.path).read_text(encoding='utf-8-sig', errors='replace')
    except OSError:
        return 'the project file can\'t be read again'
    if '<!DOCTYPE' in raw or '<!ENTITY' in raw:
        return 'a DOCTYPE or entity declaration'
    # the loader looks at the values it decodes (every attribute value, every run of text), so a character reference
    # (&#103;lsl.) is read here decoded too
    decoded = [value for element in timeline.root.iter() for value in
               (*element.attrib.values(), element.text or '', element.tail or '')]
    if any('glsl.' in value or 'movit.' in value for value in [raw, *decoded]):
        return 'a glsl. or movit. value (the loader switches to a GPU consumer)'
    profile = timeline.root.find('profile')
    for name in PROFILE_NUMBERS:
        value = profile.get(name)
        if value is None:              # the engine keeps its starting profile's value; Timeline would assume one
            return f'a profile without its {name}'
        if value is not None and not _PROFILE_FORM.fullmatch(value):
            return f'the profile\'s {name}={value[:12]} read another way by the engine'
    if int(profile.get('frame_rate_num')) == 0 or int(profile.get('frame_rate_den')) == 0:
        return 'a profile without a frame rate'
    fps = timeline.fps
    order, ended, stack = [], {}, [(timeline.root, False)]
    while stack:                                      # document order: each element's start, and its end
        element, done = stack.pop()
        if done:
            ended[id(element)] = len(order)
            order.append(('end', element))
            continue
        order.append(('start', element))
        stack.append((element, True))
        stack.extend((child, False) for child in reversed(list(element)))
    registered, references, tracks_of = {}, [], collections.defaultdict(set)
    for position, (event, element) in enumerate(order):
        tag = element.tag
        if event == 'start':
            names = [prop.get('name') for prop in element if prop.tag == 'property']
            if len(names) != len(set(names)):
                return f'a setting named twice in <{tag}>'
            if tag == 'blank' and element.get('length') is None:
                return 'a gap without its length'           # the loader adds none; Timeline can't place what follows
            if tag in ('entry', 'track'):
                # what the loader's map holds now; it must have ended already (not this element's own parent)
                target_id = element.get('producer')
                target = registered.get(target_id)
                if target is not None and ended[id(target)] > position:
                    target = None
                references.append((element, target_id, target))
            for name in ('in', 'out', 'length'):
                if element.get(name) is not None:
                    reason = _time_outside(f'{tag}@{name}', element.get(name), fps)
                    if reason:
                        return reason
        registers = (event == 'start' and tag in ('chain', 'playlist', 'tractor')) or (
            event == 'end' and tag == 'producer')
        if registers and element.get('id') is not None:
            if element.get('id') in RESERVED_IDS:
                return f'the id {element.get("id")} is one of the loader\'s own names'
            if element.get('id') in registered:
                return f'the id {element.get("id")} used twice'
            registered[element.get('id')] = element
    count = len(timeline.main.findall('track'))
    for element, target_id, target in references:
        if target is None:
            return f'<{element.tag}> pointing at {target_id}, not defined before it'
        if target is not timeline.elements.get(target_id):
            return f'<{element.tag}> pointing at {target_id}, another element than Timeline finds'
        if element.tag == 'entry':
            if target.tag not in ('chain', 'producer'):
                return f'an entry pointing at a <{target.tag}>'
            length = timeline_model.props(target).get('length')
            if length is None or element.get('in') is None or element.get('out') is None:
                return 'an entry without its in and out, or on a clip without a length'
            if _time_outside('length', length, fps):
                return _time_outside(f'{target.tag} length', length, fps)
            first, last, frames = (_engine_frames(element.get('in'), fps), _engine_frames(element.get('out'), fps),
                                   _engine_frames(length, fps))
            if not first <= last < frames:
                return 'an entry outside its clip (the engine clamps it)'
        else:
            if target.tag != 'playlist':
                return f'a track pointing at a <{target.tag}>'
            tracks_of[target_id].add(element.get('hide'))
    for target_id, hides in tracks_of.items():
        if len(hides) > 1:
            return f'the playlist {target_id} on tracks hidden differently'
    entry_targets = {element.get('producer') for element, _, _ in references if element.tag == 'entry'}
    if entry_targets & set(tracks_of):
        return 'a playlist both on a track and in a cut'
    for transition in timeline.root.iter('transition'):
        properties = timeline_model.props(transition)
        for name in ('a_track', 'b_track'):
            # both written: the loader plants a missing one at 0, the keys read a missing b_track as 1
            value = properties.get(name)
            if value is None or not _FRAMES_FORM.fullmatch(value) or int(value) >= count:
                return f'a transition\'s {name}={str(value)[:12]}'
    return None


def _markers_outside(element):
    """Why a <properties> on the main timeline is anything but Shotcut's markers, or None."""
    if set(element.attrib) != {'name'} or element.get('name') != 'shotcut:markers':
        return 'properties other than shotcut:markers'
    for marker in element:
        if marker.tag != 'properties' or set(marker.attrib) != {'name'} or not str(marker.get('name')).isdigit():
            return 'a marker other than numbered properties'
        for prop in marker:
            if (prop.tag != 'property' or set(prop.attrib) != {'name'} or len(prop) or
                    prop.get('name') not in MARKER_PROPERTIES):
                return 'a marker holding something other than its text, start, end and colour'
    return None


def _value_outside(name, value, rule):
    if rule in (ANY, LABEL):
        return None
    if isinstance(rule, tuple) and rule[0] == 'file':
        try:
            path = Path(value)
            if path.is_absolute() and path.suffix.lower() in rule[1] and path.is_file():
                return None
        except (OSError, ValueError):
            pass
        return f'{name} not an absolute path to one existing {"/".join(sorted(rule[1]))} file'
    return None if value in rule else f'{name}={value[:40]}'


def _outside_element(element, timeline, folder):
    """Why this one element is outside the list (its kind, where it is, an attribute or its value, a child's kind, a
    property or its value, its property form), or None. `folder` is where the render runs (unused while every file is
    named by an absolute path; kept so the check and the keys read files from one place)."""
    import letitedit.timeline.timeline_model as timeline_model
    tag = element.tag
    parents = getattr(timeline, '_kit_parents', None)
    if parents is None:
        parents = timeline._kit_parents = {id(child): parent for parent in timeline.root.iter() for child in parent}
    if tag not in UNDERSTOOD_CHILDREN:
        return f'<{tag}>'
    if tag == 'mlt':
        if [child for child in element if child.tag != 'profile'][-1:] != [timeline.main]:
            return 'the engine plays another element than the main timeline'
        if len(element.findall('profile')) != 1:
            return 'not exactly one profile'
        reason = _bindings_outside(timeline)        # how the loader binds ids, times and tracks (above)
        if reason:
            return reason
    for child in element:
        if child.tag == 'properties' and element is timeline.main:
            reason = _markers_outside(child)
            if reason:
                return reason
            continue
        if child.tag not in UNDERSTOOD_CHILDREN[tag]:
            return f'<{child.tag}> in <{tag}>'
    if tag == 'property':
        if set(element.attrib) != {'name'}:
            return 'a property with attributes besides its name'
        return None
    if tag in UNDERSTOOD_ATTRIBUTES:
        allowed = UNDERSTOOD_ATTRIBUTES[tag]
        for name, value in element.attrib.items():
            if name not in allowed:
                return f'{tag}@{name}'
            if allowed[name] is not ANY and value not in allowed[name]:
                return f'{tag}@{name}={value}'
        return None
    properties = timeline_model.props(element)
    service = properties.get('mlt_service') if tag not in ('tractor', 'playlist') else None
    rule = UNDERSTOOD.get((tag, service))
    if rule is None:
        return f'{tag} {service}' if service else f'<{tag}>'
    where, attributes, allowed = rule
    parent = parents.get(id(element))
    if where == 'root' and element is not timeline.main:
        return 'a tractor besides the main timeline'
    if where == 'main' and parent is not timeline.main:
        return f'{service} away from the main timeline'
    if where == 'chain' and (parent is None or parent.tag != 'chain'):
        return f'{service} away from a clip'
    for name in element.attrib:
        if name not in attributes:
            return f'{tag}@{name}'
    for name, value in properties.items():
        if name not in allowed:
            return f'{service or tag} property {name}'
        reason = _value_outside(name, value, allowed[name])
        if reason:
            return f'{service or tag} {reason}'
    return None


def _outside(timeline, roots, folder, follow=True, known=None):
    """Why anything in or under `roots` is outside the list: every element, attribute and property, and, with
    `follow`, what each entry and track points at, at any depth (each element read once; no recursion, so a deep
    graph can't overflow). [] when all of it is understood. `known` keeps each element's own answer within a check."""
    known = {} if known is None else known
    reasons, seen, stack = [], set(), list(roots)
    while stack:
        element = stack.pop()
        if element is None:
            reasons.append('an entry or track pointing at nothing')
            continue
        if id(element) in seen:
            continue
        seen.add(id(element))
        if id(element) not in known:
            known[id(element)] = _outside_element(element, timeline, folder)
        if known[id(element)]:
            reasons.append(known[id(element)])
        if follow and element.tag in ('entry', 'track'):
            stack.append(timeline.elements.get(element.get('producer')))     # what it plays
        for child in element:
            if child.tag == 'properties' and element is timeline.main:
                continue                    # Shotcut's markers, checked whole with the main timeline
            stack.append(child)
    return reasons


def render_folder(timeline):
    """The folder the kit check's renders run in (_mode_files sets the project's own folder as their root): the one
    folder the list check, the keys and the picture digest read files from."""
    return str(Path(timeline.path).parent)


def outside_document(timeline, known=None):
    """Why anything in the project file is outside the list: [] when the whole-result receipt may be reused. `known`
    receives each element's own answer (for _files_in)."""
    return _outside(timeline, [timeline.root], render_folder(timeline), known=known)


def picture_digest(path):
    """Everything the main timeline draws with, as the engine reads it (the video's own effects and its blends with
    their in and out points, which the script leaves out, and every file the list accepted, by content when small),
    for the whole-result receipt. None when it can't be computed in full (the project can't be read, anything in it is
    outside the list (outside_document), a file it accepted can't be read now (Unreadable), or its text is
    unavailable: timeline_model.UNAVAILABLE): the receipt is then never reused."""
    try:
        import letitedit.review.checks as checks
        import letitedit.timeline.timeline_model as timeline_model
        timeline, _ = checks.resolve(path)
        known = {}
        if outside_document(timeline, known):
            return None
        folder = render_folder(timeline)
        files = {}
        _files_in(timeline, timeline.main, folder, files, known=known)
        text = timeline.canon(timeline.main)
        if text.startswith(timeline_model.UNAVAILABLE):
            return None
        return digest([text, sorted(files.items()), sorted(timeline.profile.items())])
    except Exception:  # noqa: BLE001 - not computed in full: measured again (RecursionError included)
        return None


def _stripped(element, attributes=(), properties=()):
    """A copy of element without the given attributes and properties (to fingerprint it without them)."""
    import xml.etree.ElementTree as ET
    out = ET.Element(element.tag, {k: v for k, v in element.attrib.items() if k not in attributes})
    out.extend(child for child in element if not (child.tag == 'property' and child.get('name') in properties))
    return out


# Effects and blends that draw the same on every frame of their life while their parameters are fixed: the engine's
# wrappers animate parameters (frei0r's helper, qtblend's rect and rotation) and pass the position or time on, but
# with every value a plain one the picture doesn't change along the life (frei0r's premultiply and cairoblend ignore
# the time they are given). So they count as static only when no value uses the engine's animation syntax: any "=" or
# ";" in a value (keyframes, with any easing letter) makes them move. Every other effect or blend may change over its
# life (brightness's start and end, a dissolve's progress) and is taken to move: a fingerprint that reuses less is
# better than one that reuses a stale result.
STATIC_SERVICES = frozenset({'frei0r.premultiply', 'frei0r.cairoblend', 'qtblend'})


def _window(element, fps):
    """(first, last) frame of an effect's or a blend's in and out points as the engine reads them: an out of 0 (or
    none) is open, last None; None when both are 0 or missing (it acts on every frame)."""
    import letitedit.timeline.timeline_model as timeline_model
    first = timeline_model.clock_to_frames(element.get('in'), fps) or 0
    last = timeline_model.clock_to_frames(element.get('out'), fps) or 0
    if first == 0 and last == 0:
        return None
    return first, (last or None)


def _timing(element, fps):
    """(window, static): an effect's or a blend's window (_window) and whether it draws the same at every point of its
    life (a STATIC_SERVICES one with nothing keyframed)."""
    import letitedit.timeline.timeline_model as timeline_model
    properties = timeline_model.props(element)
    static = (properties.get('mlt_service') in STATIC_SERVICES and
              not any('=' in str(value) or ';' in str(value) for value in properties.values()))
    return _window(element, fps), static


def _when(timing, frame, length, always=False):
    """What an effect or a blend adds to a frame's fingerprint: [0] outside its window; inside, [1] with the frames
    since its start and its length (its window's, or else what it lasts for, `length`) when it has a window or moves,
    since it can change along its life whether or not any value is keyframed; None for a static one with no window.
    always: a blend that acts outside its window too (its position still counts there)."""
    window, static = timing
    if window is None:
        return None if static else [1, frame, length]
    first, last = window
    if not always and (frame < first or (last is not None and frame > last)):
        return [0]
    return [1, frame - first, length if last is None else last - first]


def _plain_background(own, element, timeline):
    """How many frames a plain-colour background covers from the start, or None when it is anything more: a plain
    colour is one entry (no cuts, no gaps) of a colour source with no effects and no animated value, and no effects on
    the track itself. Several colours, gaps or anything else are described in full instead (fail closed)."""
    import letitedit.timeline.timeline_model as timeline_model
    if any(child.tag in ('filter', 'link', 'transition') for child in own):
        return None
    entries = [child for child in element if child.tag in ('entry', 'blank')]
    if len(entries) != 1 or entries[0].tag != 'entry':
        return None
    entry = entries[0]
    source = timeline.elements.get(entry.get('producer'))
    first = timeline_model.clock_to_frames(entry.get('in'), timeline.fps) or 0
    last = timeline_model.clock_to_frames(entry.get('out'), timeline.fps)
    if last is None and source is not None:
        last = timeline_model.clock_to_frames(source.get('out'), timeline.fps)
    if last is None or last < first:
        return None
    for source in [source]:
        if source is None or source.tag != 'producer':
            return None
        if any(child.tag not in ('property',) for child in source):
            return None
        properties = timeline_model.props(source)
        if properties.get('mlt_service') not in ('color', 'colour'):
            return None
        if any('=' in str(value) or ';' in str(value) for value in properties.values()):
            return None
    return last - first + 1


class _Track:
    """One picture track for the frame fingerprints: its own part (effects, whether it is the kit's), its items as
    (start, end, digest, moves), whether it draws on every frame (its own effects, or the background), its effects'
    timing (_timing, in their order) and its length."""

    def __init__(self, own, kit, items, always, moves, timings=(), length=None, cover=None):
        import bisect
        self.own, self.kit, self.items, self.always, self.moves = own, kit, items, always, moves
        self.timings, self.length, self.cover = list(timings), length, cover
        self.starts = [item[0] for item in items]
        self._bisect = bisect.bisect_right

    def at(self, frame):
        index = self._bisect(self.starts, frame) - 1
        if index >= 0 and self.items[index][0] <= frame < self.items[index][1]:
            return self.items[index]
        return None


class _FrameKeys:
    """Each frame's fingerprint (see PIECE_FORMAT above) and its kit items in the fingerprint's order, for one check
    of one timeline: key(frame) -> (fingerprint, [kit item ids]), or None where no kit item shows."""

    def __init__(self, timeline, placed, selected, base):
        import letitedit.timeline.timeline_model as timeline_model
        self.fps = fps = timeline.fps
        folder = render_folder(timeline)
        hashed = {}
        # set when any part can't be described in full (timeline_model.UNAVAILABLE): these keys then match nothing
        # and the check keeps none of its frames
        self.unavailable = False
        # reuse rests on the list of what is understood (UNDERSTOOD_*). Outside it in the project file's own parts, the
        # profile, the main timeline (its effects, blends and tracks) or a track's own parts: every frame is drawn and
        # none kept (unavailable). Outside it in an item (its cut and what it plays, at any depth): that item's frames
        # are drawn and not kept (outside_spans)
        known = {}
        mine = _outside_element(timeline.root, timeline, folder)
        self.outside = ([mine] if mine else []) + _outside(
            timeline, [timeline.root.find('profile'), timeline.main], folder, False, known)
        self.outside_spans = []

        def canon(element):
            text = timeline.canon(element)
            if text.startswith(timeline_model.UNAVAILABLE):
                self.unavailable = True
            return text

        def files_of(element):
            # the files the list accepted in it, read with the list check's own answers (known): one that can't be
            # read now turns these keys off (unavailable: every frame drawn, none kept), never a mark that may match
            files = {}
            try:
                _files_in(timeline, element, folder, files, hashed=hashed, known=known)
            except Unreadable:
                self.unavailable = True
                return [timeline_model.unavailable()]
            return sorted(files.items())

        def timings_of(element):
            return [_timing(child, fps) for child in element if child.tag == 'filter']

        # the video's own effects, each with its own timing and the files it reads (a look-up table, a mask), which its
        # properties alone don't give (a subtitle feed draws nothing itself: its burned cues are below)
        effects = [child for child in timeline.main.findall('filter')
                   if timeline_model.props(child).get('mlt_service') != 'subtitle_feed']
        self.master = [_timing(child, fps) for child in effects]
        self.frames = timeline.frames
        burned = {fp.get('feed', 'Subtitles') for fp in timeline.burn_filters}
        self.cues = [(feed, start * fps, end * fps, text) for feed, cues in sorted(timeline.subtitle_feeds.items())
                     if feed in burned for start, end, text in cues]
        self.head = [base, sorted(timeline.profile.items()),
                     [[sorted((k, v) for k, v in timeline_model.props(child).items()
                              if k not in timeline_model.VOLATILE), files_of(child)] for child in effects]]
        items_of = {track.index: track.items for track in timeline.tracks}
        self.tracks, names = {}, {}
        for index, track in enumerate(timeline.main.findall('track')):
            producer = track.get('producer')
            element = timeline.elements.get(producer)
            if element is None or track.get('hide') in ('video', 'both'):
                continue                                    # draws no picture
            attributes = sorted((k, v) for k, v in track.attrib.items() if k != 'producer')
            if producer == 'background' or element.tag != 'playlist':
                self.outside += _outside(timeline, [element], folder, True, known)
            else:
                # the playlist's own parts here; each cut with what it plays below, for its own frames
                mine = _outside_element(element, timeline, folder)
                self.outside += ([mine] if mine else []) + _outside(
                    timeline, [child for child in element if child.tag != 'entry'], folder, False, known)
                for item in items_of.get(index, []):
                    if _outside(timeline, [item.entry], folder, True, known):
                        self.outside_spans.append((item.start, item.end))
            if producer != 'background' and element.tag != 'playlist':
                # not a playlist (no Shotcut timeline makes one): all of it, at this frame's own position
                self.tracks[index] = _Track([attributes, canon(element), files_of(element)], index in selected, [],
                                            True, True)
                continue
            own = _stripped(element, ('in', 'out'))
            # Shotcut's own labels on a track (its name, lock, the sound or picture switch the editor shows) draw
            # nothing: the engine reads none of them. A caption track renamed when it is rebuilt keeps its frames
            own[:] = [child for child in element if child.tag not in ('entry', 'blank') and not
                      (child.tag == 'property' and str(child.get('name')).startswith('shotcut:'))]
            text = canon(own)
            if producer == 'background':
                cover = _plain_background(own, element, timeline)
                if cover is not None:
                    # under everything: one plain colour, without the length that follows the video's; each frame
                    # says whether the colour reaches it (it covers `cover` frames from the start)
                    source = timeline.elements.get(element.find('entry').get('producer'))
                    parts = [text, canon(_stripped(source, ('in', 'out'), ('length',)))]
                    moves = False
                else:
                    # anything more (several colours, cuts or gaps, an effect on the colour or the track, another kind
                    # of source, an animated value): all of it as the engine reads it, lengths and effects included, at
                    # this frame's own position
                    parts, moves = [canon(element)], True
                self.tracks[index] = _Track([attributes, parts, files_of(element)], index in selected, [], True,
                                            moves, timings_of(own), timeline.frames, cover)
                continue
            names[timeline_model.props(element).get('shotcut:name')] = index
            effects = any(child.tag == 'filter' for child in own)
            items = []
            for item in items_of.get(index, []):
                described = canon(item.elem)
                digest_ = hashlib.sha256(json.dumps(
                    [described, item.in_, item.out, files_of(item.elem)], default=str).encode('utf-8')).hexdigest()
                items.append((item.start, item.end, digest_, 'dynamictext' in described))
            # a track's own effects (outside the list, so these keys are off anyway) count as moving at every frame:
            # no reading of their values for keyframes, which the engine reads by its own grammar (is_keyframe_token)
            self.tracks[index] = _Track([attributes, text, files_of(own)], index in selected, items, effects,
                                        effects, timings_of(own),
                                        items[-1][1] if items else 0)
        self.links = []
        for transition in timeline.main.findall('transition'):
            properties = timeline_model.props(transition)
            if properties.get('mlt_service') == 'mix':
                continue                                    # sound only
            # without its in and out points (where it acts and its progress are given per frame below) and its
            # track numbers; with the files it reads (a dissolve's mask)
            text = [canon(_stripped(transition, ('in', 'out'), ('a_track', 'b_track'))), files_of(transition)]
            self.links.append((int(properties.get('a_track') or 0), int(properties.get('b_track') or 1), text,
                               properties.get('always_active') == '1', _timing(transition, fps)))
        self.kits = []
        for position, item in enumerate(placed):
            start, end = round(item['start'] * fps), round(item['end'] * fps)
            drawing = [item.get('family'), item.get('graphic'), item.get('blend'), item.get('family_blend'),
                       end - start]
            self.kits.append((names.get(item.get('track')), start, end, position, item['item'],
                              hashlib.sha256(json.dumps(drawing, sort_keys=True, default=str).encode('utf-8')).hexdigest(),
                              set(item.get('flash_frames', ()))))
        if self.outside:
            self.unavailable = True         # outside the list on the timeline itself: every frame drawn, none kept
        self.known = {}

    def key(self, frame):
        if frame in self.known:
            return self.known[frame]
        showing = sorted((kit for kit in self.kits if kit[1] <= frame < kit[2]),
                         key=lambda kit: (-1 if kit[0] is None else kit[0], kit[1], kit[3]))
        if not showing:
            self.known[frame] = None
            return None
        if any(first <= frame < end for first, end in self.outside_spans):
            # an item outside the list shows here: a key that matches nothing (drawn), never kept (OUTSIDE)
            import uuid
            self.known[frame] = OUTSIDE + uuid.uuid4().hex, [kit[4] for kit in showing]
            return self.known[frame]
        drawn = {}
        for index, track in self.tracks.items():
            item = track.at(frame)
            if item is not None or track.always:
                drawn[index] = item
        # a blend acts inside its window (open when its out is 0), or everywhere when it is always active
        links = [link for link in self.links
                 if (link[3] or _when(link[4], frame, self.frames) != [0]) and (link[1] in drawn or link[3])]
        order = sorted(set(drawn) | {link[0] for link in links} | {link[1] for link in links})
        rank = {index: n for n, index in enumerate(order)}
        rows = []
        for index in order:
            track = self.tracks.get(index)
            if track is None:
                rows.append([rank[index], 'no picture'])
                continue
            item = drawn.get(index)
            rows.append([rank[index], track.own, track.kit, frame if track.moves else None,
                         None if item is None else [item[2], frame - item[0], frame if item[3] else None],
                         [_when(timing, frame, track.length) for timing in track.timings],
                         None if track.cover is None else frame < track.cover])
        blends = [[rank[a], rank[b], text, _when(timing, frame, self.frames, always)]
                  for a, b, text, always, timing in links]
        kits = [[rank.get(kit[0]), kit[5], frame - kit[1], frame in kit[6]] for kit in showing]
        cues = [[feed, round(frame - start, 2), round(end - frame, 2), text] for feed, start, end, text in self.cues
                if start < frame + 1 and end > frame]
        master = [_when(timing, frame, self.frames) for timing in self.master]      # each with its own effect
        key = hashlib.sha256(json.dumps([self.head, master, rows, blends, kits, cues],
                                        default=str).encode('utf-8')).hexdigest()[:40]
        self.known[frame] = key, [kit[4] for kit in showing]
        return self.known[frame]


class _KeptFrames:
    """Each frame's result beside the project (graphic-kit-pieces.json) under its fingerprint (_FrameKeys), the kit
    items named by their place in the fingerprint's order: [visible, {place: [fully on, near invisible]}, overlap,
    no face]. Written during a check (at most every SAVE_S, so a check cut short keeps what it drew) and at its end,
    with the frames it used first and up to FRAMES_KEPT in all."""

    SAVE_S = 20.0

    def __init__(self, path):
        import time
        self.path, self.used, self.keys, self.saved = Path(path), {}, None, time.monotonic()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            # kept only while every font file their drawings may have used has the same bytes
            usable = data.get('format') == PIECE_FORMAT and _fonts_unchanged(data.get('fonts'))
            self.known = data['frames'] if usable else {}
            self.fonts = data['fonts'] if usable else {}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.known, self.fonts = {}, {}

    def bind(self, keys):
        self.keys = keys

    def lookup(self, span):
        """The kept results of [a, b)'s frames ({frame: result}) and the frames to draw (a kit item shows, none kept)."""
        have, draw = {}, []
        for frame in range(*span):
            found = self.keys.key(frame)
            if found is None:
                continue
            key, ids = found
            kept = self.known.get(key)
            try:
                visible, inversion, overlap, unknown = kept
                have[frame] = {'visible': [ids[place] for place in visible],
                               'inversion': {ids[int(place)]: list(counts) for place, counts in inversion.items()},
                               'overlap': bool(overlap), 'unknown': bool(unknown)}
                self.used[key] = kept
            except (TypeError, ValueError, IndexError, KeyError):
                draw.append(frame)
        return have, draw

    def put(self, frames):
        import time
        for frame, result in frames.items():
            key, ids = self.keys.key(frame)
            if key.startswith(OUTSIDE):
                continue                    # drawn by something outside the list: never kept
            place = {name: n for n, name in enumerate(ids)}
            self.used[key] = [sorted(place[name] for name in result['visible']),
                              {str(place[name]): list(counts) for name, counts in result['inversion'].items()},
                              int(result['overlap']), int(result['unknown'])]
        if time.monotonic() - self.saved >= self.SAVE_S:
            self.save()

    def save(self):
        import time
        # this check's frames first (the latest FRAMES_KEPT when it used more), then earlier checks' up to the limit
        frames = dict(list(self.used.items())[-FRAMES_KEPT:])
        for key, kept in self.known.items():
            if len(frames) >= FRAMES_KEPT:
                break
            frames.setdefault(key, kept)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            self.fonts = _fonts_used(self.fonts)
            if not _fonts_complete(self.fonts):
                # a font a drawing may have used can't be read: these results rest on it, so none is kept (the store
                # already there stays as it was, still checked against its own fonts when read)
                self.saved = time.monotonic()
                return
            temporary.write_text(json.dumps({'format': PIECE_FORMAT, 'frames': frames, 'fonts': self.fonts},
                                            separators=(',', ':')), encoding='utf-8')
            temporary.replace(self.path)
        except OSError:
            pass                 # not kept: the next check draws these frames again
        self.saved = time.monotonic()


def _runs(frames, join):
    """Frames to draw (in order) as runs [a, b), a run going on over gaps of up to `join` frames."""
    runs = []
    for frame in frames:
        if runs and frame - runs[-1][1] <= join:
            runs[-1][1] = frame + 1
        else:
            runs.append([frame, frame + 1])
    return [tuple(run) for run in runs]


class _MemoryWatch:
    """While a turn's engine renders run: the memory the PC can promise, read every MEMORY_POLL_S. Under floor_gb the
    renders are stopped at once (they are what the check added), so the PC never runs out because of them."""

    def __init__(self, streams, floor_gb):
        import threading
        self.streams, self.floor, self.tripped = streams, floor_gb, None
        self.lowest = memory_room.memory_gb()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, name='kit-memory', daemon=True)
        self.thread.start()

    def _watch(self):
        while not self.stop.wait(MEMORY_POLL_S):
            free = memory_room.memory_gb()[1]
            if free is None:
                continue
            self.lowest = free if self.lowest is None else min(self.lowest, free)
            if free < self.floor:
                self.tripped = free
                for stream in self.streams:
                    stream.kill()
                return

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)


class _Drawings:
    """Each kit item's drawings frame by frame, started when the item first shows and let go after its last frame, so
    only the items on screen hold a picture. Asked for a frame before the one it is at (a piece drawn again), an item
    starts over from its first frame and draws its way up to it."""

    def __init__(self, width, height, fps):
        self.width, self.height, self.fps, self.live = width, height, fps, {}

    def _start(self, item):
        import itertools
        import letitedit.pictures.graphics as graphics
        import letitedit.looks.style_pack as style_pack
        drawn = graphics.draw_frames(item['graphic'], style_pack.load(), self.width, self.height, self.fps)
        return iter(drawn) if item['graphic']['params'].get('animated', True) else itertools.repeat(next(drawn))

    def get(self, item, frame):
        state = self.live.get(item['item'])
        if state is None or state[1] > frame:
            state = self.live[item['item']] = [self._start(item), round(item['start'] * self.fps)]
        try:
            while state[1] <= frame:
                _, drawing = next(state[0])
                state[1] += 1
        except StopIteration:
            raise ValueError('kit duration and rendered interval disagree') from None
        if state[1] >= round(item['end'] * self.fps):
            del self.live[item['item']]          # its last frame: nothing more is drawn for it
        return drawing


# T246: the two per-frame masks in 8-bit arithmetic (OpenCV), 13 times faster than in 16-bit numpy (about 5 ms against
# 70 a 1080x1920 frame) with exactly the same masks: every pair of 8-bit values gives the same answer
# (test_graphic_kit_fast). Ink is where the kit over white and over black differ by under 255 on every channel (a
# negative difference counts as 0 either way); the finished picture differs from the clean one where some channel
# differs by 4 or more.
def _channels_max(picture):
    import cv2
    blue, green, red = cv2.split(picture)
    return cv2.max(cv2.max(blue, green), red)


def _ink(white, black):
    import cv2
    return _channels_max(cv2.subtract(white, black)) < 255


def _delta(composite, background):
    import cv2
    return _channels_max(cv2.absdiff(composite, background)) >= 4


def _pack(mask):
    import zlib
    import numpy as np
    return zlib.compress(np.packbits(mask).tobytes(), 1)


def _unpack(data, shape):
    import zlib
    import numpy as np
    bits = np.unpackbits(np.frombuffer(zlib.decompress(data), np.uint8), count=shape[0] * shape[1])
    return bits.reshape(shape).astype(bool)


def _count_inversion(item, frame, alpha, background, counts):
    """For a piece of a blend family: one more measured frame when its letters are fully on (opaque glyph cores; a fade
    or a two-frame negative flash is left out), and one more near-invisible frame when inverted letters there would
    have under NEAR_INVISIBLE median contrast with the picture under them. counts[item] = [frames, near invisible]."""
    if not item.get('family_blend') or frame in item.get('flash_frames', ()):
        return
    ratio = inverted_contrast(background, alpha >= 230)
    if ratio is None:
        return
    row = counts.setdefault(item['item'], [0, 0])
    row[0] += 1
    row[1] += ratio < NEAR_INVISIBLE


def inversion_rows(placed, records):
    """The 8 Nov rule per piece of a blend family: its letters stay inverted unless they are near invisible on more
    than half of their measured frames, then that whole piece is plain white. Returns (rows, findings)."""
    rows, findings = [], []
    for item in placed:
        if not item.get('family_blend'):
            continue
        frames, near = records.get(item['item'], {}).get('inversion', [0, 0])
        choose = None if not frames else 'normal' if near / frames > .5 else item['family_blend']
        rows.append({'item': item['item'], 'family': item['family'], 'placed': item['blend'], 'choose': choose,
                     'fully_on_frames': frames, 'near_invisible_frames': near,
                     'near_invisible_share': round(near / frames, 3) if frames else None})
        if choose is None:
            findings.append({'item': item['item'], 'problem': 'inverted letters not measured: no fully-on frame'})
        elif choose != item['blend']:
            edit = ({'op': 'set', 'id': item['item'], 'effects': None} if choose == 'normal' else
                    {'op': 'effects', 'id': item['item'],
                     'effects': [{'filter': 'cairoblend_mode', 'params': {'mode': choose}}]})
            findings.append({'item': item['item'], 'edit': edit, 'problem': (
                f'inverted letters near invisible on {near} of {frames} fully-on frames: this piece is plain white'
                if choose == 'normal' else
                f'plain white letters, but inverted ones are near invisible on only {near} of {frames} fully-on '
                'frames: this piece inverts with the picture')})
    return rows, findings


def _alpha(drawing, held, name):
    """A drawing's alpha and its mask; a held drawing (the same picture as the frame before) reuses them."""
    import numpy as np
    known = held.get(name) if held is not None else None
    if known is not None and known[0] is drawing:
        return known[1], known[2]
    alpha = np.asarray(drawing.getchannel('A'))
    mask = alpha > 0
    if held is not None:
        held[name] = (drawing, alpha, mask)
    return alpha, mask


_finder = []


def _face_finder():
    """T246: one helper thread that finds each frame's faces (OpenCV lets go of Python while it looks) while the check
    draws the kit items and compares them: the same detector, one frame at a time, so the same boxes."""
    import concurrent.futures
    if not _finder:
        _finder.append(concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix='kit-faces'))
    return _finder[0]


def _judge(frame, ink, delta, background, items, drawings, out, faces=None, held=None):
    """One frame where kit items show: which of them show in the finished picture, and whether the kit's ink touches a
    face found on the picture without the kit. faces: the face boxes being found meanwhile (a future), else found
    here; held: each item's last alpha (_alpha)."""
    import numpy as np
    height, width = ink.shape
    for item in items:
        alpha, mask = _alpha(drawings.get(item, frame), held, item['item'])
        if np.any(mask & ink & delta):
            out['visible'][item['item']] = out['visible'].get(item['item'], 0) + 1
        _count_inversion(item, frame, alpha, background, out.setdefault('inversion', {}))
    boxes = detect_faces(background) if faces is None else faces.result()
    if not boxes:
        out['unknown'].append(frame)
    if any(np.any(ink[max(0, y0):min(height, y1), max(0, x0):min(width, x1)]) for x0, y0, x1, y1 in boxes):
        out['overlap'].append(frame)


def _piece(span, plan, files, timeline, folder, export, placed, drawings, deadline, record=False):
    """Frames a..b-1 checked with the renders in `plan` (turns, each a list of modes rendered at once). With two turns
    the first keeps each frame's ink (packed, compressed) for the second. Returns what it found (record: also each
    frame's own result, under 'frames'); raises ShortOfMemory when the memory the PC can promise fell under the
    reserve while they ran (they were stopped)."""
    import time
    a, b = span
    fps = timeline.fps
    shape = (timeline.profile['height'], timeline.profile['width'])
    out = {'visible': {}, 'active': 0, 'overlap': [], 'unknown': [], 'lowest_gb': None, 'inversion': {}}
    frames = {} if record else None
    showing = {frame: [item for item in placed if round(item['start'] * fps) <= frame < round(item['end'] * fps)]
               for frame in range(a, b)}
    inks, held = {}, {}
    import concurrent.futures
    finder = _face_finder()
    for number, turn in enumerate(plan):
        judging = number == len(plan) - 1
        engine, watch = {}, None
        try:
            for mode in turn:
                engine[mode] = _EngineFrames(files[mode], a, b, timeline, folder)
            watch = _MemoryWatch(list(engine.values()), memory_room.RESERVE_GB)
            streams = dict(engine)
            if export and 'background' in turn:
                export.seek(a)
                streams['composite'] = export
            for frame in range(a, b):
                if time.monotonic() > deadline:
                    raise TimeoutError('kit check ran past two hours')
                pictures = {name: stream.read() for name, stream in streams.items()}
                if any(picture.shape[:2] != shape for picture in pictures.values()):
                    raise ValueError('render dimensions differ from project')
                if not showing[frame]:
                    continue
                if 'white' in pictures:
                    ink = _ink(pictures['white'], pictures['black'])
                    if not judging:
                        inks[frame] = _pack(ink)
                        continue
                else:
                    ink = _unpack(inks.pop(frame), shape)
                out['active'] += 1
                faces = finder.submit(detect_faces, pictures['background'])
                one = {'visible': {}, 'overlap': [], 'unknown': [], 'inversion': {}}
                try:
                    _judge(frame, ink, _delta(pictures['composite'], pictures['background']), pictures['background'],
                           showing[frame], drawings, one, faces, held)
                finally:
                    faces.cancel()
                    concurrent.futures.wait([faces])
                _add_frame(out, frame, one)
                if frames is not None:
                    frames[frame] = {'visible': sorted(one['visible']), 'inversion': one['inversion'],
                                     'overlap': bool(one['overlap']), 'unknown': bool(one['unknown'])}
            for stream in engine.values():
                stream.finish(deadline)
        except Exception as error:
            if watch is not None and watch.tripped is not None:
                raise ShortOfMemory(
                    f"the memory the PC can promise fell to {watch.tripped:.1f} GB while {len(engine)} of the check's "
                    f'renders ran (under the {memory_room.RESERVE_GB:g} GB kept for other programs), so they were '
                    'stopped') from error
            raise
        finally:
            if watch is not None:
                watch.close()
                if watch.lowest is not None:
                    out['lowest_gb'] = round(watch.lowest if out['lowest_gb'] is None else
                                             min(out['lowest_gb'], watch.lowest), 2)
            for stream in engine.values():
                stream.close()
    if frames is not None:
        out['frames'] = frames
    return out


def _add_frame(out, frame, one):
    """One judged frame's findings added to `out` (visible counts, inversion counts, overlap and no-face frames)."""
    for name in one['visible']:
        out['visible'][name] = out['visible'].get(name, 0) + 1
    for name, (fully_on, near) in one['inversion'].items():
        row = out['inversion'].setdefault(name, [0, 0])
        row[0], row[1] = row[0] + fully_on, row[1] + near
    if one['overlap']:
        out['overlap'].append(frame)
    if one['unknown']:
        out['unknown'].append(frame)


def _plan_for(modes, split):
    """The turns for the next piece, from the memory the PC can promise now. When not even one pair fits, letitedit's
    idle model helpers end first, then it waits (at most MEMORY_WAIT_S) for memory; still none: NoRoom, said plainly.
    Returns (turns, the memory room's report or None)."""
    import time
    plan = turns(modes, memory_room.memory_gb()[1], split)
    if plan:
        return plan, None
    need = _need(turns(modes, None, True), memory_room.RESERVE_GB)
    room = memory_room.make_room(need, 'Look kit every-frame check')
    wait_s = _WAIT_S.get()
    wait_s = MEMORY_WAIT_S if wait_s is None else wait_s
    t0 = time.monotonic()
    while True:
        free = memory_room.memory_gb()[1]
        plan = turns(modes, free, split)
        if plan:
            return plan, room
        if time.monotonic() - t0 >= wait_s:
            raise NoRoom(f"the PC can promise {free:.1f} GB of memory and two of the check's renders at a time need "
                         f'about {need:.1f} GB ({memory_room.RESERVE_GB:g} GB of it kept for other programs); it waited '
                         f'{wait_s / 60:g} min and none was freed, so the check was not run; it is measured '
                         'again next time')
        time.sleep(min(5.0, max(.1, wait_s / 10)))


def _measure_streamed(path, script, placed, video=None, kept=None):
    """Every frame where a kit item is on screen, at native size and rate: the kit's ink (the kit tracks over black and
    over white), whether it shows in the finished picture, and whether it touches a face found on the picture without
    the kit. Only the stretches with kit items are rendered, in pieces, each mode straight from the export engine into
    memory, as many at once as the memory the PC can promise holds; `video` (a render of this exact timeline at native
    size) stands in for the composite."""
    import tempfile
    import time
    import xml.etree.ElementTree as ET
    import letitedit.review.checks as checks
    import cv2
    import letitedit.timeline.timeline_model as timeline_model
    if not checks.YUNET.is_file():
        raise ValueError('local face model missing; no download attempted')
    timeline, path = checks.resolve(path)
    width, height = timeline.profile['width'], timeline.profile['height']
    cv2.setNumThreads(4)
    names = {item['track'] for item in placed}
    records = {item['item']: {'visible_frames': 0, 'fps': timeline.fps} for item in placed}
    tree = ET.parse(path).getroot()
    tractors = tree.findall('tractor')
    main = next((element for element in reversed(tractors) if timeline_model.props(element).get('shotcut') == '1'), tractors[-1])
    selected_ids = {element.get('id') for element in tree.findall('playlist') if timeline_model.props(element).get('shotcut:name') in names}
    selected = {index for index, track in enumerate(main.findall('track')) if track.get('producer') in selected_ids}
    if len(selected) != len(names):
        raise ValueError('kit track routing could not be resolved')
    checks.CACHE.mkdir(parents=True, exist_ok=True)
    spans = stretches(placed, timeline.fps, timeline.frames)
    deadline = time.monotonic() + 7200
    drawings = _Drawings(width, height, timeline.fps)
    modes = [mode for mode in MODES if not (mode == 'composite' and video)]
    parts = pieces(spans, timeline.fps)
    store = None
    if kept:
        store, base = kept
        try:
            keys = _FrameKeys(timeline, placed, selected, base)
            store.bind(keys)
            if keys.unavailable:
                store = None        # part of what draws these frames can't be described in full: all drawn, none kept
        except RecursionError:
            store = None            # what draws these frames can't be described in full: every frame drawn, none kept
    with tempfile.TemporaryDirectory(prefix='look-kit-', dir=checks.CACHE) as folder:
        files = _mode_files(tree, path, main, selected, folder)
        export = _FileFrames(video, timeline) if video else None
        try:
            found = _check_pieces(parts, timeline.fps, modes, lambda span, plan: _piece(
                span, plan, files, timeline, folder, export, placed, drawings, deadline, record=store is not None),
                store)
        finally:
            if export:
                export.close()
            if store is not None:
                store.save()
    for name, frames in found['visible'].items():
        records[name]['visible_frames'] += frames
    for name, counts in found.get('inversion', {}).items():
        records[name]['inversion'] = counts
    return {'items': records, 'seconds': timeline.frames / timeline.fps, 'checked_frames': timeline.frames,
            'active_frames': found['active'], 'rendered_frames': found['rendered'],
            'stretches': [list(span) for span in spans],
            'face_overlap_frames': found['overlap'], 'missing_face_frames': found['unknown'],
            'render_size': [width, height],
            'rendered_by': 'melt; native size/rate; every frame where a kit item is on screen (only those stretches '
                           'rendered, in pieces, straight into memory, as many renders at once as the memory free to '
                           'promise holds), clean-picture YuNet faces',
            'renders': found['renders']}


def _check_pieces(spans, fps, modes, run, kept=None):
    """Each piece checked by run(span, turns) -> what _piece found, with the turns the memory allows (_plan_for). A
    piece whose renders were stopped for memory is checked again a pair at a time, and the rest of the check stays at a
    pair; stopped twice that way, ShortOfMemory. kept (a bound _KeptFrames): each frame's kept result is used instead
    of drawing it, the other frames are drawn in runs (_runs; run then gives each frame's result) and kept. Returns
    the pieces' findings added up, in frame order, and 'renders' (how the renders ran, what was reused and drawn, the
    lowest memory free to promise seen, the memory notes)."""
    total = {'visible': {}, 'active': 0, 'rendered': 0, 'overlap': [], 'unknown': [], 'inversion': {}}
    used, notes, lowest, split = {}, [], None, False
    reused = {'pieces': 0, 'frames': 0}
    drawn = {'runs': 0, 'frames': 0}
    for span in spans:
        have, parts = None, [span]
        if kept is not None:
            have, draw = kept.lookup(span)
            parts = _runs(draw, round(RUN_JOIN_S * fps))
            reused['pieces'] += not parts
        fresh = {}
        for part in parts:
            trips = 0
            while True:
                plan, room = _plan_for(modes, split)
                if room and room.get('note'):
                    notes.append(room['note'])
                try:
                    found = run(part, plan)
                    key = ' + '.join(', '.join(turn) for turn in plan)
                    used[key] = used.get(key, 0) + 1
                    break
                except ShortOfMemory as short:
                    notes.append(f'{part[0] / fps:.1f}-{part[1] / fps:.1f} s: {short}')
                    trips += split
                    if trips > 1:
                        raise ShortOfMemory(f'{short}, twice with two renders at a time; it is measured again next '
                                            'time') from None
                    split = True            # the rest of the check: a pair of renders at a time
            drawn['runs'] += 1
            drawn['frames'] += part[1] - part[0]
            if found.get('lowest_gb') is not None:
                lowest = found['lowest_gb'] if lowest is None else min(lowest, found['lowest_gb'])
            if kept is not None:
                kept.put(found['frames'])
                fresh.update(found['frames'])
                continue
            for name, frames in found['visible'].items():
                total['visible'][name] = total['visible'].get(name, 0) + frames
            for name, (frames, near) in (found.get('inversion') or {}).items():
                row = total['inversion'].setdefault(name, [0, 0])
                row[0], row[1] = row[0] + frames, row[1] + near
            total['active'] += found['active']
            total['overlap'].extend(found['overlap'])
            total['unknown'].extend(found['unknown'])
        if kept is not None:
            results = {**have, **fresh}
            reused['frames'] += len(set(have) - set(fresh))
            for frame in sorted(results):
                total['active'] += 1
                _add_frame(total, frame, results[frame])
        total['rendered'] += span[1] - span[0]
    total['renders'] = {'pieces': len(spans), 'turns': used, 'lowest_free_gb': lowest}
    if reused['frames']:
        total['renders']['reused'] = {**reused, 'note': 'kept from an earlier check: nothing that draws these '
                                                        'frames changed'}
        total['renders']['drawn'] = drawn
    if notes:
        total['renders']['memory'] = notes[-6:]
    return total


_detectors = {}


def detect_faces(frame):
    import cv2
    import letitedit.review.checks as checks
    height, width = frame.shape[:2]
    scale = min(1., 960 / width)
    small = cv2.resize(frame, (round(width * scale), round(height * scale)))
    key = (str(checks.YUNET), small.shape[1], small.shape[0])
    if key not in _detectors:
        _detectors[key] = cv2.FaceDetectorYN.create(str(checks.YUNET), '', (small.shape[1], small.shape[0]), .75, .3, 20)
    detector = _detectors[key]
    _, rows = detector.detect(small)
    return [] if rows is None else [(max(0, math.floor(row[0] / scale)), max(0, math.floor(row[1] / scale)),
                                     min(width, math.ceil((row[0] + row[2]) / scale)),
                                     min(height, math.ceil((row[1] + row[3]) / scale))) for row in rows]
