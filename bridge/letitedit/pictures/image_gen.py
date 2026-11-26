"""letitedit_image: pictures for a video, drawn by whichever AI or key on this PC can draw, and kept in the video's side
folder. See DOC. T56.

Who draws, in this order:
  antigravity  when installed, signed in and allowed by the person's other-AI switch, in a visible conversation
  own    the AI driving has its own image tool: it draws in its own session, and letitedit files the result
  key    the person added their own image API key: letitedit calls the maker's image API
  other  an AI that can draw is on this PC, signed in, and the person turned this on after a plain notice: letitedit starts
         the person's own program, on their own sign-in, and returns the picture to the AI that asked
  none   nothing can draw: the reply says so in facts, and the AI goes on in code

Nothing here reads a sign-in file. A new AI that can draw says so in the one AI list (ai_list.json). An AI that runs only on screen
(Antigravity) draws for another AI in a labelled conversation in the panel, through its connector and never `agy -p`, and the picture
goes back to the AI that asked. A failed image never raises or hangs: the reply carries a plain message.

python image_gen.py --status                         who can draw, as JSON (the app's panel)
python image_gen.py --history <project>              what was made for a video, as JSON
python image_gen.py --set-other-ai on|off            the person's choice (the panel's switch)
python image_gen.py --set-key openai | --clear-key openai   the key comes on stdin, never on the command line
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import letitedit.app.ai_clis as ai_clis
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

SHAPES = {'wide': '16:9', 'tall': '9:16', 'square': '1:1'}
MAX_REFERENCES = 5      # the image tool's own limit (MAX_EDIT_IMAGES in openai/codex)
MAX_COUNT = 6
AT_ONCE = 3             # T56 Part 1: three runs at once work
START_GAP_S = 2.0       # T56 Part 1: runs started 2 s apart don't collide over Codex's skills folder
RUN_LIMIT_S = 240       # the slowest of 26 real runs took 85 s
CALL_LIMIT_S = 420      # no new run starts after this; a call always ends
API_LIMIT_S = 300
LIMIT_HOLD_S = 900      # after a maker says "limit", don't spend 40 s per image finding out again
OTHER_AI_SETTING = 'image_other_ai'     # panel.json; missing means off
DEFAULT_CODEX_MODEL = 'gpt-6-luna'      # the AI only passes the words on, so the lightest model that can; falls back to the person's own
KEY_MAKERS = {'openai': 'OpenAI'}
# The AIs that can draw, from the one list (the program comes from ai_clis).
DRAWERS = {i: ai_clis.NAMES[i] for i, row in ai_clis.AIS.items() if row.get('can', {}).get('draw')}
GOOGLE_REFERENCES = 3   # generate_image takes up to 3 (tests/t57/GATE.md)
GOOGLE_FACTS = ('Its own image tool: no size, quality or transparency setting, JPEG. Wide gives 1376x768, tall 768x1376, square 1024x1024; up to 3 '
                'reference images. A "transparent" picture comes on a flat green that is not exact, so a key must allow for that. On a free Google '
                'plan 7 pictures locked it for about a week.')
OWES = ("This video uses AI-made pictures from OpenAI's image model. OpenAI's sharing policy asks you to say so where people "
        "will see it, for example in the description.")

_start_lock = threading.Lock()
_last_start = [0.0]


# ---------------------------------------------------------------- where things are

def _cache():
    return Path(os.environ.get('LETITEDIT_CACHE') or ai_clis.ROOT / 'cache')


def _codex_home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def image_store():
    """Where Codex saves its pictures: <Codex home>\\generated_images\\<thread id>\\*.png"""
    return _codex_home() / 'generated_images'


def side_folder(project=None, folder=None):
    """<project stem>.letitedit\\images beside the project, or <folder>\\.letitedit\\images when there's no project yet."""
    if project:
        p = Path(project)
        return p.parent / (p.stem + '.letitedit') / 'images'
    if folder:
        return Path(folder) / '.letitedit' / 'images'
    return None


def project_size(project):
    """The video's width and height from its .mlt, or None."""
    try:
        with open(project, encoding='utf-8', errors='replace') as f:
            head = f.read(8192)
    except (OSError, TypeError):
        return None
    tag = re.search(r'<profile\b[^>]*>', head)
    if not tag:
        return None
    w, h = re.search(r'\bwidth="(\d+)"', tag.group(0)), re.search(r'\bheight="(\d+)"', tag.group(0))
    return [int(w.group(1)), int(h.group(1))] if w and h else None


# ---------------------------------------------------------------- the person's own API key

def _keys_file():
    return Path(os.environ.get('LETITEDIT_IMAGE_KEYS') or Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'letitedit' / 'image-keys.json')


def _dpapi(data, protect):
    """Windows' own per-user encryption, so the key isn't readable in a copied file."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    call = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not call(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError('Windows could not protect this key')
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _read_keys():
    try:
        data = json.loads(_keys_file().read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_key(maker, key):
    if maker not in KEY_MAKERS:
        raise ValueError(f'No image key for {maker!r}')
    keys = _read_keys()
    keys[maker] = base64.b64encode(_dpapi(key.strip().encode('utf-8'), True)).decode('ascii')
    path = _keys_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys), encoding='utf-8')


def clear_key(maker):
    keys = _read_keys()
    if keys.pop(maker, None) is not None:
        _keys_file().write_text(json.dumps(keys), encoding='utf-8')


def _key(maker):
    """The person's key for a maker: only one they added to letitedit. OPENAI_API_KEY alone is never used: a key from
    somewhere else shouldn't start costing money per picture without them choosing it."""
    from_env = os.environ.get(f'LETITEDIT_IMAGE_{maker.upper()}_KEY')
    if from_env:
        return from_env
    stored = _read_keys().get(maker)
    if not stored:
        return None
    try:
        return _dpapi(base64.b64decode(stored), False).decode('utf-8')
    except (OSError, ValueError):
        return None


def has_key(maker):
    return bool(_key(maker))


# ---------------------------------------------------------------- who can draw

def _limit_file():
    return _cache() / 'image-limit.json'


def _note_limit(by, said):
    try:
        path = _limit_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'by': by, 'said': said, 'at': time.time()}), encoding='utf-8')
    except OSError:
        pass


def _limit_held(by):
    """What the maker last said about its limit, while that still holds."""
    try:
        note = json.loads(_limit_file().read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    if note.get('by') == by and time.time() - float(note.get('at', 0)) < LIMIT_HOLD_S:
        return note.get('said') or 'its limit'
    return None


def routes(settings=None, driver=None):
    """Who can draw here, best first, and what's switched off. Names only an AI that is on this PC and signed in."""
    settings = ai_clis.chat_settings() if settings is None else settings
    driver = ai_clis.editor(settings) if driver is None else driver
    found, off = [], []
    if driver in DRAWERS and ai_clis.find(driver, settings):
        found.append({'route': 'own', 'by': driver, 'name': DRAWERS[driver]})
    for maker, name in KEY_MAKERS.items():
        if has_key(maker):
            held = _limit_held(maker)
            if held:
                off.append({'route': 'key', 'by': maker, 'why': f'{name} said: {held}'})
            else:
                found.append({'route': 'key', 'by': maker, 'name': name})
    for ai, name in DRAWERS.items():
        if ai == driver:
            continue
        exe = ai_clis.find(ai, settings)
        if not exe or ai_clis.signed_in(ai, exe, settings=settings) is False:
            continue                                    # not here or signed out: never named to the person
        if settings.get(OTHER_AI_SETTING) is not True:
            off.append({'route': 'other', 'by': ai, 'why': f'{name} is on this PC and can draw for this AI once the person turns '
                                                           'that on in the Image generator. It is off.'})
        elif not ai_clis.visible_only(ai) and not ai_clis.background_allowed(settings):
            off.append({'route': 'other', 'by': ai, 'why': f'{name} could draw, but runs of an AI that nobody is watching are off in Connect Your AI.'})
        elif _limit_held(ai):
            off.append({'route': 'other', 'by': ai, 'why': f'{name} said: {_limit_held(ai)}'})
        else:
            found.append({'route': 'other', 'by': ai, 'name': name, 'exe': exe})
    found.sort(key=lambda route: 0 if route['by'] == 'antigravity' else 1)
    off.sort(key=lambda route: 0 if route['by'] == 'antigravity' else 1)    # first: the one that draws once it is on
    return {'driving': driver, 'routes': found, 'off': off}


def status(settings=None, driver=None):
    """For the tool's `status` and the app's panel: who draws, what each one can do, and the switch's state."""
    settings = ai_clis.chat_settings() if settings is None else settings
    found = routes(settings, driver)
    facts = {'own': 'Its own image tool: no size, quality or count setting. Wide usually gives 1672x941, tall 941x1672 (once 1051x1497); a transparent one has come back at 1024x1536 and 941x1672.',
             'other': 'One picture per run, 30-60 s each, up to three at once. Wide usually gives 1672x941, tall 941x1672 (once 1051x1497); a transparent one has come back at 1024x1536 and 941x1672. '
                      'Uses the person\'s own plan.',
             'key': "The maker's image API, paid per image by the person: exact sizes, quality and masks."}
    rows = [{k: v for k, v in r.items() if k != 'exe'} | {'can': GOOGLE_FACTS if ai_clis.visible_only(r.get('by')) and r['route'] != 'key' else facts[r['route']]}
            for r in found['routes']]
    return {'driving': found['driving'], 'draws_now': rows[0] if rows else None, 'routes': rows, 'off': found['off'],
            'other_ai_on': settings.get(OTHER_AI_SETTING) is True, 'keys': {m: has_key(m) for m in KEY_MAKERS},
            'message': _nobody(found) if not rows else f"{rows[0]['name']} draws."}


def _nobody(found):
    why = ' '.join(o['why'] for o in found['off'])
    return ('Nothing on this PC can draw an image for this AI right now. ' + (why + ' ' if why else '') +
            'Nothing was drawn: the picture can be drawn in code (letitedit_code_scene, letitedit_graphic, letitedit_motion).')


# ---------------------------------------------------------------- filing

def _sidecars(side):
    return sorted(Path(side).glob('generated-image-*.json')) if side and Path(side).is_dir() else []


def history(project=None, folder=None):
    """Everything made for this video, oldest first, with the words that made it."""
    rows = []
    for car in _sidecars(side_folder(project, folder)):
        try:
            row = json.loads(car.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if Path(row.get('path', '')).exists():
            rows.append(row)
    return rows


def _find_filed(ref, project, folder):
    for row in history(project, folder):
        if ref in (row['id'], row['path'], Path(row['path']).name):
            return row
    return None


def _reserve(side, suffix):
    """The next free number, claimed on disk so that runs at once can't take the same one."""
    side.mkdir(parents=True, exist_ok=True)
    taken = [int(m.group(1)) for p in side.glob('generated-image-*') if (m := re.match(r'generated-image-(\d+)', p.name))]
    n = max(taken, default=0) + 1
    while True:
        dest = side / f'generated-image-{n:04d}{suffix}'
        try:
            os.close(os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return n, dest
        except FileExistsError:
            n += 1


def _measure(path):
    from PIL import Image
    with Image.open(path) as im:
        return list(im.size), 'A' in im.getbands()


def _fit_copy(path, n, side, size, video):
    """A smooth copy at the video's size when the picture has the video's shape, so a full-frame plate fills it exactly."""
    if not video or size == video or abs(size[0] / size[1] - video[0] / video[1]) > 0.01:
        return None
    from PIL import Image
    out = side / f'generated-image-{n:04d}-fit-{video[0]}x{video[1]}.png'
    try:
        with Image.open(path) as im:
            im.convert('RGBA' if 'A' in im.getbands() else 'RGB').resize(tuple(video), Image.LANCZOS).save(out)
    except OSError:
        return None
    return str(out)


def file_image(source, side, meta, project=None):
    """Copy a made picture, byte for byte so its provenance marks stay, into the side folder with its words beside it."""
    source = Path(source)
    n, dest = _reserve(side, source.suffix.lower() or '.png')
    shutil.copyfile(source, dest)
    size, alpha = _measure(dest)
    video = project_size(project) if project else None
    row = dict(meta, generated=True, kind='image', tool='letitedit_image', id=f'img-{n:04d}', path=str(dest), source=str(source),
               size=size, alpha=alpha, created=time.strftime('%Y-%m-%dT%H:%M:%S'), url=dest.as_uri())
    if video:
        row['video_size'] = video
        row['scale_to_fill'] = round(max(video[0] / size[0], video[1] / size[1]), 3)
        fit = _fit_copy(dest, n, side, size, video)
        if fit:
            row['fit_path'] = fit
    _carry_credits(row, dest)
    place = row.get('fit_path') or row['path']
    row['edit_item'] = {'op': 'insert', 'item': {'clip': place, 'len': 4}}     # the track and the time are the caller's
    (side / f'generated-image-{n:04d}.json').write_text(json.dumps(row, indent=1), encoding='utf-8')
    return row


def _carry_credits(row, dest):
    """A picture drawn from real pictures (references, or the picture it edits) carries their credit lines (T178)."""
    try:
        import letitedit.pictures.real_pictures as real_pictures
        sources = [*(row.get('references') or []), *([row['edit_of']] if row.get('edit_of') else [])]
        real_pictures.made_from(dest, sources, tool='letitedit_image')
        if row.get('fit_path'):
            real_pictures.made_from(row['fit_path'], [dest], tool='letitedit_image')
    except Exception:  # noqa: BLE001 - a line of credit must never stop a picture
        pass


def _maker_of_program(by):
    return 'google' if by == 'antigravity' else 'openai'


def owes(paths):
    """What a video owes for the generated pictures among these files: the credit lines, as assets.credits gives them."""
    used = []
    for p in paths or []:
        name = Path(str(p)).name
        if not name.startswith('generated-image-') or not os.path.isabs(str(p)):
            continue
        car = Path(p).parent / (re.match(r'generated-image-\d+', name).group(0) + '.json')
        try:
            row = json.loads(car.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if row.get('generated') and (row.get('made_by') or {}).get('maker') == 'openai':
            used.append(row['id'])
    return [{'line': OWES, 'assets': sorted(set(used))}] if used else []


def scene_images(project):
    """The generated pictures a project's code scenes load, from the scenes' sources (a page has its own relative copy)."""
    from urllib.request import url2pathname
    from urllib.parse import urlparse
    p = Path(project)
    found = set()
    for page in (p.parent / (p.stem + '.letitedit') / 'scenes').glob('*/revisions/*/scene.json'):
        try:
            text = page.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for url in re.findall(r"file:///[^'\"\s)`]*generated-image-\d+[^'\"\s)`]*", text):
            found.add(url2pathname(urlparse(url).path))
    return sorted(found)


def _log(side, row):
    try:
        side.mkdir(parents=True, exist_ok=True)
        with open(side / 'log.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(dict(row, at=time.strftime('%Y-%m-%dT%H:%M:%S')), default=str) + '\n')
    except OSError:
        pass


# ---------------------------------------------------------------- references

def _resolve_references(references, characters, edit, prompt, project, folder):
    """The files to attach, checked before any run: what's missing is said now, not after using the person's allowance. Character
    sheets come first and are attached whenever the character is named or mentioned; a scene is only ever an extra."""
    rows, notes, want = history(project, folder), [], []
    sheets = {r['character'].lower(): r for r in rows if r.get('character')}
    for name in characters or []:
        row = sheets.get(str(name).lower())
        if not row:
            known = ', '.join(sorted(sheets)) or 'none yet'
            return None, f'There is no character sheet called {name!r} for this video (known: {known}). Nothing was drawn.', notes
        want.append(row['path'])
    for name, row in sheets.items():
        if re.search(rf'\b{re.escape(name)}\b', prompt or '', re.I) and row['path'] not in want:
            want.append(row['path'])
            notes.append(f"{row['character']}'s character sheet was attached because the words name them.")
    if edit:
        filed = _find_filed(str(edit), project, folder)
        want.append(filed['path'] if filed else str(edit))
    for ref in references or []:
        filed = _find_filed(str(ref), project, folder)
        want.append(filed['path'] if filed else str(ref))
    seen, out = set(), []
    for path in want:
        full = str(Path(path).resolve())
        if full.lower() in seen:
            continue
        seen.add(full.lower())
        if not Path(full).is_file():
            return None, f'This reference image is not there: {path}. Nothing was drawn.', notes
        try:
            _measure(full)
        except Exception:  # noqa: BLE001 - not a picture
            return None, f'This reference is not a picture that can be opened: {path}. Nothing was drawn.', notes
        out.append(full)
    if len(out) > MAX_REFERENCES:
        return None, f'{len(out)} reference images were given; the image tools take at most {MAX_REFERENCES}. Nothing was drawn.', notes
    made_scenes = {r['path'].lower() for r in rows if not r.get('character')}
    if sheets and any(p.lower() in made_scenes for p in out) and not edit:
        notes.append('A reference here is a generated scene, not a character sheet. In tests a character chained from scene to scene '
                     'became someone else by the third step; the same words with the sheet attached stayed right.')
    return out, None, notes


def _words(prompt, shape, transparent, refs, edit):
    parts = [str(prompt).strip()]
    if shape in SHAPES:
        parts.append(f'Shape: {SHAPES[shape]}.')
    if transparent:
        parts.append('A real transparent background.')
    if edit:
        parts.append('Change only what is asked. Everything else stays exactly the same.')
    elif refs:
        parts.append('The attached images are references: keep exactly what they show (the same character, object or place, and '
                     'the same drawing style).')
    return ' '.join(parts)


# ---------------------------------------------------------------- drawing: the person's own program

def _exec_prompt(words, refs, transparent):
    how = ['$imagegen Make exactly one image with your image tool (image_gen__imagegen), then stop. Change no files and run nothing else.',
           'Give the exec call the first-line @exec directive for 120 seconds and return the image with generatedImage(result). The tool '
           'saves the file itself, so make no second image, even if you cannot see the first.']
    if refs:
        how.append(f'Pass the {len(refs)} attached image(s) to the tool with num_last_images_to_include: {len(refs)}.')
    if transparent:
        how.append('Set transparent_background to true.')
    how.append('The image to make: ' + words)
    return '\n\n'.join(how)


def _kill_tree(pid):
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)


def _text(data):
    if data is None:
        return ''
    return data.decode('utf-8', 'replace') if isinstance(data, bytes) else data


def _thread_of(stream):
    for line in stream.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('type') == 'thread.started':
            return row.get('thread_id')
    return None


def _stream_said(stream):
    """The run's own errors, and what the AI wrote, kept apart: its words can mention a limit without having hit one."""
    errors, said = [], []
    for line in stream.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        item = row.get('item') or {}
        if row.get('type') in ('error', 'turn.failed'):
            inner = row.get('error')
            words = row.get('message') or (inner.get('message') if isinstance(inner, dict) else inner)
            errors.append(str(words or json.dumps(row))[:600])
        elif item.get('type') == 'error':
            errors.append(str(item.get('message') or item.get('text'))[:600])
        elif item.get('type') == 'agent_message':
            said.append(str(item.get('text'))[:600])
    return errors, said


def _session_failure(thread):
    """The image tool's own reason, from the run's session log: a usage limit is written there as usageLimitExceeded."""
    if not thread:
        return None
    try:
        for path in (_codex_home() / 'sessions').rglob(f'*{thread}*.jsonl'):
            with open(path, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if '"failure"' in line and 'image_gen' in line:
                        found = re.search(r'"failure"\s*:\s*(\{[^{}]*\})', line)
                        if found:
                            return found.group(1)[:400]
    except OSError:
        pass
    return None


def _start_turn():
    with _start_lock:
        wait = _last_start[0] + START_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_start[0] = time.monotonic()


def _run_codex(exe, prompt, refs, work, model, limit, normal_speed=False):
    """One picture from one run of the person's own Codex. Returns {thread, files, errors, said, stderr, exit, seconds}."""
    args = [exe, 'exec']
    for ref in refs:
        args += ['-i', ref]
    args += ['--ignore-rules', '--skip-git-repo-check', '-s', 'read-only']
    if model:
        args += ['-m', model, '-c', 'model_reasoning_effort="low"']
    args += ['--json']
    args = ai_clis.with_speed(args, 'codex', model, normal=normal_speed)
    _start_turn()
    begun = time.monotonic()
    try:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=work,
                                env=ai_clis.child_env())
    except OSError as exc:
        return {'thread': None, 'files': [], 'errors': [str(exc)], 'said': [], 'stderr': '', 'exit': None, 'seconds': 0}
    timed_out = False
    try:
        out, err = proc.communicate(prompt.encode('utf-8'), timeout=limit)
    except subprocess.TimeoutExpired as exc:
        timed_out, out, err = True, exc.stdout, exc.stderr
        _kill_tree(proc.pid)
        try:                                # a grandchild can hold the pipes open: never wait on it for long
            more_out, more_err = proc.communicate(timeout=5)
            out, err = more_out or out, more_err or err
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
    stream, err = _text(out), _text(err)
    thread = _thread_of(stream)
    files = sorted((image_store() / thread).glob('*.png'), key=lambda p: p.stat().st_mtime) if thread and (image_store() / thread).is_dir() else []
    errors, said = _stream_said(stream)
    if not normal_speed and not timed_out and not files and not said and ai_clis.selected_speed('codex', model) != 'normal' \
            and ai_clis.speed_refused(' '.join(errors) + ' ' + err):
        notice = ai_clis.speed_notice('codex')
        run = _run_codex(exe, prompt, refs, work, model, limit, normal_speed=True)
        run['stderr'] = notice + '\n' + run['stderr']
        return run
    return {'thread': thread, 'files': files, 'errors': errors, 'said': said, 'stderr': err[-1500:], 'exit': proc.returncode,
            'timed_out': timed_out, 'seconds': round(time.monotonic() - begun, 1)}


def _model_refused(run):
    text = ' '.join(run['errors']) + ' ' + run['stderr']
    return bool(re.search(r'model[^.\n]{0,60}(not supported|does not exist|not available|not found|unsupported|no access)', text, re.I))


def _why_no_image(run, name):
    """A plain message for a run that left no file, and what kind of failure it was."""
    reason = _session_failure(run.get('thread'))
    errors = ' '.join(run['errors'])
    if reason and 'usageLimitExceeded' in reason:
        return 'limit', f"{name} has hit its image limit. Its own words: {reason}"
    for text in (errors, run['stderr'], ' '.join(run['said'])):
        if ai_clis.LIMIT.search(text):
            return 'limit', ai_clis.limit_line(text) or f'{name} has hit its usage limit.'
    kind = ai_clis.failure_kind(errors + '\n' + run['stderr'])
    if kind == 'signin':
        return 'signin', f'{name} is not signed in, so it could not draw.'
    if run.get('timed_out'):
        return 'timeout', f'{name} did not finish a picture within {RUN_LIMIT_S} s, so that run was stopped.'
    if re.search(r'unable to read referenced image', errors + run['stderr'], re.I):
        return 'reference', f'{name} could not read a reference image.'
    if reason:
        return 'failed', f'{name} could not draw it. Its own words: {reason}'
    return 'no_image', f"{name} finished without saving a picture."


def _draw_other(found, words, refs, transparent, count, side, meta, project, model=None):
    """count pictures, up to AT_ONCE runs at a time, each a separate run. Files are counted; what the AI says isn't trusted."""
    exe, by, name = found['exe'], found['by'], found['name']
    work = side / 'work'
    work.mkdir(parents=True, exist_ok=True)
    prompt = _exec_prompt(words, refs, transparent)
    model = model or os.environ.get('LETITEDIT_IMAGE_CODEX_MODEL') or DEFAULT_CODEX_MODEL
    deadline = time.monotonic() + CALL_LIMIT_S
    results, stop = [], threading.Event()
    lock = threading.Lock()
    todo = list(range(count))

    def worker():
        while not stop.is_set():
            with lock:
                if not todo or time.monotonic() > deadline:
                    return
                todo.pop()
            limit = min(RUN_LIMIT_S, max(30, deadline - time.monotonic()))
            run = _run_codex(exe, prompt, refs, work, model, limit)
            if not run['files'] and _model_refused(run):      # that model isn't on their plan: the person's own default
                run = _run_codex(exe, prompt, refs, work, None, limit)
            kind = said = None
            if not run['files']:
                kind, said = _why_no_image(run, name)
                if kind in ('limit', 'signin'):
                    stop.set()
                    if kind == 'limit':
                        _note_limit(by, said)
            with lock:
                results.append(dict(run, kind=kind, why=said))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(AT_ONCE, count))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(CALL_LIMIT_S + RUN_LIMIT_S + 30)
    images, failed = [], []
    with lock:
        finished = list(results)
    for run in finished:
        for path in run['files']:
            images.append(file_image(path, side, dict(meta, made_by={'route': 'other', 'program': name, 'maker': 'openai', 'thread': run['thread'],
                                                                     'seconds': run['seconds']}), project))
        if not run['files']:
            failed.append({'kind': run['kind'], 'message': run['why'], 'seconds': run['seconds'],
                           'exit': run['exit'], 'said': run['said'][-1:], 'errors': run['errors'][-2:], 'stderr_tail': run['stderr'][-300:]})
    return images, failed


# ---------------------------------------------------------------- drawing: an AI that runs only on screen

def _show_conversation(params, project):
    """Asks the letitedit window showing this video to run a labelled conversation in its panel. False when there is no window that can."""
    import letitedit.app.letitedit_instances as inst
    from letitedit.app.letitedit_client import ShotcutBridge
    try:
        rows = inst.list_instances()
    except Exception:  # noqa: BLE001 - no window
        return False

    def same(a, b):
        return bool(a and b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    row = next((r for r in rows if same(r.get('project'), project)), None) \
        or next((r for r in rows if r['instance_id'] == os.environ.get('LETITEDIT_INSTANCE')), None) or (rows[0] if len(rows) == 1 else None)
    if not row:
        return False
    try:
        with inst.scope(row['instance_id']), ShotcutBridge(timeout=30) as bridge:
            return bool(bridge.call('chat_review', params).get('started'))
    except Exception:  # noqa: BLE001 - an older window, or one that went away
        return False


def _draw_visible(found, words, refs, transparent, count, shape, side, meta, project, driver=None):
    """Pictures from an AI that runs only on screen: one labelled conversation in the panel, one prompt per picture. The window starts it;
    this hands over the request and waits for done.json. Paths come from the tool calls, and never from what the AI says."""
    by, name = found['by'], found['name']
    out = side / 'work' / f'draw-{uuid.uuid4().hex[:8]}'
    out.mkdir(parents=True, exist_ok=True)
    copies = []
    for n, ref in enumerate(refs[:GOOGLE_REFERENCES]):
        copy = out / f'reference-{n + 1}{Path(ref).suffix.lower()}'
        shutil.copyfile(ref, copy)
        copies.append(str(copy))
    how = [f'Use your generate_image tool exactly once, then stop. Run nothing else and change no files. ImageName: letitedit_picture. AspectRatio: {SHAPES.get(shape, "16:9")}.']
    if copies:
        how.append('ImagePaths: ' + json.dumps(copies))
    if transparent:
        how.append('You cannot make a transparent picture: put the subject on one flat, pure green background with no shadow.')
    how.append('Prompt: ' + words)
    prompt = '\n'.join(how)
    request = out / 'request.md'
    request.write_text(prompt, encoding='utf-8')
    request.with_suffix('.json').write_text(json.dumps({'prompts': [prompt] * count}), encoding='utf-8')
    asking = ai_clis.NAMES.get(driver or '', 'your AI')
    label = f'{name} is drawing {"a picture" if count == 1 else f"{count} pictures"} for {asking}, on your own plan:'
    answer = out / 'done.json'
    began = time.monotonic()
    shown = _show_conversation({'request': str(request), 'out': str(out), 'answer': answer.name, 'label': label, 'mode': 'draw', 'engine': by}, project)
    if not shown:
        return [], [{'kind': 'no_window', 'message': f'{name} draws only in a conversation you can see, and no letitedit window could show one (none is open for this '
                                                     'video, or another conversation is running there).', 'seconds': 0}]
    result = None
    deadline = began + CALL_LIMIT_S + RUN_LIMIT_S * count
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            result = json.loads(answer.read_text(encoding='utf-8-sig'))
            break
        except (OSError, ValueError):
            continue
    if result is None:
        return [], [{'kind': 'timeout', 'message': f'{name} did not finish in time.', 'seconds': round(time.monotonic() - began)}]
    seconds = round(time.monotonic() - began, 1)
    images = [file_image(path, side, dict(meta, made_by={'route': 'other', 'program': name, 'maker': _maker_of_program(by), 'seconds': seconds}), project)
              for path in result.get('pictures') or [] if Path(path).is_file()]
    failed = []
    if result.get('error'):      # the person closed the conversation, or it ended early
        failed.append({'kind': result.get('error_kind') or 'failed', 'message': f"{name}'s conversation was closed before it finished.", 'seconds': seconds})
    elif result.get('failure'):
        kind = result['failure']
        if kind == 'limit':
            _note_limit(by, result.get('message'))
        failed.append({'kind': kind, 'message': result.get('message'), 'seconds': seconds})
    elif len(images) < count:
        failed.append({'kind': 'no_image', 'message': f"{name} finished with {len(images)} of {count} pictures.", 'seconds': seconds})
    return images, failed


# ---------------------------------------------------------------- drawing: the person's own key

def _api_base():
    return os.environ.get('LETITEDIT_IMAGE_OPENAI_URL') or 'https://api.openai.com/v1'


def _api_size(shape, size, transparent):
    if size:
        m = re.fullmatch(r'(\d+)x(\d+)', str(size))
        if not m:
            raise ValueError(f'size {size!r}: give it as WIDTHxHEIGHT, for example 2048x1152')
        w, h = int(m.group(1)), int(m.group(2))
        if not transparent and (max(w, h) > 3840 or w % 16 or h % 16 or max(w, h) / min(w, h) > 3 or not 655360 <= w * h <= 8294400):
            raise ValueError(f'size {size}: gpt-image-2 needs both sides multiples of 16, at most 3840, at most 3:1, and 655,360 to 8,294,400 pixels')
        return str(size)
    if transparent:         # gpt-image-1.5's sizes
        return {'wide': '1536x1024', 'tall': '1024x1536', 'square': '1024x1024'}[shape]
    return {'wide': '2048x1152', 'tall': '1152x2048', 'square': '1024x1024'}[shape]


def _multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for key, value in fields.items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode('utf-8'))
    for key, path in files:
        name = Path(path).name
        kind = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(Path(path).suffix.lower(), 'application/octet-stream')
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\nContent-Type: {kind}\r\n\r\n'.encode('utf-8'))
        body.write(Path(path).read_bytes())
        body.write(b'\r\n')
    body.write(f'--{boundary}--\r\n'.encode('utf-8'))
    return body.getvalue(), f'multipart/form-data; boundary={boundary}'


def _api_error(code, body, name):
    try:
        said = (json.loads(body).get('error') or {}).get('message') or ''
    except (ValueError, AttributeError):
        said = ''
    said = re.sub(r'sk-[A-Za-z0-9_\-]{6,}', '[key]', str(said))[:300]
    if code in (401, 403):
        return 'key', f'{name} refused this API key. {said}'.strip()
    if code == 429:
        return 'limit', f'{name} says this key is over its limit or out of credit. {said}'.strip()
    return 'failed', f'{name} could not draw it (HTTP {code}). {said}'.strip()


def _draw_key(found, words, refs, mask, count, shape, size, quality, transparent, side, meta, project):
    maker, name = found['by'], found['name']
    key = _key(maker)
    model = 'gpt-image-1.5' if transparent else 'gpt-image-2'
    try:
        fields = {'model': model, 'prompt': words, 'n': int(count), 'size': _api_size(shape, size, transparent)}
    except ValueError as exc:
        return [], [{'kind': 'size', 'message': str(exc)}]
    if quality:
        fields['quality'] = quality
    if transparent:
        fields.update(background='transparent', output_format='png')
    if refs:
        files = [('image[]', p) for p in refs] + ([('mask', mask)] if mask else [])
        data, kind = _multipart(fields, files)
        url = _api_base() + '/images/edits'
    else:
        data, kind = json.dumps(fields).encode('utf-8'), 'application/json'
        url = _api_base() + '/images/generations'
    req = urllib.request.Request(url, data=data, headers={'Authorization': f'Bearer {key}', 'Content-Type': kind})
    begun = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=API_LIMIT_S) as res:
            answer = json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        with exc:
            kind, said = _api_error(exc.code, exc.read().decode('utf-8', 'replace'), name)
        if kind == 'limit':
            _note_limit(maker, said)
        return [], [{'kind': kind, 'message': said}]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        reason = str(getattr(exc, 'reason', exc))
        return [], [{'kind': 'network', 'message': f'{name} could not be reached: {reason}'[:300]}]
    work = side / 'work'
    work.mkdir(parents=True, exist_ok=True)
    images = []
    for row in answer.get('data') or []:
        raw = row.get('b64_json')
        if not raw:
            continue
        tmp = work / f'{uuid.uuid4().hex}.png'
        tmp.write_bytes(base64.b64decode(raw))
        images.append(file_image(tmp, side, dict(meta, made_by={'route': 'key', 'program': name, 'maker': maker, 'model': model,
                                                                'seconds': round(time.monotonic() - begun, 1)}), project))
        tmp.unlink(missing_ok=True)
    return images, ([] if images else [{'kind': 'no_image', 'message': f'{name} answered with no picture.'}])


# ---------------------------------------------------------------- drawing: the AI's own tool

def _ask_own(words, refs, meta, side, count, by='codex', shape='wide', transparent=False):
    """The AI driving has its own image tool: it draws in its own session, then asks for the result to be filed."""
    request = uuid.uuid4().hex[:10]
    (side / 'requests').mkdir(parents=True, exist_ok=True)
    (side / 'requests' / f'{request}.json').write_text(json.dumps({'request': request, 'time': time.time(), 'meta': meta, 'count': count}), encoding='utf-8')
    if ai_clis.visible_only(by):
        how = ('One call, one picture. Takes Prompt, ImageName, AspectRatio (' + SHAPES.get(shape, '16:9') + ') and ImagePaths (up to '
               f'{GOOGLE_REFERENCES} absolute paths). ' + GOOGLE_FACTS)
        if transparent:
            how += ' Put the subject on one flat, pure green background with no shadow.'
        return {'made': 0, 'route': 'own', 'request': request, 'draw_with': 'generate_image', 'words': words, 'referenced_image_paths': refs[:GOOGLE_REFERENCES],
                'how_the_tool_works': how, 'then': f"letitedit_image(action='file', request='{request}') files what you made beside the video and returns it."}
    return {'made': 0, 'route': 'own', 'request': request, 'draw_with': 'image_gen__imagegen', 'words': words, 'referenced_image_paths': refs,
            'how_the_tool_works': 'One call, one picture. In exec: the first-line @exec directive for 120 s, and generatedImage(result) shows you '
                                  'the picture. referenced_image_paths takes absolute paths.',
            'then': f"letitedit_image(action='file', request='{request}') files what you made beside the video and returns it."}


def _own_store(by, settings):
    """Where this AI's own image tool saves its pictures, and what they are called."""
    if ai_clis.visible_only(by):
        return ai_clis.profile(by, settings) / 'antigravity-acp' / 'brain', '*.jpg'
    return image_store(), '*.png'


def file_own(request=None, path=None, thread=None, project=None, folder=None, character=None):
    """File what the AI's own image tool made: named by path, or the new files of its thread since the request."""
    settings = ai_clis.chat_settings()
    by = ai_clis.editor(settings) or 'codex'
    by = by if by in DRAWERS else 'codex'
    side = side_folder(project, folder)
    if side is None:
        return {'made': 0, 'failure': 'no_project', 'message': 'Give project (or folder), so the picture has somewhere to go.'}
    req = {}
    if request:
        try:
            req = json.loads((side / 'requests' / f'{request}.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return {'made': 0, 'failure': 'request', 'message': f'There is no request {request!r} for this video.'}
    rows = history(project, folder)
    filed = {r.get('source', '').lower() for r in rows}
    notes = []
    if path:
        if not Path(path).is_file():
            return {'made': 0, 'failure': 'no_file', 'message': f'There is no file at {path}.'}
        same = next((r for r in rows if r.get('source', '').lower() == str(path).lower()), None)
        if same:        # a retry after a reply that got cut off: the same picture, not a second copy
            return {'made': 0, 'route': 'own', 'images': [same], 'already_filed': True, 'message': f"That picture is already filed as {same['id']}."}
        new = [Path(path)]
    else:
        since = req.get('time', time.time() - 900) - 5
        thread = thread or os.environ.get('CODEX_THREAD_ID')
        store, pattern = _own_store(by, settings)
        folders = [store / thread] if thread else (sorted(p for p in store.iterdir() if p.is_dir()) if store.is_dir() else [])
        fresh = {}
        for d in folders:
            found = [p for p in d.glob(pattern) if p.stat().st_mtime >= since and str(p).lower() not in filed] if d.is_dir() else []
            if found:
                fresh[d] = found
        if len(fresh) > 1:         # another session is drawing too: the newest is the likeliest, and the reply shows it
            newest = max(fresh, key=lambda d: max(p.stat().st_mtime for p in fresh[d]))
            notes.append(f'Several {ai_clis.NAMES[by]} sessions drew since this request; these came from the newest, {newest.name}. Check the picture, or pass thread=.')
            fresh = {newest: fresh[newest]}
        new = sorted((p for files in fresh.values() for p in files), key=lambda p: p.stat().st_mtime)
    if not new:
        return {'made': 0, 'failure': 'no_file', 'message': 'No new picture from your image tool has been saved since this request.'}
    meta = dict(req.get('meta') or {'prompt': None})
    if character:
        meta['character'] = character
    images = [file_image(p, side, dict(meta, made_by={'route': 'own', 'program': ai_clis.NAMES[by], 'maker': _maker_of_program(by), 'thread': p.parent.name}), project) for p in new]
    _log(side, {'route': 'own', 'request': request, 'made': len(images), 'files': [i['path'] for i in images]})
    return {'made': len(images), 'route': 'own', 'images': images, 'notes': notes, 'made_by': f"{ai_clis.NAMES[by]}, on the person's own sign-in."}


# ---------------------------------------------------------------- the one way in

def make(prompt=None, project=None, folder=None, references=None, characters=None, edit=None, count=1, shape='wide', transparent=False,
         character=None, size=None, quality=None, mask=None, maker='auto', settings=None, driver=None):
    """See DOC. Never raises for a failed image: the reply's `made` counts the files and `message` says what happened."""
    side = side_folder(project, folder)
    if side is None:
        return {'made': 0, 'failure': 'no_project', 'message': 'Give project (or folder), so the picture has somewhere to go.'}
    if not str(prompt or '').strip():
        return {'made': 0, 'failure': 'no_words', 'message': 'Give prompt: the words for the picture.'}
    if shape not in SHAPES:
        return {'made': 0, 'failure': 'shape', 'message': f'shape is one of {", ".join(SHAPES)}.'}
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    if count < 1 or count > MAX_COUNT:
        return {'made': 0, 'failure': 'count', 'message': f'count is 1 to {MAX_COUNT}.'}
    refs, problem, notes = _resolve_references(references, characters, edit, prompt, project, folder)
    if problem:
        _log(side, {'route': None, 'prompt': prompt, 'made': 0, 'failure': 'reference', 'message': problem})
        return {'made': 0, 'failure': 'reference', 'message': problem}
    if mask and not Path(mask).is_file():
        return {'made': 0, 'failure': 'reference', 'message': f'This mask is not there: {mask}. Nothing was drawn.'}
    settings = ai_clis.chat_settings() if settings is None else settings
    found = routes(settings, driver)
    choices = found['routes']
    if maker != 'auto':
        choices = [r for r in choices if r['route'] == maker]
    if not choices:
        message = _nobody(found) if maker == 'auto' else f'{maker} cannot draw here right now. ' + _nobody(found)
        _log(side, {'route': None, 'prompt': prompt, 'made': 0, 'failure': 'nobody', 'message': message})
        return {'made': 0, 'route': 'none', 'failure': 'nobody', 'message': message}
    pick = choices[0]
    words = _words(prompt, shape, transparent, refs, edit)
    meta = {'prompt': str(prompt), 'words': words, 'references': refs, 'shape': shape, 'transparent': bool(transparent), 'edit_of': str(edit) if edit else None}
    if character:
        meta['character'] = str(character)
    limited = ai_clis.visible_only(pick.get('by')) and pick['route'] != 'key'
    if limited and transparent:
        notes.append('This AI has no real transparency: the picture comes on a flat green, which a key has to allow for, and it is a JPEG.')
    if limited and len(refs) > GOOGLE_REFERENCES:
        notes.append(f'This AI takes up to {GOOGLE_REFERENCES} reference images, so the first {GOOGLE_REFERENCES} were used.')
    if pick['route'] == 'own':
        return _ask_own(words, refs, meta, side, count, pick['by'], shape, transparent) | ({'notes': notes} if notes else {})
    began = time.monotonic()
    _log(side, {'route': pick['route'], 'by': pick['by'], 'prompt': prompt, 'count': count, 'state': 'drawing'})
    try:
        if pick['route'] == 'key':
            images, failed = _draw_key(pick, words, refs, mask, count, shape, size, quality, transparent, side, meta, project)
        elif ai_clis.visible_only(pick['by']):
            images, failed = _draw_visible(pick, words, refs, transparent, count, shape, side, meta, project, found.get('driving'))
        else:
            images, failed = _draw_other(pick, words, refs, transparent, count, side, meta, project)
    except Exception as exc:  # noqa: BLE001 - a failed image must never end a video
        images, failed = [], [{'kind': 'failed', 'message': f"{pick['name']} could not draw it: {exc}"[:400]}]
    if pick['route'] == 'other' and (size or quality or mask):
        notes.append('size, quality and mask only apply to an API key; this one came from the program, whose tool has none of them.')
    reply = {'made': len(images), 'route': pick['route'], 'by': pick['name'], 'images': images, 'seconds': round(time.monotonic() - began, 1),
             'made_by': f"{pick['name']} drew this, on the person's own " + ('API key.' if pick['route'] == 'key' else 'sign-in.')}
    if notes:
        reply['notes'] = notes
    if failed:
        reply['failed'] = failed
        first = failed[0]
        reply['failure'] = first.get('kind')
        reply['message'] = (f"{len(images)} of {count} made. " if images else 'No picture was made. ') + str(first.get('message')) + \
            ' Whatever is missing can be drawn in code.'
    _log(side, {'route': pick['route'], 'by': pick['by'], 'prompt': prompt, 'made': len(images), 'failed': failed, 'files': [i['path'] for i in images]})
    return reply


# ---------------------------------------------------------------- pictures for the AI

def preview(path, long_edge=1024):
    """A small JPEG of a picture for the AI to see; see-through parts show on a checkerboard."""
    from PIL import Image, ImageDraw
    with Image.open(path) as im:
        im = im.convert('RGBA')
        im.thumbnail((long_edge, long_edge), Image.LANCZOS)
        back = Image.new('RGBA', im.size, (128, 128, 128, 255))
        d = ImageDraw.Draw(back)
        for y in range(0, im.height, 16):
            for x in range(0, im.width, 16):
                if (x // 16 + y // 16) % 2:
                    d.rectangle((x, y, x + 15, y + 15), fill=(170, 170, 170, 255))
        back.alpha_composite(im)
        buf = io.BytesIO()
        back.convert('RGB').save(buf, 'JPEG', quality=85)
    return buf.getvalue()


def _brief(row):
    """An image's row in a reply: what a caller needs, without the bookkeeping."""
    keep = ('id', 'path', 'url', 'size', 'alpha', 'prompt', 'character', 'video_size', 'scale_to_fill', 'fit_path', 'edit_item', 'made_by', 'created', 'shape')
    out = {k: row[k] for k in keep if k in row}
    scale = row.get('scale_to_fill')
    if scale and scale > 1.001:
        size, video = row['size'], row['video_size']
        out['scale_note'] = f'{size[0]}x{size[1]} on this {video[0]}x{video[1]} video: filling the frame scales it up {round((scale - 1) * 100)}%.'
    return out


DOC = """Pictures for a video: a plate, a character, a prop, an edit of a picture, drawn by whichever AI or key on this PC can draw.
Every picture is kept in <video>.letitedit\\images, marked as generated, with the words that made it.

action 'status': who draws here and what each can do. action 'make' (default): prompt (the words), project (a .mlt, which needn't
exist yet) or folder; references (up to 5 image paths or ids), characters (names of saved character sheets), edit (a path or id: change
only what the words ask), count (1-6, default 1), shape (wide, tall, square; default wide), transparent, character (save this picture as
the character sheet of that name), maker (auto, own, key, other). action 'history': what was made for this video, oldest first.
action 'show': id -> the picture. action 'file': own route only, see below.

Who draws, in order: the AI driving, if it has its own image tool; the person's own image API key, if they added one (paid per image by
them); another AI on this PC that can draw, if the person turned that on (it runs on their own plan, as a separate run of their own
program, or as a labelled conversation in the panel for an AI that only runs on screen; that one needs a letitedit window open). Otherwise
nothing can draw: made is 0, message says so, and pictures can be drawn in code.

route 'other' (one picture per run, 30-60 s each, three at once, started 2 s apart): no size, quality, mask or count setting. Wide usually gives 1672x941, tall 941x1672 (once 1051x1497), transparent 1024x1536 or 941x1672 with real
alpha; words asking for 4K change nothing. route 'key' (OpenAI): size (multiples of 16, up to 3840), quality, mask; default 2048x1152 or
1152x2048; transparent uses gpt-image-1.5 at 1536x1024 or 1024x1536.
route 'own': this reply draws nothing; it gives the words and paths for your own image tool, and a request id. Draw, then
action='file', request=<id> files the new pictures and gives their details; path= names a file, thread= a session. generatedImage(result)
in your exec call is what shows you the picture; action 'show' returns it too.

Each image in the reply: id, path, url (a file:// address for a scene), size, alpha, video_size, scale_to_fill (above 1 means filling the
frame scales it up), fit_path (a smooth copy at the video's size, when the shape matches), edit_item (a timeline insert; add track and at), and the
picture itself. A named character's sheet is attached whenever the words name them. Reference paths are checked before anything runs.
made counts files on disk, never what an AI says it made.

Antigravity's own tool: JPEG, about 1 megapixel (wide 1376x768, tall 768x1376, square 1024x1024), up to 3 references, no transparency.

A failed picture never ends the call badly: made is lower than count, failure is its kind (limit, signin, timeout, reference, nobody,
key, network, no_image, no_window) and message says what happened. After a limit the maker isn't asked again for 15 minutes.

OpenAI's Usage Policies bar someone's likeness without their consent; its sharing policy asks that AI-made content is labelled.
letitedit_export_job and letitedit_review_bundle list what a video owes."""


def register(mcp, Image):
    @mcp.tool()
    def letitedit_image(action: str = 'make', prompt: str | None = None, project: str | None = None, folder: str | None = None,
                        references: list[str] | None = None, characters: list[str] | None = None, edit: str | None = None,
                        count: int = 1, shape: str = 'wide', transparent: bool = False, character: str | None = None,
                        size: str | None = None, quality: str | None = None, mask: str | None = None, maker: str = 'auto',
                        id: str | None = None, request: str | None = None, path: str | None = None, thread: str | None = None) -> list:
        def pictured(reply, rows):
            return [Image(data=preview(r['path']), format='jpeg') for r in rows if Path(r['path']).exists()] + [reply]

        if action == 'status':
            return [status()]
        if action == 'history':
            rows = history(project, folder)
            return [{'count': len(rows), 'images': [_brief(r) for r in rows]}]
        if action == 'show':
            row = _find_filed(str(id or path), project, folder)
            if not row:
                return [{'message': f'There is no picture {id or path!r} for this video.'}]
            return pictured(_brief(row), [row])
        if action == 'file':
            reply = file_own(request, path, thread, project, folder, character)
            # no picture here: its own tool showed it already, and in exec this reply is printed, so a picture is a wall of text
            return [reply | {'images': [_brief(r) for r in reply.get('images', [])]}]
        if action != 'make':
            return [{'message': "action is one of make, status, history, show, file."}]
        reply = make(prompt, project, folder, references, characters, edit, count, shape, transparent, character, size, quality, mask, maker)
        rows = reply.get('images', [])
        return pictured(reply | {'images': [_brief(r) for r in rows]} if rows else reply, rows)

    letitedit_image.__doc__ = DOC


def _main(argv):
    if '--status' in argv:
        print(json.dumps(status(), indent=1))
    elif '--history' in argv:
        print(json.dumps(history(argv[argv.index('--history') + 1]), indent=1))
    elif '--set-other-ai' in argv:
        path = Path(os.environ.get('LETITEDIT_CHAT_SETTINGS') or ai_clis.ROOT / 'chat' / 'panel.json')
        settings = ai_clis.chat_settings()
        if not path.exists():
            settings['view_mode'] = 'bubbles'    # a new install starts in chat bubbles (aiChatSaveSettings in the editor)
        settings[OTHER_AI_SETTING] = argv[argv.index('--set-other-ai') + 1] == 'on'
        path.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    elif '--set-key' in argv:
        set_key(argv[argv.index('--set-key') + 1], sys.stdin.read())
    elif '--clear-key' in argv:
        clear_key(argv[argv.index('--clear-key') + 1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
