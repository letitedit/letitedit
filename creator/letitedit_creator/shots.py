"""Shot-level video processing for the VFX-beta creator effects (backdrop, text behind the head,
clone yourself, sky replacement, tracked blur/erase...).

Frames are streamed (ffmpeg decode pipe -> numpy -> ffmpeg encode pipe), so a whole shot can be
processed without a time cap or temp image sequences. Frames are decoded from the clip's SOURCE
file at the project size/fps (letterboxed like Shotcut does), not from the rendered timeline, so
overlays already on the timeline (captions, stickers) never get baked in.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import common

sys.path.insert(0, str(common.LETITEDIT_ROOT / "vfx"))
from letitedit_vfx import analyze as vana  # noqa: E402

# One model inference at a time per process: GPU providers (DirectML) can crash the whole MCP server
# when two jobs run sessions concurrently. CPU work (compositing, encoding) still runs in parallel.
import threading  # noqa: E402
GPU_LOCK = threading.RLock()


def matte(img, ref=512):
    with GPU_LOCK:
        return vana.matte(img, ref=ref)


def fit_filter(w, h, fps=None, mode="fit"):
    """ffmpeg -vf that matches Shotcut's default fit (letterbox) or a fill (crop) to w x h."""
    pre = f"fps={fps}," if fps else ""
    if mode == "fill":
        return f"{pre}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return (f"{pre}scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")


class FrameReader:
    """Iterate RGB uint8 frames (H, W, 3) of `path` from start_s for `count` frames."""

    def __init__(self, path, start_s, count, fps, width, height, mode="fit", loop=False):
        self.w, self.h, self.count = width, height, count
        args = [common.ffmpeg(), "-v", "error"]
        if loop:
            args += ["-stream_loop", "-1"]
        args += ["-ss", f"{max(0.0, start_s):.4f}", "-i", str(path), "-frames:v", str(count),
                 "-vf", fit_filter(width, height, fps, mode), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=common.NO_WINDOW)

    def __iter__(self):
        size = self.w * self.h * 3
        n = 0
        while n < self.count:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                break
            n += 1
            yield np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3)
        self.close()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


class VideoWriter:
    """RGB frames -> H.264 (opaque, full frame) or RGBA -> ProRes 4444 (overlay with alpha)."""

    def __init__(self, path, width, height, fps, alpha=False):
        self.path = common.check_output_path(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.alpha = alpha
        # qscale 8 with a lossless 16-bit alpha: a third of the default size, the alpha identical, colour about 50 dB
        # against the default (T45); threads capped at 4 (the PC rule)
        codec = (["-threads", "4", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
                  "-qscale:v", "8", "-vendor", "apl0"]
                 if alpha else ["-c:v", "libx264", "-crf", "15", "-preset", "fast", "-pix_fmt", "yuv420p",
                                "-movflags", "+faststart"])
        args = [common.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24",
                "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", *codec, str(self.path)]
        self.proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=common.NO_WINDOW)
        self.frames = 0

    def write(self, frame):
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        if self.alpha:
            # fully transparent pixels -> black: ProRes then spends almost nothing on them
            # (a 2 s full-frame overlay drops from ~170 MB to a few MB)
            frame = frame.copy()
            frame[frame[..., 3] == 0, :3] = 0
        self.proc.stdin.write(frame.tobytes())
        self.frames += 1

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg encode failed: {err[-800:]}")
        return self.path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.close()
        else:
            self.proc.kill()


def probe_duration(path):
    out = common.run([common.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                      str(path)]).strip()
    try:
        return float(out)
    except ValueError:
        return None


def content_rect(path, width, height):
    """Where the picture sits inside the project frame after Shotcut's letterbox fit
    (x, y, w, h) -- e.g. vertical phone video in a 16:9 project has black side bars."""
    import json as _json
    try:
        out = common.run([common.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:stream_side_data=rotation", "-of", "json", str(path)])
        st = _json.loads(out)["streams"][0]
        sw, sh = int(st["width"]), int(st["height"])
        rot = 0
        for sd in st.get("side_data_list", []) or []:
            rot = int(sd.get("rotation", 0) or 0)
        if abs(rot) % 180 == 90:
            sw, sh = sh, sw
    except Exception:
        return 0, 0, width, height
    s = min(width / sw, height / sh)
    cw, ch = int(round(sw * s)), int(round(sh * s))
    return (width - cw) // 2, (height - ch) // 2, cw, ch


def rect_mask(rect, width, height):
    m = np.zeros((height, width), np.float32)
    x, y, w, h = rect
    m[y:y + h, x:x + w] = 1.0
    return m


def main_subject(matte, keep=0.15):
    """Drop stray matte blobs: keep connected regions at least `keep` x the largest one."""
    import cv2
    binary = (matte > 0.3).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 2:
        return matte
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = areas.max()
    good = np.zeros(n, np.uint8)
    good[1:] = areas >= big * keep
    region = good[lab].astype(np.float32)
    region = cv2.dilate(region, np.ones((9, 9), np.uint8))            # keep soft hair edges
    return (matte * region).astype(np.float32)


def is_still(path):
    return Path(path).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


# ---------------------------------------------------------------- stationary (tripod) check
class CameraMotion:
    """Cumulative camera motion (similarity transform: shift, rotation, zoom) relative to the first
    frame, from optical flow on background points. People are masked out, so someone moving
    in front of a tripod camera does not count as camera motion."""

    def __init__(self, work_width=480):
        self.ww = work_width
        self.prev = self.pts = None
        self.M = np.eye(3, dtype=np.float64)          # frame0 -> current, in work-resolution pixels
        self.scale = 1.0
        self.lost = 0

    def _mask(self, shape, matte):
        if matte is None:
            return None
        import cv2
        m = cv2.resize(matte.astype(np.float32), (shape[1], shape[0]))
        m = (m < 0.25).astype(np.uint8) * 255
        return cv2.erode(m, np.ones((15, 15), np.uint8))

    def update(self, frame, matte=None):
        """Feed the next frame (RGB uint8); returns the 2x3 frame0->current transform in FULL-res pixels."""
        import cv2
        h, w = frame.shape[:2]
        self.scale = self.ww / w
        g = cv2.cvtColor(cv2.resize(frame, (self.ww, max(8, int(h * self.scale)))), cv2.COLOR_RGB2GRAY)
        mask = self._mask(g.shape, matte)
        if self.prev is not None and self.pts is not None and len(self.pts) >= 8:
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, g, self.pts, None, winSize=(21, 21), maxLevel=3)
            ok = st.reshape(-1) == 1
            if mask is not None:                       # drop points that are now on the person
                p = nxt.reshape(-1, 2)
                xi = np.clip(p[:, 0].astype(int), 0, g.shape[1] - 1)
                yi = np.clip(p[:, 1].astype(int), 0, g.shape[0] - 1)
                ok &= mask[yi, xi] > 0
            a, b = self.pts[ok], nxt[ok]
            if len(a) >= 8:
                T, inl = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                if T is not None:
                    self.M = np.vstack([T, [0, 0, 1]]) @ self.M
                    keep = inl.reshape(-1) == 1 if inl is not None else np.ones(len(b), bool)
                    self.pts = b[keep].reshape(-1, 1, 2)
                else:
                    self.lost += 1
            else:
                self.lost += 1
        if self.pts is None or len(self.pts) < 120:
            new = cv2.goodFeaturesToTrack(g, maxCorners=400, qualityLevel=0.01, minDistance=7, mask=mask)
            if new is not None:
                self.pts = new.astype(np.float32) if self.pts is None or len(self.pts) == 0 else \
                    np.concatenate([self.pts.astype(np.float32), new.astype(np.float32)])[:400]
        self.prev = g
        return self.full()

    def full(self):
        s = self.scale
        S, Si = np.diag([s, s, 1.0]), np.diag([1 / s, 1 / s, 1.0])
        return (Si @ self.M @ S)[:2]

    def magnitude(self, width):
        """(shift as fraction of width, rotation degrees, zoom change) of the cumulative motion."""
        M = self.full()
        zoom = float(np.hypot(M[0, 0], M[1, 0]))
        rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
        return float(np.hypot(M[0, 2], M[1, 2]) / width), rot, zoom - 1


def stationary(path, start_s, duration_s, fps_sample=6, max_shift=0.012, max_rot=0.6, max_zoom=0.012):
    """Is the camera locked off (tripod / propped up) for this stretch? Tracks the background at a
    few frames per second and reports the largest drift from the first frame."""
    import cv2
    frames = max(4, int(duration_s * fps_sample))
    w, h = 480, 270
    peak = [0.0, 0.0, 0.0]
    n, lost = 0, 0
    g0 = pts0 = None
    for i, fr in enumerate(FrameReader(path, start_s, frames, fps_sample, w, h, mode="fill")):
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        person = matte(Image.fromarray(fr), ref=256) > 0.25
        n += 1
        if g0 is None:
            bgmask = cv2.erode((~person).astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
            pts0 = cv2.goodFeaturesToTrack(g, maxCorners=400, qualityLevel=0.01, minDistance=7, mask=bgmask)
            g0 = g
            if pts0 is None or len(pts0) < 12:
                return {"stationary": False, "reason": "not enough background detail to judge the camera",
                        "frames_checked": 1}
            continue
        # compare DIRECTLY with the first frame (no accumulated drift)
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(g0, g, pts0, None, winSize=(31, 31), maxLevel=4)
        ok = st.reshape(-1) == 1
        p = nxt.reshape(-1, 2)
        xi, yi = np.clip(p[:, 0].astype(int), 0, w - 1), np.clip(p[:, 1].astype(int), 0, h - 1)
        ok &= ~person[yi, xi]
        if ok.sum() < 10:
            lost += 1
            peak[0] = max(peak[0], 1.0)
            continue
        T, inl = cv2.estimateAffinePartial2D(pts0[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=2.0)
        if T is None or (inl is not None and inl.sum() < 8):
            lost += 1
            peak[0] = max(peak[0], 1.0)
            continue
        zoom = float(np.hypot(T[0, 0], T[1, 0])) - 1
        rot = float(np.degrees(np.arctan2(T[1, 0], T[0, 0])))
        moved = T @ np.array([w / 2, h / 2, 1.0]) - np.array([w / 2, h / 2])      # frame-centre displacement
        shift = float(np.hypot(*moved) / w)
        peak = [max(peak[0], shift), max(peak[1], abs(rot)), max(peak[2], abs(zoom))]
    if n < 3:
        raise RuntimeError("could not decode frames to check the shot")
    ok = peak[0] <= max_shift and peak[1] <= max_rot and peak[2] <= max_zoom and lost == 0
    return {"stationary": ok, "max_shift": round(min(peak[0], 1.0), 4), "max_rotation_deg": round(peak[1], 2),
            "max_zoom": round(peak[2], 4), "frames_checked": n, "lost_tracking": lost}


# ---------------------------------------------------------------- mattes
class MatteStream:
    """Per-frame person matte with flicker suppression (blend toward the previous matte where
    the change is small; follow immediately where the person really moved)."""

    def __init__(self, ref=512, smooth=0.55, tighten=0.06):
        self.ref, self.smooth, self.tighten, self.prev = ref, smooth, tighten, None

    def __call__(self, frame):
        m = matte(Image.fromarray(frame), ref=self.ref)
        if self.tighten:
            m = np.clip((m - self.tighten) / (1 - 2 * self.tighten), 0, 1)
        m = main_subject(m)
        if self.prev is not None:
            d = np.abs(m - self.prev)
            k = np.where(d < 0.2, self.smooth, 0.0)
            m = (m * (1 - k) + self.prev * k).astype(np.float32)
        self.prev = m
        return m


def blur(arr, radius):
    """Gaussian blur of float/uint8 HxW or HxWxC array (OpenCV when available)."""
    if radius <= 0:
        return arr
    try:
        import cv2
        if radius >= 4:            # big blurs: blur a downscaled copy and scale back (same look, ~20x faster)
            s = min(8.0, radius / 2.0)
            h, w = arr.shape[:2]
            small = cv2.resize(arr, (max(1, int(w / s)), max(1, int(h / s))), interpolation=cv2.INTER_AREA)
            r = radius / s
            k = int(r * 3) * 2 + 1
            return cv2.resize(cv2.GaussianBlur(small, (k, k), r), (w, h), interpolation=cv2.INTER_LINEAR)
        k = int(radius * 3) * 2 + 1
        return cv2.GaussianBlur(arr, (k, k), radius)
    except ImportError:
        from PIL import ImageFilter
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        return np.asarray(img.filter(ImageFilter.GaussianBlur(radius))).astype(arr.dtype)
