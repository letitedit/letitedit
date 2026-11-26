"""MCP tool letitedit_music_make: instrumental music generated on this PC and fitted to a cut (music_gen.py).

    register(mcp, Image)   adds the tool to an MCP server
"""
from __future__ import annotations

import json

import letitedit.sound.music_gen as music_gen

DOC = """Instrumental music written on this PC by ACE-Step 1.5 (MIT; the 2B turbo model, DiT-only, 48 kHz stereo) to a
text description, then cut and joined on its own beats and bars (av_tools.fit_music, as letitedit_fit_music) to a length
or to hit times. Nothing is uploaded. Measured on the RTX 2070 SUPER: about 3 s per 38 s take once loaded (first load
about 20 s), 6.5-7.3 GB of GPU memory (other local models move to RAM first).

description: what the music is (genre, instruments, mood, energy...; up to 512 characters).
length: seconds (default: the project's length with project=, else 30). bpm (30-300), key ('E minor', ...),
time_signature (2, 3, 4, 6): passed to the model; None = its own choice. seed (None: random, reported).
steps (default 8), shift (default 3.0): the turbo model's diffusion steps and timestep shift. peak_db: the take's
peak (default -1.0 dBFS). extra_s (default 8): the take is this much longer than length, for the fit to cut in.
fit (default True with a length, hits, cuts or project): hits [[output_s, 'downbeat' | 'beat' | 'section' |
'section:<name>' | 'end' | take_s], ...], land ('cut' | 'stretch' | 'none'), crossfade_s, stretch_max, tolerance_s,
snap, fade_in, fade_out: as letitedit_fit_music (same defaults). cuts: output times (s) or 'project' (the project's V1
cut times); cuts_on 'downbeat' (default) | 'beat' | 'section' makes each a hit, 'none' only reports.
project: a .mlt; files then go to <project folder>\\made (else C:\\LetItEdit\\cache\\music_gen). out: output path
(.wav 32-bit float, .flac, .mp3, .m4a, .ogg).
Returns: file, raw_file (the whole take, kept for refitting), length_s, bpm_asked and bpm (measured), pulse, beats,
downbeats and sections of the file, fit (pieces, joints, hits with where each landed), alignment (per cut: nearest
beat and downbeat and their offsets), model, licence, settings (every value used), timings, GPU use. Files are named
'generated-music-...' with 'Generated music' metadata and a sidecar .json. A take with the same description and
settings is reused from the cache (cached: true)."""


def register(mcp, Image):
    def letitedit_music_make(description: str, length: float | None = None, bpm: float | None = None,
                           key: str | None = None, time_signature: str | None = None, seed: int | None = None,
                           steps: int | None = None, shift: float | None = None, extra_s: float | None = None,
                           hits: list | None = None, cuts: list | str | None = None, cuts_on: str | None = None,
                           project: str | None = None, fit: bool | None = None, land: str | None = None,
                           crossfade_s: float | None = None, stretch_max: float | None = None,
                           tolerance_s: float | None = None, snap: str | None = None, fade_in: float | None = None,
                           fade_out: float | None = None, peak_db: float | None = None, out: str | None = None) -> dict:
        try:
            res = music_gen.make(description, length=length, bpm=bpm, key=key, time_signature=time_signature,
                                 seed=seed, steps=steps, shift=shift, extra_s=extra_s, hits=hits, cuts=cuts,
                                 cuts_on=cuts_on, project=project, fit=fit, land=land, crossfade_s=crossfade_s,
                                 stretch_max=stretch_max, tolerance_s=tolerance_s, snap=snap, fade_in=fade_in,
                                 fade_out=fade_out, peak_db=peak_db, out=out)
        except (FileNotFoundError, ValueError, KeyError, RuntimeError, TimeoutError) as e:
            return {'error': f'{type(e).__name__}: {e}'}
        return json.loads(json.dumps(res, default=str))
    letitedit_music_make.__doc__ = DOC
    mcp.tool()(letitedit_music_make)
