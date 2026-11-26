"""Word-level transcription with local whisper.cpp, tightened to where the audio is actually voiced.

Every word: {"text", "start", "end", "filler"} in seconds of the audio given (callers add offsets).
"""

import json
import re
import uuid
import wave
from pathlib import Path

import numpy as np

from . import common

FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "ah", "hmm", "mm", "mhm"}
FILLER_PROMPT = "Um, uh, so, like, you know, I mean, okay. Umm, uh."


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, rate


def voiced_envelope(samples, rate, hop_s=0.01):
    """Per-10ms frame: True when louder than an adaptive speech threshold."""
    hop = max(1, int(rate * hop_s))
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0, bool), hop_s
    frames = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 10)
    loud = np.percentile(db, 95)
    thresh = max(floor + 0.35 * (loud - floor), -50)
    voiced = db > thresh
    # bridge tiny gaps (stop consonants) so words are not chopped
    k = 5
    padded = np.convolve(voiced.astype(float), np.ones(k), "same") > 0
    return padded, hop_s


def norm(token):
    return re.sub(r"[^a-z0-9']", "", token.lower())


def transcribe(wav, language="en", cache=True):
    wav = Path(wav)
    key = common.sha1_file(wav)
    cache_file = common.CACHE / "words" / f"{key}.json"
    if cache and cache_file.exists():
        return common.read_json(cache_file)
    out = common.WORK / f"whisper-{uuid.uuid4().hex[:8]}"
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [common.whisper_cli(), "-m", common.whisper_model(), "-f", str(wav), "-ml", "1", "-sow", "-oj",
            "-of", str(out), "--prompt", FILLER_PROMPT]
    if language and language != "en":
        args += ["-l", language]
    common.run(args, timeout=3600)
    data = json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))
    raw = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        raw.append({"text": text, "start": seg["offsets"]["from"] / 1000.0, "end": seg["offsets"]["to"] / 1000.0})
    words = tighten(raw, *load_wav(wav))
    if cache:
        common.write_json(cache_file, words)
    return words


def tighten(words, samples, rate):
    """Shrink each word to the voiced audio inside its whisper span (whisper smears words over
    pauses), and flag fillers."""
    voiced, hop = voiced_envelope(samples, rate)
    out = []
    for w in words:
        a, b = int(w["start"] / hop), max(int(w["end"] / hop), int(w["start"] / hop) + 1)
        seg = voiced[a:b] if b <= len(voiced) else voiced[a:]
        start, end = w["start"], w["end"]
        if len(seg) and seg.any():
            idx = np.nonzero(seg)[0]
            start = (a + idx[0]) * hop
            end = (a + idx[-1] + 1) * hop
            # a word never lasts more than ~1.2 s; keep its END near the voiced tail
            if end - start > 1.2:
                start = end - 1.2
        start, end = float(start), float(end)
        out.append({"text": w["text"], "start": round(start, 3), "end": round(max(end, start + 0.06), 3),
                    "filler": norm(w["text"]) in FILLERS})
    return out


def offset(words, seconds):
    return [{**w, "start": round(w["start"] + seconds, 3), "end": round(w["end"] + seconds, 3)} for w in words]


def find_phrase(words, phrase, max_results=10):
    """Occurrences of a phrase (case/punctuation-insensitive, tolerant of one missing/extra word)."""
    target = [norm(t) for t in phrase.split() if norm(t)]
    toks = [norm(w["text"]) for w in words]
    hits = []
    n = len(target)
    if not n:
        return hits
    for i in range(len(toks)):
        for span in (n, n - 1, n + 1):
            if span < 1 or i + span > len(toks):
                continue
            window = toks[i:i + span]
            matches = sum(1 for t in target if t in window)
            if window[0] == target[0] and matches >= max(1, n - 1) and (span == n or matches == n):
                hits.append({"start": words[i]["start"], "end": words[i + span - 1]["end"],
                             "text": " ".join(w["text"] for w in words[i:i + span]),
                             "exact": window == target})
                break
    hits.sort(key=lambda h: (not h["exact"], h["start"]))
    return hits[:max_results]
