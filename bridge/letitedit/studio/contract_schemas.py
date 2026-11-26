"""The Studio contract's version and its JSON Schemas (contract/schemas), loaded once.

Uses the jsonschema package (in letitedit's own Python). No letitedit imports: the reference fake uses it too.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONTRACT_VERSION = '1.6'
MAJOR = 1
CONTRACT_DIR = Path(__file__).resolve().parent / 'contract'
SCHEMAS = CONTRACT_DIR / 'schemas'
EXAMPLES = CONTRACT_DIR / 'examples'
BASE = 'https://letitedit.app/studio/1/'


@lru_cache(maxsize=1)
def _loaded():
    from referencing import Registry, Resource
    reg = Registry()
    docs = {}
    for f in sorted(SCHEMAS.rglob('*.schema.json')):
        doc = json.loads(f.read_text(encoding='utf-8-sig'))
        reg = reg.with_resource(doc['$id'], Resource.from_contents(doc))
        docs[f.relative_to(SCHEMAS).as_posix()] = doc
    return reg, docs


def schema(name):
    """'job', 'status', 'event', 'result', 'common' or 'kinds/<kind>'."""
    return _loaded()[1][f'{name}.schema.json']


@lru_cache(maxsize=64)
def _validator(ref):
    from jsonschema import Draft202012Validator
    reg, _ = _loaded()
    return Draft202012Validator({'$ref': ref}, registry=reg)


def problems(doc, name):
    """[{'field', 'message'}] where doc doesn't match the schema `name` (empty: it matches)."""
    v = _validator(BASE + f'{name}.schema.json')
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]):
        field = '.'.join(str(p) for p in e.absolute_path) or '(top)'
        out.append({'field': field, 'message': e.message[:300]})
    return out


def kinds():
    return list(schema('common')['$defs']['kind']['enum'])


def inputs_properties(kind):
    """The inputs fields a kind's schema names (for 'field_ignored' warnings)."""
    try:
        return set(schema(f'kinds/{kind}')['$defs']['inputs'].get('properties', {}))
    except KeyError:
        return set()


def job_properties():
    return set(schema('job')['properties'])
