r"""letitedit first-run setup: the work behind the setup window (setup_wizard.py) and the uninstaller.

Nothing here signs in to anything. Registration only writes the local config files Claude Code and Codex read:
  Claude Code: one entry "letitedit" under mcpServers in <home>\.claude.json (CLAUDE_CONFIG_DIR\.claude.json when set)
  Codex:       [marketplaces.letitedit] (a local marketplace = <install>\codex) and [plugins."letitedit@letitedit"]
               enabled = true in <CODEX_HOME or home\.codex>\config.toml
With the tools come the editing skills: every letitedit* folder of <install>\skills is copied into the app's skills
folder (<CLAUDE_CONFIG_DIR or home\.claude>\skills, <CODEX_HOME or home\.codex>\skills), as skills\install.py and the
editor's Connect Your AI do.
Each file is copied to <file>.before-letitedit-<time> before it is changed, written in one step, and read back.
What was written is kept in <install>\setup\registrations.json so that unregister() (run by the uninstaller) removes
only letitedit's own entries - and only while they still point into this install.

    python -I letitedit_setup.py detect | hardware | unregister | cleanup [--working-files]
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

APP = Path(__file__).resolve().parent.parent
REG = APP / 'setup' / 'registrations.json'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
CODEX_MARKET = 'letitedit'
CODEX_PLUGIN = f'letitedit@{CODEX_MARKET}'
# The person's own settings, removed only when they ask at uninstall (caches, job records and the like always go: the
# installer's [UninstallDelete]). In the install folder, and the editor's folders in %LOCALAPPDATA%\letitedit.
WORKING = ('appdata',)
WORKING_LOCAL = ('chat', 'progress', 'sharing', 'ai')


def bridge():
    p = str(APP / 'bridge')
    if p not in sys.path:
        sys.path.insert(0, p)


def home():
    return Path(os.path.expanduser('~'))


def python_exe():
    return APP / 'env' / 'Scripts' / 'python.exe'


def stamp():
    return time.strftime('%Y%m%d-%H%M%S')


# ------------------------------------------------------------------ finding the apps

def claude_config():
    d = os.environ.get('CLAUDE_CONFIG_DIR')
    return (Path(d) if d else home()) / '.claude.json'


def codex_home():
    return Path(os.environ.get('CODEX_HOME') or home() / '.codex')


def _version(exe):
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80] if (r.stdout or r.stderr).strip() else None
    except (OSError, subprocess.SubprocessError):
        return None


def detect_claude():
    found = []
    w = shutil.which('claude')
    if w:
        found.append(w)
    for p in (home() / '.local' / 'bin' / 'claude.exe', Path(os.environ.get('APPDATA', '')) / 'npm' / 'claude.cmd'):
        if p.is_file() and str(p) not in found:
            found.append(str(p))
    cfg = claude_config()
    # a ~/.claude folder alone doesn't count: installing the skills can make one
    return {'name': 'Claude Code', 'found': bool(found) or cfg.exists(),
            'programs': found, 'config': str(cfg), 'config_exists': cfg.exists(),
            'registered': claude_registered(cfg)}


def detect_codex():
    found = []
    w = shutil.which('codex')
    if w:
        found.append(w)
    local = os.environ.get('LOCALAPPDATA', '')
    found += [p for p in glob.glob(os.path.join(local, 'OpenAI', 'Codex', 'bin', '*', 'codex.exe')) if p not in found]
    app = Path(local) / 'OpenAI' / 'Codex'
    cfg = codex_home() / 'config.toml'
    # a ~/.codex folder alone doesn't count: installing the skills can make one
    return {'name': 'Codex', 'found': bool(found) or app.is_dir() or cfg.exists(), 'programs': found,
            'config': str(cfg), 'config_exists': cfg.exists(), 'registered': codex_registered(cfg)}


# ------------------------------------------------------------------ Claude Code

def claude_entry(app=APP):
    return {'type': 'stdio', 'command': str(app / 'env' / 'Scripts' / 'python.exe'),
            'args': [str(app / 'bridge' / 'letitedit_mcp.py')], 'env': {'PYTHONUTF8': '1'}}


def claude_registered(cfg=None):
    cfg = Path(cfg or claude_config())
    try:
        e = json.loads(cfg.read_text(encoding='utf-8')).get('mcpServers', {}).get('letitedit')
    except (OSError, ValueError, AttributeError):
        return None
    if not e:
        return None
    return 'this install' if e == claude_entry() else 'another copy'


SKILLS = APP / 'skills'


def skills_dirs():
    r"""Where each app reads skills: <CLAUDE_CONFIG_DIR or home\.claude>\skills and <CODEX_HOME or home\.codex>\skills."""
    d = os.environ.get('CLAUDE_CONFIG_DIR')
    return {'claude': (Path(d) if d else home() / '.claude') / 'skills', 'codex': codex_home() / 'skills'}


def _skills_installer():
    import importlib.util
    spec = importlib.util.spec_from_file_location('letitedit_skills_install', SKILLS / 'install.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_skills(key):
    """Copy the editing skills into that app's skills folder ('claude' | 'codex'). Returns {'dir', 'names'}, or None
    when this install has no skills folder."""
    if not (SKILLS / 'install.py').is_file():
        return None
    target = skills_dirs()[key]
    return {'dir': str(target), 'names': _skills_installer().install([target])[str(target)]}


def remove_skills(rec):
    """Take out the skill folders install_skills() copied (named in rec); anything else there is left alone."""
    out = []
    for n in (rec or {}).get('names') or []:
        p = Path(rec['dir']) / n
        if n.startswith('letitedit') and p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            out.append(n)
    return out


def _write_atomic(path, text):
    tmp = path.with_name(path.name + f'.letitedit-{os.getpid()}.tmp')
    tmp.write_text(text, encoding='utf-8', newline='')
    os.replace(tmp, path)


def _backup(path):
    if not path.exists():
        return None
    b = path.with_name(f'{path.name}.before-letitedit-{stamp()}')
    shutil.copy2(path, b)
    return str(b)


def _reg():
    try:
        return json.loads(REG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_reg(r):
    REG.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(REG, json.dumps(r, indent=1) + '\n')


def register_claude(cfg=None):
    cfg = Path(cfg or claude_config())
    data = {}
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding='utf-8'))      # a broken file is not overwritten (raises)
    backup = _backup(cfg)
    servers = data.setdefault('mcpServers', {})
    previous = servers.get('letitedit')
    servers['letitedit'] = claude_entry()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(cfg, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    check = json.loads(cfg.read_text(encoding='utf-8'))['mcpServers']['letitedit']
    if check != claude_entry():
        raise RuntimeError(f'{cfg}: the entry did not read back as written')
    skills = install_skills('claude')
    r = _reg()
    old = r.get('claude') or {}
    r['claude'] = {'config': str(cfg), 'entry': 'mcpServers.letitedit', 'written': claude_entry(),
                   'previous': old.get('previous') if old.get('config') == str(cfg) else previous,
                   'backup': backup, 'skills': skills, 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
    _save_reg(r)
    return {'config': str(cfg), 'backup': backup, 'replaced': previous is not None and previous != claude_entry(),
            'skills': skills}


def unregister_claude():
    r = _reg()
    c = r.get('claude')
    if not c:
        return 'nothing registered'
    cfg = Path(c['config'])
    if not cfg.exists():
        r.pop('claude')
        _save_reg(r)
        return 'config file gone'
    data = json.loads(cfg.read_text(encoding='utf-8'))
    servers = data.get('mcpServers', {})
    cur = servers.get('letitedit')
    if cur and str(APP).lower() in json.dumps(cur).replace('\\\\', '\\').lower():
        _backup(cfg)
        if c.get('previous'):
            servers['letitedit'] = c['previous']
        else:
            servers.pop('letitedit')
        _write_atomic(cfg, json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        msg = 'removed' + (' (the earlier entry put back)' if c.get('previous') else '')
        if remove_skills(c.get('skills')):
            msg += ' (and its skills)'
    else:
        msg = 'left alone (the entry no longer points to this install)'
    r.pop('claude')
    _save_reg(r)
    return msg


# ------------------------------------------------------------------ Codex

def _toml_str(s):
    return "'" + s + "'" if "'" not in s else json.dumps(s)


def codex_tables(app=APP):
    return (f'[marketplaces.{CODEX_MARKET}]\nsource_type = "local"\nsource = {_toml_str(str(app / "codex"))}\n\n'
            f'[plugins."{CODEX_PLUGIN}"]\nenabled = true\n')


_HEAD = re.compile(r'^\s*\[\[?([^\]]+)\]\]?\s*(#.*)?$')


def _drop_tables(text, names):
    """The TOML text without the tables whose header is one of names (header line to the next header)."""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        m = _HEAD.match(line)
        if m:
            skip = m.group(1).strip() in names
        if not skip:
            out.append(line)
    return ''.join(out)


OUR_TABLES = (f'marketplaces.{CODEX_MARKET}', f'plugins."{CODEX_PLUGIN}"')


def codex_registered(cfg=None):
    cfg = Path(cfg or codex_home() / 'config.toml')
    if not cfg.exists() or tomllib is None:
        return None
    try:
        d = tomllib.loads(cfg.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    m = d.get('marketplaces', {}).get(CODEX_MARKET)
    if not m:
        return None
    on = d.get('plugins', {}).get(CODEX_PLUGIN, {}).get('enabled')
    same = Path(str(m.get('source', '')).replace('\\\\?\\', '')).resolve() == (APP / 'codex').resolve()
    return ('this install' if same else 'another copy') + ('' if on else ' (plugin off)')


def register_codex(cfg=None):
    cfg = Path(cfg or codex_home() / 'config.toml')
    text = cfg.read_text(encoding='utf-8') if cfg.exists() else ''
    if text and tomllib:
        tomllib.loads(text)                     # a broken file is not changed (raises)
    backup = _backup(cfg)
    had = any(_HEAD.match(l) and _HEAD.match(l).group(1).strip() in OUR_TABLES for l in text.splitlines())
    new = _drop_tables(text, OUR_TABLES).rstrip('\n')
    new = (new + '\n\n' if new else '') + codex_tables()
    if tomllib:
        d = tomllib.loads(new)
        if d['marketplaces'][CODEX_MARKET]['source'] != str(APP / 'codex') or not d['plugins'][CODEX_PLUGIN]['enabled']:
            raise RuntimeError('Codex config did not parse back as written')
    cfg.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(cfg, new)
    cache, how = install_codex_plugin(cfg.parent)
    skills = install_skills('codex')
    r = _reg()
    r['codex'] = {'config': str(cfg), 'tables': list(OUR_TABLES), 'backup': backup, 'plugin_cache': cache,
                  'installed_by': how, 'skills': skills, 'at': time.strftime('%Y-%m-%d %H:%M:%S')}
    _save_reg(r)
    return {'config': str(cfg), 'backup': backup, 'replaced': had, 'plugin_cache': cache, 'installed_by': how,
            'skills': skills}


def _plugin_version():
    p = APP / 'codex' / 'plugins' / 'letitedit' / '.codex-plugin' / 'plugin.json'
    return json.loads(p.read_text(encoding='utf-8-sig')).get('version', 'local')


def install_codex_plugin(home_dir):
    """Codex runs a plugin from its own cache (<CODEX_HOME>\\plugins\\cache\\<marketplace>\\<plugin>\\<version>):
    'codex plugin add letitedit@letitedit' puts it there (local copy, no sign-in); without a Codex command-line
    program the folder is copied the same way. Returns (cache folder, 'codex plugin add' | 'copied')."""
    cache = Path(home_dir) / 'plugins' / 'cache' / CODEX_MARKET / 'letitedit' / _plugin_version()
    exes = detect_codex()['programs']
    env = dict(os.environ, CODEX_HOME=str(home_dir))
    for exe in exes:
        try:
            r = subprocess.run([exe, 'plugin', 'add', CODEX_PLUGIN], capture_output=True, text=True, timeout=120,
                               env=env, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and cache.is_dir():
            return str(cache), 'codex plugin add'
    if cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(APP / 'codex' / 'plugins' / 'letitedit', cache)
    return str(cache), 'copied'


def unregister_codex():
    r = _reg()
    c = r.get('codex')
    if not c:
        return 'nothing registered'
    cfg = Path(c['config'])
    msg = 'config file gone'
    if cfg.exists():
        text = cfg.read_text(encoding='utf-8')
        state = codex_registered(cfg)
        if state and state.startswith('this install'):
            _backup(cfg)
            _write_atomic(cfg, _drop_tables(text, OUR_TABLES).rstrip('\n') + '\n')
            msg = 'removed'
            cache = c.get('plugin_cache')
            if cache and Path(cache).is_dir() and Path(cache).parent.parent.name == CODEX_MARKET:
                market_dir = Path(cache).parent.parent
                shutil.rmtree(market_dir, ignore_errors=True)    # <CODEX_HOME>\plugins\cache\letitedit
                msg += ' (and its plugin copy in Codex)'
            if remove_skills(c.get('skills')):
                msg += ' (and its skills)'
        else:
            msg = 'left alone (the entries no longer point to this install)'
    r.pop('codex')
    _save_reg(r)
    return msg


def unregister():
    return {'claude': unregister_claude(), 'codex': unregister_codex()}


# ------------------------------------------------------------------ settings and folders

def settings_path():
    return Path(os.environ.get('LETITEDIT_SETTINGS', APP / 'settings.json'))


def read_settings():
    p = settings_path()
    base = {}
    d = APP / 'setup' / 'default-settings.json'
    if d.exists():
        base = json.loads(d.read_text(encoding='utf-8-sig'))
    if p.exists():
        try:
            base.update(json.loads(p.read_text(encoding='utf-8-sig')))
        except ValueError:
            pass
    return base


def write_settings(values):
    s = read_settings()
    s.update({k: v for k, v in values.items() if v is not None})
    p = settings_path()
    if p.exists():
        _backup(p)
    _write_atomic(p, json.dumps(s, indent=2) + '\n')
    return str(p)


def set_audio_folders(music=None, sfx=None):
    """The music and sound-effects folders the tools' library search (letitedit_library) and the editor use."""
    bridge()
    import audio_library
    return audio_library.audio_settings(sfx_folder=sfx or None, music_folder=music or None)


def index_audio(kind, progress=None, page=100):
    """Measure every song's tempo and beats (music; cached by the tools) or list the sound effects (sfx)."""
    bridge()
    import core_tools
    offset, total, done, tempos = 0, None, 0, 0
    while total is None or offset < total:
        r = core_tools.library(kind, '', offset, page, beats=True)
        if not r.get('configured'):
            return {'kind': kind, 'configured': False}
        total = r.get('total', 0)
        items = r.get('items') or []
        done += len(items)
        tempos += sum(1 for it in items if it.get('bpm'))
        offset += page
        if progress:
            progress(kind, done, total)
        if not items:
            break
    return {'kind': kind, 'configured': True, 'files': done, 'with_tempo': tempos}


def hardware():
    bridge()
    import hardware as hw
    r = hw.check(refresh=True)
    fits = hw.better_speech_fits(r)
    return {'tier': r['tier'], 'lines': hw.text(r), 'features': r['features'], 'better_speech': fits,
            'speech_note': None if fits else speech_note(hw), 'slow_note': slow_note(hw, r)}


def slow_note(hw, r):
    """What this PC can't do quickly, in plain words (hardware.slow_here); None on a PC whose graphics card runs the
    local models."""
    try:
        lines = hw.slow_here(r)
    except Exception:  # noqa: BLE001 - a note never stops the setup
        return None
    return ("What this PC can't do quickly:\n" + '\n'.join('- ' + line for line in lines)) if lines else None


BETTER_SPEECH_ENV = 'whisper_gpu'
BETTER_SPEECH_MODEL = 'whisper-large-v3-turbo'


def better_speech_size():
    """What the better speech model takes, the environment and its model file together: (bytes to download, words)."""
    bridge()
    import env_build as eb
    import model_fetch as mf
    plan = eb.plan(BETTER_SPEECH_ENV)
    n = (0 if plan['ready'] else plan.get('download_bytes') or 0) + mf.status(BETTER_SPEECH_MODEL)['missing_bytes']
    return n, f'{n / 2**30:.1f} GB'


def speech_outcome(answers):
    """After the setup: what speech will be on a PC that can run the better model, in plain words (T76). None on any other PC."""
    bridge()
    import env_build as eb
    import hardware as hw
    import model_fetch as mf
    if not hw.better_speech_fits():
        return None
    built = eb.plan(BETTER_SPEECH_ENV)['ready']
    here = mf.status(BETTER_SPEECH_MODEL)['present'] or (Path.home() / '.cache' / 'whisper' / 'large-v3-turbo.pt').is_file()
    if built and here:
        return 'Speech: the better model is ready. It runs on your graphics card and understands any language.'
    if built:
        return "Speech: the better model's download didn't finish. letitedit tries again the first time it listens to a video."
    why = ("you left the better speech model unticked" if BETTER_SPEECH_ENV not in (answers.get('envs') or [])
           else "the better speech model couldn't be set up (see above)")
    try:
        import speech_language
        speech_language.up_front()      # they've been told now: not again
    except Exception:  # noqa: BLE001
        pass
    return (f"Speech on this PC will understand English only, because {why}. Speech in another language would come out wrong. "
            "letitedit will use its English model, a 1.4 GB download the first time it listens. Everything else works. "
            "To get the better model later, open letitedit setup again.")


def speech_note(hw):
    """T76: the plain line for someone whose Windows isn't in English, on a PC whose speech will be English only. Once."""
    try:
        import speech_language
        return speech_language.up_front() if hw.speech_engine() == 'cpu' else None
    except Exception:  # noqa: BLE001 - a note never stops the setup
        return None


def models_for(tier):
    bridge()
    import model_fetch as mf
    return [s for s in mf.listing() if tier in (s.get('tiers') or [])], mf


def envs_for(tier):
    """Model environments that run on this tier, with sizes (env_build.plan; form cuda / cpu by the tier)."""
    bridge()
    import env_build as eb
    return [eb.plan(n, eb.form_for(n, tier)) for n, s in eb.specs().items() if tier in (s.get('tiers') or [])]


# ------------------------------------------------------------------ uninstall clean-up

def cleanup(working_files=False):
    """Run by the uninstaller before it deletes its files: remove the downloaded models (only what model_fetch
    downloaded) and, when asked, the person's letitedit settings (WORKING, WORKING_LOCAL, settings.json, the chat's
    panel.json)."""
    out = {'unregister': unregister(), 'models_removed': [], 'working_removed': []}
    try:
        bridge()
        import model_fetch as mf
        rec = mf._record()
        for i in list(rec):
            out['models_removed'].append(mf.remove(i)['id'])
        rp = mf._record_path()
        if rp.exists() and not mf._record():
            rp.unlink()
        for top in (mf.MODELS_HOME, mf.VFX, mf.MAPS):      # folders the downloads left empty
            if Path(top).is_dir() and str(Path(top).resolve()).lower().startswith(str(APP).lower()):
                for d in sorted((p for p in Path(top).rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
                    try:
                        d.rmdir()
                    except OSError:
                        pass
    except Exception as ex:  # noqa: BLE001
        out['models_error'] = f'{type(ex).__name__}: {ex}'
    out['envs_removed'] = []
    try:                     # model environments env_build made (never one it did not make)
        bridge()
        import env_build as eb
        for n in eb.specs():
            if eb.remove(n).get('removed'):
                out['envs_removed'].append(n)
        for lock in Path(eb.ENVS_HOME).glob('.build-*.lock') if Path(eb.ENVS_HOME).is_dir() else []:
            lock.unlink()
        if Path(eb.ENVS_HOME).is_dir() and not any(Path(eb.ENVS_HOME).iterdir()):
            Path(eb.ENVS_HOME).rmdir()
    except Exception as ex:  # noqa: BLE001
        out['envs_error'] = f'{type(ex).__name__}: {ex}'
    if working_files:
        for d in WORKING:
            p = APP / d
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                out['working_removed'].append(d)
        local = Path(os.environ['LOCALAPPDATA']) / 'letitedit' if os.environ.get('LOCALAPPDATA') else None
        for d in WORKING_LOCAL if local else ():
            p = local / d
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                out['working_removed'].append(str(p))
        for f in ('settings.json', 'chat/panel.json'):     # the person's AI choices are written beside the shipped chat files
            p = APP / f
            if p.exists():
                p.unlink()
                out['working_removed'].append(f)
    return out


def main(argv):
    cmd = argv[0] if argv else 'detect'
    if cmd == 'detect':
        print(json.dumps({'claude': detect_claude(), 'codex': detect_codex()}, indent=1))
    elif cmd == 'hardware':
        print('\n'.join(hardware()['lines']))
    elif cmd == 'unregister':
        print(json.dumps(unregister()))
    elif cmd == 'cleanup':
        r = cleanup('--working-files' in argv)
        import tempfile
        Path(tempfile.gettempdir(), 'letitedit-uninstall.json').write_text(json.dumps(r, indent=1), encoding='utf-8')
        print(json.dumps(r))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
