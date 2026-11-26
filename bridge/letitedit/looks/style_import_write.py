"""From reference reports to a draft letitedit style: merge several references (what they share is the style, what
only one does is content), then write a pack with style_pack._legacy_create(): style.yaml (captions, fonts, colours, editing,
music, sound effects, effect presets with when/where rules, hook rules, measured numbers, provenance), recipe.md (the
findings in our own words) and an import/ folder with the reports and pictures.

    facts(report)                 -> the flat facts of one reference
    merge(reports, notes='')      -> {'videos', 'facts': {key: {values, value, spread, consistent}}, 'one_offs', ...}
    draft(merged, name, kind, notes='', label=None) -> {'data', 'recipe_md', 'assets'}
    write(merged, name, kind, notes='', label=None, overwrite=False, reports=()) -> style_pack._legacy_create()'s result
"""
from __future__ import annotations

import datetime
import json
import math
import re
import shutil
from pathlib import Path

import numpy as np

TOOL = 'letitedit style import (bridge/style_import.py)'
SFX_FILE = {'whoosh': 'whoosh.wav', 'pop': 'pop.wav', 'ding': 'ding.wav', 'boom / bass hit': 'thump.wav',
            'click': 'pop.wav', 'riser': 'whoosh.wav', 'scratch / glitch': 'whoosh.wav'}
SR_SYNTH = 44100


def synth(name):
    """A short stand-in sound made here (numpy, no samples): 'pop', 'ding', 'whoosh' or 'thump' -> WAV bytes
    (44.1 kHz, mono, 16 bit). letitedit's own; the style ships these in place of the references' sounds."""
    import io
    import wave
    sr = SR_SYNTH
    rng = np.random.default_rng(7)
    if name == 'pop':
        t = np.arange(int(0.09 * sr)) / sr
        f = 1100 * np.exp(-t * 28) + 260
        y = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 45)
        y[:40] += rng.normal(0, 0.4, 40) * np.linspace(1, 0, 40)
    elif name == 'ding':
        t = np.arange(int(1.2 * sr)) / sr
        y = sum(a * np.sin(2 * np.pi * 1320 * k * t) * np.exp(-t * d)
                for k, a, d in ((1.0, 1.0, 3.5), (2.76, 0.45, 6.0), (5.4, 0.2, 9.0)))
        y *= np.minimum(1.0, t / 0.004)
    elif name == 'whoosh':
        n = int(0.55 * sr)
        t = np.arange(n) / sr
        noise = rng.normal(0, 1, n)
        env = np.sin(np.pi * np.clip(t / 0.55, 0, 1)) ** 2
        # a one-pole low-pass whose cut-off sweeps up then down: the 'swish'
        cut = 300 + 5000 * env
        alpha = 1 - np.exp(-2 * np.pi * cut / sr)
        y = np.zeros(n)
        acc = 0.0
        for i in range(n):
            acc += alpha[i] * (noise[i] - acc)
            y[i] = acc
        y *= env
    else:  # thump
        t = np.arange(int(0.4 * sr)) / sr
        f = 95 * np.exp(-t * 6) + 45
        y = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 9)
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.7
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype('<i2').tobytes())
    return buf.getvalue()
SFX_NAME = {'whoosh': 'whoosh', 'pop': 'pop', 'ding': 'ding', 'boom / bass hit': 'thump', 'click': 'pop',
            'riser': 'whoosh', 'scratch / glitch': 'whoosh'}
ANIM_IN = {'scale': 'pop', 'fade': 'fade', 'slide': 'slide_up', 'cut': 'none'}
ANIM_OUT = {'scale': 'shrink', 'fade': 'fade', 'slide': 'slide_down', 'cut': 'none'}
TRIGGER_MAP = {'word mentioned': 'mention', 'number': 'number', 'punchline': 'punchline',
               'sentence start': 'topic_change', 'at a cut': 'cut', 'during speech': 'emphasis',
               'between phrases': 'pause', 'no speech': 'cut'}
ZONE_POS = {'upper_left': 'upper_left', 'upper_right': 'upper_right', 'lower_left': 'lower_left',
            'lower_right': 'lower_right', 'upper': 'top', 'lower': 'bottom', 'middle_left': 'left',
            'middle_right': 'right', 'centre': 'center'}


def _get(d, path, default=None):
    for k in path.split('.'):
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def _med(x):
    return x.get('median') if isinstance(x, dict) else x


def facts(rep):
    """The style facts of one report, flat: {key: number | str | bool | list}."""
    dur = float(rep.get('duration_s') or 0)
    mins = max(1e-6, dur / 60)
    p = rep.get('pacing') or {}
    c = rep.get('captions') or {}
    o = rep.get('overlays') or {}
    s = rep.get('sound') or {}
    m = s.get('music') or {}
    fx = s.get('sfx') or {}
    lk = rep.get('look') or {}
    h = rep.get('hook') or {}
    e = rep.get('ending') or {}
    f = rep.get('faces') or {}
    tr = p.get('transitions') or {}
    zooms = rep.get('zooms') or []
    punches = []
    for zoom in zooms:
        if zoom.get('kind') not in ('punch_in', 'punch_out'):
            continue
        try:
            scale = float(zoom.get('scale'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(scale) and scale > 0 and math.isfinite(1 / scale):
            punches.append(scale)
    ov_good = [x for x in o.get('events') or [] if x.get('conf', 0) >= 0.5]
    gfx = [x for x in ov_good if x.get('kind') != 'text']
    # text pops: short text laid on top; labels and titles (on screen through a section) are counted apart
    txt = [x for x in ov_good if x.get('kind') == 'text' and x.get('role') not in ('label', 'title', 'watermark')
           and (x.get('len') or 0) < 2.5]
    from letitedit.looks.style_import_visual import from_reports
    semantic = (from_reports([rep])['references'][0]['semantic'] if rep.get('visual_review') is not None
                else {'broll_share': None, 'reviewed_share': 0})
    out = {
        'duration_s': round(dur, 1), 'orientation': rep.get('orientation'),
        'cuts_per_min': p.get('cuts_per_minute'), 'shot_len_median_s': _get(p, 'shot_length_s.median'),
        'shot_len_p25_s': _get(p, 'shot_length_s.p25'), 'shot_len_p75_s': _get(p, 'shot_length_s.p75'),
        'talking_head': p.get('talking_head'), 'cutaway_share': p.get('cutaway_share'),
        'broll_share': semantic['broll_share'], 'semantic_reviewed_share': semantic['reviewed_share'],
        'broll_rhythm': semantic.get('broll_rhythm'),
        'jump_cut_share': round((p.get('cut_kinds') or {}).get('jump', 0) / max(1, p.get('cuts') or 0), 3),
        'punches_per_min': round(len(punches) / mins, 2),
        'punch_scale': round(float(np.median([scale if scale >= 1 else 1 / scale for scale in punches])), 3)
        if punches else None,
        'push_ins_per_min': round((p.get('push_ins') or 0) / mins, 2),
        'shakes_per_min': round(len(rep.get('shake') or []) / mins, 2),
        'transitions_per_min': round(sum(v for k, v in tr.items() if k not in ('fade_in', 'fade_out')) / mins, 2),
        'transition_kinds': sorted(k for k in tr if k not in ('fade_in', 'fade_out')),
        'fades_in_out': sorted(k for k in tr if k in ('fade_in', 'fade_out')),
        'captions': bool(c.get('present')),
        'caption_chunking': c.get('chunking'), 'caption_words': _med(c.get('words_per_caption')),
        'caption_lines': _med(c.get('lines_per_caption')), 'caption_case': c.get('case'),
        'caption_zone': _get(c, 'position.zone'), 'caption_y': _get(c, 'position.y.median'),
        'caption_line_h': _get(c, 'size.line_height_share.median'), 'caption_width': _get(c, 'size.width_share.median'),
        'caption_timing': c.get('timing'), 'caption_lead_s': _get(c, 'lead_s.median'),
        'caption_fill': _get(c, 'look.fill'), 'caption_fill_kind': _get(c, 'look.fill_kind'),
        'caption_outline': _get(c, 'look.outline.color'), 'caption_outline_px': _get(c, 'look.outline.width_px'),
        'caption_plate': _get(c, 'look.plate'), 'caption_shadow': (_get(c, 'look.shadow_share') or 0) >= 0.5,
        'caption_weight': _get(c, 'look.weight_guess'),
        'caption_highlight': bool(_get(c, 'highlight.present')), 'caption_highlight_color': _get(c, 'highlight.color'),
        'caption_highlight_kind': _get(c, 'highlight.kind'),
        'caption_entry': _get(c, 'entry.style'), 'caption_entry_ms': _get(c, 'entry.ms_to_full.median'),
        'caption_fonts': [x['family'] for x in (c.get('font_guess') or [])[:3]],
        'caption_font_weight': ((c.get('font_guess') or [{}])[0]).get('weight'),
        'overlays_per_min': round(len(gfx) / mins, 2), 'text_pops_per_min': round(len(txt) / mins, 2),
        'overlay_zone': _top((x.get('zone') for x in gfx)),
        'overlay_from_face': _top((x.get('from_face') for x in gfx if x.get('from_face'))),
        'overlay_size': round(float(np.median([x.get('size') or math.sqrt(x['area']) for x in gfx])), 3) if gfx else None,
        'overlay_len_s': round(float(np.median([x['len'] for x in gfx])), 2) if gfx else None,
        'overlay_entry': _top((x.get('entry') for x in gfx if x.get('entry'))),
        'overlay_exit': _top((x.get('exit') for x in gfx if x.get('exit'))),
        'text_pop_entry': _top((x.get('entry') for x in txt if x.get('entry'))),
        'text_pop_exit': _top((x.get('exit') for x in txt if x.get('exit'))),
        'camera_moves_per_min': round(len(rep.get('camera_moves') or []) / mins, 2),
        'split_share': _share(rep, 'layout', dur, lambda e: e.get('kind') == 'split'),
        'split_where': _top((e.get('where') for e in (rep.get('layout') or {}).get('events') or []
                             if e.get('kind') == 'split' and e.get('conf', 0) >= 0.5)),
        'inset_share': _share(rep, 'layout', dur, lambda e: e.get('kind') == 'inset'),
        'slow_motion_share': (None if str(_get(rep, 'speed.checks.absolute_slow_fast') or '').startswith('not_checked')
                              else _share(rep, 'speed', dur, lambda e: e.get('kind') == 'slow')),
        'cards': len(rep.get('cards') or []),
        'overlay_triggers': _count((x.get('trigger') or '').split(' + ')[0] for x in gfx if x.get('trigger')),
        'overlay_with_sfx': round(sum(1 for x in gfx if x.get('sfx')) / len(gfx), 2) if gfx else None,
        'text_pop_triggers': _count((x.get('trigger') or '').split(' + ')[0] for x in txt if x.get('trigger')),
        'text_pop_zone': _top((x.get('zone') for x in txt)),
        'labels_per_min': round(len((rep.get('on_screen_text') or {}).get('labels') or []) / mins, 2),
        'watermark': bool((rep.get('on_screen_text') or {}).get('watermarks')),
        'words_per_min': _get(s, 'speech.words_per_minute_while_talking'), 'speech_share': _get(s, 'speech.speech_share'),
        'pause_p90_s': _get(s, 'speech.pauses_s.p90_within_talk') or _get(s, 'speech.pauses_s.p90'),
        'music_share': m.get('music_share'), 'tempo_bpm': m.get('tempo_bpm'), 'beat_quality': m.get('beat_quality'),
        'cuts_on_beat': _get(m, 'cuts_on_beat.share'), 'cuts_on_beat_chance': _get(m, 'cuts_on_beat.chance'),
        'music_under_voice_db': m.get('under_voice_db'), 'ducking_db': m.get('ducking_db'),
        'sfx_per_min': fx.get('per_minute'), 'sfx_kinds': fx.get('kinds') or {},
        'sfx_at_cuts': fx.get('at_cuts_share'), 'sfx_at_overlays': fx.get('at_overlays_share'),
        'loudness_lufs': _get(s, 'loudness.integrated_lufs'), 'silences_per_min': round((_get(s, 'silences.count') or 0) / mins, 2),
        'brightness': _get(lk, 'brightness.median'), 'contrast': lk.get('contrast_word'),
        'saturation': lk.get('saturation_word'), 'warmth': lk.get('warmth'), 'grain': _get(lk, 'grain.word'),
        'vignette': _get(lk, 'vignette.likely'), 'letterbox': _get(lk, 'bars.letterbox'),
        'blurred_bands': _get(lk, 'blurred_bands.likely'),
        'face_share': f.get('share_with_face'), 'framing': f.get('typical_framing'),
        'face_height': _get(f, 'face_height.median'),
        'hook_talks_at_once': h.get('talks_from_the_first_second'), 'hook_text_at_once': h.get('text_in_first_second'),
        'hook_question': h.get('question'), 'hook_number': h.get('number'),
        'hook_moves': (h.get('cuts') or 0) + (h.get('zooms') or 0), 'hook_sfx': bool(h.get('sfx')),
        'hook_said': h.get('said'),
        'ending_cta': bool(e.get('call_to_action')), 'ending_cta_words': e.get('call_to_action') or [],
        'ending_loops': e.get('loop_guess'), 'ending_said': e.get('said'),
        'sections': len(rep.get('sections') or []),
        'pace_variation': _cv([w['per_minute'] for w in rep.get('pace_curve') or []]),
    }
    out['effects_per_min'] = round(sum(x or 0 for x in (out['punches_per_min'], out['overlays_per_min'],
                                                          out['text_pops_per_min'], out['shakes_per_min'],
                                                          out['transitions_per_min'])), 2)
    return out


def _top(vals):
    vals = [v for v in vals if v]
    return max(set(vals), key=vals.count) if vals else None


def _share(rep, key, dur, which):
    """Share of the video's time covered by the counted events of one kind (layout, speed)."""
    ev = [e for e in (rep.get(key) or {}).get('events') or [] if e.get('conf', 0) >= 0.5 and which(e)]
    return round(min(1.0, sum(max(0.0, e['end'] - e['t']) for e in ev) / max(1e-6, dur)), 3)


def _count(vals):
    out = {}
    for v in vals:
        if v:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _cv(vals):
    vals = [float(v) for v in vals if v is not None]
    if len(vals) < 2 or np.mean(vals) == 0:
        return None
    return round(float(np.std(vals) / np.mean(vals)), 2)


# ------------------------------------------------------------------ several references -> one style

def _agree(values):
    """(value, spread, consistent) of one fact over the references."""
    vals = [v for v in values if v is not None and v != [] and v != {}]
    if not vals:
        return None, None, None
    if all(isinstance(v, bool) for v in vals):
        share = sum(vals) / len(vals)
        return share >= 0.5, round(share, 2), (share >= 0.75 or share <= 0.25) if len(vals) > 1 else None
    if all(isinstance(v, (int, float)) for v in vals):
        med = float(np.median(vals))
        lo, hi = min(vals), max(vals)
        rel = (hi - lo) / abs(med) if abs(med) > 1e-9 else (0.0 if hi == lo else float('inf'))
        absolute = hi - lo
        ok = (rel <= 0.6 or absolute <= 0.15 * max(1.0, abs(med))) if len(vals) > 1 else None
        return round(med, 3), {'min': round(lo, 3), 'max': round(hi, 3)}, ok
    if all(isinstance(v, dict) for v in vals):
        tot = {}
        for v in vals:
            for k, n in v.items():
                tot[k] = tot.get(k, 0) + n
        return dict(sorted(tot.items(), key=lambda kv: -kv[1])), None, None
    if all(isinstance(v, list) for v in vals):
        flat = [x for v in vals for x in v]
        common = sorted({x for x in flat if sum(1 for v in vals if x in v) >= max(1, math.ceil(len(vals) * 2 / 3))})
        return common or _top(flat) and [_top(flat)], None, (bool(common) if len(vals) > 1 else None)
    keyed = [json.dumps(v, sort_keys=True) if not isinstance(v, str) else v for v in vals]
    top = max(set(keyed), key=keyed.count)
    share = keyed.count(top) / len(keyed)
    val = vals[keyed.index(top)]
    return val, round(share, 2), (share >= 2 / 3) if len(vals) > 1 else None


CONTENT_KEYS = ('hook_said', 'ending_said', 'ending_cta_words', 'duration_s')


def ref_names(reports):
    """A short, unique name per reference: the file name, with its folder when two files share a name."""
    names = [Path(r['file']).name for r in reports]
    out = []
    for r, nm in zip(reports, names):
        if names.count(nm) > 1:
            nm = f"{Path(r['file']).parent.name}/{nm}" if Path(r['file']).parent.name not in ('renders', 'render',
                                                                                             'export', 'exports') \
                else f"{Path(r['file']).parent.parent.name}/{nm}"
        out.append(nm)
    if len(set(out)) < len(out):
        out = [f'{k + 1}. {nm}' for k, nm in enumerate(out)]
    return out


def merge(reports, notes=''):
    """Several references -> one set of facts: each fact's value over the references (median for numbers, the most
    common for words), its spread, and whether they agree (the style) or not (it varies: content or a one-off)."""
    fs = [facts(r) for r in reports]
    keys = list(fs[0]) if fs else []
    merged = {}
    for k in keys:
        value, spread, ok = _agree([f.get(k) for f in fs])
        merged[k] = {'value': value, 'spread': spread, 'consistent': ok,
                     'values': [f.get(k) for f in fs]}
    consistent = sorted(k for k, v in merged.items() if v['consistent'] and k not in CONTENT_KEYS)
    varies = sorted(k for k, v in merged.items() if v['consistent'] is False and k not in CONTENT_KEYS)
    one_offs = []
    for r in reports:
        name = r.get('name')
        for o in [x for x in (r.get('overlays') or {}).get('events') or [] if x.get('conf', 0) >= 0.5][:12]:
            one_offs.append({'video': name, 't': o['t'], 'what': o.get('text') or o.get('kind') or 'graphic',
                             'said': o.get('said'), 'word': o.get('word')})
        for t in ((r.get('on_screen_text') or {}).get('labels') or [])[:6]:
            one_offs.append({'video': name, 'what': f'label "{t}"'})
        hk = (r.get('hook') or {}).get('said')
        if hk:
            one_offs.append({'video': name, 'what': f'hook line "{hk}"'})
    shown = ref_names(reports)
    from letitedit.looks.style_import_visual import from_reports
    visual = (from_reports(reports) if any(report.get('native_effects') or report.get('visual_review')
                                          for report in reports) else None)
    return {'format': 'letitedit-style-import/1', 'videos': [{'file': r['file'], 'name': nm,
                                                              'duration_s': r['duration_s'], 'kind': r['kind'],
                                                              'report': str(Path(r['folder']) / 'report.json'),
                                                              'breakdown': r.get('breakdown')}
                                                             for r, nm in zip(reports, shown)],
            'n': len(reports), 'facts': merged, 'consistent': consistent, 'varies': varies, 'one_offs': one_offs,
            'notes': notes or '', 'made': datetime.datetime.now().isoformat(timespec='seconds'),
            'single_reference': len(reports) == 1, 'visual': visual}


# ------------------------------------------------------------------ the draft style

def _v(merged, key, default=None):
    f = merged['facts'].get(key)
    if not f:
        return default
    v = f['value']
    return default if v is None else v


def _hexok(x):
    return isinstance(x, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', x) is not None


def _draft_captions(merged, V, data):
    """Build agreed colours, fonts and caption settings from measured facts."""
    def agreed(key):
        # a colour the references disagree on is not the style's: leave it to the defaults
        f = merged['facts'].get(key) or {}
        return f.get('consistent') is not False
    fill = V('caption_fill') if _hexok(V('caption_fill')) and agreed('caption_fill') else None
    outline = V('caption_outline') if _hexok(V('caption_outline')) and agreed('caption_outline') else None
    hl = (V('caption_highlight_color') if V('caption_highlight') and _hexok(V('caption_highlight_color'))
          and agreed('caption_highlight_color') else None)
    colors = {}
    if fill:
        colors['primary'] = fill
        colors['light'] = fill if _lum(fill) > 160 else '#FFFFFF'
    if hl:
        colors['secondary'] = hl
        colors['accent'] = hl
    if outline and _lum(outline) < 90:
        colors['dark'] = outline
    if colors:
        data['colors'] = colors
    fonts = V('caption_fonts') or []
    weight = {'black': 900, 'bold': 800, 'regular': 500}.get(V('caption_weight') or '', 700)
    if fonts:
        data['fonts'] = {'captions': {'family': fonts[0], 'weight': weight},
                         'heading': {'family': fonts[0], 'weight': max(weight, 800)}}
    # captions
    if V('captions'):
        line_h = V('caption_line_h')
        H = 1920 if V('orientation') != 'horizontal' else 1080
        size = int(round((line_h or 0.035) * H * 0.8))
        y = V('caption_y')
        pos = 'top' if (y or 0.8) < 0.33 else 'center' if (y or 0.8) < 0.62 else 'bottom'
        margin = round(max(0.03, min(0.45, 1 - (y or 0.85) - (line_h or 0.03) / 2)), 3) if pos == 'bottom' else \
            round(max(0.03, min(0.45, (y or 0.15) - (line_h or 0.03) / 2)), 3) if pos == 'top' else 0.07
        case = {'ALL CAPS': 'upper', 'lower case': 'lower'}.get(V('caption_case'), 'as_spoken')
        words = V('caption_words') or 3
        cap = {'font': 'captions', 'size': max(28, min(140, size)), 'fill': 'light' if fill else 'light',
               'position': pos, 'margin': margin, 'max_lines': int(min(3, max(1, round(V('caption_lines') or 1)))),
               'max_chars': int(max(8, min(48, round(words * 6.5)))), 'case': case}
        has_outline = bool(outline) or (V('caption_outline_px') is not None and agreed('caption_outline_px'))
        if has_outline:
            cap['outline'] = {'color': 'dark', 'width': int(max(1, min(10, V('caption_outline_px') or 3)))}
        else:
            cap['outline'] = None
        if V('caption_shadow'):
            cap['shadow'] = {'color': 'dark', 'x': 3, 'y': 4}
        plate = V('caption_plate')
        if _hexok(plate):
            cap['background'] = {'color': plate}
        data['captions'] = cap
        if V('caption_chunking') in ('one word at a time', 'two or three words') or V('caption_highlight'):
            entry = V('caption_entry') or 'cut'
            style = 'karaoke' if V('caption_highlight') and V('caption_highlight_kind') == 'text' else \
                'highlight' if V('caption_highlight') else 'pop' if entry in ('pop', 'bounce') else 'plain'
            wc = {'style': style, 'font': 'captions', 'size': cap['size'], 'fill': 'light',
                  'outline': 'dark' if has_outline else None,
                  'outline_width': cap['outline']['width'] if has_outline else 0,
                  'position': pos, 'margin_y': margin, 'uppercase': case == 'upper'}
            if hl:
                wc['highlight'] = 'secondary'
            if entry == 'bounce':
                wc['pop_scale'] = 1.2
            elif entry == 'pop':
                wc['pop_scale'] = 1.12
            data['graphics'] = {'word_captions': {k: v for k, v in wc.items() if v is not None}}


def _draft_editing(V, data, pace, kind):
    """Set editing, music and export options from the measured pacing and levels."""
    # editing, music, export
    p90 = V('pause_p90_s')
    soft = [k for k in (V('transition_kinds') or []) if k in ('dissolve', 'fade_black', 'fade_white')]
    data['editing'] = {'pace': pace,
                       'transitions': 'dissolve' if soft and (V('transitions_per_min', 0) or 0) >= 2 else 'cut',
                       'max_pause': round(max(0.15, min(1.2, p90 if p90 else 0.6)), 2)}
    if V('blurred_bands'):
        data['editing']['blur_pad'] = True
    music = {}
    uv = V('music_under_voice_db')
    if (V('music_share', 0) or 0) >= 0.3 and uv is not None:
        music['zones'] = {'talk': round(max(-30.0, min(-6.0, uv)), 1)}
        music['duck_under_speech'] = bool((V('ducking_db', 0) or 0) >= 3)
        music['notes'] = (f"Music on {round(100 * V('music_share'))}% of the references"
                          + (f", around {round(V('tempo_bpm'))} BPM" if V('tempo_bpm') else '')
                          + (f", {round(abs(uv))} dB under the voice" if uv is not None else '')
                          + (f", rising {round(V('ducking_db'))} dB in the pauses" if (V('ducking_db') or 0) >= 3 else '')
                          + '.')
    elif (V('music_share', 0) or 0) < 0.2:
        music['notes'] = 'The references have little or no music.'
    if music:
        data['music'] = music
    lufs = V('loudness_lufs')
    data['export'] = {'preset': 'social_h264' if kind == 'short' else 'high_quality_h264',
                      'loudness': round(max(-18.0, min(-9.0, lufs)), 1) if lufs is not None else -14.0}


def _draft_sounds(V, merged, n, data):
    """Create measured sound stand-ins, credits and event mappings."""
    # sound effects: the kinds heard, mapped to letitedit's own generated sounds
    kinds = V('sfx_kinds') or {}
    # sound effects are the least reliable measurement (on letitedit's own edits most finds were music or speech):
    # the style only carries them when every reference has a steady rate of them
    sfx_rates = [x for x in (merged['facts'].get('sfx_per_min') or {}).get('values') or [] if x is not None]
    sfx_sure = bool(sfx_rates) and len(sfx_rates) == n and min(sfx_rates) >= 3.0
    heard = [k for k, c in kinds.items() if k in SFX_FILE and c >= max(1, n)] if sfx_sure else []
    assets, credits, smap = {}, [], {}
    for k in heard:
        fname = SFX_FILE[k]
        if f'assets/{fname}' not in assets:
            assets[f'assets/{fname}'] = synth(fname.split('.')[0])
        smap[SFX_NAME[k]] = f'assets/{fname}'
    for rel in assets:
        credits.append({'file': rel, 'source': 'synthesised by letitedit style import (bridge/style_import_write.py '
                                               'synth()), a stand-in for the kind of sound heard in the references',
                        'licence': "letitedit's own (generated)"})
    events = {}
    if 'whoosh' in smap:
        events['transition'] = 'whoosh'
        if (V('sfx_at_cuts', 0) or 0) >= 0.3:
            events['cut'] = 'whoosh'
    if 'pop' in smap:
        events['popup'] = 'pop'
        events['text'] = 'pop'
    if 'ding' in smap:
        events['count'] = 'ding'
    if 'thump' in smap:
        events['punchline'] = 'thump'
        events['shake'] = 'thump'
    if smap:
        data['sfx'] = {'gain_db': -12.0, 'map': smap, 'events': events}
    if credits:
        data['credits'] = credits
    return assets, smap


def draft(merged, name, kind='short', notes='', label=None):
    """The draft style: (data for style.yaml, recipe.md text, assets to copy)."""
    V = lambda k, d=None: _v(merged, k, d)  # noqa: E731
    n = merged['n']
    label = label or name.replace('-', ' ').replace('_', ' ').strip().capitalize()
    cpm = V('cuts_per_min', 0) or 0
    pace = 'fast' if cpm >= 20 else 'medium' if cpm >= 8 else 'slow'
    tags = []
    if V('talking_head'):
        tags.append('talking head')
    if V('captions'):
        tags += ['captions'] + (['word by word'] if V('caption_chunking') == 'one word at a time' else [])
    if (V('overlays_per_min', 0) or 0) >= 2:
        tags.append('pop-ups')
    if (V('punches_per_min', 0) or 0) >= 3:
        tags.append('punch-ins')
    sfx_rates0 = [x for x in (merged['facts'].get('sfx_per_min') or {}).get('values') or [] if x is not None]
    sfx_steady = bool(sfx_rates0) and len(sfx_rates0) == n and min(sfx_rates0) >= 3.0
    if sfx_steady:
        tags.append('sound effects')
    if (V('music_share', 0) or 0) >= 0.5:
        tags.append('music')
    tags.append({'fast': 'fast cuts', 'medium': 'steady pace', 'slow': 'slow pace'}[pace])
    data = {'name': label, 'label': label, 'kind': kind, 'tags': tags, 'recipe': 'recipe.md',
            'description': f'Imported from {n} reference video{"s" if n != 1 else ""} by letitedit style import '
                           f'(a draft: measured numbers and our own written recipe; refine before relying on it).'}
    bits = []
    if V('captions'):
        bits.append(f"{V('caption_chunking') or 'captions'} captions")
    bits.append(f'{pace} cuts ({round(cpm)}/min)')
    if (V('punches_per_min', 0) or 0) >= 1:
        bits.append('punch-ins')
    if (V('overlays_per_min', 0) or 0) >= 1:
        bits.append('pop-ups on key words')
    if sfx_steady:
        bits.append('sound effects')
    data['summary'] = (', '.join(bits)[:1].upper() + ', '.join(bits)[1:])[:140]
    # colours and fonts
    _draft_captions(merged, V, data)

    _draft_editing(V, data, pace, kind)

    assets, smap = _draft_sounds(V, merged, n, data)

    # effect presets with when / where rules
    effects, recipe_fx = presets(merged, smap)
    if effects:
        data['effects'] = effects
    epm = V('effects_per_min', 0) or 0
    if epm:
        gap = round(60 / max(epm, 1e-6), 1)
        data['fx'] = {'density': {'per_min': int(math.ceil(epm * 1.2)), 'min_gap_s': round(max(0.5, gap * 0.4), 1)},
                      'safe_zone': 'youtube_shorts' if kind == 'short' else None,
                      'never': ['outside_safe_zone', 'overlapping'],
                      'rhythm': f'In the references something is added on screen about every {gap} s '
                                f'({epm} effects a minute: punch-ins, pop-ups, text pops, transitions).'}
        if data['fx']['safe_zone'] is None:
            data['fx'].pop('safe_zone')
    # hook
    approaches = []
    if V('hook_question'):
        approaches.append('question')
    if V('hook_number'):
        approaches.append('number')
    approaches += [a for a in ('result_first', 'stakes', 'quote', 'mid_action') if a not in approaches]
    data['hook'] = {'max_s': 3.0 if kind == 'short' else 15.0, 'approaches': approaches,
                    'text': {'max_words': 6, 'case': 'upper' if V('caption_case') == 'ALL CAPS' else 'as_said'},
                    'rules': hook_rules(merged), 'avoid': ['greetings', 'logo cards'] if V('hook_talks_at_once') else []}
    # shots, b-roll, signature
    data['shots'] = {'framing': {'close-up': 'close', 'medium close-up': 'close', 'medium': 'medium',
                                 'wide': 'wide'}.get(V('framing') or '', 'medium'),
                     'punch_ins': 'lots' if (V('punches_per_min', 0) or 0) >= 4 else
                     'some' if (V('punches_per_min', 0) or 0) >= 1 else 'none'}
    cs = V('broll_share')
    if cs is not None:
        data['broll'] = {'amount': 'lots' if cs >= 0.35 else 'some' if cs >= 0.1 else 'little'}
    touches = []
    if V('ending_cta'):
        touches.append('ends on a call to action')
    if V('ending_loops'):
        touches.append('the ending runs back into the start (a loop)')
    if V('watermark'):
        touches.append('a handle or logo stays on screen')
    if touches:
        data['signature'] = {'touches': touches}
    data['measured'] = measured(merged)
    data['provenance'] = {'sources': [{'path': v['file'], 'title': Path(v['file']).stem, 'duration_s': v['duration_s'],
                                       'measured': _source_numbers(merged, i)} for i, v in enumerate(merged['videos'])],
                          'measured': merged['made'][:10], 'tool': TOOL,
                          'notes': ('Draft made from the measurements; recipe.md is written in our own words from the '
                                    'numbers, not copied from anywhere. ' + (f'Notes given: {notes.strip()[:400]}'
                                                                            if notes else ''))}
    data['taste'] = ', '.join(tags)[:120]
    recipe = recipe_md(merged, label, kind, data, recipe_fx, notes)
    return {'data': data, 'recipe_md': recipe, 'assets': assets}


def _lum(hx):
    r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def presets(merged, smap):
    """Effect presets for what the references do, each with when / where rules from the measurements. Returns
    (effects, lines for the recipe)."""
    V = lambda k, d=None: _v(merged, k, d)  # noqa: E731
    fx, lines = {}, []
    ppm = V('punches_per_min', 0) or 0
    if ppm >= 0.5:
        scale = V('punch_scale') or 1.15
        fx['punch_in'] = {'kind': 'zoom_punch', 'about': 'A quick push-in that holds to the next cut, as the '
                                                         'references do on stressed words and jump cuts.',
                          'scale': round(max(1.04, min(1.5, scale)), 2), 'ramp_s': 0.06,
                          'rules': {'triggers': ['emphasis', 'cut', 'punchline'],
                                    'density': {'per_min': int(math.ceil(ppm * 1.25)),
                                                'min_gap_s': round(max(1.0, 60 / max(ppm, 1e-6) * 0.4), 1)},
                                    'when': f'About {round(ppm, 1)} a minute in the references, at {round(scale, 2)}x; '
                                            'mostly where a jump cut would show, alternating zoomed and not.'}}
        lines.append(('punch_in', f'zoom punches, {round(ppm, 1)} a minute at {round(scale, 2)}x'))
    opm = V('overlays_per_min', 0) or 0
    if opm >= 0.5:
        trig = V('overlay_triggers') or {}
        tlist = []
        for k in trig:
            m = TRIGGER_MAP.get(k)
            if m and m not in tlist:
                tlist.append(m)
        tlist = tlist[:4] or ['mention']
        zone = V('overlay_zone')
        from_face = V('overlay_from_face') or ''
        placement = {'zone': 'opposite_face' if 'beside' in from_face else ZONE_POS.get(zone, 'upper_right'),
                     'avoid': ['face', 'captions', 'covered']}
        hold = V('overlay_len_s') or 1.2
        size = V('overlay_size') or 0.26
        entry, exit_ = V('overlay_entry'), V('overlay_exit')
        fx['thing_pop'] = {'kind': 'popup', 'about': 'A picture, emoji or icon of what is being said pops up, as in '
                                                     'the references.',
                           'size': round(max(0.12, min(0.6, size)), 2),
                           # measured slides and scales are taken; a measured cut or fade is the least sure reading
                           # (the footage changing behind at the same moment), so those keep the pop
                           'in': ANIM_IN[entry] if entry in ('scale', 'slide') else 'pop',
                           'out': ANIM_OUT[exit_] if exit_ in ('scale', 'slide') else 'shrink',
                           'hold_s': round(max(0.5, min(4.0, hold)), 1),
                           'rules': {'triggers': tlist,
                                     'density': {'per_min': int(math.ceil(opm * 1.25)),
                                                 'min_gap_s': round(max(1.0, 60 / max(opm, 1e-6) * 0.4), 1)},
                                     'placement': placement,
                                     'duration_s': [round(max(0.4, hold * 0.6), 1), round(hold * 1.6, 1)],
                                     'never': ['over_face', 'over_captions'],
                                     'when': f'In the references about {round(opm, 1)} a minute, '
                                             f'{_trig_words(trig)}; {(zone or "beside the speaker").replace("_", " ")}, about '
                                             f'{round(size * 100)}% of the frame\'s short side, on for '
                                             f'{round(hold, 1)} s.'}}
        if 'pop' in smap and (V('overlay_with_sfx', 0) or 0) >= 0.3:
            fx['thing_pop']['sfx'] = 'pop'
        lines.append(('thing_pop', f'pop-ups, {round(opm, 1)} a minute, {_trig_words(trig)}'))
    tpm = V('text_pops_per_min', 0) or 0
    if tpm >= 0.5:
        trig = V('text_pop_triggers') or {}
        tlist = []
        for k in trig:
            m = TRIGGER_MAP.get(k)
            if m and m not in tlist:
                tlist.append(m)
        tlist = tlist[:4] or ['emphasis']
        zone = V('text_pop_zone')
        fx['text_pop'] = {'kind': 'text_pop', 'about': 'A short word or phrase on screen, apart from the captions.',
                          'size': 0.5, 'fill': 'secondary' if V('caption_highlight') else 'light', 'hold_s': 1.2,
                          'rules': {'triggers': tlist,
                                    'density': {'per_min': int(math.ceil(tpm * 1.25)),
                                                'min_gap_s': round(max(1.0, 60 / max(tpm, 1e-6) * 0.4), 1)},
                                    'placement': {'zone': ZONE_POS.get(zone, 'top') if zone else 'above_captions',
                                                  'avoid': ['face', 'captions', 'covered']},
                                    'never': ['over_face'],
                                    'when': f'{round(tpm, 1)} a minute in the references, {_trig_words(trig)}.'}}
        if 'pop' in smap:
            fx['text_pop']['sfx'] = 'pop'
        lines.append(('text_pop', f'text pops, {round(tpm, 1)} a minute'))
    spm = V('shakes_per_min', 0) or 0
    if spm >= 0.5:
        fx['shake_hit'] = {'kind': 'shake', 'about': 'A short shake on a hit moment.', 'amount': 0.45, 'len': 0.3,
                           'rules': {'triggers': ['punchline', 'reveal', 'reaction'],
                                     'density': {'per_min': int(math.ceil(spm * 1.25)), 'min_gap_s': 5.0},
                                     'when': f'{round(spm, 1)} a minute in the references.'}}
        if 'thump' in smap:
            fx['shake_hit']['sfx'] = 'thump'
        lines.append(('shake_hit', f'shakes, {round(spm, 1)} a minute'))
    trk = V('transition_kinds') or []
    trpm = V('transitions_per_min', 0) or 0
    for k in trk:
        if k == 'flash':
            fx['flash_cut'] = {'kind': 'flash', 'about': 'A quick white flash over a cut.', 'color': 'light',
                               'len': 0.2, 'opacity': 0.8,
                               'rules': {'triggers': ['reveal', 'topic_change'],
                                         'density': {'per_min': max(1, int(math.ceil(trpm))), 'min_gap_s': 6.0}}}
            lines.append(('flash_cut', 'flash transitions'))
        elif k == 'glitch':
            fx['glitch_cut'] = {'kind': 'glitch', 'about': 'A short digital glitch on a cut.', 'amount': 0.6,
                                'len': 0.3, 'rules': {'triggers': ['topic_change', 'reveal'],
                                                      'density': {'per_min': max(1, int(math.ceil(trpm))),
                                                                  'min_gap_s': 6.0}}}
            lines.append(('glitch_cut', 'glitch transitions'))
        elif k in ('dissolve', 'fade_black', 'fade_white'):
            fx['soft_cut'] = {'kind': 'transition', 'about': 'A soft transition for a change of time or place.',
                              'transition': {'type': 'dissolve', 'len': 0.5},
                              'rules': {'triggers': ['topic_change'],
                                        'density': {'per_min': max(1, int(math.ceil(trpm))), 'min_gap_s': 8.0}}}
            lines.append(('soft_cut', f'{k.replace("_", " ")} transitions'))
        elif k in ('whip', 'zoom'):
            # no whip or zoom transition in the edit tools: a whoosh on the cut is the nearest ready device
            if 'whoosh' in smap:
                name = f'{k}_cut'
                fx[name] = {'kind': 'whoosh', 'about': f'A whoosh on the cut where the references {k} into the next shot.',
                            'sfx': 'whoosh', 'sfx_offset_s': -0.2,
                            'rules': {'triggers': ['cut', 'topic_change'],
                                      'density': {'per_min': max(1, int(math.ceil(trpm))), 'min_gap_s': 5.0},
                                      'when': f'The references {k} between some shots; letitedit has no {k} '
                                              'transition, so the cut carries a whoosh instead.'}}
                lines.append((name, f'{k} transitions (as a whoosh on the cut)'))
            else:
                lines.append((None, f'{k} transitions (letitedit has no ready {k} transition; plain cuts)'))
    if 'whoosh' in smap and (V('sfx_at_cuts', 0) or 0) >= 0.3 and not any(v['kind'] == 'whoosh' for v in fx.values()):
        fx['whoosh_cut'] = {'kind': 'whoosh', 'about': 'A whoosh landing on a cut.', 'sfx': 'whoosh',
                            'sfx_offset_s': -0.2,
                            'rules': {'triggers': ['cut', 'topic_change'],
                                      'density': {'per_min': max(1, int(math.ceil((V('sfx_per_min', 1) or 1)
                                                                                  * (V('sfx_at_cuts') or 0.3)))),
                                                  'min_gap_s': 4.0},
                                      'when': f"{round(100 * V('sfx_at_cuts'))}% of the sound effects in the "
                                              f"references land on a cut."}}
        lines.append(('whoosh_cut', 'whooshes on cuts'))
    ss = V('split_share', 0) or 0
    if ss >= 0.1:
        fit = 'right' if V('split_where') == 'left_right' else 'bottom'
        fx['split_screen'] = {'kind': 'broll', 'about': 'A second picture fills half the frame beside the first, as '
                                                        'the references do.', 'fit': fit, 'len': 3.0,
                              'rules': {'triggers': ['mention', 'list_item'], 'duration_s': [2.0, 6.0],
                                        'when': f'Split screens ({(V("split_where") or "top_bottom").replace("_", " / ")}) '
                                                f'cover {round(ss * 100)}% of the references\' time.'}}
        lines.append(('split_screen', f'split screens, {round(ss * 100)}% of the time'))
    cs = V('broll_share')
    if cs is not None and cs >= 0.08:
        fx['cutaway'] = {'kind': 'broll', 'about': 'A cutaway to what is being described while the voice goes on.',
                         'fit': 'cover', 'len': 1.8,
                         'rules': {'triggers': ['mention', 'list_item'], 'duration_s': [1.0, 3.5],
                                   'when': f'Cutaways cover {round(cs * 100)}% of the references\' time.'}}
        lines.append(('cutaway', f'cutaways, {round(cs * 100)}% of the time'))
    return fx, lines


def _trig_words(trig):
    if not trig:
        return 'with no clear trigger measured'
    tot = sum(trig.values())
    parts = [f'{round(100 * n / tot)}% {k}' for k, n in list(trig.items())[:3]]
    return 'when: ' + ', '.join(parts)


def hook_rules(merged):
    V = lambda k, d=None: _v(merged, k, d)  # noqa: E731
    bits = []
    if V('hook_talks_at_once'):
        bits.append('the speaker starts talking within the first half second')
    if V('hook_text_at_once'):
        bits.append('text is on screen in the first second')
    if V('hook_question'):
        bits.append('the first line is a question')
    if V('hook_number'):
        bits.append('the first line has a number in it')
    if (V('hook_moves', 0) or 0) >= 1:
        bits.append(f"the picture changes about {round(V('hook_moves'))} time(s) in the first seconds")
    if V('hook_sfx'):
        bits.append('a sound effect marks the start')
    if not bits:
        return 'The references open without a strong measured device; choose the opening by the content.'
    return 'In the references ' + '; '.join(bits) + '.'


def measured(merged):
    V = lambda k, d=None: _v(merged, k, d)  # noqa: E731
    F = merged['facts']

    def rng(key):
        f = F.get(key) or {}
        return f.get('spread') if isinstance(f.get('spread'), dict) else None
    out = {'references': merged['n'],
           'cuts_per_min': V('cuts_per_min'), 'cuts_per_min_range': rng('cuts_per_min'),
           'shot_len_s': {'median': V('shot_len_median_s'), 'p25': V('shot_len_p25_s'), 'p75': V('shot_len_p75_s')},
           'words_per_min': V('words_per_min'), 'speech_share': V('speech_share'),
           'effects_per_min': V('effects_per_min'), 'punches_per_min': V('punches_per_min'),
           'overlays_per_min': V('overlays_per_min'), 'text_pops_per_min': V('text_pops_per_min'),
           'sfx_per_min': V('sfx_per_min'), 'transitions_per_min': V('transitions_per_min'),
           'caption': {'chunking': V('caption_chunking'), 'words_per_caption': V('caption_words'),
                       'lines': V('caption_lines'), 'case': V('caption_case'), 'y': V('caption_y'),
                       'line_height_share': V('caption_line_h'), 'timing': V('caption_timing'),
                       'lead_s': V('caption_lead_s')} if V('captions') else None,
           'loudness_lufs': V('loudness_lufs'), 'music_share': V('music_share'), 'tempo_bpm': V('tempo_bpm'),
           'music_under_voice_db': V('music_under_voice_db'), 'ducking_db': V('ducking_db'),
           'cuts_on_beat': V('cuts_on_beat'), 'cuts_on_beat_chance': V('cuts_on_beat_chance'),
           'face_share': V('face_share'), 'cutaway_share': V('cutaway_share'),
           'look': {k: V(k) for k in ('brightness', 'contrast', 'saturation', 'warmth', 'grain')},
           'consistent': merged['consistent'], 'varies': merged['varies']}
    return _clean(out)


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items() if v is not None and v != {} and v != []}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _source_numbers(merged, i):
    out = {}
    for k in ('cuts_per_min', 'words_per_min', 'effects_per_min', 'punches_per_min', 'overlays_per_min',
              'sfx_per_min', 'loudness_lufs'):
        vals = (merged['facts'].get(k) or {}).get('values') or []
        if i < len(vals) and vals[i] is not None:
            out[k] = vals[i]
    return _clean(out)


def _recipe_structure(V, a, kind):
    """Structure: length, pace stretches, the talking head and b-roll shares, pace variation."""
    a('## Structure')
    secs = V('sections')
    a(f"- {('Shorts' if kind == 'short' else 'Long videos')} of about {round(V('duration_s', 0))} s; "
      f"{round(secs)} stretch(es) of different pace in a video." if secs else
      f"- About {round(V('duration_s', 0))} s long.")
    if V('talking_head'):
        a(f"- One person talks to camera ({V('framing') or 'medium'} framing, a face on screen "
          f"{round(100 * (V('face_share') or 0))}% of the time); face-absent samples cover "
          f"{round(100 * (V('cutaway_share') or 0))}% of the time (not semantic b-roll).")
    if V('broll_share') is not None:
        a(f"- Reviewed semantic b-roll covers {V('broll_share'):.1%} of runtime.")
    else:
        a('- Semantic b-roll share is unknown until the picture roles are reviewed.')
    pv = V('pace_variation')
    if pv is not None:
        a(f"- The pace {'changes a lot' if pv > 0.6 else 'shifts a little' if pv > 0.3 else 'stays even'} "
          f"through the video (variation {pv}).")


def _recipe_pacing(V, a, data):
    """Pacing: cuts a minute, shot lengths, jump cuts, pauses and speaking rate."""
    a('## Pacing')
    a(f"- {V('cuts_per_min')} cuts a minute; shots last {V('shot_len_median_s')} s in the middle "
      f"(half of them between {V('shot_len_p25_s')} and {V('shot_len_p75_s')} s).")
    if (V('jump_cut_share') or 0) >= 0.2:
        a(f"- {round(100 * V('jump_cut_share'))}% of the cuts are jump cuts within the same framing: pauses and "
          f"retakes are cut out rather than covered.")
    if V('pause_p90_s') is not None:
        a(f"- Pauses between phrases stay short: 9 in 10 are under {V('pause_p90_s')} s "
          f"(editing.max_pause {data.get('editing', {}).get('max_pause')}).")
    if V('words_per_min'):
        a(f"- Speech runs at about {round(V('words_per_min'))} words a minute while talking.")


def _recipe_captions(V, a):
    """Captions, when measured: chunking, place, look, the word being said, entry and fonts."""
    if V('captions'):
        a('')
        a('## Captions')
        a(f"- {V('caption_chunking') or 'Captions'}: {V('caption_words')} word(s) a caption on "
          f"{V('caption_lines')} line(s), {V('caption_case') or 'as said'}, timing {V('caption_timing')}.")
        a(f"- Sit in the {V('caption_zone')} (centre at {round(100 * (V('caption_y') or 0))}% of the height), text "
          f"about {round(100 * (V('caption_line_h') or 0), 1)}% of the frame height.")
        look = []
        if V('caption_fill'):
            look.append(f"fill {V('caption_fill')}")
        if V('caption_outline'):
            look.append(f"outline {V('caption_outline')} about {V('caption_outline_px')} px at full size")
        if V('caption_plate'):
            look.append(f"on a plate {V('caption_plate')}")
        if V('caption_shadow'):
            look.append('with a drop shadow')
        if V('caption_weight'):
            look.append(f"{V('caption_weight')} weight")
        if look:
            a('- Look: ' + ', '.join(look) + '.')
        if V('caption_highlight'):
            a(f"- The word being said is set apart ({V('caption_highlight_kind') or 'colour'} "
              f"{V('caption_highlight_color') or ''}).")
        if V('caption_entry'):
            a(f"- Each caption comes in with a {V('caption_entry')}"
              + (f" over about {round(V('caption_entry_ms'))} ms." if V('caption_entry_ms') and V('caption_entry') != 'cut'
                 else ' (all at once).' if V('caption_entry') == 'cut' else '.'))
        if V('caption_fonts'):
            a(f"- Nearest bundled fonts by letter shape: {', '.join(V('caption_fonts'))} (an estimate: compare the "
              f"caption crops in import/ before settling).")


def _recipe_effects(V, a, data, fx_lines):
    """Effects: each preset with its rule, then labels, rhythm, pop-up motion, insets, slow motion and cards."""
    a('## Effects: when and where')
    if fx_lines:
        for name, line in fx_lines:
            if name is None:
                a(f'- {line}.')
                continue
            rule = ((data.get('effects') or {}).get(name) or {}).get('rules', {}).get('when')
            a(f"- `{name}`: {line}." + (f' {rule}' if rule else ''))
    else:
        a('- No ready effect presets were established; this does not prove the reference has no effects.')
    if (V('labels_per_min') or 0) > 0:
        a(f"- Labels that stay on screen through a section: {round(V('labels_per_min'), 1)} a minute (titles of the "
          f"steps or chapters).")
    if data.get('fx', {}).get('rhythm'):
        a(f"- Rhythm: {data['fx']['rhythm']}")
    if V('overlay_entry') in ANIM_IN or V('overlay_exit') in ANIM_OUT:
        a(f"- Pop-ups come in with a {V('overlay_entry') or 'cut'} and go with a {V('overlay_exit') or 'cut'} "
          f"(measured frame by frame around each one; the least sure part of the pop-up measurements: look at "
          f"overlays.png).")
    if (V('inset_share') or 0) >= 0.05:
        a(f"- A second picture sits in a corner (picture-in-picture) for {round(100 * V('inset_share'))}% of the time.")
    if (V('slow_motion_share') or 0) >= 0.03:
        a(f"- Slow motion on {round(100 * V('slow_motion_share'))}% of the time.")
    if (V('camera_moves_per_min') or 0) >= 1:
        a(f"- The camera itself moves toward or away from things about {round(V('camera_moves_per_min'))} times a "
          f"minute (handheld or travelling shots): that is the footage, not zooms added in the edit.")
    if V('cards'):
        a('- Full-screen title or end cards are used (their text is listed with each reference, not counted as '
          'pop-ups).')


def _recipe_sound(V, a, data):
    """Sound: measured effects, music and its beat, and the finished loudness."""
    a('## Sound')
    if V('sfx_per_min'):
        kinds = V('sfx_kinds') or {}
        a(f"- Measured: {V('sfx_per_min')} sound effects a minute "
          f"({', '.join(f'{k} {c}' for k, c in kinds.items()) or 'unsorted'}); "
          f"{round(100 * (V('sfx_at_cuts') or 0))}% on cuts, {round(100 * (V('sfx_at_overlays') or 0))}% with pop-ups. "
          + ('Every reference has them, so the style carries stand-in sounds for those kinds.'
             if data.get('sfx') else
             'Not carried into the style: sound effects are the least reliable measurement here (listen to the '
             'references around the pop-ups and cuts, and add them by hand if they are part of the style).'))
    else:
        a('- No sound effects measured (they can be missed under music: listen to the references to be sure).')
    if (V('music_share') or 0) >= 0.3:
        bq = {'clear': 'a clear beat', 'weak': 'a weak beat', 'none': 'no clear beat'}.get(V('beat_quality'), 'beat ?')
        a(f"- Music on {round(100 * V('music_share'))}% of the time"
          + (f", about {round(V('tempo_bpm'))} BPM ({bq})" if V('tempo_bpm') else '')
          + (f", {abs(round(V('music_under_voice_db')))} dB under the voice" if V('music_under_voice_db') is not None else '')
          + (f", up {round(V('ducking_db'))} dB in the pauses" if (V('ducking_db') or 0) >= 3 else '') + '.')
        if V('cuts_on_beat') is not None:
            a(f"- Cuts on the beat: {round(100 * V('cuts_on_beat'))}% (chance would give "
              f"{round(100 * (V('cuts_on_beat_chance') or 0))}%): "
              + ('cut to the music.' if V('cuts_on_beat') > 1.5 * (V('cuts_on_beat_chance') or 1) else
                 'the cuts follow the words, not the beat.'))
    else:
        a('- Little or no music.')
    if V('loudness_lufs') is not None:
        a(f"- Finished at {V('loudness_lufs')} LUFS.")


def recipe_md(merged, label, kind, data, fx_lines, notes=''):
    """recipe.md: the findings in our own words, with the measured numbers."""
    V = lambda k, d=None: _v(merged, k, d)  # noqa: E731
    n = merged['n']
    L = []
    a = L.append
    a(f'# {label}: the recipe')
    a('')
    a(f"A draft imported from {n} reference video{'s' if n != 1 else ''} ({', '.join(v['name'] for v in merged['videos'])}) "
      f"by measuring them frame by frame. Every number below was measured; the wording is ours. "
      + ('With one reference nothing can be told apart as style rather than content: treat each habit as a guess until '
         'a second example agrees.' if n == 1 else
         'Habits all the references share are written as the style; what only some do is listed under "Varies".'))
    if notes:
        a('')
        a(f'What the person likes about them (their notes): {notes.strip()[:600]}')
    a('')
    _recipe_structure(V, a, kind)
    a('')
    _recipe_pacing(V, a, data)
    a('')
    a('## Hook')
    a(f"- {data['hook']['rules']}")
    hs = [x for x in (merged['facts'].get('hook_said') or {}).get('values') or [] if x]
    if hs:
        a('- First lines heard (content, for reference only): ' + '; '.join(f'"{h[:80]}"' for h in hs[:3]) + '.')
    _recipe_captions(V, a)
    a('')
    _recipe_effects(V, a, data, fx_lines)
    a('')
    _recipe_sound(V, a, data)
    a('')
    a('## Look')
    a(f"- {V('contrast') or 'medium'} contrast, {V('saturation') or 'natural'} colour, {V('warmth') or 'neutral'}; grain "
      f"{V('grain') or 'n/a'}" + ('; letterbox bars' if V('letterbox') else '') + ('; a blurred copy fills the bars'
                                                                                    if V('blurred_bands') else '') + '.')
    a('')
    a('## Ending')
    if V('ending_cta'):
        a(f"- Ends on a call to action ({', '.join(V('ending_cta_words') or [])}).")
    if V('ending_loops'):
        a('- The ending loops back into the start.')
    if not V('ending_cta') and not V('ending_loops'):
        a('- Ends on the content itself: no call to action and no loop measured.')
    if merged['varies']:
        a('')
        a('## Varies between the references (not part of the style)')
        a('- ' + ', '.join(merged['varies']))
    a('')
    a('## Limits of this draft')
    a('- Pop-ups: text laid on top (labels, titles, word stickers) is found reliably; pictures, emoji and animated '
      'stickers are found less often (a 3D emoji or a photo looks like the footage), and how each comes in and goes '
      'is the least sure part. Zoom punches and push-ins are told from a moving camera, but a push-in on footage that '
      'itself moves hard is missed. Split screens are listed as unsure (a still camera with movement below a straight '
      'edge looks the same); speed holds and reverse replays need picture evidence; cadence and motion changes '
      'alone remain unsure, not slow motion. Fonts are the nearest '
      'of the bundled ones by shape. Look at the pictures in import/ before relying on any of it.')
    a('- Sound effects: found as sharp sounds that sound unlike the music around them; on real videos with music '
      'most are still missed: check them by ear. Sounds in assets/ (when there are any) are letitedit\'s own '
      'generated stand-ins for the kinds heard, not the references\' sounds.')
    if merged.get('visual') is not None:
        from letitedit.looks.style_import_visual import recipe as visual_recipe
        a('')
        a(visual_recipe(merged['visual']))
    return '\n'.join(L) + '\n'


def _legacy_write(merged, name, kind='short', notes='', label=None, overwrite=False, reports=(), style_root=None):
    """Write the draft style pack (style_pack.create) plus import/ (merged facts, each report and its pictures).
    style_root: destination, defaulting to the person's My Looks/.imports, outside the library. Returns create()'s result plus
    'import_folder'."""
    import letitedit.looks.style_pack as style_pack
    if style_root is None:
        import letitedit.looks.learned_looks as learned_looks
        style_root = learned_looks.root() / '.imports'
    style_root = Path(style_root)
    d = draft(merged, name, kind, notes, label)
    data = d['data']
    probs = style_pack.validate({**data, 'format': style_pack.FORMAT})
    dropped = []
    if probs:
        # drop the effect presets the validator refuses, keep the rest of the style
        for key in list((data.get('effects') or {})):
            if any(f'effects.{key}' in pbl for pbl in probs):
                dropped.append(key)
                data['effects'].pop(key)
        probs = style_pack.validate({**data, 'format': style_pack.FORMAT})
    dropped_fields = []
    if probs:
        # any other field the format refuses is left out (named in the result) rather than losing the whole draft
        keep = {'name', 'label', 'kind', 'format', 'recipe', 'description', 'summary', 'tags'}
        for pbl in probs:
            key = re.split(r'[.:\s\[]', str(pbl).strip(), 1)[0]
            if key in data and key not in keep:
                data.pop(key)
                dropped_fields.append(key)
        probs = style_pack.validate({**data, 'format': style_pack.FORMAT})
    if probs:
        raise ValueError('the draft style does not validate: ' + ' | '.join(probs))
    res = style_pack._legacy_create(name, data, recipe_md=d['recipe_md'], assets=d['assets'], overwrite=overwrite,
                            root=style_root)
    res['dropped_fields'] = dropped_fields
    if merged.get('visual') is not None:
        (style_root / name / 'visual.json').write_text(
            json.dumps(merged['visual'], indent=2, allow_nan=False), encoding='utf-8')
    folder = style_root / name / 'import'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'merged.json').write_text(json.dumps(merged, indent=1, default=str), encoding='utf-8')
    for k, r in enumerate(reports):
        safe = re.sub(r'[^\w.-]+', '_', ref_names(reports)[k])[:56]
        sub = folder / f'{k + 1:02d}-{safe}'
        sub.mkdir(parents=True, exist_ok=True)
        src = Path(r['folder'])
        for fname in ('report.json', 'breakdown.md', 'timeline.png', 'hook.png', 'ending.png', 'overlays.png',
                      'transitions.png', 'captions.png', 'step-errors.log'):
            if (src / fname).exists():
                shutil.copy2(src / fname, sub / fname)
    res['import_folder'] = str(folder)
    res['dropped_presets'] = dropped
    return res
