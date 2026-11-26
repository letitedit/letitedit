"""Blender entry point: blender -b --factory-startup --python runner.py -- job.json

Builds the requested effect (template or free-form script) and renders an RGBA PNG sequence.
Writes <out_dir>/render_status.json for progress and the engine actually used.
"""

import importlib
import json
import os
import sys
import time
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "effects"))

import vfxlib  # noqa: E402


def status(out_dir, **data):
    path = os.path.join(out_dir, "render_status.json")
    final = data.get("state") in ("done", "failed")
    for attempt in range(40 if final else 3):
        try:
            with open(path + ".tmp", "w") as fh:
                json.dump(data, fh)
            os.replace(path + ".tmp", path)     # Windows: fails while the poller has the file open
            return
        except PermissionError:
            time.sleep(0.05)
    if final:
        raise RuntimeError("could not write render_status.json")


def configure_engine(scene, job, engine):
    if engine == "EEVEE":
        scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version < (5, 0, 0) else "BLENDER_EEVEE"
        scene.eevee.taa_render_samples = job["samples"]
        try:
            scene.eevee.use_shadows = True
        except AttributeError:
            pass
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = max(8, job["samples"])
        scene.cycles.use_denoising = True


def build(job):
    scene = vfxlib.reset_scene(job)
    ctx = vfxlib.Ctx(job)
    if job["effect"] == "script":
        code = job["params"].get("script", "")
        namespace = {"bpy": bpy, "ctx": ctx, "vfx": vfxlib, "math": __import__("math")}
        exec(compile(code, "<agent script>", "exec"), namespace)
        if "build" not in namespace:
            raise RuntimeError("free-form script must define build(ctx)")
        namespace["build"](ctx)
    else:
        module = importlib.import_module(job["effect"])
        module.build(ctx)
    return scene


def main():
    job_path = sys.argv[sys.argv.index("--") + 1]
    with open(job_path) as fh:
        job = json.load(fh)
    out_dir = job["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    engines = ["EEVEE", "CYCLES"] if job.get("engine", "AUTO") in ("AUTO", "EEVEE") else ["CYCLES"]
    last_error = None
    for engine in engines:
        try:
            scene = build(job)
            configure_engine(scene, job, engine)
            scene.render.filepath = os.path.join(out_dir, "elem_#####")
            started = time.time()

            def on_write(sc, *_):
                status(out_dir, state="rendering", engine=engine, frame=sc.frame_current,
                       frames=job["frames"], elapsed_s=round(time.time() - started, 1))

            bpy.app.handlers.render_write.clear()
            bpy.app.handlers.render_write.append(on_write)
            bpy.ops.render.render(animation=True)
            missing = [f for f in range(1, job["frames"] + 1)
                       if not os.path.exists(os.path.join(out_dir, f"elem_{f:05d}.png"))]
            if missing:
                raise RuntimeError(f"{len(missing)} frames missing after render (first {missing[0]})")
            status(out_dir, state="done", engine=engine, frame=job["frames"], frames=job["frames"],
                   elapsed_s=round(time.time() - started, 1))
            return 0
        except Exception as exc:  # EEVEE needs OpenGL 4.3; old laptops fall back to Cycles CPU
            last_error = "".join(traceback.format_exception(exc))
            status(out_dir, state="retrying", engine=engine, error=last_error[-2000:])
            if job["effect"] == "script" and "Error" in last_error and engine == "EEVEE" \
                    and "<agent script>" in last_error:
                break  # a bug in the agent's script will not be fixed by switching engines
    status(out_dir, state="failed", error=(last_error or "")[-4000:])
    return 1


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        sys.stdout.flush()
    sys.exit(code)
