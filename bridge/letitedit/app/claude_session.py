"""Claude Code as an editing session that nobody watches: the session runner's transport (T319's H2; T331 step P9).

    command(exe, session_id, ...)        Claude Code's command line for one editing session (the editor's New video
                                         chat, aichatpanel.cpp aiClaudeChatArgs, as far as a session with no window
                                         can follow it)
    settings_text(env)                   its --settings: no CLAUDE.md of the person's, no memory, the chat's deny rules
    session_env(env)                     its environment: no parent session's markers, long tool calls wait
    write_mcp_config(path, ...)          the letitedit tool server for the session (a tool profile goes in its env)
    decide(tool, tool_input, roots)      the answer to a permission request when nobody is there to ask
    session_log(session_id, homes)       Claude Code's own record of a session (the provider's receipt), or None
    ClaudeSession(exe, args, ...)        one running Claude Code: send(text), turn(limit_s), close()

Nothing here starts a model by itself: ClaudeSession runs what the caller gives it. The session speaks streaming JSON
both ways (`-p --input-format stream-json --output-format stream-json`), so a message of any size goes on stdin, never
on the command line, and `--replay-user-messages` echoes each message back: the caller checks the echo against what it
sent (stage_start.verify), so a cut or changed first message is caught before the AI works on it.

A turn ends on the stream's `result` message, or when the program ends, never on an idle timer. A turn whose result
comes while work it started still runs (a tool call without its answer yet, an MCP task, a shell command left running,
a subagent) is held: the program carries on by itself when that work ends (Claude Code tells the model), and the turn
ends at the next result. A held turn whose work has ended but that never carries on ends after HELD_RESUME_S, as the
editor's chat does (aichatpanel.cpp aiChatWatchHeldTurn).

Permission requests (`control_request` / `can_use_tool`, from `--permission-prompt-tool stdio`) are answered by
decide(): the letitedit tools and reading are allowed; writing is allowed inside the session's own folders and never to
a footage or sound file; anything else is refused with a message that says nobody is watching. `--permission-mode
auto` (the editor's New video) decides most actions before a request is made.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows)
from letitedit.app import ai_clis

HELD_RESUME_S = 120          # a held turn whose work has ended and that doesn't carry on within this ends
CLOSE_WAIT_S = 20            # close(): how long the program has to end by itself after its input closes
# the work that keeps a turn open (aichatpanel.cpp aiChatTaskHolds, for New video, where nobody sends the next message)
HOLDING_TASKS = ('local_bash', 'shell', 'mcp_task', 'MCP task', 'local_agent', 'subagent', 'local_workflow',
                 'workflow')
READ_TOOLS = ('Read', 'Glob', 'Grep', 'Skill', 'ToolSearch', 'LS')
WRITE_TOOLS = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')
# a person's originals are media files: the chat never writes one with its file tools (aichatpanel.cpp
# aiClaudeChatDenyRules), and neither does a session nobody watches
MEDIA_EXT = ('mov', 'mp4', 'm4v', 'mkv', 'avi', 'mts', 'm2ts', 'mxf', 'wav', 'mp3', 'm4a', 'aac', 'flac', 'heic', 'dng',
             'cr2', 'arw', 'nef', 'braw', 'r3d', 'insv', 'lrv')
NOBODY = ('Nobody is watching this run, so this action cannot be approved: {action}. Do it another way: the letitedit '
          'tools, or files inside the project\'s own folder.')


def deny_rules():
    """The chat's deny rules (aichatpanel.cpp aiClaudeChatDenyRules): no deleting from a shell, no git push, no writing
    a footage or sound file with the file tools."""
    deny = [f'Bash({c} *)' for c in ('rm', 'rmdir', 'del', 'rd', 'erase', 'shred')] + ['Bash(git push*)']
    deny += [f'PowerShell({c} *)' for c in ('Remove-Item', 'rm', 'del', 'rmdir', 'ri', 'rd', 'erase')]
    deny += ['PowerShell(git push*)']
    deny += [f'{tool}(//**/*.{ext})' for tool in ('Edit', 'Write', 'NotebookEdit') for ext in MEDIA_EXT]
    return deny


def settings_text(env=None):
    """Claude Code's --settings for the session: the editor's instruction settings (no CLAUDE.md under the person's
    Claude folder, no automatic memory) plus the chat's deny rules."""
    _, text = ai_clis.claude_instruction_args(env)
    settings = json.loads(text)
    settings['permissions'] = {'deny': deny_rules()}
    return json.dumps(settings, separators=(',', ':'))


def session_env(env=None, extra=None):
    """The program's environment: this one without the markers of a session it sits inside (ai_clis.child_env), the
    editor's long-tool settings (aiClaudeLongToolEnvironment: a letitedit tool call is never moved to the background
    and never timed out by Claude Code), without the person's window token (LETITEDIT_OWNER), plus `extra`."""
    out = ai_clis.child_env(env)
    out.pop('LETITEDIT_OWNER', None)
    out.update({'CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS': '0', 'CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT': '0',
                'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    out.update(extra or {})
    return out


def write_mcp_config(path, python, server, env=None):
    """Write the session's MCP config (the letitedit tool server alone) and return its path. env: the tool server's
    own environment entries (a tool profile's, tool_profiles.mcp_env)."""
    server_env = {'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', **(env or {})}
    config = {'mcpServers': {'letitedit': {'command': str(python), 'args': [str(server)], 'env': server_env}}}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config, indent=1), encoding='utf-8')
    os.replace(temp, path)
    return path


def command(exe, session_id, *, resume=False, mcp_config, settings=None, tool_args=(), model=None, effort=None,
            prompt_file=None):
    """Claude Code's command line for one editing session. resume: carry on `session_id` (--resume) instead of
    starting it (--session-id: the id is chosen before the launch, so a lost reply can be matched to its session).
    tool_args: the built-in tools turned off (ai_clis.editing_tool_args). model and effort: the run's choice (nothing:
    Claude Code's own setting)."""
    args = [str(exe), '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
            '--replay-user-messages', '--mcp-config', str(mcp_config), '--strict-mcp-config', *tool_args,
            '--permission-mode', 'auto', '--permission-prompts', 'none', '--permission-prompt-tool', 'stdio',
            '--allowedTools', 'mcp__letitedit__*', '--settings', settings or settings_text()]
    if prompt_file and Path(prompt_file).is_file():
        args += ['--append-system-prompt-file', str(prompt_file)]
    if model:
        args += ['--model', str(model)]
    if effort:
        args += ['--effort', str(effort)]
    args += ['--resume', str(session_id)] if resume else ['--session-id', str(session_id)]
    return args


def user_line(text):
    """One user message on the program's input (stream-json), as bytes."""
    message = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}}
    return (json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8')


def _inside(path, roots):
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for root in roots:
        try:
            if p.is_relative_to(Path(root).resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


def decide(tool, tool_input, roots=()):
    """(allow, message) for a permission request when nobody is watching. The letitedit tools and reading are
    allowed; a write is allowed inside `roots` (the project's folder, the session's own folder) and never to a media
    file; anything else is refused, and the message tells the AI why."""
    tool = str(tool or '')
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool.startswith('mcp__letitedit__') or tool in READ_TOOLS:
        return True, ''
    if tool in WRITE_TOOLS:
        target = tool_input.get('file_path') or tool_input.get('notebook_path') or tool_input.get('path') or ''
        if target and str(target).rsplit('.', 1)[-1].lower() in MEDIA_EXT:
            return False, NOBODY.format(action=f'{tool} on the media file {target} (a person\'s footage stays as it '
                                               'is)')
        if target and _inside(target, roots):
            return True, ''
        return False, NOBODY.format(action=f'{tool} on {target or "a file"} outside the project\'s folder')
    shown = json.dumps(tool_input, ensure_ascii=False)[:200]
    return False, NOBODY.format(action=f'{tool} {shown}')


def control_response(request_id, allow, tool_input, message=''):
    decision = ({'behavior': 'allow', 'updatedInput': tool_input} if allow
                else {'behavior': 'deny', 'message': message or NOBODY.format(action='this')})
    response = {'type': 'control_response',
                'response': {'subtype': 'success', 'request_id': request_id, 'response': decision}}
    return (json.dumps(response, ensure_ascii=False) + '\n').encode('utf-8')


def session_log(session_id, homes=None):
    """The session's own log, Claude Code's record that it started (~/.claude/projects/<folder>/<id>.jsonl), or None.
    It is written from the session's first message on, so a missing log means no turn of it began."""
    if not session_id:
        return None
    homes = homes or [Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')]
    for home in homes:
        home = Path(home)
        base = home if home.name == '.claude' or (home / 'projects').is_dir() else home / '.claude'
        for path in (base / 'projects').glob(f'*/{session_id}.jsonl'):
            if path.is_file():
                return path
    return None


def _text_of(message):
    content = (message.get('message') or {}).get('content')
    if isinstance(content, str):
        return content
    return ''.join(part.get('text') or '' for part in content or [] if isinstance(part, dict)
                   and part.get('type') == 'text')


def _api_error(message):
    """The kind of API error an assistant message reports (Claude Code's `error` field, set with isApiErrorMessage
    on a message that stands for a failed API call: 'authentication_failed', 'rate_limit', ...), else None."""
    kind = message.get('error') or (message.get('message') or {}).get('error')
    if isinstance(kind, dict):
        kind = kind.get('type')
    if kind:
        return str(kind)
    return 'unknown' if message.get('isApiErrorMessage') else None


def _default_spawn(args, env, cwd):
    return subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=env, cwd=str(cwd))


def kill_tree(pid):
    """End a process and everything under it (Windows: taskkill /T; elsewhere the process alone)."""
    if not pid:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(int(pid))], capture_output=True)
    else:
        try:
            os.kill(int(pid), 9)
        except OSError:
            pass


class ClaudeSession:
    """One running Claude Code session. spawn(args, env, cwd) starts the program and returns a process with binary
    `stdin`/`stdout`, `pid`, `poll()`, `wait(timeout)` and `kill()` (subprocess.Popen by default; the session runner
    gives one that starts it on a private desktop). roots: where the AI may write (decide). on_event(message): every
    message the program writes, for the caller's record."""

    def __init__(self, args, env, cwd, *, roots=(), spawn=None, on_event=None):
        self.args, self.env, self.cwd, self.roots = list(args), env, cwd, tuple(roots)
        self.on_event = on_event
        self.proc = (spawn or _default_spawn)(self.args, env, cwd)
        self.pid = getattr(self.proc, 'pid', None)
        self.session_id = None          # from the stream's init
        self.model = None
        self.tools = None
        self.sent = []                  # sha256 of each message sent
        self.replayed = []              # (sha256, text) of each message the program echoed
        self.denied = []                # [(tool, message)] permission requests refused
        self.tool_calls = set()         # tool_use ids without their result yet
        self.tasks = {}                 # background task id -> type
        self.steps = 0                  # assistant messages
        self.exit_code = None
        self._events = queue.Queue()
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, name='claude-session-reader', daemon=True)
        self._reader.start()

    # ---------------------------------------------------------------- the stream

    def _write(self, data):
        with self._write_lock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def _read(self):
        try:
            for raw in self.proc.stdout:
                line = raw.decode('utf-8', 'replace').strip() if isinstance(raw, bytes) else str(raw).strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                self._handle(message)
                if self.on_event:
                    try:
                        self.on_event(message)
                    except Exception:  # noqa: BLE001 - a record that fails never stops the session
                        pass
                self._events.put((message, self.holding()))     # the running work as of this message
        except (OSError, ValueError):
            pass
        finally:
            self._events.put((None, False))       # the program's output ended

    def _handle(self, message):
        """What the reader thread does at once (answers can't wait for the caller): permissions, the session's id,
        the work still running."""
        kind, subtype = message.get('type'), message.get('subtype')
        if kind == 'control_request':
            request = message.get('request') or {}
            if request.get('subtype') == 'can_use_tool':
                tool_input = request.get('input') if isinstance(request.get('input'), dict) else {}
                allow, why = decide(request.get('tool_name'), tool_input, self.roots)
                if not allow:
                    self.denied.append((request.get('tool_name'), why))
                self._write(control_response(message.get('request_id'), allow, tool_input, why))
            else:
                self._write(json.dumps({'type': 'control_response', 'response': {
                    'subtype': 'error', 'request_id': message.get('request_id'),
                    'error': 'letitedit\'s session runner does not answer this request.'}}).encode('utf-8') + b'\n')
        elif kind == 'system' and subtype == 'init':
            self.session_id = message.get('session_id') or self.session_id
            self.model = message.get('model') or self.model
            self.tools = message.get('tools')
        elif kind == 'system' and subtype == 'background_tasks_changed':
            self.tasks = {str(t.get('task_id')): str(t.get('task_type')) for t in message.get('tasks') or []
                          if isinstance(t, dict)}
        elif kind == 'assistant':
            self.steps += 1
            for part in (message.get('message') or {}).get('content') or []:
                if isinstance(part, dict) and part.get('type') == 'tool_use' and part.get('id'):
                    self.tool_calls.add(part['id'])
        elif kind == 'user':
            content = (message.get('message') or {}).get('content')
            results = [p for p in content or [] if isinstance(p, dict) and p.get('type') == 'tool_result'] \
                if isinstance(content, list) else []
            for part in results:
                self.tool_calls.discard(part.get('tool_use_id'))
            if not results:
                text = _text_of(message)
                if text:
                    self.replayed.append((hashlib.sha256(text.encode('utf-8')).hexdigest(), text))

    def holding(self):
        """True while work the AI started still runs (its turn's result doesn't end it)."""
        return bool(self.tool_calls) or any(t in HOLDING_TASKS for t in self.tasks.values())

    # ---------------------------------------------------------------- the caller's side

    def send(self, text):
        """Send one user message. Returns its sha256 (the echo is matched against it), or None when the program's
        input is closed (it has ended)."""
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if not self._write(user_line(text)):
            return None
        self.sent.append(digest)
        return digest

    def echoed(self, digest):
        """The text the program echoed for the message with this sha256, or None (not echoed, or echoed changed)."""
        return next((text for sha, text in self.replayed if sha == digest), None)

    def wait_echo(self, seen, timeout_s, check=None, every_s=0.2):
        """The text of the first message the program echoed after `seen` echoes (len(self.replayed) before the send),
        or None: the program ended, the AI started answering first (a program that doesn't echo), or timeout_s passed.
        The caller compares it with what it sent (stage_start.verify) before the AI's turn counts."""
        steps = self.steps
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if len(self.replayed) > seen:
                return self.replayed[seen][1]
            if self.steps > steps or self.proc.poll() is not None:
                break
            if check:
                check()
            time.sleep(every_s)
        return self.replayed[seen][1] if len(self.replayed) > seen else None

    def alive(self):
        return self.proc.poll() is None

    def turn(self, limit_s, check=None, every_s=2.0):
        """Wait for the turn to end. Returns {'ended': 'result' | 'exit' | 'limit', 'is_error', 'subtype', 'text'
        (the result's text, else the last assistant text), 'held' (it was held on running work), 'steps', 'api_error'
        (the kind of API error the program named on its last failed message, such as 'authentication_failed', else
        None)}. A turn whose last message was such an error is a failed turn, whatever the result's subtype says.
        check(): called every `every_s` (a cancel raises from it). 'limit' is the caller's ceiling, not a done
        signal: the turn is still running."""
        end = time.monotonic() + limit_s
        held, held_since, last_text, api_error = False, None, '', None
        steps_before = self.steps
        while True:
            if check:
                check()
            left = end - time.monotonic()
            if left <= 0:
                return {'ended': 'limit', 'is_error': False, 'subtype': None, 'text': last_text, 'held': held,
                        'steps': self.steps - steps_before}
            try:
                message, holding = self._events.get(timeout=min(every_s, left))
            except queue.Empty:
                if held and held_since is not None and time.monotonic() - held_since > HELD_RESUME_S:
                    return {'ended': 'result', 'is_error': False, 'subtype': 'held_not_resumed', 'text': last_text,
                            'held': True, 'steps': self.steps - steps_before}
                continue
            if message is None:
                self._events.put((None, False))              # later calls see the end too
                try:
                    self.exit_code = self.proc.wait(timeout=10)
                except Exception:  # noqa: BLE001 - the output ended; the code is best effort
                    self.exit_code = self.proc.poll()
                return {'ended': 'exit', 'is_error': True, 'subtype': 'exit', 'text': last_text, 'held': held,
                        'steps': self.steps - steps_before, 'exit_code': self.exit_code, 'api_error': api_error}
            kind = message.get('type')
            if kind == 'assistant':
                text = _text_of(message)
                last_text = text or last_text
                held_since = None
                api_error = _api_error(message)
            elif kind in ('user', 'system') and held and not holding and held_since is None:
                held_since = time.monotonic()                # the work it waited on has ended (an answer, a task)
            elif kind == 'result':
                failed = bool(message.get('is_error')) and (message.get('subtype') != 'success' or bool(api_error))
                text = str(message.get('result') or last_text or '')
                if not failed and holding:
                    held, held_since = True, None
                    continue
                return {'ended': 'result', 'is_error': failed, 'subtype': message.get('subtype'), 'text': text,
                        'held': held, 'steps': self.steps - steps_before, 'api_error': api_error,
                        'usage': message.get('usage'), 'cost_usd': message.get('total_cost_usd')}

    def close(self, wait_s=None):
        """End the session: its input closes (the program ends by itself after its turn), then the whole process tree
        is ended if it hasn't within `wait_s`. Returns the exit code, or None."""
        with self._write_lock:
            try:
                self.proc.stdin.close()
            except (OSError, ValueError):
                pass
        try:
            self.exit_code = self.proc.wait(timeout=CLOSE_WAIT_S if wait_s is None else wait_s)
        except Exception:  # noqa: BLE001 - subprocess.TimeoutExpired or the spawner's own
            kill_tree(self.pid)
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.exit_code = self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.exit_code = None
        self._reader.join(timeout=5)
        return self.exit_code
