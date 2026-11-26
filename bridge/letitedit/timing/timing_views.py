"""View registry of the timing perception layer (TIMING-SPEC.md): modules plug a view into the one MCP tool
(`letitedit_timing`, timing_tools.py) without editing it.

    register_view(name, fn, summary)
        fn(source, start_s, end_s, items, cuts, options, detail) -> dict with 'images': [paths], the common
        contract fields (common_fields() fills the missing ones) and the view's own data.
    views()            -> {name: summary} of every registered view (plugins discovered first)
    get(name)          -> the view's function (KeyError lists the views)
    run(name, source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief')
                       -> the view's result with every common contract field present
    common_fields(...) -> the contract fields every result carries (schema_version, result_id, project_revision,
                          source_fingerprints, checked_ranges, unchecked_ranges, warnings, unsupported,
                          preview_artifacts, changes)
    load_plugins()     -> imports the bridge modules that register lanes or views (timing_signals.load_plugins)

Views register at import (`timing_views.register_view('cuts', fn, 'one line')`). The modules that register
are listed in timing_signals.PLUGINS; timing_signals.load_plugins() imports each once per process (an import error is
reported, never raised).
"""
from __future__ import annotations

import hashlib
import json
import threading

SCHEMA_VERSION = 1
_VIEWS = {}          # name -> {'fn', 'summary', 'module'}
_LOCK = threading.RLock()


def register_view(name, fn, summary):
    """Register (or replace) a view. name: short word ('map', 'cuts'); fn(source, start_s, end_s, items, cuts,
    options, detail) -> dict; summary: one line for the tool's description."""
    if not name or not isinstance(name, str):
        raise ValueError('a view needs a name')
    if not callable(fn):
        raise TypeError(f'view {name!r}: fn must be callable')
    from letitedit.timing.timing_signals import public_module
    with _LOCK:
        _VIEWS[name] = {'fn': fn, 'summary': str(summary or '').strip(), 'module': public_module(fn)}
    return fn


def _ensure_loaded():
    try:
        import letitedit.timing.timing_signals as timing_signals
        timing_signals.load_plugins()
    except Exception:  # noqa: BLE001 - discovery problems are reported by timing_signals.plugin_report()
        pass


def views(load=True):
    """{name: summary} of the registered views."""
    if load:
        _ensure_loaded()
    with _LOCK:
        return {k: v['summary'] for k, v in sorted(_VIEWS.items())}


def get(name, load=True):
    if load and name not in _VIEWS:
        _ensure_loaded()
    with _LOCK:
        v = _VIEWS.get(name)
    if v is None:
        raise KeyError(f'no timing view {name!r}; views: {", ".join(sorted(_VIEWS)) or "(none registered)"}')
    return v['fn']


def result_id(*parts):
    """A stable id from the inputs that decide a result (same inputs -> same id)."""
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]


def common_fields(source=None, sig=None, view=None, inputs=None, checked_ranges=None, unchecked_ranges=None,
                  warnings=None, unsupported=None, preview_artifacts=None):
    """The contract fields of every timing result (TIMING-SPEC 'Common contract fields'). sig: a
    timing_signals.signals() result (gives the project revision, fingerprints and checked ranges)."""
    out = {'schema_version': SCHEMA_VERSION}
    rid_parts = [view, source, inputs]
    if sig:
        rid_parts.append(sig.get('key'))
        out['project_revision'] = sig.get('project_revision')
        out['source_fingerprints'] = sig.get('source_fingerprints') or {}
        cr = sig.get('checked_ranges')
        ur = sig.get('unchecked_ranges')
    else:
        out['project_revision'] = None
        out['source_fingerprints'] = {}
        cr = ur = None
    out['result_id'] = result_id(*rid_parts)
    out['checked_ranges'] = list(checked_ranges if checked_ranges is not None else (cr or []))
    out['unchecked_ranges'] = list(unchecked_ranges if unchecked_ranges is not None else (ur or []))
    out['warnings'] = list(warnings or [])
    out['unsupported'] = list(unsupported or [])
    out['preview_artifacts'] = list(preview_artifacts or [])
    out['changes'] = []
    return out


CONTRACT = ('schema_version', 'result_id', 'project_revision', 'source_fingerprints', 'checked_ranges',
            'unchecked_ranges', 'warnings', 'unsupported', 'preview_artifacts', 'changes')


def run(name, source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """Run a view and make sure its result carries every contract field and an 'images' list."""
    fn = get(name)
    res = fn(source, start_s, end_s, items, cuts, options or {}, detail)
    if not isinstance(res, dict):
        res = {'data': res}
    base = common_fields(source=str(source), view=name,
                         inputs=[start_s, end_s, items, cuts, options, detail])
    for k in CONTRACT:
        if k not in res or res[k] is None and k not in ('project_revision',):
            res[k] = base[k]
    res.setdefault('images', [])
    res.setdefault('view', name)
    return res
