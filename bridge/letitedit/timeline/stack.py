"""What is in front of what: a timeline's layers at a moment, back to front, from the script and the project's blends.

Read only. `comment` is the one line `edit_script.to_yaml` adds; `view` is what letitedit_timeline_read(stack_at=...) and
letitedit_check_frames(stack=True) show; `blend_notes` is what an edit says about a blend effect that can't work where it is.
"""
from __future__ import annotations

from pathlib import Path

from letitedit.timeline.edit_sync import layout, to_seconds

BLEND_SERVICES = ('frei0r.cairoblend', 'qtblend', 'movit.overlay')
CAIRO_EFFECTS = ('cairoblend_mode', 'blend_mode')
QT_EFFECTS = ('qtblend_mode', 'blend_mode_qtblend')
AUDIO_WORDS = ('mute', 'gain', 'fade_in_audio', 'fade_out_audio', 'split_mute', 'loudness', 'limiter')
MASK_START, MASK_APPLY = 'mask_start', 'mask_apply'
ALPHA_FILES = ('.png', '.webp', '.gif', '.tga', '.svg')
UNKNOWN_ALPHA_FILES = ('.mov', '.webm', '.mkv')      # most are solid (a phone's .MOV), and only reading the file would tell
QT_MODES = {12: 'plus', 13: 'multiply', 14: 'screen', 15: 'overlay', 16: 'darken', 17: 'lighten', 18: 'colour dodge',
            19: 'colour burn', 20: 'hard light', 21: 'soft light', 22: 'difference', 23: 'exclusion'}


def _video(script):
    return [t for t in script['tracks'] if t.get('kind', 'video') == 'video']


def _hidden(track):
    return track.get('hide') in ('video', 'both')


def comment(script):
    """One YAML comment line, or '' for a timeline with one picture track or a partial read."""
    video = _video(script)
    if script.get('partial') or len(video) < 2:
        return ''
    names = ' < '.join(str(t['name']).replace('\n', ' ') + (' (hidden)' if _hidden(t) else '') for t in video)
    captions = '; captions on top' if any(c.get('burn_in', True) for c in script.get('captions') or []) else ''
    return f'# Stack, back to front: {names}{captions}\n'


def track_blends(doc):
    """{track name: {'service', 'mode'}} for the picture tracks in a project: which engine blends each one and any blend
    mode set on the whole track (in the app's track properties)."""
    from letitedit.timeline.edit_script import _get
    rows = list(doc.main.findall('track'))
    out = {}
    for tr, pl, name, kind in doc.tracks():
        if kind != 'video':
            continue
        index = rows.index(tr)
        for t in doc.main.findall('transition'):
            if _get(t, 'mlt_service') in BLEND_SERVICES and str(_get(t, 'b_track')) == str(index):
                service = _get(t, 'mlt_service')
                raw = _get(t, '1') if service == 'frei0r.cairoblend' else _get(t, 'compositing')
                out[name] = {'service': service, 'mode': None if raw in (None, '', 'normal', '0') else raw}
                break
    return out


def _word(effect):
    if isinstance(effect, str):
        return effect
    if not isinstance(effect, dict):
        return None
    if effect.get('filter'):
        return str(effect['filter'])
    return next(iter(effect), None)


def _is_audio(effect):
    word = _word(effect)
    if word in AUDIO_WORDS:
        return True
    if isinstance(effect, dict) and effect.get('filter'):
        try:
            import letitedit.timeline.edit_effects as ee
            return ee.resolve(effect['filter']).get('kind') == 'audio'
        except Exception:  # noqa: BLE001 - an effect the catalog doesn't know is shown, not hidden
            return False
    return False


def _range(effect, fps):
    params = effect.get('params') if isinstance(effect, dict) else None
    if not isinstance(params, dict) or 'in' not in params or 'out' not in params:
        return None
    try:
        return float(params['in']) / fps, (float(params['out']) + 1) / fps
    except (TypeError, ValueError):
        return None


def _names(effects, where, fps, t=None):
    """Picture effects as short phrases: the ones a time range leaves out at t are skipped, a mask's trio is one phrase."""
    out, inside = [], False
    for e in effects or []:
        word = _word(e)
        if word is None or _is_audio(e) or word in CAIRO_EFFECTS + QT_EFFECTS or word == 'size_position':
            continue
        if word == MASK_START:
            inside = True
            continue
        if word == MASK_APPLY:
            inside = False
            continue
        span = _range(e, fps)
        if span and t is not None and not (span[0] - 1e-6 <= t < span[1]):
            continue
        extra = [where] if where else []
        if inside:
            extra.append('in a shape')
        if span:
            extra.append(f'{span[0]:.2f}-{span[1]:.2f} s')
        out.append(word + (f" ({', '.join(extra)})" if extra else ''))
    return out


def _first_line(text, limit=32):
    line = ' '.join(str(text).split())
    return line[:limit] + ('...' if len(line) > limit else '')


def _ass_words(ass):
    for line in str(ass).splitlines():
        if line.startswith('Dialogue:'):
            return _first_line(line.split(',', 9)[-1].split('}')[-1])
    return ''


def _vfx_output(name):
    try:
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.EFFECTS[name]['output']
    except Exception:  # noqa: BLE001
        return 'replace'


def _describe(item, start, t):
    """(what it shows, how the things below show through)."""
    speed = float(item.get('speed') or 1.0)
    if item.get('adjust'):
        name = item.get('name') or 'Adjustment layer'
        return f'adjustment layer "{name}"', 'changes everything below it, nothing above'
    if item.get('scene'):
        scene = item['scene']
        name = item.get('name') or scene.get('id')
        return f'code scene "{name}" rev {str(scene.get("revision"))[:6]}', "alpha: its own, letitedit_code_scene look shows what it covers"
    if item.get('vfx'):
        vfx = item['vfx']
        src = vfx.get('source') or {}
        file = Path(str(src.get('clip'))).name if src.get('clip') else ''
        at = f' at {float(src.get("in") or 0) + (t - start) * float(src.get("speed") or 1):.2f} s' if file else ''
        if vfx.get('effect') == 'cutout':
            return f'cut-out of {file}{at}', 'alpha: person matte'
        if vfx.get('effect') == 'object':
            return f'object layer of {file}{at}', 'alpha: the object'
        kind = _vfx_output(vfx.get('effect'))
        return f'{vfx.get("effect")} effect{" of " + file + at if file else ""}', 'alpha: its own' if kind == 'overlay' else 'full frame'
    if item.get('clip'):
        file = Path(str(item['clip'])).name
        at = to_seconds(item.get('in') or 0) + (t - start) * speed
        suffix = Path(file).suffix.lower()
        alpha = "alpha: the file's own, if it has one" if suffix in ALPHA_FILES else '' if suffix in UNKNOWN_ALPHA_FILES else 'solid'
        return f'{file} at {at:.2f} s', alpha
    if item.get('color') is not None:
        colour = str(item['color'])
        clear = colour.startswith('#') and len(colour) == 9 and colour[1:3] == '00'
        return f'colour {colour}', 'transparent' if clear else 'solid'
    if item.get('ass'):
        return f'text "{_ass_words(item["ass"])}"', 'alpha: text'
    if item.get('graphic'):
        return f'graphic {item["graphic"].get("template") or "custom"}', 'alpha: its own'
    if item.get('motion'):
        return f'motion {item["motion"].get("block")}', 'alpha: its own'
    if item.get('freeze'):
        return f'freeze of {Path(str(item["freeze"].get("clip"))).name}', 'solid'
    for key in ('ffmpeg', 'render3d', 'map', 'raw'):
        if item.get(key) is not None:
            return f'made clip ({key})', 'alpha: its own, if it has one'
    return 'item ' + str(item.get('id') or ''), ''


def _size(effects, width, height):
    for e in effects or []:
        if isinstance(e, dict) and 'size_position' in e:
            value = e['size_position']
            if isinstance(value, dict):
                return 'moving size and position'
            try:
                vals = [float(x) for x in (value.split() if isinstance(value, str) else value)]
                share = round(100 * vals[2] * vals[3] / max(1, width * height))
                return f'at {vals[0]:g} {vals[1]:g}, {vals[2]:g} x {vals[3]:g} ({share}% of the frame)'
            except (TypeError, ValueError, IndexError):
                return 'its own size and position'
    return None


def _item_blend(effects):
    """The blend effect on an item: (effect name, mode) or None."""
    for e in effects or []:
        if isinstance(e, dict) and e.get('filter') in CAIRO_EFFECTS + QT_EFFECTS:
            params = e.get('params')
            return e['filter'], (params.get('mode') if isinstance(params, dict) else None)
    return None


def _blend_problem(track_name, first_video, service, effect, mode):
    """A plain sentence when this blend effect can't do anything where it is, else None."""
    if track_name == first_video:
        return f'{track_name}: a blend effect does nothing on the first video track, which has nothing below it'
    if service is None:
        return None
    qt = service == 'qtblend'
    if effect in CAIRO_EFFECTS and service != 'frei0r.cairoblend':
        return (f'{track_name}: {effect} does nothing on this track, which blends with {service}'
                + ('; use qtblend_mode, whose mode is a number: 13 multiply, 14 screen, 15 overlay' if qt else ''))
    if effect in QT_EFFECTS and service != 'qtblend':
        return (f'{track_name}: {effect} does nothing on this track, which blends with {service}'
                + ('; use cairoblend_mode, whose mode is a name: multiply, screen, overlay' if service == 'frei0r.cairoblend' else ''))
    if effect in QT_EFFECTS and not str(mode).lstrip('-').isdigit():
        return f'{track_name}: qtblend_mode takes a number, not {mode!r}: 13 multiply, 14 screen, 15 overlay'
    if effect in CAIRO_EFFECTS and str(mode).lstrip('-').isdigit():
        return f'{track_name}: {effect} takes a name, not {mode!r}: multiply, screen, overlay'
    return None


def blend_notes(script, doc):
    """Sentences for blend effects that do nothing where they are; one per track and effect."""
    video = _video(script)
    if not video:
        return []
    blends = track_blends(doc)
    notes = []
    for t in video:
        for item in t['items']:
            found = _item_blend(item.get('effects'))
            if found:
                problem = _blend_problem(t['name'], video[0]['name'], (blends.get(t['name']) or {}).get('service'), *found)
                if problem and problem not in notes:
                    notes.append(problem)
    return notes


def _track_mode(blend):
    mode = (blend or {}).get('mode')
    if mode is None:
        return None
    if str(mode).isdigit():
        return QT_MODES.get(int(mode), f'mode {mode}')
    return str(mode)


def layers_at(script, t, blends=None):
    """{'time', 'layers': [back to front], 'whole', 'captions', 'warnings'} at timeline second t."""
    profile = script.get('profile') or {}
    fps = float(profile.get('fps') or 30)
    width, height = int(profile.get('width') or 1920), int(profile.get('height') or 1080)
    blends = blends or {}
    video = _video(script)
    layers, warnings = [], []
    for track in video:
        found = next(((i, s) for i, s, e in layout(track) if s - 1e-6 <= t < e - 1e-6), None)
        if found is None:
            continue
        item, start = found
        shows, alpha = _describe(item, start, t)
        row = {'track': track['name'], 'id': item.get('id'), 'shows': shows, 'alpha': alpha, 'item': item, 'start': start}
        size = _size(item.get('effects'), width, height)
        if size:
            row['size'] = size
        blend = _item_blend(item.get('effects'))
        if blend:
            row['blend'] = str(blend[1])
            problem = _blend_problem(track['name'], video[0]['name'], (blends.get(track['name']) or {}).get('service'), *blend)
            if problem:
                warnings.append(problem)
        whole_track = _track_mode(blends.get(track['name']))
        if whole_track and 'blend' not in row:
            row['blend'] = f'{whole_track} (set on the whole track)'
        effects = (_names(item.get('effects'), '' if item.get('adjust') else 'clip', fps, t)
                   + _names(track.get('effects'), f'track {track["name"]}', fps, t))
        if effects:
            row['effects'] = effects
        if _hidden(track):
            row['hidden'] = True
        layers.append(row)
    shown = [r for r in layers if not r.get('hidden')]
    for i, row in enumerate(shown):
        if row['item'].get('scene') and i > 0 and not any((r['item'].get('vfx') or {}).get('effect') in ('cutout', 'object') for r in shown[i + 1:]):
            warnings.append(f'{row["track"]}: a scene with no cut-out above it covers the footage wherever it is not transparent; '
                            'a {vfx: cutout} on a track above it keeps the person in front')
    for i, row in enumerate(shown):
        if row['item'].get('adjust'):
            if i == 0:
                warnings.append(f'{row["track"]}: this adjustment layer has nothing below it here, so it changes nothing')
            if any(r['item'].get('scene') for r in shown[:i]):
                warnings.append(f'{row["track"]}: a code scene is below this adjustment layer. The export and letitedit_code_scene look '
                                'show the effect on the scene; the live player draws the scene over the picture, so it shows the '
                                'scene without it')
    warnings += _out_of_step(shown, t, fps)
    whole = _names([e for e in script.get('master') or []], '', fps, t)
    said = None
    for cap in script.get('captions') or []:
        if cap.get('burn_in', True):
            cue = next((q for q in cap.get('cues') or [] if to_seconds(q['start']) - 1e-6 <= t < to_seconds(q['end'])), None)
            if cue:
                said = {'track': cap.get('track'), 'text': _first_line(cue.get('text', ''))}
    return {'time': round(t, 3), 'layers': layers, 'whole': whole, 'captions': said, 'warnings': warnings}


def _out_of_step(shown, t, fps):
    """A cut-out of the same file as the footage below it, showing another moment of that file."""
    out = []
    if not shown or not shown[0]['item'].get('clip'):
        return out
    base = shown[0]
    speed = float(base['item'].get('speed') or 1.0)
    base_at = to_seconds(base['item'].get('in') or 0) + (t - base['start']) * speed
    for row in shown[1:]:
        vfx = row['item'].get('vfx') or {}
        src = vfx.get('source') or {}
        if vfx.get('effect') != 'cutout' or not src.get('clip'):
            continue
        if Path(str(src['clip'])).resolve() != Path(str(base['item']['clip'])).resolve():
            continue
        at = float(src.get('in') or 0) + to_seconds(row['item'].get('skip') or 0) + (t - row['start']) * float(src.get('speed') or 1.0)
        if abs(at - base_at) > 1.5 / fps:
            out.append(f'{row["track"]}: the cut-out shows {at:.2f} s of {Path(str(src["clip"])).name} over the footage at {base_at:.2f} s, '
                       f'so the person is out of step by {abs(at - base_at):.2f} s')
    return out


def block(script, t, blends=None):
    """The stack at a moment as plain text."""
    data = layers_at(script, t, blends)
    lines = [f'{t:.2f} s, back to front:']
    if not data['layers']:
        lines.append('nothing on a video track')
    for n, row in enumerate(data['layers'], 1):
        parts = [row['shows']]
        if row.get('size'):
            parts.append(row['size'])
        if row.get('alpha'):
            parts.append(row['alpha'])
        if row.get('blend'):
            parts.append(f'blend: {row["blend"]}')
        if row.get('effects'):
            parts.append('effects: ' + ', '.join(row['effects']))
        if row.get('hidden'):
            parts.append('HIDDEN')
        lines.append(f'{n} {row["track"]}: ' + '; '.join(parts))
    tail = []
    if data['whole']:
        tail.append('whole video: ' + ', '.join(data['whole']))
    if data['captions']:
        tail.append(f'captions last, drawn over everything and untouched by whole-video effects: "{data["captions"]["text"]}"')
    if tail:
        lines.append('Then ' + '. Then '.join(tail) + '.')
    lines += [f'warning: {w}' for w in data['warnings']]
    return '\n'.join(lines)


def _changes_in(script, a, b):
    """Times in (a, b) where a layer starts or ends."""
    fps = float((script.get('profile') or {}).get('fps') or 30)
    times = {a}
    for track in _video(script):
        for _, s, e in layout(track):
            for x in (s, e):
                if a + 1e-6 < x < b - 1e-6:
                    times.add(x)
        for e in track.get('effects') or []:
            times |= _range_edges(e, fps, a, b)
    for e in script.get('master') or []:
        times |= _range_edges(e, fps, a, b)
    return sorted(times)


def _range_edges(effect, fps, a, b):
    span = _range(effect, fps)
    return {x for x in (span or ()) if a + 1e-6 < x < b - 1e-6}


def view(script, doc, stack_at, limit=12):
    """Plain text for a time (one block) or a [start, end] range (one block per change, at most `limit`)."""
    blends = track_blends(doc)
    if isinstance(stack_at, (list, tuple)):
        if len(stack_at) == 1:
            return block(script, float(stack_at[0]), blends)
        if len(stack_at) != 2:
            raise ValueError('stack_at is a time in seconds, or [start, end]')
        a, b = float(stack_at[0]), float(stack_at[1])
        if b <= a:
            raise ValueError('stack_at: the end comes before the start')
        times = _changes_in(script, a, b)
        text = '\n\n'.join(block(script, x, blends) for x in times[:limit])
        if len(times) > limit:
            text += f'\n\n{len(times) - limit} more changes before {b:.2f} s: ask for a shorter range from {times[limit]:.2f} s.'
        return text
    return block(script, float(stack_at), blends)
