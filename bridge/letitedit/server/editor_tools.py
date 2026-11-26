"""MCP tool letitedit_editor: what the person is looking at in an open letitedit window right now.

Read through the editor's local pipe bridge (methods state + editor_state; claudebridge.cpp). Selected timeline
items and the items under the playhead are given with the clip ids letitedit_timeline_read uses (the same live
snapshot of the window, unsaved changes included). Nothing in the window changes.
"""
from __future__ import annotations

import ctypes
import os
import tempfile
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

DOC = """What the person sees in an open letitedit window right now (read-only; nothing in the window changes).
Returns: the open letitedit windows (instance_id, project, unsaved changes); for the chosen window: the project file
and whether it has unsaved changes, the player tab ('timeline' or 'source'), playing or paused, the playhead (seconds
and frame on the timeline; in the source tab also the source clip's position, in/out marks and length), the
selected timeline items (track, clip id as letitedit_timeline_read gives it, file, source in/out, timeline start/end),
the selected range across the selection, the item under the playhead on each track with the source second there,
markers (seconds, text, colour; range markers with an end) sorted by distance from the playhead, the visible panels
(docks), other open windows and any open dialog, the top undo/redo step, and the words said on the timeline from
words_s before to words_s after the playhead (with [playhead] where it is, from the clips' word timings; each word
with its time and clip id). Optionally the frame at the playhead as a picture (frame=true; frame_width px).
instance_id: the window [None: the window in front if it is a letitedit window, else 'main' when open, else the
first open one]. words_s [8.0]; transcribe [True: files not transcribed yet are transcribed locally first; False:
only words already cached]; frame [False]; frame_width [540]; max_markers [50]; max_words [120].
Times are timeline seconds unless named source. The clip ids work in letitedit_timeline_apply changes on the open
project; applying to it lands in this window as one Undo step."""


def _foreground_pid():
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:  # noqa: BLE001
        return None


def _pick(rows, instance_id):
    if instance_id:
        return next((r for r in rows if r['instance_id'] == instance_id), None)
    if not rows:
        return None
    front = _foreground_pid()
    for r in rows:
        if front and r.get('pid') == front:
            return r
    return next((r for r in rows if r['instance_id'] == 'main'), rows[0])


def _sec(frames, fps):
    return round(frames / fps, 3) if frames is not None and frames >= 0 else None


def _script_for(instance_id):
    """Edit script of the window's live timeline (same ids as letitedit_timeline_read), or None."""
    try:
        import letitedit.timeline.edit_script as es
        import letitedit.app.live_edit as live_edit
        snap, _rev = live_edit.snapshot(instance_id)
        return es.read(snap)
    except Exception:  # noqa: BLE001 - no timeline in the window, or an unreadable one
        return None


def _layouts(script):
    from letitedit.timeline.edit_sync import layout
    return {t['name']: layout(t) for t in script.get('tracks', [])}


def _item_brief(it, s, e, track):
    out = {'track': track, 'id': it.get('id'), 'start': round(s, 3), 'end': round(e, 3)}
    for k in ('clip', 'in', 'out', 'speed', 'color', 'said'):
        if it.get(k) is not None:
            out[k] = it[k]
    for k in ('graphic', 'ffmpeg', 'freeze', 'vfx', 'voice', 'ass'):
        if k in it:
            out['made'] = k
    return out


def state(instance_id=None, words_s=8.0, transcribe=True, frame=False, frame_width=540, max_markers=50,
          max_words=120, out_dir=None):
    """letitedit_editor without MCP: (report dict, frame image path or None)."""
    import letitedit.app.letitedit_instances as inst
    from letitedit.app.letitedit_client import ShotcutBridge
    rows = inst.list_instances()
    windows = [{'instance_id': r['instance_id'], 'project': r.get('project') or None,
                'unsaved_changes': bool(r.get('modified')), 'pid': r.get('pid')} for r in rows]
    row = _pick(rows, instance_id)
    if row is None:
        msg = (f"no letitedit window '{instance_id}' is open" if instance_id else 'no letitedit window is open')
        return {'windows': windows, 'text': msg}, None
    iid = row['instance_id']
    with inst.scope(iid), ShotcutBridge(timeout=30) as b:
        st = b.call('state') or {}
        try:
            ed = b.call('editor_state') or {}
        except Exception as exc:  # noqa: BLE001 - a build without editor_state
            ed = {'missing': f'editor_state not in this build ({exc})'}
        frame_path = None
        if frame:
            folder = Path(out_dir) if out_dir else Path(tempfile.gettempdir()) / 'letitedit_ai' / 'editor'
            folder.mkdir(parents=True, exist_ok=True)
            frame_path = folder / f'playhead-{iid}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:4]}.jpg'
            try:
                b.call('snapshot', {'path': str(frame_path), 'width': int(frame_width)})
            except Exception as exc:  # noqa: BLE001
                frame_path = None
                ed['frame_error'] = str(exc)

    fps = float(ed.get('fps') or (st.get('profile') or {}).get('fps') or 30.0)
    tl = st.get('timeline') or {}
    pos_f = ed.get('timeline_position', tl.get('position', -1))
    playhead = _sec(pos_f, fps)
    rep = {
        'windows': windows,
        'instance_id': iid,
        'project': st.get('project') or None,
        'unsaved_changes': bool(st.get('modified')),
        'player_tab': ed.get('player_tab'),
        'playing': ed.get('playing'),
        'playhead_s': playhead,
        'playhead_frame': pos_f,
        'fps': fps,
        'timeline_length_s': _sec(ed.get('timeline_length'), fps),
        'profile': st.get('profile'),
        'panels': st.get('visibleDocks') or [],
        'other_windows': st.get('otherWindows') or [],
        'dialog': st.get('dialog'),
        'undo': ed.get('undo'),
    }
    if ed.get('missing'):
        rep['note'] = ed['missing']
    src = ed.get('source')
    if src:
        rep['source'] = {'file': src.get('resource'), 'name': src.get('caption') or None,
                         'position_s': _sec(src.get('position'), fps), 'in_s': _sec(src.get('in'), fps),
                         'out_s': _sec(src.get('out'), fps), 'length_s': _sec(src.get('length'), fps)}

    script = _script_for(iid) if ed.get('timeline_open', True) and tl.get('tracks') else None
    lay = _layouts(script) if script else {}
    # selection -> ids
    sel = []
    for s in ed.get('selection') or [{'track': x.get('track'), 'clip': x.get('clip')} for x in tl.get('selection', [])]:
        entry = {'track': s.get('track_name'), 'track_index': s.get('track'), 'clip_index': s.get('clip')}
        if s.get('start') is not None:
            start, dur = s['start'], s.get('duration', 0)
            entry.update(start=_sec(start, fps), end=_sec(start + dur, fps))
            if s.get('blank'):
                entry['gap'] = True
            if s.get('transition'):
                entry['transition'] = True
            mid = (start + dur / 2.0) / fps
            match = None
            for it, a, z in lay.get(s.get('track_name'), []):
                if a - 1e-6 <= mid < z + 1e-6:
                    match = (it, a, z)
                    if not s.get('transition'):
                        break
            if match and not s.get('blank'):
                entry.update({k: v for k, v in _item_brief(*match, s.get('track_name')).items()
                              if k not in ('track', 'start', 'end')})
            elif s.get('ai_id'):
                entry['id'] = s['ai_id']
            if not entry.get('clip') and s.get('resource'):
                entry['file'] = s['resource']
        sel.append(entry)
    rep['selection'] = sel
    rng = ed.get('selected_range') or {}
    if rng.get('start_frame', -1) >= 0:
        rep['selected_range'] = {'start_s': _sec(rng['start_frame'], fps),
                                 'end_s': _sec(rng['end_frame'] if 'end_frame' in rng else rng.get('end_frame_inclusive'), fps)}
    # items under the playhead
    under = []
    if playhead is not None:
        for name, items in lay.items():
            for it, a, z in items:
                if a - 1e-6 <= playhead < z:
                    brief = _item_brief(it, a, z, name)
                    if 'clip' in it and it.get('in') is not None:
                        brief['source_s_at_playhead'] = round(float(it['in']) + (playhead - a) * float(it.get('speed', 1.0)), 3)
                    under.append(brief)
    rep['under_playhead'] = under
    # markers
    marks = []
    for m in ed.get('markers') or []:
        a = _sec(m.get('start'), fps)
        z = _sec(m.get('end'), fps) if m.get('end', -1) not in (None, -1, m.get('start')) else None
        d = None
        if playhead is not None and a is not None:
            d = 0.0 if (z is not None and a <= playhead <= z) else round(min(abs(a - playhead), abs((z or a) - playhead)), 3)
        marks.append({'start_s': a, 'end_s': z, 'text': m.get('text', ''), 'color': m.get('color'), 'distance_s': d})
    marks.sort(key=lambda m: (m['distance_s'] is None, m['distance_s'] or 0))
    rep['markers'] = marks[:int(max_markers)]
    if len(marks) > int(max_markers):
        rep['markers_left_out'] = len(marks) - int(max_markers)
    # words around the playhead
    if script and playhead is not None and words_s:
        import letitedit.footage.speech as speech
        import letitedit.timeline.timeline_speech as timeline_speech
        lo, hi = max(0.0, playhead - float(words_s)), playhead + float(words_s)
        ctx = nullcontext() if transcribe else mock.patch.object(speech, 'words',
                                                                    lambda p, a=None, b=None: speech.cached_words(p, a, b) or [])
        with ctx:
            words = timeline_speech.timeline_words(script, lo, hi)
        if len(words) > int(max_words):
            words.sort(key=lambda w: abs((w['t0'] + w['t1']) / 2 - playhead))
            words = sorted(words[:int(max_words)], key=lambda w: w['t0'])
        line, placed = [], False
        for w in words:
            if not placed and w['t0'] >= playhead:
                line.append('[playhead]')
                placed = True
            line.append(w['w'].strip())
        if not placed:
            line.append('[playhead]')
        rep['said_around_playhead'] = {'from_s': round(lo, 3), 'to_s': round(hi, 3), 'text': ' '.join(line),
                                       'words': [{'w': w['w'].strip(), 't0': w['t0'], 't1': w['t1'], 'id': w['id'],
                                                  'track': w['track']} for w in words]}
    if frame_path:
        rep['frame'] = str(frame_path)
    rep['text'] = summary(rep)
    return rep, (str(frame_path) if frame_path else None)


def _clock(s):
    if s is None:
        return '?'
    return f'{int(s // 60)}:{s % 60:04.1f}'


def summary(rep):
    lines = []
    proj = rep.get('project') or '(project not saved yet)'
    lines.append(f"window {rep['instance_id']}: {proj}{' (unsaved changes)' if rep.get('unsaved_changes') else ''}")
    lines.append(f"{rep.get('player_tab') or '?'} tab, {'playing' if rep.get('playing') else 'paused'}, playhead "
                 f"{_clock(rep.get('playhead_s'))} (frame {rep.get('playhead_frame')}) of "
                 f"{_clock(rep.get('timeline_length_s'))}")
    if rep.get('source'):
        s = rep['source']
        lines.append(f"source clip {s.get('name') or s.get('file')}: at {_clock(s['position_s'])}, in {_clock(s['in_s'])}"
                     f" out {_clock(s['out_s'])} of {_clock(s['length_s'])}")
    for s in rep.get('selection', []):
        what = 'gap' if s.get('gap') else 'transition' if s.get('transition') else (s.get('id') or 'item')
        src = f" {Path(s['clip']).name} {s.get('in')}-{s.get('out')}" if s.get('clip') else ''
        lines.append(f"selected: {s.get('track')} {what}{src} at {_clock(s.get('start'))}-{_clock(s.get('end'))}")
    if rep.get('selected_range'):
        r = rep['selected_range']
        lines.append(f"selected range {_clock(r['start_s'])}-{_clock(r['end_s'])}")
    for u in rep.get('under_playhead', []):
        extra = f" source {u['source_s_at_playhead']}s" if 'source_s_at_playhead' in u else ''
        name = Path(u['clip']).name if u.get('clip') else u.get('made') or u.get('color') or ''
        lines.append(f"under playhead: {u['track']} {u.get('id')} {name}{extra}")
    for m in rep.get('markers', [])[:5]:
        end = f"-{_clock(m['end_s'])}" if m.get('end_s') is not None else ''
        lines.append(f"marker {_clock(m['start_s'])}{end} {m.get('text') or ''}".rstrip())
    if rep.get('said_around_playhead'):
        lines.append('said: ' + rep['said_around_playhead']['text'])
    if rep.get('dialog'):
        lines.append(f"dialog open: {rep['dialog'].get('title')}")
    u = rep.get('undo') or {}
    if u.get('undo_text'):
        lines.append(f"top undo step: {u['undo_text']}")
    if len(rep.get('windows', [])) > 1:
        lines.append('other windows: ' + ', '.join(w['instance_id'] for w in rep['windows']
                                                   if w['instance_id'] != rep['instance_id']))
    return '\n'.join(lines)


def register(mcp, Image):
    def letitedit_editor(instance_id: str | None = None, words_s: float = 8.0, transcribe: bool = True,
                       frame: bool = False, frame_width: int = 540, max_markers: int = 50,
                       max_words: int = 120) -> list:
        try:
            rep, img = state(instance_id, words_s, transcribe, frame, frame_width, max_markers, max_words)
        except Exception as e:  # noqa: BLE001
            return [{'error': f'{type(e).__name__}: {e}'}]
        out = []
        if img:
            try:
                out.append(Image(data=Path(img).read_bytes(), format='jpeg'))
            except OSError:
                pass
        return out + [rep.get('text', ''), {k: v for k, v in rep.items() if k != 'text'}]
    letitedit_editor.__doc__ = DOC
    mcp.tool(structured_output=False)(letitedit_editor)
    return letitedit_editor
