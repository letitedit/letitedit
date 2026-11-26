"""Everything a reviewer needs to judge one export, covering the whole video, and one delivery verdict.

bundle(video, kind=None, project=None, brief=None, out=None, critic=None, engine=None) writes, in out:
  pages/page-01.jpg ...  every sampled frame of the WHOLE video, labelled with its time (1 per s up to 3 min,
                         1 per 2 s up to 15 min, 1 per 4 s beyond)
  details.jpg            larger frames at the start, middle and end and at every risk point (caption changes, flagged
                         ranges, the critic's timecodes)
  strips/*.jpg           motion strips, 6 frames a second: the first and last 3 s and up to three flagged moments
  excerpts/*.mp4         the first and the last 8 s, for a reviewer (or a person) who can watch and listen
  transcript.srt         the render's own transcript, complete
  audio.png              the level over the whole video, silences shaded
  checks.json, report.md the gate's measurements (letitedit-gate), judged for the brief's mode, driver, deliverable
                         and platforms (gate_context); pace checks are advisory unless the brief or a reference sets
                         the tempo (the brief's `pace` limits, a local `reference` video)
  review_bundle.json     all of it: findings with times and severity, the brief check, the coverage record, verdict
  review.md              the same for people
The critic also gets the story plan (story_plan.json next to the project or the brief, or in the bundle folder).
Each finding says who can fix it ('owner': 'ai' or 'person', review_memory.who_fixes) and how ('fix'). Only the AI's findings set the
verdict; the person's go on the 'for_you' list. review_memory.json in the video's side folder keeps what earlier rounds found and how
many full rounds there have been: critic='run' past ROUND_LIMIT reuses the last review, critic='again' runs one more.
Verdict: 'blocked' (a critical problem), 'revise' (a major one), 'ready' (neither, and the editorial review was done),
'incomplete' (neither found, but a needed check was not done: no editorial review, a failed checker, a stale export, the
speech the review couldn't hear). A critical or major problem sets the verdict even when a check was not done;
'not_checked' names every required check that wasn't, whatever the verdict, and the verdict is never 'ready' with one.
A gate check's finding severity comes from its own severity (gate_severity): advisory -> minor, blocking -> major.
Technical checks passing never means the video is good; the editorial review is a separate, required line.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import letitedit.app.ai_clis as ai_clis
import letitedit.review.review_memory as review_memory
import letitedit.review.review_order as review_order
import datetime
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.environ.get('LETITEDIT_ROOT', _paths.CODE_ROOT))
# the gate and the critic are this code's own scripts, from its own tree (as letitedit_quality_gate and
# letitedit_critic run them); their programs and models still come from LETITEDIT_ROOT, which they read themselves.
# In an install the two are one folder.
GATE = _paths.CODE_ROOT / 'skills' / 'letitedit-gate' / 'scripts' / 'gate.py'
CRITIC = _paths.CODE_ROOT / 'skills' / 'letitedit-review' / 'scripts' / 'critic.py'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
SEVERITIES = ('critical', 'major', 'minor')


def _gate():
    spec = importlib.util.spec_from_file_location('letitedit_gate', GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CRITIC_TIMEOUT = 3900    # two AIs' tries at 30 minutes each (critic.ASK_TIMEOUT), plus its own preparation
NOBODY_COULD = ('no_ai', 'signed_out', 'limit', 'background_off', 'missing')    # the review wasn't done, rather than failed


def _run(args, timeout=1800, heavy=False, **kw):
    """Run a program. heavy (a pass over the export: its frames, sound, words or the gate's measurements) holds the PC
    render lock, one at a time in this process, on the export's thread cap at below-normal priority
    (render_lock.run_render); the critic, an AI's conversation, does not."""
    import letitedit.core.render_lock as render_lock
    return render_lock.run_render([str(a) for a in args], what=f'review bundle: {Path(str(args[0])).stem}',
                                  heavy=heavy, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                  creationflags=NO_WINDOW, timeout=timeout, **kw)


def fmt(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:04.1f}'


def sample_every(duration):
    return 1.0 if duration <= 180 else 2.0 if duration <= 900 else 4.0


# ---------------------------------------------------------------- pictures

def _font(px):
    from PIL import ImageFont
    for name in ('seguisb.ttf', 'segoeui.ttf', 'arial.ttf'):
        p = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
        if p.exists():
            return ImageFont.truetype(str(p), px)
    return ImageFont.load_default()


def _label(img, text, px=15):
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    f = _font(px)
    box = d.textbbox((0, 0), text, font=f)
    d.rectangle([0, 0, box[2] - box[0] + 10, box[3] - box[1] + 8], fill=(0, 0, 0))
    d.text((5, 3 - box[1]), text, font=f, fill=(255, 230, 0))
    return img


def sample_frames(ffmpeg, video, every_s, width, folder):
    """[(t, path)] one frame every every_s seconds over the whole video, width px wide."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('f_*.jpg'):
        old.unlink()
    _run([ffmpeg, '-v', 'error', '-y', '-i', video, '-vf', f'fps=1/{every_s},scale={width}:-2', '-q:v', '4',
          str(folder / 'f_%05d.jpg')], heavy=True)
    files = sorted(folder.glob('f_*.jpg'))
    return [(i * every_s, p) for i, p in enumerate(files)]


def pages(frames, folder, portrait):
    """Contact pages of the labelled frames, in time order: 7 x 6 tiles (wide video) or 11 x 3 (tall)."""
    from PIL import Image
    cols, rows = (11, 3) if portrait else (7, 6)
    out = []
    per = cols * rows
    for n in range(0, len(frames), per):
        chunk = frames[n:n + per]
        tiles = [_label(Image.open(p).convert('RGB'), fmt(t)) for t, p in chunk]
        tw, th = tiles[0].size
        sheet = Image.new('RGB', (cols * (tw + 4) + 4, math.ceil(len(tiles) / cols) * (th + 4) + 4), (255, 255, 255))
        for i, tile in enumerate(tiles):
            sheet.paste(tile, (4 + (i % cols) * (tw + 4), 4 + (i // cols) * (th + 4)))
        path = folder / f'page-{len(out) + 1:02d}.jpg'
        sheet.save(path, quality=85)
        out.append({'file': str(path), 'from_s': round(chunk[0][0], 2), 'to_s': round(chunk[-1][0], 2)})
    return out


def saved_summary(path, result):
    """A check's whole result saved as a file beside the review, and the line review.md shows for it: passed or not, how
    many findings and the first few, and the file. (Written into review.md whole, two of these made it 6 MB.)"""
    try:
        Path(path).write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    except (OSError, TypeError, ValueError):
        pass
    result = result if isinstance(result, dict) else {}
    found = [f for f in result.get('findings') or [] if isinstance(f, dict)
             and f.get('severity') not in ('receipt', 'note')]     # the record and what wasn't checked are no faults
    first = '; '.join(str(f.get('problem') or f.get('what') or '')[:120] for f in found[:3])
    state = 'passed' if result.get('passed') else ('not applicable' if result.get('applicable') is False else 'not passed')
    return (f"{state}, {len(found)} finding(s)" + (f": {first}" + (' ...' if len(found) > 3 else '') if first else '')
            + f" (all of it: {Path(path).name})")


REPLY_FINDINGS = 25         # findings written out in the tool's reply; the rest are in review.md
# T363's cut 3: a run whose review rounds take a session each (the session runner sets this in its tool server's
# environment, letitedit.app.substeps' review_round_sessions): after a critic round that leaves rounds, the reply says
# the round's conversation ends here
ROUND_SESSIONS_ENV = 'LETITEDIT_RUN_ROUND_SESSIONS'
ROUND_SESSION_LINE = ("This run gives each review round its own conversation: end your turn now with your note for "
                      "what comes next (what you changed, what didn't work, where things are). letitedit starts the "
                      'next round, or the final look, in a fresh conversation from these findings and that note.')
REPLY_TEXT = 260            # characters of one finding's problem and fix in the reply


def _reply_line(f):
    what = ' '.join(str(f.get('what') or '').split())
    fix = ' '.join(str(f.get('fix') or '').split())
    text = what + (f' | fix: {fix}' if fix else '')
    if len(text) > REPLY_TEXT:
        text = text[:REPLY_TEXT - 3] + '...'
    return f"{f.get('at') or '-'} {f.get('severity')} [{f.get('source')}{' ' + f['id'] if f.get('id') else ''}] {text}"


def _open_list(found):
    """'2 critical or major findings (r3 at 0:09.0, r5 at 0:20.0)', '1 major finding (...)', for a next line."""
    severities = sorted({f['severity'] for f in found}, key=SEVERITIES.index)
    what = ' or '.join(severities)
    items = ', '.join(f"{f.get('id') or f.get('source') or 'a finding'} at {f.get('at') or '-'}" for f in found[:6])
    more = f' and {len(found) - 6} more' if len(found) > 6 else ''
    return f"{len(found)} {what} finding{'s' if len(found) != 1 else ''} ({items}{more})"


def _are(found):
    return 'are' if len(found) != 1 else 'is'



def fix_changes(findings):
    """T362 (review_fix_changes): the ready trims the clip-edge findings carry, one trim per clip (both its edges in
    one), as {'what', 'changes'} for one letitedit_timeline_apply; None when no finding carries one."""
    by_id = {}
    for f in findings:
        c = f.get('change')
        if isinstance(c, dict) and c.get('op') == 'trim' and c.get('id'):
            by_id.setdefault(c['id'], {'op': 'trim', 'id': c['id']}).update(
                {k: v for k, v in c.items() if k in ('in', 'out')})
    if not by_id:
        return None
    return {'what': f"the trims that make {len(by_id)} clip edge(s) the findings name clean, each on a whole frame "
                    "(the fix: lines marked 'one of fix_changes'); together they are one changes list for "
                    "letitedit_timeline_apply",
            'changes': list(by_id.values())}


def reply(r):
    """What the tool hands back: the verdict, the fixes in order with their times, what the review couldn't check, what
    to do next and where the files are. Everything else (evidence, every coverage line, the brief's requirements, the
    measurements) is in review.md and review_bundle.json in the review's folder."""
    files = r.get('files') or {}
    findings = r.get('findings') or []
    rounds = r.get('rounds') or {}
    out = {'verdict': r['verdict'], 'counts': r['counts'], 'kind': r.get('kind'), 'duration_s': r.get('duration_s'),
           'fixes': [_reply_line(f) for f in findings[:REPLY_FINDINGS]]
           + ([f'... {len(findings) - REPLY_FINDINGS} more in review.md'] if len(findings) > REPLY_FINDINGS else []),
           'for_you': [_reply_line(f) for f in r.get('for_you') or []],
           'not_checked': [f"{c['check']}: {c['state']}" + (f" ({' '.join(str(c.get('detail') or '').split())[:160]})"
                                                           if c.get('detail') else '')
                           for c in r.get('coverage') or [] if c.get('state') != 'done'],
           'rounds': {k: rounds[k] for k in ('done', 'limit', 'limit_reached', 'final', 'turbo') if k in rounds},
           **({'next': r['next']} if r.get('next') else {}),
           **({'credits': r['credits']} if r.get('credits') else {}),
           'files': {k: v for k, v in (('review_md', r.get('report')),
                                       ('folder', str(Path(r['report']).parent) if r.get('report') else None),
                                       ('details', files.get('details')),
                                       ('pages', [p['file'] if isinstance(p, dict) else p for p in files.get('pages') or []]),
                                       ('final_frames', files.get('final_frames'))) if v}}
    changes = fix_changes(findings)
    if changes:
        out['fix_changes'] = changes
    if r.get('render'):
        out['render'] = r['render']
    if r.get('review_order'):
        out['review_order'] = r['review_order']
    if r.get('final_export'):
        out['final_export'] = r['final_export']
    if r.get('final_check'):
        out['final_check'] = {k: r['final_check'][k] for k in ('matches', 'problems')}
    if r.get('errors'):
        out['errors'] = [str(e)[:200] for e in r['errors']]
    return out


def preview_size_of(video, project, info):
    """(width, height) of the project's own picture when `video` is a smaller render of it (a preview), else None."""
    if not project or not str(project).lower().endswith('.mlt') or not Path(project).is_file():
        return None
    try:
        import letitedit.review.checks as checks
        profile = checks.resolve(project)[0].profile
        full = (int(profile['width']), int(profile['height']))
    except Exception:  # noqa: BLE001 - an unreadable project: judged as the file is
        return None
    width, height = info.get('width') or 0, info.get('height') or 0
    if width and height and width < full[0] and height < full[1] and abs(width / height - full[0] / full[1]) < .02:
        return full
    return None


def engine_detail_page(project, moments, path, portrait):
    """The details page from full-size frames of the project drawn by the export engine (for a review on a preview)."""
    from PIL import Image
    import letitedit.review.checks as checks
    if not moments:
        return None
    timeline, resolved = checks.resolve(project)
    width = 540 if portrait else 960
    with tempfile.TemporaryDirectory() as tmp:
        pngs = checks.render_frames(timeline, resolved, [round(t * timeline.fps) for t, _ in moments], Path(tmp))
        tiles = []
        for png, (t, why) in zip(pngs, moments):
            picture = Image.open(png).convert('RGB')
            picture = picture.resize((width, round(picture.height * width / picture.width)))
            tiles.append(_label(picture, f'{fmt(t)}  {why}  (full size)'[:90], 20))
    cols = 4 if portrait else 2
    tw, th = tiles[0].size
    sheet = Image.new('RGB', (cols * (tw + 6) + 6, math.ceil(len(tiles) / cols) * (th + 6) + 6), (255, 255, 255))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (6 + (i % cols) * (tw + 6), 6 + (i // cols) * (th + 6)))
    sheet.save(path, quality=92)
    return str(path)


def detail_page(ffmpeg, video, moments, path, portrait):
    """One page of larger frames at chosen moments [(t, why)], each labelled with its time and reason."""
    from PIL import Image
    if not moments:
        return None
    width = 540 if portrait else 960
    tiles = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (t, why) in enumerate(moments):
            f = Path(tmp) / f'd{i}.jpg'
            seek = math.floor(max(0.0, t) * 1_000_000) / 1_000_000
            _run([ffmpeg, '-v', 'error', '-y', '-ss', f'{seek:.6f}', '-i', video, '-frames:v', '1', '-vf',
                  f'scale={width}:-2', '-q:v', '3', str(f)], heavy=True)
            if f.exists():
                tiles.append(_label(Image.open(f).convert('RGB'), f'{fmt(t)}  {why}'[:90], 20))
    if not tiles:
        return None
    cols = 4 if portrait else 2
    tw, th = tiles[0].size
    sheet = Image.new('RGB', (cols * (tw + 6) + 6, math.ceil(len(tiles) / cols) * (th + 6) + 6), (255, 255, 255))
    for i, tile in enumerate(tiles):
        sheet.paste(tile.resize((tw, th)), (6 + (i % cols) * (tw + 6), 6 + (i // cols) * (th + 6)))
    sheet.save(path, quality=88)
    return str(path)


def boundary_moments(cuts, duration, fps):
    """The outgoing frame at each picture cut, plus the final frame, in timeline seconds."""
    rate = fps or 30.0
    frames = sorted({max(0, round(moment * rate) - 1)
                     for moment in list(cuts) + [duration] if 0 < moment <= duration})
    return [(frame / rate,
             f'last picture before {(frame + 1) / rate:.3f} s; check text/logo reveal and frame edges')
            for frame in frames]


def strip(ffmpeg, video, start, seconds, path, fps=6, width=200):
    n = max(1, int(round(seconds * fps)))
    _run([ffmpeg, '-v', 'error', '-y', '-ss', f'{max(0.0, start):.3f}', '-t', f'{seconds:.3f}', '-i', video, '-vf',
          f'fps={fps},scale={width}:-2,tile={n}x1:padding=2:color=white', '-frames:v', '1', '-q:v', '4', str(path)],
         heavy=True)
    return str(path) if Path(path).exists() else None


def excerpt(ffmpeg, video, start, seconds, path):
    _run([ffmpeg, '-v', 'error', '-y', '-ss', f'{max(0.0, start):.3f}', '-t', f'{seconds:.3f}', '-i', video, '-vf',
          'scale=720:-2', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-c:a', 'aac', '-b:a', '96k',
          str(path)], heavy=True)
    return str(path) if Path(path).exists() else None


# ---------------------------------------------------------------- sound and words

NO_SPEECH_PROGRAM = "letitedit's speech program isn't in this install"
NO_SPEECH_MODEL = "letitedit's speech model isn't installed on this PC"
NO_TRANSCRIPT = "letitedit's speech model wrote no transcript of it"


def transcript(gate, video, folder, why=None, plain=None):
    """The render's whole transcript as cues [(start, end, text)], written to transcript.srt (an earlier round's file
    is removed first, so none is ever read as this render's). The whisper.cpp model (141 MB) comes on first use;
    without it (no download allowed, or it failed) there is no transcript. why: a list that gets the reason when there
    is none (technical: it may name a folder); plain: a list that gets it in plain words, with no path."""
    why = [] if why is None else why
    plain = [] if plain is None else plain
    (Path(folder) / 'transcript.srt').unlink(missing_ok=True)
    model = gate.MODEL
    if gate.WHISPER.exists() and not (model and Path(model).exists()):
        import letitedit.core.first_use as first_use
        if first_use.optional(models=['whisper-cpp-base-en'], feature="the review's transcript (whisper.cpp base.en)"):
            model = next(iter(sorted((gate.ROOT / 'models').glob('ggml-*.bin'), key=lambda p: p.stat().st_size)), None)
    if not (gate.WHISPER.exists() and model):
        why.append(f'its speech program ({Path(str(gate.WHISPER)).name}) is not in this install'
                   if not gate.WHISPER.exists() else
                   f"its speech model (whisper.cpp base.en, 141 MB) is not on this PC ({gate.ROOT / 'models'}) "
                   "and wasn't downloaded")
        plain.append(NO_SPEECH_PROGRAM if not gate.WHISPER.exists() else NO_SPEECH_MODEL)
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wav, base = Path(tmp) / 'a.wav', Path(tmp) / 'a'
        _run([gate.FFMPEG, '-v', 'error', '-y', '-i', video, '-ar', '16000', '-ac', '1', wav], heavy=True)
        _run([gate.WHISPER, '-m', model, '-f', wav, '-osrt', '-of', base, '-np'], timeout=3600, heavy=True)
        srt = base.with_suffix('.srt')
        if not srt.exists():
            why.append('the speech model wrote no transcript')
            plain.append(NO_TRANSCRIPT)
            return None
        text = srt.read_text(encoding='utf-8', errors='replace')
    (folder / 'transcript.srt').write_text(text, encoding='utf-8')
    cues = []
    for m in re.finditer(r'(\d\d):(\d\d):(\d\d)[,.](\d{3}) --> (\d\d):(\d\d):(\d\d)[,.](\d{3})[^\n]*\n(.*?)(?:\n\n|\Z)',
                         text, re.S):
        g = [int(x) for x in m.groups()[:8]]
        cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                     m.group(9).replace('\n', ' ').strip()))
    return cues


def level_graph(ffmpeg, video, duration, silences, path):
    """Level (dBFS RMS per 0.5 s) over the whole video, silences shaded."""
    import numpy as np
    from PIL import Image, ImageDraw
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'l.wav'
        _run([ffmpeg, '-v', 'error', '-y', '-i', video, '-ar', '8000', '-ac', '1', wav], heavy=True)
        if not wav.exists():
            return None
        with wave.open(str(wav)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
            rate = w.getframerate()
    step = rate // 2
    levels = [20 * math.log10(max(1e-5, float(np.sqrt(np.mean(pcm[i:i + step] ** 2))))) for i in range(0, len(pcm), step)]
    W, H, pad = 1600, 260, 40
    img = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x = lambda t: pad + (W - 2 * pad) * t / max(duration, 0.1)        # noqa: E731
    y = lambda db: pad + (H - 2 * pad) * min(1.0, max(0.0, -db / 60))  # noqa: E731
    for s, e in silences:
        d.rectangle([x(max(0, s)), pad, x(e if e is not None else duration), H - pad], fill=(255, 225, 225))
    for db in (0, -20, -40, -60):
        d.line([pad, y(db), W - pad, y(db)], fill=(220, 220, 220))
        d.text((4, y(db) - 7), f'{db}', fill=(120, 120, 120), font=_font(12))
    pts = [(x(i * 0.5), y(v)) for i, v in enumerate(levels)]
    if len(pts) > 1:
        d.line(pts, fill=(30, 90, 200), width=2)
    for m in range(0, int(duration) + 1, 30 if duration > 240 else 10):
        d.text((x(m) - 10, H - pad + 6), fmt(m).split('.')[0], fill=(80, 80, 80), font=_font(12))
    d.text((pad, 8), 'Level over the whole video (dBFS, 0.5 s RMS); shaded: silences', fill=(0, 0, 0), font=_font(15))
    img.save(path)
    return str(path)


# ---------------------------------------------------------------- the verdict

TEXT_PARAMS = ('text', 'title', 'subtitle', 'name', 'role', 'label', 'line', 'caption', 'number', 'heading')


def onscreen_text(project):
    """The words graphics put on screen (word-by-word captions, titles, labels, lower thirds), one line each: the
    brief's claims count there as in caption tracks."""
    try:
        import letitedit.timeline.edit_script as es
        script = es.read(project)
    except Exception:  # noqa: BLE001 - no readable project: caption tracks only
        return ''
    lines = []
    for track in script.get('tracks') or []:
        for item in track.get('items') or []:
            params = ((item.get('graphic') or {}).get('params')) or {}
            words = params.get('words')
            if isinstance(words, list):
                lines.append(' '.join(str(w[0] if isinstance(w, (list, tuple)) else w) for w in words))
            lines += [str(params[k]) for k in TEXT_PARAMS if isinstance(params.get(k), (str, int, float))]
            motion = (item.get('motion') or {}).get('params') if isinstance(item.get('motion'), dict) else None
            if isinstance(motion, dict):     # word-by-word kinetic captions: rows of {text, start}
                rows = [r for r in (list(motion.get('words') or []) + list(motion.get('phrases') or [])) if isinstance(r, dict)
                        and isinstance(r.get('text'), str)]
                rows.sort(key=lambda r: float(r.get('start') or 0))
                if rows:
                    lines.append(' '.join(r['text'] for r in rows))
    return '\n'.join(l for l in lines if l.strip())


TIMING_LANES = ['edit', 'frame_features', 'motion', 'visual_beats', 'motion_events', 'attention', 'shots', 'audio',
                'music']   # the bundle transcribes on its own, so the map skips the speech lane


AUDIO_ONLY = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.wma'}
MUSIC_TRACK = re.compile(r'music|song|score|bed', re.I)


def music_possible(project):
    """False only when the project surely has no music: no audible clip on a track named for music and no audio-only
    file playing (a song is an audio file). Unknown (no project, unreadable): True, so the timing map measures music.
    The music lane is the slowest part of the map (minutes on a long talk) and finds 'beats' in speech."""
    if not project or not str(project).lower().endswith('.mlt') or not Path(project).is_file():
        return True
    try:
        import letitedit.timeline.edit_script as es
        script = es.read(project)
    except Exception:  # noqa: BLE001 - unreadable: measure as before
        return True
    for t in script['tracks']:
        if t.get('hide') in ('audio', 'both'):
            continue
        for it in t['items']:
            clip = it.get('clip')
            if not clip or 'mute' in (it.get('effects') or []):
                continue
            if MUSIC_TRACK.search(t.get('name') or '') or Path(str(clip)).suffix.lower() in AUDIO_ONLY:
                return True
    return False


def timing_facts(video, out, cuts_at=None, music=True):
    """The rhythm map and, with music, the sync view of the export (letitedit_timing): measured timing for the critic
    and the person; cuts_at adds a project's own cuts; music=False leaves the music lane out (no music in the
    project). Writes out/timing.json; returns (facts, images) or raises."""
    import letitedit.server.timing_tools as timing_tools
    lanes = TIMING_LANES if music else [n for n in TIMING_LANES if n != 'music']
    m = timing_tools.timing(str(video), 'map', options={'lanes': lanes, **({'cuts_at': cuts_at} if cuts_at else {})})
    facts = {'map': {'summary': m.get('summary'), 'sections': [
        {k: s.get(k) for k in ('label', 't0', 't1', 'numbers') if k in s} for s in m.get('sections') or []],
        'music': m.get('music'), 'result_file': m.get('result_file')}, 'warnings': list(m.get('warnings') or [])}
    images = list(m.get('images') or [])[:2]
    if m.get('music'):
        s = timing_tools.timing(str(video), 'sync', options={'cuts_at': cuts_at} if cuts_at else None)
        keep = ('n_with_music', 'share_on_beat', 'chance_on_beat', 'share_near_beat', 'chance_near_beat',
                'median_abs_offset_frames', 'median_offset_frames')
        summary = {k: {**{x: v.get(x) for x in keep if x in v},
                       'phase_locking': (v.get('phase_locking') or {}).get('vector_strength')}
                   for k, v in (s.get('summary') or {}).items() if isinstance(v, dict) and v.get('n_with_music')}
        facts['sync'] = {'summary': summary, 'monotony': s.get('monotony'),
                         'music': {k: (s.get('music') or {}).get(k) for k in ('tempo_bpm', 'beat_quality',
                                                                                'beat_confidence')},
                         'speech_vs_music': s.get('speech_vs_music'), 'result_file': s.get('result_file')}
        facts['warnings'] += list(s.get('warnings') or [])[:5]
        images += list(s.get('images') or [])[:1]
    (Path(out) / 'timing.json').write_text(json.dumps(facts, indent=1, default=str), encoding='utf-8')
    return facts, images


def _finding(source, severity, what, at=None, evidence='', fix=''):
    return {'source': source, 'severity': severity, 'at_s': None if at is None else round(float(at), 2),
            'at': '' if at is None else fmt(at), 'what': what, 'evidence': evidence, 'fix': fix}


def cut_word_findings(found, pins, tag=None):
    """The review's findings for checks.cut_words' edges: a pinned edge says who kept it; a ready trim (T362,
    review_fix_changes) rides along as `change` with its `fix` line, never for a pinned edge."""
    import letitedit.review.checks as project_checks
    out = []
    for f in found:
        pin = project_checks.pin_note(f, pins)
        ready = {'change': f['change']} if f.get('change') and not pin else {}
        out.append({**_finding('project', f.get('severity', 'major'), f['problem'] + pin, f['at'],
                               fix=f.get('fix', '') if ready else ''), **(tag or {}), **ready})
    return out


def restart_findings(project, restarts, talk=('clean', ''), spoken=()):
    """Findings for the restarts left in the cut (checks.false_starts): major, or minor with the line that keeps it when
    the fine or finish notes keep it on purpose (a choice the edit wrote down: the person hears it, the verdict doesn't
    wait on it). In natural talk (checks.talk_kind: a conversation) only a clear false start is a finding of its own;
    the doubled words and quick self-corrections a conversation keeps, with the render transcript's restarts (`spoken`,
    which have no pauses to judge), are one minor line."""
    import letitedit.review.checks as project_checks
    out = []
    if talk[0] == 'natural':
        natural = [f for f in restarts if not project_checks.clear_false_start(f)] + list(spoken)
        restarts = [f for f in restarts if project_checks.clear_false_start(f)]
        if natural:
            natural.sort(key=lambda f: f['at'])
            times = ', '.join(fmt(f['at']) for f in natural[:8]) + (' ...' if len(natural) > 8 else '')
            out.append(_finding('project', 'minor', f"{len(natural)} doubled word(s) and quick self-correction(s) left in "
                                f"({talk[1]}): a conversation keeps them; only a sentence begun, dropped and begun "
                                f"again is cut. At {times}", natural[0]['at']))
    for f in restarts:
        kept = project_checks.kept_on_purpose(project, f.get('said', ''))
        if kept:
            out.append(_finding('project', 'minor', f"{f['problem']}; kept on purpose in the fine notes "
                                f"(\"{kept[:160]}\"): listen that it reads as meant", f['at']))
        else:
            out.append(_finding('project', 'major', f['problem'], f['at']))
    return out


def once_each(findings):
    """The findings with repeats from one source left out: the same problem at the same moment, found twice (a cue
    checked on the burned-in track and again on its SRT copy), is one finding. The worse severity is kept."""
    out, seen = [], {}
    for f in findings:
        key = (f.get('source'), f.get('what'), f.get('at_s'))
        if key in seen:
            kept = seen[key]
            if SEVERITIES.index(f['severity']) < SEVERITIES.index(kept['severity']):
                kept['severity'] = f['severity']
            continue
        seen[key] = f
        out.append(f)
    return out


def _once(findings):
    """Each finding once: the same problem at the same moment and severity from two checks (or two tracks) is one row,
    with the other sources under `also_from`."""
    out, first = [], {}
    for finding in findings:
        key = (finding['severity'], finding['at_s'], finding['what'])
        if key not in first:
            first[key] = finding
            out.append(finding)
        elif finding['source'] != first[key]['source'] and finding['source'] not in first[key].get('also_from', []):
            first[key].setdefault('also_from', []).append(finding['source'])
    return out


def preexport_split(preexport):
    """A pre-export receipt's findings as (its Look check's own, the rest). The review runs the Look check again on the
    delivered bytes ('look completeness'), so the Look's findings are said there, once."""
    own = {finding.get('problem') for finding in
           ((preexport.get('checks') or {}).get('look') or {}).get('findings') or []}
    findings = preexport.get('findings') or []
    return ([finding for finding in findings if finding.get('problem') in own],
            [finding for finding in findings if finding.get('problem') not in own])


def preexport_coverage(preexport, summary):
    """(state, detail) of the pre-export checks' coverage line. A check that could not run at export is no fault in
    the video, and that export is not checked by it: 'failed', naming each, so the verdict is never 'ready' on it."""
    missing = [u for u in preexport.get('unavailable') or [] if isinstance(u, dict)]
    if preexport.get('not_compared'):       # an older receipt on a moved project (T347): said, not a change
        summary = f"{summary}; {preexport['not_compared']}"
    if not missing:
        return 'done', summary
    return 'failed', (f"{summary}; could not run at export: "
                      + '; '.join(f"{u.get('check')} ({u.get('reason')})" for u in missing))


def look_rows(result):
    """The Look check's rows for the review: (its faults in the video as findings, at their own severity; how many rows
    are the receipt's record of the AI's decisions or something not checked). A receipt row is no fault in the video:
    it is counted in the coverage line, never a finding the person reads or the AI fixes by exporting again."""
    faults = [_finding('look completeness', finding['severity'], finding['problem'])
              for finding in result.get('findings') or [] if finding.get('severity') in ('critical', 'major', 'minor')]
    record = sum(finding.get('severity') not in ('critical', 'major', 'minor') for finding in result.get('findings') or [])
    return faults, record


def gate_severity(check):
    """The finding severity of a failed gate check, from the severity gate.py recorded: advisory -> minor,
    blocking -> major (gate.py makes only OFF/EXP checks and the brief's or a reference's own limits blocking; a HYP
    default never blocks, so a blocking HYP check stays minor). A checks.json from an older gate has no severity:
    OFF/EXP -> major, the rest minor."""
    severity = check.get('severity')
    if severity == 'advisory':
        return 'minor'
    if severity == 'blocking':
        return 'minor' if check.get('tag') == 'HYP' else 'major'
    return 'major' if check.get('tag') in ('OFF', 'EXP') else 'minor'


def gate_findings(checks):
    out = []
    for c in checks.get('checks', []):
        if c['state'] != 'fail':
            continue
        sev = gate_severity(c)
        fix = ('fix it, or waive it with a reason if the brief asks for it' if sev == 'major' else
               'a default for this kind of video, not a rule: change it if that helps the video, or leave it and '
               'say why')
        length = c['check'] in ('duration_vs_target', 'platform_max_length_s')
        text = (f"length {c['value']} s; {c['threshold']}" if length else
                f"{c['check']} = {c['value']} (wanted {c['threshold']})")
        out.append(_finding('gate', sev, text, c.get('at_s'),
                            evidence=c.get('note', ''), fix='' if length else fix))
    return out


def _deliverable_entry(brief, kind):
    """The brief's deliverable for this export: the one whose kind matches; for a long export, a podcast /
    broadcast / web one; else the only one; else None."""
    entries = [d for d in (brief.get('deliverables') or []) if isinstance(d, dict)]
    match = [d for d in entries if d.get('kind') == kind]
    if match:
        return match[0]
    if kind == 'long':
        other = [d for d in entries if str(d.get('kind') or '').lower() in ('podcast', 'broadcast', 'web')]
        if other:
            return other[0]
    return entries[0] if len(entries) == 1 else None


def gate_context(brief, kind, gate, project=None):
    """What gate.py needs from the brief for this export: mode (`mode`, the first of several leads; else `genre`),
    driver, deliverable (`deliverable`, or the matching deliverables[].deliverable / .kind: web | podcast |
    broadcast), platforms (the matching deliverables[].platforms, else every deliverable's), the brief's own pace
    limits (`pace`: {check: number | "on" | "off"}) and a local `reference` video. Unknown values fall back to the
    gate's defaults (story, the mode's usual driver, web) with a note."""
    brief = brief if isinstance(brief, dict) else {}
    notes = []
    raw_mode = brief.get('mode') or brief.get('genre')
    mode = gate.norm_mode(raw_mode) if raw_mode else None
    if raw_mode and not mode:
        notes.append(f'mode {raw_mode!r} is not one the gate knows: judged as story')
    raw_driver = brief.get('driver')
    driver = gate.norm_driver(raw_driver) if raw_driver else None
    if raw_driver and not driver:
        notes.append(f"driver {raw_driver!r} is not one the gate knows: the mode's usual driver")
    from letitedit.review.brief_check import wordless
    if wordless(brief) and not driver:
        driver = 'visual'
    entry = _deliverable_entry(brief, kind) or {}
    deliverable = next((gate.norm_deliverable(c) for c in (brief.get('deliverable'), entry.get('deliverable'),
                                                            entry.get('kind'))
                        if isinstance(c, str) and gate.norm_deliverable(c)), None)
    if entry:
        platforms = entry.get('platforms') or []
    else:
        platforms = [p for d in brief.get('deliverables') or [] if isinstance(d, dict)
                     for p in d.get('platforms') or []]
    platforms = gate.norm_platforms(platforms if isinstance(platforms, (list, tuple, str)) else [])
    limits = {}
    pace = {}
    look = {}
    if brief.get('look') not in (None, '', 'auto', 'none', 'freestyle'):   # the Look's own pace (a single unbroken shot, say); the brief's numbers win
        import letitedit.looks.looks as looks
        look = looks.offered(brief['look']) or {}
        pace.update(look.get('pace') or {})
    if isinstance(brief.get('pace'), dict):
        pace.update(brief['pace'])
    if pace:
        for name, value in pace.items():
            try:
                limits.update(gate.parse_limits({name: value}))
            except ValueError as e:
                notes.append(f'pace: {e}')
    reference = None
    ref = brief.get('reference')
    if isinstance(ref, dict):
        ref = ref.get('file') or ref.get('path') or ref.get('video') or ref.get('url')
    if isinstance(ref, str) and ref.strip():
        path = Path(ref.strip())
        if not path.is_absolute() and project:
            path = Path(project).parent / path
        if '://' not in ref and path.is_file():
            reference = str(path)
        else:
            notes.append(f'reference {ref!r} is not a local file: its tempo was not measured')
    ending = brief.get('ending') or look.get('ending') or {}
    allow_black = isinstance(ending, dict) and ending.get('allow_black_tail') is True
    return {'mode': mode or 'story', 'driver': driver, 'deliverable': deliverable or 'web', 'platforms': platforms,
            'limits': limits, 'reference': reference, 'notes': notes,
            'tolerance_s': entry.get('tolerance') if entry.get('tolerance') is not None else entry.get('tolerance_s'),
            'allow_black_tail': allow_black}


def gate_args(ctx):
    """The gate.py flags for a gate_context."""
    args = ['--mode', ctx['mode'], '--deliverable', ctx['deliverable']]
    if ctx.get('driver'):
        args += ['--driver', ctx['driver']]
    if ctx.get('platforms'):
        args += ['--platforms', ','.join(ctx['platforms'])]
    for name, value in (ctx.get('limits') or {}).items():
        args += ['--limit', f'{name}={value:g}' if isinstance(value, float) else f'{name}={value}']
    if ctx.get('reference'):
        args += ['--reference', ctx['reference']]
    if ctx.get('tolerance_s') is not None:
        args += ['--tolerance-s', str(ctx['tolerance_s'])]
    if ctx.get('allow_black_tail'):
        args += ['--allow-black-tail']
    return args


def story_plan_path(project=None, brief=None, out=None):
    """A story_plan.json next to the project or the brief file, or in the bundle folder; None when there is none."""
    folders = []
    if project:
        folders += [Path(project).parent, Path(project).with_suffix('')]
        import letitedit.timeline.project_journal as project_journal
        folders.append(project_journal.folder(project))
    if isinstance(brief, (str, os.PathLike)) and not str(brief).strip().startswith('{') and Path(brief).is_file():
        folders.append(Path(brief).parent)
    if out:
        folders.append(Path(out))
    return next((f / 'story_plan.json' for f in folders if (f / 'story_plan.json').is_file()), None)


BY_EAR = {'must_keep': 'required line to confirm by ear', 'must_avoid': 'line to avoid, to confirm by ear',
          'claim': 'claim to confirm by ear', 'ending': 'ending to confirm by ear'}


def brief_findings(result):
    out = []
    for r in result.get('requirements', []):
        if r['state'] == 'unknown' and r.get('by_ear') and r['kind'] in BY_EAR:
            # the review couldn't hear it, and the timeline's own words place it: where to listen
            a, b = r['by_ear']
            fix = (f'listen at {a:.1f}-{b:.1f} s: if it is said there, cut it' if r['kind'] == 'must_avoid' else
                   f'listen at {a:.1f}-{b:.1f} s: if it is hard to hear under the music or noise, lower them there')
            out.append(_finding('brief', 'minor', f"{BY_EAR[r['kind']]}: {r['requirement']}", a, r.get('evidence', ''),
                                f"{r.get('why', '')}; {fix}"))
            continue
        if r['state'] == 'unknown' and r['kind'] == 'must_keep' and 'reviewer judges' in r.get('why', ''):
            out.append(_finding('brief', 'minor', f"must_keep for the reviewer: {r['requirement']}", None, r.get('evidence', ''),
                                r.get('why', '')))
            continue
        if r['state'] == 'unknown' and r['kind'] == 'claim':        # probably misheard by the transcriber
            m = re.search(r'at (\d+(?:\.\d+)?)', r.get('evidence') or '')
            out.append(_finding('brief', 'minor', f"claim to confirm by ear: {r['requirement']}",
                                float(m.group(1)) if m else None, r.get('evidence', ''), r.get('why', '')))
            continue
        if r['state'] != 'fail':
            continue
        sev = 'critical' if r['kind'] in ('must_keep', 'must_avoid', 'claim', 'narration', 'protected') else 'major'
        m = re.search(r'at (\d+(?:\.\d+)?)', r.get('evidence') or '')
        out.append(_finding('brief', sev, f"{r['kind']}: {r['requirement']}", float(m.group(1)) if m else None,
                            r.get('evidence', ''), r.get('why', '')))
    return out


def _has_code_scene(project):
    """A code scene changes the picture in a way the cut detector, which counts filmed setups, can't see."""
    if not project:
        return False
    try:
        import letitedit.timeline.edit_script as es
        return any('scene' in i for t in es.read(project)['tracks'] for i in t['items'])
    except Exception:  # noqa: BLE001 - not readable: the finding stands
        return False


def firstcut_visual_finding(checks, ctx, stage_progress, brief, project=None):
    """A dialogue-led default Short needs a reason for a very long static stretch. A code scene is one: without this, a talking head
    with scenes could never clear the finding, whatever the AI did. The reviewer still judges how the picture changes."""
    if _has_code_scene(project):
        return None
    if not (stage_progress is not None and checks and ctx.get('driver') == 'dialogue'
            and ctx.get('mode') in ('product', 'story', 'tutorial')
            and (brief or {}).get('style') in (None, 'none')):
        return None
    duration = float((checks.get('info') or {}).get('duration') or 0)
    shots = int(checks.get('shots') or 0)
    if ctx.get('mode') == 'product' and duration >= 15 and shots <= 2:
        return _finding('story', 'major', f'Only {shots} picture setups across {duration:.1f} s',
                        None, 'the detector counts filmed setups; subtle cuts and crops can still read as one '
                        'unchanging scene in the rendered video',
                        'Options with this footage: motivated wide/close/wide resets or a clearly labelled '
                        'explanatory illustration on a product-action line. A real demonstration still needs '
                        'screen footage. Inspect the rendered opening and middle.')
    if checks.get('holds'):
        return None
    hold = next((c for c in checks.get('checks', []) if c.get('check') == 'longest_static_s'), None)
    if not hold or hold.get('state') != 'fail' or float(hold.get('value') or 0) < 10:
        return None
    return _finding('story', 'major', f"The picture stays nearly unchanged for {hold['value']:g} s",
                    hold.get('at_s'), 'dialogue-led Short with no hold: reason',
                    'add a motivated crop reset, cutaway or honest graphic; or mark an intentional hold')


EDIT_KINDS = ('apply', 'undo', 'hand_edit', 'version')     # journal entries that change the cut


def edited_after(entries, entry):
    """Whether the journal has an edit after `entry` (an apply that only wrote markers is none)."""
    later = entries[next((i for i, e in enumerate(entries) if e is entry), len(entries)) + 1:]
    return any(e.get('kind') in EDIT_KINDS and not e.get('markers_only') and e.get('changes_total', 1) != 0
               for e in later)


def _script_of(path):
    import letitedit.timeline.edit_script as es
    return es.read(path)


def _when(text):
    import datetime
    try:
        moment = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def measured_cut(project, entry, entries):
    """(export record, kept timeline) of the cut a sound_check `entry` measured, or None: the newest export started
    before the measurement (an export measures the mix from its own sound render), with no edit in the journal between
    the two."""
    import letitedit.timeline.export_checks as export_checks
    import datetime
    at = _when(entry.get('time'))
    if at is None:
        return None
    at += datetime.timedelta(seconds=1)       # the journal keeps whole seconds, an export's start finer
    started = [(_when(row.get('started')), row, kept) for row, kept in export_checks.kept_exports(project)]
    before = [s for s in started if s[0] is not None and s[2] is not None and s[0] <= at]
    if not before:
        return None
    when, row, kept = max(before, key=lambda s: s[0])
    # the journal's order says what came before the measurement; its whole seconds, what came after the export
    earlier = entries[:next((i for i, e in enumerate(entries) if e is entry), len(entries))]
    since = when - datetime.timedelta(seconds=1)
    between = [e for e in earlier if e.get('kind') in EDIT_KINDS and not e.get('markers_only')
               and e.get('changes_total', 1) not in (0, '0') and (_when(e.get('time')) or since) >= since]
    return None if between else (row, kept)


def mix_changed(project, entry, entries=(), notes=None):
    """Whether the cut's sound differs from the one a sound_check `entry` measured (its `audio` signature). A
    signature from before T347 (no checks.AUDIO_PREFIX) is compared as it was made, also with the paths put back in a
    folder the project was in. When the signature differs, the timeline that was measured (kept by its export,
    measured_cut) is compared by its sound, but for settings the editor's window fills in with no edit since; with no
    such timeline, a signature of today's kind stands, and an older one counts only when the journal has an edit after
    it (none: not counted as a change, and `notes` says the measurement couldn't be compared)."""
    import letitedit.review.checks as _checks
    stored = entry['audio']
    entries = list(entries)
    current = str(stored).startswith(_checks.AUDIO_PREFIX)
    try:
        import letitedit.timeline.export_checks as export_checks
        moved = export_checks.project_moves(project)
        if current:
            if _checks.audio_signature(project, moved) == stored:
                return False
        else:
            import letitedit.timeline.edit_script as es
            if export_checks.legacy_match(project, es.read(project), stored, _checks.audio_signature_legacy):
                return False
        measured = measured_cut(project, entry, entries)
        if measured is not None:        # the timeline that was measured, kept by its export: its sound against now's
            row, kept = measured
            then_moved = [(export_checks.project_folder(kept), Path(project).resolve().parent)]
            if row.get('sources_sha256') and row['sources_sha256'] != export_checks.sources_digest(
                    _script_of(kept), export_checks.project_folder(kept), then_moved):
                return True             # a source file replaced since
            now = _checks.audio_content(project, moved)
            then = _checks.audio_content(kept, then_moved)
            return not (now == then or (export_checks.relaxed_equal(now, then) and not edited_after(entries, entry)))
    except Exception:  # noqa: BLE001 - unreadable: the earlier measurement stands
        return False
    if current or edited_after(entries, entry):
        return True
    if notes is not None:
        notes.append('the mix was measured before letitedit recorded the sound by what its sources are, and that '
                     'measurement no longer matches the project\'s paths (a moved project), so it can\'t be compared; '
                     'no edit since it is in the journal, so this is not counted as a change')
    return False


def export_freshness(project, video):
    """(changed, how): whether the saved project differs from what this video was exported from, by what the video is
    made of (export_checks.changed_since_export, T347): a project moved to another folder, or saved with markers or
    notes added, is unchanged. None when it can't be compared (how says why). A video with no export record (made
    before letitedit kept one) falls back to the files' times."""
    import letitedit.timeline.export_checks as export_checks
    changed, how = export_checks.changed_since_export(project, video)
    if how == 'no record':
        return Path(project).stat().st_mtime > Path(video).stat().st_mtime + 2, 'by the files\' times (no export record)'
    return changed, how


def sound_findings(project, spoken=True, notes=None):
    """What the finish stage should have done to the sound and didn't: the mix never measured on this cut, the voice
    clean-up on no clip with no word why. Facts the gate can read: the journal's sound_check, the clips' fix effects,
    the finish notes. A voice this PC made has no room to clean: a no-footage video without the person's own voiceover."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.project_journal as project_journal
    out = []
    # a measurement of one stretch (start_s/end_s) doesn't measure the mix of the cut
    entries = project_journal.entries(project, limit=None)
    measured = [e for e in entries if e.get('kind') == 'sound_check' and not e.get('range')]
    if not measured:
        out.append(_finding('sound', 'major', 'The mix was never measured on this cut (letitedit_check_audio did not run).',
                            evidence='no sound_check in the project journal', fix='letitedit_check_audio(project, stems=True)'))
    elif measured[-1].get('audio'):
        if mix_changed(project, measured[-1], entries, notes):
            out.append(_finding('sound', 'major', 'The mix was measured on an earlier cut: clips, cut points or levels have '
                                'changed since letitedit_check_audio last ran.',
                                evidence=f"the sound_check at {measured[-1].get('time')} saw another signature of the sound",
                                fix='letitedit_check_audio(project, stems=True) on the cut you are handing over'))
    if not spoken:
        return out
    import letitedit.looks.look_inputs as look_inputs
    if look_inputs.no_footage(project) and not look_inputs.has_voiceover(look_inputs.read(project)):
        return out
    script = es.read(project)
    cleaned = any((e.get('fix') or {}).get('kind') == 'voice' for t in script['tracks'] for i in t['items']
                  for e in i.get('effects') or [] if isinstance(e, dict))
    notes = project_journal.folder(project) / 'finish_pass.md'
    reason = notes.is_file() and 'voice' in notes.read_text(encoding='utf-8', errors='replace').casefold()
    if not cleaned and not reason:
        out.append(_finding('sound', 'major', 'No clip has the voice clean-up, and the finish notes give no reason.',
                            evidence='no {fix: {kind: voice}} effect on any clip; finish_pass.md does not mention the voice',
                            fix="letitedit_fix(project, item=<clip>, fix='voice') on the talking clips, or say why not in finish_pass.md"))
    return out


def _editor_words(timeline):
    """What the editing transcript (the better speech model) heard in the project's sources, from its cache. Never runs a model."""
    if timeline is None:
        return None
    import letitedit.footage.speech as speech
    said = []
    for path in {i.resource for t in timeline.tracks for i in t.items if getattr(i, 'resource', None)}:
        try:
            said += [str(w.get('w', '')) for w in speech.cached_words(path) or []]
        except Exception:  # noqa: BLE001 - not cached, or not a file with speech
            continue
    return ' '.join(said) or None


PREFERENCE = 'preference'     # a problem about a brief's preference: a note, never counted
PREFERENCES_NOTE = ("preferences are the person's wishes, below every requirement in this brief: the editor follows each "
                    "unless it conflicts with a requirement or an earlier preference, and reports on each one itself. "
                    "A preference that wasn't followed is not a problem: never list it in problems. If you list one "
                    "anyway, give it kind \"preference\"; the review leaves it out of its counts and its verdict.")


def counted_problems(review):
    """The critic's problems that count toward the verdict: all but those about a brief's preference."""
    return [p for p in review.get('problems') or [] if isinstance(p, dict)
            and str(p.get('kind') or '').strip().lower() != PREFERENCE]


def critic_findings(review):
    out = []
    problems = counted_problems(review)
    only_preferences = bool(review.get('problems')) and not problems
    for i, p in enumerate(problems):
        sev = str(p.get('severity') or '').lower()
        if sev not in SEVERITIES:
            sev = 'major' if i < 2 and review.get('verdict') in ('block', 'revise') else 'minor'
        at = None
        m = re.match(r'\s*(\d+):(\d+(?:\.\d+)?)', str(p.get('t') or ''))
        if m:
            at = int(m.group(1)) * 60 + float(m.group(2))
        out.append(_finding('critic', sev, f"{p.get('kind', 'edit')}: {p.get('evidence') or p.get('what') or ''}"[:300],
                            at, p.get('evidence', ''), p.get('fix', '')))
        out[-1]['said_owner'] = p.get('owner')
    if review.get('verdict') == 'block' and not only_preferences and not any(f['severity'] == 'critical' for f in out):
        out.append(_finding('critic', 'critical', 'the reviewer would block this video', evidence=review.get('why', '')))
    return out


def verdict(findings, coverage):
    if any(c['check'] == 'first-cut stages' and c['state'] != 'done' for c in coverage):
        return 'incomplete'
    if any(f['severity'] == 'critical' for f in findings):
        return 'blocked'
    if any(f['severity'] == 'major' for f in findings):
        return 'revise'
    if any(c['state'] in ('not done', 'failed') and c.get('required') for c in coverage):
        return 'incomplete'
    return 'ready'


# ---------------------------------------------------------------- the bundle

def _start_final(project, errors):
    """Submit the project's final export (full size, its default name); {job_id, output}, or None with the error noted
    (the review goes on and the final is exported after it)."""
    try:
        import letitedit.timeline.render_queue as render_queue
        job = render_queue.submit(project)
        return {'job_id': job.get('job_id'), 'output': job.get('output') or
                (json.loads((render_queue.JOBS / job['job_id'] / 'spec.json').read_text(encoding='utf-8-sig'))
                 .get('output'))}
    except Exception as e:  # noqa: BLE001 - the review goes on; the final is exported after it
        errors.append(f'final export: {type(e).__name__}: {e}'[:300])
        return None


CHANGE_ITEM = 'change'      # a look's question about the cut as a whole: did the change since the last look break anything


def change_item(project):
    """The look's question about a cut no reviewer saw: what changed since the last round (the journal's labels)."""
    try:
        labels = _recent_changes(project)
    except Exception:  # noqa: BLE001 - the question stands without the labels
        labels = []
    named = f" ({'; '.join(str(x)[:80] for x in labels)})" if labels else ''
    return {'id': CHANGE_ITEM, 'at': None, 'what': (
        f"The editor changed the cut after the last review{named}. Look at the whole video: say still_open, with what "
        "you saw, only if something a viewer would notice is now broken (a cut through a word, a jump, a flash, text "
        "that is wrong, cut off or over a face, a sudden sound); otherwise say fixed.")}


def _record_usage(project, answer, what):
    """A separate run of the person's AI (the critic, a look): its token use goes in the project's background calls
    (hooks.record_background_call), so the run's cost (run_cost) counts it; one with no usage is recorded as not
    measured. Never fails the review."""
    try:
        if not project or not isinstance(answer, dict) or not answer.get('engine'):
            return
        import letitedit.footage.hooks as hooks
        used = answer.get('usage') if isinstance(answer.get('usage'), dict) else None
        hooks.record_background_call(project, what, answer['engine'], answer.get('model'), used)
    except Exception:  # noqa: BLE001 - a cost line, never a reason to lose the review
        pass


def targeted_look(gate, memory, video, project, kind, out, duration, portrait, page_list, engine, instead_of_round=False,
                  only=None, key='targeted_look', gone=None, change=None, project_hash=None, shown=''):
    """A look past the round limit (or, with the review order on, instead of a second full round after mechanical
    fixes: instead_of_round): a reviewer sees only the open items and the pictures and words around each, and says
    fixed or still open for each. Returns (answers or None, a line for the review). Every look, answered or not, is
    kept in the memory's looks with the project state it saw (project_hash) and its token use is counted
    (_record_usage); one that gave no answer closes nothing.
    only: just these item ids (review_memory.text_gone's), recorded under key ('text_look') instead. gone: the items
    whose quoted words this cut no longer shows (shown): the reviewer says how each still-open one reads now, and the
    note is rewritten with that (review_memory.rewrite), never left quoting words that are gone. change: a question
    about the cut as a whole (change_item); a still_open answer to it becomes a new major finding in
    memory['_look_findings']."""
    gone = set(gone or [])
    items = [i for i in review_memory.open_for_look(memory) if only is None or i['id'] in only]
    asked = [{'id': i['id'], 'what': i.get('now') or i.get('what'), 'at': i.get('at'), 'fix': i.get('fix'),
              **({'quote_gone': True} if i['id'] in gone else {})} for i in items]
    if change:
        asked.append(dict(change))
    folder = Path(out) / 'targeted'
    folder.mkdir(parents=True, exist_ok=True)
    timed = [i for i in items if i.get('at_s') is not None]
    moments = [(min(float(i['at_s']), max(0.0, duration - 0.1)), i['id']) for i in timed]
    pictures = []
    for at, name in moments:
        start = max(0.0, at - 2.0)
        pictures.append(strip(gate.FFMPEG, video, start, min(4.0, duration - start), folder / f'{name}.jpg'))
    if moments:
        pictures.append(detail_page(gate.FFMPEG, video, moments, folder / 'frames.jpg', portrait))
    whole = len(timed) < len(asked)       # a finding about no one moment, or the change question: the whole video
    if whole:
        pictures += [p['file'] for p in page_list]
    srt = Path(out) / 'transcript.srt'
    cues = []
    if srt.is_file():
        for block in srt.read_text(encoding='utf-8', errors='replace').strip().split('\n\n'):
            lines = block.splitlines()
            m = re.match(r'(\d+):(\d+):(\d+)', lines[1]) if len(lines) > 2 else None
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                if whole or any(abs(t - at) <= 8 for at, _ in moments):
                    cues.append(block)
    spec = folder / 'look.json'
    spec.write_text(json.dumps({'items': asked, 'pictures': [str(p) for p in pictures if p], 'words': '\n\n'.join(cues)},
                               indent=1), encoding='utf-8')
    answer_file = Path(out) / 'targeted-look.json'
    answer_file.unlink(missing_ok=True)
    cmd = [sys.executable, CRITIC, video, '--kind', kind, '--brief', spec, '--out', out, '--project', project, '--targeted', spec]
    if engine:
        cmd += ['--engine', engine]
    try:
        _run(cmd, timeout=CRITIC_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    look = json.loads(answer_file.read_text(encoding='utf-8-sig')) if answer_file.is_file() else {}
    _record_usage(project, look, 'Review look')
    when = time.strftime('%Y-%m-%dT%H:%M:%S')
    if look.get('error') or look.get('verdict') != 'targeted':
        review_memory.record_look(memory, key, {'when': when, 'video': str(video), 'project_hash': project_hash,
                                                'engine': look.get('engine'), 'failed': True})
        return None, f"a reviewer couldn't take the one targeted look at the open items: {str(look.get('error') or 'no answer')[:200]}"
    answers = review_memory.look_answers(memory, look, only)
    said = {str(p.get('id')): p for p in look.get('previously') or [] if isinstance(p, dict)}
    rewritten = {}
    for item in items:          # a note quoting words that are gone: closed, or rewritten from the look's words
        if item['id'] in gone and answers.get(item['id']) == 'still_open':
            p = said.get(item['id']) or {}
            rewritten[item['id']] = review_memory.rewrite(item, p.get('now') or p.get('why'), shown)
    asked_change = said.get(CHANGE_ITEM) if change else None
    matched = None
    if asked_change and str(asked_change.get('status') or '').lower() == 'still_open':
        words = str(asked_change.get('why') or 'something is broken')[:300]
        # one finding per defect: the look's words name an open note again (the same moment and kind) -> that note
        # carries them, at the change's severity, instead of a second finding
        matched = review_memory.same_defect([i for i in items if answers.get(i['id']) == 'still_open'], words)
        if matched is not None:
            matched['now'] = (review_memory.LOOK_CHANGE + words if str(matched.get('what') or '')
                              .startswith(review_memory.LOOK_CHANGE) else review_memory.rewrite(matched, words, shown))
            if SEVERITIES.index(matched.get('severity') or 'minor') > SEVERITIES.index('major'):
                matched['severity'] = 'major'
        else:
            raised = _finding('critic', 'major', review_memory.LOOK_CHANGE + words,
                              evidence="a reviewer's look at the changed cut", fix=DEFAULT_LOOK_FIX)
            raised['look_when'] = when          # _remember_review names the item it becomes in this look's record
            memory.setdefault('_look_findings', []).append(raised)
    record = review_memory.record_look(memory, key, {
        'when': when, 'video': str(video), 'project_hash': project_hash, 'engine': look.get('engine'),
        'model': look.get('model'), 'answers': answers,
        **({'instead_of_round': True} if instead_of_round else {}),
        **({'text_gone': True} if only is not None else {}),
        **({'rewritten': rewritten} if rewritten else {}),
        **({'change': 'fixed' if str(asked_change.get('status') or '').lower() == 'fixed' else 'still_open'}
           if asked_change else {}),
        **({'change_matched': matched['id']} if matched is not None else {}),
        'why': {str(p.get('id')): str(p.get('why') or '')[:200] for p in look.get('previously') or [] if isinstance(p, dict)}})
    return answers, look_line(record)


DEFAULT_LOOK_FIX = ('Look at that moment with letitedit_check_frames and letitedit_hear, change it with '
                    'letitedit_timeline_apply (or undo the change with letitedit_timeline_undo), then run the bundle again.')


def look_line(look):
    """What one look did, in a line: what it closed, what it left open and what it found about the change."""
    who = ai_clis.NAMES.get(look.get('engine'), look.get('engine') or 'a reviewer')
    answers = look.get('answers') or {}
    when = ('instead of a second full review' if look.get('instead_of_round') else
            'at notes quoting text this cut no longer shows' if look.get('text_gone') else 'past the round limit')
    closed = [k for k, v in answers.items() if v == 'fixed']
    still = [k for k, v in answers.items() if v != 'fixed']
    parts = ['it closed ' + (', '.join(closed) if closed else 'none of the open items')]
    if still:
        parts.append('still open: ' + ', '.join(still))
    if look.get('change') == 'fixed':
        parts.append('the change since the last review broke nothing it could see')
    elif look.get('change') == 'still_open':
        parts.append(f"the change since the last review: still the problem in {look['change_matched']} (kept as that "
                     'one finding)' if look.get('change_matched') else
                     f"new: {look.get('raised') or 'one problem'} the change made")
    else:
        parts.append('it was asked only about the open items, so it found nothing new')
    return f"One targeted look {when}, by {who}: " + '; '.join(parts) + '.'


def _record_critic_usage(project, review_file):
    """The critic is a separate run of the person's AI: its token use goes in the project's background calls
    (hooks.record_background_call), so the run's cost (run_cost) counts it. A critic that gave no usage (Codex's plain
    answer) is recorded as not measured; no review, no line. Never fails the review."""
    try:
        review = json.loads(Path(review_file).read_text(encoding='utf-8-sig')) if project and review_file and \
            Path(review_file).is_file() else None
    except (OSError, ValueError, TypeError):  # a cost line, never a reason to lose the review
        return
    _record_usage(project, review, 'Review critic')


def run_critic(cmd, out, timeout=CRITIC_TIMEOUT):
    """Run the critic for this export; returns review.json's path. An older review in the same folder is about an older
    video, so it goes first and can't stand in for a run that failed."""
    review = Path(out) / 'review.json'
    review.unlink(missing_ok=True)
    try:
        _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    return review


def _measure_export(gate, video, kind, out, ctx, target, project, preview_of, findings, cover):
    """Run the technical gate and record its coverage, keeping stale measurements out."""
    args = [sys.executable, GATE, video, '--kind', kind, '--out', out] + gate_args(ctx)
    if target:
        args += ['--target-s', target]
    if project:
        args += ['--project', project]
    if preview_of:
        args += ['--full-size', f'{preview_of[0]}x{preview_of[1]}']
    old_checks = out / 'checks.json'
    if old_checks.exists():
        old_checks.unlink()          # never read a previous run's measurements as this one's
    gate_run = _run(args, timeout=3600, heavy=True)
    checks = json.loads((out / 'checks.json').read_text(encoding='utf-8-sig')) if (out / 'checks.json').exists() else None
    if checks:
        findings += gate_findings(checks)
        off = checks.get('off') or []
        cover('technical measurements', 'done',
              f"{len(checks['checks'])} checks for a {checks.get('mode', ctx['mode'])} {kind} (driver "
              f"{checks.get('driver') or 'default'}, {checks.get('deliverable', ctx['deliverable'])} loudness"
              + (f", platforms {', '.join(checks.get('platforms') or [])}" if checks.get('platforms') else '')
              + '): length, size, loudness and true peak, cuts, holds, silences, first speech; pace checks are '
              'advisory unless the brief or a reference sets the tempo'
              + (f"; not judged for this video: {', '.join(o['check'] for o in off)}" if off else '')
              + (f"; {'; '.join(ctx['notes'])}" if ctx['notes'] else ''), required=True)
    else:
        cover('technical measurements', 'failed', 'the gate did not run: '
              + ((gate_run.stderr or gate_run.stdout or '').strip().splitlines() or ['no output'])[-1][:300],
              required=True)
    return checks


def _craft_findings(project, video, findings, cover, out=None, brief_data=None):
    """T346, behind its switch (craft_checks.enabled, on by default): an insert held too briefly to read, how busy
    the opening picture is against the rest, and the picture after the last word, as measured facts and findings.
    Its numbers go to the critic beside the gate's (craft_checks.FACTS_FILE in the review folder). T349, behind the
    same switch: the picture under the words (a camera move nobody can read under a line, above all one that points
    at something) and b-roll in the footage the cut never shows (picture_words). T361, the same switch: a shot under
    0.3 s between two cuts (craft_checks.slivers, in its findings) and, in a layout that shows the footage in a
    window, the subject of a shot at the window's edge where the source runs on (window_edge)."""
    import letitedit.review.craft_checks as craft_checks
    facts_file = Path(out) / craft_checks.FACTS_FILE if out else None
    if facts_file is not None and facts_file.exists():
        facts_file.unlink()          # never read a previous review's numbers as this one's
    if not craft_checks.enabled():
        return
    numbers = {}
    try:
        import letitedit.review.checks as project_checks
        rows, facts, numbers = craft_checks.findings(project, video, project_checks.FFMPEG, numbers=True)
        for f in rows:
            findings.append({**_finding('project', f['severity'], f['what'], f['at'], fix=f['fix']), 'check': f['check']})
        cover('craft facts', 'done', facts)
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        cover('craft facts', 'failed', f'{type(e).__name__}: {e}'[:300])
    try:
        import letitedit.review.picture_words as picture_words
        rows, facts, more = picture_words.review(project, video, brief_data)
        for f in rows:
            findings.append({**_finding('project', f['severity'], f['what'], f['at'], fix=picture_words.options(f['check'])),
                             'check': f['check'], **({'until_s': f['t1']} if f.get('t1') is not None else {})})
        numbers.update(more)
        cover('picture under the words', 'done', facts)
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        cover('picture under the words', 'failed', f'{type(e).__name__}: {e}'[:300])
    try:
        import letitedit.review.window_edge as window_edge
        rows, facts, more = window_edge.review(project)
        for f in rows:
            findings.append({**_finding('project', f['severity'], f['what'], f['at'], fix=f['fix']),
                             'check': f['check'], 'until_s': f['t1']})
        numbers.update(more)
        cover('subject at a window edge', 'done', facts)
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        cover('subject at a window edge', 'failed', f'{type(e).__name__}: {e}'[:300])
    try:
        numbers.update(craft_checks.measured_music(project))
    except Exception as e:  # noqa: BLE001 - the timing map's own figure stands
        cover('music under the voice', 'failed', f'{type(e).__name__}: {e}'[:300])
    if facts_file is not None and numbers:
        facts_file.write_text(json.dumps(numbers, indent=1), encoding='utf-8')


def _overlay_findings(project, video, findings, cover, out=None):
    """T352, behind its switch (overlay_clash.enabled, on by default): the overlay words letitedit adds to each
    delivered file after the export, where each goes (the Studio's boxes beside the project) as facts, and each box
    that lies over the video's own text or graphics as a measured finding. The review judges what the person posts.
    The boxes go to the critic beside the gate's numbers (overlay_clash.FACTS_FILE in the review folder)."""
    import letitedit.review.overlay_clash as overlay_clash
    facts_file = Path(out) / overlay_clash.FACTS_FILE if out else None
    if facts_file is not None and facts_file.exists():
        facts_file.unlink()          # never read a previous review's boxes as this one's
    if not overlay_clash.enabled() or not overlay_clash.boxes_file(project):
        return
    try:
        rows, facts, numbers = overlay_clash.findings(project, video)
        for f in rows:
            findings.append({**_finding('project', f['severity'], f['what'], f['at'], fix=f['fix']),
                             'check': f['check'], 'until_s': f['t1'], 'plain': f.get('plain', ''), 'overlay': f.get('overlay')})
        cover('overlay words after the export', 'done', facts)
        if facts_file is not None and numbers:
            facts_file.write_text(json.dumps(numbers, indent=1, ensure_ascii=False), encoding='utf-8')
    except Exception as e:  # noqa: BLE001 - a check that can't run is said, never a pass
        cover('overlay words after the export', 'failed', overlay_clash.no_paths(f'{type(e).__name__}: {e}')[:300])


def _check_project(project, video, cues, brief_data, kind, findings, cover, out=None):
    """Check the editable project and collect its visible text, preserving partial results."""
    # the project: words cut at clip edges, graphics over captions, the captions' text
    timeline, captions = None, None
    if project:
        try:
            import letitedit.review.checks as project_checks
            timeline, _ = project_checks.resolve(project)
            captions = '\n'.join(text for cues_ in timeline.subtitle_feeds.values() for _, _, text in cues_)
            captions = '\n'.join(t for t in (captions, onscreen_text(project)) if t)
            try:
                pins = project_checks.edge_pins(project)
            except Exception:  # noqa: BLE001 - no pins read: the findings stand as measured
                pins = {}
            tag = {'check': 'cut_words'} if review_order.enabled() else {}    # the review order tells these apart
            findings += cut_word_findings(project_checks.cut_words(project), pins, tag)
            talk = project_checks.talk_kind(project, brief_data)
            for f in project_checks.ending_findings(project, talk[0] == 'natural' and kind != 'short'):
                findings.append(_finding('project', f['severity'], f['problem'], f['at']))
            _craft_findings(project, video, findings, cover, out, brief_data)
            _overlay_findings(project, video, findings, cover, out)
            restarts = project_checks.false_starts(project)
            # one restart found by both is said once
            spoken = [f for f in project_checks.spoken_restarts(cues or [])
                      if not any(abs(f['at'] - r['at']) < 6 for r in restarts)]
            findings += restart_findings(project, restarts, talk, spoken if talk[0] == 'natural' else ())
            if talk[0] != 'natural':
                findings += [_finding('project', 'major', f['problem'], f['at']) for f in spoken]
            for f in project_checks.edit_quality_findings(project):
                findings.append(_finding('project', f.get('severity', 'major'), f['problem'], f['at']))
            for msg, frame in project_checks.graphic_caption_collisions(timeline):
                findings.append(_finding('project', 'major', msg, frame / timeline.fps))
            changed, how = export_freshness(project, video)
            cover('project checks', 'done', 'words cut at clip edges (and their tails), restarts left in the cut, the last line running on in the source (and, in a long talk video, a goodbye in the source left out just after the cut), caption grouping and face placement, effect timing and overlap'
                  + ('' if changed is not None else f'; whether the project changed after this export: {how}'))
            if changed:
                findings.append(_finding('freshness', 'major', 'the project changed after this export',
                                         fix='export again before judging'))
        except Exception as e:  # noqa: BLE001
            cover('project checks', 'failed', f'{type(e).__name__}: {e}')
    else:
        cover('project checks', 'not done', 'no project given (cut words, caption collisions)')
    return timeline, captions


def _project_credits(project, cover):
    """Record the library credits owed by the project."""
    # the credit lines the video owes for library assets it uses (Google's Noto animated emoji: CC BY 4.0)
    credits = None
    if project:
        try:
            import letitedit.catalogs.assets as assets
            import letitedit.review.checks as project_checks
            credits = assets.project_credits(project_checks.resolve(project)[1])
            cover('credits', 'done', f'{len(credits)} credit line(s) owed: put them in the description' if credits
                  else 'no library asset in the project owes a credit line')
        except Exception as e:  # noqa: BLE001
            cover('credits', 'failed', f'{type(e).__name__}: {e}')
    else:
        cover('credits', 'not done', 'no project given (credit lines owed for library assets)')
    return credits


def _check_motion(project, video, out, portrait, preview_of, gate, findings, errors, cover):
    """Measure motion and graphics; failed measurements leave the rest of the review intact."""
    # motion and graphics, event by event: density, landing on the word, reading time, elements at once, impact
    # sounds on their picture, stutter and flashes on the export; a dense video's reviewer also gets frame-by-frame
    # strips around every arrival and exit and full-size frames of its words on screen
    motion = None
    if project and Path(project).is_file():
        try:
            import letitedit.review.dense as dense
            motion = dense.analyse(project, video, out)
            for f in motion['findings']:
                findings.append(_finding('motion', f['severity'], f"{f['check']}: {f['problem']}", f['at']))
            if motion['dense'] and motion['text_moments']:
                try:
                    motion['text_frames'] = (engine_detail_page(project, motion['text_moments'], out / 'text-frames.jpg', portrait)
                                             if preview_of else
                                             detail_page(gate.FFMPEG, video, motion['text_moments'], out / 'text-frames.jpg', portrait))
                except Exception as e:  # noqa: BLE001 - the strips and pages stand
                    errors.append(f'text frames: {type(e).__name__}: {e}'[:300])
            cover('motion and graphics', 'done',
                  f"{motion['events_per_s']} events a second ("
                  + ', '.join(f'{v} {k}' for k, v in motion['counts'].items()) + ')'
                  + ('; a dense video: the reviewer saw every frame around each arrival and exit'
                     + (' and full-size frames of the words on screen' if motion.get('text_frames') else '')
                     if motion['dense'] else '')
                  + f"; measured: {', '.join(motion['measured'])}"
                  + (f"; not measured: {', '.join(m for m in motion['not_measured'] if 'feel' not in m)}"
                     if len(motion['not_measured']) > 1 else '') + ' (motion-timing.md)')
        except Exception as e:  # noqa: BLE001 - a review without these checks is still a review
            cover('motion and graphics', 'failed', f'{type(e).__name__}: {e}'[:300])
    cover('feel of motion and sound', 'not done', 'no code judges how the motion and the sound feel (smoothness, '
          'weight, whether a hit lands): watch it with the sound on')
    return motion


def _check_timing(video, out, checks, project, cover):
    """Measure edit rhythm and music synchronization for the review."""
    # timing: rhythm map and music sync of the export, measured frame by frame
    timing_images = []
    try:
        shots_seen = (checks or {}).get('shot_changes') or {}
        music = music_possible(project)
        tf, timing_images = timing_facts(video, out, shots_seen.get('project_cuts'), music=music)
        s = (tf['map'] or {}).get('summary') or {}
        cover('timing', 'done', f"rhythm map{' and music sync' if 'sync' in tf else ''}"
              f"{'' if music else ' (no music in the project, so no beats measured)'}: {s.get('cuts')} cuts, "
              f"{s.get('cut_rate_per_min')} a minute, median shot {s.get('median_shot_s')} s, on action "
              f"{s.get('cuts_on_action_share')}"
              + (f", on the beat {s['cuts_on_beat_share']}" if 'cuts_on_beat_share' in s else '')
              + (f"; {shots_seen['added_from_project']} of the cuts come from the project's clips (a jump cut on a person who stays in "
                 "frame doesn't show as a picture change)" if shots_seen.get('added_from_project') else '')
              + '; measures only, the judgment is the reviewer\'s (timing.json)')
    except Exception as e:  # noqa: BLE001 - a review without timing is still a review
        cover('timing', 'failed', f'{type(e).__name__}: {e}'[:300])
    return timing_images


def _timeline_said(project):
    """(words, complete): the editing transcript's words on the project's timeline, in its time, and whether every
    clip with sound on a speech track had its words transcribed; (None, False) without a project or a readable one.
    Only words already transcribed are read: it never runs the speech model. Placing them uses each source's voice
    times (music.voice_times): cached per file, but measured for a source that has words and none yet, which is a
    decode of its sound with ffmpeg and the Silero voice detector on the CPU. That step takes no PC lock, as no
    voice-times measurement does (it is no render and no GPU model)."""
    if not project:
        return None, False
    try:
        import letitedit.timeline.edit_script as es
        import letitedit.timeline.timeline_speech as timeline_speech
        missing = []
        return timeline_speech.timeline_words(es.read(project), cached_only=True, missing=missing), not missing
    except Exception:  # noqa: BLE001 - no words: hearing is judged from the review's own transcript alone
        return None, False


def _check_hearing(brief_result, deaf, cover):
    """Name the speech check when the review couldn't hear the video, or a stretch of its talk: the why is technical
    (for not_checked and the log), the plain sentence is the person's."""
    if not deaf:
        return
    unheard = (brief_result or {}).get('unheard') or []
    why = deaf['why'] + ('; nothing said in the video was checked' if deaf.get('whole')
                         else '; what is said there was not checked')
    if unheard and not deaf.get('whole'):
        why += '; the brief asks for ' + ', '.join(f"\"{u['requirement']}\"" for u in unheard[:4]) + ' there'
    cover('speech', 'not done', why, required=True, plain=deaf.get('plain') or '')


def _check_brief(brief_data, project, cues, duration, kind, timeline, captions, info, findings, cover, said=None,
                 deaf=None, said_complete=False):
    """Check the written requirements against the exported words and project."""
    # the brief
    brief_result = None
    if brief_data:
        import letitedit.review.brief_check as brief_check
        written_from = None
        if project:
            import letitedit.looks.look_inputs as look_inputs
            if look_inputs.no_footage(project):
                written_from = look_inputs.about_text(look_inputs.read(project))
        brief_result = brief_check.check(brief_data, cues or [], duration, kind, timeline, captions, _editor_words(timeline),
                                         written_from=written_from, fps=info.get('fps') or 30.0, said=said, deaf=deaf,
                                         said_complete=said_complete, transcript_ran=cues is not None)
        findings += brief_findings(brief_result)
        cover('brief', 'done', f"{brief_result['counts']['pass']} kept, {brief_result['counts']['fail']} broken, "
              f"{brief_result['counts']['unknown']} for the reviewer", required=True)
    else:
        cover('brief', 'not done', 'no brief found (brief.json next to the project, a journal note, or brief=)',
              required=True)
    return brief_result


def _check_look(project, video, out, brief_data, findings, cover):
    """Record pre-export, Look completeness and supplied-media checks in order."""
    # what the person gave the Look up front (T64): no "style" picture in the video, every "show" file used or explained
    if project:
        preexport_look = []
        try:
            import letitedit.timeline.export_checks as export_checks
            preexport = export_checks.read(project)
            preexport_look, others = preexport_split(preexport)
            for finding in others:
                findings.append(_finding('pre-export checks', 'major', finding['problem']))
            cover('pre-export checks', *preexport_coverage(preexport, saved_summary(out / 'pre-export-checks.json',
                                                                                     preexport)), required=True)
        except Exception as error:
            findings.append(_finding('pre-export checks', 'major', f'Pre-export findings unavailable: {error}'))
        try:
            import letitedit.looks.look_check as look_check
            result = look_check.check(project, look=(brief_data or {}).get('look'), video=video)
            faults, record = look_rows(result)
            findings += faults
            summary = saved_summary(out / 'look-check.json', result)
            if record:
                summary = f"{summary}; {record} receipt note(s) on the AI's record, not faults in the video"
            cover('look completeness', 'done' if result.get('passed') else 'not done', summary,
                  required=result.get('applicable', False))
        except Exception as error:
            findings.append(_finding('look completeness', 'major', f'Look check unavailable: {error}'))
            cover('look completeness', 'failed', str(error), required=True)
            # the review couldn't run it again: what the export's own run found stands
            findings += [_finding('pre-export checks', 'major', finding['problem']) for finding in preexport_look
                         if finding.get('severity', 'major') in ('critical', 'major')]

    if project and str(project).lower().endswith('.mlt') and Path(project).is_file():
        try:
            import letitedit.looks.look_inputs as look_inputs
            given = look_inputs.check(project, video)
            if given['has_inputs']:
                findings += look_inputs.findings(given, _finding)
                (out / 'look-inputs.json').write_text(json.dumps(given, indent=1, default=str), encoding='utf-8')
                cover('look inputs', 'failed' if given.get('export_check_error') else 'done',
                      look_inputs.coverage_detail(given) + '. ' + look_inputs.CANT_CATCH)
        except Exception as exc:  # noqa: BLE001 - a review without this check is still a review
            cover('look inputs', 'failed', f'{type(exc).__name__}: {exc}'[:300])


def _check_posted_song(project, video, out, findings, cover):
    """Check a song that will be added when posting and record its evidence."""
    # T72: a song the person adds when posting. Measured: it must not be in this file; its beats, not its level, count.
    guide = None
    if project and Path(project).is_file():
        try:
            import letitedit.sound.guide_song as guide_song
            guide = guide_song.review_facts(project, video)
        except Exception as exc:  # noqa: BLE001 - a review without this check is still a review
            cover('song stays out', 'failed', f'{type(exc).__name__}: {exc}'[:300])
        if guide:
            (out / 'song-added-when-posting.json').write_text(json.dumps(guide, indent=1, default=str), encoding='utf-8')
            m = guide.get('song_in_file') or {}
            cover('song stays out', 'done' if m.get('proven') else 'failed',
                  ('the song IS in this file' if m.get('song_found') else 'the song was not found in this file')
                  + f" (score {m.get('score')}, found at {m.get('found_at')}; with the song mixed in on purpose it scores "
                  f"{m.get('controls')}, so this check catches it down to {m.get('catches_down_to_db')} dB against the file). "
                  f"Cuts on its beats: {guide.get('cuts_on_beats')}.")
            if m.get('song_found'):
                findings.append(_finding('song', 'critical', 'The song the person adds when posting is in this file, so it would '
                                         'play twice and carries its rights problems with it.', evidence=str(m),
                                         fix='letitedit_export(project) leaves it out; export again and review the new file.'))
            elif m.get('proven') is False:
                findings.append(_finding('song', 'major', "Couldn't prove the song is out of this file: the check didn't find it "
                                         'even when it was mixed in on purpose.', evidence=str(m),
                                         fix='letitedit_song(mode=finish) and read song_in_upload.'))
            for p in guide.get('problems') or []:
                findings.append(_finding('song', 'major', f'A phone app could not reproduce the song as placed: {p}.',
                                         fix='letitedit_song(mode=place) lays it again in one piece from the start.'))
    return guide


def _record_used_assets(project, out, cover):
    """List the personal assets actually used in the video."""
    # My assets (T69; 4 Nov: an organising space, no promise either way): which of the person's own files the
    # video uses, when it uses any. A fact for the person, never a finding, and nothing about what it left out.
    try:
        import letitedit.catalogs.my_assets as my_assets
        used = my_assets.used_in(project) if project and Path(project).is_file() else []
        if used:
            (out / 'my-assets.json').write_text(json.dumps({'used': used}, indent=1), encoding='utf-8')
            cover('my assets', 'done', 'in the video: ' + ', '.join(f"{u['id']} ({u['kind']})" for u in used))
    except Exception as exc:  # noqa: BLE001 - a review without this line is still a review
        cover('my assets', 'failed', f'{type(exc).__name__}: {exc}'[:300])


def _check_story(project, brief, out, kind, stage_progress, cues, duration, brief_data, findings, cover, said=None,
                 deaf=None):
    """Check the selected story and payoff plan for a Short."""
    # A first cut must keep the story chosen before the rough edit. The brief's
    # target can be AI chosen, so checking only that mutable target missed a thin Short.
    plan_path = story_plan_path(project, brief, out)
    story_result = None
    if kind == 'short' and (stage_progress is not None or plan_path):
        if plan_path:
            import letitedit.review.story_integrity as story_integrity
            try:
                story_result = story_integrity.check(json.loads(plan_path.read_text(encoding='utf-8-sig')),
                                                     cues or [], duration, kind, brief_data, said=said, deaf=deaf)
                findings += [_finding('story', f['severity'], f['what'], f['at_s'], f['evidence'], f['fix'])
                             for f in story_result['findings']]
                missing = story_result['missing']
                cover('story integrity', 'not done' if missing else 'done',
                      '; '.join(missing) if missing else 'selected length and payoff plan checked; '
                      + ('; '.join(story_result['review']) if story_result.get('review')
                         else 'exact payoff and spoken ending checked'),
                      required=stage_progress is not None)
            except (OSError, ValueError, TypeError) as exc:
                cover('story integrity', 'failed', f'{type(exc).__name__}: {exc}',
                      required=stage_progress is not None)
        else:
            cover('story integrity', 'not done', 'first-cut story_plan.json is missing', required=True)
    return plan_path, story_result


def _critic_boundaries(gate, project, duration, info, video, out, portrait, page_list, cover):
    """Add the outgoing cut frames to the evidence shown to the critic."""
    cuts, cut_note = gate.project_cuts(project, duration)
    boundaries = boundary_moments(cuts, duration, info.get('fps'))
    boundary_files = []
    for start in range(0, len(boundaries), 8):
        batch = boundaries[start:start + 8]
        picture = detail_page(gate.FFMPEG, video, batch, out / f'boundaries-{start // 8 + 1:02d}.jpg', portrait)
        if picture:
            boundary_files.append(picture)
            page_list.append({'file': picture, 'from_s': batch[0][0], 'to_s': batch[-1][0],
                              'purpose': 'outgoing frames: text/logo completeness'})
    cover('outgoing frames', 'done' if boundary_files else 'failed',
          f'{len(boundaries)} cut/end moments; {cut_note}', required=True)


def _write_critic_bundle(video, kind, page_list, out, brief_data, checks, plan, timing_images, findings, motion,
                         cues=(), deaf=None, talk='unknown'):
    """Write measured evidence before the critic is started: this render's transcript (none when it has none) and,
    as 'hearing', whether the review heard its speech (all, part or none, with the stretches it didn't), whether its
    transcript ran, and whether the timeline's own words have talk ('yes', 'no', or 'unknown' when not all known)."""
    partial = {'video': str(video), 'kind': kind, 'pages': page_list,
               'transcript': str(out / 'transcript.srt') if cues is not None and (out / 'transcript.srt').is_file()
               else None,
               'hearing': {**({'heard': 'none' if deaf.get('whole') else 'part', 'unheard': deaf.get('unheard') or []}
                              if deaf else {'heard': 'all', 'unheard': []}), 'ran': cues is not None, 'talk': talk},
               'brief': brief_data, 'checks': checks, 'story_plan': str(plan) if plan else None,
               'timing_images': timing_images}
    # what the code measured, so a reviewer never redoes it (the panel's reviewers get the list)
    partial['code_findings'] = [{'at': f.get('at_s'), 'what': str(f.get('what'))[:200]} for f in findings][:120]
    if motion:
        partial['motion_summary'] = {'dense': motion['dense'], 'events_per_s': motion['events_per_s'],
                                     'arrivals': motion['counts'].get('arrivals and exits', 0) > 0}
    if motion and motion['dense']:
        partial['motion'] = {'sheet': motion.get('sheet'), 'strips': motion.get('strips') or [],
                             'text_frames': motion.get('text_frames'), 'events_per_s': motion['events_per_s']}
    (out / 'review_bundle.json').write_text(json.dumps(partial, indent=1, default=str), encoding='utf-8')


def _write_critic_brief(out, brief_data, project, guide):
    """Write the brief, chosen Look and supplied-media constraints for the critic."""
    brief_file = out / 'brief-for-critic.json'
    for_critic = dict(brief_data or {})
    look_id = for_critic.get('look')
    if look_id and look_id not in ('auto', 'none'):   # the chosen Look's recipe, so the critic judges against it
        try:
            import letitedit.looks.looks as looks
            for_critic['look_recipe'] = looks.read(str(look_id))['recipe_text']
        except Exception:  # noqa: BLE001 - a Look that is no longer offered just leaves the field out
            pass
    if project:     # what the person gave the Look: the critic doesn't ask for what the Look forbids
        try:
            import letitedit.looks.look_inputs as look_inputs
            given_text = look_inputs.describe(look_inputs.read(project))
            if given_text:
                for_critic['look_inputs'] = given_text
                for_critic['look_inputs_note'] = (
                    'Roles: about = the brief; show = files that may appear on screen; style = pictures the person '
                    'wants the FEEL of, which must never appear in the video (do not ask for them to be shown); '
                    "voiceover = the person's own voice (empty means a voice on this PC read the AI's script); "
                    'product / person = the subject. Nothing was asked of the person after they pressed Go, so do '
                    'not list a missing answer as a question for them.')
        except Exception:  # noqa: BLE001
            pass
    if for_critic.get('preferences'):
        for_critic['preferences_note'] = PREFERENCES_NOTE
    if guide:
        import letitedit.sound.guide_song as guide_song
        for_critic['song_added_when_posting'] = guide_song.CRITIC_NOTE
    brief_file.write_text(json.dumps(for_critic, indent=1), encoding='utf-8')
    return brief_file


def _call_critic(video, kind, brief_file, out, engine, plan, project, memory):
    """Start the critic with the brief, evidence and previous review notes."""
    cmd = [sys.executable, CRITIC, video, '--kind', kind, '--brief', brief_file, '--out', out,
           '--bundle', out / 'review_bundle.json']
    if engine:
        cmd += ['--engine', engine]
    if plan:
        cmd += ['--story-plan', plan]
    if project:
        cmd += ['--project', project]
    notes = review_memory.for_critic(memory)
    if notes:
        (out / 'review-memory-for-critic.txt').write_text(notes, encoding='utf-8')
        cmd += ['--memory', out / 'review-memory-for-critic.txt']
    critic = run_critic(cmd, out)
    return critic


def _review_evidence(duration, findings, timeline, detail_max, preview_of, project, gate, video, out, portrait, errors):
    """Make detail frames, motion strips and listening excerpts around the findings."""
    # bigger pictures where it matters
    moments = [(0.5, 'opening'), (duration / 2, 'middle'), (max(0.0, duration - 0.6), 'ending')]
    moments += [(f['at_s'], f"{f['source']}: {f['what'][:40]}") for f in findings if f['at_s'] is not None]
    if timeline is not None:
        starts = sorted({round(s, 2) for cues_ in timeline.subtitle_feeds.values() for s, _, _ in cues_})
        for s in starts[::max(1, len(starts) // 6)][:6]:
            moments.append((s + 0.4, 'caption'))
    moments = sorted({round(t, 1): (t, why) for t, why in moments if 0 <= t < duration}.values())[:detail_max]
    details = None
    if preview_of and project:
        try:
            details = engine_detail_page(project, moments, out / 'details.jpg', portrait)
        except Exception as e:  # noqa: BLE001 - the preview's own frames stand in, said so
            errors.append(f'full-size details: {type(e).__name__}: {e}'[:300])
    if details is None:
        details = detail_page(gate.FFMPEG, video, moments, out / 'details.jpg', portrait)
    (out / 'strips').mkdir(exist_ok=True)
    strips = [strip(gate.FFMPEG, video, 0, min(3.0, duration), out / 'strips' / 'opening.jpg'),
              strip(gate.FFMPEG, video, max(0.0, duration - 3.0), min(3.0, duration), out / 'strips' / 'ending.jpg')]
    flagged = sorted((f for f in findings if f['at_s'] is not None), key=lambda f: SEVERITIES.index(f['severity']))
    for i, f in enumerate(flagged[:3]):          # the worst flagged moments first
        strips.append(strip(gate.FFMPEG, video, max(0.0, f['at_s'] - 1.5), 3.0, out / 'strips' / f'flag-{i + 1}.jpg'))
    (out / 'excerpts').mkdir(exist_ok=True)
    excerpts = [excerpt(gate.FFMPEG, video, 0, min(8.0, duration), out / 'excerpts' / 'opening.mp4'),
                excerpt(gate.FFMPEG, video, max(0.0, duration - 8.0), min(8.0, duration), out / 'excerpts' / 'ending.mp4')]
    return details, strips, excerpts


def _check_sound_and_words(gate, video, info, duration, out, findings, cover, why=None, plain=None):
    """Read the exported speech and measure sound, keeping tone-scan failures local. why: a list that gets the reason
    there is no transcript, when there is none (plain: the same in plain words)."""
    # sound and words
    why = [] if why is None else why
    (Path(out) / 'transcript.srt').unlink(missing_ok=True)      # a video with no sound: no earlier round's words either
    sil = gate.silences(video) if info['has_audio'] else []
    audio_png = level_graph(gate.FFMPEG, video, duration, sil, out / 'audio.png') if info['has_audio'] else None
    cues = transcript(gate, video, out, why, plain) if info['has_audio'] else []
    cover('transcript', 'done' if cues is not None else 'failed',
          f'{len(cues or [])} cues over the whole video (local whisper; names and numbers can be misheard)'
          + (f"; no transcript: {'; '.join(why)}" if cues is None and why else ''))
    if info['has_audio']:
        try:
            import letitedit.sound.tonal_check as tonal_check
            tones = tonal_check.scan_file(video)
            tones['flagged'] = tonal_check.flagged(tones)
            (out / 'tones.json').write_text(json.dumps(tones, indent=1), encoding='utf-8')
            if tones['flagged']:
                findings.append(_finding('sound', 'major', tonal_check.summary_line(tones, 'the finished sound'),
                                         tonal_check.held(tones)[0]['start_s'], f"tones.json: {tones['seconds_flagged']:g} s in "
                                         f"{len(tones['events'])} stretches",
                                         'a different song or section, unless the Look or the person wants that sound'))
            cover('whistle-like tones', 'done', f"{len(tones['events'])} sustained narrow tone(s), "
                  f"{tones['seconds_flagged']:g} s ({tones['share']:.0%}); " + ('flagged' if tones['flagged'] else 'not flagged'))
        except Exception as e:  # noqa: BLE001
            cover('whistle-like tones', 'failed', str(e)[:200])
    return audio_png, cues


def _last_round_time(project):
    """When the video's last full review round ran (local time, as review_memory keeps it), or None."""
    try:
        rounds = review_memory.load(project, None).get('rounds') or []
        return datetime.datetime.strptime(rounds[-1]['when'], '%Y-%m-%dT%H:%M:%S') if rounds else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _after(journal_time, local):
    """True when a journal time (UTC, '...Z') is after a local time: an edit made since that review round."""
    try:
        utc = datetime.datetime.strptime(str(journal_time), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return False
    return utc.astimezone().replace(tzinfo=None) > local


def _recent_changes(project):
    """The edits the person's "what changed" line names (the last three): every edit since the last full review
    round, whatever its label; before any round, the ones labelled as fixes."""
    import letitedit.timeline.project_journal as project_journal
    last_round = _last_round_time(project)
    return [e['label'] for e in project_journal.entries(project, None)
            if e.get('kind') == 'apply' and e.get('label')
            and (_after(e.get('time'), last_round) if last_round else
                 re.search(r'\b(fix|restore|clean|correct|repair|recaption)\b', e['label'], re.I))][-3:]


def _firstcut_progress(project, checks, ctx, brief_data, findings, cover):
    """Record first-cut stage progress and replace the generic static-shot finding when appropriate."""
    stage_progress = None
    recent_changes = []
    if project and 'first cut' in Path(project).stem.lower():
        import letitedit.timeline.project_journal as project_journal
        stage_progress = project_journal.stage_progress(project)
        skipped = [name for name, state in stage_progress.items() if not state['done']]
        cover('first-cut stages', 'not done' if skipped else 'done',
              'missing or unfinished: ' + ', '.join(skipped) if skipped else 'log, story, rough, fine and finish complete',
              required=True)
        recent_changes = _recent_changes(project)
        visual = firstcut_visual_finding(checks, ctx, stage_progress, brief_data, project)
        if visual:
            findings = [f for f in findings if not (f['source'] == 'gate' and
                        f['what'].startswith('longest_static_s'))]
            findings.append(visual)
    return stage_progress, recent_changes, findings


def _read_editorial_review(critic, critic_asked, limit_reached, round_limit, findings, cover, review, reviewer):
    """Read the saved editorial judgment or record precisely why it is unavailable."""
    if critic and Path(critic).exists():
        review = json.loads(Path(critic).read_text(encoding='utf-8-sig'))
        reviewer = ai_clis.reviewer_line(review)
        if review.get('error'):
            cover('editorial review', 'not done' if review.get('error_kind') in NOBODY_COULD else 'failed',
                  str(review.get('error')), required=True)
            review = None
        else:
            findings += critic_findings(review)
            who = ai_clis.NAMES.get(review.get('engine'), review.get('engine', 'a reviewer'))
            if limit_reached:
                reviewer = (f"The review rounds have reached their limit ({round_limit}), so the reviewer's notes are "
                            'from the last round; the measured checks ran again on this export.')
            cover('editorial review', 'done', f"by {who}: verdict "
                  f"{review.get('verdict')}, {len(review.get('problems') or [])} problems; story plan shown: "
                  f"{review.get('story_plan') or 'none found'}", required=True)
    elif critic_asked:     # asked, and it left nothing
        reviewer = 'The review could not finish: the reviewer stopped without an answer. Run it again.'
        cover('editorial review', 'failed', reviewer, required=True)
    elif limit_reached:
        reviewer = f'The review limit ({round_limit}) was reached, but its saved review is unavailable. No new round ran.'
        cover('editorial review', 'not done', reviewer, required=True)
    else:
        cover('editorial review', 'not done', 'no reviewer has judged story, pacing and shots: run with critic="run" '
              'or have a person watch it', required=True)
    return review, reviewer


def reviewed_hash(project, read=None):
    """One hash of the project state this review read, the one a round records and the next call compares with: an
    open window's revision (its timeline now, unsaved changes included: what the review's checks read and the export
    renders), else the saved file's sha256. None without a project, or for a window that gives no revision (the
    review then never takes it for an unchanged one)."""
    if not project or not Path(project).is_file():
        return None
    if (read or {}).get('state') == 'live':
        revision = (read or {}).get('revision')
        return f'window:{revision}' if revision else None
    return hashlib.sha256(Path(project).read_bytes()).hexdigest()


def shown_text(captions, cues):
    """What this cut shows and says, in order: its captions and on-screen words, then what the transcript heard."""
    heard = ' '.join(str(c[2]) for c in cues or [] if len(c) > 2)
    return '\n'.join(t for t in (captions or '', heard) if t)


def _look_at_cut(gate, memory, video, project, kind, out, duration, portrait, page_list, engine, project_hash, critic,
                 shown, cover):
    """Past the round limit: a cut no reviewer saw (review_memory.cut_unseen: neither a round nor an answered look read
    this project state) gets a look of its own (review_memory.can_look_cut: one per changed cut, LOOK_LIMIT in all),
    at the open notes, the notes quoting words that are gone and the change as a whole. Returns (why no reviewer saw
    this cut, or None when one did, the look's answers or None)."""
    if not (critic and project and Path(project).is_file()):
        return None, None
    if not review_memory.cut_unseen(memory, project_hash, Path(project).stat().st_mtime, Path(critic).stat().st_mtime):
        return None, None
    stale = (f"the reviewer's notes are from review round {review_memory.rounds_done(memory)}"
             + (' and a look' if any(not e.get('failed') for e in review_memory.looks(memory)) else '')
             + ', on an earlier cut')
    window = str(project_hash or '').startswith('window:')    # the window's own state: what render= exports
    if not window and video.stat().st_mtime < Path(project).stat().st_mtime - 2:
        why = 'this export is older than the project, so a look would see an older cut (export again)'
        cover('targeted look', 'not done', f'no look at this cut: {why}')
        return f'{stale}, and {why}', None
    may, why_not = review_memory.can_look_cut(memory, project_hash)
    if not may:
        cover('targeted look', 'not done', f'no look at this cut: {why_not}')
        return f'{stale}, and {why_not}', None
    gone = review_memory.text_gone(memory, shown)
    answers, note = targeted_look(gate, memory, video, project, kind, out, duration, portrait, page_list, engine,
                                  gone=gone, change=change_item(project), project_hash=project_hash, shown=shown)
    cover('targeted look', 'done' if answers is not None else 'failed', note)
    if answers is None:
        return f'{stale}, and the look at this cut gave no answer ({note})', None
    return None, answers


def _check_note_targets(project, duration, findings, cover):
    """A revision's notes with a measurable target (note_targets: a length, the music's level, the captions' size),
    measured on this cut against what the note asked: a miss beyond the tolerance is a major finding the AI fixes
    before hand-over. Returns the checks ([] when the project's notes name none)."""
    if not (project and str(project).lower().endswith('.mlt') and Path(project).is_file()):
        return []
    import letitedit.review.note_targets as note_targets
    if not note_targets.kept(project):
        return []
    try:
        import letitedit.timeline.edit_script as es
        checked = note_targets.check(project, es.read(project), duration)
    except Exception as exc:  # noqa: BLE001 - a review without this check is still a review
        cover('note targets', 'failed', f'{type(exc).__name__}: {exc}'[:300], required=True)
        return []
    findings += note_targets.findings(checked)
    missed = [c for c in checked if c.get('met') is False]
    cover('note targets', 'done', '; '.join(c['line'] for c in checked), required=True,
          plain=('A note asked for something this cut misses: ' + '; '.join(c['line'] for c in missed)) if missed else '')
    return checked


GONE_FIX = ("Look at this moment on this cut with letitedit_check_frames and letitedit_hear, and fix what is still wrong "
            f"there: the reviewer's own fix was for an earlier cut and named {review_memory.GONE_WORDS}.")


def _quotes_gone(findings, shown):
    """A reviewer's note still quoting words this cut no longer shows (no look rewrote it) says so in place of the
    quote in its problem and its evidence, so it never stands as quoted; a fix naming such words was written for an
    earlier cut and gives way to GONE_FIX (fix_gone), so neither the AI nor the person's plain section is told to put
    back words that are gone."""
    for f in findings:
        if f.get('source') == 'critic' and shown:
            for key in ('what', 'evidence'):
                if f.get(key):
                    f[key] = review_memory.without_gone_quotes(f[key], shown)
            if f.get('fix') and review_memory.gone_quotes(f['fix'], shown):
                f['fix'], f['fix_gone'] = GONE_FIX, True
    return findings


def _against_notes(findings, note_checks, duration, memory):
    """A revision's findings that would undo one of the person's notes (note_targets.against: a fix moving a note's
    measured value away from its target, or a finding about the part a note cut): held out of the verdict and of
    What is left, listed apart as settled by the notes, and kept in the memory with status 'note', so no look or
    later round carries them as open. Returns (the findings that stand, the ones held)."""
    if not note_checks:
        return findings, []
    import letitedit.review.note_targets as note_targets
    items = {i.get('id'): i for i in memory.get('items') or []}
    kept, held = [], []
    for f in findings:
        why = note_targets.against(f, note_checks, duration)
        if not why or f.get('owner') == 'person':
            kept.append(f)
            continue
        held.append({**{k: f.get(k) for k in ('id', 'source', 'severity', 'at', 'at_s', 'what', 'fix')}, **why})
        item = items.get(f.get('id'))
        if item is not None and item.get('status') == 'open':
            item.update(status='note', against_note={'note': why['note'], 'asked': why['asked'], 'why': why['why']})
    if held and memory.get('_file'):
        review_memory.save(memory)
    return kept, held


def _may_look(memory, project, project_hash, last_review):
    """Whether the one targeted look per video can be taken now (review_memory.can_look, with a project and a saved review)."""
    if not (project and project_hash and last_review and Path(last_review).is_file() and Path(project).is_file()):
        return False
    return review_memory.can_look(memory, project_hash, Path(project).stat().st_mtime, Path(last_review).stat().st_mtime)


def _remember_review(findings, project, errors, critic_asked, review, memory, video, looked, project_hash,
                     round_facts=None):
    """Reconcile findings and persist the review round before making detail evidence."""
    findings = once_each(findings)
    # who fixes what, how, and what earlier rounds found
    findings = _once(findings)
    for f in findings:
        review_memory.ensure_fix(f)
        f['owner'] = review_memory.who_fixes(f, f.pop('said_owner', None))
    if project:
        try:
            import letitedit.timeline.project_journal as project_journal
            pickups = Path(project_journal.folder(project)) / 'pickups.md'
            if pickups.is_file():
                review_memory.footage_pickups(findings, pickups.read_text(encoding='utf-8', errors='replace'))
        except Exception as e:  # noqa: BLE001 - the findings stand as the reviewer gave them
            errors.append(f'pickups: {type(e).__name__}: {e}'[:300])
    full_round = bool(critic_asked and review)
    try:
        import letitedit.review.picture_words as picture_words
        if picture_words.enabled():
            picture_words.floor(findings)       # T349: a measured picture major sets the critic's floor there
    except Exception as e:  # noqa: BLE001 - the findings stand as the reviewer gave them
        errors.append(f'picture floor: {type(e).__name__}: {e}'[:300])
    findings = review_memory.update(memory, findings, review, full_round, video, looked=looked, project_hash=project_hash,
                                    round_facts=round_facts)
    for f in findings:          # a look's new finding: its record names the item it became (look_line)
        when = f.pop('look_when', None)
        for entry in memory.get('looks') or [] if when else []:
            if entry.get('when') == when and f.get('id'):
                entry['raised'] = f['id']
    if full_round:
        kept = Path(memory['_file']).with_name('last_review.json')
        kept.write_text(json.dumps(review, indent=1), encoding='utf-8')
        memory['last_review'] = str(kept)
    review_memory.save(memory)
    return findings


RENDERS = ('preview', 'final')
RENDER_WAIT_S = 4 * 3600      # the longest this waits for its own export (the AI hears "still working" long before)
RENDER_POLL_S = 3.0
ENDED = ('done', 'failed', 'error', 'cancelled', 'interrupted')


def render_for_review(project, render, wait_s=RENDER_WAIT_S, poll_s=RENDER_POLL_S):
    """The export a review is made on, rendered now and waited for: render='preview' is letitedit_export's preview
    (preview=True), 'final' its full-size final (its defaults, as final=True starts). {job_id, output, preview, seconds};
    an export that doesn't finish raises, naming its job."""
    if render not in RENDERS:
        raise ValueError(f"render is one of {', '.join(RENDERS)}")
    if not project:
        raise ValueError('render needs project= (the timeline to export)')
    import letitedit.timeline.render_queue as render_queue
    t0 = time.monotonic()
    job_id = render_queue.submit(project, preview=render == 'preview')['job_id']
    status = render_queue.status(job_id)
    while status.get('state') not in ENDED and time.monotonic() - t0 < wait_s:
        time.sleep(poll_s)
        status = render_queue.status(job_id)
    if status.get('state') != 'done' or not status.get('output') or not Path(status['output']).is_file():
        raise RuntimeError(f"The {render} export {job_id} is {status.get('state')}: "
                           f"{status.get('error') or status.get('message') or 'no file'}. "
                           f"letitedit_export_job('{job_id}', action='resume') carries it on from the chunks already "
                           'drawn; then review its file with video=.')
    redrawn = status.get('redrawn_alone') or []
    return {'job_id': job_id, 'output': status['output'], 'preview': render == 'preview',
            'seconds': round(time.monotonic() - t0, 1),
            **({'redrawn_alone': redrawn, 'recovered': recovered_line(render, redrawn)} if redrawn else {})}


def recovered_line(render, redrawn):
    """The plain line for an export that drew some of its pieces again on its own (render_queue's one-at-a-time
    retry) and finished: what happened, and that nothing needs redoing."""
    memory = [p.get('piece') for p in redrawn if p.get('why') != 'stalled']
    stalled = [p.get('piece') for p in redrawn if p.get('why') == 'stalled']
    why = ' and '.join(part for part in (
        'the PC ran short of memory drawing its pieces at once' if memory else '',
        'the engine stopped making frames' if stalled else '') if part)
    return (f'The {render} export recovered by itself: {why}, so it drew {len(redrawn)} piece(s) again one at a time '
            f"({', '.join(str(p) for p in memory + stalled)}) and finished. The video is complete; nothing needs "
            'redoing.')


def start_revision(project, revision_of=None):
    """A revision of a finished video gets review rounds of its own (review_memory.start_revision)."""
    return review_memory.start_revision(project, revision_of)


def keep_note_targets(project, notes):
    """A revision's notes with a measurable target, measured on the cut before it and kept for its reviews
    (note_targets.keep). Returns the targets."""
    import letitedit.review.note_targets as note_targets
    return note_targets.keep(project, notes)


def note_target_checks(project, duration=None):
    """The kept targets against the project as it is now (note_targets.check), the export's duration as its length."""
    import letitedit.review.note_targets as note_targets
    import letitedit.timeline.edit_script as es
    if not note_targets.kept(project):
        return []
    return note_targets.check(project, es.read(project), duration)


def unattended(project, on=True):
    """An unattended run starts or ends (review_memory.unattended): while it runs, an edit after the last review said
    hand over is refused when no reviewer look is left for a changed cut."""
    review_memory.unattended(project, on)


def edit_after_handover(project):
    """None, or why an edit is refused now (review_memory.edit_after_handover)."""
    return review_memory.edit_after_handover(project)


def bundle(video=None, kind=None, project=None, brief=None, out=None, critic=None, engine=None, detail_max=16,
           final_of=None, final=False, render=None):
    """_bundle, with the project read as an open letitedit window shows it (checks.as_window_shows): the state its
    export renders, so a join fixed in the window but not yet saved is never measured on the saved file's old cut.
    The result's project_read says which state the project checks read."""
    import letitedit.review.checks as project_checks
    with project_checks.as_window_shows(project) as read:
        return _bundle(video, kind, project, brief, out, critic, engine, detail_max, final_of, final, render, read)


def _bundle(video=None, kind=None, project=None, brief=None, out=None, critic=None, engine=None, detail_max=16,
            final_of=None, final=False, render=None, read=None):
    """Build the review bundle for one export (see the module doc). critic: None (use review.json in out when it is
    newer than the export), 'run' (a separate run of an AI on this PC now, with these pages, until ROUND_LIMIT rounds, then the last
    review is reused), 'again' (one more run past the limit), or a review.json path. final_of: the preview this final
    export was rendered after (final_check.run: the final's technical check against it, in the final's review folder).
    final: on a preview, start the final export of the project (letitedit_export) once the measurements are done, so
    it renders while the critic reads; the result's final_export names its job. render: 'preview' or 'final', with
    project and no video: the export is made first and waited for (render_for_review), then reviewed."""
    rendered = None
    if render:
        if video or final_of:
            raise ValueError('render makes the video to review: give render= or video=, and final_of= only with video=')
        rendered = render_for_review(project, render)
        video = rendered['output']
    if not video:
        raise ValueError("video= (an export to review), or render='preview' | 'final' with project=")
    if final_of:
        import letitedit.review.final_check as final_check
        return final_check.run(video, final_of, project=project, out=out)
    t0 = time.monotonic()
    gate = _gate()
    video = Path(video).resolve()
    if not video.is_file():
        import letitedit.core.long_paths as long_paths
        long_paths.check(video)
        raise FileNotFoundError(f'No video at {video}')
    out = Path(out) if out else video.parent / f'{video.stem} review'
    import letitedit.core.long_paths as long_paths
    long_paths.check(out / 'review-memory-for-critic.txt')
    out.mkdir(parents=True, exist_ok=True)
    info = gate.probe(video)
    duration = info['duration']
    portrait = (info['height'] or 0) > (info['width'] or 0)
    kind = kind or ('short' if portrait and duration <= 180 else 'long')
    preview_of = preview_size_of(video, project, info)
    every = sample_every(duration)
    head = video.read_bytes()[:1 << 20]
    identity = {'file': str(video), 'bytes': video.stat().st_size, 'modified': time.ctime(video.stat().st_mtime),
                'sha1_first_mb': hashlib.sha1(head).hexdigest()}
    coverage, findings, errors = [], [], []

    def cover(name, state, detail='', required=False, plain=''):
        coverage.append({'check': name, 'state': state, 'detail': detail, 'required': required,
                         **({'plain': plain} if plain else {})})

    # pictures of the whole video
    frames = sample_frames(gate.FFMPEG, video, every, 160 if portrait else 256, out / 'frames')
    page_list = pages(frames, out, portrait)
    cover('pictures', 'done' if frames else 'failed',
          f'{len(frames)} frames, one every {every:g} s from 0:00 to {fmt(frames[-1][0]) if frames else "?"} of '
          f'{fmt(duration)}, on {len(page_list)} pages; motion between samples is not seen', required=True)

    # the gate's measurements
    brief_data = None
    try:
        import letitedit.review.brief_check as brief_check
        brief_data = brief_check.load(brief, project)
    except Exception as e:  # noqa: BLE001
        errors.append(f'brief: {e}')
    target = next((d.get('target_s') for d in (brief_data or {}).get('deliverables', [])
                   if d.get('kind') in (None, kind) and d.get('target_s')), None)
    ctx = gate_context(brief_data, kind, gate, project)
    checks = _measure_export(gate, video, kind, out, ctx, target, project, preview_of, findings, cover)

    no_transcript, no_transcript_plain = [], []
    audio_png, cues = _check_sound_and_words(gate, video, info, duration, out, findings, cover, no_transcript,
                                             no_transcript_plain)

    if rendered and rendered.get('recovered'):
        cover('render', 'done', rendered['recovered'])
    if rendered and not rendered['preview']:
        cover('final file', 'done', 'this review is of the full-size final itself, rendered for it from the timeline '
              'as it stands: it is the file to deliver, and no final_of check follows it')
    if preview_of:
        cover('preview', 'done', f"reviewed on a preview the export engine drew at {info['width']}x{info['height']} with the "
              f"final's sound, for a {preview_of[0]}x{preview_of[1]} final: the size checks judge the final's size; the "
              'details page and the Look kit check are full-size frames from the export engine (small text, thin lines, '
              'faces under graphics, the colour grade); the final file gets its own technical check against this '
              'preview (final_of)')
    cover('listening', 'not done', 'no code judges how the mix sounds (pumping, harsh joins, music taste): listen to '
          'excerpts/ or the whole export')

    timeline, captions = _check_project(project, video, cues, brief_data, kind, findings, cover, out)

    stage_progress, recent_changes, findings = _firstcut_progress(project, checks, ctx, brief_data, findings, cover)

    credits = _project_credits(project, cover)

    motion = _check_motion(project, video, out, portrait, preview_of, gate, findings, errors, cover)

    timing_images = _check_timing(video, out, checks, project, cover)

    # did the review hear the video? (its transcript against what the timeline's own words say is there)
    said, said_complete = _timeline_said(project)
    deaf = brief_check.hearing(cues, said, duration, audio=info['has_audio'], wordless=brief_check.wordless(brief_data),
                               why='; '.join(no_transcript), said_complete=said_complete,
                               plain='; '.join(no_transcript_plain))
    brief_result = _check_brief(brief_data, project, cues, duration, kind, timeline, captions, info, findings, cover,
                                said, deaf, said_complete)
    _check_hearing(brief_result, deaf, cover)

    _check_look(project, video, out, brief_data, findings, cover)

    guide = _check_posted_song(project, video, out, findings, cover)

    _record_used_assets(project, out, cover)

    # the sound: the same two steps on every cut
    if project and str(project).lower().endswith('.mlt') and Path(project).is_file():
        try:
            sound_notes = []
            sound = sound_findings(project, spoken=bool(brief_check.speech_cues(cues or [])), notes=sound_notes)
            findings += sound
            cover('sound steps', 'done', '; '.join([f['what'] for f in sound] + sound_notes)
                  or 'mix measured, voice clean-up on or reasoned')
        except Exception as exc:  # noqa: BLE001 - a review without this check is still a review
            cover('sound steps', 'failed', f'{type(exc).__name__}: {exc}'[:300])

    note_checks = _check_note_targets(project, duration, findings, cover)

    plan_path, story_result = _check_story(project, brief, out, kind, stage_progress, cues, duration, brief_data, findings,
                                           cover, said, deaf)

    # the editorial review
    review = reviewer = None
    critic_asked = False
    memory = review_memory.load(project, video)
    last_review = memory.get('last_review')
    round_limit = review_memory.round_limit(brief_data)
    explicit_again = critic == 'again'
    limit_reached = critic == 'run' and review_memory.rounds_done(memory) >= round_limit
    project_hash = reviewed_hash(project, read)
    video_hash = review_order.export_hash(video)
    facts = review_order.round_facts(video_hash, brief_data, timeline)     # what a full round records, to compare with
    # the review order (review_order, behind its switch): the code checks first, then one critic; a second round only
    # for a real picture, story or sound problem; no critic on a video that hasn't changed
    order = None
    if review_order.enabled():
        findings += review_order.code_checks(project, brief_data, kind, ctx.get('platforms'), timeline, cover)
        order = review_order.decide(critic, memory, round_limit, review_order.code_failures(checks, findings),
                                    video_hash, brief_data, timeline, project_hash, last_review)
    else:       # always on: no critic round is spent on a cut identical to the last round's
        order = review_order.unchanged(critic, memory, round_limit, project_hash, brief_data, last_review, video_hash,
                                       timeline)
    held = bool(order and order['critic'] == 'held')
    # the final export, on a preview. On the last review of the run (the rounds are used up) nothing can change the
    # video any more, so it starts now and renders while the critic reads (the critic uses little of the PC). On an
    # earlier round the review may list fixes, after which this final would be replaced: it waits for the verdict.
    final_export = None
    wants_final = bool(final and preview_of and project)
    if wants_final and limit_reached:
        final_export = _start_final(project, errors)
    looked, look_note = None, ''
    unseen = None       # past the round limit: why no reviewer saw this cut, when none did
    shown = shown_text(captions, cues)
    if limit_reached:
        critic = last_review if last_review and Path(last_review).is_file() else None
        unseen, looked = _look_at_cut(gate, memory, video, project, kind, out, duration, portrait, page_list, engine,
                                      project_hash, critic, shown, cover)
        findings += memory.pop('_look_findings', [])
    if order and order['critic'] == 'reuse' and order['close']:
        order = review_order.settle(order, _may_look(memory, project, project_hash, last_review))
    if order and order['critic'] == 'look':
        critic = last_review
        looked, look_note = targeted_look(gate, memory, video, project, kind, out, duration, portrait, page_list, engine,
                                          instead_of_round=True, project_hash=project_hash)
        cover('targeted look', 'done' if looked else 'failed', look_note)
        if not looked:
            order = review_order.after_failed_look(order, look_note)
            critic = 'run'
    elif order and order['critic'] == 'reuse':
        critic = last_review
    elif held:
        critic = None
    if critic in ('run', 'again'):
        plan = plan_path
        _critic_boundaries(gate, project, duration, info, video, out, portrait, page_list, cover)

        _write_critic_bundle(video, kind, page_list, out, brief_data, checks, plan, timing_images, findings, motion,
                             cues, deaf, 'yes' if brief_check.said_cues(said) else
                             'no' if said is not None and said_complete else 'unknown')

        brief_file = _write_critic_brief(out, brief_data, project, guide)

        critic = _call_critic(video, kind, brief_file, out, engine, plan, project, memory)
        _record_critic_usage(project, critic)

        critic_asked = True
    elif critic is None and not held and (out / 'review.json').exists() and \
            (out / 'review.json').stat().st_mtime >= video.stat().st_mtime:
        critic = out / 'review.json'
    if held:
        reviewer = f"The reviewer hasn't read this video yet: {order['why']}."
        cover('editorial review', 'not done', order['why'], required=True)
    else:
        review, reviewer = _read_editorial_review(critic, critic_asked, limit_reached, round_limit, findings, cover,
                                                  review, reviewer)
        if review and order and order['critic'] == 'reuse':
            reviewer = f"No new reviewer ran: {order['why']}."
        elif review and order and order['critic'] == 'look':
            reviewer = f"No second full review: {order['why']}."
    if unseen and review:      # past the round limit, on a cut no reviewer saw: never ready on stale evidence
        reviewer = (f"No reviewer saw this cut: {unseen}. The measured checks ran on this export; the reviewer's "
                    'notes below are about the earlier cut.')
        for c in coverage:
            if c['check'] == 'editorial review':
                c.update(state='not done', required=True, detail=f'no reviewer saw this cut: {unseen}',
                         plain='No reviewer saw this version of the video: it changed after the last review.')
    elif limit_reached and review and looked is not None:
        reviewer = ("The review rounds have reached their limit, so a reviewer took one look at this cut: at the notes "
                    "still open and the change since the last review. The measured checks ran again on this export.")

    findings = _remember_review(findings, project, errors, critic_asked, review, memory, video, looked, project_hash,
                                facts)
    findings, settled = _against_notes(findings, note_checks, duration, memory)   # on the fixes as the reviewer wrote them
    if limit_reached:
        findings = _quotes_gone(findings, shown)
        settled = _quotes_gone(settled, shown)

    details, strips, excerpts = _review_evidence(duration, findings, timeline, detail_max, preview_of, project, gate, video, out, portrait, errors)

    findings.sort(key=lambda f: (SEVERITIES.index(f['severity']), f['at_s'] if f['at_s'] is not None else 1e9))
    # what this review means for the run: a bundle past the round limit is the last one (it re-measured this export
    # and took the one targeted look, if there was one to take): the video is handed over with what is left listed
    final = bool(limit_reached)
    open_majors = [f for f in findings if f['severity'] in ('critical', 'major') and f.get('owner') != 'person']
    if final and open_majors and review_memory.looks_left(memory):
        # past the last round a critical or major still open is fixed and looked at, never delivered as it is: the
        # rounds cap the critic, not the fixes (T331 P12's retry handed over three open majors with two looks left)
        left = review_memory.looks_left(memory)
        next_step = (f"Don't hand the video over yet: {_open_list(open_majors)} {_are(open_majors)} still open after the last review round. "
                     'Fix each one now, as its fix says or better. Check each fixed range on the export engine\'s '
                     'frames before the bundle: letitedit_check_frames at those moments beside their neighbours (or '
                     'letitedit_check_range / letitedit_look on the range), and the code check the fix touches '
                     '(letitedit_caption_readability for text over a busy or pale background, letitedit_timing for '
                     "joins). Then run the bundle once more with render='final': a reviewer takes one targeted look "
                     f'at the changed cut ({left} of {review_memory.LOOK_LIMIT} looks left for this edit). Hand over '
                     'when none is open. One that truly cannot be fixed with this footage is said plainly in the '
                     'closing message: what it is, what you tried and why it can\'t be fixed.')
        if project:
            review_memory.hand_over(memory, project_hash)
            review_memory.save(memory)
    elif final:
        left = review_memory.looks_left(memory)
        next_step = ('Hand the video over now: this was the last review of this run (the rounds are used up). Quote '
                     "review.md's For the person section, with what is left, in the closing message. Don't export or "
                     'run the bundle again unless the cut changes. '
                     + (f"A change to the cut after this needs the bundle once more with render='final' before hand-over: "
                        f"a reviewer takes one look at the changed cut ({left} of {review_memory.LOOK_LIMIT} looks "
                        'left for this edit).' if left else
                        'No reviewer look is left for a changed cut, so keep the cut as it is: an unattended run '
                        'refuses an edit now, and a cut changed anyway is handed over saying no reviewer saw it.')
                     + (f' {_open_list(open_majors)} {_are(open_majors)} still open: say each one plainly in the closing message as not '
                        'fixed, with what you tried.' if open_majors else ''))
        if project:
            review_memory.hand_over(memory, project_hash)
            review_memory.save(memory)
    elif review_memory.rounds_done(memory) >= round_limit:
        next_step = ('The review rounds are used up. Fix what you can from these findings in one pass, then run the '
                     "bundle once more to confirm (that one is the last), then hand the video over. render='final' "
                     'makes that last one on the full-size final itself (no separate final export or final_of check '
                     'after it); on a preview, final=True starts the final while it runs.'
                     + (f' Fix every critical and major ({_open_list(open_majors)}) and check each fixed range on the '
                        "export engine's frames before that bundle; if one is still open after it, its reply says how "
                        'to go on.' if open_majors else ''))
    else:
        next_step = review_order.next_line(order) if order else None
        if critic_asked and os.environ.get(ROUND_SESSIONS_ENV) == '1':
            next_step = ((next_step + ' ') if next_step else '') + ROUND_SESSION_LINE
    for_you = [f for f in findings if f.get('owner') == 'person']
    findings = [f for f in findings if f.get('owner') != 'person']
    the_verdict = verdict(findings, coverage)
    if wants_final and not limit_reached:
        if the_verdict == 'ready':
            final_export = _start_final(project, errors)
        else:
            fixes = sum(1 for f in findings if f['severity'] in ('critical', 'major'))
            final_export = {'started': False,
                            'why': f"not started: the verdict is {the_verdict} with {fixes} critical or major finding(s) "
                                   f"to fix, and this is review round {review_memory.rounds_done(memory)} of "
                                   f"{round_limit}. A final started now would be replaced after the fixes. final=True "
                                   "starts it during the last review (past the round limit), or after a review whose "
                                   "verdict is ready."}
    result = {'schema_version': 1, 'video': identity, 'kind': kind, 'duration_s': round(duration, 2),
              'size': f"{info['width']}x{info['height']}", 'verdict': the_verdict,
              'counts': {s: sum(1 for f in findings if f['severity'] == s) for s in SEVERITIES},
              'findings': findings, 'for_you': for_you, 'coverage': coverage,
              'not_checked': [{'check': c['check'], 'why': c['detail']} for c in coverage
                              if c.get('required') and c['state'] in ('not done', 'failed')],
              'brief': brief_result, 'story': story_result,
              'rounds': {'done': review_memory.rounds_done(memory), 'limit': round_limit, 'turbo': round_limit < review_memory.ROUND_LIMIT,
                         'limit_reached': review_memory.rounds_done(memory) >= round_limit,
                         'explicit_override': explicit_again, 'memory': memory['_file'], 'final': final,
                         **({'targeted_look': memory['targeted_look']} if memory.get('targeted_look') else {}),
                         **({'text_look': memory['text_look']} if memory.get('text_look') else {}),
                         **({'looks': review_memory.looks(memory),
                             'looks_left': review_memory.looks_left(memory)} if memory.get('looks') else {}),
                         **({'seen_by_reviewer': not unseen} if limit_reached else {}),
                         'fixed_since_last': [i['what'] for i in memory.get('_fixed_now') or []]},
              'credits': credits,
              **({'final_export': final_export} if final_export else {}),
              **({'preview_of': {'size': f"{info['width']}x{info['height']}",
                                 'full_size': f'{preview_of[0]}x{preview_of[1]}'}} if preview_of else {}),
              **({'note_targets': note_checks} if note_checks else {}),
              **({'settled_by_notes': settled} if settled else {}),
              'stage_progress': stage_progress, 'recent_changes': recent_changes,
              'files': {'pages': page_list, 'details': details, 'strips': [s for s in strips if s],
                        'excerpts': [e for e in excerpts if e], 'audio': audio_png,
                        'transcript': str(out / 'transcript.srt') if cues is not None and (out / 'transcript.srt')
                        .is_file() else None,
                        'checks': str(out / 'checks.json') if checks else None,
                        'timing': str(out / 'timing.json') if (out / 'timing.json').exists() else None,
                        'timing_images': timing_images,
                        **({'motion_timing': motion['sheet'], 'motion_strips': motion['strips'],
                            'text_frames': motion.get('text_frames')} if motion and motion.get('sheet') else {}),
                        'review': str(critic) if review else None},
              **({'render': rendered} if rendered else {}),
              **({'review_order': {k: order[k] for k in ('critic', 'why', 'code_failures')}} if order else {}),
              'reviewer': reviewer, 'errors': errors, 'seconds': round(time.monotonic() - t0, 1),
              **({'project_read': {k: v for k, v in read.items() if k != 'project'}} if project and read else {}),
              **({'next': next_step} if next_step else {})}
    (out / 'review_bundle.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    (out / 'review.md').write_text(markdown(result), encoding='utf-8')
    result['report'] = str(out / 'review.md')
    return result


def markdown(r):
    reviewer = r.get('reviewer')
    lines = [f"# Review of {Path(r['video']['file']).name}", '', '## For the person', '',
             _person_verdict(r), '', *([reviewer, ''] if reviewer and _person_text_is_current(reviewer, r['duration_s']) else []),
             *_person_for_you(r),
             '**What is working:** ' + _person_good(r), '',
             '**What was fixed or adjusted:** ' + _person_changes(r), '',
             '**What is left:** ' + _person_left(r), '',
             *(['**Kept as your notes asked:** ' + _person_settled(r), ''] if r.get('settled_by_notes') else []),
             '**What still needs a person:** Listen to the video for harsh sound, awkward joins and music that '
             'does not fit. Watch it all the way through for story and pacing.', '',
             '## Technical detail for the AI', '',
             f"**Verdict: {r['verdict']}** ({r['kind']}, {fmt(r['duration_s'])}, {r['size']}): "
             f"{r['counts']['critical']} critical, {r['counts']['major']} major, {r['counts']['minor']} minor.", '',
             *([f"Reviewed on a preview ({r['preview_of']['size']}) drawn by the export engine for the "
                f"{r['preview_of']['full_size']} final, with the final's sound.", ''] if r.get('preview_of') else []),
             *([('The final file matches the reviewed preview' if r['final_check'].get('matches') else
                 'The final file differs from the reviewed preview') + ' (length, loudness and true peak, black and '
                'frozen stretches, sound and picture in step, the same picture): final-check.json, full-size frames in '
                'final-frames.jpg.', ''] if r.get('final_check') else [])]
    if r['findings']:
        lines += ['| When | Severity | From | Problem | Fix |', '|---|---|---|---|---|']
        for f in r['findings']:
            lines.append(f"| {f['at'] or '-'} | {f['severity']} | {f['source']} | {f['what']} | {f['fix']} |")
    else:
        lines.append('No problems found by the checks that ran.')
    if r.get('settled_by_notes'):
        lines += ['', "Settled by the person's notes for this revision: each would undo a note, so it is not a change "
                  'to make and does not count in the verdict.', '', '| When | From | Problem | Why it stays |',
                  '|---|---|---|---|']
        for f in r['settled_by_notes']:
            lines.append(f"| {f.get('at') or '-'} | {f.get('source')} | {f.get('what')} | {f.get('why')} "
                         f"(note {f['note'] + 1}: \"{f.get('asked')}\") |")
    if r.get('credits'):
        lines += ['', '## Credit lines this video owes', '',
                  "The video uses library assets whose licence asks for credit: put these lines in its description.", '']
        for c in r['credits']:
            ids = ', '.join(c['assets'][:6]) + (f" and {len(c['assets']) - 6} more" if len(c['assets']) > 6 else '')
            lines.append(f"- {c['line']} (for {ids})")
    if r.get('for_you'):
        lines += ['', "On the person's list (these don't hold the video back):", '', '| When | Severity | Problem | What it needs |', '|---|---|---|---|']
        for f in r['for_you']:
            lines.append(f"| {f['at'] or '-'} | {f['severity']} | {f['what']} | {f['fix']} |")
    rounds = r.get('rounds') or {}
    if rounds:
        lines += ['', f"Review rounds: {rounds.get('done')} of {rounds.get('limit')}. Kept in {rounds.get('memory')}."]
        if r.get('next'):
            lines += [f"**Next:** {r['next']}"]
        if rounds.get('looks'):
            lines += [look_line(e) for e in rounds['looks'] if not e.get('failed')]
        else:
            if rounds.get('targeted_look'):
                lines += [look_line(rounds['targeted_look'])]
            if rounds.get('text_look'):
                lines += [look_line(rounds['text_look'])]
        if rounds.get('seen_by_reviewer') is False:
            lines += ['No reviewer saw this cut: it changed after the last review round and look.']
        if rounds.get('turbo'):
            lines += ['Turbo was on for this run: one review round, by design. The findings above are what that round found.']
        if (r.get('review_order') or {}).get('why'):
            lines += ['Review order: ' + r['review_order']['why'] + '.']
        if rounds.get('fixed_since_last'):
            lines += ['Fixed since the last review: ' + '; '.join(str(x)[:90] for x in rounds['fixed_since_last'])]
    lines += ['', '## What was checked', '', '| Check | State | Detail |', '|---|---|---|']
    for c in r['coverage']:
        lines.append(f"| {c['check']}{' (required)' if c['required'] else ''} | {c['state']} | {c['detail']} |")
    if r.get('brief'):
        lines += ['', '## The brief', '', '| Requirement | State | Evidence |', '|---|---|---|']
        for q in r['brief']['requirements']:
            lines.append(f"| {q['kind']}: {q['requirement']} | {q['state']} | {q['evidence'] or q['why']} |")
    lines += ['', '## Files', '']
    lines += [f"- page {i + 1}: {p['file']} ({fmt(p['from_s'])} to {fmt(p['to_s'])})"
              for i, p in enumerate(r['files']['pages'])]
    lines += [f'- timing page: {p}' for p in r['files'].get('timing_images') or []]
    for key in ('details', 'audio', 'transcript', 'checks', 'timing', 'review'):
        if r['files'].get(key):
            lines.append(f"- {key}: {r['files'][key]}")
    lines += [f'- {p}' for p in r['files']['strips'] + r['files']['excerpts']]
    lines += ['', 'Passing technical checks does not make a video good: the editorial review and a person watching '
              'it are separate lines above.']
    return '\n'.join(lines) + '\n'


def _person_verdict(r):
    stages_missing = any(not s.get('done') for s in (r.get('stage_progress') or {}).values())
    said = {'ready': ('This video is ready, apart from the short list for you below.' if r.get('for_you')
                      else 'The checks found no reason to hold this video.'),
            'revise': 'This video needs changes before it is ready.',
            'blocked': 'This video has a serious issue to fix before sharing.',
            'incomplete': ('The first cut is incomplete; some editing or review steps are missing.' if stages_missing
                           else 'No reviewer saw this version of the video: it changed after the last review, so '
                           'it is not reviewed.' if (r.get('rounds') or {}).get('seen_by_reviewer') is False
                           else 'The review is not finished: a required check did not run.')}.get(
                r['verdict'], 'The review could not finish.')
    speech = next((c for c in r.get('coverage') or [] if c['check'] == 'speech' and c['state'] != 'done'), None)
    if speech:
        heard = speech.get('plain') or "The review couldn't hear the speech in this video, so what is said wasn't checked."
        return heard if r['verdict'] == 'incomplete' and not stages_missing else f'{said} {heard}'
    return said


def _person_for_you(r):
    """Things only the person can provide: on the list, never holding the video back, and never hidden."""
    items = r.get('for_you') or []
    if not items:
        return []
    lines, seen = ['**For you** (only you can do these; the video can go without them, and you decide):', ''], set()
    for f in items:
        for need in _person_needs(f, r['duration_s']):
            if need not in seen:
                seen.add(need)
                lines.append('- ' + need)
    return lines + ['']


# A note asking to see software, a screen or a product in use. "footage", "recording" or "capture" alone is not one:
# a shot to film next time (pickups.md) or a sound recording says them too.
_THING = r'(software|screen|app|application|product|tool|website|program|interface|dashboard)'
SHOW_THE_SOFTWARE = re.compile(
    r'\bscreen[- ]?(recording|capture|grab|record)|'
    rf'\b{_THING}[- ]+(\w+[- ]+)?(capture|recording|footage|demo|demonstration)s?\b|'
    rf'\b(capture|recording|footage|demo|demonstration)s? of (it|the|a|an|your|their|its)? ?(\w+ )?{_THING}s?\b|'
    rf'\bshow(s|ing)?( it| a| the| your| their)? (real |actual )?{_THING}s?\b( (in use|working|running))?', re.I)


def _person_text_is_current(text, duration):
    return review_memory.GONE_WORDS not in text.casefold() and all(
        int(m) * 60 + float(s) <= duration for m, s in review_memory.TIMECODE.findall(text))


def _person_at(f, duration):
    """Keep a timestamp only if both its position and its displayed value fit this cut."""
    at, seconds = f.get('at'), f.get('at_s')
    if at and (seconds is None or 0 <= seconds <= duration) and _person_text_is_current(at, duration):
        return f'At {at}: '
    return ''


def _person_needs(f, duration=math.inf):
    """What one finding asks of the person, in plain words. One note can ask for more than one thing."""
    text = f"{f.get('what')} {f.get('fix')}".lower()
    what = str(f.get('what') or '')
    if what.startswith('claim to confirm'):
        claim = what.split(':', 1)[-1].strip()
        if _person_text_is_current(claim, duration):
            return [f"Listen and confirm the words: {claim}. The speech check wasn't sure of them."]
        return ['Listen to the video and confirm what was said. The speech check was uncertain.']
    needs = []
    if re.search(r'follower|analytics|subscriber|account (result|milestone|capture)', text):
        needs.append('A claim is made with nothing on screen to prove it. Add proof if you have it (a dated screenshot of the numbers), or keep it as your own word.')
    if SHOW_THE_SOFTWARE.search(text):
        needs.append('The video talks about the software without showing it. If you have a screen recording of it in use, give it to the AI to cut in.')
    if re.search(r'sign[- ]?up (link|url|route|destination)|signup (link|url|route|destination)|beta link|link in bio|destination|url|handle', text):
        needs.append('The ending asks people to act but does not say where. Tell the AI the real link or instruction.')
    said = str(f.get('fix') or what)
    at = _person_at(f, duration)
    if 'letitedit_' in said or not _person_text_is_current(said, duration):
        said = LOOK_AGAIN if at else 'A reviewer flagged a possible issue. Watch the video to see if it needs a change.'
    return needs or [at + said[:160]]


LOOK_AGAIN = 'A reviewer flagged this moment. Watch it, and tell the AI what to change if it still needs a change.'


def _person_good(r):
    length_ok = any(x.get('kind') == 'length' and x.get('state') == 'pass'
                    for x in ((r.get('brief') or {}).get('requirements') or []))
    size = str(r.get('size') or '').lower().split('x')
    portrait = len(size) == 2 and all(x.isdigit() for x in size) and int(size[1]) > int(size[0])
    if r.get('kind') == 'short' and portrait:
        return ('It is a vertical Short at the length you asked for.' if length_ok else
                'It is a vertical Short. The review below says what still needs work.')
    if length_ok:
        return 'Its length fits the request. The review below says what still needs work.'
    return 'The video was reviewed from beginning to end. The review below says what still needs work.'


def _person_changes(r):
    fixed = len((r.get('rounds') or {}).get('fixed_since_last') or [])
    if fixed:
        return f"{fixed} thing{'s' if fixed != 1 else ''} the last review found {'are' if fixed != 1 else 'is'} fixed."
    changes = ' '.join(str(s).lower() for s in r.get('recent_changes') or [])
    if not changes:
        return 'No changes since an earlier check were recorded.'
    kinds = []
    for words, plain in ((('opening', 'hook'), 'the opening'),
                         (('caption', 'subtitle'), 'the captions'),
                         (('cut', 'trim', 'pause', 'join'), 'the pacing'),
                         (('music', 'voice', 'sound', 'audio'), 'the sound'),
                         (('title', 'graphic', 'text'), 'the on-screen words')):
        if any(word in changes for word in words):
            kinds.append(plain)
    listed = (kinds[0] if len(kinds) == 1 else
              ' and '.join(kinds) if len(kinds) == 2 else
              ', '.join(kinds[:-1]) + ', and ' + kinds[-1] if kinds else 'the edit')
    return 'Adjusted ' + listed + ' since the last check.'


SENTENCE_END = re.compile(r'(?<!e\.g)(?<!i\.e)\.\s')      # "e.g. 1.0x" is not a sentence's end


def _first_sentence(text):
    return SENTENCE_END.split(str(text), 1)[0].rstrip('.')


def _person_issue(f):
    what = str(f.get('what') or '').strip()
    lower = what.lower()
    source = f.get('source')
    if source == 'freshness':
        return 'The video changed after this export. Export it again.'
    if f.get('check') == 'overlay_over_own_text' and f.get('plain'):
        return str(f['plain'])                  # T357: the overlay line, the platform, roughly where and when
    if 'caption covers the face or mouth' in lower:
        return "A caption covers someone's face or mouth."
    if lower.startswith('captions sit high'):
        return 'The captions sit high, close under the face, with plenty of room lower down.'
    if 'into a blurred border' in lower:
        return 'The picture is shrunk, with a blurred border around it.'
    if 'caption ends on a dangling word' in lower:
        return 'A caption breaks a phrase in an awkward place.'
    if source == 'project' and ('sound is still going' in lower or 'middle of a sound' in lower or
                                'middle of the word' in lower):
        return 'A cut clips a spoken word or other sound.'
    if source == 'brief' and lower.startswith('length:'):
        return 'The video length does not fit the request.'
    if source == 'gate':
        for key, plain in (('longest_static_s', 'The picture stays the same for too long.'),
                           ('duration_vs_target', 'The video length may need adjusting.'),
                           ('cuts_per_min', 'The picture may need more changes of shot.'),
                           ('visual_change_first3s', 'The opening has no visual change.')):
            if key in lower:
                return plain
    if source == 'critic':
        if lower.startswith('story:') and ('opening' in lower or 'speech opens' in lower):
            return 'The opening starts mid-thought or needs a clearer setup.'
        if lower.startswith('text:') and 'caption' in lower and any(
                word in lower for word in ('small', 'thin', 'pale', 'difficult to read', 'hard to read')):
            return 'Some captions are hard to read.'
        if lower.startswith('pacing:') and any(word in lower for word in ('uninterrupted', 'motion energy', 'unchanged')):
            return 'The picture stays nearly the same for too long.'
        if lower.startswith('shots:') and any(word in lower for word in ('no interface', 'editing action', 'resulting edit')):
            return 'The video does not show the action or result being discussed.'
    if source == 'critic' and (f.get('fix_gone') or what.startswith(review_memory.LOOK_CHANGE)):
        # the fix can't say it (it was for an earlier cut, or it is the look's general one): the problem in its words
        body = what[len(review_memory.LOOK_CHANGE):] if what.startswith(review_memory.LOOK_CHANGE) else \
            what.split(':', 1)[1] if re.match(r'^[a-z]+:\s', what) else what
        first = _first_sentence(body.strip())
        if first and len(first) <= 220:
            return first[0].upper() + first[1:] + '.'
    fix = str(f.get('fix') or '').strip()
    if fix:
        first = _first_sentence(fix)
        if len(first) <= 180:
            return first + '.'
    return 'This part needs a closer look; the details are below.'


def _person_settled(r):
    """The plain line for the findings the person's notes settled: how many, against which note."""
    held = r.get('settled_by_notes') or []
    notes = {}
    for f in held:
        notes.setdefault((f['note'], f.get('asked') or ''), []).append(f)
    against = '; '.join(f'{len(fs)} against your note ' +
                        (f'"{asked}"' if asked and _person_text_is_current(asked, r['duration_s']) else str(note + 1))
                        for (note, asked), fs in sorted(notes.items()))
    return (f"The review raised {len(held)} thing{'s' if len(held) != 1 else ''} that would undo what your notes asked "
            f"({against}), so {'they are' if len(held) != 1 else 'it is'} left as you asked, not changes to make.")


def _person_left(r):
    stages = r.get('stage_progress') or {}
    missing = [name for name, state in stages.items() if not state.get('done')]
    labels = {'log': 'footage review', 'story': 'story plan', 'rough': 'rough cut',
              'fine': 'fine cut', 'finish': 'finishing'}
    items = ['Finish the ' + ', '.join(labels.get(name, name) for name in missing) + ' step' +
             ('s' if len(missing) > 1 else '') + '.'] if missing else []
    duration = r.get('duration_s', math.inf)
    seen = set()
    for f in r.get('findings') or []:
        issue = _person_issue(f)
        if not _person_text_is_current(issue, duration):
            issue = 'This part needs a closer look; the details are below.'
        if issue in seen:
            continue
        seen.add(issue)
        items.append(_person_at(f, duration) + issue)
        if len(seen) == 4:
            break
    return ' '.join(items) if items else 'Nothing else was flagged by the checks that ran.'
