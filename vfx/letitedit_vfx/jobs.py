"""Durable background jobs (analysis and effect renders) that survive the MCP client closing."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import config


def _job_dir(job_id):
    if not job_id or any(c in job_id for c in "\\/.:"):
        raise KeyError(f"invalid job id '{job_id}'")
    return config.JOBS / job_id


def read(job_id):
    path = _job_dir(job_id) / "job.json"
    if not path.exists():
        raise KeyError(f"unknown VFX job '{job_id}'")
    return json.loads(path.read_text(encoding="utf-8"))


def write(job):
    d = _job_dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    os.replace(tmp, d / "job.json")


def update(job_id, **fields):
    job = read(job_id)
    job.update(fields)
    job["updated"] = time.time()
    write(job)
    return job


def validate_access(job_id):
    job=read(job_id); ctx=config.context()
    if not job.get("instance_id") or job["instance_id"]!=ctx["instance_id"]:
        raise ValueError("VFX job belongs to another editor (or predates ownership metadata). Render a new job in this instance.")
    if not ctx["project"] or job.get("project")!=ctx["project"]:
        raise ValueError("VFX job belongs to another project. Open its original project before reuse.")
    return job


def start(kind, spec):
    ctx=config.context()
    if not ctx["project"]: raise ValueError("Save a project before starting VFX")
    import sys
    bridge_dir=str(config.LETITEDIT_ROOT / "bridge")
    if bridge_dir not in sys.path: sys.path.insert(0,bridge_dir)
    import letitedit_instances as instances
    instances.claim_project(ctx["project"])
    job_id = f"{kind}-{uuid.uuid4().hex[:10]}"
    job = {"id": job_id, "kind": kind, "state": "queued", "progress": 0.0, "spec": spec,
           "created": time.time(), "updated": time.time(), "dir": str(_job_dir(job_id))}
    job.update(ctx)
    job["owner_token"]=instances.TOKEN
    write(job)
    log = open(_job_dir(job_id) / "worker.log", "w")
    kwargs = {"stdout": log, "stderr": subprocess.STDOUT, "cwd": str(config.VFX_ROOT), "env":{**instances.worker_env(),"SHOTCUT_VFX_PROJECT":ctx["project"]}}
    if config.IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "letitedit_vfx.worker", job_id], **kwargs)
    log.close()
    instances.claim_instance(proc.pid)
    return update(job_id, pid=proc.pid, state="running")


def _alive(pid):
    if not pid:
        return False
    if config.IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(job_id):
    job = read(job_id)
    if job["state"] == "running" and not _alive(job.get("pid")) and time.time() - job["updated"] > 5:
        log = (_job_dir(job_id) / "worker.log")
        tail = log.read_text(errors="replace")[-2000:] if log.exists() else ""
        job = update(job_id, state="failed", error="worker process exited unexpectedly\n" + tail)
    return job
