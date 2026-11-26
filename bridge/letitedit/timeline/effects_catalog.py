"""Every effect Shotcut's engine (MLT 7) can apply: find it, read its settings, resolve it, preview it.

    index()                          -> every entry (Shotcut's own filters, frei0r/MLT services, FFmpeg avfilter.*,
                                        LADSPA/SoX audio), Shotcut's first
    search(query, kind=None, limit)  -> ranked entries (Shotcut's own first, then frei0r/MLT, then FFmpeg)
    info(name)                       -> one entry with every parameter
    resolve(name)                    -> {'service', 'shotcut_id', 'link', 'defaults', 'name', 'kind', 'needs'}
                                        for the edit-script compiler (edit_effects.py)
    preview(name, params, clip, at_s, width) -> JPEG bytes: before/after of one frame (waveforms + levels for audio)
    categories(kind=None)            -> counts per category with recommended names
    overview / listing / describe    -> the text the letitedit_effects MCP tool returns

An entry: {name, title, kind: 'video'|'audio', service, shotcut_id, source: 'shotcut'|'mlt'|'ffmpeg', keywords,
description, params: [{name, title, type, min, max, default, keyframes, description, values?}], needs?, link,
defaults, hidden, available, category}. Shotcut filters are named by their folder (vignette, audio_compressor...);
everything else by its MLT service id (frei0r.glow, avfilter.eq, ladspa.1216, sox.echo...).

Sources: Shotcut's filter QML (meta*.qml: names, keywords, keyframable parameters; ui*.qml: the values a NEW filter
gets, read by a tiny interpreter of the `if (filter.isNew)` / Component.onCompleted code), MLT's service metadata
(share/mlt/*/filter_*.yml, link_*.yml, and `melt -query` for frei0r/avfilter/LADSPA/SoX). Movit (GPU-only)
variants and letitedit's own ai_* layers are left out. The index is cached in C:\\LetItEdit\\cache\\effects-index.json
(service metadata in effects-services.json) and rebuilt when the app folder, the filter QML, melt or CATALOG_VERSION
change; loading a valid cache never runs melt.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings, and YAML read with PyYAML or a tolerant subset
from letitedit.timeline.effects_catalog_yaml import (  # noqa: E402,F401
    _SAI_ROOT, APP, MELT, FFPROBE, QML, FILTERS_QML, CONTROLS_QML, MLT_SHARE, MLT_LIBS, CACHE, INDEX_FILE,
    SERVICES_FILE, CATALOG_VERSION, NO_WINDOW, CATEGORIES, RECOMMENDED, _yaml, _YLoader, yaml_load, _yscalar,
    _ykey, mini_yaml
)
# a tiny QML/JS evaluator: what a filter's settings panel offers
from letitedit.timeline.effects_catalog_qml import (  # noqa: E402,F401
    _Bail, _Unknown, _UNK, _TOKEN_RE, _SPECIAL, _OPEN, _unescape, _tokenize, _known, _truthy, _js_str, _num,
    _binop, _rgba, _method, _MATH, _JS, _clean_value, _Qml, _DECL, _ONCOMPLETED, _FILTER_CALL, _PRESET_PARAMS,
    _ARRAY_SYMBOLS, _declare, _base_sym_cache, _base_symbols, _ui_analysis, _match_brace, _parse_meta
)
# the engine's service metadata
from letitedit.timeline.effects_catalog_services import (  # noqa: E402,F401
    _melt, _service_lists, _is_avfilter, _compact_service, _keep, _clean_text, _yml_services, _query_service,
    _services_stamp, _qml_mtime, _stamp, _load_services, _PLUMBING
)
# the index built and its categories
from letitedit.timeline.effects_catalog_build import (  # noqa: E402,F401
    _TIMING, _ANALYSIS, _GPU_ALT, _NOTES, _keywords, _kind_of_service, _first_sentence, _norm_range, _sub_meta,
    _INTERNAL, _ENGINE_SKIP, _letitedit_entries, _visible, _letitedit_entry, _raw_entries, _CAT_OVERRIDES,
    _HARDWARE, _VIDEO_RULES, _AUDIO_RULES, _category, _build, _norm_key, _make_state, _fmt_num, _isnum
)


import array
import bisect
import concurrent.futures
import copy
import difflib
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

_lock = threading.RLock()
_state = None          # {'entries', 'by_name', 'by_title', 'by_object', 'stamp', 'checked'}
_REVALIDATE_S = 30.0


def _load(force=False):
    global _state
    with _lock:
        now = time.time()
        if _state is not None and not force and now - _state['checked'] < _REVALIDATE_S:
            return _state
        stamp = _stamp()
        if _state is not None and not force and _state['stamp'] == stamp:
            _state['checked'] = now
            return _state
        data = None
        if not force:
            try:
                data = json.loads(INDEX_FILE.read_text(encoding='utf-8-sig'))
                if data.get('stamp') != stamp or data.get('version') != CATALOG_VERSION:
                    data = None
            except (OSError, ValueError):
                data = None
        if data is None:
            data = _build()
        _state = _make_state(data)
        return _state


def rebuild():
    """Rebuild the index from Shotcut's QML and melt now (normally automatic). Returns build info."""
    st = _load(force=True)
    return {'entries': len(st['entries']), 'built': st['built'], 'build_seconds': st['build_seconds']}


# =============================================================================== public API

def index():
    """Every entry, Shotcut's own first (visible before hidden), then MLT/frei0r/LADSPA/SoX, then FFmpeg avfilter.*.
    The dicts are shared: copy before changing them."""
    return list(_load()['entries'])


def _find(name):
    st = _load()
    if not isinstance(name, str) or not name.strip():
        raise ValueError('an effect name is needed')
    raw = name.strip()
    low = raw.lower()
    e = (st['by_name'].get(raw) or st['by_lname'].get(low) or st['by_title'].get(low)
         or st['by_object'].get(raw) or st['by_object'].get(low) or st['by_norm'].get(_norm_key(raw)))
    if e is not None:
        return e
    if low.startswith('movit.'):
        raise ValueError(f'{raw} is GPU-only (Movit), which letitedit does not use; search for the CPU effect '
                         f'(e.g. {raw[6:]}) instead')
    words = set(re.findall(r'[a-z0-9]+', low))
    if words:
        same = [x for x in st['entries'] if x['source'] == 'shotcut'
                and set(re.findall(r'[a-z0-9]+', (x['title'] or '').lower())) == words]
        if len(same) == 1:
            return same[0]
    raise ValueError(f'unknown effect {raw!r}' + _suggest(raw))


def _suggest(raw):
    st = _load()
    pool = {}
    for e in st['entries']:
        pool.setdefault(e['name'].lower(), e['name'])
        if e['source'] == 'shotcut':
            pool.setdefault((e['title'] or '').lower(), e['name'])
    close = [pool[k] for k in difflib.get_close_matches(raw.lower(), list(pool), n=8, cutoff=0.6)]
    for e in search(raw, limit=5):
        close.append(e['name'])
    seen, out = set(), []
    for n in close:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return f'; did you mean: {", ".join(out[:5])}?' if out else '; search with letitedit_effects(query=...)'


def info(name):
    """One entry (a deep copy) with every parameter: accepts what resolve() accepts."""
    return copy.deepcopy(_find(name))


def resolve(name):
    """NAME -> {'service', 'shotcut_id', 'link', 'defaults', 'name', 'kind', 'needs'}.

    NAME may be a catalogue name (folder name for Shotcut filters, service id otherwise), Shotcut's display name
    (any case), a Shotcut objectName, or a raw MLT service id. defaults = the properties Shotcut gives a NEW filter
    (empty for raw services: the engine's own defaults apply). Unknown names raise ValueError with close matches."""
    e = _find(name)
    return {'service': e['service'], 'shotcut_id': e['shotcut_id'], 'link': bool(e['link']),
            'defaults': dict(e['defaults']), 'name': e['name'], 'kind': e['kind'], 'needs': e.get('needs')}


_SYNONYMS = {
    'colour': ['color'], 'color': ['colour'], 'grey': ['gray', 'grayscale', 'desaturate'],
    'greyscale': ['grayscale', 'desaturate'], 'blackandwhite': ['grayscale', 'desaturate'],
    'denoise': ['noise', 'denoiser'], 'volume': ['gain', 'level'], 'loudness': ['normalize', 'loud', 'level'],
    'zoom': ['scale', 'size'], 'move': ['position'], 'greenscreen': ['chroma', 'key'], 'slow': ['speed'],
    'fast': ['speed'], 'pitch': ['tone'], 'echo': ['delay'], 'sharpen': ['sharp', 'sharpness'],
    'stabilise': ['stabilize'], 'old': ['film', 'vintage'], 'vintage': ['old', 'film'],
}


def _qtokens(query):
    toks = [t for t in re.findall(r'[a-z0-9]+', query.lower().replace('&', ' and ')) if t not in ('and', 'the', 'a')]
    return [[t] + _SYNONYMS.get(t, []) for t in toks]


def _word_hit(tok, words):
    for w in words:
        if w == tok:
            return 1.0
    for w in words:
        if len(tok) >= 4 and (w.startswith(tok) or (len(w) >= 4 and tok.startswith(w))):
            return 0.7
    return 0.0


def search(query, kind=None, limit=30):
    """Entries ranked for a query (title, name, keywords, description, then parameter names); Shotcut's own filters
    first, then frei0r/MLT, then FFmpeg avfilter.*. kind: 'video' or 'audio'."""
    st = _load()
    query = (query or '').strip()
    groups = _qtokens(query)
    if not groups:
        return []
    qlow = query.lower()
    scored = []
    for e in st['entries']:
        if kind and e['kind'] != kind:
            continue
        name_words = re.findall(r'[a-z0-9]+', e['name'].lower().replace('avfilter.', '').replace('frei0r.', ''))
        title_words = re.findall(r'[a-z0-9]+', (e['title'] or '').lower())
        kw = e['keywords']
        desc_words = re.findall(r'[a-z0-9]+', (e['description'] or '').lower())
        total, matched, strong = 0.0, 0, True
        for alts in groups:
            best = 0.0
            for i, tok in enumerate(alts):
                f = 1.0 if i == 0 else 0.8
                best = max(best, f * max(6 * _word_hit(tok, title_words), 5 * _word_hit(tok, name_words),
                                         3 * _word_hit(tok, kw), 1.5 * _word_hit(tok, desc_words)))
                if best < 0.5:
                    for p in e['params']:
                        if tok == p['name'].lower().removeprefix('av.') or tok in (p.get('title') or '').lower().split():
                            best = max(best, 0.5 * f)
                            break
            if best > 0:
                matched += 1
            strong = strong and best >= 2.0     # every word hit the title, name or keywords
            total += best
        if not matched:
            continue
        score = total * (matched / len(groups)) ** 2
        t = (e['title'] or '').lower()
        exact = qlow == e['name'].lower() or (e['source'] == 'shotcut' and qlow == t)
        if len(qlow) > 3 and qlow in t:
            score += 4
        # Shotcut's own first, then frei0r/MLT, then FFmpeg; odd ones (hidden, missing, analysis, timing) after
        rank = {'shotcut': 0, 'mlt': 1, 'ffmpeg': 2}.get(e['source'], 1) + (0.5 if e['hidden'] else 0)
        if not e['available']:
            rank += 4
        if e.get('needs') and ('analysis only' in e['needs'] or 'changes timing' in e['needs']):
            rank += 1.5
        scored.append((not exact, not strong, rank, -score, e['name'], e))
    scored.sort(key=lambda x: x[:5])
    return [x[5] for x in scored[:limit]]


def categories(kind=None):
    """[{'category', 'count', 'recommended': [{'name', 'title'}]}] in CATEGORIES order."""
    st = _load()
    counts = {c: 0 for c in CATEGORIES}
    for e in st['entries']:
        if kind and e['kind'] != kind:
            continue
        counts[e['category']] = counts.get(e['category'], 0) + 1
    out = []
    for c in CATEGORIES:
        if kind == 'audio' and not c.startswith('audio') and c != 'other':
            continue
        if kind == 'video' and c.startswith('audio'):
            continue
        rec = []
        for n in RECOMMENDED.get(c, []):
            e = st['by_name'].get(n)
            if e and e['available'] and (not kind or e['kind'] == kind):
                rec.append({'name': n, 'title': e['title']})
        out.append({'category': c, 'count': counts.get(c, 0), 'recommended': rec})
    return out


# =============================================================================== text for the MCP tool

FORM = '{filter: NAME, params: {prop: value | {keys: [[t, v], [t, v, ease], ...]}}}'


def _flow(v):
    """Python value -> compact YAML flow text."""
    if isinstance(v, dict):
        return '{' + ', '.join(f'{_flow_key(k)}: {_flow(x)}' for k, x in v.items()) + '}'
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_flow(x) for x in v) + ']'
    if isinstance(v, str):
        return v if re.fullmatch(r'[A-Za-z_][\w.\-]*', v) and v.lower() not in ('yes', 'no', 'true', 'false', 'null', 'on', 'off') \
            else json.dumps(v)
    return _fmt_num(v)


def _flow_key(k):
    return k if re.fullmatch(r'[A-Za-z_][\w.\-]*', str(k)) else json.dumps(str(k))


def _keyframable(e, limit=6):
    names = [p['name'] for p in e['params'] if p.get('keyframes')]
    if len(names) > limit:
        return ', '.join(names[:limit]) + f' +{len(names) - limit}'
    return ', '.join(names)


def overview(kind=None):
    st = _load()
    entries = [e for e in st['entries'] if not kind or e['kind'] == kind]
    by_src = {}
    for e in entries:
        fam = e['source'] if e['source'] != 'mlt' else ('frei0r' if e['name'].startswith('frei0r.') else
                                                         'LADSPA/SoX' if e['name'].startswith(('ladspa.', 'sox')) else
                                                         'MLT')
        by_src[fam] = by_src.get(fam, 0) + 1
    order = [('shotcut', "Shotcut's own"), ('frei0r', 'frei0r'), ('MLT', 'MLT'), ('LADSPA/SoX', 'LADSPA/SoX audio'),
             ('ffmpeg', 'FFmpeg avfilter.*')]
    lines = [f'{len(entries)} effects{" (" + kind + ")" if kind else ""}: '
             + ', '.join(f'{by_src[k]} {label}' for k, label in order if by_src.get(k)) + '.',
             f'Use in a clip\'s effects: {FORM}  (t = seconds from the clip start).', '']
    for c in categories(kind):
        rec = ', '.join(f'{r["name"]} ({r["title"]})' for r in c['recommended'])
        lines.append(f'{c["category"]} ({c["count"]}): {rec}')
    lines += ['', "Next: query='...' to search (e.g. 'film grain', 'compressor'), name='...' for every setting, "
                  "name + preview_clip='<media file>' to see it before/after."]
    return '\n'.join(lines)


def _line(e):
    what = e['description'] or ''
    if len(what) > 110:
        what = what[:107].rstrip() + '...'
    keys = _keyframable(e)
    flags = []
    if not e['available']:
        flags.append('NOT AVAILABLE')
    if e['hidden']:
        flags.append('hidden')
    if e['link']:
        flags.append('link')
    if e.get('needs') and 'analysis pass' in e['needs']:
        flags.append('needs analysis')
    tail = f' [{", ".join(flags)}]' if flags else ''
    return f'{e["name"]} | {e["title"]} | {what}{" | keys: " + keys if keys else ""}{tail}'


def listing(query, kind=None, limit=25):
    hits = search(query, kind=kind, limit=limit)
    if not hits:
        return f'No effect matches {query!r}. Try a plainer word (blur, colour, grain, echo, compressor) or no query ' \
               f'for the categories.'
    head = f'{len(hits)} effects for {query!r}{" (" + kind + ")" if kind else ""}, best first ' \
           f'(name | title | what it does | keyframable params):'
    return '\n'.join([head] + [_line(e) for e in hits] +
                     ['', "name='...' shows every setting and an example; add preview_clip='<file>' to see it."])


def _range(p):
    lo, hi = p.get('min'), p.get('max')
    if lo is None and hi is None:
        return ''
    return f'{_fmt_num(lo) if lo is not None else ""}..{_fmt_num(hi) if hi is not None else ""}'


def _example(e):
    """An effect entry that changes something visible: one setting keyframed over 2 s, one set."""
    params = {}
    numeric = [p for p in e['params'] if p.get('type') in ('float', 'integer', 'double', None)
               and (_isnum(p.get('default')) or (_isnum(p.get('min')) and _isnum(p.get('max'))))]

    def changed(p, frac):
        lo, hi, d = p.get('min'), p.get('max'), p.get('default')
        if not (_isnum(lo) and _isnum(hi) and hi > lo):
            start = d if _isnum(d) else 0
            if _isnum(lo) and start > lo:
                return start, round(lo + (start - lo) * 0.3, 3)
            return start, round(start * 1.5, 3) if start else 0.5
        start = d if _isnum(d) else (1 if lo <= 1 <= hi and p['name'].endswith('speed_map') else lo)
        target = lo + (hi - lo) * frac
        if abs(target - start) < (hi - lo) * 0.25:
            target = lo + (hi - lo) * (0.25 if start - lo > (hi - lo) / 2 else 0.85)
        if p.get('type') == 'integer' or all(isinstance(x, int) for x in (lo, hi)) and isinstance(d, int):
            target = int(round(target))
        return start, round(target, 3) if isinstance(target, float) else target

    own = [p for p in e['params'] if not p.get('engine')]
    rect = next((p for p in own[:1] if p.get('type') == 'rect' and p.get('keyframes')), None)
    anim = None
    if rect:
        params[rect['name']] = {'keys': [[0, '0%/0%:100%x100%'], [2, '-5%/-5%:110%x110%', 'smooth']]}
    else:
        anim = next((p for p in numeric if p.get('keyframes') and not p.get('engine')), None) or \
            next((p for p in numeric if p.get('keyframes')), None)
        if anim:
            start, target = changed(anim, 0.6)
            params[anim['name']] = {'keys': [[0, start], [2, target, 'smooth']]}
    other = next((p for p in own if p is not anim and p is not rect
                  and not str(p['name']).startswith('shotcut') and p.get('type') != 'rect'), None)
    if other:
        if other in numeric:
            params[other['name']] = changed(other, 0.35)[1]
        elif other.get('type') == 'color':
            params[other['name']] = '#ff2060c0'
        elif other.get('values'):
            vals = [v for v in other['values'] if v != other.get('default')]
            if vals:
                params[other['name']] = vals[0]
        elif re.search(r'(^|\.)(file|resource|filename)$', other['name']):
            params[other['name']] = 'C:/path/to/file'
        elif other.get('default') is not None:
            params[other['name']] = other['default']
    out = {'filter': e['name']}
    if params:
        out['params'] = params
    return _flow(out)


def _param_line(p, w):
    bits = [p['name'].ljust(w), (p.get('title') or '')[:30].ljust(30), str(p.get('type') or '').ljust(7),
            _range(p).ljust(12), ('= ' + _flow(p['default'])) if p.get('default') is not None else '',
            'keys' if p.get('keyframes') else '']
    line = '  ' + ' '.join(bits).rstrip()
    extra = []
    if p.get('description') and p.get('description') != p.get('title'):
        extra.append(p['description'][:110])
    if p.get('values'):
        extra.append('values: ' + ', '.join(map(str, p['values'][:12])))
    if extra:
        line += '  -- ' + '; '.join(extra)
    return line


def describe(name, params=None):
    e = _find(name)
    src = {'shotcut': 'Shotcut filter', 'mlt': 'MLT service', 'ffmpeg': 'FFmpeg filter via MLT'}[e['source']]
    head = f'{e["name"]} - {e["title"]} ({src}, {e["kind"]}; engine: {e["service"]}' + \
           (f', shotcut:filter {e["shotcut_id"]}' if e['shotcut_id'] else '') + ')'
    lines = [head]
    if e['description']:
        lines.append(f'What: {e["description"]}')
    lines.append(f'Category: {e["category"]}')
    if e.get('needs'):
        lines.append(f'Needs: {e["needs"]}')
    if e['params']:
        w = min(26, max(len(p['name']) for p in e['params']))
        own = [p for p in e['params'] if not p.get('engine')]
        extra_params = [p for p in e['params'] if p.get('engine')]
        for group, title in ((own, 'Settings (name  title  type  range  = default  keys = keyframable):'),
                             (extra_params, 'Also accepted by the engine (not on Shotcut\'s panel):')):
            if not group:
                continue
            lines.append(title)
            for p in group:
                lines.append(_param_line(p, w))
    else:
        lines.append('Settings: none (it just applies).')
    if e['defaults']:
        lines.append('A new one starts with: ' + _flow(e['defaults'])[1:-1] + '  (list only what you change).')
    lines.append(f'Example effect entry:  {_example(e)}')
    lines.append(f'Form: {FORM}; t = seconds from the clip start; ease: linear (default), hold, smooth, ease_in, '
                 f'ease_out, ease_in_out, or sine/quad/cubic/expo/back/elastic/bounce _in/_out/_in_out.')
    if params:
        warn = check_params(e['name'], params)
        if warn:
            lines.append('Check: ' + ' '.join(warn))
    return '\n'.join(lines)


def check_params(name, params):
    """Warnings for settings an effect doesn't have (they would be written but ignored)."""
    e = _find(name)
    known = {p['name'] for p in e['params']}
    st = _load()
    raw = st['by_name'].get(e['service'])
    if raw is not None:
        known |= {p['name'] for p in raw['params']}
    unknown = [k for k in (params or {}) if k not in known and not _INTERNAL.match(str(k))]
    if unknown and known:
        close = {k: difflib.get_close_matches(k, list(known), n=1) for k in unknown}
        return [f'{e["name"]} has no setting {k!r}' + (f' (did you mean {c[0]!r}?)' if c else '') + '.'
                for k, c in close.items()]
    return []


# =============================================================================== preview

def mlt_value(v):
    """A script value as MLT property text (numbers, bools, colour/rect strings, [x, y, w, h] lists)."""
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, float):
        return f'{v:.6f}'.rstrip('0').rstrip('.') if not v.is_integer() else str(int(v))
    if isinstance(v, (list, tuple)):
        return ' '.join(mlt_value(x) for x in v)
    return str(v)


def static_value(v, at_s=None):
    """A param value at one moment: {keys: [[t, v, ease?], ...]} -> the value at at_s (seconds from the clip start;
    linear between numeric keys, held otherwise), or the first key's value when at_s is None."""
    if not (isinstance(v, dict) and 'keys' in v):
        return v
    keys = sorted((k for k in v['keys'] if isinstance(k, (list, tuple)) and len(k) >= 2), key=lambda k: float(k[0]))
    if not keys:
        raise ValueError('keys must be [[seconds, value], ...]')
    if at_s is None or at_s <= float(keys[0][0]):
        return keys[0][1]
    for a, b in zip(keys, keys[1:]):
        ta, tb = float(a[0]), float(b[0])
        if ta <= at_s < tb:
            hold = len(a) > 2 and str(a[2]).lower() in ('hold', 'step', 'discrete')
            if not hold and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a[1], b[1])) \
                    and tb > ta:
                return a[1] + (b[1] - a[1]) * (at_s - ta) / (tb - ta)
            return a[1]
    return keys[-1][1]


def _probe(path):
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams',
                        str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, timeout=60)
    data = json.loads(r.stdout or '{}')
    v = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    a = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)
    out = {'duration': float((data.get('format') or {}).get('duration') or 0), 'audio': a is not None,
           'video': v is not None, 'width': 1280, 'height': 720, 'fps_num': 30, 'fps_den': 1}
    if v:
        w, h = int(v.get('width') or 1280), int(v.get('height') or 720)
        rot = 0
        for sd in v.get('side_data_list') or []:
            if 'rotation' in sd:
                rot = int(float(sd['rotation']))
        rot = rot or int(float((v.get('tags') or {}).get('rotate', 0) or 0))
        if abs(rot) % 180 == 90:
            w, h = h, w
        num, _, den = (v.get('avg_frame_rate') or v.get('r_frame_rate') or '30/1').partition('/')
        try:
            num, den = int(num), int(den or 1)
        except ValueError:
            num, den = 30, 1
        if num <= 0 or den <= 0 or num / den > 240:
            num, den = 30, 1
        out.update(width=w, height=h, fps_num=num, fps_den=den)
    return out


def _x(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _effect_xml(entry, r, props):
    tag = 'link' if r['link'] else 'filter'
    allp = {**props, 'mlt_service': r['service']}
    if r['shotcut_id']:
        allp['shotcut:filter'] = r['shotcut_id']
    body = ''.join(f'<property name="{_x(k)}">{_x(v)}</property>' for k, v in allp.items())
    xml = f'<{tag}>{body}</{tag}>'
    if r['service'] == 'mask_start':
        xml += '<filter><property name="mlt_service">mask_apply</property></filter>'
    return xml


def _wrapper(profile, clip, fx_xml, link, entries):
    w, h, num, den = profile
    g = math.gcd(w, h)
    res = _x(str(Path(clip).resolve()))
    plain = f'<producer id="plain"><property name="resource">{res}</property></producer>'
    if link:
        fx = f'<chain id="fx"><property name="resource">{res}</property>{fx_xml}</chain>'
    else:
        fx = f'<producer id="fx"><property name="resource">{res}</property>{fx_xml}</producer>'
    return ('<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C">\n'
            f'<profile width="{w}" height="{h}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
            f'display_aspect_num="{w // g}" display_aspect_den="{h // g}" frame_rate_num="{num}" '
            f'frame_rate_den="{den}" colorspace="709"/>\n{plain}\n{fx}\n<playlist id="pl">'
            + ''.join(f'<entry producer="{p}" in="{a}" out="{b}"/>' for p, a, b in entries) + '</playlist>\n</mlt>\n')


def _run_melt(args, timeout):
    r = subprocess.run([str(MELT), *map(str, args)], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                       cwd=str(APP))
    if r.returncode != 0:
        raise RuntimeError(f'melt failed ({r.returncode}): {(r.stderr or r.stdout)[-1200:]}')
    return r


def preview(name, params=None, clip=None, at_s=None, width=640):
    """JPEG bytes: one frame of `clip` before (left) and after (right) the effect, rendered by melt (the export
    engine). Keyframed params use their value at at_s (or the first key). Audio effects: waveforms and levels of
    ~4 s around at_s before/after. width = width of each half."""
    from PIL import Image as PILImage, ImageDraw
    if not clip:
        raise ValueError('preview needs clip: a media file to try the effect on')
    clip = Path(clip)
    if not clip.is_file():
        raise FileNotFoundError(f'no media file at {clip}')
    e = _find(name)
    if not e['available']:
        raise ValueError(f'{e["name"]} cannot render here: {e.get("needs") or "service missing"}')
    r = resolve(e['name'])
    pr = _probe(clip)
    props = {k: mlt_value(v) for k, v in r['defaults'].items()}
    for k, v in (params or {}).items():
        props[str(k)] = mlt_value(static_value(v, at_s))
    width = max(160, min(1920, int(width or 640)))
    work = Path(tempfile.mkdtemp(prefix='fxprev-', dir=_tmp_root()))
    try:
        if e['kind'] == 'audio' or not pr['video']:
            return _audio_preview(e, r, props, clip, pr, at_s, width, work)
        w, h = pr['width'], pr['height']
        if w > 1920:
            h, w = int(round(h * 1920 / w)), 1920
        w, h = max(2, w - w % 2), max(2, h - h % 2)
        fps = pr['fps_num'] / pr['fps_den']
        dur = pr['duration']
        t = at_s if at_s is not None else (dur / 2 if dur > 0 else 0)
        frame = max(0, int(round(t * fps)))
        if dur > 0:
            frame = min(frame, max(0, int(dur * fps) - 2))
        xml = _wrapper((w, h, pr['fps_num'], pr['fps_den']), clip, _effect_xml(e, r, props), r['link'],
                       [('plain', frame, frame), ('fx', frame, frame)])
        (work / 'preview.mlt').write_text(xml, encoding='utf-8')
        _run_melt(['-quiet', work / 'preview.mlt', '-consumer', f'avformat:{work / "f_%04d.png"}', 'vcodec=png',
                   'pix_fmt=rgba', 'an=1', 'audio_off=1'], timeout=180)
        pngs = sorted(work.glob('f_*.png'))
        if len(pngs) < 2:
            raise RuntimeError(f'melt rendered {len(pngs)} of 2 frames')
        tiles = []
        for p in pngs[:2]:
            im = PILImage.open(p)
            im.load()
            if im.mode in ('RGBA', 'LA', 'P'):
                im = im.convert('RGBA')
                bg = _checker(im.size)
                bg.alpha_composite(im)
                im = bg
            tiles.append(im.convert('RGB'))
        th = max(2, int(round(tiles[0].height * width / tiles[0].width)))
        bar = 26
        sheet = PILImage.new('RGB', (width * 2 + 6, th + bar), (20, 20, 24))
        d = ImageDraw.Draw(sheet)
        for i, (tile, label) in enumerate(zip(tiles, ('before', f'after: {e["name"]} ({e["title"]})'))):
            x = i * (width + 6)
            sheet.paste(tile.resize((width, th), PILImage.LANCZOS), (x, bar))
            d.text((x + 8, 6), f'{label}  @ {t:.2f}s' if i == 0 else label, fill=(225, 225, 225))
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=86)
        return buf.getvalue()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _tmp_root():
    d = CACHE / 'effects-preview'
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _checker(size, cell=16):
    from PIL import Image as PILImage, ImageDraw
    im = PILImage.new('RGBA', size, (200, 200, 200, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], cell):
        for x in range((y // cell) % 2 * cell, size[0], cell * 2):
            d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(150, 150, 150, 255))
    return im


def _read_wav(path):
    with wave.open(str(path), 'rb') as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise RuntimeError('expected 16-bit audio from melt')
    a = array.array('h')
    a.frombytes(raw)
    return a, ch, rate


def _levels(a):
    if not a:
        return -120.0, -120.0
    peak = max(abs(min(a)), abs(max(a))) / 32768
    rms = math.sqrt(sum(x * x for x in a) / len(a)) / 32768
    db = lambda x: 20 * math.log10(x) if x > 1e-6 else -120.0  # noqa: E731
    return db(rms), db(peak)


def _audio_preview(e, r, props, clip, pr, at_s, width, work):
    from PIL import Image as PILImage, ImageDraw
    dur = pr['duration'] or 4.0
    span = min(4.0, dur)
    start = (at_s - span / 2) if at_s is not None else (dur / 2 - span / 2)
    start = max(0.0, min(start, dur - span))
    fps = 25
    a, b = int(start * fps), int(start * fps) + max(1, int(span * fps)) - 1
    waves = []
    for which in ('plain', 'fx'):
        xml = _wrapper((640, 360, fps, 1), clip, _effect_xml(e, r, props), r['link'], [(which, a, b)])
        mlt = work / f'{which}.mlt'
        mlt.write_text(xml, encoding='utf-8')
        out = work / f'{which}.wav'
        _run_melt(['-quiet', mlt, '-consumer', f'avformat:{out}', 'acodec=pcm_s16le', 'ar=48000', 'ac=2', 'vn=1',
                   'video_off=1'], timeout=180)
        waves.append(_read_wav(out))
    ph = 170
    sheet = PILImage.new('RGB', (width * 2 + 6, ph + 44), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    for i, ((samples, ch, rate), label) in enumerate(zip(waves, ('before', f'after: {e["name"]} ({e["title"]})'))):
        x0 = i * (width + 6)
        rms, peak = _levels(samples)
        d.text((x0 + 8, 5), label, fill=(225, 225, 225))
        d.text((x0 + 8, 22), f'RMS {rms:.1f} dBFS   peak {peak:.1f} dBFS   {start:.1f}-{start + span:.1f}s',
               fill=(170, 200, 230))
        mid = 44 + ph // 2
        d.line([(x0, mid), (x0 + width, mid)], fill=(60, 60, 70))
        n = len(samples)
        step = max(1, n // width)
        for col in range(width):
            seg = samples[col * step:(col + 1) * step]
            if not seg:
                break
            hi, lo = max(seg) / 32768, min(seg) / 32768
            d.line([(x0 + col, mid - hi * (ph // 2 - 2)), (x0 + col, mid - lo * (ph // 2 - 2))],
                   fill=(90, 170, 255) if i == 0 else (255, 170, 80))
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=88)
    return buf.getvalue()
