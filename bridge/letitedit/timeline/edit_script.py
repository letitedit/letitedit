"""The edit script: Claude's readable view of a Shotcut timeline, and the compiler that writes it back.

read(project)                -> script dict (tracks of clips/gaps with stable ids, effects, captions)
compile_script(script, base) -> writes the .mlt; anything the script doesn't understand is kept verbatim
apply_changes(project, ops)  -> small edits by id (trim, delete, move, insert, set, captions) on the current file
diff(a, b)                   -> plain-language list of changes between two scripts

The timeline file stays the single source of truth: the script is regenerated from it every time, and every
clip carries a hidden id (property letitedit_ai:id) so edits made by hand in Shotcut are recognised.
Times in the script are seconds (4 decimals) or "m:ss.mmm"; positions are derived from order + gaps.

The code is in parts, each imported back here: edit_script_base (settings, small helpers), edit_script_project
(project access), edit_script_transitions, edit_script_reading (a project read as an edit script, with the track,
master and caption readers) and edit_script_diff (diff, YAML). This file keeps building new elements, compiling
and the edits by id, which read names the tests patch (kit_for, _made_dir, read, edit, _history_dir and others).
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings and small helpers
from letitedit.timeline.edit_script_base import (  # noqa: E402,F401
    _SAI_ROOT, FORMAT, ID_PROP, GRAPHIC_PROP, SCENE_PROP, LOOK_PROP, HOOK_PROP, LIFT_PROP, SPLIT_PROP,
    SPLIT_MUTE_PROP, MULTICAM_PROP, FADE_FLOOR_PROP, FRIENDLY_TEXT_KEYS, HISTORY, IMAGE_EXT, FFPROBE, Conflict, clock, to_seconds,
    file_hash, _props, _get, _set, _slug, _r
)
# project access: the document, its tracks and clips in friendly words
from letitedit.timeline.edit_script_project import (  # noqa: E402,F401
    Doc, _user_filters, _drop_parts, _anim_to_keys, _keys_to_anim, tm_clock, describe_filter, _describe_friendly
)
# transitions between clips
from letitedit.timeline.edit_script_transitions import (  # noqa: E402,F401
    TRANSITION_PROP, WIPES, TRANSITION_TYPES, transition_spec, _transition_view, _transition_info, _track_records,
    _build_transition, _new_id
)
# reading a project as an edit script with stable ids, with the track, master and caption readers it uses
from letitedit.timeline.edit_script_reading import (  # noqa: E402,F401
    _ids_for, item_view, read, reading_as, _resolve, CAPTION_STYLE_KEYS, _track_volume_filter, _mix_for, _track_filters,
    _track_fx, _track_audio, MASTER_SKIP, FLATTEN_ROLE, _master_filters, _describe_master, _master_view,
    _master_effects, _caption_burns, _geom_offset, compact, only_ids, in_range, page, COMPACT_AUTO,
    COMPACT_PAGE
)
# two edit scripts compared, and the YAML form
from letitedit.timeline.edit_script_diff import (  # noqa: E402,F401
    _says, diff, to_yaml, from_yaml
)


import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import letitedit.timeline.adjust as adjust
import letitedit.timeline.edit_effects as ee
import letitedit.timeline.made as made
import letitedit.timeline.timeline_model as tm


# ---------------------------------------------------------------------------- building new elements

_probe_cache = {}


def probe(path):
    if path not in _probe_cache:
        r = subprocess.run([str(FFPROBE), '-v', 'error', '-show_entries', 'stream=index,codec_type,width,height:format=duration',
                            '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           creationflags=0x08000000)
        d = json.loads(r.stdout or '{}')
        st = d.get('streams', [])
        v = [s for s in st if s['codec_type'] == 'video']
        a = [s for s in st if s['codec_type'] == 'audio']
        _probe_cache[path] = {'duration': float(d.get('format', {}).get('duration') or 0),
                              'video_index': v[0]['index'] if v else -1, 'audio_index': a[0]['index'] if a else -1}
    return _probe_cache[path]


def build_producer(doc, item, fps):
    """New producer/chain element for a script item (clip, image, color)."""
    if 'color' in item:
        n = round((to_seconds(item['out']) if 'out' in item else to_seconds(item.get('len', 5))) * fps)
        el = ET.Element('producer', {'id': _new_id(doc, 'producer'), 'in': '0', 'out': str(max(0, n - 1))})
        for k, v in (('length', max(n, 15000)), ('eof', 'pause'), ('resource', item['color']), ('aspect_ratio', 1),
                     ('mlt_service', 'color'), ('mlt_image_format', 'rgba'), ('shotcut:caption', item.get('name', item['color']))):
            _set(el, k, v)
        return el
    clip = item['clip']
    ext = Path(clip).suffix.lower()
    speed = float(item.get('speed', 1.0))
    if ext in IMAGE_EXT:
        el = ET.Element('producer', {'id': _new_id(doc, 'producer'), 'in': '0', 'out': '1079999'})
        for k, v in (('length', 1080000), ('eof', 'pause'), ('resource', clip), ('ttl', 1), ('aspect_ratio', 1), ('progressive', 1),
                     ('seekable', 1), ('mlt_service', 'qimage'), ('shotcut:caption', item.get('name', os.path.basename(clip)))):
            _set(el, k, v)
        return el
    info = probe(clip)
    if abs(speed - 1.0) > 1e-9:
        length = int(round(info['duration'] * fps / speed))
        el = ET.Element('producer', {'id': _new_id(doc, 'producer'), 'in': '0', 'out': str(max(0, length - 1))})
        sp = f'{speed:g}'
        for k, v in (('length', length), ('eof', 'pause'), ('resource', f'{sp}:{clip}'), ('warp_speed', sp), ('warp_resource', clip),
                     ('warp_pitch', 0), ('mlt_service', 'timewarp'), ('shotcut:producer', 'avformat'), ('seekable', 1),
                     ('audio_index', info['audio_index']), ('video_index', info['video_index']),
                     ('shotcut:caption', item.get('name', f'{os.path.basename(clip)} ({sp}x)'))):
            _set(el, k, v)
        return el
    length = int(round(info['duration'] * fps))
    el = ET.Element('chain', {'id': _new_id(doc, 'chain'), 'out': str(max(0, length - 1))})
    for k, v in (('length', length), ('eof', 'pause'), ('resource', clip), ('mlt_service', 'avformat-novalidate'), ('seekable', 1),
                 ('audio_index', info['audio_index']), ('video_index', info['video_index']),
                 ('shotcut:caption', item.get('name', os.path.basename(clip)))):
        _set(el, k, v)
    return el


def _filter(service, props, shotcut_id=None):
    el = ET.Element('filter')
    for k, v in props.items():
        _set(el, k, v)
    _set(el, 'mlt_service', service)
    if shotcut_id:
        _set(el, 'shotcut:filter', shotcut_id)
    return el


def _set_track_fx(pl, effects):
    for prop in [x for x in pl.findall('property') if x.get('name') == made.FX_PROP]:
        pl.remove(prop)
    if effects:
        for e in effects:
            made.fx_stage(e)   # fails early on a malformed effect
        _set(pl, made.FX_PROP, json.dumps(list(effects)))


def _rebuild_track_filters(doc, pl, effects):
    originals = _track_filters(pl)
    if [describe_filter(f, doc.fps, 0, doc.width, doc.height) for f in originals] == list(effects):
        return
    patched, new = set(), []
    for eff in effects:
        same = next((f for f in originals if id(f) not in patched
                     and describe_filter(f, doc.fps, 0, doc.width, doc.height) == eff), None)
        if same is not None:
            patched.add(id(same))
            new.append(copy.deepcopy(same))
        elif isinstance(eff, dict) and 'filter' in eff:
            orig = next((f for f in originals if id(f) not in patched
                         and (describe_filter(f, doc.fps, 0, doc.width, doc.height) or {}).get('filter') == eff['filter']), None)
            if orig is not None:
                patched.add(id(orig))
            new.append(ee.build(eff, doc.fps, original=orig))
        else:
            new.extend(build_filter(eff, doc.fps, 1, doc.width, doc.height, kit=getattr(doc, 'kit', None)))
    for f in originals:
        pl.remove(f)
    _drop_parts(pl)
    first = next((i for i, c in enumerate(pl) if c.tag in ('filter', 'entry', 'blank')), len(pl))
    for k, f in enumerate(new):
        if not f.get('id'):
            f.set('id', _new_id(doc, 'filter'))
        if _get(f, ee.AIM_TAG) is None:       # an aim's time range stays
            for a in ('in', 'out'):
                f.attrib.pop(a, None)
        pl.insert(first + k, f)


def _ensure_flatten(doc, needed):
    """Where a clip doesn't fill the frame (vertical footage, a picture-in-picture), the engine leaves the space
    transparent, and a half-transparent overlay drawn over it comes out at full strength. Premultiplying the final
    picture fixes that (opaque pixels don't change). Hidden from Shotcut's filter list and from the script."""
    have = [f for f in doc.main.findall('filter') if _get(f, 'letitedit_ai:role') == FLATTEN_ROLE]
    if not needed:
        for f in have:
            doc.main.remove(f)
        return
    if have:
        return
    f = ET.Element('filter', {'id': _new_id(doc, 'filter')})
    for k, v in (('mlt_service', 'frei0r.premultiply'), ('shotcut:hidden', 1), ('letitedit_ai:role', FLATTEN_ROLE)):
        _set(f, k, v)
    children = list(doc.main)
    first = next((i for i, c in enumerate(children) if c.tag == 'filter'), len(children))
    doc.main.insert(first, f)


def _master_kept(doc):
    """Older scripts name master effects without a friendly word as {keep: 'name#k'}."""
    kept, k = {}, 0
    for f in _master_filters(doc):
        d = _describe_master(f, k)
        if 'keep' in d:
            kept[d['keep']] = f
            k += 1
    return kept


def _build_master(effect, doc, kept, originals=(), patched=None):
    if 'keep' in effect:
        if effect['keep'] not in kept:
            raise ValueError(f"no master effect {effect['keep']} to keep")
        return copy.deepcopy(kept[effect['keep']])
    if 'filter' in effect:
        patched = patched if patched is not None else set()
        same = next((f for f in originals if id(f) not in patched and _master_view(f, doc.fps) == effect), None)
        if same is not None:
            patched.add(id(same))
            return copy.deepcopy(same)
        orig = next((f for f in originals if id(f) not in patched and _master_view(f, doc.fps).get('filter') == effect['filter']), None)
        if orig is not None:
            patched.add(id(orig))
        return ee.build(effect, doc.fps, original=orig)
    if 'loudness' in effect:
        c = {'target': -16, 'window': 10, 'max_gain': 15, 'min_gain': -15, 'max_rate': 3, **(effect['loudness'] or {})}
        return _filter('dynamic_loudness', {'target_loudness': c['target'], 'window': c['window'], 'max_gain': c['max_gain'],
                                            'min_gain': c['min_gain'], 'max_rate': c['max_rate'], 'discontinuity_reset': 1})
    if 'limiter' in effect:
        c = {'input_gain': 0, 'limit_db': -1.5, 'release_s': 0.08, **(effect['limiter'] or {})}
        return _filter('ladspa.1913', {'0': c['input_gain'], '1': c['limit_db'], '2': c['release_s'], 'channel_mask': -1,
                                       'instances': 1})
    if 'gain' in effect and len(effect) == 1:
        return build_filter({'gain': effect['gain']}, doc.fps, 0, 0, 0)[0]
    raise ValueError(f'unknown master effect {effect}: use gain, loudness, limiter, or any engine effect as '
                     '{filter: NAME, params}')


def _apply_track_audio(doc, t, tr, pl, kind):
    """Bring a track's volume filter and auto-ducking to the script's gain / duck."""
    f = _track_volume_filter(pl)
    if 'gain' in t and t['gain'] is not None:
        g = t['gain']
        level = _keys_to_anim(g['keys'], doc.fps) if isinstance(g, dict) else f'{float(g):g}'
        if f is None:
            f = ET.Element('filter', {'id': _new_id(doc, 'filter')})
            for k, v in (('window', 75), ('max_gain', '20dB'), ('channel_mask', -1), ('mlt_service', 'volume'),
                         ('shotcut:filter', 'audioGain'), ('shotcut:trackVolume', 'Volume'), ('shotcut:trackVolumeName', t['name'])):
                _set(f, k, v)
            first = next((i for i, c in enumerate(pl) if c.tag in ('filter', 'entry', 'blank')), len(pl))
            pl.insert(first, f)
        if str(_get(f, 'level')) != level:
            _set(f, 'level', level)
    elif f is not None and _get(f, 'shotcut:trackVolume'):
        pl.remove(f)
    mix = _mix_for(doc, tr)
    if mix is None:
        return
    duck = t.get('duck')
    if duck:
        want = {'duck_threshold': f"{float(duck.get('threshold', -30)):g}", 'duck_attenuation': f"{float(duck.get('attenuation', -12)):g}",
                'shotcut:duck_enabled': '1', 'shotcut:duck_threshold': f"{float(duck.get('threshold', -30)):g}"}
    elif _get(mix, 'shotcut:duck_enabled') == '1' or float(_get(mix, 'duck_threshold') or 0) < 0:
        want = {'duck_threshold': '0', 'shotcut:duck_enabled': '0'}
    else:
        want = {}
    for k, v in want.items():
        if str(_get(mix, k)) != v:
            _set(mix, k, v)


def _offset_geom(geom, dx, dy):
    parts = str(geom).split()
    parts[0] = f'{float(parts[0]) + float(dx):g}'
    parts[1] = f'{float(parts[1]) + float(dy):g}'
    return ' '.join(parts)


def project_look_identity(script):
    from letitedit.looks import look_library
    return look_library.project_identity(script)


def kit_for(script_or_name):
    """Editing defaults for the selected Look, or the neutral defaults."""
    import letitedit.looks.look_library as look_library
    return look_library.project_kit(script_or_name) if isinstance(script_or_name, dict) else look_library.kit(script_or_name)


def friendly_text_style(style, kit, width, height, caption=True):
    """Translate kit-style keys (font, fill, outline {color, width}, background, position, margin, max_lines,
    shadow {color, x, y}, italic) into Shotcut filter properties; other keys pass through as they are."""
    import letitedit.catalogs.fonts as fonts
    if not isinstance(style, dict):
        raise ValueError(f"style is a table of settings, such as {{font, size, fill, outline, position}}; got {style!r}. "
                         "A named Look for the whole video goes in {op: look, id}.")
    raw = {k: v for k, v in style.items() if k not in FRIENDLY_TEXT_KEYS}
    scale = height / 1080.0
    st = {k: v for k, v in style.items() if k not in raw}
    if 'font' in st or 'italic' in st:
        f = kit.font(st.get('font', 'captions' if caption else 'heading'), 'captions' if caption else 'heading')
        if 'italic' in st:
            f['italic'] = bool(st['italic'])
        raw.update(fonts.mlt_text_style(f['family'], f['weight'], f['italic']))
    if 'fill' in st:
        raw['fgcolour'] = kit.mlt_color(st['fill'])
    if 'background' in st:
        raw['bgcolour'] = kit.mlt_color(st['background']) if st['background'] else '#00000000'
    if 'outline' in st:
        o = st['outline']
        if isinstance(o, dict):
            raw['olcolour'] = kit.mlt_color(o.get('color', 'dark'))
            raw['outline'] = round(float(o.get('width', 3)) * scale)
        elif isinstance(o, str):
            try:
                raw['outline'] = float(o)
            except ValueError:
                raw['olcolour'] = kit.mlt_color(o)
                raw['outline'] = round(3 * scale)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            raw['outline'] = o
        else:
            raw['outline'] = round(3 * scale) if o else 0
    if {'position', 'margin', 'max_lines'} & set(st):
        over = {k: st[k] for k in ('position', 'margin', 'max_lines') if k in st}
        if 'size' in raw:
            over['size'] = float(raw['size']) / scale
        placed = (kit.caption_props if caption else kit.text_props)(width, height, {**over, 'geometry': None})
        raw.update({k: placed[k] for k in ('geometry', 'halign', 'valign')})
    if 'shadow' in st:
        sh = st['shadow']
        if sh:
            raw['shadow'] = {'fgcolour': kit.mlt_color(sh.get('color', 'dark')), 'x': round(float(sh.get('x', 3)) * scale, 2),
                             'y': round(float(sh.get('y', 4)) * scale, 2)}
            if sh.get('spread'):     # a wider, soft-edged copy: its outline is the text's outline plus this
                raw['shadow']['spread'] = round(float(sh['spread']) * scale)
        else:
            raw['shadow'] = None
    return raw


def font_props(style):
    """style/weight for a text or caption style that render as asked in Shotcut's text engine (fonts.mlt_text_style).
    Accepts weight as CSS (100-900), italic: true, or a face name in style ('Black', 'SemiBold Italic')."""
    try:
        import letitedit.catalogs.fonts as fonts
    except ImportError:
        return {}
    fam = style.get('family')
    if not fam or not fonts.family(fam):
        return {}
    st = str(style.get('style') or 'normal')
    try:
        weight = int(float(style.get('weight') or 400))
    except ValueError:
        weight = 400
    if weight > 1000:
        weight = (weight - 10) // 10
    italic = bool(style.get('italic')) or 'italic' in st.lower() or 'oblique' in st.lower()
    named = {s['style'].lower(): s for s in fonts.styles(fam)}
    if st.lower() in named:
        weight, italic = named[st.lower()]['weight'], named[st.lower()]['italic']
    out = fonts.mlt_text_style(fam, weight, italic)
    return {'family': out['family'], 'style': out['style'], 'weight': out['weight']}


BLUR_PAD_PART = 'blur_pad'
BLUR_PAD_DEFAULTS = {'blur': 7}      # Shotcut's Blur: Pad as it always was; the settings are optional
BLUR_PAD_KEYS = ('blur', 'darken', 'saturation', 'tint', 'size', 'x', 'y', 'border', 'shadow', 'rect')


def blur_pad_settings(effect):
    opts = effect['blur_pad'] if isinstance(effect, dict) and isinstance(effect['blur_pad'], dict) else {}
    unknown = sorted(set(opts) - set(BLUR_PAD_KEYS))
    if unknown:
        raise ValueError(f'blur_pad: unknown setting(s) {", ".join(unknown)} (it takes {", ".join(BLUR_PAD_KEYS[:-1])})')
    out = {**BLUR_PAD_DEFAULTS, **{k: v for k, v in opts.items() if v is not None}}
    if isinstance(out.get('border'), (int, float)):
        out['border'] = {'width': out['border']}
    if out.get('shadow') is True:
        out['shadow'] = {}
    if isinstance(out.get('tint'), str):
        out['tint'] = {'color': out['tint']}
    return out


def _hex(color, alpha=None):
    c = str(color).strip()
    c = '0x' + c[1:] if c.startswith('#') else c
    return f'{c}@{float(alpha):g}' if alpha is not None else c


def _blur_pad_filters(opts, width, height):
    """The picture fitted into a portrait panel with blurred copies of itself around it (pillar_echo); the
    surroundings darkened, desaturated, tinted and given a drop shadow through a mask (mask_start ... mask_apply), so the
    picture itself is untouched; an optional border around the picture. The helpers are hidden in Shotcut's filter
    list; the settings live on the Blur: Pad filter."""
    size = min(1.0, max(0.2, float(opts.get('size', 1.0))))
    ph = round(height * size / 2) * 2
    pw = round(ph * 9 / 16 / 2) * 2
    cx, cy = float(opts.get('x', 0.5)), float(opts.get('y', 0.5))
    x0 = round(min(width - pw, max(0, width * cx - pw / 2)))
    y0 = round(min(height - ph, max(0, height * cy - ph / 2)))
    rect = opts.get('rect') or f'{x0} {y0} {pw} {ph} 1'
    rx, ry, rw, rh = [float(v) for v in str(rect).split()[:4]]
    settings = {k: opts[k] for k in BLUR_PAD_KEYS if k in opts}
    part = {'shotcut:hidden': 1, 'letitedit_ai:part': BLUR_PAD_PART}
    out = []
    if not opts.get('rect') and (size < 1.0 or abs(cx - 0.5) > 1e-6 or abs(cy - 0.5) > 1e-6):
        # the engine fits a vertical picture in the middle of the frame: scale/move the whole frame so the picture lands
        # in the panel (Blur: Pad then fills around that panel)
        fw, fh = width * size, height * size
        bx, by = x0 + pw / 2 - fw / 2, y0 + ph / 2 - fh / 2
        out.append(_filter('affine', {**part, 'background': 'color:#00000000', 'transition.fill': 1, 'transition.distort': 0,
                                      'transition.rect': f'{bx:.1f} {by:.1f} {fw:.1f} {fh:.1f} 1', 'transition.valign': 'middle',
                                      'transition.halign': 'center', 'transition.threads': 0, 'transition.fix_rotate_x': 0},
                           'affineSizePosition'))
    out.append(_filter('pillar_echo', {'rect': rect, 'blur': opts['blur'],
                                       'letitedit_ai:blur_pad': json.dumps(settings, sort_keys=True)}, 'blur_pad'))
    darken, sat = float(opts.get('darken', 0)), float(opts.get('saturation', 1))
    tint, shadow, border = opts.get('tint'), opts.get('shadow'), opts.get('border')
    bw = int((border or {}).get('width', 6)) if border else 0
    graded = []
    if darken or abs(sat - 1) > 1e-6:
        graded.append(_filter('avfilter.eq', {**part, 'av.brightness': round(-darken, 4), 'av.saturation': round(sat, 4)}))
    if tint:
        graded.append(_filter('avfilter.drawbox', {**part, 'av.x': 0, 'av.y': 0, 'av.w': width, 'av.h': height, 'av.t': 'fill',
                                                   'av.color': _hex(tint.get('color', '#0B1E2D'), tint.get('amount', 0.45))}))
    if shadow is not None and shadow is not False:
        dx, dy = shadow.get('x', 14), shadow.get('y', 16)
        graded.append(_filter('avfilter.drawbox', {**part, 'av.x': round(rx - bw + dx), 'av.y': round(ry - bw + dy),
                                                   'av.w': round(rw + 2 * bw), 'av.h': round(rh + 2 * bw), 'av.t': 'fill',
                                                   'av.color': _hex(shadow.get('color', '#000000'), shadow.get('amount', 0.45))}))
    if graded:
        # mask: 0 over the picture, 1 around it, so only the surroundings take the grade
        out.append(_filter('mask_start', {**part, 'filter': 'frei0r.alphaspot', 'filter.0': 0,
                                          'filter.1': round((rx + rw / 2) / width, 5), 'filter.2': round((ry + rh / 2) / height, 5),
                                          'filter.3': round(rw / width / 2, 5), 'filter.4': round(rh / height / 2, 5),
                                          'filter.5': 0.5, 'filter.6': 0, 'filter.7': 1, 'filter.8': 0, 'filter.9': 0}))
        out += graded
        out.append(_filter('mask_apply', {**part, 'transition': 'frei0r.cairoblend'}))
    if border:
        out.append(_filter('avfilter.drawbox', {**part, 'av.x': round(rx - bw), 'av.y': round(ry - bw),
                                                'av.w': round(rw + 2 * bw), 'av.h': round(rh + 2 * bw), 'av.t': bw,
                                                'av.color': _hex(border.get('color', '#F2E6D0'))}))
    return out


def build_filter(effect, fps, n, width, height, kit=None):
    """Filter element(s) for a friendly effect."""
    if effect == 'blur_pad' or (isinstance(effect, dict) and 'blur_pad' in effect):
        return _blur_pad_filters(blur_pad_settings(effect), width, height)
    if effect == 'mute':
        return [_filter('volume', {'gain': 0, 'channel_mask': -1}, 'muteVolume')]
    if isinstance(effect, dict) and 'filter' in effect:
        return [ee.build(effect, fps)]
    if isinstance(effect, dict) and 'split_mute' in effect:
        # a split edit's covered sound: silent over the clip's last `tail` (first `head`) seconds, crossing over
        # `fade` seconds at the sound cut; a keyframed Gain/Volume filter in Shotcut (split_edit.mute_keys)
        import letitedit.timeline.split_edit as split_edit
        spec = dict(effect['split_mute'] or {})
        if not ({'tail', 'head'} & set(spec)):
            raise ValueError(f'split_mute needs tail or head (seconds): {effect!r}')
        f = _filter('volume', {'level': _keys_to_anim(split_edit.mute_keys(spec, n, fps), fps), 'channel_mask': -1},
                    'audioGain')
        _set(f, SPLIT_MUTE_PROP, json.dumps(spec, sort_keys=True))
        return [f]
    if isinstance(effect, dict) and set(effect) == {'opacity'}:
        a = ee.value(effect['opacity'], fps)
        return [_filter('brightness', {'level': 1, 'alpha': a, 'opacity': a}, 'brightnessOpacity')]
    if isinstance(effect, dict) and ('zoom' in effect or 'size_position' in effect):
        rect = ee.motion_rect(effect, width, height, fps)
        props = {'background': 'color:#00000000', 'transition.fill': 1, 'transition.distort': 1 if effect.get('distort') else 0,
                 'transition.rect': rect, 'transition.valign': 'middle', 'transition.halign': 'center',
                 'shotcut:animIn': '00:00:00.000', 'shotcut:animOut': '00:00:00.000', 'transition.threads': 0,
                 'transition.fix_rotate_x': ee.value(effect['rotate'], fps) if effect.get('rotate') is not None else 0}
        if effect.get('lift'):
            props[LIFT_PROP] = effect['lift']
        return [_filter('affine', props, 'affineSizePosition')]
    if not isinstance(effect, dict) or len([k for k in effect if k not in ('opacity', 'style', 'floor_db')]) != 1:
        raise ValueError(f'Unknown effect: {effect!r}. Any engine effect works as {{filter: NAME, params: {{...}}}} '
                         '(find names with letitedit_effects).')
    if 'gain' in effect:
        g = effect['gain']
        if isinstance(g, dict):
            level = _keys_to_anim(g['keys'], fps)
        else:
            level = f'{float(g):g}'
        return [_filter('volume', {'level': level, 'channel_mask': -1}, 'audioGain')]
    # floor_db: how far the edge frame dips (-60 = silence; declick uses a shallow dip so no hole opens)
    floor = float(effect.get('floor_db', -60)) if isinstance(effect, dict) else -60.0
    extra = {FADE_FLOOR_PROP: f'{floor:g}'} if floor != -60 else {}
    if 'fade_in_audio' in effect:
        k = max(1, round(to_seconds(effect['fade_in_audio']) * fps))
        return [_filter('volume', {'level': f'{tm_clock(0, fps)}={floor:g};{tm_clock(k - 1, fps)}=0', 'channel_mask': -1,
                                   'shotcut:animIn': tm_clock(k, fps), **extra}, 'fadeInVolume')]
    if 'fade_out_audio' in effect:
        k = max(1, round(to_seconds(effect['fade_out_audio']) * fps))
        return [_filter('volume', {'level': f'{tm_clock(max(0, n - k), fps)}=0;{tm_clock(n - 1, fps)}={floor:g}',
                                   'channel_mask': -1, 'shotcut:animOut': tm_clock(k, fps), **extra}, 'fadeOutVolume')]
    if 'fade_in' in effect:
        k = max(1, round(to_seconds(effect['fade_in']) * fps))
        anim = f'{tm_clock(0, fps)}=0;{tm_clock(k - 1, fps)}=1'
        props = {'level': 1, 'alpha': anim} if effect.get('opacity') else {'level': anim, 'alpha': 1}
        props['shotcut:animIn'] = tm_clock(k, fps)
        return [_filter('brightness', props, 'fadeInBrightness')]
    if 'fade_out' in effect:
        k = max(1, round(to_seconds(effect['fade_out']) * fps))
        anim = f'{tm_clock(max(0, n - k), fps)}=1;{tm_clock(n - 1, fps)}=0'
        props = {'level': 1, 'alpha': anim} if effect.get('opacity') else {'level': anim, 'alpha': 1}
        props['shotcut:animOut'] = tm_clock(k, fps)
        return [_filter('brightness', props, 'fadeOutBrightness')]
    if 'text' in effect:
        kit = kit or kit_for(None)
        style = kit.text_props(width, height)
        given = dict(effect.get('style') or {})
        if not any(k in given for k in ('geometry', 'position')):
            given.setdefault('position', 'top')
        style.update(friendly_text_style(given, kit, width, height, caption=False))
        style.pop('shadow', None)
        style.update(font_props(style))
        style.pop('italic', None)
        style['argument'] = effect['text']
        return [_filter('dynamictext', style, 'dynamicText')]
    raise ValueError(f'Unknown effect: {effect!r}. Any engine effect works as {{filter: NAME, params: {{...}}}} '
                     '(find names with letitedit_effects).')


# ---------------------------------------------------------------------------- compiling

def _comparable(item):
    return {k: v for k, v in item.items() if k not in ('at', 'pin', 'len', 'from', 'said', 'recorded')}


def _refuse_first_track_move(script, doc):
    """The first video track carries the main picture, and its blend is the one that is off: a script that puts another
    video track under it would come out as a wrong picture with no error."""
    was = next((name for _, _, name, kind in doc.tracks() if kind == 'video'), None)
    video = [t['name'] for t in script['tracks'] if t.get('kind', 'video') == 'video']
    if was in video and video[0] != was:
        raise ValueError(f"This script puts {video[0]} under {was}, the first video track, which the engine can't draw "
                         f"correctly. Keep {was} first and change what is on the tracks instead (move items with "
                         "{op: move}), or reorder only the tracks above it.")


def _mute_field_to_effect(script):
    """`mute: true` on an item means the `mute` effect; the effect list is what the engine and the read keep."""
    for t in script['tracks']:
        for it in t.get('items') or []:
            if 'mute' not in it:
                continue
            effects = [e for e in it.get('effects') or [] if e != 'mute']
            if it.pop('mute'):
                effects.append('mute')
            if effects:
                it['effects'] = effects
            else:
                it.pop('effects', None)


def _compile_tracks(doc, script, base_items, used_producers, fps):
    """Compile each track and its frame-aligned items into playlists."""
    base_tracks = {name: (tr, pl, kind) for tr, pl, name, kind in doc.tracks()}
    new_track_elems = []   # (track element, playlist, kind)
    totals = []
    for t in script['tracks']:
        if any('omitted' in it for it in t['items']):
            raise ValueError(f'Track {t["name"]} was omitted when reading; read the full script before compiling.')
        kind = t.get('kind', 'video')
        if t['name'] in base_tracks:
            tr, pl, _ = base_tracks[t['name']]
            for child in [c for c in pl if c.tag in ('entry', 'blank')]:
                pl.remove(child)
        else:
            pl = ET.Element('playlist', {'id': _new_id(doc, 'playlist')})
            _set(pl, f'shotcut:{"audio" if kind == "audio" else "video"}', 1)
            _set(pl, 'shotcut:name', t['name'])
            doc.elements[pl.get('id')] = pl
            tr = ET.Element('track', {'producer': pl.get('id')})
            if kind == 'audio':
                tr.set('hide', 'video')
            # place new playlists before the main tractor
            doc.root.insert(list(doc.root).index(doc.main), pl)
        track_fx = [e for e in t.get('effects') or [] if made.is_fx(e)] if kind == 'video' else []
        engine_effects = [e for e in t.get('effects') or [] if not made.is_fx(e)]
        if engine_effects or _track_filters(pl):
            _rebuild_track_filters(doc, pl, engine_effects)
        if track_fx or _track_fx(pl, doc):
            _set_track_fx(pl, track_fx)
        if t.get('hide'):
            tr.set('hide', t['hide'])
        elif kind == 'audio':
            tr.set('hide', 'video')
        elif 'hide' in tr.attrib:
            del tr.attrib['hide']
        pos = 0
        prev_clip = None   # the entry right before, when it can take a transition
        # on every track but the main picture track, each item starts on the frame of its time in the script (gaps
        # and lengths are rounded to frames one by one, and over a hundred captions that adds up to whole seconds)
        from letitedit.timeline.edit_sync import layout as _layout, main_track as _main_track
        anchored = {} if t is _main_track(script) else {id(it): st for it, st, _ in _layout(t)}
        for k_item, item in enumerate(t['items']):
            if 'gap' in item:
                nxt = t['items'][k_item + 1] if k_item + 1 < len(t['items']) else {}
                if (nxt.get('pin') and nxt.get('at') is not None) or (id(nxt) in anchored and not nxt.get('transition')):
                    prev_clip = None
                    continue          # the item after it places itself on its exact frame
                n = round(to_seconds(item['gap']) * fps)
                if n > 0:
                    ET.SubElement(pl, 'blank', {'length': tm_clock(n, fps)})
                    pos += n
                    prev_clip = None
                continue
            if id(item) in anchored and not item.get('transition'):
                want = round(anchored[id(item)] * fps)
                if want > pos:
                    ET.SubElement(pl, 'blank', {'length': tm_clock(want - pos, fps)})
                    pos = want
            elif 'at' in item and item.get('pin'):
                want = round(to_seconds(item['at']) * fps)
                if want > pos:
                    ET.SubElement(pl, 'blank', {'length': tm_clock(want - pos, fps)})
                    pos = want
                elif want < pos - 2:
                    raise ValueError(f'{item.get("id")}: pinned at {item["at"]} but the track is already filled to {clock(pos / fps)}')
            entry, n = _compile_item(doc, item, base_items, used_producers, fps, track_fx)
            spec = transition_spec(item.get('transition'))
            if spec and prev_clip is not None:
                nt = round(spec['len'] * fps)
                pa_n = doc.f(prev_clip.get('out')) - (doc.f(prev_clip.get('in')) or 0) + 1
                if nt < 1 or nt >= n or nt >= pa_n:
                    raise ValueError(f"{item.get('id')}: a {spec['len']:g} s transition needs both clips longer than it "
                                     f"(this one {n / fps:.2f} s, the one before {pa_n / fps:.2f} s)")
                a_out = doc.f(prev_clip.get('out'))
                prev_clip.set('out', tm_clock(a_out - nt, fps))
                b_in = doc.f(entry.get('in')) or 0
                entry.set('in', tm_clock(b_in + nt, fps))
                trn = _build_transition(doc, spec, doc.elements[prev_clip.get('producer')], a_out - nt + 1,
                                        doc.elements[entry.get('producer')], b_in, nt)
                doc.root.insert(list(doc.root).index(doc.main), trn)
                doc.elements[trn.get('id')] = trn
                ET.SubElement(pl, 'entry', {'producer': trn.get('id'), 'in': tm_clock(0, fps), 'out': tm_clock(nt - 1, fps)})
                n -= nt
            pl.append(entry)
            pos += n
            prod_now = doc.elements.get(entry.get('producer'))
            prev_clip = entry if prod_now is not None and prod_now.tag != 'tractor' else None
        totals.append(pos)
        new_track_elems.append((tr, pl, kind))
        if any(e == 'blur_pad' or (isinstance(e, dict) and 'blur_pad' in e) for e in engine_effects):
            wide = [it.get('id') for it in t['items'] if 'color' in it or 'graphic' in it or made.is_made(it)]
            if wide:
                doc.render_notes.append(f"blur_pad on track {t['name']} also draws these full-frame items in the "
                                        f"narrow middle column: {', '.join(map(str, wide[:6]))}")
    return base_tracks, new_track_elems, totals


def _compile_track_order(doc, new_track_elems):
    """Reorder tracks and preserve or build their mixing and compositing transitions."""
    # tractor tracks in script order (video first is Shotcut's convention; keep script order)
    old_tracks = doc.main.findall('track')
    old_index = {id(tr): i for i, tr in enumerate(old_tracks)}
    background = [tr for tr in old_tracks if tr.get('producer') == 'background']
    for tr in old_tracks:
        doc.main.remove(tr)
    order = background + [tr for tr, _, _ in new_track_elems]
    insert_at = 0
    for child in list(doc.main):
        if child.tag == 'property':
            insert_at += 1
    for k, tr in enumerate(order):
        doc.main.insert(insert_at + k, tr)
    new_index = {id(tr): i for i, tr in enumerate(order)}
    remap = {old_index[id(tr)]: new_index[id(tr)] for tr in order if id(tr) in old_index}
    # transitions: keep those whose tracks survive (renumbered), add standard ones for new tracks
    covered_mix, covered_blend = set(), set()
    for trn in list(doc.main.findall('transition')):
        a, b = int(_get(trn, 'a_track', 0)), int(_get(trn, 'b_track', 0))
        if a not in remap and a != 0 or b not in remap:
            doc.main.remove(trn)
            continue
        _set(trn, 'a_track', remap.get(a, 0))
        _set(trn, 'b_track', remap[b])
        svc = _get(trn, 'mlt_service')
        (covered_mix if svc == 'mix' else covered_blend).add(remap[b])
    first_video = next((new_index[id(tr)] for tr, _, kind in new_track_elems if kind == 'video'), 1)
    for tr, _, kind in new_track_elems:
        b = new_index[id(tr)]
        if b not in covered_mix:
            trn = ET.SubElement(doc.main, 'transition', {'id': _new_id(doc, 'transition')})
            for k, v in (('a_track', 0), ('b_track', b), ('mlt_service', 'mix'), ('always_active', 1), ('sum', 1)):
                _set(trn, k, v)
        if kind == 'video' and b not in covered_blend:
            # MLT applies transitions in document order: picture blends must come before the audio mixes (as Shotcut
            # writes them), or a new overlay track is mixed away before it is composited and never shows.
            children = list(doc.main)
            blends = [i for i, c in enumerate(children) if c.tag == 'transition' and _get(c, 'mlt_service') != 'mix']
            mixes = [i for i, c in enumerate(children) if c.tag == 'transition' and _get(c, 'mlt_service') == 'mix']
            at = blends[-1] + 1 if blends else (mixes[0] if mixes else len(children))
            # blends composite in document order, so a track inserted below an upper one goes before that one's blend
            later = [i for i in blends if int(_get(children[i], 'b_track', 0)) > b]
            if later:
                at = later[0]
            trn = ET.Element('transition', {'id': _new_id(doc, 'transition')})
            doc.main.insert(at, trn)
            for k, v in (('a_track', 0 if b == first_video else first_video), ('b_track', b), ('version', 0.1),
                         ('mlt_service', 'frei0r.cairoblend'), ('threads', 0), ('disable', 1 if b == first_video else 0)):
                _set(trn, k, v)
    # a project saved with its picture blends out of track order (before the fix above) is put right on its next edit
    children = list(doc.main)
    slots = [i for i, c in enumerate(children) if c.tag == 'transition' and _get(c, 'mlt_service') != 'mix']
    in_order = sorted((children[i] for i in slots), key=lambda c: int(_get(c, 'b_track', 0)))
    if in_order != [children[i] for i in slots]:
        for i in slots:
            doc.main.remove(children[i])
        for i, c in zip(slots, in_order):
            doc.main.insert(i, c)


def _compile_master(script, doc):
    """Replace or remove the master audio chain requested by the script."""
    # master audio chain
    if 'master' in script and script['master'] != _master_effects(doc):
        kept = _master_kept(doc)
        originals = _master_filters(doc)
        patched = set()
        for f in originals:
            doc.main.remove(f)
        for eff in script['master']:
            el = _build_master(eff, doc, kept, originals, patched)
            if not el.get('id'):
                el.set('id', _new_id(doc, 'filter'))
            doc.main.append(el)
    elif 'master' not in script and _master_filters(doc):
        for f in _master_filters(doc):
            doc.main.remove(f)


def _compile_captions(script, doc):
    """Update caption feeds, burn-in filters and styles, then remove obsolete feeds."""
    # captions
    if 'captions' in script:
        # no caption runs into the last frame (the engine would not draw it); the script's own cues change too, so a
        # live window gets the same ones
        doc.render_notes += fit_captions(script, doc_frames(doc), doc.fps)
        feeds = {_get(f, 'feed'): f for f in doc.main.findall('filter') if _get(f, 'mlt_service') == 'subtitle_feed'}
        for cap in script['captions']:
            srt = _srt(cap['cues'])
            if cap['track'] in feeds:
                _set(feeds[cap['track']], 'text', srt)
                if cap.get('style'):
                    _restyle_captions(doc, cap['track'], cap['style'])
            else:
                f = ET.SubElement(doc.main, 'filter', {'id': _new_id(doc, 'filter')})
                for k, v in (('feed', cap['track']), ('lang', 'eng'), ('mlt_service', 'subtitle_feed'), ('shotcut:hidden', 1), ('text', srt)):
                    _set(f, k, v)
                if cap.get('burn_in', True):
                    kit = doc.kit
                    style = kit.caption_props(doc.width, doc.height)
                    if kit['captions'].get('shadow'):
                        style.update(friendly_text_style({'shadow': kit['captions']['shadow']}, kit, doc.width, doc.height))
                    style.update(cap.get('style') or {})
                    style.update(font_props(style))
                    style.pop('italic', None)
                    shadow = style.pop('shadow', None)
                    if shadow:
                        sb = ET.SubElement(doc.main, 'filter', {'id': _new_id(doc, 'filter')})
                        for k, v in {**style, 'fgcolour': shadow['fgcolour'], 'olcolour': shadow['fgcolour'],
                                     **_shadow_outline(style, shadow),
                                     'geometry': _offset_geom(style['geometry'], shadow['x'], shadow['y']),
                                     'feed': cap['track'], 'mlt_service': 'subtitle', 'shotcut:filter': 'subtitles',
                                     'letitedit_ai:role': 'shadow'}.items():
                            _set(sb, k, v)
                    b = ET.SubElement(doc.main, 'filter', {'id': _new_id(doc, 'filter')})
                    for k, v in {**style, 'feed': cap['track'], 'mlt_service': 'subtitle', 'shotcut:filter': 'subtitles'}.items():
                        _set(b, k, v)
        keep = {c['track'] for c in script['captions']}
        for name, f in feeds.items():
            if name not in keep:
                doc.main.remove(f)
                for b in [x for x in doc.main.findall('filter') if _get(x, 'mlt_service') == 'subtitle' and _get(x, 'feed') == name]:
                    doc.main.remove(b)


def _finish_timeline_graph(totals, doc, fps):
    """Set project duration and remove unreferenced transitions and producers."""
    # overall length
    total = max(totals or [1])
    for f in doc.main.findall('filter'):
        if f.get('out') is not None and _get(f, ee.AIM_TAG) is None:
            f.set('out', tm_clock(total - 1, fps))
    doc.main.set('in', tm_clock(0, fps))
    doc.main.set('out', tm_clock(total - 1, fps))
    black = doc.elements.get('black')
    if black is not None:
        black.set('out', tm_clock(total - 1, fps))
        _set(black, 'length', tm_clock(total, fps) if ':' in (_get(black, 'length') or '') else total)
    bg = doc.elements.get('background')
    if bg is not None:
        for e in bg.findall('entry'):
            e.set('out', tm_clock(total - 1, fps))
    # remove transitions and producers that are no longer referenced by any entry
    in_entries = {e.get('producer') for e in doc.root.iter('entry')}
    for el in list(doc.root):
        if el.tag == 'tractor' and el is not doc.main and _get(el, TRANSITION_PROP) is not None and el.get('id') not in in_entries:
            doc.root.remove(el)
    referenced = {e.get('producer') for e in doc.root.iter('entry')} | {t.get('producer') for t in doc.root.iter('track')}
    for el in list(doc.root):
        if el.tag in ('chain', 'producer') and el.get('id') not in referenced and el.get('id') != 'black':
            doc.root.remove(el)


def compile_script(script, base=None, out=None, force=False, graphics_dir=None):
    """Write a project from a script. base = the project the script was read from (default script['project']).
    Raises Conflict if base changed since the script was read (unless force). Returns the output path."""
    base = Path(base or script['project'])
    if not force and script.get('base') and file_hash(base) != script['base']:
        raise Conflict('The timeline changed since this script was read (probably edited in Shotcut). Read it again, '
                       'or use apply_changes for edits by id.')
    if script.get('partial'):
        raise ValueError('This script only covers part of the timeline; use apply_changes for partial edits.')
    if (script.get('view') or {}).get('compact'):
        raise ValueError('This is the compact view (keyframes and long texts folded); read with detail="full" to send '
                         'a whole script, or use apply_changes for edits by id.')
    doc = Doc(base)
    fps = doc.fps
    _refuse_first_track_move(script, doc)
    _mute_field_to_effect(script)
    doc.kit = kit_for(script)
    doc.render_notes = script.setdefault('_render_notes', [])
    doc.graphics_dir = Path(graphics_dir) if graphics_dir else None
    identity = project_look_identity(script)
    if identity:
        script['look'] = identity
    for key, prop in (('look', LOOK_PROP), ('hook', HOOK_PROP)):
        if script.get(key) != _get(doc.main, prop):
            if script.get(key):
                _set(doc.main, prop, script[key])
            else:
                for p in [p for p in doc.main.findall('property') if p.get('name') == prop]:
                    doc.main.remove(p)
    ids = _ids_for(doc)
    base_items = {}   # id -> (entry element, producer element, view)
    for tr, pl, name, kind in doc.tracks():
        for r in _track_records(doc, pl, name, ids):
            if r['kind'] == 'entry':
                view = item_view(doc, r['entry'], r['prod'], r['id'])
                if r.get('transition'):
                    view['transition'] = r['transition']
                base_items[r['id']] = (r['entry'], r['prod'], view)
    used_producers = {}
    _prerender_graphics(doc, script, base_items)
    _prerender_fx(doc, script, base_items)
    _prerender_mattes(doc, script, base_items)
    base_tracks, new_track_elems, totals = _compile_tracks(doc, script, base_items, used_producers, fps)

    _compile_track_order(doc, new_track_elems)

    # track volume and auto-ducking (needs the transitions in place)
    for (tr, pl, kind), t in zip(new_track_elems, script['tracks']):
        _apply_track_audio(doc, t, tr, pl, kind)
    _compile_master(script, doc)

    _ensure_flatten(doc, sum(1 for _, _, kind in new_track_elems if kind == 'video') > 1)
    # drop playlists of removed tracks
    kept_pl = {pl.get('id') for _, pl, _ in new_track_elems}
    for name, (tr, pl, kind) in base_tracks.items():
        if pl.get('id') not in kept_pl and pl in list(doc.root):
            doc.root.remove(pl)
    _compile_captions(script, doc)

    _finish_timeline_graph(totals, doc, fps)

    _order_elements(doc)
    import letitedit.timeline.stack as stack
    doc.render_notes += stack.blend_notes(script, doc)
    out = Path(out or base)
    tmp = out.with_name(out.name + f'.{uuid.uuid4().hex[:6]}.tmp')
    import letitedit.core.long_paths as long_paths
    long_paths.check(tmp)
    ET.indent(doc.tree, space='  ')
    doc.tree.write(tmp, encoding='utf-8', xml_declaration=True)
    os.replace(tmp, out)
    return out


def _order_elements(doc):
    """Put every element after the producers it uses (MLT reads the file in one pass and silently drops an entry
    whose producer comes later). Keeps the existing order wherever it is already valid."""
    kids = list(doc.root)
    pos = {id(e): i for i, e in enumerate(kids)}
    by_id = {e.get('id'): e for e in kids if e.get('id')}
    deps = {}
    for e in kids:
        refs = {x.get('producer') for x in e.iter() if x is not e and x.tag in ('entry', 'track')}
        deps[id(e)] = sorted((by_id[r] for r in refs if r in by_id and by_id[r] is not e), key=lambda d: pos[id(d)])
    placed, ordered = set(), []

    def visit(e):
        if id(e) in placed:
            return
        placed.add(id(e))
        for d in deps[id(e)]:
            visit(d)
        ordered.append(e)
    for e in kids:
        visit(e)
    if [id(e) for e in ordered] != [id(e) for e in kids]:
        for e in kids:
            doc.root.remove(e)
        for e in ordered:
            doc.root.append(e)


def doc_frames(doc):
    """The timeline's length in frames as the engine counts it: its longest track (blanks and entries)."""
    best = 0
    for tr, pl, name, kind in doc.tracks():
        pos = 0
        for e in pl:
            if e.tag == 'blank':
                pos += tm.clock_to_frames(e.get('length'), doc.fps) or 0
            elif e.tag == 'entry':
                a = tm.clock_to_frames(e.get('in'), doc.fps) or 0
                b = tm.clock_to_frames(e.get('out'), doc.fps)
                if b is None:
                    src = doc.elements.get(e.get('producer'))
                    b = (tm.clock_to_frames(src.get('out'), doc.fps) or 0) if src is not None else a
                pos += b - a + 1
        best = max(best, pos)
    return best


def fit_captions(script, frames, fps=None):
    """The engine's caption burn-in draws nothing, for the whole cue, when a cue runs into the timeline's last frame
    (a 12 s video at 30 fps: a cue ending at 11.933 s shows, one ending at 11.967 or 12.5 s never does). So every cue
    ends by the start of the frame before the last one (frames: the timeline's length in frames, doc_frames); a cue
    that only starts there is dropped. Changes `script` in place; returns notes."""
    fps = float(fps or (script.get('profile') or {}).get('fps') or 30)
    if frames < 3:
        return []
    last = math.floor((frames - 2) / fps * 1000) / 1000
    notes = []
    for cap in script.get('captions') or []:
        cues, cut, dropped = [], 0, 0
        for q in cap.get('cues') or []:
            if to_seconds(q['end']) > last + 1e-6:
                # one that only starts on the last frames is dropped, and so is one the cut leaves under 0.1 s (it would
                # flash for a frame or two, unreadable)
                if to_seconds(q['start']) >= last - 0.5 / fps or last - to_seconds(q['start']) < 0.1:
                    dropped += 1
                    continue
                q = dict(q, end=clock(last) if isinstance(q['end'], str) else last)
                cut += 1
            cues.append(q)
        if cut or dropped:
            cap['cues'] = cues
            notes.append(f"captions \"{cap['track']}\": " + ', '.join(
                x for x in (f'{cut} caption(s) now end at {clock(last)}, a frame before the last' if cut else '',
                            f'{dropped} starting on the last frames dropped' if dropped else '') if x)
                         + " (the engine draws no caption that runs into the video's last frame)")
    return notes


def _srt(cues):
    def t(s):
        ms = int(round(to_seconds(s) * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'
    cues = sorted(cues, key=lambda c: to_seconds(c['start']))
    return '\n'.join(f'{i}\n{t(c["start"])} --> {t(c["end"])}\n{c["text"]}\n' for i, c in enumerate(cues, 1))


def fill_out(item):
    """A clip given without out: a video or sound plays to the end of its file, a picture lasts `len` (5 s)."""
    if 'clip' in item and 'out' not in item and not made.is_made(item) and 'graphic' not in item:
        item.setdefault('in', 0.0)
        if Path(item['clip']).suffix.lower() in IMAGE_EXT:
            item['out'] = round(to_seconds(item['in']) + to_seconds(item.get('len', 5)), 4)
        else:
            dur = probe(item['clip']).get('duration')
            if dur:
                item['out'] = round(float(dur), 4)
            elif not Path(item['clip']).exists():
                raise FileNotFoundError(f"no such file: {item['clip']}")
            else:
                raise ValueError(f"can't read the length of {item['clip']}; give the item an out")
    return item


def _compile_item(doc, item, base_items, used, fps, track_fx=()):
    """Return (entry element, frames on timeline)."""
    iid = item.get('id')
    fill_out(item)
    base = base_items.get(iid) or base_items.get(item.get('from'))
    if item.get('adjust'):
        same = {iid: (base[0], base[1], adjust.plain_item(base[2]))} if base else {}
        entry, n = _compile_item(doc, adjust.plain_item(item), same, used, fps)
        adjust.mark(doc.elements[entry.get('producer')], fps)
        return entry, n
    if 'scene' in item:
        return _compile_scene(doc, item, base, used, fps)
    if 'clip' in item and not made.is_made(item) and 'graphic' not in item and _fx_for(item, track_fx):
        return _compile_fx(doc, item, base_items, used, fps, _fx_for(item, track_fx), track_fx)
    if 'raw' in item:
        if not base:
            raise ValueError(f'{iid}: raw item without an original')
        e, prod, view = base
        entry = copy.deepcopy(e)
        return entry, (doc.f(e.get('out')) - (doc.f(e.get('in')) or 0) + 1)
    if 'graphic' in item:
        return _compile_graphic(doc, item, base_items, used, fps)
    if 'freeze' in item:
        fx = [e for e in item.get('effects') or [] if made.is_fx(e)] + list(track_fx)
        if fx:
            return _compile_freeze_fx(doc, item, base_items, used, fps, fx, track_fx)
    if made.is_made(item):
        return _compile_made(doc, item, base_items, used, fps)
    speed = float(item.get('speed', 1.0))
    if 'color' in item and 'out' not in item:
        n = round(to_seconds(item.get('len', 5)) * fps)
        a, b = 0, n - 1
    else:
        a = round(to_seconds(item['in']) * fps / speed)
        b = round(to_seconds(item['out']) * fps / speed) - 1
        n = b - a + 1
        if n < 1:
            raise ValueError(f'{iid or item.get("clip")}: out must be after in')
    if base:
        e, prod, view = base
        unchanged = _comparable(view) == _comparable(item)
        same_source = (view.get('clip') == item.get('clip') and abs(float(view.get('speed', 1.0)) - speed) < 1e-9
                       and view.get('color') == item.get('color') and not _get(prod, made.FX_PROP))
    else:
        unchanged = same_source = False
    if base and same_source:
        e, prod, view = base
        if prod.get('id') in used:
            prod = copy.deepcopy(prod)
            prod.set('id', _new_id(doc, prod.tag))
            doc.root.insert(list(doc.root).index(doc.main), prod)
            doc.elements[prod.get('id')] = prod
        if unchanged:
            a0, b0 = doc.f(e.get('in')) or 0, doc.f(e.get('out'))
            a, b, n = a0, b0, b0 - a0 + 1
        else:
            _rebuild_filters(doc, prod, item, view, a, b, n, fps)
    else:
        prod = build_producer(doc, item, fps)
        if base:
            # source changed: carry kept filters over from the original clip
            _, old, view = base
            _rebuild_filters(doc, prod, item, view, a, b, n, fps, old=old)
        else:
            _rebuild_filters(doc, prod, item, None, a, b, n, fps)
        doc.root.insert(list(doc.root).index(doc.main), prod)
        doc.elements[prod.get('id')] = prod
    used[prod.get('id')] = True
    _set(prod, ID_PROP, iid or _new_id(doc, 'clip-'))
    if 'name' in item:
        _set(prod, 'shotcut:caption', item['name'])
    _set_split(prod, item)
    plen = doc.f(_get(prod, 'length') or '0') or 0
    if b >= plen and _get(prod, 'mlt_service') not in ('color', 'qimage'):
        if b - plen <= round(0.15 * fps) and plen > a:
            b = plen - 1                  # an out point a hair past the end (a rounded length): the file's last frame
            n = b - a + 1
        else:
            raise ValueError(f'{iid or item.get("clip")}: out point {to_seconds(item.get("out", 0)):.3f}s is past the end of '
                             f'the source ({plen / fps:.3f}s)')
    entry = ET.Element('entry', {'producer': prod.get('id'), 'in': tm_clock(a, fps), 'out': tm_clock(b, fps)})
    return entry, n


def _compile_scene(doc, item, base, used, fps):
    """A saved code scene is a selectable transparent timeline clip. Its live
    picture comes from WebView2; export substitutes its exact full render in a
    snapshot. The marker itself never becomes a low-quality export fallback."""
    scene = item['scene']
    if not isinstance(scene, dict) or not scene.get('id') or not scene.get('revision'):
        raise ValueError('a code scene needs scene: {id, revision}')
    n = round(to_seconds(item.get('len', 0)) * fps)
    if n < 1:
        raise ValueError('a code scene needs a positive len')
    if base and base[1].get('id') not in used and _get(base[1], SCENE_PROP):
        prod = base[1]
    else:
        prod = build_producer(doc, {'color': '#00000000', 'len': n / fps,
                                    'name': item.get('name') or 'Code scene'}, fps)
        doc.root.insert(list(doc.root).index(doc.main), prod)
        doc.elements[prod.get('id')] = prod
    _set(prod, ID_PROP, item.get('id') or _new_id(doc, 'scene-'))
    _set(prod, SCENE_PROP, json.dumps(scene, sort_keys=True))
    _set(prod, 'shotcut:caption', item.get('name') or 'Code scene')
    used[prod.get('id')] = True
    skip = round(to_seconds(item.get('in') or 0) * fps)
    if skip + n > (doc.f(prod.get('out')) or 0) + 1:
        prod.set('out', str(skip + n - 1))
    return ET.Element('entry', {'producer': prod.get('id'), 'in': tm_clock(skip, fps),
                                'out': tm_clock(skip + n - 1, fps)}), n


def _set_split(prod, item):
    """Store (or clear) split-edit and sound-target records on a clip's producer."""
    from letitedit.looks.sound_targets import PROPERTY
    if isinstance(item.get('sound_target'), dict):
        _set(prod, PROPERTY, json.dumps(item['sound_target'], sort_keys=True))
    else:
        for prop in [prop for prop in prod.findall('property') if prop.get('name') == PROPERTY]:
            prod.remove(prop)
    if isinstance(item.get('split_edit'), dict):
        _set(prod, SPLIT_PROP, json.dumps(item['split_edit'], sort_keys=True))
    else:
        for p in [p for p in prod.findall('property') if p.get('name') == SPLIT_PROP]:
            prod.remove(p)
    if isinstance(item.get('multicam'), dict):
        _set(prod, MULTICAM_PROP, json.dumps(item['multicam'], sort_keys=True))
    else:
        for p in [p for p in prod.findall('property') if p.get('name') == MULTICAM_PROP]:
            prod.remove(p)


def _fx_for(item, track_fx):
    """The ffmpeg effects a clip plays through: its own, then its track's (track ones only on clips with a picture)."""
    own = [e for e in item.get('effects') or [] if made.is_fx(e)]
    if track_fx and 'clip' in item and (Path(item['clip']).suffix.lower() in IMAGE_EXT
                                        or probe(item['clip'])['video_index'] >= 0):
        return own + list(track_fx)
    return own


def _fx_plan(doc, item, base, fx_effects, fps):
    """(recipe to render, None) for a clip with ffmpeg effects, or (None, base producer) when the base render covers it."""
    speed = float(item.get('speed', 1.0))
    s_in, s_out = to_seconds(item['in']), to_seconds(item['out'])
    if s_out <= s_in:
        raise ValueError(f"{item.get('id') or item['clip']}: out must be after in")
    stages = [made.fx_stage(e) for e in fx_effects]
    if base is not None:
        old = _get(base[1], made.FX_PROP)
        old = json.loads(old) if old else None
        if (old and old['clip'] == item['clip'] and abs(old.get('speed', 1.0) - speed) < 1e-9 and old['stages'] == stages
                and old['start'] <= s_in + 0.5 / fps and old['end'] >= s_out - 0.5 / fps):
            return None, base[1]
    image = Path(item['clip']).suffix.lower() in IMAGE_EXT
    info = {'duration': 0, 'video_index': 0, 'audio_index': -1} if image else probe(item['clip'])
    handle = made.FX_HANDLE_S * speed
    start = math.floor(max(0.0, s_in - handle) * fps) / fps
    end = s_out + handle
    if info['duration']:
        if s_out > info['duration'] + 1.0 / fps:
            raise ValueError(f"{item.get('id') or item['clip']}: out point {s_out:.3f}s is past the end of the source "
                             f"({info['duration']:.3f}s)")
        end = min(end, info['duration'])
    recipe = {'kind': 'fx', 'clip': item['clip'], 'in': round(start, 4), 'out': round(end, 4), 'speed': speed,
              'stages': stages, 'picture': info['video_index'] >= 0, 'sound': info['audio_index'] >= 0}
    return recipe, None


def _prerender_fx(doc, script, base_items):
    """Render every clip whose ffmpeg effects (its own or its track's) need a new render, several at once."""
    from concurrent.futures import ThreadPoolExecutor
    jobs, seen = [], set()
    for t in script['tracks']:
        track_fx = [e for e in t.get('effects') or [] if made.is_fx(e)] if t.get('kind', 'video') == 'video' else []
        for it in t['items']:
            if 'clip' not in it or made.is_made(it) or 'graphic' in it:
                continue
            fx = _fx_for(it, track_fx)
            if not fx:
                continue
            base = base_items.get(it.get('id')) or base_items.get(it.get('from'))
            recipe, _ = _fx_plan(doc, it, base, fx, doc.fps)
            key = json.dumps(recipe, sort_keys=True) if recipe else None
            if recipe and key not in seen:
                seen.add(key)
                jobs.append((it.get('id'), recipe))
    if len(jobs) < 2:
        return

    def run(job):
        iid, recipe = job
        try:
            made.render(recipe, doc.width, doc.height, doc.fps, out_dir=_made_dir(doc))
        except Exception as exc:  # noqa: BLE001
            raise type(exc)(f'{iid}: {exc}') from None
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as pool:
        list(pool.map(run, jobs))
    doc.render_notes.append(f'rendered {len(jobs)} clips through their ffmpeg effects in {time.monotonic() - started:.0f} s '
                            f'(trims within {made.FX_HANDLE_S:g} s of a render reuse it)')


def _prerender_mattes(doc, script, base_items):
    """Every person matte this script's new cut-outs need, as one job with one model load, before their clips are made.
    A clip that finds a matte missing still makes it itself, so nothing here can fail the edit."""
    recipes = []
    for t in script['tracks']:
        for it in t['items']:
            if isinstance(it.get('vfx'), dict):
                base = base_items.get(it.get('id')) or base_items.get(it.get('from'))
                if base and _comparable(base[2]) == _comparable(it):
                    continue        # unchanged: _compile_made keeps its clip and makes nothing
                try:
                    recipe = made.recipe_of(it)
                    if not _movie_of(doc, base, recipe):     # a trim only changes which part of its movie plays
                        recipes.append(recipe)
                except (ValueError, OSError, KeyError, TypeError):      # the clip itself reports what is wrong with it
                    pass
    if not recipes:
        return
    import letitedit.pictures.vfx_items as vfx_items
    res = vfx_items.fill_mattes(recipes, doc.width, doc.height, doc.fps, out_dir=_made_dir(doc))
    if res and res.get('drawn'):
        doc.render_notes.append(f"person cut-outs: {res['drawn']} frames drawn and {res['kept']} already known, in "
                                f"{res.get('seconds', 0):.0f} s")


def _compile_fx(doc, item, base_items, used, fps, fx_effects, track_fx=()):
    """A clip played through ffmpeg effects: render its source range (with handles) once and play the render. The
    source clip, its in/out and the graphs stay on the producer, so the timeline still reads as the source clip."""
    iid = item.get('id')
    base = base_items.get(iid) or base_items.get(item.get('from'))
    speed = float(item.get('speed', 1.0))
    s_in, s_out = to_seconds(item['in']), to_seconds(item['out'])
    n = round(s_out * fps / speed) - round(s_in * fps / speed)
    if n < 1:
        raise ValueError(f'{iid or item.get("clip")}: out must be after in')
    recipe, prod = _fx_plan(doc, item, base, fx_effects, fps)
    own = [e for e in item.get('effects') or [] if made.is_fx(e)]
    rest = dict(item, effects=[e for e in item.get('effects') or [] if not made.is_fx(e)])
    if prod is not None:
        fx = json.loads(_get(prod, made.FX_PROP))
        if prod.get('id') in used:
            prod = copy.deepcopy(prod)
            prod.set('id', _new_id(doc, prod.tag))
            doc.root.insert(list(doc.root).index(doc.main), prod)
            doc.elements[prod.get('id')] = prod
        old = None
    else:
        try:
            rendered = made.render(recipe, doc.width, doc.height, fps, out_dir=_made_dir(doc))
        except Exception as exc:  # noqa: BLE001
            raise type(exc)(f'{iid}: {exc}') from None
        kinds = [st['fix']['kind'] for st in recipe['stages'] if 'fix' in st]
        caption = item.get('name') or (f"{os.path.basename(item['clip'])} (fix: {', '.join(kinds)})" if kinds
                                       else f"{os.path.basename(item['clip'])} (ffmpeg)")
        prod = build_producer(doc, {'clip': rendered['path'], 'name': caption}, fps)
        fx = {'clip': item['clip'], 'start': recipe['in'], 'end': recipe['out'], 'speed': speed, 'stages': recipe['stages']}
        doc.root.insert(list(doc.root).index(doc.main), prod)
        doc.elements[prod.get('id')] = prod
        old = base[1] if base else None
    fx['effects'] = own
    fx['track'] = list(fx_effects[len(own):])
    if item.get('name'):
        fx['name'] = item['name']
    else:
        fx.pop('name', None)
    _set(prod, made.FX_PROP, json.dumps(fx, sort_keys=True))
    a = round((s_in - fx['start']) * fps / speed)
    b = a + n - 1
    plen = doc.f(_get(prod, 'length') or '0') or 0
    if b >= plen:
        if b - plen > 2:
            raise ValueError(f'{iid or item.get("clip")}: out point {s_out:.3f}s is past the end of the source')
        b = plen - 1
        n = b - a + 1
    view = base[2] if base else None
    if view is not None:
        view = dict(view, effects=[e for e in view.get('effects') or [] if not made.is_fx(e)])
    _rebuild_filters(doc, prod, rest, view, a, b, n, fps, old=old)
    used[prod.get('id')] = True
    _set(prod, ID_PROP, iid or _new_id(doc, 'clip-'))
    if 'name' in item:
        _set(prod, 'shotcut:caption', item['name'])
    _set_split(prod, item)
    entry = ET.Element('entry', {'producer': prod.get('id'), 'in': tm_clock(a, fps), 'out': tm_clock(b, fps)})
    return entry, n


def _made_dir(doc):
    return getattr(doc, 'graphics_dir', None) and Path(doc.graphics_dir).parent / 'made' or doc.path.parent / 'made'


def _compile_freeze_fx(doc, item, base_items, used, fps, fx_effects, track_fx):
    """A freeze frame with ffmpeg effects (its own, or its track's such as a blurred fill): the source frame at its own
    size, held for the freeze's length, played through the effects like any clip. Reads back as the freeze."""
    fz = item['freeze']
    still = made.render({'kind': 'still', 'clip': str(fz['clip']), 'at': to_seconds(fz.get('at', 0))},
                        doc.width, doc.height, fps, out_dir=_made_dir(doc))
    length = made.default_len(item)
    clip_item = {k: v for k, v in item.items() if k not in ('freeze', 'len', 'skip')}
    clip_item.update(clip=still['path'], **{'in': 0.0, 'out': round(length, 4)})
    entry, n = _compile_fx(doc, clip_item, base_items, used, fps, fx_effects, track_fx)
    prod = doc.elements.get(entry.get('producer'))
    if prod is not None:
        recipe = made.recipe_of(item)
        _set(prod, made.MADE_PROP, json.dumps(recipe, sort_keys=True))
    return entry, n


def _movie_of(doc, base, recipe):
    """The movie an item already plays, when its recipe is the one this new item asks for: a trim or a split only changes
    which part of it plays, wherever it is kept (a copy of a project plays the original's). None: it must be made."""
    if not base or base[1] is None:
        return None
    stored = _get(base[1], made.MADE_PROP)
    if not stored:
        return None
    try:
        if json.loads(stored) != json.loads(json.dumps(recipe, sort_keys=True)):
            return None
    except ValueError:
        return None
    resource = _get(base[1], 'resource')
    if not resource:
        return None
    path = Path(resource) if Path(resource).is_absolute() else doc.path.parent / resource
    return str(path) if path.is_file() else None


def _compile_made(doc, item, base_items, used, fps):
    """A clip made from other clips (ffmpeg graph, reverse, freeze): render (or reuse) it and place it."""
    iid = item.get('id')
    base = base_items.get(iid) or base_items.get(item.get('from'))
    if base and _comparable(base[2]) == _comparable(item) and base[1].get('id') not in used:
        e, prod, view = base
        n = (doc.f(e.get('out')) or 0) - (doc.f(e.get('in')) or 0) + 1
        if item.get('len') is None or round(to_seconds(item['len']) * fps) == n:
            used[prod.get('id')] = True
            _set(prod, ID_PROP, iid)
            return copy.deepcopy(e), n
    if isinstance(item.get('motion'), dict) and not item['motion'].get('kit') and not item['motion'].get('pack'):
        import letitedit.pictures.motion as motion
        import letitedit.looks.look_library as look_library
        selected = look_library.kit(item['motion']['look']) if item['motion'].get('look') else doc.kit
        item = dict(item, motion=dict(item['motion'], kit=motion.kit_snapshot(selected)))
    recipe = made.recipe_of(item)
    kept = _movie_of(doc, base, recipe)
    rendered = {'path': kept, 'cached': True} if kept else made.render(recipe, doc.width, doc.height, fps,
                                                                       out_dir=_made_dir(doc))
    for note in ([rendered['notes']] if isinstance(rendered.get('notes'), str) else rendered.get('notes') or []):
        doc.render_notes.append(f'{iid}: {note}')
    skip = round(to_seconds(item.get('skip', 0)) * fps)
    if recipe['kind'] == 'freeze':
        n = round(made.default_len(item) * fps)
    elif item.get('len') is not None and recipe['kind'] not in ('reverse', 'voice'):
        n = round(to_seconds(item['len']) * fps)
    else:
        n = round(probe(rendered['path'])['duration'] * fps) - skip
    prod = build_producer(doc, {'clip': rendered['path'], 'name': item.get('name') or made.label_of(recipe)}, fps)
    _rebuild_filters(doc, prod, item, base[2] if base else None, skip, skip + n - 1, n, fps, old=base[1] if base else None)
    _set(prod, made.MADE_PROP, json.dumps(recipe, sort_keys=True))
    doc.root.insert(list(doc.root).index(doc.main), prod)
    doc.elements[prod.get('id')] = prod
    used[prod.get('id')] = True
    _set(prod, ID_PROP, iid or _new_id(doc, 'made-'))
    plen = doc.f(_get(prod, 'length') or '0') or 0
    if recipe['kind'] != 'freeze' and skip + n > plen + 1:
        raise ValueError(f"{iid}: the made clip is {plen / fps:.2f} s, shorter than skip + len ({(skip + n) / fps:.2f} s)")
    n = min(n, plen - skip) if recipe['kind'] != 'freeze' else n
    entry = ET.Element('entry', {'producer': prod.get('id'), 'in': tm_clock(skip, fps), 'out': tm_clock(skip + n - 1, fps)})
    return entry, n


def _shadow_outline(style, shadow):
    """The shadow copy's outline: the text's own, plus the shadow's spread (a soft halo) when it has one."""
    if not shadow.get('spread'):
        return {}
    try:
        base = float(style.get('outline') or 0)
    except (TypeError, ValueError):
        base = 0.0
    width = round(base + float(shadow['spread']))
    return {'outline': width, 'outline_width': width}


def _restyle_captions(doc, feed, style):
    """Bring a caption track's burn-in (and its shadow copy) to `style` (raw filter properties + shadow)."""
    main_b, shadow_b = _caption_burns(doc, feed)
    if main_b is None:
        return
    want = dict(style)
    shadow = want.pop('shadow', None)
    current = _props(main_b)
    changed = {k: v for k, v in want.items() if str(current.get(k)) != str(v)}
    if {'family', 'weight', 'style', 'italic'} & set(changed):
        changed.update(font_props({**current, **changed}))
    changed.pop('italic', None)
    for k, v in changed.items():
        _set(main_b, k, v)
    if shadow:
        mp = _props(main_b)
        target = {**{k: mp[k] for k in CAPTION_STYLE_KEYS if k in mp}, 'fgcolour': shadow['fgcolour'],
                  'olcolour': shadow['fgcolour'], **_shadow_outline(mp, shadow),
                  'geometry': _offset_geom(mp['geometry'], shadow['x'], shadow['y'])}
        if shadow_b is None:
            shadow_b = ET.Element('filter', {'id': _new_id(doc, 'filter')})
            for k in ('in', 'out'):
                if main_b.get(k) is not None:
                    shadow_b.set(k, main_b.get(k))
            for k, v in (('feed', feed), ('mlt_service', 'subtitle'), ('shotcut:filter', 'subtitles'),
                         ('letitedit_ai:role', 'shadow')):
                _set(shadow_b, k, v)
            doc.main.insert(list(doc.main).index(main_b), shadow_b)
        sp_ = _props(shadow_b)
        for k, v in target.items():
            if str(sp_.get(k)) != str(v):
                _set(shadow_b, k, v)
    elif shadow_b is not None:
        doc.main.remove(shadow_b)


def _graphics_dir(doc):
    return getattr(doc, 'graphics_dir', None) or doc.path.parent / 'graphics'


def _graphic_job(doc, item, base_items, fps):
    """The render recipe for a graphic item, or None when the clip is unchanged (nothing to render)."""
    g = item['graphic']
    n = max(1, round(to_seconds(item.get('len', 0) or 0) * fps)) if item.get('len') else None
    base = base_items.get(item.get('id')) or base_items.get(item.get('from'))
    if base:
        e, prod, view = base
        old_n = (doc.f(e.get('out')) or 0) - (doc.f(e.get('in')) or 0) + 1
        if n is None:
            n = old_n
        if _comparable(view) == _comparable(item) and n == old_n:
            return None
    recipe = {'template': g['template'], 'params': g.get('params') or {}}
    if g.get('code'):
        recipe['code'] = g['code']
    if g.get('source'):
        recipe['source'] = g['source']
    if n is not None:
        recipe['len'] = n / fps
    return recipe


def _prerender_graphics(doc, script, base_items):
    """Render every new or changed graphic at once, several in parallel (captions can be a hundred of them); the
    compiler then finds them already made."""
    import letitedit.pictures.graphics as graphics
    from concurrent.futures import ThreadPoolExecutor
    jobs, seen = [], set()
    for t in script['tracks']:
        for it in t['items']:
            r = _graphic_job(doc, it, base_items, doc.fps) if 'graphic' in it else None
            key = json.dumps(r, sort_keys=True, default=str) if r is not None else None
            if r is not None and key not in seen:       # the same graphic twice renders once (one file each)
                seen.add(key)
                jobs.append(r)
    if len(jobs) < 2:
        return
    out_dir = _graphics_dir(doc)
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as pool:
        list(pool.map(lambda r: graphics.render(r, doc.width, doc.height, doc.fps, kit=doc.kit, out_dir=out_dir), jobs))


def _compile_graphic(doc, item, base_items, used, fps):
    """A Python-drawn graphic: render (or reuse) its file and place it like a clip. Returns (entry, frames)."""
    import letitedit.pictures.graphics as graphics
    iid = item.get('id')
    g = item['graphic']
    n = max(1, round(to_seconds(item.get('len', 0) or 0) * fps)) if item.get('len') else None
    base = base_items.get(iid) or base_items.get(item.get('from'))
    if base:
        e, prod, view = base
        old_n = (doc.f(e.get('out')) or 0) - (doc.f(e.get('in')) or 0) + 1
        if n is None:
            n = old_n
        if _comparable(view) == _comparable(item) and n == old_n:
            used[prod.get('id')] = True
            _set(prod, ID_PROP, iid)
            return copy.deepcopy(e), n
    recipe = {'template': g['template'], 'params': g.get('params') or {}}
    if g.get('code'):
        recipe['code'] = g['code']
    if g.get('source'):
        recipe['source'] = g['source']
    if n is not None:
        recipe['len'] = n / fps
    rendered = graphics.render(recipe, doc.width, doc.height, fps, kit=doc.kit, out_dir=_graphics_dir(doc))
    if n is None:
        n = max(1, round(rendered['recipe']['len'] * fps))
    p = rendered['recipe']['params']
    label = p.get('title') or p.get('text') or p.get('value') or ''
    prod = build_producer(doc, {'clip': rendered['path'], 'name': f"{g['template']}: {label}".strip(': ')}, fps)
    view = base[2] if base else None
    _rebuild_filters(doc, prod, item, view if view and 'graphic' in view else None, 0, n - 1, n, fps,
                     old=base[1] if base else None)
    stored = {'template': g['template'], 'params': g.get('params') or {}, 'file': rendered['path']}
    if g['template'] == 'word_captions':
        stored['readable_word_hold'] = True
    if g.get('code'):
        stored['code'] = g['code']
    if g.get('source'):
        stored['source'] = g['source']
    _set(prod, GRAPHIC_PROP, json.dumps(stored, sort_keys=True))
    doc.root.insert(list(doc.root).index(doc.main), prod)
    doc.elements[prod.get('id')] = prod
    used[prod.get('id')] = True
    _set(prod, ID_PROP, iid or _new_id(doc, 'graphic-'))
    if 'name' in item:
        _set(prod, 'shotcut:caption', item['name'])
    plen = doc.f(_get(prod, 'length') or '0') or 0
    if rendered['animated'] and n > plen:
        raise ValueError(f'{iid}: graphic file has {plen} frames, needs {n}')
    entry = ET.Element('entry', {'producer': prod.get('id'), 'in': tm_clock(0, fps), 'out': tm_clock(n - 1, fps)})
    return entry, n


def _rebuild_filters(doc, prod, item, view, a, b, n, fps, old=None):
    src = old if old is not None else prod
    originals = _user_filters(src)
    kept = {}
    friendly_originals = []
    k = 0
    for f in originals:
        if describe_filter(f, fps, n, doc.width, doc.height, generic=False) is None:
            fp = _props(f)
            kept[f"{fp.get('shotcut:filter') or fp.get('mlt_service') or f.tag}#{k}"] = f
            k += 1
        friendly_originals.append((describe_filter(f, fps, n, doc.width, doc.height), f))
    patched = set()
    effects = list(item.get('effects', []))
    glyphs = item.get('graphic') or item.get('motion') or {}
    if glyphs.get('template') == 'word_captions' or glyphs.get('block') == 'kinetic_type':
        from letitedit.looks.kinetic_type import glyph_blend
        effects = [effect for effect in effects if not (isinstance(effect, dict) and effect.get('filter') == 'cairoblend_mode')]
        effects.extend(effect for effect in glyph_blend(glyphs.get('params') or {}) if effect not in effects)
    old_n = None
    if view is not None and 'in' in view:
        old_n = round((to_seconds(view['out']) - to_seconds(view['in'])) * fps / float(view.get('speed', 1.0)))
    new_filters = []
    for eff in effects:
        if isinstance(eff, dict) and 'cutaway_negative' in eff:
            pulse = eff['cutaway_negative']
            seconds = float(pulse.get('len', .1))
            edge = pulse.get('edge', 'in')
            if edge not in ('in', 'out') or not .03 <= seconds <= .2:
                raise ValueError('cutaway_negative needs edge in/out and len .03 to .2 seconds')
            count = min(n, max(1, round(seconds * fps)))
            start = a if edge == 'in' else b - count + 1
            effect = _filter('invert', {'letitedit:cutaway_negative': json.dumps(pulse)})
            effect.set('in', tm_clock(start, fps))
            effect.set('out', tm_clock(start + count - 1, fps))
            new_filters.append(effect)
            continue
        if isinstance(eff, dict) and 'keep' in eff and eff['keep'] not in kept and eff['keep'] in ('blur_pad', 'mute'):
            eff = eff['keep']   # {keep: blur_pad} means the effect itself
        if isinstance(eff, dict) and 'keep' in eff:
            if eff['keep'] not in kept:
                raise ValueError(f'{item.get("id")}: no original effect {eff["keep"]} to keep (kept effects here: '
                                 f'{", ".join(kept) or "none"}; friendly effects are written as themselves, e.g. blur_pad)')
            new_filters.append(copy.deepcopy(kept[eff['keep']]))
            continue
        match = next((f for d, f in friendly_originals if d == eff and id(f) not in patched), None)
        length_sensitive = isinstance(eff, dict) and any(x in eff for x in ('fade_out', 'fade_out_audio', 'blur_pad',
                                                                            'split_mute'))
        length_sensitive = length_sensitive or eff == 'blur_pad'
        # a blur pad is more than its one filter (hidden helpers grade and edge the sides, dropped below): it is always
        # rebuilt from its settings, or an unrelated change to the clip's effects would lose its grade and border
        rebuilt = eff == 'blur_pad' or (isinstance(eff, dict) and 'blur_pad' in eff)
        if match is not None and not rebuilt and not (length_sensitive and old_n != n):
            patched.add(id(match))
            new_filters.append(copy.deepcopy(match))
        elif isinstance(eff, dict) and 'filter' in eff:
            orig = next((f for d, f in friendly_originals if isinstance(d, dict) and d.get('filter') == eff['filter']
                         and id(f) not in patched), None)
            if orig is not None:
                patched.add(id(orig))
            new_filters.append(ee.build(eff, fps, original=orig))
        else:
            new_filters.extend(build_filter(eff, fps, n, doc.width, doc.height, kit=getattr(doc, 'kit', None)))
    # zoom/size must come before blur pad
    def rank(f):
        return 0 if _get(f, 'shotcut:filter') == 'affineSizePosition' else 1
    if any(_get(f, 'shotcut:filter') == 'blur_pad' for f in new_filters):
        new_filters.sort(key=rank)
    for f in [c for c in prod if c.tag in ('filter', 'link') and c in _user_filters(prod)]:
        prod.remove(f)
    _drop_parts(prod)
    for f in new_filters:
        if f.tag == 'link':
            prod.append(f)
            continue
        if not _get(f, 'letitedit:cutaway_negative'):
            f.set('in', tm_clock(a, fps))
            f.set('out', tm_clock(b, fps))
        if not f.get('id'):
            f.set('id', _new_id(doc, 'filter'))
        prod.append(f)


# ---------------------------------------------------------------------------- edits by id

def _place_at(script, op):
    """{op: insert, track, at, item} / {op: move, id, track?, at}: put an item on a track (not the main picture track)
    starting at a timeline time; the empty space around it adjusts and the track's other items keep their times."""
    from letitedit.timeline.edit_sync import layout, main_track, item_len
    at = to_seconds(op['at'])
    if op['op'] == 'move':
        t0, i0, item = _find(script, op['id'])
        i = i0
        t0['items'].pop(i0)
        # the space it leaves keeps the items after it where they were
        n = item_len(item)
        if i < len(t0['items']):
            t0['items'].insert(i, {'gap': n})
        name = op.get('track', t0['name'])
    else:
        item = dict(op['item'])
        item.setdefault('id', f'new-{uuid.uuid4().hex[:6]}')
        name = op['track']
    t = next((x for x in script['tracks'] if x['name'] == name), None)
    if t is None:
        raise KeyError(f"No track named {name}; tracks: {', '.join(x['name'] for x in script['tracks'])}")
    if t is main_track(script):
        raise ValueError('at: places items on other tracks; the main picture track is a sequence (use after/before)')
    n = item_len(item)
    # Times are kept to the millisecond, so items that touch can read a fraction of a frame apart. Less than half a
    # frame is not an overlap: both land on the same frame when compiled.
    touch = max(1e-4, 0.5 / float((script.get('profile') or {}).get('fps') or 30.0))
    busy = lambda x: next(((it, s, e) for it, s, e in layout(x) if s < at + n - touch and e > at + touch), None)
    if op.get('overlap') == 'next_track' and busy(t):
        # the next track of the same kind named like this one ('SFX 2', 'SFX 3'...), made after the last one if needed
        root = re.sub(r'\s+\d+$', '', name)
        family = [x for x in script['tracks'] if x.get('kind') == t.get('kind') and x is not main_track(script)
                  and re.fullmatch(re.escape(root) + r'(\s+\d+)?', x['name'])]
        free = next((x for x in family if not busy(x)), None)
        if free is None:
            k = 2
            while any(x['name'] == f'{root} {k}' for x in script['tracks']):
                k += 1
            free = {'name': f'{root} {k}', 'kind': t.get('kind', 'video'), 'items': []}
            script['tracks'].insert(script['tracks'].index(family[-1]) + 1, free)
        op['_result'] = f"{t['name']} was busy then, so it went on {free['name']}"
        t, name = free, free['name']
    spans = [(it, s, e) for it, s, e in layout(t)]
    clash = busy(t)
    if clash:
        free = [x['name'] for x in script['tracks'] if x is not t and x is not main_track(script)
                and x.get('kind') == t.get('kind')
                and not any(s < at + n - touch and e > at + touch for _, s, e in layout(x))]
        where = (f"free then: {', '.join(free)}" if free else
                 f"no other {t.get('kind', '')} track is free then ({{op: add_track}} makes one)")
        raise ValueError(f"{item.get('id')} at {clock(at)} for {n:.2f} s would overlap {clash[0].get('id')} "
                         f"({clock(clash[1])}-{clock(clash[2])}) on {name}; a track plays one item at a time, so "
                         f"pick another time or track ({where}), or overlap: next_track")
    pid = item['id']
    item['at'], item['pin'] = clock(at), True      # compiled to land on exactly that frame
    entries = sorted(spans + [(item, at, at + n)], key=lambda x: x[1])
    items, pos = [], 0.0
    for it, s, e in entries:
        if s > pos + 1e-4 and it is not item:
            items.append({'gap': round(s - pos, 4)})
        items.append(it)
        pos = e
    t['items'] = items
    op['_pinned'] = pid


def _find(script, iid):
    for t in script['tracks']:
        for i, it in enumerate(t['items']):
            if it.get('id') == iid:
                return t, i, it
    raise KeyError(f'No clip with id {iid}')


def _effects_many(script, op):
    """{op: effects, ids | id | track, effects | add}: one op for a set of items. `ids` (a list) and/or `id`, and/or
    `track` (a name or names: every clip of a file on it). `effects` replaces each item's effects; `add` adds to each
    one's own: {fix: ...} entries after its other fixes, the rest at the end."""
    ids = list(op.get('ids') or []) + ([op['id']] if op.get('id') else [])
    if op.get('track'):
        names = [op['track']] if isinstance(op['track'], str) else list(op['track'])
        known = {t['name'] for t in script['tracks']}
        missing = [n for n in names if n not in known]
        if missing:
            raise KeyError(f"No track named {', '.join(map(repr, missing))}")
        ids += [it['id'] for t in script['tracks'] if t['name'] in names for it in t['items']
                if it.get('id') and 'clip' in it]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError('effects names no items: give id, ids or track')
    if ('effects' in op) == ('add' in op):
        raise ValueError('effects takes either effects (replaces each item\'s effects) or add (adds to them)')
    for iid in ids:
        t, i, it = _find(script, iid)
        if 'effects' in op:
            it['effects'] = copy.deepcopy(op['effects'])
            continue
        effects = list(it.get('effects') or [])
        for e in op['add']:
            e = copy.deepcopy(e)
            if isinstance(e, dict) and 'fix' in e:
                effects.insert(sum(1 for x in effects if isinstance(x, dict) and 'fix' in x), e)
            else:
                effects.append(e)
        it['effects'] = effects
    op['_result'] = f'{len(ids)} items'


def _place_words(item, op, fps=30.0):
    """An item given as {clip, words: "the phrase"}: in/out on the gaps around where that phrase is said."""
    import letitedit.timeline.cutpoints as cutpoints
    found = cutpoints.find(item['clip'], item['words'], near=item.get('near'))
    note = f"\"{found['said']}\" at {clock(found['in'])}-{clock(found['out'])} in {os.path.basename(item['clip'])}"
    if found['match'] < 1:
        note += f" (closest match to \"{item['words']}\")"
    if found['others']:
        note += f"; also said at {', '.join(clock(x) for x in found['others'])} (near: seconds picks one)"
    op['_result'] = note
    for k in ('words', 'near'):
        item.pop(k, None)
    fps = float(fps)   # whole frames, rounded outwards so the cut never lands inside the phrase
    item['in'] = _r(math.floor(found['in'] * fps + 1e-6) / fps)
    item['out'] = _r(math.ceil(found['out'] * fps - 1e-6) / fps)
    return item


ANIMATED_CAPTION_KEYS = ('font', 'weight', 'size', 'fill', 'highlight', 'outline', 'outline_width', 'shadow', 'position', 'margin_y',
                         'max_width', 'center_x', 'uppercase', 'box', 'pop_scale', 'shrink_to_fit')


def _picture_widths(script):
    """f(t) -> share of the frame width the main track's picture covers at timeline time t (1.0 = full width)."""
    from letitedit.timeline.edit_sync import layout, main_track
    prof = script.get('profile') or {}
    fw, fh = float(prof.get('width', 1920)), float(prof.get('height', 1080))
    spans = []
    try:
        import letitedit.server.core_tools as core_tools
        for it, s, e in layout(main_track(script)):
            frac = 1.0
            src = it.get('clip') or (it.get('graphic') or {}).get('source', {}).get('clip')
            fills = any(isinstance(x, dict) and ('zoom' in x or 'size_position' in x) for x in it.get('effects', []))
            if src and not fills and not (it.get('graphic') or {}).get('source', {}).get('fit') == 'cover':
                info = core_tools.probe(src)
                w, h = float(info.get('width') or 0), float(info.get('height') or 0)
                if w and h and w / h < fw / fh:
                    frac = (w / h) * (fh / fw)
            spans.append((s, e, frac))
    except Exception:  # noqa: BLE001 - unknown sizes: captions use the full width
        return None
    return lambda t: next((f for s, e, f in spans if s <= t < e), 1.0)


def _animated_captions(script, op):
    """Captions as a video track of word-by-word graphics (one per cue), following the words as they are said."""
    animate = op.get('animate') or 'plain'
    style = animate if isinstance(animate, str) else (animate or {}).get('style', 'pop')
    look = dict(op.get('style') or {})
    if isinstance(look.get('outline'), dict):
        look['outline_width'] = look['outline'].get('width', 7)
        look['outline'] = look['outline'].get('color')
    elif isinstance(look.get('outline'), (int, float)) and not isinstance(look['outline'], bool):
        look['outline_width'] = look.pop('outline')    # a number is a thickness, as in a plain caption's style
    params_base = {k: look[k] for k in ANIMATED_CAPTION_KEYS if k in look}
    for key in ('blend', 'protected'):
        if key in look:
            params_base[key] = look[key]
    if look.get('blend', 'normal') != 'normal':
        from letitedit.looks.kinetic_type import glyph_blend
        glyph_blend(params_base)
    under = _picture_widths(script)          # share of the frame width the footage covers, by time
    picture = under if 'max_width' not in params_base else None
    name = op['track']
    track = next((t for t in script['tracks'] if t['name'] == name), None)
    if track is None:
        track = {'name': name, 'kind': 'video', 'items': []}
        script['tracks'].append(track)
    elif track.get('kind') != 'video':
        raise ValueError(f'{name} is an audio track; animated captions need a video track name')
    cues = sorted(op.get('cues') or [], key=lambda c: to_seconds(c['start']))
    items, pos = [], 0.0
    for k, cue in enumerate(cues):
        a, b = to_seconds(cue['start']), to_seconds(cue['end'])
        if b - a < 0.2:
            continue
        if a > pos + 1e-3:
            items.append({'gap': round(a - pos, 4)})
        words = cue.get('words')
        if not words:
            toks = cue['text'].split()
            step = (b - a) / max(1, len(toks))
            words = [[w, a + i * step, a + (i + 1) * step] for i, w in enumerate(toks)]
        params = {**params_base, 'style': style,
                  'words': [[w, round(max(0.0, t0 - a), 3), round(max(0.0, t1 - a), 3)] for w, t0, t1 in words]}
        if params.get('protected'):
            params['protected'] = [dict(region, start=float(region.get('start', 0)) - a,
                                        end=float(region.get('end', b)) - a) for region in params['protected']]
        if picture:
            frac = picture((a + b) / 2)
            if frac < 0.9:   # the picture under this caption is narrower than the frame (vertical footage)
                params['max_width'] = round(frac * 0.92, 3)
        items.append({'id': f'{_slug(name)}-{k + 1:03d}', 'graphic': {'template': 'word_captions', 'params': params},
                      'len': round(b - a, 4)})
        pos = b
    track['items'] = items
    script['captions'] = [c for c in script.get('captions', []) if c['track'] != name]
    op['_result'] = f'{len([i for i in items if "graphic" in i])} animated captions ({style}) on track {name}'
    fracs = [under((to_seconds(c['start']) + to_seconds(c['end'])) / 2) for c in cues] if under and cues else []
    narrow = [f for f in fracs if f < 0.9]
    if narrow:
        frac = min(narrow)
        widths = sorted({round(float(i['graphic']['params'].get('max_width', 0.82)), 2) for i in items if 'graphic' in i})
        cx = float(params_base.get('center_x', 0.5))
        op['_result'] += (f"; lines up to {'/'.join(f'{w:.0%}' for w in widths)} of the frame width, centred at {cx:.2f}; "
                          f"the footage under {len(narrow)} of {len(fracs)} captions covers {frac:.0%} of the width "
                          f"({(1 - frac) / 2:.2f}-{(1 + frac) / 2:.2f})")


def _unsure_words(script, op, fix=None, limit=20):
    """'; N words the transcriber wasn't sure of: "Spree" 1:04.2, ...' for captions made from speech ('' when none);
    words the spelling fixes (`fix`: the op's own and the style's, else the op's) already rewrite are left out."""
    try:
        import letitedit.footage.speech as speech
        from letitedit.timeline.timeline_speech import timeline_words
        fixed = {w.lower().strip('.,?!') for k in (fix if fix is not None else op.get('fix') or {})
                 for w in str(k).split()}
        uns = [w for w in timeline_words(script) if speech.unsure(w) and w['w'].strip().strip('.,?!').lower() not in fixed]
    except Exception:  # noqa: BLE001 - a note, never a reason to fail
        return ''
    if not uns:
        return ''
    shown = ', '.join(f'"{w["w"].strip()}" {clock(w["t0"])}' for w in uns[:limit])
    return f"; {len(uns)} words the transcriber wasn't sure of: {shown}" + (', ...' if len(uns) > limit else '')


def _len_or_none(it):
    from letitedit.timeline.edit_sync import item_len
    try:
        return item_len(it)
    except Exception:  # noqa: BLE001 - a made clip whose length isn't known yet
        return None


def _keep_later_in_place(script, t, i, before):
    """After an item on a track other than the main picture track got shorter or longer, the space after it takes
    up the difference, so the items after it keep their times (as on a timeline, where trimming one title doesn't
    move the next). A longer item eats into the space after it; with no space left, later items move."""
    from letitedit.timeline.edit_sync import main_track
    if before is None or t is main_track(script):
        return
    after = _len_or_none(t['items'][i])
    if after is None or abs(after - before) < 1e-6 or i + 1 >= len(t['items']):
        return
    delta = before - after
    nxt = t['items'][i + 1]
    if 'gap' in nxt:
        g = to_seconds(nxt['gap']) + delta
        if g > 1e-6:
            nxt['gap'] = round(g, 4)
        else:
            t['items'].pop(i + 1)
    elif delta > 1e-6:
        t['items'].insert(i + 1, {'gap': round(delta, 4)})


def _edge_fps(script, item):
    """The frame rate a clip's clean edges are found on, or None (the
    switch off, or a clip not played at normal speed forwards)."""
    import letitedit.timeline.cutpoints as cutpoints
    if not cutpoints.quiet_frame() or item.get('reverse') or float(item.get('speed', 1.0) or 1.0) != 1.0:
        return None
    try:
        return float(((script or {}).get('profile') or {}).get('fps') or 0) or None
    except (TypeError, ValueError):
        return None


def _guard_spoken_edges(item, change, exact=False, fps=None):
    """Move numeric source edges out of a spoken word or sound when a cached transcript supports it.

    cutpoints.clean_edge measures each edge with the review's own rules and moves it to the nearest clean place:
    the rest of a clipped word kept, or the clipped part dropped; a word's tail or soft opening kept; a pause; and,
    where the sound runs on, the quietest moment between two words (never more than EDGE_REACH_OUT_S outward or
    EDGE_REACH_IN_S inward). Exact mode keeps a deliberate frame-accurate cut and only notes an edge the review
    will flag, with the nearest clean place. Returns plain notes on what moved and what could not be made clean.
    fps (_edge_fps): edges are measured on the frame the engine cuts at, and moved to a whole frame.
    """
    notes = []
    exact = exact or change.get('edge_mode') == 'exact'
    if not item.get('clip'):
        return notes
    path = Path(item['clip'])
    if not path.is_file():
        return notes
    import letitedit.footage.speech as speech
    import letitedit.timeline.cutpoints as cutpoints
    for key, side in (('in', 'in'), ('out', 'out')):
        if key not in change:
            continue
        at = to_seconds(change[key])
        if at <= 0:
            continue
        words = speech.cached_words(str(path), at - .5, at + .5)
        if words:
            import letitedit.footage.word_reheard as word_reheard
            words = word_reheard.overlay(str(path), words, at - .5, at + .5)    # what's already been heard
        if not words:            # not transcribed yet, or no words near: nothing to measure the edge against
            continue
        edge = cutpoints.clean_edge(str(path), at, side, ws=words, fps=fps)
        if exact:                # kept as given; still say what the review will measure there
            if edge.get('problem'):
                better = (f"; the nearest clean place is {clock(edge['at'])} ({edge['at'] - at:+.2f} s), {edge['how']}"
                          if edge['clean'] or edge.get('between_words') else '')
                notes.append(f"{key} {clock(at)} kept as given (edge_mode: exact), but it goes through a "
                             f"{edge['problem']}: the review will flag it{better}")
            continue
        if abs(edge.get('moved', edge['at'] - at)) > .005 and (edge['clean'] or edge.get('between_words')):
            change[key] = edge['at']
            notes.append(f"{key} {clock(at)} went through a {edge.get('problem') or 'sound'}: moved to {clock(edge['at'])} "
                         f"({edge['at'] - at:+.2f} s), {edge['how']}")
        elif not edge['clean'] and edge.get('problem'):
            notes.append(f"{key} {clock(at)} goes through a {edge['problem']} and no clean place is within "
                         f"{cutpoints.EDGE_REACH_IN_S:g}-{cutpoints.EDGE_REACH_OUT_S:g} s: left as given; {edge['how']}")
    return notes


def _edge_notes(op, notes):
    if notes:
        op['_result'] = (op['_result'] + '; ' if op.get('_result') else '') + 'clean cut: ' + '; '.join(notes)


def _apply_captions(script, op):
    """Apply one caption operation, keeping its cues, style and result notes together."""
    fix = None
    if op.get('from_speech'):
        from letitedit.timeline.timeline_speech import caption_fixes, captions_from_speech, style_fixes
        kit = kit_for(script)
        cap_kit = kit['captions']      # the style's line length when the op doesn't say
        # the style's spelling list (captions.corrections, e.g. from My style) unless style_fix: false; the
        # op's own fix wins on the same words
        use_style = op.get('style_fix', True) is not False
        fix, counts = caption_fixes(kit, op.get('fix'), use_style), {}
        op['cues'] = captions_from_speech(script, chunk=op.get('chunk', 'short' if op.get('animate') else 'sentence'),
                                          max_chars=int(op.get('max_chars', cap_kit.get('max_chars') or 42)),
                                          max_lines=int(op.get('max_lines', cap_kit.get('max_lines') or 2)),
                                          with_words=bool(op.get('animate')), fix=fix,
                                          fillers=bool(op.get('fillers', False)), counts=counts)
        op['_result'] = f"{len(op['cues'])} captions from what is said on the timeline"
        own = {str(v) for v in (op.get('fix') or {}).values()}
        styled = {str(v) for v in style_fixes(kit).values()} - own if use_style else set()
        done = [f'"{w}" x{n}' for w, n in counts.items() if w in styled]
        if done:
            op['_result'] += (f"; spelled the Look's way ({kit.source}'s captions.corrections): "
                              + ', '.join(done) + ' (style_fix: false leaves them out)')
    if ('cues' in op and not op.get('from_speech') and op.get('align', True) is not False
            and not str(op.get('note', '')).startswith('letitedit_caption_fit')):
        from letitedit.timeline.timeline_speech import align_cues_to_words
        op['cues'], aligned = align_cues_to_words(script, op['cues'])
        if aligned['moved']:
            op['_result'] = (op.get('_result', '') + '; ' if op.get('_result') else '') +                         (f"{aligned['moved']} of {len(op['cues'])} cues moved to their words' times on the timeline "
                 f"(largest move {aligned['largest_move_s']:g} s; align: false keeps given times)")
    if 'cues' in op and not str(op.get('note', '')).startswith('letitedit_caption_fit'):
        from letitedit.timeline.timeline_speech import tidy_caption_cues
        original = op['cues']
        op['cues'] = tidy_caption_cues(original, max_chars=int(op.get('max_chars', 42)),
                                       max_lines=int(op.get('max_lines', 2)))
        if op['cues'] != original:
            op['_result'] = (op.get('_result', '') + '; ' if op.get('_result') else '') + \
                            'repaired phrase endings and reading time'
    unsure_note = _unsure_words(script, op, fix) if op.get('from_speech') else ''
    if op.get('animate') or (op.get('style') or {}).get('blend', 'normal') != 'normal':
        _animated_captions(script, op)
        op['_result'] = op.get('_result', '') + unsure_note
        return
    if unsure_note:
        op['_result'] = op.get('_result', '') + unsure_note
    caps = script.setdefault('captions', [])
    existing = next((c for c in caps if c['track'] == op['track']), None)
    style = None
    if op.get('style'):
        prof = script.get('profile') or {}
        style = friendly_text_style(op['style'], kit_for(script), prof.get('width', 1920), prof.get('height', 1080))
    if existing:
        if 'cues' in op:
            existing['cues'] = op['cues']
        if style:
            merged = {**(existing.get('style') or {}), **style}
            if merged.get('shadow') is None:
                merged.pop('shadow', None)
            existing['style'] = merged
    else:
        caps.append({'track': op['track'], 'cues': op.get('cues', []), 'style': style,
                     'burn_in': op.get('burn_in', True)})


def apply_ops(script, ops):
    """Mutate a full script with small edits. Ops:
    trim {id, in?, out?} | delete {id, close_gap=True} | insert {track, after?|before?|at_start?, item}
    move {id, track?, after?|before?} | set {id, ...fields} | effects {id, effects} | gap {id, before|after: seconds}
    captions {track, cues} | add_track {name, kind}."""
    for op in ops:
        kind = op['op']
        if kind in ('fx', 'popups') and 'pack' in op:
            raise ValueError('pack selection was removed; look selects Look defaults')
        if kind == 'insert' and isinstance(op.get('item'), dict) and op['item'].get('words') and op['item'].get('clip'):
            op['item'] = _place_words(dict(op['item']), op, (script.get('profile') or {}).get('fps', 30))
        if kind == 'trim' and op.get('words'):
            t, i, it = _find(script, op['id'])
            if 'clip' not in it:
                raise ValueError(f"{op['id']}: words works on clips of video or sound files")
            placed = _place_words({'clip': it['clip'], 'words': op['words'], 'near': op.get('near')}, op,
                                  (script.get('profile') or {}).get('fps', 30))
            op = {**op, 'in': placed['in'], 'out': placed['out']}
        if kind == 'trim':
            t, i, it = _find(script, op['id'])
            before = _len_or_none(it)
            if it.get('adjust'):         # a block has no source: in and out count from its own start
                a = to_seconds(op.get('in', 0))
                it['len'] = round(to_seconds(op.get('out', it.get('len', 0))) - a, 4)
                if it['len'] <= 0:
                    raise ValueError(f"{op['id']}: out must be after in")
                _keep_later_in_place(script, t, i, before)
                continue
            if 'scene' in it:            # in and out count in the scene's own time
                a = to_seconds(op.get('in', it.get('in') or 0))
                b = to_seconds(op.get('out', to_seconds(it.get('in') or 0) + to_seconds(it.get('len', 0))))
                if b <= a or a < 0:
                    raise ValueError(f"{op['id']}: out must be after in")
                it['len'] = round(b - a, 4)
                if a:
                    it['in'] = round(a, 4)
                else:
                    it.pop('in', None)
                _keep_later_in_place(script, t, i, before)
                continue
            if not op.get('words'):
                _edge_notes(op, _guard_spoken_edges(it, op, fps=_edge_fps(script, {**it, **op})))
            if 'in' in op:
                it['in'] = to_seconds(op['in'])
            if 'out' in op:
                it['out'] = to_seconds(op['out'])
            _keep_later_in_place(script, t, i, before)
        elif kind == 'delete':
            # on the main picture track the gap closes by default; on other tracks the items after it keep their times
            t, i, it = _find(script, op['id'])
            t['items'].pop(i)
            from letitedit.timeline.edit_sync import main_track
            if not op.get('close_gap', t is main_track(script)):
                t['items'].insert(i, {'gap': it.get('len', 0)})
        elif kind in ('insert', 'move') and op.get('at') is not None:
            _place_at(script, op)
        elif kind in ('insert', 'move'):
            if kind == 'move':
                t0, i0, item = _find(script, op['id'])
                t0['items'].pop(i0)
                if op.get('leave_gap'):
                    t0['items'].insert(i0, {'gap': item.get('len', 0)})
                target = next(t for t in script['tracks'] if t['name'] == op.get('track', t0['name']))
            else:
                item = dict(op['item'])
                if 'clip' in item and not item.get('words'):
                    _edge_notes(op, _guard_spoken_edges(item, item, exact=op.get('edge_mode') == 'exact',
                                                        fps=_edge_fps(script, item)))
                item.setdefault('id', f'new-{uuid.uuid4().hex[:6]}')
                target = next((t for t in script['tracks'] if t['name'] == op['track']), None)
                if target is None:
                    raise KeyError(f"No track named {op['track']}; tracks: {', '.join(x['name'] for x in script['tracks'])}")
            if op.get('after'):
                _, j, _ = _find(script, op['after'])
                target['items'].insert(j + 1, item)
            elif op.get('before'):
                _, j, _ = _find(script, op['before'])
                target['items'].insert(j, item)
            elif op.get('at_start'):
                target['items'].insert(0, item)
            else:
                target['items'].append(item)
        elif kind == 'set':
            t, i, it = _find(script, op['id'])
            before = _len_or_none(it)
            edge_notes = []
            if 'clip' in it and ('in' in op or 'out' in op):      # a clip's edges set by hand get the same clean-cut rule
                edge = {k: op[k] for k in ('in', 'out', 'edge_mode') if k in op}
                edge_notes = _guard_spoken_edges(it, edge, fps=_edge_fps(script, {**it, **op}))
                for k in ('in', 'out'):
                    if k in edge:
                        op[k] = edge[k]
            for k, v in op.items():
                if k not in ('op', 'id', '_result', 'edge_mode', 'edge_reason'):
                    if k == 'vfx' and isinstance(v, dict) and 'effect' not in v and isinstance(it.get('vfx'), dict):
                        v = {**it['vfx'], **v}     # a new source or params for the effect already there
                    if k == 'len' and v is not None and 'out' in it and 'out' not in op:
                        # an item with in/out (a read-back colour or a clip): len sets where it ends
                        it['out'] = _r(to_seconds(it.get('in', 0)) + to_seconds(v) * float(it.get('speed', 1.0)))
                        it[k] = v
                    elif v is None:
                        it.pop(k, None)
                    elif k == 'graphic' and isinstance(v, dict) and 'graphic' in it:
                        merged = {**it['graphic'], **{kk: vv for kk, vv in v.items() if kk != 'params'}}
                        merged['params'] = {**(it['graphic'].get('params') or {}), **(v.get('params') or {})}
                        it['graphic'] = merged
                    else:
                        it[k] = v
            _edge_notes(op, edge_notes)
            _keep_later_in_place(script, t, i, before)
        elif kind == 'effects':
            if 'id' in op and 'effects' in op and not ('ids' in op or 'track' in op or 'add' in op):
                t, i, it = _find(script, op['id'])
                it['effects'] = op['effects']
            else:
                _effects_many(script, op)
        elif kind == 'gap':
            # sets the empty space right before/after an item (replacing what is there); later items move with it
            t, i, it = _find(script, op['id'])
            items = t['items']
            if 'after' in op:
                j = i + 1
                while j < len(items) and 'gap' in items[j]:
                    items.pop(j)
                if to_seconds(op['after']) > 0:
                    items.insert(j, {'gap': to_seconds(op['after'])})
            if 'before' in op:
                j = i
                while j > 0 and 'gap' in items[j - 1]:
                    items.pop(j - 1)
                    j -= 1
                if to_seconds(op['before']) > 0:
                    items.insert(j, {'gap': to_seconds(op['before'])})
        elif kind == 'captions':
            _apply_captions(script, op)
        elif kind == 'look':
            from letitedit.looks import look_library
            identity = op.get('id') or 'neutral'
            if identity != 'neutral':
                look_library.read(identity)
                if look_library.project_identity(script) != identity and not identity.startswith('mine-custom-'):
                    look_library.require_offered(identity)
            script['look'] = identity
            script.pop('style', None)
        elif kind == 'track':
            t = next((x for x in script['tracks'] if x['name'] == op['name']), None)
            if t is None:
                raise ValueError(f"No track named {op['name']!r}")
            for k in ('gain', 'duck', 'hide', 'effects'):
                if k in op:
                    if op[k] is None or op[k] is False:
                        t.pop(k, None)
                    else:
                        t[k] = op[k]
        elif kind == 'master':
            if op.get('effects'):
                script['master'] = op['effects']
            else:
                script.pop('master', None)
        elif kind == 'aim':
            import letitedit.timeline.aim as aim
            aim.apply_op(script, op)
        elif kind == 'adjust':
            adjust.apply_op(script, op)
        elif kind == 'lift':
            import letitedit.pictures.object_lift as object_lift
            object_lift.apply_op(script, op)
        elif kind == 'add_track':
            new_track = {'name': op['name'], 'kind': op.get('kind', 'video'), 'items': []}
            if op.get('after'):
                index = next((i for i, t in enumerate(script['tracks']) if t['name'] == op['after']), None)
                if index is None:
                    raise ValueError(f"No track named {op['after']!r}")
                script['tracks'].insert(index + 1, new_track)
            else:
                script['tracks'].append(new_track)
        elif kind == 'tighten':
            from letitedit.timeline.edit_sync import tighten
            tighten(script, op)
        elif kind == 'score':
            import letitedit.sound.music as music
            music.score(script, op)
        elif kind == 'level':
            import letitedit.sound.music as music
            op['_result'] = music.level_voice(script, op, exclude={t['name'] for t in music.music_tracks(script)})
        elif kind == 'split_edit':
            import letitedit.timeline.split_edit as split_edit
            split_edit.apply_op(script, op)
        elif kind == 'multicam':
            import letitedit.timeline.multicam as multicam
            multicam.apply_op(script, op)
        elif kind == 'declick':
            import letitedit.timeline.declick as declick
            declick.apply_op(script, op)
        elif kind == 'popups':
            import letitedit.looks.popups as popups
            popups.apply_op(script, op)
        elif kind == 'fx':
            import letitedit.looks.fx as fx
            fx.apply_op(script, op)
        elif kind == 'hook':
            import letitedit.footage.hooks as hooks
            hooks.apply_op(script, op)
        else:
            messages = {'style': 'The style op was removed; use {op: look, id} to select a Look'}
            raise ValueError(messages.get(kind, f'Unknown op {kind}'))
    return script


# ops that read the finished timeline (what is said where, the final picture timing) run after the others
LATE_OPS = ('score', 'level', 'declick', 'popups')
SPLIT_OPS = ('split_edit',)


def edit(before, ops):
    """Apply edits by id to a copy of the script `before`: ops in order, then (when the main picture track changed)
    other tracks and captions move with their picture, then split edits (J/L cuts) are made and every split edit is
    rebuilt for the new timing (split_edit.refresh), then ops that read the finished timeline (score, captions from
    speech). Returns (after, notes)."""
    from letitedit.timeline.edit_sync import main_track, resync
    import letitedit.timeline.op_specs as op_specs
    import letitedit.timeline.split_edit as split_edit
    op_specs.check(ops)
    is_late = lambda o: o.get('op') in LATE_OPS or (o.get('op') == 'captions' and o.get('from_speech'))
    is_split = lambda o: o.get('op') in SPLIT_OPS
    early = [o for o in ops if not is_late(o) and not is_split(o)]
    splits = [o for o in ops if is_split(o)]
    late = [o for o in ops if is_late(o)]
    after = apply_ops(copy.deepcopy(before), early)
    notes = []
    main_b, main_a = main_track(before), main_track(after)
    sig = lambda t: [(x.get('clip'), x.get('in'), x.get('out'), x.get('speed'), x.get('gap'), x.get('len'),
                      str(x.get('transition'))) for x in t['items']] if t else []
    if sig(main_b) != sig(main_a) and not any(o.get('ripple') is False for o in early):
        touched = {o.get('id') for o in early if o.get('track') not in (None, (main_a or {}).get('name'))}
        touched |= {(o.get('item') or {}).get('id') for o in early if o.get('track') != (main_a or {}).get('name')}
        touched.discard(None)
        pinned = set()
        for o in early:          # items placed at a time keep it (an op that places several pins a list)
            p = o.get('_pinned')
            pinned |= set(p) if isinstance(p, (list, tuple, set)) else ({p} if p else set())
        import letitedit.sound.guide_song as guide_song       # T72: a phone app plays the song straight through, so it stays put when the picture moves
        pinned |= {i.get('id') for x in after['tracks'] if guide_song.is_guide_name(x.get('name')) for i in x['items']}
        notes += resync(before, after, touched=touched, pinned=pinned)
        import letitedit.timeline.multicam as multicam         # angle clips go back on the moment of the talk they show
        notes += multicam.refresh(after, skip=pinned, before=before)
    # split edits after the picture moved (a move: picture roll keeps every other track's timing, so no resync)
    if splits:
        apply_ops(after, splits)
    notes += split_edit.refresh(after)
    if late:
        apply_ops(after, late)
        notes += split_edit.refresh(after)      # moved sound follows its clip's new speech level
    import letitedit.pictures.object_lift as object_lift
    if not any(o.get('op') == 'lift' for o in ops):
        notes += object_lift.follow(after)
    notes += object_lift.uncovered(after)
    from letitedit.looks import caption_timing, sound_targets
    notes += caption_timing.follow_words(before, after)
    notes += sound_targets.follow_captions(before, after)
    for o in ops:
        if '_result' in o:
            notes.append(f"{o['op']} {o.get('id') or ''}: {o['_result']}".replace(' :', ':'))
    return after, notes


def apply_changes(project, ops=None, script=None, keep_history=True, force=False, actor=None, label=None,
                  lease_s=None, wait_s=None, journal=True):
    """Apply a full script or edits-by-id to a saved project. Keeps a history copy for undo.
    When edits change the main picture track, the other tracks and captions follow their picture (resync).
    The write holds the project's edit lease for `actor` (project_journal.take: refused while another actor's lease
    is unexpired after wait_s; the lease then runs lease_s more seconds), refuses changes to tracks owned by another
    actor, and adds a journal entry.
    Returns {'project', 'history', 'changes', 'notes', 'lease'}."""
    import letitedit.timeline.project_journal as pj
    path = _resolve(project)
    who = pj.actor(actor)
    requests = pj.owner_requests(ops) if script is None else []
    import letitedit.looks.project_look as project_look
    with pj.writing(path, who, lease_s, wait_s) as lease:
        before = read(path)
        if journal:
            project_look.note_hand_edits(path, script=before)     # the person's own edits since the AI's last
        notes, frames_at = [], None
        if script is None:
            ops = [dict(o) for o in (ops or [])]
            script, notes = edit(before, ops)
            script['base'] = before['base']
        else:
            import letitedit.timeline.split_edit as split_edit
            notes = split_edit.refresh(script)      # a whole script sent back: its split edits follow its picture
            from letitedit.looks import caption_timing, sound_targets
            notes += caption_timing.follow_words(before, script)
            notes += sound_targets.follow_captions(before, script)
        pj.check(path, who, before, script, requests)
        hist = None
        if keep_history:
            hist = _new_history_file(path, before['base'])
            shutil.copy2(path, hist)
        frames_at = script.pop('_frames_at', None)
        compile_script(script, base=path, out=path, force=force)
        notes = list(notes) + script.pop('_render_notes', [])
        pj.save_requests(path, who, requests)
        after = read(path)
        changes = diff(before, after)
    if journal:
        pj.record(path, 'apply', who, label, changes, history=str(hist) if hist else None, hand_checked=True)
        project_look.remember(path)           # the timeline as this edit left it: the next check compares with it
    out = {'project': str(path), 'history': str(hist) if hist else None, 'changes': changes, 'notes': notes,
           'lease': lease}
    if frames_at:
        out['frames_at'] = sorted(set(frames_at))
    return out


def _stamp():
    """Sortable time to the microsecond (several applies can land in one second)."""
    import datetime
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')


def _legacy_history_dir(path):
    """Where history was kept before it moved beside the project (still read; nothing there is moved)."""
    key = hashlib.sha256(str(Path(path).resolve()).lower().encode()).hexdigest()[:12]
    return HISTORY / f'{Path(path).stem[:40]}-{key}'


def _history_dir(path):
    """The project's own history folder: <project folder>/<stem>.letitedit/history."""
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(path).resolve()) / 'history'


def _history_dirs(path):
    """Every folder holding history copies of this project, new place first."""
    return [_history_dir(path), _legacy_history_dir(path)]


def _new_history_file(path, base):
    """A new history copy's path: in the project's folder, or the cache when that folder can't be written."""
    name = f'{_stamp()}-{base}.mlt'
    import letitedit.core.long_paths as long_paths
    for d in _history_dirs(path):
        if long_paths.too_long(d / name):
            continue                    # beside a project this deep the copy can't be written: the cache takes it
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d / name
        except OSError:
            continue
    raise OSError(f'No writable history folder for {path}')


def _history_files(path):
    """History copies from both places, newest first (names start with a sortable time)."""
    files = [f for d in _history_dirs(path) if d.is_dir() for f in d.glob('*.mlt')]
    return sorted(files, key=lambda f: f.name, reverse=True)


def history(project, limit=20):
    path = _resolve(project)
    return [str(f) for f in _history_files(path)[:limit]]


def undo(project, actor=None, lease_s=None, wait_s=None, journal=True):
    """Restore the most recent history copy (the current file is itself saved to history first).
    Holds the edit lease like apply_changes and adds a journal entry."""
    import letitedit.timeline.project_journal as pj
    path = _resolve(project)
    who = pj.actor(actor)
    files = _history_files(path)
    if not files:
        raise ValueError('No history for this project')
    with pj.writing(path, who, lease_s, wait_s) as lease:
        files = _history_files(path)
        if not files:
            raise ValueError('No history for this project')
        last = files[0]
        current = read(path)
        pj.check(path, who, current, read(last))   # an undo that changes another actor's track is refused too
        # the state being undone is kept apart from the history, so the next undo goes further back instead of returning here
        redo = _history_dir(path) / 'undone'
        try:
            redo.mkdir(parents=True, exist_ok=True)
        except OSError:
            redo = _legacy_history_dir(path) / 'undone'
            redo.mkdir(parents=True, exist_ok=True)
        keep = redo / f'{_stamp()}-{current["base"]}.mlt'
        shutil.copy2(path, keep)
        shutil.copy2(last, path)
        last.unlink()
        changes = diff(current, read(path))
    if journal:
        pj.record(path, 'undo', who, f'undo to {last.name}', changes, restored=str(last))
        import letitedit.looks.project_look as project_look
        project_look.remember(path)           # an undo is the AI's own change, not the person's
    return {'restored': str(last), 'saved_current_as': str(keep), 'changes': changes, 'lease': lease}
