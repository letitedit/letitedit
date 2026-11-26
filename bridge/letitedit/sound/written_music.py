"""Music written as a score and performed in code (T73): the tool letitedit_music_write around written-music\\written-music.mjs.

No model, no GPU, no download, no network, no sign-up: the AI writes every note as JSON, the bundled engine (based on
anidoodle, Apache-2.0: written-music\\README.md) performs, mixes and masters it on the CPU, the same every time.

    grid(project=..., anchors=[...])    bar lines that fall on chosen moments, and what is said in each bar
    write(score, project=...)           the file at the film's exact length, with every check
    register(mcp, Image)                adds the tool to an MCP server
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
BUNDLE = HERE.parent / 'written-music' / 'written-music.mjs'
CACHE = Path(os.environ.get('LETITEDIT_ROOT') or HERE.parent) / 'cache' / 'written_music'
LICENCE = ('Written for this video on this PC: nothing recorded, no sample pack, nothing owed per video. Engine: based on '
           'anidoodle by Alex Greenshpun, Apache-2.0 (THIRD-PARTY-NOTICES.md).')
BEATS_PER_BAR = {'2/4': 2, '3/4': 3, '4/4': 4, '5/4': 5, '6/8': 2, '7/8': 3.5, '9/8': 3, '12/8': 4}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BELOW_NORMAL = getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
MAX_BARS_SHOWN = 80
FIX = {     # the engine's own words for each check that can fail
    'masking': 'The melody beats every other part in 500 Hz-4 kHz by 3 dB in 80 % of its bars. Options: raise levels.lead (lead_headroom_db over its target is allowed), thin or lower what sits in its register, or move it. This outranks stems.',
    'stems': 'A part is over the tolerance from its target: change levels.<slot> by the off value in stems.rows.',
    'ghost': 'Sustained sound with too few onsets and no cadence: a rhythmic layer or motif, shorter tails, a cadence.',
    'reverb': 'The late tail sits too close to the dry sound: lower sends (voices) or moodControls.space.',
    'key': "The notes don't support the declared key: the bass on the tonic at section starts and cadences, the mode's colour note stated, or declare the key you wrote.",
    'craft': 'A note is outside what its instrument can play: see craft.findings.',
    'novelty': "Too close to one of the engine's own pieces, or a quoted melody: change the lead's rhythm and contour, the groove, the form. Changing the key doesn't count.",
    'tones': "A narrow, pure tone held 2 s or more, whistle- or howl-like (tones: when and at what pitch), measured as the export's pre-check measures the music a cut uses, where it counts as a major finding. Options: another voice for the part that holds it (the style's alternates), shorter held notes, or keep it when the Look or the person wants that sound.",
}


def _threads():
    """Up to 4 threads (the PC rule); one while another job holds the PC lock, so a render or a build keeps its share."""
    env = os.environ.get('LETITEDIT_MUSIC_THREADS')
    if env:
        return max(1, int(env))
    try:
        import letitedit.core.render_lock as render_lock
        if render_lock.info().get('held'):
            return 1
    except Exception:  # noqa: BLE001 - the lock file can't be read: one thread is always safe
        return 1
    return max(1, min(4, (os.cpu_count() or 2) - 1))


def _node(*args, timeout=1800):
    import letitedit.pictures.motion as motion
    if not BUNDLE.is_file():
        raise FileNotFoundError(f'{BUNDLE} is missing (written-music\\build.mjs makes it)')
    p = subprocess.run([motion.node_exe(), str(BUNDLE), *[str(a) for a in args]], capture_output=True, encoding='utf-8',
                       errors='replace', timeout=timeout, creationflags=NO_WINDOW | BELOW_NORMAL)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _node_json(*args, timeout=1800):
    code, out, err = _node(*args, timeout=timeout)
    try:
        res = json.loads(out)
    except ValueError:
        raise RuntimeError(f'the music engine stopped (exit {code}): {(err or out)[-600:]}') from None
    if 'error' in res:
        raise ValueError(res['error'])
    return res


def _slug(text, n=32):
    return re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:n].rstrip('-') or 'score'


def _project_info(project):
    import letitedit.timeline.timeline_model as timeline_model
    tl = timeline_model.load(project)
    return {'project': str(Path(project).resolve()), 'length_s': round(tl.seconds, 3), 'fps': tl.fps,
            'v1_cuts_s': [round(f / tl.fps, 3) for f in tl.cut_points()]}


def _words(project):
    """(words said on the timeline {'w', 't0', 't1'}, how many files have no transcript yet). No transcription starts."""
    import letitedit.pictures.caption_layout as caption_layout
    import letitedit.timeline.edit_script as es
    words, missing = caption_layout.cached_timeline_words(es.read(project))
    return words, len(missing)


# ---------------------------------------------------------------- a score, whole or as changes to an earlier one

def _apply_changes(score, changes):
    """changes: [{path: 'sections.7.lead', value: ...}, ...]; no value (or null) removes that key or list item."""
    out = copy.deepcopy(score)
    if not isinstance(changes, list):
        raise ValueError("changes: a list of {path: 'levels.lead', value: 2}")
    done = []
    for c in changes:
        if not isinstance(c, dict) or not c.get('path'):
            raise ValueError("each change: {path: 'levels.lead', value: 2} (no value removes it)")
        keys = str(c['path']).split('.')
        at = out
        for i, k in enumerate(keys[:-1]):
            if isinstance(at, list):
                if not k.isdigit() or int(k) >= len(at):
                    raise ValueError(f"{c['path']}: no item {k} at {'.'.join(keys[:i]) or 'the top'} (it has {len(at)})")
                at = at[int(k)]
            else:
                if k not in at:
                    at[k] = {}
                at = at[k]
        last, value = keys[-1], c.get('value')
        if isinstance(at, list):
            if not last.isdigit() or int(last) > len(at):
                raise ValueError(f"{c['path']}: the list has {len(at)} items")
            if value is None:
                del at[int(last)]
            elif int(last) == len(at):
                at.append(value)
            else:
                at[int(last)] = value
        elif value is None:
            at.pop(last, None)
        else:
            at[last] = value
        done.append(c['path'])
    return out, done


def _load_score(score):
    if isinstance(score, dict):
        return score
    if not isinstance(score, str) or not score.strip():
        raise ValueError('score: the score as JSON, or the path of a .json file')
    text = score.strip()
    if text.startswith('{'):
        try:
            return json.loads(text)
        except ValueError as e:
            raise ValueError(f'the score is not valid JSON: {e}') from None
    p = Path(text)
    if not p.is_file():
        raise FileNotFoundError(f'no score file {p}')
    return json.loads(p.read_text(encoding='utf-8-sig'))


def _folder(proj, out):
    if out:
        return Path(out).parent
    return Path(proj['project']).parent / 'made' if proj else CACHE


def _last_score(folder):
    found = sorted(folder.glob('written-music-*.score.json'), key=lambda p: p.stat().st_mtime) if folder.is_dir() else []
    if not found:
        raise FileNotFoundError(f'no earlier written score in {folder}')
    return found[-1]


def _resolve(score, base, changes, folder):
    """The score to play, and what changed against its base: ({...}, {'from', 'paths'} or None, the base's score)."""
    if base is not None and score is not None:
        raise ValueError('score or base, not both')
    if base is None and score is None:
        raise ValueError('score: the score as JSON or a .json path (or base and changes for a revision)')
    if base is not None:
        path = _last_score(folder) if str(base) == 'last' else Path(base)
        before = _load_score(str(path))
        now, paths = _apply_changes(before, changes or [])
        return now, {'from': str(path), 'paths': paths}, before
    now = _load_score(score)
    if changes:
        now, _ = _apply_changes(now, changes)
    return now, None, None


def _temp_score(score):
    fd, path = tempfile.mkstemp(prefix='written-music-', suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(score, f)
    return path


def _parts(score):
    path = _temp_score(score)
    try:
        return _node_json('craft', path, timeout=120)['parts']
    finally:
        os.unlink(path)


# ---------------------------------------------------------------- facts about the cut

def _lead_over_words(notes, words, start):
    """Which lead notes sound while a word is said (over 30 ms)."""
    hits = []
    for a, b in notes:
        a, b = a + start, max(b, a) + start
        for w in words:
            if min(b, w['t1']) - max(a, w['t0']) > 0.03:
                hits.append({'at_s': round(a, 2), 'word': w['w']})
                break
    return {'lead_notes': len(notes), 'over_words': len(hits), 'share': round(len(hits) / len(notes), 2) if notes else 0,
            'first': hits[:10]}


def _anchor_list(anchors):
    """[(seconds, what or None)] from anchors given as seconds, or as {at (or at_s), what} for a named moment."""
    out = []
    for a in anchors or []:
        if isinstance(a, dict):
            at = a.get('at', a.get('at_s'))
            if at is None:
                raise ValueError(f'an anchor needs its time: {{at: seconds, what?}} or seconds (got {a})')
            out.append((float(at), str(a['what']) if a.get('what') else None))
        else:
            out.append((float(a), None))
    return out


def _named(row, what):
    return {**row, 'what': what} if what else row


def _anchors_off(anchors, bars, start):
    """Each chosen moment against the nearest bar line as the performance plays it."""
    out = []
    lines = [b['at_s'] + start for b in bars]
    for t, what in _anchor_list(anchors):
        if lines:
            near = min(range(len(lines)), key=lambda i: abs(lines[i] - t))
            out.append(_named({'at_s': round(t, 3), 'bar': bars[near]['bar'], 'off_s': round(lines[near] - t, 3)}, what))
    return out


def grid(project=None, length=None, meter='4/4', bpm=None, bpm_range=None, anchors=None, start=0.0, window=None):
    """Tempos whose bar lines fall on chosen moments, then per bar what is said and which beats are free of words."""
    if meter not in BEATS_PER_BAR:
        raise ValueError(f"meter: one of {', '.join(BEATS_PER_BAR)}")
    proj = _project_info(project) if project else None
    start = float(start or 0)
    if length is None and not proj:
        raise ValueError('grid needs project or length')
    length = float(length) if length is not None else proj['length_s'] - start
    named = sorted(_anchor_list(anchors), key=lambda a: a[0])
    anchors = [t for t, _ in named]
    names = {t: what for t, what in named if what}
    bpb = BEATS_PER_BAR[meter]
    words, missing = _words(project) if project else ([], 0)

    def errors(tempo):
        bar = bpb * 60.0 / tempo
        return [((t - start) / bar, t, bar) for t in anchors]

    lo, hi = (float(bpm), float(bpm)) if bpm else (bpm_range or (60.0, 130.0))
    tried = []
    t = float(lo)
    while t <= float(hi) + 1e-9:
        errs = [abs(round(x) - x) * bar for x, _, bar in errors(t)]
        tried.append((max(errs) if errs else 0.0, round(t, 1)))
        t += 0.1
    tried.sort()
    picks = []
    for e, tempo in tried:
        if all(abs(tempo - p[1]) >= 3 for p in picks):
            picks.append((e, tempo))
        if len(picks) == 4 or bpm:
            break
    chosen = float(bpm) if bpm else picks[0][1]
    candidates = []
    for e, tempo in picks:
        bar = bpb * 60.0 / tempo
        candidates.append({'bpm': tempo, 'bar_s': round(bar, 3), 'bars': int(length / bar + 0.999), 'worst_off_s': round(e, 3),
                           'anchors': [_named({'at_s': a, 'bar': int(round(x)) + 1, 'off_s': round((round(x) - x) * b, 3)},
                                              names.get(a)) for x, a, b in errors(tempo)]})
    bar = bpb * 60.0 / chosen
    beat = 60.0 / chosen
    total = int(length / bar + 0.999)
    a, b = window or (start, start + length)
    rows, shown = [], 0
    for i in range(total):
        t0 = start + i * bar
        t1 = t0 + bar
        if t1 <= float(a) or t0 >= float(b):
            continue
        if shown >= MAX_BARS_SHOWN:
            break
        shown += 1
        inside = [w for w in words if w['t1'] > t0 and w['t0'] < t1]
        free, at = [], 0.0
        for w in inside:
            x, y = (max(w['t0'], t0) - t0) / beat, (min(w['t1'], t1) - t0) / beat
            if x - at >= 0.25:
                free.append([round(at, 2), round(x, 2)])
            at = max(at, y)
        if bpb - at >= 0.25:
            free.append([round(at, 2), bpb])
        row = {'bar': i + 1, 'at_s': round(t0, 2), 'free_beats': free}
        if inside:
            row['says'] = ' '.join(w['w'] for w in inside)
        cuts = [c for c in (proj['v1_cuts_s'] if proj else []) if t0 <= c < t1]
        if cuts:
            row['cuts_beat'] = [round((c - t0) / beat, 2) for c in cuts]
        rows.append(row)
    res = {'meter': meter, 'length_s': round(length, 3), 'start_s': start, 'chosen_bpm': chosen, 'candidates': candidates,
           'bars': rows, 'bars_total': total}
    if shown < total and not window:
        res['note'] = f'{shown} of {total} bars listed; window=[from_s, to_s] lists others'
    if missing:
        res['no_transcript'] = f'{missing} file(s) on the timeline have no transcript yet (letitedit_words makes them)'
    return res


# ---------------------------------------------------------------- the file

def _tag(src, dst, title):
    import letitedit.pictures.gen_common as gen_common
    tmp = Path(dst).with_name(Path(dst).stem + '.tmp.wav')
    subprocess.run([gen_common.ffmpeg(), '-v', 'error', '-y', '-i', str(src), '-map_metadata', '-1', '-c:a', 'copy',
                    *gen_common.meta_args('music', title, 'written as a score and performed in code'), str(tmp)],
                   check=True, creationflags=NO_WINDOW | BELOW_NORMAL)
    os.replace(tmp, dst)


def _tones(path):
    """The export pre-check's narrow-tone measure (tonal_check) on a written file: flagged (a strong tone held LONG_S or
    more, a whistle: it fails the music's check), the longest, the strong tones (when and at what pitch; shorter ones
    are reported, not counted) and the pre-check's line."""
    try:
        import letitedit.sound.tonal_check as tonal_check
        r = tonal_check.scan_file(str(path))
        strong = tonal_check.strong(r)
        longest = max((e['end_s'] - e['start_s'] for e in strong), default=0.0)
        return {'flagged': tonal_check.flagged(r), 'longest_s': round(longest, 2),
                'seconds': round(sum(e['end_s'] - e['start_s'] for e in strong), 2),
                'events': [{k: e[k] for k in ('start_s', 'end_s', 'hz') if k in e} for e in strong[:8]],
                **({'line': tonal_check.summary_line(r, 'the written music')} if strong else {})}
    except Exception as exc:  # noqa: BLE001 - a measure that can't run doesn't fail the music
        return {'flagged': False, 'error': f'{type(exc).__name__}: {exc}'[:200]}


def write(score=None, base=None, changes=None, project=None, length=None, start=0.0, payoff=None, anchors=None, fit=False,
          end_fade=None, out=None, keep_file=True):
    """Play a score: check it and write the file. The same score at the same length comes back from the cache."""
    t0 = time.monotonic()
    proj = _project_info(project) if project else None
    start = float(start or 0)
    folder = _folder(proj, out)
    folder.mkdir(parents=True, exist_ok=True)
    now, revision, before = _resolve(score, base, changes, folder)
    seconds = float(length) if length is not None else (round(proj['length_s'] - start, 3) if proj else None)
    if seconds is not None and seconds <= 0:
        raise ValueError(f'length: {seconds:g} s')
    fade = 1.0 if end_fade is None else float(end_fade)
    key = hashlib.sha256(json.dumps({'score': now, 'seconds': seconds, 'payoff': payoff, 'fit': bool(fit), 'fade': fade,
                                     'engine': hashlib.sha256(BUNDLE.read_bytes()).hexdigest() if BUNDLE.is_file() else ''},
                                    sort_keys=True).encode()).hexdigest()[:10]
    dst = Path(out) if out else folder / f"written-music-{_slug(now.get('title', ''))}-{key}.wav"
    side = dst.with_name(dst.stem + '.report.json')
    rep = json.loads(side.read_text(encoding='utf-8-sig')) if dst.is_file() and side.is_file() else None
    cached = bool(rep) and rep.get('key') == key      # the same path with another score or length is played again
    if not cached:
        path = _temp_score(now)
        raw = dst.with_name(dst.stem + '.engine.wav')
        try:
            args = ['report', path, '--threads', _threads(), '--end-fade', fade, '--out', raw]
            if seconds is not None:
                args += ['--seconds', seconds]
            if payoff is not None:
                args += ['--payoff', float(payoff)]
            if fit:
                args += ['--fit']
            rep = _node_json(*args)
            _tag(raw, dst, str(now.get('title') or 'written score')[:120])
        finally:
            os.unlink(path)
            raw.unlink(missing_ok=True)
        side.write_text(json.dumps({**rep, 'key': key}), encoding='utf-8')
    if dst.is_file() and 'tones' not in rep:     # measured once per file, kept in its report beside it
        rep['tones'] = _tones(dst)
        side.write_text(json.dumps({**rep, 'key': key}), encoding='utf-8')
    if (rep.get('tones') or {}).get('flagged'):
        rep['pass'] = False
        rep['failed'] = [k for k in rep.get('failed') or [] if k != 'tones'] + ['tones']
    score_file = dst.with_name(dst.stem + '.score.json')
    score_file.write_text(json.dumps(now, indent=1), encoding='utf-8')
    rep.pop('key', None)
    notes = rep.pop('lead_notes', [])
    res = {**rep, 'cached': cached, 'wall_s': round(time.monotonic() - t0, 1), 'score_file': str(score_file), 'licence': LICENCE}
    if keep_file:
        res['file'] = str(dst)
        if rep.get('pass'):
            res['place'] = {'op': 'insert', 'track': 'Music', 'at': start, 'item': {'clip': str(dst)}}
    if rep.get('failed'):
        res['fix'] = {k: FIX[k] for k in rep['failed'] if k in FIX}
    if anchors:
        res['anchors'] = _anchors_off(anchors, rep.get('bars', []), start)
    if project:
        words, missing = _words(project)
        res['melody_vs_words'] = _lead_over_words(notes, words, start)
        if missing:
            res['melody_vs_words']['no_transcript'] = missing
    if revision:
        was = _parts(before)
        res['revision'] = {**revision,
                           'parts_same': [k for k, v in rep['parts'].items() if was.get(k) == v],
                           'parts_changed': [k for k, v in rep['parts'].items() if was.get(k) != v] + [k for k in was if k not in rep['parts']]}
    res.pop('parts', None)
    return res


def vocab(style=None):
    code, text, err = _node('vocab', *([style] if style else []), timeout=60)
    if code:
        try:
            raise ValueError(json.loads(text)['error'])
        except (ValueError, KeyError) as e:
            raise ValueError(str(e) or err) from None
    return text


def craft(score=None, base=None, changes=None):
    now, _, _ = _resolve(score, base, changes, CACHE)
    path = _temp_score(now)
    try:
        res = _node_json('craft', path, timeout=120)
    finally:
        os.unlink(path)
    res.pop('parts', None)
    return res


DOC = """Music written note by note as a score (JSON) and performed, mixed and mastered in code on this PC: no model, GPU, download, network or sign-up, and the same score always gives the same audio. Based on anidoodle (Apache-2.0).

mode:
- 'vocab': the 21 styles with their moods, tempos, meters and grooves, and the section kinds; with style=<id>, that style's voices and alternates, stem targets, harmony, melody and arrangement language.
- 'grid': tempos whose bar lines fall on chosen moments. project (or length), meter (default 4/4), anchors [seconds on the timeline], bpm_range [lo, hi] or bpm, start (where the music will start on the timeline), window [from_s, to_s]. Returns candidates (bpm, bar length, how far each anchor is from a bar line) and, per bar of the chosen tempo, the time, what is said (cached transcripts), the beats free of words and the beats of picture cuts.
- 'craft': how the notes are written, read in about a second with no audio: scores, findings with fixes, tension per bar.
- 'check': everything below without returning the file.
- 'render' (default): the file and everything below.

score: the score as JSON or the path of a .json file. For a revision instead: base (a score_file from an earlier reply, or 'last': the newest in this project) and changes [{path: 'levels.lead', value: -2}, {path: 'sections.3.lead', value: ['m1', 'rest']}, {path: 'motifs.m4', value: '...'}] (no value removes that key or list item).
A score: {style, title, seed, mood, bpm, key, mode, meter, moodControls: {energy, warmth, brightness, tension, space} (each 0-1), swing, dyn: [start, end], tail, voices: {slot: alternate name or {inst, role, gainDb}}, levels: {slot: dB}, chords: {name: {voicing: '[C3 G3 E4]' or 'r', bass: 'one bar'}}, motifs: {name: 'notation'}, grooves: {name: {family, density, variation, fill}, or written lanes}, sections: [{kind, bars, harmony: [chord per bar; 'A B' splits a bar, '~' holds], lead, counter, arp: motif names or notation, comp, bass, groove, chordVel, energy, loopLines, repeat, stretch, key, mode}]}. Every field but title's meaning is the engine's: missing harmony, grooves or form is an error that says what to write.
Notation: NOTE:BEATS[@VEL] ('F#4:1.5@0.7'), [NOTE NOTE]:BEATS, r:BEATS; bars separated by '|'; each bar must add up to the meter. Lines play once from the section's first bar unless loopLines.

project: a .mlt: its length minus start is the length, the file goes to <project folder>\\made, and the reply says which lead notes sound over words. length: seconds (a render with no length and no project ends at the last note plus tail). start: where the music will sit on the timeline (default 0). payoff: the second of the piece the picture pays off. anchors: [timeline seconds]: each one's distance from the nearest bar line as performed. fit: repeat or drop the score's stretch section, or change its tempo, to reach the length. end_fade: seconds of fade on what rings after the last note (default 1; 0 = only the engine's 0.25 s). out: the output .wav.

Returns: pass, failed (key, ghost, reverb, masking, stems, craft, novelty, tones), master (mode, lufs, true peak; the engine masters to -14 or -16 LUFS whatever the level under a voice will be), guards, stems (each part against its target), craft, arc (loudest moment, range, opening, ending), novelty (similarity to the engine's own pieces), bars (each bar's time as performed, level and section), first_bar_vs_median_db, lift (with payoff: that bar's level over the two bars before it), end (last note, fade, notes past the end, silence after), tones (narrow, pure, whistle- or howl-like tones in the file, measured as the export's pre-check measures the music a cut uses: flagged (one held 2 s or more; fails the check), longest_s, seconds, when and at what pitch; shorter ones are reported, not counted), sound (centroid_hz, speech_band_db: the share of the music's energy in 300-3400 Hz), melody_vs_words, anchors, revision (with base: the changed paths, parts_same: note for note, parts_changed), wall_s, score_file, licence, file, place (an insert for timeline_apply, when the check passes), fix (when it fails: what each failed check measures and the options). A score and length already played come back at once (cached: true). A failed check still writes the file. Runs at below-normal priority on up to 4 threads, one while the PC lock is held."""


def register(mcp, Image):
    def letitedit_music_write(mode: str = 'render', score: dict | str | None = None, base: str | None = None,
                              changes: list | None = None, project: str | None = None, length: float | None = None,
                              start: float | None = None, payoff: float | None = None, anchors: list | None = None,
                              fit: bool | None = None, end_fade: float | None = None, out: str | None = None,
                              style: str | None = None, meter: str | None = None, bpm: float | None = None,
                              bpm_range: list | None = None, window: list | None = None) -> dict:
        try:
            if mode == 'vocab':
                return {'vocab': vocab(style)}
            if mode == 'grid':
                return grid(project=project, length=length, meter=meter or '4/4', bpm=bpm, bpm_range=bpm_range, anchors=anchors,
                            start=start or 0.0, window=window)
            if mode == 'craft':
                return craft(score=score, base=base, changes=changes)
            if mode in ('render', 'check'):
                return write(score=score, base=base, changes=changes, project=project, length=length, start=start or 0.0,
                             payoff=payoff, anchors=anchors, fit=bool(fit), end_fade=end_fade, out=out,
                             keep_file=mode == 'render')
            return {'error': f"mode: vocab, grid, craft, check or render, not {mode!r}"}
        except (FileNotFoundError, ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as e:
            return {'error': f'{type(e).__name__}: {e}'}
    letitedit_music_write.__doc__ = DOC
    mcp.tool()(letitedit_music_write)
