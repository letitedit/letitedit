"""Replies that carry what the next step reads, and calls that take the shapes an AI sends (T345 C2; T344's levers
4, 13, 14, 15 and 16). On by default.

    enabled()                      the switch
    describe(name, text)           a tool's short text with the facts an AI otherwise looked up in the guide mid-phase
    fit_bin(add, markers)          bin entries without a file but with a text and a time are markers
    fit_try(versions, start_s, end_s, align)   a version's `name` is its label; start_s/end_s line the versions up
    fit_hooks(entries)             an added hook's own label and an approach outside the list kept as its words
    sheet_width(px)                the width of a timeline_apply reply's automatic frames
    after_apply(result, before, after)   timeline_apply's reply gets the tracks the edit changed (`after`)
    timing_keep(res)               the keys a compact timing reply keeps whole (the per-cut summary `text`)
    bin_reply / caption_fit_reply / soundtrack_reply   about a third of the text: every marker, problem and finding
                                   still listed (one line each), the rest shortened, the whole reply on disk
    looks_get_reply                a Look's card without its empty fields and example paths (its recipe text whole)
    heard_at_cuts(info) / heard_for_version(row)   check_range's joins and edges, and each try version's joins, with
                                   the words heard on their own render

The switch: settings.json `next_step_replies` (default true; LETITEDIT_NEXT_STEP_REPLIES, 1 or 0, wins). Tool texts
and arguments are read when the tool server starts; replies follow the switch at each call. Off, every function here
returns its input unchanged and the tools' texts, arguments and replies are exactly as before.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTING = 'next_step_replies'
ENV = 'LETITEDIT_NEXT_STEP_REPLIES'

SHARE = 3                 # a long reply is sent at about 1/SHARE of its own size ...
SHORT_MIN = 1500          # ... when it is longer than this many characters (shorter ones are sent whole)
SHORT_FLOOR = 1200        # ... and never in fewer than this
TRACKS_CHARS = 3000       # the changed tracks' script carried inline in an apply's reply; past it, the file has it all
WORDS_PAD_S = 1.0         # the words around a change on the main picture track: this long before and after it
WORDS_MAX = 80            # words listed inline (the rest are counted)


def enabled():
    """settings.json next_step_replies (default true); LETITEDIT_NEXT_STEP_REPLIES (1 or 0) wins."""
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


# ------------------------------------------------------------------------------------- tool texts (lever 16, 4, 15)

DESCRIBED = {
    'letitedit_bin': " add: subclips [{file, in, out, name, note, color, folder}]; markers: [{at | start, end?, text, "
                     "color?}]; remove: marker ids or names. An add entry with a text and a time but no file is a "
                     "marker. Without arguments: everything there now.",
    'letitedit_look': " items: [{file | project, times | range (+ count | every_s) | nothing (the whole source), crop?, "
                      "label?, lanes?, pad?, span?}].",
    'letitedit_try': " versions: [{label (or name), changes | code}]; start_s and end_s (timeline seconds, together) "
                     "line the versions up on that span (align: {range: [start_s, end_s]}). With joins, each "
                     "version's joins carry `heard`: the words heard on its own render (transcribed), each join "
                     "marked |t| where it falls, and heard_before / heard_after / heard_inside per join.",
    'letitedit_check_range': " With joins, `heard`: the words heard on the render itself (transcribed, timeline "
                             "seconds), every listed join and clip edge marked |t| where it falls, and heard_before / "
                             "heard_after / heard_inside on each listed join and edge.",
    'letitedit_hooks': " add: [{from: <id> | id: <id> | source: {clip, in, out}, text: [1-3 options], label?, approach?, "
                       "why?}]; an approach outside the list is kept as the label (the approach is then quote).",
    'letitedit_timeline_apply': " The changes run in order, each on the timeline the ones before it left (ids stay "
                                "the same), and the whole list is one undo step. Every change is checked before "
                                "anything is written: a refused apply names the op, the field and what it takes, and "
                                "writes nothing. With check, the reply's `after` gives the script of the tracks "
                                "the ops name that changed, names the other tracks that changed, and lists the words "
                                "said around a change on the main picture track.",
    'letitedit_timing': " A compact reply keeps the per-cut summary (`text`, one line per cut) whole.",
}


def describe(name, text):
    """`text` (a tool's short description) with what DESCRIBED adds for it, when the switch is on."""
    extra = DESCRIBED.get(name)
    if not extra or not enabled() or extra.strip() in (text or ''):
        return text
    return (text or '').rstrip() + extra


# ------------------------------------------------------------------------------------- calls that fit (lever 16)

def _is_marker(entry):
    return (isinstance(entry, dict) and not entry.get('file') and entry.get('text') is not None
            and any(entry.get(k) is not None for k in ('at', 'start')))


def fit_bin(add, markers):
    """(add, markers, note): bin `add` entries that have a text and a time (at | start) but no file go to `markers`
    (a subclip needs a file). note: what was moved, or None. Off, or nothing to move: the inputs as given."""
    if not enabled() or not isinstance(add, list):
        return add, markers, None
    moved = [e for e in add if _is_marker(e)]
    if not moved:
        return add, markers, None
    keep = [e for e in add if not _is_marker(e)]
    markers = list(markers or []) + [{k: v for k, v in e.items() if k in ('at', 'start', 'end', 'text', 'color')}
                                     for e in moved]
    return keep or None, markers, f'{len(moved)} add entries with a text and a time but no file went in as markers'


def fit_try(versions, start_s=None, end_s=None, align=None):
    """(versions, align): a version's `name` becomes its label when it has none; start_s / end_s become
    align {'range': [start_s, end_s]} when no align is given (the two go together)."""
    if not enabled():
        return versions, align
    out = []
    for v in versions or []:
        if isinstance(v, dict) and v.get('name') and not v.get('label'):
            v = {**{k: x for k, x in v.items() if k != 'name'}, 'label': v['name']}
        out.append(v)
    if align is None and (start_s is not None or end_s is not None):
        if start_s is None or end_s is None:
            raise ValueError("start_s and end_s go together (the span the versions line up on); or give align: "
                             "{'at': [s], pad} | {'words': phrase} | {'id': clip id} | {'range': [a, b]}")
        align = {'range': [float(start_s), float(end_s)]}
    return out, align


def fit_hooks(entries, approaches):
    """letitedit_hooks' add entries: an entry's own `label` is kept (`label_given`), and an approach outside
    `approaches` is kept in its own words as the label (the approach itself then defaults to 'quote')."""
    if not enabled() or not isinstance(entries, list):
        return entries
    out = []
    for e in entries:
        if isinstance(e, dict):
            if e.get('approach') and e['approach'] not in approaches:
                e = {**e, 'approach': 'quote', 'label': e.get('label') or str(e['approach'])}
            if e.get('label'):
                e = {**e, 'label_given': True}
        out.append(e)
    return out


# --------------------------------------------------------------------------------- timeline_apply (levers 4, 14)

def sheet_width(px):
    """An apply reply's automatic frames: half the width (a quarter of the pixels) with the switch on."""
    return max(120, int(px) // 2) if enabled() else px


def _seconds(x):
    import letitedit.timeline.edit_script as es
    return es.to_seconds(x)


def _main(script):
    return next((t for t in script.get('tracks') or [] if t.get('kind', 'video') == 'video'), None)


def named_tracks(before, changes):
    """The track names the ops in `changes` name themselves: their `track` (or list of them), an added or changed
    track's `name`, and the track of every clip id they edit (`id`, `ids`) in script `before`."""
    where = {it.get('id'): t.get('name') for t in before.get('tracks') or [] for it in t.get('items') or []
             if 'id' in it}
    names = set()
    for op in changes or []:
        if not isinstance(op, dict):
            continue
        tr = op.get('track')
        names.update([tr] if isinstance(tr, str) else [x for x in tr or [] if isinstance(x, str)]
                     if isinstance(tr, list) else [])
        if op.get('op') in ('add_track', 'track') and isinstance(op.get('name'), str):
            names.add(op['name'])
        for i in [op.get('id')] + list(op.get('ids') or []):
            if i in where:
                names.add(where[i])
    return names


def changed_tracks(before, after, changes=None):
    """{'tracks': [...], 'captions': [...], 'moved': [...], 'removed': [...]}: the tracks (other than the main picture
    track) and caption tracks of script `after` that differ from `before` or are new. With `changes` (the ops), a
    changed track the ops don't name (one that moved with its picture, music a score op levelled) is only named in
    `moved`."""
    main = (_main(after) or {}).get('name')
    named = None if changes is None else named_tracks(before, changes)
    old = {t.get('name'): t for t in before.get('tracks') or []}
    new = {t.get('name'): t for t in after.get('tracks') or []}
    diff = [t for n, t in new.items() if n != main and old.get(n) != t]
    oc = {c.get('track'): c for c in before.get('captions') or []}
    cdiff = [c for c in after.get('captions') or [] if oc.get(c.get('track')) != c]
    tracks = [t for t in diff if named is None or t.get('name') in named or t.get('name') not in old]
    caps = [c for c in cdiff if named is None or c.get('track') in named or c.get('track') not in oc]
    out = {}
    if tracks:
        out['tracks'] = tracks
    if caps:
        out['captions'] = caps
    moved = sorted({t.get('name') for t in diff if t not in tracks} | {c.get('track') for c in cdiff if c not in caps})
    if moved:
        out['moved'] = moved
    removed = sorted(n for n in old if n not in new)
    if removed:
        out['removed'] = removed
    return out


def _same(item):
    """An item without what moves when the clips before it change (its place, length on the timeline, words heard)."""
    return {k: v for k, v in item.items() if k not in ('at', 'pin', 'len', 'from', 'said', 'recorded')}


def _main_changes(before, after):
    """[(start, end)] timeline seconds of the main picture track's items that are new or changed in `after`."""
    mb, ma = _main(before), _main(after)
    if ma is None:
        return []
    old = {it.get('id'): it for it in (mb or {}).get('items') or [] if 'id' in it}
    spans = []
    for it in ma.get('items') or []:
        if 'id' not in it or 'at' not in it:
            continue
        o = old.get(it['id'])
        if o is None or _same(o) != _same(it):
            a = _seconds(it['at'])
            spans.append((a, a + float(it.get('len') or 0)))
    gone = [it for i, it in old.items() if i not in {x.get('id') for x in ma.get('items') or []}]
    if gone and not spans:          # a delete that closed its gap: the join it left
        for it in gone:
            a = _seconds(it['at']) if 'at' in it else None
            if a is not None:
                spans.append((a, a))
    return spans


def words_around(after, spans):
    """The words said on the timeline around `spans` (WORDS_PAD_S each side), per word, as one line
    't0-t1 word' each with its clip id, and '|' where a main-track cut falls between two words."""
    from letitedit.timeline.timeline_speech import timeline_words
    if not spans:
        return None
    lo = max(0.0, min(a for a, _ in spans) - WORDS_PAD_S)
    hi = max(b for _, b in spans) + WORDS_PAD_S
    ws = timeline_words(after, lo, hi, heard=True)
    if not ws:
        return {'range': [round(lo, 2), round(hi, 2)], 'text': 'nothing is said there'}
    lines, last = [], None
    for w in ws[:WORDS_MAX]:
        if last is not None and w.get('id') != last:
            lines.append('| cut')
        lines.append(f"{w['t0']:.2f}-{w['t1']:.2f} {w['w']} [{w.get('id')}]")
        last = w.get('id')
    out = {'range': [round(lo, 2), round(hi, 2)], 'words': lines}
    if len(ws) > WORDS_MAX:
        out['more_words'] = len(ws) - WORDS_MAX
    return out


def after_apply(result, before, after, project=None, changes=None):
    """With the switch on, result['after'] = the tracks the edit's ops name that it changed (their script, compact
    YAML; past TRACKS_CHARS characters a file holds it whole), the other tracks it changed by name (`also_changed`),
    and the words said around changes on the main picture track. `before` and
    `after` are scripts or project files. Never fails the edit, which is already made."""
    if not enabled() or not isinstance(result, dict) or before is None or after is None:
        return result
    try:
        import letitedit.timeline.edit_script as es
        a = es.read(after) if isinstance(after, (str, Path)) else after
        b = es.read(before) if isinstance(before, (str, Path)) else before
        out = {}
        changed = changed_tracks(b, a, changes)
        if changed.get('tracks') or changed.get('captions'):
            part = {'tracks': changed.get('tracks') or []}      # the script's own shape (to_yaml reads tracks)
            shown = {'tracks': es.compact(part)['tracks']}      # long keyframe lists folded ...
            if changed.get('captions'):         # ... captions whole: their words are what a caption pass reads
                part['captions'] = shown['captions'] = changed['captions']
            lines = es.to_yaml(shown).splitlines()
            while lines and lines[0].startswith('#'):      # the script's header (how to read and edit it)
                lines.pop(0)
            text = chr(10).join(lines) + chr(10)
            if len(text) > TRACKS_CHARS:
                import letitedit.server.compact_reply as compact_reply
                file = compact_reply.write_detail('apply-tracks', {'project': str(project or a.get('project')),
                                                                   'yaml': es.to_yaml(part)})
                out['tracks_file'] = file
                out['tracks_chars'] = len(text)
                text = text[:TRACKS_CHARS].rsplit('\n', 1)[0] + '\n# ... the rest in tracks_file'
            out['tracks'] = text
        if changed.get('moved'):
            out['also_changed'] = changed['moved']
        if changed.get('removed'):
            out['removed_tracks'] = changed['removed']
        said = words_around(a, _main_changes(b, a))
        if said:
            out['words'] = said
        if out:
            result['after'] = out
    except Exception as exc:  # noqa: BLE001 - a reading in the reply, never a reason to fail an edit that is made
        result['after_error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
    return result


# ----------------------------------------------------------------------------------------------- timing (lever 4)

TEXT_LINES = 40           # per-cut summary lines a compact timing reply keeps (the rest are counted)
TEXT_LINE_CHARS = 260     # ... each cut to this length


def timing_keep(res, body):
    """Keys a compact timing reply keeps whole besides its own: the per-cut summary `text` of a view that has one, as
    its first TEXT_LINES lines (each at most TEXT_LINE_CHARS) written into `body`; the result file has it whole."""
    if not (enabled() and isinstance(res, dict) and isinstance(res.get('text'), str) and isinstance(body, dict)):
        return ()
    lines = [ln.rstrip() for ln in res['text'].splitlines() if ln.strip()]
    shown = [ln if len(ln) <= TEXT_LINE_CHARS else ln[:TEXT_LINE_CHARS].rstrip() + ' ...' for ln in lines[:TEXT_LINES]]
    if len(lines) > TEXT_LINES:
        shown.append(f'... {len(lines) - TEXT_LINES} more lines in detail.file')
    body['text'] = '\n'.join(shown)
    return ('text',)


# ------------------------------------------------------------------------------------- short replies (lever 13)

def _short(kind, full, body, keep=(), secondary=(), how=None, detail_file=None):
    import letitedit.server.compact_reply as compact_reply
    if not enabled() or not isinstance(full, dict) or full.get('error'):
        return full
    size = compact_reply.chars(full)
    if size <= SHORT_MIN:
        return full
    budget = max(SHORT_FLOOR, size // SHARE)
    return compact_reply.envelope(full, kind=kind, body=body, keep=keep, secondary=secondary, budget=budget,
                                  force=True, detail_file=detail_file, how=how)


def _clock(t):
    try:
        return f'{float(t):g}'
    except (TypeError, ValueError):
        return str(t)


LINE_CHARS = 110          # one marker, violation or finding as one line, its text cut to this length


def _line(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= LINE_CHARS else text[:LINE_CHARS - 4].rstrip() + ' ...'


def bin_reply(res):
    """letitedit_bin's reply: every marker as one line 'id start[-end] text' and every bin item as 'name file in-out
    note', all of them listed (texts cut to LINE_CHARS); the rest shortened, everything whole in detail.file."""
    if not enabled() or not isinstance(res, dict):
        return res
    body = {k: v for k, v in res.items() if k not in ('markers', 'bin')}
    rows = []
    for m in res.get('markers') or []:
        if isinstance(m, dict):
            span = _clock(m.get('start'))
            if m.get('end') not in (None, m.get('start')):
                span += '-' + _clock(m.get('end'))
            rows.append(_line(f"{m.get('id')} {span} {m.get('text') or ''}"))
        else:
            rows.append(_line(m))
    body['markers'] = rows
    items = []
    for it in res.get('bin') or []:
        if isinstance(it, dict):
            items.append(_line(f"{it.get('name') or it.get('id')} {Path(str(it.get('file') or '')).name} "
                               f"{_clock(it.get('in'))}-{_clock(it.get('out'))} {it.get('note') or ''}"))
        else:
            items.append(_line(it))
    body['bin'] = items
    for key in ('added', 'removed'):
        if isinstance(res.get(key), list):
            body[key] = [_line(x.get('marker') or x.get('id') or json.dumps(x, ensure_ascii=False, default=str))
                         if isinstance(x, dict) else _line(x) for x in res[key]]
    return _short('bin', res, body, keep=('project', 'read', 'fitted', 'note', 'markers', 'bin', 'not_found',
                                          'missing_files'),
                  secondary=('folders', 'seconds', 'fps', 'added', 'removed', 'backup', 'checks'),
                  how='detail.file: every marker and bin item whole (ids, times, frames, colours)')


def caption_fit_reply(res):
    """letitedit_caption_fit's (brief) reply: every problem left after the fit as one line (cue, times, kind,
    severity, what; '[unresolved]' when the fit could not solve it), all of them listed; the plan file and
    detail.file hold the whole proposal."""
    if not enabled() or not isinstance(res, dict) or 'applied' in res:
        return res
    unresolved = {(u.get('cue'), u.get('kind')): u for u in res.get('unresolved') or [] if isinstance(u, dict)}
    rows, seen = [], set()
    for v in res.get('violations_after') or []:
        if not isinstance(v, dict):
            continue
        key = (v.get('cue'), v.get('kind'))
        seen.add(key)
        rows.append(_line(f"{v.get('cue') or v.get('layer')} {v.get('start_clock', '')}-{v.get('end_clock', '')} "
                          f"{v.get('kind')} {v.get('severity') or ''}{' [unresolved]' if key in unresolved else ''}: "
                          f"{v.get('detail') or ''}"))
    for key, u in unresolved.items():
        if key not in seen:
            rows.append(_line(f"{u.get('cue') or u.get('layer')} {u.get('start_clock', '')}-{u.get('end_clock', '')} "
                              f"{u.get('kind')} [unresolved]: {u.get('why') or ''}"))
    body = {k: v for k, v in res.items() if k not in ('violations_after', 'unresolved', 'frame', 'schema_version')}
    body['after_the_fit'] = rows
    frame = res.get('frame') or {}
    if isinstance(frame, dict):
        body['frame'] = {k: frame[k] for k in ('width', 'height', 'platform', 'safe', 'min_size_px') if k in frame}
    return _short('caption-fit', res, body,
                  keep=('plan_id', 'plan_file', 'project', 'project_revision', 'summary', 'changes_count',
                        'after_the_fit', 'unresolved_options', 'violations_after_omitted', 'unresolved_omitted',
                        'warnings', 'unsupported', 'layers'),
                  secondary=('render_check', 'detail_in_plan_file', 'frame',
                             'seconds', 'unchecked_ranges', 'picture_files', 'changes'),
                  how='detail.file: this reply whole; plan_file: the whole proposal (every cue, violation, option, '
                      "change); detail='full' returns it here")


def soundtrack_reply(res):
    """letitedit_soundtrack's reply: the plan id, what to send next, the pieces, sections, hits, joins, findings, the
    gain and the measurements kept; the song's analysis, the settings and the fingerprints on disk."""
    if not enabled() or not isinstance(res, dict):
        return res
    body = {k: v for k, v in res.items() if k not in ('source_fingerprints', 'settings', 'schema_version', 'song')}
    song = res.get('song')
    if isinstance(song, dict):
        body['song'] = {k: song[k] for k in ('song', 'duration_s', 'bpm', 'beat_quality', 'bars', 'bar_s',
                                             'integrated_lufs') if k in song}
    return _short('soundtrack', res, body,
                  keep=('plan_id', 'mode', 'project', 'next', 'applied', 'plan_file', 'project_revision_after',
                        'findings', 'pieces', 'hits', 'joins', 'sections', 'protect', 'correction'),
                  secondary=('unsupported', 'checked_ranges', 'unchecked_ranges', 'search', 'repeats', 'request',
                             'preview_artifacts', 'picture_files', 'song', 'seconds', 'warnings', 'changes'),
                  how='detail.file: this reply whole (the song analysis, every setting, the fingerprints); plan_file: '
                      'the plan')


def looks_get_reply(res):
    """letitedit_looks action='get': the card without its empty fields and without the example files' paths (posters,
    previews: the sample sheet stays), the whole card on disk (`detail`). The recipe text, settings and measured files
    stay whole: they are the Look's own instructions."""
    import letitedit.server.compact_reply as compact_reply
    if not enabled() or not isinstance(res, dict) or res.get('error') or compact_reply.chars(res) <= SHORT_MIN:
        return res
    gone = [k for k, v in res.items() if v in (None, '', [], {}) or k in LOOK_PATHS]
    try:
        file = compact_reply.write_detail('looks-get', res)
    except (OSError, TypeError, ValueError):
        return res
    out = {k: v for k, v in res.items() if k not in gone}
    out['detail'] = {'file': file, 'left_out': gone, 'how': 'detail.file: the whole card'}
    return out


LOOK_PATHS = ('preview', 'poster', 'preview_long', 'poster_long', 'poster_s', 'poster_long_s', 'picture_files')


# ----------------------------------------------------------------- the render's own words at the joins (lever 4)

HEARD_WORDS = 120         # a render with more words than this gives only the words around each join ...
HEARD_AROUND_S = 1.5      # ... this long before and after it
HEARD_CLEAR_S = 0.02      # a word ending this close after a join still counts as before it (frame rounding)


def heard_words(media, offset_s=0.0):
    """[(word, start, end)] heard on a rendered file by the transcriber (the words tool's view of a file, cached by
    file), in timeline seconds: offset_s is the timeline time of the file's 0 s."""
    import letitedit.footage.speech as speech
    ws = speech.sound_words(str(media), heard=True) or []
    return [(str(w['w']).strip(), round(float(w['s']) + offset_s, 3), round(float(w['e']) + offset_s, 3))
            for w in ws if str(w.get('w') or '').strip()]


def mark_joins(words, times):
    """The heard words as one text with each join time marked where it falls ('bucks |5.27| on'; a join inside a
    word: 'buc|5.27|ks' is written 'bucks(|5.27| inside)'), and per join the heard word before it, after it and
    one it falls inside. Past HEARD_WORDS words, only the words within HEARD_AROUND_S of a join, joined by ' ... '."""
    times = sorted(float(t) for t in times)
    rows = []
    for t in times:
        before = [w for w in words if w[2] <= t + HEARD_CLEAR_S]
        after = [w for w in words if w[1] >= t - HEARD_CLEAR_S]
        inside = next((w for w in words if w[1] + HEARD_CLEAR_S < t < w[2] - HEARD_CLEAR_S), None)
        row = {'t': round(t, 3), 'heard_before': before[-1][0] if before else None,
               'heard_after': after[0][0] if after else None}
        if inside:
            row['heard_inside'] = inside[0]
        rows.append(row)
    keep = words if len(words) <= HEARD_WORDS else [
        w for w in words if any(t - HEARD_AROUND_S <= w[2] and w[1] <= t + HEARD_AROUND_S for t in times)]
    parts, pending, last_end = [], list(times), None
    for w in keep:
        if last_end is not None and len(words) > HEARD_WORDS and w[1] - last_end > 2 * HEARD_AROUND_S:
            parts.append('...')
        while pending and pending[0] <= w[1] + HEARD_CLEAR_S:
            parts.append(f'|{pending.pop(0):g}|')
        text = w[0]
        while pending and pending[0] < w[2] - HEARD_CLEAR_S:
            text += f'(|{pending.pop(0):g}| inside)'
        parts.append(text)
        last_end = w[2]
    parts += [f'|{t:g}|' for t in pending]
    return ' '.join(parts), rows


def heard_at_joins(joins, media, offset_s=0.0):
    """joins_brief's result with the words heard on the render itself: `heard` (the render's words, each join marked
    where it falls) and, on each listed join, heard_before / heard_after / heard_inside. media: the rendered file
    (its sound is the export engine's mix); offset_s: the timeline time of its 0 s. Off, or no joins: as given;
    a transcription that fails is said in `heard_error`, never fails the check."""
    if not enabled() or not isinstance(joins, dict) or joins.get('error') or not media:
        return joins
    try:
        words = heard_words(media, offset_s)
        times = [r['t'] for r in joins.get('at') or [] if isinstance(r, dict) and isinstance(r.get('t'), (int, float))]
        text, rows = mark_joins(words, times)
        by_t = {r['t']: r for r in rows}
        at = [{**r, **{k: v for k, v in by_t.get(round(float(r['t']), 3), {}).items() if k != 't'}}
              if isinstance(r, dict) and isinstance(r.get('t'), (int, float)) else r for r in joins.get('at') or []]
        return {**joins, 'at': at, 'heard': text or 'nothing is heard on the render',
                'heard_from': f'{Path(str(media)).name}, transcribed (timeline seconds)'}
    except Exception as exc:  # noqa: BLE001 - words beside a check, never a reason to fail the check
        return {**joins, 'heard_error': f'{type(exc).__name__}: {str(exc)[:200]}'}


def _times(block):
    return [r['t'] for r in (block or {}).get('at') or [] if isinstance(r, dict) and isinstance(r.get('t'), (int, float))]


def _with_heard(block, by_t):
    if not isinstance(block, dict) or block.get('error'):
        return block
    at = [{**r, **{k: v for k, v in by_t.get(round(float(r['t']), 3), {}).items() if k != 't'}}
          if isinstance(r, dict) and isinstance(r.get('t'), (int, float)) else r for r in block.get('at') or []]
    return {**block, 'at': at}


def heard_at_cuts(info, offset_s=None):
    """check_range's info (with `joins` and `edges` measured) with the words heard on its own render (`clip`):
    `heard` (the render's words, every listed join and clip edge marked where it falls: a range's last clip end
    comes last), `heard_from`, and on each listed join and edge heard_before / heard_after / heard_inside.
    offset_s: the timeline time of the render's 0 s (default: the start of info['range']). Off, or nothing
    measured: as given; a transcription that fails is said in `heard_error`, never fails the check."""
    if not enabled() or not isinstance(info, dict) or not info.get('clip'):
        return info
    joins, edges = info.get('joins'), info.get('edges')
    ok = [b for b in (joins, edges) if isinstance(b, dict) and not b.get('error')]
    if not ok:
        return info
    try:
        if offset_s is None:
            import letitedit.timeline.edit_script as es
            offset_s = es.to_seconds((info.get('range') or [0])[0])
        words = heard_words(info['clip'], offset_s)
        times = sorted({round(float(t), 3) for b in ok for t in _times(b)})
        text, rows = mark_joins(words, times)
        by_t = {r['t']: r for r in rows}
        return {**info, 'joins': _with_heard(joins, by_t), 'edges': _with_heard(edges, by_t),
                'heard': text or 'nothing is heard on the render',
                'heard_from': f'{Path(str(info["clip"])).name}, transcribed; times are timeline seconds, |t| a listed '
                              f'join or clip edge'}
    except Exception as exc:  # noqa: BLE001 - words beside a check, never a reason to fail the check
        return {**info, 'heard_error': f'{type(exc).__name__}: {str(exc)[:200]}'}


TRY_HEARD_CHARS = 400     # a version's heard words in try's one-line joins summary


def heard_for_version(row):
    """One try version (its row, with `joins` measured): the joins with the words heard on that version's own span
    render (row['render']['file'], which starts footage.views.PREROLL before its span, on a frame). Off: as given."""
    if not enabled() or not isinstance(row, dict) or not isinstance(row.get('joins'), dict):
        return row
    media = (row.get('render') or {}).get('file') if isinstance(row.get('render'), dict) else None
    span = row.get('span') or []
    if not media or not span:
        return row
    try:
        import letitedit.footage.views as views
        import letitedit.timeline.edit_script as es
        fps = float((es.read(row['project']).get('profile') or {}).get('fps') or 30)
        offset = round(max(0.0, float(span[0]) - views.PREROLL) * fps) / fps
    except Exception as exc:  # noqa: BLE001
        return {**row, 'joins': {**row['joins'], 'heard_error': f'{type(exc).__name__}: {str(exc)[:200]}'}}
    return {**row, 'joins': heard_at_joins(row['joins'], media, offset)}


def heard_line(joins):
    """' | heard: ...' for try's one-line joins summary, or ''."""
    if not enabled() or not isinstance(joins, dict) or not joins.get('heard'):
        return ''
    text = joins['heard']
    return ' | heard: ' + (text if len(text) <= TRY_HEARD_CHARS else text[:TRY_HEARD_CHARS - 4].rstrip() + ' ...')
