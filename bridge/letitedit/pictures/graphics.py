"""Python-made graphics: title cards, lower thirds, callouts, badges, chapter cards, end cards, or any custom drawing.

A graphic is a recipe {template, params, len} that Pillow draws at the project size in the active style pack's
colours and fonts. A graphic that never changes is one PNG; an animated one is a QuickTime Animation (.mov, alpha)
file. Files are named by a hash of the recipe, kit and size, kept in <project folder>/graphics, and reused: the same
recipe renders once. The edit script stores the recipe on the clip, so changing the text re-renders it.

Templates live in bridge/graphics_templates (and a pack's graphics/ folder). Each is a module with
    TITLE, DESCRIPTION, PARAMS (defaults), ANIMATED (bool), DEFAULT_LEN (seconds) and draw(ctx).
Custom drawing: {template: 'custom', code: 'def draw(ctx): ...'} runs in a separate Python process with a time limit.

Graphics can use the footage: ctx.still(clip, t) is any source frame as a picture, and a recipe with
source: {clip, in, out, speed?, fit?} gives draw(ctx) that clip's frame for every frame drawn (ctx.src), so Python can
process footage itself (freeze and annotate, split screens, cut-outs with ctx.matte, stylised looks...). Graphics with
a source are opaque H.264 unless params.alpha is true.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import copy
import hashlib
import importlib.util
import inspect
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import letitedit.catalogs.fonts as fonts
import letitedit.looks.style_pack as style_pack
import letitedit.looks.look_library as look_library

HERE = _paths.BRIDGE
TEMPLATES = HERE / 'graphics_templates'
FFMPEG = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app'))) / 'ffmpeg.exe'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
RECIPE_PROP = 'letitedit_ai:graphic'
CUSTOM_TIMEOUT = 120
CUSTOM_SECONDS_PER_FRAME = 0.5      # on top of CUSTOM_TIMEOUT: a long animated graphic gets more time
SOURCE_SECONDS_PER_FRAME = 1.0   # extra time limit per frame for custom code that processes footage


# ------------------------------------------------------------------ easing

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


EASES = {
    'linear': lambda x: x,
    'out': lambda x: 1 - (1 - x) ** 3,
    'in': lambda x: x ** 3,
    'in_out': lambda x: 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2,
    'back': lambda x: 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2,
    'elastic': lambda x: x if x in (0, 1) else 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1,
}


# ------------------------------------------------------------------ drawing context

_local = threading.local()


def _thread_fonts():
    """Loaded fonts, kept between frames (loading a font file for every frame is most of the drawing time)."""
    if not hasattr(_local, 'fonts'):
        _local.fonts = {}
    return _local.fonts


class Ctx:
    """What a template's draw(ctx) gets. Sizes in helpers are pixels at 1080p (scaled to the project); positions are
    pixels of this canvas (use ctx.w / ctx.h, or ctx.x(0.5) for fractions)."""

    def __init__(self, width, height, fps, length, t, frame, params, kit, src=None):
        self.w, self.h, self.fps, self.len = width, height, fps, length
        self._t, self._frame = t, frame
        # what this frame's drawing depended on: the time itself, an animation in progress, or the next time an
        # animation starts (until then the picture can't change, so the renderer holds it)
        self._timed, self._moving, self._next = False, False, float('inf')
        self.p = params
        self.kit = kit
        self.scale = height / 1080.0
        self.canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        self.src = src   # this frame of the recipe's source clip (RGBA, canvas size), or None
        self._fonts = {}

    # footage
    def still(self, clip, t, size=None):
        """A frame of any video or picture file at t seconds, as an RGBA picture (fitted inside `size` (w, h) if given)."""
        return still(clip, t, size or (self.w, self.h))

    def matte(self, img=None):
        """Mask (L picture, 255 = person) of the people in `img` (default: ctx.src), from the local cut-out model."""
        return person_matte(img if img is not None else self.src)

    def depth(self, img=None):
        """Depth (L picture, 255 = nearest) of `img` (default: ctx.src): put text behind the subject, blur the far."""
        return depth_map(img if img is not None else self.src)

    # sizes and positions
    def s(self, px):
        return px * self.scale

    def x(self, frac):
        return frac * self.w

    def y(self, frac):
        return frac * self.h

    # time
    @property
    def t(self):
        self._timed = True
        return self._t

    @property
    def frame(self):
        self._timed = True
        return self._frame

    def _phase(self, start, dur):
        x = (self._t - start) / dur
        if x <= 0:
            self._next = min(self._next, start)
        elif x < 1:
            self._moving = True
        return x

    def ease(self, name, x):
        return EASES.get(name, EASES['out'])(clamp(x))

    def anim_in(self, dur=0.45, delay=0.0, ease='out'):
        """0 -> 1 over `dur` seconds from `delay`."""
        return self.ease(ease, self._phase(delay, dur)) if dur > 0 else 1.0

    def anim_out(self, dur=0.4, ease='in'):
        """1 -> 0 over the last `dur` seconds."""
        if dur <= 0:
            return 1.0
        return 1 - self.ease(ease, self._phase(self.len - dur, dur))

    def visible(self, dur_in=0.45, dur_out=0.4):
        return min(self.anim_in(dur_in), self.anim_out(dur_out))

    # style
    def color(self, ref, alpha=None):
        r, g, b, a = self.kit.rgba(ref)
        if alpha is not None:
            a = int(round(a * clamp(alpha)))
        return (r, g, b, a)

    def font(self, ref, size):
        f = self.kit.font(ref, 'body')
        key = (f['family'], f['weight'], f['italic'], int(round(self.s(size))))
        cache = _thread_fonts()
        if key not in cache:
            if len(cache) > 256:
                cache.clear()
            cache[key] = fonts.pil_font(f['family'], max(4, key[3]), weight=f['weight'], italic=f['italic'])
        return cache[key]

    def layer(self):
        return Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))

    def paste(self, layer, dx=0, dy=0, opacity=1.0):
        """Composite a layer onto the canvas, moved by (dx, dy) and faded by opacity."""
        if opacity <= 0:
            return
        if opacity < 1:
            alpha = layer.getchannel('A').point(lambda v: int(v * opacity))
            layer = layer.copy()
            layer.putalpha(alpha)
        if dx or dy:
            moved = self.layer()
            moved.paste(layer, (int(round(dx)), int(round(dy))), layer)
            layer = moved
        self.canvas.alpha_composite(layer)

    # shapes
    def rect(self, box, fill=None, radius=0, outline=None, width=0, on=None):
        d = ImageDraw.Draw(on or self.canvas)
        box = [int(round(v)) for v in box]
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        if radius:
            d.rounded_rectangle(box, radius=int(round(self.s(radius))), fill=self._c(fill),
                                outline=self._c(outline), width=int(round(self.s(width))))
        else:
            d.rectangle(box, fill=self._c(fill), outline=self._c(outline), width=int(round(self.s(width))))

    def line(self, points, fill, width=4, on=None):
        ImageDraw.Draw(on or self.canvas).line([tuple(map(float, p)) for p in points], fill=self._c(fill),
                                               width=int(round(self.s(width))), joint='curve')

    def circle(self, center, radius, fill=None, outline=None, width=0, on=None):
        cx, cy = center
        r = self.s(radius)
        ImageDraw.Draw(on or self.canvas).ellipse([cx - r, cy - r, cx + r, cy + r], fill=self._c(fill),
                                                  outline=self._c(outline), width=int(round(self.s(width))))

    def image(self, path, box, fit='contain', opacity=1.0, on=None):
        """Draw an image file (a logo...) or a picture (ctx.src, ctx.still(...)) into box (x0, y0, x1, y1)."""
        im = path.convert('RGBA') if isinstance(path, Image.Image) else Image.open(path).convert('RGBA')
        bw, bh = box[2] - box[0], box[3] - box[1]
        r = (min if fit == 'contain' else max)(bw / im.width, bh / im.height)
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
        if opacity < 1:
            im.putalpha(im.getchannel('A').point(lambda v: int(v * opacity)))
        (on or self.canvas).alpha_composite(im, (int(box[0] + (bw - im.width) / 2), int(box[1] + (bh - im.height) / 2)))

    def place(self, box_w, box_h, position='bottom-left', margin_x=0.06, margin_y=0.08):
        """Top-left (x, y) for a box of this size at a named position inside the title-safe margins:
        top-left, top, top-right, left, center, right, bottom-left, bottom, bottom-right."""
        mx, my = self.w * margin_x, self.h * margin_y
        col = 0 if 'left' in position else 2 if 'right' in position else 1
        row = 0 if 'top' in position else 2 if 'bottom' in position else 1
        x = [mx, (self.w - box_w) / 2, self.w - mx - box_w][col]
        y = [my, (self.h - box_h) / 2, self.h - my - box_h][row]
        return x, y

    def _c(self, ref):
        if ref is None:
            return None
        if isinstance(ref, tuple):
            return ref
        return self.color(ref)

    # text
    def wrap(self, text, font_ref, size, max_width):
        """Lines of `text` that fit max_width pixels."""
        f = self.font(font_ref, size)
        d = ImageDraw.Draw(self.canvas)
        out = []
        for para in str(text).split('\n'):
            line = ''
            for word in para.split():
                trial = (line + ' ' + word).strip()
                if line and d.textlength(trial, font=f) > max_width:
                    out.append(line)
                    line = word
                else:
                    line = trial
            out.append(line)
        return out

    def measure(self, text, font_ref, size, stroke=0):
        """(width, height) of text drawn with the default 'la' anchor: height runs from the anchor (top of the
        ascender) to the lowest ink, so the next line can go at y + height + gap."""
        f = self.font(font_ref, size)
        box = ImageDraw.Draw(self.canvas).multiline_textbbox((0, 0), str(text), font=f, stroke_width=int(round(self.s(stroke))),
                                                             spacing=int(self.s(size) * 0.15))
        return box[2] - min(0, box[0]), box[3]

    def fit_size(self, text, font_ref, size, max_width, min_size=18):
        """Largest size <= size at which `text` fits max_width on one line."""
        f = self.font(font_ref, size)
        d = ImageDraw.Draw(self.canvas)
        while size > min_size and d.textlength(str(text), font=f) > max_width:
            size -= 2
            f = self.font(font_ref, size)
        return size

    def text(self, xy, text, font_ref='body', size=54, fill='light', anchor='la', align='left', outline=None,
             outline_width=0, shadow=None, shadow_offset=(4, 5), shadow_blur=0, opacity=1.0, on=None, letter_spacing=0):
        """Draw text. anchor: Pillow anchor ('la' left-top... 'mm' middle). outline/shadow: colours. letter_spacing:
        extra space between letters (px@1080p) on one line of text. Returns bbox."""
        text = str(text)
        if letter_spacing and len(text) > 1 and '\n' not in text:
            return self._spaced_text(xy, text, font_ref, size, fill, anchor, outline, outline_width, shadow,
                                     shadow_offset, shadow_blur, opacity, on, letter_spacing)
        return self._text(xy, text, font_ref, size, fill, anchor, align, outline, outline_width, shadow, shadow_offset,
                          shadow_blur, opacity, on)

    def _spaced_text(self, xy, text, font_ref, size, fill, anchor, outline, outline_width, shadow, shadow_offset,
                     shadow_blur, opacity, on, letter_spacing):
        """One line drawn letter by letter with extra space between letters: every shadow first, then every outline, then
        every fill, so no letter's outline or shadow covers its neighbour."""
        f = self.font(font_ref, size)
        gap = self.s(letter_spacing)
        widths = [f.getlength(ch) for ch in text]
        total = sum(widths) + gap * (len(text) - 1)
        horizontal, vertical = (anchor or 'la')[0], (anchor or 'la')[1:] or 'a'
        x = xy[0] - (total / 2 if horizontal == 'm' else total if horizontal == 'r' else 0)
        places = []
        for ch, width in zip(text, widths):
            if not ch.isspace():
                places.append(((x, xy[1]), ch))
            x += width + gap
        clear = (0, 0, 0, 0)
        if shadow:
            for at, ch in places:
                self._text(at, ch, font_ref, size, clear, 'l' + vertical, 'left', clear if outline else None,
                           outline_width, shadow, shadow_offset, shadow_blur, opacity, on)
        if outline and outline_width:
            for at, ch in places:
                self._text(at, ch, font_ref, size, outline, 'l' + vertical, 'left', outline, outline_width, None,
                           shadow_offset, 0, opacity, on)
        boxes = [self._text(at, ch, font_ref, size, fill, 'l' + vertical, 'left', None, 0, None, shadow_offset, 0,
                            opacity, on) for at, ch in places]
        sw = int(round(self.s(outline_width))) if outline else 0
        if not boxes:
            return (xy[0], xy[1], xy[0], xy[1])
        return (min(b[0] for b in boxes) - sw, min(b[1] for b in boxes) - sw, max(b[2] for b in boxes) + sw,
                max(b[3] for b in boxes) + sw)

    def _text(self, xy, text, font_ref='body', size=54, fill='light', anchor='la', align='left', outline=None,
              outline_width=0, shadow=None, shadow_offset=(4, 5), shadow_blur=0, opacity=1.0, on=None):
        f = self.font(font_ref, size)
        target = on or self.canvas
        sw = int(round(self.s(outline_width))) if outline else 0
        spacing = int(self.s(size) * 0.15)
        if shadow:
            sx, sy = xy[0] + self.s(shadow_offset[0]), xy[1] + self.s(shadow_offset[1])
            box = ImageDraw.Draw(target).multiline_textbbox((sx, sy), str(text), font=f, anchor=anchor, align=align,
                                                             stroke_width=sw, spacing=spacing)
            pad = int(3 * self.s(shadow_blur)) + 4 if shadow_blur else 2
            x0, y0 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
            x1, y1 = min(target.width, int(box[2]) + pad), min(target.height, int(box[3]) + pad)
            if x1 > x0 and y1 > y0:      # draw and blur only the area around the text (a full-frame blur is slow)
                lay = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
                ImageDraw.Draw(lay).multiline_text((sx - x0, sy - y0), str(text), font=f, fill=self.color(shadow, opacity),
                                                   anchor=anchor, align=align, stroke_width=sw,
                                                   stroke_fill=self.color(shadow, opacity), spacing=spacing)
                if shadow_blur:
                    lay = lay.filter(ImageFilter.GaussianBlur(self.s(shadow_blur)))
                target.alpha_composite(lay, dest=(x0, y0))
        d = ImageDraw.Draw(target)
        d.multiline_text(xy, str(text), font=f, fill=self.color(fill, opacity), anchor=anchor, align=align,
                         stroke_width=sw, stroke_fill=self.color(outline, opacity) if outline else None, spacing=spacing)
        return d.multiline_textbbox(xy, str(text), font=f, anchor=anchor, align=align, stroke_width=sw, spacing=spacing)


# ------------------------------------------------------------------ footage

_stills = {}


def _decode_cmd(clip, start, width, height, fps=None, duration=None, speed=1.0, fit='contain'):
    vf = []
    if fps:
        vf.append(f'fps={fps / speed:.6f}')
    if fit == 'cover':
        vf += [f'scale={width}:{height}:force_original_aspect_ratio=increase', f'crop={width}:{height}', 'format=rgba']
    else:
        vf += [f'scale={width}:{height}:force_original_aspect_ratio=decrease', 'format=rgba',
               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000']
    cmd = [str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-ss', f'{max(0.0, start):.3f}']
    if duration is not None:
        cmd += ['-t', f'{duration:.3f}']
    return cmd + ['-i', str(clip), '-vf', ','.join(vf), '-fps_mode', 'passthrough', '-an', '-f', 'rawvideo', '-pix_fmt',
                  'rgba', '-']


def still(clip, t, size=(1920, 1080)):
    """RGBA picture of `clip` (video or image) at t seconds, fitted inside size (transparent around it)."""
    key = (str(clip), round(float(t), 3), tuple(size))
    if key not in _stills:
        w, h = size
        if Path(clip).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'):
            im = Image.open(clip).convert('RGBA')
            im.thumbnail((w, h), Image.LANCZOS)
            out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            out.alpha_composite(im, ((w - im.width) // 2, (h - im.height) // 2))
        else:
            cmd = _decode_cmd(clip, t, w, h)
            cmd[cmd.index('-an'):cmd.index('-an')] = ['-frames:v', '1']
            r = subprocess.run(cmd, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if len(r.stdout) < w * h * 4:
                raise ValueError(f'no frame at {t:.2f} s in {clip}: {r.stderr.decode(errors="replace")[-300:]}')
            out = Image.frombytes('RGBA', (w, h), r.stdout[:w * h * 4])
        if len(_stills) > 64:
            _stills.clear()
        _stills[key] = out
    return _stills[key].copy()


def source_frame(source, t, width, height):
    """The source clip's frame shown at t seconds into a graphic."""
    if source.get('fit') == 'cover':
        im = still(source['clip'], source['in'] + t * source.get('speed', 1.0), (width * 4, height * 4))
        box = im.getbbox() or (0, 0, im.width, im.height)
        im = im.crop(box)
        r = max(width / im.width, height / im.height)
        im = im.resize((max(width, round(im.width * r)), max(height, round(im.height * r))), Image.LANCZOS)
        x, y = (im.width - width) // 2, (im.height - height) // 2
        return im.crop((x, y, x + width, y + height))
    return still(source['clip'], source['in'] + t * source.get('speed', 1.0), (width, height))


def source_frames(source, width, height, fps):
    """Stream the source clip's frames (one per output frame) as RGBA pictures."""
    speed = float(source.get('speed', 1.0))
    dur = float(source['out']) - float(source['in'])
    p = subprocess.Popen(_decode_cmd(source['clip'], source['in'], width, height, fps, dur, speed, source.get('fit', 'contain')),
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    size = width * height * 4
    last = None
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            last = Image.frombytes('RGBA', (width, height), buf)
            yield last
        while last is not None:   # source shorter than the graphic: hold its last frame
            yield last.copy()
    finally:
        p.kill()
        p.stdout.close()
        p.wait()


def person_matte(img):
    """L mask of the people in an RGBA/RGB picture (MODNet, local)."""
    import numpy as np
    sys.path.insert(0, (_SAI_ROOT + '\\creator'))
    from letitedit_creator import shots
    import letitedit.core.render_lock as render_lock          # the matte model runs on the GPU (DirectML): under the PC render lock like every model
    with render_lock.model_slot('person cut-out (picture)'):
        m = np.asarray(shots.matte(img.convert('RGB')), dtype=np.float32)
    return Image.fromarray((m.clip(0, 1) * 255).astype('uint8'), 'L').resize(img.size)


def depth_map(img):
    """L picture of relative depth (255 = nearest the camera), from the local depth model."""
    import numpy as np
    sys.path.insert(0, str(Path((_SAI_ROOT + '\\vfx'))))
    from letitedit_vfx import analyze
    import letitedit.core.render_lock as render_lock
    with render_lock.model_slot('depth map (picture)'):
        d = np.asarray(analyze.depth(img.convert('RGB')), dtype=np.float32)
    return Image.fromarray((d.clip(0, 1) * 255).astype('uint8'), 'L').resize(img.size)


# ------------------------------------------------------------------ templates

def _load_module(path):
    spec = importlib.util.spec_from_file_location(f'letitedit_ai_graphic_{Path(path).stem}', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def templates(kit=None):
    """{name: module} for the built-in templates plus the style pack's graphics/ folder (pack wins on a name clash)."""
    found = {}
    folders = [TEMPLATES]
    if kit is not None and kit.root is not None and (kit.root / 'graphics').is_dir():
        folders.append(kit.root / 'graphics')
    for folder in folders:
        for f in sorted(folder.glob('*.py')):
            if not f.name.startswith('_'):
                found[f.stem] = f
    return found


# built-in templates listed to agents: the caption animator and the progress bar. The ready-made designs (title_card, lower_third,
# chapter_card, callout, badge, end_card, big_number, text_pop) still render where projects use them, but are not
# offered: a design made for the video beat a filled-in one in every comparison. A style pack's own templates (saved by
# the user) are offered.
OFFERED = {'word_captions', 'progress_bar'}


def offered(kit=None):
    """{name: path} of the templates agents are shown: OFFERED built-ins and the style pack's own."""
    return {name: path for name, path in templates(kit).items() if name in OFFERED or path.parent != TEMPLATES}


def template_info(kit=None, everything=False):
    """[{name, title, description, params, animated, default_len}] for the offered templates (all with everything)."""
    out = []
    for name, path in (templates(kit) if everything else offered(kit)).items():
        m = _load_module(path)
        out.append({'name': name, 'title': getattr(m, 'TITLE', name), 'description': getattr(m, 'DESCRIPTION', ''),
                    'params': getattr(m, 'PARAMS', {}), 'animated': getattr(m, 'ANIMATED', True),
                    'default_len': getattr(m, 'DEFAULT_LEN', 4.0)})
    out.append({'name': 'custom', 'title': 'Custom drawing', 'description': (
        "Your own Python: code='def draw(ctx): ...' (Pillow). ctx: w, h, t (seconds), len, frame, p (params), kit; "
        "s(px@1080p), x(frac), y(frac), anim_in(dur, delay, ease), anim_out(dur), visible(), ease(name, x), "
        "color(ref, alpha), font(ref, size), text(xy, text, font_ref, size, fill, anchor, align, outline, outline_width, "
        "shadow, shadow_offset, shadow_blur, opacity, letter_spacing), wrap, measure, fit_size, rect(box, fill, radius, outline, width), "
        "line, circle, image(path, box), layer() (a blank RGBA image; the drawing helpers take on=layer), "
        "paste(layer, dx, dy, opacity), canvas (RGBA Image). Colours: kit names, '#RRGGBB(AA)' or (r, g, b[, a]). "
        "Set animated: false in params for a still."), 'params': {'code': '', 'animated': True}, 'animated': True,
        'default_len': 4.0})
    return out


def _resolve_template(recipe, kit):
    name = recipe.get('template')
    if name == 'custom':
        return None
    paths = templates(kit)
    if name not in paths:
        raise ValueError(f'Unknown graphic template {name!r}; templates: {", ".join(sorted(offered(kit)))}, custom')
    return _load_module(paths[name])


def normalise(recipe, kit=None):
    """The recipe with template defaults filled in: {template, params, len}."""
    kit = kit or look_library.kit()
    recipe = copy.deepcopy(recipe)
    mod = _resolve_template(recipe, kit)
    params = dict(getattr(mod, 'PARAMS', {}) if mod else {'animated': True})
    pack_defaults = (kit.get('graphics') or {}).get(recipe['template'], {})
    params.update(pack_defaults)
    params.update(recipe.get('params') or {})
    if mod is None:
        if not params.get('code') and not recipe.get('code'):
            raise ValueError("custom graphic needs code: 'def draw(ctx): ...'")
        params['code'] = recipe.get('code') or params['code']
    source = recipe.get('source')
    if source:
        source = {**source, 'in': float(source.get('in', 0)), 'speed': float(source.get('speed', 1.0))}
        if 'out' not in source:
            source['out'] = source['in'] + float(recipe.get('len') or 4.0) * source['speed']
        source['out'] = float(source['out'])
    default_len = (source['out'] - source['in']) / source['speed'] if source else \
        (getattr(mod, 'DEFAULT_LEN', 4.0) if mod else 4.0)
    length = float(recipe.get('len') or default_len)
    out = {'template': recipe['template'], 'params': params, 'len': round(length, 3)}
    if source:
        out['source'] = source
    return out


def _digest(recipe, kit, width, height, fps):
    mod_src = ''
    if recipe['template'] != 'custom':
        mod_src = Path(templates(kit)[recipe['template']]).read_text(encoding='utf-8')
    src = recipe.get('source')
    if src:
        st = os.stat(src['clip'])
        recipe = {**recipe, 'source_file': [st.st_size, int(st.st_mtime)]}
    key = json.dumps({'r': recipe, 'colors': kit['colors'], 'fonts': kit['fonts'], 'g': kit.get('graphics', {}),
                      'size': [width, height], 'fps': round(fps, 4), 'src': hashlib.sha1(mod_src.encode()).hexdigest(),
                      'engine': 2}, sort_keys=True, default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def drawing_kit(recipe, kit):
    """The kit a recipe is drawn with: the style frozen in its params (_look_kit), else `kit`."""
    frozen = ((recipe.get('params') or {}).get('_look_kit') or {}).get('style')
    if frozen is not None:
        return style_pack.Kit({**copy.deepcopy(style_pack.DEFAULTS), **frozen})
    return kit


def draw_frames(recipe, kit, width, height, fps, times=None):
    """Yield (t, RGBA Image) for a normalised recipe, in-process (built-in templates)."""
    kit = drawing_kit(recipe, kit)
    mod = _resolve_template(recipe, kit)
    animated = getattr(mod, 'ANIMATED', True) if mod else recipe['params'].get('animated', True)
    n = max(1, int(round(recipe['len'] * fps))) if animated else 1
    if mod is None:
        ns = {}
        exec(compile(recipe['params']['code'], '<custom graphic>', 'exec'), ns)  # noqa: S102 - runs in the sandbox process
        draw = ns.get('draw')
        if draw is None:
            raise ValueError('custom graphic code must define draw(ctx)')
    else:
        draw = mod.draw
    frames = range(n) if times is None else [min(n - 1, int(round(t * fps))) for t in times]
    source = recipe.get('source')
    stream = source_frames(source, width, height, fps) if source and times is None else None
    # a template may say when a frame looks the same as the one before (frame_key), so it isn't drawn again
    key_fn = getattr(mod, 'frame_key', None) if mod is not None and not source else None
    last_key, last = object(), None
    hold_until = -1.0      # custom code: the last frame can't change before this time (see Ctx._next)
    for i in frames:
        t = i / fps if animated else min(1.0, recipe['len'] / 2)
        if last is not None and times is None and t < hold_until - 1e-9:
            yield t, last
            continue
        src = None
        if source:
            src = next(stream, None) if stream is not None else source_frame(source, t, width, height)
        ctx = Ctx(width, height, fps, recipe['len'], t, i, recipe['params'], kit, src=src)
        if key_fn is not None:
            k = key_fn(ctx)
            if k == last_key and last is not None:
                yield t, last
                continue
            last_key = k
        draw(ctx)
        last = ctx.canvas
        hold_until = ctx._next if (mod is None and not source and not ctx._timed and not ctx._moving) else -1.0
        yield t, ctx.canvas


def render(recipe, width=1920, height=1080, fps=30.0, kit=None, out_dir=None):
    """Render a recipe to a file and return {'path', 'recipe', 'animated', 'frames', 'seconds', 'cached'}."""
    kit = kit if isinstance(kit, style_pack.Kit) else look_library.kit(kit)
    recipe = normalise(recipe, kit)
    out_dir = Path(out_dir or CACHE / 'graphics')
    out_dir.mkdir(parents=True, exist_ok=True)
    mod = _resolve_template(recipe, kit)
    animated = getattr(mod, 'ANIMATED', True) if mod else bool(recipe['params'].get('animated', True))
    name = f"{recipe['template']}-{_digest(recipe, kit, width, height, fps)}"
    opaque = bool(recipe.get('source')) and not recipe['params'].get('alpha')
    path = out_dir / (name + (('.mp4' if opaque else '.mov') if animated else '.png'))
    n = max(1, int(round(recipe['len'] * fps))) if animated else 1
    if path.exists():
        return {'path': str(path), 'recipe': recipe, 'animated': animated, 'frames': n, 'cached': True}
    if mod is None:
        _render_sandboxed(recipe, kit, width, height, fps, path, animated, n)
    elif not animated:
        _, img = next(draw_frames(recipe, kit, width, height, fps))
        tmp = path.with_suffix('.tmp.png')
        img.save(tmp)
        os.replace(tmp, path)
    else:
        _encode(draw_frames(recipe, kit, width, height, fps), width, height, fps, path)
    return {'path': str(path), 'recipe': recipe, 'animated': animated, 'frames': n, 'cached': False}


def _encode(frames, width, height, fps, path):
    """RGBA frames -> QuickTime Animation (qtrle, argb) .mov with alpha, or H.264 for an .mp4 path (opaque)."""
    tmp = path.with_name(path.stem + '.tmp' + path.suffix)
    rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
    codec = (['-c:v', 'libx264', '-crf', '14', '-preset', 'fast', '-pix_fmt', 'yuv420p'] if path.suffix == '.mp4'
             else ['-c:v', 'qtrle', '-pix_fmt', 'argb'])
    p = subprocess.Popen([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba',
                          '-s', f'{width}x{height}', '-r', rate, '-i', '-', *codec, str(tmp)],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        for _, img in frames:
            p.stdin.write(img.tobytes())
        p.stdin.close()
        err = p.stderr.read().decode(errors='replace')
        p.stderr.close()
        if p.wait() != 0:
            raise RuntimeError(f'ffmpeg could not encode the graphic: {err[-400:]}')
    except BaseException:
        p.kill()
        try:
            p.wait(timeout=10)
            tmp.unlink(missing_ok=True)
        except (OSError, subprocess.TimeoutExpired):     # left for the next render: the draw error is what matters
            pass
        raise
    os.replace(tmp, path)


def _render_sandboxed(recipe, kit, width, height, fps, path, animated, frames=1):
    """Custom code runs in its own Python process (isolated mode, time limit) so a bug can't hang or crash the editor."""
    limit = CUSTOM_TIMEOUT + CUSTOM_SECONDS_PER_FRAME * frames + (SOURCE_SECONDS_PER_FRAME * frames if recipe.get('source') else 0)
    with tempfile.TemporaryDirectory() as d:
        job = Path(d) / 'job.json'
        job.write_text(json.dumps({'recipe': recipe, 'kit': kit.source, 'width': width, 'height': height, 'fps': fps,
                                   'out': str(path), 'animated': animated, 'kit_values': dict(kit),
                                   'kit_root': str(kit.root) if kit.root else None,
                                   'kit_references': getattr(kit, 'references', {})}), encoding='utf-8')
        try:
            r = subprocess.run([sys.executable, '-I', str(HERE / 'graphics_runner.py'), str(job)], cwd=d,
                               capture_output=True, text=True, timeout=limit,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'custom graphic took longer than {limit:.0f}s and was stopped') from None
        if r.returncode != 0 or not path.exists():
            raise RuntimeError('custom graphic failed:\n' + (r.stderr or r.stdout)[-1500:])


def run_job(job_path):
    """Entry point for graphics_runner.py (inside the sandbox process)."""
    job = json.loads(Path(job_path).read_text(encoding='utf-8-sig'))
    kit = style_pack.Kit(job['kit_values'])
    kit.source = job['kit']
    kit.root = Path(job['kit_root']) if job.get('kit_root') else None
    kit.references = job.get('kit_references', {})
    path = Path(job['out'])
    frames = draw_frames(job['recipe'], kit, job['width'], job['height'], job['fps'])
    if job['animated']:
        _encode(frames, job['width'], job['height'], job['fps'], path)
    else:
        _, img = next(frames)
        img.save(path)


# ------------------------------------------------------------------ previews

def preview(recipe, width=1920, height=1080, fps=30.0, kit=None, times=None, background='checker', cols=3, tile_w=640,
            background_at=None):
    """JPEG bytes: frames of a graphic at `times` (default: in, middle, out) over a checkerboard or a picture."""
    kit = kit if isinstance(kit, style_pack.Kit) else look_library.kit(kit)
    recipe = normalise(recipe, kit)
    L = recipe['len']
    times = times or [min(0.35, L / 4), L / 2, max(0.0, L - 0.25)]
    if recipe['template'] == 'custom':
        res = render(recipe, width, height, fps, kit)
        imgs = _frames_from_file(res['path'], times, fps) if res['animated'] else [Image.open(res['path']).convert('RGBA')] * len(times)
    else:
        imgs = [img for _, img in draw_frames(recipe, kit, width, height, fps, times=times)]
    bg = _background(background, width, height, background_at)
    tiles = []
    for img in imgs:
        tile = bg.copy()
        tile.alpha_composite(img)
        tiles.append(tile.convert('RGB'))
    return _sheet(tiles, [f'{t:.2f}s' for t in times], cols, tile_w)


def _frames_from_file(path, times, fps):
    out = []
    with tempfile.TemporaryDirectory() as d:
        for i, t in enumerate(times):
            png = Path(d) / f'{i}.png'
            subprocess.run([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{t:.3f}', '-i', path,
                            '-frames:v', '1', '-pix_fmt', 'rgba', str(png)], capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            out.append(Image.open(png).convert('RGBA') if png.exists() else Image.new('RGBA', (16, 16)))
    return out


def _video_frame(path, at=None):
    import io
    import subprocess
    if at is None:
        r = subprocess.run([str(FFMPEG).replace('ffmpeg.exe', 'ffprobe.exe'), '-v', 'error', '-show_entries',
                            'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            at = float(r.stdout.strip()) / 2
        except ValueError:
            at = 0.0
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-ss', f'{float(at):.3f}', '-i', path, '-frames:v', '1', '-f',
                        'image2pipe', '-vcodec', 'png', '-'], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if not r.stdout:
        raise ValueError(f'background: no picture at {at:.2f} s in {path}')
    return Image.open(io.BytesIO(r.stdout)).convert('RGBA')


def _background(kind, width, height, background_at=None):
    if kind and os.path.isdir(str(kind)):
        raise ValueError(f'background is a folder ({kind}); give one image file in it')
    if kind and os.path.exists(str(kind)):
        try:
            im = Image.open(kind).convert('RGBA')
        except Exception:  # noqa: BLE001 - a video: one of its frames (background_at seconds, else its middle)
            im = _video_frame(str(kind), background_at)
        return im.resize((width, height))
    bg = Image.new('RGBA', (width, height), (70, 74, 82, 255))
    d = ImageDraw.Draw(bg)
    step = max(16, height // 18)
    for yy in range(0, height, step):
        for xx in range((yy // step) % 2 * step, width, step * 2):
            d.rectangle([xx, yy, xx + step - 1, yy + step - 1], fill=(92, 96, 104, 255))
    return bg


def _sheet(tiles, labels, cols, tile_w):
    th = int(tiles[0].height * tile_w / tiles[0].width)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * tile_w, rows * (th + 26)), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(zip(tiles, labels)):
        x, y = (i % cols) * tile_w, (i // cols) * (th + 26)
        sheet.paste(tile.resize((tile_w, th), Image.LANCZOS), (x, y + 26))
        d.text((x + 8, y + 5), label, fill=(220, 220, 220))
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=86)
    return buf.getvalue()


def pack_sheet(kit=None, width=1920, height=1080):
    """JPEG bytes: every template drawn in a style pack (mid-animation), plus a caption sample: the kit at a glance."""
    kit = kit if isinstance(kit, style_pack.Kit) else look_library.kit(kit)
    tiles, labels = [], []
    bg = _background('checker', width, height)
    for info in template_info(kit):
        if info['name'] == 'custom':
            continue
        recipe = normalise({'template': info['name'], 'params': SAMPLE_PARAMS.get(info['name'], {})}, kit)
        _, img = next(draw_frames(recipe, kit, width, height, 30.0, times=[recipe['len'] / 2]))
        tile = bg.copy()
        tile.alpha_composite(img)
        tiles.append(tile.convert('RGB'))
        labels.append(info['name'])
    tiles.append(_caption_sample(kit, width, height, bg))
    labels.append('captions')
    return _sheet(tiles, labels, 3, 560)


SAMPLE_PARAMS = {
    'title_card': {'title': 'The Vent Fan Swap', 'subtitle': 'Episode 2'},
    'chapter_card': {'number': 2, 'title': 'Pulling the old fan'},
    'lower_third': {'title': 'Alex', 'subtitle': 'Bus builder'},
    'callout': {'text': 'Cracked housing', 'target_x': 0.62, 'target_y': 0.42},
    'badge': {'text': '$42 part'},
    'end_card': {'title': 'Thanks for watching!', 'subtitle': 'Subscribe for the next build'},
    'big_number': {'value': 1240, 'prefix': '$', 'label': 'spent so far'},
    'text_pop': {'text': 'NO WAY'},
    'asset_sticker': {'asset': 'emoji:fire'},
    'depth_parallax': {'image': str(Path(_SAI_ROOT) / 'app/share/shotcut/elements/graphics/Depth Parallax Source.png'),
                       'depth_mask': str(Path(_SAI_ROOT) / 'app/share/shotcut/elements/graphics/Depth Parallax Mask.png')},
}


def _caption_sample(kit, width, height, bg):
    """How the kit's captions look, drawn with Pillow (the export draws them with the same font and colours)."""
    props = kit.caption_props(width, height)
    tile = bg.copy()
    d = ImageDraw.Draw(tile)
    x, y, w, h = [float(v) for v in props['geometry'].split()[:4]]
    f = fonts.pil_font(props['family'], props['size'], weight=kit.font(kit['captions'].get('font'), 'captions')['weight'])
    text = 'This is how captions look\nin this style'
    anchor = {'bottom': 'md', 'top': 'ma', 'middle': 'mm'}.get(props['valign'], 'md')
    ty = {'bottom': y + h, 'top': y, 'middle': y + h / 2}.get(props['valign'], y + h)
    sh = kit['captions'].get('shadow')
    if sh:
        d.multiline_text((x + w / 2 + float(sh.get('x', 3)) * height / 1080, ty + float(sh.get('y', 4)) * height / 1080), text,
                         font=f, fill=kit.rgba(sh.get('color', 'dark')), anchor=anchor, align='center',
                         stroke_width=props['outline'], stroke_fill=kit.rgba(sh.get('color', 'dark')))
    d.multiline_text((x + w / 2, ty), text, font=f, fill=_argb_to_rgba(props['fgcolour']), anchor=anchor, align='center',
                     stroke_width=props['outline'], stroke_fill=_argb_to_rgba(props['olcolour']))
    return tile.convert('RGB')


def _argb_to_rgba(c):
    c = c.lstrip('#')
    return (int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16), int(c[0:2], 16))
