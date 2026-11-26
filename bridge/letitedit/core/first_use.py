r"""First use of a feature that needs a local model or a model environment: get what is missing.

    need(env=None, models=(), feature='')   before the feature runs: builds the environment (env_build.ensure) and
                                            downloads the models (model_fetch.ensure). settings.json 'model_downloads':
                                            'auto' (default) = do it now; 'ask' / 'never' = raise with the sizes and
                                            the command that gets them (EnvMissing / ModelMissing, RuntimeErrors).
    need_for_python(python, models=(), feature='')   the same, the environment named by its python.exe path
                                            (<envs>\<name>\Scripts\python.exe; any other path: models only)
    optional(models=(), env=None, feature='') -> True when present / got now; False when the setting says ask/never
                                            or the download failed (for features with a fallback)
    events()                                what this process fetched or built (newest last)

Sizes are worked out before anything is downloaded and written, with each result, to <root>\cache\first-use.log
(one JSON line per event) and to stderr (stdout is the MCP channel). Once a model or environment is confirmed
present it is not checked again in this process. A missing manifest / recipe entry never stops a feature: the
feature then runs as before (and fails as before when the files really are missing).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
LOG = Path(os.environ.get('LETITEDIT_CACHE') or ROOT / 'cache') / 'first-use.log'
_ok = set()
_lock = threading.RLock()
_notes = []
_events = []


def _say(text):
    try:
        sys.stderr.write(f'[letitedit first use] {text}\n')
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _tell(feature, size_text):
    """Before a first-use download starts (T76): in plain words on the progress card of a video being made, and in the reply of the
    tool call it happens in (letitedit_mcp), since the line on stderr reaches nobody."""
    name = feature or 'A part of letitedit'
    text = f"{name[:1].upper()}{name[1:]}: downloading {size_text}, first time only"
    _notes.append(text)
    _card(text)


def _card(text):
    try:
        import letitedit.app.progress_feed as progress_feed
        progress_feed.note(text)
    except Exception:  # noqa: BLE001 - words on a card never stop the work
        pass


def say_in_reply(text):
    """Something the person should hear, in the reply of the tool call it happens in."""
    _notes.append(text)


def drain():
    """What was said since the last time, once."""
    said = list(_notes)
    _notes.clear()
    return said


def _log(ev):
    ev = dict(ev, at=time.strftime('%Y-%m-%d %H:%M:%S'))
    _events.append(ev)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(ev) + '\n')
    except OSError:
        pass


def events():
    return list(_events)


def _env(name, feature):
    if not name or ('env', name) in _ok:
        return
    import letitedit.core.env_build as eb
    try:
        if eb.is_ready(name):
            _ok.add(('env', name))
            return
        p = eb.plan(name)
    except (KeyError, FileNotFoundError, ValueError) as ex:   # no recipe: leave it to the feature
        _log({'kind': 'env', 'name': name, 'feature': feature, 'result': f'no recipe ({ex})'})
        return
    _say(f'{feature or name}: ' + eb.describe(p))
    if eb._setting() == 'auto':     # 'ask' and 'never' refuse below, with the size: nothing downloads
        _tell(feature or name, p['download_text'])
    t0 = time.monotonic()
    try:
        eb.ensure(name, progress=_say)
    except Exception as ex:
        _card(None)
        _log({'kind': 'env', 'name': name, 'feature': feature, 'form': p.get('form'),
              'download_bytes': p.get('download_bytes'), 'result': f'{type(ex).__name__}: {ex}'})
        raise
    _card(None)
    _ok.add(('env', name))
    _log({'kind': 'env', 'name': name, 'feature': feature, 'form': p.get('form'),
          'download_bytes': p.get('download_bytes'), 'installed_bytes': p.get('installed_bytes'),
          'result': 'built', 'seconds': round(time.monotonic() - t0, 1)})


def _model(mid, feature):
    if ('model', mid) in _ok:
        return
    import letitedit.core.model_fetch as mf
    try:
        p = mf.plan([mid])
    except (KeyError, FileNotFoundError, ValueError) as ex:   # not in the manifest: leave it to the feature
        _log({'kind': 'model', 'id': mid, 'feature': feature, 'result': f'not in the manifest ({ex})'})
        return
    if not p['download_bytes'] and all(s['present'] for s in p['models']):
        _ok.add(('model', mid))
        return
    _say(f"{feature or mid}: {mid} and what it needs: {p['download_text']} to download "
         f"({p['disk_free_text']} free)")
    if mf._setting() == 'auto':     # 'ask' and 'never' refuse below, with the size: nothing downloads
        _tell(feature or mid, p['download_text'])
    t0 = time.monotonic()
    try:
        mf.ensure(mid)
    except Exception as ex:
        _card(None)
        _log({'kind': 'model', 'id': mid, 'feature': feature, 'download_bytes': p['download_bytes'],
              'result': f'{type(ex).__name__}: {ex}'})
        raise
    _card(None)
    _ok.add(('model', mid))
    _log({'kind': 'model', 'id': mid, 'feature': feature, 'download_bytes': p['download_bytes'],
          'result': 'downloaded', 'seconds': round(time.monotonic() - t0, 1)})


def need(env=None, models=(), feature=''):
    with _lock:
        _env(env, feature)
        for m in models or ():
            _model(m, feature)


def env_of(python):
    """The environment name when python is <envs>\\<name>\\Scripts\\python.exe, else None."""
    try:
        import letitedit.core.env_build as eb
        p = Path(python).resolve() if Path(python).exists() else Path(os.path.abspath(python))
        envs = Path(eb.ENVS_HOME).resolve() if Path(eb.ENVS_HOME).exists() else Path(os.path.abspath(eb.ENVS_HOME))
        if p.name.lower() == 'python.exe' and p.parent.name.lower() == 'scripts' and \
                p.parent.parent.parent == envs:
            return p.parent.parent.name
    except Exception:  # noqa: BLE001
        pass
    return None


def need_for_python(python, models=(), feature=''):
    need(env_of(python), models, feature)


def optional(models=(), env=None, feature=''):
    try:
        need(env, models, feature)
        return True
    except Exception as ex:  # noqa: BLE001 - the feature has a fallback
        _say(f'{feature}: not fetched ({ex}); using the fallback')
        return False
