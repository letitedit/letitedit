"""Things that follow an object through a shot: track a box (OpenCV CSRT), then draw an arrow /
circle / box / spotlight that sticks to it, blur or pixelate it (faces, license plates), or erase it
(clean background plate for tripod shots, LaMa inpainting otherwise).

Tracks are stored as JSON (one box per frame, project frame rate, project pixel coordinates) so the
agent can inspect, correct and reuse them.
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import common, graphics as g, shots

TRACKS = common.CACHE / "tracks"
YUNET = common.MODELS / "yunet_2023mar.onnx"
LAMA = common.MODELS / "lama_fp32.onnx"


# ---------------------------------------------------------------- tracking
def _tracker():
    import cv2
    try:
        p = cv2.TrackerCSRT_Params()
        return cv2.TrackerCSRT_create(p)
    except Exception:
        return cv2.legacy.TrackerCSRT_create()


def track_box(src, start_s, frames, fps, width, height, box, backwards_frames=0, progress=None):
    """Track box=(x, y, w, h) in project pixels from the first frame. Returns [{f, x, y, w, h, ok}]."""
    import cv2
    x, y, w, h = [int(round(v)) for v in box]
    if w < 4 or h < 4:
        raise ValueError("box too small")
    tr = _tracker()
    out = []
    lost = 0
    for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
        bgr = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR)
        if i == 0:
            tr.init(bgr, (x, y, w, h))
            out.append({"f": 0, "x": x, "y": y, "w": w, "h": h, "ok": True})
            continue
        ok, b = tr.update(bgr)
        if ok:
            out.append({"f": i, "x": float(b[0]), "y": float(b[1]), "w": float(b[2]), "h": float(b[3]), "ok": True})
        else:
            lost += 1
            prev = dict(out[-1])
            prev.update(f=i, ok=False)
            out.append(prev)
        if progress and i % 20 == 0:
            progress("tracking", 0.05 + 0.6 * i / frames)
    return smooth(out), lost


def smooth(boxes, radius=2):
    """Light temporal smoothing of the track (removes CSRT jitter, keeps real motion)."""
    if len(boxes) < 3:
        return boxes
    arr = np.array([[b["x"], b["y"], b["w"], b["h"]] for b in boxes], np.float64)
    out = arr.copy()
    for i in range(len(arr)):
        lo, hi = max(0, i - radius), min(len(arr), i + radius + 1)
        out[i] = arr[lo:hi].mean(axis=0)
    return [{**b, "x": round(float(o[0]), 1), "y": round(float(o[1]), 1), "w": round(float(o[2]), 1),
             "h": round(float(o[3]), 1)} for b, o in zip(boxes, out)]


def detect_faces(src, start_s, frames, fps, width, height, every=2, min_score=0.6, progress=None):
    """Face boxes per frame (YuNet), interpolated between detection frames. Returns list of lists."""
    import cv2
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (width, height), min_score, 0.3, 5000)
    found, last = [], []
    for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
        if i % every == 0:
            _, faces = det.detect(cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
            last = [] if faces is None else [tuple(float(v) for v in f[:4]) for f in faces]
        found.append(last)
        if progress and i % 20 == 0:
            progress("finding faces", 0.05 + 0.5 * i / frames)
    # keep a face for 6 frames after a missed detection (no flashes of an unblurred face)
    held = []
    for i in range(len(found)):
        boxes = list(found[i])
        for j in range(max(0, i - 6), i):
            for b in found[j]:
                if not any(_iou(b, c) > 0.2 for c in boxes):
                    boxes.append(b)
        held.append(boxes)
    return held


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / max(1e-6, aw * ah + bw * bh - inter)


def save_track(track_id, data):
    TRACKS.mkdir(parents=True, exist_ok=True)
    common.write_json(TRACKS / f"{track_id}.json", data)


def load_track(track_id):
    if any(c in track_id for c in "\\/:."):
        raise ValueError("bad track id")
    data = common.read_json(TRACKS / f"{track_id}.json")
    if not data:
        raise KeyError(f"unknown track '{track_id}' (run letitedit_track_object first)")
    return data


# ---------------------------------------------------------------- annotations that follow
def render_annotation(boxes, out_path, fps, width, height, kind="circle", color="yellow", label=None,
                      thickness=None, t_in=0.25, t_out=0.25, pad=0.15):
    """Alpha overlay: circle / box / arrow / spotlight / label sticking to the tracked box."""
    short = min(width, height)
    th = thickness or max(4, int(short * 0.008))
    col = g.color(color)
    fnt = g.font(int(short * 0.06), "black")
    label_img = g.text_image(label, fnt, g.color("white"), stroke=max(3, th // 2), stroke_fill=(0, 0, 0, 255),
                             shadow=3) if label else None
    n = len(boxes)
    dur = n / fps
    with shots.VideoWriter(out_path, width, height, fps, alpha=True) as wr:
        for i, b in enumerate(boxes):
            t = i / fps
            k = min(g.clamp01(t / t_in) if t_in else 1, g.clamp01((dur - t) / t_out) if t_out else 1)
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
            rx, ry = b["w"] / 2 * (1 + pad), b["h"] / 2 * (1 + pad)
            if kind == "spotlight":
                dark = Image.new("RGBA", (width, height), (0, 0, 0, int(150 * k)))
                hole = Image.new("L", (width, height), 0)
                ImageDraw.Draw(hole).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
                hole = hole.filter(ImageFilter.GaussianBlur(short * 0.02))
                dark.putalpha(Image.composite(Image.new("L", hole.size, 0), dark.getchannel("A"), hole))
                layer = dark
            elif kind == "circle":
                grow = g.ease_out_back(g.clamp01(t / max(0.01, t_in * 1.4)), 1.6)
                d.ellipse((cx - rx * grow, cy - ry * grow, cx + rx * grow, cy + ry * grow), outline=(*col[:3], int(255 * k)),
                          width=th)
            elif kind == "box":
                d.rounded_rectangle((cx - rx, cy - ry, cx + rx, cy + ry), radius=int(th * 2),
                                    outline=(*col[:3], int(255 * k)), width=th)
            elif kind == "arrow":
                # arrow from the upper-left (or upper-right near the left edge) pointing at the object
                side = -1 if cx > width * 0.35 else 1
                bob = math.sin(t * 6) * short * 0.012
                tip = (cx + side * rx * 0.9 + side * bob * 0.5, cy - ry * 0.9 - bob)
                tail = (tip[0] + side * short * 0.2, tip[1] - short * 0.2)
                _arrow(d, (tail[0] + 3, tail[1] + 4), (tip[0] + 3, tip[1] + 4), (0, 0, 0, int(110 * k)), th * 2.6)   # shadow
                _arrow(d, tail, tip, (*col[:3], int(255 * k)), th * 2.4)
                if label_img:
                    g.paste_center(layer, label_img, tail[0] + side * label_img.width * 0.35, tail[1] - label_img.height * 0.7, k)
            if label_img and kind != "arrow":
                g.paste_center(layer, label_img, cx, max(label_img.height, cy - ry - label_img.height * 0.8), k)
            wr.write(np.asarray(layer))
    return {"path": str(out_path), "frames": n}


def _arrow(d, tail, tip, fill, width):
    ang = math.atan2(tip[1] - tail[1], tip[0] - tail[0])
    head = width * 3.2
    base = (tip[0] - head * math.cos(ang), tip[1] - head * math.sin(ang))
    d.line([tail, base], fill=fill, width=int(width))
    left = (tip[0] - head * math.cos(ang - 0.5), tip[1] - head * math.sin(ang - 0.5))
    right = (tip[0] - head * math.cos(ang + 0.5), tip[1] - head * math.sin(ang + 0.5))
    d.polygon([tip, left, right], fill=fill)


# ---------------------------------------------------------------- blur / pixelate that follows
def render_blur(src, start_s, frames, fps, width, height, out_path, boxes_per_frame, mode="blur", strength=1.0,
                pad=0.25, ellipse=True, progress=None):
    """Alpha overlay containing blurred/pixelated copies of the regions (faces, plates) only."""
    import cv2
    with shots.VideoWriter(out_path, width, height, fps, alpha=True) as wr:
        for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
            boxes = boxes_per_frame[min(i, len(boxes_per_frame) - 1)] if boxes_per_frame else []
            rgba = np.zeros((height, width, 4), np.uint8)
            for (x, y, w, h) in boxes:
                px, py = w * pad, h * pad
                x0, y0 = int(max(0, x - px)), int(max(0, y - py))
                x1, y1 = int(min(width, x + w + px)), int(min(height, y + h + py))
                if x1 - x0 < 4 or y1 - y0 < 4:
                    continue
                roi = fr[y0:y1, x0:x1]
                if mode == "pixelate":
                    cells = max(4, int(12 / max(0.3, strength)))
                    small = cv2.resize(roi, (cells, max(2, int(cells * roi.shape[0] / roi.shape[1]))),
                                       interpolation=cv2.INTER_AREA)
                    eff = cv2.resize(small, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST)
                else:
                    eff = shots.blur(roi, max(6.0, max(roi.shape[:2]) * 0.12 * strength))
                m = np.zeros(roi.shape[:2], np.uint8)
                if ellipse:
                    cv2.ellipse(m, (m.shape[1] // 2, m.shape[0] // 2), (m.shape[1] // 2 - 1, m.shape[0] // 2 - 1), 0, 0,
                                360, 255, -1)
                else:
                    m[:] = 255
                m = cv2.GaussianBlur(m, (0, 0), max(1.0, min(m.shape) * 0.04))
                region = rgba[y0:y1, x0:x1]
                region[..., :3] = eff
                region[..., 3] = np.maximum(region[..., 3], m)
            wr.write(rgba)
            if progress and i % 20 == 0:
                progress("blurring", 0.6 + 0.35 * i / frames)
    return {"path": str(out_path), "frames": wr.frames}


# ---------------------------------------------------------------- erase
_lama = None


def lama(img_rgb, mask):
    """Inpaint mask (uint8 HxW, 255 = remove) in an RGB uint8 image with LaMa (512x512 crop around
    the hole, so detail elsewhere is untouched)."""
    global _lama
    import onnxruntime as ort
    if _lama is None:
        # DirectML rejects one of LaMa's FFT MatMuls; CUDA works, otherwise CPU (~2-4 s per patch).
        prov = ["CUDAExecutionProvider"] if "CUDAExecutionProvider" in ort.get_available_providers() else []
        try:
            _lama = ort.InferenceSession(str(LAMA), providers=prov + ["CPUExecutionProvider"])
        except Exception:
            _lama = ort.InferenceSession(str(LAMA), providers=["CPUExecutionProvider"])
    import cv2
    H, W = mask.shape
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return img_rgb
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    side = int(min(max(W, H), max(xs.max() - xs.min(), ys.max() - ys.min()) * 2.6 + 64))
    side = max(side, min(W, H, 256))
    x0 = int(min(max(0, cx - side / 2), max(0, W - side)))
    y0 = int(min(max(0, cy - side / 2), max(0, H - side)))
    x1, y1 = min(W, x0 + side), min(H, y0 + side)
    crop, mcrop = img_rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]
    im = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    mk = (cv2.resize(mcrop, (512, 512), interpolation=cv2.INTER_NEAREST) > 127).astype(np.float32)
    feed = {"image": im.transpose(2, 0, 1)[None], "mask": mk[None, None]}
    try:
        with shots.GPU_LOCK:
            out = _lama.run(None, feed)[0][0]
    except Exception:
        _lama = ort.InferenceSession(str(LAMA), providers=["CPUExecutionProvider"])
        out = _lama.run(None, feed)[0][0]
    out = out.transpose(1, 2, 0)
    if out.max() <= 1.5:
        out = out * 255.0
    out = cv2.resize(np.clip(out, 0, 255).astype(np.uint8), (x1 - x0, y1 - y0), interpolation=cv2.INTER_CUBIC)
    soft = cv2.GaussianBlur(mcrop, (0, 0), 3).astype(np.float32)[..., None] / 255.0
    res = img_rgb.copy()
    res[y0:y1, x0:x1] = (out * soft + crop * (1 - soft)).astype(np.uint8)
    return res


def box_mask(width, height, b, pad=0.12, ellipse=False):
    import cv2
    m = np.zeros((height, width), np.uint8)
    px, py = b["w"] * pad, b["h"] * pad
    x0, y0 = int(max(0, b["x"] - px)), int(max(0, b["y"] - py))
    x1, y1 = int(min(width - 1, b["x"] + b["w"] + px)), int(min(height - 1, b["y"] + b["h"] + py))
    if ellipse:
        cv2.ellipse(m, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 255, -1)
    else:
        m[y0:y1, x0:x1] = 255
    return m


def render_erase(src, start_s, frames, fps, width, height, out_path, boxes, static_camera=True, pad=0.12,
                 progress=None):
    """Alpha overlay that paints over the object. Tripod shots: one LaMa patch of the background
    (from the first frame) reused for the whole shot -- steady, no flicker. A moving object over a
    still camera uses a clean plate (per-pixel median of frames where the object is elsewhere)."""
    import cv2
    moving = _moves(boxes)
    plate = None
    if static_camera and moving:
        plate = clean_plate(src, start_s, frames, fps, width, height, boxes, pad, progress)
    patch_cache = None
    with shots.VideoWriter(out_path, width, height, fps, alpha=True) as wr:
        for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
            b = boxes[min(i, len(boxes) - 1)]
            m = box_mask(width, height, b, pad)
            if plate is not None:
                fill = plate
            elif static_camera:
                if patch_cache is None:
                    patch_cache = lama(fr, m)
                fill = patch_cache
            else:
                fill = lama(fr, m)
            soft = cv2.GaussianBlur(m, (0, 0), 4)
            wr.write(np.dstack([fill, soft]))
            if progress and i % 10 == 0:
                progress("erasing", 0.5 + 0.45 * i / frames)
    return {"path": str(out_path), "frames": wr.frames, "method": "clean plate" if plate is not None else
            ("LaMa (one patch, tripod)" if static_camera else "LaMa per frame")}


def _moves(boxes):
    if len(boxes) < 2:
        return False
    xs = [b["x"] + b["w"] / 2 for b in boxes]
    ys = [b["y"] + b["h"] / 2 for b in boxes]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    return span > max(boxes[0]["w"], boxes[0]["h"]) * 1.2


def clean_plate(src, start_s, frames, fps, width, height, boxes, pad=0.12, progress=None, samples=40):
    """Median of frames with the object masked out (object must move away at some point)."""
    step = max(1, frames // samples)
    stack, masks = [], []
    for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
        if i % step:
            continue
        b = boxes[min(i, len(boxes) - 1)]
        stack.append(fr)
        masks.append(box_mask(width, height, b, pad + 0.1) > 0)
        if progress:
            progress("building clean plate", 0.05 + 0.4 * i / frames)
    arr = np.ma.masked_array(np.stack(stack).astype(np.float32),
                             mask=np.repeat(np.stack(masks)[..., None], 3, axis=3))
    plate = np.ma.median(arr, axis=0)
    holes = np.ma.getmaskarray(plate).any(axis=2)
    plate = np.asarray(plate.filled(0), np.uint8)
    if holes.any():                                   # pixels never uncovered: inpaint those
        plate = lama(plate, holes.astype(np.uint8) * 255)
    return plate
