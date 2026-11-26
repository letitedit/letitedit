"""Role/phase-aligned private typography sheets, without automatic editorial scores."""
from pathlib import Path


SUBPARTS = ('fonts', 'sizes', 'layout', 'colour', 'movement')


def pairs(reference, result):
    inventories = [(report.get('typography') or {}).get('events') or [] for report in (reference, result)]
    sample_fps = min((report.get('typography') or {}).get('fps', 15) for report in (reference, result))
    sample_fps = max(10, min(30, sample_fps))
    output, unmatched = [], []
    for role in ('linking', 'emphasis'):
        groups = [[event for event in inventory if event.get('role') == role and event.get('phases')]
                  for inventory in inventories]
        for index in range(max(map(len, groups), default=0)):
            if any(index >= len(group) for group in groups):
                unmatched.append({'role': role, 'ordinal': index, 'missing': 'reference' if index >= len(groups[0]) else 'result'})
                continue
            before, after = (group[index] for group in groups)
            for phase in ('entry', 'hold', 'exit'):
                if phase not in before['phases'] or phase not in after['phases']:
                    continue
                output.append({'role': role, 'phase': phase, 'reference_id': before['id'], 'result_id': after['id'],
                               'reference': before['phases'][phase], 'result': after['phases'][phase],
                               'reference_text': before.get('text'), 'result_text': after.get('text')})
            for offset in (step / sample_fps for step in range(5)):
                selected = []
                for event in (before, after):
                    entry = event['phases'].get('entry')
                    if not entry:
                        selected.append(None)
                        continue
                    anchor = entry['t']
                    dense = event.get('dense') or []
                    hit = min(dense, key=lambda item: abs(item['t'] - anchor - offset)) if dense else None
                    selected.append(hit if hit and abs(hit['t'] - anchor - offset) <= 0.55 / sample_fps else None)
                if all(selected):
                    output.append({'role': role, 'phase': f'entry+{offset:.3f}s', 'reference_id': before['id'],
                                   'result_id': after['id'], 'reference': selected[0], 'result': selected[1]})
    return {'pairs': output, 'unmatched': unmatched,
            'status': 'ready_for_visual_review' if output else 'unmeasured',
            'alignment': 'Same role and phase, ordinal pairing within role; not a semantic or timing match.',
            'subparts': {part: {'critic_score': None} for part in SUBPARTS}}


def sheets(reference, result, out):
    from PIL import Image, ImageDraw
    evidence = pairs(reference, result)
    directory = Path(out) / 'text-private'
    directory.mkdir(parents=True, exist_ok=True)
    pages, tiles = [], []
    resolutions = [(report.get('typography') or {}).get('resolution') for report in (reference, result)]
    for pair in evidence['pairs']:
        paths = [Path(pair[side]['path']) for side in ('reference', 'result')]
        if not all(path.is_file() for path in paths):
            pair['status'] = 'missing_crop'
            continue
        with Image.open(paths[0]) as before, Image.open(paths[1]) as after:
            images = [before.convert('RGB'), after.convert('RGB')]
        scales = [1080 / resolution[0] if resolution else 1 for resolution in resolutions]
        common = min(0.5, *(520 / (image.width * scale) for image, scale in zip(images, scales)))
        heights = [round(image.height * scale * common) for image, scale in zip(images, scales)]
        tile = Image.new('RGB', (1080, max(heights) + 55), '#202020')
        draw = ImageDraw.Draw(tile)
        draw.text((8, 4), f"{pair['role']} / {pair['phase']} - reference LEFT, result RIGHT", fill='white')
        for index, (image, scale) in enumerate(zip(images, scales)):
            resized = image.resize((max(1, round(image.width * scale * common)), max(1, heights[index])))
            tile.paste(resized, (index * 540 + (540 - resized.width) // 2, 48))
            draw.text((index * 540 + 8, 25), f"source {pair[('reference', 'result')[index]]['t']:.4f}s", fill='white')
        tiles.append(tile)
        pair['status'] = 'pictured'
    for start in range(0, len(tiles), 6):
        batch = tiles[start:start + 6]
        page = Image.new('RGB', (1080, sum(tile.height for tile in batch)), '#202020')
        top = 0
        for tile in batch:
            page.paste(tile, (0, top))
            top += tile.height
        path = directory / f'text-{start // 6 + 1:03d}.jpg'
        page.save(path, quality=95)
        pages.append(str(path.resolve()))
    evidence['pages'] = pages
    if not pages:
        evidence['status'] = 'unmeasured'
    evidence['scale_note'] = 'Common source-width scale on BOTH sides; no independent fit-to-box enlargement.'
    evidence['layout_note'] = 'Crops are centred for shape comparison; use full-frame boxes for absolute layout.'
    return evidence


def validate_scores(assessment):
    scores = assessment.get('text_parts')
    if assessment.get('score') is None and scores is None:
        return {part: {'critic_score': None} for part in SUBPARTS}
    if not isinstance(scores, dict) or set(scores) != set(SUBPARTS):
        raise ValueError('captions need separate text_parts: fonts, sizes, layout, colour, movement')
    for part, value in scores.items():
        if not isinstance(value, dict):
            raise ValueError(f'text_parts.{part} needs an assessment')
        score = value.get('score')
        if score is not None and (type(score) not in (float, int) or not 0 <= score <= 10):
            raise ValueError(f'text_parts.{part} score must be 0-10 or null')
        if not isinstance(value.get('evidence'), str) or not value['evidence'].strip():
            raise ValueError(f'text_parts.{part} needs timestamped evidence')
        if (not isinstance(value.get('limitations'), list)
                or not all(isinstance(item, str) for item in value['limitations'])):
            raise ValueError(f'text_parts.{part} needs limitations')
    if assessment.get('score') is not None:
        if any(value.get('score') is None for value in scores.values()):
            raise ValueError('caption total cannot be assessed while a text subpart is unknown')
        if assessment['score'] > min(value['score'] for value in scores.values()):
            raise ValueError('caption total cannot exceed its weakest text subpart')
    return {part: {**value, 'critic_score': value.get('score')} for part, value in scores.items()}


def validate_evidence(assessment, evidence):
    scores = assessment.get('text_parts') or {}
    measured = [part for part in SUBPARTS if (scores.get(part) or {}).get('score') is not None]
    if measured and not evidence.get('pages'):
        raise ValueError('text scores need pictured role/phase crops; missing evidence is unassessed')
    dense = [pair for pair in evidence.get('pairs', [])
             if pair.get('status') == 'pictured' and pair['phase'].startswith('entry+')]
    if 'movement' in measured and len(dense) < 2:
        raise ValueError('movement score needs at least two pictured dense entry pairs')
