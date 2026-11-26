"""Picture callouts: show an image (cut out of its background, or as a photo card) beside the
speaker for a moment -- pop in, gentle float, pop out -- e.g. when they say "AC roof unit".

Object cut-out uses BiRefNet-lite (MIT licence, general objects, ~224 MB) via ONNX Runtime.
"""

import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from . import common, graphics as g
from .overlay import OverlayWriter

_session = None
USER_AGENT = "letitedit/1.0 (local video editor; asset download)"


def _birefnet():
    global _session
    if _session is None:
        import onnxruntime as ort
        path = common.MODELS / "birefnet_lite.onnx"
        if not path.exists():
            raise FileNotFoundError(f"object cut-out model missing: {path} (run setup_creator.py)")
        # DirectML hangs the GPU on BiRefNet ("GPU will not respond") and a removed device breaks every
        # other GPU session in the process, so DirectML is never used for this model.
        prov = [p for p in ("CUDAExecutionProvider", "CoreMLExecutionProvider")
                if p in ort.get_available_providers()] + ["CPUExecutionProvider"]
        try:
            _session = ort.InferenceSession(str(path), providers=prov)
        except Exception:
            _session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _session


def cutout(img):
    """RGBA image with the main object kept and the background transparent, cropped to content."""
    img = img.convert("RGB")
    x = np.asarray(img.resize((1024, 1024), Image.BICUBIC), np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    global _session
    sess = _birefnet()
    from . import shots
    try:
        with shots.GPU_LOCK:
            out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    except Exception:
        # Some GPU drivers (DirectML) reject BiRefNet ops; one image on the CPU takes a few seconds.
        import onnxruntime as ort
        _session = ort.InferenceSession(str(common.MODELS / "birefnet_lite.onnx"),
                                        providers=["CPUExecutionProvider"])
        out = _session.run(None, {_session.get_inputs()[0].name: x})[0][0, 0]
    if out.min() < 0 or out.max() > 1:          # logits -> probability
        out = 1 / (1 + np.exp(-out))
    mask = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).resize(img.size, Image.BILINEAR)
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    box = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
    coverage = float(np.asarray(mask).mean() / 255)
    return (rgba.crop(box) if box else rgba), coverage


def fetch(source, dest_dir):
    """Copy a local file or download an http(s) URL into the project's assets folder."""
    dest_dir = Path(common.check_output_path(Path(dest_dir) / "x")).parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    if str(source).lower().startswith(("http://", "https://")):
        name = Path(urllib.parse.urlparse(source).path).name or "image"
        if "." not in name:
            name += ".jpg"
        dest = dest_dir / f"{common.stamp()}-{name[-80:]}"
        req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
            shutil.copyfileobj(r, fh)
        Image.open(dest).verify()
        return dest
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(source)
    dest = dest_dir / f"{common.stamp()}-{src.name}"
    shutil.copy2(src, dest)
    return dest


def render(image, out_path, fps, width, height, duration=2.5, x=0.74, y=0.32, size=0.38,
           style="sticker", label=None, label_color="white", accent="orange", t_in=0.28, t_out=0.22,
           tilt_deg=-4.0, float_px=None):
    """image: RGBA (already cut out for 'sticker') or RGB for 'card'. size: fraction of the
    shorter frame side for the image's longer side."""
    short = min(width, height)
    target = short * size
    if style == "sticker":
        art = g.sticker(g.fit(image, target, target), outline=max(6, int(short * 0.012)),
                        shadow=max(8, int(short * 0.018)))
    elif style == "card":
        art = g.card(g.fit(image, target, target), pad=max(8, int(short * 0.012)),
                     radius=max(10, int(short * 0.025)), shadow=max(8, int(short * 0.02)))
    else:
        art = g.fit(image.convert("RGBA"), target, target)
    if label:
        fnt = g.font(int(short * 0.05), "black")
        tag = g.text_image(label, fnt, g.color(label_color), stroke=max(3, int(short * 0.006)),
                           shadow=max(2, int(short * 0.004)))
        pill = g.rounded_rect((tag.width + int(short * 0.04), tag.height + int(short * 0.02)),
                              int(short * 0.03), g.color(accent))
        pill.alpha_composite(tag, ((pill.width - tag.width) // 2, (pill.height - tag.height) // 2))
        combo = Image.new("RGBA", (max(art.width, pill.width), art.height + pill.height - int(short * 0.02)),
                          (0, 0, 0, 0))
        combo.alpha_composite(art, ((combo.width - art.width) // 2, 0))
        combo.alpha_composite(pill, ((combo.width - pill.width) // 2, art.height - int(short * 0.03)))
        art = combo
    art = art.rotate(tilt_deg, resample=Image.BICUBIC, expand=True)
    frames = max(1, int(round(duration * fps)))
    float_px = float_px if float_px is not None else short * 0.008
    cx, cy = x * width, y * height
    import math
    with OverlayWriter(out_path, width, height, fps) as wr:
        for f in range(frames):
            t = f / fps
            if t < t_in:
                s = g.ease_out_back(t / t_in, 2.4)
                op = g.clamp01(t / (t_in * 0.5))
            elif t > duration - t_out:
                k = (t - (duration - t_out)) / t_out
                s = 1 - g.ease_in_back(k, 1.6)
                op = 1 - g.clamp01((k - 0.5) * 2)
            else:
                s, op = 1.0, 1.0
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            if s > 0.02 and op > 0.01:
                bob = math.sin(t * 2.4) * float_px
                g.paste_center(canvas, g.scaled(art, s), cx, cy + bob, op)
            wr.write(canvas)
    return {"path": str(out_path), "frames": frames}
