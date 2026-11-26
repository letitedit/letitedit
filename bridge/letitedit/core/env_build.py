r"""letitedit's model environments (torch and the voice / music engines): built on first use with uv from pinned
package lists, the sizes shown before anything is downloaded.

    specs()                    -> {name: record} from envs.json (release\envs\make_envs.py made it on the build PC)
    form_for(name, tier=None)  -> 'cuda' | 'cpu' | None (None: this environment needs an NVIDIA GPU)
    plan(name, form=None)      -> {'name', 'form', 'ready', 'folder', 'python', 'packages', 'download_bytes',
                                   'download_text', 'installed_bytes', 'installed_text', 'disk_free_text', 'features'}
    build(name, form=None, progress=None) -> {'name', 'form', 'python', 'seconds', 'log'}; raises BuildError
    ensure(name, progress=None) -> the environment's python.exe; builds it when settings 'model_downloads' is 'auto'
                                   (the default), else raises EnvMissing whose text gives the sizes and the command
    dry_run(name, form=None)   -> what uv would install (nothing installed): {'ok', 'would_install', 'output'}

Where: <envs> = LETITEDIT_ENVS or <root>\envs; <root> = LETITEDIT_ROOT or the folder above this bridge folder.
Recipes: LETITEDIT_ENV_SPECS, else <root>\setup\envs\envs.json (installed copy), else <root>\release\envs\envs.json.
Form: 'cuda' on gpu8 / gpu4 PCs (hardware.py tier), 'cpu' elsewhere when the environment has a CPU form; settings.json
'env_form' ('auto' | 'cuda' | 'cpu') or LETITEDIT_ENV_FORM overrides. Python itself (the version in the recipe)
comes from uv's python-build-standalone into <root>\python. Packages are installed with --no-deps: exactly the set
the build PC has. A finished environment has letitedit-env.json in its folder; one being built has
.letitedit-building (a stopped build is redone from scratch). Log: <root>\cache\envs\<name>-build.log.
An environment that exists without either file (made by hand, like the build PC's own) counts as ready.

Command line:
    python env_build.py list
    python env_build.py plan|dry-run <name> [--form cuda|cpu]
    python env_build.py build <name> [--form cuda|cpu] [--yes]      shows the sizes and asks first unless --yes
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
from letitedit.core import vc_runtime  # noqa: E402  (Microsoft's C++ runtime, installed into Windows on a PC without it)
ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
ENVS_HOME = Path(os.environ.get('LETITEDIT_ENVS') or ROOT / 'envs')
SETTINGS = Path(os.environ.get('LETITEDIT_SETTINGS', ROOT / 'settings.json'))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DONE = 'letitedit-env.json'
BUILDING = '.letitedit-building'


class EnvMissing(RuntimeError):
    pass


class BuildError(RuntimeError):
    pass


def human(n):
    if n is None:
        return '?'
    for unit, k in (('GB', 1 << 30), ('MB', 1 << 20), ('KB', 1 << 10)):
        if n >= k:
            return f'{n / k:.1f} {unit}'
    return f'{n} bytes'


def spec_path():
    for p in (os.environ.get('LETITEDIT_ENV_SPECS'), ROOT / 'setup' / 'envs' / 'envs.json',
              ROOT / 'release' / 'envs' / 'envs.json'):
        if p and Path(p).is_file():
            return Path(p)
    raise FileNotFoundError('no environment recipes (setup\\envs\\envs.json)')


def specs():
    return json.loads(spec_path().read_text(encoding='utf-8-sig'))['envs']


def spec(name):
    s = specs()
    if name not in s:
        raise KeyError(f'unknown environment {name!r}; known: {", ".join(s)}')
    return s[name]


def folder(name):
    return ENVS_HOME / name


def python_path(name):
    return folder(name) / 'Scripts' / 'python.exe'


def is_ready(name):
    f = folder(name)
    return (f / 'Scripts' / 'python.exe').is_file() and not (f / BUILDING).exists()


def _settings():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _tier():
    try:
        if str(ROOT / 'bridge') not in sys.path and (ROOT / 'bridge' / 'hardware.py').is_file():
            sys.path.insert(0, str(ROOT / 'bridge'))
        import letitedit.core.hardware as hardware
        return hardware.check()['tier']
    except Exception:  # noqa: BLE001 - no reading: assume no GPU
        return 'cpu'


def form_for(name, tier=None):
    s = spec(name)
    forced = (os.environ.get('LETITEDIT_ENV_FORM') or str(_settings().get('env_form', 'auto'))).lower()
    have = s['variants']
    if forced in have:
        return forced
    tier = tier or _tier()
    if tier in ('gpu8', 'gpu4') and 'cuda' in have:
        return 'cuda'
    return 'cpu' if 'cpu' in have else None


def _free(p):
    p = Path(p)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def plan(name, form=None):
    s = spec(name)
    form = form or form_for(name)
    v = s['variants'].get(form) if form else None
    inst = (v or {}).get('installed_bytes') or (v or {}).get('installed_bytes_estimate')
    free = _free(ENVS_HOME)
    out = {'name': name, 'form': form, 'ready': is_ready(name), 'folder': str(folder(name)),
           'python': s['python'], 'packages': s['packages'], 'features': s['features'],
           'download_bytes': (v or {}).get('download_bytes'), 'download_text': human((v or {}).get('download_bytes')),
           'installed_bytes': inst, 'installed_text': human(inst),
           'installed_is_estimate': bool(v and not v.get('installed_bytes')),
           'disk_free_bytes': free, 'disk_free_text': human(free), 'optional': s.get('optional', False)}
    if v is None:
        out['note'] = f'{name} needs an NVIDIA GPU (forms: {", ".join(s["variants"])}); this PC has none big enough'
    return out


def describe(p):
    est = ' (estimate)' if p.get('installed_is_estimate') else ''
    return (f"the {p['name']} environment ({p['form']}, Python {p['python']}, {p['packages']} packages): "
            f"{p['download_text']} to download, about {p['installed_text']}{est} on disk; "
            f"{p['disk_free_text']} free")


def find_uv():
    for p in (os.environ.get('LETITEDIT_UV'), ROOT / 'setup' / 'uv' / 'uv.exe',
              ROOT / 'release' / 'installer' / 'tools' / 'uv' / 'uv.exe'):
        if p and Path(p).is_file():
            return str(p)
    w = shutil.which('uv')
    if w:
        return w
    raise BuildError('uv was not found (setup\\uv\\uv.exe); repair the installation')


def _uv_env():
    env = dict(os.environ)
    for k in ('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH', 'CONDA_PREFIX'):
        env.pop(k, None)
    env.update(UV_NO_CONFIG='1', UV_PYTHON_INSTALL_DIR=str(ROOT / 'python'), UV_PYTHON_BIN_DIR=str(ROOT / 'python' / 'bin'),
               UV_PYTHON_PREFERENCE='only-managed', UV_LINK_MODE='copy', UV_NO_PROGRESS='1', PYTHONUTF8='1',
               UV_CACHE_DIR=str(ROOT / 'cache' / 'uv'), UV_HTTP_TIMEOUT='300')
    return env


def _run(cmd, log, progress=None, ok=(0,)):
    with open(log, 'a', encoding='utf-8') as fh:
        fh.write('> ' + ' '.join(str(c) for c in cmd) + '\n')
        fh.flush()
        p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding='utf-8', errors='replace', env=_uv_env(), creationflags=NO_WINDOW)
        lines = []
        for line in p.stdout:
            fh.write(line)
            lines.append(line.rstrip())
            if progress and line.strip():
                progress(line.strip()[:160])
        code = p.wait()
        fh.write(f'(exit {code})\n')
    return code, lines


def _base_python(version, log, progress):
    """The exact python.exe of uv's managed CPython <version> in <root>\\python (installed when missing). uv's
    'cpython-3.12-...' minor-version junction is removed (only the link): some sandboxes refuse to follow junctions."""
    base = ROOT / 'python'

    def find():
        for d in sorted(base.glob(f'cpython-{version}-*')) if base.is_dir() else []:
            if d.is_dir() and not os.path.islink(d) and not _is_junction(d) and (d / 'python.exe').is_file():
                return d / 'python.exe'
        return None

    exe = find()
    if exe is None:
        if progress:
            progress(f'getting Python {version} (about 30 MB)')
        _run([find_uv(), 'python', 'install', version, '--no-bin', '--no-registry'], log, None)
        exe = find()
    for d in base.iterdir() if base.is_dir() else []:
        if _is_junction(d):
            try:
                os.rmdir(d)      # removes the junction itself, never its target
            except OSError:
                pass
    if exe is None:
        raise BuildError(f'Python {version} could not be installed (log: {log})')
    try:
        done = vc_runtime.ensure(str(ROOT), log=progress)
    except Exception as e:
        raise BuildError(f"Microsoft's C++ runtime, which this PC lacks, isn't installed: {e}")
    if done.get('needed'):
        with open(log, 'a', encoding='utf-8') as fh:
            fh.write(f"Microsoft's C++ runtime {done.get('installed')} installed into Windows (exit {done.get('exit')})\n")
    return exe


def _is_junction(p):
    try:
        return bool(os.lstat(p).st_file_attributes & 0x400) and p.is_dir()
    except (OSError, AttributeError):
        return False


def _lock(name):
    ENVS_HOME.mkdir(parents=True, exist_ok=True)
    lp = ENVS_HOME / f'.build-{name}.lock'
    try:
        if lp.exists() and time.time() - lp.stat().st_mtime > 6 * 3600:
            lp.unlink()
        fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lp
    except FileExistsError:
        raise BuildError(f'the {name} environment is being built by another process ({lp}); try again later')


def build(name, form=None, progress=None):
    """Build <envs>\\<name> from its recipe. A folder left by a stopped build is replaced; a finished or hand-made
    environment is never touched (remove it first)."""
    s = spec(name)
    form = form or form_for(name)
    if form not in s['variants']:
        raise BuildError(plan(name, form).get('note') or f'{name} has no {form} form')
    v = s['variants'][form]
    req = spec_path().parent / v['file']
    f = folder(name)
    if is_ready(name):
        return {'name': name, 'form': form, 'python': str(python_path(name)), 'seconds': 0, 'already': True}
    logs = ROOT / 'cache' / 'envs'
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f'{name}-build.log'
    lock = _lock(name)
    t0 = time.monotonic()
    try:
        log.write_text(f'letitedit environment {name} ({form}) {time.strftime("%Y-%m-%d %H:%M:%S")}\n', encoding='utf-8')
        if f.exists():
            if not (f / BUILDING).exists():
                raise BuildError(f'{f} exists but is not a letitedit build; nothing changed')
            shutil.rmtree(f)                       # what a stopped build of ours left
        base = _base_python(s['python'], log, progress)
        f.mkdir(parents=True)
        (f / BUILDING).write_text(time.strftime('%Y-%m-%d %H:%M:%S'), encoding='utf-8')
        if progress:
            progress(f'making the {name} environment')
        code, out = _run([base, '-I', '-m', 'venv', '--without-pip', f], log)
        cfg = f / 'pyvenv.cfg'
        if code != 0 or not cfg.is_file():
            raise BuildError(f'could not make the environment (log: {log})')
        lines = [('home = ' + str(base.parent)) if re.match(r'^home\s*=', l) else l
                 for l in cfg.read_text(encoding='utf-8').splitlines()]
        cfg.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if progress:
            progress(f'downloading and installing {s["packages"]} packages ({human(v.get("download_bytes"))})')
        cmd = [find_uv(), 'pip', 'install', '--python', python_path(name), '--no-deps', '-r', req]
        if v.get('index'):
            cmd += ['--extra-index-url', v['index'], '--index-strategy', 'unsafe-best-match']
        code, out = _run(cmd, log, progress)
        if code != 0:
            raise BuildError(f'installing the packages failed: {" | ".join(out[-3:])} (log: {log})')
        if progress:
            progress('checking the environment')
        chk = 'import importlib,sys\nfor m in sys.argv[1:]: importlib.import_module(m)\nprint("imports OK")'
        code, out = _run([python_path(name), '-I', '-c', chk] + list(s.get('check') or []), log)
        if code != 0:
            raise BuildError(f'the environment does not load: {" | ".join(out[-3:])} (log: {log})')
        info = {'name': name, 'form': form, 'python': s['python'], 'packages': s['packages'], 'recipe': v['file'],
                'index': v.get('index'), 'built': time.strftime('%Y-%m-%d %H:%M:%S'),
                'seconds': round(time.monotonic() - t0, 1)}
        (f / DONE).write_text(json.dumps(info, indent=1) + '\n', encoding='utf-8')
        (f / BUILDING).unlink()
        shutil.rmtree(ROOT / 'cache' / 'uv', ignore_errors=True)      # downloaded wheels (copied into the env)
        return {'name': name, 'form': form, 'python': str(python_path(name)), 'seconds': info['seconds'],
                'log': str(log)}
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _setting():
    return str(_settings().get('model_downloads', 'auto')).lower()


def ensure(name, progress=None):
    """python.exe of the environment; built now when missing and settings 'model_downloads' is 'auto' (default).
    'ask' and 'never' raise EnvMissing with the sizes and the command that builds it."""
    if is_ready(name):
        return python_path(name)
    p = plan(name)
    if p['form'] is None:
        raise EnvMissing(p['note'])
    if _setting() == 'auto':
        if progress:
            progress('first use: building ' + describe(p))
        build(name, p['form'], progress)
        return python_path(name)
    raise EnvMissing(f"{describe(p)[0].upper()}{describe(p)[1:]} is not on this PC yet. Build it from the setup "
                     f"window, or: python {Path(__file__).name} build {name}  (settings.json model_downloads "
                     f"'auto' builds it on first use).")


def remove(name):
    """Delete an environment this module built (one with letitedit-env.json or a stopped build)."""
    f = folder(name)
    if not f.exists():
        return {'name': name, 'removed': False, 'note': 'not there'}
    if not ((f / DONE).exists() or (f / BUILDING).exists()):
        return {'name': name, 'removed': False, 'note': 'not built by letitedit; left alone'}
    shutil.rmtree(f)
    return {'name': name, 'removed': True}


def dry_run(name, form=None, python=None):
    """uv's resolution of the recipe against the package indexes, nothing installed. python: an existing Python
    3.x to resolve for (default: the managed Python in <root>\\python, else any 'py -3.12')."""
    s = spec(name)
    form = form or form_for(name)
    v = s['variants'][form]
    req = spec_path().parent / v['file']
    import tempfile
    env = _uv_env()
    env.pop('UV_PYTHON_PREFERENCE')
    with tempfile.TemporaryDirectory(prefix='letitedit-dry-') as tmp:
        env['UV_CACHE_DIR'] = str(Path(tmp) / 'uv-cache')      # nothing left behind
        if not python:      # an empty throwaway venv of the recipe's Python (any copy uv finds, else it fetches one)
            subprocess.run([find_uv(), 'venv', '--python', s['python'], str(Path(tmp) / 'v')], capture_output=True,
                           env=env, creationflags=NO_WINDOW)
            python = str(Path(tmp) / 'v' / 'Scripts' / 'python.exe')
        cmd = [find_uv(), 'pip', 'install', '--dry-run', '--no-deps', '-r', str(req), '--python', python]
        if v.get('index'):
            cmd += ['--extra-index-url', v['index'], '--index-strategy', 'unsafe-best-match']
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
                           creationflags=NO_WINDOW)
    text = (r.stdout + r.stderr).strip()
    m = re.search(r'Would install (\d+) packages?', text)
    return {'name': name, 'form': form, 'ok': r.returncode == 0, 'would_install': int(m.group(1)) if m else None,
            'output': text[-4000:]}


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    yes = '--yes' in rest
    form = rest[rest.index('--form') + 1] if '--form' in rest else None
    names = [a for a in rest if not a.startswith('--') and a != form]
    if cmd == 'list':
        for n in specs():
            p = plan(n)
            print(f"{n:<14} {'ready' if p['ready'] else 'not built':<10} {str(p['form']):<5} "
                  f"download {p['download_text']:>9}  disk {p['installed_text']:>9}  {'; '.join(p['features'])}"[:200])
        return 0
    if cmd == 'plan':
        print(json.dumps([plan(n, form) for n in names], indent=1))
        return 0
    if cmd == 'dry-run':
        r = [dry_run(n, form) for n in names]
        print(json.dumps(r, indent=1))
        return 0 if all(x['ok'] for x in r) else 1
    if cmd == 'remove':
        print(json.dumps([remove(n) for n in names]))
        return 0
    if cmd == 'build':
        for n in names:
            p = plan(n, form)
            if p['ready']:
                print(f'{n}: already built')
                continue
            if p['form'] is None:
                print(p['note'])
                return 2
            print('To build: ' + describe(p))
            if not yes and input('Build now? Type yes: ').strip().lower() not in ('y', 'yes'):
                print('Nothing built.')
                return 1
            try:
                r = build(n, p['form'], lambda t: print('  ' + t, flush=True))
            except BuildError as ex:
                print(f'Not built: {ex}')
                return 2
            print(json.dumps(r))
        return 0
    print(f'unknown command {cmd!r}')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
