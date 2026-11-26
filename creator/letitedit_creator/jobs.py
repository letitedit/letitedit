"""Small in-process background jobs for creator renders (status persisted to disk so a client can
poll after a timeout). The MCP tool layer runs the work in a thread with the caller's context
(editor instance) so bridge calls go to the right Shotcut window.

State lives in memory (under a lock) and is mirrored to CACHE/jobs/<id>.json with atomic replaces,
so a poll never reads a half-written file."""

import contextvars
import json
import os
import threading
import time
import traceback
import uuid

from . import common

JOBS = common.CACHE / "jobs"
_live = {}
_state = {}
_lock = threading.RLock()


def _path(job_id):
    if not job_id or any(c in job_id for c in "\\/.:"):
        raise KeyError(f"invalid job id {job_id}")
    return JOBS / f"{job_id}.json"


def _persist(job_id, data):
    JOBS.mkdir(parents=True, exist_ok=True)
    path = _path(job_id)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for attempt in range(20):                     # Windows: a reader may hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    tmp.unlink(missing_ok=True)


def update(job_id, **fields):
    with _lock:
        data = _state.get(job_id)
        if data is None:
            data = common.read_json(_path(job_id), {}) or {}
        data = {**data, **fields, "updated": time.time()}
        _state[job_id] = data
        _persist(job_id, data)
        return dict(data)


def start(kind, fn, *args, **kwargs):
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    update(job_id, id=job_id, kind=kind, state="running", stage="starting", progress=0.0, created=time.time())
    ctx = contextvars.copy_context()

    def progress(stage=None, value=None):
        fields = {}
        if stage is not None:
            fields["stage"] = stage
        if value is not None:
            fields["progress"] = round(float(value), 3)
        update(job_id, **fields)

    def work():
        try:
            result = ctx.run(fn, *args, progress=progress, **kwargs)
            update(job_id, state="done", stage="done", progress=1.0, result=result)
        except Exception as exc:  # reported to the agent via status()
            update(job_id, state="failed", stage="failed", error="".join(traceback.format_exception(exc))[-3000:])
        finally:
            _live.pop(job_id, None)

    t = threading.Thread(target=work, daemon=True, name=job_id)
    _live[job_id] = t
    t.start()
    return {"job_id": job_id, "state": "running"}


def status(job_id):
    with _lock:
        data = _state.get(job_id)
    if data is None:
        for _ in range(5):
            data = common.read_json(_path(job_id))
            if data is not None:
                break
            time.sleep(0.1)
    if data is None:
        raise KeyError(f"unknown creator job '{job_id}'")
    if data.get("state") == "running" and job_id not in _live and time.time() - data.get("updated", 0) > 30:
        data = update(job_id, state="failed", error="job was interrupted (the MCP server restarted); run it again")
    return dict(data)


def wait(job_id, timeout=170):
    """Block up to `timeout` s (keeps short jobs synchronous for the agent)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = status(job_id)
        if st["state"] != "running":
            return st
        time.sleep(0.5)
    return status(job_id)
