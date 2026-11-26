"""Small, local progress feed for AI editing jobs.

The MCP server writes tool events here, one record per run (runs/<run>.json, below). The editor reads its own
run's record; it does not need to inspect a chat transcript or know which AI client made the call.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STAGES = ('log', 'story', 'rough', 'fine', 'finish', 'export', 'review')
# The time estimate's six stages (measured before the export had a step of its own): the export counts as review.
EST_STAGES = ('log', 'story', 'rough', 'fine', 'finish', 'review')
LABELS = {'log': 'Watching your footage', 'story': 'Picking the best moments',
          'rough': 'Cutting your video', 'fine': 'Polishing the cuts',
          'finish': 'Adding the finishing touches', 'export': 'Saving your video',
          'review': 'Checking the video'}
# Measured journal markers put most Codex wall time in export/review revisions;
# Claude's one complete run spent more time in the finish pass.  See
# tests/progress-bar/baseline-runs.json for the four starting observations.
WEIGHTS = {
    'codex': {'log': .07, 'story': .07, 'rough': .13, 'fine': .09, 'finish': .14, 'review': .50},
    # T48's clock (Sonnet high, a scene behind him, 118.7 min): log 2, story 1, rough 4, fine 3, finish 62, review 46
    # minutes. The early stages pass in minutes; the long steps (cut-out, captions, exports) come after them.
    'claude': {'log': .03, 'story': .02, 'rough': .04, 'fine': .03, 'finish': .50, 'review': .38},
    'agent': {'log': .09, 'story': .08, 'rough': .18, 'fine': .12, 'finish': .23, 'review': .30},
}
TOOL_STAGE = {
    'footage': 'log', 'words': 'log', 'transcript': 'log', 'segments': 'log',
    'find_ranges': 'log', 'find_takes': 'log', 'ask_frames': 'log', 'log_frames': 'log',
    'search': 'log', 'look': 'log', 'stills': 'log', 'hear': 'log',
    'project_new': 'rough', 'timeline_read': 'rough', 'timeline_apply': 'rough',
    'timeline_undo': 'fine', 'reframe': 'fine', 'declick': 'fine', 'caption_fit': 'finish',
    'soundtrack': 'finish', 'fit_music': 'finish', 'song': 'finish', 'match_shots': 'finish',
    'check_frames': 'review', 'check_range': 'review', 'check_audio': 'review',
    'timing': 'review', 'export': 'export', 'export_job': 'export',
    'review_bundle': 'review', 'quality_gate': 'review', 'critic': 'review',
}
SEED_MINUTES = {'codex': {'short': 50, 'long': 80, 'both': 105, 'review': 15},
                'claude': {'short': 105, 'long': 150, 'both': 195, 'review': 20},
                'agent': {'short': 60, 'long': 100, 'both': 130, 'review': 18}}
# Real runs, minutes. Claude's 119+ was stopped while still revising (quiet PC, four
# reviews, 65 minutes to the first review); first cuts now stop after two full rounds.
SEED_EVIDENCE = {'codex': {'short': [35.9, 38.1, 48.6, 69.6]},
                 'claude': {'short': [74.1, 108.8, 119.0, 118.7, 130.0]}}
ACTIVE_S = 8 * 3600
REQUEST_REUSE_S = 120   # the window starts a request once; a second start this soon is the same request
# The feed's public state contract. Stage describes where an edit is; state
# describes whether anyone is working on it. UI surfaces read these same names.
STATE_LABELS = {
    'idle': '',
    'working': 'Getting ready',
    'waiting': 'Waiting for you: answer the question in the AI panel',
    'stopped': 'This run stopped',
    'failed': 'This run failed',
    'done': 'First cut done: review not finished',
    'over_time': 'Taking longer than expected; still making progress',
    'limit': "Waiting for your AI's usage limit to reset",
}
START_TOOLS = set(TOOL_STAGE) - {'timeline_read', 'check_frames', 'check_range', 'check_audio', 'timing'}


def _test_process() -> bool:
    """Plainly a test: the test runner's marker, pytest, or unittest's own entry point or a test_*.py script."""
    if os.environ.get('LETITEDIT_TEST_RUN') or os.environ.get('PYTEST_CURRENT_TEST') or 'pytest' in sys.modules:
        return True
    main = Path(getattr(sys.modules.get('__main__'), '__file__', None) or (sys.argv[0] if sys.argv else '') or '.')
    return (main.name == '__main__.py' and main.parent.name == 'unittest') or main.name.startswith('test_')


def root() -> Path:
    override = os.environ.get('LETITEDIT_PROGRESS_DIR')
    if not override and _test_process():
        # A test never writes the PC's real feed (a person's card reads it). Its children inherit the folder.
        override = os.environ['LETITEDIT_PROGRESS_DIR'] = str(Path(tempfile.gettempdir()) / 'letitedit-test-progress'
                                                              / str(os.getpid()))
    base = Path(override) if override else Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'letitedit/progress'
    base.mkdir(parents=True, exist_ok=True)
    return base


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                # Qt briefly holds live.json open while painting the feed.
                time.sleep(.05)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _normalize(name: str) -> str:
    return name.replace('mcp__letitedit__', '').removeprefix('letitedit_')


def _source(args: dict) -> str:
    for key in ('files', 'items'):
        value = args.get(key)
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            return value[0]
    for key in ('project', 'folder', 'source', 'path'):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ('items', 'files'):
        value = args.get(key)
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0]
    return ''


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def _media_size(source: str, selected=None) -> tuple[int, float, float]:
    """Video count, size and summed source minutes (capped work, no decoding)."""
    if not source:
        return 0, 0.0, 0.0
    p = Path(source)
    candidates = [Path(item) for item in selected] if selected else ([p] if p.is_file() else list(p.glob('*')) if p.is_dir() else [])
    video = [x for x in candidates if x.suffix.lower() in {'.mov', '.mp4', '.mkv', '.avi', '.webm', '.m4v'}]
    probe = _paths.CODE_ROOT / 'app' / 'ffprobe.exe'
    durations = []
    if probe.exists():
        for file in video[:24]:
            try:
                result = subprocess.run([str(probe), '-v', 'error', '-show_entries', 'format=duration',
                                         '-of', 'default=noprint_wrappers=1:nokey=1', str(file)],
                                        capture_output=True, text=True, timeout=3, check=False)
                durations.append(float(result.stdout.strip()))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
    return len(video), sum(x.stat().st_size for x in video) / (1024 ** 3), sum(durations) / 60


def _baseline(job: dict) -> float:
    engine = job.get('engine', 'agent').lower()
    if engine not in SEED_MINUTES:
        engine = 'agent'
    kind = job.get('kind', 'short').lower()
    if kind not in SEED_MINUTES[engine]:
        kind = 'short'
    seed = SEED_MINUTES[engine][kind]
    history = _read(root() / 'history.json')
    specific_key = f"{engine}:{job.get('model', '').lower()}:{job.get('effort', '').lower()}:{kind}"
    samples = history.get(specific_key) or history.get(f'{engine}:{kind}', [])
    if samples:
        recent = [float(x) for x in samples[-12:] if isinstance(x, (int, float)) and x > 0]
        if recent:
            seed = .4 * seed + .6 * (sum(recent) / len(recent))
    files = int(job.get('file_count') or 0)
    gigabytes = float(job.get('source_gb') or 0)
    minutes = float(job.get('source_minutes') or 0)
    scale = 1 + min(.55, max(0, files - 3) * .035 + max(0, gigabytes - 1.0) * .02
                    + max(0, minutes - 4) * .012)
    effort = str(job.get('effort') or '').lower()
    if effort in ('low', 'medium'):
        scale *= .78 if effort == 'low' else .88
    elif effort in ('max', 'ultra'):
        scale *= 1.12
    return seed * scale


def _weights(job: dict) -> dict[str, float]:
    engine = job.get('engine', 'agent').lower()
    base = WEIGHTS.get(engine, WEIGHTS['agent'])
    kind = job.get('kind', 'short').lower()
    model = job.get('model', '').lower()
    effort = job.get('effort', '').lower()
    saved = _read(root() / 'stage-history.json')
    samples = saved.get(f'{engine}:{model}:{effort}:{kind}') or saved.get(f'{engine}:{kind}') or []
    if not samples:
        return base
    shares = {stage: [] for stage in EST_STAGES}
    for sample in samples[-12:]:
        if not isinstance(sample, dict):
            continue
        total = sum(float(sample.get(stage) or 0) for stage in EST_STAGES)
        if total <= 0:
            continue
        for stage in EST_STAGES:
            shares[stage].append(float(sample.get(stage) or 0) / total)
    if not shares['review']:
        return base
    raw = {stage: .4 * base[stage] + .6 * sum(shares[stage]) / len(shares[stage])
           for stage in EST_STAGES}
    total = sum(raw.values())
    return {stage: raw[stage] / total for stage in EST_STAGES}


def _estimate(job: dict, now: float) -> dict:
    stage = job.get('stage') or 'log'
    if stage == 'export':
        stage = 'review'
        job = {**job, 'stage_started': {**(job.get('stage_started') or {}),
                                        'review': (job.get('stage_started') or {}).get('export') or job['started']}}
    index = EST_STAGES.index(stage) if stage in EST_STAGES else 0
    weights = _weights(job)
    completed = sum(weights[x] for x in EST_STAGES[:index])
    starts = job.get('stage_started') or {}
    stage_started = float(starts.get(stage) or job['started'])
    expected = _baseline(job) * 60 * weights[stage]
    stage_share = min(.90, max(.04, (now - stage_started) / max(expected, 1)))
    raw = min(.96, completed + weights[stage] * stage_share)
    # A stage marker is evidence of forward movement; do not make the bar retreat.
    fraction = max(float(job.get('fraction') or 0), raw)
    elapsed_min = max(0, now - float(job['started'])) / 60
    remaining = max(0, _baseline(job) * (1 - fraction))
    lower = max(3, int(math.floor(remaining * .72 / 5) * 5))
    # Early on the range is wide: two full runs on the same Short took 119 and 130 minutes against the 50-105 it
    # showed for the first 25 minutes. It narrows to the usual spread by the time half the work is done.
    spread = 1.38 + .55 * max(0.0, 1 - fraction / .5)
    upper = max(lower + 5, int(math.ceil(remaining * spread / 5) * 5))
    if stage == 'review' and fraction > .85:
        # Revisions are open-ended; a nearly full bar is not evidence that the
        # last export or review will finish in a few minutes.
        lower, upper = max(5, lower), max(15, upper)
    if job.get('no_estimate'):
        # Nothing measured to estimate this kind of run from (Turbo, a Look with no footage): no made-up time.
        return {'fraction': round(fraction, 3), 'range': 'Time left unknown', 'overdue': False}
    review_overrun = stage == 'review' and (now - stage_started) > expected * 1.3
    overdue = elapsed_min > _baseline(job) * 1.38 or review_overrun
    if overdue:
        range_text = 'Taking longer than expected; still making progress'
    elif lower >= 60:
        range_text = f'about {round(lower / 60, 1):g}-{round(upper / 60, 1):g} hours left'
    else:
        range_text = f'about {lower}-{upper} minutes left'
    return {'fraction': round(fraction, 3), 'range': range_text, 'overdue': overdue}


# ----------------------------------------------------------------------------- one record per run (T193)
# A run is one New video (or Review) a window asked for, from its start until it truly ends: the person stops it, it
# finishes, or it fails and isn't carried on. Its record is runs/<run>.json. The window names the run (the chat's
# progress_run, else its request id) and gives it to its AI's processes as LETITEDIT_PROGRESS_RUN; a tool call attaches
# to that run, else to the active run whose project or save folder it touches, else to nothing: an unrelated AI's or a
# test's calls never show on a window's card. live.json stays a copy of the latest claimed run for older builds.
RUN_ENV = 'LETITEDIT_PROGRESS_RUN'
PHASE_LABELS = dict(LABELS)
EXPORT_TOOLS = {'export', 'export_job'}
REVIEW_TOOLS = {'review_bundle', 'critic', 'quality_gate'}
EDIT_TOOLS = {'timeline_apply', 'timeline_undo', 'caption_fit', 'soundtrack', 'fit_music', 'song', 'match_shots',
              'reframe', 'import_srt', 'dub', 'fix'}
# Work on the video itself: after a save has started, a call to one of these means the AI went back to working on it
# (the step line follows it; the step itself never goes back).
WORK_TOOLS = EDIT_TOOLS | {'music_write', 'music_make', 'graphic', 'motion', 'image', 'stock', 'real_picture', 'voice',
                           'separate', 'hooks', 'annotate', 'code_scene'}
# Setting up and reading a project is not cutting it: these never move the step.
SETUP_TOOLS = {'project_new', 'timeline_read'}
# A first cut's stage notes own its steps. Until the first one (it comes within a minute or two), or in a run that
# never writes them, tool calls move the step only after this long.
TOOL_STAGE_GRACE_S = 180
# The review's own limit on full rounds (review_memory.ROUND_LIMIT): the card never counts past it.
REVIEW_ROUND_LIMIT = 2
# What is happening now, in the person's words (the card's second line)
NOW_LABELS = {'footage': 'Watching the clips', 'words': "Listening to what's said", 'transcript': "Reading what's said",
              'segments': 'Finding where each part starts', 'find_ranges': 'Finding the best takes',
              'find_takes': 'Finding the best takes', 'ask_frames': 'Looking closely at the footage',
              'log_frames': 'Looking closely at the footage', 'look': 'Looking closely at the footage',
              'stills': 'Looking closely at the footage', 'hear': 'Listening to the sound',
              'speakers': 'Working out who is speaking', 'sync': 'Lining up the cameras',
              'project_new': 'Setting up your project', 'timeline_apply': 'Editing the timeline',
              'timeline_undo': 'Undoing a change', 'reframe': 'Framing the shots', 'caption_fit': 'Placing the captions',
              'soundtrack': 'Working on the music', 'fit_music': 'Fitting the music to the cut', 'song': 'Adding the song',
              'music_write': 'Writing the music', 'music_make': 'Making the music',
              'match_shots': 'Matching the colours of the shots', 'check_frames': 'Looking at the frames',
              'check_range': 'Watching a part of the video', 'check_audio': 'Checking the sound',
              'timing': 'Checking the rhythm', 'export': 'Saving your video', 'export_job': 'Saving your video',
              'review_bundle': 'Watching the finished video', 'critic': 'Watching the finished video',
              'quality_gate': 'Checking the finished video', 'hooks': 'Finding a strong opening',
              'graphic': 'Making a graphic', 'motion': 'Making a moving graphic', 'stock': 'Finding extra shots',
              'image': 'Making a picture', 'real_picture': 'Finding a picture',
              'separate': 'Separating the voice from the music',
              'voice': 'Cleaning the voice', 'dub': 'Dubbing the voice'}
OP_NOW = {'score': 'Mixing the music and the voice', 'level': 'Evening out the sound', 'master': 'Finishing the sound',
          'declick': 'Cleaning the voice', 'captions': 'Adding captions', 'fx': 'Adding effects',
          'popups': 'Adding pop-ups', 'style': 'Setting the style', 'hook': 'Choosing the opening',
          'tighten': 'Tightening the pauses', 'split_edit': 'Smoothing the cuts',
          'multicam': 'Cutting between the cameras', 'adjust': 'Matching the lighting',
          'effects': 'Adjusting the picture', 'lift': 'Lifting out a part of the picture', 'aim': 'Adjusting the picture',
          'insert': 'Cutting your video', 'trim': 'Cutting your video', 'delete': 'Cutting your video',
          'move': 'Cutting your video', 'gap': 'Cutting your video'}


def _safe(run: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(run))[:120] or 'run'


def run_path(run: str) -> Path:
    return root() / 'runs' / f'{_safe(run)}.json'


def _load(run: str | None) -> dict:
    return _read(run_path(run)) if run else {}


def _runs() -> list[dict]:
    folder = root() / 'runs'
    return [r for r in (_read(p) for p in folder.glob('*.json')) if r.get('run')] if folder.is_dir() else []


def review_round(rec: dict) -> int:
    """The round the review is in, as the review counts it: its full rounds done so far plus the one under way, never
    past its limit (the review stops at two; a last confirming check is still that round)."""
    if not rec.get('reviewed'):
        return 1
    return max(1, min(int(rec.get('review_rounds') or 0) + 1, REVIEW_ROUND_LIMIT))


def is_note(rec: dict) -> bool:
    """A Review note's run (kind review): a change to a video that exists, not a video being made."""
    return rec.get('kind') == 'review'


def note_label(rec: dict) -> str:
    """The card's line for a note: what it asks, in the person's words."""
    count = int(rec.get('notes') or 1)
    what = ' '.join(str(rec.get('what') or '').split())
    if len(what) > 80:
        what = what[:77].rstrip() + '...'
    if count > 1:
        return f'Working on your {count} notes' + (f': {what}, ...' if what else '')
    return f'Working on your note: {what}' if what else 'Working on your note'


def _done_line(label: str, args: dict, tool: str) -> str:
    """One finished change of a note, in a few words: the apply's own Undo label without its "Review:" prefix."""
    text = str(label or '').strip()
    text = re.sub(r'^(review|claude|codex|antigravity|letitedit|ai)\s*(\d+)?\s*:\s*', '', text, flags=re.I)
    return text or _now_words(tool, args) or ''


def phase_label(rec: dict) -> str:
    if is_note(rec):
        return note_label(rec)
    phase = rec.get('phase') or rec.get('stage') or 'log'
    # a check keeps the round it started in (its own end counts its round, before anything is fixed)
    rnd = int(rec.get('checking_round') or 1) if phase == 'review' else review_round(rec)
    if phase == 'fix':
        return f'Fixing what the check found (round {rnd})' if rnd > 1 else 'Fixing what the check found'
    label = PHASE_LABELS.get(phase, PHASE_LABELS['log'])
    return f'{label} (round {rnd})' if rnd > 1 and phase in ('export', 'review') else label


def _review_rounds(args: dict) -> int | None:
    """Full review rounds done on this project, from the review's own memory (review_memory.json in the project's
    folder); None when it can't be read."""
    project = str(args.get('project') or args.get('video') or '')
    if not project:
        return None
    try:
        import letitedit.timeline.project_journal as project_journal
        memory = Path(project_journal.folder(project)) / 'review_memory.json'
        return len(json.loads(memory.read_text(encoding='utf-8-sig')).get('rounds') or [])
    except Exception:  # noqa: BLE001 - no memory yet, or unreadable: counted from the calls instead
        return None


def _rendered_video(args: dict) -> str | None:
    """A review that rendered its own video (render='preview' | 'final' with project=, no video=): the video its newest
    review folder beside the project names (T379: a final reviewed 'ready' ended as 'review not finished')."""
    project = args.get('project')
    if not project or not args.get('render'):
        return None
    try:
        bundles = [Path(args['out']) / 'review_bundle.json'] if args.get('out') else \
            sorted(Path(project).parent.glob('* review/review_bundle.json'), key=lambda p: p.stat().st_mtime)[-1:]
        data = json.loads(bundles[-1].read_text(encoding='utf-8-sig')) if bundles else {}
    except (OSError, ValueError):
        return None
    video = data.get('video') if isinstance(data, dict) else None
    video = video.get('file') if isinstance(video, dict) else video
    return str(video) if video else None


def review_status(args: dict) -> dict:
    video = args.get('video') or _rendered_video(args)
    if not video:
        return {}
    folder = Path(args.get('out') or Path(video).with_suffix('').with_name(Path(video).stem + ' review'))
    try:
        path = folder / 'review_bundle.json'
        if path.stat().st_mtime < Path(video).stat().st_mtime:
            return {}
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        return {'verdict': data.get('verdict'), 'report': str(folder / 'review.md')}
    except (OSError, ValueError):
        return {}


def finished_label(review: dict) -> str:
    return {'ready': 'Your video is ready',
            'revise': 'First cut done: the review found changes to make',
            'incomplete': 'First cut done: review not finished',
            'blocked': 'First cut blocked: the review found a serious issue'}.get(
                review.get('verdict'), 'First cut done: review not finished')


def _mirror(rec: dict) -> None:
    """live.json for older builds' cards: only a claimed run, and never over another claimed run that is still going."""
    if not rec.get('request_id'):
        return
    live = _read(root() / 'live.json')
    other = live.get('run') or live.get('request_id')
    if (live.get('active') and live.get('request_id') and other != rec.get('run')
            and float(rec.get('updated') or time.time()) - float(live.get('updated') or 0) < 600):
        return
    copy = dict(rec)
    if copy.get('stage') == 'export':      # older cards know six stages
        copy['stage'] = 'review'
    _write(root() / 'live.json', copy)


def _save(rec: dict) -> dict:
    if rec.get('state') in ('working', 'over_time'):
        rec['label'] = phase_label(rec)
    _write(run_path(rec['run']), rec)
    _mirror(rec)
    return rec


def _norm(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except (TypeError, ValueError):
        return ''


def _paths_in(args: dict) -> list[str]:
    found = []
    for key in ('project', 'folder', 'path', 'output', 'source', 'files', 'items'):
        value = args.get(key)
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, str) and item and ('\\' in item or '/' in item or item.lower().endswith('.mlt')):
                found.append(_norm(item))
    return found


def _touches(rec: dict, paths: list[str]) -> bool:
    if not paths:
        return False
    projects = {_norm(p) for p in rec.get('projects') or []}
    folders = [_norm(f) for f in [rec.get('folder')] if f]
    for path in paths:
        if path in projects or any(path == f or path.startswith(f.rstrip('\\/') + os.sep) for f in folders):
            return True
    return False


_CURRENT = {'run': None}   # the run of the tool call this process is in (note() writes to it)


def _attach(args: dict, now: float) -> tuple[dict, str | None]:
    """The run this tool call belongs to: (its record, or {} if it has none yet; the run's name, or None)."""
    named = os.environ.get(RUN_ENV)
    if named:
        return _load(named), named
    paths = _paths_in(args)
    runs = [r for r in _runs() if r.get('active') and now - float(r.get('updated') or 0) < ACTIVE_S]
    for rec in runs:
        if _touches(rec, paths):
            return rec, rec['run']
    # An older window names no run and gives its AI none: its calls go to its run as they always did (the newest
    # claimed one). A window that names its runs never gets calls it didn't send.
    legacy = sorted((r for r in runs if r.get('legacy') and r.get('request_id')), key=lambda r: float(r.get('updated') or 0))
    if legacy:
        return legacy[-1], legacy[-1]['run']
    return {}, None


def _new_record(run: str, meta: dict, now: float) -> dict:
    source = str(meta.get('source') or _source(meta))
    selected = meta.get('files') or []
    count, gb, duration = _media_size(source, selected)
    rec = {'version': 2, 'id': f'{int(now * 1000)}-{os.getpid()}', 'run': run, 'active': True,
           'started': now, 'updated': now, 'request_id': meta.get('request_id'),
           'source': source, 'selected_files': selected, 'kind': meta.get('kind') or 'short',
           'engine': meta.get('engine') or 'agent', 'model': meta.get('model') or '',
           'effort': meta.get('effort') or '', 'file_count': count, 'source_gb': round(gb, 2),
           'source_minutes': round(duration, 2), 'stage': 'log', 'stage_started': {'log': now}, 'phase': 'log',
           'round': 1, 'now': '', 'state': 'working', 'label': STATE_LABELS['working'], 'whole_video': True,
           'tool_calls': 0, 'fraction': 0.0}
    _note_meta(rec, meta)
    for key in ('folder', 'instance'):
        if meta.get(key):
            rec[key] = str(meta[key])
    if meta.get('no_estimate'):
        rec['no_estimate'] = True
    rec.update(_estimate(rec, now))
    return rec


def _note_meta(rec: dict, meta: dict) -> None:
    """A Review note's run: not a whole video (the card shows the note and what's done, no steps and no time left)."""
    if (meta.get('kind') or rec.get('kind')) != 'review':
        return
    rec['whole_video'] = False
    rec['no_estimate'] = True
    for key in ('what', 'notes'):
        if meta.get(key):
            rec[key] = meta[key]
    # the open project: a Review chat names no run, so the AI's edits to this project find the note's card by it
    named = [str(p) for p in meta.get('projects') or [] if str(p).lower().endswith('.mlt')]
    if named:
        rec['projects'] = ([p for p in rec.get('projects') or [] if p not in named] + named)[-12:]


def start(meta: dict, *, now: float | None = None, auto: bool = False) -> dict:
    """A run starts, or carries on: the same run (meta 'run', else its request id) keeps its record, its step and its
    time so far; a new request of it (a carry-on, Continue, Carry on after Stop, a wait for a usage limit) only updates
    the request id. (auto is kept for older callers; nothing starts a run by itself any more.)"""
    now = time.time() if now is None else now
    legacy = not meta.get('run')
    run = str(meta.get('run') or meta.get('request_id') or f'run-{int(now * 1000)}-{os.getpid()}')
    request = str(meta.get('request_id') or '')
    if legacy and ':' in request and not _load(run):
        # An older window names each request, not the run: a later request of the same chat (the app's carry-on,
        # Continue the edit) is the same video being made, so it keeps that run.
        chat = request.rsplit(':', 1)[0] + ':'
        same = [r for r in _runs() if str(r.get('request_id') or '').startswith(chat) and r.get('legacy')
                and now - float(r.get('updated') or 0) < 3600]
        if same:
            run = max(same, key=lambda r: float(r.get('updated') or 0))['run']
    rec = _load(run)
    if (rec and not run.startswith('nv-') and request and rec.get('request_id') == request
            and (not rec.get('active') or now - float(rec.get('updated') or 0) > REQUEST_REUSE_S)):
        # A run named by its request is that one request. The same name again, on a record that has ended or gone
        # quiet, is another request: a chat restored after a restart numbers its requests from 1 again.
        stale, rec = rec.get('id'), {}
    else:
        stale = None
    if not rec:
        fresh = _new_record(run, meta, now)    # measures the footage, which can take a while
        rec = _load(run)
        if not rec or rec.get('id') == stale:
            if legacy:
                fresh['legacy'] = True
            return _save(fresh)
        # the AI's first tool call wrote the run meanwhile: keep its step and "now" line, add what the window knows
        for key in ('source', 'selected_files', 'file_count', 'source_gb', 'source_minutes'):
            if not rec.get(key) and fresh.get(key):
                rec[key] = fresh[key]
    rec.update({k: meta[k] for k in ('request_id', 'kind', 'engine', 'model', 'effort', 'folder', 'instance')
                if meta.get(k)})
    if meta.get('no_estimate'):
        rec['no_estimate'] = True
    if meta.get('source') and not rec.get('file_count'):
        rec['source'] = str(meta['source'])
        rec['selected_files'] = meta.get('files') or []
        rec['file_count'], rec['source_gb'], rec['source_minutes'] = _media_size(rec['source'], rec['selected_files'])
    rec.update(active=True, whole_video=True, updated=now)
    _note_meta(rec, meta)
    if rec.get('state') != 'waiting':
        rec['state'] = 'working'
    rec.pop('limit', None)
    rec.pop('outcome', None)
    rec.update(_estimate(rec, now))
    return _save(rec)


def _fix_round(rec: dict) -> None:
    """The check sent it back: fixing, in the review's own round (review_round), never back to step 1."""
    rec['phase'] = 'fix'
    rec['round'] = review_round(rec)


def _apply_note(rec: dict, note: str, finished_ok: bool) -> str | None:
    """A note from the first-cut skill. Returns the stage it moves to (never back)."""
    match = re.match(r'stage:(log|story|rough|fine|finish|export):done', note)
    if match:
        if not finished_ok:
            return None
        rec['whole_video'] = True
        ix = STAGES.index(match.group(1))
        return STAGES[min(ix + 1, len(STAGES) - 1)]
    if re.match(r'stage:review:(fix|revise)', note):
        if finished_ok:
            _fix_round(rec)
        return None
    if note.startswith(('story_plan:', 'pickups:')):
        return 'story'
    if note.startswith('fine_pass:'):
        return 'fine'
    if note.startswith('finish_pass:'):
        return 'finish'
    if note.startswith('brief:'):
        try:
            brief = json.loads(note.split(':', 1)[1].strip())
            deliverables = brief.get('deliverables') or []
            if deliverables and isinstance(deliverables[0], dict):
                rec['kind'] = deliverables[0].get('kind') or rec.get('kind')
            if not rec.get('source') and brief.get('footage'):
                rec['source'] = str(brief['footage'][0])
                rec['file_count'], rec['source_gb'], rec['source_minutes'] = _media_size(rec['source'])
        except (ValueError, AttributeError, TypeError):
            pass
    return None


def _advance(rec: dict, stage: str, now: float) -> None:
    """The step only goes forward; the phase follows it."""
    if STAGES.index(stage) > STAGES.index(rec.get('stage', 'log')):
        rec['stage'] = stage
        rec.setdefault('stage_started', {})[stage] = now
        rec['phase'] = stage


def _now_words(tool: str, args: dict) -> str:
    if tool == 'timeline_apply':
        changes = args.get('changes') if isinstance(args.get('changes'), list) else []
        changes = [c for c in changes if isinstance(c, dict)]
        if any(c.get('grade') for c in changes):
            return 'Matching the lighting'
        for change in changes:
            if change.get('op') in OP_NOW:
                return OP_NOW[change['op']]
    return NOW_LABELS.get(tool, '')


def _export_status(job_id: str) -> str:
    cache = Path(os.environ.get('LETITEDIT_CACHE') or Path(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT) / 'cache')
    return str(cache / 'exports' / _safe(job_id) / 'status.json')


def record_tool(name: str, args: dict | None = None, *, finished: bool = False,
                success: bool = True, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    args = args if isinstance(args, dict) else {}
    tool = _normalize(name)
    rec, run = _attach(args, now)
    _CURRENT['run'] = run
    with (root() / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'time': now, 'run': run, 'job': rec.get('id'), 'tool': tool, 'finished': finished,
                            'success': success, 'pid': os.getpid()}) + '\n')
    if not run:
        return {}                         # nobody's card: an unrelated AI, a test, a person's own terminal
    if not rec:
        if tool not in START_TOOLS:
            return {}
        # the AI reached the tool server before the window's start helper wrote the run: start it; the window adds the rest
        rec = _new_record(run, {'source': _source(args), 'files': args.get('files') or [],
                                'engine': os.environ.get('LETITEDIT_ACTOR', 'agent').lower()}, now)
    elif not rec.get('active'):
        return rec                        # ended (stopped, done or failed): a late call never reopens it
    if str(args.get('project') or '').lower().endswith('.mlt'):
        # the projects this run worked on, for the window to find the finished video (first_cut_result.py)
        named = [p for p in rec.get('projects') or [] if p != str(args['project'])]
        rec['projects'] = (named + [str(args['project'])])[-12:]
    if _source(args) and not rec.get('source'):
        rec['source'] = _source(args)
        rec['selected_files'] = args.get('files') or []
        rec['file_count'], rec['source_gb'], rec['source_minutes'] = _media_size(rec['source'], rec['selected_files'])
    stage = None
    if tool == 'journal':
        note_text = str(args.get('text') or '') if args.get('action') in ('add', 'note') else ''
        stage = _apply_note(rec, note_text, finished and success) if note_text else None
        if note_text.startswith(('brief:', 'stage:')):
            rec['staged'] = True
    else:
        stage = TOOL_STAGE.get(tool)
        if tool == 'review_bundle':
            if finished and success:
                rec['review'] = review_status(args)
            elif not finished:
                rec.pop('review', None)
        at_finish = STAGES.index(rec.get('stage', 'log')) >= STAGES.index('finish')
        if tool in EXPORT_TOOLS:
            if args.get('job_id'):
                rec['export_status'] = _export_status(str(args['job_id']))
            elif tool == 'export' and not finished:
                rec.pop('export_status', None)
                rec.pop('review', None)
            if at_finish:
                _advance(rec, 'export', now)
                rec['phase'] = 'export'
        elif tool in REVIEW_TOOLS and at_finish:
            if tool == 'review_bundle' and finished and success:
                # the review's own count of full rounds (it stops at two); counted from the calls if it can't be read
                done = _review_rounds(args)
                rec['review_rounds'] = done if done is not None else int(rec.get('review_rounds') or 0) + 1
            if not finished:
                _advance(rec, 'review', now)
                rec['checking_round'] = review_round(rec)
                rec['phase'] = 'review'
                rec['reviewed'] = True
        elif tool in WORK_TOOLS and not finished and rec.get('phase') in ('review', 'export'):
            rec.pop('review', None)
            if rec.get('reviewed'):
                _fix_round(rec)            # the check sent it back: fixing, never back to step 1
            else:
                rec['phase'] = 'finish'    # back at work after starting a save: the step line follows (not the step)
        if rec.get('kind') == 'review':
            pass                           # Review on a finished video follows its tools
        elif tool in SETUP_TOOLS:
            stage = None                   # making or reading the project isn't cutting it
        elif (rec.get('staged') or (stage and STAGES.index(stage) > STAGES.index('rough'))
              or (stage and stage != 'log' and now - float(rec.get('started') or now) < TOOL_STAGE_GRACE_S)):
            # The accepted stage notes own the order of a first cut; before the first one comes, the first minutes'
            # calls say nothing about how far a video has come; and a checking tool never says it (the step never goes
            # back, so it would pin the bar at the end).
            stage = None
    if is_note(rec):                       # a note shows no steps: what it's done instead
        if finished and success and tool in EDIT_TOOLS and not args.get('dry_run'):
            line = _done_line(args.get('label'), args, tool)
            done = [d for d in rec.get('done') or [] if d != line]
            rec['done'] = (done + [line])[-6:] if line else done
    if stage:
        _advance(rec, stage, now)
    words = _now_words(tool, args) if not finished else ''
    if words:
        rec['now'] = words
        rec['now_since'] = now
    if not finished:
        rec['tool_calls'] = int(rec.get('tool_calls') or 0) + 1
    rec['updated'] = now
    rec['last_tool'] = tool
    rec['last_success'] = success
    rec.update(_estimate(rec, now))
    if rec.get('state') == 'limit' and not finished:
        rec.pop('limit', None)             # the AI is working again: the usage limit's wait is over
        rec['state'] = 'working'
    if rec.get('state') not in ('waiting', 'limit'):
        rec['state'] = 'over_time' if rec['overdue'] else 'working'
    rec['round'] = review_round(rec)
    return _save(rec)


def note(text: str | None, *, now: float | None = None) -> None:
    """Words for the card of the video being made (its "now" line), for as long as something long happens inside one
    tool call; None puts back what it said. No run of a window: nothing to do."""
    now = time.time() if now is None else now
    rec = _load(os.environ.get(RUN_ENV) or _CURRENT['run'])
    if not rec.get('active'):
        return
    if text:
        rec.setdefault('before_note', rec.get('now') or '')
        rec['now'] = text
    elif 'before_note' in rec:
        rec['now'] = rec.pop('before_note')
    rec['updated'] = now
    _save(rec)


def _find(run: str | None = None, request_id: str | None = None) -> dict:
    rec = _load(run) if run else {}
    if not rec and request_id:
        rec = _load(request_id) or next((r for r in _runs() if r.get('request_id') == request_id), {})
    return rec


def set_waiting(waiting: bool, *, request_id: str | None = None, run: str | None = None,
                now: float | None = None) -> dict:
    now = time.time() if now is None else now
    rec = _find(run, request_id)
    if not rec.get('active'):
        return rec
    if waiting:
        rec['label'] = STATE_LABELS['waiting']
    rec.pop('limit', None)                 # a usage limit's wait is over once the run waits on something else or works
    rec['state'] = 'waiting' if waiting else 'working'
    rec['updated'] = now
    if not waiting:
        rec.update(_estimate(rec, now))
        rec['state'] = 'over_time' if rec['overdue'] else 'working'
    return _save(rec)


def set_limit(*, run: str | None = None, request_id: str | None = None, words: str = '',
              resets_at: float | None = None, now: float | None = None) -> dict:
    """The AI's usage limit was reached: the run waits for the reset (the window carries on by itself then)."""
    now = time.time() if now is None else now
    rec = _find(run, request_id)
    if not rec:
        return rec
    rec.update(active=True, state='limit', updated=now, label=words or STATE_LABELS['limit'],
               limit={'words': words, 'resets_at': resets_at, 'since': now})
    return _save(rec)


def finish(*, now: float | None = None, success: bool = True, request_id: str | None = None,
           outcome: str | None = None, run: str | None = None) -> dict:
    now = time.time() if now is None else now
    rec = _find(run, request_id)
    if not rec.get('active'):
        return rec
    if request_id and not run and rec.get('request_id') != request_id:
        return rec
    rec['active'] = False
    rec['updated'] = now
    outcome = outcome or ('done' if success else 'failed')
    if outcome not in ('done', 'stopped', 'failed'):
        raise ValueError(f'Unknown progress outcome: {outcome}')
    success = outcome == 'done'
    rec['state'] = outcome
    rec['outcome'] = outcome
    rec.pop('limit', None)
    rec['fraction'] = 1.0 if success else rec.get('fraction', 0)
    rec['range'] = ''
    rec['label'] = STATE_LABELS[outcome]
    if success:
        rec['label'] = finished_label(rec.get('review') or {})
        if is_note(rec):
            rec['label'] = 'Your notes are done' if int(rec.get('notes') or 1) > 1 else 'Your note is done'
    if success and rec.get('whole_video') and rec.get('tool_calls', 0) >= 3 and not rec.get('no_estimate'):
        engine, kind = rec.get('engine', 'agent'), rec.get('kind', 'short')
        key = f'{engine}:{kind}'
        specific_key = f"{engine}:{rec.get('model', '').lower()}:{rec.get('effort', '').lower()}:{kind}"
        history_path = root() / 'history.json'
        history = _read(history_path)
        history[key] = (history.get(key, []) + [round((now - rec['started']) / 60, 2)])[-20:]
        history[specific_key] = (history.get(specific_key, []) + [round((now - rec['started']) / 60, 2)])[-20:]
        _write(history_path, history)
        starts = dict(rec.get('stage_started') or {})
        if 'export' in starts:
            starts['review'] = min(float(starts['export']), float(starts.get('review') or now))
        if all(stage in starts for stage in EST_STAGES):
            stage_times = [float(starts[stage]) for stage in EST_STAGES] + [now]
            durations = {stage: round(max(0, stage_times[i + 1] - stage_times[i]), 1)
                         for i, stage in enumerate(EST_STAGES)}
            stage_path = root() / 'stage-history.json'
            stage_history = _read(stage_path)
            for k in (key, specific_key):
                stage_history[k] = (stage_history.get(k, []) + [durations])[-20:]
            _write(stage_path, stage_history)
    return _save(rec)


def stop(*, run: str | None = None, request_id: str | None = None, now: float | None = None) -> dict:
    """The person stopped the run: it ends as stopped, and the exports it started stop too (the export worker kills
    its current melt run and gives the PC lock back; finished chunks stay for a Carry on)."""
    rec = _find(run, request_id)
    if rec.get('active'):
        rec = finish(run=rec['run'], outcome='stopped', now=now)
    if not rec:
        return rec
    stopped = []
    projects = {_norm(p) for p in rec.get('projects') or []}
    folder = _norm(rec['folder']).rstrip('\\/') + os.sep if rec.get('folder') else ''
    try:
        import letitedit.timeline.render_queue as rq
        for job in rq.list_jobs(40):
            project = _norm(job.get('project') or '')
            if (project in projects or (folder and project.startswith(folder))) and job.get('state') not in (
                    'done', 'failed', 'error', 'cancelled', 'interrupted'):
                rq.cancel(job['job_id'])
                stopped.append(job['job_id'])
    except Exception as exc:  # noqa: BLE001 - ending the run's record matters more than an export we can't reach
        rec['stop_error'] = str(exc)
    rec['stopped_jobs'] = stopped
    return _save(rec)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'finish', 'waiting', 'working', 'show', 'stop', 'limit'))
    parser.add_argument('--json', default='{}')
    parser.add_argument('--failed', action='store_true')
    parser.add_argument('--outcome', choices=('done', 'stopped', 'failed'))
    args = parser.parse_args()
    meta = json.loads(args.json)
    run, request_id = meta.get('run'), meta.get('request_id')
    if args.action == 'start':
        result = start(meta)
    elif args.action == 'finish':
        result = finish(success=not args.failed, request_id=request_id, run=run, outcome=args.outcome)
    elif args.action == 'stop':
        result = stop(run=run, request_id=request_id)
    elif args.action == 'limit':
        result = set_limit(run=run, request_id=request_id, words=meta.get('words') or '',
                           resets_at=meta.get('resets_at'))
    elif args.action in ('waiting', 'working'):
        result = set_waiting(args.action == 'waiting', request_id=request_id, run=run)
    else:
        result = _find(run, request_id) or _read(root() / 'live.json')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
