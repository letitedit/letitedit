"""Ground truth for style_import: the events a letitedit project (.mlt) really holds, compared with what
style_import.analyse() finds in the project's rendered video.

    truth(mlt)                       -> {'length', 'cuts', 'transitions', 'zooms', 'captions', 'overlays', 'sfx', 'music'}
    score(truth, report)             -> precision / recall / timing error per event kind
    python style_import_eval.py <project.mlt> <render.mp4> [...more pairs] [--json out.json]

What counts as an event in the project:
  cuts         a picture change on the main video track (the first video track): between two items, unless the
               second continues the first (same file, its in point where the first ended); full-frame video on an
               upper track (b-roll) cuts in and out. 'jump' = same file, later or earlier in it; 'new' = another file.
  transitions  an item's transition (dissolve...) and fades to / from black (fade_in / fade_out effects)
  zooms        a change of scale between two consecutive main-track items (size_position / zoom effects), i.e. a
               punch in or out at a cut, and keyframed zooms inside an item (push in / pull out)
  captions     items on a captions track (word_captions graphics: their words and times) and subtitle cues
  overlays     items on upper video tracks that are graphics, pictures or alpha clips (labels, pop-ups, stickers,
               lower thirds, titles), not captions and not full-frame b-roll
  sfx          short audio items (under 3 s) on audio tracks that are not music or dialogue, and files under an sfx
               folder
A render must be made from the project as saved (its time is the project's time).
"""
from __future__ import annotations

import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

GRAPHIC_EXT = {'.mov', '.png', '.webm', '.gif', '.apng', '.svg', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}
TOL = {'cuts': 0.07, 'transitions': 0.35, 'zooms': 0.1, 'punches': 0.1, 'push_ins': 0.5, 'captions': 0.25,
       'overlays': 0.35, 'sfx': 0.25, 'speed': 0.5, 'layout': 0.5}


def _sec(v):
    import letitedit.timeline.edit_script as es
    return float(es.to_seconds(v))


def _zoom_of(effects, w=1080, h=1920):
    """Scale an item's effects put on the picture: {zoom: s}, size_position rects ('x y w h' wider than the frame),
    1.0 when none. Keyframed values give their first and last scale."""
    first = last = 1.0
    for e in effects or []:
        if not isinstance(e, dict):
            continue
        if 'zoom' in e:
            z = e['zoom']
            if isinstance(z, dict) and 'keys' in z:
                ks = z['keys']
                first, last = float(ks[0][1]), float(ks[-1][1])
            elif isinstance(z, (int, float)):
                first = last = float(z)
        sp = e.get('size_position')
        if sp is not None:
            vals = []
            if isinstance(sp, str):
                for part in sp.split(';'):
                    nums = re.findall(r'-?\d+(?:\.\d+)?', part.split('=')[-1])
                    if len(nums) >= 4:
                        vals.append(float(nums[2]) / w)
            elif isinstance(sp, dict) and 'keys' in sp:
                for k in sp['keys']:
                    r = k[1] if len(k) > 1 else None
                    if isinstance(r, str):
                        nums = re.findall(r'-?\d+(?:\.\d+)?', r)
                        if len(nums) >= 4:
                            vals.append(float(nums[2]) / w)
                    elif isinstance(r, (list, tuple)) and len(r) >= 4:
                        vals.append(float(r[2]) / w)
            if vals:
                first, last = vals[0], vals[-1]
    return first, last


def _key(path):
    return str(path or '').replace('/', '\\').lower()


def _graphic_props(mlt):
    """{graphic file (lower case): (graphic recipe dict, caption name)} from the project file's shotcut_ai:graphic
    properties. Keyed by the producer's file, not by item id: ids in a saved project need not match the edit
    script's numbering, while each rendered graphic file is its own."""
    out = {}
    try:
        root = ET.parse(mlt).getroot()
    except ET.ParseError:
        return out
    for prod in root.iter():
        if prod.tag not in ('producer', 'chain'):
            continue
        props = {p.get('name'): (p.text or '') for p in prod.findall('property')}
        g = props.get('shotcut_ai:graphic') or props.get('letitedit:graphic')
        made = props.get('shotcut_ai:made') or props.get('letitedit:made')
        res = props.get('resource')
        if res and g:
            try:
                out[_key(res)] = (json.loads(g), props.get('shotcut:caption'))
            except ValueError:
                pass
        elif res and made:
            try:
                m = json.loads(made)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get('kind') == 'ass' and m.get('script'):
                out[_key(res)] = ({'template': 'ass', 'dialogue': ass_dialogue(m['script'])}, None)
    return out


def ass_dialogue(script):
    """[(start s, end s, text)] of an ASS script's Dialogue lines (override tags and line breaks taken out)."""
    out = []
    for ln in str(script).splitlines():
        if not ln.startswith('Dialogue:'):
            continue
        parts = ln.split(',', 9)
        if len(parts) < 10:
            continue

        def sec(v):
            h, m_, s_ = v.strip().split(':')
            return int(h) * 3600 + int(m_) * 60 + float(s_)
        try:
            a, b = sec(parts[1]), sec(parts[2])
        except ValueError:
            continue
        text = re.sub(r'\{[^}]*\}', '', parts[9]).replace('\\N', ' ').replace('\\n', ' ').strip()
        out.append((a, b, text))
    return out


def _rect_of(value, W, H):
    """(x, y, w, h) pixels of a size_position rect text 'x y w h [opacity]' (percent values allowed) or None."""
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return tuple(float(v) for v in value[:4])
    nums = re.findall(r'-?\d+(?:\.\d+)?%?', str(value).split('=')[-1])
    if len(nums) < 4:
        return None
    out = []
    for k, v in enumerate(nums[:4]):
        if v.endswith('%'):
            out.append(float(v[:-1]) / 100 * (W if k in (0, 2) else H))
        else:
            out.append(float(v))
    return tuple(out)


def _is_crop(e):
    return str(e.get('filter') or '').lower().replace(' ', '').replace('_', '').replace(':', '') in (
        'croprectangle', 'crop')


def _zoom_keys(effects, W=1080, H=1920):
    """An item's picture scale over its own time: [(t s from the item's start, scale, ease)], [] when it has no zoom.
    From {zoom: z | {keys}} or a size_position rect (static or keyframed); the scale is the rect's width over the
    frame's. A half-frame panel (size_position with a Crop: Rectangle) or a picture smaller than the frame (an inset)
    is a layout, not a zoom: []."""
    fx = [e for e in effects or [] if isinstance(e, dict)]
    if any(_is_crop(e) for e in fx):
        return []
    for e in fx:
        if 'zoom' in e:
            z = e['zoom']
            if isinstance(z, dict) and 'keys' in z:
                return [(float(k[0]), float(k[1]), k[2] if len(k) > 2 else 'linear') for k in z['keys']]
            if isinstance(z, (int, float)):
                return [(0.0, float(z), 'linear')]
        sp = e.get('size_position')
        if sp is None:
            continue
        if isinstance(sp, dict) and 'keys' in sp:
            out = []
            for k in sp['keys']:
                r = _rect_of(k[1], W, H) if len(k) > 1 else None
                if r:
                    out.append((float(k[0]), r[2] / W, k[2] if len(k) > 2 else 'linear'))
            if out and max(s for _, s, _ in out) < 0.92:
                return []
            return out
        r = _rect_of(sp, W, H)
        if r and r[2] / W >= 0.92:
            return [(0.0, r[2] / W, 'linear')]
    return []


def _scale_at(keys, t):
    """The scale of keyed zoom at t (s from the item's start): held before the first and after the last key, 'hold'
    keeps a key's value until the next, anything else is taken as a straight line between keys."""
    if not keys:
        return 1.0
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, s0, e0), (t1, s1, _) in zip(keys, keys[1:]):
        if t0 <= t < t1:
            if e0 == 'hold' or t1 - t0 < 1e-6:
                return s0
            return s0 + (s1 - s0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def _zoom_events(keys, at, ln, fps, item_id):
    """Zoom events inside one item: steps (the scale jumps within about two frames, or a 'hold' key gives way: a punch
    inside the shot) and ramps (a change spread over 0.3 s or more: a push-in or pull-out)."""
    out = []
    for (t0, s0, e0), (t1, s1, _) in zip(keys, keys[1:]):
        if t0 >= ln or abs(math.log(max(1e-6, s1) / max(1e-6, s0))) < 0.03:
            continue
        r = s1 / s0
        if e0 == 'hold' or t1 - t0 <= 2.5 / fps:
            if abs(r - 1) >= 0.04 and t1 < ln:
                out.append({'t': at + t1, 'kind': 'punch_in' if r > 1 else 'punch_out', 'scale': r, 'id': item_id,
                            'at_cut': False, 'inside': True})
        elif t1 - t0 >= 0.3:
            end = min(t1, ln)
            r = _scale_at(keys, end) / s0
            if abs(math.log(r)) >= 0.03:
                out.append({'t': at + t0, 'end': at + end, 'kind': 'push_in' if r > 1 else 'pull_out', 'scale': r,
                            'id': item_id})
    return out


_FRAMES = {}


def _grey_frame(path, t):
    """A small grey frame of a source file at t (for checking that two items show the same picture)."""
    import cv2
    import letitedit.looks.style_import as si
    key = (str(path), round(float(t), 3))
    if key not in _FRAMES:
        info = si.probe(path)
        fr = si.frames_at(path, [max(0.0, float(t))], 270, info)
        f = next(iter(fr.values()), None) if fr else None
        _FRAMES[key] = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f is not None else None
    return _FRAMES[key]


def same_picture(path, t_a, t_b):
    """Do two times of one source file show the same picture (the same framing of the same scene, before any zoom is
    applied)? Features matched with a similarity fit at a scale near 1 (bridge/style_import.feature_scale). A phone
    take moves on: a few seconds apart it often shows something else, and a cut there with a zoom change is a cut to a
    new picture, not a visible punch."""
    import letitedit.looks.style_import as si
    a, b = _grey_frame(path, t_a), _grey_frame(path, t_b)
    if a is None or b is None:
        return None
    fs = si.feature_scale(a, b)
    # measured on the ground-truth sets: the same picture matched 22-438 points at a scale within 3% (a talking head
    # that moved: 38 points, 28% of the matches); new pictures 3-12 points or an absurd fit
    return bool(fs and fs['inliers'] >= 20 and fs['ratio'] >= 0.2 and abs(fs['scale'] - 1) < 0.06
                and abs(fs['rotation_deg']) < 3 and math.hypot(fs['dx'], fs['dy']) < 0.15)


MOTION_NAMES = {'pop': 'scale', 'shrink': 'scale', 'spin': 'scale', 'bounce': 'scale', 'grow': 'scale',
                'drop': 'slide', 'fade': 'fade', 'none': 'cut'}


def _motion_of(it, W, H, g=None):
    """How an overlay item comes in and goes out: 'cut', 'fade', 'slide' or 'scale' (grow / shrink, pop, spin), from a
    popup or asset_sticker graphic's in / out, fade effects with opacity, keyframed size_position, or an ASS fade."""
    entry = exit_ = 'cut'
    if g is None and Path(str(it.get('clip') or '')).suffix.lower() in ('.mov', '.webm', '.gif', '.apng', '.mp4'):
        # a pre-rendered animation: how it comes in is drawn inside the file, unknown here
        entry = exit_ = None
    if g is not None:
        p = g.get('params') or {}
        tmpl = g.get('template')
        if tmpl in ('popup', 'asset_sticker'):
            full = str(p.get('fit') or '') in ('cover', 'contain', 'width')
            a_in = str(p.get('in') or ('none' if full else 'pop'))
            a_out = str(p.get('out') or ('none' if full else 'shrink'))
            entry = 'slide' if a_in.startswith('slide') else MOTION_NAMES.get(a_in, 'scale')
            exit_ = 'slide' if a_out.startswith('slide') else MOTION_NAMES.get(a_out, 'scale')
        elif tmpl == 'ass' and re.search(r'\\fade?\s*\(', str(g.get('script') or '')):
            entry = exit_ = 'fade'
    ln = float(it.get('len') or 0)
    for e in it.get('effects') or []:
        if not isinstance(e, dict):
            continue
        if 'fade_in' in e and e.get('opacity'):
            entry = 'fade'
        if 'fade_out' in e and e.get('opacity'):
            exit_ = 'fade'
        sp = e.get('size_position')
        if isinstance(sp, dict) and len(sp.get('keys') or []) >= 2:
            ks = [(float(k[0]), _rect_of(k[1], W, H)) for k in sp['keys'] if len(k) > 1 and _rect_of(k[1], W, H)]
            for which, pair in (('in', ks[:2]), ('out', ks[-2:])):
                if len(pair) < 2:
                    continue
                (ta, ra), (tb, rb) = pair
                if (which == 'in' and ta > 0.3) or (which == 'out' and tb < ln - 0.3):
                    continue
                grow = rb[2] / max(1e-6, ra[2])
                move = math.hypot((rb[0] + rb[2] / 2) - (ra[0] + ra[2] / 2), (rb[1] + rb[3] / 2) - (ra[1] + ra[3] / 2))
                kind = 'scale' if abs(math.log(max(1e-6, grow))) > 0.2 else 'slide' if move > 0.1 * W else None
                if kind and which == 'in':
                    entry = kind
                elif kind:
                    exit_ = kind
    return entry, exit_


def _layout_of(it, W, H):
    """What a video item shows of the frame: ('split', side) for a half-frame panel, ('inset', box) for a picture
    smaller than the frame (picture-in-picture), None for a full-frame picture. Boxes and sides as fractions."""
    fx = [e for e in it.get('effects') or [] if isinstance(e, dict)]
    crop = next((e for e in fx if _is_crop(e)), None)
    rect = _rect_of((crop.get('params') or {}).get('rect'), W, H) if crop else None
    if rect is None:
        sp = next((e.get('size_position') for e in fx if 'size_position' in e), None)
        if isinstance(sp, str):
            rect = _rect_of(sp, W, H)
    if rect is None:
        return None
    x0, y0 = max(0.0, rect[0] / W), max(0.0, rect[1] / H)
    x1, y1 = min(1.0, (rect[0] + rect[2]) / W), min(1.0, (rect[1] + rect[3]) / H)
    area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if area >= 0.92:
        return None
    if crop and 0.4 <= area <= 0.6:
        side = ('top' if y0 < 0.02 and y1 < 0.6 else 'bottom' if y1 > 0.98 and y0 > 0.4 else
                'left' if x0 < 0.02 and x1 < 0.6 else 'right')
        return ('split', side)
    if area < 0.45:
        return ('inset', [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)])
    return None


def _merge_layout(events):
    """Split halves that overlap in time become one split screen ('top_bottom' or 'left_right')."""
    splits = sorted([e for e in events if e['kind'] == 'split'], key=lambda e: e['t'])
    rest = [e for e in events if e['kind'] != 'split']
    merged = []
    for e in splits:
        hit = next((m for m in merged if min(m['end'], e['end']) - max(m['t'], e['t']) > 0.5), None)
        if hit:
            hit['t'], hit['end'] = min(hit['t'], e['t']), max(hit['end'], e['end'])
            hit['sides'] = sorted(set(hit['sides']) | {e['where']})
        else:
            merged.append({**e, 'sides': [e['where']]})
    for m in merged:
        sides = set(m.pop('sides'))
        m['where'] = 'top_bottom' if sides & {'top', 'bottom'} else 'left_right'
    return sorted(merged + rest, key=lambda e: e['t'])


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
FIXES = _paths.CODE_ROOT / 'tools' / 'style_import' / 'truth_fixes.json'


def _fixes(mlt):
    """Hand-checked corrections to what a project file says (tools/style_import/truth_fixes.json): e.g. caption lines
    drawn as pictures on an upper track are captions, not overlays."""
    try:
        d = json.loads(FIXES.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    name = str(mlt).replace('/', '\\').lower()
    for k, v in d.items():
        if not k.startswith('_') and name.endswith(k.replace('/', '\\').lower()):
            return v
    return {}


def _source_fixes():
    """{file name (lower case): [{at, kind, ...}]}: hand-checked visible events inside source files."""
    try:
        d = json.loads(FIXES.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    return {k.lower(): v for k, v in (d.get('_sources') or {}).items()}


AUDIO_EXT = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.aif', '.aiff', '.wma'}
_ONSETS = {}


def sound_onset(file_name):
    """Where a sound from the asset library actually starts (its onset_s in assets/manifest: some begin with a little
    silence or a build-up), 0 for other files."""
    if not _ONSETS:
        root = _paths.CODE_ROOT / 'assets' / 'manifest'
        for m in root.glob('*.json'):
            try:
                d = json.loads(m.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                continue
            for it in d.get('items') or []:
                if it.get('file') and it.get('onset_s') is not None:
                    _ONSETS[Path(it['file']).name.lower()] = float(it['onset_s'])
        _ONSETS.setdefault('', 0.0)
    return _ONSETS.get(str(file_name).lower(), 0.0)
TEXT_TEMPLATES = ('ass', 'text_pop', 'title_card', 'lower_third', 'chapter_card', 'big_number')


def _truth_main_track(main, W, H, fps, out, src_fix, length, check_sources):
    """Read cuts, transitions, zooms and speed from the main picture track."""
    prev = None
    prev_keys = None
    for it in main['items']:
        if 'gap' in it:
            prev = None
            continue
        at = _sec(it['at'])
        ln = float(it.get('len') or 0)
        keys = _zoom_keys(it.get('effects'), W, H)
        out['zooms'] += _zoom_events(keys, at, ln, fps, it.get('id'))
        sp = float(it.get('speed') or 1.0)
        for sev in src_fix.get(Path(str(it.get('clip') or '')).name.lower(), []):
            s_in = float(it.get('in') or 0)
            if s_in <= sev['at'] < s_in + ln * sp - 0.05 and sev.get('kind') in ('punch_in', 'punch_out'):
                out['zooms'].append({'t': at + (sev['at'] - s_in) / sp, 'kind': sev['kind'], 'scale': sev.get('scale'),
                                     'id': it.get('id'), 'at_cut': False, 'inside': True, 'source_event': True})
        if abs(sp - 1.0) > 0.02 and 'clip' in it:
            out['speed'].append({'t': at, 'end': at + ln, 'speed': sp, 'id': it.get('id')})
        lay = _layout_of(it, W, H)
        if lay:
            out['layout'].append({'t': at, 'end': at + ln, 'kind': lay[0], 'where': lay[1], 'id': it.get('id'),
                                  'track': main.get('name')})
        for e in it.get('effects') or []:
            if isinstance(e, dict) and 'fade_in' in e and not isinstance(e['fade_in'], bool):
                out['transitions'].append({'t': at, 'kind': 'fade_in' if at < 0.05 else 'fade_black',
                                           'len': float(e['fade_in']), 'id': it.get('id')})
            if isinstance(e, dict) and 'fade_out' in e and not isinstance(e['fade_out'], bool):
                end = at + ln
                out['transitions'].append({'t': end, 'kind': 'fade_out' if end > length - 0.05 else 'fade_black',
                                           'len': float(e['fade_out']), 'id': it.get('id')})
        if prev is not None:
            same_file = str(prev.get('clip')) == str(it.get('clip'))
            gap_src = abs(float(prev.get('out', 0)) - float(it.get('in', 0)))
            continuous = same_file and gap_src < 0.05
            pz = _scale_at(prev_keys, float(prev.get('len') or 0)) if prev_keys else 1.0
            z0 = _scale_at(keys, 0.0) if keys else 1.0
            tr = it.get('transition')
            if tr:
                kind = tr.get('type', 'dissolve') if isinstance(tr, dict) else 'dissolve'
                tl = float(tr.get('len', 0.5)) if isinstance(tr, dict) else float(tr)
                out['transitions'].append({'t': at, 'kind': kind, 'len': tl, 'id': it.get('id')})
            if not continuous:
                out['cuts'].append({'t': at, 'kind': 'jump' if same_file else 'new', 'id': it.get('id'),
                                    'transition': bool(tr)})
            # a change of zoom is a visible punch only when both sides show the same picture: a continuous cut, or a
            # jump within the same file whose source frames on both sides match (a phone take moves on, so a few
            # seconds later it often shows something else: a cut to a new picture that happens to be zoomed)
            if abs(z0 / pz - 1) >= 0.04 and same_file and 'clip' in it:
                if continuous:
                    same = True
                elif check_sources:
                    same = same_picture(it['clip'], float(prev.get('out', 0)) - 1.0 / fps, float(it.get('in', 0)))
                else:
                    same = gap_src <= 3.0
                ev = {'t': at, 'kind': 'punch_in' if z0 > pz else 'punch_out', 'scale': z0 / pz, 'id': it.get('id'),
                      'at_cut': not continuous}
                if same:
                    out['zooms'].append(ev)
                else:
                    out['not_punches'].append({**ev, 'why': 'the source picture changes across the cut'})
        prev = it
        prev_keys = keys


def _truth_overlays(fix, vtracks, main, gprops, W, H, out, length):
    """Read caption graphics, overlays and cutaways from the upper video tracks."""
    caption_files = {str(x).lower() for x in fix.get('caption_files') or []}
    for t in vtracks:
        if t is main:
            continue
        name = str(t.get('name') or '')
        is_cap_track = 'caption' in name.lower() or 'subtitle' in name.lower()
        for it in t['items']:
            if 'gap' in it:
                continue
            at = _sec(it['at'])
            ln = float(it.get('len') or 0)
            clip = str(it.get('clip') or '')
            g, capname = gprops.get(_key(clip), (None, None))
            if g is None and isinstance(it.get('graphic'), dict):
                g = it['graphic']
            if g is None and it.get('ass'):
                g = {'template': 'ass', 'script': it['ass'], 'dialogue': ass_dialogue(it['ass'])}
            ext = Path(clip).suffix.lower()
            if is_cap_track or capname or (g and g.get('template') in ('word_captions', 'captions')) or \
                    Path(clip).name.lower() in caption_files:
                words = []
                if g and isinstance(g.get('params'), dict):
                    for wd in g['params'].get('words') or []:
                        if isinstance(wd, (list, tuple)) and len(wd) >= 3:
                            words.append({'w': wd[0], 's': at + float(wd[1]), 'e': at + float(wd[2])})
                out['captions'].append({'t': at, 'end': at + ln, 'text': ' '.join(w['w'] for w in words) or None,
                                        'words': words, 'id': it.get('id'), 'track': name})
                continue
            graphic = 'graphic' in it or 'motion' in it or 'ass' in it or ext in GRAPHIC_EXT or bool(g)
            entry, exit_ = _motion_of(it, W, H, g)
            typ = 'graphic'
            if g:
                p = g.get('params') or {}
                if g.get('template') in TEXT_TEMPLATES or (g.get('template') == 'popup' and not p.get('image')
                                                           and not p.get('emoji')):
                    typ = 'text'
            typ = (fix.get('types') or {}).get(Path(clip).name, typ)
            if graphic and g and g.get('template') == 'ass' and g.get('dialogue'):
                # a subtitle-style graphic showing a sequence of labels: one overlay per label it shows
                src_in = float(it.get('in') or 0)
                for a, b, text in g['dialogue']:
                    a2, b2 = at + a - src_in, at + b - src_in
                    if b2 > at and a2 < at + ln:
                        out['overlays'].append({'t': max(at, a2), 'end': min(at + ln, b2), 'id': it.get('id'),
                                                'track': name, 'file': Path(clip).name if clip else None,
                                                'template': 'ass', 'text': text, 'type': 'text', 'entry': entry,
                                                'exit': exit_})
            elif graphic:
                ov = {'t': at, 'end': at + ln, 'id': it.get('id'), 'track': name,
                      'file': Path(clip).name if clip else None, 'template': (g or {}).get('template'), 'type': typ,
                      'entry': entry, 'exit': exit_}
                p = (g or {}).get('params') or {}
                if (g or {}).get('template') in ('popup', 'asset_sticker') and 'x' in p and 'y' in p:
                    # where it sits: centred on (x, y), its longest side size x the frame's shorter side
                    half = float(p.get('size') or 0.3) * min(W, H) / 2
                    x, y = float(p['x']), float(p['y'])
                    ov['box'] = [round(max(0.0, x - half / W), 3), round(max(0.0, y - half / H), 3),
                                 round(min(1.0, x + half / W), 3), round(min(1.0, y + half / H), 3)]
                out['overlays'].append(ov)
            else:
                lay = _layout_of(it, W, H)
                if lay:
                    # a picture on part of the frame: a split-screen half or an inset (picture-in-picture); the main
                    # picture goes on around it, so it is not a cut
                    out['layout'].append({'t': at, 'end': at + ln, 'kind': lay[0], 'where': lay[1],
                                          'id': it.get('id'), 'track': name})
                    continue
                # full-frame video above the main track: b-roll, it cuts in and out
                out['cuts'].append({'t': at, 'kind': 'broll_in', 'id': it.get('id'), 'track': name})
                if at + ln < length - 0.05:
                    out['cuts'].append({'t': at + ln, 'kind': 'broll_out', 'id': it.get('id'), 'track': name})


def _truth_sound(atracks, out):
    """Read music and sound-effect timing from audio tracks."""
    for t in atracks:
        name = str(t.get('name') or '').lower()
        music = 'music' in name or 'score' in name or 'song' in name
        for it in t['items']:
            if 'gap' in it:
                continue
            at = _sec(it['at'])
            ln = float(it.get('len') or 0)
            clip = str(it.get('clip') or '')
            if music:
                out['music'].append({'t': at, 'end': at + ln, 'file': Path(clip).name})
            elif Path(clip).suffix.lower() in AUDIO_EXT and (ln < 3.0 or 'sfx' in clip.lower() or 'sfx' in name):
                # a sound file; a picture's own sound moved to a J/L-cut track is not an effect. Its time is where
                # the sound starts to be heard (the library's onset, past the item's in point)
                on = max(0.0, sound_onset(Path(clip).name) - float(it.get('in') or 0))
                out['sfx'].append({'t': at + on, 'end': at + ln, 'file': Path(clip).name, 'track': t.get('name'),
                                   'onset_s': round(on, 3)})


def truth(mlt, check_sources=True):
    import letitedit.timeline.edit_script as es
    s = es.read(str(mlt))
    prof = s['profile']
    W, H = int(prof.get('width') or 1080), int(prof.get('height') or 1920)
    fps = float(prof.get('fps') or 30.0)
    length = _sec(s['length'])
    gprops = _graphic_props(mlt)
    fix = _fixes(mlt)
    src_fix = _source_fixes()
    vtracks = [t for t in s['tracks'] if t.get('kind') == 'video']
    atracks = [t for t in s['tracks'] if t.get('kind') == 'audio']
    main = next((t for t in vtracks if t.get('name') == 'V1'), vtracks[0] if vtracks else None)
    out = {'length': length, 'cuts': [], 'transitions': [], 'zooms': [], 'captions': [], 'overlays': [], 'sfx': [],
           'music': [], 'speed': [], 'layout': [], 'not_punches': [], 'profile': prof}
    if main is None:
        return out
    _truth_main_track(main, W, H, fps, out, src_fix, length, check_sources)

    _truth_overlays(fix, vtracks, main, gprops, W, H, out, length)

    # subtitle feeds burned into the picture (a burn-in style on them) are captions too; a feed named for a title
    # (a hook line, a label, a chapter) carries text laid on the picture that is not the speech: overlays
    for feed in s.get('captions') or []:
        if feed.get('burn_in') is False or not feed.get('style', True):
            continue
        titled = re.search(r'hook|title|label|chapter|heading|name|text', str(feed.get('track') or ''), re.I) and \
            not re.search(r'caption|subtitle', str(feed.get('track') or ''), re.I)
        for cue in feed.get('cues') or []:
            a, b = _sec(cue['start']), _sec(cue['end'])
            if titled:
                out['overlays'].append({'t': a, 'end': b, 'text': cue.get('text'), 'track': f"subtitles {feed.get('track')}",
                                        'type': 'text', 'entry': 'cut', 'exit': 'cut'})
                continue
            out['captions'].append({'t': a, 'end': b, 'text': cue.get('text'), 'words': [],
                                    'track': f"subtitles {feed.get('track')}"})
    _truth_sound(atracks, out)

    out['layout'] = _merge_layout(out['layout'])
    out['cuts'].sort(key=lambda c: c['t'])
    # the cut list: one per time (b-roll edges can coincide with main-track cuts)
    dedup = []
    for c in out['cuts']:
        if dedup and abs(dedup[-1]['t'] - c['t']) < 0.02:
            continue
        dedup.append(c)
    out['cuts'] = [c for c in dedup if 0.02 < c['t'] < length - 0.02]
    for k in ('transitions', 'zooms', 'captions', 'overlays', 'sfx', 'speed', 'layout'):
        out[k].sort(key=lambda e: e['t'])
    if fix:
        out['fixes'] = {k: v for k, v in fix.items() if not k.startswith('_')}
    return out


def match(truth_times, found_times, tol):
    """Greedy one-to-one matching by time: (pairs [(i_truth, j_found, dt)], unmatched truth, unmatched found)."""
    cand = sorted(((abs(t - f), i, j) for i, t in enumerate(truth_times) for j, f in enumerate(found_times)
                   if abs(t - f) <= tol))
    ti, fj, pairs = set(), set(), []
    for dt, i, j in cand:
        if i in ti or j in fj:
            continue
        ti.add(i)
        fj.add(j)
        pairs.append((i, j, found_times[j] - truth_times[i]))
    return pairs, [i for i in range(len(truth_times)) if i not in ti], [j for j in range(len(found_times)) if j not in fj]


def pr(n_truth, n_found, n_match):
    p = n_match / n_found if n_found else None
    r = n_match / n_truth if n_truth else None
    f = 2 * p * r / (p + r) if p and r else None
    return {'truth': n_truth, 'found': n_found, 'matched': n_match, 'precision': None if p is None else round(p, 3),
            'recall': None if r is None else round(r, 3), 'f1': None if f is None else round(f, 3)}


def _found(report, kind):
    """The analysis' events of one kind as times (and the events)."""
    if kind == 'cuts':
        ev = [c for c in (report.get('cuts') or []) if c.get('kind') != 'jump?']
        return [c['t'] for c in ev], ev
    if kind == 'cuts_all':
        ev = report.get('cuts') or []
        return [c['t'] for c in ev], ev
    if kind == 'transitions':
        ev = [g for g in report.get('transitions') or [] if g.get('kind') not in ('cut',)]
        return [g['t'] for g in ev], ev
    if kind == 'zooms':
        ev = [z for z in report.get('zooms') or []]
        return [z['t'] for z in ev], ev
    if kind == 'punches':
        ev = [z for z in report.get('zooms') or [] if z['kind'] in ('punch_in', 'punch_out')]
        return [z['t'] for z in ev], ev
    if kind == 'push_ins':
        ev = [z for z in report.get('zooms') or [] if z['kind'] in ('push_in', 'pull_out')]
        return [z['t'] for z in ev], ev
    if kind == 'captions':
        ev = [e for e in report.get('text_events') or [] if e.get('role') == 'caption']
        return [c['t'] for c in ev], ev
    if kind == 'overlays':
        ev = [o for o in (report.get('overlays') or {}).get('events') or [] if o.get('conf', 0) >= 0.5]
        return [o['t'] for o in ev], ev
    if kind == 'sfx':
        ev = ((report.get('sound') or {}).get('sfx') or {}).get('events') or []
        return [s['t'] for s in ev], ev
    if kind in ('speed', 'layout'):
        ev = [e for e in (report.get(kind) or {}).get('events') or [] if e.get('conf', 1) >= 0.5]
        return [e['t'] for e in ev], ev
    return [], []


def match_spans(truth_ev, found_ev, tol):
    """One-to-one matching of stretches (push-ins, speed changes, layouts): a found stretch matches a true one when
    they overlap by at least 30% of their union, or start within tol. Greedy by overlap."""
    cand = []
    for i, t in enumerate(truth_ev):
        a0, a1 = t['t'], t.get('end', t['t'])
        for j, f in enumerate(found_ev):
            b0, b1 = f['t'], f.get('end', f['t'])
            inter = max(0.0, min(a1, b1) - max(a0, b0))
            union = max(1e-6, max(a1, b1) - min(a0, b0))
            iou = inter / union
            if iou >= 0.3 or abs(a0 - b0) <= tol:
                cand.append((-iou, abs(a0 - b0), i, j))
    cand.sort()
    ti, fj, pairs = set(), set(), []
    for _, _, i, j in cand:
        if i in ti or j in fj:
            continue
        ti.add(i)
        fj.add(j)
        pairs.append((i, j, found_ev[j]['t'] - truth_ev[i]['t']))
    return pairs, [i for i in range(len(truth_ev)) if i not in ti], [j for j in range(len(found_ev)) if j not in fj]


def score(tr, report, kinds=('cuts', 'transitions', 'punches', 'push_ins', 'captions', 'overlays', 'sfx')):
    out = {}
    for kind in kinds:
        if kind == 'punches':
            truth_ev = [z for z in tr['zooms'] if z['kind'] in ('punch_in', 'punch_out')]
        elif kind == 'push_ins':
            truth_ev = [z for z in tr['zooms'] if z['kind'] in ('push_in', 'pull_out')]
        elif kind == 'cuts':
            truth_ev = tr['cuts']
            # a cut inside a transition is the transition's: compare plain cuts with plain cuts
            truth_ev = [c for c in truth_ev if not c.get('transition')]
        elif kind == 'transitions':
            truth_ev = [t for t in tr['transitions'] if t['kind'] not in ('fade_in', 'fade_out') or t['len'] >= 0.2]
        else:
            truth_ev = tr.get(kind) or []
        ft, fev = _found(report, kind)
        if kind == 'cuts':
            # transitions found as gradual changes are not cuts: drop found cuts inside them; a punch found as a cut
            # where the project zooms within one continuous shot is the punch (scored there), not a cut
            spans = [(g.get('start', g['t']) - 0.05, g.get('end', g['t']) + 0.05)
                     for g in report.get('transitions') or [] if g.get('kind') in ('dissolve', 'fade_black', 'fade_white')]
            inner = [z['t'] for z in tr['zooms'] if z['kind'] in ('punch_in', 'punch_out') and not z.get('at_cut')
                     and not any(abs(z['t'] - c['t']) <= 0.1 for c in tr['cuts'])]
            keep = [k for k, t in enumerate(ft) if not any(a <= t <= b for a, b in spans)
                    and not (fev[k].get('kind') == 'punch' and any(abs(t - z) <= 0.1 for z in inner))]
            ft, fev = [ft[k] for k in keep], [fev[k] for k in keep]
        tt = [e['t'] for e in truth_ev]
        tol = TOL[kind]
        if kind == 'captions':
            spans = [(e['t'], e.get('end', e['t'])) for e in truth_ev]
            cand = sorted((abs(ft[j] - a), i, j) for i, (a, b) in enumerate(spans) for j in range(len(ft))
                          if a - tol <= ft[j] <= max(a + tol, b - 0.05))
            ti, fj, pairs = set(), set(), []
            for dt, i, j in cand:
                if i in ti or j in fj:
                    continue
                ti.add(i)
                fj.add(j)
                pairs.append((i, j, ft[j] - tt[i]))
            mt = [i for i in range(len(tt)) if i not in ti]
            mf = [j for j in range(len(ft)) if j not in fj]
        elif kind == 'transitions':
            pairs, mt, mf = match(tt, ft, max(tol, 0.0))
            # a long transition: its middle can sit up to half its length from the edit point
            extra = []
            for i in list(mt):
                L = float(truth_ev[i].get('len') or 0)
                for j in list(mf):
                    if abs(ft[j] - tt[i]) <= max(tol, L * 0.75 + 0.1):
                        extra.append((i, j, ft[j] - tt[i]))
                        mt.remove(i)
                        mf.remove(j)
                        break
            pairs += extra
        elif kind in ('push_ins', 'speed', 'layout'):
            pairs, mt, mf = match_spans(truth_ev, fev, tol)
        else:
            pairs, mt, mf = match(tt, ft, tol)
        res = pr(len(tt), len(ft), len(pairs))
        if pairs:
            errs = [abs(p[2]) for p in pairs]
            res['timing_error_s'] = {'median': round(float(sorted(errs)[len(errs) // 2]), 3),
                                     'max': round(max(errs), 3)}
        res['missed'] = [{'t': round(tt[i], 3), **{k: v for k, v in truth_ev[i].items()
                                                   if k in ('kind', 'id', 'text', 'file', 'track', 'type', 'speed',
                                                            'where', 'end')}}
                         for i in mt][:30]
        res['extra'] = [{'t': round(ft[j], 3), **{k: v for k, v in fev[j].items()
                                                  if k in ('kind', 'conf', 'text', 'box', 'role', 'speed', 'where',
                                                           'end', 'type')}} for j in mf][:30]
        if kind == 'overlays':
            # how well each kind of overlay is found, and whether the way a matched one comes in and goes out is
            # measured right (cut, fade, slide, scale)
            by = {}
            for i, o in enumerate(truth_ev):
                by.setdefault(o.get('type') or 'graphic', [0, 0])[0] += 1
            for i, j, _ in pairs:
                by[truth_ev[i].get('type') or 'graphic'][1] += 1
            res['recall_by_type'] = {k: f'{v[1]}/{v[0]}' for k, v in by.items()}
            for key in ('entry', 'exit'):
                n = ok = 0
                conf = {}
                for i, j, _ in pairs:
                    want, got = truth_ev[i].get(key), fev[j].get(key)
                    if want and got:
                        n += 1
                        ok += want == got
                        conf[f'{want}->{got}'] = conf.get(f'{want}->{got}', 0) + 1
                res[f'{key}_ok'] = f'{ok}/{n}'
                res[f'{key}_confusion'] = dict(sorted(conf.items(), key=lambda kv: -kv[1]))
        if kind in ('speed', 'layout'):
            n = ok = 0
            for i, j, _ in pairs:
                n += 1
                if kind == 'speed':
                    ok += (truth_ev[i]['speed'] > 1) == ((fev[j].get('speed') or 1) > 1)
                else:
                    ok += truth_ev[i]['kind'] == fev[j].get('kind')
            res['kind_ok'] = f'{ok}/{n}'
        if kind == 'cuts':
            by = {}
            for i, c in enumerate(truth_ev):
                by.setdefault(c['kind'], [0, 0])
                by[c['kind']][0] += 1
            for i, j, _ in pairs:
                by[truth_ev[i]['kind']][1] += 1
            res['recall_by_kind'] = {k: f'{v[1]}/{v[0]}' for k, v in by.items()}
        if kind == 'captions':
            # text: matched captions whose read words are (mostly) the true caption's words: 70% of the words read
            # are in the truth, ignoring case and punctuation (a caption read before all its words popped in counts)
            good = 0
            tot = 0
            for i, j, _ in pairs:
                t_txt = truth_ev[i].get('text')
                f_txt = fev[j].get('text')
                if t_txt and f_txt:
                    tot += 1
                    tw, fw = _norm(t_txt).split(), _norm(f_txt).split()
                    if fw and sum(1 for w in fw if w in tw) >= 0.7 * len(fw):
                        good += 1
            res['text_read_ok'] = f'{good}/{tot}'
            if pairs:
                lag = sorted(p[2] for p in pairs)
                res['start_offset_s'] = {'median': round(lag[len(lag) // 2], 3), 'p90': round(lag[int(0.9 * (len(lag) - 1))], 3)}
        out[kind] = res
    return out


def _norm(s):
    return re.sub(r'[^a-z0-9 ]+', '', str(s).lower()).strip()


def evaluate(pairs, kinds=None, analyse_kw=None, progress=print):
    import letitedit.looks.style_import as style_import
    rows = []
    totals = {}
    for mlt, mp4 in pairs:
        tr = truth(mlt)
        rep = style_import.analyse(mp4, **(analyse_kw or {}))
        sc = score(tr, rep, kinds or ('cuts', 'transitions', 'zooms', 'captions', 'overlays', 'sfx'))
        rows.append({'project': str(mlt), 'render': str(mp4), 'scores': sc})
        for k, v in sc.items():
            t = totals.setdefault(k, [0, 0, 0])
            t[0] += v['truth']
            t[1] += v['found']
            t[2] += v['matched']
        if progress:
            progress(f'{Path(mlt).name}: ' + ', '.join(f"{k} P={v['precision']} R={v['recall']} ({v['matched']}/{v['truth']})"
                                                      for k, v in sc.items()))
    return {'per_video': rows, 'totals': {k: pr(*v) for k, v in totals.items()}}


if __name__ == '__main__':
    args = sys.argv[1:]
    out_json = None
    if '--json' in args:
        k = args.index('--json')
        out_json = args[k + 1]
        args = args[:k] + args[k + 2:]
    pairs = list(zip(args[0::2], args[1::2]))
    res = evaluate(pairs)
    print(json.dumps(res['totals'], indent=1))
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1), encoding='utf-8')
