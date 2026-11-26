"""Three depth planes from a still and its greyscale depth mask.

The mask can come from a photographer's own depth edit or the local depth tool.
It is read once, before frame drawing; no model runs alongside a render.
"""
from functools import lru_cache
from PIL import Image, ImageFilter

TITLE = 'Depth parallax'
DESCRIPTION = ('Move foreground, middle distance and background of a still at different speeds. '
               'image is a still path; depth_mask is a greyscale picture (white nearest).')
PARAMS = {'image': '', 'depth_mask': '', 'strength': 32, 'background_blur': 3}
ANIMATED = True
DEFAULT_LEN = 3.0


def _cover(path, w, h, pad):
    image = Image.open(path).convert('RGBA')
    width, height = w + 2 * pad, h + 2 * pad
    scale = max(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(size, Image.Resampling.LANCZOS)
    return image.crop(((image.width - width) // 2, (image.height - height) // 2,
                       (image.width + width) // 2, (image.height + height) // 2))


@lru_cache(maxsize=12)
def _planes(image_path, mask_path, w, h, blur):
    pad = round(max(w, h) * .08)
    still = _cover(image_path, w, h, pad)
    depth = _cover(mask_path, w, h, pad).convert('L')
    near = depth.point(lambda v: 255 if v >= 175 else 0).filter(ImageFilter.GaussianBlur(max(1, h / 500)))
    middle = depth.point(lambda v: 255 if 75 <= v < 175 else 0).filter(ImageFilter.GaussianBlur(max(1, h / 600)))
    background = still.filter(ImageFilter.GaussianBlur(blur)) if blur else still.copy()
    mid = still.copy()
    mid.putalpha(middle)
    front = still.copy()
    front.putalpha(near)
    return pad, background, mid, front


def draw(ctx):
    p = ctx.p
    if not p.get('image') or not p.get('depth_mask'):
        raise ValueError('depth_parallax needs image and depth_mask picture paths')
    strength = min(ctx.w * .06, ctx.s(float(p['strength'])))
    blur = max(0, round(ctx.s(float(p.get('background_blur', 0)))))
    pad, background, middle, front = _planes(str(p['image']), str(p['depth_mask']), ctx.w, ctx.h, blur)
    progress = ctx.ease('in_out', ctx.t / max(.001, ctx.len)) * 2 - 1
    for im, speed in ((background, -.3), (middle, .35), (front, 1.0)):
        dx = round(progress * strength * speed)
        dy = round(progress * strength * speed * .18)
        ctx.canvas.alpha_composite(im.crop((pad - dx, pad - dy,
                                           pad - dx + ctx.w, pad - dy + ctx.h)))
