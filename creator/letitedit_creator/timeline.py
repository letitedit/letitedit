"""Get audio/frames out of the CURRENT timeline (including unsaved edits) via melt."""

import uuid
from pathlib import Path

from . import common


def write_mlt(xml_with_profile, name="timeline"):
    common.WORK.mkdir(parents=True, exist_ok=True)
    path = common.WORK / f"{name}-{uuid.uuid4().hex[:8]}.mlt"
    path.write_text(xml_with_profile, encoding="utf-8")
    return path


def render_audio(mlt, out_wav, in_frame=None, out_frame=None, rate=16000, channels=1):
    """Mixed timeline audio as WAV (default 16 kHz mono for speech recognition)."""
    args = [common.melt(), "-quiet", str(mlt)]
    if in_frame is not None:
        args += [f"in={in_frame}", f"out={out_frame}"]
    args += ["-consumer", f"avformat:{out_wav}", "vn=1", "acodec=pcm_s16le", f"ar={rate}", f"channels={channels}"]
    common.run(args)
    if not Path(out_wav).exists() or Path(out_wav).stat().st_size < 1000:
        raise RuntimeError("timeline audio render produced nothing (is there audio on the timeline?)")
    return Path(out_wav)


def render_frames(mlt, out_dir, in_frame, out_frame, pattern="plate_%05d.jpg"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.run([common.melt(), "-quiet", str(mlt), f"in={in_frame}", f"out={out_frame}",
                "-consumer", f"avformat:{out_dir / pattern}", "f=image2", "vcodec=mjpeg", "qscale=2", "an=1"])
    return sorted(out_dir.glob(pattern.replace("%05d", "*")))
