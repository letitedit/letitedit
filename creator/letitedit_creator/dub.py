"""Translated dubbing: the agent translates the transcript lines (it is a language model); this
module voices each line with Kokoro TTS (local, Apache-2.0), fits it into the original line's time
slot (gentle tempo change, never chipmunk), and builds one dub audio file for the timeline."""

import numpy as np

from . import common, words as wordmod

MODEL = common.MODELS / "kokoro-v1.0.onnx"
VOICES = common.MODELS / "voices-v1.0.bin"
LANGS = {  # language -> (kokoro lang code, default voice male, female)
    "es": ("es", "em_alex", "ef_dora"), "fr": ("fr-fr", "ff_siwis", "ff_siwis"),
    "it": ("it", "im_nicola", "if_sara"), "pt": ("pt-br", "pm_alex", "pf_dora"),
    "hi": ("hi", "hm_omega", "hf_alpha"), "ja": ("ja", "jm_kumo", "jf_alpha"),
    "zh": ("cmn", "zm_yunxi", "zf_xiaobei"), "en": ("en-us", "am_michael", "af_heart"),
    "en-gb": ("en-gb", "bm_george", "bf_emma"),
}
_k = None


def kokoro():
    global _k
    if _k is None:
        from kokoro_onnx import Kokoro
        if not MODEL.exists():
            raise FileNotFoundError(f"{MODEL} missing (dubbing voice model)")
        _k = Kokoro(str(MODEL), str(VOICES))
    return _k


def voices(language=None):
    v = kokoro().get_voices()
    if language and language in LANGS:
        pre = LANGS[language][1][0]
        v = [x for x in v if x[0] == pre]
    return v


def lines(words, max_gap=0.7, max_len=9.0):
    """Group transcript words into sentence-ish lines with timings (for the agent to translate)."""
    out, cur = [], []
    for w in words:
        if w.get("filler"):
            continue
        if cur and (w["start"] - cur[-1]["end"] > max_gap or w["end"] - cur[0]["start"] > max_len):
            out.append(cur)
            cur = []
        cur.append(w)
        if w["text"].rstrip().endswith((".", "?", "!")) and w["end"] - cur[0]["start"] > 1.2:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"i": i, "start": round(c[0]["start"], 3), "end": round(c[-1]["end"], 3),
             "text": " ".join(x["text"] for x in c).strip()} for i, c in enumerate(out)]


def _stretch(y, sr, factor):
    """Tempo change without pitch change via ffmpeg atempo (factor > 1 = faster)."""
    import soundfile as sf
    tmp_in = common.WORK / f"st-{id(y)}-in.wav"
    tmp_out = common.WORK / f"st-{id(y)}-out.wav"
    sf.write(tmp_in, y, sr)
    chain = []
    f = factor
    while f > 2.0:
        chain.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        chain.append("atempo=0.5")
        f /= 0.5
    chain.append(f"atempo={f:.4f}")
    common.run([common.ffmpeg(), "-v", "error", "-y", "-i", str(tmp_in), "-af", ",".join(chain), str(tmp_out)])
    out, _ = sf.read(tmp_out, dtype="float32")
    tmp_in.unlink(missing_ok=True)
    tmp_out.unlink(missing_ok=True)
    return out


def render(segments, out_wav, language="es", voice=None, gender="male", speed=1.0, max_speedup=1.35,
           total_s=None, progress=None):
    """segments: [{start, end, text}] in timeline seconds (already translated). Returns placement
    info and per-line fit report."""
    import soundfile as sf
    if language not in LANGS:
        raise ValueError(f"language must be one of {sorted(LANGS)}")
    lang, male, female = LANGS[language]
    voice = voice or (male if gender == "male" else female)
    k = kokoro()
    sr = 24000
    end = max([s["end"] for s in segments] + [total_s or 0]) + 2.0
    track = np.zeros(int(end * sr) + sr, np.float32)
    report = []
    for n, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        y, sr = k.create(text, voice=voice, speed=speed, lang=lang)
        slot = max(0.3, float(seg["end"]) - float(seg["start"]))
        nxt = segments[n + 1]["start"] if n + 1 < len(segments) else end
        room = max(slot, float(nxt) - float(seg["start"]) - 0.08)        # may run into the pause after
        dur = len(y) / sr
        factor = 1.0
        if dur > room:
            factor = min(max_speedup, dur / room)
            y = _stretch(y, sr, factor)
        a = int(float(seg["start"]) * sr)
        b = min(len(track), a + len(y))
        track[a:b] += y[:b - a]
        report.append({"i": seg.get("i", n), "start": seg["start"], "slot_s": round(slot, 2),
                       "speech_s": round(len(y) / sr, 2), "speedup": round(factor, 2),
                       "overruns": len(y) / sr > room + 0.05})
        if progress:
            progress("voicing", 0.1 + 0.8 * n / max(1, len(segments)))
    peak = float(np.abs(track).max()) or 1.0
    track = track / peak * 0.89
    sf.write(out_wav, track, sr)
    return {"path": str(out_wav), "voice": voice, "language": language, "lines": report,
            "overruns": sum(1 for r in report if r["overruns"])}
