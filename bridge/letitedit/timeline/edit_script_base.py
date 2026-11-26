"""The settings and small helpers.

Part of `edit_script` (letitedit/timeline/edit_script.py), which imports every name here back,
so `edit_script.X` is the same object it always was.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

FORMAT = 'letitedit-edit/1'
ID_PROP = 'letitedit_ai:id'
GRAPHIC_PROP = 'letitedit_ai:graphic'
SCENE_PROP = 'letitedit_ai:code_scene'
LOOK_PROP = 'letitedit_ai:look'
HOOK_PROP = 'letitedit_ai:hook'               # the opening a hook swap put in: '<candidate id>|<words>' (hooks.py)
LIFT_PROP = 'letitedit_ai:lift'                # {op: lift}'s settings, on its Size, Position & Rotate filter (object_lift.py)
SPLIT_PROP = 'letitedit_ai:split_edit'        # the record a split edit's moved-sound clip carries (split_edit.py)
MULTICAM_PROP = 'letitedit_ai:multicam'          # an angle clip's sync record ({op: multicam}, multicam.py)
SPLIT_MUTE_PROP = 'letitedit_ai:split_mute'   # on the Gain/Volume filter that silences the covered sound
FADE_FLOOR_PROP = 'letitedit_ai:floor_db'     # an audio fade's start/end level when it isn't silence (declick)
FRIENDLY_TEXT_KEYS = ('font', 'fill', 'outline', 'background', 'position', 'margin', 'max_lines', 'shadow', 'italic')
HISTORY = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'history'
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic'}
FFPROBE = Path((_SAI_ROOT + '\\app\\ffprobe.exe'))


class Conflict(Exception):
    """The timeline changed since the script was read."""


# ---------------------------------------------------------------------------- small helpers

def clock(seconds):
    seconds = max(0.0, float(seconds))
    return f'{int(seconds // 60)}:{seconds % 60:06.3f}'


def to_seconds(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ':' in text:
        parts = [float(p) for p in text.split(':')]
        s = 0.0
        for p in parts:
            s = s * 60 + p
        return s
    return float(text)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def _props(elem):
    return {p.get('name'): (p.text or '') for p in elem.findall('property')}


def _get(elem, name, default=None):
    for p in elem.findall('property'):
        if p.get('name') == name:
            return p.text or ''
    if name.startswith('letitedit_ai:'):     # projects made before the 29 Oct rename keep their ids and recipes
        old = 'shotcut_ai:' + name[len('letitedit_ai:'):]
        for p in elem.findall('property'):
            if p.get('name') == old:
                return p.text or ''
    return default


def _set(elem, name, value):
    for p in elem.findall('property'):
        if p.get('name') == name:
            p.text = str(value)
            return
    p = ET.SubElement(elem, 'property', {'name': name})
    p.text = str(value)
    # keep properties before child filters/links (Shotcut's own layout)
    children = list(elem)
    first_child = next((i for i, c in enumerate(children) if c.tag != 'property'), None)
    if first_child is not None:
        elem.remove(p)
        elem.insert(first_child, p)


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 't'


def _r(x, nd=4):
    return round(float(x), nd)
