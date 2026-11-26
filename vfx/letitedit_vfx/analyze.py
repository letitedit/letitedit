"""Shot understanding: person matte (MODNet), relative depth (Depth Anything V2 Small),
camera-motion check and a simple light estimate. Small ONNX models; GPU if available, else CPU."""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import config, hardware

_sessions = {}


def _providers():
    import onnxruntime as ort
    available = ort.get_available_providers()
    preferred = ["CUDAExecutionProvider", "DmlExecutionProvider", "CoreMLExecutionProvider"]
    return [p for p in preferred if p in available] + ["CPUExecutionProvider"]


def _session(name):
    if name not in _sessions:
        import onnxruntime as ort
        path = config.MODELS / f"{name}.onnx"
        if not path.exists():
            raise FileNotFoundError(f"model {path} missing; run setup_vfx.py")
        try:
            _sessions[name] = ort.InferenceSession(str(path), providers=_providers())
        except Exception:  # a GPU provider can fail on old drivers; CPU always works
            _sessions[name] = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _sessions[name]


def matte(img, ref=512):
    """Alpha matte of people in the frame, float32 HxW in [0,1] at the image's size."""
    w, h = img.size
    # MODNet expects the SHORT side near 512 (long side capped for speed); a long-side 512
    # input loses heads/torsos in vertical video.
    scale = min(ref / min(w, h), 1024 / max(w, h))
    rw, rh = max(32, int(w * scale) // 32 * 32), max(32, int(h * scale) // 32 * 32)
    x = np.asarray(img.convert("RGB").resize((rw, rh), Image.BILINEAR), dtype=np.float32) / 255.0
    x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
    sess = _session("modnet")
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    m = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    return np.asarray(m, dtype=np.float32) / 255.0


def depth(img, ref=518):
    """Relative depth, float32 HxW in [0,1] where 1 = nearest to camera."""
    w, h = img.size
    scale = ref / max(w, h)
    rw, rh = max(14, int(w * scale) // 14 * 14), max(14, int(h * scale) // 14 * 14)
    x = np.asarray(img.convert("RGB").resize((rw, rh), Image.BICUBIC), dtype=np.float32) / 255.0
    x = ((x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32))
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    sess = _session("depth_anything_v2_small")
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    lo, hi = np.percentile(out, 2), np.percentile(out, 98)
    d = np.clip((out - lo) / max(hi - lo, 1e-6), 0, 1)
    d = Image.fromarray((d * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    return np.asarray(d, dtype=np.float32) / 255.0


def _tile_shift(a, b, grid=3):
    """Median translation over a grid of tiles, so a static overlay (captions, logo) in one
    region cannot mask a camera pan."""
    th, tw = a.shape[0] // grid, a.shape[1] // grid
    vals = [_shift(a[r * th:(r + 1) * th, c * tw:(c + 1) * tw], b[r * th:(r + 1) * th, c * tw:(c + 1) * tw])
            for r in range(grid) for c in range(grid)]
    return float(np.median(vals))


def _shift(a, b):
    """Translation between two grayscale frames via phase correlation (pixels)."""
    fa, fb = np.fft.fft2(a), np.fft.fft2(b)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    y, x = np.unravel_index(np.argmax(c), c.shape)
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return float(np.hypot(x, y))


def analyze(plates, out_dir, fps, progress=None):
    """Run analysis on plate frames; writes matte_/depth_ PNGs, analysis.json and a contact sheet."""
    out_dir = Path(out_dir)
    tier = hardware.detect()
    depth_stride = {"high": 1, "medium": 2, "low": 4}[tier["tier"]]
    from .portrait_matte import MatteStream
    mattes = MatteStream()
    prev_g, last_d = None, None
    shifts, bg_colors, lum_points = [], [], []
    n = len(plates)
    first = Image.open(plates[0])
    W, H = first.size
    for i, path in enumerate(plates):
        img = Image.open(path).convert("RGB")
        m = mattes(np.asarray(img))
        Image.fromarray((m * 255).astype(np.uint8)).save(out_dir / f"matte_{i + 1:05d}.png")
        if i % depth_stride == 0 or last_d is None:
            last_d = depth(img)
        Image.fromarray((last_d * 255).astype(np.uint8)).save(out_dir / f"depth_{i + 1:05d}.png")

        small = np.asarray(img.resize((256, max(16, int(256 * H / W)))).convert("L"), np.float32)
        small_m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize(small.shape[::-1]), np.float32) / 255
        g = small * (1 - small_m) + small.mean() * small_m      # ignore the moving person
        if prev_g is not None:
            shifts.append(_tile_shift(prev_g, g) * (W / 256))
        prev_g = g
        if i % max(1, n // 12) == 0:
            arr = np.asarray(img, np.float32) / 255
            bg = arr[m < 0.3]
            if bg.size:
                bg_colors.append(bg.mean(axis=0))
            lum = arr.mean(axis=2) * (m < 0.3)
            ys, xs = np.nonzero(lum >= np.percentile(lum, 97))
            if len(xs):
                lum_points.append(((xs.mean() / W) - 0.5, (ys.mean() / H) - 0.5))
        if progress:
            progress(i + 1, n)

    motion = float(np.median(shifts)) if shifts else 0.0
    motion_1080 = motion * 1080 / H
    bg = np.mean(bg_colors, axis=0) if bg_colors else np.array([0.5, 0.5, 0.5])
    light_dir = np.mean(lum_points, axis=0) if lum_points else np.array([0.0, -0.3])
    coverage = float(np.mean([np.asarray(Image.open(out_dir / f"matte_{i + 1:05d}.png")).mean() / 255
                              for i in range(0, n, max(1, n // 10))]))
    result = {
        "frames": n, "fps": fps, "width": W, "height": H,
        "subject_coverage": round(coverage, 3),
        "subject_found": coverage > 0.01,
        "camera_motion_px_per_frame_1080p": round(motion_1080, 2),
        "camera_moving": motion_1080 > 1.5,
        "light": {
            "background_rgb": [round(float(c), 3) for c in bg],
            "background_luminance": round(float(bg.mean()), 3),
            "warmth": round(float(bg[0] - bg[2]), 3),
            "brightest_side": {"x": round(float(light_dir[0]), 2), "y": round(float(light_dir[1]), 2)},
        },
        "notes": [],
    }
    if result["camera_moving"]:
        result["notes"].append("Camera moves (handheld?). Effects are screen-locked in this beta and "
                               "will not stick to surfaces; prefer tripod shots or short effects.")
    if not result["subject_found"]:
        result["notes"].append("No person detected; 'behind subject' occlusion has nothing to cut out.")
    (out_dir / "analysis.json").write_text(json.dumps(result, indent=2))
    contact_sheet(out_dir, plates, out_dir / "analysis_sheet.png")
    return result


def contact_sheet(out_dir, plates, out_path, columns=4, width=320):
    """Rows: plate, matte (red overlay), depth -- at 4 moments across the segment."""
    out_dir = Path(out_dir)
    n = len(plates)
    idx = [int(round(k * (n - 1) / (columns - 1))) for k in range(columns)] if n > 1 else [0] * columns
    first = Image.open(plates[0])
    th = int(width * first.height / first.width)
    sheet = Image.new("RGB", (width * columns, th * 3), (20, 20, 20))
    for c, i in enumerate(idx):
        plate = Image.open(plates[i]).convert("RGB").resize((width, th))
        m = Image.open(out_dir / f"matte_{i + 1:05d}.png").resize((width, th))
        red = Image.new("RGB", (width, th), (255, 40, 40))
        over = Image.composite(Image.blend(plate, red, 0.55), plate, m)
        d = Image.open(out_dir / f"depth_{i + 1:05d}.png").resize((width, th))
        dcol = Image.merge("RGB", (d, d.point(lambda v: int(v * 0.6)), d.point(lambda v: 255 - v)))
        sheet.paste(plate, (c * width, 0))
        sheet.paste(over, (c * width, th))
        sheet.paste(dcol, (c * width, 2 * th))
    sheet.save(out_path)
    return out_path


if __name__ == "__main__":  # quick manual check: python -m letitedit_vfx.analyze <frames_dir>
    d = Path(sys.argv[1])
    print(json.dumps(analyze(sorted(d.glob("plate_*.jpg")), d, 30), indent=2))
