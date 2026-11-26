"""Dubbing a project into another language: letitedit_dub_lines, letitedit_dub, letitedit_dub_voices.

You translate (you are a language model). letitedit_dub_lines gives what is said on the timeline as lines with their
times; you translate each line's text to about the same length; letitedit_dub has the translated lines spoken on this
PC by Kokoro (Apache-2.0; model kokoro-v1.0, downloaded on first use like the other local models), each fitted into
its line's slot (sped up at most max_speedup, never pitch-shifted), writes them as one sound file in
<project folder>\\AI Generated\\Dubs, puts it on a 'Dub (<language>)' audio track from the start of the timeline
(replacing an earlier dub on that track) and turns the original voice down: lower (-20 dB on each track the voice is
on), mute (that track's sound hidden) or keep. It is one change: in a project open in letitedit, one undo step.

    dub_lines(project, start_s=None, end_s=None)   -> {project, lines: [{i, start, end, text}], languages}
    dub_project(project, language, lines, ...)     -> {file, track, voice, language, lines, overruns, ...}
    dub_voices(language=None)                       -> {voices, default_per_language}
    register(mcp, Image)                            the three MCP tools
"""
from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path
from typing import Literal

import letitedit.timeline.edit_script as es

LOWER_DB = -20.0
MODEL_ID = 'kokoro-v1.0'


def _creator(name):
    import letitedit.pictures.vfx_items as vfx_items
    return vfx_items._creator(name)


def _model():
    """The voice model on this PC (downloaded on first use when settings.json model_downloads is 'auto')."""
    import letitedit.core.model_fetch as model_fetch
    with contextlib.redirect_stdout(sys.stderr):        # the MCP server talks on stdout
        model_fetch.ensure(MODEL_ID)


def _words(script, start_s=None, end_s=None):
    from letitedit.timeline.timeline_speech import timeline_words
    return sorted(timeline_words(script, start_s, end_s), key=lambda w: w['t0'])


def dub_lines(project, start_s=None, end_s=None):
    """What is said on the timeline between start_s and end_s as lines to translate (um and uh left out)."""
    from letitedit.timeline.timeline_speech import FILLERS
    path = es._resolve(project)
    words = [{'start': w['t0'], 'end': w['t1'], 'text': w['w'].strip(),
              'filler': w['w'].strip(" .,!?;:'\"").lower() in FILLERS} for w in _words(es.read(path), start_s, end_s)]
    d = _creator('dub')
    return {'project': str(path), 'lines': d.lines(words), 'languages': sorted(d.LANGS)}


def dub_voices(language=None):
    d = _creator('dub')
    if language and language not in d.LANGS:
        raise ValueError(f"language: one of {', '.join(sorted(d.LANGS))}")
    _model()
    with contextlib.redirect_stdout(sys.stderr):
        found = d.voices(language)
    return {'voices': found,
            'default_per_language': {k: {'male': v[1], 'female': v[2]} for k, v in d.LANGS.items()}}


def _segments(lines):
    segs = []
    for n, line in enumerate(lines or []):
        if not isinstance(line, dict) or 'start' not in line or 'end' not in line:
            raise ValueError(f'lines[{n}]: a line is {{start, end, text}} (from letitedit_dub_lines, its text translated)')
        segs.append({'i': line.get('i', n), 'start': float(line['start']), 'end': float(line['end']),
                     'text': str(line.get('text') or '')})
    if not any(s['text'].strip() for s in segs):
        raise ValueError('No line has text to speak: give the translated lines from letitedit_dub_lines')
    return sorted(segs, key=lambda s: s['start'])


def _voice_changes(script, original_voice):
    """Edit ops that lower or mute the tracks the voice is on, and what each was before."""
    if original_voice == 'keep':
        return [], []
    on = sorted({w['track'] for w in _words(script)})
    tracks = {t['name']: t for t in script['tracks']}
    ops, changed = [], []
    for name in on:
        t = tracks.get(name) or {}
        if original_voice == 'mute':
            hide = 'both' if t.get('hide') in ('video', 'both') else 'audio'
            ops.append({'op': 'track', 'name': name, 'hide': hide})
            changed.append({'track': name, 'hide_before': t.get('hide'), 'hide': hide})
        else:
            ops.append({'op': 'track', 'name': name, 'gain': LOWER_DB})
            changed.append({'track': name, 'gain_before': t.get('gain'), 'gain': LOWER_DB})
    return ops, changed


def dub_project(project, language, lines, voice=None, gender='male', original_voice='lower', speed=1.0,
                max_speedup=1.35, track=None, label=None, render=None):
    """Voice the translated lines and put them on the project (see the module doc). render: the voicing function
    (dub.render's arguments); tests give a stand-in."""
    d = _creator('dub')
    if language not in d.LANGS:
        raise ValueError(f"language: one of {', '.join(sorted(d.LANGS))}")
    if original_voice not in ('lower', 'mute', 'keep'):
        raise ValueError("original_voice: 'lower', 'mute' or 'keep'")
    if gender not in ('male', 'female'):
        raise ValueError("gender: 'male' or 'female'")
    segs = _segments(lines)
    path = Path(es._resolve(project))
    script = es.read(path)
    name = track or f'Dub ({language})'
    out_dir = path.parent / 'AI Generated' / 'Dubs'
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f'dub-{language}-{time.strftime("%Y%m%d-%H%M%S")}.wav'
    if render is None:
        _model()
        shots = _creator('shots')
        with contextlib.redirect_stdout(sys.stderr), shots.GPU_LOCK:
            res = d.render(segs, wav, language=language, voice=voice, gender=gender, speed=float(speed),
                           max_speedup=float(max_speedup))
    else:
        res = render(segs, wav, language=language, voice=voice, gender=gender, speed=float(speed),
                     max_speedup=float(max_speedup))
    import soundfile as sf
    length = es.to_seconds(script['length']) if script.get('length') else None
    dur = sf.info(str(wav)).duration
    out_s = round(min(dur, length) if length else dur, 3)
    changes = []
    existing = next((t for t in script['tracks'] if t['name'] == name), None)
    if existing is None:
        changes.append({'op': 'add_track', 'name': name, 'kind': 'audio'})
    else:
        changes += [{'op': 'delete', 'id': it['id']} for it in existing['items'] if it.get('id') and 'clip' in it]
    changes.append({'op': 'insert', 'track': name, 'at': 0, 'item': {'clip': str(wav), 'in': 0, 'out': out_s}})
    voice_ops, changed = _voice_changes(script, original_voice)
    import letitedit.server.timeline_tools as timeline_tools
    result, _ = timeline_tools.apply_project(str(path), changes=changes + voice_ops, check=False,
                                             label=label or f'Dub ({language})')
    return {'file': str(wav), 'track': name, 'voice': res.get('voice'), 'language': language,
            'lines': res.get('lines'), 'overruns': res.get('overruns'), 'original_voice': original_voice,
            'tracks_changed': changed, 'replaced_earlier_dub': existing is not None,
            'project': result.get('project', str(path)) if isinstance(result, dict) else str(path),
            'changes': result.get('changes') if isinstance(result, dict) else result,
            'editor': result.get('editor') if isinstance(result, dict) else None}


def register(mcp, Image):  # noqa: ARG001 - the shared register(mcp, Image) form
    @mcp.tool()
    def letitedit_dub_lines(project: str, start_s: float | None = None, end_s: float | None = None) -> dict:
        """Step 1 of dubbing a project into another language: what is said on its timeline as lines with their
        times, [{i, start, end, text}] in timeline seconds (um and uh left out; transcribed locally where not cached).
        Translate each line's text yourself to about the same length, so it fits its slot, then pass the lines to
        letitedit_dub. languages: the languages the voices speak."""
        return dub_lines(project, start_s, end_s)

    @mcp.tool()
    def letitedit_dub(project: str, language: str, lines: list[dict], voice: str | None = None,
                      gender: Literal['male', 'female'] = 'male',
                      original_voice: Literal['lower', 'mute', 'keep'] = 'lower', speed: float = 1.0,
                      max_speedup: float = 1.35, track: str | None = None, label: str | None = None) -> dict:
        """Step 2 of dubbing: the translated lines ([{start, end, text}] from letitedit_dub_lines) spoken on this PC
        (Kokoro voices; language es, fr, it, pt, hi, ja, zh, en or en-gb; voice: a name from letitedit_dub_voices,
        default the language's male or female voice) and put on the project. Each line is fitted into its slot
        (into the pause after it when needed; sped up at most max_speedup, never pitch-shifted; lines that still run
        over are counted in overruns and marked per line). The voices are one sound file in <project folder>\\AI
        Generated\\Dubs, placed from the start of the timeline on the track `track` (default 'Dub (<language>)';
        an earlier dub there is replaced) and cut at the timeline's end. original_voice: lower (-20 dB on each
        track the voice is on), mute (that track's sound hidden) or keep; tracks_changed says what each was before.
        One change: in a project open in letitedit, one undo step (named by label). Returns the file, the voice,
        each line's fit (slot, speech length, speed-up, overrun) and the changes."""
        return dub_project(project, language, lines, voice=voice, gender=gender, original_voice=original_voice,
                           speed=speed, max_speedup=max_speedup, track=track, label=label)

    @mcp.tool()
    def letitedit_dub_voices(language: str | None = None) -> dict:
        """The dubbing voices (all, or one language's): names start with a/b (American / British English), e
        (Spanish), f (French), h (Hindi), i (Italian), j (Japanese), p (Portuguese) or z (Chinese), then f or m
        (female / male); and each language's default male and female voice."""
        return dub_voices(language)

    return letitedit_dub
