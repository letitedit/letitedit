"""Reviewed base-picture provenance, separate overlays and production routes."""
from __future__ import annotations

import copy
import html
import json
import math
from pathlib import Path

from vendor.rea_video.sources import LABELS, group_of

FORMAT = 'letitedit-shot-sources/1'
OVERLAYS = ('caption', 'sticker', 'pip', 'sound_effect')
ROUTES = {'live_action': 'film_or_licensed_stock', 'generated': 'generate',
          'three_d': 'render_3d', 'code': 'render_code', 'animation': 'animate',
          'screen_capture': 'record_screen',
          'still_motion': 'image', 'static_hold': 'image', 'unknown': 'review'}


def number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite and nonnegative')
    return float(value)


def interval(entry, duration):
    start, end = (number(entry.get(key), key) for key in ('start_s', 'end_s'))
    if not 0 <= start < end <= duration:
        raise ValueError('source interval must lie inside its reference')
    return start, end


def validate(profile, reports=None):
    profile = copy.deepcopy(profile)
    if not isinstance(profile, dict) or profile.get('format') != FORMAT:
        raise ValueError('invalid shot-source profile format')
    references = profile.get('references')
    if not isinstance(references, list) or not 1 <= len(references) <= 3:
        raise ValueError('shot sources need one to three references')
    if reports is not None and len(references) != len(reports):
        raise ValueError('shot-source references must match importer reports')
    for index, source in enumerate(references):
        if not isinstance(source, dict):
            raise ValueError('each source must be an object')
        duration = number(source.get('duration_s'), 'duration_s')
        if duration <= 0 or not isinstance(source.get('file'), str) or not source['file']:
            raise ValueError('source needs file and positive duration_s')
        if reports is not None:
            report = reports[index]
            if (Path(source['file']).resolve() != Path(report['file']).resolve()
                    or abs(duration - report['duration_s']) > .001):
                raise ValueError('shot-source identity and duration must match importer report')
        segments = source.get('segments')
        if not isinstance(segments, list) or not segments:
            raise ValueError('source needs a complete base-picture inventory')
        cursor = 0.
        for entry in segments:
            if not isinstance(entry, dict):
                raise ValueError('each base-picture interval must be an object')
            start, end = interval(entry, duration)
            if abs(start - cursor) > .001:
                raise ValueError('base-picture intervals must cover the reference without gaps or overlaps')
            cursor = end
            if entry.get('kind') not in LABELS:
                raise ValueError('unknown base-picture kind')
            status = entry.get('status')
            if status not in ('reviewed', 'unknown') or (entry['kind'] == 'unknown') != (status == 'unknown'):
                raise ValueError('known source kinds require reviewed evidence; unknown stays unknown')
            if not isinstance(entry.get('evidence'), str) or not entry['evidence'].strip():
                raise ValueError('source needs evidence or an explicit uncertainty')
            if not isinstance(entry.get('frames', []), list) or not all(isinstance(frame, str) for frame in entry.get('frames', [])):
                raise ValueError('source frames must be a list of paths')
        if abs(cursor - duration) > .001:
            raise ValueError('base-picture inventory must include the ending')
        if not isinstance(source.get('overlays'), list):
            raise ValueError('overlays must be a separate list')
        for entry in source['overlays']:
            if not isinstance(entry, dict):
                raise ValueError('each overlay must be an object')
            interval(entry, duration)
            if entry.get('kind') not in OVERLAYS or entry.get('status') not in ('reviewed', 'candidate'):
                raise ValueError('overlay needs a supported kind and reviewed or candidate status')
            if not all(isinstance(entry.get(key), str) and entry[key].strip() for key in ('evidence', 'anchor')):
                raise ValueError('overlay needs evidence and a story-relative anchor')
            if entry['kind'] == 'pip' and entry['status'] == 'reviewed' and entry.get('source_kind') not in LABELS:
                raise ValueError('reviewed picture-in-picture needs source_kind, including unknown when unresolved')
        coverage = source.get('overlay_coverage')
        if not isinstance(coverage, dict) or any(coverage.get(kind) not in ('unassessed', 'partial', 'complete') for kind in OVERLAYS):
            raise ValueError('each overlay kind needs explicit inventory coverage')
    return profile


def unknown(report):
    duration = report['duration_s']
    boundaries = sorted({0., float(duration)} | {float(shot['start']) for shot in report.get('shots', [])
                                               if 0 < shot.get('start', -1) < duration})
    return {'file': report['file'], 'duration_s': duration,
            'segments': [{'start_s': start, 'end_s': end, 'kind': 'unknown', 'status': 'unknown',
                          'evidence': 'Production provenance is not established by pixels or missing face detections.'}
                         for start, end in zip(boundaries, boundaries[1:])],
            'overlays': [], 'overlay_coverage': {kind: 'unassessed' for kind in OVERLAYS}}


def from_reports(reports):
    references = []
    for report in reports:
        if report.get('shot_sources') is not None:
            references.extend(validate(report['shot_sources'], [report])['references'])
        else:
            references.append(unknown(report))
    return validate({'format': FORMAT, 'references': references}, reports)


def plan(profile):
    profile = validate(profile)
    bases, overlays, unresolved = [], [], []
    for reference, source in enumerate(profile['references']):
        for index, entry in enumerate(source['segments']):
            row = {**entry, 'reference': reference, 'key': f'{reference}:base:{index}',
                   'route': ROUTES[group_of(entry['kind'])]}
            (unresolved if entry['kind'] == 'unknown' else bases).append(row)
        for index, entry in enumerate(source['overlays']):
            overlays.append({**entry, 'reference': reference, 'key': f'{reference}:overlay:{index}'})
    return {'base_picture': bases, 'overlays': overlays, 'unresolved': unresolved,
            'allowed_kinds': sorted({entry['kind'] for entry in bases}),
            'allowed_families': sorted({group_of(entry['kind']) for entry in bases}),
            'timing': 'Reference intervals are evidence, not edit times. Place devices on new story anchors.',
            'limits': 'Reviewed labels are declarations, not automatic proof. Unknown never authorizes generation.'}


def recipe(profile):
    result = plan(profile)
    kinds = ', '.join(result['allowed_kinds']) or 'unknown'
    return ('## Shot sources and overlays\nRead `sources.json`: ' + kinds + '. Preserve source families. '
            'Re-anchor reviewed overlays; audition candidates. Record provenance, event decisions and incomplete '
            'coverage in receipts.')


def reference_report(reference, out, package=None):
    source_path = Path(reference).resolve(strict=True)
    output = Path(out).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('source review needs a new empty output folder')
    report = json.loads(source_path.read_text(encoding='utf-8-sig'))
    source = unknown(report)
    package = package or {}
    for key in ('segments', 'overlays', 'overlay_coverage'):
        if key in package:
            source[key] = package[key]
    marked = None
    if package.get('picture_marks'):
        import letitedit.looks.style_import_marks as style_import_marks
        marks = package['picture_marks']
        marked = style_import_marks.apply(marks['request'], marks.get('pages') or {'items': marks.get('items', [])})
        source['overlays'] = list(source['overlays']) + marked['overlays']
        coverage = dict(source['overlay_coverage'])
        for kind, level in marked['coverage'].items():
            if 'overlay_coverage' not in package or kind not in package['overlay_coverage']:
                coverage[kind] = level
        source['overlay_coverage'] = coverage
    profile = validate({'format': FORMAT, 'references': [source]}, [report])
    report['shot_sources'] = profile
    output.mkdir(parents=True, exist_ok=True)
    (output / 'sources.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    rows = []
    for row in sorted(plan(profile)['base_picture'] + plan(profile)['unresolved'], key=lambda row: row['start_s']):
        images = ''.join('<img width="240" src="' + html.escape(Path(frame).resolve().as_uri(), quote=True) + '">' for frame in row.get('frames', []))
        rows.append('<tr>' + ''.join('<td>' + html.escape(str(row[key])) + '</td>' for key in ('start_s', 'end_s', 'kind', 'route', 'evidence')) + '<td>' + images + '</td></tr>')
    document = ('<!doctype html><meta charset="utf-8"><title>Shot sources</title><h1>Shot sources</h1>'
                '<p>Reviewer declarations; unknown is not absence. Base pictures and overlays stay separate.</p>'
                '<table><tr><th>Start</th><th>End</th><th>Source</th><th>Route</th><th>Evidence</th><th>Frames</th></tr>'
                + ''.join(rows) + '</table><h2>Overlay inventory</h2><pre>'
                + html.escape(json.dumps(source['overlays'], indent=2)) + '</pre><h2>Coverage</h2><pre>'
                + html.escape(json.dumps(source['overlay_coverage'], indent=2)) + '</pre>')
    (output / 'sources.html').write_text(document, encoding='utf-8')
    result = {'report': str(output / 'report.json'), 'profile': str(output / 'sources.json'),
              'html': str(output / 'sources.html'), 'plan': plan(profile)}
    if marked is not None:
        result['picture_marks'] = {key: marked[key] for key in ('items', 'dropped_items', 'tiles_marked', 'tiles')}
    return result


def permitted_labels(profile):
    """The source labels a base picture may carry under this profile: every label in its reference families."""
    families = plan(profile)['allowed_families']
    return sorted(label for label in LABELS if label != 'unknown' and group_of(label) in families)


def check(profile, entry, script, brief=None, decisions=None):
    """The shot_sources receipt: every visible picture's source, the Look's incomplete inventories, and each overlay
    event of the Look's inventory. An overlay event with no decision of its own is accounted for by the decision on
    its kind's device in the same receipt (captions, the sound effects, stickers): a placed captions device covers
    the reference's caption events, which are its own words re-anchored to the new speaker; a sound-effect candidate
    is covered by a sound-effects decision. Inventory coverage the receipt leaves out is the Look's own."""
    from letitedit.looks.look_check import decline_problem
    result = plan(profile)
    decisions = decisions or {}
    problems = []
    tracks = [track for track in script['tracks'] if track.get('kind') == 'video' and track.get('hide') not in ('video', 'both')]
    # adjustment layers (cut flashes, lighting windows) change the pictures under them; they are not pictures
    visual = {item['id']: item for track in tracks for item in track['items'] if 'id' in item and not item.get('adjust')}
    items = {item['id']: item for track in script['tracks'] for item in track['items'] if 'id' in item}
    audio = {item['id'] for track in script['tracks'] if track.get('kind') == 'audio'
             and track.get('hide') not in ('audio', 'both') for item in track['items'] if 'id' in item}
    bottom = next(({item['id'] for item in track['items'] if 'id' in item and not item.get('adjust')} for track in tracks
                   if any('id' in item and not item.get('adjust') for item in track['items'])), set())
    declarations = entry.get('sources', {})
    if not isinstance(declarations, dict):
        return ['sources maps each visible picture item ID to {role: base|overlay, kind, evidence} '
                '(a list of {id, role, kind, evidence} reads the same)']
    if not visual:
        problems.append('source receipt needs current visible picture items')
    permitted = permitted_labels(profile)
    wrong_kinds = {}
    for identity in visual:
        declared = declarations.get(identity, {})
        if not isinstance(declared, dict):
            problems.append(f'{identity}: source declaration must be an object')
            continue
        kind = declared.get('kind')
        if declared.get('role') == 'overlay' and identity not in bottom:
            if kind not in OVERLAYS or not str(declared.get('evidence', '')).strip():
                problems.append(f'{identity}: overlay needs its device kind ({", ".join(OVERLAYS)}) and evidence')
            if kind == 'pip' and group_of(declared.get('source_kind')) not in result['allowed_families']:
                problems.append(f'{identity}: inset picture needs a permitted source family ({", ".join(permitted)})')
        elif (declared.get('role') != 'base' or kind not in LABELS or kind == 'unknown'
              or group_of(kind) not in result['allowed_families'] or not str(declared.get('evidence', '')).strip()):
            wrong_kinds.setdefault(repr(kind) if declared else 'no declaration', []).append(identity)
    for kind, identities in wrong_kinds.items():
        problems.append(f'{len(identities)} base picture(s) declared {kind} ({", ".join(identities[:4])}'
                        f'{", ..." if len(identities) > 4 else ""}): each needs role base, a kind this Look permits '
                        f'({", ".join(permitted) or "none"}) and evidence of where it came from')
    if set(declarations) - set(visual):
        problems.append('source declarations contain stale or non-picture item IDs')
    if result['unresolved']:
        problems.append('reference base-picture source types remain unresolved')
    coverage_receipt = entry.get('coverage') if isinstance(entry.get('coverage'), dict) else {}
    for reference, source in enumerate(profile['references']):
        for kind, coverage in source['overlay_coverage'].items():
            acknowledgment = coverage_receipt.get(f'{reference}:{kind}')
            if coverage != 'complete' and acknowledgment is not None:
                if not isinstance(acknowledgment, dict) or acknowledgment.get('status') != coverage:
                    problems.append(f'{reference}:{kind}: the Look records this inventory as {coverage}; '
                                    f'coverage says otherwise')
    events = entry.get('events') or {}
    if not isinstance(events, dict):
        events = {}
    device_of = {'caption': 'captions', 'sound_effect': 'sound_accents', 'sticker': 'stickers', 'pip': 'stickers'}

    def accounted(overlay):
        """The overlay's kind is decided for the whole video in this receipt."""
        device = decisions.get(device_of.get(overlay['kind'], 'stickers')) or {}
        if overlay['kind'] == 'sound_effect':
            sources = decisions.get('_sources') or {}
            decided = [entry for key, entry in sources.items() if key.startswith('sound.json:effects')]
            decided += [device] if device else []
            return any(isinstance(row, dict) and row.get('status') in ('placed', 'declined') and str(row.get('reason', '')).strip()
                       for row in decided)
        if overlay['kind'] == 'caption':
            return device.get('status') == 'placed' and bool(device.get('items'))
        return device.get('status') in ('placed', 'declined', 'unassessed') and bool(str(device.get('reason', '')).strip())

    unaccounted = []
    for overlay in result['overlays']:
        decision = events.get(overlay['key'])
        if decision is None and accounted(overlay):
            continue
        if not isinstance(decision, dict):
            decision = {}
        if overlay['status'] == 'candidate':
            if decision.get('status') != 'unassessed' or not decision.get('reason'):
                unaccounted.append(overlay['key'] + ' (candidate: unassessed with a reason)')
        elif (decision.get('status') not in ('placed', 'declined') or not decision.get('reason')
              or (decision.get('status') == 'placed' and (not decision.get('items')
                  or any(identity not in items for identity in decision['items']) or not decision.get('anchor')))):
            unaccounted.append(overlay['key'] + f" ({overlay['kind']}: placed with items and a new-story anchor, or declined)")
        elif decision.get('status') == 'declined':
            device = {'caption': 'captions', 'sound_effect': 'sound_accents', 'pip': 'stickers'}.get(overlay['kind'], 'stickers')
            problem = decline_problem(device, decision, {device: json.dumps(overlay)}, brief or {}, decisions)
            if problem:
                problems.append(overlay['key'] + ': ' + problem)
        elif decision.get('status') == 'placed' and overlay['kind'] == 'sound_effect':
            if any(identity not in audio for identity in decision['items']):
                problems.append(overlay['key'] + ': sound effect must name audible audio-track items')
        elif decision.get('status') == 'placed':
            for identity in decision['items']:
                declaration = declarations.get(identity) or {}
                if not isinstance(declaration, dict) or declaration.get('role') != 'overlay' or declaration.get('kind') != overlay['kind']:
                    problems.append(overlay['key'] + f": placed overlay {identity} needs sources[{identity!r}] = "
                                    f"{{role: overlay, kind: {overlay['kind']}, evidence}}")
    if unaccounted:
        problems.append(f'{len(unaccounted)} overlay event(s) of the Look have no decision, and their device has none '
                        'either: ' + '; '.join(unaccounted[:5]) + ('; ...' if len(unaccounted) > 5 else ''))
    return problems


def sound_effect_overlays(sfx, duration):
    """The sound_effect overlay entries and their coverage from the importer's sound effects found in the separated
    residue (style_import_sound.residue_report): ([entries], coverage). Entries are candidates, never reviewed (no
    one has listened). Coverage is 'complete' when the whole file was checked and nothing was left not sure,
    'partial' when some sounds are not sure, and 'unassessed' when the residue was not measured."""
    if not isinstance(sfx, dict) or sfx.get('by') != 'residue' or not (sfx.get('checked') or {}).get('complete'):
        return [], 'unassessed'
    duration = number(duration, 'duration')
    entries = []
    for event in sfx.get('events') or []:
        start = min(max(0., float(event['t'])), max(0., duration - 0.01))
        end = min(duration, max(start + 0.01, float(event.get('end', start + 0.1))))
        anchor = ('the picture event it lands on' if event.get('on_picture_event')
                  else 'the cut it lands on' if event.get('at_cut') else 'its own moment, off cuts and picture events')
        entries.append({'kind': 'sound_effect', 'status': 'candidate', 'start_s': round(start, 3),
                        'end_s': round(end, 3), 'anchor': anchor, 'sound_kind': event.get('kind') or 'unsorted',
                        'evidence': f"{event.get('kind') or 'a sound'}: {event.get('why') or 'found in the residue'} "
                                    f"(rises {event.get('jump_db')} dB); unheard"})
    return entries, 'partial' if sfx.get('not_sure') else 'complete'
