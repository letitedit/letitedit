"""Put rendered effect frames into the shot.

overlay   : effect only, transparent background (Shotcut composites it over the footage).
composite : full frames for the segment: plate + effect + (person or near objects back on top),
            plus optional glow, light flicker on the plate and camera shake.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def _load_rgba(path, size):
    im = Image.open(path).convert("RGBA")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, np.float32) / 255.0


def _glow(rgba, strength, radius):
    """Bloom: blur the bright, opaque parts of the effect and add them back."""
    rgb, a = rgba[..., :3], rgba[..., 3:4]
    bright = np.clip((rgb * a - 0.55) / 0.45, 0, 1)
    img = Image.fromarray((bright * 255).astype(np.uint8))
    blur = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), np.float32) / 255.0
    return blur * strength


def overlay_frames(elem_files, out_dir, size, glow=0.0):
    """Upscale element frames to the project size (and optionally bake glow into them)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    radius = max(4, size[1] // 60)
    for i, path in enumerate(elem_files, 1):
        e = _load_rgba(path, size)
        if glow > 0:
            g = _glow(e, glow, radius)
            ga = np.clip(g.max(axis=2, keepdims=True), 0, 1)
            a = e[..., 3:4]
            out_a = a + ga * (1 - a)
            rgb = (e[..., :3] * a + g) / np.maximum(out_a, 1e-4)
            e = np.concatenate([np.clip(rgb, 0, 1), out_a], axis=2)
        Image.fromarray((e * 255).astype(np.uint8), "RGBA").save(out_dir / f"over_{i:05d}.png")
    return sorted(out_dir.glob("over_*.png"))


def composite_frames(plates, elem_files, analysis_dir, out_dir, occlusion="subject", depth_cut=0.6,
                     glow=0.0, flicker=0.0, shake=0.0, flicker_color=(1.0, 0.62, 0.3), seed=3,
                     size=None):
    """Full-frame composite. occlusion: 'subject' (person matte in front), 'depth' (anything nearer
    than depth_cut in front), 'subject+depth', or 'none'."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir = Path(analysis_dir) if analysis_dir else None
    size = tuple(size) if size else Image.open(plates[0]).size
    radius = max(4, size[1] // 60)
    rng = np.random.default_rng(seed)
    n = min(len(plates), len(elem_files))
    energies = []
    for i in range(n):
        e = _load_rgba(elem_files[i], size)
        energies.append(float((e[..., :3].mean(axis=2) * e[..., 3]).mean()))
    peak = max(energies) or 1.0
    for i in range(n):
        plate_img = Image.open(plates[i]).convert("RGB")
        if plate_img.size != size:
            plate_img = plate_img.resize(size, Image.LANCZOS)
        plate = np.asarray(plate_img, np.float32) / 255.0
        e = _load_rgba(elem_files[i], size)
        energy = energies[i] / peak
        if flicker > 0:                      # the effect lights up the room (and the person)
            tint = np.array(flicker_color, np.float32)
            plate = np.clip(plate * (1 + flicker * energy * 0.6 * tint), 0, 1)
        a = e[..., 3:4]
        out = e[..., :3] * a + plate * (1 - a)
        if glow > 0:
            out = np.clip(out + _glow(e, glow, radius), 0, 1)
        if occlusion != "none" and analysis_dir is not None:
            front = np.zeros(plate.shape[:2], np.float32)
            if "subject" in occlusion:
                m = analysis_dir / f"matte_{i + 1:05d}.png"
                if m.exists():
                    front = np.maximum(front, np.asarray(Image.open(m).resize(size), np.float32) / 255.0)
            if "depth" in occlusion:
                d = analysis_dir / f"depth_{i + 1:05d}.png"
                if d.exists():
                    dep = np.asarray(Image.open(d).resize(size), np.float32) / 255.0
                    front = np.maximum(front, np.clip((dep - depth_cut) / 0.08, 0, 1))
            front = front[..., None]
            out = plate * front + out * (1 - front)      # person / near objects stay in front
        img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
        if shake > 0:                        # constant 3% zoom hides edges; offsets follow energy
            amp = shake * energy * size[1] * 0.012
            dx, dy = rng.normal(0, amp, 2) if energy > 0.05 else (0.0, 0.0)
            # never shift further than the 3% zoom margin, or black edges show
            dx = float(np.clip(dx, -size[0] * 0.012, size[0] * 0.012))
            dy = float(np.clip(dy, -size[1] * 0.012, size[1] * 0.012))
            img = img.transform(size, Image.AFFINE, (1.03, 0, dx - size[0] * 0.015, 0, 1.03,
                                                     dy - size[1] * 0.015), Image.BILINEAR)
        img.save(out_dir / f"comp_{i + 1:05d}.jpg", quality=95)
    return sorted(out_dir.glob("comp_*.jpg"))


def filmstrip(frames, out_path, count=6, width=320, background=None):
    """Tile evenly spaced frames; RGBA frames are shown over a neutral background or the plates."""
    frames = list(frames)
    n = len(frames)
    idx = [int(round(k * (n - 1) / (count - 1))) for k in range(count)] if n > 1 else [0] * count
    first = Image.open(frames[0])
    th = int(width * first.height / first.width)
    cols = 3 if count > 3 else count
    rows = (count + cols - 1) // cols
    sheet = Image.new("RGB", (width * cols, th * rows), (25, 25, 25))
    for k, i in enumerate(idx):
        im = Image.open(frames[i])
        if im.mode == "RGBA":
            if background:
                bg = Image.open(background[min(i, len(background) - 1)]).convert("RGBA").resize(im.size)
            else:
                bg = Image.new("RGBA", im.size, (96, 104, 112, 255))
            im = Image.alpha_composite(bg, im)
        sheet.paste(im.convert("RGB").resize((width, th)), ((k % cols) * width, (k // cols) * th))
    sheet.save(out_path)
    return out_path
