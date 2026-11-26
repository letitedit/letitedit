"""Effects at moments: a batch of mixed effects the AI planned (things popping up as they are mentioned, text pops,
zoom punches, shakes, flashes, whooshes, sounds, count-ups, place tags, b-roll cutaways...), placed as ONE change and
measured against the style's rules (STYLES.md, "Effects: what, when and where"). Manual items specify moments; auto
plans candidates from cached words and cuts. This places them and says which rules each placement breaks.

    {op: fx, items: [{at | words (+ near), preset | kind, id?, said?, trigger?, ...look fields}],
     auto?: true, model?: local 3D file, check: warn | strict | off, pack?, platform?}

Each item is one effect at one moment: `preset` names one of the style's effects (its kind, look, sound and rules),
`kind` a bare kind (style_pack.EFFECT_KINDS) with the defaults below; fields on the item override the preset's.
`words` places it where a phrase is said on the timeline (its first place, or the one nearest `near`); `said` (the
words that called for it) is checked against what is said there; `trigger` against the preset's triggers.

What each kind makes:
    popup, text_pop      a sticker (picture, emoji or text) on the style's effects track (graphics_templates/popup)
    zoom_punch, shake, glitch, effect   a keyframed effect added to the main-track clip under the moment
    flash                a colour flash on the effects track
    whoosh, sfx          a sound on the effects sound track (a whoosh lands its peak on the moment: sfx_offset_s)
    count_up, location, motion   a motion clip (letitedit_motion block) on the effects track
    graphic              a graphic (letitedit_graphic template) on the effects track
    light_leak           a light-leak shot effect on the effects track
    broll                a cutaway clip (muted, filling the frame) on the B-roll track just above the main track; fit
                         top | bottom | left | right fills that half of the frame instead (a split layout: the
                         speaker stays in the other half)
    transition           the transition into the main-track clip that starts at the moment (the rest of the batch is
                         mapped onto the new timing); transition.type cutaway_negative addresses a B-roll clip id,
                         edge in/out and len .03-.2 seconds, without changing the main speaker
    item                 any timeline item on the preset's track
Sounds: the item's sfx, else the preset's, else the pack's sfx.events for that kind (only when the pack maps one).

Checks (warn: placed and listed; strict: nothing is placed when any rule is broken; off): the presets' density
(per_10s, per_min, min_gap_s, counting the effects already there), duration_s, triggers, placement (zone and avoid:
face, captions, covered) and never rules (over_face, over_captions, outside_safe_zone, overlapping, first_s,
last_s), and the style's fx.density and fx.never over all effects together. Faces come from the local face finder
on the source frame (OpenCV YuNet, when its model is on this PC); caption boxes from the project's captions; covered
areas from letitedit_platforms (fx.safe_zone or `platform`; 'phone' = YouTube Shorts, TikTok and Reels together).
"""
from __future__ import annotations

import copy
import os
import re
import tempfile
from pathlib import Path

import letitedit.looks.style_pack as style_pack

ID_PREFIX = 'fx-'
POP_PREFIX = 'pop-'
CHECKS = ('warn', 'strict', 'off')
OVERLAY_KINDS = ('popup', 'text_pop', 'flash', 'count_up', 'location', 'motion', 'graphic', 'three_d', 'light_leak', 'broll',
                 'item')
CLIP_KINDS = ('zoom_punch', 'push_in', 'shake', 'glitch', 'effect')
MOVE_KIND = 'camera_move'
SOUND_KINDS = ('whoosh', 'sfx')
PHONE = ('youtube_shorts', 'tiktok', 'instagram_reels')
PANEL_FITS = ('top', 'bottom', 'left', 'right')    # a cutaway that fills half the frame (a split layout)
MODERN_TRANSITIONS = {
    'whip_left': ('slideleft', 'avgblur=sizeX=16:sizeY=1'),
    'whip_right': ('slideright', 'avgblur=sizeX=16:sizeY=1'),
    'zoom_through': ('fade', None),
    'slide_left': ('slideleft', None), 'slide_right': ('slideright', None),
    'slide_up': ('slideup', None), 'slide_down': ('slidedown', None),
    'push_left': ('smoothleft', None), 'push_right': ('smoothright', None),
    'light_leak': ('fadewhite', None),
    'spin': ('fade', None),
    'clean_glitch': ('fade', None),
}
STICKER_KEYS = ('in', 'out', 'in_s', 'out_s', 'wiggle', 'tilt', 'shadow', 'outline', 'outline_color', 'font', 'fill',
                'stroke', 'stroke_width', 'size')
KIND_DEFAULTS = {
    'popup': {'size': 0.28, 'in': 'pop', 'out': 'shrink', 'in_s': 0.28, 'out_s': 0.2, 'hold_s': 1.2,
              'position': 'upper_right', 'shadow': True, 'outline': 0, 'outline_color': 'light', 'event': 'popup'},
    'text_pop': {'size': 0.62, 'in': 'pop', 'out': 'fade', 'in_s': 0.22, 'out_s': 0.2, 'hold_s': 0.9,
                 'position': 'center', 'fill': 'secondary', 'stroke': 'dark', 'stroke_width': 12, 'font': 'heading',
                 'shadow': True, 'tilt': -3, 'event': 'text'},
    'zoom_punch': {'scale': 1.15, 'ramp_s': 0.08, 'len': None, 'event': 'zoom'},
    'push_in': {'scale': 1.12, 'len': 2.0, 'event': 'zoom'},
    'shake': {'amount': 0.5, 'len': 0.35, 'speed': 0.6, 'event': 'shake'},
    'flash': {'color': 'light', 'len': 0.25, 'opacity': 0.85, 'event': 'flash'},
    'glitch': {'amount': 0.6, 'len': 0.4, 'event': 'transition'},
    'whoosh': {'sfx_offset_s': -0.2, 'event': 'transition'},
    'transition': {'transition': {'type': 'dissolve', 'len': 0.3}, 'event': None},
    'sfx': {'event': None},
    'count_up': {'block': 'count_up', 'params': {}, 'len': None, 'event': 'count'},
    'location': {'block': 'location', 'params': {}, 'len': None, 'event': 'place'},
    'broll': {'fit': 'cover', 'len': None, 'event': None},
    'light_leak': {'params': {}, 'len': 1.5, 'event': None},
    'graphic': {'params': {}, 'len': None, 'event': None},
    'motion': {'params': {}, 'len': None, 'event': None},
    'three_d': {'params': {}, 'len': None, 'event': None},
    'effect': {'event': None},
    'camera_move': {'event': None},
    'item': {'event': None},
}
ITEM_KEYS = {'at', 'words', 'near', 'preset', 'kind', 'id', 'said', 'trigger', 'clip', 'in', 'out', 'text', 'asset',
             'position', 'zone', 'len', 'sfx', 'sfx_offset_s', 'sfx_gain_db', 'params', 'block', 'template', 'scale',
             'ramp_s', 'focus', 'amount', 'speed', 'color', 'opacity', 'fit', 'transition', 'effect', 'item', 'track',
             'hold_s', 'note', 'radius', 'model', 'move', 'extra_per_s', 'drift_per_s', 'max_scale', 'push', 'ease', 'replace',
             'sound_target',
             *STICKER_KEYS}


def _es():
    import letitedit.timeline.edit_script as es
    return es


# ------------------------------------------------------------------ the frame: faces, captions, covered areas

class Frame:
    """What is on screen when: the project size, faces per moment (lazily), caption boxes and covered areas."""

    def __init__(self, script, kit, platform=None):
        prof = script.get('profile') or {}
        self.script, self.kit = script, kit
        self.w, self.h = int(prof.get('width', 1920)), int(prof.get('height', 1080))
        self.short = min(self.w, self.h)
        self._faces = {}
        self.face_note = None
        self.captions = _caption_boxes(script, kit, self.w, self.h)
        self.platform = platform or (kit.get('fx') or {}).get('safe_zone')
        self.covered = _covered(self.platform)

    def faces(self, t):
        """Face boxes [(x0, y0, x1, y1) fractions] on the main track at timeline time t; None when unknown."""
        key = round(float(t), 2)
        if key in self._faces:
            return self._faces[key]
        out = None
        try:
            import letitedit.review.checks as checks
            if not checks.YUNET.exists():
                self.face_note = 'faces not checked: the face model is not on this PC'
            else:
                hit = _main_clip_at(self.script, t)
                if hit:
                    it, s, e = hit
                    src_t = float(it['in']) + (float(t) - s) * float(it.get('speed', 1.0))
                    import letitedit.pictures.graphics as graphics
                    boxes = []
                    # A blink, turn or motion blur can lose one frame. Nearby frames still establish
                    # where the face is for this short effect.
                    with tempfile.TemporaryDirectory() as d:
                        for delta in (0.0, -0.2, 0.2, -0.4, 0.4):
                            sample = min(float(it['out']) - 0.05, max(float(it['in']), src_t + delta))
                            img = graphics.still(it['clip'], sample, size=(self.w, self.h)).convert('RGB')
                            png = Path(d) / 'f.png'
                            img.save(png)
                            boxes = checks.faces_in(png)
                            if boxes:
                                break
                    out = [(x0 / self.w, y0 / self.h, x1 / self.w, y1 / self.h) for x0, y0, x1, y1 in boxes]
        except Exception as exc:  # noqa: BLE001 - a missing face check is a note, never a failed edit
            self.face_note = f'faces not checked ({type(exc).__name__}: {exc})'
            out = None
        self._faces[key] = out
        return out

    def captions_at(self, a, b):
        return [box for s, e, box in self.captions if s < b and e > a]

    def caption_words_at(self, a, b):
        from letitedit.timeline.edit_sync import layout
        out = []
        for cap in self.script.get('captions') or []:
            for cue in cap.get('cues') or []:
                if _es().to_seconds(cue['start']) < b and _es().to_seconds(cue['end']) > a:
                    out.append(cue['text'])
        for track in self.script['tracks']:
            for item, s, e in layout(track):
                p = (item.get('graphic') or {}).get('params') or {}
                if s < b and e > a and (item.get('graphic') or {}).get('template') == 'word_captions':
                    out.append(' '.join(str(w[0]) for w in p.get('words') or [] if w))
        return out


def _same_caption(text, captions):
    if not text:
        return False
    clean = lambda s: re.sub(r'[^\w]+', ' ', str(s).lower()).strip()
    needle = clean(text)
    return bool(needle) and any(f' {needle} ' in f' {clean(c)} ' for c in captions)


def _main_clip_at(script, t, need_file=True):
    """(item, start, end) of the main picture track's item playing at timeline time t (need_file: only a clip of
    a file), or None."""
    from letitedit.timeline.edit_sync import layout, main_track
    m = main_track(script)
    for it, s, e in (layout(m) if m else []):
        if s - 1e-6 <= t < e and ('clip' in it or not need_file):
            return it, s, e
    return None


def _geom_box(geom, w, h):
    """'x y w h [opacity]' in pixels (or with %) -> (x0, y0, x1, y1) fractions."""
    try:
        parts = re.split(r'[\s/:x]+', str(geom).strip())
        vals = []
        for i, p in enumerate(parts[:4]):
            if p.endswith('%'):
                vals.append(float(p[:-1]) / 100)
            else:
                vals.append(float(p) / (w if i % 2 == 0 else h))
        x, y, bw, bh = vals
        return (x, y, x + bw, y + bh)
    except (ValueError, IndexError):
        return None


def _caption_boxes(script, kit, w, h):
    """[(start, end, box)] where captions are on screen: burned-in caption tracks and word-by-word caption tracks."""
    es = _es()
    out = []
    for cap in script.get('captions') or []:
        if cap.get('burn_in') is False:
            continue
        geom = (cap.get('style') or {}).get('geometry') or kit.caption_props(w, h).get('geometry')
        box = _geom_box(geom, w, h)
        if box is None:
            continue
        for q in cap.get('cues') or []:
            out.append((es.to_seconds(q['start']), es.to_seconds(q['end']), box))
    from letitedit.timeline.edit_sync import layout
    import letitedit.pictures.graphics as graphics
    for t in script['tracks']:
        if t.get('kind', 'video') != 'video':
            continue
        for it, s, e in layout(t):
            g = it.get('graphic') or {}
            if g.get('template') != 'word_captions':
                continue
            try:      # the values the caption is drawn with: the template's, the style's, the item's own
                p = graphics.normalise({'template': 'word_captions', 'params': g.get('params') or {}}, kit)['params']
            except Exception:  # noqa: BLE001
                p = g.get('params') or {}
            out.append((s, e, _word_caption_box(p, w, h)))
    return out


def _word_caption_box(p, w, h):
    """Where a word-by-word caption block sits (fractions), from the caption template's own layout: lines of
    size x 1.22 (size in px at 1080 high), placed by position and margin_y; the number of lines estimated from the
    words and the width the lines may take."""
    size = float(p.get('size', 84))
    mw, cx = float(p.get('max_width', 0.82)), float(p.get('center_x', 0.5))
    text = ' '.join(str(x[0]) for x in (p.get('words') or []) if x)
    char_w = size * (h / 1080.0) * 0.62 * (1.1 if p.get('uppercase') else 1.0)
    per_line = max(1, int(mw * w / max(1.0, char_w)))
    lines = max(1, min(4, -(-len(text) // per_line))) if text else 2
    band = lines * size * 1.22 / 1080.0
    pos, my = p.get('position', 'bottom'), float(p.get('margin_y', 0.12))
    thirds = {'lower-third': 0.72, 'lower third': 0.72, 'lower_third': 0.72, 'upper-third': 0.28,
              'upper third': 0.28, 'upper_third': 0.28}
    if isinstance(pos, str) and pos.strip().lower() in thirds:
        pos = thirds[pos.strip().lower()]
    try:
        y0 = min(0.95, max(0.05, float(pos))) - band / 2
    except (TypeError, ValueError):
        y0 = my if pos == 'top' else (1 - band) / 2 if pos in ('middle', 'center') else 1 - my - band
    return (cx - mw / 2, y0, cx + mw / 2, y0 + band)


def _covered(platform):
    """Covered areas [(x0, y0, x1, y1, name)] of a platform id, 'phone' (Shorts + TikTok + Reels) or None."""
    if not platform:
        return []
    ids = PHONE if platform == 'phone' else (platform,)
    out = []
    try:
        import letitedit.catalogs.platforms as platforms
        for pid in ids:
            for z in (platforms.load(pid).get('safe_zones') or {}).get('value') or []:
                out.append((z['x'], z['y'], z['x'] + z['w'], z['y'] + z['h'], f"{pid}: {z['name']}"))
    except Exception:  # noqa: BLE001 - an unknown platform is reported by style_pack.check
        return []
    return out


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


# ------------------------------------------------------------------ resolving an item

def resolve(item, kit):
    """The item with its preset and kind defaults filled in: (spec, preset name, rules)."""
    item = dict(item)
    presets = kit.get('effects') or {}
    pname = item.get('preset')
    preset = {}
    if pname:
        if pname not in presets:
            raise ValueError(f"fx: preset {pname!r} is not in the style's effects "
                             f"({', '.join(sorted(presets)) or 'the project has no style with presets'})")
        preset = copy.deepcopy(presets[pname])
    kind = item.get('kind') or preset.get('kind')
    if kind not in style_pack.EFFECT_KINDS:
        raise ValueError(f"fx: kind is one of {', '.join(style_pack.EFFECT_KINDS)} (or a preset); got {kind!r}")
    rules = preset.pop('rules', None) or {}
    spec = {**KIND_DEFAULTS.get(kind, {}), **{k: v for k, v in preset.items() if k not in ('about', 'kind')}}
    for k, v in item.items():
        if k in ('preset', 'kind'):
            continue
        if k == 'params' and isinstance(v, dict) and isinstance(spec.get('params'), dict):
            spec[k] = {**spec['params'], **v}     # the moment's text over the preset's look (its position, sizes)
            continue
        spec[k] = v
    spec['kind'] = kind
    if 'asset' in preset and 'asset' not in item:
        if kit.root is not None:
            spec['_asset_root'] = str(kit.root)
        asset = spec.get('asset')
        if isinstance(asset, dict) and asset.get('image'):
            spec['asset'] = dict(asset, image=kit.path(asset['image']))
    zone = spec.pop('zone', None) or (rules.get('placement') or {}).get('zone')
    if zone is not None and 'position' not in item:
        spec['zone'] = zone
    return spec, pname, rules


def _sound_for(spec, kit):
    if 'sfx' in spec:
        return kit.sfx_file(spec['sfx']) if spec['sfx'] else None
    ev = spec.get('event')
    if ev and ((kit.get('sfx') or {}).get('events') or {}).get(ev):
        return kit.sfx_file(ev)
    return None


def _xy(spec, frame, at, length, box_wh):
    """Where an overlay's centre goes: an explicit position, else its zone (opposite_face, above_captions), else the
    kind's default position. Returns ((x, y), note)."""
    zone = spec.get('zone')
    if 'position' in spec and spec.get('position') is not None and not zone:
        return style_pack.position_xy(spec['position']), None
    if zone == 'opposite_face':
        faces = frame.faces(at + min(0.3, length / 2))
        if faces:
            f = max(faces, key=_area)
            cx = (f[0] + f[2]) / 2
            bw, bh = box_wh
            right_edge = min([z[0] for z in frame.covered if z[1] < 0.5 < z[3] and z[0] > 0.5] + [0.97])
            if cx < 0.5:
                x = min(right_edge - 0.01 - bw / 2, max(0.73, f[2] + 0.02 + bw / 2))
            else:
                x = max(0.03 + bw / 2, min(0.27, f[0] - 0.02 - bw / 2))
            y = max(bh / 2 + 0.07, min(0.3, f[1] + bh / 2))
            return (x, y), None
        return style_pack.position_xy(spec.get('position') or 'upper_right'), (
            'face not found in nearby frames: placed at its default position' if faces == [] else None)
    if zone == 'above_captions':
        caps = frame.captions_at(at, at + length)
        if caps:
            top = min(b[1] for b in caps)
            return (0.5, max(box_wh[1] / 2 + 0.07, top - 0.02 - box_wh[1] / 2)), None
        return style_pack.position_xy(spec.get('position') or 'center'), None
    if zone is not None:
        return style_pack.position_xy(zone), None
    return style_pack.position_xy(spec.get('position')), None


def _text_aspect(text):
    """Height / width of a text sticker (the sticker wraps long text on two or three lines)."""
    n = max(1, len(str(text)))
    lines = 1 if n <= 14 else 2 if n <= 32 else 3
    return min(1.0, lines * 1.25 / (0.62 * n / lines))


def _sticker_wh(spec, frame):
    side = float(spec.get('size', 0.28)) * frame.short
    asset = spec.get('asset') or {}
    if spec['kind'] == 'text_pop' or 'text' in asset:
        a = _text_aspect(spec.get('text') or asset.get('text') or '')
        return side / frame.w, side * a / frame.h
    return side / frame.w, side / frame.h


def _sticker_box(spec, frame, xy):
    bw, bh = _sticker_wh(spec, frame)
    x, y = xy
    x = min(max(x, bw / 2), 1 - bw / 2)
    y = min(max(y, bh / 2), 1 - bh / 2)
    return (x - bw / 2, y - bh / 2, x + bw / 2, y + bh / 2)


# ------------------------------------------------------------------ placing

def _count(script, prefix):
    return sum(1 for t in script['tracks'] for it in t['items'] if str(it.get('id', '')).startswith(prefix)
               and not str(it.get('id', '')).endswith('-sfx'))


def _new_id(script, kind, prefix=ID_PREFIX):
    base = f'{prefix}{re.sub(r"[^a-z0-9]+", "-", kind.lower())}-'
    n = _count(script, base) + 1
    used = {it.get('id') for t in script['tracks'] for it in t['items']}
    while f'{base}{n}' in used:
        n += 1
    return f'{base}{n}'


def _free_id(script, base, suffix=''):
    used = {it.get('id') for t in script['tracks'] for it in t['items']}
    n = 1
    while f'{base}{n}{suffix}' in used:
        n += 1
    return f'{base}{n}{suffix}'


def _shift_keys(value, offset):
    if isinstance(value, dict):
        return {k: ([[round(float(r[0]) + offset, 4)] + list(r[1:]) if isinstance(r, (list, tuple)) and r else r
                     for r in v] if k == 'keys' and isinstance(v, list) else _shift_keys(v, offset))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_shift_keys(v, offset) for v in value]
    return value


def _burst(on, off, o, n, fps=30.0):
    """Keys that hold `off`, jump to `on` at o for n seconds, then back (hold easing: no in-between values)."""
    step = 1.0 / fps
    keys = []
    if o > step / 2:
        keys.append([0, off, 'hold'])
    keys += [[round(o, 4), on, 'hold'], [round(o + max(n, step), 4), off, 'hold']]
    return {'keys': keys}


def clip_effect(spec, offset, fps=30.0):
    """The keyframed clip effect of a zoom_punch, shake, glitch or raw effect starting `offset` s into the clip."""
    kind = spec['kind']
    if kind in ('zoom_punch', 'push_in'):
        # The easing belongs to the *arrival* key (edit_effects.anim), not the departure key.
        # Keeping a distinct hold key avoids a linear drift during the emphasis beat.
        s, r = float(spec.get('scale', 1.15)), max(1.0 / fps, float(spec.get('ramp_s', 0.12)))
        keys = [[round(offset, 4), 1.0]]
        if kind == 'push_in':
            n = max(2.0 / fps, float(spec.get('len') or 2.0))
            keys += [[round(offset + n, 4), s, 'ease_in_out']]
        elif spec.get('len'):
            n = max(3.0 / fps, float(spec['len']))
            r = min(r, n / 3)
            h = n - 2 * r
            keys += [[round(offset + r, 4), s, 'ease_out']]
            if h > 1.0 / fps:
                keys += [[round(offset + r + h, 4), s, 'hold']]
            keys += [[round(offset + n, 4), 1.0, 'ease_in_out']]
        else:
            keys += [[round(offset + r, 4), s, 'ease_out']]
        eff = {'zoom': {'keys': keys}}
        if spec.get('focus'):
            eff['focus'] = list(spec['focus'])
        return eff
    if kind == 'shake':
        a, n = float(spec.get('amount', 0.5)), float(spec.get('len', 0.35))
        # amplitude and the border zoom go to 0 outside the burst ('5', the filter's opacity, is the picture's own:
        # keyframing it to 0 blacks the clip out)
        return {'filter': 'shake', 'params': {'0': _burst(a, 0, offset, n, fps), '1': _burst(a, 0, offset, n, fps),
                                              '3': _burst(min(0.3, a * 0.3), 0, offset, n, fps),
                                              '4': float(spec.get('speed', 0.6))}}
    if kind == 'glitch':
        a, n = float(spec.get('amount', 0.6)), float(spec.get('len', 0.4))
        return {'filter': 'glitch', 'params': {'0': _burst(a, 0, offset, n, fps), '2': _burst(a, 0, offset, n, fps),
                                               '3': _burst(a, 0, offset, n, fps)}}
    if kind == 'effect':
        return _shift_keys(copy.deepcopy(spec['effect']), offset)
    raise ValueError(kind)


def _clip_len(spec):
    if spec['kind'] in ('zoom_punch', 'push_in'):
        return float(spec['len']) if spec.get('len') else None
    return float(spec.get('len') or 0.35)


def _motion_box(block, params, frame=None):
    """Conservative screen footprint for the common text/panel motion blocks.

    These templates draw into a transparent full-frame clip. A whole-frame box
    would make the face and phone checks meaningless, so use their documented
    positions and enough room for the panel and its text.
    """
    height_px = max(1080, min(1920, getattr(frame, 'h', 1920)))
    pos = params.get('position')
    if block == 'count_up':
        centres = {'center': (.5, .5), 'left': (.25, .5), 'right': (.75, .5),
                   'top': (.5, .25), 'bottom': (.5, .72)}
        x, y = (float(pos[0]), float(pos[1])) if isinstance(pos, (list, tuple)) and len(pos) == 2 else centres.get(pos, (.5, .5))
        digits = len(f"{int(float(params.get('to', 1000))):,}{params.get('suffix', '')}")
        width = min(.7, .06 + digits * float(params.get('size', 220)) * .65 / 1080)
        height = .035 + float(params.get('size', 220)) / height_px
        if params.get('label'):
            height += .012 + float(params.get('label_size', 56)) / height_px
        return (max(0, x - width / 2), max(0, y - height / 2), min(1, x + width / 2), min(1, y + height / 2))
    if block == 'lower_third':
        side = params.get('side', 'left')
        margin_x = float(params.get('margin_x', .06))
        bottom = 1 - float(params.get('margin_y', .2))
        width = min(.8, .32 + .018 * max(len(str(params.get('name', ''))), len(str(params.get('role', '')))))
        height = max(.055, min(.14, .03 + (float(params.get('size', 62))
                                      + float(params.get('role_size', 38))) / height_px))
        return ((1 - margin_x - width if side == 'right' else margin_x), max(0, bottom - height),
                (1 - margin_x if side == 'right' else min(1, margin_x + width)), min(1, bottom))
    if block == 'subscribe':
        side = str(pos or 'bottom-left')
        margin = float(params.get('margin', .07))
        height = .08
        width = min(.85, .3 + .012 * (len(str(params.get('text', ''))) + len(str(params.get('handle', '')))))
        x0 = 1 - margin - width if 'right' in side else margin
        y0 = 1 - margin - height if 'bottom' in side else margin
        if side == 'center':
            x0, y0 = (.5 - width / 2), (.5 - height / 2)
        return (max(0, x0), max(0, y0), min(1, x0 + width), min(1, y0 + height))
    return None


def _overlay_item(spec, kit, frame, at):
    """(item, length, box or None, note) of an overlay kind."""
    import letitedit.looks.popups as popups
    kind = spec['kind']
    if kind in ('popup', 'text_pop'):
        if kind == 'text_pop':
            text = spec.get('text') or (spec.get('asset') or {}).get('text')
            if not text:
                raise ValueError('fx: a text_pop needs text')
            spec = dict(spec, asset={'text': str(text)})
        if spec.get('asset') is not None:
            spec = dict(spec, asset=style_pack.resolve_asset(spec['asset'], kit))     # a library reference too
        if not isinstance(spec.get('asset'), dict):
            raise ValueError("fx: a popup needs asset: {image | emoji | text | graphic | motion} or a library "
                             "reference like 'emoji:fire'")
        if isinstance(spec.get('font'), dict):         # the pop-up template takes a font name: 'Family 600 Italic'
            f = kit.font(spec['font'])
            spec = dict(spec, font=f"{f['family']} {f['weight']}{' Italic' if f['italic'] else ''}")
        root = spec.get('_asset_root') or spec.get('_root')
        n = float(spec.get('len') or (float(spec['in_s']) + float(spec['hold_s']) + float(spec['out_s'])))
        wh = _sticker_wh(spec, frame)
        xy, note = _xy(spec, frame, at, n, wh)
        box = _sticker_box(spec, frame, xy)
        if any(_inter(box, c) > 0.02 * min(_area(box), _area(c)) for c in frame.captions_at(at, at + n)):
            moved, _ = _xy(dict(spec, zone='above_captions'), frame, at, n, wh)
            xy = moved
            note = 'moved clear of captions'
        g = spec['asset'].get('graphic') if isinstance(spec['asset'].get('graphic'), dict) else None
        if g and g.get('template') == 'asset_sticker':      # a library animation: placed and sized like a sticker
            g = copy.deepcopy(g)
            g.setdefault('params', {}).update({'x': round(xy[0], 4), 'y': round(xy[1], 4)})
            g['params'].update({k: spec[k] for k in ('size', 'in', 'out', 'in_s', 'out_s', 'wiggle', 'tilt', 'shadow',
                                                     'outline', 'outline_color') if spec.get(k) is not None})
            spec = dict(spec, asset={'graphic': g})
        entry = dict(spec, id=spec.get('id') or 'fx', len=n, position=list(xy))
        entry.pop('zone', None)
        item, n = popups.overlay_item(entry, root, kit, frame.script)
        box = _sticker_box(spec, frame, xy) if (any(k in spec['asset'] for k in ('image', 'emoji', 'text'))
                                                or (g and g.get('template') == 'asset_sticker')) else None
        return item, n, box, note
    if kind == 'flash':
        n = float(spec.get('len') or 0.25)
        item = {'color': kit.mlt_color(spec.get('color') or 'light'), 'len': round(n, 3),
                'effects': [{'opacity': float(spec.get('opacity', 0.85))}, {'fade_out': round(n * 0.85, 3),
                                                                           'opacity': True}]}
        return item, n, (0.0, 0.0, 1.0, 1.0), None
    if kind in ('count_up', 'location', 'motion'):
        import letitedit.pictures.motion as motion
        m = {'block': spec.get('block') or kind, 'params': dict(spec.get('params') or {})}
        if spec.get('len'):
            m['duration'] = float(spec['len'])
        n = motion.normalise(m)['duration']
        return {'motion': m}, n, _motion_box(m['block'], m['params'], frame), None
    if kind == 'graphic':
        import letitedit.pictures.graphics as graphics
        g = {'template': spec['template'], 'params': dict(spec.get('params') or {})}
        n = float(spec.get('len') or graphics.normalise(g, kit)['len'])
        return {'graphic': g, 'len': round(n, 3)}, n, None, None
    if kind == 'three_d':
        model = spec.get('model') or (spec.get('params') or {}).get('model')
        if not model:
            raise ValueError('fx: three_d needs model (a local 3D file)')
        r = {'model': model, **(spec.get('params') or {})}
        if spec.get('len'):
            r['duration'] = float(spec['len'])
        import letitedit.pictures.render3d as render3d
        r = render3d.normalise(r)
        size = max(0.1, min(.9, float(spec.get('size', .3))))
        xy, note = _xy(spec, frame, at, float(r['duration']), (size, size))
        x, y = xy
        box = (max(0, x - size / 2), max(0, y - size / 2),
               min(1, x + size / 2), min(1, y + size / 2))
        rect = f'{box[0] * frame.w:.1f} {box[1] * frame.h:.1f} {size * frame.w:.1f} {size * frame.h:.1f}'
        return {'render3d': r, 'effects': [{'size_position': rect}]}, float(r['duration']), box, note
    if kind == 'light_leak':
        n = float(spec.get('len') or 1.5)
        return {'vfx': {'effect': 'light_leak', 'params': dict(spec.get('params') or {})}, 'len': round(n, 3)}, n, \
            (0.0, 0.0, 1.0, 1.0), None
    if kind == 'broll':
        es = _es()
        clip = spec.get('clip')
        if not clip:
            raise ValueError('fx: a broll needs clip (and in, out or len)')
        a = float(spec.get('in', 0))
        b = float(spec['out']) if spec.get('out') is not None else a + float(spec.get('len') or 2.0)
        item = {'clip': clip, 'in': round(a, 4), 'out': round(b, 4), 'effects': ['mute']}
        fit = spec.get('fit', 'cover')
        if fit in PANEL_FITS:
            effects, box = panel_effects(clip, fit, frame.w, frame.h, spec.get('radius') or 0)
            item['effects'] += effects
            return item, b - a, box, None
        if fit == 'blur_pad':
            item['effects'].append('blur_pad')
        elif fit == 'cover':
            import letitedit.server.core_tools as core_tools
            info = core_tools.probe(clip)
            cw, ch = float(info.get('width') or frame.w), float(info.get('height') or frame.h)
            contain = min(frame.w / cw, frame.h / ch)
            cover = max(frame.w / cw, frame.h / ch)
            if cover / contain > 1.001:
                item['effects'].append({'zoom': round(cover / contain, 4)})
        return item, b - a, (0.0, 0.0, 1.0, 1.0), None
    if kind == 'item':
        it = copy.deepcopy(spec['item'])
        from letitedit.timeline.edit_sync import item_len
        return it, item_len(it), None, None
    raise ValueError(kind)


def panel_effects(clip, fit, frame_w, frame_h, radius=0):
    """A clip filling one half of the frame (fit top | bottom | left | right): its picture scaled to cover that half
    and centred on it (Size & Position), everything outside the half masked off (Crop: Rectangle). Returns
    (effects, the half as fractions (x0, y0, x1, y1))."""
    import letitedit.server.core_tools as core_tools
    info = core_tools.probe(clip)
    W, H = float(frame_w), float(frame_h)
    cw, ch = float(info.get('width') or W), float(info.get('height') or H)
    if fit in ('top', 'bottom'):
        pw, ph = W, float(round(H / 2))
        px, py = 0.0, (0.0 if fit == 'top' else H - ph)
    elif fit in ('left', 'right'):
        pw, ph = float(round(W / 2)), H
        px, py = (0.0 if fit == 'left' else W - pw), 0.0
    else:
        raise ValueError(f"fx: a panel fit is one of {', '.join(PANEL_FITS)}; got {fit!r}")
    s = max(pw / cw, ph / ch)
    w, h = cw * s, ch * s
    x, y = px + (pw - w) / 2, py + (ph - h) / 2
    effects = [{'size_position': f'{x:.1f} {y:.1f} {w:.1f} {h:.1f}'},
               {'filter': 'Crop: Rectangle', 'params': {'rect': f'{px:.0f} {py:.0f} {pw:.0f} {ph:.0f}',
                                                       'color': '#00000000', 'radius': float(radius)}}]
    return effects, (px / W, py / H, (px + pw) / W, (py + ph) / H)


def _fills_frame(size_position, width, height):
    """True when a size_position (a rectangle text or {keys}) covers the whole frame, opaque, at every key: a cover-fit
    or a camera move keeps the cutaway full-frame."""
    keys = size_position.get('keys') if isinstance(size_position, dict) else [[0, size_position]]
    try:
        for k in keys or []:
            vals = [float(v) for v in (k[1].split() if isinstance(k[1], str) else k[1])]
            x, y, w, h = vals[:4]
            opacity = vals[4] if len(vals) > 4 else 1.0
            if opacity < 0.999 or x > 0.5 or y > 0.5 or x + w < width - 0.5 or y + h < height - 0.5:
                return False
    except (TypeError, ValueError, IndexError, AttributeError):
        return False
    return bool(keys)


def _clamp_end(item, at, n, total):
    """An item that would run past the end of the main picture is shortened to end with it (past it, the video would
    get black frames after its last shot). Returns the length; refused when it would start within 0.25 s of the end."""
    if total <= 0 or at + n <= total + 1e-3:
        return n
    room = total - at
    if room < 0.25:
        raise ValueError(f'fx: an effect at {_clock(at)} starts within 0.25 s of the end of the video ({_clock(total)})')
    if 'clip' in item:
        item['out'] = round(float(item.get('in', 0)) + room * float(item.get('speed', 1.0)), 4)
    elif isinstance(item.get('motion'), dict):
        item['motion']['duration'] = round(room, 3)
    elif isinstance(item.get('render3d'), dict):
        item['render3d']['duration'] = round(room, 3)
    else:
        item['len'] = round(room, 3)
    return room


def _place_sound(script, kit, path, at, track, gain=None, iid=None, target=None):
    import letitedit.looks.popups as popups
    duration = float(_es().probe(path).get('duration') or 1.0)
    snd = popups.sound_item({'id': iid or 'fx', 'sfx': path, 'sfx_gain_db': gain}, None, kit, duration)
    if at < 0:
        snd['in'] = min(float(snd['out']), -at)
    if target:
        snd['sound_target'] = target
    total = _timeline_end(script)
    if total > 0 and max(0.0, at) + float(snd['out']) - float(snd['in']) > total + 1e-3:
        if total - max(0.0, at) < 0.05:
            raise ValueError(f'fx: sound {iid or path} starts outside the video')
        snd['out'] = round(float(snd['in']) + total - max(0.0, at), 3)
    popups._ensure_track(script, track, 'audio')
    snd['id'] = iid
    popups._place(script, track, max(0.0, at), snd)
    return snd


def _broll_track(script, name):
    """The B-roll track, made just above the main picture track (cutaways sit under captions and effects)."""
    from letitedit.timeline.edit_sync import main_track
    if any(x['name'] == name for x in script['tracks']):
        return
    main = main_track(script)
    idx = script['tracks'].index(main) + 1 if main is not None else len(script['tracks'])
    while idx < len(script['tracks']) and any(isinstance(it.get('multicam'), dict)       # over a multicam cut's angles
                                              for it in script['tracks'][idx].get('items') or []):
        idx += 1
    script['tracks'].insert(idx, {'name': name, 'kind': 'video', 'items': []})


def _modern_transition(script, cut, kind, length):
    """Full-frame xfade across a cut, using both clips' real handles and keeping their audio on the main track."""
    from letitedit.timeline.edit_sync import layout, main_track
    import letitedit.server.core_tools as core_tools
    clips = [(it, s, e) for it, s, e in layout(main_track(script)) if 'clip' in it]
    pair = next(((a, b) for a, b in zip(clips, clips[1:])
                 if abs(a[2] - cut) < 0.04 and abs(b[1] - cut) < 0.04), None)
    if pair is None:
        raise ValueError(f'fx: {kind} needs two adjacent picture clips at {_clock(cut)}')
    a, b = pair[0][0], pair[1][0]
    if float(a.get('speed', 1)) != 1 or float(b.get('speed', 1)) != 1:
        raise ValueError(f'fx: {kind} needs normal-speed clips on both sides of the cut')
    half = length / 2
    ai, ao = float(a['out']) - half, float(a['out']) + half
    bi, bo = float(b['in']) - half, float(b['in']) + half
    a_duration = float(core_tools.probe(a['clip']).get('duration') or 0)
    b_duration = float(core_tools.probe(b['clip']).get('duration') or 0)
    if ai < 0 or bi < 0 or ao > a_duration - .01 or bo > b_duration - .01:
        raise ValueError(f'fx: {kind} needs {half:.2f} s of source footage on both sides of the cut')
    profile = script.get('profile') or {}
    w, h, fps = int(profile.get('width', 1920)), int(profile.get('height', 1080)), float(profile.get('fps', 30))
    xfade, blur = MODERN_TRANSITIONS[kind]
    prep = f'fps={fps:g},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=yuv420p'
    if blur:
        prep += ',' + blur
    prep_a = prep_b = prep
    if kind == 'zoom_through':
        # xfade's built-in zoomin exposes its fill colour at the midpoint. Keep
        # both real shots covering the canvas as they move through the cut.
        step = max(0.01, 0.75 / max(2, round(length * fps)))
        prep_a += f",zoompan=z='min(1.75,1+on*{step:.5f})':d=1:s={w}x{h}:fps={fps:g}"
        prep_b += f",zoompan=z='max(1,1.75-on*{step:.5f})':d=1:s={w}x{h}:fps={fps:g}"
    elif kind == 'spin':
        zoom = f'scale=trunc(iw*1.7/2)*2:trunc(ih*1.7/2)*2'
        prep_a += f",{zoom},rotate='0.45*t/{length:.4f}':ow=iw:oh=ih:c=black,crop={w}:{h}"
        prep_b += f",{zoom},rotate='-0.45*(1-t/{length:.4f})':ow=iw:oh=ih:c=black,crop={w}:{h}"
    elif kind == 'clean_glitch':
        fringe = "rgbashift=rh=5:bh=-5:enable='between(t,0.12,0.28)'"
        prep_a += ',' + fringe
        prep_b += ',' + fringe
    graph = (f'[0:v]{prep_a},settb=AVTB,setpts=PTS-STARTPTS[a];'
             f'[1:v]{prep_b},settb=AVTB,setpts=PTS-STARTPTS[b];'
             f'[a][b]xfade=transition={xfade}:duration={length:.4f}:offset=0[v]')
    return {'ffmpeg': {'inputs': [{'clip': a['clip'], 'in': ai, 'out': ao},
                                  {'clip': b['clip'], 'in': bi, 'out': bo}],
                       'video': graph, 'audio': False, 'fit': 'cover'}, 'len': length}


def _attach_effect_sound(spec, kit, kind, script, prefix, rec, es, layout, settings):
    """Place the effect's own sound, aimed at what it accompanies: a cut, an entrance, a word or the effect."""
    snd_path = _sound_for(spec, kit)
    if kind in SOUND_KINDS and not snd_path:
        if kind == 'whoosh':
            snd_path = kit.sfx_file('whoosh') or kit.sfx_file('transition')
        if not snd_path:
            raise ValueError(f"fx: a {kind} needs a sound: sfx (a name in the pack's sfx.map or sfx.events, or a "
                             f"file)")
    if snd_path:
        off = float(spec.get('sfx_offset_s') or 0.0)
        if kind in SOUND_KINDS:
            sid = spec.get('_id') or _new_id(script, kind, prefix)
            rec['id'] = sid
        elif kind in OVERLAY_KINDS and rec.get('id'):
            sid = rec['id'] + '-sfx'
        else:
            sid = _free_id(script, f'{prefix}{re.sub(r"[^a-z0-9]+", "-", kind)}-', '-sfx')
        from letitedit.looks import sound_targets
        from letitedit.review import dense
        target = spec.get('sound_target')
        if not target and rec.get('on_clip'):
            target_track, _, target_item = es._find(script, rec['id'])
            target_start = next(start for item, start, end in layout(target_track) if item is target_item)
            target = {'kind': 'effect', 'id': rec['id'], 'word': kind, 'at': rec['at'],
                      'offset': rec['at'] - target_start,
                      'effect_keys': list((target_item.get('effects') or [{}])[-1])}
        if not target:
            picture_events, _ = dense.events(script)
            candidates = [event for event in picture_events if event['kind'] in ('cut', 'in', 'out', 'caption_word')]
            target_id = rec.get('id') if kind not in SOUND_KINDS else spec.get('id')
            intended = rec.get('cut', rec['at'])
            if kind == 'transition' and rec.get('cut') is not None and not rec.get('broll_only'):
                target_id = None
                candidates = [event for event in candidates if event['kind'] == 'cut']
            own = [event for event in candidates if target_id and event.get('id') == target_id]
            fps = float((script.get('profile') or {}).get('fps') or 30)
            chosen = min(own or [event for event in candidates if abs(event['t'] - intended) <= 1 / fps],
                         key=lambda event: abs(event['t'] - intended), default=None)
            target = sound_targets.target_for(chosen) if chosen else {
                'kind': 'story' if spec.get('words') else 'in', 'at': rec['at'],
                **({'word': spec['words']} if spec.get('words') else {})}
        _place_sound(script, kit, snd_path, rec['at'] + off, settings['sfx_track'], spec.get('sfx_gain_db'), sid, target)
        rec['sfx'], rec['sfx_id'] = os.path.basename(snd_path), sid
        if kind in SOUND_KINDS:
            from letitedit.timeline.edit_sync import item_len
            t = next(x for x in script['tracks'] if any(it.get('id') == sid for it in x['items']))
            rec['len'] = round(item_len(next(it for it in t['items'] if it.get('id') == sid)), 3)
            rec['track'] = t['name']


def place(script, spec, kit, frame, settings, prefix=ID_PREFIX):
    """Place one resolved effect at spec['at'] (timeline seconds). Returns the placed record."""
    import letitedit.looks.popups as popups
    es = _es()
    from letitedit.timeline.edit_sync import layout, main_track
    kind, at = spec['kind'], float(spec['at'])
    rec = {'kind': kind, 'at': round(at, 3), 'len': 0.0, 'box': None, 'track': None}
    note = None
    if kind == MOVE_KIND:
        import letitedit.looks.camera_moves as camera_moves
        if not spec.get('id'):
            raise ValueError('fx: a camera_move needs id (the cutaway clip)')
        t, i, it = es._find(script, spec['id'])
        hit = next(((x, s, e) for x, s, e in layout(t) if x is it), None)
        if not hit or not (it.get('clip') or it.get('image')):
            raise ValueError(f"fx: camera_move {spec['id']} is not a picture or video clip")
        if t is main_track(script):
            raise ValueError("fx: a camera_move goes on a cutaway, never on the speaker's track")
        spec.setdefault('move', 'push_in')
        note = camera_moves.apply(script, it, hit[2] - hit[1], spec)
        rec.update(id=it.get('id'), at=round(hit[1], 3), len=round(hit[2] - hit[1], 3), box=(0, 0, 1, 1), track=t['name'],
                   on_clip=True, move=spec['move'])
        if spec.get('note'):
            note = f"{note} ({spec['note']})"
    elif kind in CLIP_KINDS:
        hit = _main_clip_at(script, at, need_file=False)
        if spec.get('id'):
            t, i, it = es._find(script, spec['id'])
            hit = next(((x, s, e) for x, s, e in layout(t) if x is it), None)
        if not hit:
            raise ValueError(f'fx: no clip on the main picture track at {es.clock(at)} for the {kind}')
        it, s, e = hit
        offset = max(0.0, at - s)
        it.setdefault('effects', []).append(clip_effect(spec, offset, float((script.get('profile') or {}).get('fps',
                                                                                                             30))))
        n = _clip_len(spec)
        rec.update(id=it.get('id'), len=round((e - at) if n is None else min(n, e - at), 3), box=(0, 0, 1, 1),
                   track=main_track(script)['name'], on_clip=True)
    elif kind == 'transition' and isinstance(spec.get('transition'), dict) and spec['transition'].get('type') == 'cutaway_negative':
        track, _, item = es._find(script, spec.get('id'))
        if track is main_track(script) or track['name'] != (spec.get('track') or settings['broll_track']) or not item.get('clip'):
            raise ValueError('fx: cutaway_negative targets a full-frame clip on the B-roll track, never the speaker')
        effects = list(item.get('effects') or [])
        prof = script.get('profile') or {}
        if any(isinstance(effect, dict) and (any(key in effect for key in ('opacity', 'crop')) or (
                'size_position' in effect and not _fills_frame(effect['size_position'], prof.get('width', 1920),
                                                               prof.get('height', 1080)))) for effect in effects):
            raise ValueError('fx: cutaway_negative needs opaque full-frame b-roll')
        pulse = spec['transition']
        edge, seconds = pulse.get('edge', 'in'), float(pulse.get('len', .1))
        if edge not in ('in', 'out') or not .03 <= seconds <= .2:
            raise ValueError('fx: cutaway_negative needs edge in/out and len .03 to .2 seconds')
        effects = [effect for effect in effects if not (isinstance(effect, dict) and effect.get('cutaway_negative', {}).get('edge') == edge)]
        item['effects'] = [*effects, {'cutaway_negative': {'edge': edge, 'len': seconds}}]
        start, end = next((start, end) for candidate, start, end in layout(track) if candidate is item)
        rec.update(id=item['id'], at=round(start if edge == 'in' else end, 3), len=seconds, track=track['name'],
                   cut=round(start if edge == 'in' else end, 3), broll_only=True)
    elif kind == 'transition':
        m = main_track(script)
        cand = [(x, s, e) for x, s, e in layout(m)] if m else []
        target = None
        if spec.get('id'):
            target = next(((x, s, e) for x, s, e in cand if x.get('id') == spec['id']), None)
        else:
            target = min((c for c in cand[1:] if abs(c[1] - at) <= 0.25), key=lambda c: abs(c[1] - at), default=None)
        if target is None:
            raise ValueError(f'fx: no cut near {es.clock(at)} for a transition (give id: the clip after the cut)')
        tr = spec.get('transition') or {'type': 'dissolve', 'len': 0.3}
        ttype = tr.get('type') if isinstance(tr, dict) else 'dissolve'
        if ttype in MODERN_TRANSITIONS:
            n = float(tr['len'])
            if not 0.12 <= n <= 1.0:
                raise ValueError('fx: a modern transition needs len between 0.12 and 1.0 s')
            if ttype in ('clean_glitch', 'spin'):
                faces = frame.faces(target[1] - .05)
                if faces is None or faces:
                    raise ValueError(f'fx: {ttype} needs a face-free cut verified at {_clock(target[1])}')
            start = target[1] - n / 2
            try:
                item = _modern_transition(script, target[1], ttype, n)
            except ValueError as exc:
                if not spec.get('_auto'):
                    raise
                tr = {'type': 'dissolve', 'len': n}
                target[0]['transition'] = tr
                rec.update(id=target[0].get('id'), at=round(target[1], 3), len=n, track=m['name'])
                note = f'{ttype} fell back to a dissolve: {exc}'
                item = None
            if item is not None:
                item['id'] = spec.get('_id') or _new_id(script, 'transition', prefix)
                track = spec.get('track') or settings['track']
                popups._ensure_track(script, track, 'video')
                popups._place(script, track, start, item)
                rec.update(id=item['id'], at=round(start, 3), len=n, track=track,
                           box=(0.0, 0.0, 1.0, 1.0), cut=round(target[1], 3))
        else:
            es.transition_spec(tr)
            target[0]['transition'] = tr
            rec.update(id=target[0].get('id'), at=round(target[1], 3), len=float(tr['len'] if isinstance(tr, dict) else tr),
                       track=m['name'])
    elif kind in SOUND_KINDS:
        rec['track'] = settings['sfx_track']
    else:
        if kind == 'broll':
            track = spec.get('track') or settings['broll_track']
            _broll_track(script, track)
        else:
            track = spec.get('track') or settings['track']
            popups._ensure_track(script, track, 'video')
        item, n, box, note = _overlay_item(spec, kit, frame, at)
        n = _clamp_end(item, at, n, _timeline_end(script))
        item['id'] = spec.get('_id') or _new_id(script, kind, prefix)
        moved = popups._place(script, track, at, item)
        rec.update(id=item['id'], len=round(n, 3), box=box or spec.get('_box'), track=track)
        if moved:
            rec['moved'] = moved
            m = re.search(r'went on (.+)$', moved)
            if m:
                rec['track'] = m.group(1)
    _attach_effect_sound(spec, kit, kind, script, prefix, rec, es, layout, settings)
    if note:
        rec['note'] = note
    elif spec.get('note'):
        rec['note'] = str(spec['note'])
    return rec


# ------------------------------------------------------------------ checking the rules

def _density_problems(recs, density, label):
    out = []
    if not density:
        return out
    starts = sorted(r['at'] for r in recs)
    gap = density.get('min_gap_s')
    if gap:
        for a, b in zip(starts, starts[1:]):
            if b - a < float(gap) - 1e-6:
                out.append((b, f'{label}: {b - a:.1f} s after the one before (min_gap_s {gap})'))
    for win, key in ((10.0, 'per_10s'), (60.0, 'per_min')):
        cap = density.get(key)
        if cap is None:
            continue
        for i, a in enumerate(starts):
            n = sum(1 for b in starts[i:] if b < a + win)
            if n > float(cap) + 1e-6:
                out.append((a, f'{label}: {n} in the {int(win)} s from {_clock(a)} ({key} {cap})'))
                break
    return out


def _never_problems(rec, never, frame, others, total):
    out = []
    a, n = rec['at'], rec['len']
    for r in never or []:
        if isinstance(r, dict):
            (k, v), = r.items()
            if k == 'first_s' and a < float(v):
                out.append(f'starts at {_clock(a)}, inside the first {v} s')
            if k == 'last_s' and a + n > total - float(v):
                out.append(f'runs into the last {v} s')
            continue
        box = rec.get('box')
        if box is None or rec.get('on_clip') or tuple(box) == (0, 0, 1, 1) or tuple(box) == (0.0, 0.0, 1.0, 1.0):
            continue                     # sounds, clip effects and full-frame overlays (flash, cutaway) have no spot
        if rec.get('kind') == 'broll' and r != 'over_face':
            continue                     # a half-frame cutaway is a picture: only a face it hides matters
        if r == 'over_face':
            faces = frame.faces(a + min(0.3, n / 2))
            if faces and any(_inter(box, f) > 0.15 * _area(f) for f in faces):
                out.append('covers the face')
        elif r == 'over_captions':
            if any(_inter(box, c) > 0.1 * min(_area(c), _area(box)) for c in frame.captions_at(a, a + n)):
                out.append('covers the captions')
        elif r == 'outside_safe_zone':
            hit = [z[4] for z in frame.covered if _inter(box, z[:4]) > 0.1 * _area(box)]
            if hit:
                out.append(f"in an area the app covers ({'; '.join(sorted(set(hit))[:2])})")
        elif r == 'overlapping':
            for o in others:
                if o is rec or o.get('box') is None or o.get('on_clip') or o['box'] == (0, 0, 1, 1) \
                        or o.get('kind') == 'broll':
                    continue
                if o['at'] < a + n and o['at'] + o['len'] > a and _inter(box, o['box']) > 0.05 * _area(box):
                    out.append(f"overlaps {o['id']}")
                    break
    return out


def _avoid_to_never(rules):
    av = (rules.get('placement') or {}).get('avoid') or []
    m = {'face': 'over_face', 'captions': 'over_captions', 'covered': 'outside_safe_zone'}
    return [m[a] for a in av if a in m]


def _said_near(script, said, at, words_cache):
    import letitedit.looks.popups as popups
    if words_cache.get('w') is None:
        from letitedit.timeline.timeline_speech import timeline_words
        words_cache['w'] = timeline_words(script)
    hits = popups.find_phrase(words_cache['w'], said)
    return any(abs(h[2] - at) <= 1.5 for h in hits), hits


def _speech_boundary(script, at, words_cache):
    if words_cache.get('boundary') is None:
        from letitedit.timeline.timeline_speech import timeline_words
        try:
            words_cache['boundary'] = timeline_words(script, cached_only=True)
        except TypeError:  # test and plugin shims with the older timeline_words signature
            words_cache['boundary'] = timeline_words(script)
    for w in words_cache['boundary']:
        if w['t0'] + 0.04 < at < w['t1'] - 0.04:
            edges = (w['t0'], w['t1'])
            near = min(edges, key=lambda x: abs(x - at))
            return round(near, 3) if abs(near - at) <= 0.25 else at
    return at


def check(recs, frame, kit, existing=(), total=None):
    """Every rule the placed effects break: [{id, at, rule}]."""
    out = []
    total = total if total is not None else _timeline_end(frame.script)
    by_preset = {}
    for r in list(existing) + recs:
        if r.get('preset'):
            by_preset.setdefault(r['preset'], []).append(r)
    presets = kit.get('effects') or {}
    for name, rs in by_preset.items():
        rules = (presets.get(name) or {}).get('rules') or {}
        for t, msg in _density_problems(rs, rules.get('density'), f'preset {name}'):
            rid = next((r['id'] for r in rs if abs(r['at'] - t) < 1e-3 and r in recs), None)
            if rid:
                out.append({'id': rid, 'at': round(t, 3), 'rule': msg})
    fx = kit.get('fx') or {}
    for t, msg in _density_problems([r for r in list(existing) + recs if r.get('kind') not in SOUND_KINDS],
                                    {'min_gap_s': 0.35}, 'visual effects'):
        rid = next((r['id'] for r in recs if abs(r['at'] - t) < 1e-3), None)
        if rid:
            out.append({'id': rid, 'at': round(t, 3), 'rule': msg})
    for t, msg in _density_problems(list(existing) + recs, fx.get('density'), 'all effects'):
        rid = next((r['id'] for r in recs if abs(r['at'] - t) < 1e-3), None)
        if rid:
            out.append({'id': rid, 'at': round(t, 3), 'rule': msg})
    for r in recs:
        if r.get('kind') == 'text_pop' and _same_caption(r.get('text'), frame.caption_words_at(r['at'], r['at'] + r['len'])):
            out.append({'id': r['id'], 'at': r['at'], 'rule': 'repeats the caption words'})
        box = r.get('box')
        if box and r.get('kind') in ('popup', 'text_pop') and any(
                _inter(box, c) > 0.02 * min(_area(box), _area(c)) for c in frame.captions_at(r['at'], r['at'] + r['len'])):
            out.append({'id': r['id'], 'at': r['at'], 'rule': 'covers the captions'})
        if r.get('kind') == 'glitch' and float(r.get('amount', 0.6)) >= 0.4 and frame.faces(r['at'] + r['len'] / 2):
            out.append({'id': r['id'], 'at': r['at'], 'rule': 'heavy glitch over a face'})
        rules = r.get('rules') or (((presets.get(r['preset']) or {}).get('rules') or {}) if r.get('preset') else {})
        never = list(rules.get('never') or []) + _avoid_to_never(rules) + list(fx.get('never') or [])
        seen = []
        for v in never:
            if v not in seen:
                seen.append(v)
        for msg in _never_problems(r, seen, frame, recs + list(existing), total):
            out.append({'id': r['id'], 'at': r['at'], 'rule': msg})
        du = rules.get('duration_s')
        if du is not None and r['len']:
            lo, hi = (du, du) if isinstance(du, (int, float)) else du
            if not (float(lo) - 0.05 <= r['len'] <= float(hi) + 0.05):
                out.append({'id': r['id'], 'at': r['at'], 'rule': f"{r['len']:.2f} s long (duration_s {du})"})
        trig = rules.get('triggers')
        if trig and r.get('trigger') and r['trigger'] not in trig:
            out.append({'id': r['id'], 'at': r['at'],
                        'rule': f"used for '{r['trigger']}'; preset {r['preset']} is for {', '.join(trig)}"})
        if r.get('said_missing'):
            out.append({'id': r['id'], 'at': r['at'], 'rule': f"\"{r['said']}\" is not said within 1.5 s of it"})
    return out


def _timeline_end(script):
    from letitedit.timeline.edit_sync import layout, main_track
    m = main_track(script)
    return max((e for _, _, e in (layout(m) if m else [])), default=0.0)


def _clock(s):
    return _es().clock(s)


def existing_effects(script, prefixes=(ID_PREFIX, POP_PREFIX), frame=None):
    """Effects already on the timeline (placed by earlier fx / popups edits), as records for the density checks; with
    a frame, pop-ups also get their spot on screen, so a new effect that would sit on one is caught (overlapping)."""
    from letitedit.timeline.edit_sync import layout
    out = []
    for t in script['tracks']:
        for it, s, e in layout(t):
            iid = str(it.get('id', ''))
            if iid.startswith(prefixes) and not iid.endswith('-sfx'):
                out.append({'id': iid, 'at': round(s, 3), 'len': round(e - s, 3), 'box': _placed_box(it, frame),
                            'preset': None})
    return out


def _placed_box(item, frame):
    """The screen box of a pop-up already on the timeline (its template's x, y, size and text), else None."""
    g = item.get('graphic') or {}
    p = g.get('params') or {}
    if frame is None or g.get('template') not in ('popup', 'asset_sticker') or p.get('x') is None:
        return None
    asset = {'text': p['text']} if p.get('text') else {'image': True}
    spec = {'kind': 'text_pop' if p.get('text') else 'popup', 'size': p.get('size', 0.28), 'asset': asset,
            'text': p.get('text')}
    try:
        return _sticker_box(spec, frame, (float(p['x']), float(p['y'])))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ the op

def settings_for(kit, op):
    fx = kit.get('fx') or {}
    return {'track': op.get('track') or fx.get('track') or 'Effects',
            'sfx_track': op.get('sfx_track') or fx.get('sfx_track') or 'Effect sounds',
            'broll_track': op.get('broll_track') or fx.get('broll_track') or 'B-roll'}


def _prepare_effect_specs(op, script, kit, existing, frame, es):
    """Expand requested plans and resolve each effect at its spoken or explicit time."""
    words = {}
    specs = []
    raw_items = list(op.get('items') or [])
    if op.get('sync_sounds'):
        import letitedit.looks.sound_sync as sound_sync
        synced = sound_sync.plan_for_op(script, op['sync_sounds'], _timeline_end(script))
        raw_items = synced['items'] + raw_items
        op['_sync_sounds'] = synced
    if op.get('camera_moves'):
        import letitedit.looks.camera_moves as camera_moves
        moved = camera_moves.plan_for_op(script, op['camera_moves'])
        raw_items = moved['items'] + raw_items
        op['_camera_moves'] = moved
    if op.get('cut_flashes'):
        import letitedit.looks.cut_flashes as cut_flashes
        flashed = cut_flashes.plan_for_op(script, op['cut_flashes'])
        raw_items = flashed['items'] + raw_items
        op['_cut_flashes'] = flashed
    if op.get('pace'):
        import letitedit.looks.pace_cut as pace_cut
        op['_pace'] = pace_cut.apply(script, op['pace'])
    if op.get('lighting'):
        import letitedit.looks.lighting as lighting
        op['_lighting'] = lighting.cover_speaker(script, op['lighting'], baked_ok=False)
    if op.get('grade'):
        import letitedit.looks.grade as grade
        op['_grade'] = grade.cover_footage(script, op['grade'])
    if op.get('auto'):
        import letitedit.looks.creative_plan as creative_plan
        planned, notes = creative_plan.plan(script, kit, op, existing, frame=frame)
        for item in planned:
            item['_auto'] = True
        raw_items = planned + raw_items
        op['_auto_notes'] = notes
    for n, raw in enumerate(raw_items, 1):
        if not isinstance(raw, dict):
            raise ValueError(f'fx: item {n} is a mapping {{at, preset | kind, ...}}')
        extra = sorted(k for k in raw if k not in ITEM_KEYS and not str(k).startswith('_'))
        if extra:
            raise ValueError(f"fx: item {n}: unknown {', '.join(extra)}")
        spec, pname, rules = resolve(raw, kit)
        if raw.get('at') is None and raw.get('words'):
            ok, hits = _said_near(script, raw['words'], 0.0, words)
            if not hits:
                raise ValueError(f"fx: item {n}: \"{raw['words']}\" is not said on the timeline")
            near = raw.get('near')
            h = min(hits, key=lambda x: abs(x[2] - es.to_seconds(near))) if near is not None else hits[0]
            spec['at'] = h[2]
            spec.setdefault('said', ' '.join(w['w'].strip() for w in words['w'][h[0]:h[1]]))
        elif raw.get('at') is None and not raw.get('id'):
            raise ValueError(f'fx: item {n} needs at (timeline seconds), words (a phrase said) or id (a clip)')
        if spec.get('at') is not None:
            spec['at'] = es.to_seconds(spec['at'])
            if spec['kind'] not in ('transition', *SOUND_KINDS) and not spec.get('_exact'):
                spec['at'] = _speech_boundary(script, spec['at'], words)
        spec['_n'], spec['_preset'], spec['_root'] = n, pname, raw.get('_root') or op.get('_root')
        specs.append(spec)
    return words, specs


def _place_effect_specs(specs, script, kit, frame, settings, mapper, op, es, words):
    """Place timing-changing transitions first, then map and place the other effects."""
    # transitions first (they move the timing of what follows); the other moments are mapped onto the new timing
    def boundary(spec):
        return spec['kind'] == 'transition' and isinstance(spec.get('transition'), dict) and spec['transition'].get('type') == 'cutaway_negative'
    trans = [s for s in specs if s['kind'] == 'transition' and not boundary(s)]
    rest = [s for s in specs if s['kind'] != 'transition'] + [s for s in specs if boundary(s)]
    recs = []
    skipped = []
    if trans:
        before = copy.deepcopy(script)
        for s in trans:
            if s.get('at') is None and s.get('id'):
                s['at'] = 0.0
            recs.append(dict(place(script, s, kit, frame, settings), n=s['_n'], preset=s['_preset'],
                             trigger=s.get('trigger')))
        mt = mapper(before, script)
        for s in rest:
            if s.get('at') is not None and mt is not None:
                got = mt(float(s['at']), nearest=True)
                if got is not None:
                    s['at'] = got
        frame = Frame(script, kit, op.get('platform'))
    for s in rest:
        if s.get('at') is None:
            from letitedit.timeline.edit_sync import layout
            t, i, it = es._find(script, s['id'])
            s['at'] = next((st for x, st, e in layout(t) if x is it), 0.0)
        if s['kind'] == 'text_pop' and _same_caption(s.get('text'), frame.caption_words_at(s['at'], s['at'] +
                                                                                           float(s.get('len') or 1.5))):
            skipped.append(f"item {s['_n']}: text repeats the caption at {_clock(s['at'])}")
            continue
        if s['kind'] == 'glitch' and float(s.get('amount', 0.6)) >= 0.4 and frame.faces(s['at'] + 0.2):
            skipped.append(f"item {s['_n']}: heavy glitch over a face at {_clock(s['at'])}")
            continue
        rec = place(script, s, kit, frame, settings)
        rec.update(n=s['_n'], preset=s['_preset'], trigger=s.get('trigger'), text=s.get('text'),
                   amount=s.get('amount'))
        if s.get('_exact'):
            rec['synced'] = True
        if s.get('said'):
            rec['said'] = s['said']
            if not s.get('words'):
                ok, _ = _said_near(script, s['said'], s['at'], words)
                rec['said_missing'] = not ok
        recs.append(rec)
    return recs, skipped, frame


def _describe_effects(recs, op, problems, mode, sound_receipts, skipped, script, frame):
    """Write the effect summary and retain speaker-side flash placement order."""
    kinds = {}
    for r in recs:
        kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    parts = [f"{len(recs)} effect{'s' if len(recs) != 1 else ''} placed ("
             + ', '.join(f'{v} {k}' for k, v in kinds.items()) + ')']
    synced_recs = [r for r in recs if r.get('synced')]
    shown = [r for r in recs if not r.get('synced')]
    parts.append('; '.join(f"{r['id']} {r['kind']}{' ' + r['preset'] if r.get('preset') else ''} {_clock(r['at'])}"
                           + (f" ({r['note']})" if r.get('note') else '') for r in shown[:30]))
    if synced_recs:
        sy = op.get('_sync_sounds') or {}
        by_role = {}
        for r in synced_recs:
            by_role.setdefault(r.get('trigger') or 'sound', []).append(r['id'])
        parts.append('picture-synced sounds: ' + ', '.join(f'{v} {k.replace("_", " ")}' for k, v in
                                                          (sy.get('counts') or {}).items())
                     + (' (' + '; '.join(sy['skipped']) + ')' if sy.get('skipped') else '')
                     + ' | ids ' + '; '.join(f"{k}: {', '.join(v)}" for k, v in by_role.items()))
    if problems:
        parts.append(f'{len(problems)} rule(s) broken: ' + '; '.join(
            f"{p['id']} {_clock(p['at'])}: {p['rule']}" for p in problems[:20]))
    elif mode != 'off':
        parts.append('every rule held')
    if sound_receipts:
        parts.append('sound timing (125 ms limit): ' + sound_receipts)
    if skipped:
        parts.append('not placed: ' + '; '.join(skipped))
    if op.get('_auto_notes'):
        parts.append('; '.join(op['_auto_notes']))
    if op.get('_cut_flashes'):
        cf = op['_cut_flashes']
        parts.append(f"inverted flashes on {cf['counts']['cut_flash']} cutaway edge(s)"
                     + (' (not flashed: ' + '; '.join(cf['skipped'][:8]) + ')' if cf['skipped'] else '')
                     + '; the click for the same edges is sync_sounds in the same op')
    if op.get('_cut_flashes') and op['_cut_flashes'].get('speaker'):
        import letitedit.looks.cut_flashes as cut_flashes
        blocks = cut_flashes.place_speaker_side(script, op['_cut_flashes'])
        op['_pinned'] = [*op.get('_pinned', []), *blocks]
        parts.append(f"the speaker's picture flashes at the same {len(blocks)} cut(s) (sides: both; blocks {', '.join(blocks)})")
    if op.get('_lighting'):
        lit = op['_lighting']
        parts.append(f"lighting on {len(lit['lit'])} speaker clip{'s' if len(lit['lit']) != 1 else ''}: "
                     + (', '.join(lit['lit']) or 'none new')
                     + (f"; already lit: {', '.join(lit['already'])}" if lit['already'] else '')
                     + ('; ' + '; '.join(lit['skipped']) if lit['skipped'] else '')
                     + ('; room_ev tuned to the Look: ' + '; '.join(
                         f"{t['id']} separation {t['clip_stops']:g} stops against the Look's {t['look_stops']:g}, room_ev {t['room_ev']:g}"
                         for t in lit['tuned']) if lit.get('tuned') else '')
                     + ('; the face is lifted within its limits and never darkened (face-check.json beside each clip)'
                        if lit.get('how') == 'baked' else
                        '; live filters on the clip (Mask: Simple Shape + Color Grading), the window follows the face; '
                        'letitedit_ai lighting.check_live(project) measures the face and the room on the export engine'))
    if op.get('_pace'):
        import letitedit.looks.pace_cut as pace_cut
        parts.append(pace_cut.describe(op['_pace']))
    if op.get('_grade'):
        import letitedit.looks.grade as grade
        parts.append(grade.describe(op['_grade']))
    if frame.face_note:
        parts.append(frame.face_note)
    op['_result'] = ' | '.join(parts)


def apply_op(script, op):
    """{op: fx, items, check?, pack?, platform?}: place every item, then measure the rules."""
    es = _es()
    from letitedit.timeline.edit_sync import mapper
    identity = op.get('look')
    kit = es.kit_for(identity) if identity else es.kit_for(script)
    mode = op.get('check') or 'warn'
    if mode not in CHECKS:
        raise ValueError(f"fx: check is one of {', '.join(CHECKS)}")
    settings = settings_for(kit, op)
    frame = Frame(script, kit, op.get('platform'))
    existing = existing_effects(script, frame=frame)
    words, specs = _prepare_effect_specs(op, script, kit, existing, frame, es)

    recs, skipped, frame = _place_effect_specs(specs, script, kit, frame, settings, mapper, op, es, words)

    problems = check([r for r in recs if not r.get('synced')], frame, kit, existing) if mode != 'off' else []
    if problems and mode == 'strict':
        raise ValueError('fx not applied (check: strict): ' + ' | '.join(
            f"item {next((r['n'] for r in recs if r['id'] == p['id']), '?')} {p['id']} at {_clock(p['at'])}: "
            f"{p['rule']}" for p in problems))
    from letitedit.looks import sound_targets
    sound_receipts = sound_targets.receipts(script, recs)
    op['_placed'] = [{k: v for k, v in r.items() if k in ('id', 'kind', 'preset', 'at', 'len', 'track', 'sfx',
                                                           'said', 'trigger', 'note', 'moved', 'sound_sync')} for r in recs]
    op['_problems'] = problems
    op['_frames_at'] = sorted({round(r['at'] + min(0.35, (r['len'] or 0.6) / 2), 2) for r in recs
                               if r['kind'] not in SOUND_KINDS})[:24]
    script.setdefault('_frames_at', []).extend(op['_frames_at'])
    op['_pinned'] = [r['id'] for r in recs if r.get('id') and not r.get('on_clip')
                     and (r['kind'] != 'transition' or r.get('cut') is not None)] \
        + [r['sfx_id'] for r in recs if r.get('sfx_id') and r['kind'] not in SOUND_KINDS]
    _describe_effects(recs, op, problems, mode, sound_receipts, skipped, script, frame)

    return recs
