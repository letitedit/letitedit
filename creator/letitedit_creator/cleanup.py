"""Find dead air and filler words ("um", "uh") to cut for jump-cut pacing.

Returns ranges in seconds (timeline time when the words carry timeline offsets). Applying them is
done by the tool layer with letitedit's synchronized section delete, last range first, so later
ranges never shift underneath earlier ones and captions/music/markers stay aligned.
"""

import numpy as np

from . import words as words_mod


def plan(words, samples=None, rate=None, audio_offset=0.0, min_silence=0.6, keep_pad=0.15,
         remove_fillers=True, filler_pad=0.04, start_limit=None, end_limit=None, min_cut=0.25):
    """words: tightened words (timeline seconds). samples/rate: the same span's audio (optional,
    used to confirm silences are really quiet). Returns sorted, merged cut ranges with reasons."""
    ws = sorted(words, key=lambda w: w["start"])
    if start_limit is not None:
        ws = [w for w in ws if w["end"] > start_limit]
    if end_limit is not None:
        ws = [w for w in ws if w["start"] < end_limit]
    cuts = []
    voiced = hop = None
    if samples is not None:
        voiced, hop = words_mod.voiced_envelope(samples, rate)

    def quiet(a, b):
        if voiced is None:
            return True
        i, j = int((a - audio_offset) / hop), int((b - audio_offset) / hop)
        seg = voiced[max(i, 0):max(j, 0)]
        return len(seg) == 0 or seg.mean() < 0.15

    speech = [w for w in ws if not (remove_fillers and w.get("filler"))]
    for a, b in zip(speech, speech[1:]):
        gap_start, gap_end = a["end"] + keep_pad, b["start"] - keep_pad
        if b["start"] - a["end"] >= min_silence and gap_end - gap_start >= min_cut and quiet(a["end"], b["start"]):
            cuts.append({"start": gap_start, "end": gap_end, "reason": "silence"})
    if remove_fillers:
        for w in ws:
            if w.get("filler"):
                cuts.append({"start": w["start"] - filler_pad, "end": w["end"] + filler_pad,
                             "reason": f"filler '{w['text'].strip('.,!?')}'"})
    # head/tail dead air inside the requested window
    if speech and start_limit is not None and speech[0]["start"] - keep_pad - start_limit >= min_silence:
        cuts.append({"start": start_limit, "end": speech[0]["start"] - keep_pad, "reason": "leading silence"})
    if speech and end_limit is not None and end_limit - (speech[-1]["end"] + keep_pad) >= min_silence:
        cuts.append({"start": speech[-1]["end"] + keep_pad, "end": end_limit, "reason": "trailing silence"})
    return merge(cuts, min_cut)


def merge(cuts, min_cut=0.25):
    cuts = sorted(cuts, key=lambda c: c["start"])
    out = []
    for c in cuts:
        if c["end"] - c["start"] <= 0:
            continue
        if out and c["start"] <= out[-1]["end"] + 0.05:
            out[-1]["end"] = max(out[-1]["end"], c["end"])
            if c["reason"] not in out[-1]["reason"]:
                out[-1]["reason"] += " + " + c["reason"]
        else:
            out.append(dict(c))
    return [dict(c, start=round(c["start"], 3), end=round(c["end"], 3)) for c in out if c["end"] - c["start"] >= min_cut]


def summary(cuts):
    total = sum(c["end"] - c["start"] for c in cuts)
    fill = sum(1 for c in cuts if "filler" in c["reason"])
    return {"cuts": len(cuts), "seconds_removed": round(total, 2), "filler_cuts": fill,
            "silence_cuts": len(cuts) - fill}
