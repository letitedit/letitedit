"""MCP tool of the timing perception layer: letitedit_timing(source, view=...) with one view per kind of question
(the views register themselves in timing_views; TIMING-SPEC.md)."""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import time
import uuid
from pathlib import Path
from typing import Literal

import letitedit.server.compact_reply as compact_reply
import letitedit.timing.timing_views as timing_views

RESULTS = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'timing' / 'results'
BRIEF_LIST = 60          # lists longer than this are cut in detail='brief' (the full result is in result_file)

DOC = """Timing, motion and rhythm of an edit or a video as numbers and pictures you can read: where the cuts are
(exact frames), how much the picture moves once the camera's own move is removed, what the camera does, where the
eye goes, the shots and their sizes, loudness and sound onsets, and (when those modules are present) speech,
music beats and what happens in each movement. Nothing is edited (changes: []).

source: a project (.mlt, a managed episode/cut folder, or 'live' for the open editor) or a video file. A project is
analysed as the viewer gets it: a small preview render of its timeline with sound (melt, the export engine), cached
in chunks so a small edit re-renders and re-analyses only what changed. view: one of the views below.
start_s / end_s: the part to look at (timeline seconds). items: clip ids to look at (views that take them).
cuts: cut frames or times to look at (views that take them). options: the view's own options (each view lists
them in its result under 'options_used'); options.refresh = true recomputes the measurements;
options.settings = {lane: {key: value}} overrides measuring settings (defaults and every threshold used are in
bridge/timing_thresholds.json and in each result). detail: 'brief' (lists cut at 60 entries) or 'full'.
images: how many pictures come back inline (all are saved; their paths are in the result).

Every result carries: schema_version, result_id, project_revision (projects), source_fingerprints,
checked_ranges, unchecked_ranges, warnings, unsupported (what it cannot judge), preview_artifacts, changes: [],
result_file (the full result as JSON) and the view's numbers, each with its unit, method and threshold. Frames are
on the source's own grid; times are seconds; ranges are half-open [f0, f1).

The first call on a project renders the preview with melt, one chunk at a time, plus about 45 s of analysis for a
3-minute edit (measured cold: 3.5 minutes with 4 chunks side by side; one at a time, the default, expect up to
about 6-7 minutes); it holds the PC render lock while more than 30 s must be rendered. Later calls reuse
everything; after a small edit only the touched chunks are rendered and analysed again (a 1 s trim near the end of
that edit: 75 s). A video file needs no render.

Views:
"""


def _views_doc():
    try:
        vs = timing_views.views()
    except Exception as e:  # noqa: BLE001
        return f'  (views could not be listed: {e})'
    if not vs:
        return '  (no views registered)'
    return '\n'.join(f'  {name}: {summary}' for name, summary in vs.items())


def _cut_lists(x, n=BRIEF_LIST, depth=0):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if isinstance(v, list) and len(v) > n and depth < 6:
                out[k] = [_cut_lists(e, n, depth + 1) for e in v[:n]]
                out[k + '_cut'] = f'{len(v) - n} more in result_file'
            else:
                out[k] = _cut_lists(v, n, depth + 1)
        return out
    if isinstance(x, list):
        return [_cut_lists(e, n, depth + 1) for e in x]
    return x


def save_result(res):
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = f'{time.strftime("%Y%m%d-%H%M%S")}-{res.get("view", "view")}-{res.get("result_id") or uuid.uuid4().hex[:8]}.json'
    return compact_reply.write_json_atomic(RESULTS / name, res)    # whole before any reply is shortened


def timing(source, view='map', start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief',
           refresh=False):
    """Python form of the tool: the view's full result (images as paths)."""
    opts = dict(options or {})
    if refresh:
        opts['refresh'] = True
    res = timing_views.run(view, source, start_s, end_s, items, cuts, opts, detail)
    res['result_file'] = save_result(res)
    return res


JOINS_LISTED = 24      # joins listed one by one in a check's reply (all of them are in its file)


def joins_brief(source, start_s=None, end_s=None):
    """The sound at every join of a project (or a range of it) as letitedit_try and letitedit_check_range carry it:
    the 'joins' view's numbers without pictures, one short row per join. {verdict, joins, flagged, by_flag, at: [{t,
    kind, last_word, next_word, word_cut, problems}], file} or {error} when it could not be measured."""
    try:
        res = timing(source, view='joins', start_s=start_s, end_s=end_s, options={'images': 0})
    except Exception as exc:  # noqa: BLE001 - a measurement beside a check, never a reason to fail the check
        return {'error': f'joins not measured: {exc}'}
    summary = res.get('summary') or {}
    rows = []
    for j in (res.get('joins') or [])[:JOINS_LISTED]:
        words = j.get('words') or {}
        row = {'t': j.get('t'), 'kind': j.get('kind'), 'last_word': words.get('last_word'),
               'next_word': words.get('next_word')}
        if words.get('word_cut'):
            row['word_cut'] = words['word_cut']
        if j.get('problems'):
            row['problems'] = [p.get('text') for p in j['problems'] if p.get('text')]
        rows.append({k: v for k, v in row.items() if v is not None})
    flagged = int(summary.get('flagged') or 0)
    count = summary.get('joins', len(rows))
    out = {'verdict': ('no joins' if not count else 'clean' if not flagged else f'{flagged} of {count} joins flagged'),
           'joins': count, 'flagged': flagged, 'by_flag': summary.get('by_flag') or {},
           'at': rows, 'file': res.get('result_file')}
    if len(res.get('joins') or []) > JOINS_LISTED:
        out['not_listed'] = len(res['joins']) - JOINS_LISTED
    for key in ('warnings', 'unsupported'):
        if res.get(key):
            out[key] = res[key]
    return out


def joins_line(brief, flagged_listed=4):
    """joins_brief's result in one line: the verdict, then each flagged join's time, words and first problem."""
    if brief.get('error'):
        return brief['error']
    parts = []
    for row in brief.get('at') or []:
        if row.get('problems') and len(parts) < flagged_listed:
            words = f"{row.get('last_word') or '-'}|{row.get('next_word') or '-'}"
            parts.append(f"{row.get('t')} s {words}: {row['problems'][0]}")
    head = f"{brief.get('verdict')} ({brief.get('joins')} joins)"
    return head + (': ' + '; '.join(parts) if parts else '')


def compact(res, detail='brief'):
    """The MCP reply: detail='full' the whole result; 'brief' the result with lists cut at BRIEF_LIST, and past
    compact_reply.BUDGET characters the compact envelope (verdict, findings, what wasn't checked, the view's numbers
    shortened; result_file holds everything)."""
    if detail == 'full':
        return res
    return compact_reply.timing_reply(res, brief=_cut_lists(res))


def register(mcp, Image):
    def letitedit_timing(source: str, view: str = 'map', start_s: float | None = None, end_s: float | None = None,
                       items: list[str] | None = None, cuts: list | None = None, options: dict | None = None,
                       detail: Literal['brief', 'full'] = 'brief', images: int = 2, refresh: bool = False) -> list:
        try:
            res = timing(source, view=view, start_s=start_s, end_s=end_s, items=items, cuts=cuts, options=options,
                         detail=detail, refresh=refresh)
        except (FileNotFoundError, ValueError, KeyError) as e:
            return [{'error': str(e), 'views': timing_views.views()}]
        out = []
        for p in res.get('images') or []:
            if len(out) >= max(0, int(images)):
                break
            pp = Path(p)
            if pp.exists():
                fmt = 'png' if pp.suffix.lower() == '.png' else 'jpeg'
                out.append(Image(data=pp.read_bytes(), format=fmt))
        return out + [compact(res, detail)]
    letitedit_timing.__doc__ = DOC + _views_doc()
    return mcp.tool(structured_output=False)(letitedit_timing)
