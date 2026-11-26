"""Reusable effect presets ("a 3D ratchet in our brand style") shared by every project."""

import json
import re
import time

from . import config


def _path(name):
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("preset name needs letters or digits")
    return config.LIBRARY / f"{slug}.json"


def save(name, effect, params, settings=None, notes=""):
    config.LIBRARY.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "effect": effect, "params": params, "settings": settings or {},
            "notes": notes, "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}
    path = _path(name)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"saved": str(path), **data}


def load(name):
    path = _path(name)
    if not path.exists():
        raise KeyError(f"no VFX preset '{name}'")
    return json.loads(path.read_text(encoding="utf-8"))


def list_presets():
    if not config.LIBRARY.exists():
        return []
    out = []
    for p in sorted(config.LIBRARY.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name"), "effect": d.get("effect"), "notes": d.get("notes", "")})
        except ValueError:
            continue
    return out
