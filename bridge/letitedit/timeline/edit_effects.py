"""Any engine effect in the edit script, with keyframes.

    {filter: NAME, params: {prop: value | {keys: [[t, v], [t, v, ease], ...]}}}

NAME is a Shotcut filter (vignette, glow, hue_lightness_saturation, audio_compressor...) or any MLT service
(frei0r.glow, avfilter.eq...); effects_catalog resolves it. Keyframe times are seconds from the start of the clip (or
of the timeline, for track and master effects); ease is how the value moves on to the next key (linear by default).

Reading shows every filter the script has no friendlier word for in this form, so nothing is hidden behind {keep}.
"""
from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET

import letitedit.timeline.timeline_model as tm

EASE = {'linear': '', 'hold': '|', 'smooth': '~', 'smooth_natural': '$', 'smooth_tight': '-',
        'sine_in': 'a', 'sine_out': 'b', 'sine_in_out': 'c', 'quad_in': 'd', 'quad_out': 'e', 'quad_in_out': 'f',
        'cubic_in': 'g', 'cubic_out': 'h', 'cubic_in_out': 'i', 'quart_in': 'j', 'quart_out': 'k', 'quart_in_out': 'l',
        'quint_in': 'm', 'quint_out': 'n', 'quint_in_out': 'o', 'expo_in': 'p', 'expo_out': 'q', 'expo_in_out': 'r',
        'circ_in': 's', 'circ_out': 't', 'circ_in_out': 'u', 'back_in': 'v', 'back_out': 'w', 'back_in_out': 'x',
        'elastic_in': 'y', 'elastic_out': 'z', 'elastic_in_out': 'A', 'bounce_in': 'B', 'bounce_out': 'C',
        'bounce_in_out': 'D'}
ALIASES = {'ease_in': 'cubic_in', 'ease_out': 'cubic_out', 'ease_in_out': 'cubic_in_out', 'ease': 'cubic_in_out',
           'step': 'hold', 'discrete': 'hold', 'none': 'linear'}
CHAR_EASE = {v: k for k, v in EASE.items() if v}
# properties that are bookkeeping, not settings: not shown, kept when a filter is changed
HIDDEN = {'mlt_service', 'shotcut:filter', 'shotcut:hash', 'version', 'threads', 'letitedit_ai:role'}
AIM_TAG = 'letitedit_ai:aim'     # an effect placed by {op: aim} (aim.py): its time range follows the picture
_KEY = re.compile(r'^\s*(\d+:\d+:\d+(?:\.\d+)?)([|~$\-a-zA-D]?)=(.*)$')


def _clock(frames, fps):
    return tm.frames_to_clock(frames, fps)      # as the engine writes it, so it reads back as the same frame


def ease_char(name):
    if not name:
        return ''
    n = str(name).lower().replace('-', '_').replace(' ', '_')
    n = ALIASES.get(n, n)
    if n not in EASE:
        raise ValueError(f'unknown ease {name!r}: use linear, hold, smooth, ease_in, ease_out, ease_in_out, or '
                         f'{", ".join(k for k in EASE if k not in ("linear", "hold", "smooth"))}')
    return EASE[n]


def _num(text):
    """'0.5' -> 0.5, '3' -> 3, anything else unchanged."""
    if isinstance(text, str) and re.fullmatch(r'-?\d+', text.strip()):
        return int(text)
    if isinstance(text, str) and re.fullmatch(r'-?(\d+\.\d*|\.\d+)', text.strip()):
        return float(text)
    return text


def fmt(v):
    """A script value as an MLT property string."""
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, float):
        return f'{v:.6f}'.rstrip('0').rstrip('.') if not v.is_integer() else str(int(v))
    if isinstance(v, (list, tuple)):
        return ' '.join(fmt(x) for x in v)
    return str(v)


def anim(keys, fps):
    """[[t, v], [t, v, ease], ...] -> '00:00:00.000=v;00:00:01.000e=v2' (times in seconds from the filter's start)."""
    out = []
    for k in keys:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            raise ValueError(f'a keyframe is [seconds, value] or [seconds, value, ease], not {k!r}')
        t, v = float(k[0]), k[1]
        out.append(f'{_clock(round(t * fps), fps)}{ease_char(k[2] if len(k) > 2 else None)}={fmt(v)}')
    return ';'.join(out)


def parse_anim(text, fps):
    """The keyframes in an MLT animation string, or None unless they write back to exactly the same text."""
    if not isinstance(text, str) or '=' not in text:
        return None
    keys = []
    for part in text.split(';'):
        m = _KEY.match(part)
        if not m:
            return None
        t = tm.clock_to_frames(m.group(1), fps) / fps
        k = [round(t, 3), _num(m.group(3))]
        if m.group(2):
            k.append(CHAR_EASE[m.group(2)])
        keys.append(k)
    try:
        if anim(keys, fps) != text:
            return None
    except ValueError:
        return None
    return keys


def value(v, fps):
    """A script parameter value -> property text."""
    if isinstance(v, dict) and 'keys' in v:
        return anim(v['keys'], fps)
    return fmt(v)


def view_value(text, fps):
    keys = parse_anim(text, fps)
    if keys is not None:
        return {'keys': keys}
    return _num(text)


# ------------------------------------------------------------------ naming

_names = None


def _name_index():
    global _names
    if _names is None:
        _names = {}
        try:
            import letitedit.timeline.effects_catalog as effects_catalog
            for e in effects_catalog.index():
                if e.get('shotcut_id'):
                    _names.setdefault(('id', e['shotcut_id']), e['name'])
                elif e.get('source') == 'shotcut':
                    _names.setdefault(('svc', e['service']), e['name'])
        except Exception:  # noqa: BLE001 - catalogue unavailable: fall back to raw ids
            pass
    return _names


def name_of(props):
    sid, svc = props.get('shotcut:filter'), props.get('mlt_service', '')
    names = _name_index()
    if sid and ('id', sid) in names:
        return names[('id', sid)]
    if not sid and ('svc', svc) in names:
        return names[('svc', svc)]
    return sid or svc


def resolve(name):
    """{'service', 'shotcut_id', 'link', 'defaults'} for a filter name."""
    try:
        import letitedit.timeline.effects_catalog as effects_catalog
    except ImportError:
        return {'service': name, 'shotcut_id': None, 'link': False, 'defaults': {}}
    return effects_catalog.resolve(name)


# ------------------------------------------------------------------ view and build

def _attr_frames(text, fps):
    """A filter's in or out attribute (frames, or a clock time) as frames, as the engine reads it."""
    return tm.clock_to_frames(str(text), fps)


def view(elem, fps):
    """Generic script view of a filter/link element."""
    p = {c.get('name'): (c.text or '') for c in elem.findall('property')}
    out = {'filter': name_of(p)}
    params = {k: view_value(v, fps) for k, v in p.items() if k not in HIDDEN}
    if AIM_TAG in p:
        # a time range the app has written as attributes, as clock times
        for k in ('in', 'out'):
            if k not in params and elem.get(k) is not None:
                params[k] = _attr_frames(elem.get(k), fps)
    if params:
        out['params'] = params
    if elem.tag == 'link':
        out['link'] = True
    return out


def _set(el, name, val):
    for c in el.findall('property'):
        if c.get('name') == name:
            c.text = val
            return
    q = ET.SubElement(el, 'property', {'name': name})
    q.text = val


def _unset(el, name):
    for c in el.findall('property'):
        if c.get('name') == name:
            el.remove(c)


def build(effect, fps, original=None):
    """Filter element for {filter: NAME, params}. With `original` (an element of the same filter), its bookkeeping
    and any settings the effect doesn't mention are kept; settings removed from the effect go back to default."""
    params = effect.get('params') or {}
    if not isinstance(params, dict):
        raise ValueError(f"{effect['filter']}: params must be a mapping of setting -> value")
    if original is not None:
        el = copy.deepcopy(original)
        before = view(original, fps).get('params', {})
        tagged = AIM_TAG in {c.get('name') for c in el.findall('property')}
        for k in before:
            if k not in params:
                _unset(el, k)
                if tagged and k in ('in', 'out'):
                    el.attrib.pop(k, None)
        for k, v in params.items():
            if tagged and k in ('in', 'out') and el.get(k) is not None:
                el.set(k, value(v, fps))        # the app's attribute stays the one place the range is kept
                continue
            _set(el, str(k), value(v, fps))
        return el
    r = resolve(effect['filter'])
    el = ET.Element('link' if (r.get('link') or effect.get('link')) else 'filter')
    props = {k: fmt(v) for k, v in (r.get('defaults') or {}).items()}
    props.update({str(k): value(v, fps) for k, v in params.items()})
    props['mlt_service'] = r['service']
    if r.get('shotcut_id'):
        props['shotcut:filter'] = r['shotcut_id']
    for k, v in props.items():
        _set(el, k, v)
    return el


# ------------------------------------------------------------------ friendly motion

def rect_text(rect):
    """'x y w h [opacity]' or [x, y, w, h(, o)] -> MLT rect text."""
    vals = rect.split() if isinstance(rect, str) else list(rect)
    vals = [float(x) for x in vals]
    if len(vals) == 4:
        vals.append(1.0)
    if len(vals) != 5:
        raise ValueError(f'a rectangle is "x y w h" or "x y w h opacity", not {rect!r}')
    return ' '.join(fmt(round(x, 3)) for x in vals)


def zoom_rect(z, width, height, focus=(0.5, 0.5)):
    """The size/position rectangle that zooms the picture by z towards a focus point (fractions of the frame)."""
    z = float(z)
    fx, fy = (float(focus[0]), float(focus[1])) if focus is not None else (0.5, 0.5)
    w, h = width * z, height * z
    return f'{fmt(round(-(w - width) * fx, 1))} {fmt(round(-(h - height) * fy, 1))} {fmt(round(w, 1))} {fmt(round(h, 1))} 1'


def motion_rect(effect, width, height, fps):
    """Rect property text for {zoom: z | {keys}, focus?} or {size_position: rect | {keys}}."""
    if 'zoom' in effect:
        z = effect['zoom']
        focus = effect.get('focus')
        if focus is None and isinstance(effect.get('style'), dict) and 'anchor_y' in effect['style']:
            focus = (0.5, effect['style']['anchor_y'])
        if isinstance(z, dict):
            return anim([[k[0], zoom_rect(k[1], width, height, focus)] + list(k[2:]) for k in z['keys']], fps)
        return zoom_rect(z, width, height, focus)
    r = effect['size_position']
    if isinstance(r, dict):
        return anim([[k[0], rect_text(k[1])] + list(k[2:]) for k in r['keys']], fps)
    return rect_text(r)
