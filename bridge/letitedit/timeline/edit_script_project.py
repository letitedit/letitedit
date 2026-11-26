"""Project access: the document, its tracks and clips in friendly words.

Part of `edit_script` (letitedit/timeline/edit_script.py), which imports every name here back,
so `edit_script.X` is the same object it always was.
"""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import letitedit.timeline.edit_effects as ee
import letitedit.timeline.timeline_model as tm
from letitedit.timeline.edit_script_base import (  # noqa: E402
    FADE_FLOOR_PROP, LIFT_PROP, SPLIT_MUTE_PROP, _get, _props, _r
)


# ---------------------------------------------------------------------------- project access

class Doc:
    """Parsed project with helpers shared by the reader and the compiler."""

    def __init__(self, path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()
        prof = self.root.find('profile')
        self.fps = int(prof.get('frame_rate_num', 30)) / int(prof.get('frame_rate_den', 1))
        self.width, self.height = int(prof.get('width')), int(prof.get('height'))
        self.elements = {e.get('id'): e for e in self.root if e.get('id')}
        tractors = [e for e in self.root if e.tag == 'tractor']
        marked = [t for t in tractors if _get(t, 'shotcut') == '1']
        self.main = (marked or tractors)[-1]

    def f(self, value):
        return tm.clock_to_frames(value, self.fps)

    def tracks(self):
        """[(tractor_track_element, playlist_element, unique_name, kind)] excluding the background."""
        out, seen = [], {}
        for tr in self.main.findall('track'):
            pid = tr.get('producer')
            pl = self.elements.get(pid)
            if pl is None or pl.tag != 'playlist' or pid == 'background':
                continue
            name = _get(pl, 'shotcut:name') or pid
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                name = f'{name} ({seen[name]})'
            # A hidden video track also says hide="video"; only a track the editor marked as a video one stays video.
            kind = 'audio' if (_get(pl, 'shotcut:audio') == '1'
                               or (tr.get('hide') == 'video' and _get(pl, 'shotcut:video') != '1')) else 'video'
            out.append((tr, pl, name, kind))
        return out

    def entries(self, playlist):
        """[(kind, element, frames_or_None)] kind 'blank'|'entry'."""
        out = []
        for e in playlist:
            if e.tag == 'blank':
                out.append(('blank', e, self.f(e.get('length'))))
            elif e.tag == 'entry':
                out.append(('entry', e, None))
        return out


def _user_filters(producer):
    out = []
    for child in producer:
        if child.tag in ('filter', 'link'):
            p = _props(child)
            if p.get('_loader') == '1' or p.get('shotcut:hidden') == '1':
                continue
            out.append(child)
    return out


def _drop_parts(elem):
    """Remove the hidden helper filters of friendly effects (blur_pad's side grade and border); they are rebuilt."""
    for f in [c for c in elem if c.tag == 'filter' and _get(c, 'letitedit_ai:part')]:
        elem.remove(f)


def _anim_to_keys(value, fps):
    """'00:00:01.000=-20;00:00:05.000=-8' -> [[1.0, -20.0], [5.0, -8.0]] (eased keys keep their ease)"""
    eased = ee.parse_anim(str(value), fps)
    if eased is not None and all(isinstance(k[1], (int, float)) for k in eased):
        return [[k[0], float(k[1])] + k[2:] for k in eased]
    keys = []
    for part in str(value).split(';'):
        if '=' not in part:
            continue
        t, v = part.split('=', 1)
        t = re.sub(r'[|~$!]$', '', t.strip())
        v = re.sub(r'(?i)db$', '', v.strip())
        try:
            keys.append([_r(tm.clock_to_frames(t, fps) / fps, 3), float(v)])
        except ValueError:
            return None
    return keys


def _keys_to_anim(keys, fps):
    """[[t, v], [t, v, ease], ...] -> an MLT animation string (gain keys in dB)."""
    return ee.anim([[float(k[0]), float(k[1])] + list(k[2:3]) for k in keys], fps)


def tm_clock(frames, fps):
    return tm.frames_to_clock(frames, fps)      # as the engine writes it, so it reads back as the same frame


def describe_filter(elem, fps, clip_frames, profile_w=1920, profile_h=1080, generic=True):
    """Script view of a filter element: a friendly word when there is one, else {filter: name, params} (any engine
    effect). generic=False returns None instead of the generic form (how older scripts named it: {keep})."""
    d = _describe_friendly(elem, fps)
    if d is None and generic:
        return ee.view(elem, fps)
    return d


def _describe_friendly(elem, fps):
    p = _props(elem)
    if p.get('letitedit:cutaway_negative'):
        return {'cutaway_negative': json.loads(p['letitedit:cutaway_negative'])}
    fid = p.get('shotcut:filter') or ''
    svc = p.get('mlt_service', '')
    if elem.tag == 'link':
        return None
    if fid == 'blur_pad' or svc == 'pillar_echo':
        if '=' in p.get('rect', ''):
            return None
        if p.get('letitedit_ai:blur_pad'):
            try:
                return {'blur_pad': json.loads(p['letitedit_ai:blur_pad'])}
            except ValueError:
                pass
        return {'blur_pad': {'blur': float(p.get('blur', 7))}}
    if fid == 'brightnessOpacity':
        a = ee.view_value(p.get('alpha', '1'), fps)
        return {'opacity': a} if isinstance(a, (int, float, dict)) else None
    if fid == 'muteVolume':
        return 'mute'
    if p.get(SPLIT_MUTE_PROP):
        try:
            return {'split_mute': json.loads(p[SPLIT_MUTE_PROP])}
        except ValueError:
            pass
    if fid == 'audioGain' or (svc == 'volume' and not fid):
        level = p.get('level', '0')
        if '=' in level:
            keys = _anim_to_keys(level, fps)
            return {'gain': {'keys': keys}} if keys else None
        try:
            return {'gain': float(re.sub(r'(?i)db$', '', level))}
        except ValueError:
            return None
    if fid in ('fadeInVolume', 'fadeOutVolume'):
        anim = p.get('shotcut:animIn' if fid == 'fadeInVolume' else 'shotcut:animOut')
        if anim:
            d = {('fade_in_audio' if fid == 'fadeInVolume' else 'fade_out_audio'): _r(tm.clock_to_frames(anim, fps) / fps, 3)}
            if p.get(FADE_FLOOR_PROP):
                d['floor_db'] = float(p[FADE_FLOOR_PROP])
            return d
        return None
    if fid in ('fadeInBrightness', 'fadeOutBrightness'):
        anim = p.get('shotcut:animIn' if fid == 'fadeInBrightness' else 'shotcut:animOut')
        if anim:
            key = 'fade_in' if fid == 'fadeInBrightness' else 'fade_out'
            out = {key: _r(tm.clock_to_frames(anim, fps) / fps, 3)}
            if '=' in p.get('alpha', ''):
                out['opacity'] = True
            return out
        return None
    if fid == 'dynamicText':
        style = {k: p[k] for k in ('geometry', 'family', 'size', 'weight', 'style', 'fgcolour', 'olcolour', 'bgcolour',
                                   'outline', 'halign', 'valign') if k in p}
        return {'text': p.get('argument', ''), 'style': style}
    if fid == 'affineSizePosition':
        rect = p.get('transition.rect', '')
        extra = {}
        turn = p.get('transition.fix_rotate_x', '0')
        if turn not in ('', '0', '0.0'):
            turn_keys = ee.parse_anim(turn, fps)
            if turn_keys:
                extra['rotate'] = {'keys': turn_keys}
            elif '=' not in turn:
                extra['rotate'] = float(turn)
            else:
                return None
        if p.get('transition.distort', '0') not in ('', '0'):
            extra['distort'] = True
        if p.get(LIFT_PROP):
            extra['lift'] = p[LIFT_PROP]
        if '=' not in rect:
            return {'size_position': rect, **extra}
        keys = ee.parse_anim(rect, fps)
        return {'size_position': {'keys': keys}, **extra} if keys else None
    return None
