"""Semantic, export-bound cutaway measurements; face detections are only proxies."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def measure(report, verify_media=False):
    evidence = report.get("b_roll_evidence")
    if evidence is None:
        return None
    if not isinstance(evidence, dict) or evidence.get("format") != "letitedit-broll-evidence/1":
        raise ValueError("b-roll evidence needs format letitedit-broll-evidence/1")
    duration = report.get("duration_s")
    if not _number(duration) or duration <= 0 or evidence.get("duration_s") != duration:
        raise ValueError("b-roll evidence duration must match the final export report")
    fingerprint = evidence.get("media_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch("[a-f0-9]{64}", fingerprint):
        raise ValueError("b-roll evidence needs the actual media_sha256")
    for key in ("method", "reviewer"):
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            raise ValueError(f"b-roll evidence needs {key}")
    tolerance = evidence.get("boundary_tolerance_s")
    if not _number(tolerance) or tolerance < 0:
        raise ValueError("b-roll evidence needs boundary_tolerance_s")
    if verify_media:
        with Path(report["file"]).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != fingerprint:
            raise ValueError("b-roll evidence is stale: media_sha256 does not match the export")
    intervals = evidence.get("intervals")
    if not isinstance(intervals, list):
        raise ValueError("b-roll evidence intervals must be a list")
    totals = {key: 0.0 for key in ("b_roll", "talking_head", "other", "unknown", "own", "stock", "made", "reference")}
    cursor, longest_head, head_run = 0.0, 0.0, 0.0
    roles = []
    for shot in intervals:
        if not isinstance(shot, dict):
            raise ValueError("b-roll intervals must be objects")
        start, end = shot.get("start_s"), shot.get("end_s")
        if not all(_number(value) for value in (start, end)) or not 0 <= start < end <= duration:
            raise ValueError("b-roll intervals must lie inside the export")
        if start < cursor - 1e-7:
            raise ValueError("b-roll intervals must be ordered and non-overlapping")
        if start > cursor + 1e-7:
            totals["unknown"] += start - cursor
            head_run = 0.0
        kind = shot.get("kind")
        if kind not in ("b_roll", "talking_head", "other", "unknown"):
            raise ValueError("b-roll interval kind must be b_roll, talking_head, other or unknown")
        seconds = end - start
        totals[kind] += seconds
        head_run = head_run + seconds if kind == "talking_head" else 0.0
        longest_head = max(longest_head, head_run)
        if kind == "b_roll":
            provenance = shot.get("provenance")
            if provenance not in ("own", "stock", "made", "reference"):
                raise ValueError("b-roll interval needs own, stock, made or reference provenance")
            for key in ("role", "line", "shows", "source"):
                if not isinstance(shot.get(key), str) or not shot[key].strip():
                    raise ValueError(f"b-roll interval needs {key}")
            if type(shot.get("illustration")) is not bool or (provenance in ("made", "stock") and not shot["illustration"]):
                raise ValueError("made and stock b-roll must be declared illustration, never event evidence")
            totals[provenance] += seconds
            roles.append(dict(shot))
        cursor = end
    totals["unknown"] += duration - cursor
    complete = totals["unknown"] < 1e-7
    return {"status": "measured" if complete else "partial", "duration_s": duration,
            "b_roll_share": totals["b_roll"] / duration,
            "talking_head_share": totals["talking_head"] / duration,
            "unknown_share": totals["unknown"] / duration,
            "own_share": totals["own"] / duration, "stock_share": totals["stock"] / duration,
            "made_share": totals["made"] / duration, "reference_share": totals["reference"] / duration,
            "longest_talking_head_s": longest_head, "seconds": totals, "roles": roles,
            "method": evidence["method"], "reviewer": evidence["reviewer"],
            "boundary_tolerance_s": tolerance, "media_sha256": fingerprint}


def compare(reference, result):
    measurements = [measure(report) for report in (reference, result)]
    metrics = {}
    complete = all(value and value["status"] == "measured" for value in measurements)
    for key in ("b_roll_share", "talking_head_share", "unknown_share", "own_share", "stock_share",
                "made_share", "longest_talking_head_s"):
        before, after = [value.get(key) if value else None for value in measurements]
        metrics[key] = {"reference": before, "result": after,
                        "delta": round(after - before, 4) if complete else None,
                        "status": "measured" if complete else "unmeasured"}
    target = measurements[0]["b_roll_share"] if measurements[0] and measurements[0]["status"] == "measured" else None
    actual = measurements[1]
    checked = target is not None and actual and actual["status"] == "measured"
    return {"metrics": metrics, "critic_score": None, "evidence": dict(zip(("reference", "result"), measurements)),
            "target_check": {"target_share": target,
                             "reached": actual["b_roll_share"] >= target if checked else None,
                             "missing_seconds": max(0.0, target * actual["duration_s"] - actual["seconds"]["b_roll"]) if checked else None},
            "detector_proxies": {name: {key: (report.get("pacing") or {}).get(key) for key in ("cutaway_share", "talking_head")}
                                 for name, report in zip(("reference", "result"), (reference, result))},
            "note": "Semantic annotations of the final visible picture, not face absence, captions or duplicate crops. "
                    "Gaps are unknown, not zero b-roll. Share is not a likeness score; judge roles, imagery and rhythm separately."}
