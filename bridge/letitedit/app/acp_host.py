"""Runs a connector AI (ai_list.json, protocol "acp") for the chat panel, so the panel needs no protocol code of its own.

    python acp_host.py chat   --ai <id> [--model M] [--effort E] [--resume <session> | --session <new id>] [--work DIR]
                              [--autonomous] [--write-dir DIR]
    python acp_host.py once   --ai <id> --request FILE --out DIR --label WORDS --mode review|draw
    python acp_host.py signin --ai <id>        (the connector opens the browser; a line of JSON per step on stdout)
    python acp_host.py signout --ai <id>
    python acp_host.py install --ai <id>       (the download, checked; a line of JSON per step)
    python acp_host.py state  --ai <id>

`chat` talks to the panel in the lines the panel already reads for Claude Code's chat view: `system init`, `stream_event`,
`assistant`, `user`, `control_request` (asks to use a tool), `result`. Those are this program's own stdin and stdout; toward
the connector it is plainly letitedit. Two extra lines: {"type":"system","subtype":"letitedit_note","text":...} for a line in the
chat, and subtype "letitedit_signin" when the person has to sign in. On stdin: {"type":"user",...}, {"type":"control_response",...}
and {"type":"interrupt"}. End of stdin ends everything.

`once` prints a plain, labelled conversation for a person to watch in the panel's second view (a review, or pictures for another
AI). Nothing of this program runs hidden: every use is a conversation on screen.

**The limits on what's allowed without asking (New video never stops to ask; T30):**
- letitedit's own tools and the AI's own picture tool: yes.
- Reading anything in the project's folder, the work folder or the AI's own session folder: yes.
- Writing files there: yes. Anywhere else: no.
- Shell commands: no, except plain looks at folders and files (`dir`, `ls`, `type`, `cat`), since nothing sandboxes them here. letitedit's
  tools take Python for what a command would do.
- Sub-agents, web fetches and anything else: no. The AI is told and goes another way.
In a normal chat, what's outside this list asks the person in the panel, as Claude Code does.
"""
import argparse
import importlib
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
sys.path.insert(0, str(HERE))

import letitedit.app.acp_client as acp_client  # noqa: E402
import letitedit.app.ai_clis as ai_clis  # noqa: E402
import letitedit.server.long_calls as long_calls  # noqa: E402

SILENCE_LIMIT_S = 900          # no sign of life from the connector, with no tool or question open: a hang
CANCEL_WAIT_S = 15
EOF_CANCEL_WAIT_S = 2
AUTH_WAIT_S = 60               # a saved sign-in answers in seconds
SIGNIN_WAIT_S = 330            # the connector itself gives up at 300 s
CHOICES_FILE = 'letitedit-choices.json'
PASS_ON = ('LETITEDIT_INSTANCE', 'LETITEDIT_ROOT', 'LETITEDIT_SETTINGS', 'LETITEDIT_PROGRESS_DIR', 'LETITEDIT_PROGRESS_RUN',
           'LETITEDIT_RENDER_LOCK',
           'LETITEDIT_WHISPER_CPU', 'LETITEDIT_CHAT_SETTINGS', 'LETITEDIT_AI_LIST', 'LETITEDIT_AI_HOME', 'CUDA_VISIBLE_DEVICES',
           'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'PYTHON_CPU_COUNT', 'LETITEDIT_MY_LOOKS')
LOOK_ONLY = re.compile(r'^\s*(dir|ls|type|cat|Get-ChildItem|Get-Content)(\s|$)', re.I)
QUIET_FAILURE = re.compile(r'Rejected by user|approved but never executed', re.I)
SHELL_JOIN = re.compile(r'[;&|<>`$]')


def adapter_for(ai, settings):
    entry = ai_clis.AIS[ai]
    name = entry.get('adapter')
    if name:
        return importlib.import_module(name).make(entry, settings)
    return acp_client.Adapter(entry, settings)


def rules_text(ai, settings):
    """The panel's prompt, since a connector doesn't read AGENTS.md or GEMINI.md, plus what this AI's limit means."""
    parts = []
    prompt = settings.get('prompt') or ai_clis.ROOT / 'chat' / 'panel-prompt.md'
    try:
        parts.append(Path(prompt).read_text(encoding='utf-8'))
    except OSError:
        pass
    if ai_clis.tool_call_limit_s(ai):
        parts.append("Some letitedit calls take longer than your tool limit. A result that says 'still working' is not a failure: "
                     f'call {long_calls.WAIT_TOOL} with its call_id, as often as needed.')
    return '\n\n'.join(parts)


def tool_server(ai, settings):
    """letitedit's tool server for session/new, with this AI's limit on a tool call."""
    python = settings.get('python') or sys.executable
    server = settings.get('mcp_server') or str(HERE / 'letitedit_mcp.py')
    env = {'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'LETITEDIT_ACTOR': ai}
    env.update({k: os.environ[k] for k in PASS_ON if os.environ.get(k)})
    limit = ai_clis.tool_call_limit_s(ai)
    if limit:
        env[long_calls.LIMIT_VAR] = str(limit)
    return {'name': 'letitedit', 'command': str(python), 'args': [str(server)],
            'env': [{'name': k, 'value': v} for k, v in env.items()]}


def _start(ai, settings, cwd, on_update=None, on_permission=None, browser=None):
    """A connector, started and answering. Raises Gone or AcpError when it can't."""
    exe = ai_clis.find(ai, settings)
    if not exe:
        raise FileNotFoundError(f"{ai_clis.NAMES[ai]} isn't set up on this PC yet. Use Connect Your AI.")
    adapter = adapter_for(ai, settings)
    home = ai_clis.profile(ai, settings)
    home.mkdir(parents=True, exist_ok=True)
    temps = ai_clis.ai_home(ai, settings) / 'tmp'
    temps.mkdir(parents=True, exist_ok=True)
    acp_client.clean_old_temps(temps)
    temp = temps / f'{os.getpid()}-{int(time.time())}'
    temp.mkdir(parents=True, exist_ok=True)
    env = adapter.env(dict(os.environ), home, temp)
    env.pop('BROWSER', None)
    if browser or os.environ.get('LETITEDIT_ACP_TEST_BROWSER'):
        env['BROWSER'] = browser or os.environ['LETITEDIT_ACP_TEST_BROWSER']
    connector = acp_client.Connector(exe, cwd, env, on_update, on_permission, ai_clis.ai_home(ai, settings) / 'last-run.log', temp)
    try:
        connector.initialize()
    except Exception:
        connector.end()
        raise
    return adapter, connector


def save_choices(ai, settings, session, auth=None):
    """What this account is offered, from session/new, for the AI's model and effort menus."""
    options = {o.get('id'): o for o in (session.get('configOptions') or []) if isinstance(o, dict)}
    def rows(option):
        return [{'value': x.get('value'), 'label': x.get('name') or x.get('value')} for x in (options.get(option, {}).get('options') or [])]
    found = {'models': rows('model'), 'efforts': rows('thinking_level')}
    tier = (((auth or {}).get('_meta') or {}).get(ai) or {}).get('tier') or {}
    for meta in ((auth or {}).get('_meta') or {}).values():
        tier = tier or (meta.get('tier') if isinstance(meta, dict) else None) or {}
    if tier.get('name'):
        found['plan'] = tier['name']
    try:
        path = ai_clis.profile(ai, settings) / CHOICES_FILE
        path.write_text(json.dumps(found, indent=1), encoding='utf-8')
    except OSError:
        pass
    return found


def set_choice(connector, session_id, session, config_id, wanted):
    """Sets a model or thinking level the account offers. Returns (value now, was the wanted one refused)."""
    option = next((o for o in (session.get('configOptions') or []) if o.get('id') == config_id), None)
    if not option:
        return wanted, False
    current = option.get('currentValue')
    if not wanted or wanted == current:
        return current, False
    if wanted not in [x.get('value') for x in option.get('options') or []]:
        return current, True
    connector.request('session/set_config_option', {'sessionId': session_id, 'configId': config_id, 'value': wanted}, timeout=60)
    return wanted, False


def allow_option(params, allow):
    """The option to answer with: allow once, or reject once. An `allow_always` is never picked: it lasts one session anyway."""
    want = 'allow_once' if allow else 'reject_once'
    options = params.get('options') or []
    chosen = next((o for o in options if o.get('kind') == want), None)
    return chosen.get('optionId') if chosen else None


def _inside(path, folders):
    try:
        target = Path(path).resolve()
    except (OSError, ValueError, TypeError):
        return False
    return any(target == Path(f).resolve() or Path(f).resolve() in target.parents for f in folders if f)


def own_tool_name(call):
    title = str(call.get('title') or '')
    found = re.match(r'Run (\w+)\?', title)
    return found.group(1) if found else ''


def permission(call, folders, picture_tools=('generate_image',)):
    """Yes, no, or 'ask', within the limits at the top of this file. `call` is the request's toolCall."""
    meta = (call.get('_meta') or {}).get('mcp') or {}
    if meta.get('server') == 'letitedit':
        return 'yes'
    raw = call.get('rawInput') if isinstance(call.get('rawInput'), dict) else {}
    if own_tool_name(call) in picture_tools or ('ImageName' in raw and 'Prompt' in raw):
        return 'yes'
    kind = call.get('kind')
    places = [loc.get('path') for loc in call.get('locations') or [] if isinstance(loc, dict)]
    if kind in ('read', 'search', 'edit'):
        return 'yes' if places and all(_inside(p, folders) for p in places) else 'ask'
    if kind == 'execute':
        command = str(raw.get('CommandLine') or call.get('title') or '')
        if LOOK_ONLY.match(command) and not SHELL_JOIN.search(command):
            return 'yes'
    return 'ask'


class Chat:
    """The chat panel's side of one conversation."""

    def __init__(self, args):
        self.args, self.ai = args, args.ai
        self.settings = ai_clis.chat_settings()
        self.name = ai_clis.NAMES[self.ai]
        self.out_lock = threading.Lock()
        self.input = queue.Queue()
        self.answers = {}
        self.answer_lock = threading.Lock()
        self.connector = None
        self.adapter = None
        self.session_id = None
        self.first_prompt_extra = ''
        self.work = Path(args.work or self.settings.get('work_dir') or Path.cwd())
        self.folders = [self.work, args.write_dir, ai_clis.profile(self.ai, self.settings)]
        self.turn_text, self.message_text, self.tools = '', '', {}
        self.last_life = time.monotonic()
        self.open_questions = 0
        self.stopping = threading.Event()
        self.turn_running = threading.Event()
        self.cancelled_at = None

    # --- to the panel
    def emit(self, obj):
        line = json.dumps(obj, ensure_ascii=False) + '\n'
        with self.out_lock:
            try:
                sys.stdout.buffer.write(line.encode('utf-8'))
                sys.stdout.buffer.flush()
            except (OSError, ValueError):
                self.stopping.set()

    def note(self, text):
        self.emit({'type': 'system', 'subtype': 'letitedit_note', 'text': text})

    def result(self, words='', failed=False, subtype=None):
        self.emit({'type': 'result', 'subtype': subtype or ('error' if failed else 'success'), 'is_error': failed, 'result': words})

    # --- from the connector
    def on_update(self, params):
        self.last_life = time.monotonic()
        update = params.get('update') or {}
        kind = update.get('sessionUpdate')
        if kind == 'agent_message_chunk':
            content = update.get('content') or {}
            text = content.get('text') if isinstance(content, dict) else None
            if text:
                if not self.message_text:
                    self.emit({'type': 'stream_event', 'event': {'type': 'message_start'}})
                self.message_text += text
                self.turn_text += text
                self.emit({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': text}}})
        elif kind in ('tool_call', 'tool_call_update'):
            self._flush_message()
            self._tool(update)

    def _flush_message(self):
        if self.message_text:
            self.emit({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': self.message_text}]}})
            self.message_text = ''

    def _ledger(self, **row):
        """LETITEDIT_ACP_EVENTS names a file for a timed record of a run (a test's time ledger): when each tool call began and ended. Off otherwise."""
        path = os.environ.get('LETITEDIT_ACP_EVENTS')
        if path:
            try:
                with open(path, 'a', encoding='utf-8') as out:
                    out.write(json.dumps(dict(row, t=round(time.time(), 2))) + '\n')
            except OSError:
                pass

    def _tool(self, update):
        call_id = update.get('toolCallId')
        self._ledger(kind='tool', id=call_id, tool=self.adapter.tool_name(update) if update.get('title') else None, status=update.get('status'))
        if call_id not in self.tools and update.get('title'):
            self.tools[call_id] = True
            self.emit({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': call_id, 'name': self.adapter.tool_name(update),
                                                                      'input': self.adapter.tool_input(update)}]}})
        if update.get('status') == 'failed':
            said = update.get('rawOutput')
            words = said if isinstance(said, str) else json.dumps(said)[:400] if said else 'That step failed.'
            if QUIET_FAILURE.search(words):     # a refusal the chat has already said, or a step a finished turn dropped
                return
            self.emit({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': call_id, 'is_error': True, 'content': words}]}})

    def on_permission(self, params):
        self.last_life = time.monotonic()
        call = params.get('toolCall') or {}
        answer = permission(call, self.folders)
        if answer == 'ask' and self.args.autonomous:
            answer = 'no'
            self.note(f'Not allowed in a New video: {str(call.get("title"))[:160]}')
        if answer == 'ask':
            answer = self._ask_person(call)
        return allow_option(params, answer == 'yes')

    def _ask_person(self, call):
        request_id = f'p{time.monotonic_ns()}'
        box = queue.Queue()
        with self.answer_lock:
            self.answers[request_id] = box
            self.open_questions += 1
        self.emit({'type': 'control_request', 'request_id': request_id,
                   'request': {'subtype': 'can_use_tool', 'tool_name': self.adapter.tool_name(call), 'input': self.adapter.tool_input(call),
                               'description': str(call.get('title') or '')[:700]}})
        try:
            while not self.stopping.is_set():
                try:
                    return box.get(timeout=0.5)
                except queue.Empty:
                    continue
            return 'no'
        finally:
            with self.answer_lock:
                self.answers.pop(request_id, None)
                self.open_questions -= 1
            self.last_life = time.monotonic()

    # --- from the panel
    def read_panel(self):
        for raw in iter(sys.stdin.buffer.readline, b''):
            try:
                msg = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError:
                continue
            kind = msg.get('type')
            if kind == 'control_response':
                inner = msg.get('response') or {}
                decision = (inner.get('response') or {}).get('behavior')
                with self.answer_lock:
                    box = self.answers.get(inner.get('request_id'))
                if box:
                    box.put('yes' if decision == 'allow' else 'no')
            elif kind == 'interrupt':
                self._cancel()
            elif kind == 'user':
                if self.turn_running.is_set():
                    self.note(f'{self.name} takes one message at a time: this one goes next, when it finishes.')
                self.input.put(msg)
        self.input.put(None)        # the panel closed: everything ends

    def _cancel(self):
        if self.connector and self.session_id and self.turn_running.is_set():
            try:
                self.connector.notify('session/cancel', {'sessionId': self.session_id})
            except acp_client.Gone:
                pass
            self.cancelled_at = time.monotonic()

    # --- the conversation
    def open_session(self):
        args = self.args
        self.note(f'Starting {self.name}: about 15 seconds.')
        home_signed_in = ai_clis.signed_in(self.ai, None, settings=self.settings)
        if home_signed_in is False:
            self.emit({'type': 'system', 'subtype': 'letitedit_signin', 'text': f"{self.name} isn't signed in yet. Use Connect Your AI to sign in."})
            self.result(f"{self.name} isn't signed in yet. Use Connect Your AI to sign in.", failed=True)
            return False
        # A saved sign-in answers without any page. If Google wants a new one the connector must not open a browser by itself.
        self.adapter, self.connector = _start(self.ai, self.settings, self.work, self.on_update, self.on_permission, browser='cmd /c exit 0')
        method = ai_clis.AIS[self.ai].get('auth_method')
        auth = None
        if method:
            try:
                auth = self.connector.request('authenticate', {'methodId': method}, timeout=AUTH_WAIT_S)
            except (acp_client.AcpError, TimeoutError) as exc:
                words = f"{self.name} couldn't use your saved sign-in. Use Connect Your AI to sign in again. ({str(exc)[:200]})"
                self.emit({'type': 'system', 'subtype': 'letitedit_signin', 'text': words})
                self.result(words, failed=True)
                return False
        self.adapter.install_skills(ai_clis.profile(self.ai, self.settings))
        rules = rules_text(self.ai, self.settings)
        meta = self.adapter.session_meta(rules)
        if meta is None:
            self.first_prompt_extra = rules
        base = {'cwd': str(self.work), 'mcpServers': [tool_server(self.ai, self.settings)]}
        if meta:
            base['_meta'] = meta
        session = self._resume(base) if args.resume else None
        if session is None:
            session = self.connector.request('session/new', base, timeout=300)
            if args.resume:
                self.note("The earlier conversation couldn't be continued, so this is a new one.")
        self.session_id = session.get('sessionId') or args.resume
        offered = save_choices(self.ai, self.settings, session, auth)
        model, refused = set_choice(self.connector, self.session_id, session, 'model', args.model)
        if refused:
            names = {m['value']: m['label'] for m in offered['models']}
            self.note(f"{args.model} isn't on this Google plan, so this chat uses {names.get(model, model)}.")
        set_choice(self.connector, self.session_id, session, 'thinking_level', args.effort)
        self.emit({'type': 'system', 'subtype': 'init', 'session_id': self.session_id, 'model': model or '', 'tools': [],
                   'permissionMode': 'auto' if args.autonomous else 'host'})
        return True

    def _resume(self, base):
        can_resume, can_load = self.connector.can_resume()
        for method, able in (('session/resume', can_resume), ('session/load', can_load)):
            if not able:
                continue
            try:
                reply = self.connector.request(method, dict(base, sessionId=self.args.resume), timeout=300)
                return dict(reply, sessionId=self.args.resume)
            except (acp_client.AcpError, TimeoutError):
                continue
        return None

    def run_turn(self, msg):
        blocks = []
        for block in (msg.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'text':
                blocks.append({'type': 'text', 'text': block.get('text', '')})
        if self.first_prompt_extra and blocks:
            blocks[0]['text'] = self.first_prompt_extra + '\n\n' + blocks[0]['text']
            self.first_prompt_extra = ''
        self.turn_text, self.message_text = '', ''
        self.cancelled_at = None
        before = len(self.connector.stderr)
        self.turn_running.set()
        answer, problem = {}, {}

        def ask():
            try:
                answer.update(self.connector.request('session/prompt', {'sessionId': self.session_id, 'prompt': blocks}, timeout=86400))
            except Exception as exc:  # noqa: BLE001 - reported as the turn's end
                problem['error'] = exc
        worker = threading.Thread(target=ask, daemon=True)
        self.last_life = time.monotonic()
        worker.start()
        while worker.is_alive():
            worker.join(0.5)
            if self.cancelled_at and time.monotonic() - self.cancelled_at > CANCEL_WAIT_S:
                self.note(f'{self.name} did not stop in {CANCEL_WAIT_S} s, so it was closed. Your next message continues this conversation.')
                self.result(subtype='cancelled')
                self.turn_running.clear()
                return False
            if not self.open_questions and time.monotonic() - self.last_life > SILENCE_LIMIT_S:
                self.result(f'{self.name} went quiet for {SILENCE_LIMIT_S // 60} minutes, so it was closed. Your next message continues this conversation.', failed=True)
                self.turn_running.clear()
                return False
            if self.stopping.is_set():
                self.turn_running.clear()
                return False
        self.turn_running.clear()
        self._flush_message()
        self._ledger(kind='turn', stop=answer.get('stopReason'), error=str(problem.get('error'))[:200] if problem else None)
        if self.cancelled_at:
            self.result(subtype='cancelled')
            return True
        if problem:
            error = problem['error']
            self.result(f'{self.name} stopped unexpectedly: {str(error)[:300]}. Your next message continues this conversation.', failed=True)
            return not isinstance(error, acp_client.Gone)
        tail = '\n'.join(self.connector.stderr[before:])
        said = self.adapter.image_limit(self.turn_text, tail)
        if said:
            self.note(said)
        failure = self.adapter.turn_failure(self.turn_text, answer.get('stopReason'), tail)
        if failure:
            if failure.get('kind') == 'signin':
                self.emit({'type': 'system', 'subtype': 'letitedit_signin', 'text': failure['words']})
            self.result(failure['words'], failed=True)
        else:
            self.result(self.turn_text)
        return True

    def run(self):
        threading.Thread(target=self.read_panel, daemon=True).start()
        opened = False
        try:
            while True:
                msg = self.input.get()
                if msg is None:
                    break
                if not opened:
                    if not self.open_session():
                        break
                    opened = True
                if not self.run_turn(msg):
                    break
        except FileNotFoundError as exc:
            self.result(str(exc), failed=True)
        except (acp_client.Gone, acp_client.AcpError, TimeoutError, OSError) as exc:
            self.result(f"{self.name} couldn't start: {str(exc)[:300]}", failed=True)
        finally:
            self.stopping.set()
            if self.connector:
                self._cancel()
                if self.turn_running.is_set():
                    time.sleep(EOF_CANCEL_WAIT_S)
                self.connector.end()


# ------------------------------------------------------------------- a conversation a person watches

def _say(text=''):
    try:
        sys.stdout.write(text + '\n')
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _decode_picture(adapter, update, out, number):
    """Saves a picture a tool call made, from the update itself: never from what the AI says."""
    path, data = adapter.picture_from(update)
    if not (path or data):
        return None
    if path and Path(path).is_file():
        return str(Path(path))
    import base64
    target = Path(out) / f'picture-{number}.jpg'
    target.write_bytes(base64.b64decode(data))
    return str(target)


def run_once(args):
    """One visible conversation: the request (a text file, and beside it a .json with `images` and `prompts`), a plain record of
    it on screen, and done.json in `out` when it ends. Pictures come back by path, for the AI that asked."""
    settings = ai_clis.chat_settings()
    ai, name = args.ai, ai_clis.NAMES[args.ai]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    done = {'pictures': [], 'failure': None, 'message': None}
    request = Path(args.request)
    extras = {}
    try:
        extras = json.loads(request.with_suffix('.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        pass
    prompts = extras.get('prompts') or [request.read_text(encoding='utf-8')]
    answer_file = extras.get('answer')
    _say(args.label)
    _say(f'Starting {name}: about 15 seconds.')
    state = {'seen': set(), 'tools': {}, 'text': []}
    connector = None

    def on_update(params):
        update = params.get('update') or {}
        kind = update.get('sessionUpdate')
        if kind == 'agent_message_chunk':
            content = update.get('content') or {}
            if isinstance(content, dict) and content.get('text'):
                state['text'].append(content['text'])
        elif kind in ('tool_call', 'tool_call_update'):
            if state['text']:
                _say(''.join(state['text']))
                state['seen'].add('text')
            call_id = update.get('toolCallId')
            if call_id not in state['tools'] and update.get('title'):
                state['tools'][call_id] = True
                _say(f"[{str(update.get('title'))[:100]}]")
            picture = _decode_picture(adapter, update, out, len(done['pictures']) + 1) if update.get('status') == 'completed' else None
            if picture and picture not in done['pictures']:
                done['pictures'].append(picture)
                _say(f'Picture saved: {picture}')

    def on_permission(params):
        call = params.get('toolCall') or {}
        meta = (call.get('_meta') or {}).get('mcp') or {}
        raw = call.get('rawInput') if isinstance(call.get('rawInput'), dict) else {}
        places = [loc.get('path') for loc in call.get('locations') or [] if isinstance(loc, dict)]
        if args.mode == 'draw':
            allow = own_tool_name(call) == 'generate_image' or ('ImageName' in raw and 'Prompt' in raw)
        else:
            allow = meta.get('server') != 'letitedit' and call.get('kind') in ('read', 'edit') and bool(places) \
                and all(_inside(p, [out]) for p in places)
        _say(f"{'Allowed' if allow else 'Not allowed'}: {str(call.get('title'))[:100]}")
        return allow_option(params, allow)

    try:
        adapter, connector = _start(ai, settings, out, on_update, on_permission, browser='cmd /c exit 0')
        method = ai_clis.AIS[ai].get('auth_method')
        if method:
            connector.request('authenticate', {'methodId': method}, timeout=AUTH_WAIT_S)
        session = connector.request('session/new', {'cwd': str(out), 'mcpServers': []}, timeout=300)
        session_id = session.get('sessionId')
        entry = ai_clis.AIS[ai]
        set_choice(connector, session_id, session, 'model', entry.get('draw_model') if args.mode == 'draw' else args.model)
        set_choice(connector, session_id, session, 'thinking_level', entry.get('draw_effort') if args.mode == 'draw' else args.effort)
        for number, prompt in enumerate(prompts):
            blocks = [{'type': 'text', 'text': prompt}] + ([acp_client.image_block(p) for p in extras.get('images') or []] if number == 0 else [])
            before = len(connector.stderr)
            state['text'] = []
            reply = connector.request('session/prompt', {'sessionId': session_id, 'prompt': blocks}, timeout=1800)
            text = ''.join(state['text'])
            if text:
                _say(text)
            tail = '\n'.join(connector.stderr[before:])
            limit = adapter.image_limit(text, tail) if args.mode == 'draw' else None
            failure = adapter.turn_failure(text, reply.get('stopReason'), tail)
            if limit or failure:
                done['failure'] = 'limit' if limit or failure.get('kind') == 'limit' else failure.get('kind') or 'failed'
                done['message'] = limit or failure.get('words')
                _say(done['message'])
                break
    except (acp_client.Gone, acp_client.AcpError, TimeoutError, OSError) as exc:
        done['failure'] = 'failed'
        done['message'] = f"{name} couldn't finish: {str(exc)[:300]}"
        _say(done['message'])
    finally:
        if connector:
            connector.end()
    if answer_file and not Path(answer_file).is_file():
        # Whoever waits for the answer file hears why: nothing has to run out a timer.
        if not done['failure']:
            done['failure'], done['message'] = 'failed', f'{name} finished without saving its answer.'
        Path(answer_file).write_text(json.dumps({'error': done['message'], 'error_kind': done['failure']}), encoding='utf-8')
    (out / 'done.json').write_text(json.dumps(done, indent=1), encoding='utf-8')
    _say('Finished.')
    return 0


# ------------------------------------------------------------------- sign-in and setup

def _line(**fields):
    sys.stdout.write(json.dumps(fields, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def run_signin(args):
    settings = ai_clis.chat_settings()
    ai, name = args.ai, ai_clis.NAMES[args.ai]
    _line(state='starting', message=f'Starting {name}: about 15 seconds.')
    work = ai_clis.ai_home(ai, settings) / 'work'
    connector = None
    try:
        adapter, connector = _start(ai, settings, work)
        method = ai_clis.AIS[ai].get('auth_method')
        _line(state='waiting', message=adapter.signin_waiting_words() if hasattr(adapter, 'signin_waiting_words')
              else f'Finish signing in on the page that opened. {name} waits 5 minutes.')
        try:
            auth = connector.request('authenticate', {'methodId': method}, timeout=SIGNIN_WAIT_S)
        except acp_client.AcpError as exc:
            _line(**adapter.signin_refused(exc.error))
            return 1
        except TimeoutError:
            _line(state='timeout', message=f'The sign-in page timed out after 5 minutes. Nothing went wrong: press Sign in to try again.')
            return 1
        adapter.install_skills(ai_clis.profile(ai, settings))
        session = connector.request('session/new', {'cwd': str(work), 'mcpServers': []}, timeout=300)
        found = save_choices(ai, settings, session, auth)
        _line(state='signed_in', message=f'{name} is signed in.', plan=found.get('plan'), models=found.get('models'))
        return 0
    except (acp_client.Gone, acp_client.AcpError, TimeoutError, OSError) as exc:
        _line(state='failed', message=f"{name} couldn't start: {str(exc)[:300]}")
        return 1
    finally:
        if connector:
            connector.end()


def run_signout(args):
    settings = ai_clis.chat_settings()
    connector = None
    try:
        _, connector = _start(args.ai, settings, ai_clis.ai_home(args.ai, settings) / 'work')
        connector.request('logout', {}, timeout=60)
        _line(state='signed_out', message=f'{ai_clis.NAMES[args.ai]} is signed out.')
        return 0
    except (acp_client.Gone, acp_client.AcpError, TimeoutError, OSError) as exc:
        _line(state='failed', message=str(exc)[:300])
        return 1
    finally:
        if connector:
            connector.end()


def run_install(args):
    settings = ai_clis.chat_settings()
    adapter = adapter_for(args.ai, settings)
    if not hasattr(adapter, 'install'):
        _line(state='failed', message=f'{ai_clis.NAMES[args.ai]} has no download.')
        return 1
    try:
        adapter.install(ai_clis.ai_home(args.ai, settings), _line)
        return 0
    except Exception as exc:  # noqa: BLE001 - a person reads this
        _line(state='failed', message=str(exc)[:500])
        return 1


def run_state(args):
    settings = ai_clis.chat_settings()
    exe = ai_clis.find(args.ai, settings)
    print(json.dumps({'installed': bool(exe), 'signed_in': bool(exe) and ai_clis.signed_in(args.ai, exe, settings=settings)}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['chat', 'once', 'signin', 'signout', 'install', 'state'])
    parser.add_argument('--ai', required=True)
    parser.add_argument('--model')
    parser.add_argument('--effort')
    parser.add_argument('--resume')
    parser.add_argument('--session')
    parser.add_argument('--work')
    parser.add_argument('--autonomous', action='store_true')
    parser.add_argument('--write-dir')
    parser.add_argument('--request')
    parser.add_argument('--out')
    parser.add_argument('--label', default='')
    parser.add_argument('--mode', choices=['review', 'draw'], default='review')
    args = parser.parse_args(argv)
    if args.ai not in ai_clis.AIS:
        print(f'{args.ai} is not in the list of AIs.', file=sys.stderr)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    if args.command == 'chat':
        Chat(args).run()
        sys.stdout.flush()
        os._exit(0)     # the thread reading the panel's input may be in the middle of a read: nothing is left to tidy
    return {'once': run_once, 'signin': run_signin, 'signout': run_signout, 'install': run_install, 'state': run_state}[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
