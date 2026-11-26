"""Reusable animated templates: lower third (name/title), subscribe button, light leak.
(The progress bar is built natively in Shotcut by the tool layer, so it stays editable.)"""

import math
import random

from PIL import Image, ImageDraw, ImageFilter

from . import graphics as g
from .overlay import OverlayWriter


def lower_third(out_path, fps, width, height, name, title="", duration=4.0, side="left",
                accent="orange", bar="brown", text_color="cream", y=None):
    short = min(width, height)
    vertical = height > width
    name_f = g.font(int(short * (0.062 if vertical else 0.05)), "black")
    title_f = g.font(int(short * (0.036 if vertical else 0.03)), "bold")
    name_img = g.text_image(name, name_f, g.color(text_color), shadow=2)
    title_img = g.text_image(title, title_f, g.color(text_color, 230), shadow=2) if title else None
    pad = int(short * 0.025)
    box_w = max(name_img.width, title_img.width if title_img else 0) + pad * 3
    box_h = name_img.height + (title_img.height if title_img else 0) + pad * 2
    margin = int(width * 0.06)
    y0 = int((y if y is not None else (0.74 if vertical else 0.78)) * height) - box_h // 2
    frames = int(round(duration * fps))
    with OverlayWriter(out_path, width, height, fps) as wr:
        for f in range(frames):
            t = f / fps
            k_in = g.ease_out_cubic(t / 0.45)
            k_out = g.ease_in_back(max(0.0, (t - (duration - 0.4)) / 0.4), 1.2)
            reveal = g.clamp01((t - 0.18) / 0.35)
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            w_now = int(box_w * k_in * (1 - k_out))
            if w_now > 4:
                x0 = margin if side == "left" else width - margin - w_now
                d = ImageDraw.Draw(canvas)
                d.rounded_rectangle((x0, y0, x0 + w_now, y0 + box_h), radius=int(pad * 0.6), fill=g.color(bar, 235))
                ax = x0 if side == "left" else x0 + w_now - int(pad * 0.45)
                d.rectangle((ax, y0, ax + int(pad * 0.45), y0 + box_h), fill=g.color(accent))
                txt = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                tx = (x0 + pad * 2) if side == "left" else (x0 + w_now - pad * 2 - name_img.width)
                txt.alpha_composite(name_img, (int(tx), y0 + pad // 2))
                if title_img:
                    tx2 = (x0 + pad * 2) if side == "left" else (x0 + w_now - pad * 2 - title_img.width)
                    txt.alpha_composite(title_img, (int(tx2), y0 + pad // 2 + name_img.height))
                clip = Image.new("L", (width, height), 0)
                ImageDraw.Draw(clip).rectangle((x0, y0, x0 + w_now, y0 + box_h), fill=int(255 * reveal * (1 - k_out)))
                txt.putalpha(Image.composite(txt.getchannel("A"), Image.new("L", txt.size, 0), clip))
                canvas.alpha_composite(txt)
            wr.write(canvas)
    return {"path": str(out_path), "frames": frames}


def _bell(size, color):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    d.pieslice((s * 0.18, s * 0.12, s * 0.82, s * 0.86), 180, 360, fill=color)
    d.rectangle((s * 0.18, s * 0.49, s * 0.82, s * 0.72), fill=color)
    d.polygon([(s * 0.1, s * 0.78), (s * 0.9, s * 0.78), (s * 0.82, s * 0.68), (s * 0.18, s * 0.68)], fill=color)
    d.ellipse((s * 0.42, s * 0.78, s * 0.58, s * 0.94), fill=color)
    d.ellipse((s * 0.45, s * 0.04, s * 0.55, s * 0.14), fill=color)
    return img


def _cursor(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(0, 0), (0, size * 0.8), (size * 0.22, size * 0.62), (size * 0.38, size * 0.95),
           (size * 0.5, size * 0.9), (size * 0.34, size * 0.58), (size * 0.6, size * 0.58)]
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=max(2, size // 14))
    return img


def subscribe(out_path, fps, width, height, duration=3.5, x=0.5, y=0.8, label="SUBSCRIBE",
              done_label="SUBSCRIBED", color="red", channel=None):
    """Button pops in, a cursor glides over and clicks, button turns grey 'SUBSCRIBED', bell rings."""
    short = min(width, height)
    fnt = g.font(int(short * 0.055), "black")
    pad_x, pad_y = int(short * 0.05), int(short * 0.025)
    labels = {}
    for key, text in (("idle", label), ("done", done_label)):
        tw, th, _ = g.text_size(text, fnt)
        btn = g.rounded_rect((tw + pad_x * 2, th + pad_y * 2), int(short * 0.02),
                             g.color(color) if key == "idle" else (110, 110, 110, 255))
        txt = g.text_image(text, fnt, (255, 255, 255, 255))
        btn.alpha_composite(txt, ((btn.width - txt.width) // 2, (btn.height - txt.height) // 2))
        labels[key] = btn
    bell = _bell(labels["idle"].height, (255, 255, 255, 255))
    bell_bg = g.rounded_rect((bell.width + pad_y, bell.height), int(short * 0.02), (110, 110, 110, 255))
    bell_bg.alpha_composite(g.scaled(bell, 0.7), (int(bell.width * 0.15 + pad_y / 2), int(bell.height * 0.15)))
    cursor = _cursor(int(short * 0.06))
    frames = int(round(duration * fps))
    cx, cy = x * width, y * height
    click_t = 1.2
    with OverlayWriter(out_path, width, height, fps) as wr:
        for f in range(frames):
            t = f / fps
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            s_in = g.ease_out_back(t / 0.35, 2.2)
            s_out = 1 - g.ease_in_back(max(0.0, (t - (duration - 0.35)) / 0.35), 1.6)
            s = max(0.0, min(s_in, s_out))
            btn = labels["done" if t >= click_t else "idle"]
            press = 0.9 if click_t <= t < click_t + 0.12 else 1.0
            if s > 0.02:
                total_w = btn.width + bell_bg.width + pad_y
                bx = cx - total_w / 2 + btn.width / 2
                g.paste_center(canvas, g.scaled(btn, s * press), bx, cy)
                ring = math.sin((t - click_t - 0.25) * 30) * 18 * max(0, 1 - (t - click_t - 0.25) / 0.8) \
                    if t > click_t + 0.25 else 0
                b = g.scaled(bell_bg, s)
                if abs(ring) > 0.5:
                    b = b.rotate(ring, resample=Image.BICUBIC, expand=True)
                g.paste_center(canvas, b, cx + total_w / 2 - bell_bg.width / 2, cy)
                # cursor path: from lower right to the button, click, then away
                if 0.35 < t < duration - 0.4:
                    k = g.ease_in_out((t - 0.35) / (click_t - 0.35))
                    px = cx + width * 0.25 * (1 - k) + (bx - cx) * k
                    py = cy + height * 0.12 * (1 - k)
                    if t > click_t + 0.5:
                        k2 = g.ease_in_out((t - click_t - 0.5) / 0.6)
                        px += width * 0.2 * k2
                        py += height * 0.08 * k2
                    canvas.alpha_composite(g.scaled(cursor, press), (int(px), int(py)))
            wr.write(canvas)
    return {"path": str(out_path), "frames": frames}


def light_leak(out_path, fps, width, height, duration=1.5, palette="warm", strength=0.45, seed=4):
    """Soft drifting colour blooms for transitions; overlay above the cut."""
    rnd = random.Random(seed)
    cols = {"warm": [(255, 140, 40), (255, 80, 30), (255, 200, 90)],
            "golden": [(255, 190, 80), (255, 220, 150), (240, 150, 50)],
            "cool": [(90, 160, 255), (160, 120, 255), (80, 220, 255)],
            "rose": [(255, 90, 140), (255, 150, 120), (255, 200, 160)]}[palette]
    blobs = [(rnd.choice([rnd.uniform(-0.15, 0.25), rnd.uniform(0.75, 1.15)]), rnd.uniform(-0.1, 1.1), rnd.uniform(0.18, 0.38), rnd.choice(cols),
              rnd.uniform(-0.25, 0.25), rnd.uniform(-0.15, 0.15)) for _ in range(4)]
    small = (max(64, width // 8), max(64, height // 8))
    frames = int(round(duration * fps))
    with OverlayWriter(out_path, width, height, fps) as wr:
        for f in range(frames):
            t = f / fps
            env = math.sin(math.pi * g.clamp01(t / duration)) ** 1.5 * strength
            layer = Image.new("RGBA", small, (0, 0, 0, 0))
            for bx, by, r, c, vx, vy in blobs:
                px, py = (bx + vx * t) * small[0], (by + vy * t) * small[1]
                rad = r * max(small)
                blob = Image.new("RGBA", small, (0, 0, 0, 0))
                ImageDraw.Draw(blob).ellipse((px - rad, py - rad, px + rad, py + rad), fill=(*c, int(150 * env)))
                layer.alpha_composite(blob.filter(ImageFilter.GaussianBlur(rad * 0.45)))
            wr.write(layer.resize((width, height), Image.BICUBIC))
    return {"path": str(out_path), "frames": frames}


def solid_png(path, color_value, size=(16, 16)):
    Image.new("RGBA", size, g.color(color_value)).save(path)
    return path
