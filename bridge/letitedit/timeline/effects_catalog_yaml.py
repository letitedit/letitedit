"""The settings, and YAML read with PyYAML or a tolerant subset.

Part of `effects_catalog` (letitedit/timeline/effects_catalog.py), which imports every name here back,
so `effects_catalog.X` is the same object it always was.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import os
import re
from pathlib import Path
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

APP = Path((_SAI_ROOT + '\\app'))
MELT = APP / 'melt.exe'
FFPROBE = APP / 'ffprobe.exe'
QML = APP / 'share' / 'shotcut' / 'qml'
FILTERS_QML = QML / 'filters'
CONTROLS_QML = QML / 'modules' / 'Shotcut' / 'Controls'
MLT_SHARE = APP / 'share' / 'mlt'
MLT_LIBS = (APP / 'lib' / 'mlt', APP / 'lib' / 'frei0r-1', APP / 'lib' / 'ladspa')
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
INDEX_FILE = CACHE / 'effects-index.json'
SERVICES_FILE = CACHE / 'effects-services.json'
CATALOG_VERSION = 4
NO_WINDOW = 0x08000000

CATEGORIES = ['colour & light', 'blur & sharpen', 'stylize', 'distort & transform', 'keying & masks', 'time & motion',
              'audio levels & dynamics', 'audio EQ & filters', 'audio cleanup', 'audio space/effects', 'other']
RECOMMENDED = {
    'colour & light': ['color', 'hue_lightness_saturation', 'levels', 'white', 'lut3d', 'vibrance'],
    'blur & sharpen': ['blur_gaussian', 'sharpen', 'smartblur', 'hqdn3d', 'pillar_echo'],
    'stylize': ['vignette', 'glow', 'grain', 'oldfilm', 'glitch', 'dropshadow'],
    'distort & transform': ['size_position', 'crop_rectangle', 'mirror', 'lenscorrection', 'corners'],
    'keying & masks': ['mask_chromakey', 'mask_alphaspot', 'mask_apply', 'keyspillm0pup', 'select0r'],
    'time & motion': ['speed', 'time_remap', 'stabilize', 'shake', 'trails'],
    'audio levels & dynamics': ['audio_gain', 'audio_compressor', 'audio_limiter', 'audio_normalize_1p', 'audio_fadein'],
    'audio EQ & filters': ['audio_eqparametric', 'audio_eq3band', 'audio_highpass', 'audio_lowpass', 'audio_notch'],
    'audio cleanup': ['audio_rnnoise_link', 'audio_noisegate', 'audio_adeclick', 'avfilter.afftdn', 'avfilter.adeclip'],
    'audio space/effects': ['audio_reverb', 'audio_delay', 'audio_pan', 'audio_pitch', 'audio_stereoenhance'],
    'other': ['dynamictext', 'audiolevelgraph', 'spectrum', 'waveform', 'timer'],
}


# =============================================================================== YAML (PyYAML, or a tolerant subset)

try:
    import yaml as _yaml
    _YLoader = getattr(_yaml, 'CSafeLoader', _yaml.SafeLoader)
except ImportError:  # pragma: no cover - PyYAML is optional
    _yaml = None


def yaml_load(text):
    """MLT metadata YAML -> Python. PyYAML when installed, else (or when it chokes) mini_yaml."""
    if _yaml is not None:
        try:
            return _yaml.load(text, Loader=_YLoader)
        except Exception:  # noqa: BLE001 - fall back to the tolerant parser
            pass
    return mini_yaml(text)


def _yscalar(s):
    s = s.strip()
    if not s:
        return None
    if s[0] in '"\'':
        q = s[0]
        end = s.rfind(q)
        body = s[1:end] if end > 0 else s[1:]
        if q == '"':
            return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), body)
        return body.replace("''", "'")
    if s[0] == '[' and s.endswith(']'):
        parts, buf, quote = [], '', None
        for ch in s[1:-1]:
            if quote:
                buf += ch
                quote = None if ch == quote else quote
            elif ch in '"\'':
                buf, quote = buf + ch, ch
            elif ch == ',':
                parts.append(buf)
                buf = ''
            else:
                buf += ch
        if buf.strip():
            parts.append(buf)
        return [_yscalar(p) for p in parts]
    if ' #' in s:
        s = s.split(' #', 1)[0].rstrip()
    low = s.lower()
    if low in ('yes', 'true', 'on'):
        return True
    if low in ('no', 'false', 'off'):
        return False
    if low in ('null', '~'):
        return None
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            pass
    return s


def _ykey(c):
    if c[:1] in '"\'':
        end = c.find(c[0], 1)
        if end > 0 and c[end + 1:end + 2] == ':':
            return c[1:end], c[end + 2:].strip()
        return None, None
    m = re.match(r'^([^:#\s][^:#]*?)\s*:(?:\s+|$)(.*)$', c)
    return (m.group(1).strip(), m.group(2).strip()) if m else (None, None)


def mini_yaml(text):
    """A tolerant parser for the YAML subset MLT metadata uses: block mappings and sequences, plain/quoted scalars,
    flow lists, | and > block scalars, plain scalars continued on deeper lines."""
    rows, raws = [], []     # (indent or -1 for blank/comment, text); raws keep comment-looking lines for blocks
    for raw in text.replace('\t', '    ').splitlines():
        st = raw.strip()
        if st in ('---', '...'):
            continue
        rows.append((-1, '') if not st or st.startswith('#') else (len(raw) - len(raw.lstrip(' ')), st))
        raws.append((len(raw) - len(raw.lstrip(' ')), st))
    n = len(rows)
    pos = 0

    def skip():
        nonlocal pos
        while pos < n and rows[pos][0] < 0:
            pos += 1

    def is_item(c):
        return c == '-' or c.startswith('- ')

    def block(parent, style):
        nonlocal pos
        lines, base = [], None
        while pos < n:
            i, c = rows[pos]
            if 0 <= i <= parent:
                break
            ri, rc = raws[pos]
            if i < 0 and rc and ri <= parent:
                break               # a real comment at the parent's level ends the block
            if rc:
                base = ri if base is None else base
                lines.append(' ' * max(0, ri - base) + rc)
            else:
                lines.append('')
            pos += 1
        while lines and not lines[-1]:
            lines.pop()
        return '\n'.join(lines) + '\n' if style == '|' else ' '.join(x.strip() for x in lines if x.strip())

    def node():
        skip()
        if pos >= n:
            return None
        i, c = rows[pos]
        return seq(i) if is_item(c) else mapping(i)

    def seq(indent):
        nonlocal pos
        out = []
        while True:
            skip()
            if pos >= n:
                break
            i, c = rows[pos]
            if i != indent or not is_item(c):
                break
            item = c[1:].strip()
            if not item:
                pos += 1
                out.append(node())
            elif _ykey(item)[0] is not None and item[0] not in '[{':
                rows[pos] = (indent + 2, item)
                out.append(mapping(indent + 2))
            else:
                pos += 1
                out.append(_yscalar(item))
        return out

    def mapping(indent):
        nonlocal pos
        out = {}
        while True:
            skip()
            if pos >= n:
                break
            i, c = rows[pos]
            if i < indent or (i == indent and is_item(c)):
                break
            if i > indent:
                pos += 1
                continue
            key, rest = _ykey(c)
            pos += 1
            if key is None:
                continue
            if re.match(r'^[|>][-+]?(\s+#.*)?$', rest):
                out[key] = block(indent, rest[0])
            elif rest == '':
                skip()
                if pos < n and rows[pos][0] > indent and not is_item(rows[pos][1]) \
                        and _ykey(rows[pos][1])[0] is None:
                    lines = []          # a plain scalar starting on the next, deeper line
                    while pos < n and rows[pos][0] > indent:
                        lines.append(rows[pos][1])
                        pos += 1
                    out[key] = _yscalar(' '.join(lines))
                elif pos < n and (rows[pos][0] > indent or (rows[pos][0] == indent and is_item(rows[pos][1]))):
                    out[key] = node()
                else:
                    out[key] = None
            else:
                while pos < n and rows[pos][0] > indent and _ykey(rows[pos][1])[0] is None:
                    rest += ' ' + rows[pos][1]
                    pos += 1
                out[key] = _yscalar(rest)
        return out

    return node()
