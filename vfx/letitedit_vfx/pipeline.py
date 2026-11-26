"""The two VFX jobs: analyze a shot segment, and render an effect (preview or final)."""

import json
import shutil
import subprocess
import time
from pathlib import Path

from . import analyze as analysis_mod
from . import composite, config, hardware, jobs, media

EFFECTS = {
    "tool_popup": {"layer": "overlay", "description":
                   "3D tool pops up beside you with a label card (wrench, ratchet, screwdriver, hammer)."},
    "explosion": {"layer": "composite", "description":
                  "Stylised flash/fireball/smoke/sparks; best BEHIND the person (occlusion=subject) "
                  "with glow, light flicker and camera shake."},
    "bus_drive": {"layer": "overlay", "description":
                  "Code-built 3D bus (1980s Wanderlodge) drives across a surface at ground_y."},
    "script": {"layer": "overlay", "description":
               "Free-form: params.script is Blender Python defining build(ctx); see vfxlib helpers."},
}

EFFECT_DEFAULTS = {
    "explosion": {"glow": 0.5, "flicker": 0.7, "shake": 0.6, "occlusion": "subject"},
    "tool_popup": {"glow": 0.0},
    "bus_drive": {"glow": 0.0},
    "script": {"glow": 0.0},
}


def analysis_dir(analysis_id):
    d = config.WORK / analysis_id
    if not (d / "analysis.json").exists():
        raise KeyError(f"unknown or unfinished analysis '{analysis_id}'")
    return d


def run_analyze(job):
    spec = job["spec"]
    out = config.WORK / job["id"]
    out.mkdir(parents=True, exist_ok=True)
    jobs.update(job["id"], stage="extracting frames")
    if spec.get("mlt"):
        plates = media.frames_from_timeline(spec["mlt"], spec["in_frame"], spec["out_frame"], out)
    else:
        plates = media.frames_from_file(spec["file"], spec["start_s"], spec["duration_s"], spec["fps"],
                                        (spec["width"], spec["height"]), out)
    jobs.update(job["id"], stage="analysing", frames=len(plates))

    def progress(i, n):
        if i % 5 == 0 or i == n:
            jobs.update(job["id"], progress=round(i / n, 3))

    result = analysis_mod.analyze(plates, out, spec["fps"], progress)
    result.update({"analysis_id": job["id"], "dir": str(out), "sheet": str(out / "analysis_sheet.png"),
                   "timeline_start_frame": spec.get("in_frame"), "source": spec})
    (out / "analysis.json").write_text(json.dumps(result, indent=2))
    return result


def _render_blender(spec, out_dir, render_w, render_h, samples, job_id):
    blender_job = {
        "effect": spec["effect"], "params": spec.get("params", {}),
        "width": spec["width"], "height": spec["height"],
        "render_width": render_w, "render_height": render_h,
        "fps": spec["fps"], "frames": spec["frames"], "samples": samples,
        "out_dir": str(out_dir), "light": spec.get("light"), "seed": spec.get("seed", 7),
        "engine": spec.get("engine", "AUTO"),
    }
    job_file = out_dir / "blender_job.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps(blender_job, indent=2))
    args = [str(config.blender_exe()), "-b", "--factory-startup", "--python",
            str(config.BLENDER_SCRIPTS / "runner.py"), "--", str(job_file)]
    log = open(out_dir / "blender.log", "w")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    status_file = out_dir / "render_status.json"

    def read_status(retries=1):
        # Blender swaps this file in atomically; on Windows a read can collide with the swap.
        for _ in range(retries):
            try:
                return json.loads(status_file.read_text())
            except (OSError, ValueError):
                time.sleep(0.1)
        return None

    while proc.poll() is None:
        time.sleep(1)
        st = read_status()
        if st and st.get("frame"):
            jobs.update(job_id, stage=f"rendering ({st.get('engine')})",
                        progress=round(0.1 + 0.7 * st["frame"] / spec["frames"], 3))
    st = read_status(retries=30) or {"state": "failed", "error": "no render status written"}
    if proc.returncode != 0 or st.get("state") != "done":
        tail = (out_dir / "blender.log").read_text(errors="replace")[-1500:]
        raise RuntimeError(f"Blender render failed: {st.get('error', '')[-2500:]}\n{tail}")
    return sorted(out_dir.glob("elem_*.png")), st.get("engine")


def run_effect(job):
    spec = job["spec"]
    tier = hardware.detect()
    work = Path(job["dir"])
    final = spec.get("quality") == "final"
    scale = 1.0 if final else tier["settings"]["preview_scale"]
    samples = tier["settings"]["final_samples" if final else "preview_samples"]
    render_w = max(64, int(spec["width"] * scale) // 2 * 2)
    render_h = max(64, int(spec["height"] * scale) // 2 * 2)
    elems, engine = _render_blender(spec, work / "render", render_w, render_h, samples, job["id"])

    jobs.update(job["id"], stage="compositing", progress=0.82)
    mode = spec["mode"]
    out_size = (spec["width"], spec["height"]) if final else (render_w, render_h)
    if mode == "composite":
        adir = analysis_dir(spec["analysis_id"])
        plates = sorted(adir.glob("plate_*.jpg"))
        frames = composite.composite_frames(
            plates, elems, adir, work / "comp", occlusion=spec.get("occlusion", "subject"),
            depth_cut=spec.get("depth_cut", 0.6), glow=spec.get("glow", 0.0), flicker=spec.get("flicker", 0.0),
            shake=spec.get("shake", 0.0), size=out_size)
        strip_bg = None
    else:
        frames = composite.overlay_frames(elems, work / "over", out_size, glow=spec.get("glow", 0.0))
        strip_bg = None
        if spec.get("analysis_id"):
            strip_bg = sorted(analysis_dir(spec["analysis_id"]).glob("plate_*.jpg"))
    strip = composite.filmstrip(frames, work / "filmstrip.png", background=strip_bg)

    jobs.update(job["id"], stage="encoding", progress=0.92)
    ext = ".mov" if mode == "overlay" else ".mp4"
    if final:
        out = Path(spec["output_path"]).with_suffix(ext)
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = work / f"preview{ext}"
    pattern = frames[0].parent / (("over_%05d.png") if mode == "overlay" else "comp_%05d.jpg")
    if mode == "overlay":
        media.encode_overlay(pattern, spec["fps"], out)
    else:
        media.encode_full(pattern, spec["fps"], out)
    info = media.probe(out)
    if not final:
        shutil.rmtree(work / "render", ignore_errors=True)
    return {"output": str(out), "filmstrip": str(strip), "mode": mode, "engine": engine,
            "quality": spec.get("quality"), "frames": len(frames), "fps": spec["fps"],
            "timeline_start_frame": spec.get("timeline_start_frame"),
            "render_size": [render_w, render_h], "media": info}
