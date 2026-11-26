"""capabilities.typical by the AI a job runs on (contract 1.2): each figure says the engine, model and effort it was
measured with, and a request for an AI with no figure of its own gets the nearest one, saying so.

Standard library only: the reference fake uses it too.
"""
from __future__ import annotations

EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
SAYS = {'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'extra high', 'max': 'max'}
BASIS_RANK = {'measured_here': 0, 'reference': 1, 'estimate': 2}


def effort_of(value):
    """The contract's effort word: 'extra high', 'extra-high' and 'xhigh' are one."""
    v = str(value or '').strip().lower().replace('-', ' ')
    return {'extra high': 'xhigh', 'x high': 'xhigh'}.get(v, v.replace(' ', '')) or None


def label(ai):
    """{engine, model, effort} of an `ai` (a job's choice or a result's cost.ai), only the parts it gives."""
    ai = ai or {}
    out = {}
    for k in ('engine', 'model', 'effort'):
        v = ai.get(k)
        if v:
            out[k] = effort_of(v) if k == 'effort' else str(v).strip().lower()
    return out


def key(ai):
    a = label(ai)
    return (a.get('engine'), a.get('model'), a.get('effort'))


def same_model(a, b):
    """One model under two spellings ('opus' and 'claude-opus-5-5')."""
    if not a or not b:
        return True
    a, b = a.lower(), b.lower()
    return a == b or a in b.split('-') or b in a.split('-')


def distance(have, want):
    """How far a figure measured with `have` is from `want`: (engine, model, effort steps); (9, 9, 9) for a figure
    that says no AI. Parts `want` leaves out don't count."""
    have, want = label(have), label(want)
    if not have:
        return (9, 9, 9)
    eng = int(bool(want.get('engine')) and have.get('engine') != want.get('engine'))
    mod = int(bool(want.get('model')) and not same_model(have.get('model'), want.get('model')))
    eff = 0
    if want.get('effort'):
        if have.get('effort') in EFFORTS and want['effort'] in EFFORTS:
            eff = abs(EFFORTS.index(have['effort']) - EFFORTS.index(want['effort']))
        elif have.get('effort') != want['effort']:
            eff = 5
    return (eng, mod, eff)


def says(ai):
    """'claude-opus-5-5 at high effort' (the model names its engine), or 'codex at medium effort'."""
    a = label(ai)
    who = a.get('model') or a.get('engine') or 'an AI'
    return who + (f" at {SAYS.get(a['effort'], a['effort'])} effort" if a.get('effort') else '')


def choose(candidates, want):
    """The figure for `want` among one kind and tier's candidates (each a typical figure, with `ai` when it was
    measured with one): the exact match, else the nearest (measured here before letitedit's reference before an
    estimate), with `match` and, for a nearest one, `match_note` saying what it stands in for. `by_ai` lists every
    candidate measured with an AI."""
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    want = label(want)
    if not want:                                       # a kind that runs no AI: its one figure, as it is
        best = dict(sorted(candidates, key=lambda c: (BASIS_RANK.get(c.get('basis'), 3), -int(c.get('samples') or 0)))[0])
        best.pop('match', None)
        return best
    scored = sorted(candidates, key=lambda c: (distance(c.get('ai'), want), BASIS_RANK.get(c.get('basis'), 3), -int(c.get('samples') or 0)))
    best = dict(scored[0])
    exact = bool(best.get('ai')) and distance(best['ai'], want) == (0, 0, 0)
    best['match'] = 'exact' if exact else 'nearest'
    if not exact:
        stand = f"No job of this kind has been measured with {says(want)} yet; " + (
            f"this figure is the nearest, measured with {says(best['ai'])} ({best.get('basis', 'estimate')})."
            if best.get('ai') else "this is letitedit's estimate, not measured with any AI.")
        best['match_note'] = stand
    with_ai = [dict(c) for c in candidates if c.get('ai')]
    for c in with_ai:
        c.pop('by_ai', None)
        c.pop('match', None)
        c.pop('match_note', None)
    if with_ai and (len(with_ai) > 1 or not exact):
        best['by_ai'] = with_ai
    return best


USES_AI = ('short', 'batch_shorts', 'still', 'revise', 'hooks', 'learn')


def choose_all(typical, want, measured=None):
    """capabilities.typical for `want`: every key's figure chosen from its reference (`typical`: a figure or a list of
    them, each with its `ai`) and the figures
    measured here (`measured`: {key: [figure, ...]}, each with `ai`). A kind that runs no AI ignores `want`."""
    out = {}
    for k in sorted(set(typical) | set(measured or {})):
        ref = typical.get(k)                         # one reference figure, or a list of them (one per AI)
        cands = (list(ref) if isinstance(ref, list) else [ref] if ref else []) + list((measured or {}).get(k) or [])
        got = choose(cands, want if k.split('.')[0] in USES_AI else None)
        if got:
            out[k] = got
    return out
