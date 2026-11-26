"""A library asset on screen (bridge/assets.py, letitedit_assets): an animated emoji, sticker, graphic or transition
(Lottie / Glaxnimate, drawn frame by frame by the export engine) or a still picture, coming in and going like the
pop-up sticker (same in/out motions, wiggle, tilt, shadow and outline).

Pop-ups of animated assets use it (assets.popup_asset); usable directly as
{graphic: {template: asset_sticker, params: {asset: 'anim:fire', x: 0.7, y: 0.25}}, len: 2}.
fit: sticker (what the animation draws, its longer side `size` x the frame's shorter side, centred on x, y and kept
inside the frame) | width (what it draws, `size` x the frame's width: banners, lower thirds) | cover (the whole
animation filling the frame: transitions) | contain (the whole animation inside the frame).
texts replaces a graphic's own texts: {'Sample title': 'Day 3', 'Description': 'Bus build'} or ['Day 3', 'Bus build']
(title first).
"""
import importlib.util
import os
from pathlib import Path

from PIL import Image

TITLE = 'Library asset'
DESCRIPTION = ('An asset from letitedit_assets (asset: a ref like anim:fire, sticker:speech, transition:barn door, '
               'emoji:rocket, or an id) on screen: animations play (loop: true repeats them), pictures hold; in/out '
               'motions as the pop-up sticker; fit: sticker | width | cover | contain; texts: a graphic\'s own texts.')
PARAMS = {'asset': '', 'x': 0.5, 'y': 0.3, 'size': 0.3, 'fit': '', 'in': '', 'out': '', 'in_s': 0.28, 'out_s': 0.2,
          'wiggle': 0.0, 'tilt': 0.0, 'shadow': None, 'outline': 0, 'outline_color': 'light', 'loop': True,
          'speed': 1.0, 'texts': None, 'color': '', 'style': '', 'asset_stamp': ''}
ANIMATED = True
DEFAULT_LEN = 2.0

_HERE = Path(__file__).resolve().parent
_popup = None
_prepared = {}      # (asset, look, canvas, fps) -> prepared drawing info
_frames = {}        # (prepared key, frame index) -> RGBA picture at its placed size (only the last few kept)


def _popup_mod():
    global _popup
    if _popup is None:
        spec = importlib.util.spec_from_file_location('letitedit_ai_graphic_popup_helpers', _HERE / 'popup.py')
        _popup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_popup)
    return _popup


def _prepare(ctx):
    """What to draw: still picture or animation frames, at what size, cropped to what box."""
    import assets
    p = ctx.p
    key = (str(p.get('asset')), str(p.get('texts')), p.get('fit'), float(p.get('size') or 0.3), p.get('color'),
           p.get('style'), p.get('asset_stamp'), ctx.w, ctx.h, round(ctx.fps, 3))
    if key in _prepared:
        return key, _prepared[key]
    ref = str(p.get('asset') or '')
    if ref.lower().startswith('mine:'):         # the person's own My assets item: their file
        import my_assets
        ref = my_assets.get(ref)['path']
    if not ref:
        raise ValueError('asset_sticker needs asset (a ref or id from letitedit_assets, or a file)')
    lottie_ext = ('.tgs', '.rawr', '.json', '.lottie')
    if os.path.isfile(ref):
        path, kind, animated = os.path.abspath(ref), 'sticker', Path(ref).suffix.lower() in lottie_ext
    else:
        e = assets.find(ref)
        kind, animated = e['kind'], bool(e.get('animated'))
        path = assets.abspath(e['file'])
        if kind in assets.SOUND:
            raise ValueError(f"{e['id']} is a sound, not a picture")
    fit = p.get('fit') or assets.DEFAULT_FIT.get(kind, 'sticker')
    size = float(p.get('size') or 0.3)
    short = min(ctx.w, ctx.h)
    info = {'fit': fit, 'animated': animated, 'kind': kind}
    if not animated:
        px = max(8, round(size * (ctx.w if fit == 'width' else short)))
        if os.path.isfile(ref):
            f = ref
        else:
            f = assets.resolve(ref, size_px=px, color=p.get('color') or None, style=p.get('style') or None)['file']
        with Image.open(f) as src:
            im = src.convert('RGBA')
        box = im.getchannel('A').getbbox()
        im = im.crop(box) if box else im
        info.update(still=_fit_still(im, fit, size, ctx))
        _prepared[key] = info
        return key, info
    src = assets.with_texts(path, p.get('texts')) if p.get('texts') else path
    li = assets.lottie_info(src)
    if fit in ('cover', 'contain'):
        s = (max if fit == 'cover' else min)(ctx.w / li['w'], ctx.h / li['h'])
        w, h = max(2, round(li['w'] * s / 2) * 2), max(2, round(li['h'] * s / 2) * 2)
        info.update(files=assets.lottie_frames(src, ctx.fps, aspect=(w, h)), box=None, scale=1.0, wh=(w, h))
    else:
        # where the animation draws, over all its frames (a small pass), then a pass big enough for that part
        probe = assets.lottie_frames(src, ctx.fps, 320)
        box = None
        for f in probe:
            with Image.open(f) as im:
                b = im.getchannel('A').getbbox()
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        with Image.open(probe[0]) as im:
            pw, ph = im.size
        box = box or (0, 0, pw, ph)
        fx0, fy0, fx1, fy1 = box[0] / pw, box[1] / ph, box[2] / pw, box[3] / ph
        if fit == 'width':
            target_w = size * ctx.w
            canvas_w = target_w / max(1e-3, fx1 - fx0)
            s = canvas_w / li['w']
        else:
            target = size * short
            longest = max((fx1 - fx0) * li['w'], (fy1 - fy0) * li['h'])
            s = target / max(1.0, longest)
        s *= 1.05
        w, h = max(2, round(li['w'] * s / 2) * 2), max(2, round(li['h'] * s / 2) * 2)
        if max(w, h) > 4096:
            k = 4096 / max(w, h)
            w, h, s = max(2, round(w * k / 2) * 2), max(2, round(h * k / 2) * 2), s * k
        files = assets.lottie_frames(src, ctx.fps, aspect=(w, h))
        crop = (int(fx0 * w), int(fy0 * h), int(round(fx1 * w)) + 1, int(round(fy1 * h)) + 1)
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        want = (size * ctx.w) if fit == 'width' else (size * short)
        scale = want / max(1, cw if fit == 'width' else max(cw, ch))
        info.update(files=files, box=crop, scale=scale, wh=(max(1, round(cw * scale)), max(1, round(ch * scale))))
    _prepared[key] = info
    return key, info


def _fit_still(im, fit, size, ctx):
    if fit == 'cover' or fit == 'contain':
        s = (max if fit == 'cover' else min)(ctx.w / im.width, ctx.h / im.height)
    elif fit == 'width':
        s = size * ctx.w / im.width
    else:
        s = size * min(ctx.w, ctx.h) / max(im.width, im.height)
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def _frame_index(ctx, info):
    n = len(info['files'])
    i = int(ctx._t * ctx.fps * float(ctx.p.get('speed') or 1.0) + 1e-6)
    return i % n if ctx.p.get('loop', True) else min(i, n - 1)


def _picture(ctx, key, info):
    """This frame's picture at its placed size, with the outline and shadow asked for."""
    p = ctx.p
    pop = _popup_mod()
    shadow = p.get('shadow')
    shadow = info['fit'] == 'sticker' if shadow is None else bool(shadow)
    if not info['animated']:
        k = (key, 'still', shadow, p.get('outline'), p.get('outline_color'))
        if k not in _frames:
            im = pop._sticker_edge(info['still'], ctx.s(float(p.get('outline') or 0)),
                                   ctx.color(p.get('outline_color') or 'light'))
            _frames[k] = pop._with_shadow(im, ctx.scale) if shadow else im
        return _frames[k]
    i = _frame_index(ctx, info)
    k = (key, i, shadow, p.get('outline'), p.get('outline_color'))
    if k in _frames:
        return _frames[k]
    with Image.open(info['files'][i]) as src:
        im = src.convert('RGBA')
    if info['box']:
        im = im.crop(info['box'])
    if info['wh'] != im.size:
        im = im.resize(info['wh'], Image.LANCZOS)
    if info['fit'] in ('sticker', 'width'):
        if float(p.get('outline') or 0):
            im = pop._sticker_edge(im, ctx.s(float(p['outline'])), ctx.color(p.get('outline_color') or 'light'))
        if shadow:
            im = pop._with_shadow(im, ctx.scale)
    if len(_frames) > 48:
        _frames.clear()
    _frames[k] = im
    return im


def frame_key(ctx):
    key, info = _prepare(ctx)
    if info['animated']:
        return (key, _frame_index(ctx, info), _motion_key(ctx))
    return ('hold', key) if _motion_key(ctx) == 'hold' else (key, ctx._frame)


def _motion_key(ctx):
    p = ctx.p
    t, d = ctx._t, ctx.len
    if float(p.get('wiggle') or 0):
        return ctx._frame
    if t >= float(p.get('in_s', 0.28)) and t <= d - float(p.get('out_s', 0.2)):
        return 'hold'
    return ctx._frame


def draw(ctx):
    key, info = _prepare(ctx)
    p = ctx.p
    pop = _popup_mod()
    full = info['fit'] in ('cover', 'contain')
    look = dict(p)
    look['in'] = p.get('in') or ('none' if full else 'pop')
    look['out'] = p.get('out') or ('none' if full else 'shrink')
    saved, ctx.p = ctx.p, look
    try:
        s, o, dx, dy, ang = pop._state(ctx)
    finally:
        ctx.p = saved
    if s <= 0.01 or o <= 0.01:
        return
    base = _picture(ctx, key, info)
    im = base
    if abs(s - 1) > 1e-3:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BICUBIC)
    if abs(ang) > 0.05:
        im = im.rotate(ang, resample=Image.BICUBIC, expand=True)
    if o < 1:
        im = im.copy()
        im.putalpha(im.getchannel('A').point(lambda v: int(v * o)))
    if full:
        cx, cy = ctx.w / 2, ctx.h / 2
    else:
        cx = min(max(float(p.get('x', 0.5)) * ctx.w, base.width / 2), ctx.w - base.width / 2)
        cy = min(max(float(p.get('y', 0.3)) * ctx.h, base.height / 2), ctx.h - base.height / 2)
    x, y = round(cx + dx - im.width / 2), round(cy + dy - im.height / 2)
    ctx.canvas.alpha_composite(pop._clip(im, x, y, ctx), (max(0, x), max(0, y)))
