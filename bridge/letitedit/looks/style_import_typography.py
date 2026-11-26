"""Private native-resolution text evidence; shape fits are not font identification."""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

import cv2
import numpy as np


VERSION = 1


def native_inventory(video, folder, band=(0, 0.43, 1, 0.57), start_s=0, end_s=None):
    import hashlib
    import json
    from PIL import Image, ImageDraw
    if not isinstance(band, (list, tuple)) or len(band) != 4 or any(type(edge) not in (int, float) or not math.isfinite(edge) for edge in band) or not (0 <= band[0] < band[2] <= 1 and 0 <= band[1] < band[3] <= 1):
        raise ValueError('native typography band needs ordered frame fractions')
    if type(start_s) not in (int, float) or not math.isfinite(start_s) or start_s < 0 or (end_s is not None and (type(end_s) not in (int, float) or not math.isfinite(end_s) or end_s <= start_s)):
        raise ValueError('native typography range needs finite ordered seconds')
    digest = hashlib.sha256()
    with Path(video).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not capture.isOpened() or fps <= 0:
        capture.release()
        raise ValueError('cannot decode native typography source')
    source_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    first = max(0, math.floor(start_s * fps))
    last = source_frames if end_s is None else min(source_frames, math.ceil(end_s * fps))
    if first >= last:
        capture.release()
        raise ValueError('native typography range is empty')
    band_hash = hashlib.sha256(json.dumps(list(band)).encode('utf-8')).hexdigest()[:12]
    destination = Path(folder) / 'native-type-private' / f'{source_hash[:16]}-{band_hash}-{first:05d}-{last:05d}'
    destination.mkdir(parents=True, exist_ok=True)
    records, pages, tiles = [], [], []
    previous = None

    def flush():
        if not tiles:
            return
        tile_width, tile_height = tiles[0].size
        page = Image.new('RGB', (tile_width * 6, tile_height * math.ceil(len(tiles) / 6)), '#171717')
        for index, tile in enumerate(tiles):
            page.paste(tile, ((index % 6) * tile_width, (index // 6) * tile_height))
        path = destination / f'page-{records[len(records) - len(tiles)]["frame"]:05d}.jpg'
        page.save(path, quality=94)
        pages.append(str(path.resolve()))
        tiles.clear()

    try:
        for frame_index in range(last):
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f'native typography incomplete decode at frame {frame_index}; expected {last}')
            if frame_index < first:
                continue
            image, bounds = crop(frame, band)
            path = destination / f'f-{frame_index:05d}.png'
            if not cv2.imwrite(str(path), image):
                raise OSError(f'cannot write typography crop {path}')
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            delta = None if previous is None else round(float(np.abs(gray.astype(np.int16) - previous).mean()), 4)
            previous = gray.astype(np.int16)
            records.append({'frame': frame_index, 't': frame_index / fps, 'path': str(path.resolve()),
                            'crop_px': bounds, 'mean_delta': delta})
            picture = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            picture.thumbnail((360, 160))
            tile = Image.new('RGB', (360, picture.height + 22), '#171717')
            ImageDraw.Draw(tile).text((5, 3), f'{frame_index} / {frame_index / fps:.4f}s', fill='white')
            tile.paste(picture, (0, 22))
            tiles.append(tile)
            if len(tiles) == 60:
                flush()
        flush()
    finally:
        capture.release()
    report = {'version': 1, 'source_sha256': source_hash, 'fps': fps, 'band': band,
              'source_frames': source_frames, 'decoded_frames': len(records), 'range_frames': [first, last],
              'frames': records, 'pages': pages,
              'limitations': ['Every frame in the requested band is retained at native resolution, not OCR or a font/easing verdict.',
                              'Contact sheets are reduced for browsing; inspect native crops for exact boundaries.',
                              'Background motion contributes to mean_delta; it is not a text-onset detector.',
                              'Text outside the chosen band is not inventoried. No automatic role exclusions.']}
    report_path = destination / f'inventory-{first:05d}-{last:05d}.json'
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {key: value for key, value in report.items() if key != 'frames'} | {'report': str(report_path.resolve())}


def learning_evidence(report):
    evidence = report.get('typography') or {}
    events = evidence.get('events') or []
    return {'status': 'available' if events else 'unmeasured',
            'coverage': evidence.get('coverage'), 'fps': evidence.get('fps'),
            'resolution': evidence.get('resolution'),
             'error': evidence.get('error'), 'skipped': evidence.get('skipped', False),
             'partial': evidence.get('partial', False), 'limitations': evidence.get('limitations', []),
            'native_inventory': {key: value for key, value in (evidence.get('native_inventory') or {}).items()
                                 if key in ('report', 'source_sha256', 'fps', 'band', 'source_frames', 'decoded_frames', 'range_frames', 'limitations', 'error')},
            'events': [{'id': event['id'], 'role': event.get('role'),
                        'reading_status': event.get('reading_status', 'unverified'),
                        'hold': (event.get('phases') or {}).get('hold'),
                        'dense_frames': len(event.get('dense') or []),
                        'words': [{'text': word['text'], 'box': word.get('box'),
                                   'font_fit': word.get('font_fit'), 'font_sheet': word.get('font_sheet')}
                                  for word in (event.get('words') or [])[:8]]}
                       for event in events[:8]],
            'font_styles': _styles_evidence(evidence.get('styles')),
            'preview_events': min(8, len(events)), 'total_events': len(events),
            'notice': 'Bounded preview only; inspect the full report and native crops. '
                      'Roles, OCR and font fits are unverified estimates, not a type system. '
                      'No easing, mixed-font or per-word animation match is established.'}


def _styles_evidence(styles):
    """A bounded view of font_styles' answer for Learn: each style's family top 3 (or not sure, with why), weight,
    lean, case, treatment and a few samples."""
    if not styles:
        return {'status': 'unmeasured'}
    if styles.get('error'):
        return {'status': 'error', 'error': styles['error']}
    keep = ('id', 'start_s', 'end_s', 'kind', 'italic', 'weight', 'weight_class', 'case', 'treatment', 'observations')
    return {'status': 'available', 'checked': styles.get('checked'), 'limitations': styles.get('limitations'),
            'styles': [{**{key: style.get(key) for key in keep},
                        'family': {key: style['family'].get(key) for key in ('status', 'top', 'why_not_sure')},
                        'samples': [sample['text'] for sample in style.get('samples') or []][:5]}
                       for style in (styles.get('styles') or [])[:12]],
            'too_brief': len(styles.get('too_brief') or [])}


def sample_times(event, duration, fps=15):
    if not 10 <= fps <= 30:
        raise ValueError('typography fps must be 10-30')
    start, end = float(event['t']), min(duration, float(event['end']))
    hold = min(end - 0.001, max(start, float(event.get('best_t', (start + end) / 2))))
    times = {round(max(0, min(duration - 0.001, hold)), 4)}
    for boundary in (start, end):
        times.update(round(max(0, min(duration - 0.001, boundary + offset / fps)), 4)
                     for offset in range(-2, 6))
    return sorted(times)


def crop(frame, box, pad=0):
    height, width = frame.shape[:2]
    left, top, right, bottom = box
    bounds = (max(0, int((left - pad) * width)), max(0, int((top - pad) * height)),
              min(width, math.ceil((right + pad) * width)), min(height, math.ceil((bottom + pad) * height)))
    return frame[bounds[1]:bounds[3], bounds[0]:bounds[2]], bounds


def mask_measure(image):
    import letitedit.looks.style_import_text as text
    mask, _ = text._glyph_mask(image)
    if mask is None:
        return {'ink_px': 0, 'box_px': None, 'fill': None}
    rows, columns = np.where(mask > 0)
    colors = image[mask > 0][:, ::-1].astype(np.int16)
    quantized = (colors // 32 * 32 + 16).clip(0, 255)
    packed = (quantized[:, 0].astype(np.int32) // 32 * 64
              + quantized[:, 1] // 32 * 8 + quantized[:, 2] // 32)
    counts = np.bincount(packed, minlength=512)
    codes = np.arange(512)
    unique = np.column_stack((codes // 64, codes // 8 % 8, codes % 8)) * 32 + 16
    order = np.argsort(counts)[::-1][:4]
    palette = [{'color': '#%02x%02x%02x' % tuple(unique[index]),
                'share': round(float(counts[index] / len(colors)), 3)} for index in order]
    return {'ink_px': len(rows), 'box_px': [int(columns.min()), int(rows.min()),
                                           int(columns.max() + 1), int(rows.max() + 1)],
            'fill': palette, 'note': 'Mask estimate; background, outlines and reveal can contaminate it.'}


def font_fit(image, wording, families=None):
    """Coarse bundled-family shape search, then spacing search on its best candidates."""
    from PIL import Image, ImageDraw
    import letitedit.catalogs.fonts as fonts
    import letitedit.looks.style_import_text as text
    if len(''.join(character for character in wording if character.isalnum())) < 4 or len(wording) > 24:
        return {'candidates': [], 'status': 'unmeasured', 'reason': 'Needs 4-24 legible characters; use individual words.'}
    mask, _ = text._glyph_mask(image)
    mask_method = 'caption glyph mask'
    if mask is None:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        bright = ((hsv[:, :, 2] > 230) & (hsv[:, :, 1] < 60)).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
        components = [index for index in range(1, count)
                      if 0.2 * image.shape[0] <= stats[index, cv2.CC_STAT_HEIGHT] <= image.shape[0]
                      and stats[index, cv2.CC_STAT_AREA] >= 20]
        if 2 <= len(components) <= len(wording) + 2:
            mask = np.isin(labels, components).astype(np.uint8) * 255
            mask_method = 'bright large-component fallback; inspect for background contamination'
    if mask is None:
        return {'candidates': [], 'status': 'unmeasured', 'reason': 'No usable glyph mask.'}
    candidates = text.font_candidates(mask, wording, limit=5, families=families)
    left, top, width, height = cv2.boundingRect(cv2.findNonZero(mask))
    target = cv2.resize(mask[top:top + height, left:left + width],
                        (max(8, round(width * 64 / height)), 64)) > 127
    fitted = []
    for candidate in candidates:
        path, _, _ = fonts.font_file(candidate['family'], candidate['weight'])
        if not Path(path).resolve().is_relative_to(fonts.LIB.resolve()):
            continue
        font = fonts.pil_font(candidate['family'], 96, candidate['weight'])
        best = None
        for spacing in (-0.06, -0.03, 0, 0.03, 0.06):
            canvas = Image.new('L', (len(wording) * 140 + 100, 200))
            draw = ImageDraw.Draw(canvas)
            cursor = 30.0
            for index, character in enumerate(wording):
                draw.text((cursor, 20), character, font=font, fill=255)
                advance = float(font.getlength(character))
                if index + 1 < len(wording):
                    advance = float(font.getlength(character + wording[index + 1]) - font.getlength(wording[index + 1]))
                cursor += advance + spacing * 96
            bounds = canvas.getbbox()
            if not bounds:
                continue
            glyphs = np.array(canvas.crop(bounds))
            aspect = glyphs.shape[1] / glyphs.shape[0]
            rendered = cv2.resize(glyphs, (target.shape[1], 64)) > 127
            overlap = float((rendered & target).sum() / max(1, (rendered | target).sum()))
            score = overlap - 0.6 * abs(math.log(aspect / (width / height)))
            fit = {**candidate, 'score': round(score, 3), 'overlap': round(overlap, 3),
                   'letter_spacing_em': spacing, 'size_px_estimate': round(96 * height / glyphs.shape[0], 2)}
            if best is None or score > best['score']:
                best = fit
        if best:
            fitted.append(best)
    fitted.sort(key=lambda item: -item['score'])
    return {'candidates': fitted[:3], 'status': 'estimated' if fitted else 'unmeasured',
            'mask_method': mask_method,
            'score_kind': 'mask overlap minus aspect penalty; not a probability or editorial score',
            'limitations': ['Check OCR and glyph masks visually; exact font remains unknown.',
                            'Spacing search is conditional on five coarse family fits.']}


def font_sheet(image, wording, fit, path):
    from PIL import Image, ImageDraw
    import letitedit.catalogs.fonts as fonts
    if not fit.get('candidates'):
        return None
    rows = [Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))]
    labels = ['Reference crop, native pixels; candidate fills below are white for shape comparison']
    for candidate in fit['candidates']:
        size = max(1, round(candidate['size_px_estimate']))
        font = fonts.pil_font(candidate['family'], size, candidate['weight'])
        canvas = Image.new('RGB', (max(1, size * (len(wording) + 2)), size * 3), '#202020')
        draw = ImageDraw.Draw(canvas)
        cursor = float(size)
        for index, character in enumerate(wording):
            draw.text((cursor, size), character, font=font, fill='white')
            advance = float(font.getlength(character))
            if index + 1 < len(wording):
                advance = float(font.getlength(character + wording[index + 1]) - font.getlength(wording[index + 1]))
            cursor += advance + candidate['letter_spacing_em'] * size
        bounds = canvas.convert('L').point(lambda value: 255 if value > 100 else 0).getbbox()
        rows.append(canvas.crop(bounds) if bounds else canvas)
        labels.append(f"{candidate['family']} {candidate['weight']} / spacing {candidate['letter_spacing_em']}em / shape {candidate['score']}")
    page = Image.new('RGB', (max(640, *(row.width for row in rows)) + 16,
                             sum(row.height + 30 for row in rows)), '#202020')
    draw, top = ImageDraw.Draw(page), 0
    for row, label in zip(rows, labels):
        draw.text((8, top + 2), label, fill='white')
        page.paste(row, (8, top + 24))
        top += row.height + 30
    page.save(path)
    return str(Path(path).resolve())


def analyse(video, events, info, folder, fps=15, check=None, progress=None, max_events=8, families=None, budget_s=120):
    import letitedit.footage.ocr as ocr
    import letitedit.looks.style_import as importer
    import letitedit.looks.style_import_text as text
    started = time.monotonic()
    destination = Path(folder) / 'typography-private'
    destination.mkdir(parents=True, exist_ok=True)
    eligible = [(index, event) for index, event in enumerate(events)
                if event.get('role') not in ('watermark', 'scene') and event.get('box')]
    chosen = eligible if max_events is None else eligible[:max_events]
    deadline = started + budget_s
    measured = []
    with ocr.Reader() as reader:
        for ordinal, (index, event) in enumerate(chosen):
            if time.monotonic() >= deadline:
                break
            if check:
                check()
            source_fps = float(info['fps'] or 30)
            times = sorted({round(round(stamp * source_fps) / source_fps, 4)
                            for stamp in sample_times(event, float(info['duration']), fps)
                            if round(stamp * source_fps) / source_fps < float(info['duration'])})
            frames = importer.frames_at(video, times, int(info['width']), info)
            if len(frames) != len(times):
                measured.append({'id': index, 'status': 'unmeasured',
                                 'reason': 'Incomplete decode; frame/time association not trusted.'})
                continue
            height, width = next(iter(frames.values())).shape[:2]
            box = event['box']
            hold_time = min(frames, key=lambda stamp: abs(stamp - float(event.get('best_t', (event['t'] + event['end']) / 2))))
            phase_times = {'entry': min(frames, key=lambda stamp: abs(stamp - event['t'])), 'hold': hold_time,
                           'exit': min(frames, key=lambda stamp: abs(stamp - event['end']))}
            phases = {}
            for phase, stamp in phase_times.items():
                picture, bounds = crop(frames[stamp], box, 0.025)
                path = destination / f'{index:04d}-{phase}.png'
                cv2.imwrite(str(path), picture)
                phases[phase] = {'t': stamp, 'path': str(path.resolve()), 'source_rect_px': list(bounds)}
            reading = ocr.read([phases['hold']['path']], reader=reader, variants=('raw', 'light'))[0]
            left, top, right, bottom = phases['hold']['source_rect_px']
            words, line_centers = [], []
            for line_index, line in enumerate(reading.get('lines') or []):
                line_centers.append((line['box'][1] + line['box'][3]) / 2 * (bottom - top) / height)
                for word in line.get('words') or []:
                    if time.monotonic() >= deadline:
                        break
                    word_box = word['box']
                    global_box = [(left + word_box[0] * (right - left)) / width,
                                  (top + word_box[1] * (bottom - top)) / height,
                                  (left + word_box[2] * (right - left)) / width,
                                  (top + word_box[3] * (bottom - top)) / height]
                    image, _ = crop(frames[hold_time], global_box)
                    if not image.size:
                        continue
                    trajectory = []
                    for stamp, frame in frames.items():
                        region, _ = crop(frame, global_box, 0.012)
                        trajectory.append({'t': stamp, **mask_measure(region)})
                    fitted = font_fit(image, word['text'], families)
                    if not families and fitted.get('candidates'):
                        families = [candidate['family'] for candidate in fitted['candidates']]
                    candidate_sheet = font_sheet(image, word['text'], fitted,
                                                 destination / f'{index:04d}-word-{len(words):02d}-fonts.png')
                    words.append({'text': word['text'], 'line': line_index, 'box': global_box,
                                  'glyph_height_share': global_box[3] - global_box[1],
                                  'case': 'upper' if word['text'].isupper() else 'as_written',
                                  'look': text.caption_look(image), 'font_fit': fitted, 'font_sheet': candidate_sheet,
                                  'trajectory': trajectory, 'easing': None,
                                  'motion_status': 'fixed-region mask observations, not tracked glyphs',
                                  'limitations': ['A moving word can leave its hold box; background can enter it.',
                                                  'Scale versus reveal and easing need visual judgment.']})
            dense = []
            for stamp, frame in frames.items():
                picture, bounds = crop(frame, box, 0.025)
                path = destination / f'{index:04d}-{stamp:.4f}.png'
                cv2.imwrite(str(path), picture)
                dense.append({'t': stamp, 'path': str(path.resolve()), 'source_rect_px': list(bounds)})
            measured.append({'id': index, 'status': 'measured',
                             'role': 'emphasis' if box[3] - box[1] >= 0.045 else 'linking',
                             'source_role': event.get('role'), 'role_method': '4.5% height threshold; confirm visually',
                             'text': ' '.join(line['text'] for line in reading.get('lines') or []),
                             'reading_status': 'unverified' if words else 'unmeasured',
                             'reading_note': 'Hold inherits coarse OCR timing and can still be mid-reveal. '
                                             'Confirm the intended word visually before using its font fit.',
                             'original_ocr': event.get('text'), 'box': box, 'phases': phases, 'dense': dense,
                             'words': words, 'line_spacing_height_share': np.diff(sorted(line_centers)).tolist(),
                             'layout_status': 'OCR boxes preserve lines and overlap; mixed fonts remain hypotheses',
                             'motion': text.entry_motion([frame for stamp, frame in frames.items()
                                                         if event['t'] - 2 / fps <= stamp <= event['t'] + 5 / fps],
                                                        box, fps)})
            if progress:
                progress((ordinal + 1) / max(1, len(chosen)), f'Text evidence {ordinal + 1}/{len(chosen)}')
    return {'version': VERSION, 'events': measured, 'fps': fps, 'resolution': [info['width'], info['height']],
            'coverage': {'eligible_events': len(eligible), 'attempted_events': len(chosen),
                         'decoded_events': sum(item['status'] == 'measured' for item in measured),
                         'not_sampled_ids': [index for index, _ in eligible if index not in {item['id'] for item in measured}],
                         'excluded_roles': ['watermark', 'scene']},
            'took_s': round(time.monotonic() - started, 2),
            'partial': len(measured) < len(eligible) or time.monotonic() >= deadline,
            'limitations': ['Typography detail is bounded by event count and time; unsampled events and unfinished font fits were not learned.',
                            'Fonts after the first fit use its candidate shortlist; another font may be missed.',
                            'OCR may miss text or split words into fragments.',
                            'Translucent or partially revealed letters can be missed by OCR and the glyph mask.',
                            'Entry/exit anchors inherit coarse OCR timing error; inspect dense brackets.',
                            'Crops and shape fits are evidence, not a copied type system or approval.']}


# ---------------------------------------------------------------- font styles (T198): every distinct style of
# on-screen text in a reference, each with its closest bundled families, weight, slant, case and treatment.

STYLES_VERSION = 1
STYLE_PROBES = {                     # varied families by kind of letter: a word's distances to them are its shape signature
    'sans': ('Inter', 'Montserrat', 'Poppins', 'Roboto', 'Raleway', 'Nunito', 'DM Sans', 'Space Grotesk', 'Barlow',
             'League Spartan', 'Archivo Black'),
    'condensed': ('Oswald', 'Bebas Neue', 'Roboto Condensed', 'Anton'),
    'serif': ('Lora', 'Playfair Display', 'Instrument Serif', 'Fraunces', 'DM Serif Display', 'Merriweather'),
    'slab': ('Roboto Slab', 'Alfa Slab One'),
    'mono': ('JetBrains Mono', 'Space Mono'),
    'script': ('Caveat', 'Permanent Marker', 'Pacifico'),
}
SIGNATURE = [family for families in STYLE_PROBES.values() for family in families]
POPULARITY_WEIGHT = 0.04             # how much a family's popularity (Google Fonts rank) counts against shape distance
ITALIC_SLOPE = 0.08                  # a lean above this is an italic (or oblique)
BROKEN_PARTS = 1.7                   # mask pieces per letter above which the letters are broken up (a picture fill)
WEIGHT_CLASSES = ((450, 'regular'), (650, 'medium'), (750, 'bold'), (1000, 'heavy'))
_RENDERS = {}


def _tight(ink):
    if ink is None or not ink.any():
        return None
    rows, cols = np.where(ink.any(1))[0], np.where(ink.any(0))[0]
    return ink[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def _render(family, weight, italic, text, size=96):
    """Tight bool drawing of text in a family on this PC (None when it can't be drawn); cached per process."""
    from PIL import Image, ImageDraw
    import letitedit.catalogs.fonts as fonts
    key = (family, weight, italic, text)
    if key not in _RENDERS:
        out = None
        try:
            font = fonts.pil_font(family, size, weight, italic)
            left, top, right, bottom = font.getbbox(text)
            if right > left and bottom > top:
                canvas = Image.new('L', (right - left + 8, bottom - top + 8), 0)
                ImageDraw.Draw(canvas).text((4 - left, 4 - top), text, font=font, fill=255)
                out = _tight(np.asarray(canvas) > 127)
        except Exception:  # noqa: BLE001 - a family that can't be drawn is skipped
            out = None
        if len(_RENDERS) > 30000:
            _RENDERS.clear()
        _RENDERS[key] = out
    return _RENDERS[key]


def _shear(ink, slope):
    """Lean a bool drawing right by slope (the top moves right by slope times the height)."""
    if not slope or ink is None:
        return ink
    height, width = ink.shape
    pad = int(math.ceil(abs(slope) * height)) + 2
    shift = slope * (height - 1) if slope > 0 else 0.0
    matrix = np.float32([[1, -slope, shift + (pad if slope < 0 else 0)], [0, 1, 0]])
    out = cv2.warpAffine(ink.astype(np.uint8) * 255, matrix, (width + pad, height), flags=cv2.INTER_LINEAR)
    return _tight(out > 127)


def slant_of(ink):
    """The lean of a word's letters (0 upright, about 0.2 for an italic): the median slope of its near-vertical
    edges (diagonal letters such as v, w and y barely count, since their edges are steeper or flatter)."""
    soft = cv2.GaussianBlur(ink.astype(np.float32), (5, 5), 1.2)
    gx = cv2.Sobel(soft, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(soft, cv2.CV_32F, 0, 1, ksize=3)
    strength = np.hypot(gx, gy)
    chosen = (np.abs(gx) > 2.5 * np.abs(gy)) & (strength > 0.3 * max(1e-6, float(strength.max())))
    if chosen.sum() < 10:
        return 0.0
    return round(float(np.median(gy[chosen] / gx[chosen])), 3)


def stroke_of(ink):
    """Stroke thickness as a share of the drawing's height (twice the ink over its edge length)."""
    padded = np.pad(ink, 1)
    edge = padded[1:-1, 1:-1] & ~(padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return float(2.0 * ink.sum() / max(1, edge.sum())) / max(1, ink.shape[0])


def kind_masks(crop, threshold=None):
    """{kind: bool mask} of light, coloured and dark pixels and the crop's own two-tone split (Otsu), and the split's
    threshold."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if threshold is None:
        threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return {'light': (v > 195) & (s < 80), 'colour': (v > 150) & (s >= 100), 'dark': v < 75,
            'otsu_light': gray > threshold, 'otsu_dark': gray <= threshold}, threshold


def word_mask(crop, letters, variant=None, detail=False):
    """(bool mask of the letters, kind) for a crop around one word, or (None, why). Tries light, coloured and dark
    text and the crop's own two-tone split; keeps the one whose parts look most like that many letters.
    detail=True adds a third item: {offset: (top, left) of the mask in the crop, parts: pieces per letter,
    threshold}."""
    options, threshold = kind_masks(crop)
    height, width = crop.shape[:2]
    best, best_score = None, None
    for kind, mask in options.items():
        share = float(mask.mean())
        if share < 0.04 or share > 0.7:
            continue
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        parts = [index for index in range(1, count) if stats[index, cv2.CC_STAT_AREA] >= max(4, height * height * 0.002)]
        border = [index for index in parts
                  if stats[index, cv2.CC_STAT_LEFT] == 0 or stats[index, cv2.CC_STAT_TOP] == 0
                  or stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] >= width
                  or stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] >= height]
        inner = [index for index in parts if index not in border]
        if not inner:
            continue
        heights = np.array([stats[index, cv2.CC_STAT_HEIGHT] for index in inner], float)
        tall = int((heights >= 0.3 * heights.max()).sum())
        if heights.max() < 0.35 * height:
            continue
        border_area = sum(int(stats[index, cv2.CC_STAT_AREA]) for index in border)
        inner_area = sum(int(stats[index, cv2.CC_STAT_AREA]) for index in inner)
        score = (-abs(math.log((tall + 0.5) / (letters + 0.5))) - 2.0 * border_area / max(1, border_area + inner_area)
                 + (0.15 if variant and variant != 'raw' and kind == variant else 0))
        if best_score is None or score > best_score:
            best, best_score = (np.isin(labels, inner), kind, len(inner) / max(1, letters)), score
    if best is None or best_score < -1.2:
        return (None, 'no letter-like mask', None) if detail else (None, 'no letter-like mask')
    ink = _tight(best[0])
    if ink is None or ink.shape[0] < 8:
        return (None, 'letters too small', None) if detail else (None, 'letters too small')
    if not detail:
        return ink, best[1]
    rows, cols = np.where(best[0].any(1))[0], np.where(best[0].any(0))[0]
    return ink, best[1], {'offset': (int(rows[0]), int(cols[0])), 'parts': round(best[2], 2), 'threshold': threshold,
                          'midpoint': _tight(_midpoint(crop, best[0]))}


def _midpoint(crop, mask):
    """The letters re-cut halfway between their fill and the background just around them, so anti-aliased edges
    count as half ink and stroke widths come out true whichever colour test found them."""
    lightness = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    m8 = mask.astype(np.uint8)
    core = cv2.erode(m8, np.ones((3, 3), np.uint8)) > 0
    ring = (cv2.dilate(m8, np.ones((7, 7), np.uint8)) > 0) & ~(cv2.dilate(m8, np.ones((3, 3), np.uint8)) > 0)
    if core.sum() < 10 or ring.sum() < 10:
        return mask
    fill, around = float(np.median(lightness[core])), float(np.median(lightness[ring]))
    if abs(fill - around) < 40:
        return mask
    middle = (fill + around) / 2
    refined = (lightness > middle) if fill > around else (lightness < middle)
    refined &= cv2.dilate(m8, np.ones((5, 5), np.uint8)) > 0
    return refined if refined.sum() >= 0.5 * mask.sum() else mask


def treatment_of(picture, mask, kind=None, threshold=None):
    """Fill, plate, outline and shadow of letters (mask True) in a picture with a margin around them:
    {fill: hex, plate: hex | None, outline: hex | None, shadow: bool}. The plate is an even colour behind the
    letters (a box, a pill or a plain card); the outline a band of one colour hugging them; the shadow a darker
    copy offset down and right. Needs a margin of about the letters' height around them."""
    height = int(np.ptp(np.where(mask.any(1))[0]) + 1) if mask.any() else 0
    if height < 8:
        return None
    lab = cv2.cvtColor(picture, cv2.COLOR_BGR2LAB).astype(np.float32)
    m8 = mask.astype(np.uint8)
    core = cv2.erode(m8, np.ones((3, 3), np.uint8)) if height >= 16 else m8
    if core.sum() < 10:
        core = m8
    others = np.zeros(mask.shape, bool)
    if kind:
        options, _ = kind_masks(picture, threshold)
        others = cv2.dilate((options.get(kind, others) & ~mask).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

    def grown(radius):
        radius = max(1, int(round(radius)))
        return cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))) > 0

    hug = grown(max(3, height * 0.08)) & ~grown(1) & ~others
    near = grown(height * 0.3) & ~grown(height * 0.14) & ~others
    far = grown(height * 0.95) & ~grown(height * 0.6) & ~others
    fill = np.median(lab[core > 0], 0)
    out = {'fill': _hex(np.median(picture[core > 0], 0))}
    if hug.sum() < 20 or near.sum() < 20:
        out.update(plate=None, outline=None, shadow=False)
        return out
    hug_value, near_value = np.median(lab[hug], 0), np.median(lab[near], 0)
    spread_hug, spread_near = float(lab[hug].std(0).mean()), float(lab[near].std(0).mean())
    distance = lambda a, b: float(np.linalg.norm(a - b))  # noqa: E731
    rows_, cols_ = np.indices(mask.shape)
    centre_y, centre_x = np.argwhere(mask).mean(0)
    before = hug & ((rows_ - centre_y) + (cols_ - centre_x) < 0)
    after = hug & ((rows_ - centre_y) + (cols_ - centre_x) >= 0)
    even = (before.sum() >= 10 and after.sum() >= 10
            and distance(np.median(lab[before], 0), np.median(lab[after], 0)) < 20)
    outline = (even and distance(hug_value, fill) > 45 and distance(hug_value, near_value) > 30 and spread_hug < 20)
    out['outline'] = _hex(np.median(picture[hug], 0)) if outline else None
    bounded = far.sum() >= 20 and distance(np.median(lab[far], 0), near_value) > 25
    plate = distance(near_value, fill) > 40 and (spread_near < 5 and bounded or spread_near < 2)
    out['plate'] = _hex(np.median(picture[near], 0)) if plate else None
    step = max(2, int(round(height * 0.06)))
    ring = ~grown(1)
    down = np.roll(np.roll(mask, step, 0), step, 1) & ring & ~others
    up = np.roll(np.roll(mask, -step, 0), -step, 1) & ring & ~others
    out['shadow'] = bool(not outline and not plate and down.sum() > 20 and up.sum() > 20
                         and float(np.median(lab[down][:, 0])) + 18 < float(np.median(lab[up][:, 0])))
    return out


def _hex(bgr):
    b, g, r = (int(round(float(x))) for x in bgr)
    return f'#{r:02X}{g:02X}{b:02X}'


def compare(target, drawn, height=48):
    """Distance between two bool drawings of the same word (lower is closer): outline distance both ways, ink share
    and width, at a common height."""
    from scipy import ndimage
    if drawn is None or target is None:
        return None
    aspect_t, aspect_d = target.shape[1] / target.shape[0], drawn.shape[1] / drawn.shape[0]
    width = max(8, int(round(height * aspect_t)))
    a = cv2.resize(target.astype(np.uint8) * 255, (width, height), interpolation=cv2.INTER_AREA) > 127
    b = cv2.resize(drawn.astype(np.uint8) * 255, (width, height), interpolation=cv2.INTER_AREA) > 127
    if not a.any() or not b.any():
        return None
    chamfer = float(ndimage.distance_transform_edt(~b)[a].mean() + ndimage.distance_transform_edt(~a)[b].mean()) / height * 10
    ink = abs(float(a.mean()) - float(b.mean())) / max(0.05, float(a.mean()))
    return chamfer + 0.5 * ink + 1.5 * abs(math.log(aspect_d / aspect_t))


def _weights_of(row):
    named = [str(w) for w in row.get('weights') or ['400']]
    offered = sorted({int(re.sub(r'\D', '', w) or 400) for w in named if not w.endswith('i')})
    if row.get('variable_axes') and len(offered) <= 2:
        offered = [300, 400, 500, 600, 700, 800, 900]
    return [w for w in offered if 300 <= w <= 900] or offered[:1]


def match_word(ink, text, slope, rows):
    """[(distance, family, weight)] for one word's mask against catalog rows, closest first: per family, the two
    weights whose stroke is closest to the word's, compared by shape. An italic word is drawn in the family's italic,
    or leaned by the measured slope when the family has none."""
    italic = slope >= ITALIC_SLOPE
    target_stroke = stroke_of(ink)
    out = []
    for row in rows:
        has_italic = any(str(w).endswith('i') for w in row.get('weights') or [])

        def drawn(weight):
            picture = _render(row['family'], weight, italic and has_italic, text)
            return _shear(picture, slope) if picture is not None and italic and not has_italic else picture
        weights = _weights_of(row)
        light = 400 if 400 in weights else weights[0]
        heavy = weights[-1]
        pictures = {light: drawn(light)}
        if pictures[light] is None:
            continue
        guess = light
        if heavy != light:
            pictures[heavy] = drawn(heavy)
            if pictures[heavy] is not None:
                low, high = stroke_of(pictures[light]), stroke_of(pictures[heavy])
                if high > low:
                    guess = light + (target_stroke - low) / (high - low) * (heavy - light)
        guess = min(weights, key=lambda weight: abs(weight - guess))
        if guess not in pictures:
            pictures[guess] = drawn(guess)
        score = compare(ink, pictures[guess])
        if score is not None:
            out.append((round(score, 4), row['family'], guess))
    out.sort()
    return out


def _catalog_rows():
    import letitedit.catalogs.fonts as fonts
    return list(fonts.catalog())


def probe_word(ink, text, slope):
    """{family: distance} for the SIGNATURE families: the word's shape signature."""
    rows = {row['family']: row for row in _catalog_rows()}
    return {family: distance for distance, family, _ in
            match_word(ink, text, slope, [rows[name] for name in SIGNATURE if name in rows])}


def case_of(texts):
    """'upper', 'title' or 'as_written' (sentence or lower case), from the words read (a vote, so a misread word
    doesn't decide it); None with too few letters."""
    words = [word for text in texts for word in re.findall(r"[A-Za-z][A-Za-z'’]*", text)]
    letters = ''.join(words)
    if len(letters) < 3:
        return None
    voters = [word for word in words if sum(ch.isalpha() for ch in word) >= 2] or words
    upper = sum(1 for word in voters if sum(ch.isupper() for ch in word) >= 0.75 * sum(ch.isalpha() for ch in word))
    if upper >= 0.6 * len(voters):
        return 'upper'
    long_words = [word for word in words if len(word) >= 4]
    if len(long_words) >= 2 and sum(word[0].isupper() for word in long_words) >= 0.75 * len(long_words):
        return 'title'
    return 'as_written'


def ruler_weight(ink, text, slope):
    """The weight the word looks, read against Inter drawing the same text at 300-900 (stroke thickness for its
    height), so a heavy-looking single-weight family still reads as heavy."""
    upright = _shear(ink, -slope) if slope >= ITALIC_SLOPE else ink
    if upright is None:
        return None
    target = stroke_of(upright)
    strokes = []
    for weight in (300, 400, 500, 600, 700, 800, 900):
        drawn = _render('Inter', weight, False, text)
        if drawn is not None:
            strokes.append((stroke_of(drawn), weight))
    if len(strokes) < 2:
        return None
    strokes.sort()
    if target <= strokes[0][0]:
        return strokes[0][1]
    for (low, low_weight), (high, high_weight) in zip(strokes, strokes[1:]):
        if low <= target <= high:
            return int(round((low_weight + (target - low) / max(1e-6, high - low) * (high_weight - low_weight)) / 50) * 50)
    return strokes[-1][1]


def weight_class(weight):
    return next(name for limit, name in WEIGHT_CLASSES if weight <= limit)


def colour_name(hex_colour):
    value = str(hex_colour or '').lstrip('#')
    if len(value) != 6:
        return None
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    h, s, v = (int(x) for x in cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0, 0])
    if v < 70:
        return 'black'
    if s < 50:
        return 'white' if v > 185 else 'grey'
    hue = h * 2
    return ('red' if hue < 15 or hue >= 340 else 'orange' if hue < 40 else 'yellow' if hue < 70 else 'green' if hue < 160
            else 'cyan' if hue < 200 else 'blue' if hue < 260 else 'purple' if hue < 300 else 'pink')


def read_words(video, every_s=0.5, reader=None, check=None, deadline=None, reading=None, max_frames=900):
    """Words on screen every every_s seconds, each with its letter mask, lean and stroke: {words: [{t, text, line,
    box, variant, ink, kind, slope, stroke, look, height_px}], readings: [{t, lines}], ...}. A frame that hardly
    changed reuses the previous reading. reading: an earlier readings list, to skip the OCR (tests, re-runs)."""
    import letitedit.footage.ocr as ocr
    import tempfile
    capture = cv2.VideoCapture(str(video))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(every_s * fps)))
    targets = list(range(0, total, step))[:max_frames]
    cached = {round(float(item['t']), 3): item for item in reading or []}
    own = reader is None and reading is None
    scratch = Path(tempfile.mkdtemp(prefix='letitedit_fonts_'))
    words, readings, previous, previous_lines, reused = [], [], None, None, 0
    reader = ocr.Reader() if own else reader
    try:
        wanted = iter(targets)
        target, index = next(wanted, None), 0
        while target is not None:
            if check:
                check()
            if deadline and time.monotonic() > deadline:
                break
            if not capture.grab():
                break
            if index != target:
                index += 1
                continue
            ok, frame = capture.retrieve()
            index += 1
            frame_number, stamp = target, round(target / fps, 3)
            target = next(wanted, None)
            if not ok:
                continue
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (96, max(8, 96 * frame.shape[0] // frame.shape[1])))
            small = small.astype(np.int16)
            if stamp in cached:
                lines = cached[stamp]['lines']
            elif reading is not None:
                lines = []
            elif previous is not None and float(np.abs(small - previous).mean()) < 0.6:
                lines, reused = previous_lines, reused + 1
            else:
                path = scratch / f'frame-{frame_number:06d}.png'
                cv2.imwrite(str(path), frame)
                got = ocr.read([path], variants=('raw', 'light', 'colour', 'dark'), reader=reader, scratch=scratch / 'masks')[0]
                try:
                    path.unlink()
                except OSError:
                    pass
                lines = [{'text': line['text'], 'box': line['box'], 'variant': line.get('variant'),
                          'words': line.get('words') or []} for line in got.get('lines') or []]
            previous, previous_lines = small, lines
            readings.append({'t': stamp, 'frame': frame_number, 'lines': lines})
            height, width = frame.shape[:2]
            for line_index, line in enumerate(lines):
                for word in line['words']:
                    text = word['text'].strip('.,:;!?"“”()[]')
                    letters = sum(ch.isalnum() for ch in text)
                    if letters < 1 or not ocr.plausible(text):
                        continue
                    x0, y0, x1, y1 = word['box']
                    box_px = [int(x0 * width), int(y0 * height), int(math.ceil(x1 * width)), int(math.ceil(y1 * height))]
                    entry = {'t': stamp, 'frame': frame_number, 'text': text, 'line': line['text'],
                             'line_index': line_index, 'box': [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
                             'variant': line.get('variant'), 'letters': letters}
                    if letters >= 3 and box_px[3] - box_px[1] >= 10:
                        pad = max(2, int((box_px[3] - box_px[1]) * 0.18))
                        picture = frame[max(0, box_px[1] - pad):box_px[3] + pad, max(0, box_px[0] - pad):box_px[2] + pad]
                        ink, kind, detail = (word_mask(picture, letters, line.get('variant'), detail=True)
                                             if picture.size else (None, 'empty crop', None))
                        if ink is not None:
                            top = max(0, box_px[1] - pad) + detail['offset'][0]
                            left = max(0, box_px[0] - pad) + detail['offset'][1]
                            margin = max(4, int(ink.shape[0] * 1.0))
                            y0, x0 = max(0, top - margin), max(0, left - margin)
                            wide = frame[y0:top + ink.shape[0] + margin, x0:left + ink.shape[1] + margin]
                            placed = np.zeros(wide.shape[:2], bool)
                            placed[top - y0:top - y0 + ink.shape[0], left - x0:left - x0 + ink.shape[1]] = ink
                            entry.update({'ink': ink, 'kind': kind, 'slope': slant_of(ink), 'stroke': round(stroke_of(ink), 4),
                                          'parts': detail['parts'], 'height_px': int(ink.shape[0]),
                                          'ink_mid': detail['midpoint'],
                                          'look': treatment_of(wide, placed, kind, detail['threshold']) or {}})
                        else:
                            entry['mask_problem'] = kind
                    words.append(entry)
    finally:
        capture.release()
        if own:
            reader.close()
        for leftover in scratch.glob('*'):
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            scratch.rmdir()
        except OSError:
            pass
    return {'words': words, 'readings': readings, 'fps': fps, 'duration': total / fps if total else 0.0,
            'every_s': every_s, 'frames_read': len(readings), 'frames_reused': reused,
            'complete': len(readings) == len(targets) and len(targets) * step >= total - step + 1}


def looks_like_a_word(text):
    """False for OCR noise: one character making up most of a word ('iiiiiii', '0000', 'oopo')."""
    letters = [ch.lower() for ch in text if ch.isalnum()]
    if not letters:
        return False
    most = max(letters.count(ch) for ch in set(letters))
    return not (len(letters) >= 3 and most / len(letters) > 0.5 and len(set(letters)) <= 2)


def well_read(text):
    """False for a word the OCR plainly misread (stray symbols, digits glued into letters, accents in English)."""
    import letitedit.footage.ocr as ocr
    letters = sum(ch.isalnum() for ch in text)
    return letters > 0 and ocr.quality(text) >= 0.7 * letters


def track_words(words, every_s):
    """Words seen in several samples at about the same place, as one item each: [{text, first, last, seen: [word]}]."""
    items = []
    for word in sorted(words, key=lambda item: item['t']):
        if not looks_like_a_word(word['text']) or not well_read(word['text']):
            continue
        key = re.sub(r'\W', '', word['text']).lower()
        cx, cy = (word['box'][0] + word['box'][2]) / 2, (word['box'][1] + word['box'][3]) / 2
        hit = None
        for item in reversed(items):
            if word['t'] - item['last'] > every_s * 2.5:
                break
            if item['key'] == key and abs(item['cx'] - cx) < 0.05 and abs(item['cy'] - cy) < 0.05:
                hit = item
                break
        if hit is None:
            items.append({'key': key, 'text': word['text'], 'cx': cx, 'cy': cy, 'first': word['t'], 'last': word['t'],
                          'seen': [word]})
        else:
            hit.update(last=word['t'], cx=cx, cy=cy)
            hit['seen'].append(word)
    for item in items:
        measured = [word for word in item['seen'] if word.get('ink') is not None]
        item['best'] = (max(measured, key=lambda word: (-round(abs(math.log(max(0.2, word.get('parts', 1)))), 1),
                                                        word['height_px'])) if measured else None)
        item['broken'] = bool(item['best'] and item['best'].get('parts', 1) > BROKEN_PARTS)
        if item['best'] is not None:
            item['best']['slope'] = slant_of(item['best']['ink'])
    return items


def _relative(item):
    """The item's weight and width against Inter Regular drawing the same text: stroke ratio and width ratio (both
    about 1 for Inter Regular), which hold whatever the words say."""
    best = item['best']
    drawn = _render('Inter', 400, False, best['text'])
    if drawn is None:
        return None
    upright = _shear(best['ink'], -best['slope']) if best['slope'] >= ITALIC_SLOPE else best['ink']
    if upright is None:
        return None
    return {'weight': stroke_of(upright) / max(1e-6, stroke_of(drawn)),
            'width': (upright.shape[1] / upright.shape[0]) / (drawn.shape[1] / drawn.shape[0])}


def _probe_kind(item):
    """(kind of letter, normalised signature vector or None) for an item."""
    found = probe_word(item['best']['ink'], item['best']['text'], item['best']['slope'])
    if len(found) < len(SIGNATURE) // 2:
        return None, None
    closest = min(found, key=found.get)
    kind = next(name for name, families in STYLE_PROBES.items() if closest in families)
    vector = np.array([found.get(family, np.nan) for family in SIGNATURE], float)
    vector = np.where(np.isnan(vector), np.nanmax(vector), vector)
    spread = vector.std()
    return kind, ((vector - vector.mean()) / spread if spread > 1e-6 else None)


GROUP_LIMIT = 1.5                    # how far a word may be from a style (shape signature, weight, lean) to join it


def group_items(items):
    """Measured items grouped into styles by shape signature (distances to the STYLE_PROBES families, compared by
    correlation), relative weight and lean. Words seen longest go first, so a style starts from clean examples."""
    styles = []
    for item in sorted(items, key=lambda item: -len(item['seen'])):
        if item['best'] is None or item['best']['letters'] < 3:
            continue
        rel = _relative(item)
        if rel is None:
            continue
        kind, signature = _probe_kind(item)
        if signature is None:
            continue
        item.update(kind=kind, signature=signature, rel=rel, italic=item['best']['slope'] >= ITALIC_SLOPE)
        best, best_distance = None, None
        for style in styles:
            centre = style['signature'] / max(1e-6, np.linalg.norm(style['signature']))
            likeness = float(np.dot(signature / np.linalg.norm(signature), centre))
            distance = ((1 - likeness) / 0.15 + abs(math.log(rel['weight'] / style['weight'])) / 0.3
                        + (1.5 if item['italic'] != style['italic'] else 0))
            if best_distance is None or distance < best_distance:
                best, best_distance = style, distance
        if best is not None and best_distance <= GROUP_LIMIT:
            best['items'].append(item)
            n = len(best['items'])
            best['signature'] = best['signature'] + signature
            best['weight'] = math.exp((math.log(best['weight']) * (n - 1) + math.log(rel['weight'])) / n)
            best['width'] = math.exp((math.log(best['width']) * (n - 1) + math.log(rel['width'])) / n)
        else:
            styles.append({'items': [item], 'weight': rel['weight'], 'width': rel['width'], 'italic': item['italic'],
                           'kind': kind, 'signature': signature.copy()})
    styles = _fold_small(styles)
    for style in styles:
        kinds = [item['kind'] for item in style['items']]
        style['kind'] = max(set(kinds), key=kinds.count)
        leaning = [item['italic'] for item in style['items']]
        style['italic'] = sum(leaning) > len(leaning) / 2
    return styles


def _style_distance(a, b):
    likeness = float(np.dot(a['signature'], b['signature'])
                     / max(1e-6, np.linalg.norm(a['signature']) * np.linalg.norm(b['signature'])))
    return ((1 - likeness) / 0.15 + abs(math.log(a['weight'] / b['weight'])) / 0.3
            + (1.5 if a['italic'] != b['italic'] else 0))


def _kind_of(style):
    kinds = [item.get('kind') for item in style['items'] if item.get('kind')]
    return max(set(kinds), key=kinds.count) if kinds else None


def _fold_small(styles, small=4, limit=2.0):
    """Groups of fewer than `small` words join the nearest group of at least that many with the same lean and kind
    of letter, when it is within limit (a few serif or italic emphasis words stay their own style)."""
    big = [style for style in styles if len(style['items']) >= small]
    out = list(big)
    for style in styles:
        if len(style['items']) >= small:
            continue
        alike = [other for other in big if other['italic'] == style['italic']
                 and _kind_of(other) == _kind_of(style)]
        home = min(alike, key=lambda other: _style_distance(style, other), default=None)
        if home is not None and _style_distance(style, home) <= limit:
            home['items'].extend(style['items'])
            home['signature'] = home['signature'] + style['signature']
        else:
            out.append(style)
    return out


def _family_ranking(chosen, rows, shortlist=60, prior=None):
    """Families ranked over a style's chosen words: each word's shape distance above its closest family, averaged,
    plus prior times the log of the family's popularity rank (popular families are used far more often)."""
    prior = POPULARITY_WEIGHT if prior is None else prior
    table = {}
    for number, item in enumerate(chosen):
        best = item['best']
        if number == 1 and table:
            keep = {family for family, entry in sorted(table.items(), key=lambda kv: kv[1]['distances'][0])[:shortlist]}
            rows = [row for row in rows if row['family'] in keep]
        ranked = match_word(best['ink'], best['text'], best['slope'], rows)
        if not ranked:
            continue
        top = ranked[0][0]
        for distance, family, weight in ranked:
            entry = table.setdefault(family, {'distances': [], 'weights': []})
            entry['distances'].append(distance - top)
            entry['weights'].append(weight)
    used = max((len(entry['distances']) for entry in table.values()), default=0)
    popularity = {row['family']: row.get('popularity') for row in rows}
    out = []
    for family, entry in table.items():
        if len(entry['distances']) < used:
            continue
        distance = float(np.mean(entry['distances']))
        rank = popularity.get(family) or 2000
        out.append({'family': family, 'distance': round(distance, 4), 'weight': int(np.median(entry['weights'])),
                    'popularity': rank, 'score': round(distance + prior * math.log(max(1, rank)), 4)})
    out.sort(key=lambda entry: entry['score'])
    return out, used


def _majority(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return max(set(values), key=values.count)


def describe_style(style, rows, max_words=5, prior=None):
    """One style's answer: family top 3 (or not sure, with why), weight, lean, case, treatment, times and samples."""
    clean = [item for item in style['items'] if not item['broken']]
    broken_share = 1 - len(clean) / max(1, len(style['items']))
    items = sorted(clean or style['items'], key=lambda item: (-min(item['best']['letters'], 10), -item['best']['height_px']))
    chosen, seen_texts = [], set()
    for item in items:
        if item['key'] in seen_texts:
            continue
        seen_texts.add(item['key'])
        chosen.append(item)
        if len(chosen) >= max_words:
            break
    ranking, used = _family_ranking(chosen, rows, prior=prior)
    texts = [item['text'] for item in style['items']]
    looks = [word.get('look') or {} for item in style['items'] for word in item['seen'] if word.get('look')]
    fills = [colour_name(look.get('fill')) for look in looks]
    fill_counts = {}
    for name in fills:
        if name:
            fill_counts[name] = fill_counts.get(name, 0) + 1
    observations = sum(len(item['seen']) for item in style['items'])
    reasons = []
    if used < 2:
        reasons.append('fewer than two different words to compare')
    if broken_share > 0.5:
        reasons.append('the letters are broken up (filled with a picture or a texture), so their shapes are unclear')
    if ranking and len(ranking) > 3 and ranking[3]['score'] - ranking[0]['score'] < 0.02:
        reasons.append('the closest families are nearly tied')
    ruler = [ruler_weight(item['best'].get('ink_mid') if item['best'].get('ink_mid') is not None else item['best']['ink'],
                          item['best']['text'], item['best']['slope']) for item in chosen]
    ruler = [value for value in ruler if value]
    weight = int(np.median(ruler)) if ruler else (ranking[0]['weight'] if ranking else None)
    return {
        'start_s': round(min(item['first'] for item in style['items']), 3),
        'end_s': round(max(item['last'] for item in style['items']), 3),
        'samples': [{'text': item['text'], 't': item['first'], 'box': item['best']['box']} for item in chosen[:5]],
        'words': len(style['items']), 'observations': observations,
        'seen': [[item['text'], item['first'], item['last'], item['best']['box']] for item in style['items']],
        'family': {'status': 'not_sure' if reasons or not ranking else 'found',
                   'top': [entry['family'] for entry in ranking[:3]],
                   'ranking': ranking[:8], 'words_compared': used, 'why_not_sure': reasons or None,
                   'by_shape': sorted(ranking, key=lambda entry: entry['distance'])[:40]},
        'kind': style['kind'], 'italic': style['italic'],
        'weight': weight, 'weight_class': weight_class(weight) if weight else None,
        'relative_weight': round(style['weight'], 3), 'relative_width': round(style['width'], 3),
        'case': case_of(texts),
        'treatment': {'fill': sorted(fill_counts, key=fill_counts.get, reverse=True)[:3],
                      'plate': _majority([look.get('plate') is not None for look in looks if 'plate' in look]),
                      'outline': _majority([look.get('outline') is not None for look in looks if 'outline' in look]),
                      'shadow': _majority([bool(look.get('shadow')) for look in looks])},
    }


def merge_alike(styles):
    """Styles with the same lean and weight class whose closest families overlap (two of the top three) are one
    style: the one seen most keeps its answer, the others' times, samples and words join it."""
    styles = sorted(styles, key=lambda style: -style['observations'])
    kept = []
    for style in styles:
        home = next((other for other in kept
                     if other['italic'] == style['italic'] and other['weight_class'] == style['weight_class']
                     and len(set(other['family']['top']) & set(style['family']['top'])) >= 2), None)
        if home is None:
            kept.append(style)
            continue
        home['start_s'], home['end_s'] = min(home['start_s'], style['start_s']), max(home['end_s'], style['end_s'])
        home['seen'] = home['seen'] + style['seen']
        home['words'] += style['words']
        home['observations'] += style['observations']
        home['samples'] = (home['samples'] + style['samples'])[:5]
        home.setdefault('merged', 0)
        home['merged'] += 1
    return sorted(kept, key=lambda style: style['start_s'])


def font_styles(video, folder=None, every_s=0.5, check=None, progress=None, budget_s=600, reading=None, words=None,
                min_observations=3):
    """Every distinct style of on-screen text: found (family top 3, weight, lean, case, treatment), not sure (why),
    and what was checked. Reads the text with the PC's own OCR every every_s seconds."""
    started = time.monotonic()
    deadline = started + budget_s
    got = words or read_words(video, every_s, check=check, deadline=deadline, reading=reading)
    if progress:
        progress(0.5, 'font styles: words read')
    items = track_words(got['words'], every_s)
    styles = group_items(items)
    rows = _catalog_rows()
    found, unsure_small = [], []
    for index, style in enumerate(sorted(styles, key=lambda style: min(item['first'] for item in style['items']))):
        if check:
            check()
        observations = sum(len(item['seen']) for item in style['items'])
        if observations < min_observations:
            unsure_small.append({'texts': [item['text'] for item in style['items']][:5],
                                 'start_s': min(item['first'] for item in style['items']), 'observations': observations})
            continue
        if time.monotonic() > deadline:
            unsure_small.append({'texts': [item['text'] for item in style['items']][:5], 'reason': 'time budget'})
            continue
        found.append(describe_style(style, rows))
        if progress:
            progress(0.5 + 0.5 * (index + 1) / max(1, len(styles)), 'font styles')
    found = merge_alike(found)
    for number, style in enumerate(found, 1):
        style['id'] = f'font-{number}'
    unread = sum(1 for word in got['words'] if word.get('letters', 0) >= 3 and word.get('ink') is None)
    return {'version': STYLES_VERSION, 'styles': found, 'too_brief': unsure_small,
            'checked': {'every_s': every_s, 'frames_read': got['frames_read'], 'frames_reused': got['frames_reused'],
                        'complete': got['complete'], 'words_read': len(got['words']),
                        'words_without_clean_letters': unread},
            'took_s': round(time.monotonic() - started, 1),
            'limitations': ['Text is read with Windows OCR (Latin script); other scripts are not read, so their styles '
                            'are not checked.',
                            'Families are the closest of the bundled library; a commercial font (SF Pro, Helvetica) '
                            'shows as its nearest open look-alikes.',
                            'Text inside pictures (screenshots, logos, a clip\'s own captions) is read like any text.']}
