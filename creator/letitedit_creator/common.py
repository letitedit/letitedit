"""Shared paths and helpers. Tool locations (ffmpeg, melt, Blender, models) come from the VFX
package so both stay in sync across Windows/macOS."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # ...\LetItEdit\creator
LETITEDIT_ROOT = ROOT.parent
WORK = ROOT / "work"
CACHE = ROOT / "cache"
ASSETS = ROOT / "assets"

_vfx = str(LETITEDIT_ROOT / "vfx")
if _vfx not in sys.path:
    sys.path.insert(0, _vfx)
from letitedit_vfx import config as vconf  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MODELS = vconf.MODELS


def ffmpeg():
    return str(vconf.ffmpeg())


def ffprobe():
    return str(vconf.ffprobe())


def melt():
    return str(vconf.melt())


def whisper_cli():
    exe = LETITEDIT_ROOT / "app" / ("whisper-cli.exe" if vconf.IS_WINDOWS else "whisper-cli")
    if exe.exists():
        return str(exe)
    from shutil import which
    found = which("whisper-cli")
    if found:
        return found
    raise FileNotFoundError("whisper-cli not found (it ships with letitedit's app folder)")


def whisper_model():
    p = LETITEDIT_ROOT / "models" / "ggml-base.en.bin"
    if not p.exists():
        raise FileNotFoundError(f"speech model missing: {p}")
    return str(p)


def run(args, timeout=None, input_bytes=None):
    proc = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout, input=input_bytes,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-1500:]
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({proc.returncode}): {err}")
    return proc.stdout.decode("utf-8", "replace")


def check_output_path(path):
    return vconf.check_output_path(path)


def sha1_file(path, limit=None):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            if limit and fh.tell() >= limit:
                break
    return h.hexdigest()


def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
