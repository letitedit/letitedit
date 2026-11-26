"""Motion clips: animated titles, lower thirds, kinetic text, count-ups, charts, end cards... written as HTML/CSS/JS
and rendered frame by frame by the HyperFrames engine (Apache-2.0, run as a separate program) into a ProRes 4444
.mov with alpha that sits on an overlay track.

    blocks()                                 -> {name: meta}  our own blocks in C:\\LetItEdit\\motion\\blocks
    normalise(spec)                          -> spec with the block's defaults filled in
    preview(spec, width, height, fps, ...)   -> {'sheet', 'frames', ...} stills at chosen times (transparent on a
                                                checkerboard, or over a frame of footage)
    render(spec, width, height, fps, ...)    -> {'path', 'cached', 'alpha', 'sheet', ...}
    recipe/view/default_len/label/render_recipe   the {motion: spec} timeline item (made.GENERATED)

Spec: {block, params: {...}, duration, pack (style pack name; default the project's), format: mov | mp4 | png}.
block 'custom' runs the caller's own code instead: {block: 'custom', html, css, script} where script calls
M.block('custom', (stage, p, c) => { ...; return (t) => { ... } }) with the same runtime (motion\\runtime\\motion.js).

Rules for every composition (checked here): no GSAP (its licence is not GPL-compatible) and nothing loaded from the
network (no http/https URLs); fonts come from the bundled library, copied next to the page. HyperFrames telemetry,
update checks and skill installs are switched off for every run. Every output is named 'generated-motion-...',
carries the 'generated' metadata (gen_common) and a sidecar <file>.json with the spec.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import copy
import hashlib
import html as _html
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import letitedit.pictures.gen_common as gc

MOTION = Path(os.environ.get('LETITEDIT_MOTION', (_SAI_ROOT + '\\motion')))
BLOCKS = MOTION / 'blocks'
RUNTIME = MOTION / 'runtime' / 'motion.js'
CANVAS_RENDER = MOTION / 'runtime' / 'canvas-render.js'
PLUS = MOTION / 'runtime' / 'motion-plus.js'   # springs, curves, camera (3 Nov); loaded into every page, hashed only when used
DRAW = MOTION / 'runtime' / 'draw.js'          # scene drawing helpers (M.draw): in a page only when its script uses them
WORLD = MOTION / 'runtime' / 'world.js'         # pictures, a camera that never stops, the page check (M.world): as M.draw, in a page only when used
LOOKS = MOTION / 'runtime' / 'looks'           # drawing hands (M.look.<name>): each in a page, and in its hash, only when its script names it
SHADER_RUNTIME = MOTION / 'runtime' / 'shaders.js'
SHADERS = MOTION / 'runtime' / 'shaders'
# A saved code scene draws from the copy of all this in its own page (T93: saved_parts, saved_page), so changing these files can't orphan it.
# motion.js itself stays frozen for now (test_motion_runtime pins it): a change to it reaches new scenes only.
_PLUS_NAMES = re.compile(r"\bM\s*\.\s*(?:spring|springSettle|springEase|bezier|stagger|typed|camera|parallax|draw)\b"
                         r"|['\"](?:sineInOut|quartOut|quintOut|quartIn|quartInOut|circOut|smooth|backOutSoft|anticipate)['\"]"
                         r"|\.ease\s*\.\s*(?:sineInOut|quartOut|quintOut|quartIn|quartInOut|circOut|smooth|backOutSoft|anticipate)\b")
ENGINE = MOTION / 'engine' / 'node_modules' / 'hyperframes' / 'bin' / 'hyperframes.mjs'
CHROME_ROOT = MOTION / 'chrome'
CACHE = gc.CACHE / 'motion'
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
NO_WINDOW = gc.NO_WINDOW
WORKERS = 2                 # Chrome workers per render (each ~256 MB); the PC rule is one heavy job at a time
CANVAS_PAGES = 4            # pages drawing a canvas scene at once (the PC rule: 4 threads)
RENDER_TIMEOUT = 900
ENGINE_VERSION = 1          # bump to re-render every cached motion clip
MAX_LEN = 120.0
FORMATS = ('mov', 'mp4', 'png')

BANNED = [(re.compile(r'gsap|greensock|TweenMax|TweenLite|TimelineMax|ScrollTrigger', re.I),
           'GSAP is not allowed (its licence is not GPL-compatible): animate with the M runtime, CSS or WAAPI'),
          (re.compile(r'(?:https?:)?//(?!www\.w3\.org/)[a-z0-9.-]+\.[a-z]{2,}', re.I),
           'nothing may load from the network: use bundled fonts and local files only'),
          (re.compile(r'\b(fetch|XMLHttpRequest|WebSocket|importScripts|navigator\.sendBeacon)\b'),
           'network calls are not allowed in a motion clip'),
          (re.compile(r'\b(requestAnimationFrame|setInterval|setTimeout|Date\.now|performance\.now)\b'),
           'every frame must be a function of t alone: no timers, rAF or clock reads (use render(t))'),
          (re.compile(r'Math\.random'), 'use M.rand(seed) so every render is the same')]


# ------------------------------------------------------------------ engine
# The engine is HyperFrames on Node (motion\node\node.exe, shipped by the installer; else node on PATH). It draws
# with a Chromium browser in headless mode: the chrome-headless-shell build HyperFrames pins when it is in
# motion\chrome (this PC), else the Microsoft Edge or Google Chrome already on the PC (on Windows HyperFrames captures
# frames as screenshots, which every Chromium browser does), else LETITEDIT_MOTION_BROWSER names one.

NODE_MIN = (22, 12)         # hyperframes 0.8.214 needs Node 22+, its puppeteer-core 22.12+
BROWSER_ENV = 'LETITEDIT_MOTION_BROWSER'
BROWSER_MIN_MAJOR = 140     # older Edge/Chrome builds are not used (measured: the pinned 152 and Edge/Chrome 156)
_NODE_VERSIONS = {}


def _version_tuple(text):
    return tuple(int(x) for x in re.findall(r'\d+', text or '')[:3]) or (0,)


def node_exe():
    own = MOTION / 'node' / 'node.exe'
    found = str(own) if own.exists() else shutil.which('node')
    if not found:
        raise RuntimeError('Node.js is missing: motion clips need motion\\node\\node.exe (the installer puts it there) '
                           'or Node.js 22.12+ on PATH')
    if found not in _NODE_VERSIONS:
        try:
            p = subprocess.run([found, '--version'], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            _NODE_VERSIONS[found] = p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            _NODE_VERSIONS[found] = f'unknown ({e})'
    if _version_tuple(_NODE_VERSIONS[found].lstrip('v')) < NODE_MIN:
        raise RuntimeError(f'Node.js {_NODE_VERSIONS[found]} at {found} is too old for motion clips (22.12+ needed)')
    return found


def _app_path(exe):
    """A program's path from Windows' App Paths registry entries (the user's, then the PC's)."""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as k:
                value = winreg.QueryValue(k, None)
        except OSError:
            continue
        if value:
            return value.strip().strip('"')
    return None


def browser_version(path):
    """The version of an installed Edge/Chrome: its newest version-named folder beside the exe ('156.0.4314.50'),
    the shell's from its folder name; '' when unknown."""
    p = Path(path)
    m = re.search(r'(\d+\.\d+\.\d+\.\d+)', str(p.parent.parent.name if p.parent.name.endswith('-win64') else ''))
    if m:
        return m.group(1)
    try:
        names = [d.name for d in p.parent.iterdir() if d.is_dir() and re.fullmatch(r'\d+\.\d+\.\d+\.\d+', d.name)]
    except OSError:
        return ''
    return max(names, key=lambda n: tuple(int(x) for x in n.split('.')), default='')


def installed_browsers():
    """Chromium browsers on this PC motion clips can draw with, in the order they are used:
    [{'kind': shell | edge | chrome, 'path', 'version'}]. Edge/Chrome builds older than BROWSER_MIN_MAJOR are left out."""
    env = os.environ
    pf, pf86 = env.get('ProgramFiles', r'C:\Program Files'), env.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    local = env.get('LOCALAPPDATA', '')
    shell = sorted(CHROME_ROOT.glob('chrome-headless-shell/*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    cands = [('shell', str(shell[-1]) if shell else None),
             ('edge', _app_path('msedge.exe')),
             *[('edge', os.path.join(b, 'Microsoft', 'Edge', 'Application', 'msedge.exe')) for b in (pf86, pf, local) if b],
             ('chrome', _app_path('chrome.exe')),
             *[('chrome', os.path.join(b, 'Google', 'Chrome', 'Application', 'chrome.exe')) for b in (pf, pf86, local) if b]]
    out, seen = [], set()
    for kind, path in cands:
        if not path or os.path.normcase(path) in seen or not os.path.isfile(path):
            continue
        seen.add(os.path.normcase(path))
        version = browser_version(path)
        if kind != 'shell' and version and _version_tuple(version)[0] < BROWSER_MIN_MAJOR:
            continue
        out.append({'kind': kind, 'path': path, 'version': version})
    return out


# T71: Microsoft Edge starts a second copy of itself and the first exits with code 0 at once whenever the environment holds
# __COMPAT_LAYER (any value; Windows' compatibility layers set it, and so do some launchers). The engine then reads "the browser
# closed". Chrome ignores the variable. Every browser we start gets the variable removed and Edge the flag that stops the relaunch.
EDGE_NO_RELAUNCH = '--edge-skip-compat-layer-relaunch'


def clean_env(env=None):
    """A copy of the environment (os.environ unless given) without __COMPAT_LAYER."""
    return {k: v for k, v in (os.environ if env is None else env).items() if k.upper() != '__COMPAT_LAYER'}


_BROWSER_OK = {}     # path|size|mtime -> '' (works) or the reason it doesn't, for this process
_CHECK_FILE = CACHE / 'browser-check.json'
BROWSER_CHECK_S = 45


def _browser_key(path):
    try:
        st = os.stat(path)
        return f'{os.path.normcase(path)}|{st.st_size}|{int(st.st_mtime)}'
    except OSError:
        return os.path.normcase(str(path))


def check_browser(path, force=False):
    """Start the browser headless on its own temporary profile and take one picture. '' when it works, else a plain reason.
    A browser that works is remembered (by its file's size and date) so the next run doesn't ask again."""
    key = _browser_key(path)
    if not force and key in _BROWSER_OK:
        return _BROWSER_OK[key]
    if not force:
        try:
            if key in json.loads(_CHECK_FILE.read_text(encoding='utf-8-sig')):
                _BROWSER_OK[key] = ''
                return ''
        except (OSError, ValueError):
            pass
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp(prefix='letitedit-browser-check-'))
    shot = d / 'shot.png'
    reason = ''
    proc = None
    try:
        (d / 'p.html').write_text('<html><body style="margin:0;background:#c8653b"></body></html>', encoding='utf-8')
        cmd = [path, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', EDGE_NO_RELAUNCH,
               f'--user-data-dir={d / "profile"}', '--window-size=200,150', f'--screenshot={shot}', (d / 'p.html').as_uri()]
        proc = subprocess.Popen(cmd, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        t0 = time.monotonic()
        # a browser that relaunches itself exits at once and writes the picture a moment later, so wait for the picture
        while time.monotonic() - t0 < BROWSER_CHECK_S:
            if shot.is_file() and shot.stat().st_size > 100:
                break
            if proc.poll() is not None and time.monotonic() - t0 > 6:
                break
            time.sleep(0.2)
        if not (shot.is_file() and shot.stat().st_size > 100):
            reason = ('started and closed again without drawing' if proc.poll() is not None
                      else f'did not draw a picture in {BROWSER_CHECK_S} s')
    except OSError as e:
        reason = f'could not be started ({e})'
    finally:
        if proc is not None and proc.poll() is None:
            _kill_tree(proc)
        shutil.rmtree(d, ignore_errors=True)
    _BROWSER_OK[key] = reason
    if not reason:
        try:
            have = json.loads(_CHECK_FILE.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            have = {}
        have[key] = time.strftime('%Y-%m-%d %H:%M:%S')
        try:
            _CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CHECK_FILE.write_text(json.dumps(have, indent=1), encoding='utf-8')
        except OSError:
            pass
    return reason


_BROWSER_NAMES = {'shell': 'the bundled headless Chrome', 'edge': 'Microsoft Edge', 'chrome': 'Google Chrome'}


def browser_exe():
    """The browser motion clips draw with: LETITEDIT_MOTION_BROWSER (used as it is), else the first of installed_browsers()
    that really starts headless and draws a picture (check_browser, a second or two the first time)."""
    own = os.environ.get(BROWSER_ENV)
    if own:
        if not os.path.isfile(own):
            raise RuntimeError(f'{BROWSER_ENV} names a browser that is not there: {own}')
        return own
    found = installed_browsers()
    if not found:
        raise RuntimeError('no browser to draw motion clips with: they need Microsoft Edge or Google Chrome '
                           f'(version {BROWSER_MIN_MAJOR} or newer) on this PC')
    failed = []
    for b in found:
        why = check_browser(b['path'])
        if not why:
            return b['path']
        failed.append(f"{_BROWSER_NAMES.get(b['kind'], b['kind'])} {b['version']} {why}".replace('  ', ' '))
    raise RuntimeError('scenes and motion clips could not be drawn because no browser on this PC would draw: '
                       + '; '.join(failed) + '. The video can still be finished without them.')


chrome_exe = browser_exe    # the name before 30 Oct


def engine_env():
    env = clean_env()
    env.update({'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1', 'HYPERFRAMES_NO_UPDATE_CHECK': '1',
                'HYPERFRAMES_NO_AUTO_INSTALL': '1', 'HYPERFRAMES_SKIP_SKILLS': '1',
                'HYPERFRAMES_NO_PREVIEW_DISCOVERY': '1', 'HYPERFRAMES_BROWSER_PATH': browser_exe(),
                'HYPERFRAMES_FFMPEG_PATH': str(APP / 'ffmpeg.exe'), 'HYPERFRAMES_FFPROBE_PATH': str(APP / 'ffprobe.exe'),
                'HYPERFRAMES_EXTRACT_CACHE_DIR': str(CACHE / 'extract'), 'NO_COLOR': '1',
                # On Windows the engine takes a snapshot of every ancestor process when a render starts and cancels
                # ("render_cancelled_parent_exited") when any of them goes. Our exports are background jobs started
                # through WMI on purpose, so a short-lived ancestor (the WMI host) ended T63's export at 12 minutes.
                # The render is tied to the process that started it instead (see _engine).
                'HYPERFRAMES_RENDER_DETACHED': '1'})
    return env


def available():
    """None when motion clips can render, else the reason they cannot."""
    if not BLOCKS.is_dir() or not RUNTIME.exists():
        return f'motion clips are not installed ({MOTION} has no blocks or runtime)'
    if not ENGINE.exists():
        return f'the HyperFrames engine is not installed ({ENGINE} is missing)'
    try:
        node_exe()
        browser_exe()
    except RuntimeError as e:
        return str(e)
    return None


def status():
    """What motion clips render with on this PC: {'ready', 'reason', 'node', 'browser', 'browsers'}."""
    why = available()
    out = {'ready': why is None, 'reason': why, 'engine': str(ENGINE), 'browsers': installed_browsers()}
    for key, fn in (('node', node_exe), ('browser', browser_exe)):
        try:
            out[key] = fn()
        except RuntimeError:
            out[key] = None
    if out['node']:
        out['node_version'] = _NODE_VERSIONS.get(out['node'])
    return out


_TELEMETRY_OFF = []


def _telemetry_off(cwd):
    """HyperFrames' own config (<home>\\.hyperframes\\config.json) says telemetry is off too, written by the first run
    on a PC (the env vars already keep it off on every run)."""
    if _TELEMETRY_OFF:
        return
    try:
        if json.loads((Path.home() / '.hyperframes' / 'config.json').read_text(encoding='utf-8-sig')).get('telemetryEnabled') is False:
            _TELEMETRY_OFF.append(True)
            return
    except (OSError, ValueError):
        pass
    subprocess.run([node_exe(), str(ENGINE), 'telemetry', 'disable'], cwd=str(cwd), env=engine_env(), capture_output=True,
                   timeout=120, creationflags=NO_WINDOW)
    _TELEMETRY_OFF.append(True)


cancel_check = None         # a job sets this to a function that says "stop": the render and its browser are then killed


def _kill_on_close_job():
    """A Windows job object that kills everything in it when its last handle closes (our process ending, however it
    ends), or None. The engine and its browsers are put in one so a render never outlives the program that started it."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class _IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

        class _Ext(ctypes.Structure):
            _fields_ = [('Basic', _Basic), ('IO', _IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Ext()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        return job
    except Exception:  # noqa: BLE001 - without it the render runs as before, only not tied to this process
        return None


def _put_in_job(job, proc):
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        return bool(k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle))))
    except Exception:  # noqa: BLE001
        return False


def _kill_tree(proc):
    """The engine process, its browsers and everything they started."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
    proc.kill()


def _engine(args, cwd, timeout=RENDER_TIMEOUT, script=None):
    if args[:1] != ['telemetry'] and script is None:
        _telemetry_off(cwd)
    job = _kill_on_close_job()
    import letitedit.core.render_lock as render_lock
    # tied at birth to this process (it never runs untied), then also put in this render's own job, which is closed
    # when the render ends so nothing it started is left behind
    proc = render_lock.popen_tied([node_exe(), str(script or ENGINE), *args], cwd=str(cwd), env=engine_env(),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                                  encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if job:
        _put_in_job(job, proc)
    import threading
    out = {}

    def pump(name, stream):
        out[name] = stream.read()
    pumps = [threading.Thread(target=pump, args=(n, st), daemon=True) for n, st in (('o', proc.stdout), ('e', proc.stderr))]
    for t in pumps:
        t.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            if cancel_check is not None and cancel_check():
                _kill_tree(proc)
                import letitedit.core.render_lock as render_lock
                raise render_lock.Cancelled('Cancelled')
            if time.monotonic() - started > timeout:
                _kill_tree(proc)
                raise subprocess.TimeoutExpired(proc.args, timeout)
            time.sleep(0.25)
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
        for t in pumps:
            t.join(5)
        for stream in (proc.stdout, proc.stderr):
            with contextlib.suppress(Exception):
                stream.close()
        if job:       # the job's handle closes with this process; closing it now also ends anything left behind
            try:
                import ctypes
                ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(job))
            except Exception:  # noqa: BLE001
                pass
    stdout, stderr = out.get('o', ''), out.get('e', '')
    if proc.returncode != 0:
        tail = '\n'.join((stdout + '\n' + stderr).strip().splitlines()[-25:])
        raise RuntimeError(f'motion render failed ({" ".join(args[:2])}):\n{tail}')
    return stdout


def setup():
    """Switch HyperFrames telemetry off in its own config too (the env vars already keep it off) and report."""
    _engine(['telemetry', 'disable'], MOTION)
    return {'telemetry': _engine(['telemetry', 'status'], MOTION).strip().splitlines()[-1:], 'browser': browser_exe(),
            'node': node_exe()}


# ------------------------------------------------------------------ blocks

_HEADER = re.compile(r'/\*@block\s*(\{.*?\})\s*@\*/', re.S)


def blocks():
    """Our blocks: {name: {'title', 'about', 'duration', 'params', 'docs', 'path'}}."""
    out = {}
    for f in sorted(BLOCKS.glob('*.js')):
        m = _HEADER.search(f.read_text(encoding='utf-8-sig'))
        if not m:
            continue
        meta = json.loads(m.group(1))
        meta['path'] = str(f)
        out[f.stem] = meta
    return out


def blocks_text():
    lines = []
    for name, b in blocks().items():
        lines.append(f"{name} ({b['duration']} s): {b['about']}")
        lines.append('    params: ' + json.dumps(b['params'], ensure_ascii=False))
        for k, v in (b.get('docs') or {}).items():
            lines.append(f'    {k}: {v}')
    return '\n'.join(lines)


def check_code(*parts):
    """Raise ValueError if custom code breaks a composition rule."""
    text = '\n'.join(p for p in parts if p)
    for rx, why in BANNED:
        m = rx.search(text)
        if m:
            raise ValueError(f'custom motion code: {why} (found {m.group(0)!r})')


def normalise(spec, known=()):
    """known: drawing kits a saved scene carries in its own page, which may no longer be on this PC."""
    if isinstance(spec, str):
        spec = {'block': spec}
    s = copy.deepcopy(dict(spec))
    name = s.get('block') or ('custom' if s.get('script') else None)
    if not name:
        raise ValueError('a motion clip needs block (one of letitedit_motion(action="blocks")) or custom script')
    out = {'block': name}
    if name == 'custom':
        if not s.get('script'):
            raise ValueError("block 'custom' needs script: M.block('custom', (stage, p, c) => { ...; return (t) => {...} })")
        check_code(s.get('html'), s.get('css'), s.get('script'))
        _check_looks(s.get('script'), known)
        _check_shaders(s.get('script'), known)
        out.update({'html': s.get('html') or '', 'css': s.get('css') or '', 'script': s['script'],
                    'params': dict(s.get('params') or {})})
        out['duration'] = float(s.get('duration') or 4.0)
    elif not BLOCKS.is_dir():
        # motion clips are not installed here: the spec is kept as given and drawn as a graphic (render_fallback)
        out['params'] = dict(s.get('params') or {})
        out['duration'] = float(s.get('duration') or 4.0)
    else:
        bl = blocks()
        if name not in bl:
            raise ValueError(f'unknown motion block {name!r}; blocks: {", ".join(sorted(bl))}, custom')
        meta = bl[name]
        unknown = sorted(set(s.get('params') or {}) - set(meta['params']))
        if unknown:
            raise ValueError(f'{name}: unknown params {unknown}; it takes {sorted(meta["params"])}')
        out['params'] = dict(meta['params'], **(s.get('params') or {}))
        out['duration'] = float(s.get('duration') or meta['duration'])
    if name == 'kinetic_type':
        from letitedit.looks.kinetic_type import glyph_blend
        glyph_blend(out['params'])
        if out['params'].get('phrases'):
            from letitedit.looks.kinetic_type import compile_phrases
            params = out['params']
            if not isinstance(params['phrases'], list) or any(not isinstance(phrase, dict) or not isinstance(phrase.get('words'), list) or not phrase['words'] or any(not isinstance(word, dict) for word in phrase['words']) for phrase in params['phrases']):
                raise ValueError('kinetic_type phrases need objects with timed words')
            expanded = [dict(word, end=phrase.get('end', max(item.get('end', 0) for item in phrase['words']))) for phrase in params['phrases'] for word in phrase['words']]
            _check_kinetic_type(dict(params, words=expanded), out['duration'])
            params['words'] = compile_phrases(params)
            params['phrases'] = []
        _check_kinetic_type(out['params'], out['duration'])
    if not 0.2 <= out['duration'] <= MAX_LEN:
        raise ValueError(f'duration must be 0.2-{MAX_LEN:g} s')
    if s.get('look'):
        out['look'] = str(s['look'])
    elif s.get('pack'):
        from letitedit.looks import look_library
        out['look'] = look_library.project_identity({'style': s['pack']}) or 'neutral'
    if s.get('kit'):
        out['kit'] = s['kit']
    fmt = s.get('format') or 'mov'
    if fmt not in FORMATS:
        raise ValueError(f'format must be one of {FORMATS}')
    out['format'] = fmt
    return out


def _check_kinetic_type(params, duration):
    import letitedit.catalogs.fonts as fonts
    words = params.get('words')
    roles = params.get('roles') or {}
    if not isinstance(words, list) or not isinstance(roles, dict):
        raise ValueError('kinetic_type needs a words list and roles object')
    if any(not isinstance(settings, dict) for settings in roles.values()):
        raise ValueError('kinetic_type role defaults must be objects')
    offset = params.get('offset', 0)
    if type(offset) not in (int, float) or not math.isfinite(offset):
        raise ValueError('kinetic_type offset must be finite')
    for word in words:
        if not isinstance(word, dict) or not isinstance(roles.get(word.get('role'), {}), dict):
            raise ValueError('kinetic_type words and role defaults must be objects')
        settings = {**roles.get(word.get('role'), {}), **word}
        if not isinstance(settings.get('text'), str) or not settings['text'].strip():
            raise ValueError('kinetic_type word needs nonempty text')
        for key in ('start', 'end'):
            if type(settings.get(key)) not in (int, float) or not math.isfinite(settings[key]):
                raise ValueError(f'kinetic_type {key} must be finite')
        if settings['end'] <= settings['start'] or not 0 <= settings['start'] - offset < duration:
            raise ValueError('kinetic_type word needs a positive span starting inside the clip')
        for key in ('x', 'y', 'size', 'spacing', 'line_height', 'entry', 'exit', 'from_scale', 'from_x', 'from_y', 'outline', 'stagger'):
            if key in settings and (type(settings[key]) not in (int, float) or not math.isfinite(settings[key])):
                raise ValueError(f'kinetic_type {key} must be finite')
        if any(settings.get(key, 0) < 0 for key in ('entry', 'exit', 'outline', 'stagger')) or settings.get('size', 0.05) <= 0:
            raise ValueError('kinetic_type size must be positive; timing and outline nonnegative')
        if settings.get('from_scale', 1) <= 0 or settings.get('line_height', 1.1) <= 0:
            raise ValueError('kinetic_type scale and line height must be positive')
        if 'fade_in' in settings and type(settings['fade_in']) is not bool:
            raise ValueError('kinetic_type fade_in must be boolean')
        for key, values in {'align': ('left', 'center', 'right'), 'reveal': ('none', 'wipe', 'highlight', 'crossfade', 'letters', 'runs'),
                            'ease': ('linear', 'out', 'backOut')}.items():
            if key in settings and settings[key] not in values:
                raise ValueError(f'kinetic_type {key} must be one of {values}')
        runs = settings.get('runs', [])
        if not isinstance(runs, list) or any(not isinstance(run, dict) or not isinstance(run.get('text'), str) or not run['text'] for run in runs):
            raise ValueError('kinetic_type runs need nonempty text')
        if runs and ''.join(run['text'] for run in runs) != settings['text']:
            raise ValueError('kinetic_type runs must reproduce the word exactly')
        if settings.get('reveal') == 'runs':
            starts = [run.get('start') for run in runs]
            if not starts or any(type(start) not in (int, float) or not math.isfinite(start) or not settings['start'] <= start < settings['end'] for start in starts):
                raise ValueError('kinetic_type timed runs need starts inside the word hold')
            if starts != sorted(starts):
                raise ValueError('kinetic_type timed runs must be in onset order')
            if starts[-1] + settings.get('entry', 0.15) > settings['end']:
                raise ValueError('kinetic_type run reveal does not fit the word hold')
        if settings.get('reveal') == 'letters' and (len(settings['text']) - 1) * settings.get('stagger', 0.018) + settings.get('entry', 0.15) > settings['end'] - settings['start']:
            raise ValueError('kinetic_type letter reveal does not fit the word hold')
        for item in [settings, *runs]:
            font = item.get('font') or settings.get('font') or params.get('font') or {'family': 'Inter Tight', 'weight': 800}
            if not isinstance(font, dict) or not font.get('family'):
                raise ValueError('kinetic_type font needs bundled family and weight')
            path, _, _ = fonts.font_file(font['family'], font.get('weight', 400))
            if not Path(path).resolve().is_relative_to(fonts.LIB.resolve()):
                raise ValueError('kinetic_type uses bundled fonts only')


def kit_of(s):
    """The colours and fonts a spec draws with: its stored kit, else its pack's, else the neutral defaults."""
    if s.get('kit'):
        return {'colors': dict(s['kit'].get('colors') or {}), 'fonts': dict(s['kit'].get('fonts') or {})}
    import letitedit.looks.look_library as look_library
    k = look_library.kit(s.get('look'))
    return {'colors': dict(k['colors']), 'fonts': {n: k.font(n) for n in k['fonts']}}


def kit_snapshot(kit):
    """A project's resolved Kit -> the {colors, fonts} a recipe stores."""
    return {'colors': dict(kit['colors']), 'fonts': {n: kit.font(n) for n in kit['fonts']}}


def uses_draw(s):
    """True when the script reaches for the scene drawing helpers (M.draw), which then ride along in the page."""
    return bool(s.get('script')) and bool(re.search(r'\bM\s*\.\s*draw\b', s['script']))


def uses_world(s):
    return bool(s.get('script')) and bool(re.search(r'\bM\s*\.\s*world\b', s['script']))


def uses_plus(s):
    """True when the script uses something motion-plus.js added (springs, new curves, the camera, M.draw)."""
    return bool(s.get('script')) and bool(_PLUS_NAMES.search(s['script']))


_LOOK_USE = re.compile(r"\bM\s*\.\s*look\b(\s*\.\s*([A-Za-z_]\w*))?")


def hands():
    """The drawing hands on this PC: names under motion\\runtime\\looks with a built .js."""
    return sorted(p.stem for p in LOOKS.glob('*.js')) if LOOKS.is_dir() else []


def looks_used(s):
    """The hands a script names (M.look.paperCraft); only those ride along in the page and join its hash."""
    if not s.get('script'):
        return []
    return sorted({m.group(2) for m in _LOOK_USE.finditer(s['script']) if m.group(2)})


def _check_looks(script, known=()):
    """A hand is found by its name in the script's text, so any other way of reaching one could never load."""
    have = sorted(set(hands()) | set(known))
    for m in _LOOK_USE.finditer(script or ''):
        if not m.group(2):
            raise ValueError(f"custom motion code: write a drawing kit's name out as M.look.<name> so it can be loaded (have: {', '.join(have) or 'none'})")
        if m.group(2) not in have:
            raise ValueError(f"custom motion code: no drawing kit called {m.group(2)!r} (have: {', '.join(have) or 'none'})")


def _part(saved, key, file):
    """A piece of a page: the copy a saved scene carries, else this PC's file."""
    return (saved or {}).get(key) or file.read_text(encoding='utf-8')


_SHADER_USE = re.compile(r"\bM\s*\.\s*shader\b(\s*\.\s*([A-Za-z_]\w*))?")


def shaders():
    return sorted(path.name[:-10] for path in SHADERS.glob('*.shader.js')) if SHADERS.is_dir() else []


def shaders_used(spec):
    return sorted({match.group(2) for match in _SHADER_USE.finditer(spec.get('script') or '')
                   if match.group(2) and match.group(2) != 'last'})


def uses_shaders(spec):
    return bool(_SHADER_USE.search(spec.get('script') or ''))


def saved_names(saved):
    return list((saved or {}).get('looks') or ()) + ['shader:' + name for name in (saved or {}).get('shaders') or ()]


def _check_shaders(script, known=()):
    have = set(shaders()) | {name[7:] for name in known if name.startswith('shader:')}
    for match in _SHADER_USE.finditer(script or ''):
        name = match.group(2)
        if not name:
            raise ValueError('custom motion code: write a shader name out as M.shader.<name> so it can be loaded')
        if name != 'last' and name not in have:
            raise ValueError(f'custom motion code: no shader called {name!r} (have: {", ".join(sorted(have))})')


def _shader_text(saved, name):
    return ((saved or {}).get('shaders') or {}).get(name) or (SHADERS / f'{name}.shader.js').read_text(encoding='utf-8')


def _hand_text(saved, name):
    return ((saved or {}).get('looks') or {}).get(name) or (LOOKS / f'{name}.js').read_text(encoding='utf-8')


def digest(s, width, height, fps, saved=None):
    """saved: saved_parts() of a scene's page, which then stand in for this PC's files."""
    s2 = dict(s, kit=(saved or {}).get('kit') or kit_of(s))
    s2.pop('look', None)
    src = '' if s['block'] == 'custom' else Path(blocks()[s['block']]['path']).read_text(encoding='utf-8')
    parts = {'s': s2, 'w': width, 'h': height, 'fps': round(float(fps), 4), 'v': ENGINE_VERSION,
             'src': src, 'rt': _part(saved, 'rt', RUNTIME)}
    if uses_plus(s):          # only then, so a spec that uses none of the additions keeps the digest it always had
        parts['plus'] = _part(saved, 'plus', PLUS)
    if uses_draw(s):
        parts['draw'] = _part(saved, 'draw', DRAW)
    if uses_world(s):
        parts['world'] = _part(saved, 'world', WORLD)
    used = looks_used(s)
    if used:                  # the same promise: a scene that names no hand keeps the digest it always had
        parts['looks'] = {n: _hand_text(saved, n) for n in used}
    if uses_shaders(s):
        parts['shader_runtime'] = _part(saved, 'shader_runtime', SHADER_RUNTIME)
        parts['shaders'] = {name: _shader_text(saved, name) for name in shaders_used(s)}
    key = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:14]


def describe(s):
    p = s.get('params') or {}
    words = next((str(p[k]) for k in ('title', 'name', 'text', 'place', 'label') if p.get(k)), '')
    return f"{s['block']}{': ' + words[:50] if words else ''}"


# ------------------------------------------------------------------ the page

def _font_refs(s, kit):
    """Every font family the page may use: the kit's fonts and any family named in the params."""
    fams = {}
    for f in kit['fonts'].values():
        fams.setdefault(f['family'], set()).add(int(f.get('weight') or 400))
    for k, v in (s.get('params') or {}).items():
        if k.endswith('font') and isinstance(v, str) and v not in kit['fonts']:
            fams.setdefault(v, set()).add(700)
        if k.endswith('font') and isinstance(v, dict) and v.get('family'):
            fams.setdefault(v['family'], set()).add(int(v.get('weight') or 400))
    if s.get('block') == 'kinetic_type':
        params = s.get('params') or {}
        for item in [*(params.get('roles') or {}).values(), *(params.get('words') or [])]:
            for run in [item, *(item.get('runs') or [])]:
                font = run.get('font') or item.get('font') or params.get('font') or {}
                if isinstance(font, dict) and font.get('family'):
                    fams.setdefault(font['family'], set()).add(int(font.get('weight') or 400))
    return fams


def _font_faces(fams, work):
    """Copy the font files next to the page; return the @font-face CSS and the families not found."""
    import letitedit.catalogs.fonts as fonts
    css, missing, done = [], [], set()
    (work / 'fonts').mkdir(parents=True, exist_ok=True)
    for fam, weights in fams.items():
        for w in sorted(weights) + [400, 700]:
            for italic in (False,):
                try:
                    path, _idx, var = fonts.font_file(fam, w, italic)
                except KeyError:
                    missing.append(fam)
                    break
                if (path, italic) in done:
                    continue
                done.add((path, italic))
                name = f"f{len(done)}{Path(path).suffix.lower()}"
                shutil.copyfile(path, work / 'fonts' / name)
                row = next((f for f in fonts.family(fam)['faces'] if f['path'] == path), {})
                ax = (row.get('axes') or {}).get('wght')
                weight = f'{int(ax[0])} {int(ax[2])}' if ax else str(row.get('weight') or w)
                css.append(f'@font-face{{font-family:"{fam}";src:url("fonts/{name}");font-weight:{weight};'
                           f'font-style:{"italic" if italic else "normal"};font-display:block}}')
    return '\n'.join(css), sorted(set(missing))


_LOCAL_PICTURE = re.compile(r"file:///[^'\"\s)`<>]+?\.(?:png|jpe?g|webp|gif|svg)", re.I)


def _local_pictures(page, work, earlier=None):
    """The page's file:// pictures (letitedit_image's `url`), copied beside it under pictures/ and named relatively. The
    export's renderer serves the page and refuses file:// addresses, which a page opened from disk allows; a relative one
    works in all of them. A page with none is unchanged."""
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    def local(found):
        source = Path(url2pathname(urlparse(found.group(0)).path))
        name = hashlib.sha256(str(source).lower().encode()).hexdigest()[:10] + '-' + re.sub(r'[^\w.-]+', '-', source.name)
        if not source.is_file():                       # moved to another PC: the copy the scene's earlier page kept
            source = Path(earlier or '.') / 'pictures' / name
            if not (earlier and source.is_file()):
                return found.group(0)
        (work / 'pictures').mkdir(exist_ok=True)
        if not (work / 'pictures' / name).exists():
            shutil.copyfile(source, work / 'pictures' / name)
        return 'pictures/' + name
    return _LOCAL_PICTURE.sub(local, page)


def build_page(s, width, height, fps, work, saved=None, earlier=None):
    """saved: saved_parts() of the page this one follows, used instead of this PC's files. earlier: that page's folder."""
    if s['block'] == 'kinetic_type' and any('layout_bounds' in word for word in s['params']['words']):
        canvas = s['params'].get('layout', {}).get('canvas', [1080, 1920])
        if abs(width / height - canvas[0] / canvas[1]) > 0.001:
            raise ValueError('kinetic_type layout canvas aspect must match the render; recompile for the new canvas')
    work = Path(work)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    kit = (saved or {}).get('kit') or kit_of(s)
    face_css, missing = _font_faces(_font_refs(s, kit), work)
    block_js = s['script'] if s['block'] == 'custom' else Path(blocks()[s['block']]['path']).read_text(encoding='utf-8')
    spec_js = json.dumps({'block': s['block'], 'params': s.get('params') or {}, 'kit': kit, 'w': width, 'h': height,
                          'len': s['duration'], 'fps': float(fps)}, ensure_ascii=False)
    safe = lambda js: js.replace('</script', '<\\/script')   # noqa: E731
    shader_js = (['<script>' + safe(_part(saved, 'shader_runtime', SHADER_RUNTIME)) + '</script>']
                 + ['<script>' + safe(_shader_text(saved, name)) + '</script>' for name in shaders_used(s)]) if uses_shaders(s) else []
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>letitedit motion: {_html.escape(describe(s))}</title>
<style>
{face_css}
html, body {{ margin: 0; padding: 0; background: transparent; }}
#root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
#stage {{ position: absolute; inset: 0; overflow: hidden; }}
#stage * {{ box-sizing: border-box; }}
{s.get('css') or ''}
</style></head>
<body>
<div id="root" data-composition-id="root" data-width="{width}" data-height="{height}" data-start="0"
     data-duration="{s['duration']:.4f}"><div id="stage">{s.get('html') or ''}</div></div>
<script>window.LIM_SPEC = {safe(spec_js)};</script>
<script>{safe(_part(saved, 'rt', RUNTIME))}</script>
<script>{safe(_part(saved, 'plus', PLUS))}</script>
{('<script>' + safe(_part(saved, 'draw', DRAW)) + '</script>') if uses_draw(s) else ''}{('<script>' + safe(_part(saved, 'world', WORLD)) + '</script>') if uses_world(s) else ''}{''.join('<script>' + safe(_hand_text(saved, n)) + '</script>' for n in looks_used(s))}{''.join(shader_js)}<script>{safe(block_js)}</script>
<script>M.start();</script>
</body></html>
"""
    (work / 'index.html').write_text(_local_pictures(page, work, earlier), encoding='utf-8')
    return {'page': str(work / 'index.html'), 'missing_fonts': missing}


# ------------------------------------------------------------------ a saved scene's own page (T93)

_MASK_SCRIPT = re.compile(r'<!-- letitedit-upper-mask-start -->.*?<!-- letitedit-upper-mask-end -->\n?', re.S)
_PAGE_SIZE = re.compile(r', "w": \d+, "h": \d+, "len": ([^,]+), "fps": [^}]+\}')


def _page_text(page):
    return _MASK_SCRIPT.sub('', (Path(page) / 'index.html').read_text(encoding='utf-8'))


def saved_parts(page, s):
    """What a page built by build_page carries: {'rt', 'plus', 'draw', 'world', 'looks': {name: text}, 'kit'}. Only the pieces
    it has. None when there is no such page, or it is not laid out as build_page writes it."""
    try:
        html = _page_text(page)
    except OSError:
        return None
    first, last = html.find('<script>window.LIM_SPEC = '), html.rfind('<script>M.start();</script>')
    if first < 0 or last < first:
        return None
    scripts = [x.replace('<\\/script', '</script') for x in re.findall(r'<script>(.*?)</script>', html[first:last], re.S)]
    named = looks_used(s)
    extras = ['draw'] * uses_draw(s) + ['world'] * uses_world(s)
    middle = scripts[2:-1]
    shader_names = shaders_used(s)
    tail = len(extras) + len(named) + (1 + len(shader_names) if uses_shaders(s) else 0)
    if len(scripts) < 3 or len(middle) not in (tail, tail + 1):     # the runtime, then the additions (pages since 3 Nov), then what the scene names
        return None
    try:
        kit = json.loads(scripts[0].split('=', 1)[1].strip().rstrip(';')).get('kit')
    except ValueError:
        return None
    parts = {'rt': scripts[1], 'kit': kit}
    if len(middle) == tail + 1:
        parts['plus'] = middle[0]
    rest = middle[len(middle) - tail:]
    parts.update(zip(extras, rest))
    parts['looks'] = dict(zip(named, rest[len(extras):len(extras) + len(named)]))
    if uses_shaders(s):
        offset = len(extras) + len(named)
        parts['shader_runtime'] = rest[offset]
        parts['shaders'] = dict(zip(shader_names, rest[offset + 1:]))
    return parts


def saved_page(page, width, height, work, fps=None):
    """A working copy of a saved page, ready to draw, without the live player's masks: the same text, with only its size and
    frame rate set. Nothing here reads this PC's runtime, kits or fonts."""
    page, work = Path(page), Path(work)
    html = _page_text(page)
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    for sub in ('fonts', 'pictures'):
        if (page / sub).is_dir():
            shutil.copytree(page / sub, work / sub)
    was = re.search(r'data-width="(\d+)" data-height="(\d+)"', html)
    if was and (int(was[1]), int(was[2])) != (int(width), int(height)):
        html = html.replace(f'width: {was[1]}px; height: {was[2]}px;', f'width: {int(width)}px; height: {int(height)}px;', 1)
        html = html.replace(was[0], f'data-width="{int(width)}" data-height="{int(height)}"', 1)
    start = html.find('<script>window.LIM_SPEC = ')
    found = _PAGE_SIZE.search(html, start)
    if found:
        rate = float(fps) if fps else json.loads(found[0][found[0].index('"fps":') + 6:-1])
        html = html[:found.start()] + f', "w": {int(width)}, "h": {int(height)}, "len": {found[1]}, "fps": {json.dumps(rate)}}}' + html[found.end():]
    (work / 'index.html').write_text(html, encoding='utf-8')
    return {'page': str(work / 'index.html'), 'missing_fonts': []}


def differs_from_this_pc(saved, s):
    """What a scene's saved copy has that this PC's files don't: {'motion runtime': 'changed', 'paperCraft': 'gone'}."""
    out = {}
    for key, file, label in (('rt', RUNTIME, 'motion runtime'), ('plus', PLUS, 'motion additions'), ('draw', DRAW, 'M.draw'), ('world', WORLD, 'M.world')):
        if key in (saved or {}) and (not file.exists() or file.read_text(encoding='utf-8') != saved[key]):
            out[label] = 'changed' if file.exists() else 'gone'
    for name, text in ((saved or {}).get('looks') or {}).items():
        file = LOOKS / f'{name}.js'
        if name in looks_used(s) and (not file.exists() or file.read_text(encoding='utf-8') != text):
            out[name] = 'changed' if file.exists() else 'gone'
    if uses_shaders(s):
        if saved and saved.get('shader_runtime') != (SHADER_RUNTIME.read_text(encoding='utf-8') if SHADER_RUNTIME.exists() else None):
            out['shader runtime'] = 'changed' if SHADER_RUNTIME.exists() else 'gone'
        for name, text in ((saved or {}).get('shaders') or {}).items():
            file = SHADERS / f'{name}.shader.js'
            if name in shaders_used(s) and (not file.exists() or file.read_text(encoding='utf-8') != text):
                out['shader:' + name] = 'changed' if file.exists() else 'gone'
    return out


def _fps_arg(fps):
    fps = float(fps)
    for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(fps - num / den) < 1e-3:
            return f'{num}/{den}'
    return f'{fps:g}' if fps == int(fps) else f'{fps:.6f}'


def _lock(name):
    import letitedit.core.render_lock as render_lock
    return render_lock.slot(name, caller_pids=render_lock.ancestors())


# ------------------------------------------------------------------ preview and render

def _times(s, count, times):
    if times:
        return [max(0.0, min(s['duration'] - 1e-3, float(t))) for t in times]
    n = max(1, int(count))
    d = s['duration']
    if n == 1:
        return [d / 2]
    # the build-in, the hold and the exit: spread over the clip, last one just before the end
    return [round(min(d - 1e-3, d * i / (n - 1) * 0.97 + 0.15 * (i == 0)), 3) for i in range(n)]


def _over(img_path, background, width, height):
    """An RGBA still over a frame of footage ({clip, at}) or a colour, else left transparent."""
    from PIL import Image
    im = Image.open(img_path).convert('RGBA')
    if not background:
        return im
    if isinstance(background, dict) and background.get('clip'):
        import letitedit.pictures.graphics as graphics
        bg = graphics.still(background['clip'], float(background.get('at', 0)), size=(width, height)).convert('RGBA')
    else:
        bg = gc.background(width, height, background)
    bg = bg.resize(im.size)
    bg.alpha_composite(im)
    return bg


def preview(spec, width=1920, height=1080, fps=30.0, count=6, times=None, background=None, out=None, page=None):
    """Stills at `times` (or `count` spread over the clip) -> a frame sheet. background: None (checkerboard),
    '#rrggbb', or {clip, at} (a frame of footage under the graphic, as it will look on the timeline).
    page: a saved scene's page folder, drawn as it was saved."""
    s = normalise(spec, known=looks_used(spec) + ['shader:' + name for name in shaders_used(spec)] if page else ())
    saved = saved_parts(page, s) if page else None
    why = available()
    if why:
        raise RuntimeError(why)
    d = digest(s, width, height, fps, saved=saved)
    work = CACHE / 'work' / f'preview-{d}-{os.getpid()}'
    built = saved_page(page, width, height, work, fps) if saved else build_page(s, width, height, fps, work)
    ts = _times(s, count, times)
    t0 = time.time()
    _engine(['snapshot', '.', '--at', ','.join(f'{t:.3f}' for t in ts), '--no-end', '-o', 'snaps', '--timeout', '60000'],
            work, timeout=300)
    pngs = sorted((work / 'snaps').glob('frame-*.png'))
    if len(pngs) != len(ts):
        raise RuntimeError(f'the preview made {len(pngs)} stills for {len(ts)} times')
    frames = [_over(p, background, width, height) for p in pngs]
    out = Path(out) if out else CACHE / 'previews' / f'motion-{d}-{abs(hash(tuple(ts))) % 10**6}.jpg'
    sheet = gc.sheet(frames, [f'{t:.2f}s' for t in ts], out, cols=3, tile_w=640, checker=not background)
    return {'sheet': sheet, 'times': ts, 'frames': [str(p) for p in pngs], 'seconds': round(time.time() - t0, 1),
            'missing_fonts': built['missing_fonts'], 'spec': s}


def estimate_s(s, width, height, fps):
    return 4.0 + s['duration'] * float(fps) * (width * height) / (1920 * 1080) * 0.12


def _draw_canvas(s, width, height, fps, work, out, title, comment):
    """A custom scene that is one full-frame canvas and nothing else: its pixels go straight to the encoder from a few pages at
    once (motion\\runtime\\canvas-render.js), with no screenshot per frame and no second encode. Returns the movie, or None for
    anything else or if it can't finish: the engine then draws it, as it always has. LETITEDIT_CANVAS_RENDER=0 turns it off."""
    if (s['format'] != 'mov' or s.get('block') != 'custom' or str(s.get('html') or '').strip() or str(s.get('css') or '').strip()
            or 'canvas' not in str(s.get('script') or '') or os.environ.get('LETITEDIT_CANVAS_RENDER') == '0'
            or not CANVAS_RENDER.exists()):
        return None
    job = {'browser': browser_exe(), 'page': str(Path(work) / 'index.html'), 'width': int(width), 'height': int(height),
           'fps': float(fps), 'frames': max(1, math.ceil(float(s['duration']) * float(fps) - 1e-9)), 'out': str(out),
           'ffmpeg': str(gc.ffmpeg()), 'pages': CANVAS_PAGES,
           'encode': ['-threads', '4', '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16',
                      '-qscale:v', '8', *gc.meta_args('motion', title, comment)]}
    file = Path(work) / 'canvas-job.json'
    file.write_text(json.dumps(job), encoding='utf-8')
    try:
        _engine([str(file)], work, timeout=RENDER_TIMEOUT, script=CANVAS_RENDER)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        import letitedit.core.render_lock as render_lock
        if isinstance(e, (render_lock.Cancelled, render_lock.LockTimeout)):
            raise
        Path(out).unlink(missing_ok=True)
        return None
    return out if Path(out).is_file() and Path(out).stat().st_size else None


def render(spec, width=1920, height=1080, fps=30.0, out_dir=None, out=None, fmt=None, progress=None, sheet_count=6, page=None):
    """The whole clip. mov = ProRes 4444 with alpha (default), mp4 = H.264 (transparent parts black), png = a folder
    of RGBA PNGs. Returns {'path', 'cached', 'alpha', 'format', 'seconds', 'sheet', 'sidecar', 'spec', ...}.
    page: a saved scene's page folder, drawn as it was saved, whatever this PC's runtime and kits are now."""
    s = normalise(spec, known=looks_used(spec) + ['shader:' + name for name in shaders_used(spec)] if page else ())
    saved = saved_parts(page, s) if page else None
    if fmt:
        s['format'] = fmt
    why = available()
    if why:
        raise RuntimeError(why)
    d = digest(s, width, height, fps, saved=saved)
    out_dir = Path(out_dir or CACHE / 'out')
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = {'mov': '.mov', 'mp4': '.mp4', 'png': ''}[s['format']]
    slug = re.sub(r'[^a-z0-9]+', '-', s['block'].lower()).strip('-')
    path = Path(out) if out else out_dir / f'generated-motion-{slug}-{d}{ext}'
    sheet_path = path.with_name(path.name + '.sheet.jpg')
    if path.exists() and (Path(str(path) + '.json').exists() or (path / 'generated.json').exists()):
        _carry_credits(path, s)
        return {'path': str(path), 'cached': True, 'alpha': s['format'] != 'mp4', 'format': s['format'],
                'sheet': str(sheet_path) if sheet_path.exists() else None, 'spec': s,
                'sidecar': str(path) + '.json' if s['format'] != 'png' else str(path / 'generated.json')}
    work = CACHE / 'work' / f'render-{d}-{os.getpid()}'   # a project and its copy can draw the same revision at once
    built = saved_page(page, width, height, work, fps) if saved else build_page(s, width, height, fps, work)
    raw = work / ('raw' + (ext or ''))
    args = ['render', '.', '-o', str(raw), '--format', {'png': 'png-sequence'}.get(s['format'], s['format']),
            '--fps', _fps_arg(fps), '-w', str(WORKERS), '--quality', 'delivery' if s['format'] == 'mp4' else 'looks',
            '--quiet', '--no-best-effort']
    t0 = time.time()
    if progress:
        progress(0.05, 'waiting for the render lock')
    with _lock(f'letitedit-motion {describe(s)}'):
        if progress:
            progress(0.1, 'rendering')
        title = describe(s)
        comment = f"letitedit_motion block {s['block']} rendered by HyperFrames; spec in the sidecar"
        tmp = path.with_name(path.stem + '.tmp' + ext)
        drawn = _draw_canvas(s, width, height, fps, work, tmp, title, comment)
        if drawn is None:
            _engine(args, work)
    if drawn is None and not raw.exists():
        raise RuntimeError(f'the motion render wrote no output ({raw})')
    if drawn is not None:
        os.replace(drawn, path)
    elif s['format'] == 'png':
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        shutil.move(str(raw), str(path))
    else:
        # The engine's ProRes 4444 is 12-bit and about 1.4 Gbit/s (a 15 s 1080x1920 60 fps scene was 2.69 GB). Written
        # again as 10-bit ProRes 4444 at qscale 8 it is about a third of the size, the alpha untouched (16-bit, PSNR inf)
        # and the colour at 45.6 dB (T40).
        codec = (['-threads', '4', '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le',
                  '-alpha_bits', '16', '-qscale:v', '8', '-c:a', 'copy'] if s['format'] == 'mov' else ['-c', 'copy'])
        p = subprocess.run([gc.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(raw), '-map', '0',
                            *codec, *gc.meta_args('motion', title, comment), str(tmp)],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        if p.returncode != 0:
            raise RuntimeError(f'could not write the motion clip: {p.stderr[-800:]}')
        os.replace(tmp, path)
    side = gc.sidecar(path, {'kind': 'motion', 'tool': 'letitedit_motion', 'engine': 'HyperFrames (Apache-2.0)',
                             'spec': dict(s, kit=(saved or {}).get('kit') or kit_of(s)), 'width': width, 'height': height, 'fps': fps,
                             'title': title})
    sheet = None
    try:
        sheet = _sheet_from_file(path, s, fps, sheet_count, sheet_path)
    except Exception:  # noqa: BLE001 - a sheet is a convenience
        pass
    shutil.rmtree(work, ignore_errors=True)
    _carry_credits(path, s)
    return {'path': str(path), 'cached': False, 'alpha': s['format'] != 'mp4', 'format': s['format'],
            'seconds': round(time.time() - t0, 1), 'sheet': sheet, 'sidecar': side, 'spec': s,
            'missing_fonts': built['missing_fonts']}


def _carry_credits(path, s):
    """A motion clip carries the credit lines of the real pictures its page shows (T178)."""
    try:
        import letitedit.pictures.real_pictures as real_pictures
        real_pictures.made_from_recipe(path, s, tool='letitedit_motion')
    except Exception:  # noqa: BLE001 - a line of credit must never stop a clip
        pass


def _sheet_from_file(path, s, fps, count, out):
    from PIL import Image
    ts = _times(s, count, None)
    imgs = []
    if Path(path).is_dir():
        files = sorted(Path(path).glob('*.png'))
        for t in ts:
            imgs.append(Image.open(files[min(len(files) - 1, round(t * fps))]))
    else:
        import io
        for t in ts:
            p = subprocess.run([gc.ffmpeg(), '-v', 'error', '-i', str(path), '-ss', f'{t:.3f}', '-frames:v', '1',
                                '-f', 'image2pipe', '-vcodec', 'png', '-pix_fmt', 'rgba', '-'],
                               capture_output=True, creationflags=NO_WINDOW)
            imgs.append(Image.open(io.BytesIO(p.stdout)))
    return gc.sheet(imgs, [f'{t:.2f}s' for t in ts], out, cols=3, tile_w=640)


def alpha_report(path, times):
    """Measured: for each time, the share of the frame that is opaque (alpha > 8) and the max alpha."""
    import io
    import numpy as np
    from PIL import Image
    rows = []
    for t in times:
        p = subprocess.run([gc.ffmpeg(), '-v', 'error', '-i', str(path), '-ss', f'{t:.3f}', '-frames:v', '1',
                            '-f', 'image2pipe', '-vcodec', 'png', '-pix_fmt', 'rgba', '-'],
                           capture_output=True, creationflags=NO_WINDOW)
        a = np.asarray(Image.open(io.BytesIO(p.stdout)).convert('RGBA'))[..., 3]
        rows.append({'t': t, 'covered': round(float((a > 8).mean()), 4), 'max_alpha': int(a.max())})
    return rows


# ------------------------------------------------------------------ the {motion: spec} timeline item

def recipe(item):
    m = item['motion']
    spec = normalise(dict(m, format='mov') if isinstance(m, dict) else {'block': m, 'format': 'mov'})
    return {'kind': 'motion', 'spec': spec}


def view(r):
    s = dict(r['spec'])
    s.pop('kit', None)          # the project's kit, stored for repeatable renders; not something to edit here
    s.pop('format', None)
    return {'motion': s}


def default_len(item):
    m = item['motion']
    return normalise(m if isinstance(m, dict) else {'block': m})['duration']


def label(r):
    return f"motion: {describe(r['spec'])}"


def render_recipe(r, width, height, fps, out_dir):
    """made.render for {motion: ...} items. When the engine can't run here (available()) or a render stops, the
    item is drawn as its nearest graphic (render_fallback) with a note, so the edit still lands."""
    why = available()
    if why:
        return render_fallback(r['spec'], width, height, fps, out_dir, why)
    try:
        res = render(r['spec'], width, height, fps, out_dir=out_dir, fmt='mov')
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        import letitedit.core.render_lock as render_lock
        if isinstance(e, (render_lock.Cancelled, render_lock.LockTimeout)):    # the job was stopped, not the engine
            raise
        return render_fallback(r['spec'], width, height, fps, out_dir, f'the engine stopped: {_reason(e)}')
    notes = [f"fonts not found (a fallback was used): {res['missing_fonts']}"] if res.get('missing_fonts') else []
    return {'path': res['path'], 'cached': res['cached'], 'alpha': True, 'notes': notes}


# ------------------------------------------------------------------ when the engine can't run: the nearest drawn graphic

def _reason(e):
    lines = [ln.strip() for ln in str(e).splitlines() if ln.strip()]
    hit = next((ln for ln in reversed(lines) if re.search(r'error|fail|cannot|could not|not found|refused', ln, re.I)),
               lines[-1] if lines else type(e).__name__)
    return hit[:240]


def _words(p):
    """A block's words ([{text, start, end}] or [{w, s, e}] minus `offset`, else its text one word per `pace` s) as
    the word_captions template takes them: [[text, start, end], ...]."""
    off = float(p.get('offset') or 0)
    out = []
    for w in p.get('words') or []:
        if isinstance(w, dict):
            t, s, e = w.get('text', w.get('w')), w.get('start', w.get('s')), w.get('end', w.get('e'))
        elif isinstance(w, (list, tuple)) and len(w) >= 2:
            t, s, e = w[0], w[1], w[2] if len(w) > 2 else None
        else:
            continue
        if t is None or s is None:
            continue
        s = max(0.0, float(s) - off)
        e = max(s + 0.05, float(e) - off) if e is not None else s + 0.3
        out.append([str(t), round(s, 3), round(e, 3)])
    if not out and p.get('text'):
        pace = float(p.get('pace') or 0.3)
        out = [[t, round(i * pace, 3), round((i + 1) * pace, 3)] for i, t in enumerate(str(p['text']).split())]
    return out


def _fb_bar_chart(p):
    bars = [b for b in p.get('bars') or [] if isinstance(b, dict)]
    hi = p.get('highlight', -1)
    pick = bars[hi] if isinstance(hi, int) and 0 <= hi < len(bars) else \
        max(bars, key=lambda b: float(b.get('value') or 0), default=None)
    if not pick:
        return None
    return 'big_number', {'value': pick.get('value', 0), 'prefix': p.get('prefix'), 'suffix': p.get('unit'),
                          'decimals': p.get('decimals'), 'label': ' - '.join(str(x) for x in (p.get('title'), pick.get('label')) if x),
                          'font': p.get('font'), 'label_font': p.get('body_font'), 'fill': p.get('fill'),
                          'label_fill': p.get('bar')}


def _fb_steps(p):
    steps = [str(x) for x in p.get('steps') or []]
    if not steps:
        return None
    i = min(max(int(p.get('current') or 1), 1), len(steps))
    return 'chapter_card', {'number': f'{i}/{len(steps)}', 'title': steps[i - 1], 'kicker': p.get('title') or '',
                            'position': 'center' if p.get('position') == 'center' else 'left', 'font': p.get('font'),
                            'fill': p.get('fill'), 'accent': p.get('accent'), 'band': bool(p.get('panel', True))}


FALLBACKS = {
    'location': lambda p: ('lower_third', {
        'title': p.get('place'), 'subtitle': p.get('detail') or '', 'position': p.get('position') or 'top-left',
        'margin_y': p.get('margin', 0.07), 'font': p.get('font'), 'subtitle_font': p.get('body_font'),
        'size': p.get('size'), 'subtitle_size': p.get('detail_size'), 'fill': p.get('fill'),
        'subtitle_fill': p.get('detail_fill'), 'accent': p.get('pin'), 'panel': 'dark',
        'panel_opacity': 0.78 if p.get('panel', True) else 0.0}),
    'lower_third': lambda p: ('lower_third', {
        'title': p.get('name'), 'subtitle': p.get('role') or '', 'position': f"bottom-{p.get('side') or 'left'}",
        'margin_y': p.get('margin_y'), 'font': p.get('font'), 'subtitle_font': p.get('role_font'), 'size': p.get('size'),
        'subtitle_size': p.get('role_size'), 'fill': p.get('fill'), 'subtitle_fill': p.get('role_fill'),
        'panel': p.get('panel'), 'panel_opacity': p.get('panel_opacity'), 'accent': p.get('accent')}),
    'title': lambda p: ('title_card', {
        'title': p.get('title'), 'subtitle': p.get('subtitle') or '', 'background': 'none', 'font': p.get('font'),
        'subtitle_font': p.get('subtitle_font'), 'size': p.get('size'), 'subtitle_size': p.get('subtitle_size'),
        'fill': p.get('fill'), 'subtitle_fill': p.get('subtitle_fill'), 'accent': p.get('accent')}),
    'chapter': lambda p: ('chapter_card', {
        'number': p.get('number'), 'title': p.get('title'), 'kicker': p.get('kicker') or '',
        'position': 'center' if p.get('position') == 'center' else 'left', 'font': p.get('font'),
        'number_size': p.get('number_size'), 'size': p.get('size'), 'fill': p.get('fill'),
        'accent': p.get('number_fill'), 'band': bool(p.get('dim', True))}),
    'count_up': lambda p: ('big_number', {
        'value': p.get('to'), 'prefix': p.get('prefix'), 'suffix': p.get('suffix'), 'decimals': p.get('decimals'),
        'label': p.get('label'), 'position': p.get('position'), 'font': p.get('font'), 'size': p.get('size'),
        'label_font': p.get('label_font'), 'label_size': p.get('label_size'), 'fill': p.get('fill'),
        'label_fill': p.get('label_fill'), 'count_seconds': p.get('count_time')}),
    'end_card': lambda p: ('end_card', {
        'title': p.get('title'), 'subtitle': '  '.join(str(x) for x in (p.get('cta'), p.get('handle')) if x),
        'background': 'none' if p.get('background') in (None, '', 'none', 'dim') else p.get('background'),
        'font': p.get('font'), 'subtitle_font': p.get('body_font'), 'size': p.get('size'), 'fill': p.get('fill'),
        'accent': p.get('accent'), 'video_slots': p.get('slots')}),
    'callout': lambda p: ('callout', {
        'text': p.get('text'), 'target_x': (p.get('at') or [0.5, 0.5])[0], 'target_y': (p.get('at') or [0.5, 0.5])[1],
        'font': p.get('font'), 'size': p.get('size'), 'fill': p.get('fill'), 'label': p.get('panel'),
        'line': p.get('line'), 'ring': p.get('accent')}),
    'subscribe': lambda p: ('badge', {
        'text': '  '.join(str(x) for x in (p.get('text'), p.get('handle')) if x), 'position': p.get('position'),
        'font': p.get('font'), 'size': p.get('size'), 'fill': p.get('fill'), 'background': p.get('button')}),
    'kinetic_quote': lambda p: ('word_captions', {
        'words': _words(p), 'style': 'pop', 'font': p.get('font'), 'size': p.get('size'), 'fill': p.get('fill'),
        'highlight': p.get('emphasis_fill'), 'position': p.get('position'), 'max_width': p.get('max_width'),
        'uppercase': p.get('case') == 'upper'}) if _words(p) else None,
    'word_captions': lambda p: ('word_captions', {
        'words': _words(p), 'style': 'karaoke', 'font': p.get('font'), 'size': p.get('size'), 'fill': p.get('fill'),
        'highlight': p.get('active_fill'), 'outline': p.get('outline'), 'outline_width': p.get('outline_width'),
        'position': p.get('position'), 'margin_y': p.get('margin_y'),
        'uppercase': p.get('case', 'upper') == 'upper'}) if _words(p) else None,
    'bar_chart': _fb_bar_chart,
    'route_map': lambda p: ('list_card', {'title': p.get('title') or 'Route',
                                          'items': [s.get('name', '') for s in p.get('stops') or []],
                                          'position': 'center'}),
    'steps': _fb_steps,
    'flip_card': lambda p: ('title_card', {
        'title': p.get('back'), 'subtitle': p.get('eyebrow') or '', 'background': 'none',
        'font': p.get('font'), 'size': p.get('size'), 'fill': p.get('fill'),
        'accent': p.get('accent')}),
    'stinger': lambda p: ('text_pop', {'text': p['text'], 'font': p.get('font'), 'size': p.get('size'),
                                       'fill': p.get('fill')}) if p.get('text') else None,
}


def fallback_graphic(spec):
    """The drawn graphic (bridge/graphics_templates) nearest to a motion spec, used when the engine can't run:
    {template, params, len} at the clip's own length, or None when nothing stands in for it (a stinger without
    text, custom code, a chart without bars)."""
    s = normalise(spec)
    fn = FALLBACKS.get(s['block'])
    got = fn(dict(s.get('params') or {})) if fn else None
    if not got:
        return None
    template, params = got
    return {'template': template, 'params': {k: v for k, v in params.items() if v is not None},
            'len': round(s['duration'], 3)}


def _graphic_kit(s):
    """The style a fallback graphic draws in: the spec's pack, with the colours and fonts its recipe stored."""
    import letitedit.looks.look_library as look_library
    kit = copy.copy(look_library.kit(s.get('look')))
    snap = s.get('kit') or {}
    kit['colors'] = dict(kit['colors'], **(snap.get('colors') or {}))
    kit['fonts'] = dict(kit['fonts'], **(snap.get('fonts') or {}))
    return kit


def _empty_clip(duration, width, height, fps, out_dir):
    """A fully transparent clip (QuickTime Animation, alpha) of the given length."""
    out_dir = Path(out_dir or CACHE / 'out')
    out_dir.mkdir(parents=True, exist_ok=True)
    rate = _fps_arg(fps)
    path = out_dir / f"generated-motion-empty-{width}x{height}-{rate.replace('/', '_')}-{duration:.3f}.mov"
    if path.exists():
        return path, True
    tmp = path.with_name(path.stem + '.tmp.mov')
    p = subprocess.run([gc.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                        f'color=c=black@0.0:s={width}x{height}:r={rate}:d={duration:.4f},format=rgba',
                        '-c:v', 'qtrle', '-pix_fmt', 'argb', str(tmp)],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(f'could not write an empty clip: {p.stderr[-400:]}')
    os.replace(tmp, path)
    return path, False


def render_fallback(spec, width, height, fps, out_dir, why):
    """Draw a motion spec as its nearest graphic (fallback_graphic), or as an empty clip when none stands in for it.
    Returns made.render's {'path', 'cached', 'alpha', 'notes'} plus 'fallback' (the template or None)."""
    s = normalise(spec)
    if s['block'] == 'kinetic_type':
        raise ValueError(f'kinetic_type cannot be reproduced by a still fallback: {why}')
    reason = f"motion clips can't render on this PC: {why}"
    g = fallback_graphic(s)
    if g:
        import letitedit.pictures.graphics as graphics
        r = graphics.render(g, width, height, fps, kit=_graphic_kit(s), out_dir=out_dir)
        return {'path': r['path'], 'cached': r['cached'], 'alpha': True, 'fallback': g['template'],
                'notes': [f"{describe(s)} drawn as the {g['template']} graphic instead ({reason})"]}
    path, cached = _empty_clip(s['duration'], width, height, fps, out_dir)
    return {'path': str(path), 'cached': cached, 'alpha': True, 'fallback': None,
            'notes': [f'{describe(s)} left empty: no drawn graphic stands in for it ({reason})']}


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] == ['setup']:
        print(json.dumps(setup(), indent=1))
    elif sys.argv[1:2] == ['blocks']:
        print(blocks_text())
    elif sys.argv[1:2] == ['status']:
        print(json.dumps(status(), indent=1))
    else:
        print('usage: motion.py setup | blocks | status')
