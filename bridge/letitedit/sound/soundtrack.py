"""Soundtrack assembler: one song arranged around a project as a deliberate score (letitedit).

    analyze(song)                         the song's beat grid, bars, energy, phrases, drops and how clear its beat is
    plan(project, song, sections=..., hits=..., protect=..., start=..., end=..., repeat=..., max_stretch=...)
                                          a proposal: song pieces cut on bar lines, the joins, where every hit lands
                                          (timing error), the gain envelope, and the edit ops that build it; nothing
                                          is written
    apply(project, plan_or_id)            the plan's ops through the shared timeline apply (one undo step in an open
                                          letitedit window, or the saved file with a history copy), refused when the
                                          project or the song changed since the plan; then measure()
    measure(project, plan_or_id)          renders the mix with melt (the export engine) as two stems (this music track
                                          / everything else) and measures true peak, music under speech, the level in
                                          protected ranges, where each hit and join actually landed, and loops
    soundtrack(project, song, ..., mode)  the MCP tool's body (mode 'plan' | 'apply' | 'measure' | 'song')

How the plan is made
- The song: perception.music gives beats and downbeats from the beat finder; here every beat is moved to its transient (1 ms energy
  rise, within 35 ms), the downbeat phase is re-chosen from chord changes and kick energy, and each bar gets loudness,
  onset density, timbre (40 log-mel bands) and chroma. Phrase starts come from a 4-bar grid fitted to the bar-to-bar
  novelty (plus energy-section starts); drops are bar lines where the next two bars are 3 dB+ louder than the two
  before. Beat clarity is measured, not assumed: 'stability' (share of 12 s windows whose own tempo agrees with the
  song's) and 'salience' (onset autocorrelation at the beat period). A song without a steady beat is cut in coarse
  units (about 2 s, snapped to the strongest onsets) with long crossfades, and the result says so.
- The timeline: the music span minus drop_out ranges gives runs; each run is split at the hits. Between two fixed
  points the time is filled with whole bars when it already fits (within tolerance), else (in order of cost) a bounded
  speed change (max_stretch), a short bar (whole beats dropped/added right before the hit), or a stop (silence just
  before the hit). A run that starts with a fade has a free phase: it may start mid-bar so the first hit lands.
- The material: a beam search over bar slots picks one song bar per slot: playing on is free, a jump costs how unlike
  the replaced bar the new one is (timbre, chroma, loudness, place in the phrase, frame rounding of the join); each
  slot pays for missing its section's energy; hit slots only take bars of the hit's kind; repeat limits (uses per bar,
  minimum gap, no back-to-back loops of up to loop_bars bars) are enforced, relaxed only when nothing else fits (and
  reported).
- The timeline changes: clips of the song file (referenced in place) on the music track, joined by 2-frame Shotcut
  crossfade transitions that end on the bar line, with ordinary gain keyframes (section levels, dips under speech,
  deep ducks for protected ranges) and audio fades (music start/end, drop-outs, stops). Positions and in points are
  whole frames, so every timing number includes that rounding (17 ms at 30 fps).

Times are seconds (timeline seconds unless named song_*). Numbers called 'cost' are search costs (lower is smoother),
not probabilities; measured values come from the rendered mix; taste still needs a listen.

The code is in parts, each imported back here: soundtrack_base (settings, small helpers), soundtrack_song (the song
analysed), soundtrack_request (the request and the project), soundtrack_arrange (skeleton, search, layout) and
soundtrack_mix (gain envelope, edit ops, preview). This file keeps plan(), apply(), the rendered mix measured (the
tests patch what it reads here) and the tool.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings and the small helpers (times, decoding)
from letitedit.sound.soundtrack_base import (  # noqa: E402,F401
    _SAI_ROOT, CACHE, WORK, SCHEMA, ANALYSIS_VERSION, PLAN_VERSION, NO_WINDOW, SR, MSR, N_FFT, HOP, ENERGY_WORDS,
    HIT_KINDS, APPROACHES, PROTECT_MODES, ENDINGS, ENTRIES, MODES, LEVELS, OPTIONS, REPEAT, _MEM, _LOCK, _sec, _r,
    _ms, _clock, _span, _hash, _file_id, _json_write, _decode
)
# the song analysed: beats, bars, sections, energy and musical events
from letitedit.sound.soundtrack_song import (  # noqa: E402,F401
    _mel_fb, _chroma_fb, _frame_features, _clarity, _refine, _downbeat_phase, _novelty, _norm01, analyze, _analyze,
    song_brief
)
# the request typed and checked, and the project it scores
from letitedit.sound.soundtrack_request import (  # noqa: E402,F401
    _energy_of, _level_value, _parse_sections, _parse_hits, _parse_protect, parse_request, _live_state, _programme,
    _range_lufs, _project_context
)
# the arrangement: the skeleton of runs and fixed points, the beam search over bar slots, and the clips laid out in whole frames
from letitedit.sound.soundtrack_arrange import (  # noqa: E402,F401
    _resid_cost, _break_cost, _fit, _ending_bar, _skeleton, _talk, _join_matrix, _kind_mask, _search, _grid_label,
    _next_bar_start, _event_of, _song_len, _layout, _arrangement_repeats
)
# the gain envelope, the edit ops and the preview (a picture of the plan, a listen)
from letitedit.sound.soundtrack_mix import (  # noqa: E402,F401
    _energy_level, _value_at, _envelope, _changes, _graph, _render_bed
)


import hashlib
import json
import math
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

import numpy as np


# ============================================================================ plan

def _fingerprints(path, an, ctx):
    import letitedit.footage.perception as perception
    return {'project': {'path': str(path), 'revision': ctx['revision']}, 'song': {**_file_id(an['path']),
                                                                                  'content': an.get('key')},
            'analysis': {'soundtrack': ANALYSIS_VERSION, 'plan': PLAN_VERSION,
                         'perception_beats': perception.VERSIONS.get('beats')},
            'speech_sources': ctx['sources']}


def _plan_path(plan_id):
    return WORK / 'plans' / f'{plan_id}.json'


def load_plan(plan_or_id):
    if isinstance(plan_or_id, dict):
        return plan_or_id
    f = _plan_path(str(plan_or_id))
    if not f.exists():
        raise ValueError(f'No plan {plan_or_id!r} (plans are kept in {f.parent}); make one with mode="plan"')
    with open(f, encoding='utf-8-sig') as fh:
        return json.load(fh)


def _plan_bar_grid(lay, fps):
    # every full bar as it will play: [timeline start, song bar (0-based), piece id, timeline length]
    bar_grid = []
    for c in lay['clips']:
        for sl in c['slots']:
            if sl['kind'] != 'bar':
                continue
            t = (c['M'] + (sl['u0'] * fps / c['sigma'] - c['W_in'])) / fps
            if c['start_s'] - 1e-6 <= t < c['end_s']:
                bar_grid.append([_r(t, 4), sl['bar'], c['id'], _r(min((sl['u1'] - sl['u0']) / c['sigma'],
                                                                      c['end_s'] - t), 4)])
    return bar_grid


def _plan_sections(req, sk, an):
    # sections: what was asked and what the material gives
    secs = []
    for k, s in enumerate(req['sections']):
        sls = [sl for sl in sk['slots'] if sl.get('section') == k]
        w = np.asarray([sl['dur'] for sl in sls]) if sls else np.zeros(0)
        got = float(np.sum(w * np.asarray([an['energy'][sl['bar']] for sl in sls])) / w.sum()) if w.size else None
        secs.append({'from': _r(s['from'], 3), 'to': _r(s['to'], 3), 'name': s.get('name'),
                     'energy_asked': s['word'], 'energy_target': _r(s['energy'], 2), 'energy_got': _r(got, 2),
                     'song_bars': sorted({sl['bar'] + 1 for sl in sls})[:64]})
    return secs


def _plan_pieces(lay, an, fps):
    pieces = []
    for c in lay['clips']:
        pieces.append({'id': c['id'], 'timeline': [_r(c['start_s'], 4), _r(c['end_s'], 4)],
                       'song': [_r(c['in_s'], 4), _r(c['out_s'], 4)],
                       'bars': f"{c['slots'][0]['bar'] + 1}-{c['slots'][-1]['bar'] + 1}", 'speed': _r(c['sigma'], 5),
                       'enters': ('crossfade ' + f"{c['xfade'] / fps:.3f} s") if c['chained'] else
                       (f"fade in {c.get('fade_in_s', 0):.2f} s" if c['entry']['kind'] == 'fade' else 'on the beat'),
                       'ends': c['end_kind'] + (f" (fade {c['fade_out_s']:.2f} s)" if c.get('fade_out_s') else ''),
                       'energy': _r(float(np.mean([an['energy'][sl['bar']] for sl in c['slots']])), 2),
                       'xfade_s': _r(c['xfade'] / fps, 4), 'fade_in_s': _r(c.get('fade_in_s') or 0.0, 4),
                       'fade_out_s': _r(c.get('fade_out_s') or 0.0, 4)})
    return pieces


def _plan_warnings(sk, env, lay, search, an, ctx, req, reps):
    warnings = list(sk['warnings']) + list(env['warnings']) + list(lay['notes']) + list(search['notes'])
    if an['beat_quality'] == 'none':
        warnings.append('only coarse beats: ' + next((n for n in an.get('notes') or [] if n.startswith('no steady')),
                                                     'no steady beat'))
    elif an['beat_quality'] == 'weak':
        warnings.append(f"the beat is weak (stability {an['clarity']['stability']:.2f}, salience "
                        f"{an['clarity']['salience']:.2f}): joins use {lay['crossfade_s']:.2f} s crossfades and "
                        'downbeats may be a beat off where the beat finder drifted')
    for n in an.get('notes') or []:
        if n not in warnings and an['beat_quality'] != 'none':
            warnings.append(n)
    if not ctx['speech_ok']:
        warnings.append('speech could not be detected (' + ctx.get('speech_error', '') + '): no dips under speech; '
                        'speech levels are unknown, not fine')
    if ctx['other_music']:
        warnings.append(f"other music tracks play too ({', '.join(ctx['other_music'])}); they are measured as part of "
                        'the programme sound')
    if any('loudness' in m for m in ctx['master'] if isinstance(m, dict)):
        warnings.append('the master has a dynamic loudness normaliser: it lifts quiet stretches and works against the '
                        'levels here; prefer a limiter and set the final loudness at export')
    for r in search['relaxed']:
        warnings.append(f"at {_clock(r['at'])} nothing fitted the limits, so these were relaxed: "
                        f"{', '.join(r['relaxed'])}")
    if reps['back_to_back_loops']:
        warnings.append(f"{len(reps['back_to_back_loops'])} back-to-back repeat(s) of the same bars (repeat.loops is "
                        f"{req['repeat']['loops']}): " + ', '.join(f"{_clock(x['at'])} bars {x['bars']}"
                                                                    for x in reps['back_to_back_loops'][:6]))
    return warnings


def _plan_findings(lay, secs, fps):
    findings = []
    for h in lay['hits']:
        if 'error_ms' in h:
            sev = 'info' if abs(h['error_ms']) <= max(25.0, 0.5e3 / fps + 1) else 'warning'
            findings.append({'kind': 'hit', 'severity': sev, 'timeline': [h['at'], h['lands_at']],
                             'source': [h['song'], h['song']],
                             'text': f"hit {h['hit']} ({h['kind']}) at {_clock(h['at'])}: song {_clock(h['song'])} "
                                     f"(bar {h['bar']}, {h['event']}) lands {h['error_ms']:+.1f} ms by {h['by']}",
                             'measured': False})
        else:
            findings.append({'kind': 'hit', 'severity': 'warning', 'timeline': [h['at'], h['at']],
                             'text': f"hit {h['hit']} at {_clock(h['at'])}: {h.get('by')}", 'measured': False})
    for j in lay['joins']:
        if j.get('flam_risk') or (j['grid_error_ms'] is not None and abs(j['grid_error_ms']) > 30):
            findings.append({'kind': 'join', 'severity': 'warning', 'timeline': [j['at'], j['at']],
                             'source': [j['from_song'], j['to_song']],
                             'text': f"join at {_clock(j['at'])} ({j['why']}): beat grid off by {j['grid_error_ms']:+.0f} ms"
                                     + (f"; {j['flam_risk']}" if j.get('flam_risk') else ''), 'measured': False})
    for s in secs:
        if s['energy_target'] is not None and s['energy_got'] is not None and abs(s['energy_got'] - s['energy_target']) > 0.25:
            findings.append({'kind': 'section', 'severity': 'warning', 'timeline': [s['from'], s['to']],
                             'text': f"section {_span(s['from'], s['to'])} asked for energy {s['energy_target']:.2f}, "
                                     f"the song's bars give {s['energy_got']:.2f}", 'measured': False})
    return findings


def plan(project, song, sections=None, hits=None, protect=None, start=None, end=None, repeat=None, max_stretch=0.0,
         track='Music', levels=None, ending='auto', entry='fade', song_range=None, options=None):
    """A soundtrack proposal for `project` from one `song` (nothing is written to the project). See the module
    docstring and soundtrack_tools.letitedit_soundtrack for every input and output."""
    import letitedit.timeline.edit_script as es
    t_start = time.time()
    path = es._resolve(project)
    if isinstance(song, (list, tuple)):
        if len(song) != 1:
            raise ValueError('one song per call in this version (several songs are not supported yet): score each '
                             'stretch with its own call and track, or pick one song')
        song = song[0]
    import letitedit.sound.audio_library as audio_library
    song = str(Path(audio_library.song_file(song)).resolve()) if song else None
    if not song or not Path(song).is_file():
        raise FileNotFoundError(f'No song at {song}')
    req = parse_request(sections, hits, protect, start, end, repeat, max_stretch, track, levels, ending, entry,
                        song_range, options)
    live = _live_state(path)
    if live and live.get('modified'):
        raise ValueError('This project is open in letitedit with unsaved changes: the plan would be made from the saved '
                         'file. Save it in letitedit (or ask the person to), then plan again.')
    ctx = _project_context(path, req)
    if req['start'] is None:
        req['start'] = 0.0
    if req['end'] is None:
        req['end'] = ctx['programme_end']
    if req['end'] - req['start'] < 2.0:
        raise ValueError(f"the music span {_span(req['start'], req['end'])} is too short (is the timeline empty? give "
                         'end)')
    for s in req['sections']:
        if s['to'] <= req['start'] or s['from'] >= req['end']:
            raise ValueError(f"section {_span(s['from'], s['to'])} is outside the music ({_span(req['start'], req['end'])})")
    an = analyze(song, beats_per_bar=req['options']['beats_per_bar'])
    sk = _skeleton(req, ctx, an)
    chosen, search = _search(sk, an, req, ctx)
    lay = _layout(sk, an, req, ctx)
    env = _envelope(req, ctx, an, sk, lay)
    fp = _fingerprints(path, an, ctx)
    request_echo = {k: v for k, v in req.items()}
    plan_id = _hash({'request': request_echo, 'fp': fp, 'song': song})
    changes = _changes(req, ctx, an, lay, plan_id)
    fps = ctx['fps']
    reps = _arrangement_repeats(lay['clips'], an, req)
    bar_grid = _plan_bar_grid(lay, fps)
    secs = _plan_sections(req, sk, an)
    pieces = _plan_pieces(lay, an, fps)
    warnings = _plan_warnings(sk, env, lay, search, an, ctx, req, reps)
    findings = _plan_findings(lay, secs, fps)
    unsupported = [
        'one song per call (several songs: not yet)',
        f"metre assumed {an['beats_per_bar']} beats per bar (options.beats_per_bar); bars of changing length are "
        'used as measured, but tempo changes within a stretch are not followed by the stretch option',
        'speed changes (max_stretch) use the engine\'s timewarp, which moves the pitch with the speed (cents reported); '
        'turn on Pitch Compensation in Properties to keep the pitch',
        'positions and in points are whole frames: timing includes up to half a frame of rounding '
        f'({500.0 / fps:.1f} ms here)',
        'no key detection: joins compare chroma (chords), not keys or modulations',
        'a project open in letitedit with unsaved changes is refused (save first)',
        'automated measurement cannot certify taste or perfect intelligibility: listen to the joins and the mix',
    ]
    music_span = {'start': _r(req['start'], 4), 'end': _r(req['end'], 4)}
    out = {
        'schema_version': SCHEMA, 'plan_id': plan_id, 'mode': 'plan', 'project': str(path),
        'project_revision': ctx['revision'], 'source_fingerprints': fp, 'fps': fps, 'track': req['track'],
        'song': song_brief(an), 'music': music_span,
        'settings': {'levels': req['levels'], 'options': req['options'], 'repeat': {**req['repeat'],
                                                                                    'max_uses_used': search['max_uses']},
                     'max_stretch': req['max_stretch'], 'ending': sk['ending'], 'ending_asked': req['ending'],
                     'entry': req['entry'], 'song_range': req['song_range']},
        'request': {'sections': req['sections'], 'hits': [{k: v for k, v in h.items() if k != 'index'}
                                                          for h in req['hits']], 'protect': req['protect']},
        'pieces': pieces, 'joins': lay['joins'], 'hits': lay['hits'], 'sections': secs,
        'protect': env['protect'],
        'gain': {k: env[k] for k in ('base_gain_db', 'reference_lufs', 'reference', 'song_lufs', 'peak_capped_db',
                                     'segments', 'curve')},
        'speech': {'detected': ctx['speech_ok'], 'spans': ctx['speech'][:400], 'dips': env['talk_spans'][:400],
                   'dialogue_lufs': _r(ctx['dialogue_lufs'], 1)},
        'repeats': reps, 'search': search, 'bar_grid': bar_grid,
        'changes': changes,
        'findings': findings,
        'checked_ranges': [{'range': [music_span['start'], music_span['end']],
                            'checks': ['hit timing (planned, whole frames)', 'join grid (planned)',
                                       'repeat limits (arrangement)', 'music level plan']}],
        'unchecked_ranges': [{'range': [music_span['start'], music_span['end']],
                              'checks': ['the rendered mix: true peak, music under speech, protected ranges, '
                                         'measured hit timing, audible loops (mode apply or measure)']}],
        'warnings': warnings, 'unsupported': unsupported,
        'next': f"apply it: letitedit_soundtrack(project, mode='apply', plan_id='{plan_id}') (refused if the project or "
                'the song changed since), or send `changes` to letitedit_timeline_apply yourself',
    }
    folder = WORK / plan_id
    folder.mkdir(parents=True, exist_ok=True)
    arts = {}
    try:
        arts['graph'] = _graph(out, lay, env, an, folder / 'plan.png')
    except Exception as e:  # noqa: BLE001 - the picture is a convenience
        warnings.append(f'plan picture failed: {e}')
    if req['options']['preview_audio']:
        try:
            arts['music_bed'] = _render_bed(lay, env, an, fps, folder / 'music-bed.mp3')
        except Exception as e:  # noqa: BLE001
            warnings.append(f'music preview failed: {e}')
    out['preview_artifacts'] = arts
    out['seconds'] = _r(time.time() - t_start, 2)
    _json_write(_plan_path(plan_id), out)
    return out


# ============================================================================ apply (the shared timeline apply)

class Stale(ValueError):
    """The project, the song or the footage the plan was measured on changed since the plan was made."""


def freshness(plan, path):
    """What changed since the plan was made: [] when it can be applied as it is."""
    import letitedit.timeline.edit_script as es
    out = []
    rev = es.file_hash(path)
    if rev != plan['project_revision']:
        out.append(f"the project changed since the plan (revision {plan['project_revision']} -> {rev})")
    fp = plan['source_fingerprints']
    try:
        now = _file_id(fp['song']['path'])
        if now['size'] != fp['song']['size'] or now['mtime_ns'] != fp['song']['mtime_ns']:
            out.append('the song file changed since the plan')
    except OSError:
        out.append('the song file is gone')
    if fp['analysis'].get('soundtrack') != ANALYSIS_VERSION or fp['analysis'].get('plan') != PLAN_VERSION:
        out.append('the soundtrack analysis changed (a newer version of this tool)')
    for s in fp.get('speech_sources') or []:
        try:
            now = _file_id(s['path'])
            if now['size'] != s['size'] or now['mtime_ns'] != s['mtime_ns']:
                out.append(f"{Path(s['path']).name} changed (speech and natural sound were measured on it)")
        except OSError:
            out.append(f"{Path(s['path']).name} is gone")
    return out


def _readback(path, plan):
    """The music track as written, compared with the plan: every piece there with the same source range, start
    (whole frames) and crossfade."""
    import letitedit.timeline.edit_script as es
    after = es.read(path)
    fps = float(after['profile']['fps'])
    track = next((t for t in after['tracks'] if t['name'] == plan['track']), None)
    if track is None:
        return {'ok': False, 'problems': [f"no track {plan['track']} after the apply"]}
    items = {it.get('id'): it for it in track['items'] if it.get('id')}
    problems = []
    for p in plan['pieces']:
        it = items.get(p['id'])
        if it is None:
            problems.append(f"{p['id']} missing")
            continue
        sp = float(it.get('speed', 1.0))
        a, b = es.to_seconds(it['in']), es.to_seconds(it['out'])
        if abs(a - p['song'][0]) > 0.5 * sp / fps + 1e-3 or abs(b - p['song'][1]) > 0.5 * sp / fps + 1e-3:
            problems.append(f"{p['id']}: song {a:.3f}-{b:.3f}, planned {p['song'][0]:.3f}-{p['song'][1]:.3f}")
        at = es.to_seconds(it['at'])
        tr = it.get('transition')
        tl = es.to_seconds(tr['len']) if isinstance(tr, dict) else 0.0
        if abs((at) - p['timeline'][0]) > 0.5 / fps + 1e-3:
            problems.append(f"{p['id']}: starts at {at:.3f}, planned {p['timeline'][0]:.3f} (transition {tl:.3f})")
    extra = [i for i in items if i not in {p['id'] for p in plan['pieces']}]
    if extra:
        problems.append(f"other items on {plan['track']}: {', '.join(extra[:8])}")
    return {'ok': not problems, 'pieces': len(plan['pieces']), 'problems': problems[:20]}


def apply(project, plan_or_id, force=False, measure_after=True, label=None, actor=None):
    """Apply a plan's changes through the shared timeline apply (timeline_tools.apply_project: one undo step in an
    open letitedit window, or the saved file with a history copy). Refused when the project, the song or the footage
    changed since the plan (force=True applies anyway). Then reads the track back and measures the rendered mix."""
    import letitedit.timeline.edit_script as es
    import letitedit.server.timeline_tools as timeline_tools
    pl = load_plan(plan_or_id)
    path = es._resolve(project)
    if Path(pl['project']).resolve() != Path(path).resolve():
        raise ValueError(f"plan {pl['plan_id']} was made for {pl['project']}, not {path}")
    stale = freshness(pl, path)
    if stale and not force:
        raise Stale('not applied: ' + '; '.join(stale) + '. Plan again (mode="plan"), or force=True to apply this '
                    'plan anyway.')
    live = _live_state(path)
    if live and live.get('modified'):
        raise ValueError('This project is open in letitedit with unsaved changes. Save it in letitedit (or ask the person '
                         'to), then plan again.')
    t0 = time.time()
    song = Path(pl['song']['song']).stem
    result, _ = timeline_tools.apply_project(path, pl['changes'], check=False, actor=actor,
                                             label=label or f'soundtrack: {song[:40]} ({len(pl["pieces"])} pieces)')
    out = {'schema_version': SCHEMA, 'plan_id': pl['plan_id'], 'mode': 'apply', 'project': str(path),
           'applied': {'changes': (result.get('changes') or [])[:60], 'notes': result.get('notes'),
                       'history': result.get('history'), 'editor': result.get('editor'),
                       'undo': 'letitedit_timeline_undo(project) puts the project back as it was before this apply',
                       'forced_over': stale or None},
           'project_revision_after': es.file_hash(path), 'readback': _readback(path, pl),
           'apply_seconds': _r(time.time() - t0, 2)}
    if measure_after:
        out['measurements'] = measure(path, pl)
        fix = out['measurements'].get('corrections')
        if fix and pl['settings']['options'].get('correct_engine_offsets', True):
            # the engine plays some pieces off time (it seeks this file imprecisely): shift them by whole frames,
            # as a second undo step, and measure again
            first = out['measurements']
            r2, _ = timeline_tools.apply_project(path, fix, check=False, actor=actor,
                                                 label=f'soundtrack: timing correction ({len(fix)} pieces)')
            out['correction'] = {'changes': fix, 'history': r2.get('history'),
                                 'before': [{k: x.get(k) for k in ('id', 'offset_ms', 'shift_frames')}
                                            for x in first.get('pieces') or [] if x.get('shift_frames')],
                                 'hits_before': [{k: x.get(k) for k in ('hit', 'measured_error_ms')}
                                                 for x in first.get('hits') or []],
                                 'undo': 'letitedit_timeline_undo(project) once removes this correction, twice the '
                                         'soundtrack'}
            out['project_revision_after'] = es.file_hash(path)
            out['measurements'] = measure(path, pl)
    return out


# ============================================================================ measure the rendered mix

def _render(mlt, out, timeout=7200):
    import letitedit.review.checks as checks
    checks._run([checks.MELT, '-quiet', str(mlt), '-consumer', f'avformat:{out}', 'vn=1', 'video_off=1',
                 'acodec=pcm_f32le', 'ar=48000', 'channels=2', 'real_time=-1'], timeout=timeout)
    return out


def _read(wav):
    import soundfile
    y, sr = soundfile.read(str(wav), dtype='float32', always_2d=True)
    if sr != MSR:
        raise RuntimeError(f'{wav}: {sr} Hz, expected {MSR}')
    return y


def _kpower(y, fs=MSR):
    """K-weighted power of every 100 ms (BS.1770, channels summed)."""
    import letitedit.sound.music as music
    from scipy.signal import lfilter
    (b1, a1), (b2, a2) = music._k_weighting(fs)
    z = lfilter(b2, a2, lfilter(b1, a1, y, axis=0), axis=0)
    hop = fs // 10
    n = len(z) // hop
    return (z[:n * hop] ** 2).reshape(n, hop, -1).mean(axis=1).sum(axis=1)


def _momentary(p):
    """Momentary loudness (400 ms) every 100 ms from 100 ms powers: (times of the window ends, LUFS)."""
    if len(p) < 4:
        return np.zeros(0), np.zeros(0)
    blocks = np.convolve(p, np.ones(4) / 4, mode='valid')
    return (np.arange(len(blocks)) + 4) / 10.0, -0.691 + 10 * np.log10(np.maximum(blocks, 1e-12))


def _lufs(p, a, b):
    import letitedit.sound.music as music
    seg = p[max(0, int(round(a * 10))):max(0, int(round(b * 10)))]
    return float(music.integrated(seg)) if seg.size >= 4 else None


def _align(stem, song, t_plan, u, sigma, before, after, search=0.08, sr=MSR):
    """Where song time u really plays near timeline t_plan in the rendered music stem: (offset s, match 0-1) by
    normalized cross-correlation of the stem window [t_plan - before, t_plan + after] with the song."""
    from scipy.signal import correlate
    a, b = int(round((t_plan - before) * sr)), int(round((t_plan + after) * sr))
    if a < 0 or b > len(stem) or b - a < int(0.2 * sr):
        return None, 0.0
    x = stem[a:b]
    if float(np.sqrt(np.mean(x ** 2))) < 1e-5:
        return None, 0.0
    lag = int(round(search * sr))
    s_a = u - before * sigma - search * sigma
    s_b = u + after * sigma + search * sigma
    i0, i1 = int(round(s_a * sr)), int(round(s_b * sr))
    pad0 = max(0, -i0)
    seg = song[max(0, i0):min(len(song), i1)]
    if pad0:
        seg = np.concatenate([np.zeros(pad0, np.float32), seg])
    if abs(sigma - 1) > 1e-9:
        n_out = int(round(len(seg) / sigma))
        seg = np.interp(np.linspace(0, len(seg) - 1, n_out), np.arange(len(seg)), seg).astype(np.float32)
    need = len(x) + 2 * lag
    if len(seg) < need:
        seg = np.concatenate([seg, np.zeros(need - len(seg), np.float32)])
    seg = seg[:need]
    c = correlate(seg, x, mode='valid', method='fft')            # c[k]: seg[k:k+len(x)] against x
    e = np.convolve(seg ** 2, np.ones(len(x)), mode='valid')
    c = c / (np.sqrt(e * float(np.sum(x ** 2))) + 1e-12)
    k = int(np.argmax(c))
    # seg[k] is song time s_a + k/sr (unstretched); x[0] is timeline t_plan - before, planned to be song u - before
    return (lag - k) / sr, float(c[k])


def _mix(dt, xf, fps):
    """Shotcut's audio mix progress dt seconds into an xf-second same-track transition: in its frame k (of n) the
    mix ramps from (k-1)/n to k/n (transition_mix: progress per frame, ramped per sample from the previous one)."""
    n = max(1, int(round(xf * fps)))
    f = np.clip(dt * fps, 0, n - 1e-9)
    k = np.floor(f)
    return np.maximum(0.0, (k - 1) / n) + ((k / n) - np.maximum(0.0, (k - 1) / n)) * (f - k)


def _expected(pl, song, a, b, sr=MSR, offsets=None):
    """The music the plan says plays over timeline [a, b], mono: every piece there times its gain keys, with the
    equal-power crossfades and the fades. offsets: {piece id: seconds} the render was measured to play a piece late
    (its material then shifts by that). None when no piece plays there."""
    fps = pl['fps']
    n = int(round((b - a) * sr))
    curve = pl['gain'].get('curve') or []
    if n <= 0 or not curve:
        return None
    t = a + np.arange(n) / sr
    g = 10 ** ((pl['gain']['base_gain_db'] + np.interp(t, [c[0] for c in curve], [c[1] for c in curve])) / 20)
    out = np.zeros(n)
    pieces = pl['pieces']
    hit = False
    for k, p in enumerate(pieces):
        s, e = p['timeline']
        if e <= a or s >= b:
            continue
        idx = np.flatnonzero((t >= s) & (t < e))
        if not idx.size:
            continue
        hit = True
        tt = t[idx]
        late = (offsets or {}).get(p['id'], 0.0)
        x = np.interp((p['song'][0] + (tt - s - late) * p['speed']) * sr, np.arange(len(song)), song, left=0.0,
                      right=0.0)
        w = np.ones(idx.size)
        xf = p.get('xfade_s') or 0.0
        if xf > 0:
            w *= np.where(tt < s + xf, np.sin(_mix(tt - s, xf, fps) * np.pi / 2), 1.0)
        nxt = pieces[k + 1] if k + 1 < len(pieces) else None
        if nxt is not None and (nxt.get('xfade_s') or 0) > 0 and abs(nxt['timeline'][0] + nxt['xfade_s'] - e) < 0.5 / fps:
            t0n = e - nxt['xfade_s']
            w *= np.where(tt >= t0n, np.cos(_mix(tt - t0n, nxt['xfade_s'], fps) * np.pi / 2), 1.0)
        fi, fo = p.get('fade_in_s') or 0.0, p.get('fade_out_s') or 0.0
        if fi > 0:
            w *= np.where(tt < s + fi, 10 ** ((-60 + 60 * np.clip((tt - s) / fi, 0, 1)) / 20), 1.0)
        if fo > 0:
            w *= np.where(tt > e - fo, 10 ** ((-60 * np.clip((tt - (e - fo)) / fo, 0, 1)) / 20), 1.0)
        out[idx] += x * w
    return (out * g).astype(np.float32) if hit else None


def _mel_spec(y, sr=MSR, n_fft=2048, hop=1024, n_mels=48):
    mono = y.mean(axis=1) if y.ndim > 1 else y
    fb = _mel_fb(sr, n_fft, n_mels, 40.0, 12000.0)
    n = max(0, 1 + (len(mono) - n_fft) // hop)
    win = np.hanning(n_fft).astype(np.float32)
    out = np.empty((n, n_mels), np.float32)
    offs = np.arange(n_fft)
    for s in range(0, n, 2048):
        e = min(n, s + 2048)
        P = np.abs(np.fft.rfft(mono[np.arange(s, e)[:, None] * hop + offs[None, :]] * win, axis=1)) ** 2
        out[s:e] = np.log10(P @ fb.T + 1e-10)
    return out, sr / hop


def _block_sim(S, fr, a, b, c, d):
    """Pearson correlation of two stretches of a log-mel spectrogram resampled to the same length."""
    i0, i1, j0, j1 = (int(round(t * fr)) for t in (a, b, c, d))
    if i1 - i0 < 4 or j1 - j0 < 4 or j1 > len(S):
        return None
    A, B = S[i0:i1], S[j0:j1]
    n = min(len(A), len(B))
    A = A[np.linspace(0, len(A) - 1, n).astype(int)]
    B = B[np.linspace(0, len(B) - 1, n).astype(int)]
    A, B = A - A.mean(), B - B.mean()
    den = float(np.sqrt((A ** 2).sum() * (B ** 2).sum()))
    return float((A * B).sum() / den) if den > 0 else None


def _measure_speech_balance(pl, a0, a1, pm, po, res, checked, unchecked, findings):
    spans = [s for s in (pl['speech'].get('spans') or []) if s[1] - s[0] >= 1.0 and s[0] >= a0 and s[1] <= a1]
    rows = []
    for s in spans:
        lm, lo = _lufs(pm, s[0], s[1]), _lufs(po, s[0], s[1])
        if lm is None or lo is None or lo <= -60:
            continue
        rows.append({'range': [s[0], s[1]], 'music_lufs': _r(lm, 1), 'speech_lufs': _r(lo, 1),
                     'music_under_lu': _r(lo - lm, 1)})
    if rows:
        under = np.asarray([x['music_under_lu'] for x in rows])
        res['speech'] = {'spans': len(rows), 'median_music_under_lu': _r(float(np.median(under)), 1),
                         'min_music_under_lu': _r(float(under.min()), 1),
                         'max_music_under_lu': _r(float(under.max()), 1),
                         'spans_under_10_lu': int(np.sum(under < 10)), 'spans_over_24_lu': int(np.sum(under > 24)),
                         'closest': sorted(rows, key=lambda x: x['music_under_lu'])[:5],
                         'about': 'integrated loudness (BS.1770) of each stem over each detected speech span; the '
                                  'other stem is the voice plus its room and natural sound'}
        checked.append({'range': [a0, a1], 'checks': [f'music under speech ({len(rows)} spans)']})
        if res['speech']['median_music_under_lu'] < 10:
            findings.append({'kind': 'speech', 'severity': 'problem', 'timeline': [a0, a1], 'measured': True,
                             'text': f"music only {res['speech']['median_music_under_lu']:.1f} LU under the voice "
                                     'while people talk (aim for 10-18)'})
        elif res['speech']['median_music_under_lu'] > 24:
            findings.append({'kind': 'speech', 'severity': 'warning', 'timeline': [a0, a1], 'measured': True,
                             'text': f"music {res['speech']['median_music_under_lu']:.1f} LU under the voice: it may be "
                                     'inaudible under speech'})
        for x in rows:
            if x['music_under_lu'] < 8:
                findings.append({'kind': 'speech', 'severity': 'warning', 'timeline': x['range'], 'measured': True,
                                 'text': f"{_span(*x['range'])}: music only {x['music_under_lu']:.1f} LU under the voice"})
    elif pl['speech'].get('detected'):
        res['speech'] = {'spans': 0, 'note': 'no speech of 1 s or more inside the music'}
    else:
        unchecked.append({'range': [a0, a1], 'checks': ['music under speech: speech detection was unavailable']})


def _measure_protected_ranges(pl, m, pm, po, res, checked, findings, a0, a1):
    prot = []
    for p in pl['protect']:
        a, b = p['from'], p['to']
        i0, i1 = int(round(a * MSR)), int(round(b * MSR))
        seg = m[max(0, i0):max(0, i1)]
        mpk = 20 * math.log10(float(np.abs(seg).max(initial=0.0)) + 1e-12)
        tt, mom = _momentary(pm)
        inside = (tt - 0.4 >= a - 1e-6) & (tt <= b + 1e-6)
        mmax = float(mom[inside].max()) if inside.any() else None
        lm, lo = _lufs(pm, a, b), _lufs(po, a, b)
        rec = {'from': a, 'to': b, 'mode': p['mode'], 'music_peak_dbfs': _r(mpk, 1),
               'music_lufs': _r(lm, 1), 'music_max_momentary_lufs': _r(mmax, 1), 'natural_sound_lufs': _r(lo, 1)}
        if lm is not None and lo is not None and lo > -60:
            rec['music_under_natural_lu'] = _r(lo - lm, 1)
        if p['mode'] == 'drop_out':
            ok = mpk <= -50
            rec['verdict'] = 'music off' if ok else 'music audible'
            if not ok:
                findings.append({'kind': 'protect', 'severity': 'problem', 'timeline': [a, b], 'measured': True,
                                 'text': f'drop_out {_span(a, b)}: the music still peaks at {mpk:.1f} dBFS there'})
        else:
            margin = rec.get('music_under_natural_lu')
            rec['verdict'] = ('unknown (no natural sound measured)' if margin is None else
                              'clear' if margin >= 12 else 'close')
            if margin is not None and margin < 12:
                findings.append({'kind': 'protect', 'severity': 'warning', 'timeline': [a, b], 'measured': True,
                                 'text': f'duck_deep {_span(a, b)}: music only {margin:.1f} LU under the natural sound'})
        prot.append(rec)
    res['protect'] = prot
    if prot:
        checked.append({'range': [a0, a1], 'checks': [f'protected ranges ({len(prot)})']})


def _measure_hit_positions(pl, mono, song, fps, res, unchecked, findings):
    meas_hits = []
    for h in pl['hits']:
        if 'lands_at' not in h:
            continue
        piece = next((p for p in pl['pieces'] if p['timeline'][0] - 1e-6 <= h['lands_at'] < p['timeline'][1]), None)
        sg = piece['speed'] if piece else 1.0
        joined = h.get('by') in ('join', 'break', 'entry', 'stretch')
        before, after = (-0.02, 0.6) if joined else (0.35, 0.5)
        off, q = _align(mono, song, h['lands_at'], h['song'], sg, before, after)
        rec = {'hit': h['hit'], 'at': h['at'], 'planned_error_ms': h.get('error_ms')}
        if off is None or q < 0.5:
            rec['measured'] = None
            rec['note'] = f'no reliable match in the rendered music (match {q:.2f})'
            unchecked.append({'range': [h['at'] - 0.5, h['at'] + 0.5], 'checks': [f"hit {h['hit']} timing"]})
        else:
            rec['measured_error_ms'] = _ms(h['lands_at'] + off - h['at'])
            rec['match'] = _r(q, 3)
            if abs(rec['measured_error_ms']) > max(30.0, 500.0 / fps + 8):
                findings.append({'kind': 'hit', 'severity': 'warning', 'timeline': [h['at'], h['at'] + off],
                                 'measured': True, 'text': f"hit {h['hit']} at {_clock(h['at'])} lands "
                                                           f"{rec['measured_error_ms']:+.0f} ms off in the render"})
        meas_hits.append(rec)
    res['hits'] = meas_hits
    return meas_hits


def _measure_piece_positions(pl, song, mono, fps, res, findings, checked, a0, a1):
    rows, corrections = [], []
    song_len = len(song) / MSR
    for p in pl['pieces']:
        s, e = p['timeline']
        a = s + (p.get('xfade_s') or 0.0) + max(0.1, p.get('fade_in_s') or 0.0)
        b = min(e - (p.get('fade_out_s') or 0.0) - 0.05, a + 1.2)
        if b - a < 0.4:
            continue
        mid = (a + b) / 2
        off, q = _align(mono, song, mid, p['song'][0] + (mid - s) * p['speed'], p['speed'], (b - a) / 2, (b - a) / 2)
        if off is None or q < 0.6:
            continue
        row = {'id': p['id'], 'offset_ms': _ms(off), 'match': _r(q, 3)}
        k = int(round(off * fps))
        if abs(off) > 0.5 / fps + 0.002 and k:
            shift = k * p['speed'] / fps
            idx = pl['pieces'].index(p)
            nxt = pl['pieces'][idx + 1] if idx + 1 < len(pl['pieces']) else None
            chained_next = nxt is not None and abs(nxt['timeline'][0] + (nxt.get('xfade_s') or 0.0) - e) < 0.5 / fps
            if p['song'][0] + shift >= 0 and p['song'][1] + shift <= song_len:
                corrections.append({'op': 'set', 'id': p['id'], 'in': round(p['song'][0] + shift, 6),
                                    'out': round(p['song'][1] + shift, 6)})
                row['shift_frames'] = k
            elif shift > 0 and not chained_next and p['song'][1] - p['song'][0] > 2 * shift:
                # nothing follows it on the track: it starts later in the song and ends where it did (k frames shorter)
                corrections.append({'op': 'set', 'id': p['id'], 'in': round(p['song'][0] + shift, 6)})
                row['shift_frames'] = k
                row['note'] = 'shortened at its end: the song has no material after it'
            else:
                row['note'] = 'cannot shift: the song has no material there'
        rows.append(row)
    res['pieces'] = rows
    late_by = {r['id']: r['offset_ms'] / 1000.0 for r in rows}
    off_rows = [r for r in rows if abs(r['offset_ms']) > 500.0 / fps + 2]
    if off_rows:
        res['corrections'] = corrections
        findings.append({'kind': 'engine', 'severity': 'warning', 'timeline': [a0, a1], 'measured': True,
                         'text': f"the render plays {len(off_rows)} piece(s) off the plan by "
                                 f"{min(r['offset_ms'] for r in off_rows):+.0f} to {max(r['offset_ms'] for r in off_rows):+.0f}"
                                 ' ms: the engine seeks this song file imprecisely (a VBR MP3?); `corrections` (set '
                                 'ops) shift their in points by whole frames'})
        checked.append({'range': [a0, a1], 'checks': [f'piece placement ({len(rows)} pieces)']})
    elif rows:
        checked.append({'range': [a0, a1], 'checks': [f'piece placement ({len(rows)} pieces, all within half a frame)']})
    return late_by


def _measure_join_levels(pl, fps, mono, song, late_by, res, unchecked, findings):
    meas_joins = []
    for j in pl['joins']:
        t = j['at']
        piece_in = next((p for p in pl['pieces'] if abs(p['timeline'][0] + j['crossfade_s'] - t) < 1.5 / fps), None)
        sg = piece_in['speed'] if piece_in else 1.0
        ev = j.get('event_at', t)
        off_in, q_in = _align(mono, song, ev, j['to_song'], sg, -0.02, 0.5)
        rec = {'at': t, 'planned_grid_error_ms': j.get('grid_error_ms')}
        if off_in is not None and q_in >= 0.5:
            rec['incoming_offset_ms'] = _ms(off_in)       # the incoming downbeat, render against plan
            rec['match'] = _r(q_in, 3)
        else:
            unchecked.append({'range': [t - 0.3, t + 0.3], 'checks': ['join timing (no reliable match)']})
        # the level across the join against what the plan says plays there (a hole or a bump in the crossfade):
        # before the crossfade, inside it, just after the join
        xf = j['crossfade_s']
        lv = []
        for wa, wb in ((t - xf - 0.12, t - xf), (t - xf, t), (t + 0.005, t + 0.125)):
            if wb - wa < 0.02:
                lv.append(None)
                continue
            exp = _expected(pl, song, wa, wb, offsets=late_by)
            i0, i1 = int(round(wa * MSR)), int(round(wb * MSR))
            if exp is None or i0 < 0 or i1 > len(mono):
                lv.append(None)
                continue
            e_rms = float(np.sqrt(np.mean(exp ** 2)))
            r_rms = float(np.sqrt(np.mean(mono[i0:i1] ** 2)))
            lv.append(_r(20 * math.log10((r_rms + 1e-9) / (e_rms + 1e-9)), 1) if e_rms > 1e-5 else None)
        rec['level_vs_plan_db'] = lv
        rec['about_level'] = 'render RMS against the planned signal (before the crossfade, in it, after the join)'
        if lv[1] is not None and lv[1] < -6 and all(x is None or abs(x) < 3 for x in (lv[0], lv[2])):
            findings.append({'kind': 'join', 'severity': 'warning', 'timeline': [t - xf, t], 'measured': True,
                             'text': f'join at {_clock(t)}: the crossfade is {lv[1]:.0f} dB under the plan (a hole)'})
        meas_joins.append(rec)
    res['joins'] = meas_joins
    return meas_joins


def _measure_planned_envelope(pl, song, late_by, mono, res, findings, a0, a1):
    env_rows = []
    for p in pl['pieces']:
        s, e = p['timeline']
        lo, hi = s + max(p.get('xfade_s', 0), p.get('fade_in_s', 0)) + 0.1, e - p.get('fade_out_s', 0) - 0.15
        for c in np.linspace(lo, hi, 4)[1:-1] if hi - lo > 1.0 else []:
            exp = _expected(pl, song, c - 0.2, c + 0.2, offsets=late_by)
            i0, i1 = int(round((c - 0.2) * MSR)), int(round((c + 0.2) * MSR))
            if exp is None or i1 > len(mono):
                continue
            e_rms = float(np.sqrt(np.mean(exp ** 2)))
            if e_rms < 1e-5:
                continue
            env_rows.append(20 * math.log10((float(np.sqrt(np.mean(mono[i0:i1] ** 2))) + 1e-9) / e_rms))
    if env_rows:
        dev = np.abs(np.asarray(env_rows))
        res['envelope_vs_plan'] = {'windows': len(env_rows), 'median_abs_db': _r(float(np.median(dev)), 2),
                                   'max_abs_db': _r(float(dev.max()), 2),
                                   'about': 'music stem RMS against the planned pieces x gain keys, 0.4 s windows '
                                            'inside each piece'}
        if float(dev.max()) > 3.0:
            findings.append({'kind': 'level', 'severity': 'warning', 'timeline': [a0, a1], 'measured': True,
                             'text': f'the rendered music is up to {float(dev.max()):.1f} dB off the planned level'})


def _measure_audible_repeats(m, pl, res, findings, checked, a0, a1):
    S, fr = _mel_spec(m)
    grid = pl.get('bar_grid') or []
    loops = []
    for Lb in (1, 2, 4):
        for i in range(0, len(grid) - 2 * Lb + 1):
            g = grid[i:i + 2 * Lb]
            contiguous = all(abs((g[k][0] + g[k][3]) - g[k + 1][0]) < 0.06 for k in range(len(g) - 1))
            if not contiguous:
                continue
            a, b, c = g[0][0], g[Lb][0], g[2 * Lb - 1][0] + g[2 * Lb - 1][3]
            sim = _block_sim(S, fr, a, b, b, c)
            if sim is None or sim < 0.95:
                continue
            same = [x[1] for x in g[:Lb]] == [x[1] for x in g[Lb:]]
            loops.append({'at': _r(b, 2), 'bars': Lb, 'similarity': _r(sim, 3),
                          'cause': 'the edit repeats the same bars' if same else 'the song repeats itself here',
                          'song_bars': f'{g[0][1] + 1}-{g[Lb - 1][1] + 1}'})
    made = [x for x in loops if x['cause'].startswith('the edit')]
    res['loops'] = {'edit_made': made[:20], 'in_the_song': len(loops) - len(made),
                    'about': 'log-mel similarity >= 0.95 between a block of played bars and the next one; '
                             '"in the song" repeats are the song\'s own and need no fixing'}
    for x in made:
        findings.append({'kind': 'loop', 'severity': 'warning', 'timeline': [x['at'], x['at']], 'measured': True,
                         'text': f"audible loop at {_clock(x['at'])}: song bars {x['song_bars']} play twice in a row"})
    if grid:
        checked.append({'range': [a0, a1], 'checks': ['back-to-back repeats']})


def measure(project, plan_or_id, keep_audio=False):
    """Render the project's mix with melt as two stems (the plan's music track / everything else) and measure it
    against the plan: true peak and loudness of the mix, music against the dialogue while people talk, the level in
    every protected range, where each hit and join really landed (cross-correlation with the song), back-to-back
    repeats you can hear, and the music's loudness per section. files: mp3s of the music stem and the mix to listen
    to; keep_audio=True also keeps the 48 kHz float WAVs (about 23 MB a minute each)."""
    import letitedit.review.checks as checks
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.timeline_model as tm
    t_start = time.time()
    pl = load_plan(plan_or_id)
    path = es._resolve(project)
    timeline = tm.load(path)
    fps = timeline.fps
    mus = [t.index for t in timeline.tracks if t.name == pl['track']]
    if not mus:
        raise ValueError(f"no track {pl['track']} in {path}: apply the plan first")
    others = [t.index for t in timeline.tracks if t.index not in mus]
    work = WORK / pl['plan_id'] / f"measure-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    work.mkdir(parents=True, exist_ok=True)
    stale = freshness(pl, path)
    a0, a1 = pl['music']['start'], pl['music']['end']
    mv = checks._variant(path, timeline, set(mus))
    ov = checks._variant(path, timeline, set(others))
    try:
        m = _read(_render(mv, work / 'music.wav'))
        r = _read(_render(ov, work / 'other.wav'))
    finally:
        for f in (mv, ov):
            Path(f).unlink(missing_ok=True)
    n = max(len(m), len(r))
    m = np.vstack([m, np.zeros((n - len(m), 2), np.float32)]) if len(m) < n else m
    r = np.vstack([r, np.zeros((n - len(r), 2), np.float32)]) if len(r) < n else r
    master = [f for f in timeline.master_filters if f.get('mlt_service') not in ('subtitle_feed', 'subtitle')]
    if master:
        mix = _read(_render(path, work / 'mix.wav'))
        how = 'rendered with the master effects'
    else:
        import soundfile
        mix = m + r
        soundfile.write(str(work / 'mix.wav'), mix, MSR, subtype='FLOAT')
        how = 'the two stems summed (no master effects)'
    _series, summ = checks.loudness_series(work / 'mix.wav')
    _ms_series, msumm = checks.loudness_series(work / 'music.wav')
    pm, po = _kpower(m), _kpower(r)
    peak = float(np.abs(mix).max(initial=0.0))
    res = {'rendered_by': 'melt (the export engine), 48 kHz float', 'mix': how,
           'true_peak_dbtp': summ.get('true_peak_dbfs'), 'sample_peak_dbfs': _r(20 * math.log10(peak + 1e-12), 2),
           'samples_over_full_scale': int(np.sum(np.abs(mix) > 1.0)), 'integrated_lufs': summ.get('integrated_lufs'),
           'loudness_range_lu': summ.get('range_lu'), 'music_integrated_lufs': msumm.get('integrated_lufs'),
           'music_true_peak_dbtp': msumm.get('true_peak_dbfs'),
           'other_integrated_lufs': _r(_lufs(po, 0, len(po) / 10.0), 1)}
    findings, checked, unchecked = [], [], []
    checked.append({'range': [0.0, _r(n / MSR, 3)], 'checks': ['true peak', 'loudness', 'clipping']})
    tp = res['true_peak_dbtp']
    if tp is not None and tp > -1.0:
        findings.append({'kind': 'peak', 'severity': 'warning', 'timeline': [0.0, _r(n / MSR, 2)], 'measured': True,
                         'text': f"true peak {tp:+.1f} dBTP in the mix (the music alone: "
                                 f"{res['music_true_peak_dbtp']} dBTP): letitedit_export's limiter holds -1 dBTP "
                                 "(or add {op: master, effects: [{limiter: {limit_db: -1.5}}]})"})
    # music against the dialogue while people talk
    _measure_speech_balance(pl, a0, a1, pm, po, res, checked, unchecked, findings)
    # protected ranges
    _measure_protected_ranges(pl, m, pm, po, res, checked, findings, a0, a1)
    # where hits and joins really landed
    song = _decode(pl['song']['song'], MSR, 2).mean(axis=1)     # the same downmix as the stem below
    mono = m.mean(axis=1)
    meas_hits = _measure_hit_positions(pl, mono, song, fps, res, unchecked, findings)
    # every piece: where the render really plays it. A song file the engine seeks imprecisely (some VBR MP3s) plays
    # late or early by a constant amount per piece; whole-frame shifts of its in/out points correct that.
    late_by = _measure_piece_positions(pl, song, mono, fps, res, findings, checked, a0, a1)
    meas_joins = _measure_join_levels(pl, fps, mono, song, late_by, res, unchecked, findings)
    # the envelope as rendered: the music stem against the planned signal in the middle of every piece
    _measure_planned_envelope(pl, song, late_by, mono, res, findings, a0, a1)
    if meas_hits or meas_joins:
        checked.append({'range': [a0, a1], 'checks': [f'hit timing ({len(meas_hits)})', f'joins ({len(meas_joins)})']})
    # back-to-back repeats you can hear: each block of 1, 2 or 4 played bars against the block right after it
    _measure_audible_repeats(m, pl, res, findings, checked, a0, a1)
    # music loudness per section (does the energy contour come through?)
    secs = []
    for s in pl['sections']:
        a, b = s['from'], s['to']
        quiet = [sp for sp in pl['speech'].get('dips') or [] if sp[1] > a and sp[0] < b]
        secs.append({'from': a, 'to': b, 'energy_asked': s['energy_asked'], 'music_lufs': _r(_lufs(pm, a, b), 1),
                     'under_speech_share': _r(sum(min(b, y) - max(a, x) for x, y in quiet) / max(1e-6, b - a), 2)})
    res['sections'] = secs
    # drop-out ranges have no music to align: not checked for timing
    for p in pl['protect']:
        if p['mode'] == 'drop_out':
            unchecked.append({'range': [p['from'], p['to']], 'checks': ['music timing (no music there by design)']})
    res['findings'] = findings
    res['checked_ranges'] = checked
    res['unchecked_ranges'] = unchecked
    res['stale'] = stale or None
    try:
        tt, mom_m = _momentary(pm)
        _, mom_o = _momentary(po)
        series = {'music': list(zip(tt.tolist(), mom_m.tolist())), 'other': list(zip(tt.tolist(), mom_o.tolist()))}
        lay = _LayoutView(pl)
        res['graph'] = _graph(pl, lay, _EnvView(pl), _SongView(pl), work / 'measured.png', measured=series)
    except Exception as e:  # noqa: BLE001 - the picture is a convenience
        res['graph_error'] = str(e)
    wavs = {'music': work / 'music.wav', 'other': work / 'other.wav', 'mix': work / 'mix.wav'}
    files = {}
    for name in ('music', 'mix'):                      # small copies to listen to
        try:
            import letitedit.sound.av_tools as av_tools
            src = mix if name == 'mix' else m
            av_tools._write_audio(src, MSR, work / f'{name}.mp3')
            files[name] = str(work / f'{name}.mp3')
        except Exception as e:  # noqa: BLE001 - listening copies are a convenience
            res.setdefault('notes', []).append(f'{name}.mp3 not written: {e}')
    if keep_audio:
        files.update({f'{k}_wav': str(v) for k, v in wavs.items()})
    else:
        for f in wavs.values():
            Path(f).unlink(missing_ok=True)
    res['files'] = files
    res['seconds'] = _r(time.time() - t_start, 1)
    with open(work / 'measurements.json', 'w', encoding='utf-8') as fh:
        json.dump(res, fh, indent=1)
    return res


class _LayoutView(dict):
    """The plan's pieces in the shape _graph draws (for the measured picture)."""
    def __init__(self, pl):
        fps = pl['fps']
        clips = []
        grid = pl.get('bar_grid') or []
        for p in pl['pieces']:
            sg = p['speed']
            slots = [{'bar': g[1], 'tau0': g[0], 'u0': 0.0, 'u1': g[3] * sg} for g in grid if g[2] == p['id']]
            clips.append({'M': int(round(p['timeline'][0] * fps)), 'E': int(round(p['timeline'][1] * fps)),
                          'W_in': int(round(p['song'][0] * fps / sg)), 'sigma': sg, 'slots': slots})
        super().__init__(clips=clips)


class _EnvView(dict):
    def __init__(self, pl):
        super().__init__(curve=pl['gain']['curve'], talk_spans=pl['speech'].get('dips') or [], protect=pl['protect'])


class _SongView(dict):
    def __init__(self, pl):
        an = analyze(pl['song']['song'])
        super().__init__(duration=an['duration'], energy=an['energy'])


# ============================================================================ the tool

def soundtrack(project=None, song=None, sections=None, hits=None, protect=None, start=None, end=None, repeat=None,
               max_stretch=0.0, mode='plan', plan_id=None, track='Music', levels=None, ending='auto', entry='fade',
               song_range=None, options=None, force=False):
    """The MCP tool's body (see soundtrack_tools.letitedit_soundtrack)."""
    mode = str(mode or 'plan').lower()
    if mode not in MODES:
        raise ValueError(f'mode is {" | ".join(MODES)}, not {mode!r}')
    if mode == 'song':
        if not song:
            raise ValueError("mode 'song' needs song (a music file)")
        bpb = int((options or {}).get('beats_per_bar', OPTIONS['beats_per_bar']))
        return {'schema_version': SCHEMA, 'mode': 'song', 'song': song_brief(analyze(song, beats_per_bar=bpb))}
    if not project:
        raise ValueError('project is the .mlt (or episode/cut folder) to score')
    if mode == 'measure':
        if not plan_id:
            raise ValueError("mode 'measure' needs plan_id (the plan whose ranges and hits are measured)")
        return {'schema_version': SCHEMA, 'mode': 'measure', 'plan_id': plan_id,
                'measurements': measure(project, plan_id)}
    if mode == 'apply' and plan_id:
        return apply(project, plan_id, force=force)
    if not song:
        raise ValueError('song is the music file to arrange (referenced in place, never copied)')
    p = plan(project, song, sections=sections, hits=hits, protect=protect, start=start, end=end, repeat=repeat,
             max_stretch=max_stretch, track=track, levels=levels, ending=ending, entry=entry, song_range=song_range,
             options=options)
    if mode == 'plan':
        return p
    applied = apply(project, p, force=force)
    return {**p, **{k: v for k, v in applied.items() if k not in ('schema_version', 'plan_id', 'project')},
            'mode': 'apply'}


def job(ctx):
    """jobs.py kind 'soundtrack:job' (long timelines in the background): ctx.inputs are soundtrack()'s arguments."""
    inp = dict(ctx.inputs or {})
    mode = str(inp.get('mode') or 'plan').lower()
    ctx.progress(0.05, 'analysing the song and the project')
    ctx.check()
    if mode == 'apply' and not inp.get('plan_id'):
        args = {k: v for k, v in inp.items() if k not in ('mode', 'plan_id', 'force')}
        p = plan(**args)
        ctx.save(plan_id=p['plan_id'])
        ctx.progress(0.4, f"plan {p['plan_id']} made; applying")
        ctx.check()
        a = apply(inp['project'], p['plan_id'], force=bool(inp.get('force')), measure_after=False)
        ctx.progress(0.55, 'applied; rendering the mix to measure it')
        ctx.check()
        a['measurements'] = measure(inp['project'], p['plan_id'])
        ctx.progress(1.0, 'done')
        return {'plan_id': p['plan_id'], 'plan_file': str(_plan_path(p['plan_id'])), 'readback': a['readback'],
                'measurements': a['measurements']}
    out = soundtrack(**inp)
    ctx.progress(1.0, 'done')
    return {'result': out}
