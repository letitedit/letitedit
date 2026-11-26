"""Energy over time against the story plan: the 'trajectory' view of the timing layer (builder B4, TIMING-SPEC.md).

    trajectory(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief') -> dict
        series every trajectory.step_s seconds over a centred window of trajectory.window_s: cut rate (cuts per
        minute), motion (the motion lane's energy, camera removed, px/frame), music (level as heard, dB, from the
        music lane), speech rate (words per minute) and speech share; an energy index (the robust z-scores of those,
        weighted: trajectory.weights); the story plan's sections mapped onto the timeline with numbers per section,
        the order of the measured energy against the planned gears, and around each planned peak whether the energy
        rises into it, breathes just before it and releases after it. Images: paths.
    plan_sections(sig, options) -> (sections, where they came from, notes)
    find_story_plan(source, explicit=None) -> (plan dict or None, where)

The index is relative to this edit (its own median and spread): it says where this edit is livelier or calmer, not
how lively it is against other videos. Every number keeps its own unit next to it. No gear is computed: the plan's
gear is compared with the measured order (letitedit-craft: 'No tool computes a gear').

How plan sections land on the timeline, in order of preference: chapter/section markers in the project; each plan
beat's `selects` ('IMG_0479@35.0-50.3', 'broll/sign-pullback', 'sign-pullback.mp4@0.3-4.0') matched to the
timeline's picture items by file name and source range (items between matches inherit the section before them);
else the plan's target_s shares of the edit's length (estimated, and said so).
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

import numpy as np

import letitedit.timing.music_sync as ms

VIEW = 'trajectory'
THRESHOLDS = {
    'trajectory.window_s': {'value': 6.0, 'unit': 's', 'about': 'centred window of every series value'},
    'trajectory.step_s': {'value': 0.5, 'unit': 's', 'about': 'series step'},
    'trajectory.weights': {'value': {'cut_rate': 1.0, 'motion': 1.0, 'music': 1.0, 'speech_rate': 0.5},
                           'unit': 'relative weights', 'about': 'weights of the robust z-scores in the energy index '
                           '(a measure without variation in this edit is left out)'},
    'trajectory.music_floor_db': {'value': -60.0, 'unit': 'dB', 'about': 'music level used for the index where no '
                                  'music plays'},
    'trajectory.rise_window_s': {'value': 8.0, 'unit': 's', 'about': 'before a planned peak: the last window is '
                                 'compared with the window before it (rise into the peak)'},
    'trajectory.release_window_s': {'value': 6.0, 'unit': 's', 'about': 'after a planned peak: compared with the peak'},
    'trajectory.breath_window_s': {'value': 3.0, 'unit': 's', 'about': 'just before a planned peak: a dip here is a '
                                   'breath (release before the peak)'},
    'trajectory.rise_min': {'value': 0.3, 'unit': 'index (robust z)', 'about': 'a rise at least this big counts as '
                            'rising into the peak'},
    'trajectory.release_min': {'value': 0.3, 'unit': 'index (robust z)', 'about': 'a fall after the peak at least this '
                               'big counts as a release'},
    'trajectory.breath_dip': {'value': 0.3, 'unit': 'index (robust z)', 'about': 'a dip just before the peak at least '
                              'this deep counts as a breath'},
    'trajectory.gear_rank_min': {'value': 0.6, 'unit': 'Spearman rho', 'about': 'rank correlation between planned '
                                 'gears and the sections\' measured index at or above this is reported as matching '
                                 'order'},
}
ms.TRAJECTORY_DEFAULTS.update(THRESHOLDS)


def th(name, given=None):
    return ms.th(name, given)


# ============================================================================ the story plan

def find_story_plan(source, explicit=None, project=None):
    """(plan, where): explicit path; else story_plan.json next to the project/video, in the project's own folder
    (<stem>), or one folder up (renders\\ inside a round); else the newest journal note of the project that is a
    story plan (critic.py's rule)."""
    files = [Path(explicit)] if explicit else []
    for src in [s for s in (project, source) if s]:
        p = Path(str(src))
        if p.suffix:
            files += [p.parent / 'story_plan.json', p.with_suffix('') / 'story_plan.json',
                      p.parent.parent / 'story_plan.json']
        elif p.is_dir():
            files.append(p / 'story_plan.json')
    for f in files:
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding='utf-8-sig')), str(f)
            except ValueError:
                continue
    proj = project or (source if str(source).lower().endswith('.mlt') else None)
    if proj:
        import letitedit.timeline.project_journal as project_journal
        journal = project_journal.folder(proj) / 'journal.jsonl'
        if journal.is_file():
            for line in reversed(journal.read_text(encoding='utf-8-sig', errors='replace').splitlines()):
                try:
                    text = json.loads(line).get('text') or ''
                except (ValueError, AttributeError):
                    continue
                body = re.sub(r'^\s*story[ _-]?plan\s*:', '', text, flags=re.I)
                if body.strip().startswith('{'):
                    try:
                        data = json.loads(body)
                    except ValueError:
                        continue
                    if isinstance(data, dict) and any(k in data for k in ('logline', 'purpose', 'sections', 'beats')):
                        return data, f'{journal} (journal note)'
    return None, None


def _plan_list(plan, kind=None):
    """(sections, beats) of the plan for this deliverable (critic.py's rule); sections fall back to beats."""
    per = plan.get('deliverables')
    secs, beats = None, plan.get('beats') or []
    if isinstance(per, dict):
        mine = per.get(kind) if kind else None
        if isinstance(mine, dict):
            secs = mine.get('sections') or None
            beats = mine.get('beats') or beats
    if secs is None:
        secs = plan.get('sections') or None
    if secs is None and isinstance(per, dict):
        found = [v.get('sections') for v in per.values() if isinstance(v, dict) and v.get('sections')]
        if len(found) == 1:
            secs = found[0]
    if secs and any(isinstance(s, str) for s in secs):
        # a deliverable may list section ids: resolve them against the plan's sections, in its order
        by_id = {str(s.get('id')): s for s in plan.get('sections') or [] if isinstance(s, dict)}
        secs = [by_id.get(s, {'id': s, 'label': s}) if isinstance(s, str) else s for s in secs]
    if not secs:
        secs = [dict(b, id=b.get('id') or f'b{i + 1}') for i, b in enumerate(beats) if isinstance(b, dict)]
        beats_as_sections = True
    else:
        beats_as_sections = False
    return [s for s in secs if isinstance(s, dict)], [b for b in beats if isinstance(b, dict)], beats_as_sections


_SEL = re.compile(r'^\s*(?P<name>[^@]+?)\s*(?:@\s*(?P<a>-?\d+(?:\.\d+)?)\s*(?:-\s*(?P<b>-?\d+(?:\.\d+)?))?)?\s*$')


def _parse_select(sel):
    """'IMG_0479@35.0-50.3' -> ('img_0479', 35.0, 50.3); 'broll/sign-pullback' -> ('sign-pullback', None, None)."""
    if not isinstance(sel, str):
        return None
    text = sel.split(' (')[0].split(' - ')[0].strip()
    sp = re.match(r'^(?P<name>\S+)\s+(?P<a>\d+(?:\.\d+)?)\s*-\s*(?P<b>\d+(?:\.\d+)?)$', text)
    if sp and '@' not in text:                  # 'table-person 11.8-14.6' (a plan written without @)
        text = f"{sp.group('name')}@{sp.group('a')}-{sp.group('b')}"
    m = _SEL.match(text)
    if not m:
        return None
    name = re.split(r'[\\/]', m.group('name').strip())[-1]
    name = re.sub(r'\.(mp4|mov|m4v|mkv|avi|mts|wav|mp3|png|jpg|jpeg)$', '', name, flags=re.I).strip().lower()
    a = float(m.group('a')) if m.group('a') else None
    b = float(m.group('b')) if m.group('b') else None
    if a is not None and b is None:
        b = a + 0.5
    return name, a, b


def _kind_of(source, options):
    if options.get('deliverable'):
        return options['deliverable']
    stem = Path(str(source)).stem.lower()
    for k in ('short', 'long', 'reel', 'main'):
        if k in stem:
            return k
    return None


def _project_for(sig, options):
    """The project whose items map the plan: the source itself, options.project, or a .mlt of the same name next to
    a render (renders\\short.mp4 -> ..\\short.mlt)."""
    if sig.get('kind') == 'project':
        return sig.get('project'), None
    if options.get('project'):
        return options['project'], 'options.project'
    v = Path(str(sig.get('source')))
    for c in (v.with_suffix('.mlt'), v.parent.parent / (v.stem + '.mlt'), v.parent / (v.stem + '.mlt')):
        if c.is_file():
            return str(c), f'the project of the same name ({c.name}) maps the plan onto this render'
    # the only project next to the render or one folder up whose length matches the render to the frame
    try:
        import letitedit.timeline.timeline_model as tm
        found = []
        for folder in (v.parent, v.parent.parent):
            for c in folder.glob('*.mlt'):
                tl = tm.load(c)
                if int(tl.frames) == int(sig['frames']) and abs(float(tl.fps) - float(sig['fps'])) < 0.01:
                    found.append(c)
        if len(found) == 1:
            return str(found[0]), (f'{found[0].name} has exactly this render\'s frames and rate: it maps the plan '
                                   'onto the render')
    except Exception:  # noqa: BLE001 - no project: the plan's target_s shares are used
        pass
    return None, None


def plan_sections(sig, options=None):
    """(sections [{id, label, t0, t1, gear, feel, driver, purpose, target_s, mapped_by}], from, notes)."""
    options = options or {}
    fps = float(sig['fps'])
    dur = int(sig['frames']) / fps
    proj, proj_note = _project_for(sig, options)
    plan, where = find_story_plan(sig.get('source'), options.get('story_plan'), proj)
    notes = []
    if proj_note:
        notes.append(proj_note)
    if not plan:
        return [], None, ['no story plan found (story_plan.json next to the project or one folder up, or a '
                          '\'story_plan:\' journal note)']
    kind = _kind_of(sig.get('source'), options)
    secs, beats, as_beats = _plan_list(plan, kind)
    if not secs:
        return [], where, ['the story plan has no sections or beats']
    if as_beats:
        notes.append('the plan has no sections: its beats are used as sections')
    rows = []
    for i, s in enumerate(secs):
        rows.append({'id': str(s.get('id') or f's{i + 1}'), 'label': s.get('label') or s.get('name') or s.get('title')
                     or s.get('id') or f'section {i + 1}', 'gear': s.get('gear'), 'feel': s.get('feel'),
                     'driver': s.get('driver'), 'purpose': s.get('purpose'), 'target_s': s.get('target_s')})
    # 1) markers named like the sections
    marks = []
    if proj:
        try:
            import letitedit.timing.timing_signals as timing_signals
            marks = [m for m in timing_signals.read_markers(proj) if m.get('kind') in ('chapter', 'section')]
        except Exception:  # noqa: BLE001
            marks = []
    if marks:
        by = {}
        for m in marks:
            lab = str(m.get('label') or '').strip().lower()
            for r in rows:
                if lab and lab in (r['id'].lower(), str(r['label']).lower()):
                    by[r['id']] = float(m['t'])
        if len(by) >= max(2, len(rows) - 1):
            starts = [(by.get(r['id']), r) for r in rows]
            known = [(t, r) for t, r in starts if t is not None]
            known.sort(key=lambda x: x[0])
            out = []
            for k, (t, r) in enumerate(known):
                t1 = known[k + 1][0] if k + 1 < len(known) else dur
                out.append(dict(r, t0=round(t, 3), t1=round(t1, 3), mapped_by='markers'))
            return out, where, notes + ['sections placed by chapter/section markers named like them']
    # 2) beats' selects matched to timeline picture items
    if proj:
        try:
            mapped, cov = _map_by_selects(proj, rows, secs, beats, as_beats, fps, dur)
        except Exception as e:  # noqa: BLE001
            mapped, cov = None, None
            notes.append(f'mapping by selects failed: {type(e).__name__}: {e}')
        if mapped:
            notes.append(f'sections placed by matching the plan beats\' selects to the timeline\'s picture items '
                         f'({round(100 * cov)}% of the picture time matched directly; items between matches belong '
                         'to the section before them)')
            return mapped, where, notes
    # 3) target_s shares
    tg = [float(r['target_s']) if isinstance(r.get('target_s'), (int, float)) else None for r in rows]
    if all(v is None for v in tg):
        tg = [1.0] * len(rows)
        notes.append('no section has target_s: equal shares of the edit (a rough placement)')
    else:
        m = float(np.mean([v for v in tg if v is not None]))
        tg = [v if v is not None else m for v in tg]
        notes.append('sections placed by the plan\'s target_s shares of the edit\'s length (estimated: the plan could '
                     'not be matched to the timeline)')
    tot = sum(tg)
    t, out = 0.0, []
    for r, v in zip(rows, tg):
        t1 = t + dur * v / tot
        out.append(dict(r, t0=round(t, 3), t1=round(t1, 3), mapped_by='target_s (estimated)'))
        t = t1
    return out, where, notes


def _map_by_selects(proj, rows, secs, beats, as_beats, fps, dur):
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.edit_sync as edit_sync
    script = es.read(proj)
    main = edit_sync.main_track(script)
    picture = []
    for t in script['tracks']:
        if t.get('kind') != 'video':
            continue
        for it, s, e in edit_sync.layout(t):
            if it.get('clip'):
                picture.append((s, e, it, t is main))
    if not picture:
        return None, None
    sec_ids = [r['id'] for r in rows]
    # which section each select belongs to
    sel_sec = []
    if as_beats:
        for b in secs:
            for sel in b.get('selects') or b.get('shots') or []:
                ps = _parse_select(sel)
                if ps:
                    sel_sec.append((ps, str(b.get('id'))))
    else:
        for b in beats:
            sid = str(b.get('section') or '')
            if sid not in sec_ids:
                continue
            for sel in b.get('selects') or b.get('shots') or []:
                ps = _parse_select(sel)
                if ps:
                    sel_sec.append((ps, sid))
    if not sel_sec:
        return None, None
    labelled = []
    for s, e, it, is_main in sorted(picture, key=lambda x: (x[0], not x[3])):
        stem = Path(it['clip']).stem.lower()
        a, b = float(it.get('in') or 0.0), float(it.get('out') or 0.0)
        best = None
        for (name, sa, sb), sid in sel_sec:
            if name != stem and not stem.endswith(name) and not name.endswith(stem):
                continue
            if sa is None:
                ov = 0.01
            else:
                ov = min(b, sb + 1.0) - max(a, sa - 1.0)
            if ov > 0 and (best is None or ov > best[0]):
                best = (ov, sid)
        labelled.append((s, e, best[1] if best else None, is_main))
    # the main track decides; overlays (b-roll on V2) refine where they cover it
    timeline = [(s, e, sid) for s, e, sid, is_main in labelled if is_main]
    over = [(s, e, sid) for s, e, sid, is_main in labelled if not is_main and sid]
    step = 0.1
    n = int(math.ceil(dur / step))
    lab = [None] * n
    for s, e, sid in timeline + over:
        if sid is None:
            continue
        for j in range(int(s / step), min(n, int(math.ceil(e / step)))):
            lab[j] = sid
    direct = sum(1 for x in lab if x is not None) / max(1, n)
    if direct < 0.2:
        return None, direct
    cur = None
    for j in range(n):
        if lab[j] is None:
            lab[j] = cur
        else:
            cur = lab[j]
    first = next((x for x in lab if x is not None), None)
    lab = [x if x is not None else first for x in lab]
    spans = {}
    for j, sid in enumerate(lab):
        if sid is None:
            continue
        a = spans.setdefault(sid, [j * step, (j + 1) * step, 0])
        a[0], a[1], a[2] = min(a[0], j * step), max(a[1], (j + 1) * step), a[2] + 1
    out = []
    for r in rows:
        sp = spans.get(r['id'])
        if not sp:
            continue
        out.append(dict(r, t0=round(sp[0], 3), t1=round(min(dur, sp[1]), 3), mapped_by='selects',
                        interleaved=bool((sp[1] - sp[0]) / step > sp[2] + 2)))
    out.sort(key=lambda x: x['t0'])
    # neighbours meet: each section ends where the next starts
    for k in range(len(out) - 1):
        if out[k]['t1'] > out[k + 1]['t0']:
            out[k]['t1'] = out[k + 1]['t0']
    missing = [r['label'] for r in rows if r['id'] not in spans]
    if missing:
        for r in out:
            r.setdefault('note', None)
        out[-1]['missing_sections'] = missing
    return out, direct


# ============================================================================ the series

def _robust_z(x):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    if ok.sum() < 4:
        return None
    med = float(np.median(x[ok]))
    q1, q3 = np.percentile(x[ok], [25, 75])
    s = (q3 - q1) / 1.349
    if s < 1e-9:
        s = float(np.std(x[ok]))
    if s < 1e-9:
        return None
    return np.clip((x - med) / s, -3, 3)


def series(sig, music_lane, motion_energy, words, speech_spans, given=None):
    """The series on a step grid: t, cut_rate (/min), motion (px/frame or the fallback's unit), music_db, music
    intensity, words_per_min, speech_share, index (+ which measures made it)."""
    fps = float(sig['fps'])
    F = int(sig['frames'])
    dur = F / fps
    W = float(th('trajectory.window_s', given))
    step = float(th('trajectory.step_s', given))
    t = np.arange(0.0, dur + 1e-9, step)
    cuts = [c['f'] / fps for c in ((sig.get('lanes') or {}).get('edit') or {}).get('cuts') or []
            if c.get('detail') not in ('from black', 'to black')]
    ct = np.asarray(sorted(cuts), float)
    rate = []
    for x in t:
        a, b = max(0.0, x - W / 2), min(dur, x + W / 2)
        n = int(np.sum((ct >= a) & (ct < b)))
        rate.append(60.0 * n / max(b - a, 1e-6))
    rate = np.asarray(rate)
    motion = np.full(len(t), np.nan)
    if motion_energy is not None and len(motion_energy):
        me = np.asarray([np.nan if v is None else float(v) for v in motion_energy], float)
        cut_f = set()
        for c in ct:
            f = int(round(c * fps))
            cut_f.update((f - 1, f, f + 1))
        for f in cut_f:
            if 0 <= f < len(me):
                me[f] = np.nan
        for j, x in enumerate(t):
            a, b = int(max(0, (x - W / 2) * fps)), int(min(len(me), (x + W / 2) * fps))
            seg = me[a:b]
            seg = seg[np.isfinite(seg)]
            if len(seg):
                motion[j] = float(np.mean(seg))
    lev = music_lane.get('level_db') or []
    every = float(music_lane.get('level_every_s') or 0.1)
    inten = music_lane.get('intensity') or []
    ev = float(music_lane.get('energy_every_s') or 0.5)
    music_db = np.full(len(t), np.nan)
    music_i = np.full(len(t), np.nan)
    for j, x in enumerate(t):
        a, b = max(0.0, x - W / 2), min(dur, x + W / 2)
        vals = [lev[k] for k in range(int(a / every), min(len(lev), int(math.ceil(b / every)))) if lev[k] is not None]
        if vals:
            music_db[j] = 10 * math.log10(np.mean([10 ** (v / 10) for v in vals]))
        iv = [inten[k] for k in range(int(a / ev), min(len(inten), int(math.ceil(b / ev)))) if inten[k] is not None]
        if iv:
            music_i[j] = float(np.mean(iv))
    w0 = np.asarray([float(w['t0']) for w in words or []], float)
    wpm = np.full(len(t), np.nan) if not len(w0) and not speech_spans else np.zeros(len(t))
    share = np.zeros(len(t))
    for j, x in enumerate(t):
        a, b = max(0.0, x - W / 2), min(dur, x + W / 2)
        if len(w0):
            wpm[j] = 60.0 * int(np.sum((w0 >= a) & (w0 < b))) / max(b - a, 1e-6)
        cov = sum(max(0.0, min(b, s1) - max(a, s0)) for s0, s1 in speech_spans or [])
        share[j] = cov / max(b - a, 1e-6)
    weights = th('trajectory.weights', given) or {}
    floor = float(th('trajectory.music_floor_db', given))
    parts, used = [], {}
    for name, x in (('cut_rate', rate), ('motion', motion),
                    ('music', np.where(np.isfinite(music_db), music_db, floor)), ('speech_rate', wpm)):
        w = float(weights.get(name, 0.0) or 0.0)
        if w <= 0:
            continue
        z = _robust_z(x)
        if z is None:
            continue
        parts.append(w * np.where(np.isfinite(z), z, 0.0))
        used[name] = w
    index = np.sum(parts, axis=0) / sum(used.values()) if parts else np.full(len(t), np.nan)
    return {'t': t, 'cut_rate': rate, 'motion': motion, 'music_db': music_db, 'music_intensity': music_i,
            'words_per_min': wpm, 'speech_share': share, 'index': index, 'index_measures': used, 'window_s': W,
            'step_s': step, 'cuts': ct}


def _mean_in(t, x, a, b):
    m = (t >= a) & (t < b) & np.isfinite(x)
    return float(np.mean(x[m])) if m.any() else None


def _slope_in(t, x, a, b):
    m = (t >= a) & (t < b) & np.isfinite(x)
    if m.sum() < 3:
        return None
    return float(np.polyfit(t[m], x[m], 1)[0] * 10.0)


def section_numbers(sections, S, fps):
    t = S['t']
    out = []
    ct = S['cuts']
    for s in sections:
        a, b = float(s['t0']), float(s['t1'])
        cuts_in = ct[(ct > a + 0.5 / fps) & (ct < b - 0.5 / fps)]     # a cut on the section's own edge is its entry
        edges = [a] + list(cuts_in) + [b]
        shots = np.diff(edges)
        row = {k: s.get(k) for k in ('id', 'label', 'gear', 'feel', 'driver', 'mapped_by')}
        row.update(t0=round(a, 3), t1=round(b, 3), dur_s=round(b - a, 2), cuts=int(len(cuts_in)),
                   cuts_per_min=round(60.0 * len(cuts_in) / max(b - a, 1e-6), 1),
                   median_shot_s=round(float(np.median(shots)), 2) if len(shots) else None)
        for name, key, nd in (('motion', 'motion', 3), ('music_db', 'music_db', 1),
                              ('music_intensity', 'music_intensity', 3), ('words_per_min', 'words_per_min', 1),
                              ('speech_share', 'speech_share', 3), ('index', 'index', 3)):
            v = _mean_in(t, S[key], a, b)
            row[name] = None if v is None else round(v, nd)
        row['index_slope_per_10s'] = ms._r(_slope_in(t, S['index'], a, b), 3)
        inside = (t >= a) & (t < b)
        # music_db is the level where music plays; this says how much of the section that is
        row['music_share'] = round(float(np.mean(np.isfinite(S['music_db'][inside]))), 3) if inside.any() else None
        out.append(row)
    return out


def gear_check(rows, given=None):
    g = [(r['gear'], r['index']) for r in rows if isinstance(r.get('gear'), (int, float)) and r.get('index') is not None]
    res = {'sections_with_gear': len(g)}
    if len(g) >= 3:
        rho = ms._spearman([a for a, _ in g], [b for _, b in g])
        res['spearman_gear_vs_index'] = ms._r(rho, 3)
        res['matching_order'] = rho is not None and rho >= float(th('trajectory.gear_rank_min', given))
        res['threshold'] = th('trajectory.gear_rank_min', given)
    pairs = []
    for a, b in zip(rows, rows[1:]):
        if not (isinstance(a.get('gear'), (int, float)) and isinstance(b.get('gear'), (int, float))):
            continue
        if a.get('index') is None or b.get('index') is None:
            continue
        dg, di = b['gear'] - a['gear'], b['index'] - a['index']
        pairs.append({'from': a['label'], 'to': b['label'], 'gear_change': dg, 'index_change': round(di, 3),
                      'agree': (dg == 0) or (dg > 0 and di > 0) or (dg < 0 and di < 0),
                      'levers': {'cuts_per_min': [a['cuts_per_min'], b['cuts_per_min']],
                                 'motion': [a.get('motion'), b.get('motion')],
                                 'music_db': [a.get('music_db'), b.get('music_db')],
                                 'words_per_min': [a.get('words_per_min'), b.get('words_per_min')]}})
    res['neighbours'] = pairs
    res['neighbours_disagreeing'] = [p for p in pairs if not p['agree']]
    return res


def peaks(sections, S, given=None):
    """Planned peaks (a section whose gear is above its neighbours'; else the section with the highest index):
    the rise into it, a breath just before it, the release after it, and where the music's high point is."""
    rw, relw, bw = (float(th('trajectory.rise_window_s', given)), float(th('trajectory.release_window_s', given)),
                    float(th('trajectory.breath_window_s', given)))
    rmin, relmin, dip = (float(th('trajectory.rise_min', given)), float(th('trajectory.release_min', given)),
                         float(th('trajectory.breath_dip', given)))
    t, idx = S['t'], S['index']
    gears = [s.get('gear') if isinstance(s.get('gear'), (int, float)) else None for s in sections]
    cand = []
    if sum(g is not None for g in gears) >= 2:
        for i, g in enumerate(gears):
            if g is None:
                continue
            left = gears[i - 1] if i > 0 else None
            right = gears[i + 1] if i + 1 < len(gears) else None
            if all(n is None or g > n for n in (left, right)) and any(n is not None for n in (left, right)):
                cand.append((i, f'planned peak: gear {g} above its neighbours'))
    if not cand and sections:
        means = [_mean_in(t, idx, s['t0'], s['t1']) for s in sections]
        if any(m is not None for m in means):
            i = int(np.nanargmax([m if m is not None else -9 for m in means]))
            cand.append((i, 'no planned peak (gears): the section with the highest measured index'))
    out = []
    mus = np.where(np.isfinite(S['music_intensity']), S['music_intensity'], np.nan)
    mus_peak_t = float(t[int(np.nanargmax(mus))]) if np.isfinite(mus).any() else None
    for i, why in cand:
        s = sections[i]
        a, b = float(s['t0']), float(s['t1'])
        peak_mean = _mean_in(t, idx, a, b)
        pre2 = _mean_in(t, idx, a - 2 * rw, a - rw)
        pre1 = _mean_in(t, idx, a - rw, a)
        post = _mean_in(t, idx, b, b + relw)
        breath = None
        if a - bw > 0:
            seg = (t >= a - bw) & (t < a + 1.0) & np.isfinite(idx)
            ref = _mean_in(t, idx, a - rw, a - bw)
            if seg.any() and ref is not None:
                breath = ref - float(np.min(idx[seg]))
        row = {'section': s.get('label'), 'gear': s.get('gear'), 'why': why, 't0': round(a, 3), 't1': round(b, 3),
               'index_in_peak': ms._r(peak_mean, 3), 'index_before': ms._r(pre1, 3),
               'index_before_that': ms._r(pre2, 3), 'index_after': ms._r(post, 3),
               'rise_into_peak': ms._r(None if peak_mean is None or pre1 is None else peak_mean - pre1, 3),
               'rise_before': ms._r(None if pre1 is None or pre2 is None else pre1 - pre2, 3),
               'release_after': ms._r(None if peak_mean is None or post is None else peak_mean - post, 3),
               'breath_before': ms._r(breath, 3)}
        row['rises'] = row['rise_into_peak'] is not None and row['rise_into_peak'] >= rmin
        row['releases'] = row['release_after'] is not None and row['release_after'] >= relmin
        row['breathes'] = row['breath_before'] is not None and row['breath_before'] >= dip
        levers = {}
        for name, key in (('cuts_per_min', 'cut_rate'), ('motion', 'motion'), ('music_db', 'music_db'),
                          ('words_per_min', 'words_per_min')):
            x = S[key]
            levers[name] = {'before': ms._r(_mean_in(t, x, a - rw, a), 2), 'in_peak': ms._r(_mean_in(t, x, a, b), 2),
                            'after': ms._r(_mean_in(t, x, b, b + relw), 2)}
        row['levers'] = levers
        if mus_peak_t is not None:
            row['music_high_point_t'] = round(mus_peak_t, 2)
            row['music_high_point_in_peak'] = a <= mus_peak_t < b
            row['music_high_point_offset_s'] = round(0.0 if a <= mus_peak_t < b else
                                                     (mus_peak_t - a if mus_peak_t < a else mus_peak_t - b), 2)
        out.append(row)
    return out


# ============================================================================ drawing

SEC_COLS = [(214, 232, 247), (250, 226, 200), (222, 240, 214), (240, 220, 240), (250, 240, 200), (220, 230, 230)]


def draw(path, title, S, sections, rows, pk, plan_from, measures_used, t0, t1):
    from PIL import Image, ImageDraw
    W = 1800
    L, R = 150, 30
    lanes = [('cut rate', 'cut_rate', 'cuts/min', ms.COL['cut']), ('motion', 'motion', 'px/frame', (235, 130, 20)),
             ('music', 'music_db', 'dB', (200, 150, 30)), ('speech', 'words_per_min', 'words/min', (40, 110, 200)),
             ('ENERGY INDEX', 'index', 'robust z', (20, 20, 25))]
    lane_h = 120
    top = 150
    H = top + lane_h * len(lanes) + 70 + 30 * (len(rows) + 2) + 30 * max(1, len(pk))
    img = Image.new('RGB', (W, H), ms.COL['bg'])
    d = ImageDraw.Draw(img)
    f_t, f_s, f_m = ms.font(30, True), ms.font(18), ms.font(16)
    d.text((20, 12), title, fill=ms.COL['ink'], font=f_t)
    d.text((20, 52), f'plan: {plan_from or "none"};  index from: '
                     f'{", ".join(f"{k} x{v:g}" for k, v in measures_used.items()) or "nothing measurable"}',
           fill=ms.COL['mute'], font=f_s)
    t = S['t']

    def X(x):
        return L + (x - t0) / max(1e-6, t1 - t0) * (W - L - R)
    # sections band
    for k, s in enumerate(sections):
        a, b = max(t0, s['t0']), min(t1, s['t1'])
        if b <= a:
            continue
        d.rectangle([X(a), 84, X(b), top - 8], fill=SEC_COLS[k % len(SEC_COLS)], outline=(160, 160, 160))
        lab = str(s.get('label') or '')[:max(4, int((X(b) - X(a)) / 9))]
        d.text((X(a) + 4, 86), lab, fill=ms.COL['ink'], font=f_m)
        if s.get('gear') is not None:
            d.text((X(a) + 4, 106), f"gear {s['gear']}", fill=ms.COL['ink'], font=ms.font(18, True))
        if s.get('feel'):
            d.text((X(a) + 70, 108), str(s['feel'])[:max(2, int((X(b) - X(a) - 70) / 8))], fill=ms.COL['mute'],
                   font=f_m)
    for i, (name, key, unit, col) in enumerate(lanes):
        y0 = top + i * lane_h
        y1 = y0 + lane_h - 14
        x = np.asarray(S[key], float)
        m = np.isfinite(x) & (t >= t0) & (t <= t1)
        d.rectangle([L, y0, W - R, y1], outline=ms.COL['grid'])
        for k, s in enumerate(sections):
            a, b = max(t0, s['t0']), min(t1, s['t1'])
            if b > a:
                d.rectangle([X(a), y0 + 1, X(b), y1 - 1], fill=tuple(int(0.35 * c + 0.65 * 250) for c in
                                                                     SEC_COLS[k % len(SEC_COLS)]))
        d.text((10, y0 + 8), name, fill=col, font=ms.font(20, True))
        d.text((10, y0 + 34), unit, fill=ms.COL['mute'], font=f_m)
        if not m.any():
            d.text((L + 10, y0 + 40), 'not measured', fill=ms.COL['mute'], font=f_s)
            continue
        lo, hi = float(np.nanmin(x[m])), float(np.nanmax(x[m]))
        if hi - lo < 1e-9:
            hi = lo + 1.0
        d.text((10, y0 + 56), f'{hi:.3g} top', fill=ms.COL['mute'], font=f_m)
        d.text((10, y0 + 76), f'{lo:.3g} bottom', fill=ms.COL['mute'], font=f_m)

        def Y(v):
            return y1 - 6 - (v - lo) / (hi - lo) * (y1 - y0 - 12)
        pts = []
        for xx, v, ok in zip(t, x, m):
            if ok:
                pts.append((X(xx), Y(v)))
            elif len(pts) > 1:
                d.line(pts, fill=col, width=3 if key == 'index' else 2)
                pts = []
            else:
                pts = []
        if len(pts) > 1:
            d.line(pts, fill=col, width=3 if key == 'index' else 2)
        # section means
        for r in rows:
            v = r.get({'cut_rate': 'cuts_per_min', 'motion': 'motion', 'music_db': 'music_db',
                       'words_per_min': 'words_per_min', 'index': 'index'}[key])
            if v is None:
                continue
            a, b = max(t0, r['t0']), min(t1, r['t1'])
            if b > a:
                d.line([X(a), Y(v), X(b), Y(v)], fill=(90, 90, 90), width=1)
                d.text((X(a) + 3, Y(v) - 18), f'{v:.3g}', fill=(70, 70, 70), font=f_m)
    # peaks
    yb = top + len(lanes) * lane_h
    for p in pk:
        xa = X(max(t0, p['t0']))
        d.line([xa, top, xa, yb], fill=(200, 30, 40), width=2)
        d.text((xa + 4, yb - lane_h + 8), 'PEAK', fill=(200, 30, 40), font=ms.font(18, True))
    for s in range(int(math.ceil(t0)), int(t1) + 1, 5 if t1 - t0 > 60 else 2):
        d.text((X(s) - 10, yb + 2), f'{s}s', fill=ms.COL['mute'], font=f_m)
    # table
    y = yb + 34
    cols = [('section', 20, 'label'), ('time', 400, None), ('gear', 560, 'gear'), ('cuts/min', 620, 'cuts_per_min'),
            ('median shot s', 730, 'median_shot_s'), ('motion', 880, 'motion'), ('music dB', 980, 'music_db'),
            ('music share', 1090, 'music_share'), ('words/min', 1220, 'words_per_min'), ('index', 1340, 'index'),
            ('slope /10s', 1440, 'index_slope_per_10s')]
    for name, x, _ in cols:
        d.text((x, y), name, fill=ms.COL['ink'], font=ms.font(19, True))
    y += 28
    for r in rows:
        for name, x, key in cols:
            if key is None:
                v = f"{ms._clock(r['t0'])}-{ms._clock(r['t1'])}"
            else:
                v = r.get(key)
                v = '-' if v is None else (str(v)[:38] if key == 'label' else f'{v:g}' if isinstance(v, (int, float))
                                           else str(v))
            d.text((x, y), v, fill=ms.COL['ink'], font=f_s)
        y += 28
    for p in pk:
        d.text((20, y), f"peak '{p['section']}': rise into it {p['rise_into_peak']} "
                        f"({'rises' if p['rises'] else 'no rise'}), breath before {p['breath_before']}, release after "
                        f"{p['release_after']} ({'releases' if p['releases'] else 'no release'}); music high point "
                        f"{p.get('music_high_point_t')} s", fill=(160, 20, 30), font=f_s)
        y += 30
    img.save(path)
    return path


# ============================================================================ the view

VIEW_SUMMARY = ('energy over time (rolling cut rate, motion, music level, speech rate and an energy index) against '
                'each story-plan section\'s intended gear and feel: numbers per section, measured order against the '
                'gears, and whether the energy rises into each planned peak, breathes before it and releases after')
VIEW_OPTIONS = {'story_plan': 'path of a story_plan.json (else found next to the project, one folder up, or in the '
                              'journal)', 'deliverable': 'which deliverable\'s sections (long / short)',
                'project': 'for a render: the project whose items place the plan sections',
                'thresholds': '{trajectory.key or key: value} overrides', 'settings': '{lane: {...}} measuring settings',
                'refresh': 'recompute the measurements',
                'speech_lane': 'videos: use the prosody speech lane for the words (default false: it transcribes the '
                               'video the first time)'}


def _signals(source, start_s, end_s, options):
    opts = options or {}
    import letitedit.timing.timing_signals as timing_signals
    reg = timing_signals.lanes()
    want = ['edit', ms.LANE] + [n for n in ('motion',) if n in reg]
    if not timing_signals._is_project(source) and 'speech' in reg and opts.get('speech_lane', False):
        want.append('speech')         # opt-in (transcribes the video); else cached words or the voice detector
    return timing_signals.signals(source, start_s, end_s, lanes=want, refresh=bool(opts.get('refresh')),
                                  settings=opts.get('settings'))


def trajectory(source, start_s=None, end_s=None, items=None, cuts=None, options=None, detail='brief'):
    """The 'trajectory' view (see the module doc)."""
    t_all = time.time()
    opts = dict(options or {})
    given = opts.get('thresholds') or {}
    sig = _signals(source, start_s, end_s, opts)
    fps, F = float(sig['fps']), int(sig['frames'])
    dur = F / fps
    warnings, unsupported = list(sig.get('warnings') or []), []
    if items or cuts:
        warnings.append('items / cuts do not narrow this view (it reads whole sections); use start_s / end_s')
    ml = (sig.get('lanes') or {}).get(ms.LANE) or {}
    if ml.get('error'):
        warnings.append(f'music lane failed: {ml["error"]}')
        ml = {}
    motion_energy, motion_note = None, None
    mo = (sig.get('lanes') or {}).get('motion') or {}
    if mo and not mo.get('error') and mo.get('energy'):
        motion_energy = mo['energy']
        motion_note = (mo.get('units') or {}).get('energy') or 'px/frame'
    else:
        try:
            _, _, _, motion_energy = ms.picture_events(sig, {'fallback_motion': True}, ml)
            motion_note = 'fallback: residual frame difference (0-255)'
        except Exception as e:  # noqa: BLE001
            unsupported.append(f'motion not measured ({type(e).__name__}: {e})')
    spans, words, _, speech_how = ms._speech(sig, given)
    S = series(sig, ml, motion_energy, words, spans, given)
    sections, plan_from, notes = plan_sections(sig, opts)
    t0 = float(start_s) if start_s is not None else 0.0
    t1 = float(end_s) if end_s is not None else dur
    if not sections:
        unsupported.append('no story plan sections: numbers are given for the whole edit only')
        sections_used = [{'id': 'all', 'label': 'whole edit', 't0': 0.0, 't1': dur, 'gear': None}]
    else:
        sections_used = sections
    rows = section_numbers(sections_used, S, fps)
    gc = gear_check(rows, given) if sections else {'sections_with_gear': 0}
    pk = peaks(sections_used, S, given) if sections else []
    out_dir = ms._out_dir('trajectory')
    img = draw(out_dir / 'trajectory.png', f'Trajectory: {Path(str(source)).name}', S, sections, rows, pk, plan_from,
               S['index_measures'], t0, t1)
    try:
        import letitedit.timing.timing_views as timing_views
        base = timing_views.common_fields(source=str(source), sig=sig, view=VIEW,
                                          inputs=[start_s, end_s, items, cuts, opts, detail])
    except ImportError:
        base = {'schema_version': 1, 'result_id': ms._hash([str(source), start_s, end_s, opts]),
                'project_revision': sig.get('project_revision'), 'source_fingerprints': {}, 'checked_ranges': [],
                'unchecked_ranges': [], 'warnings': [], 'unsupported': [], 'preview_artifacts': [], 'changes': []}
    step = S['step_s']
    keep = (S['t'] >= t0) & (S['t'] <= t1)

    def ser(x, nd):
        return [None if not np.isfinite(v) else round(float(v), nd) for v in np.asarray(x, float)[keep]]
    res = dict(base)
    res.update({
        'view': VIEW, 'images': [str(img)], 'fps': fps, 'frames': F, 'duration_s': round(dur, 3),
        'plan': {'from': plan_from, 'notes': notes, 'sections': sections},
        'sections': rows, 'gear_check': gc, 'peaks': pk,
        'series': {'t0': round(float(S['t'][keep][0]), 3) if keep.any() else None, 'step_s': step,
                   'window_s': S['window_s'],
                   'cut_rate': ser(S['cut_rate'], 1), 'motion': ser(S['motion'], 3), 'music_db': ser(S['music_db'], 1),
                   'music_intensity': ser(S['music_intensity'], 3), 'words_per_min': ser(S['words_per_min'], 1),
                   'speech_share': ser(S['speech_share'], 3), 'index': ser(S['index'], 3)}
        if detail == 'full' else {'step_s': step, 'window_s': S['window_s'],
                                  'note': 'detail=full returns every series value'},
        'units': {'cut_rate': 'cuts per minute (centred window)', 'motion': motion_note,
                  'music_db': 'dB, music level as heard (power mean)', 'music_intensity': '0-1 song energy by bar',
                  'words_per_min': 'word starts per minute', 'speech_share': 'share of the window with speech',
                  'index': 'weighted mean of robust z-scores within this edit (0 = this edit\'s median)'},
        'index_measures': S['index_measures'], 'speech_from': speech_how,
        'thresholds': ms.used_thresholds('trajectory.', given, THRESHOLDS),
        'options_used': {k: opts.get(k) for k in VIEW_OPTIONS if k in opts}, 'options_available': VIEW_OPTIONS,
        'seconds': round(time.time() - t_all, 2)})
    res['warnings'] = list(base.get('warnings') or []) + warnings
    res['unsupported'] = list(base.get('unsupported') or []) + unsupported
    res['preview_artifacts'] = list(res['images'])
    return ms._clean(res)


# ============================================================================ registration

_REGISTERED = {'view': False, 'thresholds': False}


def register():
    if not _REGISTERED['view']:
        try:
            import letitedit.timing.timing_views as timing_views
            if hasattr(timing_views, 'register_view'):
                timing_views.register_view(VIEW, trajectory, VIEW_SUMMARY)
                _REGISTERED['view'] = True
        except Exception:  # noqa: BLE001
            pass
    if not _REGISTERED['thresholds']:
        try:
            ms.merge_thresholds(THRESHOLDS)
            _REGISTERED['thresholds'] = True
        except Exception:  # noqa: BLE001
            pass
    return dict(_REGISTERED)


register()
