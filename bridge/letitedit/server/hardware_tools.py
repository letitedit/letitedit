"""MCP tools letitedit_hardware, letitedit_log_frames, letitedit_log_write (hardware.py, llm_log.py).

register(mcp, Image) adds the tools.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import letitedit.core.hardware as hardware  # noqa: E402
import letitedit.footage.llm_log as llm_log  # noqa: E402

SHORT_HARDWARE = ('This PC\'s GPU, memory, CPU, RAM and disk, its tier (gpu8 / gpu4 / cpu), and which engine each '
                  'local feature uses (local GPU, local CPU, or the agent), from settings.json.')
SHORT_LOG_FRAMES = ('A video\'s footage-log stretches in batches: per stretch its id, times, the words said in it '
                    'and one image of its frames side by side.')
SHORT_LOG_WRITE = ('Store footage-log entries (action, things, place, framing, text, quality) for stretch ids; the '
                   'log is stored in the footage log cache once every stretch has one.')


def frames_text(rep):
    lines = [f"{Path(rep['file']).name}: {rep['total']} stretches, {rep['duration']:g} s; this batch: ids "
             f"{rep['stretches'][0]['id'] if rep['stretches'] else '-'}-"
             f"{rep['stretches'][-1]['id'] if rep['stretches'] else '-'}; next start: {rep['next']}; "
             f"described so far: {len(rep['described'])}; log stored: {rep['stored']}"]
    for st in rep['stretches']:
        lines.append(f"id {st['id']}  {st['clock']} ({st['from']:g}-{st['to']:g} s)  sheet: {st['sheet']}")
        lines.append(f"    said: \"{st['said']}\"" if st['said'] else '    said: (no words in the cached transcript)')
    lines.append('entry fields: ' + ', '.join(rep['entry_fields']) + "; settings: " + json.dumps(rep['settings']))
    return '\n'.join(lines)


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_hardware(refresh: bool = False, torch: bool = False, gpu8_mb: float | None = None,
                         gpu4_mb: float | None = None) -> str:
        """This PC's hardware and what runs where. Reports: each NVIDIA GPU (nvidia-smi: name, total and free MB,
        driver), logical CPU cores, RAM total/free, free disk on the models and cache drives; the tier: 'gpu8' for an
        NVIDIA GPU with >= gpu8_mb MB (default settings tier_gpu8_mb 7600; an 8 GB card reports ~8192), 'gpu4' for
        >= gpu4_mb MB (default 3800), else 'cpu'; and per feature the engine it uses: footage log (local vision
        model Qwen/Qwen3.5-4B on gpu8, Qwen/Qwen3.5-2B on gpu4 when its weights are on this PC, otherwise 'llm' =
        written by the agent with letitedit_log_frames / letitedit_log_write), speech to text (GPU whisper large-v3-turbo
        when the GPU has >= whisper_gpu_mb MB, default 6000, else CPU faster-whisper medium.en), stems, sound labels
        and voice (GPU or CPU, with the GPU MB each needs). Engines come from C:\\LetItEdit\\settings.json (created
        with the defaults on first use, never rewritten): footage_log_engine 'auto'|'local'|'llm', vision_model
        'auto' or a repo id, vision_models {tier: repo}, speech_engine 'auto'|'gpu'|'cpu', whisper_gpu_mb,
        tier_gpu8_mb, tier_gpu4_mb, hardware_ttl_s (a reading is reused this many seconds, default 300; refresh=True
        reads again). torch=True also asks torch in the models environment whether it sees CUDA (a few seconds)."""
        return '\n'.join(hardware.text(hardware.check(refresh=refresh, torch=torch, gpu8_mb=gpu8_mb, gpu4_mb=gpu4_mb)))

    @mcp.tool(structured_output=False)
    def letitedit_log_frames(file: str, start: int = 0, batch: int = 8, frames: int = 3, width: int = 448) -> list:
        """The stretches of one video for its footage log, `batch` at a time (default 8) from stretch `start`
        (default 0). The stretches are the same split as the local footage log: picture cuts (scene score > 0.3),
        shots over 8 s cut into equal parts, look-alike neighbours (mean grey difference < 5) joined up to 30 s.
        Returns one image per stretch (`frames` frames side by side, default 3, each `width` px wide, default 448,
        taken at 1/6, 3/6, 5/6 of the stretch; also saved as the JPEG named in the text) and a text with, per
        stretch, its id, times, sheet path and the words said in it (from the cached transcript), the next start
        (None after the last batch), how many stretches are described already and whether the log is stored.
        letitedit_log_write stores entries for these ids."""
        rep = llm_log.frames(file, start=start, batch=batch, frames=frames, width=width)
        out = []
        for st in rep['stretches']:
            if st['sheet']:
                out.append(Image(data=Path(st['sheet']).read_bytes(), format='jpeg'))
        return out + [frames_text(rep)]

    @mcp.tool()
    def letitedit_log_write(file: str, entries: list[dict], model: str = 'llm', finish: bool = False,
                          frames: int = 3, width: int = 448) -> dict:
        """Store footage-log entries for stretches of one video (ids from letitedit_log_frames). entries = [{'id': n,
        'action': ..., 'things': ..., 'place': ..., 'framing': ..., 'text': ..., 'quality': ..., 'best': ...}]
        (strings; any field may be left out), or [{'id': n, 'raw': 'Action: ...\\nThings: ...\\nPlace: ...\\n
        Framing: ...\\nText: ...\\nQuality: ...'}]. Field meanings as in the local model's log: action = what happens
        from the first frame to the last; things = people and objects in view; place = where; framing = wide /
        medium / close-up / extreme close-up, angle, camera movement; text = readable words or numbers in the
        picture, or none; quality = focus, exposure, shake, anything blocking the view; best = best moment
        (optional). An id written again replaces its entry. model = the name recorded as the log's author (default
        'llm'). The log is stored in the footage log cache (read by letitedit_footage's `seen:` lines) when every
        stretch has an entry, or with finish=True with the entries so far. frames / width must match the
        letitedit_log_frames call (defaults 3 / 448). Returns written ids, rejected entries, described and missing
        ids, total, complete, and the stored log's path (None when not stored yet)."""
        return llm_log.write(file, entries, model=model, finish=finish, frames=frames, width=width)

    return [letitedit_hardware, letitedit_log_frames, letitedit_log_write]
