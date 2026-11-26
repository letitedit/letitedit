"""A pop-up sticker: a picture file, an emoji or a short text that springs onto the screen, holds, and goes.

Placed by the {op: popups} / {op: popup} edits (bridge/popups.py) when a trigger word is said; usable directly as
{graphic: {template: popup, params: {...}}, len}. The sticker's longest side is `size` x the frame's shorter side; it
is centred on (x, y) (fractions of the frame) and kept inside the frame. Emoji come from the Windows emoji font
(Segoe UI Emoji), drawn in colour.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

TITLE = 'Pop-up sticker'
DESCRIPTION = ('A picture (logo, product photo, cut-out), an emoji or a short text that pops onto the screen, holds '
               'and goes; in: pop | fade | slide_up | slide_down | slide_left | slide_right | drop | spin | none, '
               'out: pop | shrink | fade | slide_* | spin | none.')
PARAMS = {'image': '', 'emoji': '', 'text': 'WOW', 'x': 0.73, 'y': 0.22, 'size': 0.3, 'in': 'pop', 'out': 'shrink',
          'in_s': 0.28, 'out_s': 0.2, 'wiggle': 0.0, 'tilt': 0.0, 'shadow': True, 'outline': 0, 'outline_color': 'light',
          'font': 'heading', 'fill': 'secondary', 'stroke': 'dark', 'stroke_width': 10, 'asset_stamp': ''}
ANIMATED = True
DEFAULT_LEN = 1.6
EMOJI_FONT = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'seguiemj.ttf')

_base = {}       # (what, size px, look) -> the sticker at full size (RGBA), drawn once per render


def _crop(im):
    box = im.getchannel('A').getbbox()
    return im.crop(box) if box else im


def _fit(im, longest):
    s = longest / max(im.width, im.height)
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def _emoji(ch, px):
    if not os.path.exists(EMOJI_FONT):
        raise ValueError(f'no emoji font on this PC ({EMOJI_FONT})')
    font = ImageFont.truetype(EMOJI_FONT, 109)        # the colour layers are drawn at this size, then scaled
    im = Image.new('RGBA', (109 * max(1, len(ch)) * 2 + 80, 260), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((40, 40), ch, font=font, embedded_color=True)
    return _fit(_crop(im), px)


def _lines(text):
    """Long text on two or three balanced lines (a line break in the text is kept as given)."""
    text = str(text).strip()
    if '\n' in text or len(text) <= 14 or ' ' not in text:
        return text
    words = text.split()
    n = 3 if len(text) > 32 and len(words) >= 3 else 2
    best = None
    for cuts in ([[i] for i in range(1, len(words))] if n == 2 else
                 [[i, j] for i in range(1, len(words) - 1) for j in range(i + 1, len(words))]):
        parts = [' '.join(words[a:b]) for a, b in zip([0] + cuts, cuts + [len(words)])]
        score = max(len(x) for x in parts)
        if best is None or score < best[0]:
            best = (score, parts)
    return '\n'.join(best[1])


def _text(ctx, p, px):
    text = _lines(p['text'])
    size = 200
    w, h = ctx.measure(text, p['font'], size, stroke=p.get('stroke_width', 0))
    pad = int(ctx.s(60))
    lay = Image.new('RGBA', (int(w) + 2 * pad, int(h) + 2 * pad), (0, 0, 0, 0))
    ctx.text((lay.width / 2, lay.height / 2), text, p['font'], size, fill=p['fill'], anchor='mm', align='center',
             outline=p.get('stroke'), outline_width=p.get('stroke_width', 0), on=lay)
    return _fit(_crop(lay), px)


def _sticker_edge(im, width_px, color):
    """A solid edge around the sticker's shape (a die-cut sticker look)."""
    if width_px < 1:
        return im
    pad = int(width_px) + 2
    big = Image.new('RGBA', (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    big.alpha_composite(im, (pad, pad))
    a = big.getchannel('A').filter(ImageFilter.GaussianBlur(width_px / 2)).point(lambda v: 255 if v > 8 else 0)
    edge = Image.new('RGBA', big.size, color)
    edge.putalpha(a)
    edge.alpha_composite(big)
    return edge


def _with_shadow(im, scale):
    off = max(2, round(10 * scale))
    blur = max(2, round(12 * scale))
    out = Image.new('RGBA', (im.width + 2 * blur + off, im.height + 2 * blur + off), (0, 0, 0, 0))
    sh = Image.new('RGBA', im.size, (0, 0, 0, 0))
    sh.putalpha(im.getchannel('A').point(lambda v: int(v * 0.45)))
    out.alpha_composite(sh, (blur + off, blur + off))
    out = out.filter(ImageFilter.GaussianBlur(blur / 2))
    out.alpha_composite(im, (blur, blur))
    return out


def sticker(ctx):
    p = ctx.p
    px = max(8, round(float(p.get('size', 0.3)) * min(ctx.w, ctx.h)))
    what = ('image', p['image']) if p.get('image') else ('emoji', p['emoji']) if p.get('emoji') else ('text', p['text'])
    key = (what, px, p.get('outline'), p.get('outline_color'), bool(p.get('shadow')), p.get('font'), p.get('fill'),
           p.get('stroke'), p.get('stroke_width'), p.get('asset_stamp'), ctx.w, ctx.h)
    if key not in _base:
        if what[0] == 'image':
            im = _fit(_crop(Image.open(what[1]).convert('RGBA')), px)
        elif what[0] == 'emoji':
            im = _emoji(what[1], px)
        elif what[1]:
            im = _text(ctx, p, px)
        else:
            raise ValueError('a pop-up needs image, emoji or text')
        im = _sticker_edge(im, ctx.s(float(p.get('outline') or 0)), ctx.color(p.get('outline_color') or 'light'))
        if p.get('shadow'):
            im = _with_shadow(im, ctx.scale)
        _base[key] = im
    return _base[key]


def _state(ctx):
    """(scale, opacity, dx, dy, angle) of the sticker at this frame."""
    p = ctx.p
    t, d = ctx._t, ctx.len
    tin, tout = float(p.get('in_s', 0.28)), float(p.get('out_s', 0.2))
    a_in, a_out = p.get('in') or 'pop', p.get('out') or 'shrink'
    s, o, dx, dy, ang = 1.0, 1.0, 0.0, 0.0, float(p.get('tilt') or 0)
    if a_in != 'none' and tin > 0 and t < tin:
        x = max(0.0, t / tin)
        if a_in == 'pop':
            s, o = ctx.ease('back', x), min(1.0, x * 2.5)
        elif a_in == 'fade':
            o = ctx.ease('out', x)
        elif a_in == 'spin':
            s, o, ang = ctx.ease('out', x), min(1.0, x * 2), ang - 200 * (1 - ctx.ease('out', x))
        elif a_in == 'drop':
            dy, o = -0.35 * ctx.h * (1 - ctx.ease('elastic', x)), min(1.0, x * 3)
        else:
            k = 1 - ctx.ease('out', x)
            dx = {'slide_left': 0.4 * ctx.w, 'slide_right': -0.4 * ctx.w}.get(a_in, 0.0) * k
            dy = {'slide_up': 0.3 * ctx.h, 'slide_down': -0.3 * ctx.h}.get(a_in, 0.0) * k
            o = min(1.0, x * 2)
    elif a_out != 'none' and tout > 0 and t > d - tout:
        x = min(1.0, (t - (d - tout)) / tout)
        if a_out == 'pop':
            s, o = 1 + 0.25 * ctx.ease('out', x), 1 - x
        elif a_out == 'shrink':
            s = 1 - ctx.ease('in', x)
        elif a_out == 'fade':
            o = 1 - x
        elif a_out == 'spin':
            s, ang = 1 - ctx.ease('in', x), ang + 200 * ctx.ease('in', x)
        else:
            k = ctx.ease('in', x)
            dx = {'slide_left': -0.4 * ctx.w, 'slide_right': 0.4 * ctx.w}.get(a_out, 0.0) * k
            dy = {'slide_up': -0.3 * ctx.h, 'slide_down': 0.3 * ctx.h}.get(a_out, 0.0) * k
            o = 1 - x
    wig = float(p.get('wiggle') or 0)
    if wig:
        ang += wig * math.sin(2 * math.pi * 1.6 * t)
    return s, o, dx, dy, ang


def frame_key(ctx):
    """Frames that look the same share a key (the hold of a sticker that doesn't wiggle is drawn once)."""
    p = ctx.p
    t, d = ctx._t, ctx.len
    holding = t >= float(p.get('in_s', 0.28)) and t <= d - float(p.get('out_s', 0.2)) and not float(p.get('wiggle') or 0)
    return 'hold' if holding else ctx._frame


def draw(ctx):
    im = sticker(ctx)
    s, o, dx, dy, ang = _state(ctx)
    if s <= 0.01 or o <= 0.01:
        return
    if abs(s - 1) > 1e-3:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BICUBIC)
    if abs(ang) > 0.05:
        im = im.rotate(ang, resample=Image.BICUBIC, expand=True)
    if o < 1:
        im = im.copy()
        im.putalpha(im.getchannel('A').point(lambda v: int(v * o)))
    p = ctx.p
    base = sticker(ctx)            # keep the resting sticker inside the frame; motion may carry it past the edge
    cx = min(max(float(p.get('x', 0.73)) * ctx.w, base.width / 2), ctx.w - base.width / 2)
    cy = min(max(float(p.get('y', 0.22)) * ctx.h, base.height / 2), ctx.h - base.height / 2)
    x, y = round(cx + dx - im.width / 2), round(cy + dy - im.height / 2)
    ctx.canvas.alpha_composite(_clip(im, x, y, ctx), (max(0, x), max(0, y)))


def _clip(im, x, y, ctx):
    """The part of im that falls inside the canvas when its top-left is at (x, y)."""
    l, t = max(0, -x), max(0, -y)
    r, b = min(im.width, ctx.w - x), min(im.height, ctx.h - y)
    if r <= l or b <= t:
        return Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    return im.crop((l, t, r, b))
