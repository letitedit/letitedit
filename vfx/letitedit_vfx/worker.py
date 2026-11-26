"""Background worker: python -m letitedit_vfx.worker <job_id>"""

import sys
import time
import traceback

from . import jobs, pipeline


def main(job_id):
    job = jobs.read(job_id)
    try:
        if job["kind"] == "analyze":
            result = pipeline.run_analyze(job)
        elif job["kind"] == "effect":
            result = pipeline.run_effect(job)
        else:
            raise ValueError(f"unknown job kind {job['kind']}")
        jobs.update(job_id, state="done", progress=1.0, stage="done", result=result, finished=time.time())
        return 0
    except Exception as exc:
        jobs.update(job_id, state="failed", stage="failed", error="".join(traceback.format_exception(exc))[-4000:])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
