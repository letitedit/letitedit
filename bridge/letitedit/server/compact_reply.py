"""Compact check replies with the full evidence on disk (T295, the refactor plan's S04).

A check's MCP reply is read again on every later step of the conversation, so a long one costs its size many times
over. When a reply's JSON is longer than BUDGET characters, the tool returns an envelope instead:

    verdict      'failed' (the check did not produce its result) | 'problems' (a critical, major or error finding) |
                 'incomplete' (some part was not checked, see not_checked) | 'warnings' | 'ok', the first that applies
    complete     False whenever anything was not checked or failed: a partial check never reads as a full pass
    revision     what the result was made from (a project revision, result id or file hash), when known
    counts       the result's own counts (frames, cuts, versions, findings by severity ...)
    findings     every finding as {severity, what, at?, id?, source?}, most severe first; past the bound the rest
                 are in page files, listed in findings_pages with their counts by severity (never dropped)
    not_checked  what was not checked and why
    evidence     the files a reviewer opens (sheets, renders, PNG folders)
    detail       {file: the full result as JSON, written first and atomically, chars, cut: what this reply shortened,
                 how: how to read the rest}
    ...          then the result's own keys (the ones scripts and skills read: state, frames[].png, cuts, versions ...),
                 shortened to fit

On by default since T365 (real runs held the edit quality): the setting `compact_check_replies` (settings.json,
read through letitedit.core.hardware.settings()), overridden by LETITEDIT_COMPACT_REPLIES=1/0. Off, every *_reply
returns its input unchanged. A reply under the bound is returned exactly as before. Python callers (letitedit_ai's functions, timing(), checks.*)
are untouched: only the MCP replies change. If the detail file cannot be written, the full reply is returned with a
note, so nothing is lost.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

ENV = 'LETITEDIT_COMPACT_REPLIES'
SETTING = 'compact_check_replies'
BUDGET = 4000            # characters of a reply's JSON (two-space indent, as the server sends it); T286's cap
PAGE_FINDINGS = 40       # findings per page file
SEVERITY_ORDER = ('critical', 'major', 'error', 'minor', 'warning', 'note', 'info')
PROBLEM = ('critical', 'major', 'error')
WARNING = ('minor', 'warning')
# (list items kept, characters per string) tried in turn until the reply fits
# (text first: every item on a shorter line beats a few items on long ones)
STEPS = ((40, 400), (40, 200), (40, 120), (40, 90), (24, 90), (24, 70), (12, 70), (8, 60), (5, 60), (3, 50),
         (1, 50), (0, 50))


def enabled():
    """Whether check replies are compacted on this install: LETITEDIT_COMPACT_REPLIES=1/0 wins, else the setting
    compact_check_replies is not false; on by default (an unreadable setting means on)."""
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def chars(x):
    """Characters of x as the server sends a dict reply (two-space indented JSON)."""
    return len(json.dumps(x, indent=2, ensure_ascii=False, default=str))


def _root():
    from letitedit.core import paths as _paths
    return Path(os.environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)


def detail_folder(kind):
    cache = os.environ.get('LETITEDIT_CACHE') or str(_root() / 'cache')
    return Path(cache) / 'replies' / kind


def write_json_atomic(path, data):
    """Write data as JSON to path through a temporary file in the same folder and a rename: a reader never sees half
    a file. Returns the path as a string."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return str(path)


def write_detail(kind, full, path=None):
    """The full result on disk (atomically) before any reply is shortened. path: where (default: the cache's
    replies/<kind>/<time>-<content hash>.json, so a changed result never overwrites an earlier one)."""
    if path is None:
        digest = hashlib.sha1(json.dumps(full, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]
        path = detail_folder(kind) / f'{time.strftime("%Y%m%d-%H%M%S")}-{digest}.json'
    return write_json_atomic(path, full)


def open_detail(path, revision=None):
    """The full result behind a compact reply: {'result': dict | None, 'error': str | None, 'stale': bool}. stale:
    the file's revision differs from `revision` (the timeline changed since it was written)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        return {'result': None, 'error': f'{type(exc).__name__}: {exc}', 'stale': False}
    have = data.get('revision', data.get('project_revision')) if isinstance(data, dict) else None
    stale = revision is not None and have is not None and have != revision
    return {'result': data, 'error': None, 'stale': stale}


def file_revision(path):
    """A short hash of a project file's bytes (None when it can't be read)."""
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:12]
    except (OSError, TypeError, ValueError):
        return None


def finding(severity, what, at=None, id=None, source=None):
    f = {'severity': severity if severity in SEVERITY_ORDER else 'warning', 'what': str(what)}
    if at is not None:
        f['at'] = at
    if id is not None:
        f['id'] = id
    if source is not None:
        f['source'] = source
    return f


def _rank(f):
    try:
        return SEVERITY_ORDER.index(f.get('severity'))
    except ValueError:
        return len(SEVERITY_ORDER)


def sort_findings(findings):
    return sorted(findings or [], key=_rank)          # stable: same-severity findings keep their order


def by_severity(findings):
    out = {}
    for f in findings or []:
        out[f.get('severity', 'warning')] = out.get(f.get('severity', 'warning'), 0) + 1
    return {k: out[k] for k in sorted(out, key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 99)}


def verdict_of(findings, complete=True, failed=False):
    if failed:
        return 'failed'
    sev = {f.get('severity') for f in findings or []}
    if sev & set(PROBLEM):
        return 'problems'             # (complete says separately whether everything was checked)
    if not complete:
        return 'incomplete'           # never 'ok' when something wasn't checked
    if sev & set(WARNING):
        return 'warnings'
    return 'ok'


def _scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def _flat(d):
    """A record of plain values (one level of nested plain records allowed)."""
    return (isinstance(d, dict) and bool(d)
            and all(_scalar(v) or isinstance(v, dict) and all(_scalar(w) for w in v.values()) for v in d.values()))


def _line(d):
    """A flat record as one line, 'key=value; key=value' (None left out, a nested record as key.sub=value): a list
    of these is far shorter than the same records as indented JSON, and as easy to read."""
    parts = []
    for k, v in d.items():
        if isinstance(v, dict):
            parts += [f'{k}.{kk}={vv}' for kk, vv in v.items() if vv is not None]
        elif v is not None:
            parts.append(f'{k}={v}')
    return '; '.join(parts)


def _cut(x, items, text, depth=0, cut=None, path=''):
    """x with lists longer than `items` cut to their first `items` (a '<key>_more' note says how many more and where),
    lists of flat records as one line each, and strings longer than `text` cut (with their length)."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            p = f'{path}.{k}' if path else str(k)
            pair = len(v) <= 4 and all(isinstance(e, (int, float)) for e in v) if isinstance(v, list) else False
            if isinstance(v, list) and len(v) > items and not pair:      # (a range or a size stays whole)
                if items:
                    out[k] = _cut(v[:items], items, text, depth + 1, cut, p)
                    out[f'{k}_more'] = f'{len(v) - items} more, {len(v)} in all: detail.file'
                if cut is not None:
                    cut[p] = f'{items} of {len(v)} here'
            else:
                out[k] = _cut(v, items, text, depth + 1, cut, p)
        return out
    if isinstance(x, list):
        if len(x) > 1 and all(_flat(e) for e in x):
            return [_cut(_line(e), items, text, depth + 1, cut, path) for e in x]
        return [_cut(e, items, text, depth + 1, cut, path) for e in x]
    if isinstance(x, str) and len(x) > text + 16:      # (a line only a little longer stays whole)
        if cut is not None:
            cut.setdefault(path or '(text)', f'text cut to {text} of {len(x)} characters')
        return x[:text].rstrip() + f' ... ({len(x)} chars)'
    return x


def page_findings(findings, detail_file, room):
    """(shown, pages): the findings that fit in `room` characters, most severe first, and the page files holding the
    rest (each {file, count, by_severity}). Nothing is dropped: shown + every page = all findings."""
    ordered = sort_findings(findings)
    shown = []
    for f in ordered:
        if chars(shown + [f]) > room and shown:
            break
        shown.append(f)
    rest = ordered[len(shown):]
    pages = []
    if rest:
        base = str(detail_file)[:-5] if str(detail_file).endswith('.json') else str(detail_file)
        for k in range(0, len(rest), PAGE_FINDINGS):
            chunk = rest[k:k + PAGE_FINDINGS]
            p = write_json_atomic(f'{base}.findings-p{k // PAGE_FINDINGS + 2}.json',
                                  {'findings': chunk, 'first': len(shown) + k + 1, 'total': len(ordered)})
            pages.append({'file': p, 'count': len(chunk), 'by_severity': by_severity(chunk)})
    return shown, pages


def all_findings(reply):
    """Every finding of a compact reply: the ones shown plus every page file's (for checks and tests)."""
    out = list(reply.get('findings') or [])
    for pg in reply.get('findings_pages') or []:
        file = pg['file'] if isinstance(pg, dict) else pg.split(' | ', 1)[0]
        out += json.loads(Path(file).read_text(encoding='utf-8-sig'))['findings']
    return out


def _fallback(full, exc):
    out = dict(full) if isinstance(full, dict) else {'result': full}
    out['detail_error'] = f'the full result could not be saved ({type(exc).__name__}: {exc}), so it is all here'
    return out


def envelope(full, *, kind, assessed=None, revision=None, counts=None, evidence=None, body=None, keep=(),
             secondary=(), detail_file=None, how=None, budget=BUDGET, force=False, findings_share=0.5):
    """The reply for `full` (the tool's whole reply dict): `full` itself when it fits in `budget` characters, else
    the compact envelope described in this module's text. assessed: {findings, not_checked, complete, failed} (an
    assess_* function's result); body: the result's own keys to keep (shortened to fit; default: full); keep: body
    keys never shortened (small ones scripts read); secondary: body keys shortened first; detail_file: where the
    full result goes (default: the cache).
    If the detail or a findings page can't be written, `full` comes back with a 'detail_error' note."""
    if not force and chars(full) <= budget:
        return full
    a = assessed or {}
    findings = list(a.get('findings') or [])
    not_checked = list(a.get('not_checked') or [])
    failed = bool(a.get('failed'))
    complete = bool(a.get('complete', True)) and not failed and not not_checked
    try:
        detail_file = write_detail(kind, full, detail_file)
        head = {'verdict': verdict_of(findings, complete, failed), 'complete': complete}
        if revision is not None:
            head['revision'] = revision
        cnt = dict(counts or {})
        cnt['findings'] = len(findings)
        if findings:
            cnt['findings_by_severity'] = by_severity(findings)
        head['counts'] = cnt
        head['not_checked'] = not_checked
        if evidence:
            head['evidence'] = evidence
    except (OSError, TypeError, ValueError) as exc:
        return _fallback(full, exc)
    detail = {'file': detail_file, 'chars': chars(full),
              'how': how or 'detail.file: the full result as JSON'}
    src = dict(full if body is None else body)
    kept = {k: src.pop(k) for k in list(src) if k in keep}
    extra = {k: src.pop(k) for k in list(src) if k in secondary}
    best = None
    # findings get up to findings_share of the room (most severe first; the rest on pages), the result's own keys
    # the rest; if nothing fits, fewer findings are shown (every one stays on a page)
    for share in (findings_share, findings_share / 2, findings_share / 4, 0.0):
        try:
            shown, pages = page_findings(findings, detail_file,
                                         max(300 if share else 0, int(budget * share) - chars(head) // 2))
        except (OSError, TypeError, ValueError) as exc:
            return _fallback(full, exc)
        h = dict(head, findings=shown)
        if pages:
            h['findings_pages'] = [f"{p['file']} | {p['count']} | "
                                   + ', '.join(f'{k} {v}' for k, v in p['by_severity'].items()) for p in pages]
            h['findings_note'] = (f'{len(shown)} of {len(findings)} findings here, most severe first; the other '
                                  f'{len(findings) - len(shown)} are in the findings_pages files (file | count | '
                                  f'by severity)')
        # the result's main keys keep as much as fits; the secondary ones give way first
        for i, (items, text) in enumerate(STEPS):
            for items2, text2 in STEPS[i:]:
                cut = {}
                trimmed = _cut(src, items, text, cut=cut)
                trimmed2 = _cut(extra, items2, text2, cut=cut)
                out = {**h, 'detail': {**detail, 'cut': cut}, **kept, **trimmed, **trimmed2}
                if chars(out) <= budget:
                    best = out
                    break
            if best is not None:
                break
        if best is not None:
            break
    if best is None:        # still over: the body's keys as their sizes, everything is in detail.file
        detail['cut'] = {k: f'{chars(v)} chars, in detail.file' for k, v in {**src, **extra}.items()}
        best = {**h, 'detail': detail, **kept}
    return best


def is_stale(reply):
    """True when a compact reply's evidence was made from a project file that has changed since (its revision's
    file hash no longer matches), False when it matches, None when the reply carries no file hash."""
    rev = reply.get('revision') if isinstance(reply, dict) else None
    if not isinstance(rev, dict) or not rev.get('file') or not rev.get('project'):
        return None
    return file_revision(rev['project']) != rev['file']


# ---------------------------------------------------------------------------------------------- the tools' replies

def _short(text, n=200):
    text = str(text)
    return text if len(text) <= n else text[:n].rstrip() + f' ... ({len(text)} chars)'


def _assessed(findings=None, not_checked=None, complete=True, failed=False):
    return {'findings': list(findings or []), 'not_checked': list(not_checked or []),
            'complete': bool(complete) and not failed and not not_checked, 'failed': bool(failed)}


CUT_SEVERITY = {'jarring': 'major', 'noticeable': 'minor'}     # a 'cuts' view verdict as a finding's severity


def _cut_findings(res):
    """The 'cuts' view's own verdicts as findings: every jarring cut (major) and noticeable one (minor) with its
    reasons, as the full result lists them; cuts the counts name beyond the listed ones, and 'unknown' ones, as
    not checked. ([findings], [not_checked])."""
    cuts = [c for c in res.get('cuts') or [] if isinstance(c, dict) and c.get('verdict')]
    findings, not_checked = [], []
    for c in cuts:
        sev = CUT_SEVERITY.get(c['verdict'])
        if not sev:
            continue
        reasons = '; '.join(str(r) for r in c.get('reasons') or [])
        findings.append(finding(sev, _short(f"cut {c.get('n')} ({c.get('from_item')} -> {c.get('to_item')}): "
                                            f"{c['verdict']}" + (f" - {reasons}" if reasons else ''), 400),
                                at=c.get('t'), id=c.get('n'), source='cuts'))
    counts = res.get('counts') if isinstance(res.get('counts'), dict) else {}
    for verdict, sev in CUT_SEVERITY.items():
        listed = sum(1 for c in cuts if c.get('verdict') == verdict)
        more = int(counts.get(verdict) or 0) - listed
        if more > 0:
            findings.append(finding(sev, f'{more} more {verdict} cut(s) counted beyond the listed ones (in the result '
                                         f'file)', source='cuts'))
    if int(counts.get('unknown') or 0):
        not_checked.append(f"{counts['unknown']} cut(s) whose verdict is unknown")
    return findings, not_checked


def assess_timing(res):
    """A timing result's findings: its warnings, every lane that failed to measure (major, and not checked), its
    unchecked ranges (not checked), and a 'cuts' view's own verdicts (jarring major, noticeable minor)."""
    findings, not_checked = _cut_findings(res)
    for w in res.get('warnings') or []:
        text = w if isinstance(w, str) else json.dumps(w, default=str)
        findings.append(finding('warning', _short(text, 400)))       # 'lane: ...' names its lane itself
    for n, d in (res.get('lanes') or {}).items():
        if isinstance(d, dict) and d.get('error'):
            findings.append(finding('major', f'lane {n} did not measure: {_short(d["error"])}', source=n))
            not_checked.append(f'lane {n} (did not measure; see findings)')
    for r in res.get('unchecked_ranges') or []:
        not_checked.append(r if isinstance(r, dict) else {'range': r})
    failed = bool(res.get('error'))
    return _assessed(findings, not_checked, failed=failed)


def _map_lines(res):
    """The rhythm map's cuts, sections and shots as one short line each (units: seconds, frames; motion in px/frame
    with the camera removed; the measures and thresholds are in the full result)."""
    def num(v, fmt='{:g}'):
        return '-' if v is None else fmt.format(v) if isinstance(v, (int, float)) else str(v)
    out = {}
    if isinstance(res.get('cuts'), list):
        out['cuts'] = [f"{num(c.get('t'))} s (f{c.get('f')}) {c.get('kind') or 'cut'}; {c.get('action') or '-'}"
                       + (f"; beat {c['beat_offset_frames']:+d} f" if isinstance(c.get('beat_offset_frames'), int)
                          else '')
                       + (f"; size {c['size_change']}" if c.get('size_change') else '')
                       + f"; motion {num(c.get('motion_before'))}->{num(c.get('motion_after'))}"
                       if isinstance(c, dict) else c for c in res['cuts']]
    if isinstance(res.get('sections'), list):
        rows = []
        for sec in res['sections']:
            if not isinstance(sec, dict):
                rows.append(sec)
                continue
            n = sec.get('numbers') or {}
            rows.append(f"{sec.get('name') or 'section'} {num(sec.get('t0'))}-{num(sec.get('t1'))} s: "
                        f"{num(n.get('cuts'))} cuts, {num(n.get('cut_rate_per_min'))}/min, median shot "
                        f"{num(n.get('median_shot_s'))} s, longest {num(n.get('longest_shot_s'))} s, motion "
                        f"{num(n.get('motion_energy'))}, on action {num(n.get('cuts_on_action_share'))}, holds "
                        f"{num(n.get('holds'))}")
        out['sections'] = rows
    if isinstance(res.get('shots'), list):
        out['shots'] = [f"{s.get('item') or '-'} {num(s.get('t0'))}-{num(s.get('t1'))} s {s.get('size') or '?'}"
                        + (' black' if s.get('black') else '') if isinstance(s, dict) else s for s in res['shots']]
    return out


def _next_step_keep(res, body):
    import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
    import letitedit.app.work_in_passes as work_in_passes              # T353, behind its own switch
    return next_step_replies.timing_keep(res, body) + work_in_passes.timing_pace(res, body)


def timing_reply(res, brief=None, budget=BUDGET):
    """letitedit_timing's reply (detail='brief'): `brief` (today's reply: res with long lists cut) when it fits, else
    the envelope; res is the whole result, which result_file holds."""
    brief = res if brief is None else brief
    if not enabled():
        return brief
    if not isinstance(res, dict) or chars(brief) <= budget:
        return brief
    lanes = res.get('lanes') or {}
    counts = {k: len(res[k]) for k in ('cuts', 'shots', 'sections', 'pages', 'images') if isinstance(res.get(k), list)}
    cr = res.get('checked_ranges') or []
    body = {k: v for k, v in res.items() if k not in (
        'warnings', 'lanes', 'unchecked_ranges', 'unsupported', 'source_fingerprints', 'preview_artifacts',
        'checked_ranges', 'measures', 'thresholds', 'options_used', 'images', 'result_file', 'render',
        'result_id', 'project_revision', 'schema_version')}       # the ids are in revision
    body['unsupported'] = [_short(u, 160) for u in res.get('unsupported') or []]
    body['checked_ranges'] = cr if chars(cr) <= 300 else f'{len(cr)} ranges (in detail.file)'
    if lanes:
        body['lanes_ok'] = sorted(n for n, d in lanes.items() if not (isinstance(d, dict) and d.get('error')))
    if res.get('view') == 'map':
        body.update(_map_lines(res))
    revision = {k: res.get(k) for k in ('project_revision', 'result_id') if res.get(k) is not None} or None
    render = res.get('render')
    return envelope(res, kind='timing', assessed=assess_timing(res), revision=revision, counts=counts,
                    evidence={'images': res.get('images') or [],
                              'render': render.get('file') if isinstance(render, dict) else render},
                    body=body, keep=('view', 'changes', 'summary') + _next_step_keep(res, body),
                    secondary=('pages', 'shots', 'checked_ranges', 'lanes_ok', 'speech_source', 'music', 'analysis_seconds',
                               'seconds'),
                    detail_file=res.get('result_file'), budget=budget, force=True, findings_share=0.34,
                    how="detail.file (= result_file): the whole view with its methods and thresholds; or detail='full'")


def _version_id(r):
    return f"{r.get('n')}. {r.get('label')}"


def assess_try(info):
    """Versions side by side: the project changing is critical; a version that failed (or lost frames) is major and
    not checked; the apply's notes are notes."""
    findings, not_checked = [], []
    if info.get('original_unchanged') is False:
        findings.append(finding('critical', 'the project file changed while the versions were made (it should not)',
                                source='original_unchanged'))
    for r in info.get('versions') or []:
        vid = _version_id(r)
        if r.get('error'):
            findings.append(finding('major', _short(r['error'], 300), id=vid, source='version'))
            not_checked.append(f'version {vid}: {_short(r["error"], 120)}')
        for note in (r.get('applied') or {}).get('notes') or []:
            findings.append(finding('note', _short(note, 300), id=vid, source='apply'))
        miss = [f.get('time') for f in r.get('frames') or [] if not f.get('png')]
        if miss:
            findings.append(finding('major', f'{len(miss)} frame(s) not rendered', at=miss, id=vid, source='frames'))
            not_checked.append(f'version {vid}: frames at {miss} not rendered')
    return _assessed(findings, not_checked)


def _version_row(r, folder=None):
    """One version as one line: number and label, error, length, span, change and note counts, frame times,
    loudness, the words said (cut)."""
    def g(v):
        return f'{v:g}' if isinstance(v, (int, float)) else str(v)
    parts = [f"{r.get('n')}. {r.get('label')}"]
    if r.get('error'):
        parts.append(f"ERROR {_short(r['error'], 140)}")
    if r.get('length_s') is not None:
        parts.append(f"length {g(r['length_s'])} s")
    if isinstance(r.get('span'), list) and len(r['span']) == 2:
        parts.append(f"span {g(r['span'][0])}-{g(r['span'][1])} s")
    applied = r.get('applied') or {}
    if applied:
        parts.append(f"{len(applied.get('changes') or [])} changes"
                     + (f", {len(applied['notes'])} notes" if applied.get('notes') else ''))
    if r.get('frames'):
        parts.append('frames at ' + ', '.join(g(f.get('time')) for f in r['frames']))
        pngs = [f.get('png') for f in r['frames'] if f.get('png')]
        if pngs:
            where = str(Path(pngs[0]).parent)
            if folder and where.startswith(str(folder)):
                where = where[len(str(folder)):].lstrip('/\\') or '.'
            parts.append(f'pngs {where}')
    loud = r.get('loudness')
    if isinstance(loud, dict):
        nums = [f'{k} {g(v)}' for k, v in loud.items() if k in ('integrated', 'lra', 'true_peak', 'short_term_max',
                                                                 'momentary_max') and v is not None]
        if nums:
            parts.append('loudness ' + ', '.join(nums))
    words = r['words'].get('text') if isinstance(r.get('words'), dict) else None
    if words:
        parts.append(f'said "{_short(words, 90)}"')
    return ' | '.join(parts)


def try_reply(info, budget=BUDGET):
    """letitedit_try's reply: per version its label, errors, length, span, frame times, words, loudness numbers and
    change count; the sheets stay inline; try.json in the version folder holds everything."""
    if not enabled():
        return info
    if not isinstance(info, dict):
        return info
    rows = info.get('versions') or []
    body = {k: v for k, v in info.items() if k not in ('versions', 'defaults', 'render', 'lanes')}
    folder = info.get('folder')
    body['versions'] = [_version_row(r, folder) for r in rows]
    return envelope(info, kind='try', assessed=assess_try(info),
                    revision={'project': info.get('project'), 'file': file_revision(info.get('project'))},
                    counts={'versions': len(rows), 'rendered': sum(1 for r in rows if r.get('frames')),
                            'sheets': len(info.get('sheets') or [])},
                    evidence={k: info.get(k) for k in ('sheets', 'mp4', 'folder') if info.get(k)},
                    body=body, keep=('project', 'read', 'original_unchanged', 'sheets', 'mp4', 'note'),
                    secondary=('mp4_parts', 'align', 'lanes', 'per_row', 'size', 'seconds', 'folder'),
                    detail_file=str(Path(folder) / 'try.json') if folder else None, budget=budget,
                    how='detail.file: every version whole (changes, frame PNGs, timed words, loudness, lanes)')


def assess_look(info):
    findings = [finding('major', _short(it['error'], 300), id=i + 1, source='item')
                for i, it in enumerate(info.get('items') or []) if isinstance(it, dict) and it.get('error')]
    return _assessed(findings, [f"item {f['id']}: {f['what']}" for f in findings])


def look_reply(info, budget=BUDGET):
    """letitedit_look's reply: the items' sources and frame times; look.json in the folder holds everything."""
    if not enabled():
        return info
    if not isinstance(info, dict):
        return info
    folder = info.get('folder')
    return envelope(info, kind='look', assessed=assess_look(info),
                    counts={'items': len(info.get('items') or []), 'sheets': len(info.get('sheets') or [])},
                    evidence={k: info.get(k) for k in ('sheets', 'folder') if info.get(k)},
                    body={k: v for k, v in info.items() if k != 'defaults'}, keep=('sheets', 'folder'),
                    detail_file=str(Path(folder) / 'look.json') if folder else None, budget=budget)


def assess_check_frames(info):
    """Frames or a storyboard: a frame without a picture is major and not checked; a code scene that could not be
    drawn is major; a stack warning (stack=True) is a warning at its frame's time."""
    findings, not_checked = [], []
    frames = info.get('frames') or []
    missing = [f.get('time') for f in frames if isinstance(f, dict) and 'png' in f and not f.get('png')]
    if missing:
        findings.append(finding('major', f'{len(missing)} frame(s) not rendered', at=missing, source='frames'))
        not_checked.append(f'frames at {missing} not rendered')
    scenes = info.get('code_scenes')
    rows = scenes if isinstance(scenes, list) else (scenes.get('scenes') if isinstance(scenes, dict) else None)
    for sc in rows or []:
        if isinstance(sc, dict) and sc.get('not_drawn'):          # code_scenes' scenes.json rows
            findings.append(finding('major', 'code scene not drawn: ' + _short(sc['not_drawn']),
                                    id=sc.get('scene'), source='code_scenes'))
            not_checked.append(f"code scene {sc.get('scene')}: not drawn")
    for f in frames:
        stack = f.get('stack') if isinstance(f, dict) else None
        for line in stack.splitlines() if isinstance(stack, str) else []:
            if line.startswith('warning: '):
                findings.append(finding('warning', _short(line[9:], 240), at=f.get('time'), source='stack'))
    return _assessed(findings, not_checked)


def check_frames_reply(info, budget=BUDGET):
    """letitedit_check_frames' reply (frames or storyboard): every frame's time and PNG (what it shows cut to fit;
    the sheet's labels show it whole); frames.json beside the sheets holds everything."""
    if not enabled():
        return info
    if not isinstance(info, dict):
        return info
    frames = info.get('frames') or []
    sheets = info.get('sheets') or ([info['sheet']] if info.get('sheet') else [])
    body = {k: v for k, v in info.items() if k != 'frames'}
    first_png = next((f.get('png') for f in frames if isinstance(f, dict) and f.get('png')), None)
    png_folder = str(Path(first_png).parent) if first_png else None

    def row(f):
        if not isinstance(f, dict):
            return f
        png = f.get('png')
        if png and png_folder and str(Path(png).parent) == png_folder:
            png = Path(png).name
        r = {'time': f.get('time'), 'png': png or 'NOT RENDERED'}
        if f.get('zones_png'):
            r['zones_png'] = Path(f['zones_png']).name
        if f.get('shows'):
            r['shows'] = _short(f['shows'], 60)
        return _line(r)
    # every frame stays, one line each (the sheet's labels show what each frame shows in full)
    body['frames'] = [row(f) for f in frames]
    if chars(body['frames']) > budget // 2:
        body['frames'] = [_line({'time': f.get('time'), 'png': Path(f['png']).name if f.get('png') else 'NOT RENDERED'})
                          if isinstance(f, dict) else f for f in frames]
    folder = str(Path(sheets[0]).parent) if sheets else None
    return envelope(info, kind='check_frames', assessed=assess_check_frames(info),
                    revision={'project': info.get('project'), 'file': file_revision(info.get('project'))},
                    counts={'frames': len(frames), 'sheets': len(sheets)},
                    evidence={'sheets': sheets, 'png_folder': png_folder},
                    body=body, keep=('project', 'read', 'sheet', 'sheets', 'rendered_by', 'covered_areas', 'frames'),
                    detail_file=str(Path(folder) / 'frames.json') if folder else None, budget=budget,
                    how='detail.file: every frame whole (stack layers when asked, code scenes); each png is full '
                        'size, in evidence.png_folder')


def assess_export_job(st):
    """An export status: a failed, cancelled or interrupted export is critical and failed; each pre-export finding
    keeps its severity; a stretch where the picture stays nearly still or the sound sits away from its level is a
    note; a pre-export check that couldn't run and a measurement that wasn't made are not checked; a job still
    running is not complete."""
    findings, not_checked = [], []
    state = st.get('state')
    failed = state in ('failed', 'error', 'cancelled', 'interrupted')
    if failed:
        findings.append(finding('critical', f"export {state}: {_short(st.get('error') or st.get('message') or '', 300)}",
                                id=st.get('job_id'), source='export'))
    pre = st.get('preexport_checks') if isinstance(st.get('preexport_checks'), dict) else {}
    for f in pre.get('findings') or []:
        f = f if isinstance(f, dict) else {'problem': str(f)}
        findings.append(finding(f.get('severity') or 'warning', f.get('problem') or json.dumps(f, default=str),
                                at=f.get('at') or f.get('time'), id=f.get('id') or f.get('device'),
                                source='preexport'))
    for u in pre.get('unavailable') or []:          # export_checks: [{device, check, reason}]
        not_checked.append(f"pre-export: {u.get('check')} ({_short(u.get('reason'), 120)})" if isinstance(u, dict)
                           else f'pre-export: {u}')
    if pre.get('error'):
        not_checked.append(f"pre-export checks: {_short(pre['error'], 160)}")
    pc, sc = st.get('picture_change'), st.get('sound_change')     # checks.picture_change / checks.sound_change
    for r in (pc.get('still_stretches') or []) if isinstance(pc, dict) else []:
        if isinstance(r, dict):
            findings.append(finding('note', f"picture nearly still {r.get('from')}-{r.get('to')} ({r.get('s')} s)",
                                    at=r.get('from'), source='picture_change'))
    for kind in ('louder', 'quieter'):
        for r in (sc.get(f'{kind}_stretches') or []) if isinstance(sc, dict) else []:
            if isinstance(r, dict):
                findings.append(finding('note', f"sound {kind} than its typical level {r.get('from')}-{r.get('to')} "
                                                f"({r.get('lufs')} LUFS)", at=r.get('from'), source='sound_change'))
    if isinstance(sc, dict) and sc.get('tones_finding'):
        findings.append(finding('warning', _short(sc['tones_finding'], 300), source='sound_change'))
    for k in ('picture_change', 'sound_change'):
        if isinstance(st.get(k), str) and st[k].startswith('not measured'):
            not_checked.append(f'{k}: {_short(st[k], 160)}')
    return _assessed(findings, not_checked, complete=state == 'done' or failed, failed=failed)


def export_job_reply(st, budget=BUDGET):
    """letitedit_export_job's reply: the job's state and output, pre-export findings, the measured picture and sound
    change as numbers; the full status is in the cache's replies/export_job folder."""
    if not enabled():
        return st
    if not isinstance(st, dict) or 'state' not in st:
        return st
    pre = st.get('preexport_checks') if isinstance(st.get('preexport_checks'), dict) else {}
    body = {k: v for k, v in st.items() if k not in ('chunks_done', 'chunks_total', 'chunks_reused')}  # in counts
    if pre:                       # its findings are the envelope's findings (and every one is in pre['file'])
        body['preexport_checks'] = {k: v for k, v in pre.items() if k not in ('findings', 'unavailable')}
    return envelope(st, kind='export_job', assessed=assess_export_job(st), revision={'job_id': st.get('job_id')},
                    body=body,
                    counts={k: st[k] for k in ('chunks_done', 'chunks_total', 'chunks_reused') if k in st},
                    evidence={'output': st.get('output'), 'checks_file': pre.get('file')},
                    keep=('job_id', 'state', 'message', 'progress', 'output', 'project', 'error', 'preexport_checks'),
                    secondary=('picture_change', 'sound_change', 'updated', 'result', 'credits'), budget=budget,
                    findings_share=0.75,
                    how='detail.file: the whole status (every loudness and picture-change reading); '
                        'preexport_checks.file: every pre-export check')


JOURNAL_FULL_ENTRIES = 5     # the newest entries a long journal read keeps whole


def journal_reply(out, slim_entry, budget=BUDGET):
    """letitedit_journal's read past the bound: the newest JOURNAL_FULL_ENTRIES entries whole, older ones as slim
    entries (an apply's change list as a count, a long note cut) and, if still too long, the oldest left to
    journal.md; journal.md and journal.jsonl hold everything, detail.file this read in full."""
    if not enabled():
        return out
    if not isinstance(out, dict) or 'entries' not in out or chars(out) <= budget:
        return out
    entries = list(out.get('entries') or [])
    whole = max(0, len(entries) - JOURNAL_FULL_ENTRIES)
    shown = [slim_entry(e) for e in entries[:whole]] + entries[whole:]
    folder = out.get('folder')
    keep = ('project', 'folder', 'lease', 'owners', 'stages', 'entries')
    rest = {k: v for k, v in out.items() if k not in ('entries',)}
    while len(shown) > 1 and chars({**rest, 'entries': shown}) + 900 > budget:
        shown = shown[1:]                       # the oldest goes first: journal.md keeps it
    # the newest entry is never cut ('read' returns the full note): a very long one makes a long reply
    left_out = len(entries) - len(shown)
    body = {**rest, 'entries': shown}
    if left_out:
        body['entries_note'] = (f'the newest {len(shown)} of {len(entries)} entries; the {left_out} older ones are '
                                f'in journal.md in {folder} (and detail.file)')
    elif whole:
        body['entries_note'] = f'the {whole} older entries are slim; journal.md in {folder} has them whole'
    return envelope(out, kind='journal', counts={'entries': len(entries), 'shown': len(shown)}, body=body,
                    keep=keep + ('entries_note',), budget=budget, force=True,
                    how=f'journal.md in {folder}: every entry whole; detail.file: this read whole')


def is_compact(x):
    return (isinstance(x, dict) and isinstance(x.get('detail'), dict) and 'file' in x['detail']
            and 'verdict' in x and 'complete' in x)


def expand(out):
    """A tool's reply with every compact envelope replaced by the full result it was made from (letitedit_ai's
    Python callers get today's whole replies). An envelope whose detail file can't be read stays as it is."""
    if isinstance(out, list):
        return [expand(x) for x in out]
    if is_compact(out):
        got = open_detail(out['detail']['file'])
        if isinstance(got['result'], dict):
            return got['result']
    return out


__all__ = ['BUDGET', 'ENV', 'SETTING', 'enabled', 'chars', 'envelope', 'finding', 'write_detail', 'open_detail', 'all_findings', 'expand',
           'is_compact', 'is_stale', 'assess_timing', 'assess_try', 'assess_look', 'assess_check_frames',
           'assess_export_job', 'timing_reply', 'try_reply', 'look_reply', 'check_frames_reply', 'export_job_reply',
           'journal_reply']
