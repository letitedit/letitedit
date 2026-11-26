"""AI backdrop / virtual green screen: keep the person, replace everything behind them with a
video, a picture, a rendered "computer screen" (HTML), a blurred version of the real background
(portrait mode) or a colour. Whole-shot, for locked-off (tripod) shots.

Also: text behind the head and clone-yourself, which reuse the same person matte stream.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import common, graphics as g, shots

EDGE_CANDIDATES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                   "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]

SCREEN_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;font-family:'Segoe UI',system-ui,Arial,sans-serif;}}
body{{background:{wallpaper};display:flex;align-items:center;justify-content:center;}}
.win{{width:86%;height:80%;background:{panel};border-radius:14px;box-shadow:0 30px 80px rgba(0,0,0,.45);
 overflow:hidden;display:flex;flex-direction:column;color:{text}}}
.bar{{height:5.5%;min-height:34px;background:{bar};display:flex;align-items:center;padding:0 18px;gap:10px;
 font-size:1.5vw;color:{bar_text}}}
.dot{{width:1vw;height:1vw;border-radius:50%;}}
.url{{flex:1;margin-left:16px;background:rgba(255,255,255,.12);border-radius:8px;padding:4px 14px;font-size:1.2vw}}
.body{{flex:1;padding:3.5% 4.5%;font-size:2.1vw;line-height:1.35;overflow:hidden}}
h1{{font-size:3.4vw;margin:0 0 2.5%}}
</style></head><body><div class="win"><div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span><span class="dot" style="background:#28c840"></span>
<span class="url">{url}</span></div><div class="body"><h1>{title}</h1>{body}</div></div></body></html>"""

THEMES = {"dark": dict(wallpaper="linear-gradient(135deg,#1d2b3a,#3b2a4d)", panel="#1e1f24", text="#f1f1f1",
                       bar="#2b2c33", bar_text="#ddd"),
          "light": dict(wallpaper="linear-gradient(135deg,#9cc3e6,#e7c9a9)", panel="#ffffff", text="#222",
                        bar="#ececec", bar_text="#333"),
          "brand": dict(wallpaper="linear-gradient(135deg,#5c3a21,#c76b2e)", panel="#efe2c4", text="#3a2414",
                        bar="#5c3a21", bar_text="#efe2c4")}


def browser():
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    found = shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")
    if not found:
        raise RuntimeError("no Edge/Chrome found to render the screen; pass an image instead")
    return found


def screen_html(title="", body="", url="", theme="dark"):
    """Fill the built-in 'browser window on a desktop' template (body may contain HTML)."""
    import html as h
    return SCREEN_TEMPLATE.format(title=h.escape(title), body=body, url=h.escape(url), **THEMES.get(theme, THEMES["dark"]))


def render_html(html_or_path, out_png, width, height):
    """Screenshot an HTML page at width x height with a headless browser (isolated profile)."""
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="scr-", dir=common.WORK))
    src = Path(html_or_path) if len(str(html_or_path)) < 400 and Path(str(html_or_path)).exists() else None
    if src is None:
        src = tmp / "page.html"
        src.write_text(str(html_or_path), encoding="utf-8")
    args = [browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={tmp / 'profile'}", f"--window-size={width},{height}",
            "--force-device-scale-factor=1", "--virtual-time-budget=3000", f"--screenshot={out_png}",
            src.resolve().as_uri()]
    subprocess.run(args, capture_output=True, timeout=90, creationflags=common.NO_WINDOW)
    shutil.rmtree(tmp, ignore_errors=True)
    if not out_png.exists():
        raise RuntimeError("the browser did not produce a screenshot")
    return out_png


class Background:
    """Yields background frames (H, W, 3 uint8) for kind image|video|screen|blur|color."""

    def __init__(self, kind, source, width, height, fps, count, start_s=0.0, drift=0.0):
        self.kind, self.w, self.h, self.drift = kind, width, height, drift
        self.reader, self.still = None, None
        if kind in ("image", "screen"):
            im = Image.open(source).convert("RGB")
            # a little extra so the slow drift never shows an edge
            pad = 1 + abs(drift) * 0.25
            s = max(width * pad / im.width, height * pad / im.height)
            im = im.resize((max(width, int(im.width * s + 0.5)), max(height, int(im.height * s + 0.5))), Image.LANCZOS)
            self.still = np.asarray(im)
            self.count = count
        elif kind == "video":
            if shots.is_still(source):
                raise ValueError("that is a picture; use kind='image'")
            self.reader = iter(shots.FrameReader(source, start_s, count, fps, width, height, mode="fill", loop=True))
        elif kind == "color":
            self.still = np.zeros((height, width, 3), np.uint8) + np.array(g.color(source)[:3], np.uint8)
        elif kind != "blur":
            raise ValueError("background kind must be image, video, screen, blur or color")
        self.i = 0

    def next(self, frame):
        self.i += 1
        if self.kind == "blur":
            return None
        if self.reader is not None:
            fr = next(self.reader, None)
            if fr is None:
                raise RuntimeError("background video ended early")
            return fr
        st = self.still
        if st.shape[0] == self.h and st.shape[1] == self.w:
            return st
        # slow Ken Burns drift across the extra margin
        k = (self.i / max(1, self.count)) if self.drift else 0.5
        x = int((st.shape[1] - self.w) * (0.5 + (k - 0.5) * (1 if self.drift > 0 else -1) * min(1, abs(self.drift) * 4)))
        y = (st.shape[0] - self.h) // 2
        x = max(0, min(st.shape[1] - self.w, x))
        return st[y:y + self.h, x:x + self.w]


def _match(fg, bg_mean, a, strength):
    """Nudge the person's colour balance toward the new background (per-channel gain)."""
    if strength <= 0:
        return fg
    w = a[::4, ::4] > 0.5
    if w.sum() < 50:
        return fg
    fg_mean = fg[::4, ::4][w].mean(axis=0) + 1e-3
    gain = np.clip((bg_mean / fg_mean) ** strength, 0.85, 1.18)
    gain = gain / gain.mean() * np.clip((bg_mean.mean() / fg_mean.mean()) ** (strength * 0.5), 0.9, 1.1)
    import cv2
    return cv2.multiply(fg, (float(gain[0]), float(gain[1]), float(gain[2]), 0))


def composite(frame, a, bgf, dim=0.0, blur_px=0.0, match=0.3, wrap=0.35, blur_source=24):
    """Person (matte a, float HxW) over the new background; OpenCV ops (release the GIL, so
    several frames composite in parallel threads)."""
    import cv2
    fg = frame.astype(np.float32)
    if bgf is None:                                      # portrait mode: the real background, blurred
        bg = shots.blur(fg, blur_source)
    else:
        bg = bgf.astype(np.float32)
        if blur_px > 0:
            bg = shots.blur(bg, blur_px)
    if dim > 0:
        bg = cv2.multiply(bg, (1 - dim, 1 - dim, 1 - dim, 0))
    if match > 0 and bgf is not None:
        fg = _match(fg, bg[::4, ::4].reshape(-1, 3).mean(axis=0), a, match)
    a3 = cv2.merge([a, a, a])
    out = cv2.add(bg, cv2.multiply(cv2.subtract(fg, bg), a3))
    if wrap > 0:                                         # light wrap: background light bleeding onto edges
        inner = shots.blur(a, 6)
        edge = np.minimum(cv2.subtract(a, inner) * (2.2 * wrap), 0.6)
        edge = np.maximum(edge, 0, out=edge)
        out = cv2.add(out, cv2.multiply(cv2.subtract(shots.blur(bg, 10), out), cv2.merge([edge, edge, edge])))
    return cv2.convertScaleAbs(out)


def process(reader, sequential, parallel, writer, total, progress=None, stage="compositing", workers=4):
    """Run `sequential(frame)` in order (e.g. the temporally-smoothed matte) and
    `parallel(frame, seq_result)` on a thread pool, writing results in order."""
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor
    pending = deque()
    with ThreadPoolExecutor(workers) as pool:
        for i, fr in enumerate(reader):
            pending.append(pool.submit(parallel, fr, sequential(fr)))
            while len(pending) > workers * 2:
                writer.write(pending.popleft().result())
            if progress and i % 15 == 0:
                progress(stage, 0.1 + 0.85 * i / max(1, total))
        while pending:
            writer.write(pending.popleft().result())


def follow(bgf, M, margin=1.12):
    """Move the new background with the real camera (M = frame0 -> current transform), zoomed in a
    little so the shifted edges never show."""
    import cv2
    h, w = bgf.shape[:2]
    Z = np.array([[margin, 0, (1 - margin) * w / 2], [0, margin, (1 - margin) * h / 2], [0, 0, 1]])
    A = np.vstack([M, [0, 0, 1]]) @ Z
    return cv2.warpAffine(bgf, A[:2], (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def render_backdrop(src, start_s, frames, fps, width, height, out_path, kind="image", source=None, dim=0.0,
                    blur_px=0.0, match=0.3, drift=0.15, bg_start_s=0.0, follow_camera=False, progress=None):
    bg = Background(kind, source, width, height, fps, frames, start_s=bg_start_s,
                    drift=0.0 if follow_camera else drift)
    mattes = shots.MatteStream()
    cam = shots.CameraMotion() if follow_camera and kind != "blur" else None
    rect = shots.content_rect(src, width, height)
    bars = None if rect == (0, 0, width, height) else 1 - shots.rect_mask(rect, width, height)

    def seq(fr):
        a = mattes(fr)
        if bars is not None:                 # letterbox/pillarbox bars stay as they are
            a = np.maximum(a * (1 - bars), bars)
        b = bg.next(fr)
        if cam is not None and b is not None:
            b = follow(b, cam.update(fr, a))
        return a, b

    with shots.VideoWriter(out_path, width, height, fps) as wr:
        process(shots.FrameReader(src, start_s, frames, fps, width, height), seq,
                lambda fr, s: composite(fr, s[0], s[1], dim=dim, blur_px=blur_px, match=match),
                wr, frames, progress)
    if wr.frames < frames * 0.9:
        raise RuntimeError(f"only {wr.frames}/{frames} frames decoded from the source")
    return {"path": str(out_path), "frames": wr.frames}


def render_text_behind(src, start_s, frames, fps, width, height, out_path, text, color="white", stroke_color=None,
                       size=0.22, y=0.42, font_weight="black", t_in=0.5, t_out=0.4, progress=None):
    """Big title placed BEHIND the person (alpha overlay: text minus the person matte)."""
    short = min(width, height)
    fnt = g.font(int(short * size), font_weight)
    lines = text.split("\n")
    imgs = [g.text_image(ln, fnt, g.color(color), stroke=int(short * 0.006) if stroke_color else 0,
                         stroke_fill=g.color(stroke_color or "black"), shadow=0) for ln in lines]
    while max(i.width for i in imgs) > width * 0.94 and fnt.size > 20:
        fnt = g.font(int(fnt.size * 0.9), font_weight)
        imgs = [g.text_image(ln, fnt, g.color(color), shadow=0) for ln in lines]
    block = Image.new("RGBA", (max(i.width for i in imgs), sum(int(i.height * 0.92) for i in imgs)), (0, 0, 0, 0))
    yy = 0
    for im in imgs:
        block.alpha_composite(im, ((block.width - im.width) // 2, yy))
        yy += int(im.height * 0.92)
    mattes = shots.MatteStream()
    dur = frames / fps
    with shots.VideoWriter(out_path, width, height, fps, alpha=True) as wr:
        for i, fr in enumerate(shots.FrameReader(src, start_s, frames, fps, width, height)):
            t = i / fps
            k_in = g.ease_out_cubic(t / t_in) if t_in else 1
            k_out = 1 - g.clamp01((t - (dur - t_out)) / t_out) if t_out else 1
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            rise = int((1 - k_in) * height * 0.06)
            g.paste_center(layer, block, width / 2, height * y + rise, opacity=min(k_in, k_out))
            arr = np.asarray(layer).copy()
            a = mattes(fr)
            arr[..., 3] = (arr[..., 3].astype(np.float32) * (1 - a)).astype(np.uint8)
            wr.write(arr)
            if progress and i % 15 == 0:
                progress("rendering", 0.1 + 0.85 * i / frames)
    return {"path": str(out_path), "frames": wr.frames}


def render_person_only(src, start_s, frames, fps, width, height, out_path, feather=1.5, progress=None):
    """Alpha overlay of just the person (for clone-yourself: put take B's person over take A)."""
    from letitedit_vfx import portrait_matte
    mattes = shots.MatteStream()

    def write(item):
        fr, m = item
        a = shots.blur(m, feather) if feather else m
        wr.write(np.dstack([fr, (np.clip(a, 0, 1) * 255).astype(np.uint8)]))

    with shots.VideoWriter(out_path, width, height, fps, alpha=True) as wr:
        reader = shots.FrameReader(src, start_s, frames, fps, width, height)
        # reading ahead and writing behind on threads of their own: the same frames, the waiting no longer adds up
        items = (portrait_matte.ahead(mattes, reader) if isinstance(mattes, portrait_matte.MatteStream)
                 else ((fr, mattes(fr)) for fr in reader))
        with portrait_matte.behind(write) as later:
            for i, item in enumerate(items):
                later(item)
                if progress and i % 15 == 0:
                    progress("rendering", 0.1 + 0.85 * i / frames)
    return {"path": str(out_path), "frames": wr.frames}
