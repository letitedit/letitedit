"""The native caption layers and the word-caption layers, solved.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import dataclasses
import hashlib
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
import letitedit.timeline.edit_script as es
import letitedit.timeline.timeline_model as tm
from letitedit.pictures.caption_layout_frame import (  # noqa: E402
    INF, _Unsupported, _fmt, _geom_text, _merge_ranges, _rbox, _shift, _slug, parse_geometry, place_extra,
    slot_anchor
)
from letitedit.pictures.caption_layout_words import (  # noqa: E402
    break_cost, keep_together_spans, vocab_lower
)
from letitedit.pictures.caption_layout_render import (  # noqa: E402
    QtText, _css, column_gaps, melt_text_blocks
)
from letitedit.pictures.caption_layout_cues import (  # noqa: E402
    Cue, Rules, _target_words, best_lines, cue_issues, regroup_cues, split_join
)
from letitedit.pictures.caption_layout_place import (  # noqa: E402
    Obstacle, _place_violations, _timing_violations, _violation, placement_cost, solve_places
)


OPTIONS = {
    'covers_face': ['another allowed place (placements)', "native captions: native_mode='tracks' puts these cues on a "
                    'caption track of their own', 'word captions (a place per cue)', "faces='off' to accept it"],
    'platform_overlay': ['a smaller size (min_size_px allows it)', 'fewer words per cue', "platform_zones='soft'"],
    'protected_region': ['another allowed place (placements)', 'a smaller protected box', 'hard: false'],
    'covers_text': ['move the other text', 'another allowed place (placements)'],
    'fused_words': ['a thinner outline', 'a font with a wider space', 'less pop (pop_scale)'],
    'fused_at_peak': ['less pop (pop_scale)', 'a thinner outline', 'style karaoke or highlight'],
    'too_small': ['allow a smaller minimum (min_size_px)', 'shorter cues', 'a narrower font'],
    'auto_shrunk': ['shorter cues', 'a narrower font', 'a wider place'],
    'reading_speed': ['the speech is faster than the limit: allow more (max_cps)', 'cut the edit so the line plays '
                      'longer'],
    'outside_frame': ['a smaller size', 'shorter cues'], 'outside_safe': ['a smaller size', 'shorter cues'],
    'too_many_lines': ['shorter cues (regroup)', 'allow more lines (max_lines)', 'a smaller size'],
}


def _unresolved(kind, layer, why, options, cue=None, start=None, end=None, constraint=None, **extra):
    u = {'kind': kind, 'layer': layer, 'constraint': constraint or kind, 'why': why, 'options': options}
    if cue is not None:
        start, end = cue.start, cue.end
        u['cue'] = cue.key
    if start is not None:
        u.update(start=round(start, 3), end=round(end, 3), start_clock=_fmt(start), end_clock=_fmt(end))
    u.update(extra)
    return u


def _unresolved_from(v):
    u = {'kind': v['kind'], 'layer': v['layer'], 'cue': v.get('cue'), 'start': v['start'], 'end': v['end'],
         'start_clock': v['start_clock'], 'end_clock': v['end_clock'], 'constraint': v['kind'], 'why': v['detail'],
         'options': OPTIONS.get(v['kind'], ['review it'])}
    for k in ('measured', 'limit', 'at', 'at_clock', 'other'):
        if k in v:
            u[k] = v[k]
    return u


def _min_gap(size_px, em):
    return max(2.0, em * size_px)


# ============================================================================ native caption layers

def _native_layer_obstacles(layer, frame, work):
    """Text obstacles for a caption track that is not being laid out: its cues as rendered."""
    style = layer.style
    got = melt_text_blocks(style, [(c.text, style.get('geometry')) for c in layer.cues], frame, work)
    return [Obstacle('text', f'caption track {layer.track}', c.start, c.end, [(None, g['ink'])], False)
            for c, g in zip(layer.cues, got) if g['ink']]


def _native_rect(model, frame, slot, max_lines):
    """Geometry rect for a slot: the safe width, tall enough for max_lines lines (and the shadow), aligned so cues
    with fewer lines share the bottom (or top, or centre)."""
    sx0, sy0, sx1, sy1 = frame.safe
    rect_h = max_lines * model.line_spacing + 2 * model.offset + 4 + max(0.0, model.shadow[1])
    y, align = slot_anchor(frame, slot)
    ry = y - rect_h if align == 'bottom' else y if align == 'top' else y - rect_h / 2
    ry = max(0.0, min(frame.height - rect_h, ry))
    return (sx0, ry, sx1 - sx0, rect_h), align


def _calibrate(model, blocks, rendered, track, warnings):
    """Correct predicted line widths by what melt drew (Qt may match another face or kern differently)."""
    ratios = []
    for b, r in zip(blocks, rendered):
        if not r['ink'] or not b['ink'] or b['scale'] < 0.999:
            continue
        pw, rw = b['ink'][2] - b['ink'][0], r['ink'][2] - r['ink'][0]
        if pw > 40:
            ratios.append(rw / pw)
    if ratios:
        k = statistics.median(ratios)
        if abs(k - 1) > 0.015:
            model.width_scale = k
        if abs(k - 1) > 0.06:
            warnings.append(f'{track}: the export engine draws {model.face} {abs(k - 1):.0%} '
                            f'{"wider" if k > 1 else "narrower"} than its font file measures (another face matched?); '
                            f'widths follow the rendered size')
        return k
    return None


def _native_user_style(st, user, kit, frame):
    """A requested style (the captions op's friendly keys: font, fill, outline {color, width} or px, shadow
    {color, x, y}, background; size in project pixels) applied to a native caption style. Returns (style, changed)."""
    changed = {}
    raw = es.friendly_text_style({k: v for k, v in user.items() if k != 'size'}, kit, frame.width, frame.height)
    if 'size' in user:
        raw['size'] = str(int(round(float(user['size']))))
    for k, v in raw.items():
        if k != 'shadow' and str(st.get(k)) != str(v):
            changed[k] = v
            st[k] = v
    if 'shadow' in raw:
        changed['shadow'] = raw['shadow']
        st['shadow'] = raw['shadow']
    return st, changed


def _outline_for_gaps(model, texts, min_gap_em):
    """The thickest outline (up to the current one) that keeps min_gap_em of clear space between neighbouring words
    of these texts, or None when the current one already does."""
    lim = _min_gap(model.size, min_gap_em)
    rect = (0, 0, 1e6, 1e6)

    def worst(m):
        return min([g for t in texts for _, _, g in m.gaps(m.block([t], rect))] or [INF])
    if worst(model) >= lim:
        return None
    for o in range(model.outline - 1, -1, -1):
        if worst(model.variant(outline=o)) >= lim:
            return o
    return 0


def _break(model, tokens, max_w, rules, phrases=()):
    """Line breaks for one cue's tokens at a pixel width: ([line text], fits)."""
    keep = keep_together_spans(tokens, phrases)
    lb = [0.0] + [break_cost(tokens[q - 1], tokens[q], None, rules.vocab) + (6.0 if q in keep else 0.0)
                  for q in range(1, len(tokens))] + [0.0]
    b, _, feasible, _ = best_lines([model.line_width(t) for t in tokens], model.space_width(), max_w, rules.max_lines, lb)
    return [' '.join(tokens[b[m]:b[m + 1]]) for m in range(len(b) - 1)], feasible


def _native_groups(cues, model, max_w, rules, regroup, keep_spans, shots):
    """Cue groups for a native layer (see regroup_cues): a cue is a problem when it runs past a sentence end, ends on
    an article, needs more lines than allowed at the width, reads too fast or is one short word."""
    def has_issue(c):
        _, feasible = _break(model, c.tokens, max_w, rules)
        return cue_issues(c.tokens, c.times, rules, None if feasible else rules.max_lines + 1, c.end - c.start)
    return regroup_cues(cues, rules, regroup, shots, keep_spans, has_issue,
                        lambda toks: [model.line_width(t) for t in toks], model.space_width(), max_w)


def _lend_native_display_time(groups, max_cps):
    """Let a regrouped cue use an available pause before it to meet the reading-speed limit."""
    for prev, group in zip(groups, groups[1:]):
        if not group.get('regrouped'):
            continue
        chars = len(' '.join(group['tokens']))
        need = chars / max(1.0, max_cps) - (group['end'] - group['start'])
        gap = group['start'] - prev['end']
        shift = min(0.2, max(0.0, need), max(0.0, gap - 0.02))
        if shift > 0.001:
            group['start'] = round(group['start'] - shift, 3)


def _native_before(H, W, ctx, frame, layer, obstacles, rect0, rules, st0, warnings, work, violations):
    # ---- BEFORE: the cues as they are, rendered by melt in the track's own style
    model0 = QtText(st0, frame)
    # cues on caption tracks an earlier fit split off are drawn in their own track's style and place
    own = {None: (st0, model0, rect0)}
    for c in layer.cues:
        if c.src and c.src not in own:
            try:
                own[c.src] = (c.src_style, QtText(c.src_style, frame), parse_geometry(c.src_style.get('geometry'), W, H))
            except ValueError:
                own[c.src] = (st0, model0, rect0)
    rendered0 = [None] * len(layer.cues)
    for src, (sty, _, _) in own.items():
        idx = [i for i, c in enumerate(layer.cues) if c.src == src]
        got = melt_text_blocks(sty, [(layer.cues[i].text, sty.get('geometry')) for i in idx], frame,
                               work / f'{_slug(layer.track)}-before{"-" + _slug(src) if src else ""}')
        for i, g in zip(idx, got):
            rendered0[i] = g
    mine = [i for i, c in enumerate(layer.cues) if c.src is None]
    _calibrate(model0, [model0.block(layer.cues[i].text.split('\n'), rect0) for i in mine],
               [rendered0[i] for i in mine], layer.track, warnings)
    blocks0 = [own[c.src][1].block(c.text.split('\n'), own[c.src][2]) for c in layer.cues]
    before_boxes = [r['ink'] or b['ink'] for b, r in zip(blocks0, rendered0)]
    for c, b, r, box in zip(layer.cues, blocks0, rendered0, before_boxes):
        violations += _native_cue_violations(ctx, layer, c, own[c.src][1], b, r, box, obstacles, 'before', rules)
    last_end = -1.0
    for c in layer.cues:
        if c.start < last_end - 0.05:
            violations.append(_violation('overlapping_cues', layer.track, c, 'starts before the previous cue ends',
                                         'before'))
        last_end = max(last_end, c.end)
    return model0, before_boxes


def _native_readable_style(H, W, ctx, frame, layer, model0, o, obstacles, st0, unresolved, warnings):
    # ---- the style the layout works in: a requested style, a readable size, an outline that keeps words apart
    st = dict(st0)
    changed = {}
    if o['style']:
        st, changed = _native_user_style(st, dict(o['style']), ctx['kit'], frame)
    model = QtText(st, frame)
    if model.face == model0.face:
        model.width_scale = model0.width_scale
    face_heights = [box[3] - box[1] for ob in obstacles if ob.kind == 'face' and ob.hard
                    for _, box in ob.boxes]
    if (frame.shape == 'tall' and face_heights and
            max(face_heights) > 0.6 * (frame.safe[3] - frame.safe[1]) and
            'size' not in o['lock'] and 'size' not in o['style']):
        cap = max(frame.min_size_px, 0.067 * min(W, H))
        if model.size > cap:
            changed['size'] = str(int(round(cap)))
            st['size'] = changed['size']
            model = QtText(st, frame)
            model.width_scale = model0.width_scale if model.face == model0.face else 1.0
    if model.size < frame.min_size_px and 'size' not in o['lock']:
        new = int(math.ceil(frame.min_size_px))
        warnings.append(f'{layer.track}: text size {model.size} px is under the readable minimum '
                        f'{frame.min_size_px:.0f} px; set to {new} px')
        changed['size'] = str(new)
        st['size'] = str(new)
        if st.get('shotcut:pointSize') or st0.get('shotcut:pointSize'):
            changed['shotcut:pointSize'] = str(round(new * 0.75))
        model = QtText(st, frame)
        model.width_scale = model0.width_scale if model.face == model0.face else 1.0
    fix = _outline_for_gaps(model, [c.text.replace('\n', ' ') for c in layer.cues], o['min_gap_em'])
    if fix is not None:
        if 'outline' in o['lock']:
            unresolved.append(_unresolved('fused_words', layer.track, f'with outline {model.outline} px the words of '
                                          f'some cues are under {o["min_gap_em"]:.2f} em apart and the outline is '
                                          f'locked', ['allow the outline to change', 'a font with a wider space']))
        else:
            warnings.append(f'{layer.track}: outline {model.outline} -> {fix} px so words keep '
                            f'{o["min_gap_em"]:.2f} em of clear space between them')
            changed['outline'] = str(fix)
            st['outline'] = str(fix)
            model = model.variant(outline=fix)
    return st, changed, model


def _native_placements(before_boxes, ctx, frame, groups, model, model0, o, obstacles, rect0, rules,
        slot_rects, slots, w):
    # ---- places: the current one, then the allowed slots; each breaks lines for its own width
    cands = [('current', rect0, model0.halign, model0.valign)]
    if 'position' not in o['lock']:
        for s in slots:
            rect, align = slot_rects[s]
            cands.append((s, rect, 'c', {'bottom': 'b', 'top': 't'}.get(align, 'm')))
    pref = o['prefer'] or _nearest_slot(frame, slots, before_boxes, rect0)
    layouts = []
    for name, rect, ha, va in cands:
        m = model.variant(halign=ha, valign=va)
        max_w = m.max_line_width(rect[2])
        per_lines = []
        for g in groups:
            lines, ok = _break(m, g['tokens'], max_w, rules, o['keep_together'])
            for extra in (1, 2):              # a cue that can't be regrouped: an extra line beats being shrunk
                if ok:
                    break
                more, ok = _break(m, g['tokens'], max_w, dataclasses.replace(rules, max_lines=rules.max_lines + extra),
                                  o['keep_together'])
                if ok:
                    lines = more
            per_lines.append(lines)
        need = max([len(l) for l in per_lines] + [rules.max_lines])
        if name != 'current' and need > rules.max_lines:
            rect = _native_rect(model, frame, name, need)[0]
        layouts.append((name, rect, ha, va, m, [(lines, m.block(lines, rect)) for lines in per_lines]))
    gcues = [Cue(g['key'], g['start'], g['end'], g['tokens'], g['times']) for g in groups]
    unary = []
    for i, g in enumerate(groups):
        row = []
        for k, (name, rect, ha, va, m, per) in enumerate(layouts):
            lines, blk = per[i]
            cost, hard = placement_cost(blk['ink'], g['start'], g['end'], obstacles, frame, w)
            if cost != INF:
                if blk['scale'] < 0.999:
                    cost += w.shrink
                if len(lines) > rules.max_lines:
                    cost += 3.0
                cost += place_extra(name, slots, pref, w, frame.free_y is not None)
            row.append(cost)
        unary.append(row)
    if o['native_mode'] == 'tracks' and len(layouts) > 1:
        choice = solve_places(unary, gcues, ctx['cuts'], w)
    else:
        totals = [sum(min(unary[i][k], 1e6) for i in range(len(groups))) for k in range(len(layouts))]
        best = min(range(len(layouts)), key=lambda k: (totals[k], k))
        choice = [best] * len(groups)
    return layouts, pref, choice


def _native_after(choice, ctx, frame, groups, layer, layouts, obstacles, rules, st, unresolved, work,
        violations):
    # ---- AFTER: render the proposed cues in the proposed style(s) and check them like the old ones
    used = sorted(set(choice), key=lambda k: -choice.count(k))
    styles = {}
    for k in used:
        name, rect, ha, va, m, per = layouts[k]
        sst = dict(st)
        if name != 'current':
            sst.update(geometry=_geom_text(*rect), halign='center',
                       valign={'b': 'bottom', 't': 'top', 'm': 'middle'}[va])
        styles[k] = sst
    rendered1 = [None] * len(groups)
    for k in used:
        idx = [i for i in range(len(groups)) if choice[i] == k]
        got = melt_text_blocks(styles[k], [('\n'.join(layouts[k][5][i][0]), styles[k]['geometry']) for i in idx], frame,
                               work / f'{_slug(layer.track)}-after-{layouts[k][0]}')
        for i, g in zip(idx, got):
            rendered1[i] = g
    finals, after_boxes = [], []
    for i, g in enumerate(groups):
        k = choice[i]
        name, rect, ha, va, m, per = layouts[k]
        lines, blk = per[i]
        box = rendered1[i]['ink'] or blk['ink']
        after_boxes.append(box)
        cue = Cue(g['key'], g['start'], g['end'], g['tokens'], g['times'], '\n'.join(lines))
        vs = _native_cue_violations(ctx, layer, cue, m, blk, rendered1[i], box, obstacles, 'after', rules)
        violations += vs
        finals.append({'group': g, 'lines': lines, 'place': name, 'k': k, 'block': blk, 'box': box})
    for v in violations:
        if v['stage'] == 'after' and (v['severity'] == 'error' or v['kind'] in (
                'covers_face', 'platform_overlay', 'reading_speed', 'auto_shrunk', 'too_many_lines')):
            unresolved.append(_unresolved_from(v))
    return used, styles, finals, after_boxes


def _native_edit_changes(H, changed, finals, layer, layouts, st0, styles, used, warnings):
    # ---- changes in the edit vocabulary: the track keeps its own place when cues still use it (only the cues that
    # move go on a caption track of their own); otherwise it takes the place most cues use
    base_k = 0 if 0 in used and layouts[0][0] == 'current' else used[0]
    tracks_out = {}
    for i, f in enumerate(finals):
        name = layer.track if f['k'] == base_k else f'{layer.track} ({layouts[f["k"]][0]})'
        tracks_out.setdefault(name, (f['k'], []))[1].append(i)
    changes = []
    for name, (k, idx) in tracks_out.items():
        sst = styles[k]
        cue_list = [{'start': es.clock(finals[i]['group']['start']), 'end': es.clock(finals[i]['group']['end']),
                     'text': '\n'.join(finals[i]['lines'])} for i in sorted(idx, key=lambda i: finals[i]['group']['start'])]
        if name == layer.track:
            delta = {kk: v for kk, v in changed.items()}
            for kk in ('geometry', 'halign', 'valign'):
                if str(sst.get(kk)) != str(st0.get(kk)):
                    delta[kk] = sst[kk]
            old = [{'start': es.clock(c.start), 'end': es.clock(c.end), 'text': c.text} for c in layer.cues
                   if c.src is None]             # the track's own cues (not those on a split-off track)
            op = {'op': 'captions', 'track': name, 'note': 'letitedit_caption_fit'}
            if cue_list != old:
                op['cues'] = cue_list
            if delta:
                op['style'] = delta
            if len(op) > 3:
                changes.append(op)
        else:
            full = {kk: v for kk, v in sst.items() if kk in es.CAPTION_STYLE_KEYS or kk.startswith('shotcut:')}
            sh = st0.get('shadow')
            if isinstance(sh, dict):
                sc = H / 1080.0
                full['shadow'] = {'color': _css(sh.get('fgcolour')), 'x': round(float(sh.get('x', 0)) / sc, 2),
                                  'y': round(float(sh.get('y', 0)) / sc, 2)}
            changes.append({'op': 'captions', 'track': name, 'cues': cue_list, 'style': full,
                            'note': 'letitedit_caption_fit: cues that need another place'})
    for sib in layer.siblings:
        if sib not in tracks_out:            # split off by an earlier fit and not needed now: emptied (kept as a track)
            changes.append({'op': 'captions', 'track': sib, 'cues': [], 'note': 'letitedit_caption_fit: cues moved back'})
    if len(tracks_out) > 1:
        warnings.append(f'{layer.track}: a caption track has one place, so cues that need another go on a caption '
                        f'track of their own: {", ".join(n for n in tracks_out if n != layer.track)}')
    return base_k, tracks_out, changes


def solve_native(ctx, layer, obstacles, joins, work):
    frame, o, w = ctx['frame'], ctx['opts'], ctx['weights']
    W, H = frame.width, frame.height
    st0 = dict(layer.style)
    try:
        rect0 = parse_geometry(st0.get('geometry'), W, H)
    except ValueError as exc:
        raise _Unsupported(f'caption track {layer.track}: {exc}; captions with animated geometry are not laid '
                           f'out') from exc
    lines_now = max([len(c.text.split('\n')) for c in layer.cues] + [1])
    tw = max(3, _target_words(layer))     # a static cue of two words flashes by
    rules = Rules(max_lines=int(o['max_lines'] or (min(3, lines_now) if lines_now > 2 else 2)), max_cps=o['max_cps'],
                  min_dur=float(o['min_duration_s'] if o['min_duration_s'] is not None else 0.8),
                  max_dur=o['max_duration_s'], target_words=tw, max_words=max(4, tw * 2 + 2),
                  vocab=vocab_lower([t for c in layer.cues for t in c.tokens]))
    warnings, unresolved, violations = [], [], []
    model0, before_boxes = _native_before(H, W, ctx, frame, layer, obstacles, rect0, rules, st0, warnings,
        work, violations)
    st, changed, model = _native_readable_style(H, W, ctx, frame, layer, model0, o, obstacles, st0,
        unresolved, warnings)
    # ---- tokens: a space the transcript shows is restored (never letters)
    token_fixes = []
    cues = [Cue(c.key, c.start, c.end, list(c.tokens), list(c.times), c.text, shot=c.shot, timing=c.timing)
            for c in layer.cues]
    for ci, ti, parts in sorted(joins, key=lambda j: (j[0], -j[1])):
        cue = cues[ci]
        sp = split_join(cue.tokens[ti], parts)
        if not sp:
            continue
        t = cue.times[ti]
        cue.tokens[ti:ti + 1] = sp
        mid = (t[0] + t[1]) / 2 if t else None
        cue.times[ti:ti + 1] = [(t[0], mid), (mid, t[1])] if t else [None, None]
        token_fixes.append({'cue': cue.key, 'from': layer.cues[ci].tokens[ti], 'to': sp})
        violations.append(_violation('missing_space', layer.track, layer.cues[ci],
                                     f'"{layer.cues[ci].tokens[ti]}" is the words "{" ".join(parts)}" without the '
                                     f'space between them (transcript)', 'before'))
    # ---- grouping, at the safe width (the widest a slot offers)
    slots = o['slots']
    slot_rects = {s: _native_rect(model, frame, s, rules.max_lines) for s in slots}
    safe_max_w = min(model.max_line_width(r[0][2]) for r in slot_rects.values())
    keep = keep_together_spans([t for c in cues for t in c.tokens], o['keep_together'])
    groups = _native_groups(cues, model, safe_max_w, rules, o['regroup'], keep, ctx['shots'])
    _lend_native_display_time(groups, rules.max_cps)
    for k, g in enumerate(groups):
        g['key'] = f'{layer.track}#{k + 1}'
    layouts, pref, choice = _native_placements(before_boxes, ctx, frame, groups, model, model0, o, obstacles,
        rect0, rules, slot_rects, slots, w)
    used, styles, finals, after_boxes = _native_after(choice, ctx, frame, groups, layer, layouts, obstacles,
        rules, st, unresolved, work, violations)
    base_k, tracks_out, changes = _native_edit_changes(H, changed, finals, layer, layouts, st0, styles, used,
        warnings)
    cues_after = [{'key': f['group']['key'], 'start': round(f['group']['start'], 3), 'end': round(f['group']['end'], 3),
                   'text': '\n'.join(f['lines']), 'place': f['place'], 'box': _rbox(after_boxes[i]),
                   'size_px': round(f['block']['eff_size'] * frame.output_scale, 1),
                   'regrouped': bool(f['group'].get('regrouped'))} for i, f in enumerate(finals)]
    unchecked = []
    unk = [c for c in layer.cues if c.timing == 'unknown']
    if unk:
        unchecked.append({'what': f'{layer.track}: grouping and reading speed by word timing',
                          'ranges': _merge_ranges([(c.start, c.end) for c in unk]),
                          'why': 'these words are not in a cached transcript, so the cues keep their grouping'})
    summary = {'track': layer.track, 'kind': 'native', 'cues_before': len(layer.cues), 'cues_after': len(finals),
               'font': model.face, 'size_px': model.size, 'outline_px': model.outline,
               'place': ', '.join(f'{layouts[k][0]} x{choice.count(k)}' for k in used), 'preferred_slot': pref,
               'geometry_before': st0.get('geometry'), 'geometry_after': styles[base_k].get('geometry'),
               'style_changes': changed, 'token_fixes': token_fixes, 'max_lines': rules.max_lines,
               'regrouped_cues': sum(1 for f in finals if f['group'].get('regrouped')),
               'width_calibration': round(model0.width_scale, 3), 'line_spacing_px': model.line_spacing,
               'tracks_out': list(tracks_out), 'siblings': list(layer.siblings)}
    return {'summary': summary, 'changes': changes, 'violations': violations, 'unresolved': unresolved,
            'warnings': warnings, 'unchecked': unchecked, 'fonts': sorted({model0.path, model.path}),
            'words_hash': hashlib.sha1(json.dumps([[c.tokens, c.times] for c in layer.cues], default=str)
                                       .encode()).hexdigest()[:12],
            'cues_after': cues_after, 'layer': layer, 'tracks_out': list(tracks_out),
            'as_obstacles': [Obstacle('text', f'caption track {layer.track}', f['group']['start'], f['group']['end'],
                                      [(None, b)], False) for f, b in zip(finals, after_boxes) if b]}


def _nearest_slot(frame, slots, boxes, rect0):
    boxes = [b for b in boxes if b]
    cy = statistics.median([(b[1] + b[3]) / 2 for b in boxes]) if boxes else rect0[1] + rect0[3] / 2
    return min(slots, key=lambda s: abs(slot_anchor(frame, s)[0] - cy))


def _native_cue_violations(ctx, layer, cue, model, block, rendered, box, obstacles, stage, rules):
    frame, o = ctx['frame'], ctx['opts']
    out = []
    ev = 'melt' if rendered and rendered.get('ink') else 'predicted'
    eff = block['eff_size']
    if rendered and rendered.get('ink') and block.get('ink') and block['scale'] >= 0.999:
        ph, rh = block['ink'][3] - block['ink'][1], rendered['ink'][3] - rendered['ink'][1]
        if ph > 0 and rh < 0.9 * ph:          # qtext shrank it although the prediction fitted
            eff = model.size * rh / ph
    if eff < model.size - 0.5:
        out.append(_violation('auto_shrunk', layer.track, cue, f'the text block is wider or taller than its place, so it '
                              f'is drawn at {eff:.0f} px instead of {model.size} px', stage, box=box,
                              measured=round(eff, 1), limit=model.size, evidence=ev))
    if eff < frame.min_size_px - 0.5:
        out.append(_violation('too_small', layer.track, cue, f'text drawn at {eff * frame.output_scale:.0f} px, under the '
                              f'readable minimum {frame.min_size_px * frame.output_scale:.0f} px', stage, box=box,
                              measured=round(eff * frame.output_scale, 1),
                              limit=round(frame.min_size_px * frame.output_scale, 1), evidence=ev))
    if len(block['words']) > rules.max_lines:
        out.append(_violation('too_many_lines', layer.track, cue, f"{len(block['words'])} lines (at most "
                              f'{rules.max_lines})', stage, measured=len(block['words']), limit=rules.max_lines))
    lim = _min_gap(eff, o['min_gap_em'])
    if rendered and rendered.get('mask') is not None:
        rows = block['words']
        if block.get('ink'):
            dx, dy = rendered['ink'][0] - block['ink'][0], rendered['ink'][1] - block['ink'][1]
            rows = [[(t, _shift(b, dx, dy)) for t, b in row] for row in rows]
        gaps = column_gaps(rendered['mask'], rendered['ink'], rows)
        source = 'melt'
    else:
        gaps = model.gaps(block)
        source = 'predicted'
    if gaps:
        a, b, g = min(gaps, key=lambda x: x[2])
        if g < lim:
            out.append(_violation('fused_words', layer.track, cue, f'"{a} {b}" read as one word: {g:.0f} px of clear '
                                  f'space between them (needs {lim:.0f})', stage, box=box, measured=round(g, 1),
                                  limit=round(lim, 1), evidence=source))
    out += _timing_violations(layer.track, cue, rules, stage)
    out += _place_violations(layer.track, cue, box, cue.start, cue.end, obstacles, frame, stage, evidence=ev)
    return out


# ============================================================================ word-caption layers

def _word_layer_style(frame, layer, o, scale, warnings):
    # ---- the layer's style: requested changes, a readable size, then pop/outline so words stay apart
    base = dict(layer.cues[0].params)
    user = dict(o['style'] or {})
    delta = {}
    for k in ('font', 'outline_width', 'shadow', 'pop_scale', 'style', 'outline', 'fill', 'highlight', 'uppercase',
              'box'):
        if k in user:
            delta[k] = user[k]
    if isinstance(user.get('outline'), dict):
        delta['outline_width'] = user['outline'].get('width', base.get('outline_width', 7))
        delta['outline'] = user['outline'].get('color', base.get('outline'))
    if 'size' in user:
        delta['size'] = round(float(user['size']) / scale, 2)        # project pixels -> the template's 1080p units
    size_px = float(delta.get('size', base.get('size', 84))) * scale
    if size_px < frame.min_size_px and 'size' not in o['lock']:
        delta['size'] = round(frame.min_size_px / scale + 0.5, 1)
        warnings.append(f"{layer.track}: size {size_px:.0f} px is under the readable minimum {frame.min_size_px:.0f} "
                        f"px; set to {delta['size']} (template units, {delta['size'] * scale:.0f} px)")
    # ---- one size through the layer: chunks that were shrunk one by one (to keep clear of a face) come back to the
    # layer's largest size, and the places below decide where each one fits; a cue that still has no free place at
    # that size is made smaller below and reported
    sizes = [float(c.params.get('size', base.get('size', 84))) for c in layer.cues if c.params]
    if 'size' not in delta and 'size' not in o['lock'] and sizes and max(sizes) - min(sizes) > 0.5:
        delta['size'] = round(max(sizes), 2)
        warnings.append(f"{layer.track}: caption sizes ran from {min(sizes) * scale:.0f} to {max(sizes) * scale:.0f} px; "
                        f"set to one size, {max(sizes) * scale:.0f} px")
    return base, delta


def _word_horizontal_layout(W, delta, frame, groups, layer, o, scale, unresolved, wc):
    # ---- per cue: the line width inside the safe area, a size only when a word can't fit, then candidates
    sx0, sy0, sx1, sy1 = frame.safe
    safe_w = sx1 - sx0
    plan = []
    for g in groups:
        length = g['end'] - g['start']
        cur = wc.normalise({**g['params'], **delta, 'words': g['words']}, length)
        plan.append({'g': g, 'cur': cur, 'rec_cur': wc.record(cur, length)})
    # one horizontal layout for the whole layer (cues side by side in time must not jump sideways): the current one
    # when every cue's ink (peaks included) is inside the safe width, else centred in the safe area
    fits = all(pc['rec_cur']['ink'] is None or (pc['rec_cur']['ink'][0] >= sx0 - 2 and pc['rec_cur']['ink'][2] <= sx1 + 2)
               for pc in plan)
    h_mode = 'current' if fits or {'center_x', 'max_width'} <= o['lock'] else 'safe area'
    for pc in plan:
        g, cur = pc['g'], pc['cur']
        length = g['end'] - g['start']
        safe, rec_safe = cur, pc['rec_cur']
        if h_mode != 'current':
            safe = dict(cur)
            if 'center_x' not in o['lock']:
                safe['center_x'] = round(((sx0 + sx1) / 2) / W, 4)
            if 'max_width' not in o['lock']:
                safe['max_width'] = round(min(float(cur.get('max_width', 0.82)), safe_w * 0.94 / W), 4)
            rec_safe = wc.record(safe, length)
            for _ in range(3):                 # the ink, peaks included, inside the safe width
                ink = rec_safe['ink']
                if not ink or ink[2] - ink[0] <= safe_w + 0.5 or 'max_width' in o['lock']:
                    break
                safe['max_width'] = round(max(0.3, float(safe['max_width']) * safe_w / (ink[2] - ink[0]) - 0.005), 4)
                rec_safe = wc.record(safe, length)
            pc['cur'], pc['rec_cur'] = safe, rec_safe
        pc['safe'], pc['rec_safe'] = safe, rec_safe
        eff_px = rec_safe['size'] * scale
        cue = Cue(g['key'], g['start'], g['end'], [x[0] for x in g['words']],
                  [(g['start'] + x[1], g['start'] + x[2]) for x in g['words']])
        if eff_px < frame.min_size_px - 0.5:
            unresolved.append(_unresolved('too_small', layer.track, f'the longest word only fits a line at {eff_px:.0f}'
                                          f' px, under the readable minimum {frame.min_size_px:.0f} px (the template '
                                          f'shrinks it to fit)', OPTIONS['too_small'] + ['a wider line (max_width)'],
                                          cue=cue, measured=round(eff_px, 1), limit=round(frame.min_size_px, 1)))
        pc['cue'] = cue
    return plan, h_mode


def _word_placements(frame, layer, o, obstacles, plan, rec0, scale, w, warnings, wc):
    # ---- places: the current one, then the allowed slots; held through shots and phrases
    slots = o['slots']
    pref = o['prefer'] or _nearest_word_slot(frame, slots, rec0)
    names = ['current'] + ([] if 'position' in o['lock'] else list(slots))
    unary, places = [], []
    for pc in plan:
        row, prow = [], []
        for name in names:
            if name == 'current':
                params, box = pc['cur'], pc['rec_cur']['ink']
            else:
                pos, box = _word_slot_position(pc['rec_safe'], frame, name)
                params = None if pos is None else {**pc['safe'], 'position': round(pos, 4)}
            cost, hard = placement_cost(box, pc['g']['start'], pc['g']['end'], obstacles, frame, w)
            if params is None:
                cost = INF
            elif cost != INF:
                cost += place_extra(name, slots, pref, w, frame.free_y is not None)
            row.append(cost)
            prow.append(params)
        unary.append(row)
        places.append(prow)
    # a cue no allowed place keeps clear (overlays, hard regions): a smaller size, never under the readable minimum
    shrunk = []
    for i, pc in enumerate(plan):
        if min(unary[i]) < INF or 'size' in o['lock']:
            continue
        length = pc['g']['end'] - pc['g']['start']
        base_size = float(pc['safe'].get('size', 84))
        for f in (0.85, 0.72, 0.6):
            sz = round(base_size * f, 1)
            if sz * scale < frame.min_size_px:
                break
            p2 = {**pc['safe'], 'size': sz}
            r2 = wc.record(p2, length)
            row, prow = [], []
            for name in names:
                if name == 'current':
                    params, box = {**p2, 'position': pc['cur'].get('position')}, r2['ink']
                else:
                    pos, box = _word_slot_position(r2, frame, name)
                    params = None if pos is None else {**p2, 'position': round(pos, 4)}
                cost, _ = placement_cost(box, pc['g']['start'], pc['g']['end'], obstacles, frame, w)
                if params is None:
                    cost = INF
                elif cost != INF:
                    cost += w.shrink * (1 - f) + place_extra(name, slots, pref, w, frame.free_y is not None)
                row.append(cost)
                prow.append(params)
            if min(row) < INF:
                unary[i], places[i] = row, prow
                pc['shrunk'] = sz
                shrunk.append(f'{pc["g"]["key"]} ({_fmt(pc["g"]["start"])}) {sz * scale:.0f} px')
                break
    if shrunk:
        warnings.append(f'{layer.track}: no allowed place kept these cues clear at full size, so they are smaller '
                        f'(never under {frame.min_size_px:.0f} px): ' + ', '.join(shrunk[:12])
                        + (' ...' if len(shrunk) > 12 else ''))
    return pref, names, unary, places


def solve_words(ctx, layer, obstacles, work):
    frame, o, w = ctx['frame'], ctx['opts'], ctx['weights']
    W, H = frame.width, frame.height
    wc = ctx['wordcaps']()
    scale = H / 1080.0
    tw = _target_words(layer)
    rules = Rules(max_lines=int(o['max_lines'] or 2), max_cps=o['max_cps'],
                  min_dur=float(o['min_duration_s'] if o['min_duration_s'] is not None else 0.4),
                  max_dur=o['max_duration_s'], target_words=tw, max_words=max(3, tw * 2),
                  vocab=vocab_lower([t for c in layer.cues for t in c.tokens]))
    warnings, unresolved, violations = [], [], []
    # ---- BEFORE: every cue recorded frame by frame as the template draws it
    rec0 = []
    for c in layer.cues:
        c.params = wc.normalise(c.params, c.end - c.start)
        rec0.append(wc.record(c.params, c.end - c.start))
    for c, r in zip(layer.cues, rec0):
        violations += _word_cue_violations(ctx, layer, c, c.params, r, obstacles, 'before', rules)
    base, delta = _word_layer_style(frame, layer, o, scale, warnings)
    # ---- grouping, then pop/outline so the words of the final cues stay apart
    groups = _words_groups(ctx, layer, rules, delta)
    gap = _words_gap_fix(ctx, layer, delta, [(Cue(g['key'], g['start'], g['end'], [x[0] for x in g['words']], []),
                                              {**g['params'], **delta, 'words': g['words']}, g['end'] - g['start'])
                                             for g in groups])
    if gap.get('delta'):
        delta.update(gap['delta'])
        warnings.append(f"{layer.track}: {gap['note']}")
    if gap.get('unresolved'):
        unresolved.append(gap['unresolved'])
    plan, h_mode = _word_horizontal_layout(W, delta, frame, groups, layer, o, scale, unresolved, wc)
    pref, names, unary, places = _word_placements(frame, layer, o, obstacles, plan, rec0, scale, w, warnings,
        wc)
    choice = solve_places(unary, [pc['cue'] for pc in plan], ctx['cuts'], w)
    finals = []
    for i, pc in enumerate(plan):
        k = choice[i]
        params = places[i][k] if places[i][k] is not None else pc['cur']
        length = pc['g']['end'] - pc['g']['start']
        rec = pc['rec_cur'] if names[k] == 'current' and not pc.get('shrunk') else wc.record(params, length)
        violations += _word_cue_violations(ctx, layer, pc['cue'], params, rec, obstacles, 'after', rules)
        finals.append({**pc['g'], 'params': params, 'rec': rec, 'place': names[k]})
    for v in violations:
        if v['stage'] == 'after' and (v['severity'] == 'error' or v['kind'] in (
                'covers_face', 'platform_overlay', 'fused_at_peak', 'too_many_lines')):
            unresolved.append(_unresolved_from(v))
    changes = _word_changes(ctx, layer, finals, wc)
    cues_after = [{'key': f['key'], 'start': round(f['start'], 3), 'end': round(f['end'], 3),
                   'text': ' '.join(x[0] for x in f['words']),
                   'lines': [' '.join(f['words'][i][0] for i in line) for line in f['rec']['lines']],
                   'place': f['place'], 'position': f['params'].get('position'), 'box': _rbox(f['rec']['ink']),
                   'size_px': round(f['rec']['size'] * scale * frame.output_scale, 1),
                   'regrouped': bool(f.get('regrouped'))} for f in finals]
    try:
        import letitedit.catalogs.fonts as fonts
        f0 = ctx['kit'].font(base.get('font', 'captions'), 'captions')
        fonts_used = [fonts.font_file(f0['family'], f0['weight'], f0['italic'])[0]]
    except Exception:  # noqa: BLE001
        fonts_used = []
    summary = {'track': layer.track, 'kind': 'words', 'cues_before': len(layer.cues), 'cues_after': len(finals),
               'animation': base.get('style', 'pop'), 'size_px': round(float(delta.get('size', base.get('size', 84)))
                                                                        * scale, 1),
               'preferred_slot': pref, 'place': ', '.join(f'{n} x{sum(1 for f in finals if f["place"] == n)}'
                                                          for n in dict.fromkeys(f['place'] for f in finals)),
               'style_changes': delta, 'gap_fix': gap.get('note'), 'horizontal': h_mode,
               'regrouped_cues': sum(1 for f in finals if f.get('regrouped')), 'tracks_out': [layer.track]}
    return {'summary': summary, 'changes': changes, 'violations': violations, 'unresolved': unresolved,
            'warnings': warnings, 'unchecked': [], 'fonts': fonts_used, 'template': wc.src_hash,
            'words_hash': hashlib.sha1(json.dumps([[c.tokens, c.times] for c in layer.cues], default=str)
                                       .encode()).hexdigest()[:12],
            'cues_after': cues_after, 'layer': layer, 'tracks_out': [layer.track], 'finals': finals,
            'as_obstacles': [Obstacle('text', f'word captions {layer.track}', f['start'], f['end'],
                                      [(None, f['rec']['ink'])], False) for f in finals if f['rec']['ink']]}


def _nearest_word_slot(frame, slots, recs):
    ys = [((r['ink'][1] + r['ink'][3]) / 2) for r in recs if r.get('ink')]
    cy = statistics.median(ys) if ys else frame.height * 0.75
    return min(slots, key=lambda s: abs(slot_anchor(frame, s)[0] - cy))


def _word_slot_position(rec, frame, slot):
    """(the template's position value, ink box there) that puts the caption's ink, peaks included, at a slot."""
    ink = rec['ink']
    if not ink:
        return None, None
    y, align = slot_anchor(frame, slot)
    dy = y - ink[3] if align == 'bottom' else y - ink[1] if align == 'top' else y - (ink[1] + ink[3]) / 2
    pos = (rec['top'] + dy + rec['block_h'] / 2) / frame.height
    if not 0.05 <= pos <= 0.95:
        clamped = min(0.95, max(0.05, pos))
        dy += (clamped - pos) * frame.height
        pos = clamped
    return pos, _shift(ink, 0, dy)


def _settled(params, i, j, t):
    """True when neither word of a pair is animating at t (the caption at rest)."""
    words = params.get('words') or []
    for k in (i, j):
        if 0 <= k < len(words) and float(words[k][1]) <= t < float(words[k][1]) + 0.4:
            return False
    return True


def _gap_report(rec, params, scale, o):
    """(worst gap at rest, worst gap while a word pops) as (time, i, j, gap, limit) or None."""
    size_px = rec['size'] * scale
    rest_lim, peak_lim = _min_gap(size_px, o['min_gap_em']), _min_gap(size_px, o['peak_gap_em'])
    rest = peak = None
    for t, i, j, g in rec['gaps']:
        if _settled(params, i, j, t):
            if g < rest_lim and (rest is None or g < rest[3]):
                rest = (t, i, j, g, rest_lim)
        elif g < peak_lim and (peak is None or g < peak[3]):
            peak = (t, i, j, g, peak_lim)
    return rest, peak


def _word_cue_violations(ctx, layer, cue, params, rec, obstacles, stage, rules):
    frame, o = ctx['frame'], ctx['opts']
    out = []
    scale = frame.height / 1080.0
    texts = rec['texts']
    rest, peak = _gap_report(rec, params, scale, o)

    def name(i, j):
        return f'the highlight box and "{texts[j]}"' if i < 0 else f'"{texts[i]} {texts[j]}"'
    if rest:
        t, i, j, g, lim = rest
        out.append(_violation('fused_words', layer.track, cue, f'{name(i, j)} read as one word: {g:.0f} px apart '
                              f'(needs {lim:.0f})', stage, at=cue.start + t, box=rec['ink'], measured=round(g, 1),
                              limit=round(lim, 1), evidence='template'))
    if peak and not (rest and (rest[1], rest[2]) == (peak[1], peak[2])):
        t, i, j, g, lim = peak
        bad = sorted({round(cue.start + tt, 3) for tt, a, b, gg in rec['gaps'] if (a, b) == (i, j) and gg < lim})
        out.append(_violation('fused_at_peak', layer.track, cue, f'{name(i, j)} touch while a word pops ({g:.0f} px '
                              f'apart at the peak, needs {lim:.0f}; {len(bad)} frame(s))', stage, at=cue.start + t,
                              box=rec['ink'], measured=round(g, 1), limit=round(lim, 1), evidence='template',
                              other={'frames_at': bad[:12]}))
    size_px = rec['size'] * scale
    if size_px < frame.min_size_px - 0.5:
        out.append(_violation('too_small', layer.track, cue, f'drawn at {size_px * frame.output_scale:.0f} px, under the '
                              f'readable minimum {frame.min_size_px * frame.output_scale:.0f} px', stage,
                              measured=round(size_px * frame.output_scale, 1),
                              limit=round(frame.min_size_px * frame.output_scale, 1), evidence='template'))
    if len(rec['lines']) > rules.max_lines:
        out.append(_violation('too_many_lines', layer.track, cue, f"{len(rec['lines'])} lines (at most "
                              f'{rules.max_lines})', stage, measured=len(rec['lines']), limit=rules.max_lines))
    out += _timing_violations(layer.track, cue, rules, stage, check_cps=False)
    out += _place_violations(layer.track, cue, rec['ink'], cue.start, cue.end, obstacles, frame, stage,
                             evidence='template')
    return out


def _words_gap_fix(ctx, layer, delta, items):
    """The layer's pop_scale / outline_width that keep words apart (at rest: min_gap_em; while a word pops:
    peak_gap_em), changing as little as possible: less pop first, then a thinner outline. items: [(Cue, params,
    length)] of the layer's final cues."""
    frame, o, wc = ctx['frame'], ctx['opts'], ctx['wordcaps']()
    scale = frame.height / 1080.0
    failing = []
    for c, params, length in items:
        p = wc.normalise(params, length)
        r = wc.record(p, length)
        if any(_gap_report(r, p, scale, o)):
            failing.append((c, p, length))
    if not failing:
        return {}
    base = failing[0][1]
    pop0 = float(base.get('pop_scale', 1.15)) if base.get('style', 'pop') == 'pop' else None
    ow0 = float(base.get('outline_width', 7)) if base.get('outline') else 0.0
    pops = [pop0] if pop0 is None or 'pop_scale' in o['lock'] else \
        [pop0] + [x for x in (1.1, 1.06, 1.03, 1.0) if x < pop0 - 1e-6]
    outs = [ow0] if not ow0 or {'outline', 'outline_width'} & o['lock'] else \
        [ow0] + [round(ow0 * f, 1) for f in (0.8, 0.65, 0.5, 0.4) if ow0 * f >= 2.0]
    tries = sorted(((p, q) for p in pops for q in outs if (p, q) != (pop0, ow0)),
                   key=lambda pq: (abs((pq[0] or 0) - (pop0 or 0)) / 0.15) + abs(pq[1] - ow0) / max(1.0, ow0) * 1.4)
    for pop, ow in tries:
        ok = True
        for c, p, length in failing:
            q = dict(p)
            if pop is not None:
                q['pop_scale'] = pop
            if ow0:
                q['outline_width'] = ow
            r = wc.record(wc.normalise(q, length), length)
            if any(_gap_report(r, q, scale, o)):
                ok = False
                break
        if ok:
            d, parts = {}, []
            if pop is not None and abs(pop - pop0) > 1e-6:
                d['pop_scale'] = pop
                parts.append(f'pop_scale {pop0:g} -> {pop:g}')
            if ow0 and abs(ow - ow0) > 1e-6:
                d['outline_width'] = ow
                parts.append(f'outline_width {ow0:g} -> {ow:g}')
            return {'delta': d, 'note': ' and '.join(parts) + f' so words stay apart ({len(failing)} cue(s) had words '
                                                              f'touching)'}
    c0 = failing[0][0]
    return {'unresolved': _unresolved('fused_words', layer.track,
                                      f'words still touch with pop_scale down to {min(pops) if pop0 else "-"} and '
                                      f'outline_width down to {min(outs):g}', OPTIONS['fused_words'] +
                                      ['style karaoke or highlight', 'allow pop_scale / outline to change (lock)'],
                                      cue=c0, constraint='min_gap_em / peak_gap_em')}


def _words_groups(ctx, layer, rules, delta):
    """Cue groups for a word-caption layer: [{key, start, end, words (relative to start), params, item_id, sources,
    regrouped}]. Regrouped only where a run has a grouping problem (regroup='auto') or everywhere ('all')."""
    o, wc = ctx['opts'], ctx['wordcaps']()
    out = []

    def keep(c):
        return {'key': c.key, 'start': c.start, 'end': c.end, 'words': c.params['words'], 'params': c.params,
                'item_id': c.item_id, 'sources': [c.item_id], 'regrouped': False, 'times': list(c.times),
                'tokens': list(c.tokens)}
    if o['regroup'] == 'none':
        return [keep(c) for c in layer.cues]
    keep_all = keep_together_spans([t for c in layer.cues for t in c.tokens], o['keep_together'])
    p0 = wc.normalise({**layer.cues[0].params, **delta}, 1.0)
    cx = wc.ctx(p0, 1.0)
    font, size = p0.get('font', 'captions'), float(p0.get('size', 84))
    grow = 1 + (float(p0.get('pop_scale', 1.15)) - 1) * 0.4 if p0.get('style', 'pop') == 'pop' else 1.0
    space = max(cx.font(font, size).getlength(' '), cx.s(size) * 0.26)
    max_w = cx.w * statistics.median(float(c.params.get('max_width', 0.82)) for c in layer.cues)

    def widths_of(toks):
        return [cx.measure(str(t).upper() if p0.get('uppercase') else str(t), font, size)[0] * grow for t in toks]

    def has_issue(c):
        p = wc.normalise({**c.params, **delta}, c.end - c.start)
        return cue_issues(c.tokens, c.times, rules, len(wc.geometry(p, c.end - c.start)['lines']), c.end - c.start)
    for gi, g in enumerate(regroup_cues(layer.cues, rules, o['regroup'], ctx['shots'], keep_all, has_issue, widths_of,
                                       space, max_w)):
        if not g['regrouped']:
            out.append(keep(g['cue']))
            continue
        src = g['sources']
        out.append({'key': f'{layer.track}-fit-{gi + 1:03d}', 'start': g['start'], 'end': g['end'],
                    'tokens': g['tokens'], 'times': g['times'], 'params': dict(src[0].params), 'item_id': None,
                    'sources': [c.item_id for c in src], 'regrouped': True,
                    'words': [[t, round(max(0.0, tt[0] - g['start']), 3), round(max(0.0, tt[1] - g['start']), 3)]
                              for t, tt in zip(g['tokens'], g['times'])]})
    return out


def _word_changes(ctx, layer, finals, wc):
    """Edit ops: {set} on kept items whose params change, {delete} + {insert at} where cues were regrouped."""
    deletes, inserts, sets = [], [], []
    by_id = {c.item_id: c for c in layer.cues}
    used = {it.get('id') for t in ctx['script']['tracks'] for it in t['items'] if it.get('id')}
    for f in finals:
        if f.get('regrouped'):
            for sid in f['sources']:
                if sid and sid not in deletes:
                    deletes.append(sid)
            iid, n = _slug(f['key']), 1
            while iid in used:
                n += 1
                iid = f"{_slug(f['key'])}-{n}"
            used.add(iid)
            at = math.ceil(f['start'] * 10000) / 10000
            inserts.append({'op': 'insert', 'track': layer.track, 'at': at,
                            'item': {'id': iid, 'graphic': {'template': 'word_captions', 'params': wc.slim(f['params'])},
                                     'len': math.floor((f['end'] - at) * 10000) / 10000},
                            'note': 'letitedit_caption_fit: regrouped'})
            continue
        old = by_id.get(f['item_id'])
        if old is None:
            continue
        d = {k: v for k, v in f['params'].items() if k != 'words' and v is not None
             and json.dumps(old.params.get(k), default=str) != json.dumps(v, default=str)}
        if d:
            sets.append({'op': 'set', 'id': f['item_id'], 'graphic': {'params': d}, 'note': 'letitedit_caption_fit'})
    sets = [s for s in sets if s['id'] not in deletes]
    return [{'op': 'delete', 'id': d, 'note': 'letitedit_caption_fit: regrouped'} for d in deletes] + inserts + sets


# ============================================================================ faces

def _absolutise(root_el, folder):
    for p in root_el.iter('property'):
        if p.get('name') in ('resource', 'warp_resource') and p.text:
            v = p.text.strip()
            if (not v or v.startswith(('#', '0x', '/', '\\', 'color:', 'colour:')) or ':' in v[:3]
                    or re.fullmatch(r'-?\d+(\.\d+)?', v)):
                continue
            cand = folder / v
            if cand.exists():
                p.text = str(cand.resolve())


def _variant(path, out, hide_tracks=(), drop_feeds=None):
    """A copy of the project with tracks' pictures hidden and caption burn-ins removed (drop_feeds: feed names, or
    'all'), media paths made absolute."""
    tree = ET.parse(path)
    r = tree.getroot()
    _absolutise(r, Path(path).resolve().parent)
    tractors = [e for e in r if e.tag == 'tractor']
    marked = [t for t in tractors if tm.props(t).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    for i, tr in enumerate(main.findall('track')):
        if i in hide_tracks:
            tr.set('hide', 'both' if tr.get('hide', '') in ('audio', 'both') else 'video')
    if drop_feeds:
        for f in list(main.findall('filter')):
            p = tm.props(f)
            if p.get('mlt_service') == 'subtitle' and (drop_feeds == 'all' or p.get('feed') in drop_feeds):
                main.remove(f)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return Path(out)


def _text_track_indices(timeline, layers):
    """Main-tractor indices of the video tracks that carry caption or overlay text."""
    names = {l.track for l in layers if l.kind == 'words'}
    idx = set()
    for t in timeline.video_tracks():
        if t.name in names:
            idx.add(t.index)
            continue
        for it in t.items:
            if it.elem is None:
                continue
            p = tm.props(it.elem)
            if p.get('letitedit_ai:graphic') or '"kind": "ass"' in (p.get('letitedit_ai:made') or ''):
                idx.add(t.index)
                break
    return idx
