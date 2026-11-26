"""Frame I/O: pull a segment out of a Shotcut timeline or a media file, and encode results."""

import json
import subprocess
from pathlib import Path

from . import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args, timeout=None):
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({proc.returncode}): {proc.stderr[-1500:]}")
    return proc.stdout


def probe(path):
    out = run([config.ffprobe(), "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate,pix_fmt",
               "-of", "json", path])
    return json.loads(out)


def frames_from_timeline(mlt_path, in_frame, out_frame, out_dir):
    """Render exactly what the viewer sees on the timeline for [in_frame, out_frame] to JPEGs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run([config.melt(), "-quiet", mlt_path, f"in={in_frame}", f"out={out_frame}",
         "-consumer", f"avformat:{out_dir / 'plate_%05d.jpg'}", "f=image2", "vcodec=mjpeg",
         "qscale=2", "an=1"])
    files = sorted(out_dir.glob("plate_*.jpg"))
    if not files:
        raise RuntimeError("melt produced no frames for that range (is the timeline empty there?)")
    return files


def frames_from_file(path, start_s, duration_s, fps, size, out_dir):
    """Decode a media file segment at the project fps/size to JPEGs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = size
    vf = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    run([config.ffmpeg(), "-v", "error", "-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}",
         "-i", path, "-vf", vf, "-q:v", "2", str(out_dir / "plate_%05d.jpg")])
    files = sorted(out_dir.glob("plate_*.jpg"))
    if not files:
        raise RuntimeError(f"no frames decoded from {path} at {start_s}s")
    return files


def encode_overlay(frame_pattern, fps, out_path):
    """RGBA PNG sequence -> ProRes 4444 with alpha (.mov); Shotcut composites it on upper tracks."""
    out_path = config.check_output_path(out_path)
    run([config.ffmpeg(), "-v", "error", "-y", "-framerate", str(fps), "-i", str(frame_pattern),
         "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
         "-vendor", "apl0", str(out_path)])
    return out_path


def encode_full(frame_pattern, fps, out_path):
    """RGB frames -> high quality H.264 segment (no audio; the original audio stays below)."""
    out_path = config.check_output_path(out_path)
    run([config.ffmpeg(), "-v", "error", "-y", "-framerate", str(fps), "-i", str(frame_pattern),
         "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out_path)])
    return out_path
