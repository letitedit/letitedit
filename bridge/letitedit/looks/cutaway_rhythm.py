"""Individual semantic shots, not detector cuts or coverage sequences."""
import math
import statistics


def metrics(lengths, duration):
    return {'count': len(lengths), 'per_minute': len(lengths) * 60 / duration,
            'median_s': statistics.median(lengths) if lengths else None,
            'min_s': min(lengths) if lengths else None, 'max_s': max(lengths) if lengths else None}


def merged_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def primary_spans(shots, duration):
    cursor = 0.
    spans = []
    for start, end in merged_spans((shot['start_s'], shot['end_s']) for shot in shots):
        if start > cursor + 1e-6:
            spans.append([cursor, start])
        cursor = end
    if cursor < duration - 1e-6:
        spans.append([cursor, duration])
    return spans


def reference(review, duration):
    shots = review.get('shots')
    if shots is None:
        return None
    if not isinstance(shots, list) or not str(review.get('shot_review_method', '')).strip():
        raise ValueError('individual shots need a list and shot_review_method')
    cursor = 0.
    lengths = []
    broll = [row for row in review['intervals'] if row['role'] == 'broll']
    for shot in shots:
        start, end = shot.get('start_s'), shot.get('end_s')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start + end) or not cursor <= start < end <= duration
                or not str(shot.get('subject', '')).strip()
                or not any(row['start_s'] <= start and end <= row['end_s'] for row in broll)):
            raise ValueError('individual b-roll shots need ordered spans inside reviewed b-roll and a subject')
        lengths.append(end - start)
        cursor = end
    if abs(sum(lengths) - sum(row['end_s'] - row['start_s'] for row in broll)) > 1e-5:
        raise ValueError('individual shots must cover all reviewed b-roll without gaps')
    result = metrics(lengths, duration)
    face = merged_spans((row['start_s'], row['end_s']) for row in review['intervals']
                        if row['role'] == 'talking_head')
    if face:
        result['longest_talking_head_s'] = max(end - start for start, end in face)
    return result


def check(script, identities, entry, requirements, duration):
    import letitedit.timeline.edit_script as edit_script
    import json
    targets = []
    for name, text in requirements.items():
        if name == 'visual.json':
            targets.extend(row.get('semantic', {}).get('broll_rhythm') for row in json.loads(text)['references'])
    targets = [target for target in targets if target is not None]
    if not targets:
        return None, []
    shots = entry.get('visible_shots')
    if not isinstance(shots, list) or not shots:
        return None, ['measured individual cutaway rhythm needs visible_shots with id/start_s/end_s']
    items = {item['id']: item for track in script['tracks'] for item in track['items'] if item.get('id') in identities}
    lengths = []
    cursor = 0.
    for shot in shots:
        start, end = shot.get('start_s'), shot.get('end_s')
        item = items.get(shot.get('id'))
        if (not item or type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start + end) or not cursor <= start < end <= duration
                or start < edit_script.to_seconds(item['at']) - 1e-6
                or end > edit_script.to_seconds(item['at']) + item['len'] + 1e-6):
            return None, ['visible shot spans must be ordered, non-overlapping and inside their declared item']
        lengths.append(end - start)
        cursor = end
    measured = metrics(lengths, duration)
    target_rate = statistics.median(target['per_minute'] for target in targets)
    target_median = statistics.median(target['median_s'] for target in targets if target['median_s'] is not None)
    target_max = max(target['max_s'] for target in targets if target['max_s'] is not None)
    problems = []
    if abs(len(lengths) - target_rate * duration / 60) > 1:
        problems.append('individual cutaway count differs from reference by more than one rounding shot')
    if measured['median_s'] > target_median * 1.25 or measured['max_s'] > target_max + .05:
        problems.append('cutaways are longer than the measured reference rhythm')
    face_limits = [target['longest_talking_head_s'] for target in targets if 'longest_talking_head_s' in target]
    if face_limits:
        spans = primary_spans(shots, duration)
        measured['talking_head_spans'] = spans
        measured['longest_talking_head_s'] = max((end - start for start, end in spans), default=0.)
        measured['talking_head_basis'] = 'uncovered primary-picture spans; conservative unless all cutaways declared'
        limit = max(face_limits)
        measured['talking_head_limit_s'] = limit
        for start, end in spans:
            if end - start > limit + .05:
                problems.append(f'talking-head stretch {start:.3f}-{end:.3f}s ({end-start:.3f}s) exceeds reference {limit:.3f}s')
    return measured, problems
