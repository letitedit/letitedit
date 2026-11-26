"""Stream RGBA frames (PIL images) straight into a ProRes 4444 .mov with transparency.
No temporary PNGs, so long overlays and weak laptops are fine."""

import subprocess
from pathlib import Path

from PIL import Image

from . import common


class OverlayWriter:
    def __init__(self, path, width, height, fps):
        self.path = Path(common.check_output_path(path))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.size = (int(width), int(height))
        self.frames = 0
        self.proc = subprocess.Popen(
            [common.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
             "-s", f"{self.size[0]}x{self.size[1]}", "-r", str(fps), "-i", "-",
             "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
             str(self.path)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=common.NO_WINDOW)
        self._blank = None

    def write(self, img):
        if img is None:
            if self._blank is None:
                self._blank = Image.new("RGBA", self.size, (0, 0, 0, 0)).tobytes()
            data = self._blank
        else:
            if img.size != self.size:
                img = img.resize(self.size, Image.LANCZOS)
            data = img.convert("RGBA").tobytes()
        self.proc.stdin.write(data)
        self.frames += 1

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise RuntimeError(f"overlay encode failed: {err[-800:]}")
        return {"path": str(self.path), "frames": self.frames}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            try:
                self.proc.kill()
            except OSError:
                pass


def filmstrip(frames_or_path, out_path, count=6, width=300, background=(96, 104, 112)):
    """Contact sheet of an overlay .mov (decoded with ffmpeg) over a neutral background."""
    src = Path(frames_or_path)
    tmp = common.WORK / f"strip-{src.stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    info = common.run([common.ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0",
                       "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(src)])
    total = max(1, int((info.strip() or "1").split(",")[0]))
    picks = [int(round(k * (total - 1) / max(count - 1, 1))) for k in range(count)]
    sel = "+".join(f"eq(n\\,{p})" for p in picks)
    common.run([common.ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vf", f"select='{sel}'",
                "-fps_mode", "vfr", str(tmp / "s_%02d.png")])
    imgs = [Image.open(p).convert("RGBA") for p in sorted(tmp.glob("s_*.png"))]
    if not imgs:
        raise RuntimeError("could not decode overlay for filmstrip")
    th = int(width * imgs[0].height / imgs[0].width)
    cols = min(len(imgs), 3)
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (width * cols, th * rows), (20, 20, 20))
    for k, im in enumerate(imgs):
        bg = Image.new("RGBA", im.size, (*background, 255))
        sheet.paste(Image.alpha_composite(bg, im).convert("RGB").resize((width, th)),
                    ((k % cols) * width, (k // cols) * th))
    sheet.save(out_path)
    return Path(out_path)
