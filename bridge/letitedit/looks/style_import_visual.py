"""Native picture effects, paired-plate lettering fits and reviewed visual evidence."""
from __future__ import annotations

import copy
import json
import math

import numpy as np

FORMAT = 'letitedit-visual-evidence/1'
ROLES = ('talking_head', 'broll', 'primary', 'graphics', 'unknown')
TRANSITIONS = ('cut', 'dissolve', 'fade_black', 'fade_white', 'wipe', 'slide', 'zoom_blur', 'invert', 'unknown')
BLENDS = ('normal', 'difference', 'exclusion', 'screen', 'multiply', 'addition', 'overlay', 'darken', 'lighten')


def _number(value, name, minimum=0):
    if type(value) not in (float, int) or not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be a finite number >= {minimum}')
    return float(value)


def _inverse_pair(before, after):
    active = ~((before.max(axis=2) < .025) & (after.max(axis=2) < .025))
    if np.mean(active) < .4:
        return None
    first, second = before[active], after[active]
    if float(np.std(first)) < .09 or float(np.std(second)) < .09:
        return None
    residual = float(np.mean(np.abs(first + second - 1)))
    direct = float(np.mean(np.abs(first - second)))
    correlation = float(np.corrcoef(first.ravel(), second.ravel())[0, 1])
    support = float(np.mean(np.mean(np.abs(first + second - 1), axis=1) < .15))
    if residual <= .075 and direct >= .25 and correlation <= -.85 and support >= .85:
        return {'mae': round(residual, 5), 'correlation': round(correlation, 5), 'support': round(support, 5)}
    return None


def inversion_events(frames, fps, check=None):
    fps = _number(fps, 'fps', .001)
    previous = anchor = None
    start = proof = None
    events, count = [], 0
    for index, image in enumerate(frames):
        count = index + 1
        picture = np.asarray(image)
        if picture.dtype != np.uint8 or picture.ndim != 3 or picture.shape[2] != 3 or not picture.size:
            raise ValueError('frames need finite three-channel 8-bit pictures')
        current = picture.astype(np.float32) / 255
        if previous is not None and previous.shape != current.shape:
            raise ValueError('frame dimensions changed')
        if start is not None:
            if _inverse_pair(anchor, current) is None:
                events.append({'kind': 'invert', 'start_frame': start, 'end_frame': index,
                               't': start / fps, 'end': index / fps, 'len': (index - start) / fps,
                               'evidence': proof, 'status': 'measured_candidate'})
                start = anchor = None
        elif previous is not None:
            inverse = _inverse_pair(previous, current)
            if inverse is not None:
                start, anchor, proof = index, previous, inverse
        previous = current
        if check and index % 120 == 0:
            check()
    if start is not None:
        events.append({'kind': 'invert', 'start_frame': start, 'end_frame': count,
                       't': start / fps, 'end': count / fps, 'len': (count - start) / fps,
                       'evidence': proof, 'status': 'measured_candidate'})
    return {'events': events, 'decoded_frames': count, 'fps': fps, 'coverage_s': count / fps,
            'method': 'Every decoded native frame, small RGB pictures; textured negative correlation and inverse residual. '
                      'Black borders excluded. Half-open native frame intervals; no easing or sound inferred.',
            'limitations': ['Candidates need inspection; motion/occlusion can hide an inversion or split its span.',
                            'An inverted first frame has no clean predecessor and cannot be established.',
                            'Not a general shot-boundary, wipe, blur or transition-direction classifier.']}


def analyse(video, check=None):
    import cv2
    cv2.setNumThreads(4)
    capture = cv2.VideoCapture(str(video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 4])
    try:
        if not capture.isOpened():
            raise ValueError('could not open reference for native visual analysis')
        fps = capture.get(cv2.CAP_PROP_FPS)
        expected = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

        def frames():
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                height, width = frame.shape[:2]
                scale = min(1, 160 / max(height, width))
                yield cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                                 interpolation=cv2.INTER_AREA)

        result = inversion_events(frames(), fps, check)
        result['expected_frames'] = expected
        result['decode_complete'] = expected > 0 and result['decoded_frames'] == expected
        if not result['decode_complete']:
            result['limitations'].append('Container frame count and decoded coverage disagree; uncovered tail is unknown.')
        return result
    finally:
        capture.release()


def composite(background, colour, mode):
    if mode == 'normal':
        return np.broadcast_to(colour, background.shape)
    if mode == 'difference':
        return np.abs(background - colour)
    if mode == 'exclusion':
        return background + colour - 2 * background * colour
    if mode == 'screen':
        return 1 - (1 - background) * (1 - colour)
    if mode == 'multiply':
        return background * colour
    if mode == 'addition':
        return np.minimum(1, background + colour)
    if mode == 'overlay':
        return np.where(background <= .5, 2 * background * colour, 1 - 2 * (1 - background) * (1 - colour))
    if mode == 'darken':
        return np.minimum(background, colour)
    if mode == 'lighten':
        return np.maximum(background, colour)
    raise ValueError('unknown blend mode')


def fit_blend(background, observed, glyph_mask):
    from scipy.optimize import least_squares
    background, observed, mask = np.asarray(background), np.asarray(observed), np.asarray(glyph_mask)
    if (background.shape != observed.shape or background.ndim != 3 or background.shape[2] != 3
            or mask.shape != background.shape[:2] or mask.dtype != bool
            or not np.isfinite(background).all() or not np.isfinite(observed).all()
            or background.min() < 0 or observed.min() < 0 or background.max() > 1 or observed.max() > 1):
        raise ValueError('blend fit needs aligned finite RGB [0,1] pictures and a boolean glyph mask')
    if mask.sum() < 32:
        raise ValueError('blend fit needs at least 32 glyph-core pixels')
    plate, ink = background[mask], observed[mask]
    stride = max(1, len(plate) // 12000)
    plate, ink = plate[::stride], ink[::stride]
    fits = []
    for mode in BLENDS:
        candidates = []
        for seed in (.001, .5, .999):
            solved = least_squares(lambda colour: (composite(plate, colour, mode) - ink).ravel(),
                                   np.full(3, seed), bounds=(0, 1), max_nfev=60)
            candidates.append((float(np.sqrt(np.mean(solved.fun ** 2))), solved.x))
        residual, colour = min(candidates, key=lambda item: item[0])
        fits.append({'mode': mode, 'rmse': round(residual, 6),
                     'colour_rgb': [round(float(channel), 5) for channel in colour]})
    fits.sort(key=lambda item: item['rmse'])
    best = fits[0]['rmse']
    plausible = [item['mode'] for item in fits if item['rmse'] <= best + .015]
    tonal_variation = float(np.max(np.std(plate, axis=0)))
    status = ('supported_family' if best <= .06 and len(plausible) < len(BLENDS)
              and tonal_variation >= .05 else 'unresolved')
    return {'status': status, 'candidates': plausible if status != 'unresolved' else [],
            'fits': fits, 'pixels': int(mask.sum()), 'background_std': float(np.std(plate)),
            'background_tonal_variation': tonal_variation,
            'scope': 'Opaque glyph cores over an independently supplied aligned clean plate. '
                     'Fits do not prove the plate is clean; alpha, grading and registration can confound them.',
            'ambiguity': 'White Difference and white Exclusion both produce 1-background; baked pixels cannot distinguish them.'}


def _span(item, duration, instant=False):
    if not isinstance(item, dict):
        raise ValueError('visual event must be an object')
    start, end = _number(item.get('start_s'), 'visual start'), _number(item.get('end_s'), 'visual end')
    if start >= duration or end > duration or end < start or (not instant and end == start):
        raise ValueError('visual event must be inside the reference duration')
    return start, end


def cut_flash_profile(native, cut_times, intervals=None, window_frames=12):
    """How the reference flashes its cuts: of its cuts, how many carry whole-picture inversion pulses within
    window_frames of the cut, how long the pulses last, how many each cut has and where they sit (frames before or after
    the cut). With reviewed picture roles, the same counts for cuts between a talking head and b-roll and for cuts between
    b-roll shots. None when there is nothing to count."""
    events = (native or {}).get('events') or []
    fps = (native or {}).get('fps')
    if not fps or not cut_times:
        return None
    import statistics

    def role_at(t):
        for item in intervals or []:
            if item['start_s'] - 1e-6 <= t < item['end_s'] - 1e-6:
                return item['role']
        return None

    rows = []
    for t in cut_times:
        cut = round(t * fps)
        near = [e for e in events if abs(e['start_frame'] - cut) <= window_frames]
        before, after = role_at(t - .05), role_at(t + .05)
        kind = ('speaker_broll' if {before, after} == {'talking_head', 'broll'}
                else 'broll_broll' if before == after == 'broll' else 'other') if intervals else 'all'
        rows.append({'cut': cut, 'near': near, 'kind': kind})
    flashed = [r for r in rows if r['near']]
    pulses = [e for r in flashed for e in r['near']]
    if not rows:
        return None
    out = {'cuts': len(rows), 'cuts_with_flash': len(flashed), 'share': round(len(flashed) / len(rows), 3), 'fps': fps,
           'pulse_frames': statistics.median(e['end_frame'] - e['start_frame'] for e in pulses) if pulses else None,
           'pulses_per_flashed_cut': statistics.median(len(r['near']) for r in flashed) if flashed else None,
           'frames_before_cut': statistics.median([r['cut'] - e['end_frame'] for r in flashed for e in r['near']
                                                   if e['end_frame'] <= r['cut']] or [None]) if pulses else None,
           'frames_after_cut': statistics.median([e['start_frame'] - r['cut'] for r in flashed for e in r['near']
                                                  if e['start_frame'] >= r['cut']] or [None]) if pulses else None,
           'whole_picture_support': round(statistics.median(e['evidence']['support'] for e in pulses
                                                             if (e.get('evidence') or {}).get('support') is not None), 3)
           if any((e.get('evidence') or {}).get('support') is not None for e in pulses) else None}
    if intervals:
        for kind in ('speaker_broll', 'broll_broll'):
            group = [r for r in rows if r['kind'] == kind]
            out[kind] = {'cuts': len(group), 'with_flash': sum(1 for r in group if r['near'])}
    return out


def validate(profile, references=None):
    if not isinstance(profile, dict) or profile.get('format') != FORMAT:
        raise ValueError(f'visual must have format {FORMAT}')
    sources = profile.get('references')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 3:
        raise ValueError('visual references must contain one to three objects')
    if references is not None and len(sources) != len(references):
        raise ValueError('visual references must match the importer reports in order')
    result = copy.deepcopy(profile)
    for index, source in enumerate(result['references']):
        if not isinstance(source, dict):
            raise ValueError('visual reference must be an object')
        duration = _number(source.get('duration_s'), 'visual duration', .001)
        movement = source.get('broll_motion')
        if movement is not None:
            if not isinstance(movement, dict) or not isinstance(movement.get('shots'), list):
                raise ValueError('cutaway motion needs measured shots')
            if _number(movement.get('moving_share'), 'moving share') > 1:
                raise ValueError('moving share cannot exceed one')
            for shot in movement['shots']:
                _span(shot, duration)
                if shot.get('moving') is not None and type(shot['moving']) is not bool:
                    raise ValueError('moving must be true, false or unknown')
        if source.get('camera') is not None:
            from letitedit.looks.camera_language import validate as validate_camera
            validate_camera(source['camera'], duration)
        if references is not None and abs(duration - references[index]['duration_s']) > .001:
            raise ValueError('visual duration does not match its importer report')
        if references is not None and source.get('file') != references[index]['file']:
            raise ValueError('visual source does not match its importer report')
        native = source.get('native_effects')
        if native is not None:
            if not isinstance(native, dict) or not isinstance(native.get('events'), list):
                raise ValueError('native effects need an event list')
            fps = _number(native.get('fps'), 'native fps', .001)
            for event in native['events']:
                if not isinstance(event, dict):
                    raise ValueError('native effects must be objects')
                start, end = event.get('start_frame'), event.get('end_frame')
                if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                        or end / fps > duration + 1 / fps or event.get('kind') != 'invert'):
                    raise ValueError('invalid native inversion interval')
        review = source.get('review')
        if review is None:
            source['semantic'] = {'reviewed_share': 0, 'broll_share': None, 'broll_seconds': 0}
            continue
        if not isinstance(review, dict) or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
            raise ValueError('visual review needs a named reviewer')
        intervals, transitions, captions = (review.get(key, []) for key in ('intervals', 'transitions', 'captions'))
        if not all(isinstance(items, list) for items in (intervals, transitions, captions)):
            raise ValueError('visual review intervals/transitions/captions must be lists')
        if not all(isinstance(item, dict) for item in intervals):
            raise ValueError('semantic intervals must be objects')
        for item in intervals:
            _span(item, duration)
        covered = broll = previous = 0
        for item in sorted(intervals, key=lambda item: item['start_s']):
            start, end = _span(item, duration)
            if start < previous - 1e-8:
                raise ValueError('semantic intervals must not overlap')
            previous = end
            if item.get('role') not in ROLES:
                raise ValueError('invalid semantic picture role')
            if not isinstance(item.get('subject'), str) or not item['subject'].strip():
                raise ValueError('semantic interval needs a subject')
            if item['role'] != 'unknown':
                covered += end - start
            if item['role'] == 'broll':
                broll += end - start
        for item in transitions:
            _span(item, duration, instant=True)
            if item.get('kind') not in TRANSITIONS:
                raise ValueError('invalid reviewed transition kind')
        for item in captions:
            _span(item, duration)
            if not isinstance(item.get('text'), str):
                raise ValueError('reviewed caption needs text')
            blend = item.get('blend_candidates')
            if blend is not None and (not isinstance(blend, list) or not blend or any(mode not in BLENDS for mode in blend)):
                raise ValueError('invalid caption blend candidates')
        rules = review.get('rules', [])
        if not isinstance(rules, list) or any(not isinstance(rule, str) or not rule.strip() for rule in rules):
            raise ValueError('visual rules must be nonempty text')
        from letitedit.looks.cutaway_rhythm import reference
        from letitedit.looks.cutaway_character import reviewed_character
        cut_times = [item['start_s'] for item in transitions if item.get('kind') == 'cut'] or source.get('cuts') or []
        source['semantic'] = {'broll_character': reviewed_character(review),
                              'broll_rhythm': reference(review, duration),
                              'cut_flash': cut_flash_profile(source.get('native_effects'), cut_times, intervals),
                              'reviewed_share': round(covered / duration, 6), 'broll_seconds': round(broll, 6),
                              'broll_share': round(broll / duration, 6) if abs(covered - duration) <= 1e-6 else None}
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('visual evidence must be finite JSON') from error
    return result


def _camera(report):
    """The reference's measured camera language (the importer's camera step), else its moves from the report's shots
    (sizes unknown); None for a report without shots."""
    import letitedit.looks.camera_language as camera_language
    camera = report.get('camera')
    if camera is None and report.get('shots'):
        camera = camera_language.from_shots(report['shots'], report.get('zooms'), report.get('camera_moves'))
    if camera is None:
        return None
    return {key: value for key, value in camera.items() if key not in ('file', 'video_sha256')}


def from_reports(reports):
    return validate({'format': FORMAT, 'references': [
        {'file': report['file'], 'duration_s': report['duration_s'], 'native_effects': report.get('native_effects'),
         'review': report.get('visual_review'), 'broll_motion': report.get('broll_motion'),
         **({'cuts': [c['t'] for c in report['cuts'] if c.get('t') is not None]} if report.get('cuts') else {}),
         **({'camera': camera} if (camera := _camera(report)) is not None else {}),
         'provenance': report.get('visual_provenance')} for report in reports]})


def recipe(profile):
    lines = ['## Measured visual profile',
             'visual.json keeps the per-reference evidence; reference times are evidence, not placements in a new story.']
    for index, source in enumerate(profile['references']):
        semantic = source['semantic']
        share = semantic['broll_share']
        lines.append(f'- Reference {index + 1}: semantic review {semantic["reviewed_share"]:.1%}; '
                     + (f'b-roll {share:.1%} of runtime.' if share is not None else 'full b-roll share unknown.'))
        native = source.get('native_effects') or {}
        if source.get('camera'):
            from letitedit.looks.camera_language import recipe_line
            line = recipe_line(source['camera'])
            if line:
                lines.append(line)
        movement = source.get('broll_motion')
        if movement and movement.get('moving_share') is not None:
            lines.append(f'- Cutaway image motion: {movement["moving_share"]:.1%} moving; '
                         f'median drift {movement["median_speed_per_s"]:.3g} frame fractions/s, '
                         f'zoom {movement["median_zoom_per_s"]:.2g} log-scale/s. '
                         'Prefer moving stock; slow keyframed movement on static shots at these speeds.')
        rhythm = semantic.get('broll_rhythm')
        if rhythm:
            lines.append(f'- Individually reviewed b-roll: {rhythm["count"]} shots, {rhythm["per_minute"]:.2f}/min; '
                         f'median {rhythm["median_s"]:.3f} s, range {rhythm["min_s"]:.3f}-{rhythm["max_s"]:.3f} s. '
                         'Match count and lengths as well as share; inversion frames are not extra shots.')
        flash = semantic.get('cut_flash')
        if flash and flash.get('cuts_with_flash'):
            between = flash.get('speaker_broll')
            lines.append(
                f"- Cut flashes: {flash['cuts_with_flash']} of {flash['cuts']} cuts carry {flash['pulses_per_flashed_cut']:g} "
                f"whole-picture inversions of {flash['pulse_frames']:g} frames ({flash['fps']:g} fps)"
                + (f", one ending {flash['frames_before_cut']:g} before the cut" if flash.get('frames_before_cut') is not None else '')
                + (f", one starting {flash['frames_after_cut']:g} after it" if flash.get('frames_after_cut') is not None else '')
                + (f"; talking head and b-roll {between['with_flash']} of {between['cuts']} cuts, both ways; "
                   f"b-roll and b-roll {flash['broll_broll']['with_flash']} of {flash['broll_broll']['cuts']}" if between else '')
                + '.')
        events = native.get('events', [])
        if events:
            lengths = [event['end_frame'] - event['start_frame'] for event in events]
            lines.append(f'- Native picture analysis: {len(events)} inversion candidates, '
                         f'{min(lengths)}-{max(lengths)} frames at {native["fps"]:g} fps. '
                         'Outside a cut flash, do not tint or invert a new speaker.')
        review = source.get('review') or {}
        roles = sorted({item['role'] for item in review.get('intervals', [])})
        if roles:
            lines.append('- Picture roles: ' + ', '.join(roles) + '. Primary product or graphic footage is not automatically b-roll.')
        lines.extend('- ' + rule for rule in review.get('rules', []))
        kinds = sorted({item['kind'] for item in review.get('transitions', [])})
        if kinds:
            lines.append('- Reviewed transition kinds: ' + ', '.join(kinds) + '; lengths/directions are in visual.json, not assumed.')
        families = sorted({mode for item in review.get('captions', []) for mode in item.get('blend_candidates', [])})
        if families:
            lines.append('- Letter blend candidates: ' + ', '.join(families) + '. White difference/exclusion are indistinguishable; '
                         'choose a supported implementation, never call the source editor setting uniquely identified.')
    return '\n'.join(lines)


def reference_report(reference, out, options=None):
    import hashlib
    from pathlib import Path
    import letitedit.core.render_lock as render_lock
    options = options or {}
    source = Path(reference).resolve(strict=True)
    report = json.loads(source.read_text(encoding='utf-8-sig'))
    video = Path(report['file']).resolve(strict=True)
    destination = Path(out).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'report.json'
    if target == source or target.exists():
        raise ValueError('visual evidence needs a new output report; source and existing files are not replaced')
    with render_lock.slot('reference visual evidence', timeout_s=300):
        report['native_effects'] = analyse(video)
        samples = []
        for sample in options.get('blend_samples', []):
            from PIL import Image
            background = np.asarray(Image.open(sample['background']).convert('RGB'), dtype=float) / 255
            observed = np.asarray(Image.open(sample['observed']).convert('RGB'), dtype=float) / 255
            mask = np.asarray(Image.open(sample['mask']).convert('L')) >= 128
            fitted = fit_blend(background, observed, mask)
            samples.append({'files': sample, 'fit': fitted})
    if 'review' in options:
        report['visual_review'] = options['review']
    shots = (report.get('visual_review') or {}).get('shots')
    if shots:
        from letitedit.looks.cutaway_motion import measure
        with render_lock.slot('reference cutaway motion', timeout_s=3600):
            report['broll_motion'] = measure(video, shots)
        for shot, measured in zip(shots, report['broll_motion']['shots']):
            shot['picture_properties'] = {key: measured[key] for key in ('median_luma', 'median_saturation')}
    with video.open('rb') as stream:
        video_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    report['visual_provenance'] = {'report': str(source), 'report_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                   'video_sha256': video_hash,
                                   'blend_samples': samples}
    profile = from_reports([report])
    target.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    return {'report': str(target), 'visual': profile, 'blend_samples': samples,
            'notice': 'Review is caller-supplied evidence, not automatic semantic recognition. Clean plates must be independently aligned.'}
