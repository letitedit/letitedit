"""Paths, the off-by-default feature flag, and per-platform tool locations."""

import contextvars
import re
import uuid
import json
import os
import platform
import sys
import time
from pathlib import Path

VFX_ROOT = Path(__file__).resolve().parent.parent          # ...\LetItEdit\vfx
LETITEDIT_ROOT = VFX_ROOT.parent                               # ...\LetItEdit
SETTINGS = VFX_ROOT / "settings.json"
MODELS = VFX_ROOT / "models"
WORK = VFX_ROOT / "work"
JOBS = VFX_ROOT / "jobs"
LIBRARY = VFX_ROOT / "library"
OUTPUTS = VFX_ROOT / "outputs"
BLENDER_SCRIPTS = Path(__file__).resolve().parent / "blender"

BLENDER_VERSION = "4.5.14"
MAX_SEGMENT_S = 20.0

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


class VFXDisabled(RuntimeError):
    pass


_project = contextvars.ContextVar("vfx_project", default=os.environ.get("SHOTCUT_VFX_PROJECT", ""))

def current_instance():
    try:
        import letitedit_instances
        return letitedit_instances.current()
    except ImportError:
        value=os.environ.get("LETITEDIT_INSTANCE", "main")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,59}",value): raise ValueError("Invalid instance")
        return value

def settings_path():
    return LETITEDIT_ROOT / "instances" / current_instance() / "vfx-settings.json"

def context():
    return {"instance_id":current_instance(), "project":_project.get()}

def _read_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_enabled():
    return bool(_read_settings().get("enabled", False))


def settings():
    data = {"enabled": False}
    data.update(_read_settings())
    return data


def enable(user_request):
    if not user_request or len(user_request.strip()) < 8:
        raise ValueError("Pass the user's own words asking for effects (user_request); "
                         "VFX is only enabled when the user explicitly asks for it.")
    data = settings()
    data.update({"enabled": True, "enabled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "enabled_for_request": user_request.strip()[:500]})
    _write(data)
    return data


def disable():
    data = settings()
    data.update({"enabled": False, "disabled_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    _write(data)
    return data


def _write(data):
    path=settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def require_enabled():
    if not is_enabled():
        raise VFXDisabled(
            "VFX (beta) is OFF. It is only used when the user explicitly asks for effects. "
            "If they did, call letitedit_vfx_enable(user_request=<their words>) first; "
            "otherwise do not add effects.")


def blender_exe():
    env = os.environ.get("SHOTCUT_VFX_BLENDER")
    if env and Path(env).exists():
        return Path(env)
    base = VFX_ROOT / "blender"
    if IS_WINDOWS:
        candidates = sorted(base.glob("blender-*/blender.exe"))
    elif IS_MAC:
        candidates = [base / "Blender.app" / "Contents" / "MacOS" / "Blender"]
    else:
        candidates = sorted(base.glob("blender-*/blender"))
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"Portable Blender {BLENDER_VERSION} not found under {base}. "
                            "Run C:\\LetItEdit\\vfx\\setup_vfx.py to install it.")


def _tool(name):
    app = LETITEDIT_ROOT / "app"
    if IS_WINDOWS:
        p = app / f"{name}.exe"
    elif IS_MAC:
        p = Path("/Applications/Shotcut.app/Contents/MacOS") / name
    else:
        p = app / name
    if p.exists():
        return p
    from shutil import which
    found = which(name)
    if found:
        return Path(found)
    raise FileNotFoundError(f"{name} not found (looked in {p} and PATH)")


def ffmpeg():
    return _tool("ffmpeg")


def ffprobe():
    return _tool("ffprobe")


def melt():
    return _tool("melt")


def originals_folders():
    """The person's read-only source folders: 'originals_folders' in letitedit's settings.json or, on this PC only,
    settings.local.json beside it (one folder or a list). None named: none guarded."""
    base = Path(os.environ.get("LETITEDIT_SETTINGS") or LETITEDIT_ROOT / "settings.json")
    found = []
    for f in (base, base.with_name(base.stem + ".local" + base.suffix)):
        try:
            value = json.loads(f.read_text(encoding="utf-8-sig") or "{}").get("originals_folders")
        except (OSError, ValueError, AttributeError):
            continue
        if value:
            found = [str(v) for v in ([value] if isinstance(value, str) else value) if v]
    return found


def check_output_path(path):
    """Never write into the user's Originals."""
    p = str(Path(path).resolve()).replace("/", "\\").lower().rstrip("\\") + "\\"
    for folder in originals_folders():
        root = str(Path(folder)).replace("/", "\\").lower().rstrip("\\") + "\\"
        if p.startswith(root):
            raise ValueError("Refusing to write VFX output into Originals (read-only source footage).")
    return Path(path)


def platform_summary():
    return {"system": platform.system(), "machine": platform.machine(), "python": sys.version.split()[0]}
