"""Conservative phone-size ink checks over every encoded native frame."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

import letitedit.review.checks as checks
import letitedit.timeline.edit_script as edit_script
from letitedit.looks.look_check import current_project, digest, project_digest


# ------------------------------------------------------------------ kept renders of a picture, by what they draw

PICTURE_VERSION = 1      # in every kept render's and measurement's key: a change to how they are made starts afresh
PICTURE_KEEP = 16        # kept renders; the least recently used beyond this are removed
PICTURE_KEEP_BYTES = 2 * 1024 ** 3   # and beyond this much in all (long videos), always keeping the newest
MEASURE_KEEP = 32        # kept measurements
AUDIO_ONLY = {'volume', 'panner', 'mono', 'channelcopy', 'audiolevel'}   # MLT filters that change only the sound
AUDIO_TRANSITIONS = {'mix'}                                               # and the transition that mixes it


def pictures_folder():
    return checks.CACHE / 'caption-pictures'


def _resource_stamp(text):
    """Size and date of a media file, or of the files in a folder or image sequence a resource names."""
    path = Path(text)
    try:
        if path.is_file():
            stat = path.stat()
            return [stat.st_size, stat.st_mtime_ns]
        folder = path if path.is_dir() else (path.parent if '%' in path.name and path.parent.is_dir() else None)
        if folder is not None:
            stats = [entry.stat() for entry in os.scandir(folder) if entry.is_file()]
            return [len(stats), sum(stat.st_size for stat in stats), max((stat.st_mtime_ns for stat in stats), default=0)]
    except (OSError, ValueError):
        return None
    return None


def picture_key(xml, frames, settings):
    """One digest of everything a render of `xml` draws: each track of the main tractor shown in the picture (its
    items, their producers, filters and media files' size and date, in the export's own canonical form, the
    background colour under them included), the compositing transitions and the timeline's filters, the profile,
    the project folder relative media resolve against, the engine build, the render settings and PICTURE_VERSION.
    A track hidden from the picture draws nothing and is left out (the shown ones are numbered among themselves), and
    so are the filters and the transition that change only the sound, so a change to the captions (for the picture
    under them) or to the sound keeps the key, and any other change makes another."""
    import letitedit.timeline.chunk_cache as chunk_cache
    import letitedit.timeline.timeline_model as timeline_model
    timeline = timeline_model.load(xml)
    for element in timeline.root.iter():
        for effect in [child for child in element if child.tag == 'filter'
                       and timeline_model.props(child).get('mlt_service') in AUDIO_ONLY]:
            element.remove(effect)
    shown = [timeline.elements.get(track.get('producer')) for track in timeline.main.findall('track')
             if track.get('hide', '') not in ('video', 'both')]
    files = set()
    for element in _reachable(timeline, shown + [child for child in timeline.main if child.tag in ('transition', 'filter')]):
        for prop in element.iter('property'):    # a clip's media, and any file a filter reads (a LUT, a mask)
            text = (prop.text or '').strip()
            if text and not text.startswith('#') and (prop.get('name') in ('resource', 'warp_resource')
                                                       or os.path.isabs(text)):
                files.add(text)
    result = hashlib.sha256(json.dumps({
        'version': PICTURE_VERSION, 'frames': frames, 'settings': settings, 'root': timeline.root.get('root'),
        'profile': sorted(timeline.profile.items()), 'engine': chunk_cache.renderer_signature(checks.APP),
        'media': sorted([text, _resource_stamp(text)] for text in files)}, default=str).encode())
    # tracks are counted among the shown ones only: a hidden track added or removed (a caption track split in two, an
    # audio track) moves the others' numbers without changing what is drawn
    tokens = {}
    for index, track in enumerate(timeline.main.findall('track')):
        hide = track.get('hide', '')
        if hide in ('video', 'both'):
            tokens[str(index)] = 'hidden'
            continue
        tokens[str(index)] = f'shown {sum(token != "hidden" for token in tokens.values())}'
        result.update(f'|{tokens[str(index)]}:{hide}:'.encode())
        result.update(timeline.canon(timeline.elements.get(track.get('producer'))).encode('utf-8', 'replace'))
    # the transitions (and any filter planted on a track) in their order, then the filters on the whole timeline in
    # theirs: those apply to the finished stack wherever the file writes them, as the export's fingerprint counts them
    planted = [element for element in timeline.main if element.tag == 'transition' or (
        element.tag == 'filter' and 'track' in timeline_model.props(element))]
    attached = [element for element in timeline.main if element.tag == 'filter' and element not in planted]
    for element in planted + [None] + attached:
        if element is None:
            result.update(b'|timeline filters')
            continue
        if element.tag == 'transition' and timeline_model.props(element).get('mlt_service') in AUDIO_TRANSITIONS:
            continue
        if element.tag in ('transition', 'filter'):
            element = copy.deepcopy(element)
            for prop in element.findall('property'):
                if prop.get('name') in ('a_track', 'b_track'):
                    prop.text = tokens.get((prop.text or '').strip(), prop.text)
            result.update(('|' + timeline.canon(element)).encode('utf-8', 'replace'))
    return result.hexdigest()


def _reachable(timeline, elements):
    """The elements a render of these draws from: each one and every producer its entries and tracks name, nested."""
    seen, out, todo = set(), [], [element for element in elements if element is not None]
    while todo:
        element = todo.pop()
        if id(element) in seen:
            continue
        seen.add(id(element))
        out.append(element)
        for child in element.iter():
            if child.tag in ('entry', 'track') and child.get('producer') in timeline.elements:
                todo.append(timeline.elements[child.get('producer')])
    return out


def kept_picture(key, frames, fps):
    """The kept render for `key` when it opens with exactly `frames` frames at `fps`, else None."""
    path = pictures_folder() / f'{key[:32]}.mkv'
    if not path.is_file():
        return None
    capture = cv2.VideoCapture(str(path))
    try:
        whole = (capture.isOpened() and int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == frames
                 and abs(capture.get(cv2.CAP_PROP_FPS) - fps) <= .001)
    finally:
        capture.release()
    if not whole:
        return None
    try:
        os.utime(path)          # recently used
    except OSError:
        pass
    return path


def keep_picture(key, rendered):
    """Keep a finished, checked render under `key` (a copy), and remove the least recently used beyond PICTURE_KEEP
    or PICTURE_KEEP_BYTES in all (the newest stays). A failure to keep it never fails the measurement."""
    if not key:
        return
    try:
        folder = pictures_folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{key[:32]}.mkv'
        temporary = folder / f'{key[:32]}.{uuid.uuid4().hex[:8]}.tmp'
        shutil.copyfile(rendered, temporary)
        temporary.replace(target)
        kept = sorted(folder.glob('*.mkv'), key=lambda path: path.stat().st_mtime, reverse=True)
        total = 0
        for i, path in enumerate(kept):
            total += path.stat().st_size
            if i and (i >= PICTURE_KEEP or total > PICTURE_KEEP_BYTES):
                path.unlink(missing_ok=True)
    except OSError:
        pass


def render_or_reuse(xml, output, frames, fps, settings, render):
    """`render()` writes `output`, a render of `xml`; when a kept render draws the same picture (picture_key) it is
    copied there instead. Returns the key and whether the kept one was used. Only a render the caller has checked
    should be kept: call keep_picture(key, output) after the check."""
    try:
        key = picture_key(xml, frames, settings)
    except Exception:  # noqa: BLE001 - a file this can't key is rendered, as before, and not kept
        key = None
    kept = kept_picture(key, frames, fps) if key else None
    if kept is not None:
        shutil.copyfile(kept, output)
        return key, True
    render()
    return key, False


def measurement_key(parts):
    return hashlib.sha256(json.dumps({'version': PICTURE_VERSION, **parts}, sort_keys=True, default=str).encode()).hexdigest()


def kept_measurement(key):
    try:
        return json.loads((pictures_folder() / 'measurements.json').read_text(encoding='utf-8-sig')).get(key)
    except (OSError, ValueError, AttributeError):
        return None


def keep_measurement(key, result):
    """Keep a finished measurement under `key` (the newest MEASURE_KEEP); a failure to keep it changes nothing."""
    try:
        folder = pictures_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'measurements.json'
        try:
            kept = json.loads(path.read_text(encoding='utf-8-sig'))
            kept = kept if isinstance(kept, dict) else {}
        except (OSError, ValueError):
            kept = {}
        kept.pop(key, None)
        kept[key] = json.loads(json.dumps(result, default=str))
        temporary = folder / f'measurements.{uuid.uuid4().hex[:8]}.tmp'
        temporary.write_text(json.dumps(dict(list(kept.items())[-MEASURE_KEEP:])), encoding='utf-8')
        temporary.replace(path)
    except (OSError, TypeError, ValueError):
        pass


def caption_item(item):
    if (item.get('motion') or {}).get('params', {}).get('readability') == 'edge-layer':
        return False
    return (item.get('motion') or {}).get('block') == 'kinetic_type' or (item.get('graphic') or {}).get('template') == 'word_captions'


def edge_item(item):
    return (item.get('motion') or {}).get('params', {}).get('readability') == 'edge-layer'


def without_generated_blend(script):
    result = copy.deepcopy(script)
    for track in result['tracks']:
        for item in track['items']:
            if not caption_item(item) and not edge_item(item):
                continue
            mode = (item.get('motion') or {}).get('params', {}).get('blend', 'normal')
            effects = [effect for effect in item.get('effects', [])
                       if effect != {'filter': 'cairoblend_mode', 'params': {'mode': mode}}]
            if effects:
                item['effects'] = effects
            else:
                item.pop('effects', None)
    return result


def outline_script(script, solid=False):
    result = without_generated_blend(script)
    tracks = []
    count = 0
    for track in result['tracks']:
        if any(edge_item(item) for item in track['items']):
            if any('id' in item and not edge_item(item) for item in track['items']):
                raise ValueError('Caption edge companions need a dedicated track')
            continue
        captions = [item for item in track['items'] if caption_item(item)]
        if captions:
            if any('id' in item and not caption_item(item) for item in track['items']):
                raise ValueError('Uniform aid needs dedicated caption tracks')
            companion = copy.deepcopy(track)
            companion['name'] = track['name'] + ' dark edge'
            for item in track['items']:
                if not caption_item(item):
                    continue
                if 'motion' not in item:
                    raise ValueError('Uniform aid currently supports kinetic_type only')
                params = item['motion'].setdefault('params', {})
                params.update(blend='normal' if solid else 'difference', readability='solid' if solid else 'edge')
                count += 1
            companion['items'] = copy.deepcopy(track['items'])
            for item in companion['items']:
                if 'id' in item:
                    item['id'] += '-dark-edge'
                    item['motion']['params'].update(blend='normal', readability='edge-layer')
            tracks.append(companion)
        tracks.append(track)
    if not count:
        raise ValueError('No kinetic captions to outline')
    result['tracks'] = tracks
    return result


def luminance(frame):
    channels = frame[..., ::-1].astype(np.float32) / 255
    linear = np.where(channels <= .04045, channels / 12.92, ((channels + .055) / 1.055) ** 2.4)
    return linear @ np.array([.2126, .7152, .0722], np.float32)


def ratios(first, second):
    return (np.maximum(first, second) + .05) / (np.minimum(first, second) + .05)


def solid_contrast(actual, ink, plate):
    if not ink.any() or not plate.any():
        return 0.
    boundary = ink & ~cv2.erode(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    nearby = cv2.dilate(plate.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    if not np.all(nearby[boundary]):
        return 0.
    return float(ratios(actual[ink], np.full(ink.sum(), float(actual[plate].max()))).min())


def word_span(word, params, item):
    offset = params.get('offset', 0) + edit_script.to_seconds(item.get('skip', 0))
    return word['start'] - offset, word['end'] - offset


# ------------------------------------------------------------------ word_captions graphics, as the template draws them

MEASURE_VERSION = 3        # in the kept measurements' keys beside a project: 2 measures word_captions graphics, 3 by 95% of each
                           # word's edge, each edge pixel by its strongest surround within 2 px
WORD_CORE = .95            # a phone-size pixel this much inside a letter's fill is a letter core
WORD_RING_PX = 2           # the surround read around each word's letters, in phone-size pixels: at each pixel of a
                           # letter's edge, the strongest contrast within this distance (a thin outline is a pixel or
                           # two at phone size, and the first pixel out blends letter and surround in a scaled picture)
WORD_AGREE = .9            # share of the drawn letters' cores the rendered ink must hold, or the frame is unmeasured
WORD_STRAY = .05           # rendered ink where nothing is drawn, as a share of the drawn ink, before it is unmeasured
WORD_KEEP_AT = 5           # times kept per word for frames under the floor
WORD_RING_SHARE = .05      # a word's contrast is the one all but this share of the ring around its letters meets


def _word_masks_class():
    """A graphics.Ctx that draws a word_captions frame as masks: each word's letter fill (what its fill colour
    covers) and everything the frame draws (fill, outline, shadow, boxes), at the project's size, with each word's
    boxes and the frame's fade. The text and shapes go through the same Pillow calls the template's own drawing makes."""
    import letitedit.pictures.graphics as graphics
    from PIL import Image, ImageDraw, ImageFilter

    class WordMasks(graphics.Ctx):
        def __init__(self, width, height, fps, length, t, frame, params, kit, texts):
            super().__init__(1, 1, fps, length, t, frame, params, kit)
            self.w, self.h, self.scale = width, height, height / 1080.0
            self.fill = Image.new('L', (width, height), 0)
            self.drawn = Image.new('L', (width, height), 0)
            self.canvas = self.drawn
            self.texts, self.used, self.words, self.opacity = texts, set(), [], 1.

        def layer(self):
            return Image.new('L', (1, 1))     # the words still go to the masks; paste says how faded they are

        def paste(self, layer, dx=0, dy=0, opacity=1.0):
            if dx or dy:
                raise ValueError('word_captions moved a layer; its words cannot be placed')
            self.opacity = min(self.opacity, float(opacity))

        def rect(self, box, fill=None, radius=0, outline=None, width=0, on=None):
            super().rect(box, fill=self._opacity(fill), radius=radius, outline=self._opacity(outline), width=width,
                         on=self.drawn)

        def _c(self, ref):
            return ref if isinstance(ref, int) else super()._c(ref)

        def _opacity(self, ref):
            """A colour's own opacity, 0-255, as the drawn mask's value (a translucent box or shadow is drawn
            translucent), or None for no colour."""
            return None if ref is None else int(super()._c(ref)[3])

        def text(self, xy, text, font_ref='body', size=54, fill='light', anchor='la', align='left', outline=None,
                 outline_width=0, shadow=None, shadow_offset=(4, 5), shadow_blur=0, opacity=1.0, on=None,
                 letter_spacing=0):
            if letter_spacing:
                raise ValueError('word_captions drew spaced letters; their words cannot be placed')
            text = str(text)
            f = self.font(font_ref, size)
            sw = int(round(self.s(outline_width))) if outline else 0
            spacing = int(self.s(size) * 0.15)
            if shadow:
                sx, sy = xy[0] + self.s(shadow_offset[0]), xy[1] + self.s(shadow_offset[1])
                mark = Image.new('L', (self.w, self.h), 0)
                ImageDraw.Draw(mark).multiline_text((sx, sy), text, font=f, fill=255, anchor=anchor, align=align,
                                                    stroke_width=sw, stroke_fill=255, spacing=spacing)
                if shadow_blur:
                    mark = mark.filter(ImageFilter.GaussianBlur(self.s(shadow_blur)))
                self.drawn.paste(self._opacity(shadow), mask=mark)
            ImageDraw.Draw(self.drawn).multiline_text(xy, text, font=f, fill=self._opacity(fill) or 0, anchor=anchor,
                                                      align=align, stroke_width=sw,
                                                      stroke_fill=self._opacity(outline) if outline else None,
                                                      spacing=spacing)
            ImageDraw.Draw(self.fill).multiline_text(xy, text, font=f, fill=255, anchor=anchor, align=align,
                                                     stroke_width=sw, stroke_fill=0 if outline else None,
                                                     spacing=spacing)
            draw = ImageDraw.Draw(self.drawn)
            box = draw.multiline_textbbox(xy, text, font=f, anchor=anchor, align=align, stroke_width=sw,
                                          spacing=spacing)
            letters = draw.multiline_textbbox(xy, text, font=f, anchor=anchor, align=align, spacing=spacing)
            index = next((i for i, said in enumerate(self.texts) if said == text and i not in self.used), None)
            if index is None:
                raise ValueError(f'word_captions drew {text!r}, which is not one of its words')
            self.used.add(index)
            self.words.append({'index': index, 'text': text, 'box': tuple(map(float, box)),
                               'letters': tuple(map(float, letters))})
            return box

    return WordMasks


class WordCaptionItem:
    """One word_captions clip on the timeline, drawn frame by frame the way its file was drawn: the stored recipe,
    the project's kit (or the one frozen in the recipe), the project's size and frame rate, the template the kit
    resolves, and the template's own frame_key holds. `drawn_file_matches` says whether that recipe names the very
    file the clip plays; each frame is also checked against the rendered ink when it is measured."""

    def __init__(self, item_id, recipe, start, entry_in, length, file_frames, script, timeline, width, height):
        import letitedit.pictures.graphics as graphics
        self.id, self.start, self.entry_in, self.length = item_id, start, entry_in, length
        self.fps, self.width, self.height = timeline.fps, script['profile']['width'], script['profile']['height']
        self.measure_size = (width, height)
        kit = edit_script.kit_for(script)          # what the compiler hands graphics.render
        self.recipe = graphics.normalise({'template': 'word_captions', 'params': recipe.get('params') or {},
                                          'len': file_frames / self.fps}, kit)
        self.kit = graphics.drawing_kit(self.recipe, kit)     # and what draw_frames draws with
        self.module = graphics._resolve_template(self.recipe, self.kit)
        stem = Path(str(recipe.get('file') or '')).stem
        self.drawn_file_matches = bool(stem) and stem == (
            f"word_captions-{graphics._digest(self.recipe, kit, self.width, self.height, self.fps)}")
        params = self.recipe['params']
        # The compiled file is reused when its clip is unchanged. Redraw saved legacy files with their original fade.
        if stem and not recipe.get('readable_word_hold') and not self.drawn_file_matches:
            params['_legacy_word_fade'] = True
        self.texts = [str(w[0]).upper() if params.get('uppercase') else str(w[0]) for w in params['words']]
        self.starts = [float(w[1]) for w in params['words']]
        self.frames = max(1, int(round(self.recipe['len'] * self.fps)))
        self._holds = self._hold_frames()
        self._kept = {}

    def _hold_frames(self):
        """For each frame of the file, the frame whose drawing it shows (the template's frame_key holds)."""
        import letitedit.pictures.graphics as graphics
        key_fn = getattr(self.module, 'frame_key', None)
        holds, last_key, shown = [], object(), 0
        for k in range(self.frames):
            if key_fn is None:
                holds.append(k)
                continue
            key = key_fn(graphics.Ctx(1, 1, self.fps, self.recipe['len'], k / self.fps, k, self.recipe['params'],
                                      self.kit))
            if key != last_key or k == 0:
                shown, last_key = k, key
            holds.append(shown)
        return holds

    def file_frame(self, timeline_frame):
        k = timeline_frame - self.start + self.entry_in
        return k if self.start <= timeline_frame < self.start + self.length and 0 <= k < self.frames else None

    def layout(self, k):
        """{'opacity', 'words': [{index, text, box, letters (phone-size pixels)}], 'fill', 'drawn' (phone-size
        coverage, 0-1)} of file frame k."""
        shown = self._holds[k]
        if shown not in self._kept:
            if len(self._kept) > 8:
                self._kept.clear()
            ctx = _word_masks_class()(self.width, self.height, self.fps, self.recipe['len'], shown / self.fps, shown,
                                      self.recipe['params'], self.kit, self.texts)
            self.module.draw(ctx)
            mw, mh = self.measure_size
            sx, sy = mw / self.width, mh / self.height
            fill = cv2.resize(np.asarray(ctx.fill), (mw, mh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
            drawn = cv2.resize(np.asarray(ctx.drawn), (mw, mh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
            words = [{**word, 'box': (word['box'][0] * sx, word['box'][1] * sy, word['box'][2] * sx, word['box'][3] * sy),
                      'letters': (word['letters'][0] * sx, word['letters'][1] * sy, word['letters'][2] * sx,
                                  word['letters'][3] * sy)} for word in ctx.words]
            self._kept[shown] = {'opacity': ctx.opacity, 'words': words, 'fill': fill, 'drawn': drawn}
        return self._kept[shown]


def _pixel_box(box, shape, pad=0):
    height, width = shape
    return (max(0, int(np.floor(box[0])) - pad), max(0, int(np.floor(box[1])) - pad),
            min(width, int(np.ceil(box[2])) + pad), min(height, int(np.ceil(box[3])) + pad))


def _held(drawn, ink):
    """Whether the rendered ink holds WORD_AGREE of a drawn shape, read 1 px inside the shape where it has an inside
    (at its edges the export engine's scaler and this redraw's may differ by a pixel; a thin letter is mostly edge)."""
    inner = cv2.erode(drawn.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    shape = inner if inner.any() else drawn
    return (shape & ink).sum() >= WORD_AGREE * shape.sum()


def word_frame_value(actual, ink, visible, fill, drawn, word, floor=4.5):
    """(contrast, None, detail) for one drawn word on one phone-size frame, or (0, why, {}) when it can't be measured
    there. Each pixel up to WORD_RING_PX outside the word's letters (whatever is there: its outline, a box, a
    highlight or the picture) is compared with the nearest letter core's own pixel (WCAG ratio); each pixel along the
    letters' edge takes the strongest of those within WORD_RING_PX of it (is something separating there); the
    contrast is the one all but WORD_RING_SHARE of the edge meets (a descender tip past a box's edge is a few pixels,
    a word over a pale patch is far more). detail: the edge's lowest value and the share of the edge under `floor`.
    Before that,
    the rendered ink must agree with the drawing: WORD_AGREE of the drawn letter cores and of the drawn solid ink are
    rendered opaque, and no more than WORD_STRAY of the drawn ink is rendered where nothing is drawn."""
    pad = WORD_RING_PX + 2
    x0, y0, x1, y1 = _pixel_box(word['box'], ink.shape, pad)
    if x1 <= x0 or y1 <= y0:
        return 0., 'off the frame', {}
    crop = (slice(y0, y1), slice(x0, x1))
    a, k, v, f, d = actual[crop], ink[crop], visible[crop], fill[crop], drawn[crop]
    own = np.zeros(k.shape, bool)
    lx0, ly0, lx1, ly1 = _pixel_box(word['letters'], ink.shape, 1)
    own[max(0, ly0 - y0):max(0, ly1 - y0), max(0, lx0 - x0):max(0, lx1 - x0)] = True
    cores = (f >= WORD_CORE) & own
    if not cores.any():
        return 0., 'no letter core at phone size', {}
    if not _held(cores, k):
        return 0., 'the rendered ink does not hold the drawn letters', {}
    solid = (d >= WORD_CORE) & cv2.dilate(own.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    if solid.any() and not _held(solid, k):
        return 0., 'the rendered ink does not hold the drawn outline or box', {}
    near = cv2.dilate((d > .02).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if (v & ~near).sum() > max(4, WORD_STRAY * (d > .5).sum()):
        return 0., 'rendered ink where the drawing has none', {}
    letters = f > .05
    reach = np.ones((2 * WORD_RING_PX + 1, 2 * WORD_RING_PX + 1), np.uint8)
    ring = cv2.dilate((letters & own).astype(np.uint8), reach).astype(bool) & ~letters
    edge = cv2.dilate((letters & own).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~letters
    if not ring.any() or not edge.any():
        return 0., 'no surround around the letters', {}
    cores &= k
    _, labels = cv2.distanceTransformWithLabels((~cores).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    levels = np.zeros(int(labels.max()) + 1, np.float32)
    levels[labels[cores]] = a[cores]
    contrast = np.zeros(ring.shape, np.float32)
    contrast[ring] = ratios(a[ring], levels[labels[ring]])
    values = cv2.dilate(contrast, reach)[edge]          # the strongest separation near each pixel of the edge
    return (float(np.percentile(values, WORD_RING_SHARE * 100)), None,
            {'lowest_pixel': float(values.min()), 'under_share': float((values < floor).mean())})


def word_caption_items(script, timeline, names, width, height):
    """{item id: WordCaptionItem} for the word_captions clips on the caption tracks `names`, read from the timeline
    file itself (the recipe and file each clip stores, where it starts, its in point and its file's length), or
    {'reason'} when one can't be placed."""
    import letitedit.timeline.timeline_model as timeline_model
    found = {}
    for track in timeline.tracks:
        if track.name not in names:
            continue
        for entry in track.items:
            element = entry.elem
            if element is None:
                continue
            properties = timeline_model.props(element)
            try:
                recipe = json.loads(properties.get(edit_script.GRAPHIC_PROP) or 'null')
            except ValueError:
                recipe = None
            if not isinstance(recipe, dict) or recipe.get('template') != 'word_captions':
                continue
            item_id = properties.get(edit_script.ID_PROP)
            try:
                file_frames = int(float(properties.get('length') or 0))
            except ValueError:
                file_frames = 0
            if not item_id or file_frames <= 0:
                return {'reason': f'A word_captions clip on {track.name} has no id or file length, so its words '
                                  'cannot be placed (unmeasured)'}
            found[item_id] = WordCaptionItem(item_id, recipe, entry.start, entry.in_, entry.length, file_frames,
                                             script, timeline, width, height)
    return found


def _word_row(item, words):
    return {'frames': 0, 'minimum': 21., 'below_floor_frames': 0, 'unmeasured_frames': 0, 'fading_frames': 0,
            'kind': 'word_captions', 'drawn_file_matches': item.drawn_file_matches,
            'words': {index: {'text': text, 'frames': 0, 'minimum': 21., 'below_floor_frames': 0,
                              'unmeasured_frames': 0, 'below_floor_at': [], 'unmeasured': {}}
                      for index, text in words}}


def measure_word_caption_frame(rows, items, frame_index, fps, actual, ink, visible, floor):
    """Measure every word_captions word drawn on this timeline frame into `rows` (per clip and per word: frames,
    minimum, frames under the floor with their times, unmeasured frames with why). A frame while the caption fades out
    is counted as fading, not measured."""
    at = round(frame_index / fps, 3)
    for item in items.values():
        k = item.file_frame(frame_index)
        if k is None:
            continue
        row = rows[item.id]
        try:
            drawing = item.layout(k)
        except Exception as error:  # noqa: BLE001 - a frame whose words can't be placed is unmeasured, never passed
            row['frames'] += 1
            row['unmeasured_frames'] += 1
            row['minimum'] = 0.
            row.setdefault('unplaced', str(error))
            continue
        if not drawing['words']:
            continue
        if drawing['opacity'] < .999:
            row['fading_frames'] += 1
            for word in drawing['words']:      # a word first drawn here is only ever seen fading
                row['words'][word['index']].setdefault('fading_at', at)
            continue
        row['frames'] += 1
        values, missing = [], False
        for word in drawing['words']:
            value, why, detail = word_frame_value(actual, ink, visible, drawing['fill'], drawing['drawn'], word, floor)
            cell = row['words'][word['index']]
            cell['frames'] += 1
            if detail:
                cell['lowest_pixel'] = round(min(cell.get('lowest_pixel', 21.), detail['lowest_pixel']), 3)
                cell['most_under_share'] = round(max(cell.get('most_under_share', 0.), detail['under_share']), 4)
            if value < cell['minimum']:
                cell['minimum'], cell['worst_at'] = value, at
                cell['worst_box'] = [round(word['box'][0] / ink.shape[1], 4), round(word['box'][1] / ink.shape[0], 4),
                                     round(word['box'][2] / ink.shape[1], 4), round(word['box'][3] / ink.shape[0], 4)]
            if why:
                cell['unmeasured_frames'] += 1
                cell['unmeasured'][why] = cell['unmeasured'].get(why, 0) + 1
                missing = True
            elif value < floor:
                cell['below_floor_frames'] += 1
                if len(cell['below_floor_at']) < WORD_KEEP_AT:
                    cell['below_floor_at'].append(at)
            values.append(value)
        row['minimum'] = min(row['minimum'], min(values))
        row['below_floor_frames'] += int(min(values) < floor)
        row['unmeasured_frames'] += int(missing)


def _render_caption_layers(aided, cache_budget, edge_selected, height, keys, main, path, paths, render_lock,
        root, selected, timeline, timeline_model, video, work):
    for mode in (('background', 'black', 'white', 'aid', 'composite') if aided else ('background', 'black', 'white', 'composite')):
        cache_budget.need_room(checks.CACHE, 1024 ** 3, 'measure captions', cache=checks.CACHE)
        if mode == 'composite' and video:
            paths[mode] = str(video)
            continue
        variant = copy.deepcopy(root)
        variant.set('root', str(Path(path).parent))
        current = next(element for element in variant.findall('tractor') if element.get('id') == main.get('id'))
        for index, track in enumerate(current.findall('track')):
            if track.get('producer') == 'background':
                continue
            if ((mode == 'background' and index in selected + edge_selected)
                    or (mode in ('black', 'white') and index not in selected)
                    or (mode == 'aid' and index not in edge_selected)):
                track.set('hide', 'both')
        if mode in ('black', 'white', 'aid'):
            for transition in current.findall('transition'):
                properties = timeline_model.props(transition)
                if properties.get('mlt_service') == 'frei0r.cairoblend' and int(properties.get('b_track', -1)) in selected + edge_selected:
                    for prop in transition.findall('property'):
                        if prop.get('name') == 'a_track':
                            prop.text = '0'
                        elif prop.get('name') == 'disable':
                            prop.text = '0'
            for producer in list(variant.findall('producer')) + list(variant.findall('chain')):
                if producer.get('id') in ('black', 'background'):
                    for prop in producer.findall('property'):
                        if prop.get('name') == 'resource':
                            prop.text = '#ffffffff' if mode in ('white', 'aid') else '#ff000000'
            for parent in variant.iter():
                for effect in list(parent.findall('filter')):
                    if 'cairoblend_mode' in str(timeline_model.props(effect)):
                        parent.remove(effect)
        xml = work / (mode + '.mlt')
        ET.ElementTree(variant).write(xml, encoding='utf-8', xml_declaration=True)
        output = work / (mode + '.mkv')
        arguments = ['in=0', f'out={timeline.frames - 1}', 'vcodec=ffv1', 'an=1', 'width=360', f'height={height}',
                     f'frame_rate_num={timeline.profile["frame_rate_num"]}',
                     f'frame_rate_den={timeline.profile["frame_rate_den"]}', 'sample_aspect_num=1',
                     'sample_aspect_den=1', 'progressive=1']

        def render(xml=xml, output=output):
            with render_lock.slot('caption-whole-time', timeout_s=600):
                checks._run([checks.MELT, '-quiet', xml, 'in=0', f'out={timeline.frames - 1}', '-consumer',
                             f'avformat:{output}', 'vcodec=ffv1', 'an=1', 'threads=4', 'real_time=-4',
                             'width=360', f'height={height}', f'frame_rate_num={timeline.profile["frame_rate_num"]}',
                             f'frame_rate_den={timeline.profile["frame_rate_den"]}', 'sample_aspect_num=1',
                             'sample_aspect_den=1', 'progressive=1'], timeout=600)
        keys[mode] = render_or_reuse(xml, output, timeline.frames, timeline.fps, arguments, render)
        paths[mode] = str(output)


def _measure_caption_frames(aided, floor, height, items, records, schedules, streams, timeline, word_items=None):
    word_items = word_items or {}
    frame_index = 0
    try:
        while frame_index < timeline.frames:
            frames = {}
            for name, stream in streams.items():
                okay, frame = stream.read()
                if not okay:
                    raise ValueError(f'{name}: missing native frame {frame_index}')
                frames[name] = cv2.resize(frame, (360, height), interpolation=cv2.INTER_AREA)
            alpha = 1 - np.max(np.abs(frames['white'].astype(float) - frames['black'].astype(float)), axis=2) / 255
            visible = alpha > .05
            ink = alpha > .95
            value = 0.
            if word_items:
                measure_word_caption_frame(records, word_items, frame_index, timeline.fps,
                                           luminance(frames['composite']), ink, visible, floor)
            if ink.any() and schedules:
                actual = luminance(frames['composite'])
                if aided:
                    plate = (luminance(frames['aid']) < .1) & ~ink
                    value = aided_contrast(actual, luminance(frames['background']), ink, plate, floor)[0]
                else:
                    value = float(ratios(actual[ink], luminance(frames['background'])[ink]).min())
            at = frame_index / timeline.fps
            for item in items:
                if item['id'] not in schedules:
                    continue
                start = edit_script.to_seconds(item['at'])
                expected = [word for word in schedules[item['id']] if word['start'] <= at - start < word['end']]
                if start <= at < start + item['len'] and expected:
                    row = records[item['id']]
                    row['frames'] += 1
                    values = []
                    missing = False
                    for word in expected:
                        left, top, right, bottom = word['bounds']
                        region = np.zeros(ink.shape, bool)
                        region[max(0, int(top * height)):min(height, int(np.ceil(bottom * height))),
                               max(0, int(left * 360)):min(360, int(np.ceil(right * 360)))] = True
                        cores = ink & region
                        measured = bool(cores.any() and (visible & region).any())
                        word_value = value if measured else 0.
                        if measured and aided:
                            word_value, edge_value = aided_contrast(actual, luminance(frames['background']), cores, plate & region, floor)
                            word_row = row['words'][word['index']]
                            word_row['edge_picture_minimum'] = min(word_row.get('edge_picture_minimum', 21.), edge_value)
                        elif measured:
                            word_value = float(ratios(actual[cores], luminance(frames['background'])[cores]).min())
                        word_row = row['words'][word['index']]
                        word_row['frames'] += 1
                        word_row['minimum'] = min(word_row['minimum'], word_value)
                        word_row['below_floor_frames'] += int(word_value < floor)
                        word_row['unmeasured_frames'] += int(not measured)
                        values.append(word_value)
                        missing |= not measured
                    row['minimum'] = min(row['minimum'], min(values))
                    row['below_floor_frames'] += int(min(values) < floor)
                    row['unmeasured_frames'] += int(missing)
            frame_index += 1
    finally:
        for stream in streams.values():
            stream.release()
    return frame_index


def measure(project, video=None, floor=4.5):
    import letitedit.core.cache_budget as cache_budget
    import letitedit.core.render_lock as render_lock
    import letitedit.timeline.timeline_model as timeline_model
    cache_budget.need_room(checks.CACHE, 2 * 1024 ** 3, 'measure captions', cache=checks.CACHE)
    _, path, script = current_project(project)
    timeline, path = checks.resolve(path)
    tracks = [track for track in script['tracks'] if any(caption_item(item) for item in track['items'])]
    if not tracks:
        return {'passed': False, 'applicable': False,
                'reason': 'No kinetic_type or word_captions tracks to measure here; burned-in (native) caption tracks '
                          'are measured separately'}
    if any(any('id' in item and not caption_item(item) for item in track['items']) for track in tracks):
        return {'passed': False, 'unsupported': 'mixed tracks',
                'reason': 'Unsupported: kinetic_type or word_captions items share a track with other items, and this '
                          'measurement and its colour and edge treatments work only on tracks of their own; burned-in '
                          '(native) caption tracks are measured separately'}
    names = {track['name'] for track in tracks}
    items = [item for track in tracks for item in track['items'] if caption_item(item)]
    edge_names = {track['name'] for track in script['tracks'] if any(edge_item(item) for item in track['items'])}
    treatments = {(item.get('motion') or {}).get('params', {}).get('readability') for item in items}
    if len(treatments) > 1:
        return {'passed': False, 'reason': 'Mixed caption aids are not a uniform caption treatment'}
    aided = treatments <= {'edge', 'solid'}
    if aided:
        expected = outline_script(script, solid=all(item['motion']['params'].get('readability') == 'solid' for item in items))
        if expected['tracks'] != without_generated_blend(script)['tracks']:
            return {'passed': False, 'reason': 'Dark-edge companions are absent, changed or unsynchronized; reapply uniform edge'}
    solid = all((item.get('motion') or {}).get('params', {}).get('readability') == 'solid' for item in items)
    records = {item['id']: {'frames': 0, 'minimum': 21., 'below_floor_frames': 0, 'unmeasured_frames': 0}
               for item in items}
    schedules = {}
    height = round(script['profile']['height'] * 360 / script['profile']['width'] / 2) * 2
    word_items = {}
    if any('motion' not in item for item in items):
        word_items = word_caption_items(script, timeline, names, 360, height)
        if 'reason' in word_items:
            return {'passed': False, **word_items}
        unplaced = [item['id'] for item in items if 'motion' not in item and item['id'] not in word_items]
        if unplaced:
            return {'passed': False, 'reason': f"word_captions items {', '.join(unplaced[:5])} were not found on the "
                                               'timeline file with their recipe, so their words cannot be placed '
                                               '(unmeasured)'}
        for item in items:
            if 'motion' not in item:
                drawn = word_items[item['id']]
                records[item['id']] = _word_row(drawn, enumerate(drawn.texts))
    for item in items:
        if 'motion' not in item:
            continue
        import letitedit.pictures.motion as motion
        import letitedit.looks.kinetic_type as kinetic_type
        params = motion.normalise(item['motion'])['params']
        schedules[item['id']] = []
        for index, word in enumerate(params['words']):
            settings = {'x': .5, 'y': .5, 'size': .05, 'font': params['font'], 'align': 'center'}
            settings.update((params.get('roles') or {}).get(word.get('role'), {}))
            settings.update(word)
            settings['readability'] = params.get('readability')
            if settings['align'] != 'center':
                return {'passed': False, 'reason': 'Non-centred manual words need verified bounds'}
            bounds = kinetic_type.envelope(settings, script['profile']['width'], script['profile']['height'])
            start, end = word_span(word, params, item)
            schedules[item['id']].append({'index': index, 'text': word['text'], 'bounds': bounds,
                'start': start, 'end': end})
        records[item['id']]['words'] = {word['index']: {'text': word['text'], 'frames': 0, 'minimum': 21.,
            'below_floor_frames': 0, 'unmeasured_frames': 0} for word in schedules[item['id']]}
    cv2.setNumThreads(4)
    checks.CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='caption-ink-', dir=checks.CACHE) as folder:
        work = Path(folder)
        root = ET.parse(path).getroot()
        tractors = root.findall('tractor')
        main = next((element for element in reversed(tractors) if timeline_model.props(element).get('shotcut') == '1'), tractors[-1])
        caption_ids = {element.get('id') for element in root.findall('playlist')
                       if timeline_model.props(element).get('shotcut:name') in names}
        selected = [index for index, track in enumerate(main.findall('track')) if track.get('producer') in caption_ids]
        edge_ids = {element.get('id') for element in root.findall('playlist')
                    if timeline_model.props(element).get('shotcut:name') in edge_names}
        edge_selected = [index for index, track in enumerate(main.findall('track')) if track.get('producer') in edge_ids]
        if len(selected) != len(tracks):
            return {'passed': False, 'reason': 'Caption track routing could not be resolved'}
        paths = {}
        keys = {}
        _render_caption_layers(aided, cache_budget, edge_selected, height, keys, main, path, paths,
            render_lock, root, selected, timeline, timeline_model, video, work)
        streams = {name: cv2.VideoCapture(value) for name, value in paths.items()}
        for name, stream in streams.items():
            if (abs(stream.get(cv2.CAP_PROP_FPS) - timeline.fps) > .001
                    or int(stream.get(cv2.CAP_PROP_FRAME_COUNT)) != timeline.frames):
                for opened in streams.values():
                    opened.release()
                raise ValueError(f'{name}: native frame rate/count differs from the timeline')
        for mode, (key, reused) in keys.items():
            if not reused:
                keep_picture(key, paths[mode])
        frame_index = _measure_caption_frames(aided, floor, height, items, records, schedules, streams,
            timeline, word_items)
    unsampled = [{'item': item['id'], 'word': word['text']} for item in items if item['id'] in schedules
                 for word in schedules[item['id']] if word['start'] < item['len'] and word['end'] > 0
                 and not records[item['id']]['words'][word['index']]['frames']]
    for drawn in word_items.values():       # a word said before the clip's end is drawn on its frames
        shown_until = (drawn.entry_in + drawn.length) / drawn.fps
        unsampled += [{'item': drawn.id, 'word': text} for index, text in enumerate(drawn.texts)
                      if drawn.starts[index] < shown_until - 1 / drawn.fps
                      and not records[drawn.id]['words'][index]['frames']]
    passed = all(row['frames'] and not row['below_floor_frames'] for row in records.values()) and not unsampled
    result = {'passed': bool(passed), 'project_sha256': project_digest(script), 'video_sha256': digest(video) if video else None,
            'coverage': 'every_native_frame', 'width': 360, 'floor': floor, 'frames_decoded': frame_index,
            'minimum': min(row['minimum'] for row in records.values()), 'captions': records,
            'unsampled_words': unsampled,
            'method': 'Every native frame at phone size: opaque ink cores against picture or the darkest calibrated edge. Each glyph boundary needs a calibrated edge within three pixels; its strongest local edge-to-picture/nearest-core contrast or core-to-picture contrast must meet the floor. Missing cores or disconnected contours fail. Edge versus picture minimum is reported separately, not claimed above the floor. Overlapping word envelopes cannot prove separate glyph visibility.',
            'treatment': ('white fill' if solid else 'picture-coloured Difference fill') + ' with uniform thin normal dark edge' if aided else 'ink against underlying picture'}
    if word_items:
        result['word_captions'] = {'method': WORD_METHOD, 'findings': word_findings(records, floor)}
    return result


WORD_METHOD = ("word_captions clips: each frame of the clip's file is drawn again from its stored recipe with the "
               "template's own drawing (its layout, size, shrink to fit, position, pop or bounce scale, box and "
               "highlight, and frame holds), as masks at 360 px wide: each word's letter fill and all the ink the frame "
               "draws. A word is measured on a frame when the rendered caption layer holds at least 90% of its drawn "
               "letter cores and of its drawn outline or box, with no more than 5% stray ink; otherwise that frame is "
               "unmeasured (never passed). Each pixel up to 2 px outside its letters is compared with the nearest letter "
               "core (WCAG ratio); each pixel along the letters' edge takes the strongest of those within 2 px of it "
               "(an outline, a box or the picture separating the letters there); the word's contrast is the one 95% "
               "of its edge meets, with the lowest (lowest_pixel) and the largest share of the edge under the floor "
               "on a frame (most_under_share) reported. "
               "Those pixels are whatever is composited there: outline, box, highlight or picture. Frames while "
               "the caption fades out are counted as fading, not measured; a word drawn only on those frames is a finding "
               "(shown: only while its caption fades out). drawn_file_matches says whether that "
               "recipe names the exact file the clip plays.")


def word_findings(records, floor, limit=20):
    """The words under the floor or unmeasured, lowest first: [{item, word, minimum, worst_at (timeline seconds),
    worst_box (share of the frame), below_floor_at, below_floor_frames, unmeasured}], and the words drawn only while
    their caption fades out (never on a fully shown frame): {item, word, minimum 0, worst_at, shown}."""
    out = []
    for item_id, row in records.items():
        if row.get('kind') != 'word_captions':
            continue
        if row.get('unplaced'):
            out.append({'item': item_id, 'word': None, 'minimum': 0., 'unmeasured': {row['unplaced']: row['unmeasured_frames']}})
        for cell in row['words'].values():
            if cell['below_floor_frames'] or cell['unmeasured_frames']:
                out.append({'item': item_id, 'word': cell['text'], 'minimum': round(cell['minimum'], 2),
                            'worst_at': cell.get('worst_at'), 'worst_box': cell.get('worst_box'),
                            'below_floor_at': cell['below_floor_at'], 'below_floor_frames': cell['below_floor_frames'],
                            'lowest_pixel': cell.get('lowest_pixel'), 'most_under_share': cell.get('most_under_share'),
                            'unmeasured': cell['unmeasured']})
            elif not cell['frames'] and cell.get('fading_at') is not None:
                out.append({'item': item_id, 'word': cell['text'], 'minimum': 0., 'worst_at': cell['fading_at'],
                            'shown': 'only while its caption fades out', 'below_floor_frames': 0, 'unmeasured': {}})
    out.sort(key=lambda finding: finding['minimum'])
    return out[:limit]


def solidify(project):
    return outline(project, solid=True)


def outline(project, solid=False):
    _, _, script = current_project(project)
    captions = [item for track in script['tracks'] for item in track['items'] if caption_item(item)]
    if not captions or any('motion' not in item for item in captions):
        raise ValueError('Uniform fallback currently supports kinetic_type only; other caption kinds are unverified')
    import yaml
    import letitedit.server.timeline_tools as timeline_tools
    return timeline_tools.apply_project(project, script_yaml=yaml.safe_dump(outline_script(script, solid), sort_keys=False),
                                        label='Uniform white caption fallback' if solid else 'Uniform thin dark caption edges')


def aided_contrast(actual, background, ink, plate, floor=4.5):
    if not ink.any() or not plate.any():
        return 0., 0.
    boundary = ink & ~cv2.erode(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    near = cv2.dilate(plate.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    if not np.all(near[boundary]):
        return 0., 0.
    edge_level = float(actual[plate].min())
    core_contrast = np.maximum(ratios(actual[ink], background[ink]), ratios(actual[ink], edge_level))
    shape = float(core_contrast.min())
    edge_picture = ratios(actual[plate], background[plate])
    _, labels = cv2.distanceTransformWithLabels((~ink).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    core_levels = np.zeros(int(labels.max()) + 1, np.float32)
    core_levels[labels[ink]] = actual[ink]
    edge_fill = ratios(actual[plate], core_levels[labels[plate]])
    local_contrast = np.zeros(ink.shape, np.float32)
    local_contrast[plate] = np.maximum(edge_picture, edge_fill)
    strongest_edge = cv2.dilate(local_contrast, np.ones((7, 7), np.uint8))
    contour = float(np.maximum(strongest_edge[boundary],
                               ratios(actual[boundary], background[boundary])).min())
    return min(shape, contour), float(edge_picture.min())
