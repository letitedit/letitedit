"""Entry points used by the MCP tools (and tests). Everything except status() requires the
feature flag; explicit managed overlay recipes may call these; ordinary video plans never add effects."""

import json
import math
from pathlib import Path

from . import __version__, config, hardware, jobs, library, pipeline


def status():
    info = {"version": __version__, "beta": True, **config.settings(),
            "platform": config.platform_summary()}
    try:
        info["blender"] = {"path": str(config.blender_exe()), "version": config.BLENDER_VERSION}
    except FileNotFoundError as exc:
        info["blender"] = {"error": str(exc)}
    info["models"] = {m: (config.MODELS / f"{m}.onnx").exists() for m in ("modnet", "depth_anything_v2_small")}
    try:
        import onnxruntime
        info["onnxruntime"] = {"version": onnxruntime.__version__,
                               "providers": onnxruntime.get_available_providers()}
    except ImportError:
        info["onnxruntime"] = {"error": "onnxruntime not installed"}
    info["hardware"] = hardware.detect()
    info["effects"] = list(pipeline.EFFECTS)
    info["presets"] = len(library.list_presets())
    info["ready"] = ("error" not in info["blender"] and all(info["models"].values())
                     and "error" not in info["onnxruntime"])
    return info


def list_effects():
    return {name: {**meta, "defaults": pipeline.EFFECT_DEFAULTS.get(name, {})}
            for name, meta in pipeline.EFFECTS.items()} | {"presets": library.list_presets()}


def start_analyze(fps, width, height, mlt=None, in_frame=None, out_frame=None, file=None,
                  start_s=None, duration_s=None):
    config.require_enabled()
    if mlt:
        frames = out_frame - in_frame + 1
    else:
        if not Path(file).exists():
            raise FileNotFoundError(file)
        frames = int(round(duration_s * fps))
    if frames < 1:
        raise ValueError("segment is empty")
    if frames / fps > config.MAX_SEGMENT_S:
        raise ValueError(f"segment is {frames / fps:.1f}s; the beta handles up to {config.MAX_SEGMENT_S:.0f}s "
                         "per effect -- split it into shorter effects")
    spec = {"fps": fps, "width": width, "height": height, "mlt": mlt, "in_frame": in_frame,
            "out_frame": out_frame, "file": file, "start_s": start_s, "duration_s": duration_s}
    return jobs.start("analyze", spec)


def start_effect(effect, params, fps, width, height, quality="preview", mode=None, analysis_id=None,
                 duration_s=None, timeline_start_frame=None, output_path=None, preset=None, **settings):
    config.require_enabled()
    if preset:
        p = library.load(preset)
        effect = effect or p["effect"]
        params = {**p.get("params", {}), **(params or {})}
        settings = {**p.get("settings", {}), **settings}
    if effect not in pipeline.EFFECTS:
        raise ValueError(f"unknown effect '{effect}'; choose from {sorted(pipeline.EFFECTS)}")
    if effect == "script" and not (params or {}).get("script"):
        raise ValueError("effect 'script' needs params.script (Blender Python defining build(ctx))")
    defaults = pipeline.EFFECT_DEFAULTS.get(effect, {})
    layer = pipeline.EFFECTS[effect]["layer"]
    # Without an analysed shot there is no person to keep in front: default to a transparent overlay.
    mode = mode or settings.get("mode") or (layer if (layer != "composite" or analysis_id) else "overlay")
    light = None
    if analysis_id:
        jobs.validate_access(analysis_id)
        a = json.loads((pipeline.analysis_dir(analysis_id) / "analysis.json").read_text())
        frames = a["frames"]
        light = a.get("light")
        if timeline_start_frame is None:
            timeline_start_frame = a.get("timeline_start_frame")
    else:
        if not duration_s:
            raise ValueError("give duration_s, or an analysis_id whose segment sets the length")
        frames = int(round(duration_s * fps))
    if mode == "composite" and not analysis_id:
        raise ValueError("mode 'composite' (effect behind the person / full frames) needs analysis_id; "
                         "run letitedit_vfx_analyze_shot first or use mode 'overlay'")
    if frames / fps > config.MAX_SEGMENT_S:
        raise ValueError(f"effects are limited to {config.MAX_SEGMENT_S:.0f}s each in this beta")
    if quality == "final":
        if not output_path:
            raise ValueError("final renders need output_path")
        config.check_output_path(output_path)
    spec = {"effect": effect, "params": params or {}, "fps": fps, "width": width, "height": height,
            "frames": frames, "quality": quality, "mode": mode, "analysis_id": analysis_id, "light": light,
            "timeline_start_frame": timeline_start_frame, "output_path": output_path,
            "glow": settings.get("glow", defaults.get("glow", 0.0)),
            "flicker": settings.get("flicker", defaults.get("flicker", 0.0)),
            "shake": settings.get("shake", defaults.get("shake", 0.0)),
            "occlusion": settings.get("occlusion", defaults.get("occlusion", "subject")),
            "depth_cut": settings.get("depth_cut", 0.6), "seed": settings.get("seed", 7),
            "engine": settings.get("engine", "AUTO")}
    return jobs.start("effect", spec)


def job_status(job_id):
    jobs.validate_access(job_id)
    job = jobs.status(job_id)
    keep = {k: job.get(k) for k in ("id", "kind", "state", "stage", "progress", "error", "result")}
    return keep


def save_preset(job_id, name, notes=""):
    config.require_enabled()
    job = jobs.validate_access(job_id)
    if job["kind"] != "effect":
        raise ValueError("only effect jobs can be saved as presets")
    s = job["spec"]
    settings = {k: s.get(k) for k in ("mode", "glow", "flicker", "shake", "occlusion", "depth_cut")}
    return library.save(name, s["effect"], s["params"], settings, notes)
