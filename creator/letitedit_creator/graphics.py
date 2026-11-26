"""Drawing helpers shared by captions, callouts and templates (PIL only; fast on any machine)."""

import math
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BRAND = {
    "cream": (239, 226, 196), "brown": (92, 58, 33), "orange": (199, 107, 46), "tan": (184, 138, 87),
    "white": (255, 255, 255), "black": (0, 0, 0), "yellow": (255, 214, 64), "red": (230, 40, 40),
}

FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"],
    "black": ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/seguibl.ttf",
              "/System/Library/Fonts/Supplemental/Arial Black.ttf"],
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
}


def color(value, alpha=255):
    if isinstance(value, (tuple, list)):
        return (*value[:3], value[3] if len(value) > 3 else alpha)
    value = str(value)
    if value in BRAND:
        return (*BRAND[value], alpha)
    v = value.lstrip("#")
    if len(v) == 8:   # AARRGGBB like Shotcut
        return (int(v[2:4], 16), int(v[4:6], 16), int(v[6:8], 16), int(v[0:2], 16))
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), alpha)


@lru_cache(maxsize=64)
def font(size, weight="bold", path=None):
    for p in ([path] if path else []) + FONT_CANDIDATES.get(weight, FONT_CANDIDATES["bold"]):
        if p and Path(p).exists():
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default(int(size))


# --------------------------------------------------------------------------- easing
def clamp01(t):
    return max(0.0, min(1.0, t))


def ease_out_back(t, s=1.70158):
    t = clamp01(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_back(t, s=1.70158):
    t = clamp01(t)
    return t * t * ((s + 1) * t - s)


def ease_out_cubic(t):
    return 1 - (1 - clamp01(t)) ** 3


def ease_in_out(t):
    t = clamp01(t)
    return 3 * t * t - 2 * t * t * t


def envelope(t, total, t_in, t_out):
    """0..1 visibility for an element shown from 0 to total with in/out transitions."""
    if t < t_in:
        return t / t_in if t_in else 1.0
    if t > total - t_out:
        return max(0.0, (total - t) / t_out) if t_out else 1.0
    return 1.0


# --------------------------------------------------------------------------- text
def text_size(txt, fnt, stroke=0):
    box = fnt.getbbox(txt, stroke_width=stroke)
    return box[2] - box[0], box[3] - box[1], box


def text_image(txt, fnt, fill, stroke=0, stroke_fill=(0, 0, 0, 255), shadow=0, shadow_fill=(0, 0, 0, 160)):
    """Tight RGBA image of a string with optional outline and soft drop shadow."""
    w, h, box = text_size(txt, fnt, stroke)
    pad = stroke + shadow * 2 + 4
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    origin = (pad - box[0], pad - box[1])
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((origin[0] + shadow, origin[1] + shadow), txt, font=fnt, fill=shadow_fill,
                                stroke_width=stroke, stroke_fill=shadow_fill)
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(shadow)))
        d = ImageDraw.Draw(img)
    d.text(origin, txt, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return img


def scaled(img, s):
    if abs(s - 1) < 1e-3:
        return img
    w, h = max(1, int(img.width * s)), max(1, int(img.height * s))
    return img.resize((w, h), Image.LANCZOS)


def paste_center(canvas, img, cx, cy, opacity=1.0):
    if opacity < 1:
        a = img.getchannel("A").point(lambda v: int(v * opacity))
        img = img.copy()
        img.putalpha(a)
    canvas.alpha_composite(img, (int(round(cx - img.width / 2)), int(round(cy - img.height / 2))))


def rounded_rect(size, radius, fill):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=fill)
    return img


# --------------------------------------------------------------------------- stickers
def sticker(img, outline=12, outline_color=(255, 255, 255, 255), shadow=18, shadow_alpha=110):
    """Die-cut sticker look: thick white border following the alpha, soft drop shadow."""
    img = img.convert("RGBA")
    pad = outline + shadow * 2
    base = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    base.paste(img, (pad, pad))
    alpha = base.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    grown = alpha.filter(ImageFilter.MaxFilter(outline * 2 + 1)) if outline else alpha
    border = Image.new("RGBA", base.size, outline_color)
    border.putalpha(grown)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 255))
        sh.putalpha(grown.point(lambda v: int(v * shadow_alpha / 255)))
        sh = sh.filter(ImageFilter.GaussianBlur(shadow / 2))
        out.alpha_composite(sh, (int(shadow * 0.4), int(shadow * 0.6)))
    out.alpha_composite(border)
    out.alpha_composite(base)
    return out.crop(out.getbbox() or (0, 0, 1, 1))


def card(img, pad=18, radius=28, fill=(255, 255, 255, 255), shadow=20):
    """Rounded photo card with shadow for images that should keep their background."""
    img = img.convert("RGBA")
    w, h = img.width + pad * 2, img.height + pad * 2
    out = Image.new("RGBA", (w + shadow * 3, h + shadow * 3), (0, 0, 0, 0))
    sh = rounded_rect((w, h), radius, (0, 0, 0, 120)).filter(ImageFilter.GaussianBlur(shadow / 2))
    out.alpha_composite(sh, (shadow, shadow + shadow // 2))
    out.alpha_composite(rounded_rect((w, h), radius, fill), (shadow // 2, shadow // 2))
    mask = rounded_rect(img.size, max(4, radius - pad // 2), (255, 255, 255, 255)).getchannel("A")
    photo = img.copy()
    photo.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    out.alpha_composite(photo, (shadow // 2 + pad, shadow // 2 + pad))
    return out


def fit(img, max_w, max_h):
    s = min(max_w / img.width, max_h / img.height)
    return scaled(img, s)


def wrap_words(words, fnt, max_width, stroke=0):
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and text_size(trial, fnt, stroke)[0] > max_width:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines
