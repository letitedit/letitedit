"""Reactions: animated emoji/graphics from Shotcut's Elements library, GIFs/stickers/memes,
popped in at a moment with a bounce, plus sound-effect stingers.

Elements ship with the editor: Lottie emojis, graphics, text and transitions (Lottie Simple License, see
share/shotcut/elements) and letitedit's own CC0 sound effects in elements/sounds. Shotcut's bundled GDC sound effects
were removed on 2026-10-29: their licence forbids AI use.
"""

import re
import shutil
import uuid
from pathlib import Path

from PIL import Image, ImageSequence

from . import common, graphics as g
from .overlay import OverlayWriter

ELEMENTS = common.LETITEDIT_ROOT / "app" / "share" / "shotcut" / "elements"
KINDS = ("emojis", "graphics", "text", "transitions", "sounds")
SOUNDS = ELEMENTS / "sounds"
AUDIO = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".aac")
# a kind of sound asked for by name (a tool's default stinger): the first Elements sound whose name or folder has all
# the words of the name or of one of these alternatives
SOUND_NAMES = {"whoosh": ["whoosh", "woosh", "swoosh"], "click": ["click", "tap"], "ding": ["ding", "bell", "chime"],
               "glitch": ["glitch", "digital"]}
NO_SOUND_WHY = ("no Elements sound named like {name!r} yet: letitedit's own CC0 sound effects are being added to "
                "share/shotcut/elements/sounds; meanwhile give a sound file (the person's own: letitedit_library "
                "kind='sfx')")


def list_elements(kind="emojis", query="", limit=40):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    base = ELEMENTS / kind
    q = [t for t in re.split(r"[\s_-]+", query.lower()) if t]
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_dir() or p.suffix.lower() in (".txt", ".pdf") or p.name.startswith("."):
            continue
        if kind == "sounds" and p.suffix.lower() not in AUDIO:
            continue                        # credits and licence files beside the sounds
        name = re.sub(r"^\d+-", "", p.stem).replace("_", " ")
        hay = f"{p.parent.name} {name}".lower()
        if all(t in hay for t in q):
            out.append({"name": name, "category": p.parent.name if p.parent != base else kind,
                        "path": str(p), "type": p.suffix.lower().lstrip(".")})
    return out[:limit], len(out)


def find_sound(name):
    """Path of the Elements sound for a name ('whoosh', 'ding', 'click', 'glitch' or any words), or None."""
    key = str(name).strip().lower()
    for words in SOUND_NAMES.get(key, [key]):
        items, _ = list_elements("sounds", words, 1)
        if items:
            return items[0]["path"]
    return None


def element_frames(path, fps, size=512, frames=None):
    """Render a Lottie/.rawr element (or decode a GIF/WebP/video) to RGBA PIL frames."""
    path = Path(path)
    tmp = common.WORK / f"el-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".tgs", ".json", ".rawr", ".lottie"):
        n = frames or int(fps * 3)
        common.run([common.melt(), "-quiet", str(path), f"out={n - 1}", "-consumer",
                    f"avformat:{tmp / 'e_%04d.png'}", "f=image2", "vcodec=png", "pix_fmt=rgba",
                    "mlt_image_format=rgba", f"width={size}", f"height={size}", f"frame_rate_num={int(round(fps))}",
                    "frame_rate_den=1"])
        imgs = [Image.open(p).convert("RGBA") for p in sorted(tmp.glob("e_*.png"))]
    elif path.suffix.lower() in (".gif", ".webp", ".png", ".apng"):
        im = Image.open(path)
        imgs = [f.convert("RGBA").copy() for f in ImageSequence.Iterator(im)]
        durs = [max(20, (f.info.get("duration") or 100)) for f in ImageSequence.Iterator(Image.open(path))]
        if len(imgs) > 1:                       # resample GIF timing to the project fps
            out, t, i, acc = [], 0.0, 0, durs[0]
            total = sum(durs)
            while t < total and len(out) < (frames or 10 ** 6):
                while t >= acc and i < len(imgs) - 1:
                    i += 1
                    acc += durs[i]
                out.append(imgs[i])
                t += 1000.0 / fps
            imgs = out
    else:
        common.run([common.ffmpeg(), "-v", "error", "-y", "-i", str(path), "-vf", f"fps={fps}",
                    "-pix_fmt", "rgba", str(tmp / "e_%04d.png")])
        imgs = [Image.open(p).convert("RGBA") for p in sorted(tmp.glob("e_*.png"))]
    shutil.rmtree(tmp, ignore_errors=True)
    if not imgs:
        raise RuntimeError(f"could not decode {path.name}")
    return imgs


def render(source_frames, out_path, fps, width, height, duration=2.0, x=0.75, y=0.3, size=0.3,
           t_in=0.22, t_out=0.2, loop=True, tilt_deg=0.0, wiggle=True):
    """Pop an (animated) element in at (x, y), hold/loop, pop out."""
    import math
    short = min(width, height)
    target = short * size
    scale0 = target / max(source_frames[0].size)
    frames = max(1, int(round(duration * fps)))
    cx, cy = x * width, y * height
    with OverlayWriter(out_path, width, height, fps) as wr:
        for f in range(frames):
            t = f / fps
            src = source_frames[f % len(source_frames)] if loop else source_frames[min(f, len(source_frames) - 1)]
            if t < t_in:
                s = g.ease_out_back(t / t_in, 2.6)
            elif t > duration - t_out:
                s = 1 - g.ease_in_back((t - (duration - t_out)) / t_out, 1.7)
            else:
                s = 1.0
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            if s > 0.02:
                art = g.scaled(src, scale0 * s)
                rot = tilt_deg + (6 * math.sin(t * 9) * max(0, 1 - t / 0.8) if wiggle else 0)
                if abs(rot) > 0.3:
                    art = art.rotate(rot, resample=Image.BICUBIC, expand=True)
                g.paste_center(canvas, art, cx, cy)
            wr.write(canvas)
    return {"path": str(out_path), "frames": frames}
