"""The person's AI programs (Claude Code, Codex, a connector AI; the list is ai_list.json): which are on this PC, whether they are signed in, how a failed run
failed, and a clean environment for a separate run. Nothing here starts a model or uses any allowance. Most people have
only one of the two, so nothing may assume the other exists or name it to them.

find(engine, settings=None)   the program, or None. Looks in the same places as the app's Connect Your AI
signed_in(engine, exe)        True, False, or None when it can't tell (never reads a credentials file)
failure_kind(text, api_error) 'limit', 'signin', 'missing' or None, from what a failed run printed
limit_line(text)              the line that says so ("You've hit your weekly limit · resets 3am")
child_env()                   this environment without the markers of the session it runs under
chat_settings()               the chat's panel.json ({} when the person has not saved a choice yet)
editor(settings=None)         the AI doing the editing, 'claude' or 'codex', or None
critic_order(prefer, who)     the order to try for a review: `prefer`, else the AI that isn't editing, first
background_allowed(settings)  whether letitedit may run the AI with nobody watching (the chat's "background_jobs" setting)
reviewer_line(review)         review.json in one plain sentence
editing_tool_args()           Claude Code's built-in tools turned off in an editing session (behind a switch, on by default)
probe_editing_tools(exe)      which built-in tools this PC's Claude Code offers: starts it with no model, so no allowance
choice(engine, role, ...)     the model and effort a run uses for a role ('plan' or 'routine'): a pin, the saved
                              choice, Auto (routing within the person's own AI) or the app's default (T331 P10)
choice_args(engine, picked)   that choice as the program's command-line arguments
routing_on()                  whether Auto is the choice for anyone who never chose (on by default)

What can't be told without a run: how much allowance is left, whether a sign-in that looks fine has been revoked, which
models the person's plan includes. Those show up only as a failed run (failure_kind).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

# The one list of AIs (ai_list.json), read here and by the editor. Without the file, the two older AIs still work.
_BUILT_IN = [
    {'id': 'claude', 'name': 'Claude Code', 'short': 'Claude', 'protocol': 'claude', 'status_args': ['auth', 'status'], 'api_key_var': 'ANTHROPIC_API_KEY',
     'model_key': 'model', 'effort_key': 'effort', 'can': {'chat': True, 'terminal': True, 'background': True, 'draw': False},
     'reinstall': 'open a terminal and run: npm install -g @anthropic-ai/claude-code (or follow '
                  'https://docs.claude.com/en/docs/claude-code/setup)'},
    {'id': 'codex', 'name': 'Codex', 'short': 'Codex', 'protocol': 'codex', 'status_args': ['login', 'status'], 'api_key_var': 'CODEX_API_KEY',
     'model_key': 'codex_model', 'effort_key': 'codex_reasoning', 'can': {'chat': True, 'terminal': True, 'background': True, 'draw': True},
     'reinstall': 'follow https://developers.openai.com/codex/cli'}]


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def _read_list():
    path = os.environ.get('LETITEDIT_AI_LIST') or _paths.BRIDGE / 'ai_list.json'
    try:
        rows = json.loads(Path(path).read_text(encoding='utf-8-sig'))['ais']
        return [r for r in rows if r.get('id')] or _BUILT_IN
    except (OSError, ValueError, KeyError, TypeError):
        return _BUILT_IN


AIS = {row['id']: row for row in _read_list()}
ALL_AIS = tuple(AIS)
# The AIs letitedit may run by itself, with no conversation on screen (the critic, New hook refill, the emotion graph).
ENGINES = tuple(i for i, row in AIS.items() if row.get('can', {}).get('background'))
NAMES = {i: row.get('name', i) for i, row in AIS.items()}
STATUS_ARGS = {i: tuple(row['status_args']) for i, row in AIS.items() if row.get('status_args')}     # no model, no allowance
API_KEY_VARS = {i: row['api_key_var'] for i, row in AIS.items() if row.get('api_key_var')}          # the program's own; never removed from a run
MODEL_KEYS = {i: row.get('model_key', f'{i}_model') for i, row in AIS.items()}                      # in the chat's settings
EFFORT_KEYS = {i: row.get('effort_key', f'{i}_effort') for i, row in AIS.items()}
# What an unattended run uses for an AI whose model or effort the person never saved: the app's own default (11 Nov 2026).
DEFAULT_CHOICE = {'claude': ('opus', 'medium'), 'codex': ('gpt-6.1-sol', 'medium')}
# Auto model routing (T319 rule 3, T331 P10): ai_list.json "routing" per AI. "auto" saved as the model is Auto; with the
# switch on (the default), Auto is also the choice of anyone who never saved a model. Off (settings.json
# auto_routing: false), only a saved "auto" routes.
AUTO = 'auto'
ROLES = ('plan', 'routine')
ROUTING_SWITCH = 'auto_routing'                 # settings.json; LETITEDIT_AUTO_ROUTING (1 or 0) wins
ROUTING_MAX_KEY = 'routing_max'                 # the chat's panel.json: the gear's "Max on every stage"
EFFORT_SCALE = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
ROOT = Path(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT)
# Marks of a running session. Their sign-in and config variables (CLAUDE_CONFIG_DIR, CODEX_HOME, tokens) stay.
SESSION_VARS = ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_SESSION_ID',
                'CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS', 'CODEX_THREAD_ID', 'CODEX_SANDBOX',
                'CODEX_SANDBOX_NETWORK_DISABLED', 'CODEX_CI', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE')
# Real wording: Codex "You’ve hit your usage limit. Visit ...", Claude "You've hit your weekly limit · resets 3am".
LIMIT = re.compile(r"hit your [\w ]*limit|usage limit|rate limit|limit reached|quota exceeded|exceeded your [\w ]*quota",
                   re.I)
SIGNIN = re.compile(r"not logged in|/login|codex login|invalid api key|unauthori[sz]ed|\b401\b|authentication[_ ]error|"
                    r"token (has )?expired|failed to authenticate|authentication[_ ]failed|oauth (token|session)|"
                    r"log in again", re.I)
# The kind of error Claude Code puts on an assistant message whose API call failed (its stream's `error` field), as
# failure_kind names it. A sign-in that was revoked or expired reads "Failed to authenticate: OAuth token revoked".
API_ERROR_KINDS = {'authentication_failed': 'signin'}
# A shim with no program behind it: an npm install whose update stopped partway prints this.
MISSING = re.compile(r"no such file or directory|is not recognized as|cannot find the path|system cannot find", re.I)
REINSTALL = {i: row['reinstall'] for i, row in AIS.items() if row.get('reinstall')}


def chat_settings():
    """The chat's settings as saved: LETITEDIT_CHAT_SETTINGS, else <root>/chat/panel.json. The file doesn't exist until
    the person has changed a choice, so a missing or broken one is simply no settings."""
    path = Path(os.environ.get('LETITEDIT_CHAT_SETTINGS') or ROOT / 'chat' / 'panel.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def routing_on(env=None, settings_path=None):
    """Whether Auto is the model choice of anyone who never saved one (settings.json auto_routing;
    on by default, false turns it off).
    A saved "auto" routes whatever this says: the person chose it."""
    environment = os.environ if env is None else env
    forced = str(environment.get('LETITEDIT_AUTO_ROUTING', '')).strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    path = Path(settings_path or environment.get('LETITEDIT_SETTINGS') or ROOT / 'settings.json')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig')).get(ROUTING_SWITCH) is not False
    except (OSError, ValueError, AttributeError):
        return True


def routing(engine):
    """The AI's routing table from ai_list.json ({} for an AI without one)."""
    table = AIS.get(engine, {}).get('routing')
    return table if isinstance(table, dict) else {}


def is_auto(model):
    return str(model or '').strip().lower() == AUTO


def in_provider(engine, model):
    """True when `model` is one of this AI's own (its routing table's model_pattern). Auto never leaves the AI."""
    pattern = routing(engine).get('model_pattern')
    return bool(model) and bool(pattern) and re.fullmatch(pattern, str(model)) is not None


def _lighter(a, b):
    """The lighter of two efforts on EFFORT_SCALE (one off the scale gives way to the other)."""
    if a not in EFFORT_SCALE:
        return b
    if b not in EFFORT_SCALE:
        return a
    return a if EFFORT_SCALE.index(a) <= EFFORT_SCALE.index(b) else b


def _default_pair(engine):
    entry = AIS.get(engine, {})
    return DEFAULT_CHOICE.get(engine) or (entry.get('default_model'), entry.get('default_effort'))


def auto_choice(engine, role='plan', *, max_all=False, effort=None):
    """(model, effort) Auto gives a role on this AI. max_all: every role on the max row. effort: the person's saved
    effort, kept for the plan role; routine never thinks harder than plan. An AI without a table (a connector AI)
    gets its own default; a table naming a model outside the AI's own falls back to the app's default for it."""
    if role not in ROLES:
        raise ValueError(f'Unknown model role: {role} (one of {", ".join(ROLES)})')
    table = routing(engine)
    roles = table.get('roles') or {}
    if not roles:
        return _default_pair(engine)
    if max_all and table.get('max'):
        row = table['max']
        model, chosen = row.get('model'), row.get('effort')
    else:
        plan = roles.get('plan') or {}
        row = roles.get(role) or plan
        plan_effort = effort or plan.get('effort')
        model = row.get('model')
        chosen = plan_effort if role == 'plan' else _lighter(row.get('effort'), plan_effort)
    if not in_provider(engine, model):
        return _default_pair(engine)
    return model, chosen


def choice(engine, role='plan', settings=None, pin=None, env=None, settings_path=None):
    """The model and effort a run of this AI uses for a role: {'model', 'effort', 'source', 'role'}.

    source 'pin'      the caller's pin (a job's `ai`, a test's override): always honoured
           'saved'    the model the person saved in the chat's settings: a pin too, never changed
           'auto'     Auto: the person saved "auto", or saved nothing with the switch on (routing_on)
           'max'      Auto with the gear's Max on every stage (panel.json routing_max)
           'default'  nothing saved and the switch off: the app's default (DEFAULT_CHOICE), as before
    A pin or saved model of "auto" means Auto. A saved or pinned effort is kept (for the plan role under Auto)."""
    if role not in ROLES:
        raise ValueError(f'Unknown model role: {role} (one of {", ".join(ROLES)})')
    settings = chat_settings() if settings is None else (settings or {})
    pin = pin or {}
    saved_model = str(settings.get(MODEL_KEYS.get(engine, 'model')) or '').strip()
    saved_effort = str(settings.get(EFFORT_KEYS.get(engine, 'effort')) or '').strip()
    pinned_model = str(pin.get('model') or '').strip()
    effort = str(pin.get('effort') or '').strip() or saved_effort
    default_model, default_effort = _default_pair(engine)
    if pinned_model and not is_auto(pinned_model):
        return {'model': pinned_model, 'effort': effort or default_effort, 'source': 'pin', 'role': role}
    if not pinned_model and saved_model and not is_auto(saved_model):
        return {'model': saved_model, 'effort': effort or default_effort, 'source': 'saved', 'role': role}
    if not (is_auto(pinned_model) or is_auto(saved_model) or routing_on(env, settings_path)):
        return {'model': default_model, 'effort': effort or default_effort, 'source': 'default', 'role': role}
    max_all = settings.get(ROUTING_MAX_KEY) is True
    model, chosen = auto_choice(engine, role, max_all=max_all, effort=effort or None)
    return {'model': model, 'effort': chosen, 'source': 'max' if max_all and routing(engine).get('max') else 'auto',
            'role': role}


def choice_args(engine, picked):
    """A choice as the program's arguments: Claude Code `--model m --effort e`, Codex `-m m -c
    model_reasoning_effort="e"` (Codex takes the effort per run and per app-server turn)."""
    model, effort = (picked or {}).get('model'), (picked or {}).get('effort')
    if engine == 'claude':
        return (['--model', str(model)] if model else []) + (['--effort', str(effort)] if effort else [])
    if engine == 'codex':
        return (['-m', str(model)] if model else []) + \
            (['-c', f'model_reasoning_effort={json.dumps(str(effort))}'] if effort else [])
    return []


def codex_turn_params(picked):
    """A Codex app-server `turn/start`'s model and effort for a choice (the effort changes per turn)."""
    out = {}
    if (picked or {}).get('model'):
        out['model'] = picked['model']
    if (picked or {}).get('effort'):
        out['effort'] = picked['effort']
    return out


def _claude_places():
    yield Path.home() / '.local' / 'bin' / 'claude.exe'     # Anthropic's own installer
    appdata = os.environ.get('APPDATA')
    if appdata:
        yield Path(appdata) / 'npm' / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'bin' / 'claude.exe'
    on_path = shutil.which('claude')
    if on_path:
        if on_path.lower().endswith('.cmd'):                # an npm shim: the program it starts, when it is there
            yield Path(on_path).parent / 'node_modules' / '@anthropic-ai' / 'claude-code' / 'bin' / 'claude.exe'
        yield Path(on_path)
    if appdata:
        yield Path(appdata) / 'npm' / 'claude.cmd'


def _codex_places():
    local = os.environ.get('LOCALAPPDATA')
    if local:                                               # the Codex app's own copy, newest first
        yield from sorted(Path(local).glob('OpenAI/Codex/bin/*/codex.exe'), key=lambda p: p.stat().st_mtime,
                          reverse=True)
    on_path = shutil.which('codex')
    if on_path:
        yield Path(on_path)


PLACES = {'claude': _claude_places, 'codex': _codex_places}


def ai_home(engine, settings=None):
    """The folder letitedit keeps a connector AI in: its download and its private sign-in profile (settings "<id>_ai_home",
    a test's own folder; else LETITEDIT_AI_HOME or the letitedit\\ai folder in LOCALAPPDATA, then the AI's id)."""
    chosen = (settings or {}).get(f'{engine}_ai_home')
    if chosen:
        return Path(chosen)
    base = os.environ.get('LETITEDIT_AI_HOME') or Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'letitedit' / 'ai'
    return Path(base) / engine


def profile(engine, settings=None):
    """A connector AI's private profile: its sign-in lives here and nowhere else. settings "<id>_profile" overrides it for a test."""
    chosen = (settings or {}).get(f'{engine}_profile')
    return Path(chosen) if chosen else ai_home(engine, settings) / 'profile'


def _listed_program(engine, settings=None):
    program = AIS.get(engine, {}).get('program')
    return program.replace('{ai_home}', str(ai_home(engine, settings))) if program else None


def find(engine, settings=None):
    """Where the program is: the path the person's settings name when it still exists, else the usual places."""
    chosen = (settings or {}).get(engine)
    places = [Path(chosen)] if chosen else []
    places += list(PLACES[engine]()) if engine in PLACES else []
    listed = _listed_program(engine, settings)
    places += [Path(listed)] if listed else []
    return next((str(p) for p in places if p.is_file()), None)


def visible_only(engine):
    """True for an AI that runs only in a conversation on screen (it can't serve runs nobody watches)."""
    return engine in AIS and not AIS[engine].get('can', {}).get('background')


def tool_call_limit_s(engine):
    """The AI's own limit on one tool call, in seconds, or None. Whoever starts it passes it on (long_calls.LIMIT_VAR)."""
    return AIS.get(engine, {}).get('tool_call_limit_s')


def child_env(env=None):
    """A copy of the environment for a separate AI run: nothing tells it that it sits inside another session."""
    out = dict(os.environ if env is None else env)
    for name in SESSION_VARS:
        out.pop(name, None)
    return out


def claude_instruction_args(env=None):
    environment = os.environ if env is None else env
    home = Path(environment.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').resolve()
    settings = {'claudeMdExcludes': [home.as_posix() + '/**'], 'autoMemoryEnabled': False}
    return ['--settings', json.dumps(settings)]


# Claude Code's own tools in an editing session (ai_list.json "editing_tools"). The editor's newvideotools.h does the same.
EDITING_TOOLS_SWITCH = 'editing_builtins_off'            # settings.json; LETITEDIT_EDITING_BUILTINS_OFF (1 or 0) wins
EDITING_TOOLS_CACHE = 'claude-tools.json'                # beside the chat's history: what the probe saw
PROBE_MODEL = 'letitedit-probe-no-such-model'            # no model answers, so a probe uses no allowance


def editing_tools_on(env=None, settings_path=None):
    """Whether editing sessions start with Claude Code's unused built-in tools off. On by default since T365
    (settings.json editing_builtins_off: false turns it off)."""
    environment = os.environ if env is None else env
    forced = str(environment.get('LETITEDIT_EDITING_BUILTINS_OFF', '')).strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    path = Path(settings_path or environment.get('LETITEDIT_SETTINGS') or ROOT / 'settings.json')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig')).get(EDITING_TOOLS_SWITCH) is not False
    except (OSError, ValueError, AttributeError):
        return True


def _chat_folder(env=None):
    environment = os.environ if env is None else env
    own_settings = environment.get('LETITEDIT_CHAT_SETTINGS')
    return Path(own_settings).parent if own_settings else Path(environment.get('LOCALAPPDATA') or Path.home()) / 'letitedit/chat'


def _program_key(exe):
    info = Path(exe).stat()
    return {'exe': Path(exe).resolve().as_posix(), 'size': info.st_size, 'mtime': int(info.st_mtime)}


def offered_tools(env=None):
    """The built-in tools the last probe saw Claude Code offer, or None: no probe yet, or the program it probed has
    changed or gone since (an update can change them)."""
    try:
        seen = json.loads((_chat_folder(env) / EDITING_TOOLS_CACHE).read_text(encoding='utf-8-sig'))
        if {k: seen[k] for k in ('exe', 'size', 'mtime')} != _program_key(seen['exe']):
            return None
        return [str(t) for t in seen['tools']] if isinstance(seen['tools'], list) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def probe_editing_tools(exe=None, env=None, timeout=60, write=True):
    """Start Claude Code once, with no model behind it, and read the built-in tools its start-up line lists (its stream's
    `system`/`init` message, no letitedit tools). Writes claude-tools.json beside the chat's history for the editor.
    Returns the list, or None when it couldn't tell. Uses no allowance: the model named doesn't exist."""
    exe = exe or find('claude')
    if not exe:
        return None
    folder = _chat_folder(env)
    cmd = [exe, '-p', 'x', '--output-format', 'stream-json', '--verbose', '--no-session-persistence',
           '--strict-mcp-config', '--model', PROBE_MODEL]
    tools = None
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace', env=child_env(env),
                                cwd=str(folder) if folder.is_dir() else None)
    except OSError:
        return None
    def stop():                                       # the whole tree: an npm shim's program holds the pipe too
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
        proc.kill()

    timer = threading.Timer(timeout, stop)            # a program that never answers is stopped, not waited on
    timer.start()
    try:
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                message = None
            if isinstance(message, dict) and message.get('type') == 'system' and message.get('subtype') == 'init':
                tools = sorted(str(t) for t in message.get('tools') or [] if not str(t).startswith('mcp__'))
                break
    finally:
        timer.cancel()
        if proc.poll() is None:
            stop()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        proc.stdout.close()
    if tools is not None and write:
        record = dict(_program_key(exe), tools=tools, probed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / EDITING_TOOLS_CACHE
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(record, indent=1), encoding='utf-8')
        os.replace(temp, target)
    return tools


def editing_tool_names(offered=None):
    """The built-in tools an editing session turns off: the list's drop, every other offered tool not in keep, and
    the fallback shell only when Bash is offered (a Windows PC without Git Bash has PowerShell as its only shell)."""
    spec = AIS.get('claude', {}).get('editing_tools') or {}
    keep = set(spec.get('keep') or [])
    fallback = spec.get('shell_fallback')
    out = []
    for name in spec.get('drop') or []:
        if name and name not in keep and name != fallback and name not in out:
            out.append(name)
    out += sorted({t for t in offered or [] if t and t not in keep and t != fallback and t not in out
                   and not t.startswith('mcp__')})
    if fallback and offered is not None and 'Bash' in offered and fallback not in keep:
        out.append(fallback)
    return out


def editing_tool_args(offered=None, env=None, settings_path=None, use_cache=True):
    """Claude Code's argument for an editing session's built-in tools: [] when the switch is off, else one
    `--disallowedTools=<names>` (the = form can't take in the argument after it), from editing_tool_names with the
    probe's cached list unless `offered` is given."""
    if not editing_tools_on(env, settings_path):
        return []
    if offered is None and use_cache:
        offered = offered_tools(env)
    names = editing_tool_names(offered)
    flag = (AIS.get('claude', {}).get('editing_tools') or {}).get('flag') or '--disallowedTools'
    return [f"{flag}={','.join(names)}"] if names else []


def codex_model_metadata(env=None):
    environment = os.environ if env is None else env
    home = Path(environment.get('CODEX_HOME') or Path.home() / '.codex')
    own_settings = environment.get('LETITEDIT_CHAT_SETTINGS')
    folder = Path(own_settings).parent if own_settings else Path(environment.get('LOCALAPPDATA') or Path.home()) / 'letitedit/chat'
    try:
        snapshot = json.loads((folder / 'codex-models.json').read_text(encoding='utf-8-sig'))
        fetched = snapshot['fetched_at']
        newer = any(path.exists() and path.stat().st_mtime > fetched + 0.001 for path in (home / 'auth.json', home / 'models_cache.json'))
        if (os.path.normcase(snapshot['home']) == os.path.normcase(str(home.resolve()))
                and 0 <= time.time() - fetched < 300 and not newer and isinstance(snapshot['data'], list)):
            return snapshot['data']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        models = json.loads((home / 'models_cache.json').read_text(encoding='utf-8-sig'))['models']
        return models if isinstance(models, list) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def speed_choices(engine, model, env=None):
    entry = AIS.get(engine, {})
    rows = list(entry.get('speeds', []))
    if entry.get('speed_catalog') == 'codex_models_cache':
        match = next((row for row in codex_model_metadata(env) if isinstance(row, dict)
                      and row.get('slug', row.get('model', row.get('id'))) == model), {})
        seen = {'normal', 'default'}
        offers = match.get('service_tiers', match.get('serviceTiers', []))
        for offer in offers if isinstance(offers, list) else []:
            if not isinstance(offer, dict) or not all(isinstance(offer.get(key), str) and offer[key].strip()
                                                     for key in ('id', 'name', 'description')):
                continue
            if offer['id'] in seen:
                continue
            seen.add(offer['id'])
            costs = entry.get('speed_costs', {})
            rows.append({'value': offer['id'], 'label': offer['name'], 'models': [model],
                         'tip': offer['description'] + '. ' + costs.get(offer['name'].lower(), costs.get('other', ''))
                                + ' ' + entry.get('speed_tip', ''),
                         'pass': {'config': 'service_tier', 'value': offer['id']}})
    choices = []
    for row in rows:
        choice = dict(row)
        choice.update(row.get('model_overrides', {}).get(model, {}))
        value = choice['value']
        enabled = value == 'normal' or model in choice.get('models', [])
        choice['enabled'] = enabled
        if not enabled:
            choice['tip'] = f'{choice["label"]} is not offered for {model or "this model"}. Normal speed is used. ' + choice['tip']
        choices.append(choice)
    return choices


def selected_speed(engine, model, settings=None, env=None):
    settings = chat_settings() if settings is None else settings
    wanted = settings.get(AIS.get(engine, {}).get('speed_key', ''), 'normal')
    return next((row['value'] for row in speed_choices(engine, model, env)
                 if row['value'] == wanted and row['enabled']), 'normal')


def with_speed(args, engine, model, settings=None, normal=False, env=None):
    args = list(args)
    value = 'normal' if normal else selected_speed(engine, model, settings, env)
    row = next((row for row in speed_choices(engine, model, env) if row['value'] == value), None)
    if not row:
        return args
    passing = row['pass']
    if engine == 'claude':
        overrides = {}
        if '--settings' in args:
            position = args.index('--settings')
            overrides = json.loads(args[position + 1])
            del args[position:position + 2]
        overrides[passing['setting']] = passing['value']
        args += ['--settings', json.dumps(overrides)]
    elif engine == 'codex':
        args += ['-c', passing['config'] + '=' + json.dumps(passing['value'])]
        for key, setting in AIS[engine].get('speed_config', {}).items():
            args += ['-c', key + '=' + json.dumps(setting)]
    return args


def speed_refused(text):
    text = str(text or '')
    return bool(re.search(r'fast.?mode|service[ _-]?tier|priority.?tier|fast (?:speed|mode)|ultrafast', text, re.I)
                and re.search(r'not (?:available|supported|allowed|enabled|eligible)|unavailable|unsupported|ineligible|invalid|denied|disabled|requires|not included|extra usage|credits|overloaded|capacity', text, re.I))


def speed_fallback_line(engine):
    return f'{NAMES.get(engine, engine)} could not use the selected speed; continuing at Normal. Your saved choice is unchanged.'


def speed_notice(engine):
    line = speed_fallback_line(engine)
    print(line, file=sys.stderr)
    try:
        import letitedit.app.progress_feed as progress_feed
        progress_feed.note(line)
    except (ImportError, OSError, ValueError):
        pass
    return line


def run_with_speed(args, engine, model, settings=None, runner=None, **kwargs):
    settings = chat_settings() if settings is None else settings
    runner = subprocess.run if runner is None else runner
    environment = kwargs.get('env')
    run = runner(with_speed(args, engine, model, settings, env=environment), **kwargs)
    text = str(run.stdout or '') + str(run.stderr or '')
    if run.returncode and selected_speed(engine, model, settings, environment) != 'normal' and speed_refused(text):
        notice = speed_notice(engine)
        run = runner(with_speed(args, engine, model, settings, normal=True, env=environment), **kwargs)
        run.speed_notice = notice
    return run


def _claude_said(run):
    try:
        return bool(json.loads(run.stdout)['loggedIn'])
    except (ValueError, KeyError, TypeError):
        return None


def _codex_said(run):
    said = f'{run.stdout}\n{run.stderr}'.lower()
    return False if 'not logged in' in said else True if 'logged in' in said else None


SIGNED_IN_ANSWER = {'claude': _claude_said, 'codex': _codex_said}


def signed_in(engine, exe, timeout=20, settings=None):
    """`claude auth status` / `codex login status`: under a second, no model, no allowance. Only the answer is kept,
    never the account details it also prints. None: it couldn't tell, so a real try is what decides. That includes a
    person using their own API key, which these commands may not count as a sign-in. A connector AI has no such command, and
    starting one takes 15 s: whether its sign-in file exists in the private profile, by name only (never opened)."""
    names = AIS.get(engine, {}).get('signed_in_files')
    if names:
        return any((profile(engine, settings) / name).is_file() for name in names)
    if os.environ.get(API_KEY_VARS.get(engine, '')):
        return None
    try:
        run = subprocess.run([exe, *STATUS_ARGS[engine]], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                             env=child_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return SIGNED_IN_ANSWER[engine](run)


def failure_kind(text, api_error=None):
    """What a run that gave no answer printed: 'limit', 'signin', or None for anything else. api_error: the kind of
    API error the program named on its failed message (API_ERROR_KINDS), which wins over the text."""
    if str(api_error or '') in API_ERROR_KINDS:
        return API_ERROR_KINDS[str(api_error)]
    text = text or ''
    return 'limit' if LIMIT.search(text) else 'signin' if SIGNIN.search(text) else 'missing' if MISSING.search(text) else None


def limit_line(text):
    """The AI's own words about its limit, which usually say when it comes back."""
    for line in (text or '').splitlines():
        if LIMIT.search(line):
            return line.strip()[:200]
    return ''


def editor(settings=None):
    """The AI doing the editing: LETITEDIT_ACTOR, the app above this process, else the chat's choice; None if unknown."""
    who = os.environ.get('LETITEDIT_ACTOR')
    if who in ALL_AIS:
        return who
    try:
        import letitedit.timeline.project_journal as project_journal
        who = project_journal.client_actor()
    except Exception:  # noqa: BLE001 - only the order of the tries depends on it
        who = None
    if who in ALL_AIS:
        return who
    who = chat_settings().get('engine') if settings is None else settings.get('engine')
    return who if who in ALL_AIS else None


def critic_order(prefer=None, who=None):
    """The AIs to try for a review, in order: a named one first, else the person's selected AI, else Codex.
    The other always follows, so a name that isn't on this PC (an older skill's) just moves on."""
    if prefer in ENGINES:
        first = [prefer]
    elif who in ALL_AIS:
        first = [who] if who in ENGINES else []
    else:
        first = ['codex']
    return first + [e for e in ENGINES if e not in first]


def background_allowed(settings=None):
    """False when the person has turned off runs of their AI that nobody is watching (Connect Your AI; on by default), or when
    the only AI on this PC runs in a conversation on screen and nowhere else."""
    settings = chat_settings() if settings is None else settings
    if settings.get('background_jobs') is False:
        return False
    if any(find(e, settings) for e in ENGINES):
        return True
    return not any(find(e, settings) for e in ALL_AIS if visible_only(e))


def reviewer_line(review):
    """Who reviewed, or why nobody did, in one plain sentence; None when there's no such record (an older review.json
    or one a person wrote)."""
    review = review or {}
    if review.get('error'):
        return str(review['error']) if review.get('error_kind') else None
    name = NAMES.get(review.get('engine'))
    if not name:
        return None
    if review.get('same_vendor') is False:
        return f'Reviewed by {name}, a different AI from the one that edited it.'
    return (f'Reviewed by {name}, in a separate session that saw the video, the words, the brief and the plan, '
            "not the editor's reasoning.")
