"""What letitedit_caption_fit measured, reused for pictures and caption texts that didn't change (T362). On by default.

A caption fit measures three things with the export engine: the faces in the picture under the captions (a frame
rendered with the text hidden, then the face detector), each caption's text block (rendered in the track's style) and
the visible pixels of other text overlays. Before, the faces were cached per timeline frame under a fingerprint of the
whole picture, so any picture edit (a trim on the main track moves every frame after it) rendered every face frame
again, and the text blocks and overlay pixels were measured afresh on every fit. With the switch on:

- `frame_keys`: each timeline frame's key is what that frame shows, not where it sits: for every video track that is
  drawn in the face render (bottom to top), the item under the frame with its source file (size and time), the source
  frame it plays (speed and direction included), and its picture effects. Sound-only effects are left out. An item
  whose picture changes along its length (a fade, keyframes, a transition, a drawn graphic or scene) also keys by its
  frame's place inside the item and its distance to the item's end. Track and master settings, the profile, the export
  engine and the face model are in every key. A frame keeps its faces through any edit that leaves what it shows
  as it was;
- `text_blocks`: each caption block measured once per text, place, style, frame size, font file and text engine;
- `alpha_boxes`: an overlay file's visible pixels measured once per file (size and time), stretch and frame size.

A key that can't be made falls back to measuring, as before. The switch: settings.json `caption_fit_reuse`;
LETITEDIT_CAPTION_FIT_REUSE (1 or 0) wins."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from letitedit.pictures.caption_layout_frame import CACHE, FFMPEG, MELT

SETTING = 'caption_fit_reuse'
ENV = 'LETITEDIT_CAPTION_FIT_REUSE'
VERSION = 'r1'       # a new key format starts a new cache
# what an item says about its place on the timeline or why it's there, not what it shows
PLACE_FIELDS = ('id', 'at', 'pin', 'len', 'in', 'out', 'from', 'note', 'why', 'edge_mode', 'edge_reason')
# effects that only change the sound (letitedit.timeline.stack.AUDIO_WORDS, and a voice fix)
SOUND_EFFECTS = ('mute', 'gain', 'fade_in_audio', 'fade_out_audio', 'split_mute', 'loudness', 'limiter')
# anything in an effect's text that may make its picture change along the item (keyframes, fades, moves): such an item
# keys by its frame's place in it too. Over-matching only costs a measurement, never a wrong reuse.
MOVING = ('"keys"', 'fade', 'anim', '=', ';', '"to"', '"from"', '"start"', '"end"', 'ken', 'move', 'shake', 'ramp',
          'speed', 'wiggle', 'pulse', 'zoom_in', 'zoom_out', 'push', 'spin')
PICTURE_ITEMS = ('graphic', 'scene', 'raw', 'color', 'ffmpeg', 'vfx', 'ass', 'made', 'adjust')


def enabled():
    """Whether caption_fit reuses measurements (default on; the environment variable, 1 or 0, wins)."""
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


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _stamp(path, memo):
    if path not in memo:
        try:
            st = os.stat(path)
            memo[path] = [st.st_size, st.st_mtime_ns]
        except OSError:
            memo[path] = None
    return memo[path]


def _engine(memo):
    import letitedit.review.checks as checks
    return [[str(p), _stamp(str(p), memo)] for p in (MELT, checks.YUNET)]


def _files(value, folder, memo, out):
    """Stamps of every file an item names (its clip, a graphic's or a scene's files)."""
    if isinstance(value, dict):
        for child in value.values():
            _files(child, folder, memo, out)
    elif isinstance(value, list):
        for child in value:
            _files(child, folder, memo, out)
    elif isinstance(value, str) and len(value) < 600 and ('\\' in value or '/' in value) and '.' in value:
        p = Path(value)
        if not p.is_absolute():
            p = Path(folder) / p
        try:
            if p.is_file():
                key = str(p.resolve())
                out[key] = _stamp(key, memo)
        except OSError:
            pass


def _picture_effects(effects):
    out = []
    for e in effects or []:
        if isinstance(e, str) and e in SOUND_EFFECTS:
            continue
        if isinstance(e, dict):
            names = [k for k in e if k not in ('floor_db', 'opacity', 'style')]
            if names and all(k in SOUND_EFFECTS for k in names):
                continue
            if list(e) == ['fix'] and isinstance(e['fix'], dict) and e['fix'].get('kind') == 'voice':
                continue
        out.append(e)
    return out


def _moving(value):
    text = json.dumps(value, sort_keys=True, default=str).lower()
    return any(m in text for m in MOVING)


def _item_part(it, a, b, f, fps, folder, memo):
    """What item `it` (frames a..b on its track) shows at frame f, as a JSON-able value."""
    from letitedit.timeline.edit_script import to_seconds
    body = {k: v for k, v in it.items() if k not in PLACE_FIELDS and k not in ('effects', 'mute')}
    effects = _picture_effects(it.get('effects'))
    files = {}
    _files(it, folder, memo, files)
    part = {'item': body, 'effects': effects, 'files': files}
    offset, to_end = f - a, b - f
    moving = bool(it.get('transition')) or _moving(effects) or any(k in it for k in PICTURE_ITEMS) or \
        'clip' not in it or bool(it.get('reverse')) or 'freeze' in it
    if 'clip' in it and not it.get('reverse') and 'freeze' not in it:
        speed = float(it.get('speed', 1.0) or 1.0)
        part['source_frame'] = round(to_seconds(it.get('in', 0)) * fps / speed) + offset
    if moving:      # its picture can change along it: the frame's place in it, and the item's own edges
        part['offset'], part['to_end'] = offset, to_end
        part['in'], part['out'], part['len'] = it.get('in'), it.get('out'), it.get('len')
    return part


def frame_keys(script, path, hidden_names, frames, size=None):
    """{timeline frame: key} of what each frame shows in the face render (the module text). Tracks named in
    `hidden_names` are hidden in that render and left out; `size` is the frame the faces are measured in. Raises when
    the script can't be read this way."""
    from letitedit.timeline.edit_sync import layout
    fps = float((script.get('profile') or {}).get('fps') or 30)
    folder = Path(path).resolve().parent
    memo = {}
    master = script.get('master')
    common = {'v': VERSION, 'profile': script.get('profile'), 'master': master, 'engine': _engine(memo),
              'size': list(size) if size else None}
    whole_moving = _moving(master) if master else False
    tracks = []
    for t in script.get('tracks') or []:
        if t.get('kind', 'video') != 'video' or t.get('name') in hidden_names:
            continue
        meta = {k: v for k, v in t.items() if k not in ('items', 'name')}
        if t.get('hide') in ('video', 'both'):
            tracks.append((meta, []))
            continue
        if meta and _moving(meta):
            whole_moving = True
        spans = []
        for it, s, e in layout(t, fps):
            a, b = int(round(s * fps)), int(round(e * fps))
            if b > a:
                spans.append((a, b, it))
        tracks.append((meta, spans))
    out = {}
    for f in frames:
        stack = []
        for meta, spans in tracks:
            stack.append([meta, [_item_part(it, a, b, f, fps, folder, memo) for a, b, it in spans if a <= f < b]])
        key = {**common, 'stack': stack}
        if whole_moving:
            key['frame'] = f
        out[f] = _hash(key)
    return out


def snap_samples(script, path, hidden_names, samples, frames, runs, fps, n_frames, size, reach_s):
    """([(t, t0, t1)], [frame]): each face sample moved to the nearest frame within reach_s of it, inside its picture
    run, whose faces were measured before (its own frame first), its window moved with it and kept inside the run. A
    sample with no such frame stays as it is. The grid of samples is on timeline times, so after a trim the frames it
    lands on show other moments; this puts each sample back on a moment measured already."""
    reach = int(reach_s * fps + 1e-9)
    if reach <= 0 or not samples:
        return list(samples), list(frames)
    plans = []
    wanted = set()
    for (t, t0, t1), f in zip(samples, frames):
        run = next(((a, b) for a, b in runs or [] if a <= t < b), None)
        lo, hi = 0, n_frames - 1
        if run:
            lo = max(lo, int(-(-run[0] * fps // 1)))            # the first frame inside the run
            hi = min(hi, int(-(-run[1] * fps // 1)) - 1)        # the last one
        order = [f] + [g for d in range(1, reach + 1) for g in (f - d, f + d) if lo <= g <= hi]
        plans.append((run, order))
        wanted.update(order)
    keys = frame_keys(script, path, hidden_names, sorted(wanted), size)
    known = {g for g in wanted if face_file(keys[g]).is_file()}
    out_s, out_f = [], []
    for ((t, t0, t1), f), (run, order) in zip(zip(samples, frames), plans):
        g = next((x for x in order if x in known), f)
        if g == f:
            out_s.append((t, t0, t1))
            out_f.append(f)
            continue
        d = g / fps - t
        a, b = t0 + d, t1 + d
        if run:
            a, b = max(a, run[0]), min(b, run[1])
        out_s.append((round(g / fps, 4), a, b))
        out_f.append(g)
    return out_s, out_f


def face_file(key):
    return CACHE / 'faces-by-picture' / key[:2] / f'{key}.json'


def read_faces(key):
    try:
        got = json.loads(face_file(key).read_text(encoding='utf-8-sig'))
        return got if isinstance(got, list) else None
    except (OSError, ValueError):
        return None


def write_faces(key, faces):
    _write_text(face_file(key), json.dumps(faces))


def _write_text(path, text):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f'{path.stem}-{uuid.uuid4().hex}.tmp')
        temp.write_text(text, encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass     # the measurement stands without its cache


# ---------------------------------------------------------------------------- caption text blocks

def _text_engine(memo):
    out = [[str(MELT), _stamp(str(MELT), memo)]]
    for name in ('libmltqt6.dll', 'libmltplus.dll'):
        p = Path(MELT).parent / 'lib' / 'mlt' / name
        out.append([name, _stamp(str(p), memo)])
    return out


def block_key(style, text, geom, frame, memo):
    from letitedit.pictures.caption_layout_render import CAPTION_RENDER_KEYS, resolve_font
    base = {k: style[k] for k in CAPTION_RENDER_KEYS if style.get(k) not in (None, '')}
    try:
        font = resolve_font(style.get('family') or 'Arial', style.get('style'), style.get('weight'))[0]
        font = [str(font), _stamp(str(font), memo)]
    except Exception:  # noqa: BLE001 - the family name alone
        font = None
    return _hash({'v': VERSION, 'style': base, 'shadow': style.get('shadow'), 'text': text, 'geometry': geom,
                  'size': [frame.width, frame.height], 'font': font, 'engine': _text_engine(memo)})


def _block_file(key):
    return CACHE / 'text-blocks' / key[:2] / f'{key}.npz'


def read_block(key):
    import numpy as np
    try:
        with np.load(_block_file(key)) as z:
            if not int(z['has_ink']):
                return {'ink': None, 'mask': None}
            box = tuple(int(v) for v in z['ink'])
            mask = np.unpackbits(z['mask'])[:int(z['n'])].reshape(int(z['h']), int(z['w'])).astype(bool)
            return {'ink': box, 'mask': mask}
    except (OSError, ValueError, KeyError):
        return None


def write_block(key, block):
    import numpy as np
    path = _block_file(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f'{path.stem}-{uuid.uuid4().hex}.tmp.npz')
        if block.get('ink') is None or block.get('mask') is None:
            np.savez(temp, has_ink=0)
        else:
            m = np.asarray(block['mask'], dtype=bool)
            np.savez(temp, has_ink=1, ink=np.array(block['ink'], dtype=np.int64), mask=np.packbits(m.ravel()),
                     n=m.size, h=m.shape[0], w=m.shape[1])
        os.replace(temp, path)
    except OSError:
        pass


# ---------------------------------------------------------------------------- other text overlays' pixels

def alpha_key(path, start_s, dur_s, every_s, frame):
    memo = {}
    return _hash({'v': VERSION, 'file': [str(path), _stamp(str(path), memo)], 'start': round(float(start_s), 3),
                  'dur': round(float(dur_s), 3), 'every': every_s, 'size': [frame.width, frame.height],
                  'ffmpeg': [str(FFMPEG), _stamp(str(FFMPEG), memo)]})


def read_alpha(key):
    try:
        got = json.loads((CACHE / 'alpha-boxes' / key[:2] / f'{key}.json').read_text(encoding='utf-8-sig'))
        return [(t, tuple(b)) for t, b in got] if isinstance(got, list) else None
    except (OSError, ValueError, TypeError):
        return None


def write_alpha(key, boxes):
    _write_text(CACHE / 'alpha-boxes' / key[:2] / f'{key}.json',
                json.dumps([[None if t is None else float(t), [float(v) for v in b]] for t, b in boxes]))
