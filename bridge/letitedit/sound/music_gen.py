r"""Generated instrumental music on this PC (ACE-Step 1.5, MIT), lined up with a cut by the beat tools.

    make(description, length=None, bpm=None, key=None, time_signature=None, seed=None, steps=None, shift=None,
         extra_s=None, hits=None, cuts=None, cuts_on=None, project=None, fit=None, land=None, crossfade_s=None,
         stretch_max=None, tolerance_s=None, snap=None, fade_in=None, fade_out=None, peak_db=None, out=None)
        -> {'file', 'raw_file', 'length_s', 'bpm', 'beats', 'downbeats', 'sections', 'fit', 'alignment', ...}
    release()   the music model off the GPU (model_tools.release() does the same for every model)

From a shell: python music_gen.py make '{"description": "...", "length": 30}'  -> the result as JSON.

The model runs in music_gen_worker.py in C:\LetItEdit\envs\music_acestep (one of model_tools' workers: same GPU lock,
same make-room rule, exits after LETITEDIT_MODEL_IDLE seconds idle). The generated take is analysed with
perception.music (tempo, beats, downbeats, sections) and, when a length or hits are given, cut and joined on its own
beats and bars by av_tools.fit_music (letitedit_fit_music).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import letitedit.sound.model_tools as model_tools  # noqa: E402

MODEL = 'ACE-Step/Ace-Step1.5 (acestep-v15-turbo 2B DiT + VAE + Qwen3-Embedding-0.6B; DiT-only, no 5 Hz LM)'
LICENCE = ('MIT (code and weights): https://github.com/ace-step/ACE-Step-1.5/blob/main/LICENSE, '
           'https://huggingface.co/ACE-Step/Ace-Step1.5')
MUSIC_PYTHON = Path(os.environ.get('LETITEDIT_MUSIC_PYTHON', model_tools.ENVS / 'music_acestep' / 'Scripts' / 'python.exe'))
CACHE = model_tools.CACHE.parent / 'music_gen'
DEFAULTS = {'steps': 8, 'shift': 3.0, 'extra_s': 8.0, 'length': 30.0, 'cuts_on': 'downbeat', 'peak_db': -1.0,
            'min_s': 10.0, 'max_s': 600.0}
NEED_MB = 7600             # measured peak 7.3 GB for 30 s on the RTX 2070 SUPER (VAE decode tiles itself to fit)

if 'music' not in model_tools._WORKERS:
    model_tools._WORKERS['music'] = model_tools._Worker('music', MUSIC_PYTHON, HERE / 'music_gen_worker.py')
model_tools.NEED_MB[('music', 'generate')] = NEED_MB


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def _out_of_memory(error):
    return re.search(r'memory|vram', str(error), re.I) is not None


def _plain_memory_error(error):
    """The model's "Reduce batch size" advice names settings this tool doesn't have, and its figures round to the same
    number. When the graphics card is what's short, say that; anything else stays as it was."""
    if not _out_of_memory(error):
        return error
    return RuntimeError('there is not enough free graphics memory for the music model right now: something else on this PC '
                        'is using the graphics card. The same call can be made again once that has finished, and a '
                        f'shorter length needs less (the model said: {str(error)[:160]})')


def _slug(text, n=40):
    s = re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')
    return (s[:n].rstrip('-')) or 'music'


def _ffmpeg():
    return model_tools._ffmpeg()


def _tag(src, dst, title, comment):
    """Copy src to dst (same samples) with generated-media metadata; the codec follows dst's extension."""
    import letitedit.pictures.gen_common as gen_common
    ext = Path(dst).suffix.lower()
    codec = {'.wav': ['-c:a', 'copy'], '.flac': ['-c:a', 'flac'], '.mp3': ['-c:a', 'libmp3lame', '-b:a', '320k'],
             '.m4a': ['-c:a', 'aac', '-b:a', '256k'], '.ogg': ['-c:a', 'libvorbis', '-q:a', '8']}.get(ext, ['-c:a', 'copy'])
    tmp = Path(dst).with_name(Path(dst).stem + '.tmp' + ext)
    subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-i', str(src), '-map_metadata', '-1', *codec,
                    *gen_common.meta_args('music', title, comment), str(tmp)], check=True,
                   creationflags=model_tools.NO_WINDOW)
    os.replace(tmp, dst)


def _project_info(project):
    import letitedit.timeline.timeline_model as timeline_model
    tl = timeline_model.load(project)
    cuts = [round(f / tl.fps, 4) for f in tl.cut_points()]
    return {'project': str(Path(project).resolve()), 'length_s': round(tl.seconds, 3), 'fps': tl.fps, 'v1_cuts_s': cuts}


def _nearest(arr, t):
    return min(arr, key=lambda x: abs(x - t)) if arr else None


def release():
    """The music model off the GPU (and out of RAM)."""
    w = model_tools._WORKERS['music']
    with model_tools._gpu_turn():
        return {'music': bool(w.alive() and w.call('release', timeout=300).get('released'))}


def _generate_take(spec, description, seed, gen_s, fit, raw):
    """The raw take: reused when cached, else written by the model (a 60 s take when a longer one runs out of
    graphics memory and the fit can loop it), tagged, with its sidecar."""
    cached = raw.exists() and raw.with_suffix('.wav.json').exists()
    gen = None
    if cached:
        gen = json.loads(raw.with_suffix('.wav.json').read_text(encoding='utf-8-sig')).get('generation')
    else:
        tmp = raw.with_name(raw.stem + '.model.wav')
        try:
            gen = model_tools._job('music', 'generate', timeout=3600, out=str(tmp), **spec)
        except Exception as e:  # noqa: BLE001
            # Long takes can exceed the GPU's memory even with offloading. Write a 60 s take instead and let the
            # fit below loop it on its own bars to the length asked for (what an editor would do by hand).
            if not _out_of_memory(e) or not fit or spec['duration'] <= 60:
                raise _plain_memory_error(e) from e
            spec['duration'] = 60.0
            h = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]
            raw = CACHE / 'takes' / f'generated-music-{_slug(description)}-{seed}-{h}.wav'
            tmp = raw.with_name(raw.stem + '.model.wav')
            try:
                gen = model_tools._job('music', 'generate', timeout=3600, out=str(tmp), **spec)
            except Exception as again:  # noqa: BLE001
                raise _plain_memory_error(again) from again
            gen = {**(gen or {}), 'note': f'a {gen_s:.0f} s take ran out of GPU memory; made 60 s and looped it on bars'}
        _tag(tmp, raw, description[:120], f'ACE-Step 1.5 turbo, seed {seed}; {description}')
        tmp.unlink(missing_ok=True)
        raw.with_suffix('.wav.json').write_text(json.dumps({'generated': True, 'kind': 'music', 'spec': spec,
                                                            'model': MODEL, 'licence': LICENCE, 'generation': gen},
                                                           indent=1), encoding='utf-8')
    return cached, gen, raw


def _cut_alignment(cuts, proj, beats, downs):
    """Per cut, the nearest beat and downbeat of the music and how far each is from the cut."""
    alignment = []
    for c in cuts or (proj['v1_cuts_s'] if proj else []):
        b, d = _nearest(beats, c), _nearest(downs, c)
        alignment.append({'cut_s': _r(c), 'nearest_beat_s': _r(b), 'beat_offset_s': _r(None if b is None else b - c),
                          'nearest_downbeat_s': _r(d),
                          'downbeat_offset_s': _r(None if d is None else d - c)})
    return alignment


def make(description, length=None, bpm=None, key=None, time_signature=None, seed=None, steps=None, shift=None,
         extra_s=None, hits=None, cuts=None, cuts_on=None, project=None, fit=None, land=None, crossfade_s=None,
         stretch_max=None, tolerance_s=None, snap=None, fade_in=None, fade_out=None, peak_db=None, out=None):
    """Instrumental music written by a local model to a text description, then cut to a length or to hit times.

    description: what the music is (genre, instruments, mood, energy, era...; the model's caption, < 512 characters).
    length: seconds wanted (default: the project's length with project=, else 30). bpm (30-300), key ('C major',
    'F# minor', ...), time_signature (2, 3, 4 or 6): passed to the model; None = the model's own choice.
    seed: repeatable take (None: random, reported). steps (default 8), shift (default 3.0): the turbo model's
    diffusion steps and timestep shift. peak_db: the take's peak level (default -1.0 dBFS).
    The take is generated extra_s seconds (default 8) longer than length (10-600 s), so the fit has bars to cut on.
    fit: cut and join the take on its own beats and bars with av_tools.fit_music (default True when there is a length
    or hits): length, hits ([[output_s, 'downbeat' | 'beat' | 'section' | 'section:<name>' | 'end' | take_s], ...]),
    land, crossfade_s, stretch_max, tolerance_s, snap, fade_in, fade_out pass through (their defaults are fit_music's).
    cuts: times (s) in the output, or 'project' (the project's V1 cut times); cuts_on 'downbeat' (default) | 'beat' |
    'section' turns each into a hit, 'none' only reports where the music's grid falls at each cut.
    project: a .mlt project: its length is the default length, its V1 cuts are reported, and files go to
    <project folder>\\made (else C:\\LetItEdit\\cache\\music_gen). out: the output file (.wav 32-bit float, .flac,
    .mp3, .m4a, .ogg).
    Returns the file (fitted, or the raw take with fit=False), the raw take, tempo asked and measured, beats,
    downbeats and sections of the file, the fit report (pieces, joints, hits), per cut the nearest beat and downbeat
    and their distance, the model, licence, every setting used, timings and GPU use. Every file is named
    'generated-music-...' with metadata (title 'Generated music: ...', comment 'generated by letitedit - not camera
    footage; ...', letitedit_ai_generated=1) and a sidecar <file>.json.
    """
    import letitedit.sound.av_tools as av_tools
    import letitedit.footage.perception as perception
    t0 = time.monotonic()
    description = ' '.join(str(description or '').split())
    if not description:
        raise ValueError('description is empty')
    if len(description) > 512:
        raise ValueError(f'description is {len(description)} characters; the model reads up to 512')
    proj = _project_info(project) if project else None
    if cuts == 'project':
        if not proj:
            raise ValueError("cuts='project' needs project=")
        cuts = proj['v1_cuts_s']
    cuts = [float(c) for c in (cuts or [])]
    cuts_on = (cuts_on or DEFAULTS['cuts_on']).lower()
    if cuts_on not in ('downbeat', 'beat', 'section', 'none'):
        raise ValueError("cuts_on: 'downbeat', 'beat', 'section' or 'none'")
    hits = [list(h) for h in (hits or [])]
    # a hard hit on a picture cut lands half a frame early so it reads as on the cut [AOTC Dune]
    early = 0.5 / float(proj['fps']) if proj and proj.get('fps') else 0.5 / 30.0
    if cuts and cuts_on != 'none':
        hits += [[round(c - early, 4), cuts_on] for c in cuts]
    length_given = length is not None
    length = float(length) if length is not None else (proj['length_s'] if proj else DEFAULTS['length'])
    fit = (length_given or bool(proj) or bool(hits)) if fit is None else bool(fit)
    steps = int(DEFAULTS['steps'] if steps is None else steps)
    shift = float(DEFAULTS['shift'] if shift is None else shift)
    extra = float(DEFAULTS['extra_s'] if extra_s is None else extra_s)
    peak = float(DEFAULTS['peak_db'] if peak_db is None else peak_db)
    seed = random.randrange(2**31) if seed is None else int(seed)
    if bpm is not None and not 30 <= float(bpm) <= 300:
        raise ValueError('bpm: 30-300')
    if time_signature is not None and str(time_signature).split('/')[0] not in ('2', '3', '4', '6'):
        raise ValueError('time_signature: 2, 3, 4 or 6')
    ts = str(time_signature).split('/')[0] if time_signature is not None else ''
    gen_s = min(DEFAULTS['max_s'], max(DEFAULTS['min_s'], (length + extra) if fit else length))

    folder = Path(proj['project']).parent / 'made' if proj else CACHE
    folder.mkdir(parents=True, exist_ok=True)
    spec = {'caption': description, 'duration': round(gen_s, 3), 'bpm': bpm, 'key': key or '', 'time_signature': ts,
            'seed': seed, 'steps': steps, 'shift': shift, 'peak_db': peak}
    h = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]
    raw = CACHE / 'takes' / f'generated-music-{_slug(description)}-{seed}-{h}.wav'
    raw.parent.mkdir(parents=True, exist_ok=True)
    cached, gen, raw = _generate_take(spec, description, seed, gen_s, fit, raw)
    t_gen = time.monotonic()
    take = perception.music(str(raw))

    fit_rep = None
    if fit:
        name = Path(out).name if out else f'generated-music-{_slug(description)}-{seed}-{_r(length, 2):g}s.wav'
        dst = Path(out) if out else folder / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp_fit = dst.with_name(dst.stem + '.fit.wav')
        take_s = float((spec or {}).get('duration') or length)
        # a take shorter than the length asked for repeats its middle (on bars) until it is long enough
        loop = [min(8.0, take_s * 0.15), take_s * 0.85] if length > take_s + 1 else None
        fit_rep = av_tools.fit_music(str(raw), length=length, hits=hits or None, out=str(tmp_fit), land=land,
                                     crossfade_s=crossfade_s, stretch_max=stretch_max, tolerance_s=tolerance_s,
                                     snap=snap, fade_in=fade_in, fade_out=fade_out, loop=loop)
        _tag(tmp_fit, dst, description[:120], f'ACE-Step 1.5 turbo, seed {seed}, fitted to {length:g} s on its beats')
        tmp_fit.unlink(missing_ok=True)
        fit_rep['file'] = str(dst)
        grid = fit_rep['grid']
        beats, downs, secs = grid['beats'], grid['downbeats'], grid['sections']
        final = dst
        final_len = fit_rep['length_s']
    else:
        if out:
            final = Path(out)
            final.parent.mkdir(parents=True, exist_ok=True)
            _tag(raw, final, description[:120], f'ACE-Step 1.5 turbo, seed {seed}; {description}')
        else:
            final = raw
        beats, downs = take.get('beat_times') or [], take.get('downbeats') or []
        secs = [[_r(s[0]), s[2]] for s in take.get('sections') or []]
        final_len = take.get('duration')

    alignment = _cut_alignment(cuts, proj, beats, downs)
    result = {
        'file': str(final), 'raw_file': str(raw), 'length_s': _r(final_len), 'raw_length_s': _r(take.get('duration')),
        'bpm_asked': bpm, 'bpm': take.get('bpm'), 'pulse': take.get('pulse'),
        'beats': [_r(t) for t in beats], 'downbeats': [_r(t) for t in downs], 'sections': secs,
        'raw_sections': [[_r(s[0]), _r(s[1]), s[2]] for s in take.get('sections') or []],
        'fit': None if fit_rep is None else {k: fit_rep[k] for k in ('length_s', 'settings', 'pieces', 'joints',
                                                                     'hits', 'music_ends_s', 'peak', 'snapped')},
        'alignment': alignment, 'project': proj, 'description': description,
        'settings': {'length': length, 'bpm': bpm, 'key': key, 'time_signature': ts or None, 'seed': seed,
                     'steps': steps, 'shift': shift, 'extra_s': extra, 'generated_s': round(gen_s, 3),
                     'peak_db': peak, 'fit': fit, 'cuts_on': cuts_on, 'cut_hits_early_s': round(early, 4),
                     'instrumental': True, 'lm': False},
        'model': MODEL, 'licence': LICENCE, 'sample_rate': (gen or {}).get('sample_rate'), 'cached': cached,
        'timings': {'generate_s': None if cached else (gen or {}).get('run_s'),
                    'model_load_s': None if cached else (gen or {}).get('load_s'),
                    'analyse_and_fit_s': round(time.monotonic() - t_gen, 2),
                    'took_s': round(time.monotonic() - t0, 2)},
        'gpu_peak_mb': (gen or {}).get('gpu_peak_mb'), 'gpu': None if cached else (gen or {}).get('gpu'),
        'generated': True,
    }
    if final != raw:
        Path(str(final) + '.json').write_text(json.dumps({'generated': True, 'kind': 'music', 'spec': spec,
                                                          'model': MODEL, 'licence': LICENCE,
                                                          'result': {k: v for k, v in result.items()
                                                                     if k not in ('beats',)}},
                                                         indent=1, default=str), encoding='utf-8')
    return result


def _main(argv):
    if len(argv) < 2 or argv[1] not in ('make', 'release'):
        print('usage: python music_gen.py make|release \'{"description": "...", ...}\'', file=sys.stderr)
        return 2
    args = json.loads(argv[2]) if len(argv) > 2 and argv[2].strip() else {}
    print(json.dumps(globals()[argv[1]](**args), indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv))
