"""Saved, revisioned code scenes for the live player and exact export.

The .mlt clip is a transparent, selectable marker with letitedit_ai:code_scene
{id, revision}. The source and generated page live beside the project, under
<stem>.letitedit/scenes/<id>/revisions/<hash>. A revision never changes in
place: timeline Undo restores its old hash and therefore its old picture.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import hashlib
import contextlib
import contextvars
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

import letitedit.timeline.edit_script as es
import letitedit.pictures.motion as motion

SCENE_PROP = es.SCENE_PROP
ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')


def home(project):
    path = es._resolve(project).resolve()
    return path.parent / (path.stem + '.letitedit') / 'scenes'


def scene_dir(project, scene_id):
    if not ID.fullmatch(str(scene_id)):
        raise ValueError('scene id must be 1-64 lower-case letters, digits, _ or -')
    return home(project) / scene_id


def revision_dir(project, scene_id, revision):
    if not re.fullmatch(r'[0-9a-f]{14}', str(revision)):
        raise ValueError('invalid scene revision')
    return scene_dir(project, scene_id) / 'revisions' / revision


def favorites_home():
    """The person's own scene shelf, independent of any project or installer."""
    roaming = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    return roaming / 'letitedit' / 'my-scenes'


def favorite_dir(favorite_id):
    if not ID.fullmatch(str(favorite_id)):
        raise ValueError('invalid saved scene id')
    return favorites_home() / favorite_id


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def _item(script, scene_id):
    for track in script['tracks']:
        for item in track['items']:
            if item.get('scene', {}).get('id') == scene_id:
                return track, item
    raise KeyError(f'no code scene {scene_id} on this timeline')


def _scene_id(script, given):
    """A scene id as given, or the scene of the timeline item whose id was given (T360: an AI passed the item's id,
    new-..., from status's `id` instead of its scene's)."""
    if not given:
        return given
    for track in script['tracks']:
        for item in track['items']:
            if item.get('scene', {}).get('id') == given:
                return given
    for track in script['tracks']:
        for item in track['items']:
            if item.get('id') == given and (item.get('scene') or {}).get('id'):
                return item['scene']['id']
    return given


def text_edits(spec, edits):
    """The script, html and css of a scene's spec after `edits`, [{old, new, in?}] (in: 'script' [default], 'html' or
    'css'), in order, each `old` found exactly once in the text as the edits before it left it. Returns {field: text}
    for the fields that changed. Raises ValueError naming the edit when one isn't found once (nothing is written)."""
    out = {}
    for n, edit in enumerate(edits or [], 1):
        if not isinstance(edit, dict) or not isinstance(edit.get('old'), str) or not isinstance(edit.get('new'), str):
            raise ValueError(f'edit {n}: each edit is {{old, new, in?}} with old and new as text')
        field = edit.get('in') or 'script'
        if field not in ('script', 'html', 'css'):
            raise ValueError(f"edit {n}: in is 'script', 'html' or 'css', not {field!r}")
        text = out.get(field, (spec or {}).get(field) or '')
        found = text.count(edit['old']) if edit['old'] else 0
        if found != 1:
            raise ValueError(f"edit {n}: its old text is found {found} times in the scene's {field}; it must be found "
                             'exactly once (code_scene action source shows the text). Nothing was changed.')
        out[field] = text.replace(edit['old'], edit['new'], 1)
    return out


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def _person_room(project, samples=6):
    """The room around the person, measured on the project's cut-out pieces (frame pixels), for a scene to compose to: the top
    of the person, the head's left and right at its widest, where the shoulders start, and the free strips and band those
    leave. {} when there are no pieces to measure or they can't be read."""
    import subprocess
    import numpy as np
    try:
        ffmpeg = _paths.CODE_ROOT / 'app' / 'ffmpeg.exe'
        text = Path(project).read_text(encoding='utf-8', errors='replace')
        files = sorted(set(re.findall(r'<property name="resource">([^<]*vfx-cutout-[^<]*\.mov)</property>', text)))
        files = [Path(f) for f in files]
        files = [f if f.is_absolute() else Path(project).parent / f for f in files]
        files = [f for f in files if f.is_file()]
        if not files:
            return {}
        picked = files[:: max(1, len(files) // samples)][:samples]
        layers, width, height = [], None, None
        for f in picked:
            probe = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(f), '-frames:v', '1', '-vf', 'alphaextract',
                                    '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True, timeout=60).stdout
            size = re.search(r'width="(\d+)"[^>]*height="(\d+)"', text) or re.search(r'name="width">(\d+).*?name="height">(\d+)', text, re.S)
            width, height = int(size.group(1)), int(size.group(2))
            if len(probe) == width * height:
                layers.append(np.frombuffer(probe, dtype=np.uint8) > 128)
        if not layers:
            return {}
        person = np.mean(layers, axis=0).reshape(height, width) > 0.5
        rows = np.where(person.any(axis=1))[0]
        if not len(rows):
            return {}
        top = int(rows[0])
        spread = [(int(y), int(np.where(person[y])[0][0]), int(np.where(person[y])[0][-1])) for y in rows]
        head = [s for s in spread if s[0] < top + 0.2 * height]
        y0, left, right = max(head, key=lambda s: s[2] - s[1])
        shoulders = next((s[0] for s in spread if s[0] > y0 and s[2] - s[1] > 1.35 * (right - left)), height)
        return {'pieces_measured': len(layers), 'frame': [width, height], 'person_top_y': top, 'head_widest_y': y0,
                'head_left_x': left, 'head_right_x': right, 'shoulders_y': shoulders, 'band_above_px': top,
                'strip_left_px': left, 'strip_right_px': width - 1 - right,
                'note': 'measured on one frame of each piece sampled; it moves as the person does'}
    except Exception as e:  # noqa: BLE001 - a fact the call can do without
        return {'error': f'{type(e).__name__}: {e}'[:200]}


# A file:/// address cut short or built from parts: only a whole address is copied beside the scene, and the live player needs that copy (T78).
_PART_ADDRESS = re.compile(r"""file:///[^'"`\s]*(?:/['"`]|\$\{|['"`]\s*\+)""", re.I)


def _script_text(script):
    """script is the scene's code, or the path of a file holding it. Only code handed in now passes here, never a saved scene."""
    if (isinstance(script, str) and '\n' not in script and len(script) < 1024 and 'M.block' not in script
            and re.search(r'[\\/]|\.(m?js|txt)\s*$', script)):
        file = Path(script.strip())
        if not file.is_file():
            raise ValueError(f"script is the scene's code, or the path of a file holding it; there is no file at {script}")
        script = file.read_text(encoding='utf-8')
    if isinstance(script, str):
        part = _PART_ADDRESS.search(script)
        if part:
            raise ValueError(f"a picture's file:/// address has to be written whole in the code, one string per picture, not built from parts ({part.group(0)}): "
                             "only a whole address is copied beside the scene, and the live player shows only those.")
    return script


def _spec(old, known=(), **changes):
    """known: drawing kits a saved copy provides, which may no longer be on this PC."""
    spec = dict(old or {})
    changes = {k: v for k, v in changes.items() if v is not None}
    if 'script' in changes:
        changes['script'] = _script_text(changes['script'])
    spec.update(changes)
    spec['block'] = 'custom'
    spec['format'] = 'mov'
    spec = motion.normalise(spec, known=known)
    if not re.search(r"\bM\s*\.\s*block\s*\(\s*(['\"])custom\1", spec['script']):
        raise ValueError("A Code scene must register M.block('custom', ...) with a frame function driven by t. "
                         "Browser-only animations do not follow the playhead or render reliably.")
    return spec


def _checked_page(folder, data, scene_id, revision):
    """The page to draw this revision from, proved to be what its id says: the id is recomputed from the scene's source and
    the runtime and kits its own page carries, so nothing outside the project matters. None: there is no usable page and
    this PC's files give the same id, so a page built now is the same. Refuses when the source really did change."""
    spec, width, height, fps = data['spec'], data['width'], data['height'], data['fps']
    page = folder / 'page'
    saved = motion.saved_parts(page, spec)
    if saved and motion.digest(spec, width, height, fps, saved=saved) == revision:
        return page
    try:
        if motion.digest(spec, width, height, fps) == revision:
            return None
    except (OSError, KeyError, ValueError):
        pass
    raise ValueError(f"code scene {scene_id}: this version's saved code was changed after it was made, so it can't be drawn "
                     "as saved (its revision does not match its source). An earlier version can be restored, or the scene revised.")


def _kept_note(saved, spec):
    """What a revision keeps from the version before it where this PC now has something else; plain facts for the reply."""
    differs = motion.differs_from_this_pc(saved, spec)
    if not differs:
        return {}
    gone = sorted(k for k, v in differs.items() if v == 'gone')
    changed = sorted(k for k, v in differs.items() if v == 'changed')
    words = (([f"{', '.join(gone)} (not on this PC; the project's own copy was used)"] if gone else [])
             + ([f"{', '.join(changed)} (this PC has a different one)"] if changed else []))
    return {'kept_from_this_scene': differs,
            'kept_note': 'This version was drawn with what the scene was made with, so the video keeps its look: ' + '; '.join(words)
                         + '. The action create draws a new scene with what is on this PC.'}


def _kept_kits(project, script):
    """Drawing kits a new scene names that are not on this PC: copies from this project's scenes, then My scenes."""
    wanted = [n for n in motion.looks_used({'script': script}) if n not in motion.hands()] if isinstance(script, str) else []
    found = {}
    if wanted:
        for source in [*home(project).glob('*/revisions/*/scene.json'), *favorites_home().glob('*/scene.json')]:
            with contextlib.suppress(OSError, ValueError, KeyError):
                parts = motion.saved_parts(source.parent / 'page', _json(source)['spec']) or {}
                for name in wanted:
                    if (parts.get('looks') or {}).get(name):
                        found.setdefault(name, parts['looks'][name])
    return found


def _new_revision(project, scene_id, spec, profile, saved=None, earlier=None):
    """saved, earlier: the runtime and kits to keep, and the page they came from (a revise keeps what the scene was made with)."""
    width, height, fps = profile['width'], profile['height'], profile['fps']
    revision = motion.digest(spec, width, height, fps, saved=saved)
    folder = revision_dir(project, scene_id, revision)
    source = folder / 'scene.json'
    if not source.exists():
        folder.mkdir(parents=True, exist_ok=True)
        _write(source, {'format': 'letitedit-code-scene/1', 'spec': spec,
                        'width': width, 'height': height, 'fps': fps,
                        'revision': revision})
        motion.build_page(spec, width, height, fps, folder / 'page', saved=saved, earlier=earlier)
    return revision, folder


def _upper_pass(project, track_name, output):
    """A transparent MLT copy with all video at/below Code scene hidden.
    MLT's caption filters remain on the tractor, so their alpha is included."""
    tree = ET.parse(project)
    root = tree.getroot()
    root.set('root', str(Path(project).resolve().parent))
    doc = es.Doc(project)
    main = next(e for e in root if e.get('id') == doc.main.get('id'))
    playlist_names = {e.get('id'): es._get(e, 'shotcut:name') for e in root if e.tag == 'playlist'}
    tracks = main.findall('track')
    scene_index = next((i for i, t in enumerate(tracks)
                        if playlist_names.get(t.get('producer')) == track_name), len(tracks) - 1)
    for i, t in enumerate(tracks):
        # Keep the transparent background track alive for the whole scene.
        # Hiding it makes MLT emit an opaque fallback after the last upper
        # clip ends, which punches the whole browser page away.
        if 0 < i <= scene_index:
            t.set('hide', 'video')
    black = next((e for e in root if e.get('id') == 'black'), None)
    if black is not None:
        es._set(black, 'resource', '0x00000000')
    tree.write(output, encoding='utf-8', xml_declaration=True)
    has_upper = any(i > scene_index and t.get('hide') not in ('video', 'both')
                    for i, t in enumerate(tracks))
    has_captions = any(es._get(f, 'mlt_service') in ('subtitle_feed', 'subtitle')
                       for f in main.findall('filter'))
    return has_upper or has_captions


def _replace_text(path, text):
    """Swap a file's whole text in one step, so a page that is open never reads half of it."""
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def _masks_dir(folder):
    """The folder holding this revision's finished mask set ('masks' for sets made by older builds)."""
    info = folder / 'upper-mask.json'
    name = _json(info).get('dir') if info.exists() else None
    return folder / 'page' / (name or 'masks')


def _drop_old_mask_sets(folder, keep):
    """Delete mask sets other than the ones named in keep (a page that is still open may use the previous one)."""
    for old in (folder / 'page').glob('masks*'):
        if old.is_dir() and old.name not in keep:
            shutil.rmtree(old, ignore_errors=True)


def _mask_page(folder, count, fps, masks_name='masks'):
    page = folder / 'page' / 'index.html'
    html = page.read_text(encoding='utf-8')
    script = f"""<!-- letitedit-upper-mask-start --><script>
// A cached alpha pass of tracks above this scene. MLT has already drawn those
// tracks under WebView2; taking their alpha out of the scene restores the order.
// The scene stays hidden until the mask of the frame in view has loaded, so it
// never covers them. Masks load around the playhead, not all at once.
const upperStage = document.getElementById('stage');
upperStage.style.visibility = 'hidden';
const upperMasks = new Map();
const upperMask = i => {{
  if (i < 0 || i >= {count}) return null;
  let image = upperMasks.get(i);
  if (!image) {{
    image = new Image();
    image.src = `{masks_name}/mask-${{String(i).padStart(4,'0')}}.png`;
    upperMasks.set(i, image);
  }}
  return image;
}};
let upperTime = 0, upperFrame = 0;
window.addEventListener('hf-seek', e => {{
  upperTime = e.detail.time;
  // Masks count from the scene's first frame on the timeline; a trimmed start makes the scene's own time run ahead of that.
  upperFrame = Number.isFinite(e.detail.frame) ? e.detail.frame : Math.round(upperTime * {float(fps):.8f});
  const index = upperFrame;
  if (upperMasks.size > 600)
    for (const k of upperMasks.keys()) if (k < index - 30 || k > index + 90) upperMasks.delete(k);
  for (let k = 1; k <= 45; k++) upperMask(index + k);
  const mask = upperMask(index);
  if (!mask || !mask.complete || !mask.naturalWidth) {{
    upperStage.style.visibility = 'hidden';
    if (mask) mask.onload = () => window.dispatchEvent(new CustomEvent('hf-seek', {{detail:{{time:upperTime, frame:upperFrame}}}}));
    return;
  }}
  const parts = upperStage.children;
  if (parts.length === 1 && parts[0].tagName === 'CANVAS') {{
    const canvas = parts[0], g = canvas.getContext('2d');
    g.save(); g.globalCompositeOperation = 'destination-out';
    g.drawImage(mask, 0, 0, canvas.width, canvas.height); g.restore();
  }} else {{
    // A scene made of page elements (or more than one canvas): mask the whole stage. An inline SVG mask, because a
    // CSS mask-image won't load from a local page. The picture swaps once decoded, so it never shows a gap.
    if (upperSvg().dataset.src !== mask.src) {{
      upperSvg().dataset.src = mask.src;
      const next = upperImages[upperFront ^ 1];
      next.setAttribute('href', mask.src);
      next.decode().catch(() => {{}}).then(() => {{
        if (upperSvg().dataset.src !== mask.src) return;
        next.setAttribute('visibility', 'visible');
        upperImages[upperFront].setAttribute('visibility', 'hidden');
        upperFront ^= 1;
        upperStage.style.mask = 'url(#letitedit-upper)';
        upperStage.style.visibility = '';
      }});
    }}
    return;
  }}
  upperStage.style.visibility = '';
}});
let upperFront = 0, upperImages = [], upperSvgNode = null;
function upperSvg() {{
  if (upperSvgNode) return upperSvgNode;
  const NS = 'http://www.w3.org/2000/svg', root = document.getElementById('root');
  const w = root.dataset.width, h = root.dataset.height;
  const made = (tag, values, parent) => {{
    const e = document.createElementNS(NS, tag);
    for (const k in values) e.setAttribute(k, values[k]);
    if (parent) parent.appendChild(e);
    return e;
  }};
  upperSvgNode = made('svg', {{width: 0, height: 0, style: 'position:absolute'}});
  const m = made('mask', {{id: 'letitedit-upper', maskUnits: 'userSpaceOnUse', maskContentUnits: 'userSpaceOnUse',
                           x: 0, y: 0, width: w, height: h}}, upperSvgNode);
  made('rect', {{x: 0, y: 0, width: w, height: h, fill: 'white'}}, m);
  // The mask pictures are white with the upper tracks' alpha: drawn black, they take those shapes out of the white.
  for (let i = 0; i < 2; i++)
    upperImages.push(made('image', {{x: 0, y: 0, width: w, height: h, preserveAspectRatio: 'none', visibility: 'hidden',
                                     style: 'filter:brightness(0)'}}, m));
  root.appendChild(upperSvgNode);
  return upperSvgNode;
}}
</script><!-- letitedit-upper-mask-end -->
"""
    html = re.sub(r'<!-- letitedit-upper-mask-start -->.*?<!-- letitedit-upper-mask-end -->',
                  '', html, flags=re.S)
    _replace_text(page, html.replace('</body></html>', script + '</body></html>'))


def _remove_mask_page(folder):
    page = folder / 'page' / 'index.html'
    html = page.read_text(encoding='utf-8')
    clean = re.sub(r'<!-- letitedit-upper-mask-start -->.*?<!-- letitedit-upper-mask-end -->',
                   '', html, flags=re.S)
    if clean != html:
        _replace_text(page, clean)


def _upper_fingerprint(project, track_name, start, count):
    """Hash only upper picture and captions, independent of MLT snapshot IDs.
    This stays stable across a live editor snapshot and a saved project."""
    script = es.read(project)
    names = [t['name'] for t in script['tracks']]
    index = names.index(track_name) if track_name in names else len(names) - 1
    upper = [t for t in script['tracks'][index + 1:]
             if t['kind'] == 'video' and t.get('hide') not in ('video', 'both')]
    refs = []
    for track in upper:
        for item in track['items']:
            if item.get('clip') and Path(item['clip']).is_file():
                stat = Path(item['clip']).stat()
                refs.append((item['clip'], stat.st_size, stat.st_mtime_ns))
    value = {'mask_version': 2, 'start': start, 'frames': count, 'profile': script['profile'],
             'upper': upper, 'captions': script.get('captions'), 'sources': refs}
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@contextlib.contextmanager
def _mask_lock(folder):
    """Serialize one scene's cache across the app helper and an AI edit."""
    import msvcrt
    path = folder.parent.parent / 'upper-mask.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + 120
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f'upper alpha for {folder.parent.parent.name} stayed busy') from None
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class Superseded(RuntimeError):
    """A newer edit changed what is above the scene while its masks were being drawn."""


MASK_CHUNK = 90  # frames drawn per melt run; the render lock is let go between runs


def prepare_upper_masks(project, track_name, start_s, spec, profile, folder,
                        previous=None, current=None, copy_only=False, progress=None):
    """current: optional function returning the fingerprint of the project as it is now; when it differs from the
    one this run started with, the run stops at the next chunk (Superseded) and leaves the old set in place.
    progress: optional function(done, of, old_set) called when a set has to be drawn and after each chunk."""
    with _mask_lock(folder):
        return _prepare_upper_masks(project, track_name, start_s, spec, profile, folder, previous, current, copy_only,
                                    progress)


def _prepare_upper_masks(project, track_name, start_s, spec, profile, folder,
                         previous=None, current=None, copy_only=False, progress=None):
    """Cache upper-track alpha for this scene. Code-only revisions copy it; changing the surrounding timeline
    requires regenerating the cache. A set is written whole into its own folder and the page is pointed at it in
    one step, so a player never reads a half-written set; the old set stays until then (unless the scene moved)."""
    fps = float(profile['fps'])
    start = round(float(start_s) * fps)
    count = max(1, round(spec['duration'] * fps))
    page = folder / 'page'
    fingerprint = _upper_fingerprint(project, track_name, start, count)
    current_info = folder / 'upper-mask.json'
    old = _json(current_info) if current_info.exists() else {}
    if old.get('fingerprint') == fingerprint:
        # A page made by an earlier build keeps its masks but gets today's script (it let a page-element scene cover
        # the person, and loaded every mask at once).
        if old.get('frames') and page.joinpath('index.html').is_file():
            if 'upperFrame' not in page.joinpath('index.html').read_text(encoding='utf-8'):
                _mask_page(folder, old['frames'], fps, old.get('dir') or 'masks')
        return {'frames': count, 'cached': True}
    if copy_only:
        previous_info = previous / 'upper-mask.json' if previous else None
        if not (previous_info and previous_info.exists() and _json(previous_info).get('fingerprint') == fingerprint):
            return {'deferred': True}   # nothing to copy: the window draws them when the scene is played
    # An earlier set can stand in while the new one is drawn only if it covers these same frames.
    old_set = bool(old.get('frames')) and old.get('start') == start and old.get('frames') == count
    report = (lambda done: progress(done, count, old_set)) if progress else (lambda done: None)
    report(0)   # before the page changes: the window hides the scene first when there is nothing to stand in
    if old.get('frames') and (old.get('start') != start or old.get('frames') != count):
        _remove_mask_page(folder)  # the scene moved or changed length: the old set would be the wrong frames
    set_name = 'masks-' + fingerprint[:12]
    work = folder / 'mask-work'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(exist_ok=True)
    upper = work / 'upper.mlt'
    part = page / (set_name + '.part')
    shutil.rmtree(part, ignore_errors=True)
    try:
        if not _upper_pass(project, track_name, upper):
            _remove_mask_page(folder)
            _drop_old_mask_sets(folder, keep=())
            _write(current_info, {'fingerprint': fingerprint, 'start': start, 'frames': 0})
            return {'frames': 0, 'cached': True}
        previous_info = previous / 'upper-mask.json' if previous else None
        if previous_info and previous_info.exists() and _json(previous_info).get('fingerprint') == fingerprint:
            shutil.copytree(_masks_dir(previous), part)
            bytes_total = sum(f.stat().st_size for f in part.glob('*.png'))
            cached = True
        else:
            bytes_total = _draw_masks(upper, start, count, profile, part, work, folder, fingerprint, current, report)
            cached = False
        final = page / set_name
        shutil.rmtree(final, ignore_errors=True)
        os.replace(part, final)
        _mask_page(folder, count, fps, set_name)
        _write(current_info, {'fingerprint': fingerprint, 'start': start, 'frames': count,
                              'bytes': bytes_total, 'dir': set_name})
        _drop_old_mask_sets(folder, keep=(set_name, old.get('dir') or 'masks'))
        return {'frames': count, 'bytes': bytes_total, 'cached': cached}
    finally:
        shutil.rmtree(part, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def _draw_masks(upper, start, count, profile, out_dir, work, folder, fingerprint, current, report=lambda done: None):
    """Draw the upper tracks with melt, MASK_CHUNK frames at a time, taking the PC render lock for each run only,
    and save each frame's alpha at half size into out_dir."""
    width, height = int(profile['width']), int(profile['height'])
    half = (width // 2, height // 2)
    root = _paths.CODE_ROOT
    melt = Path(os.environ.get('LETITEDIT_APP', str(root / 'app'))) / 'melt.exe'
    out_dir.mkdir(parents=True, exist_ok=True)
    # One run's raw frames are width x height x 4 bytes each (about 750 MB for 90 frames at 1080x1920). They go in the
    # PC's temp folder (never the project's folder, which may be synced to a drive) and a run is made smaller when the
    # temp drive has less than four times that free.
    temp = Path(tempfile.gettempdir())
    frame_bytes = width * height * 4
    chunk = max(5, min(MASK_CHUNK, int(shutil.disk_usage(temp).free // 4 // frame_bytes)))
    raw = temp / f'letitedit-mask-{os.getpid()}-{uuid.uuid4().hex[:8]}.raw'
    try:
        _draw_runs(upper, start, count, profile, out_dir, folder, fingerprint, current, chunk, raw, half, melt, report)
    finally:
        raw.unlink(missing_ok=True)
    return sum(f.stat().st_size for f in out_dir.glob('*.png'))


_MELT_RUNNING = threading.Event()   # the helper's watcher waits for this run to end before it stops the helper
_RAW_FILE = [None]


def _stop_with_window(pid):
    """A helper started by a window doesn't outlive it: without this it went on taking turns of the PC lock for minutes
    (and held this scene's mask lock) after the window had closed."""
    import letitedit.core.render_lock as render_lock

    def watch():
        while render_lock.pid_alive(pid):
            time.sleep(2)
        while _MELT_RUNNING.is_set():
            time.sleep(0.5)
        if _RAW_FILE[0]:
            Path(_RAW_FILE[0]).unlink(missing_ok=True)
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


def _draw_runs(upper, start, count, profile, out_dir, folder, fingerprint, current, chunk, raw, half, melt,
               report=lambda done: None):
    import numpy as np
    from PIL import Image
    import letitedit.core.render_lock as render_lock
    width, height = int(profile['width']), int(profile['height'])
    for first in range(0, count, chunk):
        n = min(chunk, count - first)
        if first and current is not None and current() != fingerprint:
            raise Superseded(folder.parent.parent.name)
        raw.unlink(missing_ok=True)
        _RAW_FILE[0] = raw
        command = [str(melt), '-quiet', str(upper), f'in={start + first}', f'out={start + first + n - 1}',
                   '-consumer', f'avformat:{raw}', 'f=rawvideo', 'vcodec=rawvideo', 'pix_fmt=rgba',
                   'an=1', 'real_time=-1', 'threads=4']
        with render_lock.slot(f'code scene upper alpha {folder.parent.parent.name}',
                              caller_pids=render_lock.ancestors()):
            _MELT_RUNNING.set()
            try:
                result = subprocess.run(command, cwd=melt.parent, capture_output=True, text=True, timeout=240,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            finally:
                _MELT_RUNNING.clear()
        if result.returncode:
            raise RuntimeError('could not render upper tracks for the live scene: ' + result.stderr[-600:])
        frame_bytes = width * height * 4
        have = raw.stat().st_size // frame_bytes if raw.exists() else 0
        if have != n:
            raise RuntimeError(f'upper-track mask has {have} frames in a run of {n}')
        frames = np.memmap(raw, dtype=np.uint8, mode='r', shape=(n, height, width, 4))

        def save(i, first=first, frames=frames):
            alpha = Image.fromarray(np.ascontiguousarray(frames[i, :, :, 3]), 'L').resize(half, Image.Resampling.LANCZOS)
            mask = Image.new('RGBA', half, (255, 255, 255, 0))
            mask.putalpha(alpha)
            mask.save(out_dir / f'mask-{first + i:04d}.png', compress_level=1)
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(save, range(n)))
        del save, frames  # let go of the file before the next run replaces it
        report(first + n)


def _live_or_saved_source(path):
    import letitedit.server.timeline_tools as timeline_tools
    live = timeline_tools._live_state(path)
    return Path(__import__('letitedit.app.live_edit', fromlist=["*"]).snapshot(live['instance_id'])[0]) if live else path


def request_refresh(project):
    """What an edit or Undo calls: returns at once and draws nothing.

    The masks only matter while someone plays a scene in the live player. A window that shows the project refreshes
    them itself (it watches its own undo stack and, when a scene comes up, checks they are current); with no window
    showing the project nobody is playing and nothing is drawn until one is opened."""
    path = es._resolve(project).resolve()
    if not home(path).is_dir():
        return []
    import letitedit.server.timeline_tools as timeline_tools
    live = timeline_tools._live_state(path)
    return [{'deferred': True, 'window': bool(live)}]


def refresh_project(project, attempts=4, progress=None):
    """Refresh derived upper alpha after an independent timeline edit or Undo (run by the app's window, or
    `code_scenes.py --refresh`). Source revisions remain immutable; only their generated page/mask cache moves.
    A newer edit while it draws makes it stop at the next chunk and start again from the newer timeline.
    """
    path = es._resolve(project).resolve()
    if not home(path).is_dir():
        return []
    refreshed = []
    for _ in range(attempts):
        source = _live_or_saved_source(path)
        script = es.read(source)
        fps = float(script['profile']['fps'])
        refreshed = []
        try:
            for track in script['tracks']:
                for item in track['items']:
                    marker = item.get('scene')
                    if not marker:
                        continue
                    folder = revision_dir(path, marker['id'], marker['revision'])
                    data = _json(folder / 'scene.json')
                    start_s = es.to_seconds(item['at'])
                    count = max(1, round(data['spec']['duration'] * fps))

                    def now(name=track['name'], start_f=round(start_s * fps), count=count):
                        return _upper_fingerprint(_live_or_saved_source(path), name, start_f, count)
                    refreshed.append(prepare_upper_masks(source, track['name'], start_s, data['spec'],
                                                         script['profile'], folder, current=now, progress=progress))
            return refreshed
        except Superseded:
            continue
    return refreshed + [{'superseded': True}]


# ---------------------------------------------------------------------------- the AI's look at scenes in place

SNAPSHOT_OF: dict[str, str] = {}   # a snapshot file of an open project (its unsaved state) -> the project's own path
_CONTEXT: contextvars.ContextVar = contextvars.ContextVar('scene_looks', default=None)
LOOK_DRAW_MAX = 150                # frames drawn for one scene in a range clip (the rest repeat the nearest earlier one)


@contextlib.contextmanager
def looking(revisions=None):
    """Within this block `looks_path` uses the given revision per scene id and collects its notes: yields the notes list."""
    context = {'revisions': dict(revisions or {}), 'notes': []}
    token = _CONTEXT.set(context)
    try:
        yield context['notes']
    finally:
        _CONTEXT.reset(token)


def finished_render(folder, revision):
    """The scene's finished full render when there is one for exactly this revision (the one the export uses)."""
    movie = folder / 'render' / f'generated-motion-custom-{revision}.mov'
    return movie if movie.is_file() and movie.stat().st_size and Path(str(movie) + '.json').exists() else None


def _use_movie(producer, source):
    producer.tag = 'chain'
    for key, value in (('mlt_service', 'avformat-novalidate'), ('resource', str(source)),
                       ('seekable', 1), ('video_index', 0), ('audio_index', -1)):
        es._set(producer, key, value)


def _entries(root, doc):
    """{producer id: [(first timeline frame, first producer frame, last producer frame)]} for every playlist entry."""
    uses = {}
    for playlist in root.iter('playlist'):
        position = 0
        for element in playlist:
            if element.tag == 'blank':
                position += doc.f(element.get('length'))
            elif element.tag == 'entry':
                first, last = doc.f(element.get('in')) or 0, doc.f(element.get('out')) or 0
                uses.setdefault(element.get('producer'), []).append((position, first, last))
                position += last - first + 1
    return uses


def _link_sequence(drawn_files, first, count, sequence):
    """One numbered file per frame of a scene, each the nearest drawn picture before it, as hard links. NTFS allows 1023
    links to a file: past that one real copy is made and the next frames link to it (T95: copying every later frame put
    up to 2.6 GB in a folder)."""
    last_file = drawn_files[first]
    for n in range(count):
        last_file = drawn_files.get(n, last_file)
        target = sequence / f'{n:05d}.png'
        try:
            os.link(last_file, target)
        except OSError:
            shutil.copy2(last_file, target)
            last_file = target


def looks_path(snapshot, frames=None, span=None, width=None, work=None, native=False):
    """The file melt should render to show these timeline frames (frames) or this range (span = (first, last)) the way
    the export will: every code scene marker in view is swapped, as the export does, for its finished render when one
    exists for that revision, else for frames drawn now by the scene's own page in a browser kept open. melt then layers
    the cut-out, captions and everything else exactly as it does for the export. A scene that cannot be drawn stays the
    transparent marker and is named in the notes (scenes.json in `work`, and the open `looking()` block's list).
    Returns the snapshot itself when it has no scene in view."""
    snapshot = Path(snapshot)
    if SCENE_PROP.encode() not in snapshot.read_bytes():
        return snapshot
    import letitedit.pictures.scene_look as scene_look
    project = SNAPSHOT_OF.get(str(snapshot)) or str(snapshot)
    context = _CONTEXT.get() or {'revisions': {}, 'notes': []}
    tree = ET.parse(snapshot)
    root = tree.getroot()
    doc = es.Doc(str(snapshot))
    fps = float(doc.fps)
    uses = _entries(root, doc)
    work = Path(work) if work else snapshot.parent
    notes = []
    changed = False
    for producer in [p for p in root if p.tag in ('producer', 'chain') and es._get(p, SCENE_PROP)]:
        marker = json.loads(es._get(producer, SCENE_PROP))
        scene_id = marker['id']
        revision = context['revisions'].get(scene_id) or marker['revision']
        needed = set()
        for position, first, last in uses.get(producer.get('id'), []):
            lo, hi = (position, position + last - first) if span is None else (max(span[0], position),
                                                                                min(span[1], position + last - first))
            for f in (range(lo, hi + 1) if span is not None else [x for x in frames if lo <= x <= hi]):
                needed.add(first + f - position)
        if not needed:
            continue
        note = {'scene': scene_id, 'revision': revision}
        try:
            folder = revision_dir(project, scene_id, revision)
            data = _json(folder / 'scene.json')
            movie = finished_render(folder, revision)
            if movie:
                _use_movie(producer, movie)
                note['shows'] = 'its finished render, as the export does'
            else:
                count = max(1, round(data['spec']['duration'] * fps))
                wanted = sorted(n for n in needed if 0 <= n < count) or [0]
                stride = 1 if native or len(wanted) <= LOOK_DRAW_MAX else -(-len(wanted) // LOOK_DRAW_MAX)
                drawn = wanted[::stride]
                size_w = int(data['width']) if not width else max(64, min(int(width), int(data['width']))) // 2 * 2
                size_h = round(int(data['height']) * size_w / int(data['width']) / 2) * 2
                page = work / 'scene-look' / f'{scene_id}-{revision}-{size_w}' / 'page'
                if motion.saved_parts(folder / 'page', data['spec']):
                    motion.saved_page(folder / 'page', size_w, size_h, page, fps)
                else:
                    motion.build_page(motion.normalise(data['spec']), size_w, size_h, fps, page)
                answer = scene_look.draw(page / 'index.html', [n / fps for n in drawn],
                                         page.parent / 'drawn', size_w, size_h)
                note['problems'] = scene_look.problems(answer)
                note['frames_drawn'] = len(drawn)
                note['seconds'] = answer['seconds']
                note['mode'] = answer.get('mode')
                if not all(answer['frames']):
                    raise RuntimeError('; '.join(answer['errors']) or 'a frame could not be drawn')
                sequence = page.parent / 'sequence'
                shutil.rmtree(sequence, ignore_errors=True)
                sequence.mkdir()
                _link_sequence(dict(zip(drawn, answer['frames'])), drawn[0], count, sequence)
                for key, value in (('mlt_service', 'qimage'), ('resource', str(sequence / '%05d.png')), ('ttl', 1),
                                   ('length', count), ('eof', 'pause')):
                    es._set(producer, key, value)
                note['shows'] = 'drawn now by the scene\'s page (no finished render for this revision)'
            changed = True
        except Exception as e:  # noqa: BLE001 - the picture must still come, with the scene named as not drawn
            note['not_drawn'] = f'{type(e).__name__}: {e}'[:300]
        notes.append(note)
    context['notes'].extend(notes)
    if notes:
        _write(work / 'scenes.json', notes)
    if not changed:
        return snapshot
    root.set('root', str(snapshot.resolve().parent))
    out = work / f'scenes-in-view-{snapshot.stem}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


def scene_labels(work, picks, labels, timeline_frames=None):
    """Words to add to a contact sheet's labels when a scene in view could not be drawn."""
    file = Path(work) / 'scenes.json'
    if not file.exists():
        return labels
    bad = [n for n in _json(file) if n.get('not_drawn')]
    if not bad:
        return labels
    return [label + '  [a code scene here is NOT drawn: ' + '; '.join(n['scene'] for n in bad) + ']' for label in labels]


_STILLS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg'}


def _shows_footage(item):
    """True for an item that is footage of someone: a video clip, a frozen frame, or a shot effect on a source."""
    if item.get('freeze'):
        return True
    vfx = item.get('vfx')
    if isinstance(vfx, dict) and vfx.get('source'):
        return True
    clip = item.get('clip')
    return bool(clip) and Path(str(clip)).suffix.lower() not in _STILLS


def _layer_notes(script, track, item):
    """An adjustment layer above a scene: true in the export and in look; the live player draws the scene over the picture."""
    from letitedit.timeline.edit_sync import layout
    start = es.to_seconds(item['at'])
    end = start + float(item['len'])
    names = [t['name'] for t in script['tracks']]
    if track['name'] not in names:
        return []
    for t in script['tracks'][names.index(track['name']) + 1:]:
        if t.get('kind', 'video') == 'video':
            for other, a, b in layout(t):
                if other.get('adjust') and a < end and b > start:
                    return [f'the adjustment layer on {t["name"]} changes this scene in the export and in these frames; the live player draws '
                            'the scene over the picture, so it shows the scene without it']
    return []


def _placement_notes(script, track, item):
    """Facts about where a scene sits, never a problem: a scene above the main footage with no footage above it
    covers the person for its whole length (a full takeover scene is legitimate, so this only says so)."""
    tracks = script['tracks']
    names = [t['name'] for t in tracks]
    video = [i for i, t in enumerate(tracks) if t.get('kind') == 'video']
    if track['name'] not in names or not video:
        return []
    mine = names.index(track['name'])
    start = es.to_seconds(item['at'])
    end = start + float(item['len'])

    def overlaps(other):
        if other.get('at') is None or other.get('len') is None:
            return False               # a gap or an item with no place of its own
        a = es.to_seconds(other['at'])
        return a < end and a + float(other['len']) > start

    below = [i for i in video if i < mine]
    if not any(overlaps(o) and (_shows_footage(o) or o.get('vfx')) for i in below for o in tracks[i]['items']):
        return []                      # no footage under it: nothing to cover
    above = [o for t in tracks[mine + 1:] if t.get('kind') == 'video' and t.get('hide') not in ('video', 'both')
             for o in t['items'] if overlaps(o)]
    if any(_shows_footage(o) for o in above):
        return []
    return ['This scene draws over the footage below it; nothing above it shows the person'
            + (f' (above it here: {len(above)} other item{"s" if len(above) != 1 else ""})' if above else '')
            + f', between {start:.2f} and {end:.2f} s. revise with behind_person=true puts the cut-out above it.']


def scene_change(spec, width, height, fps, max_samples=24, page=None):
    """How much the scene itself changes over its length, measured on the scene alone: stills at even steps (about every
    2 s, at most max_samples), and between each pair the share of the picture whose colour moved by more than 8%. Returns
    {'step_s', 'moved_pct': [...], 'little': [{'from_s', 'to_s', 'moved_pct'}]}: 'little' lists stretches of 8 s or more
    where every step moved under 3%. A fact, not a judgement: a calm scene may be meant."""
    from PIL import Image, ImageChops
    duration = float(spec['duration'])
    n = max(3, min(max_samples, int(duration / 2.0) + 1))
    times = [min(duration - 0.05, duration * k / (n - 1)) for k in range(n)]
    w = 270
    h = max(2, int(w * height / width) // 2 * 2)
    got = motion.preview(spec, w, h, fps, times=times, page=page)
    frames = []
    for path in got['frames']:
        im = Image.open(path).convert('RGBA')
        base = Image.new('RGBA', im.size, (0, 0, 0, 255))
        frames.append(Image.alpha_composite(base, im).convert('RGB'))
    moved = []
    for a, b in zip(frames, frames[1:]):
        diff = ImageChops.difference(a, b).convert('L').point(lambda v: 255 if v > 20 else 0)
        moved.append(round(100 * sum(1 for v in diff.getdata() if v) / (diff.width * diff.height), 1))
    little, start = [], None
    for k, m in enumerate(moved + [100.0]):
        if m < 3.0:
            start = k if start is None else start
        elif start is not None:
            if times[k] - times[start] >= 8.0:
                little.append({'from_s': round(times[start], 1), 'to_s': round(times[k], 1),
                               'moved_pct': round(max(moved[start:k]), 1)})
            start = None
    return {'step_s': round(times[1] - times[0], 1), 'moved_pct': moved, 'little': little,
            'about': 'share of the scene picture whose colour moved more than 8% between samples taken step_s apart, '
                     'the scene alone, nothing else on the timeline'}


def look(project, scene_id, times=None, count=8, revision=None, tile_w=360):
    """Frames of one scene in place (the person, captions and everything else around it), drawn now. `times`: seconds
    from the scene's start on the timeline; else `count` frames spread through it. Returns the contact sheet's file,
    each frame's file and what a machine could tell: page errors, blank, frozen."""
    import letitedit.review.checks as checks
    path = es._resolve(project).resolve()
    source = _live_or_saved_source(path)
    SNAPSHOT_OF[str(source)] = str(path)
    script = es.read(source)
    track, item = _item(script, scene_id)
    start, length = es.to_seconds(item['at']), float(item['len'])
    if times:
        picks = [start + float(t) for t in times if 0 <= float(t) < length]
    else:
        picks = [start + length * (i + 0.5) / max(1, int(count)) for i in range(max(1, int(count)))]
    if not picks:
        raise ValueError('times are outside the scene')
    with looking({scene_id: revision} if revision else None) as notes:
        pages, info = checks.frame_pages(str(source), times_s=picks, cols=4, tile_w=tile_w, per_page=48)
    mine = next((n for n in notes if n['scene'] == scene_id), {})
    problems = list(mine.get('problems') or [])
    if mine.get('not_drawn'):
        problems.append('the scene could not be drawn: ' + mine['not_drawn'])
    return {'scene_id': scene_id, 'revision': mine.get('revision'), 'sheet': info['sheet'],
            'frames': [{'time_in_scene_s': round(t - start, 2), 'png': f['png']} for t, f in zip(picks, info['frames'])],
            'shows': mine.get('shows'), 'problems': problems, 'ok': not problems,
            'notes': _placement_notes(script, track, item) + _layer_notes(script, track, item), 'seconds': info['seconds']}


def _manifest(project, scene_id, revision, title, anchor=None):
    folder = scene_dir(project, scene_id)
    path = folder / 'manifest.json'
    old = _json(path) if path.exists() else {}
    data = {'format': 'letitedit-code-scene/1', 'id': scene_id, 'title': title,
            'latest_revision': revision, 'revisions': list(dict.fromkeys(
                [*(old.get('revisions') or []), revision])),
            'anchor': anchor if anchor is not None else old.get('anchor')}
    _write(path, data)
    return path


def _person_changes(timeline, scene_track, at, length):
    """Changes that put a cut-out of the footage under a scene on a track above it, over the scene's time, one piece
    per clip under it (the same `{vfx: cutout}` item a person adds by hand). Returns (changes, report)."""
    tracks = timeline['tracks']
    names = [t['name'] for t in tracks]
    video = [t for t in tracks if t.get('kind') == 'video']
    end = at + length
    scene_index = names.index(scene_track) if scene_track in names else 1

    def span(item):
        if item.get('at') is None or item.get('len') is None:
            return None
        a = es.to_seconds(item['at'])
        return a, a + float(item['len'])

    def clash(a, b, items):
        return [i for i in items if span(i) and span(i)[0] < b - 1e-6 and span(i)[1] > a + 1e-6]

    covered = [i for t in tracks[scene_index + 1:] if t.get('kind') == 'video' for i in t['items']
               if (i.get('vfx') or {}).get('effect') == 'cutout']
    pieces, skipped = [], []
    below = [t for t in video if names.index(t['name']) < scene_index] or video[:1]
    clips = [(item, span(item)) for item in (below[0]['items'] if below else []) if span(item) and item.get('clip')]
    for n, (item, sp) in enumerate(clips):
        if sp[0] >= end or sp[1] <= at:
            continue
        a, b = max(at, sp[0]), min(end, sp[1])
        # clips joined by a crossfade overlap: the person changes pieces halfway through it (a track plays one at a time)
        if n and clips[n - 1][1][1] > sp[0]:
            a = max(a, (clips[n - 1][1][1] + sp[0]) / 2)
        if n + 1 < len(clips) and clips[n + 1][1][0] < sp[1]:
            b = min(b, (clips[n + 1][1][0] + sp[1]) / 2)
        if b <= a:
            continue
        if clash(a, b, covered):
            skipped.append({'at': round(a, 3), 'len': round(b - a, 3), 'why': 'a cut-out is already there'})
            continue
        speed = float(item.get('speed') or 1.0)
        src = {'clip': item['clip'], 'in': round(item['in'] + (a - sp[0]) * speed, 4),
               'out': round(item['in'] + (b - sp[0]) * speed, 4)}
        if speed != 1.0:
            src['speed'] = speed
        pieces.append((a, b, src))
    report = {'placed': len(pieces), 'skipped': skipped}
    if not pieces:
        report['note'] = ('no cut-out was placed: ' + ('a cut-out is already there' if skipped else
                          'no clip of the main footage is under the scene'))
        return [], report
    name, number = 'Person', 1
    while True:
        same = next((t for t in tracks if t['name'] == name), None)
        free = same is not None and names.index(name) > scene_index and not any(
            span(i) and span(i)[0] < end and span(i)[1] > at for i in same['items'])
        if same is None or free:
            break
        number += 1
        name = f'Person {number}'
    changes = [] if same is not None else [{'op': 'add_track', 'name': name, 'kind': 'video'}]
    for a, b, src in pieces:
        changes.append({'op': 'insert', 'track': name, 'at': round(a, 4), 'edge_mode': 'exact',
                        'item': {'vfx': {'effect': 'cutout', 'source': src}}})
    report.update(track=name, pieces=[{'at': round(a, 3), 'len': round(b - a, 3), 'clip': src['clip']}
                                      for a, b, src in pieces])
    return changes, report


def _apply_new_scene(path, changes, label, scene_id, action):
    """Put the scene on the timeline; a new scene that didn't get there leaves no folder behind to block its id."""
    import letitedit.server.timeline_tools as timeline_tools
    try:
        return timeline_tools.apply_project(str(path), changes, check=False, label=label)
    except Exception:
        if action == 'create':
            shutil.rmtree(scene_dir(path, scene_id), ignore_errors=True)
        raise


def _scene_versions(path, timeline, scene_id):
    """The scene's revisions and which one the timeline shows."""
    if not scene_id:
        raise ValueError('scene_id is required')
    _, item = _item(timeline, scene_id)
    manifest = _json(scene_dir(path, scene_id) / 'manifest.json')
    return {'scene_id': scene_id, 'current': item['scene']['revision'],
            'revisions': manifest['revisions']}


def _restore_scene_version(path, timeline, scene_id, revision):
    """Puts an earlier revision of the scene back on the timeline (checked to be this scene's, its page
    proved)."""
    import letitedit.server.timeline_tools as timeline_tools
    if not scene_id or not revision:
        raise ValueError('scene_id and revision are required')
    _, item = _item(timeline, scene_id)
    manifest = _json(scene_dir(path, scene_id) / 'manifest.json')
    if revision not in manifest['revisions']:
        raise ValueError('that version does not belong to this scene')
    data = _json(revision_dir(path, scene_id, revision) / 'scene.json')
    _checked_page(revision_dir(path, scene_id, revision), data, scene_id, revision)
    changes = [{'op': 'set', 'id': item['id'], 'scene': {'id': scene_id,
                'revision': revision}, 'len': data['spec']['duration']}]
    result, _ = timeline_tools.apply_project(str(path), changes, check=False,
                                              label='AI: restore code scene version')
    return {'scene_id': scene_id, 'revision': revision, 'edit': result}


def retime(project, scene_id, segments):
    """T362 (letitedit.server.scene_follow): a new revision of the scene whose drawing follows the cut, from `segments`
    (pictures.scene_time_map: page time on the timeline as it is now -> page time before the edit), composed with the
    time map its script already has. The timeline is not changed here: returns the marker {id, revision} to set on its
    item, or None when the drawing would be the same."""
    import letitedit.pictures.scene_time_map as scene_time_map
    path = es._resolve(project).resolve()
    timeline = es.read(path)
    track, item = _item(timeline, scene_id)
    earlier = revision_dir(path, scene_id, item['scene']['revision']) / 'page'
    old = _json(earlier.parent / 'scene.json')['spec']
    inner = scene_time_map.of(old.get('script'))
    combined = scene_time_map.compose(segments, inner)
    script = scene_time_map.with_map(old.get('script') or '', combined)
    if script == old.get('script'):
        return None
    saved = motion.saved_parts(earlier, old)
    spec = _spec(old, known=motion.saved_names(saved), script=script)
    revision, folder = _new_revision(path, scene_id, spec, timeline['profile'], saved=saved, earlier=earlier)
    if revision == item['scene']['revision']:
        return None
    _manifest(path, scene_id, revision, item.get('name') or 'Code scene')
    if not _masks_dir(folder).is_dir():
        prepare_upper_masks(path, track['name'], es.to_seconds(item.get('at') or 0), spec, timeline['profile'], folder,
                            previous=revision_dir(path, scene_id, item['scene']['revision']), copy_only=True)
    return {'id': scene_id, 'revision': revision}


def run(action='create', project=None, scene_id=None, script=None, html=None, css=None,
        params=None, duration=None, at=None, track='Code scene', title='Code scene',
        anchor=None, revision=None, favorite_id=None, times=None, count=None, behind_person=False, edits=None):
    if action == 'favorites':
        return {'scenes': list_favorites()}
    if not project:
        raise ValueError('project is required')
    path = es._resolve(project).resolve()
    import letitedit.server.timeline_tools as timeline_tools
    live = timeline_tools._live_state(path)
    source_path = Path(__import__('letitedit.app.live_edit', fromlist=["*"]).snapshot(live['instance_id'])[0]) if live else path
    timeline = es.read(source_path)
    scene_id = _scene_id(timeline, scene_id)
    if action == 'status':
        return {'scenes': [{'track': t['name'], **i} for t in timeline['tracks']
                            for i in t['items'] if 'scene' in i]}
    if action == 'source':
        if not scene_id:
            raise ValueError('scene_id is required')
        _, item = _item(timeline, scene_id)
        pinned = item['scene']['revision'] if not revision else revision
        spec = _json(revision_dir(path, scene_id, pinned) / 'scene.json')['spec']
        return {'scene_id': scene_id, 'revision': pinned,
                **{k: spec.get(k) for k in ('script', 'html', 'css', 'params', 'duration') if spec.get(k) is not None}}
    if action == 'look':
        if not scene_id:
            raise ValueError('scene_id is required')
        return look(path, scene_id, times=times, count=count or 8, revision=revision)
    if action == 'versions':
        return _scene_versions(path, timeline, scene_id)
    if action == 'restore':
        return _restore_scene_version(path, timeline, scene_id, revision)
    if action == 'save':
        if not scene_id:
            raise ValueError('scene_id is required')
        _, item = _item(timeline, scene_id)
        return save_favorite(path, item['scene'], title, favorite_id)
    if action == 'render':
        if not scene_id:
            raise ValueError('scene_id is required')
        _, item = _item(timeline, scene_id)
        return render_full(path, item['scene'])
    if action not in ('create', 'revise'):
        raise ValueError('action is create, revise, render, status, source, versions, restore, save or favorites')
    if edits and action != 'revise':
        raise ValueError('edits are for revise: text replacements in a scene that is already there')
    if action == 'create':
        if not script:
            raise ValueError('a new scene needs script with M.block(\'custom\', ...)')
        scene_id = scene_id or 'scene-' + uuid.uuid4().hex[:12]
        if scene_dir(path, scene_id).exists():
            raise ValueError(f'scene id already exists: {scene_id}')
        script = _script_text(script)
        kept = _kept_kits(path, script)
        saved = {'looks': kept} if kept else None
        earlier = None
        spec = _spec(None, known=kept, script=script, html=html, css=css, params=params, duration=duration)
    else:
        if not scene_id:
            raise ValueError('scene_id is required to revise')
        _, item = _item(timeline, scene_id)
        earlier = revision_dir(path, scene_id, item['scene']['revision']) / 'page'
        old = _json(earlier.parent / 'scene.json')['spec']
        if edits:
            if script is not None or html is not None or css is not None:
                raise ValueError('revise takes edits or a whole script, html or css, not both')
            changed = text_edits(old, edits)
            script, html, css = changed.get('script'), changed.get('html'), changed.get('css')
        saved = motion.saved_parts(earlier, old)
        spec = _spec(old, known=motion.saved_names(saved), script=script, html=html, css=css, params=params, duration=duration)
        title = title if title != 'Code scene' else item.get('name', title)
    revision, folder = _new_revision(path, scene_id, spec, timeline['profile'], saved=saved, earlier=earlier)
    kept_note = _kept_note(saved, spec)
    if action == 'revise' and item['scene']['revision'] == revision:
        out = {'scene_id': scene_id, 'revision': revision, 'unchanged': True,
               'page': str(folder / 'page' / 'index.html'), **kept_note}
        if times or count:
            try:
                out['look'] = look(path, scene_id, times=times, count=count or 8)
            except Exception as e:  # noqa: BLE001 - nothing changed; say the look failed rather than fail the call
                out['look'] = {'error': f'{type(e).__name__}: {e}'[:300]}
        if behind_person:
            import time as _time
            extra, behind = _person_changes(timeline, _item(timeline, scene_id)[0]['name'], es.to_seconds(item['at']),
                                            float(spec['duration']))
            if extra:
                started = _time.monotonic()
                out['edit'], _ = timeline_tools.apply_project(str(path), extra, check=False,
                                                               label='AI: the person in front of the code scene')
                behind['seconds'] = round(_time.monotonic() - started, 1)
            behind['room'] = _person_room(path)
            out['behind_person'] = behind
        return out
    _manifest(path, scene_id, revision, title, anchor)
    mask = {'deferred': True}
    if action == 'revise' and not _masks_dir(folder).is_dir():
        # A revision with the same picture above it takes the old masks (a copy); anything else is drawn later
        # by the window that shows the scene, never while this call waits.
        mask = prepare_upper_masks(source_path, _item(timeline, scene_id)[0]['name'], es.to_seconds(item['at']),
                                   spec, timeline['profile'], folder,
                                   previous=revision_dir(path, scene_id, item['scene']['revision']), copy_only=True)
    marker = {'id': scene_id, 'revision': revision}
    if action == 'create':
        tracks = {t['name'] for t in timeline['tracks']}
        changes = [] if track in tracks else [{'op': 'add_track', 'name': track,
                                                'kind': 'video',
                                                'after': timeline['tracks'][0]['name']}]
        changes.append({'op': 'insert', 'track': track, 'at': float(at or 0),
                        'item': {'scene': marker, 'len': spec['duration'], 'name': title}})
    else:
        changes = [{'op': 'set', 'id': item['id'], 'scene': marker,
                    'len': spec['duration'], 'name': title}]
    label = f'AI: {"add" if action == "create" else "revise"} code scene'
    behind = None
    if behind_person:
        import time as _time
        if action == 'create':
            extra, behind = _person_changes(timeline, track, float(at or 0), float(spec['duration']))
        else:
            extra, behind = _person_changes(timeline, _item(timeline, scene_id)[0]['name'], es.to_seconds(item['at']),
                                            float(spec['duration']))
        if extra:
            started = _time.monotonic()
            try:
                result, _ = timeline_tools.apply_project(str(path), changes + extra, check=False,
                                                          label=label + ' with the person in front')
                behind['seconds'] = round(_time.monotonic() - started, 1)
            except Exception as e:  # noqa: BLE001 - whatever stopped it: no scene over the person, and say why
                if action != 'create':
                    raise RuntimeError(f'The timeline is unchanged: the cut-out that keeps the person in front could not be '
                                       f'placed ({type(e).__name__}: {e}).') from e
                shutil.rmtree(scene_dir(path, scene_id), ignore_errors=True)
                raise RuntimeError(f'The scene was not added and the timeline is unchanged: the cut-out that keeps the '
                                   f'person in front could not be placed ({type(e).__name__}: {e}). The same call can be '
                                   f'made again; behind_person=false adds the scene with nothing in front of it, covering '
                                   f'the person.') from e
        else:
            result, _ = _apply_new_scene(path, changes, label, scene_id, action)
    else:
        result, _ = _apply_new_scene(path, changes, label, scene_id, action)
    try:
        seen = look(path, scene_id, times=times, count=count or 8)
    except Exception as e:  # noqa: BLE001 - the edit is made; say the look failed rather than fail the call
        seen = {'error': f'{type(e).__name__}: {e}'[:300]}
    try:
        change = scene_change(spec, timeline['profile']['width'], timeline['profile']['height'],
                              float(timeline['profile']['fps']), page=folder / 'page')
    except Exception as e:  # noqa: BLE001 - a fact the call can do without
        change = {'error': f'{type(e).__name__}: {e}'[:200]}
    if behind is not None:
        behind['room'] = _person_room(path)
    return {'scene_id': scene_id, 'revision': revision, 'page': str(folder / 'page' / 'index.html'),
            'manifest': str(scene_dir(path, scene_id) / 'manifest.json'), 'edit': result, 'scene_change': change,
            'upper_masks': mask, **({'behind_person': behind} if behind is not None else {}), 'look': seen, **kept_note,
            'export': 'full HyperFrames render required; letitedit_export prepares it under the render lock'}


def render_full(project, marker):
    scene_id, revision = marker['id'], marker['revision']
    folder = revision_dir(project, scene_id, revision)
    data = _json(folder / 'scene.json')
    spec = data['spec']
    page = _checked_page(folder, data, scene_id, revision)
    out = folder / 'render'
    rendered = motion.render(spec, data['width'], data['height'], data['fps'], out_dir=out, fmt='mov', page=page)
    return {'scene_id': scene_id, 'revision': revision, 'file': rendered['path'],
            'cached': rendered['cached']}


def save_favorite(project, marker, title='Code scene', favorite_id=None):
    """Keep source and generated files; a new project gets its own adapted revision."""
    source = revision_dir(project, marker['id'], marker['revision'])
    data = _json(source / 'scene.json')
    _checked_page(source, data, marker['id'], marker['revision'])
    favorite_id = favorite_id or 'scene-' + uuid.uuid4().hex[:12]
    target = favorite_dir(favorite_id)
    if target.exists():
        raise ValueError('saved scene id already exists')
    target.mkdir(parents=True)
    shutil.copy2(source / 'scene.json', target / 'scene.json')
    shutil.copytree(source / 'page', target / 'page', ignore=shutil.ignore_patterns('masks*'))
    # A small moving thumbnail makes this shelf browsable without baking in a
    # pre-made scene library. The exact source remains available to the AI.
    thumb = target / 'thumbnail.gif'
    try:
        movie = render_full(project, marker)['file']
        ffmpeg = _paths.CODE_ROOT / 'app' / 'ffmpeg.exe'
        # The middle of the scene: its first frames are usually an almost empty entrance.
        start = max(0.0, float(data['spec']['duration']) / 2 - 1)
        command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{start:.3f}', '-i', movie,
                   '-vf', 'fps=8,scale=240:-2:flags=lanczos', '-t', '2', '-loop', '0', str(thumb)]
        import letitedit.core.render_lock as render_lock
        with render_lock.slot('my-scene moving thumbnail', caller_pids=render_lock.ancestors()):
            result = subprocess.run(command, capture_output=True, text=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or not thumb.is_file():
            raise RuntimeError('could not make the saved scene thumbnail: ' + result.stderr[-500:])
    except Exception:
        shutil.rmtree(target)
        raise
    _write(target / 'manifest.json', {'format': 'letitedit-my-scene/1', 'id': favorite_id,
           'name': title if title != 'Code scene' else marker['id'],
           'source_scene': marker['id'], 'revision': marker['revision'],
           'thumbnail': 'thumbnail.gif', 'created': time.time()})
    return {'id': favorite_id, 'name': _json(target / 'manifest.json')['name'],
            'folder': str(target), 'thumbnail': str(thumb)}


def copy_scenes(source, dest):
    """A copy of a project (letitedit_versions, project_new copy_of) takes its scenes: their source and page, not the large
    finished movies and masks, which are drawn again when needed. Returns how many revisions came along."""
    if not home(source).is_dir():
        return 0
    shutil.copytree(home(source), home(dest), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('render', 'preview', 'fallback', 'mask-work', 'masks*', 'upper-mask.*'))
    revisions = [f for f in home(dest).glob('*/revisions/*') if (f / 'page' / 'index.html').is_file()]
    for folder in revisions:
        _remove_mask_page(folder)
    return len(revisions)


def list_favorites():
    out = []
    for folder in sorted(favorites_home().glob('*/manifest.json')):
        try:
            item = _json(folder)
            if item.get('format') != 'letitedit-my-scene/1':
                continue
            item['folder'] = str(folder.parent)
            item['thumbnail'] = str(folder.parent / item['thumbnail'])
            item['source'] = str(folder.parent / 'scene.json')
            out.append(item)
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    return out


def preview_frames(folder):
    """A small alpha preview for a player without WebView2. Export never uses it."""
    from PIL import Image, ImageChops
    folder = Path(folder).resolve()
    data = _json(folder / 'scene.json')
    spec = data['spec']
    width = max(2, int(data['width']) // 4 // 2 * 2)
    height = max(2, int(data['height']) // 4 // 2 * 2)
    fps = 8
    masks = _masks_dir(folder)
    info = _json(folder / 'upper-mask.json') if (folder / 'upper-mask.json').exists() else {}
    fingerprint = info.get('fingerprint', '')
    output = folder / 'fallback'
    index_file = output / 'index.json'
    index = _json(index_file) if index_file.exists() else {}
    if (index.get('mask_fingerprint') == fingerprint and index.get('fps') == fps
            and index.get('width') == width and index.get('height') == height):
        frames = sorted(output.glob('frame-*.png'))
        if frames:
            return {'folder': str(output), 'fps': fps, 'frames': len(frames), 'cached': True}
    rendered = motion.render(spec, width, height, fps, out_dir=folder / 'preview', fmt='png', sheet_count=0, page=folder / 'page')
    source = sorted(Path(rendered['path']).glob('*.png'))
    if not source:
        raise RuntimeError('the fallback preview made no frames')
    output.mkdir(exist_ok=True)
    for stale in output.glob('frame-*.png'):
        stale.unlink()
    project_fps = float(data['fps'])
    for i, frame in enumerate(source):
        destination = output / f'frame-{i:04d}.png'
        mask = masks / f'mask-{round(i * project_fps / fps):04d}.png'
        if mask.exists():
            with Image.open(frame) as image, Image.open(mask) as upper:
                image = image.convert('RGBA')
                upper_alpha = upper.getchannel('A').resize(image.size, Image.Resampling.BILINEAR)
                image.putalpha(ImageChops.multiply(image.getchannel('A'),
                                                   ImageChops.invert(upper_alpha)))
                image.save(destination, optimize=True)
        else:
            shutil.copy2(frame, destination)
    _write(index_file, {'mask_fingerprint': fingerprint, 'fps': fps, 'width': width,
                        'height': height, 'frames': len(source)})
    return {'folder': str(output), 'fps': fps, 'frames': len(source), 'cached': False}


def prepare_export(snapshot, project, progress: Callable[[int, int, dict], None] | None = None,
                   note: Callable[[str], None] | None = None, left_out: Callable[[str], None] | None = None):
    """Replace every marker in an export snapshot with its full alpha movie.
    Raises before melt can produce a video if even one scene cannot render. A scene whose drawing fails is drawn once
    more before that (`note` is told, so the export's message says so); a stopped export is not retried.
    T71: when this PC cannot draw scenes at all (no browser that starts, no engine), the video still exports, with the scenes
    left out (they stay transparent), and `left_out` is told why in plain words."""
    path = Path(snapshot)
    tree = ET.parse(path)
    root = tree.getroot()
    prepared = []
    candidates = [producer for producer in root if producer.tag in ('producer', 'chain')
                  and es._get(producer, SCENE_PROP)]
    why = motion.available() if candidates and left_out else None
    if why:
        n = len(candidates)
        left_out(f"This PC can't draw code scenes ({why.rstrip('. ')}), so this video was exported without its "
                 f"{n} scene{'s' if n != 1 else ''}. Everything else is in it.")
        return []
    for index, producer in enumerate(candidates, 1):
        if producer.tag not in ('producer', 'chain'):
            continue
        marker = es._get(producer, SCENE_PROP)
        if not marker:
            continue
        scene = json.loads(marker)
        if progress:
            progress(index, len(candidates), scene)
        try:
            result = render_full(project, scene)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            import letitedit.core.render_lock as render_lock
            if isinstance(e, (render_lock.Cancelled, render_lock.LockTimeout)):
                raise
            if note:
                note(f'Drawing code scene {index} of {len(candidates)} failed ({str(e).strip().splitlines()[-1][:160]}); '
                     'drawing it once more')
            result = render_full(project, scene)
        source = Path(result['file'])
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f'code scene {scene["id"]}: full render is missing')
        _use_movie(producer, source)
        prepared.append(result)
    if prepared:
        tree.write(path, encoding='utf-8', xml_declaration=True)
    with contextlib.suppress(Exception):        # disk housekeeping never fails an export
        prune_old_renders(project, {(p['scene_id'], p['revision']) for p in prepared})
    return prepared


PRUNE_AFTER_S = 3600


def prune_old_renders(project, keep, older_than_s=PRUNE_AFTER_S):
    """Delete the finished movie (revisions/<rev>/render) of every scene revision the project no longer uses, once it is
    older than older_than_s: a full-quality alpha movie is large (1.4 GB for 7 s at 1080x1920 60 fps in ProRes 4444) and
    a revision the timeline has moved on from keeps its source and page, so Restore makes the movie again when needed.
    keep: {(scene_id, revision)} in use. Returns the bytes freed."""
    freed, now = 0, time.time()
    for scene in sorted(home(project).glob('*')) if home(project).is_dir() else []:
        for rev in sorted((scene / 'revisions').glob('*')):
            movies = rev / 'render'
            if (scene.name, rev.name) in keep or not movies.is_dir():
                continue
            try:
                if now - max(f.stat().st_mtime for f in movies.rglob('*') if f.is_file()) < older_than_s:
                    continue
                size = sum(f.stat().st_size for f in movies.rglob('*') if f.is_file())
                shutil.rmtree(movies)
                freed += size
            except (OSError, ValueError):
                continue
    return freed


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_code_scene(action: str = 'create', project: str | None = None,
                            scene_id: str | None = None, script: str | None = None,
                            html: str | None = None, css: str | None = None,
                            params: dict | None = None, duration: float | None = None,
                            at: float | None = None, track: str = 'Code scene',
                            title: str = 'Code scene', anchor: dict | None = None,
                            revision: str | None = None, favorite_id: str | None = None,
                            times: list[float] | None = None, count: int | None = None,
                            behind_person: bool = False, edits: list[dict] | None = None) -> list:
        """Create, revise, look at, render or list a saved code scene. create requires
        script (the code, or the path of a file holding it) that registers M.block('custom', ...) with a frame function driven
        by t; browser-only animation cannot follow the playhead. It writes a
        selectable item on the Code scene track,
        and an immutable revision in <video>.letitedit/scenes. revise changes
        its source and timeline revision as one Undo in an open editor; it takes a whole script, html or css, or
        edits: [{old, new, in?}] exact text replacements in the pinned revision's script (in: 'html' or 'css' for
        those), applied in order, each old found exactly once, and nothing changed when one isn't. source returns the
        pinned revision's script, html, css, params and duration (revision: another one). scene_id is the scene's id,
        or the id of its timeline item. The live
        player shows the changed page without a render. create and revise return a
        look at the scene in place (times and count choose its frames). A revision's page holds its own copy of the
        runtime and any drawing kit it names and draws from that copy, whatever this PC has later, a kit's absence
        included; revise keeps that copy, and kept_from_this_scene and kept_note in its reply say what this PC has
        different or lacks. create uses what is on this PC; a kit that isn't here comes from this project's scenes or
        My scenes when one of them has it. look draws the scene now, with the person,
        captions and everything else around it, as a contact sheet (times: seconds
        from the scene's start; else count frames, 8 by default; revision: a version
        other than the pinned one) and reports page errors, a blank scene and a scene
        that does not move; `notes` lists plain facts that are not problems (for example that nothing above the scene
        shows the person). render makes its full export movie under the PC render
        lock. status lists scene items. versions lists immutable revisions; restore
        is one Undo; save puts the pinned revision in the person's My scenes shelf;
        favorites lists it.
        The page runtime is the motion tool's: letitedit_guide('letitedit_motion') lists its helpers (M.prog, springs and
        curves, M.camera, M.stagger, canvas parts under M.draw) and how a param named font loads a bundled font.
        behind_person (create, or revise for a scene already there): also places the cut-out of the footage under the scene, one `{vfx: cutout}` piece
        per clip under it and over exactly the scene's time, on a track named Person above the scene's (a track of
        that name is reused only if it is above the scene and free there; otherwise Person 2, ...), in the same
        Undo step. Pieces where a cut-out already sits above the scene are skipped. The call returns when the
        mattes are made: a first matte takes tens of seconds per second of footage (cached after), and the reply's
        behind_person says what was placed, what was skipped, how long it took and the room around the person (frame pixels: the top of
        the person, the head's width, where the shoulders start). If a cut-out can't be placed the call
        fails with the reason, no scene is added and the timeline is unchanged (behind_person=false adds it with nothing
        in front); when there is no footage under the scene to cut out, the scene is added and the reply says so. The cut-out is its own timeline item: revise leaves it alone, and moving,
        trimming or deleting the scene does not move, trim or delete it. The footage on the first video track
        under the scene is cut out; audio and other video tracks are not.
        create and revise also return scene_change, measured on the scene alone: stills about every 2 s (at most 24),
        moved_pct = the share of the picture whose colour moved more than 8% between each pair, and little = stretches
        of 8 s or more where every step moved under 3%. A measurement, not a judgement."""
        result = run(action, project, scene_id, script, html, css, params,
                     duration, at, track, title, anchor, revision, favorite_id, times, count, behind_person, edits)
        sheet = result.get('sheet') or (result.get('look') or {}).get('sheet')
        if sheet and Path(sheet).is_file():
            return [Image(data=Path(sheet).read_bytes(), format='jpeg'), result]
        return [result]


if __name__ == '__main__':
    import sys
    if len(sys.argv) in (3, 5) and sys.argv[1] == '--refresh':
        if len(sys.argv) == 5 and sys.argv[3] == '--window-pid':
            _stop_with_window(int(sys.argv[4]))
        # Started by a window: minutes of drawing in the background must not slow what the person is doing.
        import letitedit.core.render_lock as render_lock
        render_lock.below_normal()      # typed for 64-bit: an untyped SetPriorityClass call silently did nothing

        def masks_progress(done, of, old_set):
            print(json.dumps({'masks': 'drawing', 'done': done, 'of': of, 'old_set': old_set}), flush=True)
        print(json.dumps(refresh_project(sys.argv[2], progress=masks_progress)), flush=True)
    elif len(sys.argv) == 4 and sys.argv[1] == '--prepare-export':
        def report(index, total, scene):
            print(json.dumps({'index': index, 'total': total, 'scene': scene['id']}), flush=True)
        prepared = prepare_export(sys.argv[2], sys.argv[3], report)
        print(json.dumps({'done': len(prepared)}), flush=True)
    elif len(sys.argv) == 3 and sys.argv[1] == '--preview':
        print(json.dumps(preview_frames(sys.argv[2])), flush=True)
    else:
        raise SystemExit('usage: code_scenes.py --refresh <project.mlt> | --prepare-export <snapshot.mlt> <project.mlt> | --preview <revision-folder>')
