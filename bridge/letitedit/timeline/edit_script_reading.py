"""Reading a project as an edit script with stable ids, with the track, master and caption readers it uses.

Part of `edit_script` (letitedit/timeline/edit_script.py), which imports every name here back,
so `edit_script.X` is the same object it always was.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import contextlib
import contextvars
import json
import os
import re
from pathlib import Path
import letitedit.timeline.adjust as adjust
import letitedit.timeline.edit_effects as ee
import letitedit.timeline.made as made
import letitedit.timeline.timeline_model as tm
from letitedit.timeline.edit_script_base import (  # noqa: E402
    FORMAT, GRAPHIC_PROP, HOOK_PROP, ID_PROP, MULTICAM_PROP, SCENE_PROP, SPLIT_PROP, LOOK_PROP, _get, _props, _r, _slug, clock,
    file_hash, to_seconds
)
from letitedit.timeline.edit_script_project import (  # noqa: E402
    Doc, _anim_to_keys, _describe_friendly, _user_filters, describe_filter
)
from letitedit.timeline.edit_script_transitions import (  # noqa: E402
    _track_records
)


# ---------------------------------------------------------------------------- reading

def _ids_for(doc):
    """Stable id for every entry: the stored letitedit_ai:id, else a positional one. Returns {(track_name, idx): id}."""
    ids, used = {}, set()
    stored_ids = {_get(doc.elements[e.get('producer')], ID_PROP) for _, pl, _, _ in doc.tracks()
                  for k, e, _ in doc.entries(pl) if k == 'entry' and e.get('producer') in doc.elements}
    for tr, pl, name, kind in doc.tracks():
        n = 0
        for i, (k, e, _) in enumerate(doc.entries(pl)):
            if k != 'entry':
                continue
            prod = doc.elements.get(e.get('producer'))
            if prod is not None and prod.tag == 'tractor' and _get(prod, 'shotcut:transition') is not None:
                ids[(name, i)] = f'{_slug(name)}-transition-{i}'
                continue
            n += 1
            stored = _get(prod, ID_PROP) if prod is not None else None
            base = stored or f'{_slug(name)}-{n:03d}'
            cand, suffix = base, 1
            while cand in used or (not stored and cand in stored_ids):
                suffix += 1
                cand = f'{base}{chr(96 + suffix)}' if suffix <= 26 else f'{base}-{suffix}'
            used.add(cand)
            ids[(name, i)] = cand
    return ids


def item_view(doc, entry, producer, item_id):
    fps = doc.fps
    a = doc.f(entry.get('in')) or 0
    b = doc.f(entry.get('out'))
    if b is None:
        b = doc.f(producer.get('out')) or 0
    n = b - a + 1
    p = _props(producer)
    service = p.get('mlt_service', producer.tag)
    item = {'id': item_id}
    if producer.tag == 'tractor':
        item.update(raw=producer.get('id'), len=_r(n / fps))
        return item
    if adjust.is_marker(p):
        item.update(adjust=True, len=_r(n / fps), name=p.get('shotcut:caption') or adjust.DEFAULT_NAME)
        effects = [describe_filter(f, fps, n, doc.width, doc.height) for f in _user_filters(producer)]
        if effects:
            item['effects'] = effects
        return item
    if p.get(SCENE_PROP):
        try:
            item['scene'] = json.loads(p[SCENE_PROP])
            item['len'] = _r(n / fps)
            if a:      # its start was trimmed: it begins this far into the scene's own time
                item['in'] = _r(a / fps)
            item['name'] = p.get('shotcut:caption') or 'Code scene'
            return item
        except ValueError:
            pass
    if p.get(made.MADE_PROP):
        try:
            item.update(made.view_of(json.loads(p[made.MADE_PROP])))
        except ValueError:
            item['clip'] = p.get('resource', '')
        fx_own = []
        if p.get(made.FX_PROP):         # a freeze played through ffmpeg effects: its own graphs come first
            try:
                fx_own = list(json.loads(p[made.FX_PROP]).get('effects') or [])
            except ValueError:
                fx_own = []
            item['len'] = _r(n / fps)
        elif a:
            item['skip'] = _r(a / fps)
        effects = fx_own + [describe_filter(f, fps, n, doc.width, doc.height) for f in _user_filters(producer)]
        if effects:
            item['effects'] = effects
        return item
    recipe = fx = None
    if p.get(GRAPHIC_PROP):
        try:
            recipe = json.loads(p[GRAPHIC_PROP])
        except ValueError:
            recipe = None
    if p.get(made.FX_PROP):
        try:
            fx = json.loads(p[made.FX_PROP])
        except ValueError:
            fx = None
    if fx:
        # a clip played through ffmpeg effects: shown as its source clip, with the graphs among its effects
        speed = float(fx.get('speed', 1.0))
        item['clip'] = fx['clip']
        item['in'] = _r(fx['start'] + a * speed / fps)
        item['out'] = _r(fx['start'] + (b + 1) * speed / fps)
        if abs(speed - 1.0) > 1e-9:
            item['speed'] = _r(speed, 6)
        if fx.get('name'):
            item['name'] = fx['name']
    elif recipe:
        g = {'template': recipe.get('template')}
        if recipe.get('params'):
            g['params'] = recipe['params']
        if recipe.get('code'):
            g['code'] = recipe['code']
        if recipe.get('source'):
            g['source'] = recipe['source']
        item['graphic'] = g
    elif service == 'color':
        color = p.get('resource', '#ff000000')
        if '#' in color and not color.startswith('#'):  # some serializations prefix the project folder
            color = color[color.rfind('#'):]
        item.update(color=color, **{'in': _r(a / fps), 'out': _r((b + 1) / fps)})
    else:
        speed = float(p.get('warp_speed') or 1.0)
        res = p.get('warp_resource') or p.get('resource', '')
        item['clip'] = res
        item['in'] = _r(a * speed / fps)
        item['out'] = _r((b + 1) * speed / fps)
        if abs(speed - 1.0) > 1e-9:
            item['speed'] = _r(speed, 6)
        cap = p.get('shotcut:caption')
        if cap and cap != os.path.basename(res) and not cap.startswith(os.path.basename(res) + ' ('):
            item['name'] = cap
    from letitedit.looks.sound_targets import PROPERTY
    if p.get(PROPERTY):
        try:
            item['sound_target'] = json.loads(p[PROPERTY])
        except ValueError:
            pass
    if p.get(SPLIT_PROP):
        try:
            item['split_edit'] = json.loads(p[SPLIT_PROP])
        except ValueError:
            pass
    if p.get(MULTICAM_PROP):
        try:
            item['multicam'] = json.loads(p[MULTICAM_PROP])
        except ValueError:
            pass
    effects, kept = list((fx or {}).get('effects') or []), 0
    for f in _user_filters(producer):
        d = describe_filter(f, fps, n, doc.width, doc.height)
        if d is None:
            fp = _props(f)
            d = {'keep': f"{fp.get('shotcut:filter') or fp.get('mlt_service') or f.tag}#{kept}"}
            kept += 1
        effects.append(d)
    if effects:
        item['effects'] = effects
    return item


_READ_AS = contextvars.ContextVar('letitedit_read_as', default=None)


@contextlib.contextmanager
def reading_as(project, source):
    """Inside it, read(project) reads `source` instead (an open window's snapshot of that project: what the window
    shows now, unsaved changes included), still named `project` in the script. Other projects read as always."""
    token = _READ_AS.set((os.path.normcase(str(Path(project).resolve())), Path(source)))
    try:
        yield
    finally:
        _READ_AS.reset(token)


def read(project, start_s=None, end_s=None, tracks=None):
    """Return the edit script for a saved project (.mlt path or managed episode/cut folder), or, inside reading_as for
    it, for the window's snapshot of it."""
    path = name = _resolve(project)
    shown = _READ_AS.get()
    if shown and os.path.normcase(str(Path(path).resolve())) == shown[0]:
        path = shown[1]
    doc = Doc(path)
    fps = doc.fps
    ids = _ids_for(doc)
    script = {'format': FORMAT, 'project': str(name), 'base': file_hash(path),
              'profile': {'width': doc.width, 'height': doc.height, 'fps': _r(fps, 6)}, 'tracks': []}
    total = 0
    for tr, pl, name, kind in doc.tracks():
        t = {'name': name, 'kind': kind, 'items': []}
        t.update(_track_audio(doc, tr, pl))
        effs = _track_fx(pl, doc) + [describe_filter(f, fps, 0, doc.width, doc.height) for f in _track_filters(pl)]
        if effs:
            t['effects'] = effs
        if tr.get('hide') and kind == 'video':
            t['hide'] = tr.get('hide')
        if kind == 'audio' and tr.get('hide') == 'both':
            t['hide'] = 'both'
        pos = 0
        for r in _track_records(doc, pl, name, ids):
            if r['kind'] == 'blank':
                t['items'].append({'gap': _r(r['frames'] / fps)})
                pos += r['frames']
                continue
            e, prod = r['entry'], r['prod']
            item = item_view(doc, e, prod, r['id'])
            if r.get('transition'):
                item['transition'] = r['transition']
                pos -= r['tr_frames']
            a = doc.f(e.get('in')) or 0
            b = doc.f(e.get('out'))
            if b is None:
                b = doc.f(prod.get('out')) or 0
            item['at'] = clock(pos / fps)
            n = b - a + 1
            item['len'] = _r(n / fps)
            pos += n
            t['items'].append(item)
        total = max(total, pos)
        if tracks and name not in tracks:
            t['items'] = [{'omitted': len(t['items'])}]
        script['tracks'].append(t)
    script['length'] = clock(total / fps)
    caps = []
    for f in doc.main.findall('filter'):
        p = _props(f)
        if p.get('mlt_service') == 'subtitle_feed':
            cues = [{'start': clock(a), 'end': clock(b), 'text': text} for a, b, text in tm.parse_srt(p.get('text', ''))]
            cap = {'track': p.get('feed', 'Subtitles'), 'cues': cues}
            main_b, shadow_b = _caption_burns(doc, cap['track'])
            if main_b is not None:
                bp = _props(main_b)
                cap['style'] = {k: bp[k] for k in CAPTION_STYLE_KEYS if k in bp}
                if shadow_b is not None:
                    sp_ = _props(shadow_b)
                    dx, dy = _geom_offset(sp_.get('geometry'), bp.get('geometry'))
                    cap['style']['shadow'] = {'fgcolour': sp_.get('fgcolour'), 'x': dx, 'y': dy}
                    try:            # a soft halo: the shadow copy's outline is wider than the text's
                        spread = round(float(sp_.get('outline') or 0) - float(bp.get('outline') or 0))
                    except (TypeError, ValueError):
                        spread = 0
                    if spread > 0:
                        cap['style']['shadow']['spread'] = spread
            else:
                cap['burn_in'] = False
            caps.append(cap)
    if caps:
        script['captions'] = caps
    import letitedit.looks.look_library as look_library
    identity = look_library.project_identity(_props(doc.main))
    if identity:
        script['look'] = identity
    if _get(doc.main, HOOK_PROP):
        script['hook'] = _get(doc.main, HOOK_PROP)
    master = _master_effects(doc)
    if master:
        script['master'] = master
    if start_s is not None or end_s is not None:
        lo = start_s or 0
        hi = end_s if end_s is not None else total / fps
        script = in_range(script, lo, hi)
    return script


def in_range(script, lo, hi):
    """The script with only the items and caption cues that overlap lo-hi seconds (marked partial)."""
    for t in script['tracks']:
        t['items'] = [it for it in t['items'] if 'at' not in it or (to_seconds(it['at']) < hi and to_seconds(it['at']) + it['len'] > lo)]
        t['partial'] = True
    for c in script.get('captions', []):
        if isinstance(c.get('cues'), list):
            c['cues'] = [q for q in c['cues'] if to_seconds(q['start']) < hi and to_seconds(q['end']) > lo]
    script['partial'] = f'{clock(lo)}-{clock(hi)}'
    return script


def _resolve(project):
    path = Path(project)
    if path.is_dir():
        from letitedit.timeline import episodes as p
        root, data = p.load(path)
        if not data.get('timeline'):
            raise ValueError('This episode/cut has no timeline yet')
        path = p.owned(root, data['timeline'])
    if not path.is_file():
        if str(project).strip().lower() in ('live', 'current', 'editor'):
            raise FileNotFoundError(f"project '{project}' is for the tools that read or check the open window; this one "
                                    "takes the project's .mlt path, and letitedit_editor gives it")
        import letitedit.core.long_paths as long_paths
        long_paths.check(path)          # there, perhaps, but under a path too long to open
        raise FileNotFoundError(f'No project at {path}; letitedit_project_new makes one')
    return path


CAPTION_STYLE_KEYS = ('family', 'size', 'weight', 'style', 'fgcolour', 'olcolour', 'outline', 'bgcolour', 'geometry',
                      'halign', 'valign', 'pad', 'opacity')


def _track_volume_filter(pl):
    return next((f for f in pl.findall('filter') if _get(f, 'shotcut:trackVolume') or
                 (_get(f, 'mlt_service') == 'volume' and _get(f, 'shotcut:filter') == 'audioGain')), None)


def _mix_for(doc, tr):
    idx = list(doc.main.findall('track')).index(tr)
    return next((t for t in doc.main.findall('transition') if _get(t, 'mlt_service') == 'mix'
                 and str(_get(t, 'b_track')) == str(idx)), None)


def _track_filters(pl):
    """A track's own effects (the whole track: a grade on the B-roll, EQ on the music), without its volume filter."""
    vol = _track_volume_filter(pl)
    return [f for f in _user_filters(pl) if f is not vol and f.tag == 'filter']


def _track_fx(pl, doc=None):
    """A track's ffmpeg effects (rendered into each of its clips). Stored on the track and on each clip it reached: a
    track swapped into an open Shotcut window keeps only its clips, so the clips' copy is read when the track has none."""
    raw = _get(pl, made.FX_PROP)
    try:
        if raw:
            return list(json.loads(raw))
    except ValueError:
        return []
    if doc is None:
        return []
    seen = []
    for e in pl.findall('entry'):
        prod = doc.elements.get(e.get('producer'))
        fx = _get(prod, made.FX_PROP) if prod is not None else None
        if fx:
            try:
                seen.append(json.dumps(json.loads(fx).get('track') or [], sort_keys=True))
            except ValueError:
                pass
    return json.loads(seen[0]) if seen and len(set(seen)) == 1 else []


def _track_audio(doc, tr, pl):
    """Track-level sound settings shown in the script: gain (the track's volume, dB) and duck (the editor's automatic
    ducking of this track under the others: {threshold, attenuation} dB)."""
    out = {}
    f = _track_volume_filter(pl)
    if f is not None:
        level = str(_get(f, 'level', '0'))
        keys = _anim_to_keys(level, doc.fps) if '=' in level else None
        try:
            out['gain'] = {'keys': keys} if keys else float(re.sub(r'(?i)db$', '', level))
        except ValueError:
            pass
    mix = _mix_for(doc, tr)
    if mix is not None and (_get(mix, 'shotcut:duck_enabled') == '1' or float(_get(mix, 'duck_threshold') or 0) < 0):
        out['duck'] = {'threshold': float(_get(mix, 'duck_threshold') or -30),
                       'attenuation': float(_get(mix, 'duck_attenuation') or -12)}
    return out


MASTER_SKIP = ('subtitle_feed', 'subtitle')


FLATTEN_ROLE = 'flatten'


def _master_filters(doc):
    return [f for f in doc.main.findall('filter') if _get(f, 'mlt_service') not in MASTER_SKIP
            and _get(f, 'letitedit_ai:role') != FLATTEN_ROLE]


def _describe_master(f, k):
    p = _props(f)
    svc = p.get('mlt_service')
    if svc == 'dynamic_loudness':
        return {'loudness': {'target': float(p.get('target_loudness', -23)), 'window': float(p.get('window', 3)),
                             'max_gain': float(p.get('max_gain', 15)), 'min_gain': float(p.get('min_gain', -15)),
                             'max_rate': float(p.get('max_rate', 3))}}
    if svc == 'ladspa.1913':
        return {'limiter': {'input_gain': float(p.get('0', 0)), 'limit_db': float(p.get('1', -2)),
                            'release_s': float(p.get('2', 0.08))}}
    return {'keep': f'{p.get("shotcut:filter") or svc}#{k}'}


def _master_view(f, fps):
    if _get(f, 'shotcut:filter') == 'audioGain':
        g = _describe_friendly(f, fps)
        if g:
            return g
    d = _describe_master(f, 0)
    return ee.view(f, fps) if 'keep' in d else d


def _master_effects(doc):
    return [_master_view(f, doc.fps) for f in _master_filters(doc)]


def _caption_burns(doc, feed):
    """(main burn-in filter, shadow burn-in filter or None) for a caption track. The main one is drawn last; a shadow
    is an earlier copy marked letitedit_ai:role=shadow or drawn in a single colour (fill = outline)."""
    burns = [b for b in doc.main.findall('filter') if _get(b, 'mlt_service') == 'subtitle' and _get(b, 'feed') == feed]
    if not burns:
        return None, None
    main = burns[-1]
    shadow = next((b for b in burns[:-1] if _get(b, 'letitedit_ai:role') == 'shadow'
                   or (_get(b, 'fgcolour') and _get(b, 'fgcolour') == _get(b, 'olcolour'))), None)
    return main, shadow


def _geom_offset(shadow_geom, main_geom):
    try:
        s = [float(v) for v in str(shadow_geom).split()[:2]]
        m = [float(v) for v in str(main_geom).split()[:2]]
        return _r(s[0] - m[0], 2), _r(s[1] - m[1], 2)
    except (ValueError, IndexError):
        return 3, 4


# ---------------------------------------------------------------------------- the compact view
COMPACT_TEXT = 600          # a text value longer than this is folded in the compact view
COMPACT_AUTO = 36_000       # detail='auto': a read whose YAML is longer than this comes back compact
COMPACT_PAGE = 36_000       # detail='auto': a compact read longer than this stops at a main-track cut and says where to go on
# (Claude Code takes a tool answer of 25,000 tokens; a timeline's YAML runs about 2.5 characters a token)
COMPACT_CUES = 20           # a caption track with more cues than this shows their count and span in the compact view


def _fold_keys(keys):
    times = [k[0] for k in keys if isinstance(k, (list, tuple)) and k]
    vals = [k[1] for k in keys if isinstance(k, (list, tuple)) and len(k) > 1]
    out = f'{len(keys)} keyframes'
    if times:
        out += f', {times[0]}-{times[-1]} s'
    nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if nums and len(nums) == len(vals):
        out += f', values {min(nums)} to {max(nums)}'
    elif vals:
        out += f', first {vals[0]}, last {vals[-1]}'
    return out


def _fold_text(text):
    lines = text.splitlines()
    out = {'text_chars': len(text), 'text_lines': len(lines)}
    dialogue = [ln for ln in lines if ln.startswith('Dialogue:')]
    if dialogue:
        out['dialogue_lines'] = len(dialogue)
    out['starts'] = text[:120]
    return out


def _fold(value, counts):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == 'keys' and isinstance(v, list) and len(v) > 2:
                out[k] = _fold_keys(v)
                counts['keys'] += 1
            elif k == 'angles' and isinstance(v, list) and all(isinstance(a, list) and a for a in v):
                out[k] = [a[-1] for a in v]          # a multicam clip's angles by name (the full view has files and offsets)
            elif isinstance(v, str) and len(v) > COMPACT_TEXT and k not in ('clip', 'said'):
                out[k] = _fold_text(v)
                counts['texts'] += 1
            else:
                out[k] = _fold(v, counts)
        return out
    if isinstance(value, list):
        return [_fold(v, counts) for v in value]
    return value


def _fold_cues(caps, counts):
    for c in caps or []:
        cues = c.get('cues') or []
        if len(cues) > COMPACT_CUES:
            c['cues'] = f"{len(cues)} cues, {cues[0]['start']}-{cues[-1]['end']}"
            counts['cues'] += 1


def only_ids(script, ids):
    """The script with only the items whose id is in ids, and the caption cues said over them (marked partial)."""
    want = set(ids)
    found = set()
    for t in script['tracks']:
        keep = [it for it in t['items'] if it.get('id') in want]
        found.update(it['id'] for it in keep)
        if len(keep) != len(t['items']):
            t['partial'] = True
            if not keep:
                t.pop('effects', None)
        t['items'] = keep
    spans = [(to_seconds(it['at']), to_seconds(it['at']) + it['len']) for t in script['tracks'] for it in t['items']
             if 'at' in it]
    for c in script.get('captions', []):       # only the cues said over those clips
        if isinstance(c.get('cues'), list):
            c['cues'] = [q for q in c['cues'] if any(to_seconds(q['start']) < b and to_seconds(q['end']) > a
                                                     for a, b in spans)]
    script['partial'] = 'ids: ' + ', '.join(i for i in ids)
    missing = [i for i in ids if i not in found]
    if missing:
        script['not_found'] = missing
    return script


def compact(script):
    """The compact view: every keyframe list of more than two keys folded to one line (its count, first and last time,
    lowest and highest value), every text longer than COMPACT_TEXT characters (a libass script, a graphic's code) to its
    length and first characters, a multicam clip's angles to their names, and a caption track of more than
    COMPACT_CUES cues to their count and span. The result is for reading: compile_script refuses it."""
    counts = {'keys': 0, 'texts': 0, 'cues': 0}
    out = _fold(script, counts)
    _fold_cues(out.get('captions'), counts)
    if any(counts.values()):
        out['view'] = {'compact': True, 'keyframe_lists_folded': counts['keys'], 'texts_folded': counts['texts'],
                       'caption_tracks_folded': counts['cues']}
    return out


def _starts(script):
    """Every item start on the main picture track (the first video track), in seconds."""
    for t in script['tracks']:
        if t.get('kind') == 'video':
            return sorted({to_seconds(it['at']) for it in t['items'] if 'at' in it})
    return []


def page(script, size, limit, lo=0.0):
    """A compact script cut to its first stretch whose YAML (size(script) characters) is within limit, ending at a
    main-track cut. Returns (script, next_start_s or None). Each item is measured once; the stretch is the latest cut
    whose items (and caption cues) still fit beside the script's own lines, checked once on the result."""
    import copy
    whole = size(script)
    if whole <= limit:
        return script, None
    cuts = [c for c in _starts(script) if c > lo]
    if not cuts:
        return script, None
    import yaml

    def chars(value):                   # an item's YAML on its own (block style: a little over what to_yaml writes)
        return len(yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=140))
    bare = copy.deepcopy(script)
    spans = []                          # (start, end, characters) of everything a stretch can hold
    for t in bare['tracks']:
        for it in t['items']:
            if 'at' in it:
                a = to_seconds(it['at'])
                spans.append((a, a + it['len'], chars([it])))
        t['items'] = []
    for c in bare.get('captions', []):
        if isinstance(c.get('cues'), list):
            for q in c['cues']:
                spans.append((to_seconds(q['start']), to_seconds(q['end']), chars([q])))
            c['cues'] = []
    base = size(bare)

    def fits(end):
        return base + sum(n for a, b, n in spans if a < end and b > lo) <= limit

    end = cuts[0]
    for c in cuts:                      # cuts are in order and a later cut never holds less
        if not fits(c):
            break
        end = c
    out = in_range(copy.deepcopy(script), lo, end)
    i = cuts.index(end)
    while size(out) > limit and i > 0:  # the estimate was short (YAML's own indents): one cut back at a time
        i -= 1
        end = cuts[i]
        out = in_range(copy.deepcopy(script), lo, end)
    return out, end
