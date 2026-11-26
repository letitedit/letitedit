"""New video's first cut on the session runner, for the person's own editor (T331 P11; T319 rule 4). On by default.

The editor's chat runs this (bridge/new_video_runner.py) when New video sends its request and this switch and the
runner's own (session_runner) are on. It works on disk, with no window:

1. **The checks that start nothing** (`why_not`): the switches, a Short or a YouTube video (a request for both, or one
   the person described, keeps the window: its project's shape is the AI's call), not Turbo, a footage path that
   exists. A refusal here is a fallback: the editor sends the request to its AI in the window, as before, and says so in
   one line.
2. **The project, made before the AI starts** (`make_project`): `<save folder>/<folder name>.mlt`, 1080x1920 for a
   Short and 1920x1080 for a YouTube video, at the first clip's frame rate. The request gets one line naming it, so
   the AI uses it and never makes another (the Studio's prepared project, the same way).
3. **The runner's own checks** (session_runner.Runner.preflight). A refusal there is a fallback too, and the project
   made in step 2 is taken away again (only files this run made: the empty project and the empty working folder).
4. **The three phases** (plan and rough cut, fine cut and finish, review and export), each a fresh session on a
   private desktop, with a progress line before and after each. The run's tool servers carry the chat's progress run
   (LETITEDIT_PROGRESS_RUN), so New video's card follows them as it follows the window's AI.
5. **The end:** the run's status, the project and the newest export. The editor ends the chat's request; its Home
   page then opens the finished project in the person's window, the same way it does after the window path when the
   AI opened nothing (only an empty, unchanged window: home/welcomepage.h useFinishedVideo, MAIN.openWithoutFocus).

Stop: a line `stop` on stdin, or stdin closed (the editor went away), ends the run's sessions and leaves the run's
record (`<project>.letitedit/session-runner.json`), so a later start carries on the same sessions.

The switch: settings.json `new_video_runner` (default true); LETITEDIT_NEW_VIDEO_RUNNER (1 or 0) wins. Both it and
session_runner's switch must be on.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

SETTING = 'new_video_runner'
ENV = 'LETITEDIT_NEW_VIDEO_RUNNER'
RUNS_ENV = 'LETITEDIT_NEW_VIDEO_RUNS'        # where each run's AI starts (tests); default LOCALAPPDATA\letitedit
SIZES = {'short': (1080, 1920), 'long': (1920, 1080)}
VIDEO_EXT = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp', '.mpg', '.mpeg'}
PROJECT_LINE = ("letitedit has already made this video's project: {path}. Use that existing project for the whole "
                'video; do not create another. Keep its stage artifacts beside it.')


def enabled():
    """This switch and the session runner's: both on."""
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('0', 'false', 'off', 'no'):
        return False
    if forced not in ('1', 'true', 'on', 'yes'):
        try:
            import letitedit.core.hardware as hardware
            if hardware.settings().get(SETTING) is False:
                return False
        except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
            pass
    from letitedit.studio import session_runner
    return session_runner.enabled()


def facts(request, folder):
    """The typed request's facts (the record New video keeps in the save folder), else the request text's, plus the
    footage paths."""
    from letitedit.app import new_video_request as typed
    record = None
    try:
        record = typed.read(folder) if folder else None
    except (typed.RequestError, OSError):
        record = None
    if record:
        out = dict(typed.facts(record))
        footage = record.get('footage') or {}
        out['footage'] = [p for p in (footage.get('files') or []) if p] or \
            ([footage['folder']] if footage.get('folder') else [])
        out['source'] = 'typed record'
        return out
    out = dict(typed.facts_from_text(request))
    found = re.search(r'from these files: (.+?)(?: \(use the letitedit skills| in Turbo mode\.)', request) or \
        re.search(r'from the folder (.+?)(?: \(use the letitedit skills| in Turbo mode\.)', request)
    out['footage'] = [p.strip() for p in found.group(1).split(';') if p.strip()] if found else []
    out['source'] = 'request text'
    return out


def why_not(request, folder, info=None):
    """None when the runner may take this New video, else the plain reason it stays in the window."""
    if not enabled():
        return 'letitedit making videos with no window is turned off on this PC.'
    if not folder or not Path(folder).is_dir():
        return "the video's folder isn't there."
    info = info if info is not None else facts(request, folder)
    if info.get('turbo'):
        return 'Turbo makes the video in one conversation.'
    if info.get('kind') not in SIZES:
        return ('a request for both a Short and a YouTube video, or one you described, is shaped by the AI as it '
                'goes.')
    if not info.get('no_footage'):
        if not info.get('footage'):
            return "letitedit couldn't tell which footage this video uses."
        missing = [p for p in info['footage'] if not Path(p).exists()]
        if missing:
            return f'the footage {missing[0]} is not there.'
    return None


def _first_clip(paths_):
    for p in paths_:
        p = Path(p)
        if p.is_file():
            return p
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in VIDEO_EXT:
                    return child
    return None


def project_path(folder):
    folder = Path(folder).resolve()
    name = re.sub(r'[<>:"/\\|?*]+', ' ', folder.name).strip() or 'My video'
    return folder / f'{name}.mlt'


def make_project(folder, info):
    """The video's empty project in its folder, sized for the request; (path, made by this call)."""
    project = project_path(folder)
    if project.exists():
        return project, False
    width, height = SIZES[info['kind']]
    clip = None if info.get('no_footage') else _first_clip(info.get('footage') or [])
    from letitedit.server import core_tools
    try:
        core_tools.new_project(str(project), like=str(clip) if clip else None, width=width, height=height)
    except Exception:  # noqa: BLE001 - a clip that can't be read: the default frame rate
        if project.exists():
            raise
        core_tools.new_project(str(project), width=width, height=height, fps=30)
    project.with_suffix('.letitedit').mkdir(parents=True, exist_ok=True)
    return project, True


def take_back(project):
    """Remove a project this run made and nothing has used (a fallback before any launch): the empty project and its
    working folder when empty. Anything else stays."""
    project = Path(project)
    work = project.with_suffix('.letitedit')
    if work.is_dir() and not any(work.iterdir()):
        work.rmdir()
    if project.is_file() and not work.exists():
        project.unlink()


def runner_request(request, project):
    line = PROJECT_LINE.format(path=Path(project).as_posix())
    return request if line in request else request.rstrip('\n') + '\n\n' + line + '\n'


def work_dir(project):
    base = os.environ.get(RUNS_ENV) or str(Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'letitedit' /
                                           'new-video-runs')
    return Path(base) / hashlib.sha1(str(Path(project).resolve()).lower().encode('utf-8')).hexdigest()[:16]


def _export_of(folder, since):
    try:
        from letitedit.studio import short
        found = short.final_export(folder, since)
        return str(found) if found else None
    except Exception:  # noqa: BLE001 - the end line simply names no file
        return None


def _final_captions(project):
    """[(start, end, text)] of the captions the finished project shows: its caption feeds (short.caption_cues), else
    a Look's word captions drawn as graphics (as the Studio's result reads them)."""
    import letitedit.timeline.edit_script as es
    from letitedit.studio import short
    script = es.read(str(project))
    captions = short.caption_cues(script.get('captions'))
    if captions:
        return captions
    drawn = set()
    for track in script.get('tracks') or []:
        for item in track.get('items') or []:
            graphic = item.get('graphic') if isinstance(item.get('graphic'), dict) else {}
            if graphic.get('template') != 'word_captions':
                continue
            words = [str(w[0]) for w in (graphic.get('params') or {}).get('words') or []
                     if isinstance(w, (list, tuple)) and w and str(w[0]).strip()]
            if words:
                start = short._secs(item.get('at'))
                drawn.add((round(start, 3), round(start + short._secs(item.get('len')), 3),
                           ' '.join(' '.join(words).split())))
    return sorted(drawn)


def refresh_srt(project, export):
    """The SRT beside the delivered video, written from the finished project's captions when it is missing or older
    than the video (T379: the finish wrote one for a 37 s cut and the review rounds then cut the video to 25 s, so the
    upload file had lines the video no longer says). The path written, or None."""
    try:
        video = Path(export)
        srt = video.with_suffix('.srt')
        if not video.is_file() or (srt.is_file() and srt.stat().st_mtime >= video.stat().st_mtime):
            return None
        captions = sorted(_final_captions(project))
        if not captions:
            return None
        captions = [(a, min(b, captions[n + 1][0]) if n + 1 < len(captions) else b, t)   # no cue over the next
                    for n, (a, b, t) in enumerate(captions)]
        from letitedit.studio import short
        srt.write_text(short._srt(captions), encoding='utf-8')
        return str(srt)
    except Exception:  # noqa: BLE001 - the video is delivered either way; the SRT stays as the AI left it
        return None


class Stop:
    """Set from stdin (a line `stop`, or stdin closed)."""

    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            from letitedit.studio import session_runner
            raise session_runner.RunnerError('stopped', 'cancelled', 'You pressed Stop. Everything done so far stays '
                                             'in your project.')


def run(options, emit, stop=None, runner_factory=None):
    """One New video on the runner. options: {folder, request, progress_run?, engine?}. emit(dict) gets the events:
    fallback {reason} | started {project, phases} | progress {message, phase?} | done {project, export, status} |
    stopped {code, message, phase?}. Returns the last event."""
    from letitedit.app import ai_clis, phases
    from letitedit.studio import session_runner
    stop = stop or Stop()
    folder = options.get('folder') or ''
    request = options.get('request') or ''

    def fallback(reason):
        event = {'event': 'fallback', 'reason': reason}
        emit(event)
        return event

    settings = ai_clis.chat_settings()
    engine = options.get('engine') or settings.get('engine') or 'claude'
    why = session_runner.supported(engine)
    if why:
        return fallback(why)
    if not request.strip():
        return fallback('the request was empty.')
    info = facts(request, folder)
    why = why_not(request, folder, info)
    if why:
        return fallback(why)
    try:
        project, made = make_project(folder, info)
    except Exception as e:  # noqa: BLE001 - nothing launched: the window takes it
        return fallback(f"letitedit couldn't make the video's project ({e}).")
    # the person's own Looks, as this window keeps them: the run's tool server works as an instance of its own
    # (never the person's window), whose My Looks would be an empty folder, so a Look the person picked from their own
    # in New video would not be found (T331 P12)
    from letitedit.looks import learned_looks
    env = {'LETITEDIT_MY_LOOKS': str(learned_looks.root())}
    if options.get('progress_run'):
        env['LETITEDIT_PROGRESS_RUN'] = str(options['progress_run'])
    wd = work_dir(project)
    wd.mkdir(parents=True, exist_ok=True)
    make = runner_factory or session_runner.Runner
    runner = make(project, runner_request(request, project), engine=engine, settings=settings, work_dir=wd,
                  check=stop.check, note=lambda text: emit({'event': 'progress', 'message': text}), env=env)
    try:
        runner.preflight()
    except session_runner.RunnerError as e:
        if made:
            take_back(project)
        return fallback(e.message)
    since = time.time()
    emit({'event': 'started', 'project': str(project), 'phases': list(phases.AI_PHASES)})
    count = len(phases.AI_PHASES)
    state = None
    for number, phase in enumerate(phases.AI_PHASES, 1):
        title = phases.PHASES[phase]['title']
        emit({'event': 'progress', 'phase': phase,
              'message': f'Part {number} of {count}: {title}.'})
        try:
            stop.check()
            state = runner.run_until(phase)
        except session_runner.RunnerError as e:
            began = bool((runner._load() or {}).get('sessions')) if hasattr(runner, '_load') else True
            if e.kind == 'refused' and not began:
                if made:
                    take_back(project)
                return fallback(e.message)
            event = {'event': 'stopped', 'code': e.code, 'message': e.message, 'phase': phase,
                     'project': str(project)}
            emit(event)
            return event
    event = {'event': 'done', 'project': str(project), 'export': _export_of(project.parent, since),
             'status': (state or {}).get('status')}
    if event['export']:
        srt = refresh_srt(project, event['export'])
        if srt:
            event['srt'] = srt
    emit(event)
    return event


def main(stdin, stdout):
    """The editor's entry: the first line on stdin is the JSON options; then `stop` (or stdin closed) stops."""
    from letitedit.core import pipe_input
    stdin = pipe_input.reader(stdin)       # the Stop listener never leaves a read waiting while the run loads libraries
    first = stdin.readline()
    if isinstance(first, bytes):
        first = first.decode('utf-8-sig')
    try:
        options = json.loads(first or '{}')
    except ValueError:
        options = {}
    lock = threading.Lock()

    def emit(event):
        with lock:
            stdout.write(json.dumps(event, ensure_ascii=True) + '\n')
            stdout.flush()
    stop = Stop()

    def listen():
        for line in stdin:
            if isinstance(line, bytes):
                line = line.decode('utf-8', 'replace')
            if line.strip().lower() == 'stop':
                break
        stop.event.set()                       # a stop, or the editor went away
    threading.Thread(target=listen, daemon=True).start()
    try:
        last = run(options, emit, stop)
    except Exception as e:  # noqa: BLE001 - the editor always hears how it ended
        last = {'event': 'stopped', 'code': 'error', 'message': f'letitedit hit a problem making the video: {e}'}
        emit(last)
    return 0 if last.get('event') in ('done', 'fallback') else 1
