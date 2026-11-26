"""Sky replacement: find the sky (far away per the depth model + bright, smooth, connected to the top
of the frame), refine its edge against the picture (guided filter: tree branches, roof lines), and
put a new sky picture/video behind the scene, moving with the camera. Foreground gets a light grade
toward the new sky so it doesn't look pasted on."""

import numpy as np
from PIL import Image

from . import shots
from .backdrop import Background, _match, follow

import sys
from . import common
sys.path.insert(0, str(common.LETITEDIT_ROOT / "vfx"))
from letitedit_vfx import analyze as vana  # noqa: E402


_session = None


def _sky_model():
    """U2-Net sky segmentation (xiongzhu666/Sky-Segmentation-and-Post-processing, MIT)."""
    global _session
    if _session is None:
        import onnxruntime as ort
        path = common.MODELS / "skyseg.onnx"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing (sky model)")
        try:
            _session = ort.InferenceSession(str(path), providers=vana._providers())
        except Exception:
            _session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    return _session


def sky_mask(frame, prev=None, sensitivity=0.5):
    """Float HxW sky probability for an RGB uint8 frame (0..1)."""
    import cv2
    global _session
    h, w = frame.shape[:2]
    x = cv2.resize(frame, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    feed = {_sky_model().get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)}
    try:
        with shots.GPU_LOCK:
            p = _session.run(None, feed)[0][0, 0]
    except Exception:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(common.MODELS / "skyseg.onnx"), providers=["CPUExecutionProvider"])
        p = _session.run(None, feed)[0][0, 0]
    p = (p - p.min()) / max(1e-6, p.max() - p.min()) if p.max() > 1.001 or p.min() < -0.001 else p
    small_w = 480
    sh = max(8, int(h * small_w / w))
    sm = cv2.resize(frame, (small_w, sh), interpolation=cv2.INTER_AREA)
    lo = 0.5 - 0.35 * (sensitivity - 0.5)          # sensitivity 0..1 moves the cut-off
    soft = np.clip((cv2.resize(p.astype(np.float32), (small_w, sh)) - (lo - 0.15)) / 0.3, 0, 1)
    # refine the edge with the picture itself (tree branches, roof lines)
    try:
        soft = cv2.ximgproc.guidedFilter(sm, soft.astype(np.float32), 4, 1e-3)
    except Exception:
        soft = cv2.GaussianBlur(soft, (0, 0), 1.2)
    m = cv2.resize(np.clip(soft, 0, 1).astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    if prev is not None:
        dlt = np.abs(m - prev)
        k = np.where(dlt < 0.25, 0.6, 0.15).astype(np.float32)
        m = m * (1 - k) + prev * k
    return m.astype(np.float32)


def render_sky(src, start_s, frames, fps, width, height, out_path, kind="image", source=None, sensitivity=0.5,
               match=0.2, follow_camera=True, progress=None):
    import cv2
    from .backdrop import process
    bg = Background(kind, source, width, height, fps, frames, drift=0.0 if follow_camera else 0.08)
    cam = shots.CameraMotion() if follow_camera else None
    state = {"prev": None, "coverage": []}
    inside = shots.rect_mask(shots.content_rect(src, width, height), width, height)

    def seq(fr):
        m = sky_mask(fr, state["prev"], sensitivity) * inside   # never the letterbox bars
        state["prev"] = m
        state["coverage"].append(float(m.mean()))
        b = bg.next(fr)
        if cam is not None:
            b = follow(b, cam.update(fr, m), margin=1.15)
        return m, b

    def comp(fr, s):
        m, b = s
        fg = fr.astype(np.float32)
        sky = b.astype(np.float32)
        if match > 0:
            fg = _match(fg, sky[::4, ::4].reshape(-1, 3).mean(axis=0), 1 - m, match)
        m3 = cv2.merge([m, m, m])
        return cv2.convertScaleAbs(cv2.add(fg, cv2.multiply(cv2.subtract(sky, fg), m3)))

    with shots.VideoWriter(out_path, width, height, fps) as wr:
        process(shots.FrameReader(src, start_s, frames, fps, width, height), seq, comp, wr, frames, progress)
    cov = state["coverage"]
    return {"path": str(out_path), "frames": wr.frames, "sky_coverage": round(float(np.mean(cov)) if cov else 0, 3)}


def preview_mask(frame, sensitivity=0.5):
    """RGB preview: sky tinted magenta (to check what will be replaced)."""
    m = sky_mask(frame, None, sensitivity)[..., None]
    tint = np.array([255, 0, 255], np.float32)
    return np.clip(frame * (1 - 0.6 * m) + tint * 0.6 * m, 0, 255).astype(np.uint8), float(m.mean())
