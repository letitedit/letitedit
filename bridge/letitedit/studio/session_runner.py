"""The session runner: New video's phases driven on disk, with no editor window (T319's H2; T331 step P9). Off by
default.

    enabled()                         the switch
    supported(engine)                 None when the runner can drive this AI, else why not (said before any launch)
    Runner(project, request, ...)     one video's run: run_until(phase) runs its AI phases up to that one
    RunnerError                       a refusal before any launch (`refused`) or a stop after one (`stopped`)

What it does, for each AI phase of letitedit.app.phases (plan_rough, fine_finish, review_export):
- **Before the run:** the AI is one this runner drives (Claude Code; Codex's half waits, see CODEX below), the person
  lets letitedit run their AI with nobody watching (the chat's background_jobs), the program is on this PC, the
  project exists and no letitedit window has it open (the file is the only state), the AI's folder is outside the
  install (an AI started in it obeys our own AGENTS.md), and no other runner owns the project (a lease). Then P2's
  probe: which built-in tools this PC's Claude Code offers (ai_clis.probe_editing_tools; it uses no allowance), so an
  editing session turns off exactly the unused ones when that switch is on.
- **Each phase:** its complete first message from stage_start.build (the phase's skills, guide sections and inputs in
  full; never cut to fit: too big is a refusal), a fresh session with its own id chosen before the launch, the
  letitedit tool server with the phase's tool profile when that switch is on (tool_profiles.mcp_env), the run's model
  choice. The first message is checked against the program's echo of it (stage_start.verify on what it received).
  With T342's switch on (stage_start.first_message_on, on by default), the guide's index in it follows the tool
  profile, and the fine-and-finish phase's first message is for its fine step: the AI ends its turn after it, and
  the finish step's own skills and references come with the message that starts the finish step (_with_later), once.
  The phase is never accepted as done while they are due: an AI that went on past the fine step without them (in
  one turn, or before a restart) gets them with a message to check every finishing change against them and fix what
  they require, and the phase is accepted only after that turn (_later_due, _check_text). Before they are sent, a
  carry-on asks for the fine step only (_step_text). They count as sent only once the program's echo of the whole
  message matches; unconfirmed, they go again (_send, _confirm_later). A restart that has to start the phase again
  whole after its work was done sends a check of that work after the start (_recheck_text).
- **A turn's end** comes from the program's stream or its exit (claude_session), never from an idle timer. Then the
  phase's outputs are checked in code (phases.done, on the saved file) with no export of the video's folder still
  running. Done: the next phase starts in a fresh session, built from the files. Not done: the same session is asked
  to finish the phase (CARRY_ONS times at most), naming what is missing. A blocker the AI states, a usage limit or a
  sign-in problem stops the run and says so, with the AI's own words (T352: also when Claude Code names the failed
  API call on its message and its result still says "success").
- **The books** (T331 P8, letitedit.app.bookkeeping, when its switch `new_video_bookkeeping` is on): after each turn
  the stage marks the files support (`marks`); when a phase's outputs check out, its marks, why markers and the
  hand-over (`after_phase`), whose handover.md the next phase's start attaches. Off, or on an install without it,
  the AI keeps its own books as the skills say.
- **The model per turn** (T331 P10, ai_clis.choice): a pin or the person's saved model runs every turn. Under Auto
  (the person's model is "auto", or they never chose one and settings.json auto_routing is on) each turn takes the
  model of its sub-step's role (phases.PHASES[phase]['step_roles'], the step the files say the work is at): a phase
  whose steps' roles give different models (fine on the planning model, finish on the routine one) asks the AI to end
  its turn after the first, and the next step's message goes to the same session carried on (--resume) with the
  other model. At most one switch a phase (a switch rewrites the conversation's cache once). Never another AI.
- **A preview** (stop_after='rough') ends after the plan and rough cut phase: no later phase starts, so nothing can
  carry it on.
- **Every attempt is kept** in `<project>.letitedit/session-runner.json`: each phase's state (prepared, launching,
  created, acked, done), every session id of every attempt, the probe, the first message's size and checksum. A run
  started again after a stop reconciles each unfinished phase with Claude Code's own record of its session
  (claude_session.session_log): a session that began is carried on (--resume), never started a second time; one that
  never began is launched again under the same id. A missing acknowledgement alone never counts as "nothing started".
- **Before a retry** the earlier attempt's processes are ended (matched by creation time, never by name), and the run
  waits for its own clean-up: the video's exports still running and the PC lock held by one of those processes
  (T305's retry refused twice on a PC-lock hold that was gone seconds later).

The AI and its tool server run on a private Windows desktop of the run's own (spawn_on_desktop), so nothing they start
can take the person's keyboard focus or show on their screen; no console window opens.

CODEX: the runner's transports are TRANSPORTS. Codex's half (its app-server, `thread/start` / `turn/start`, as the
editor's aicodexserver.h speaks it, and its per-run `-c` options for the built-in tools) is not written yet: it waits
for the owner's Codex credits. supported('codex') says so, and a caller (the Studio's short) keeps the window path.

**Self-checks** (T345 C3, server/self_checks.py's switch `self_checks`, on by default), two parts of the runner's own:
- **The review's code checks before its phase:** with P3's review order on (review_order.enabled), before the review
  phase's first message is built the runner runs the review bundle's measured checks itself (review_bundle.bundle on
  a preview export, no critic, no round used) and attaches its reply as stage evidence (`code-checks.md` beside the
  project), so the AI opens the phase with their result. A bundle that can't run is recorded and the phase starts as
  before.
- **The phase's tools loaded up front:** with tool profiles on (P7), each Claude Code session starts with
  ENABLE_TOOL_SEARCH=false, in its environment and in its --settings env block (flag settings outrank the person's
  own). Claude Code 2.1.329 defers MCP tools behind its ToolSearch tool by default; that value turns the deferral off,
  so the profile's tools come with the session's opening (its tool-search mode function returns "standard" for a
  false value: `Cie()` in the program, beside "Invalid ENABLE_TOOL_SEARCH value ... expected auto:N"). Codex: UP_FRONT
  holds no setting for it (no deferral setting is known for Codex; its half of the runner waits, see CODEX).
The open project at the end needs nothing here: a run with no window opens nothing (core_tools.show says so) and the
editor's Home page opens the finished project (studio/first_cut.py, step 5).

**Sub-step sessions** (T354, letitedit.app.substeps' switch `substep_sessions`, on by default, read once when a run
starts): the run's units are the phases' sub-steps (log_plan, rough_cut, fine_cut, finishing, review_rounds,
final_look) instead of the three phases, each in a fresh session with its own first message, model role and tool
profile, by the same machinery as a phase (`_order`, `_spec`). A sub-step is done when its outputs check out
(substeps.done) and, when another follows, its hand-off does too: at its end the books are kept (the marks, and the
why markers once there is a cut), then letitedit.studio.substep_handoff writes the hand-off and checks it against
the files. Gaps count as missing outputs (the same session is asked to fill them, CARRY_ONS times at most; then the run
stops, `handoff_incomplete`, naming them). Before the next session starts the saved hand-off is verified again
(unchanged, still complete), and a gap stops the run there. The next session's first message attaches it as its
`handover`. Off, the runner is as before, byte for byte.

**A session per review round** (T363's cut 3, letitedit.app.substeps' switch `review_round_sessions`, off by default,
read once when a run starts; with sub-step sessions on): the review rounds sub-step's session ends once its critic
round is done (review_memory.json records one more round than when it began; the bundle's reply says so, through
LETITEDIT_RUN_ROUND_SESSIONS in its tool server's environment). With rounds left, the books are kept (the marks, the
why markers), letitedit.studio.round_handoff writes the next round's hand-off (the standing record of a sub-step
hand-off, what the round changed, the calls that failed, the files it read and its closing note) and checks it; a gap
is asked for in the same session (then `handoff_incomplete`, as for a sub-step). The next round starts in a fresh
session, its own id chosen first, from the sub-step's first message with that hand-off attached; the code checks that
opened round 1 are not attached again. The rounds used up, or a review of the cut now ready, end the sub-step as before.

The switch: settings.json `session_runner` (default true); LETITEDIT_SESSION_RUNNER (1 or 0) wins.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import letitedit.core.paths as paths

SETTING = 'session_runner'
ENV = 'LETITEDIT_SESSION_RUNNER'
STATE_FILE = 'session-runner.json'
LEASE_FILE = 'session-runner.lease'
FORMAT = 'letitedit-session-runner/1'
TRANSPORTS = ('claude',)          # Codex: see CODEX in the module text
CARRY_ONS = 2                     # the editor's ordinary carry-ons per stage conversation (ainewvideocarry.h)
PHASE_LIMIT_S = 4 * 3600          # a ceiling for one turn, not a done signal: past it the run stops
SWITCHES = 1                      # model switches a phase may make (T319 rule 3: at most once a phase)
SETTLE_S = 600                    # before a retry: how long to wait for the earlier attempt's own clean-up
EXPORT_WAIT_S = 1800              # after a turn: how long to wait for the video's exports still running
POLL_S = 2.0
ECHO_WAIT_S = 120               # how long the program has to echo the first message before the AI's turn counts
PREVIEW_STOPS = {'rough': 'plan_rough'}
UP_FRONT = {'claude': {'ENABLE_TOOL_SEARCH': 'false'}, 'codex': {}}   # T345 C3: no tool deferral (see the text)
CODE_CHECKS_PHASE = 'review_export'
HANDOFF_GAP = 'handoff_incomplete'
ROUND_UNIT = 'review_rounds'      # T363's cut 3: the sub-step whose critic rounds take a session each
CODE_CHECKS_FILE = 'code-checks.md'
CODE_CHECKS_HEAD = ("# The review's measured checks, run by letitedit before this phase\n\n"
                    "letitedit_review_bundle(project, render='preview') with no critic: no review round was used. "
                    "Its reply, as the tool gives it:\n\n")


class RunnerError(RuntimeError):
    """kind: 'refused' (nothing was launched) or 'stopped' (a launched run stopped); code: a short reason."""

    def __init__(self, kind, code, message, **detail):
        super().__init__(message)
        self.kind, self.code, self.message, self.detail = kind, code, message, detail


def signin_line(engine, said):
    """The plain line a sign-in failure stops the run with: the AI's own words, and what the person does."""
    name = {'claude': 'Claude', 'codex': 'Codex'}.get(engine, engine or 'the AI')
    words = ' '.join(str(said or '').split())[:200]
    return (f'{name} is not signed in on this PC' + (f' (it said: "{words}")' if words else '') +
            f'. Sign in to {name} again, then run this again.')


def enabled():
    """Whether New video's phases may run through this runner on this install (on by default)."""
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def self_checks_on():
    """T345 C3's switch (server/self_checks.py): off, or unreadable, means off."""
    try:
        from letitedit.server import self_checks
        return self_checks.enabled()
    except Exception:  # noqa: BLE001 - an install without it: off
        return False


PYTHON_ON_PATH = 'session_python_on_path'
PYTHON_ON_PATH_ENV = 'LETITEDIT_SESSION_PYTHON_ON_PATH'


def python_on_path_on():
    """T360's switch (on by default since 24 Nov; settings.json `session_python_on_path: false` turns it off, and the
    environment variable, 1 or 0, wins): the run's own Python first on the session's PATH."""
    forced = os.environ.get(PYTHON_ON_PATH_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(PYTHON_ON_PATH) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def with_python_on_path(env, python):
    """env with the folder of `python` (the Python the run's tool server runs on) first on PATH, so a `python` the AI
    types in Bash or PowerShell is that one, with letitedit_ai's packages, also on a PC with no Python of its own
    (T360: a clean Azure PC answered "Python was not found" to six of the AI's calls in two runs). Windows names PATH
    in any case; the key already there is kept."""
    folder = str(Path(python).parent) if python else ''
    if not folder or not Path(folder).is_dir():
        return env
    out = dict(env)
    key = next((k for k in out if k.upper() == 'PATH'), 'PATH')
    parts = [p for p in str(out.get(key) or '').split(os.pathsep) if p]
    parts = [folder] + [p for p in parts if os.path.normcase(os.path.normpath(p)) !=
                        os.path.normcase(os.path.normpath(folder))]
    out[key] = os.pathsep.join(parts)
    return out


def up_front_env(engine, profiles=None):
    """The environment entries that load a session's letitedit tools with its opening instead of on first use: {}
    unless the self-checks switch and tool profiles are on (all 88 tools up front would make every step larger)."""
    if not self_checks_on():
        return {}
    if profiles is None:
        try:
            from letitedit.server import tool_profiles
            profiles = tool_profiles.enabled()
        except Exception:  # noqa: BLE001 - no profiles readable: the tools stay deferred
            profiles = False
    return dict(UP_FRONT.get(engine) or {}) if profiles else {}


def supported(engine):
    """None when the runner drives this AI, else the plain reason it doesn't (a caller keeps its window path)."""
    if engine in TRANSPORTS:
        return None
    if engine == 'codex':
        return ("The session runner drives Claude Code only for now; Codex's half (its app-server sessions) is still "
                'to come, so New video uses its window here.')
    return f'The session runner does not drive {engine or "this AI"}; this run uses the window.'


def _substeps():
    """letitedit.app.substeps when its switch (substep_sessions) is on for this run, else None (T354)."""
    try:
        from letitedit.app import substeps
    except ImportError:
        return None
    try:
        return substeps if substeps.enabled() else None
    except Exception:  # noqa: BLE001 - a switch reader that fails: off
        return None


def install_root():
    return Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or paths.ROOT_TEXT))


def _now():
    return time.time()


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def _stamp(pid):
    """A process's creation time while it runs (a reused process id is never mistaken for it), else None."""
    if not pid:
        return None
    if os.name != 'nt':
        try:
            os.kill(int(pid), 0)
            return 'alive'
        except OSError:
            return None
    from letitedit.app import letitedit_instances
    try:
        return letitedit_instances.process_stamp(int(pid))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ the private desktop

if os.name == 'nt':
    import ctypes.wintypes as wt
    import msvcrt
    _u32, _k32 = ctypes.windll.user32, ctypes.windll.kernel32
    _u32.CreateDesktopW.restype = ctypes.c_void_p
    _u32.CreateDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.c_ulong, ctypes.c_void_p]
    _u32.CloseDesktop.argtypes = [ctypes.c_void_p]
    _k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    _k32.WaitForSingleObject.restype = wt.DWORD
    _k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    _k32.CloseHandle.argtypes = [wt.HANDLE]


class DesktopProcess:
    """A program started on a private desktop with pipes for its input and output (what spawn_on_desktop returns):
    stdin, stdout, pid, poll(), wait(timeout), kill(), as subprocess.Popen."""

    def __init__(self, pid, handle, stdin, stdout):
        self.pid, self._handle, self.stdin, self.stdout = pid, handle, stdin, stdout
        self.returncode = None

    def poll(self):
        if self.returncode is None and self._handle:
            code = wt.DWORD()
            if _k32.GetExitCodeProcess(self._handle, ctypes.byref(code)) and code.value != 259:
                self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout=None):
        if self.poll() is not None:
            return self.returncode
        ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        if _k32.WaitForSingleObject(self._handle, ms) != 0:
            raise subprocess.TimeoutExpired('desktop process', timeout)
        return self.poll()

    def kill(self):
        if self.poll() is None:
            _k32.TerminateProcess(self._handle, 1)

    def close_handle(self):
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = None


class Desktop:
    """A private Windows desktop for one run's AI and everything it starts. spawn(args, env, cwd) starts a program on
    it with pipes; close() closes the desktop (after its programs have ended)."""

    BELOW_NORMAL = 0x4000
    CREATE_UNICODE_ENVIRONMENT = 0x400
    CREATE_NO_WINDOW = 0x08000000
    CREATE_SUSPENDED = 0x00000004
    STARTF_USESHOWWINDOW = 0x1
    STARTF_USESTDHANDLES = 0x100
    GENERIC_ALL = 0x10000000

    def __init__(self, name):
        self.name = name
        self._handle = None
        self.processes = []

    def open(self):
        if os.name != 'nt' or self._handle:
            return self
        handle = _u32.CreateDesktopW(self.name, None, None, 0, self.GENERIC_ALL, None)
        if not handle:
            raise OSError(f'CreateDesktop failed: {_k32.GetLastError()}')
        self._handle = handle
        return self

    def spawn(self, args, env, cwd):
        if os.name != 'nt':                               # pragma: no cover - the runner's desktop is Windows only
            return subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=env, cwd=str(cwd))
        from letitedit.studio.window import _PROCESS_INFORMATION, _STARTUPINFOW
        import letitedit.core.render_lock as render_lock
        self.open()
        child_in, parent_in = os.pipe()                   # the program reads child_in; this process writes parent_in
        parent_out, child_out = os.pipe()
        null = os.open(os.devnull, os.O_WRONLY)
        handles = [msvcrt.get_osfhandle(fd) for fd in (child_in, child_out, null)]
        for h in handles:
            os.set_handle_inheritable(h, True)
        si = _STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = 'WinSta0' + chr(92) + self.name
        si.dwFlags = self.STARTF_USESHOWWINDOW | self.STARTF_USESTDHANDLES
        si.hStdInput, si.hStdOutput, si.hStdError = handles
        pi = _PROCESS_INFORMATION()
        block = ctypes.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in env.items()) + '\0\0')
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in args]))
        flags = self.BELOW_NORMAL | self.CREATE_UNICODE_ENVIRONMENT | self.CREATE_NO_WINDOW | self.CREATE_SUSPENDED
        try:
            ok = _k32.CreateProcessW(None, line, None, None, True, flags, block, str(cwd), ctypes.byref(si),
                                     ctypes.byref(pi))
            if not ok:
                raise OSError(f'CreateProcess failed: {_k32.GetLastError()}')
        finally:
            for fd in (child_in, child_out, null):          # the program has its own copies now
                os.close(fd)
        try:
            # born suspended, tied to this process's owner job (it ends with its owner however the owner ends)
            render_lock.tie_process(pi.hProcess, strict=False)
            render_lock.resume_process(pi.hProcess)
        except BaseException:
            _k32.CloseHandle(pi.hThread)
            _k32.CloseHandle(pi.hProcess)
            os.close(parent_in)
            os.close(parent_out)
            raise
        _k32.CloseHandle(pi.hThread)
        proc = DesktopProcess(int(pi.dwProcessId), pi.hProcess, os.fdopen(parent_in, 'wb', buffering=0),
                              os.fdopen(parent_out, 'rb'))
        self.processes.append(proc)
        return proc

    def close(self):
        for proc in self.processes:
            proc.close_handle()
        self.processes = []
        if os.name == 'nt' and self._handle:
            _u32.CloseDesktop(self._handle)
            self._handle = None


# ------------------------------------------------------------------ the run

class Runner:
    """One video's AI phases, on disk.

    project      the video's project (.mlt), made before (the Studio's prepared project): the file is the only state
    request      the original New video request text (new_video_request.render of the typed request)
    engine       'claude' (supported() says what else)
    choice       {'model', 'effort'} pinned for the run, or None: the chat's saved choice, else Claude Code's own
    work_dir     where the AI starts (outside the install); its MCP config and settings go there too
    stop_after   'rough' for a preview, else None
    start_phase  the first phase this run does (a final from a preview: 'fine_finish'); earlier ones are given
    check()      called while waiting (a cancel raises from it)
    note(text)   a progress line for the caller (the Studio's events)
    spawn        how the program starts (default: on a private desktop of the run's own)
    env          more variables for the AI and its tool server (the Studio's projects folder)
    run_id       the run's identity, kept in the state file (default: a new one, or the state's)
    """

    def __init__(self, project, request, *, engine='claude', choice=None, work_dir, stop_after=None, start_phase=None,
                 check=None, note=None, spawn=None, run_id=None, settings=None, exe=None, homes=None, env=None):
        from letitedit.app import phases
        self.phases = phases
        self.sub = _substeps()                 # T354: the sub-step table when its switch is on, else None
        # T363's cut 3: a session per review round (with sub-step sessions on; read once, like theirs)
        self.rounds = self.sub is not None and self.sub.round_sessions_on()
        self.project = Path(project).resolve()
        self.work = self.project.with_suffix('.letitedit')
        self.request = request
        self.engine = engine
        self.choice = choice
        self.work_dir = Path(work_dir).resolve()
        self.stop_after = stop_after
        self.stop_phase = PREVIEW_STOPS.get(stop_after) if stop_after else None
        if stop_after and not self.stop_phase:
            raise ValueError(f'A preview stops after one of: {", ".join(PREVIEW_STOPS)}')
        if self.sub is not None and self.stop_phase:
            self.stop_phase = self.sub.last_of(self.stop_phase)
        self.start_phase = start_phase
        self.check = check or (lambda: None)
        self.note = note or (lambda text: None)
        self._spawn = spawn
        self._desktop = None
        self.run_id = run_id
        self.settings = settings
        self.exe = exe
        self.homes = homes
        self.env = dict(env or {})
        self.state_path = self.work / STATE_FILE
        self.lease_path = self.work / LEASE_FILE
        self._attempt_begun = False
        self.offered = None

    # ---------------------------------------------------------------- the units: phases, or their sub-steps (T354)

    def _order(self):
        return self.sub.ORDER if self.sub is not None else self.phases.AI_PHASES

    def _spec(self, unit):
        if self.sub is not None and unit in self.sub.SUBSTEPS:
            return self.sub.SUBSTEPS[unit]
        return self.phases.PHASES[unit]

    def _noun(self, unit):
        return self._spec(unit).get('noun') or 'phase'

    def _title(self, unit):
        return f"{self._spec(unit)['title']} {self._noun(unit)}"

    def _display_title(self, unit):
        spec = self._spec(unit)
        return f"{spec['title']} {spec.get('display_noun') or self._noun(unit)}"

    def _done_of(self, unit):
        if self.sub is not None and unit in self.sub.SUBSTEPS:
            return self.sub.done(unit, self.project, self.request, live=False)
        return self.phases.done(unit, self.project, self.request, live=False)

    def _first_step(self, unit):
        if self.sub is not None and unit in self.sub.SUBSTEPS:
            return self.sub.first_step(unit, self.project)
        return self.phases.first_step(unit, self.project)

    def _unit_of(self, phase):
        """The unit a phase id names for this run: the phase itself, or (sub-steps on) its last sub-step."""
        if self.sub is not None and phase in self.phases.PHASES:
            return self.sub.last_of(phase)
        return phase

    def _drops(self, unit):
        """The words a unit's own lack shows up as in a later unit's missing list."""
        spec = self._spec(unit)
        out = {f'the {self._title(unit)}'}
        if spec.get('phase'):
            out.add(f"the {self.phases.PHASES[spec['phase']]['title']} phase")
        return out

    # ---------------------------------------------------------------- state

    def _load(self):
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as e:
            raise RunnerError('refused', 'state_unreadable', f'The run\'s record {self.state_path} cannot be read, '
                              'so letitedit will not guess what an earlier attempt did. Nothing was started.',
                              error=str(e)) from e
        if not isinstance(data, dict) or data.get('format') != FORMAT or not isinstance(data.get('phases'), dict):
            raise RunnerError('refused', 'state_unreadable', f'The run\'s record {self.state_path} is not one this '
                              'runner wrote. Nothing was started.')
        return data

    def _save(self, state):
        state['updated'] = _now()
        _atomic_json(self.state_path, state)

    def _state(self):
        state = self._load()
        digest = hashlib.sha256(self.request.encode('utf-8')).hexdigest()
        if state is None:
            state = {'format': FORMAT, 'run_id': self.run_id or uuid.uuid4().hex, 'engine': self.engine,
                     'project': str(self.project), 'request_sha256': digest, 'first_since': _now(), 'attempts': 0,
                     'phases': {}, 'sessions': [], 'status': 'running'}
        elif state.get('engine') != self.engine:
            raise RunnerError('refused', 'engine_changed', f"This video's run is {state.get('engine')}'s; it never "
                              f'goes on with another AI ({self.engine}). Nothing was started.')
        elif state.get('request_sha256') != digest:
            state.setdefault('requests', []).append({'sha256': state.get('request_sha256'), 'until': _now()})
            state['request_sha256'] = digest
        self.run_id = state['run_id']
        return state

    # ---------------------------------------------------------------- the lease (one runner per project)

    def _take_lease(self):
        self.work.mkdir(parents=True, exist_ok=True)
        me = {'pid': os.getpid(), 'stamp': _stamp(os.getpid()), 'since': _now()}
        for _ in range(2):
            try:
                fd = os.open(self.lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    held = json.loads(self.lease_path.read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    held = {}
                if held.get('pid') and _stamp(held['pid']) == held.get('stamp') and held.get('stamp'):
                    if held['pid'] == os.getpid():
                        return
                    raise RunnerError('refused', 'owned', 'Another run of letitedit is already working on this '
                                      f"video (process {held['pid']}). Nothing was started.", owner=held)
                self.lease_path.unlink(missing_ok=True)     # its owner has ended
                continue
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(me, f)
            return
        raise RunnerError('refused', 'owned', 'letitedit could not take this video for the run. Nothing was started.')

    def _drop_lease(self):
        try:
            held = json.loads(self.lease_path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return
        if held.get('pid') == os.getpid():
            self.lease_path.unlink(missing_ok=True)

    # ---------------------------------------------------------------- before any launch

    def _chat_settings(self):
        if self.settings is not None:
            return self.settings
        from letitedit.app import ai_clis
        return ai_clis.chat_settings()

    def preflight(self):
        """Everything checked before a program starts. Raises RunnerError('refused', ...) and starts nothing."""
        from letitedit.app import ai_clis
        why = supported(self.engine)
        if why:
            raise RunnerError('refused', 'ai_not_supported', why)
        settings = self._chat_settings()
        if not ai_clis.background_allowed(settings):
            raise RunnerError('refused', 'background_off', 'The person has turned off running their AI with nobody '
                              'watching (Connect Your AI), so this run uses the window.')
        self.exe = self.exe or ai_clis.find(self.engine, settings)
        if not self.exe:
            raise RunnerError('refused', 'ai_missing', f'{ai_clis.NAMES.get(self.engine, self.engine)} is not on '
                              'this PC.')
        if not self.project.is_file():
            raise RunnerError('refused', 'no_project', f'The project {self.project} does not exist yet; it is made '
                              'before the run (the Studio prepares it).')
        roots = {install_root().resolve(), paths.CODE_ROOT.resolve()}
        if any(self.work_dir == r or self.work_dir.is_relative_to(r) for r in roots):
            raise RunnerError('refused', 'ai_folder_in_install', f'The AI would start in {self.work_dir}, inside '
                              "letitedit's own folder, where it would obey letitedit's development notes. Nothing was "
                              'started.')
        open_in = self._open_in()
        if open_in:
            raise RunnerError('refused', 'project_open', f"The project is open in letitedit's window "
                              f"'{open_in}'. A run without a window needs the file to be the only state: close it or "
                              'use a copy. Nothing was started.')
        from letitedit.app import stage_start
        try:                                              # the first phase's message can be made in full
            first = self._next_phase(self._state())
            if first is not None:
                self._bundle(first)
        except stage_start.IncompleteStart as e:
            raise RunnerError('refused', 'start_incomplete', f'The first message could not be made in full: {e} '
                              'Nothing was cut and nothing was started.') from e

    def _open_in(self):
        try:
            from letitedit.app import letitedit_instances
            for row in letitedit_instances.list_instances():
                shown = row.get('project')
                if shown and Path(shown).resolve() == self.project:
                    return row.get('instance_id') or 'main'
        except Exception:  # noqa: BLE001 - no window answers: none has it open
            return None
        return None

    def probe(self):
        """P2's probe, before each run: the built-in tools this PC's Claude Code offers (no model answers it, so it
        uses no allowance), and the arguments that turn the unused ones off (none while that switch is off)."""
        from letitedit.app import ai_clis
        try:
            self.offered = ai_clis.probe_editing_tools(self.exe)
        except Exception:  # noqa: BLE001 - a probe that fails leaves the safe default (PowerShell kept)
            self.offered = None
        return ai_clis.editing_tool_args(offered=self.offered)

    # ---------------------------------------------------------------- the phases

    def _given(self):
        """The phases before start_phase: given to this run (a final from a preview), not checked again."""
        if not self.start_phase:
            return ()
        order = self._order()
        start = self.sub.first_of(self.start_phase) if self.sub is not None else self.start_phase
        return order[:order.index(start)]

    def _outputs(self, phase):
        """(done, missing) of a phase from the saved files; a given phase's own lack never counts against a later
        one (the preview's rough render stays with the preview)."""
        result = self._done_of(phase)
        missing = list(result['missing'])
        given = self._given()
        if given:
            drop = set()
            for name in given:
                before = self._done_of(name)
                drop |= set(before['missing']) | self._drops(name)
            # a phase between the given ones and this one that lacks only what a given phase lacks is done too (the
            # final's copy has no rough render of its own, so fine_finish read as not done through plan_rough)
            order = self._order()
            for name in order[:order.index(phase)] if phase in order else ():
                if name in given:
                    continue
                own = self._done_of(name)['missing']
                if not [m for m in own if m not in drop]:
                    drop |= self._drops(name)
            missing = [m for m in missing if m not in drop]
        return not missing, missing, result.get('newest')

    def _pending(self):
        from letitedit.app import new_video_carry
        try:
            return sorted(str(p) for p in new_video_carry.pending_exports(self.project.parent))
        except Exception:  # noqa: BLE001 - unknown job state blocks a transition, never passes it
            return ['(the exports could not be read)']

    def _next_phase(self, state):
        for phase in self._order():
            if phase in self._given():
                continue
            if (state['phases'].get(phase) or {}).get('state') != 'done':
                return phase
        return None

    @staticmethod
    def _bookkeeping():
        """letitedit.app.bookkeeping (T331 P8: the marks, why markers and hand-over written in code) when its switch
        is on for this run, else None (switched off, or an install without it)."""
        try:
            import letitedit.app.bookkeeping as bookkeeping
        except ImportError:
            return None
        try:
            return bookkeeping if bookkeeping.enabled() else None
        except Exception:  # noqa: BLE001 - a switch reader that fails: off
            return None

    def _phase_done(self, state, entry, phase, newest, **extra):
        """A phase's outputs check out: recorded, then (with bookkeeping on) the books kept in code: its marks, the
        why markers and the hand-over the next phase's start attaches (P8's after_phase)."""
        entry.update(state='done', ended=_now(), newest=newest, **extra)
        books = self._bookkeeping()
        if self.sub is not None:            # T354: kept at the sub-step's end, before its hand-off (_close_unit)
            books = None
        if books is not None:
            try:
                receipt = books.after_phase(self.project, self.request, phase,
                                            entry.get('started') or state.get('first_since') or 0)
            except Exception as e:  # noqa: BLE001 - the books never stop a run whose outputs checked out
                receipt = {'error': f'{type(e).__name__}: {e}'}
            entry['bookkeeping'] = receipt if isinstance(receipt, dict) else {'receipt': str(receipt)}
            if isinstance(receipt, dict) and receipt.get('handover'):
                entry['handover'] = str(receipt['handover'])
        self._save(state)

    def _marks(self):
        """After a turn, with bookkeeping on: the stage marks the files support (P8's marks; safe after any turn)."""
        books = self._bookkeeping()
        if books is not None:
            try:
                books.marks(self.project, self.request)
            except Exception:  # noqa: BLE001 - a mark refused or unwritable is the journal's own business
                pass

    def _handover(self, phase, state):
        """The hand-over the phase before this one left: the one the books wrote at its end (bookkeeping on), else a
        hand-over note newer than that phase's start (new_video_stages attaches one the same way)."""
        order = self._order()
        index = order.index(phase)
        before = (state['phases'].get(order[index - 1]) or {}) if index else {}
        if self.sub is not None:            # T354: the checked hand-off the sub-step before this one left
            made = before.get('handoff') or {}
            return Path(made['md']) if made.get('md') and Path(made['md']).is_file() else None
        named = before.get('handover')
        if named and Path(named).is_file():
            return Path(named)
        path = self.work / 'handover.md'
        began = before.get('started') if index else None
        try:
            if path.is_file() and path.read_text(encoding='utf-8-sig').strip() and \
                    (began is None or path.stat().st_mtime >= began):
                return path
        except OSError:
            return None
        return None

    def _bundle(self, phase, state=None, end_turn_after=None, by_step=False, step_from=None, sent=None):
        from letitedit.app import stage_start
        stop = self.stop_after if phase == self.stop_phase else None
        entry = (state or {}).get('phases', {}).get(phase) or {}
        checked = entry.get('code_checks') or {}
        evidence = [checked['file']] if checked.get('file') and Path(checked['file']).is_file() else []
        handover = self._handover(phase, state or {'phases': {}})
        made = (entry.get('round_handoff') or {}) if self.rounds and phase == ROUND_UNIT else {}
        if made.get('md') and Path(made['md']).is_file():
            # T363: a later review round starts from the last round's hand-off (it holds the standing record too),
            # never from the code checks that opened round 1
            handover, evidence = Path(made['md']), []
        return stage_start.build(self.request, phase, self.project, ai=self.engine,
                                 handover=handover, stop_after=stop,
                                 end_turn_after=end_turn_after, tools=self._tools(phase), by_step=by_step,
                                 step_from=step_from, sent=sent, **({'evidence': evidence} if evidence else {}))

    def _code_checks(self, state, entry):
        """T345 C3: before the review phase's first message, the review bundle's measured checks (P3's code checks
        first) run here, on a preview export with no critic, and their reply goes to the phase as stage evidence. Only
        with the self-checks switch and the review order on; once per run (kept in the phase's entry)."""
        if entry.get('code_checks') or not self_checks_on():
            return
        try:
            from letitedit.review import review_order
            if not review_order.enabled():
                entry['code_checks'] = {'ran': False, 'why': 'the review order (review_code_first) is off'}
                return
            from letitedit.review import review_bundle
            self.note('Checking the video before the review.')
            began = time.monotonic()
            summary = review_bundle.reply(review_bundle.bundle(project=str(self.project), render='preview',
                                                               critic=None))
        except Exception as e:  # noqa: BLE001 - the phase starts as before; the AI runs the checks itself
            entry['code_checks'] = {'ran': False, 'why': f'{type(e).__name__}: {e}'[:600]}
            self._save(state)
            return
        path = self.work / CODE_CHECKS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CODE_CHECKS_HEAD + json.dumps(summary, ensure_ascii=False, indent=1, default=str) + '\n',
                        encoding='utf-8')
        order = summary.get('review_order') if isinstance(summary.get('review_order'), dict) else {}
        entry['code_checks'] = {'ran': True, 'file': str(path), 'at': _now(), 'verdict': summary.get('verdict'),
                                'code_failures': len(order.get('code_failures') or []),
                                'seconds': round(time.monotonic() - began, 1)}
        self._save(state)

    def _unit_first(self, phase):
        return self.sub.first_of(phase) if self.sub is not None else phase

    def _tools(self, phase):
        """The letitedit tools the phase's tool server offers (its tool profile and the request's extras, as _mcp_env
        starts it), or None with tool profiles off."""
        from letitedit.app import stage_start
        if not stage_start.first_message_on():        # the index is scoped only with T342's switch on
            return None
        try:
            from letitedit.server import tool_profiles
            if not tool_profiles.enabled():
                return None
            return tool_profiles.tools_for(self._spec(phase)['tools'], tool_profiles.extras_for(self.request))
        except Exception:  # noqa: BLE001 - an unreadable profile means the full index, never a refused start
            return None

    @staticmethod
    def _later_due(entry):
        """T342: whether the phase's first message left attachments for a later step that haven't been sent yet. A
        phase is never accepted as done while they are due."""
        return bool(entry.get('later_step')) and not entry.get('later_sent')

    def _check_text(self, phase, step):
        title = self._title(phase)
        return (f'The {title}\'s work is on the saved files, but the {step} step\'s own skills, references and '
                f'guide sections were not with you yet; they are attached below. Check every {step} change already '
                'made against them, fix what they require, then end your turn.')

    def _step_text(self, phase, entry, pending, recovered=False):
        """T342: the carry-on while the phase's first step isn't done and the next step's attachments are still due:
        it asks for that step only, never the phase's later outputs (their skills haven't come yet)."""
        title = self._title(phase)
        step, following = entry.get('split_after'), entry.get('later_step')
        lines = []
        if recovered:
            lines.append(f'This run was interrupted during the {title} and carries on now. Read the project\'s '
                         'files and journal for what is already done; never repeat a finished step.')
        lines.append(f'The {step} step of the {title} is not done yet on the saved files. Finish the {step} '
                     f'step only, as the first message says, then end your turn: the {following} step\'s own skills '
                     'come with the next message. Any skill this step needs now, read IN FULL with the Skill tool.')
        if pending:
            lines.append('An export of the video is still running: collect it (letitedit_export_job) before ending '
                         'your turn.')
        return '\n'.join(lines)

    def _recheck_text(self, phase):
        title = self._title(phase)
        return (f'The {title}\'s work was already on the saved files when this conversation began, from an '
                'earlier attempt. Check every change of it against the skills, references and guide sections attached '
                'in this conversation, fix what they require, then end your turn.')

    def _confirm_later(self, state, entry, session, digest, echo):
        """T342: the next step's attachments count as sent only once the program's echo of the whole message matches
        what was sent (a program that echoes nothing, as its first message showed, counts on the send). Unconfirmed,
        they go again with the next message."""
        confirmed = session.echoed(digest) is not None or (echo is None and entry.get('ack') != 'echo')
        if confirmed:
            entry['later_sent'] = True
        else:
            entry['later_unconfirmed'] = int(entry.get('later_unconfirmed') or 0) + 1
        self._save(state)
        return confirmed

    def _send(self, state, entry, session, text, later):
        """Send one message; with the next step's attachments in it, wait for its echo and confirm them. Returns
        whether the program took it."""
        seen = len(session.replayed)
        digest = session.send(text)
        if digest is None:
            return False
        if later:
            echo = session.wait_echo(seen, ECHO_WAIT_S, check=self.check)
            self._confirm_later(state, entry, session, digest, echo)
        return True

    def _with_later(self, state, entry, phase, step, text):
        """T342: (text, whether it now carries the attachments of `step` that the phase's first message left for it,
        stage_start's `later`). They are added when due and not yet sent, built from the files as they are now, less
        what the first message held. Nothing left to send counts as sent."""
        if not self._later_due(entry) or step != entry['later_step']:
            return text, False
        from letitedit.app import stage_start
        try:
            bundle = self._bundle(phase, state, end_turn_after=entry.get('split_after'), by_step=True,
                                  step_from=entry.get('later_from'), sent=set(entry.get('first_attached') or ()))
        except stage_start.IncompleteStart as e:
            self._stop(state, 'start_incomplete', f'The {step} step\'s attachments could not be made in full: {e} '
                       'Nothing was cut.', phase=phase)
        later = stage_start.step_text(bundle)
        if not later:
            entry['later_sent'], entry['later_bytes'], entry['later_skills'] = True, 0, []
            self._save(state)
            return text, False
        entry['later_bytes'], entry['later_skills'] = len(later.encode('utf-8')), bundle['later']['skills']
        return text + '\n\n' + later, True

    def _picked(self, phase, role=None):
        """ai_clis.choice for a phase's role (its model_role unless named): the run's pin, the person's saved choice,
        Auto, or the app's default."""
        from letitedit.app import ai_clis
        role = role or self._spec(phase).get('model_role') or 'plan'
        return ai_clis.choice(self.engine, role, self._chat_settings() or {}, pin=self.choice)

    def _model(self, phase, role=None):
        """(model, effort) for a turn of a phase in a role. Nothing pinned, saved or routed (the switch off): no model,
        so Claude Code's own setting, with a pinned or saved effort, as before Auto."""
        picked = self._picked(phase, role)
        if picked['source'] == 'default':
            from letitedit.app import ai_clis
            settings = self._chat_settings() or {}
            effort = (self.choice or {}).get('effort') or settings.get(ai_clis.EFFORT_KEYS.get(self.engine, 'effort'))
            return None, effort or None
        return picked['model'], picked['effort']

    def _step_role(self, phase, step):
        spec = self._spec(phase)
        return (spec.get('step_roles') or {}).get(step) or spec.get('model_role') or 'plan'

    def _turn_role(self, phase):
        """(role, step) of the next turn: the role of the sub-step the saved files say the work is at."""
        step = self._first_step(phase)
        return self._step_role(phase, step), step

    def _split_after(self, phase):
        """The sub-step after which the AI ends its turn so the next step runs on another model, or None: only when
        the steps' roles give different models (Auto; a pin gives every role the same one)."""
        stages = list(self._spec(phase)['stages'])
        if len(stages) < 2:
            return None
        start = self._first_step(phase)
        if start not in stages:
            return None
        for here, after in zip(stages[stages.index(start):], stages[stages.index(start) + 1:]):
            if self._model(phase, self._step_role(phase, here)) != self._model(phase, self._step_role(phase, after)):
                return here
        return None

    def _next_step_text(self, phase, done_step, step):
        title, noun = self._title(phase), self._noun(phase)
        return (f'The {done_step} step is done on the saved files. Now the {step} step of the {title}: '
                f'complete the rest of this {noun}, then end your turn.')

    def _relaunch(self, state, phase, session, row, session_id, tool_args, role):
        """Carry the same session on (--resume) with the model of `role`: the turn has ended, so the program closes
        cleanly and starts again on the conversation it saved."""
        row['exit'] = session.close(wait_s=30)
        row['ended'] = _now()
        state['processes'] = [p for p in state.get('processes') or [] if p.get('pid') != session.pid]
        session, model, effort = self._launch(phase, session_id, True, tool_args, role=role)
        row = self._session_row(state, phase, session_id, True, model, effort, role=role)
        state['processes'].append({'pid': session.pid, 'stamp': _stamp(session.pid)})
        self._save(state)
        return session, row

    def _mcp_env(self, phase):
        from letitedit.server import tool_profiles
        env = {'LETITEDIT_NEW_VIDEO_PHASES': '1', 'LETITEDIT_SESSION_RUNNER_RUN': self.run_id or ''}
        if phase == self.stop_phase and self.stop_after:
            env['LETITEDIT_NEW_VIDEO_STOP_AFTER'] = self.stop_after
        if self.sub is not None:
            env['LETITEDIT_SUBSTEP_SESSIONS'] = '1'
        if self.rounds and phase == ROUND_UNIT:      # T363: the bundle's reply says the round's conversation ends
            from letitedit.review import review_bundle
            env[review_bundle.ROUND_SESSIONS_ENV] = '1'
        if tool_profiles.enabled():
            profile = self._spec(phase)['tools']
            env.update(tool_profiles.mcp_env(profile, tool_profiles.extras_for(self.request)))
        return env

    def instance(self):
        """The letitedit instance the run's tool server works as: the caller's (the Studio job's own), else one of
        the run's own."""
        own = 'runner-' + hashlib.sha1(str(self.project).encode('utf-8')).hexdigest()[:12]
        return self.env.get('LETITEDIT_INSTANCE') or own

    def _python(self):
        chosen = (self._chat_settings() or {}).get('python')
        return chosen if chosen and Path(chosen).is_file() else os.environ.get('LETITEDIT_PYTHON') or \
            __import__('sys').executable

    def _launch(self, phase, session_id, resume, tool_args, role=None):
        from letitedit.app import claude_session
        root = install_root()
        folder = self.work_dir / phase
        folder.mkdir(parents=True, exist_ok=True)
        config = claude_session.write_mcp_config(folder / 'mcp.json', self._python(),
                                                 root / 'bridge' / 'letitedit_mcp.py', self._mcp_env(phase))
        model, effort = self._model(phase, role)
        up_front = up_front_env(self.engine)
        settings = None
        if up_front:        # in the flag settings too: they outrank an env block in the person's own settings
            settings = json.loads(claude_session.settings_text())
            settings['env'] = {**(settings.get('env') or {}), **up_front}
            settings = json.dumps(settings, separators=(',', ':'))
        args = claude_session.command(self.exe, session_id, resume=resume, mcp_config=config, tool_args=tool_args,
                                      model=model, effort=effort, prompt_file=root / 'chat' / 'panel-prompt.md',
                                      settings=settings)
        # as the job's window starts its AI: no marker of a session it sits inside (a CLAUDE* or T3CODE* variable,
        # the configuration folder aside), the install it runs from, the caller's own variables
        base = {k: v for k, v in os.environ.items()
                if not (k.startswith('CLAUDE') or k.startswith('T3CODE')) or k == 'CLAUDE_CONFIG_DIR'}
        # the tool server's instance is the run's own, never the person's window ('main'): its project claims and
        # anything it asks a window go to an instance no window of the person's has. The run's mark goes to the
        # session too, not only its tool server: the AI's own Python (letitedit_ai through Bash) must see a run with
        # no window as well, or its letitedit_show starts one
        own = {'LETITEDIT_ROOT': str(root), 'LETITEDIT_INSTANCE': self.instance(),
               'LETITEDIT_SESSION_RUNNER_RUN': self.run_id or '', **self.env, **up_front}
        env = claude_session.session_env(base, extra=own)
        if python_on_path_on():
            env = with_python_on_path(env, self._python())
        log = folder / 'stream.jsonl'

        def record(message):
            with open(log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(message, ensure_ascii=False)[:20000] + '\n')
        spawn = self._spawn
        if spawn is None:
            if self._desktop is None:
                self._desktop = Desktop('letitedit-runner-' + hashlib.sha1(str(self.project).encode('utf-8'))
                                        .hexdigest()[:12]).open()
            spawn = self._desktop.spawn
        session = claude_session.ClaudeSession(args, env, self.work_dir,
                                               roots=(self.project.parent, self.work_dir), spawn=spawn,
                                               on_event=record)
        return session, model, effort

    # ---------------------------------------------------------------- clean-up before a retry

    def _settle(self, state):
        """End what an earlier attempt of this run left running (its processes, matched by creation time) and wait
        for its own clean-up: the video's exports still running and the PC lock held by one of its processes."""
        left = [p for p in state.get('processes') or [] if p.get('pid') and _stamp(p['pid']) == p.get('stamp')]
        if left:
            from letitedit.app import claude_session
            for p in left:
                claude_session.kill_tree(p['pid'])
            self.note(f'Ended {len(left)} process(es) an earlier attempt left running.')
        pids = {int(p['pid']) for p in state.get('processes') or [] if p.get('pid')}
        end = _now() + SETTLE_S
        while _now() < end:
            self.check()
            waiting = []
            if self._pending():
                waiting.append('an export of the video')
            try:
                import letitedit.core.render_lock as render_lock
                info = render_lock.info()
                holders = {info.get('owner_pid')} | {w.get('pid') for w in info.get('queue') or []}
                if info.get('held') and pids & {h for h in holders if h}:
                    waiting.append('the PC lock')
            except Exception:  # noqa: BLE001 - an unreadable lock is the lock's own business
                pass
            if not waiting:
                break
            time.sleep(POLL_S)
        state['processes'] = []

    # ---------------------------------------------------------------- one phase

    def _created(self, state, entry, session, session_id, phase):
        """The program said which session it is: it must be the one it was started as."""
        if not session.session_id:
            return
        if session.session_id != session_id:
            self._stop(state, 'session_mismatch', f'The AI program reported session {session.session_id}, not the '
                       f'one it was started as ({session_id}).', phase=phase)
        if entry['state'] == 'launching':
            entry['state'] = 'created'

    def _session_row(self, state, phase, session_id, resume, model, effort, role=None):
        role = role or self._spec(phase).get('model_role') or 'plan'
        row = {'phase': phase, 'session_id': session_id, 'attempt': state['attempts'], 'resumed': resume,
               'started': _now(), 'model': model, 'effort': effort, 'role': role,
               'source': self._picked(phase, role)['source']}
        if up_front_env(self.engine):
            row['tools_up_front'] = True        # T345 C3: the session's tools came with its opening
        if self._spec(phase).get('noun') == 'sub-step':
            row['of_phase'] = self._spec(phase)['phase']     # T354
        state['sessions'].append(row)
        return row

    def _carry_text(self, phase, missing, pending, recovered=False):
        title, noun = self._title(phase), self._noun(phase)
        lines = []
        if recovered:
            lines.append(f'This run was interrupted during the {title} and carries on now. Read the project\'s '
                         'files and journal for what is already done; never repeat a finished step.')
        lines.append(f'The {title} is not done yet. Still missing, checked on the saved files: '
                     + ('; '.join(missing) if missing else 'nothing named') + '.')
        if pending:
            lines.append('An export of the video is still running: collect it (letitedit_export_job) before ending '
                         'your turn.')
        lines.append(f'Finish only this {noun}, then end your turn.')
        return '\n'.join(lines)

    def _stop(self, state, code, message, **detail):
        state['status'] = 'stopped'
        state['stopped'] = {'code': code, 'message': message, 'at': _now(), **detail}
        self._save(state)
        raise RunnerError('stopped', code, message, **detail)

    def _wait_exports(self):
        end = _now() + EXPORT_WAIT_S
        pending = self._pending()
        while pending and _now() < end:
            self.check()
            time.sleep(POLL_S)
            pending = self._pending()
        return pending

    def _run_phase(self, state, phase, tool_args):
        from letitedit.app import ai_clis, claude_session, new_video_carry, stage_start
        entry = state['phases'].setdefault(phase, {'state': None, 'turns': 0, 'carry_ons': 0, 'sessions': []})
        self._handoff_before(state, phase)       # T354: the hand-off this sub-step starts from, checked first
        done, missing, newest = self._outputs(phase)
        done, missing = self._own_turn(entry, phase, done, missing)
        # the files are the test, whatever an attempt got to; but never while a later step's attachments are due
        # (T342: the AI went on past its step without them, so it checks its work against them first)
        checking = done and self._later_due(entry)
        if done and not checking and not self._pending():
            gaps = self._close_unit(state, entry, phase)
            if not gaps:
                self._phase_done(state, entry, phase, newest, found=True)
                self.note(f"The {self._display_title(phase)} was already done on the files.")
                return
            done, missing = False, gaps
        resume, recovered = False, False
        if entry.get('state') in ('launching', 'created', 'acked') and entry.get('session_id'):
            # an attempt stopped inside this phase: Claude Code's own record says whether its session began
            if claude_session.session_log(entry['session_id'], self.homes):
                resume, recovered = True, True
            else:
                entry['state'] = 'prepared'
        role, _ = self._turn_role(phase)
        if not resume:
            split = self._split_after(phase)
            # T342 (its switch on): the step after which the phase's next step gets its own attachments, in the
            # message that starts it (with Auto's model split at the same step, one message does both)
            step_split = stage_start.step_split(phase, self.project)
            split = split or step_split
            entry['split_after'] = split
            if phase == self._unit_first(CODE_CHECKS_PHASE):
                self._code_checks(state, entry)
            try:
                bundle = self._bundle(phase, state, end_turn_after=split,
                                      by_step=step_split is not None and split == step_split)
            except stage_start.IncompleteStart as e:
                self._stop(state, 'start_incomplete', f'The {phase} phase\'s first message could not be made in full: '
                           f'{e} Nothing was cut.')
            entry.update(state='prepared', bytes=bundle['bytes'], sha256=bundle['sha256'], skills=bundle['skills'],
                         session_id=entry.get('session_id') or str(uuid.uuid4()))
            for key in ('later_step', 'later_from', 'later_sent', 'first_attached', 'later_bytes', 'later_skills',
                        'later_unconfirmed', 'split_sent', 'recheck'):
                entry.pop(key, None)
            if checking:                    # done on the files, attachments due, no session to carry on: the whole
                entry['recheck'] = True     # start goes out, then a check of the work already done
            if bundle.get('later'):
                entry.update(later_step=bundle['later']['step'], later_from=bundle.get('step'),
                             first_attached=[item['name'] for item in bundle['attachments']])
            self._save(state)
        session_id = entry['session_id']
        entry['state'] = 'launching'
        entry.setdefault('started', _now())
        if self.rounds and phase == ROUND_UNIT:          # T363: where this round's session began
            from letitedit.studio import round_handoff
            entry.setdefault('round_from', round_handoff.rounds_done(self.project))
            entry.setdefault('round_started', _now())
        self._save(state)
        session, model, effort = self._launch(phase, session_id, resume, tool_args, role=role)
        row = self._session_row(state, phase, session_id, resume, model, effort, role=role)
        entry['sessions'].append(session_id)
        state.setdefault('processes', []).append({'pid': session.pid, 'stamp': _stamp(session.pid)})
        self._save(state)
        try:
            seen = len(session.replayed)
            later = False
            if resume and checking:
                text, later = self._with_later(state, entry, phase, entry['later_step'],
                                               self._check_text(phase, entry['later_step']))
            elif resume and self._later_due(entry) and self._turn_role(phase)[1] == entry.get('split_after'):
                text = self._step_text(phase, entry, self._pending(), recovered=True)
            elif resume:
                text, later = self._with_later(state, entry, phase, self._turn_role(phase)[1],
                                               self._carry_text(phase, missing, self._pending(), recovered=True))
            else:
                text = bundle['request']
            digest = session.send(text)          # None: the program ended first (handled as an exit)
            sent = digest is not None
            echo = session.wait_echo(seen, ECHO_WAIT_S, check=self.check) if sent else None
            if sent and later:
                self._confirm_later(state, entry, session, digest, echo)
            self._created(state, entry, session, session_id, phase)
            if echo is not None:
                if not resume:
                    try:
                        stage_start.verify(bundle, delivered=echo)
                    except stage_start.IncompleteStart as e:
                        self._stop(state, 'start_changed', f'The AI received a different first message: {e}',
                                   phase=phase)
                entry['state'], entry['ack'] = 'acked', 'echo'
            self._save(state)
            carry_ons = int(entry.get('carry_ons') or 0)
            while True:
                outcome = session.turn(PHASE_LIMIT_S, check=self.check) if sent else \
                    {'ended': 'exit', 'is_error': True, 'subtype': 'exit', 'text': '', 'held': False, 'steps': 0}
                entry['turns'] = int(entry.get('turns') or 0) + 1
                self._created(state, entry, session, session_id, phase)
                if entry['state'] == 'created' and session.steps:
                    entry['state'], entry['ack'] = 'acked', 'reply'      # a program that doesn't echo
                if session.denied:
                    entry['denied'] = [list(d) for d in session.denied][-20:]
                self._save(state)
                said = str(outcome.get('text') or '')
                if outcome['ended'] == 'limit':
                    self._stop(state, 'turn_limit', f'The AI\'s turn ran past {PHASE_LIMIT_S // 3600} hours.',
                               phase=phase)
                if (outcome.get('is_error') and outcome['ended'] == 'result') or outcome.get('api_error'):
                    # T352: a failed API call (Claude Code names it on the message, even when its result says
                    # "success") is the turn's answer: a sign-in or a limit stops the run, never a carry-on
                    kind = ai_clis.failure_kind(said, outcome.get('api_error'))
                    if kind == 'limit':
                        self._stop(state, 'usage_limit', ai_clis.limit_line(said) or 'The AI hit a usage limit.',
                                   phase=phase)
                    if kind == 'signin':
                        self._stop(state, 'signin', signin_line(self.engine, said), phase=phase,
                                   said=said.strip()[:300], api_error=outcome.get('api_error'))
                blocker = new_video_carry.plain_blocker(said)
                if blocker:
                    self._stop(state, 'blocked', blocker, phase=phase)
                pending = self._wait_exports()
                self._marks()
                done, missing, newest = self._outputs(phase)
                done, missing = self._own_turn(entry, phase, done, missing)
                checking = done and self._later_due(entry)
                if done and not pending and not checking and entry.pop('recheck', False):
                    self._save(state)
                    if session.alive() and self._send(state, entry, session, self._recheck_text(phase), False):
                        continue
                if done and not pending and not checking:
                    gaps = self._close_unit(state, entry, phase)      # T354: the hand-off checks out too
                    if gaps:
                        done, missing = False, gaps
                if done and not pending and not checking:
                    self._phase_done(state, entry, phase, newest)
                    self.note(f"The {self._display_title(phase)} is done.")
                    return
                if not done and not pending and self._round_over(entry, phase):
                    # T363: this session's critic round is done and rounds are left: the next round starts in a
                    # fresh session from a hand-off checked in code; a gap is asked for here first
                    gaps = self._close_round(state, entry, phase, said, session_id)
                    if not gaps:
                        session, row, session_id, bundle, sent = self._next_round(state, entry, phase, session, row,
                                                                                  tool_args)
                        carry_ons = 0
                        continue
                    missing = gaps
                role, step = self._turn_role(phase)
                if checking:            # T342: done past its step without that step's attachments: check against them
                    step = entry['later_step']
                    role = self._step_role(phase, step)
                split = entry.get('split_after')
                if split and step != split and not entry.get('split_sent') and not pending \
                        and outcome['ended'] != 'exit' and session.alive():
                    # the step before the switch is done on the files: the next step is its own turn, on its own
                    # model, in the same conversation (not a carry-on)
                    entry['split_sent'] = True
                    if (row.get('model'), row.get('effort')) != self._model(phase, role) \
                            and int(entry.get('switches') or 0) < SWITCHES:
                        entry['switches'] = int(entry.get('switches') or 0) + 1
                        session, row = self._relaunch(state, phase, session, row, session_id, tool_args, role)
                        self.note(f"The {step} step runs on {row.get('model')} ({role} role).")
                    self._save(state)
                    text, later = self._with_later(state, entry, phase, step,
                                                   self._check_text(phase, step) if checking
                                                   else self._next_step_text(phase, split, step))
                    sent = self._send(state, entry, session, text, later)
                    continue
                if carry_ons >= CARRY_ONS:
                    gap = bool(entry.get('handoff_gaps')) and missing == entry['handoff_gaps']
                    self._stop(state, HANDOFF_GAP if gap else 'phase_unfinished',
                               f"The {self._display_title(phase)} was not finished after the AI was asked again: "
                               + ('the hand-off to the next step is missing ' if gap else '')
                               + '; '.join(missing or pending), phase=phase, missing=missing, pending=pending)
                carry_ons += 1
                entry['carry_ons'] = carry_ons
                self._save(state)
                if self._later_due(entry) and not checking and step == entry.get('split_after'):
                    text, later = self._step_text(phase, entry, pending), False     # the first step only
                else:
                    text, later = self._with_later(state, entry, phase, step,
                                                   self._check_text(phase, step) if checking and not pending
                                                   else self._carry_text(phase, missing, pending))
                if outcome['ended'] == 'exit' or not session.alive():
                    # the program ended (a crash, or it closed its session): carry the same session on when Claude
                    # Code's record says it began, else start it again under the same id with its first message
                    row['exit'] = session.close(wait_s=5)
                    row['ended'] = _now()
                    began = claude_session.session_log(session_id, self.homes) is not None or resume
                    if not began:
                        text, later = bundle['request'], False
                    state['processes'] = [p for p in state.get('processes') or [] if p.get('pid') != session.pid]
                    keep = row.get('role')            # an exit is no model switch: the same role carries on
                    session, model, effort = self._launch(phase, session_id, began, tool_args, role=keep)
                    row = self._session_row(state, phase, session_id, began, model, effort, role=keep)
                    state['processes'].append({'pid': session.pid, 'stamp': _stamp(session.pid)})
                    self._save(state)
                sent = self._send(state, entry, session, text, later)
                self.note(f"Asked the AI to finish the {self._display_title(phase)} "
                          f'({carry_ons} of {CARRY_ONS}).')
        finally:
            row['ended'] = _now()
            row['exit'] = session.close()
            state['processes'] = [p for p in state.get('processes') or [] if p.get('pid') != session.pid]
            self._save(state)

    # ---------------------------------------------------------------- sub-steps: the books and the hand-off (T354)

    def _own_turn(self, entry, unit, done, missing):
        """A sub-step that must have its own turn (the final look: its closing message) isn't done before it has."""
        if done and self._spec(unit).get('needs_turn') and not int(entry.get('turns') or 0):
            if self.sub is not None and self.sub.hooks_on_demand():      # T363's cut 5: no candidates in the run
                return False, ["the final review's own turn: the closing message (letitedit-firstcut section 4)"]
            return False, ["the final review's own turn: the hook candidates and the closing message "
                           '(letitedit-firstcut section 4)']
        return done, missing

    def _since(self, state):
        return float(state.get('first_since') or 0)

    def _sub_books(self, state, entry, unit):
        """The books at a sub-step's end (bookkeeping on): its phase's own boundary when it ends the phase
        (after_phase, as a phase run keeps them), else the marks and, once there is a cut, the why markers."""
        books = self._bookkeeping()
        if books is None:
            return
        spec = self._spec(unit)
        try:
            if unit == self.sub.last_of(spec['phase']):
                receipt = books.after_phase(self.project, self.request, spec['phase'],
                                            entry.get('started') or self._since(state))
            else:
                receipt = {'marks': books.marks(self.project, self.request)}
                if unit != self.sub.ORDER[0]:
                    receipt['why'] = books.books_markers(self.project) if books.full() else \
                        books.why_markers(self.project)
        except Exception as e:  # noqa: BLE001 - the books never stop a run whose outputs checked out
            receipt = {'error': f'{type(e).__name__}: {e}'}
        entry['bookkeeping'] = receipt if isinstance(receipt, dict) else {'receipt': str(receipt)}

    def _close_unit(self, state, entry, unit):
        """T354: at a sub-step's end, with its outputs checked out: the books, then its hand-off written and checked
        against the files. Returns the gaps ([]: complete, or not a sub-step, or the last one)."""
        if self.sub is None or unit not in self.sub.SUBSTEPS:
            return []
        self._sub_books(state, entry, unit)
        if unit not in self.sub.NEXT:
            self._save(state)
            return []
        from letitedit.studio import substep_handoff
        try:
            made = substep_handoff.write(self.project, self.request, unit, since=self._since(state))
        except Exception as e:  # noqa: BLE001 - a hand-off that can't be made is a gap, never a silent pass
            made = {'gaps': [f'the hand-off itself ({type(e).__name__}: {e})'[:400]]}
        entry['handoff'] = made
        entry['handoff_gaps'] = list(made.get('gaps') or [])
        self._save(state)
        return entry['handoff_gaps']

    def _handoff_before(self, state, unit):
        """T354: before a sub-step's session starts, the hand-off it starts from is the one letitedit made and still
        complete against the files (substep_handoff.verify); one made now when the sub-step before was given to this
        run (a final from its preview). A gap stops the run, naming it, before anything starts."""
        if self.sub is None or unit not in self.sub.SUBSTEPS or unit not in self.sub.PREVIOUS:
            return
        before = self.sub.PREVIOUS[unit]
        prior = state['phases'].setdefault(before, {}) if before in self._given() else state['phases'].get(before)
        if prior is None:
            return
        from letitedit.studio import substep_handoff
        made = prior.get('handoff') or {}
        if not made.get('json') or not Path(made['json']).is_file():
            made = substep_handoff.write(self.project, self.request, before, since=self._since(state))
            prior['handoff'] = made
            self._save(state)
        gaps = substep_handoff.verify(made['json'], self.project, self.request)
        prior['handoff_verified'] = {'at': _now(), 'gaps': gaps}
        self._save(state)
        if gaps:
            self._stop(state, HANDOFF_GAP, f'The {self._display_title(unit)} cannot start: its hand-off is missing '
                       + '; '.join(gaps), phase=unit, gaps=gaps)

    # ---------------------------------------------------------------- review rounds, a session each (T363's cut 3)

    def _round_over(self, entry, unit):
        """Whether this session's critic round is done with rounds left: more critic rounds on file than when the
        session began, and fewer round sessions than the ceiling (the bundle's round limit ends them long before)."""
        if not self.rounds or unit != ROUND_UNIT:
            return False
        from letitedit.studio import round_handoff
        return round_handoff.rounds_done(self.project) > int(entry.get('round_from') or 0) and \
            len(entry.get('round_sessions') or []) + 1 < self.sub.ROUND_SESSIONS_MAX

    def _close_round(self, state, entry, unit, said, session_id):
        """At a round's end: the books (the marks, the why markers), then the next round's hand-off written and
        checked against the files. Returns its gaps, each named as the round's ([]: complete)."""
        from letitedit.app import claude_session
        from letitedit.studio import round_handoff
        self._sub_books(state, entry, unit)
        number = round_handoff.rounds_done(self.project)
        try:
            made = round_handoff.write(self.project, self.request, number,
                                       log=claude_session.session_log(session_id, self.homes), said=said,
                                       round_since=float(entry.get('round_started') or 0), since=self._since(state))
        except Exception as e:  # noqa: BLE001 - a hand-off that can't be made is a gap, never a silent pass
            made = {'gaps': [f'the hand-off itself ({type(e).__name__}: {e})'[:400]]}
        made['round'] = number
        entry['round_handoff'] = made
        gaps = [f'review round {number}\'s hand-off to the next round (fill it, then end your turn: the next round '
                f'starts in a fresh conversation): {gap}' for gap in made.get('gaps') or []]
        entry['handoff_gaps'] = gaps
        self._save(state)
        return gaps

    def _next_round(self, state, entry, unit, session, row, tool_args):
        """The next review round in a fresh session: the hand-off verified again, the round's session closed, the
        sub-step's first message built from the files with the hand-off attached, a new session id chosen first and
        the message checked against its echo, as for any unit. Returns (session, row, session_id, bundle, sent)."""
        from letitedit.app import stage_start
        from letitedit.studio import round_handoff, substep_handoff
        made = entry['round_handoff']
        gaps = substep_handoff.verify(made['json'], self.project, self.request)
        made['verified'] = {'at': _now(), 'gaps': gaps}
        if gaps:
            self._stop(state, HANDOFF_GAP, f'Review round {made["round"] + 1} cannot start: its hand-off is missing '
                       + '; '.join(gaps), phase=unit, gaps=gaps)
        row['ended'] = _now()
        row['exit'] = session.close()
        state['processes'] = [p for p in state.get('processes') or [] if p.get('pid') != session.pid]
        try:
            bundle = self._bundle(unit, state)
        except stage_start.IncompleteStart as e:
            self._stop(state, 'start_incomplete', f'Review round {made["round"] + 1}\'s first message could not be made '
                       f'in full: {e} Nothing was cut.')
        session_id = str(uuid.uuid4())
        entry.setdefault('round_sessions', []).append(session_id)
        entry.update(state='launching', session_id=session_id, bytes=bundle['bytes'], sha256=bundle['sha256'],
                     skills=bundle['skills'], round_from=round_handoff.rounds_done(self.project),
                     round_started=_now(), carry_ons=0)
        entry['handoff_gaps'] = []
        self._save(state)
        role, _ = self._turn_role(unit)
        session, model, effort = self._launch(unit, session_id, False, tool_args, role=role)
        row = self._session_row(state, unit, session_id, False, model, effort, role=role)
        row['round'] = made['round'] + 1
        entry['sessions'].append(session_id)
        state.setdefault('processes', []).append({'pid': session.pid, 'stamp': _stamp(session.pid)})
        self._save(state)
        seen = len(session.replayed)
        digest = session.send(bundle['request'])
        sent = digest is not None
        echo = session.wait_echo(seen, ECHO_WAIT_S, check=self.check) if sent else None
        self._created(state, entry, session, session_id, unit)
        if echo is not None:
            try:
                stage_start.verify(bundle, delivered=echo)
            except stage_start.IncompleteStart as e:
                self._stop(state, 'start_changed', f'The AI received a different first message: {e}', phase=unit)
            entry['state'], entry['ack'] = 'acked', 'echo'
        self._save(state)
        self.note(f'Review round {made["round"] + 1} starts in a fresh session.')
        return session, row, session_id, bundle, sent

    # ---------------------------------------------------------------- the run

    def run_until(self, until=None):
        """Run the AI phases up to `until` (a phase id; None: every phase, or the preview's stop). Returns the
        state record. Raises RunnerError: 'refused' before anything started, 'stopped' after."""
        order = self._order()
        target = self._unit_of(until) if until else (self.stop_phase or order[-1])
        if self.stop_phase and order.index(target) > order.index(self.stop_phase):
            target = self.stop_phase                       # a preview never goes past its stop
        self._take_lease()
        try:
            self.preflight()
            state = self._state()
            tool_args = None
            for phase in order:
                if phase in self._given():
                    continue
                if (state['phases'].get(phase) or {}).get('state') != 'done':
                    if tool_args is None:
                        tool_args = self.probe()            # P2's probe, before each run
                        state['probe'] = {'tools': self.offered, 'args': tool_args, 'at': _now()}
                        if not self._attempt_begun:
                            state['attempts'] = int(state.get('attempts') or 0) + 1
                            self._attempt_begun = True
                            self._settle(state)
                        state['status'] = 'running'
                        self._save(state)
                    self._run_phase(state, phase, tool_args)
                if phase == target:
                    break
            finished = self._next_phase(state) is None or (self.stop_phase and
                                                           (state['phases'].get(self.stop_phase) or {})
                                                           .get('state') == 'done')
            state['status'] = ('preview_done' if self.stop_phase else 'done') if finished else 'running'
            self._save(state)
            return state
        finally:
            if self._desktop is not None:
                self._desktop.close()
                self._desktop = None
            self._drop_lease()

    def sessions(self):
        """Every session id of every attempt (for run_cost.measure(..., sessions=...))."""
        state = self._load() or {}
        return list(dict.fromkeys(row['session_id'] for row in state.get('sessions') or [] if row.get('session_id')))
