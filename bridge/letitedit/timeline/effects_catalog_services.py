"""The engine's service metadata.

Part of `effects_catalog` (letitedit/timeline/effects_catalog.py), which imports every name here back,
so `effects_catalog.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from letitedit.timeline.effects_catalog_yaml import (  # noqa: E402
    APP, CACHE, CATALOG_VERSION, CONTROLS_QML, FILTERS_QML, MELT, MLT_LIBS, MLT_SHARE, NO_WINDOW, SERVICES_FILE,
    yaml_load
)


# =============================================================================== MLT service metadata

def _melt(*args, timeout=60):
    r = subprocess.run([str(MELT), *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, cwd=str(APP))
    return r.stdout or ''


def _service_lists():
    filters = (yaml_load(_melt('-query', 'filters')) or {}).get('filters') or []
    links = (yaml_load(_melt('-query', 'links')) or {}).get('links') or []
    return [str(x) for x in filters], [str(x) for x in links]


def _is_avfilter(service):
    return service.startswith('avfilter.')


def _compact_service(meta, service):
    """MLT metadata dict -> {title, description, tags, params} with only what the catalogue needs."""
    if not isinstance(meta, dict):
        return None
    params = []
    for p in meta.get('parameters') or []:
        if not isinstance(p, dict) or p.get('identifier') in (None, ''):
            continue
        ident = str(p['identifier'])
        if p.get('readonly') in (True, 'yes') or '[' in ident or ident.startswith('_') or ' ' in ident \
                or 'deprecated' in str(p.get('title') or '').lower():
            continue
        typ = p.get('type')
        default = p.get('default')
        values = p.get('values')
        desc = _clean_text(p.get('description'))
        if typ == 'color' and isinstance(default, int) and not isinstance(default, bool):
            default = f'0x{default:08x}'        # YAML 1.1 reads 0xrrggbbaa as an integer
        if _is_avfilter(service):
            expr = typ == 'string' and not values and isinstance(default, (int, float)) and not isinstance(default, bool)
            if expr:     # MLT types FFmpeg's expression-capable numbers as string
                typ = 'float'
                desc = (desc + ' ' if desc else '') + '(a number, or an FFmpeg expression)'
            keyframes = typ in ('float', 'integer', 'double') and ident != 'position'
        else:
            keyframes = p.get('animation') in (True, 'yes')
        item = {'name': ident, 'title': p.get('title'), 'type': typ,
                'min': p.get('minimum'), 'max': p.get('maximum'),
                'default': default if isinstance(default, (int, float, str, bool)) else None,
                'keyframes': keyframes, 'description': desc,
                'values': [v for v in values if isinstance(v, (int, float, str))][:24] if isinstance(values, list) else None,
                'unit': p.get('unit'), 'format': p.get('format') if isinstance(p.get('format'), str) else None,
                'mutable': p.get('mutable') in (True, 'yes')}
        params.append({k: v for k, v in item.items() if k == 'keyframes' or _keep(v)})
    tags = [str(t) for t in meta.get('tags') or [] if isinstance(t, (str, int))]
    return {'title': _clean_text(meta.get('title')), 'description': _clean_text(meta.get('description')),
            'notes': _clean_text(meta.get('notes')), 'tags': tags, 'params': params}


def _keep(v):
    return v is not None and v is not False and not (isinstance(v, (str, list)) and not v)


def _clean_text(s):
    if not isinstance(s, str):
        return None if s is None else str(s)
    return re.sub(r'\s+', ' ', s).strip() or None


def _yml_services():
    out = {}
    for path in sorted(MLT_SHARE.glob('*/*.yml')):
        base = path.name
        if not base.startswith(('filter_', 'link_', 'transition_affine')):
            continue
        try:
            meta = yaml_load(path.read_text(encoding='utf-8', errors='replace'))
        except Exception:  # noqa: BLE001 - unreadable metadata: the service is still listed by melt
            continue
        if not isinstance(meta, dict) or not meta.get('identifier'):
            continue
        ident = str(meta['identifier'])
        if base.startswith('transition_'):
            ident = '@transition.' + ident
        out.setdefault(ident, _compact_service(meta, ident))
    return out


def _query_service(service, link=False):
    text = _melt('-query', f'{"link" if link else "filter"}={service}')
    if 'identifier' not in text:
        return None
    try:
        return _compact_service(yaml_load(text), service)
    except Exception:  # noqa: BLE001
        return None


def _services_stamp():
    parts = [f'v{CATALOG_VERSION}']
    for p in (MELT, MLT_SHARE, *MLT_LIBS, APP / 'avfilter-12.dll'):
        try:
            st = p.stat()
            parts.append(f'{p.name}:{st.st_mtime_ns}:{st.st_size if p.is_file() else 0}')
        except OSError:
            parts.append(f'{p.name}:-')
    return hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]


def _qml_mtime():
    latest = 0
    for d in (FILTERS_QML, CONTROLS_QML):
        try:
            latest = max(latest, d.stat().st_mtime_ns)
            for entry in os.scandir(d):
                latest = max(latest, entry.stat().st_mtime_ns)
                if entry.is_dir():
                    for sub in os.scandir(entry.path):
                        latest = max(latest, sub.stat().st_mtime_ns)
        except OSError:
            pass
    return latest


def _stamp():
    try:
        app = APP.stat().st_mtime_ns
    except OSError:
        app = 0
    try:
        code = Path(__file__).stat().st_mtime_ns     # a change to this parser rebuilds the entries (not the melt cache)
    except OSError:
        code = 0
    return hashlib.sha1(f'{_services_stamp()}|{app}|{_qml_mtime()}|{code}'.encode()).hexdigest()[:16]


def _load_services(stamp):
    """{'filters', 'links', 'meta': {service: compact}} - cached; melt is only queried for what yml doesn't cover."""
    try:
        data = json.loads(SERVICES_FILE.read_text(encoding='utf-8-sig'))
        if data.get('stamp') == stamp:
            return data
    except (OSError, ValueError):
        pass
    filters, links = _service_lists()
    meta = _yml_services()
    todo = []
    for sid in filters + [x for x in links if x not in filters]:
        if sid in meta or sid.startswith('movit.') or sid in _PLUMBING:
            continue
        todo.append((sid, sid not in filters))
    workers = max(4, min(16, (os.cpu_count() or 8)))
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for (sid, is_link), m in zip(todo, ex.map(lambda a: _query_service(*a), todo)):
            if m is not None:
                meta[sid] = m
    data = {'stamp': stamp, 'filters': filters, 'links': links, 'meta': meta}
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = SERVICES_FILE.with_suffix(f'.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    os.replace(tmp, SERVICES_FILE)
    return data


# =============================================================================== building the index

_PLUMBING = {
    'audioconvert', 'imageconvert', 'sws_colortransform', 'audiochannels', 'audiomap', 'transition', 'fieldorder',
    'telecide', 'resize', 'rescale', 'data_feed', 'data_show', 'swresample', 'swscale', 'avcolor_space',
    'avdeinterlace', 'deinterlace', 'resample', 'glsl.manager', 'ladspa', 'subtitle_feed',
    'avfilter.null', 'avfilter.anull', 'avfilter.copy', 'avfilter.acopy', 'avfilter.format', 'avfilter.aformat',
    'avfilter.setsar', 'avfilter.setdar', 'avfilter.setparams', 'avfilter.setfield', 'avfilter.setrange',
    'avfilter.settb', 'avfilter.asettb', 'avfilter.noformat', 'avfilter.anullsink', 'avfilter.nullsink',
    'avfilter.hwdownload', 'avfilter.hwupload', 'avfilter.hwmap', 'avfilter.hwupload_cuda',
}
