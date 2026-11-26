r"""Motion meaning: what happens in each motion event and each shot of a video or an edit, read by the local vision
model, every label type with its accuracy measured on a labelled set. The timing perception layer's 'meaning' lane
and 'meaning' view (TIMING-SPEC.md). Measurement gives the exact timing (motion events, shots); the model gives the
meaning ("tool use: hand tightens the set screw; done").

    meaning(source, start=None, end=None, events=None, shots=None, settings=None, refresh=False, build=None,
            kinds=('event', 'shot'), progress=None)
        -> lane dict: 'meaning' [items], 'accuracy', 'legend', 'method', 'version', 'settings', plus the common contract
           fields (schema_version, result_id, project_revision, source_fingerprints, checked_ranges,
           unchecked_ranges, warnings, unsupported, preview_artifacts, changes)
    compute_lane(ctx)        the 'meaning' lane for timing_signals.register_lane (events and shots from ctx['lanes'])
    view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
        -> {'images': [png paths], 'lines': [...], 'meaning': [items], ...contract fields}   (timing view 'meaning')
    lines(result) / legend() text for replies;  accuracy() / accuracy_info() the measured accuracy
    thresholds()             this module's settings: DEFAULTS merged with the 'meaning.*' keys of timing_thresholds.json
    item_frames(...), prompt_for(...), parse(...), ask(...)   the pieces, used by the label-set scripts

An item (one per labelled motion event or shot part):
    {'kind': 'event'|'shot', 'id', 'f0', 'f1', 't0', 't1', 'f_peak', 't_peak' (events), 'shot' (its shot's number),
     'part' ([k, n] when a long shot is labelled in parts), 'label' (what happens: one of the vocabulary),
     'what' (a few words), 'completes' (True, False, or None = unclear / not asked), 'size', 'camera', 'subject',
     'confidence' (of 'label', 0-1), 'accuracy_basis' {type: measured accuracy, 'n', 'set'},
     'labels' {type: {'value', 'answer', 'confidence', 'accuracy', 'trusted', 'from'}}, 'frames' [{'f', 't', 'role'}],
     'cached': 'exact'|'near'|False, 'raw' (the model's reply)}
Label types: 'action' (closed vocabulary per kind of footage, VOCABULARIES), 'completes' (yes / no / unclear: is the
action finished by the last frame shown), 'size' (close-up / medium / wide), 'camera' (handheld / locked off),
'subject' (SUBJECTS), and 'what' (free words, graded by hand on the label set). A type whose measured accuracy is
under min_accuracy (default 0.8) is kept, marked '~' in every text and image and 'trusted': False.
'confidence' of an answer = how often that answer was right on the label set (shrunk toward the type's accuracy):
a measured number, not the model's own say-so. A run with a model or design the label set did not measure gets no
trusted label.

Conventions (the store's): frames are indexes on the source's frame grid (t = f / fps); ranges are half-open
[f0, f1): f0 is the first frame, f1 the first frame after (t1 = f1 / fps).
Events and shots: from the store (timing_signals lanes 'motion_events' ('events') and 'shots', when present) or
given by the caller, else from this module's fallback (bursts of residual motion in shots.features, shots from
shots.detect). With the store, meaning() asks signals(lanes=['meaning']) so the lane is computed and cached there;
without it a project's preview render is made here (melt, small, same fps).
Frames: per design ('3f': before / peak / after; '6f': before, start, rise, peak, fall, after; 'strip': one image of
strip_n numbered frames), always inside the item's shot. Answers are cached per item by the content of the frames
shown (16x16 grey thumbnails: exact key, plus a near match so a re-rendered preview reuses them), the prompt, the
design and the model, under <cache>\meaning. GPU work goes through model_tools.describe (its GPU turn and memory
requests); this module never loads a model itself.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import base64
import contextlib
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'meaning'
THRESHOLDS_FILE = Path(os.environ.get('LETITEDIT_TIMING_THRESHOLDS', str(HERE / 'timing_thresholds.json')))
ACCURACY_FILE = HERE / 'motion_meaning_accuracy.json'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
FFMPEG_THREADS = int(os.environ.get('LETITEDIT_FFMPEG_THREADS', '4'))         # decoder threads per frame grab
FRAME_WORKERS = int(os.environ.get('LETITEDIT_MEANING_FRAME_WORKERS', '2'))   # frame grabs at once
SCHEMA_VERSION = 1
LANE_VERSION = 1            # the lane's data (bump when items change shape or meaning)
PROMPT_VERSION = 1          # the prompts and parsing (part of every answer's cache key)
FALLBACK_VERSION = 1        # the fallback motion events

# ------------------------------------------------------------------ vocabulary

ACTIONS = ['hands working', 'tool use', 'part moves', 'person gestures', 'person moves', 'animal moves',
           'vehicle moves', 'camera move only', 'nothing happens']
ACTION_HINTS = {
    'hands working': 'hands hold, fit, turn, pull or place something by hand',
    'tool use': 'a tool such as a screwdriver, drill, wrench, pliers or hammer works on something',
    'part moves': 'a part or object moves by itself or by machine, e.g. a fan spins, a lid drops',
    'person gestures': 'a person stays in place and talks, points, nods or waves',
    'person moves': 'a person walks, turns, sits down, stands up, comes in or goes out',
    'animal moves': 'an animal moves',
    'vehicle moves': 'a vehicle drives, or the view is from a moving vehicle',
    'camera move only': 'nothing in the scene moves, only the camera pans, tilts, zooms or walks',
    'nothing happens': 'no clear motion',
}
# per kind of footage: the answers offered, in this order (subsets of ACTIONS; accuracy is measured with 'general')
VOCABULARIES = {
    'general': ACTIONS,
    'repair': ['hands working', 'tool use', 'part moves', 'person gestures', 'person moves', 'camera move only',
               'nothing happens'],
    'travel': ['vehicle moves', 'person moves', 'person gestures', 'animal moves', 'part moves', 'camera move only',
               'nothing happens'],
    'talk': ['person gestures', 'person moves', 'hands working', 'camera move only', 'nothing happens'],
}
COMPLETES = ['yes', 'no', 'unclear']
SIZES = ['close-up', 'medium', 'wide']
CAMERAS = ['handheld', 'locked off']
SUBJECTS = ['person', 'hands', 'tool', 'part or machine', 'vehicle', 'animal', 'landscape', 'room or building',
            'object', 'screen or text']
OPTIONS = {'action': ACTIONS, 'completes': COMPLETES, 'size': SIZES, 'camera': CAMERAS, 'subject': SUBJECTS}
LABEL_TYPES = ['action', 'completes', 'size', 'camera', 'subject']

SYN = {
    # action
    'hand working': 'hands working', 'hands work': 'hands working', 'hand work': 'hands working',
    'handwork': 'hands working', 'hands': 'hands working', 'hand': 'hands working',
    'tool': 'tool use', 'tools': 'tool use', 'using a tool': 'tool use', 'tool used': 'tool use',
    'part moving': 'part moves', 'part move': 'part moves', 'object moves': 'part moves', 'machine moves': 'part moves',
    'person gesturing': 'person gestures', 'gestures': 'person gestures', 'gesture': 'person gestures',
    'gesturing': 'person gestures', 'talking': 'person gestures', 'person talks': 'person gestures',
    'person moving': 'person moves', 'person walks': 'person moves', 'walking': 'person moves',
    'animal moving': 'animal moves', 'animal': 'animal moves', 'dog moves': 'animal moves',
    'vehicle moving': 'vehicle moves', 'vehicle': 'vehicle moves', 'driving': 'vehicle moves',
    'camera move': 'camera move only', 'camera moves': 'camera move only', 'camera only': 'camera move only',
    'camera moves only': 'camera move only', 'camera movement only': 'camera move only',
    'camera movement': 'camera move only',
    'nothing': 'nothing happens', 'no motion': 'nothing happens', 'no movement': 'nothing happens',
    'static': 'nothing happens', 'nothing moves': 'nothing happens', 'none': 'nothing happens',
    # completes
    'done': 'yes', 'finished': 'yes', 'complete': 'yes', 'completed': 'yes', 'it is done': 'yes',
    'not finished': 'no', 'not done': 'no', 'ongoing': 'no', 'still going': 'no', 'cut off': 'no',
    'incomplete': 'no', 'in progress': 'no', 'unsure': 'unclear', 'not sure': 'unclear', "can't tell": 'unclear',
    'cannot tell': 'unclear', 'unknown': 'unclear',
    # size
    'close up': 'close-up', 'closeup': 'close-up', 'extreme close-up': 'close-up', 'extreme close up': 'close-up',
    'detail': 'close-up', 'medium shot': 'medium', 'mid': 'medium', 'medium close-up': 'medium',
    'medium close up': 'medium', 'wide shot': 'wide', 'long shot': 'wide', 'establishing': 'wide',
    # camera
    'hand-held': 'handheld', 'hand held': 'handheld', 'shaky': 'handheld', 'moving': 'handheld',
    'locked-off': 'locked off', 'locked': 'locked off', 'tripod': 'locked off', 'fixed': 'locked off',
    'stationary': 'locked off', 'steady': 'locked off', 'still': 'locked off', 'mounted': 'locked off',
    # subject
    'people': 'person', 'man': 'person', 'woman': 'person', 'face': 'person', 'a person': 'person',
    'hand ': 'hands', 'machine': 'part or machine', 'part': 'part or machine', 'motor': 'part or machine',
    'fan': 'part or machine', 'machine or part': 'part or machine', 'part/machine': 'part or machine',
    'car': 'vehicle', 'bus': 'vehicle', 'truck': 'vehicle', 'van': 'vehicle', 'dog': 'animal', 'cat': 'animal',
    'scenery': 'landscape', 'nature': 'landscape', 'sky': 'landscape', 'road': 'landscape',
    'room': 'room or building', 'building': 'room or building', 'interior': 'room or building',
    'room/building': 'room or building', 'screen': 'screen or text', 'text': 'screen or text',
    'sign': 'screen or text', 'screen/text': 'screen or text',
}

# ------------------------------------------------------------------ settings

DEFAULTS = {
    'design': '6f',            # frames shown per item: '3f', '6f' or 'strip' (chosen on the label set)
    'width': 448,              # px wide, each frame shown to the model
    'strip_n': 8,              # 'strip': frames tiled into one image (4 per row) ...
    'strip_tile': 256,         # ... each this many px wide
    'pre_s': 0.25,             # an event's 'before' frame this long before its onset (kept inside its shot)
    'post_s': 0.25,            # its 'after' frame this long after its end (kept inside its shot)
    'shot_max_s': 8.0,         # shots longer than this are labelled in parts of at most this length
    'shot_margin_s': 0.1,      # a shot's first / last frame shown this far inside it (away from the cut)
    'min_event_s': 0.1,        # shorter events are left unlabelled (listed in unchecked_ranges)
    'max_items': 150,          # most items labelled in one call: shots first, then events by strength
    'min_accuracy': 0.8,       # label types measured under this are marked '~' and 'trusted': False
    'vocabulary': 'general',   # answers offered for 'action' (VOCABULARIES)
    'camera_from': 'measured', # 'measured' (the store's camera_label, else the fallback's camera shifts) or 'model';
                               # measured beat the model on the label set (accuracy_info()['camera_measured'])
    'words': False,            # give the model the words said in the item (cached transcripts) as context
    'max_new_tokens': 80,
    'batch': 4,
    'chunk': 24,               # items per model call (the GPU turn is let go between calls)
    'near_match': 2.5,         # cache: frames whose 16x16 grey thumbnails differ under this mean (0-255) reuse answers
    'build': True,             # False: cached answers only (the rest listed in unchecked_ranges)
    'range_s': None,           # [start, end] seconds to label inside the analysed source (None: all of it)
    'preview_px': 640,         # a project's own preview render (no store): long side
    # fallback motion events (used when the store's 'motion_events' lane is missing)
    'fb_smooth_s': 0.1,        # residual change (shots.features 'mad', 0-255 after the camera's move) smoothed over this
    'fb_floor_s': 4.0,         # the quiet level: a running low percentile over this window ...
    'fb_floor_pct': 20.0,      # ... at this percentile
    'fb_k_on': 3.0,            # a burst rises this many robust spreads (1.4826 MAD) above the quiet level ...
    'fb_min_excess': 1.0,      # ... and at least this much (0-255)
    'fb_off_ratio': 0.35,      # it lasts while it stays above this share of the rise threshold
    'fb_merge_gap_s': 0.3,     # bursts closer than this are one event
    'fb_min_dur_s': 0.2,       # shorter bursts are dropped
    'fb_max_event_s': 6.0,     # longer ones are split at their deepest dips
    'fb_cut_guard_s': 0.07,    # frames this close to a cut are not motion
    # measured camera (camera_from='measured'; also reported beside the model's answer)
    'cam_jitter': 0.064,       # frame widths per second of camera shake (high-passed shift) above this: handheld
    'cam_drift': 0.035,        # frame widths per second of net camera travel above this: handheld (a move)
                               # (both fitted on the label set's dev split; labelset/measure_camera.py)
}
DESIGNS = ('3f', '6f', 'strip')
ROLES = {'3f': ['before', 'peak', 'after'], '6f': ['before', 'start', 'rise', 'peak', 'fall', 'after']}
# unit and meaning of each key, written beside its value in timing_thresholds.json ('meaning.<key>')
ABOUT = {
    'design': ('name', "frames shown per item: '3f' before/peak/after, '6f' six frames, 'strip' one tiled image"),
    'width': ('px', 'width of each frame shown to the model'),
    'strip_n': ('frames', "frames tiled into the 'strip' image"),
    'strip_tile': ('px', "width of each 'strip' tile"),
    'pre_s': ('s', "an event's 'before' frame this long before its onset (inside its shot)"),
    'post_s': ('s', "an event's 'after' frame this long after its end (inside its shot)"),
    'shot_max_s': ('s', 'shots longer than this are labelled in parts of at most this length'),
    'shot_margin_s': ('s', "a shot's first and last frame shown this far inside it"),
    'min_event_s': ('s', 'shorter motion events are left unlabelled'),
    'max_items': ('items', 'most items the model labels in one call (shots first, then events by strength)'),
    'min_accuracy': ('share', 'label types measured under this are marked ~ and not trusted'),
    'vocabulary': ('name', 'answers offered for what happens (general, repair, travel, talk)'),
    'camera_from': ('name', "'measured' (camera lane / camera shifts) or 'model' for handheld / locked off"),
    'words': ('bool', 'give the model the words said in the item as context'),
    'max_new_tokens': ('tokens', 'longest model reply'),
    'batch': ('items', 'items per model forward pass'),
    'chunk': ('items', 'items per model call; the GPU turn is let go between calls'),
    'near_match': ('0-255', 'cached answers are reused for frames whose 16x16 grey thumbnails differ under this'),
    'build': ('bool', 'False: cached answers only'),
    'range_s': ('s', '[start, end] to label inside the analysed source; null: all of it'),
    'preview_px': ('px', "long side of this module's own project preview (only without the store)"),
    'fb_smooth_s': ('s', 'fallback events: residual change smoothed over this'),
    'fb_floor_s': ('s', 'fallback events: window of the running quiet level'),
    'fb_floor_pct': ('percentile', 'fallback events: the quiet level percentile'),
    'fb_k_on': ('robust spreads', 'fallback events: rise above the quiet level that starts an event'),
    'fb_min_excess': ('0-255', 'fallback events: smallest rise that starts an event'),
    'fb_off_ratio': ('share', 'fallback events: an event lasts while above this share of the rise threshold'),
    'fb_merge_gap_s': ('s', 'fallback events: closer events are merged'),
    'fb_min_dur_s': ('s', 'fallback events: shorter ones are dropped'),
    'fb_max_event_s': ('s', 'fallback events: longer ones are split at their deepest dips'),
    'fb_cut_guard_s': ('s', 'fallback events: frames this close to a cut are not motion'),
    'cam_jitter': ('frame widths/s', 'measured camera: shake above this means handheld'),
    'cam_drift': ('frame widths/s', 'measured camera: net travel above this means handheld'),
}


def _threshold_file_values():
    try:
        data = json.loads(THRESHOLDS_FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    flat = dict(data)
    for k in ('thresholds', 'values'):
        if isinstance(data.get(k), dict):
            flat.update(data[k])
    out = {}
    for k, v in flat.items():
        if isinstance(k, str) and k.startswith('meaning.'):
            out[k[len('meaning.'):]] = v.get('value') if isinstance(v, dict) and 'value' in v else v
    return out


def thresholds():
    """This module's settings: DEFAULTS with the 'meaning.<name>' keys of timing_thresholds.json over them."""
    vals = dict(DEFAULTS)
    for k, v in _threshold_file_values().items():
        if k in vals and v is not None:
            vals[k] = v
    return vals


def _settings(given=None):
    st = thresholds()
    for k, v in (given or {}).items():
        k = k[len('meaning.'):] if isinstance(k, str) and k.startswith('meaning.') else k
        if k in st and v is not None:
            st[k] = v
    if st['design'] not in DESIGNS:
        raise ValueError(f"design is one of {', '.join(DESIGNS)} (got {st['design']!r})")
    if st['vocabulary'] not in VOCABULARIES:
        raise ValueError(f"vocabulary is one of {', '.join(VOCABULARIES)} (got {st['vocabulary']!r})")
    return st


def write_thresholds(keys=None, path=None):
    """Merge this module's keys ('meaning.<name>': {value, unit, about}, only the ones missing) into
    timing_thresholds.json without touching anyone else's keys. Returns the keys added."""
    path = Path(path or THRESHOLDS_FILE)
    want = {}
    for k in (keys or DEFAULTS):
        unit, about = ABOUT.get(k, ('', ''))
        want[f'meaning.{k}'] = {'about': about, 'unit': unit, 'value': DEFAULTS[k]}
    lock = path.with_name(path.name + '.lock')
    added = []
    deadline = time.monotonic() + 20
    while True:                                   # a small lock file so two builders' merges don't race
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() > deadline or time.time() - lock.stat().st_mtime > 60:
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            time.sleep(0.2)
    try:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f'{path} is not a JSON object; left as it is')
        target = data['thresholds'] if isinstance(data.get('thresholds'), dict) else data
        for k, v in want.items():
            if k not in target:
                target[k] = v
                added.append(k)
        if added:
            if target is data:
                data = {k: data[k] for k in sorted(data, key=lambda k: (not k.startswith('_'), k))}
            tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
            os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()
    return added


# ------------------------------------------------------------------ accuracy

def accuracy_info():
    """The measured accuracy file (motion_meaning_accuracy.json), {} when not measured."""
    try:
        return json.loads(ACCURACY_FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def accuracy(design=None):
    """{label type: share right (0-1)} on the label set for design (default: the measured default design)."""
    info = accuracy_info()
    if design and design != info.get('design'):
        return dict(((info.get('designs') or {}).get(design) or {}).get('accuracy') or {})
    return dict(info.get('accuracy') or {})


def _basis_matches(info, design, model):
    """None when this run's design and model are the ones measured, else why not."""
    if not info:
        return 'no accuracy measured (motion_meaning_accuracy.json is missing)'
    if model and info.get('model_repo') and model != info['model_repo']:
        return f"measured with {info['model_repo']}, this run used {model}"
    if design != info.get('design') and design not in (info.get('designs') or {}):
        return f"design {design!r} was not measured (measured: {info.get('design')})"
    if PROMPT_VERSION != info.get('prompt_version', PROMPT_VERSION):
        return f"prompt version {PROMPT_VERSION} was not measured (measured: {info.get('prompt_version')})"
    return None


def _table(info, design):
    """(accuracy per type, n per type, precision per type and answer) for design."""
    if design == info.get('design') or design not in (info.get('designs') or {}):
        d = info
    else:
        d = info['designs'][design]
    return d.get('accuracy') or {}, d.get('n') or {}, d.get('precision') or {}


def confidence_of(ltype, value, acc_t, precision, shrink=2.0):
    """How often the model's answer `value` for label type ltype was right on the label set, shrunk toward the
    type's accuracy acc_t: (right + shrink * acc_t) / (said + shrink). None for no answer."""
    if value is None or acc_t is None:
        return None
    right, said = (precision.get(ltype) or {}).get(value, (0, 0))
    return round((right + shrink * acc_t) / (said + shrink), 3)


def camera_measured_accuracy(src, info=None):
    """{'accuracy', 'n', 'from'} of the measured camera label from src ('store': the motion lane's camera_label;
    'fallback': this module's camera shifts) on the label set, or None when not measured."""
    info = accuracy_info() if info is None else info
    m = (info.get('camera_measured') or {}).get(src) or {}
    if m.get('accuracy') is None:
        return None
    return {'accuracy': m['accuracy'], 'n': m.get('n'), 'from': f'measured ({src})'}


def legend(min_accuracy=None, design=None, camera=None):
    """One line: each label type's measured accuracy; types under min_accuracy are marked '~'. camera: the measured
    camera label's {'accuracy', 'n'} when the camera answer comes from measurement (camera_measured_accuracy)."""
    info = accuracy_info()
    if not info:
        return 'Meaning accuracy: not measured; no label is trusted.'
    mina = thresholds()['min_accuracy'] if min_accuracy is None else min_accuracy
    design = design or info.get('design')
    acc, n, _ = _table(info, design)
    acc, n = dict(acc), dict(n)
    names = {'action': 'what happens', 'completes': 'done', 'size': 'shot size', 'camera': 'camera',
             'subject': 'subject', 'what': 'words'}
    if camera:
        acc['camera'], n['camera'] = camera['accuracy'], camera.get('n')
        names['camera'] = 'camera (measured)'
    src = info if design == info.get('design') else (info.get('designs') or {}).get(design) or {}
    len_acc = src.get('lenient') or {}
    bits = [f"{'~' if acc[k] < mina else ''}{names.get(k, k)} {math.floor(acc[k] * 100)}% ("
            + (f"{math.floor(len_acc[k] * 100)}% defensible, " if len_acc.get(k) is not None else '')
            + f"n={n.get(k, '?')})" for k in LABEL_TYPES + ['what'] if k in acc]
    weak = [names.get(k, k) for k in LABEL_TYPES + ['what'] if k in acc and acc[k] < mina]
    return (f"Meaning accuracy on {info.get('items', '?')} labelled events and shots ({info.get('model', '?')}, "
            f"design {design}): " + ', '.join(bits) +
            (f"; under {mina:.0%}, marked ~ (check before relying on them): {', '.join(weak)}" if weak else ''))


# ------------------------------------------------------------------ prompts and parsing

def _choices(xs):
    return ', '.join(xs)


SIZE_HINT = ('close-up = a hand, a part or a face fills most of the frame; medium = a person from the waist up or a '
             'work area; wide = a whole room, vehicle or landscape')
CAMERA_HINT = ('handheld = the frame moves or wobbles from one frame to the next; locked off = the frame stays still '
               '(on a tripod or set down)')
DONE_HINT = ('yes = by the last frame the action is finished (the screw is in, the part is off, the hand has let go, '
             'the gesture or the camera move is over); no = it is still going on or is cut off; unclear = you cannot '
             'tell')


def prompt_for(n, kind='event', design='6f', vocabulary='general', said=None):
    """The prompt for one item shown as n frames (or a strip of n) of an event or a shot: a fill-in template of 6
    lines first, then the answer lists with their meaning."""
    acts = VOCABULARIES[vocabulary]
    if design == 'strip':
        head = (f'This image is a strip of {n} frames from a video, in time order: left to right, top row first, '
                f'numbered 1 to {n}.')
    else:
        head = f'These {n} frames come in time order from a video.'
    if kind == 'event':
        if design == 'strip':
            where = f' Frame 1 is just before a burst of motion and frame {n} just after it ends.'
        elif n == 3:
            where = ' Frame 1 is just before a burst of motion, frame 2 is its peak and frame 3 is just after it ends.'
        else:
            where = (f' Frame 1 is just before a burst of motion, frame {n} just after it ends, and the frames between '
                     'follow the motion.')
    else:
        where = ' They are spread over one shot, from its start to its end.'
    context = f'\nWhat is said meanwhile: "{said[:300]}"' if said else ''
    act_lines = '\n'.join(f'- {a}: {ACTION_HINTS[a]}' for a in acts)
    return (f'{head}{where}{context}\n'
            'Look at what moves from the first frame to the last. Reply with exactly these 6 lines and nothing else, '
            'filling in each <...>:\n'
            'Action: <one name from the action list>\n'
            'What: <3 to 8 words of your own: who or what does what>\n'
            'Done: <yes, no or unclear>\n'
            'Shot: <close-up, medium or wide>\n'
            'Camera: <handheld or locked off>\n'
            'Subject: <one name from the subject list>\n\n'
            f'Action list (the main motion):\n{act_lines}\n'
            f'Done: {DONE_HINT}.\n'
            f'Shot: {SIZE_HINT}.\n'
            f'Camera: {CAMERA_HINT}.\n'
            f'Subject list (the main thing seen): {_choices(SUBJECTS)}.')


def prompt_hash(design='6f', vocabulary='general'):
    """A short hash of the prompt templates (part of every cached answer's key, so a prompt change re-asks)."""
    text = ''.join(prompt_for(n, k, design, vocabulary) for k in ('event', 'shot') for n in (3, 6, 8))
    return hashlib.sha1(text.encode()).hexdigest()[:10]


LABEL_KEY = {'action': 'action', 'what': 'what', 'done': 'completes', 'completes': 'completes',
             'finished': 'completes', 'complete': 'completes', 'shot': 'size', 'size': 'size', 'shot size': 'size',
             'framing': 'size', 'camera': 'camera', 'subject': 'subject', 'main subject': 'subject'}


def _norm(s):
    s = str(s).strip().strip('*').strip().lower()
    s = re.sub(r'\s*\(.*?\)\s*', ' ', s)
    s = s.replace('<', ' ').replace('>', ' ')
    return re.sub(r'\s+', ' ', s).strip(' .;,"\'')


ECHO = re.compile(r'^(one (name|answer|of)|pick|choose|<)', re.I)


def _pick(ans, options):
    """The option an answer names (synonyms too; the earliest named wins), or None."""
    a = _norm(ans)
    if not a:
        return None
    if a in options:
        return a
    if a in SYN and SYN[a] in options:
        return SYN[a]
    hits = []
    for o in list(options) + list(SYN):
        val = o if o in options else SYN.get(o)
        if val not in options:
            continue
        m = re.search(r'(?<![\w-])' + re.escape(o.strip()) + r'(?![\w-])', a)
        if m:
            hits.append((m.start(), -len(o), val))
    return sorted(hits)[0][2] if hits else None


def _echo(ans, options):
    """True when an answer repeats the list of answers instead of picking one."""
    a = _norm(ans)
    n = sum(1 for o in options if re.search(r'(?<![\w-])' + re.escape(o) + r'(?![\w-])', a))
    return n >= min(3, len(options))


def parse(reply, vocabulary='general'):
    """{type: answer} from the model's 'Label: answer' lines ('what': free words). A type it didn't answer, or
    answered by repeating the list, is left out; an 'action' outside the vocabulary offered is left out too."""
    out = {}
    offered = dict(OPTIONS, action=VOCABULARIES.get(vocabulary, ACTIONS))
    hints = [_norm(h) for h in ACTION_HINTS.values()]
    for line in str(reply or '').splitlines():
        m = re.match(r'\s*[-*\d.)]*\s*\**([A-Za-z ]{3,14}?)\**\s*:\s*(.*)$', line)
        key = LABEL_KEY.get(m.group(1).strip().lower()) if m else None
        if not key or key in out:
            continue
        ans = m.group(2).strip()
        if ECHO.match(ans.strip().strip('*').strip()):
            continue                                    # the instruction repeated, not an answer
        if key == 'what':
            w = re.sub(r'\s+', ' ', ans.strip().strip('"<>').strip()).rstrip('.')
            nw = _norm(w)
            if w and not nw.startswith(('a few words', '3 to 8 words')) and not any(
                    nw == h or (len(nw) > 25 and nw in h) for h in hints):
                out['what'] = w[:120]
            continue
        if _echo(ans, offered[key]):
            continue
        v = _pick(ans, offered[key])
        if v is not None:
            out[key] = v
    return out


# ------------------------------------------------------------------ files, frames, thumbnails

def _ffmpeg():
    import letitedit.footage.shots as shots
    if Path(shots.FFMPEG).exists():
        return str(shots.FFMPEG)
    import letitedit.timeline.made as made
    return str(made.ffmpeg_exe())


def _fingerprint(path):
    import letitedit.sound.model_tools as model_tools
    return model_tools._fingerprint(str(path))


def _probe(video):
    import letitedit.footage.shots as shots
    return shots.probe(str(video))


def video_grid(video):
    """(fps, frames) of a video file's frame grid: the nominal rate, unless the file's frame count says the frames
    really come at another rate (a phone file with a 120 fps timebase holding 25 fps of frames): then its average."""
    info = _probe(video)
    fps = float(info['fps'] or 30.0)
    dur = float(info.get('duration') or 0.0)
    nb = info.get('frames')
    if nb and dur > 0:
        real = nb / dur
        if abs(real - fps) / fps > 0.15:
            fps = float(info.get('avg_fps') or real)
            if abs(fps - real) / real > 0.15:
                fps = real
    return fps, int(nb or round(dur * fps))


def _frame_path(video, t, width):
    return CACHE / 'frames' / _fingerprint(video) / f'{int(round(t * 1000)):09d}_{int(width)}.jpg'


def frames_at(video, times, width=448, fps=None, workers=None):
    """JPEG paths of the frames shown at `times` (seconds from the file's start), `width` px wide; cached by the
    file's content. A frame that could not be read is None."""
    video = str(video)
    fps = float(fps or video_grid(video)[0] or 30.0)
    out = [None] * len(times)
    todo = []
    for i, t in enumerate(times):
        p = _frame_path(video, t, width)
        if p.exists() and p.stat().st_size > 0:
            out[i] = str(p)
        else:
            todo.append((i, t, p))
    ff = _ffmpeg()

    def grab(job):
        i, t, p = job
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f'{p.stem}.{uuid.uuid4().hex[:6]}.jpg')
        seek = max(0.0, float(t) - 0.3 / fps)
        subprocess.run([ff, '-v', 'error', '-y', '-nostdin', '-threads', str(FFMPEG_THREADS), '-ss', f'{seek:.4f}',
                        '-i', video, '-frames:v', '1', '-vf', f'scale={int(width)}:-2', '-q:v', '3', str(tmp)],
                       creationflags=NO_WINDOW, capture_output=True)
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, p)
            return i, str(p)
        with contextlib.suppress(OSError):
            tmp.unlink()
        return i, None
    if todo:
        with ThreadPoolExecutor(max(1, min(int(workers or FRAME_WORKERS), len(todo)))) as ex:
            for i, p in ex.map(grab, todo):
                out[i] = p
    return out


def _thumb(path):
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert('L').resize((16, 16), Image.BOX), dtype=np.uint8)


def _font(size, bold=False):
    from PIL import ImageFont
    lib = Path(_SAI_ROOT) / 'fonts' / 'library' / 'Atkinson Hyperlegible'
    for f in ([lib / ('AtkinsonHyperlegible-Bold.ttf' if bold else 'AtkinsonHyperlegible-Regular.ttf')] +
              [Path(r'C:\Windows\Fonts') / ('arialbd.ttf' if bold else 'arial.ttf')]):
        with contextlib.suppress(OSError):
            return ImageFont.truetype(str(f), int(size))
    return ImageFont.load_default()


def strip_image(paths, labels=None, tile=256, cols=4, out=None):
    """One JPEG of the frames in `paths` tiled `cols` per row, each `tile` px wide, numbered 1..n (or `labels`)."""
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert('RGB') for p in paths]
    w = int(tile)
    h = max(int(round(im.height * w / im.width)) for im in ims)
    rows = (len(ims) + cols - 1) // cols
    gap = 4
    S = Image.new('RGB', (cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap), (0, 0, 0))
    d = ImageDraw.Draw(S)
    f = _font(max(14, w // 11), bold=True)
    for i, im in enumerate(ims):
        im = im.resize((w, int(round(im.height * w / im.width))))
        x, y = (i % cols) * (w + gap), (i // cols) * (h + gap)
        S.paste(im, (x, y))
        lab = str(labels[i]) if labels else str(i + 1)
        tw = d.textlength(lab, font=f)
        d.rectangle([x, y, x + tw + 10, y + f.size + 8], fill=(0, 0, 0))
        d.text((x + 5, y + 3), lab, fill=(255, 230, 0), font=f)
    if out is None:
        key = hashlib.sha1(json.dumps([str(p) for p in paths] + [labels, tile, cols]).encode()).hexdigest()[:20]
        out = CACHE / 'strips' / f'{key}.jpg'
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(out).with_name(f'{Path(out).stem}.{uuid.uuid4().hex[:6]}.jpg')
    S.save(tmp, quality=88)
    os.replace(tmp, out)
    return str(out)


# ------------------------------------------------------------------ which frames an item shows

def _snap(t, fps, lo, hi):
    """(frame, time) of the frame nearest t inside [lo, hi] (frame numbers)."""
    f = int(round(float(t) * fps))
    f = max(lo, min(hi, f))
    return f, f / fps


def item_frames(item, design, fps, st=None):
    """[(frame, time, role)] an item shows the model, on the source's frame grid, inside the item's shot. The item's
    range and its shot's are half-open ([f0, f1), [shot_f0, shot_f1))."""
    st = st or thresholds()
    lo = int(item.get('shot_f0', item['f0']))
    hi = int(item.get('shot_f1', item['f1'])) - 1           # the shot's last frame
    if item['kind'] == 'event':
        f0, last = int(item['f0']), int(item['f1']) - 1      # the event's first and last frame
        fp = int(item.get('f_peak', (f0 + last) // 2))
        a = max(lo, f0 - int(round(float(st['pre_s']) * fps)))
        b = min(hi, last + int(round(float(st['post_s']) * fps)))
        fp = max(a, min(b, fp))
        if design == '3f':
            fs = [a, fp, b]
        elif design == '6f':
            s0, s1 = max(a, f0), min(b, last)
            fs = [a, s0, int(round((s0 + fp) / 2)), fp, int(round((fp + s1) / 2)), b]
        else:
            n = int(st['strip_n'])
            fs = [int(round(a + (b - a) * i / (n - 1))) for i in range(n)]
    else:
        m = int(round(float(st['shot_margin_s']) * fps))
        a, b = int(item['f0']), int(item['f1']) - 1
        if b - a > 2 * m + 2:
            a, b = a + m, b - m
        n = 3 if design == '3f' else 6 if design == '6f' else int(st['strip_n'])
        fs = [int(round(a + (b - a) * i / (n - 1))) for i in range(n)]
    roles = ROLES.get(design) if item['kind'] == 'event' else None
    out = []
    for i, f in enumerate(fs):
        f, t = _snap(f / fps, fps, lo, hi)
        out.append((f, round(t, 4), (roles[i] if roles and i < len(roles) else f'{i + 1}')))
    return out


# ------------------------------------------------------------------ answer cache (by the content of the frames)

class _AnswerCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.index = {}            # meta hash -> {'keys': [...], 'thumbs': [np.ndarray (k, 16, 16)]}

    @staticmethod
    def folder(meta_hash):
        return CACHE / 'answers' / meta_hash

    def _load(self, meta_hash):
        with self.lock:
            if meta_hash in self.index:
                return self.index[meta_hash]
            idx = {'keys': [], 'thumbs': []}
            d = self.folder(meta_hash)
            if d.exists():
                for f in d.glob('*.json'):
                    try:
                        e = json.loads(f.read_text(encoding='utf-8-sig'))
                        th = np.frombuffer(base64.b64decode(e['thumbs']), np.uint8).reshape(-1, 16, 16)
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                    idx['keys'].append(f.stem)
                    idx['thumbs'].append(th)
            self.index[meta_hash] = idx
            return idx

    def get(self, meta_hash, key, thumbs, near):
        f = self.folder(meta_hash) / f'{key}.json'
        if f.exists():
            with contextlib.suppress(OSError, ValueError):
                return json.loads(f.read_text(encoding='utf-8-sig')), 'exact'
        if not near:
            return None, False
        idx = self._load(meta_hash)
        best, best_d = None, None
        x = thumbs.astype(np.float32)
        for k, th in zip(idx['keys'], idx['thumbs']):
            if th.shape != thumbs.shape:
                continue
            diff = np.abs(th.astype(np.float32) - x)
            d = float(diff.mean())
            if d < float(near) and float(diff.reshape(len(th), -1).mean(1).max()) < 2 * float(near) and \
                    (best_d is None or d < best_d):
                best, best_d = k, d
        if best is None:
            return None, False
        with contextlib.suppress(OSError, ValueError):
            e = json.loads((self.folder(meta_hash) / f'{best}.json').read_text(encoding='utf-8-sig'))
            e['near_d'] = round(best_d, 3)
            return e, 'near'
        return None, False

    def put(self, meta_hash, key, thumbs, entry):
        d = self.folder(meta_hash)
        d.mkdir(parents=True, exist_ok=True)
        entry = dict(entry, thumbs=base64.b64encode(thumbs.astype(np.uint8).tobytes()).decode('ascii'))
        tmp = d / f'{key}.{uuid.uuid4().hex[:6]}.tmp'
        tmp.write_text(json.dumps(entry), encoding='utf-8')
        os.replace(tmp, d / f'{key}.json')
        idx = self._load(meta_hash)
        with self.lock:
            idx['keys'].append(key)
            idx['thumbs'].append(thumbs)


_ANSWERS = _AnswerCache()


def _meta(st, model, kind):
    meta = {'pv': PROMPT_VERSION, 'prompt': prompt_hash(st['design'], st['vocabulary']), 'design': st['design'],
            'model': model or 'default', 'vocab': st['vocabulary'], 'width': int(st['width']), 'kind': kind,
            'tokens': int(st['max_new_tokens']), 'words': bool(st['words'])}
    if st['design'] == 'strip':
        meta.update(strip_n=int(st['strip_n']), strip_tile=int(st['strip_tile']))
    return hashlib.sha1(json.dumps(meta, sort_keys=True).encode()).hexdigest()[:16], meta


def _key(meta_hash, thumbs, said):
    h = hashlib.sha1(meta_hash.encode())
    h.update((thumbs >> 4).astype(np.uint8).tobytes())
    if said:
        h.update(said.encode('utf-8', 'replace'))
    return h.hexdigest()[:24]


# ------------------------------------------------------------------ the model

def ask(prepared, st=None, progress=None, model=None):
    """[(parsed answers, raw reply)] for prepared items [{'images': [paths], 'prompt': str}], and a report
    {'model', 'run_s', 'items', 'retried', 'gpu'}. One model_tools.describe call per `chunk` items; a reply missing
    3 or more closed answers is asked once more."""
    import letitedit.sound.model_tools as model_tools
    st = st or thresholds()
    out, run_s, rep_model, retried, gpu = [], 0.0, None, 0, []
    chunk = max(1, int(st['chunk']))
    for k in range(0, len(prepared), chunk):
        part = prepared[k:k + chunk]
        rep = model_tools.describe([{'images': p['images'], 'prompt': p['prompt']} for p in part],
                                   max_new_tokens=int(st['max_new_tokens']), batch=int(st['batch']), model=model)
        texts = list(rep.get('texts') or [])
        run_s += float(rep.get('run_s') or 0)
        rep_model = rep.get('model') or rep_model
        if rep.get('gpu'):
            gpu.append(rep['gpu'])
        retry = [i for i, t in enumerate(texts)
                 if sum(1 for lt in LABEL_TYPES if lt not in parse(t, st['vocabulary'])) >= 3]
        if retry:
            rep2 = model_tools.describe([{'images': part[i]['images'], 'prompt': part[i]['prompt']} for i in retry],
                                        max_new_tokens=int(st['max_new_tokens']) + 40, batch=int(st['batch']),
                                        model=model)
            run_s += float(rep2.get('run_s') or 0)
            for i, t in zip(retry, rep2.get('texts') or []):
                if len(parse(t, st['vocabulary'])) > len(parse(texts[i], st['vocabulary'])):
                    texts[i] = t
            retried += len(retry)
        out += [(parse(t, st['vocabulary']), t) for t in texts]
        if progress:
            progress(min(len(prepared), k + chunk), len(prepared))
    return out, {'model': rep_model, 'run_s': round(run_s, 2), 'items': len(prepared), 'retried': retried,
                 'gpu': gpu[-1] if gpu else None}


# ------------------------------------------------------------------ the store (timing_signals, B1) and the fallback

def _lane_list(lane, *names):
    """The list a lane holds: the lane itself when it is a list, else its first list-valued key among names."""
    if lane is None:
        return None
    if isinstance(lane, list):
        return lane
    if isinstance(lane, dict):
        for k in names:
            if isinstance(lane.get(k), list):
                return lane[k]
    return None


def _store(source, start=None, end=None, lanes=('motion_events', 'shots', 'motion'), settings=None, refresh=False):
    """timing_signals.signals(...) for the given lanes, or (None, why) when the store is missing or fails."""
    try:
        import letitedit.timing.timing_signals as ts
    except ImportError:
        return None, 'timing_signals (the shared signal store) is not installed'
    fn = getattr(ts, 'signals', None)
    if fn is None:
        return None, 'timing_signals has no signals()'
    try:
        return fn(str(source), start=start, end=end, lanes=list(lanes), refresh=refresh, settings=settings), None
    except Exception as e:  # noqa: BLE001 - the fallback takes over, and says so
        return None, f'timing_signals.signals failed: {type(e).__name__}: {e}'


def _running_pct(x, win, pct, hop):
    """A running percentile of x over `win` samples, computed every `hop` samples and interpolated."""
    n = len(x)
    if n == 0:
        return x
    centers = np.arange(0, n, max(1, hop))
    vals = np.empty(len(centers))
    half = max(1, win // 2)
    for j, c in enumerate(centers):
        vals[j] = np.percentile(x[max(0, c - half):min(n, c + half + 1)], pct)
    return np.interp(np.arange(n), centers, vals)


def _split_long(e, a, b, max_len):
    """[(a, b)] index runs of at most max_len samples, split at the deepest dips of e."""
    if b - a + 1 <= max_len:
        return [(a, b)]
    lo, hi = a + max_len // 4, b - max_len // 4
    if hi <= lo:
        mid = (a + b) // 2
    else:
        mid = lo + int(np.argmin(e[lo:hi + 1]))
    return _split_long(e, a, mid, max_len) + _split_long(e, mid + 1, b, max_len)


def fallback_signals(video, st=None):
    """This module's own motion events, shots and measured camera for a video file (no store):
    {'motion_events': [{f0, f_peak, f1, t0, t_peak, t1, strength, region}], 'shots': [{f0, f1, kind_in}],
     'camera': {'t': [...], 'dx': [...], 'dy': [...]} (frame widths per analysed frame), 'fps', 'frames', 'method',
     'settings', 'energy': {'t', 'e', 'floor', 'on'}}."""
    import letitedit.footage.shots as shots
    st = st or thresholds()
    fps, frames = video_grid(video)
    fe = shots.features(str(video))
    det = shots.detect(str(video))
    t = np.asarray(fe['t'], dtype=np.float64)
    n = len(t)
    fps_a = (n - 1) / max(1e-6, float(t[-1] - t[0])) if n > 1 else fps     # analysed frames per second
    mad = np.nan_to_num(np.asarray(fe['mad'], dtype=np.float64), nan=0.0)
    cut_list = [c for c in det.get('cuts') or []]
    cut_ts = sorted({float(c['t']) for c in cut_list} | {float(c.get('start', c['t'])) for c in cut_list})
    guard = float(st['fb_cut_guard_s']) + 0.5 / fps_a
    mask = np.zeros(n, bool)
    for c in cut_ts:
        mask |= np.abs(t - c) <= guard
    mad = np.where(mask, 0.0, mad)
    k = max(1, int(round(float(st['fb_smooth_s']) * fps_a)))
    e = np.convolve(mad, np.ones(k) / k, mode='same') if n else mad
    floor = _running_pct(e, max(3, int(round(float(st['fb_floor_s']) * fps_a))), float(st['fb_floor_pct']),
                         max(1, int(round(0.25 * fps_a))))
    excess = e - floor
    med = float(np.median(excess)) if n else 0.0
    spread = 1.4826 * float(np.median(np.abs(excess - med))) if n else 0.0
    on = max(float(st['fb_min_excess']), float(st['fb_k_on']) * spread)
    off = float(st['fb_off_ratio']) * on
    # runs above `on`, grown while above `off`, merged across short gaps, never across a cut
    above = excess > on
    runs, i = [], 0
    while i < n:
        if above[i]:
            j = i
            while j + 1 < n and above[j + 1]:
                j += 1
            a, b = i, j
            while a - 1 >= 0 and excess[a - 1] > off and not mask[a - 1]:
                a -= 1
            while b + 1 < n and excess[b + 1] > off and not mask[b + 1]:
                b += 1
            runs.append([a, b])
            i = b + 1
        else:
            i += 1
    gap = float(st['fb_merge_gap_s'])
    merged = []
    for a, b in runs:
        if merged and t[a] - t[merged[-1][1]] <= gap and not any(t[merged[-1][1]] < c <= t[a] for c in cut_ts):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    max_len = max(2, int(round(float(st['fb_max_event_s']) * fps_a)))
    pieces = []
    for a, b in merged:
        pieces += _split_long(e, a, b, max_len)
    grid = np.asarray(fe['grid'], dtype=np.float64)
    G = int(round(math.sqrt(grid.shape[1]))) if grid.ndim == 2 and grid.shape[1] else 0
    events = []
    for a, b in pieces:
        if t[b] - t[a] + 1.0 / fps_a < float(st['fb_min_dur_s']):
            continue
        p = a + int(np.argmax(e[a:b + 1]))
        region = None
        if G:
            cells = np.nan_to_num(grid[a:b + 1]).mean(0)
            top = cells.max()
            if top > 0:
                hot = np.flatnonzero(cells >= 0.6 * top)
                rows, cols = hot // G, hot % G
                region = [round(float(cols.min()) / G, 3), round(float(rows.min()) / G, 3),
                          round(float(cols.max() + 1) / G, 3), round(float(rows.max() + 1) / G, 3)]
        f0, fp, last = (int(round(t[x] * fps)) for x in (a, p, b))
        f1 = last + 1                                     # half-open: the first frame after the event
        events.append({'f0': f0, 'f_peak': fp, 'f1': f1, 't0': round(f0 / fps, 4), 't_peak': round(fp / fps, 4),
                       't1': round(f1 / fps, 4), 'strength': round(float(excess[p] / on), 3), 'region': region})
    shot_list = []
    kinds_in = {round(float(c['t']), 3): c.get('kind') for c in cut_list}
    for s in det.get('shots') or []:
        a = int(round(float(s['start']) * fps))
        b = min(frames, int(round(float(s['end']) * fps)))
        shot_list.append({'f0': a, 'f1': max(a + 1, b), 'kind_in': kinds_in.get(round(float(s['start']), 3))})
    if not shot_list:
        shot_list = [{'f0': 0, 'f1': max(1, frames), 'kind_in': None}]
    return {'motion_events': events, 'shots': shot_list, 'fps': fps, 'frames': frames,
            'camera': {'t': t.tolist(), 'dx': np.nan_to_num(fe['dx']).tolist(), 'dy': np.nan_to_num(fe['dy']).tolist(),
                       'fps_a': fps_a},
            'energy': {'t': t, 'e': e, 'floor': floor, 'on': on, 'off': off, 'spread': spread},
            'method': ('fallback: bursts of residual change after the camera move (shots.features mad, 0-255 at '
                       f'{fe["size"][0]}x{fe["size"][1]}), smoothed {st["fb_smooth_s"]} s, above a running '
                       f'{st["fb_floor_pct"]:g}th-percentile floor ({st["fb_floor_s"]} s) by {st["fb_k_on"]} robust '
                       f'spreads (at least {st["fb_min_excess"]}); shots from shots.detect'),
            'settings': {k: v for k, v in st.items() if k.startswith('fb_')}, 'version': FALLBACK_VERSION}


def measured_camera(cam, t0, t1, st=None):
    """('handheld' | 'locked off' | None, {'jitter', 'drift'}) of the camera between t0 and t1 (seconds) from the
    fallback's per-frame camera shifts (frame widths per analysed frame)."""
    st = st or thresholds()
    if not cam or not cam.get('t'):
        return None, {}
    t = np.asarray(cam['t'])
    sel = (t >= t0 - 1e-6) & (t <= t1 + 1e-6)
    if sel.sum() < 4:
        return None, {}
    fps_a = float(cam.get('fps_a') or 30.0)
    dx = np.asarray(cam['dx'])[sel]
    dy = np.asarray(cam['dy'])[sel]
    k = max(1, int(round(0.25 * fps_a)))
    ker = np.ones(k) / k
    sx, sy = np.convolve(dx, ker, mode='same'), np.convolve(dy, ker, mode='same')
    jitter = float(np.median(np.hypot(dx - sx, dy - sy)) * fps_a)
    drift = float(np.hypot(dx.sum(), dy.sum()) / max(1e-6, (t1 - t0)))
    lab = 'handheld' if (jitter > float(st['cam_jitter']) or drift > float(st['cam_drift'])) else 'locked off'
    return lab, {'jitter_w_per_s': round(jitter, 4), 'drift_w_per_s': round(drift, 4)}


def _camera_from_labels(labels, f0, f1):
    """The store's per-frame camera_label over [f0, f1) -> 'handheld' | 'locked off' | None."""
    if not labels:
        return None
    seg = [x for x in labels[max(0, f0):f1] if x]
    if not seg:
        return None
    still = sum(1 for x in seg if str(x) == 'static')
    return 'locked off' if still >= 0.6 * len(seg) else 'handheld'


# ------------------------------------------------------------------ items

def _shot_of(f, shots_):
    for k, s in enumerate(shots_):
        if s['f0'] <= f < s['f1']:
            return k
    return None


def build_items(events, shots_, fps, frames, st=None, kinds=('event', 'shot'), start_f=None, end_f=None):
    """(items, skipped): events clamped to their shot, and shot parts (shots longer than shot_max_s in equal parts),
    within [start_f, end_f) (half-open frame ranges throughout); skipped = [(f0, f1, why)]."""
    st = st or thresholds()
    shots_ = sorted(({'f0': int(s['f0']), 'f1': int(s['f1']), 'kind_in': s.get('kind_in'), 'size': s.get('size')}
                     for s in (shots_ or []) if int(s['f1']) > int(s['f0'])), key=lambda s: s['f0'])
    if not shots_:
        shots_ = [{'f0': 0, 'f1': max(1, int(frames)), 'kind_in': None, 'size': None}]
    lo = 0 if start_f is None else int(start_f)
    hi = int(frames) if end_f is None else int(end_f)
    items, skipped = [], []
    if 'shot' in kinds:
        max_len = max(1, int(round(float(st['shot_max_s']) * fps)))
        for k, s in enumerate(shots_):
            a, b = max(s['f0'], lo), min(s['f1'], hi)
            if b <= a:
                continue
            n = max(1, int(math.ceil((b - a) / max_len)))
            for j in range(n):
                pa = a + (b - a) * j // n
                pb = a + (b - a) * (j + 1) // n
                items.append({'kind': 'shot', 'id': f's{k + 1:03d}' + (f'.{j + 1}' if n > 1 else ''), 'shot': k + 1,
                              'part': [j + 1, n] if n > 1 else None, 'f0': pa, 'f1': pb, 'shot_f0': s['f0'],
                              'shot_f1': s['f1'], 'strength': None})
    if 'event' in kinds:
        min_len = float(st['min_event_s']) * fps
        for i, ev in enumerate(sorted(events or [], key=lambda e: int(e.get('f0', 0)))):
            f0, f1 = int(ev['f0']), int(ev['f1'])
            fp = int(ev.get('f_peak', (f0 + f1 - 1) // 2))
            if f1 <= lo or f0 >= hi:
                continue
            k = _shot_of(fp, shots_)
            if k is None:
                k = _shot_of(f0, shots_)
            s = shots_[k] if k is not None else {'f0': 0, 'f1': int(frames)}
            f0, f1 = max(f0, s['f0']), min(f1, s['f1'])
            if f1 - f0 < min_len:
                skipped.append((f0, f1, f'shorter than min_event_s ({st["min_event_s"]} s)'))
                continue
            items.append({'kind': 'event', 'id': f'e{i + 1:03d}', 'shot': (k + 1) if k is not None else None,
                          'f0': f0, 'f1': f1, 'f_peak': max(f0, min(f1 - 1, fp)), 'shot_f0': s['f0'],
                          'shot_f1': s['f1'], 'strength': ev.get('strength'), 'region': ev.get('region')})
    return items, skipped


def _said(video, t0, t1):
    try:
        import letitedit.footage.speech as speech
        ws = speech.cached_words(str(video), t0, t1)
    except Exception:  # noqa: BLE001 - words are context, never required
        return None
    return ' '.join(w['w'].strip() for w in ws) if ws else None


def _clock(s):
    s = float(s)
    return f'{int(s // 60)}:{s % 60:05.2f}'


# ------------------------------------------------------------------ the run

def _contract(**kw):
    out = {'schema_version': SCHEMA_VERSION, 'result_id': None, 'project_revision': None, 'source_fingerprints': {},
           'checked_ranges': [], 'unchecked_ranges': [], 'warnings': [], 'unsupported': [], 'preview_artifacts': [],
           'changes': []}
    out.update(kw)
    return out


def _ranges(spans, fps):
    """Merged [{'f0', 'f1', 't0', 't1'}] of half-open (f0, f1) spans."""
    spans = sorted((int(a), int(b)) for a, b in spans)
    out = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [{'f0': a, 'f1': b, 't0': round(a / fps, 3), 't1': round(b / fps, 3)} for a, b in out]


def _most_important_items(items, st, unchecked):
    """Every shot part first, then events by strength, up to max_items; the rest are listed as unchecked."""
    # most important first: every shot part, then events by strength, up to max_items
    shots_first = [it for it in items if it['kind'] == 'shot']
    evs = sorted((it for it in items if it['kind'] == 'event'), key=lambda it: -(it.get('strength') or 0))
    keep = (shots_first + evs)[:max(0, int(st['max_items']))]
    for it in (shots_first + evs)[len(keep):]:
        unchecked.append((it['f0'], it['f1'], f"over max_items ({st['max_items']}): {it['kind']} {it['id']}"))
    keep_ids = {id(x) for x in keep}
    items = [it for it in items if id(it) in keep_ids]
    return items


def _prepare_questions(items, plans, paths, video, st, model_name, refresh, unchecked):
    """Per item: its frames, then a cached answer when there is one, else the pictures and prompt to ask the
    model."""
    prepared, todo = [], []
    for it, plan in zip(items, plans):
        ims = [paths.get(t) for _, t, _ in plan]
        it['frames'] = [{'f': f, 't': t, 'role': r} for f, t, r in plan]
        if any(p is None for p in ims):
            it['error'] = 'frames could not be read'
            unchecked.append((it['f0'], it['f1'], f"{it['kind']} {it['id']}: frames could not be read"))
            continue
        thumbs = np.stack([_thumb(p) for p in ims])
        said = _said(video, plan[0][1], plan[-1][1]) if st['words'] else None
        meta_hash, _ = _meta(st, model_name, it['kind'])
        key = _key(meta_hash, thumbs, said)
        hit, how = (None, False) if refresh else _ANSWERS.get(meta_hash, key, thumbs, st['near_match'])
        if hit is not None:
            it['_answer'] = hit
            it['cached'] = how
            continue
        it['cached'] = False
        if st['design'] == 'strip':
            shown = [strip_image(ims, tile=int(st['strip_tile']))]
        else:
            shown = ims
        prepared.append({'images': shown, 'prompt': prompt_for(len(ims), it['kind'], st['design'], st['vocabulary'],
                                                              said)})
        todo.append((it, meta_hash, key, thumbs))
    return prepared, todo


def _measured_camera_label(labels, it, parsed, info, camera_labels, camera_shifts, fps, st, mina):
    """The measured camera move beside the model's camera answer (and in its place when camera_from is
    'measured')."""
    # measured camera beside the model's answer
    cam_meas, cam_info, cam_src = None, {}, None
    if camera_labels is not None:
        fr = it['frames']                       # the window the model saw
        cam_meas = _camera_from_labels(camera_labels, fr[0]['f'], fr[-1]['f'] + 1)
        cam_info, cam_src = {'from': 'store motion lane camera_label (static = locked off)'}, 'store'
    elif camera_shifts is not None:
        fr = it['frames']                       # the window the model saw
        cam_meas, cam_info = measured_camera(camera_shifts, fr[0]['t'], fr[-1]['t'] + 1.0 / fps, st)
        cam_info, cam_src = dict(cam_info, **{'from': 'shots.features camera shifts'}), 'fallback'
    if cam_meas is not None:
        ca = ((info.get('camera_measured') or {}).get(cam_src) or {}).get('accuracy')
        labels['camera']['measured'] = cam_meas
        labels['camera']['measured_basis'] = dict(cam_info, accuracy=ca)
        if st['camera_from'] == 'measured':
            labels['camera'].update(value=cam_meas, **{'from': 'measured'}, accuracy=ca, answer=parsed.get('camera'),
                                    confidence=ca, trusted=bool(ca is not None and ca >= mina))


def run(video, fps, frames, events, shots_, st, camera_labels=None, camera_shifts=None, kinds=('event', 'shot'),
        start_f=None, end_f=None, refresh=False, progress=None, events_from='given', model=None, video_offset_s=0.0):
    """Label events and shots of an analysis video (the source file, or a project's preview render) -> the lane dict
    (without the source-level contract fields, which meaning() / compute_lane() add). video_offset_s: the source
    time of the analysis video's first frame (a preview of part of a long project starts at its range)."""
    t_start = time.time()
    warnings, unsupported = [], []
    items, skipped = build_items(events, shots_, fps, frames, st, kinds, start_f, end_f)
    unchecked = [(a, b, why) for a, b, why in skipped]
    items = _most_important_items(items, st, unchecked)
    # frames
    t1 = time.time()
    plans = [item_frames(it, st['design'], fps, st) for it in items]
    times = sorted({t for p in plans for _, t, _ in p})
    off = float(video_offset_s or 0.0)
    paths = dict(zip(times, frames_at(video, [max(0.0, t - off) for t in times], int(st['width']), fps)))
    frames_s = time.time() - t1
    model_name = model
    prepared, todo = _prepare_questions(items, plans, paths, video, st, model_name, refresh, unchecked)
    report = {'model': None, 'run_s': 0.0, 'items': 0}
    if todo and not st['build']:
        for it, _, _, _ in todo:
            it['error'] = 'not built (build=False): no cached answer'
            unchecked.append((it['f0'], it['f1'], f"{it['kind']} {it['id']}: not labelled yet (build=False)"))
        todo = []
    if todo:
        answers, report = ask(prepared, st, progress=progress, model=model)
        model_name = report.get('model')
        per = report['run_s'] / max(1, len(todo))
        for (it, meta_hash, key, thumbs), (parsed, raw) in zip(todo, answers):
            entry = {'parsed': parsed, 'raw': raw, 'model': model_name, 'design': st['design'],
                     'prompt_version': PROMPT_VERSION, 'run_s': round(per, 3),
                     'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'seen_in': str(video),
                     'frames': it['frames']}
            _ANSWERS.put(meta_hash, key, thumbs, entry)
            it['_answer'] = entry
    # labels, confidence, trust
    info = accuracy_info()
    used_models = {it['_answer'].get('model') for it in items if it.get('_answer')} - {None}
    run_model = model_name or (sorted(used_models)[0] if used_models else None)
    mismatch = _basis_matches(info, st['design'], run_model)
    acc_t, n_t, prec = _table(info, st['design']) if not mismatch else ({}, {}, {})
    if mismatch:
        warnings.append(f'labels not trusted: {mismatch}')
    if st['vocabulary'] != 'general':
        warnings.append(f"vocabulary {st['vocabulary']!r}: accuracy was measured with 'general' (all answers offered)")
    mina = float(st['min_accuracy'])
    cam_src_all = 'store' if camera_labels is not None else 'fallback' if camera_shifts is not None else None
    cam_over = (camera_measured_accuracy(cam_src_all, info) if st['camera_from'] == 'measured' and cam_src_all
                else None)                      # measured camera: its own accuracy, whatever the model
    out_items = []
    for it in items:
        ans = it.pop('_answer', None)
        if ans is None:
            continue
        parsed = ans.get('parsed') or {}
        labels = {}
        for lt in LABEL_TYPES:
            v = parsed.get(lt)
            a = acc_t.get(lt)
            labels[lt] = {'value': v, 'answer': v, 'accuracy': a, 'from': 'model',
                          'confidence': confidence_of(lt, v, a, prec) if v is not None and v != 'unclear' else None,
                          'trusted': bool(a is not None and a >= mina and v is not None)}
        _measured_camera_label(labels, it, parsed, info, camera_labels, camera_shifts, fps, st, mina)
        comp = labels['completes']['value']
        row = {'kind': it['kind'], 'id': it['id'], 'f0': it['f0'], 'f1': it['f1'],
               't0': round(it['f0'] / fps, 4), 't1': round(it['f1'] / fps, 4)}
        if it['kind'] == 'event':
            row.update(f_peak=it['f_peak'], t_peak=round(it['f_peak'] / fps, 4), strength=it.get('strength'),
                       region=it.get('region'))
        row.update(shot=it.get('shot'), part=it.get('part'),
                   label=labels['action']['value'], what=parsed.get('what'),
                   completes=True if comp == 'yes' else False if comp == 'no' else None,
                   size=labels['size']['value'], camera=labels['camera']['value'], subject=labels['subject']['value'],
                   confidence=labels['action']['confidence'],
                   accuracy_basis=dict({**{lt: acc_t.get(lt) for lt in LABEL_TYPES + ['what'] if lt in acc_t},
                                        'n': n_t.get('action'), 'set': info.get('label_set_name'),
                                        'design': st['design']} if not mismatch else {'none': mismatch},
                                       **({'camera': labels['camera']['accuracy'], 'camera_from': 'measured'}
                                          if labels['camera'].get('from') == 'measured' else {})),
                   labels=labels, frames=it['frames'], cached=it.get('cached', False), raw=ans.get('raw'))
        out_items.append(row)
    out_items.sort(key=lambda r: (r['f0'], 0 if r['kind'] == 'shot' else 1))
    checked = _ranges([(r['f0'], r['f1']) for r in out_items], fps)
    un = [{'f0': a, 'f1': b, 't0': round(a / fps, 3), 't1': round(b / fps, 3), 'why': why}
          for a, b, why in unchecked]
    asked = report.get('items', 0)
    lane = {'method': ('Qwen vision model (model_tools.describe) asked closed-set questions on frames before / at / '
                       f"after each motion event and over each shot (design {st['design']}); confidence = how often "
                       'that answer was right on the label set'),
            'version': LANE_VERSION, 'prompt_version': PROMPT_VERSION,
            'settings': {k: v for k, v in st.items() if not k.startswith('fb_')},
            'warnings': warnings, 'unsupported': unsupported, 'meaning': out_items,
            'vocabulary': {'action': VOCABULARIES[st['vocabulary']], 'completes': COMPLETES, 'size': SIZES,
                           'camera': CAMERAS, 'subject': SUBJECTS},
            'accuracy': dict({lt: {'accuracy': acc_t.get(lt), 'n': n_t.get(lt), 'from': 'model',
                                   'trusted': bool(acc_t.get(lt) is not None and acc_t.get(lt) >= mina)}
                              for lt in LABEL_TYPES + ['what']},
                             **({'camera': dict(cam_over, trusted=cam_over['accuracy'] >= mina)} if cam_over else {})),
            'legend': (legend(mina, st['design'], camera=cam_over) if not mismatch else
                       f'Meaning accuracy: {mismatch}; no model label trusted' +
                       (f"; camera measured {math.floor(cam_over['accuracy'] * 100)}%" if cam_over else '') + '.'),
            'events_from': events_from, 'model': run_model, 'checked_ranges': checked, 'unchecked_ranges': un,
            'video_offset_s': round(off, 4),
            'timing': {'items': len(out_items), 'asked': asked, 'cached': len(out_items) - asked,
                       'frames_s': round(frames_s, 2), 'model_s': report.get('run_s', 0.0),
                       'model_s_per_item': round(report.get('run_s', 0.0) / asked, 2) if asked else None,
                       'retried': report.get('retried', 0), 'total_s': round(time.time() - t_start, 2)},
            'gpu': report.get('gpu')}
    return lane


# ------------------------------------------------------------------ projects without the store

def _project_preview(project, st):
    """(preview mp4 path, fps, frames, revision) of a project rendered by melt at a small size (same fps); cached by
    the project file's content. Used only when the store (timing_signals) is missing."""
    import letitedit.review.checks as checks
    timeline, path = checks.resolve(project)
    raw = Path(path).read_bytes()
    rev = hashlib.sha1(raw).hexdigest()[:16]
    p = timeline.profile
    long_side = int(st['preview_px'])
    scale = long_side / max(p['width'], p['height'])
    w = max(64, int(round(p['width'] * scale / 2)) * 2)
    h = max(64, int(round(p['height'] * scale / 2)) * 2)
    out = CACHE / 'previews' / f'{rev}-{w}x{h}.mp4'
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f'{out.stem}.{uuid.uuid4().hex[:6]}.mp4')
        args = [str(checks.MELT), '-quiet', str(path), '-consumer', f'avformat:{tmp}', 'vcodec=libx264', 'crf=26',
                'preset=veryfast', 'pix_fmt=yuv420p', 'an=1', 'audio_off=1', f'width={w}', f'height={h}',
                f'progressive={p["progressive"]}', f'frame_rate_num={p["frame_rate_num"]}',
                f'frame_rate_den={p["frame_rate_den"]}', 'sample_aspect_num=1', 'sample_aspect_den=1',
                f'display_aspect_num={w}', f'display_aspect_den={h}', 'real_time=-1']

        def render():
            r = subprocess.run(args, capture_output=True, text=True, errors='replace', creationflags=NO_WINDOW,
                               timeout=7200)
            if r.returncode != 0 or not tmp.exists():
                raise RuntimeError(f'melt could not render the preview: {(r.stderr or "")[-400:]}')
        if timeline.seconds > 30:
            import letitedit.core.render_lock as render_lock
            with render_lock.slot(f'motion_meaning preview {Path(path).name}', timeout_s=3600,
                                  caller_pids=render_lock.ancestors()):
                render()
        else:
            render()
        os.replace(tmp, out)
    return str(out), timeline.fps, int(timeline.frames), rev, str(path)


def _is_project(source):
    s = str(source).strip()
    return s.lower() in ('live', 'current', 'editor') or s.lower().endswith('.mlt')


def _caller_settings(settings, build=None):
    """The caller's own settings for this module (short keys of DEFAULTS), and build when given."""
    over = {}
    for k, v in (settings or {}).items():
        k = k[8:] if str(k).startswith('meaning.') else k
        if k in DEFAULTS:
            over[k] = v
    if build is not None:
        over['build'] = bool(build)
    return over


def _range_frames(start, end, fps):
    """Half-open frame range [start_f, end_f) of start-end seconds (None: open)."""
    return (None if start is None else int(round(float(start) * fps)),
            None if end is None else int(round(float(end) * fps)))


def _finish(lane, source, kind, video, fps, frames, start, end, revision, fingerprints, artifacts, warnings, t0,
            key=None, kinds=('event', 'shot')):
    """A lane dict as a result: the common contract fields, then the lane's data, then the source's numbers."""
    lane = dict(lane)
    if set(kinds) != {'event', 'shot'}:
        lane['meaning'] = [r for r in lane.get('meaning') or [] if r.get('kind') in kinds]
    rid = hashlib.sha1(json.dumps([str(source), start, end, sorted((fingerprints or {}).items()), revision, key,
                                   lane.get('identity'), lane.get('settings'), LANE_VERSION, PROMPT_VERSION,
                                   sorted(kinds)], default=str).encode()).hexdigest()[:16]
    out = _contract(result_id=rid, project_revision=revision, source_fingerprints=dict(fingerprints or {}),
                    checked_ranges=list(lane.pop('checked_ranges', None) or []),
                    unchecked_ranges=list(lane.pop('unchecked_ranges', None) or []),
                    warnings=list(warnings) + list(lane.pop('warnings', None) or []),
                    unsupported=list(lane.pop('unsupported', None) or []), preview_artifacts=list(artifacts or []))
    out.update(lane)
    out.update(source=str(source), kind=kind, analysed=str(video), fps=fps, frames=frames,
               seconds=round(time.time() - t0, 2))
    return out


def meaning(source, start=None, end=None, events=None, shots=None, settings=None, refresh=False, build=None,
            kinds=('event', 'shot'), progress=None, model=None, store_settings=None):
    """What happens in each motion event and shot of `source` (a video file, or a project .mlt: its preview render),
    within start-end (seconds; source seconds for a file, timeline seconds for a project). events / shots: lists in
    the store's shape ({f0, f_peak, f1, ...} / {f0, f1}, half-open) to label instead of the store's or the
    fallback's. settings: any DEFAULTS key ('design', 'vocabulary', 'max_items', 'min_accuracy', ...). build=False:
    cached answers only. kinds: ('event', 'shot') or one of them.
    With the store (timing_signals) and no events/shots given, the store computes and caches the lane
    (signals(lanes=['meaning'], settings={'meaning': {..., 'range_s': [start, end]}})); refresh recomputes it there
    (answers stay cached: the model is deterministic); progress and model apply only outside the store.
    LETITEDIT_MEANING_BUILD=0 in the environment means build=False unless build is given. store_settings: the
    store's settings for other lanes ({lane: {key: value}}, e.g. motion_events thresholds).
    Returns the lane dict with the common contract fields (see the module doc)."""
    if build is None and os.environ.get('LETITEDIT_MEANING_BUILD') == '0':
        build = False                        # a test or a CPU-only run: cached answers only
    st = _settings(settings)
    if build is not None:
        st['build'] = bool(build)
    t0 = time.time()
    warnings = []
    if events is None and shots is None:
        over = _caller_settings(settings, build)
        if start is not None or end is not None:
            over['range_s'] = [None if start is None else round(float(start), 4),
                               None if end is None else round(float(end), 4)]
        sig, why = _store(source, start, end, lanes=('meaning',), settings=dict(store_settings or {}, meaning=over),
                          refresh=['meaning'] if refresh else False)
        if sig is not None:
            store_warn = [f'store: {w}' for w in sig.get('warnings') or []]
            arts = [sig['render']] if sig.get('render') else []
            fps, frames = float(sig['fps']), int(sig['frames'])
            video = sig.get('render') or str(Path(str(source)).resolve())
            lane = (sig.get('lanes') or {}).get('meaning')
            if lane is not None and not lane.get('error'):
                return _finish(lane, source, sig['kind'], video, fps, frames, start, end, sig.get('project_revision'),
                               sig.get('source_fingerprints'), arts, store_warn, t0, key=sig.get('key'), kinds=kinds)
            warnings.append(f"the store's meaning lane failed ({lane.get('error')}): labelled here instead"
                            if lane is not None else "the store has no 'meaning' lane: labelled here instead")
            sig2, _ = _store(source, start, end)
            lanes = (sig2 or {}).get('lanes') or {}
            ev = _lane_list(lanes.get('motion_events'), 'motion_events', 'events', 'items')
            sh = _lane_list(lanes.get('shots'), 'shots', 'items')
            if ev is not None and sh is not None:
                motion = lanes.get('motion') or {}
                cam = motion.get('camera_label') if isinstance(motion, dict) else None
                start_f, end_f = _range_frames(start, end, fps)
                rng = sig2.get('range') or {}
                off = float(rng.get('f0') or 0) / fps if sig2.get('kind') == 'project' else 0.0
                lane = run(video, fps, frames, ev, sh, st, camera_labels=cam, kinds=kinds, start_f=start_f,
                           end_f=end_f, refresh=refresh, progress=progress, events_from='store', model=model,
                           video_offset_s=off)
                return _finish(lane, source, sig['kind'], video, fps, frames, start, end,
                               sig.get('project_revision'), sig.get('source_fingerprints'), arts,
                               store_warn + warnings, t0, key=sig.get('key'), kinds=kinds)
            warnings.append('the store gave no motion_events / shots lanes: fallback events and shots')
        else:
            warnings.append(f"{why}: motion events and shots from this module's fallback")
    # without the store, or with the events / shots given
    project = _is_project(source)
    revision, fingerprints, artifacts = None, {}, []
    if project:
        video, fps, frames, revision, path = _project_preview(source, st)
        artifacts.append(video)
        fingerprints[path] = revision
    else:
        video = str(Path(source).resolve())
        fps, frames = video_grid(video)
        with contextlib.suppress(OSError):
            fingerprints[video] = _fingerprint(video)
    camera_shifts, events_from = None, 'given'
    if events is None or shots is None:
        fb = fallback_signals(video, st)
        events = fb['motion_events'] if events is None else events
        shots = fb['shots'] if shots is None else shots
        camera_shifts = fb['camera']
        events_from = 'fallback'
    start_f, end_f = _range_frames(start, end, fps)
    lane = run(video, fps, frames, events, shots, st, camera_shifts=camera_shifts, kinds=kinds, start_f=start_f,
               end_f=end_f, refresh=refresh, progress=progress, events_from=events_from, model=model)
    return _finish(lane, source, 'project' if project else 'video', video, fps, frames, start, end, revision,
                   fingerprints, artifacts, warnings, t0, kinds=kinds)


def compute_lane(ctx):
    """The 'meaning' lane for timing_signals (registered at import): events from ctx['lanes']['motion_events'],
    shots from ctx['lanes']['shots'], the camera label from ctx['lanes']['motion'] (this module's fallback for any
    that is missing). ctx['settings']: this module's effective settings (code defaults, timing_thresholds.json
    'meaning.*', the caller's), and the caller's own under ctx['settings']['meaning']. Labels the store's analysed
    range (ctx['range']), narrowed to settings 'range_s' when given. Everything that changes the result comes from
    the settings (part of the store's cache identity), never from the environment."""
    given = ctx.get('settings') or {}
    sets = {k: v for k, v in given.items() if k in DEFAULTS}
    if isinstance(given.get('meaning'), dict):
        sets.update(_caller_settings(given['meaning']))
    st = _settings(sets)
    video, fps, frames = ctx['video'], float(ctx['fps']), int(ctx['frames'])
    rng = ctx.get('range') or [0, frames]
    start_f, end_f = int(rng[0]), int(rng[1])
    if st.get('range_s'):
        a, b = (list(st['range_s']) + [None, None])[:2]
        if a is not None:
            start_f = max(start_f, int(round(float(a) * fps)))
        if b is not None:
            end_f = min(end_f, int(round(float(b) * fps)))
    lanes = ctx.get('lanes') or {}
    events = _lane_list(lanes.get('motion_events'), 'motion_events', 'events', 'items')
    shots_ = _lane_list(lanes.get('shots'), 'shots', 'items')
    motion = lanes.get('motion') or {}
    camera_labels = motion.get('camera_label') if isinstance(motion, dict) else None
    camera_shifts, events_from, extra = None, 'store', []
    if events is None or shots_ is None or camera_labels is None:
        fb = fallback_signals(video, st)
        if events is None:
            events, events_from = fb['motion_events'], 'fallback (no motion_events lane in ctx)'
            extra.append('no motion_events lane given: fallback motion events')
        if shots_ is None:
            shots_ = fb['shots']
            extra.append('no shots lane given: shots from shots.detect')
        if camera_labels is None:
            camera_shifts = fb['camera']
    render = ctx.get('render') if ctx.get('kind') == 'project' else None
    offset = (float((render or {}).get('f0') or 0) / fps) if isinstance(render, dict) else 0.0
    lane = run(video, fps, frames, events, shots_, st, camera_labels=camera_labels, camera_shifts=camera_shifts,
               start_f=start_f, end_f=end_f, events_from=events_from, video_offset_s=offset)
    lane['warnings'] = extra + lane['warnings']
    return lane


def _lane_defaults():
    """compute_lane.defaults for the store: DEFAULTS plus stamps of the prompt and of the accuracy file, so the
    store's cached lane is recomputed when either changes."""
    try:
        acc = hashlib.sha1(ACCURACY_FILE.read_bytes()).hexdigest()[:10]
    except OSError:
        acc = None
    return dict(DEFAULTS, prompt_stamp=prompt_hash(DEFAULTS['design'], DEFAULTS['vocabulary']), accuracy_stamp=acc)


compute_lane.defaults = _lane_defaults()


# ------------------------------------------------------------------ text

def _mark(lab):
    v = lab.get('value')
    if v is None:
        return '?'
    return v if lab.get('trusted') else f'~{v}'


def _pct(x):
    return '' if x is None else f' {math.floor(x * 100)}%'


def _done_text(comp):
    """'done: ~yes 64%' / 'done: unclear' / 'done: ?' (not answered)."""
    cv = comp.get('value')
    if cv is None:
        return 'done: ?'
    if cv == 'unclear':
        return 'done: unclear'
    return f"done: {'' if comp.get('trusted') else '~'}{cv}{_pct(comp.get('confidence'))}"


def item_line(r):
    """'e012 0:12.30-0:13.10 (f738-786, peak 0:12.80) tool use 82%: hand tightens the set screw | done: yes ~64% |
    close-up, ~handheld, hands'."""
    lb = r.get('labels') or {}
    when = f"{_clock(r['t0'])}-{_clock(r['t1'])} (f{r['f0']}-{r['f1']}"
    when += f", peak {_clock(r['t_peak'])})" if r['kind'] == 'event' else (
        f", shot {r.get('shot')}" + (f" part {r['part'][0]}/{r['part'][1]}" if r.get('part') else '') + ')')
    act = lb.get('action', {})
    head = f"{r['id']} {when} {_mark(act)}{_pct(act.get('confidence'))}"
    if r.get('what'):
        head += f": {r['what']}"
    done = _done_text(lb.get('completes', {}))
    rest = _facts(lb)
    cam = lb.get('camera', {})
    if cam.get('measured') and cam.get('from') == 'model' and cam.get('measured') != cam.get('value'):
        rest += f" (camera measured: {cam['measured']})"
    return f'{head} | {done} | {rest}'


def lines(result, kinds=('shot', 'event')):
    """Text lines of a meaning result: the legend, then one line per item (item_line)."""
    out = [result.get('legend') or legend()]
    for r in result.get('meaning') or []:
        if r['kind'] in kinds:
            out.append(item_line(r))
    for u in result.get('unchecked_ranges') or []:
        out.append(f"unchecked {_clock(u['t0'])}-{_clock(u['t1'])}: {u['why']}")
    return out


# ------------------------------------------------------------------ the view

COLOURS = {'hands working': (66, 165, 245), 'tool use': (239, 108, 0), 'part moves': (171, 71, 188),
           'person gestures': (102, 187, 106), 'person moves': (38, 166, 154), 'animal moves': (141, 110, 99),
           'vehicle moves': (236, 64, 122), 'camera move only': (158, 158, 158), 'nothing happens': (97, 97, 97),
           None: (80, 80, 80)}


def _wrap(d, text, font, width):
    words, line, out = str(text).split(), '', []
    for w in words:
        t = (line + ' ' + w).strip()
        if d.textlength(t, font=font) <= width:
            line = t
        else:
            if line:
                out.append(line)
            line = w
    if line:
        out.append(line)
    return out


def _facts(lb):
    """'~close-up, ~handheld (measured), ~hands'."""
    out = []
    for k in ('size', 'camera', 'subject'):
        lab = lb.get(k, {})
        out.append(_mark(lab) + (' (measured)' if k == 'camera' and lab.get('from') == 'measured' else ''))
    return ', '.join(out)


def _card(item, video, fps, width=390, offset_s=0.0):
    """One card image: before / peak / after frames and the labels."""
    from PIL import Image, ImageDraw
    fr = item.get('frames') or []
    picks = [fr[0], fr[len(fr) // 2], fr[-1]] if len(fr) >= 3 else fr
    if item['kind'] == 'event' and fr:
        pk = min(fr, key=lambda x: abs(x['f'] - item.get('f_peak', x['f'])))
        picks = [fr[0], pk, fr[-1]]
    paths = frames_at(video, [max(0.0, p['t'] - offset_s) for p in picks], 448, fps) if picks else []
    ims = [Image.open(p).convert('RGB') for p in paths if p]
    tw = (width - 8 - 2 * 4) // 3
    th = 0
    tiles = []
    for im in ims:
        h = int(round(im.height * tw / im.width))
        if h > 230:
            h = 230
        tiles.append(im.resize((tw, h)))
        th = max(th, h)
    big, mid, small = _font(21, bold=True), _font(19), _font(17)
    meas = Image.new('RGB', (10, 10))
    md = ImageDraw.Draw(meas)
    lb = item.get('labels') or {}
    act = lb.get('action', {})
    title = f"{item['id']}  {_clock(item['t0'])}-{_clock(item['t1'])}"
    sub = f"f{item['f0']}-{item['f1']}" + (f", peak f{item['f_peak']}" if item['kind'] == 'event' else
                                           f", shot {item.get('shot')}" + (f" part {item['part'][0]}/{item['part'][1]}"
                                                                           if item.get('part') else ''))
    label_txt = f"{_mark(act)}{_pct(act.get('confidence'))}"
    what = _wrap(md, item.get('what') or '', mid, width - 16)[:2]
    cv = lb.get('completes', {}).get('value')
    done = _done_text(lb.get('completes', {}))
    facts = _facts(lb)
    H = 8 + th + 8 + 26 + 22 + 26 + 24 * len(what) + 24 + 24 + 8
    C = Image.new('RGB', (width, H), (250, 250, 250))
    d = ImageDraw.Draw(C)
    col = COLOURS.get(item.get('label'), COLOURS[None])
    d.rectangle([0, 0, width - 1, H - 1], outline=col, width=4)
    x = 4
    for tile in tiles:
        C.paste(tile, (x, 8 + (th - tile.height) // 2))
        x += tw + 4
    y = 8 + th + 6
    d.text((8, y), title, fill=(20, 20, 20), font=big)
    y += 26
    d.text((8, y), sub, fill=(90, 90, 90), font=small)
    y += 22
    d.rectangle([8, y + 2, 26, y + 20], fill=col)
    d.text((32, y), label_txt, fill=(20, 20, 20) if act.get('trusted') else (150, 60, 0), font=big)
    y += 26
    for ln in what:
        d.text((8, y), ln, fill=(30, 30, 30), font=mid)
        y += 24
    d.text((8, y), done, fill=(20, 110, 20) if cv == 'yes' else (170, 30, 30) if cv == 'no' else (90, 90, 90),
           font=mid)
    y += 24
    d.text((8, y), facts, fill=(60, 60, 60), font=small)
    return C


def draw(result, out_dir, per_page=12, max_pages=None, start_s=None, end_s=None, title=None):
    """PNG pages: a time axis with the shots and events (numbered, coloured by what happens), then cards with each
    item's before / peak / after frames, its label and confidence. Returns the paths."""
    from PIL import Image, ImageDraw
    items = list(result.get('meaning') or [])
    fps = float(result.get('fps') or 30.0)
    video = result.get('analysed') or result.get('source')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    W = 1640
    t_lo = float(start_s) if start_s is not None else (min((r['t0'] for r in items), default=0.0))
    t_hi = float(end_s) if end_s is not None else (max((r['t1'] for r in items), default=1.0))
    if start_s is None and result.get('frames'):
        t_lo = 0.0
    if end_s is None and result.get('frames'):
        t_hi = max(t_hi, float(result['frames']) / fps)
    t_hi = max(t_hi, t_lo + 0.5)
    shots_ = [r for r in items if r['kind'] == 'shot']
    events = [r for r in items if r['kind'] == 'event']
    order = sorted(items, key=lambda r: (r['t0'], r['kind'] != 'shot'))
    pages = [order[k:k + per_page] for k in range(0, len(order), per_page)] or [[]]
    if max_pages:
        pages = pages[:max_pages]
    head_f, mid_f, small_f = _font(26, bold=True), _font(19), _font(16)
    paths = []
    L, R = 60, W - 30

    def X(t):
        return L + (R - L) * (float(t) - t_lo) / (t_hi - t_lo)
    for pi, page in enumerate(pages):
        cards = [_card(r, video, fps, offset_s=float(result.get('video_offset_s') or 0.0)) for r in page]
        cols = 4
        cw = 390 + 12
        rows = (len(cards) + cols - 1) // cols
        row_h = [max((c.height for c in cards[k * cols:(k + 1) * cols]), default=0) for k in range(rows)]
        top = 300
        Hh = top + sum(h + 14 for h in row_h) + 20
        img = Image.new('RGB', (W, max(Hh, top + 40)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        name = title or Path(str(result.get('source', ''))).name
        d.text((20, 12), f"Meaning: {name}  {_clock(t_lo)}-{_clock(t_hi)}  ({len(events)} motion events, "
                         f"{len(shots_)} shots / parts)  page {pi + 1}/{len(pages)}", fill=(0, 0, 0), font=head_f)
        leg = _wrap(d, result.get('legend') or legend(), small_f, W - 40)
        y = 48
        for ln in leg[:3]:
            d.text((20, y), ln, fill=(70, 70, 70), font=small_f)
            y += 20
        d.text((20, y), 'Each card: frames before / at the peak / after; % = how often that answer was right on the '
                        'label set; ~ = label type measured under the trust line; done: is the action finished by the '
                        'last frame.', fill=(70, 70, 70), font=small_f)
        # axis
        ay = 200
        d.line([L, ay, R, ay], fill=(0, 0, 0), width=2)
        span = t_hi - t_lo
        step = next((s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if span / s <= 14), 1200)
        k = math.ceil(t_lo / step) * step
        while k <= t_hi + 1e-6:
            x = X(k)
            d.line([x, ay, x, ay + 8], fill=(0, 0, 0), width=2)
            d.text((x - 20, ay + 10), _clock(k)[:-1], fill=(0, 0, 0), font=small_f)
            k += step
        # shots lane
        page_ids = {r['id'] for r in page}
        for i, s in enumerate(shots_):
            x0, x1 = X(s['t0']), max(X(s['t0']) + 2, X(s['t1']))
            col = (215, 215, 215) if i % 2 == 0 else (190, 190, 190)
            d.rectangle([x0, 120, x1, 150], fill=col, outline=(0, 0, 0) if s['id'] in page_ids else None)
            if x1 - x0 > 44:
                d.text((x0 + 4, 125), s['id'], fill=(0, 0, 0), font=small_f)
        d.text((4, 124), 'shots', fill=(0, 0, 0), font=small_f)
        # events lane: bars staggered over 2 rows
        d.text((4, 164), 'events', fill=(0, 0, 0), font=small_f)
        last_x = [-1e9, -1e9]
        for ev in events:
            x0, x1 = X(ev['t0']), max(X(ev['t0']) + 3, X(ev['t1']))
            rr = 0 if x0 > last_x[0] + 4 else 1
            last_x[rr] = x1 + d.textlength(ev['id'][1:], font=small_f)
            yy = 158 + rr * 18
            col = COLOURS.get(ev.get('label'), COLOURS[None])
            d.rectangle([x0, yy, x1, yy + 12], fill=col, outline=(0, 0, 0) if ev['id'] in page_ids else None,
                        width=2 if ev['id'] in page_ids else 1)
            if ev['id'] in page_ids:
                d.text((x1 + 2, yy - 4), ev['id'][1:].lstrip('0'), fill=(0, 0, 0), font=small_f)
        # colour key
        kx = 20
        for lab in VOCABULARIES['general']:
            d.rectangle([kx, 250, kx + 16, 266], fill=COLOURS[lab])
            d.text((kx + 20, 248), lab, fill=(0, 0, 0), font=small_f)
            kx += 26 + d.textlength(lab, font=small_f) + 14
        # cards
        y = top
        for k in range(rows):
            x = 20
            for c in cards[k * cols:(k + 1) * cols]:
                img.paste(c, (x, y))
                x += cw
            y += row_h[k] + 14
        p = out_dir / f'meaning_p{pi + 1:02d}.png'
        img.save(p)
        paths.append(str(p))
    return paths


def view(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The timing view 'meaning': labelled motion events and shots of `source` with their accuracy, as images
    (events along time, cards with frames, labels and confidence) and text lines. items: edit item ids to look at
    (needs the store's edit lane); cuts: frames or seconds of cuts, to look at the events around them (+-1 s).
    options: any DEFAULTS key (design, vocabulary, max_items, min_accuracy, build, ...) plus 'kinds' (['event',
    'shot']), 'per_page' (12), 'pages' (pages drawn; detail 'brief' = 1, 'full' = all), 'refresh', and 'settings'
    ({lane: {key: value}} for the store's lanes, e.g. motion_events thresholds; 'meaning' merges with the keys above).
    detail: 'brief' (items without their frames, labels detail and raw replies; the full items are in 'full_file')
    or 'full'."""
    opts = dict(options or {})
    used = dict(opts)
    kinds = tuple(opts.pop('kinds', ('event', 'shot')))
    per_page = int(opts.pop('per_page', 12))
    pages = opts.pop('pages', None)
    refresh = bool(opts.pop('refresh', False))
    store_settings = dict(opts.pop('settings', None) or {})
    mine = dict(store_settings.pop('meaning', None) or {})
    mine.update({k: v for k, v in opts.items() if (k[8:] if str(k).startswith('meaning.') else k) in DEFAULTS})
    warnings, unsupported = [], []
    for k in opts:
        if (k[8:] if str(k).startswith('meaning.') else k) not in DEFAULTS:
            warnings.append(f'option {k!r} is not used by the meaning view')
    a, b = start_s, end_s
    if items:
        st0, why = _store(source, lanes=('edit',))
        spans = []
        if st0 is not None:
            for it in _lane_list((st0.get('lanes') or {}).get('edit'), 'items') or []:
                if str(it.get('id')) in {str(x) for x in items}:
                    spans.append((it['f0'] / float(st0['fps']), it['f1'] / float(st0['fps'])))     # half-open
        if spans:
            a = min(s for s, _ in spans) if a is None else a
            b = max(e for _, e in spans) if b is None else b
        else:
            unsupported.append(f'items {list(items)}: item spans need the store\'s edit lane ({why or "not found"})')
    res = meaning(source, start=a, end=b, settings=mine, refresh=refresh, kinds=kinds,
                  store_settings=store_settings)
    if cuts:
        fps = float(res['fps'])
        cf = [int(round(float(c) * fps)) if isinstance(c, float) else int(c) for c in cuts]
        near = int(round(fps))
        res['meaning'] = [r for r in res['meaning'] if any(r['f0'] - near <= c < r['f1'] + near for c in cf)]
    out_dir = CACHE / 'views' / (res['result_id'] + (f'-c{hashlib.sha1(str(cuts).encode()).hexdigest()[:6]}'
                                                    if cuts else ''))
    n_pages = pages if pages is not None else (1 if detail == 'brief' else None)
    images = draw(res, out_dir, per_page=per_page, max_pages=n_pages, start_s=a, end_s=b)
    res['images'] = images
    res['preview_artifacts'] = list(res.get('preview_artifacts') or []) + images
    res['lines'] = lines(res)
    res['warnings'] = warnings + res['warnings']
    res['unsupported'] = unsupported + res['unsupported']
    res['options_used'] = dict(used, kinds=list(kinds), per_page=per_page, pages=n_pages,
                               settings=res.get('settings'))
    if detail == 'brief' and len(res['meaning']) > per_page:
        res['warnings'].append(f"{len(res['meaning'])} items, the image shows the first {per_page}: "
                               "detail='full' (or options pages=N) draws them all; the lines list every one")
    if detail != 'full':
        full = out_dir / 'meaning_full.json'
        full.write_text(json.dumps(res['meaning'], indent=1, default=str), encoding='utf-8')
        res['full_file'] = str(full)
        res['meaning'] = [slim(r) for r in res['meaning']]
    return res


def slim(r):
    """An item without its frames, per-type detail and raw reply: the numbers an editor reads, and which label
    types are trusted."""
    keep = ('kind', 'id', 'f0', 'f1', 't0', 't1', 'f_peak', 't_peak', 'shot', 'part', 'label', 'what', 'completes',
            'size', 'camera', 'subject', 'confidence')
    out = {k: r.get(k) for k in keep if k in r}
    lb = r.get('labels') or {}
    out['trusted'] = [k for k in LABEL_TYPES if (lb.get(k) or {}).get('trusted')]
    comp = lb.get('completes') or {}
    out['completes_confidence'] = comp.get('confidence')
    return out


VIEW_SUMMARY = ('what happens in each motion event and shot (closed-set label, a few words, does the step finish, '
                'shot size, camera, subject) from the local vision model, each label type with its measured accuracy')


# ------------------------------------------------------------------ registration with the store and the views

LANE_DEPENDS = ('motion_events', 'shots', 'motion')


def _register():
    """Register the 'meaning' lane (timing_signals) and view (timing_views) when they are importable; never fails.
    timing_signals.load_plugins() imports this module (it is listed in timing_signals.PLUGINS)."""
    done = {}
    try:
        import letitedit.timing.timing_signals as ts
        compute_lane.defaults = _lane_defaults()
        ts.register_lane('meaning', compute_lane, depends=LANE_DEPENDS, version=LANE_VERSION)
        done['lane'] = True
    except Exception as e:  # noqa: BLE001 - the module works on its own without the store
        done['lane'] = f'{type(e).__name__}: {e}'
    try:
        import letitedit.timing.timing_views as tv
        tv.register_view('meaning', view, VIEW_SUMMARY)
        done['view'] = True
    except Exception as e:  # noqa: BLE001
        done['view'] = f'{type(e).__name__}: {e}'
    return done


REGISTERED = _register()


if __name__ == '__main__':
    import sys
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    r = view(sys.argv[1], **args)
    print('\n'.join(r['lines']))
    print(json.dumps({k: r[k] for k in ('images', 'timing', 'warnings', 'unsupported')}, indent=1))
