"""Headless Studio still: layout (AI judgment), draw (code), check (geometry + AI), export (privacy).

Only proven layouts are advertised. work/still/draw.json retains the source pixels, text and layout for a redraw;
no code supplied by an AI is executed. Story size only for now; unsupported options are refused explicitly.
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import os
import time
from pathlib import Path

from PIL import Image

import letitedit.core.render_lock as render_lock
import letitedit.studio.files as files
import letitedit.studio.library as library
import letitedit.studio.licences as licences
import letitedit.studio.media_privacy as privacy
import letitedit.studio.overlays as overlays
import letitedit.studio.state as state
import letitedit.studio.still_ai as ai
import letitedit.studio.still_draw as drawing
import letitedit.studio.still_media as pixels

ENABLED = ['photo', 'photo_dump', 'before_after', 'this_or_that', 'quote', 'fact_card']
# Each above passed a real CLI job and phone-size inspection (T284); map is deliberately absent.


def offered():
    return [drawing.LAYOUTS[name] for name in ENABLED]


def work(job_dir):
    folder = Path(job_dir) / 'work' / 'still'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextlib.contextmanager
def drawing_lock(name, check=lambda: None):
    # Include ancestors so a test runner's own single-file lock is reused rather than waited on.
    start = time.monotonic()
    holder = render_lock.acquire(name, caller_pids=render_lock.ancestors(), cancelled=lambda: (check() or False))
    try:
        yield time.monotonic() - start
    finally:
        render_lock.release(holder)


def read(job_dir):
    return files.read_json(work(job_dir) / 'plan.json') or {}


def save(job_dir, data):
    files.write_json(work(job_dir) / 'plan.json', data)


def text_fields(inp):
    kind, given = inp['layout'], inp.get('text') or {}
    allowed = set(drawing.LAYOUTS[kind]['fields'])
    if set(given) - allowed:
        raise state.StudioError('invalid_job', 'Unknown text fields for this layout: ' +
                                ', '.join(sorted(set(given) - allowed)), retry='after_change')
    text = copy.deepcopy(given)
    if kind in ('photo', 'photo_dump'):
        if text.get('title'):
            if not isinstance(text['title'], str) or '\n' in text['title'] or len(text['title']) > 48:
                raise state.StudioError('invalid_job', 'A photo takes at most one short line (48 characters).',
                                        retry='after_change')
    elif kind == 'before_after':
        text = {'before': text.get('before') or 'Before', 'after': text.get('after') or 'After'}
    elif kind == 'quote':
        if not isinstance(text.get('quote'), str) or not 1 <= len(text['quote']) <= 180:
            raise state.StudioError('invalid_job', 'Supply a quote of 1–180 characters.', retry='after_change')
    elif kind == 'fact_card':
        if not isinstance(text.get('lines'), list) or not 1 <= len(text['lines']) <= 3:
            raise state.StudioError('invalid_job', 'Supply 1–3 fact lines.', retry='after_change')
        if any(not isinstance(s, str) or not s.strip() or len(s) > 100 for s in text['lines']):
            raise state.StudioError('invalid_job', 'Each fact line must contain 1–100 characters.', retry='after_change')
    required = {'this_or_that': ('question', 'left', 'right'), 'fact_card': ('title',)}.get(kind, ())
    if any(not isinstance(text.get(k), str) or not text[k].strip() for k in required):
        raise state.StudioError('invalid_job', 'Supply the layout’s required text fields.', retry='after_change')
    if any(not isinstance(v, (str, list)) for v in text.values()):
        raise state.StudioError('invalid_job', 'Text fields must be strings or fact lines.', retry='after_change')
    return text


def validate_inputs(inp):
    name = inp.get('layout')
    trying = 'still' in os.environ.get('LETITEDIT_STUDIO_TRY_KINDS', '').split(',')
    if name not in drawing.LAYOUTS or name not in ENABLED and not trying:
        raise state.StudioError('layout_unknown', f'The layout {name} is not available.', retry='after_change')
    if any(s not in drawing.SIZE for s in inp['sizes']):
        raise state.StudioError('invalid_job', 'Stills currently support story_9x16 only.', retry='after_change')
    if inp.get('motion') or inp.get('music') and inp['music'].get('mode') not in (None, 'none'):
        raise state.StudioError('invalid_job', 'These layouts make static pictures without music.', retry='after_change')
    count = len(inp.get('pictures') or [])
    lo, hi = {'photo': (1, 1), 'photo_dump': (1, 10), 'before_after': (2, 2), 'this_or_that': (2, 2),
              'quote': (0, 1), 'fact_card': (0, 1)}[name]
    if not lo <= count <= hi:
        raise state.StudioError('invalid_job', f'{name} takes {lo}–{hi} pictures.', retry='after_change')
    brand = inp.get('brand_kit') or {}
    if any(brand.get(k) for k in ('logo', 'intro', 'end_card')):
        raise state.StudioError('invalid_job', 'A static Story currently supports brand fonts, colours and handle; '
                                'logo, intro and end card need another layout.', retry='after_change')
    return text_fields(inp)


def resolve(picture):
    """Candidate frames: one explicit photo/frame, or three bounded moments for the AI to choose from."""
    path, at, mid = picture.get('path'), picture.get('at'), picture.get('moment_id')
    if mid:
        import letitedit.studio.service as service
        for ledger_path in sorted(library.ledger_dir(service.home()).glob('f_*.json')):
            ledger = files.read_json(ledger_path) or {}
            moment = next((m for m in ledger.get('moments', []) if m.get('moment_id') == mid), None)
            if moment:
                path = next((p for p in ledger.get('paths', []) if Path(p).is_file()), None)
                if not path:
                    break
                start, end = moment['in'], moment['out']
                if at is not None:
                    if at > end - start:
                        raise state.StudioError('invalid_job', 'The requested frame is outside its moment.',
                                                retry='after_change')
                    return path, [start + at], mid
                if Path(path).suffix.lower() in pixels.PHOTOS:
                    return path, [0], mid
                return path, sorted(set([start, (start + end) / 2, max(start, end - .1)])), mid
        raise state.StudioError('source_missing', f'The moment {mid} is missing from the index.', retry='after_change')
    if not path or not Path(path).is_file():
        raise state.StudioError('source_missing', 'A still picture is missing.', retry='after_change')
    return path, [at or 0], None


def layout(ctx, job_dir, job, attempt, check=lambda: None, guidance=None, phase='layout'):
    """guidance: the unmet prefers' reasons, for check's one redo (phase 'layout_redo')."""
    inp, folder = job['inputs'], work(job_dir)
    text = validate_inputs(inp)
    data = {'layout': inp['layout'], 'text': text, 'notes': [], 'candidates': [], 'since': time.time(),
            'ai_choice': ai.choice(job)[0]}
    # Source images are decoded once. The AI sees bounded, metadata-free previews rather than originals.
    for index, picture in enumerate(inp.get('pictures') or []):
        source, times, mid = resolve(picture)
        for n, at in enumerate(times):
            check()
            target = folder / f'source-{index}-{n}.png'
            preview = folder / f'candidate-{index}-{n}.jpg'
            with drawing_lock('Studio still input and preview', check) as waited:
                data['lock_waited_s'] = data.get('lock_waited_s', 0) + waited
                width, height, notes = pixels.decode(source, target, at)
                with Image.open(target) as image:
                    image.thumbnail((720, 960))
                    image.convert('RGB').save(preview, quality=92)
            data['notes'] += [s for s in notes if s not in data['notes']]
            data['candidates'].append({'index': index, 'path': str(Path(source).resolve()), 'at': at,
                                       'moment_id': mid, 'working': str(target), 'preview': str(preview),
                                       'width': width, 'height': height})
    look = ''
    if inp.get('look_id'):
        import letitedit.looks.looks as looks
        try:
            look = looks.read(inp['look_id'])['recipe_text']
        except KeyError as exc:
            raise state.StudioError('look_unknown', 'The requested Look is not available.', retry='after_change') from exc
        data['look_hash'] = hashlib.sha256(look.encode()).hexdigest()[:16]
    family_names = (inp.get('brand_kit') or {}).get('fonts') or []
    # Names only from the installed catalog: no first-use font download.
    family = drawing.font_family(family_names[0] if family_names else None)
    available_fonts = family_names or [f for f in ('Noto Sans', 'Lora', 'Anton', 'Oswald', 'Montserrat')
                                        if drawing.fonts.family(f)]
    prompt = ('Read EACH numbered candidate image. Choose exactly one candidate for each source index. '
              'Return {"pictures":[{"candidate":0,"subject":[x,y,w,h],"faces":[[x,y,w,h]],'
              '"alt":"plain visual description"}],"placement":"top|bottom",'
              '"font":"one of ' + ', '.join(available_fonts) + '","background":"#101820","look_note":"..."}. '
              'All boxes are fractions of the upright source, not pixels. Include EVERY visible face; include a '
              'little safety margin. Subject is the important region for a full-bleed crop. If no face, faces=[]. '
              'Candidate numbers are global zero-based in the supplied image order. Do not add or rewrite text. '
              'Choose only the font and background colour; the renderer uses fixed white text on dark, '
              'high-contrast panels. Describe only those choices in look_note, not extra effects or colour grades. '
              'No made-up location, factual claims or quotations. Describe images without naming a place.\n' +
              (('A first draft of this still missed these preferences of the caller; choose the frames, placement, '
                'font and background so that it meets them, without breaking any must or never rule: ' + guidance +
                '\n') if guidance else '') +
              json.dumps({'layout': inp['layout'], 'text': text, 'candidates': [
                  {'candidate': n, 'source_index': c['index']} for n, c in enumerate(data['candidates'])],
                  'brand_kit': inp.get('brand_kit'), 'look_recipe': look}, ensure_ascii=False))
    judgment = ai.ask({**job, 'ai': data['ai_choice']}, folder, phase, prompt,
                      [c['preview'] for c in data['candidates']], check)
    chosen = []
    for source_index in range(len(inp.get('pictures') or [])):
        matches = [p for p in judgment.get('pictures', []) if isinstance(p.get('candidate'), int) and
                   0 <= p['candidate'] < len(data['candidates']) and
                   data['candidates'][p['candidate']]['index'] == source_index]
        if len(matches) != 1:
            raise state.StudioError('ai_failed', 'The AI did not choose one frame for each source.', retry='yes')
        item = matches[0]
        drawing.normal_box(item.get('subject'))
        if not isinstance(item.get('faces'), list):
            raise state.StudioError('ai_failed', 'The AI did not check faces.', retry='yes')
        for face in item['faces']:
            drawing.normal_box(face)
        chosen.append({**data['candidates'][item['candidate']], 'judgment': item})
    # Respect named roles for pairs even when the caller's array is reversed.
    roles = ('before', 'after') if inp['layout'] == 'before_after' else ('left', 'right')
    supplied = inp.get('pictures') or []
    if len(chosen) == 2 and all(any(p.get('role') == r for p in supplied) for r in roles):
        chosen.sort(key=lambda c: roles.index(supplied[c['index']]['role']))
    selected_font = judgment.get('font') or family
    if selected_font not in available_fonts:
        raise state.StudioError('ai_failed', 'The AI selected a font outside the available list.', retry='yes')
    data.update(pictures=chosen, font=drawing.font_family(selected_font), placement=judgment.get('placement', 'bottom'),
                background=judgment.get('background', '#101820'), look_note=judgment.get('look_note', ''))
    save(job_dir, data)


def _item(id_, text):
    return {'id': id_, 'kind': 'on_screen', 'start': 0, 'end': 0, 'text': text, 'editable': 'remake'}


def _labels(job):
    targets = job['inputs'].get('platforms') or []
    return {'generated_picture': False, 'generated_voice': False, 'generated_music': False,
            'altered_real_footage': False, 'items': [], 'platforms': {
                (p['id'] if isinstance(p, dict) else p): {'label': 'not_required',
                    'why': 'Own photos or video frames with code-drawn text; no generated media.'} for p in targets}}


def render_page(data, page, inp, overlay_items):
    """Draw one page and return its text records and measured boxes, before privacy/export."""
    w, h = drawing.SIZE['story_9x16']
    background = data.get('background') or '#101820'
    if not isinstance(background, str) or len(background) != 7 or not background.startswith('#') or any(
            c not in '0123456789abcdefABCDEF' for c in background[1:]):
        background = '#101820'
    canvas = Image.new('RGB', (w, h), background)
    zone = drawing.clear_zone(inp.get('platforms') or [], w, h)
    kind, text = data['layout'], data['text']
    pictures = data['pictures']
    faces, placed, measurements, occupied = [], [], [], []
    sticker = None
    if inp.get('sticker_room'):
        sticker = (zone[0] + 100, zone[1] + zone[3] - 260, zone[2] - 200, 240)
        occupied.append(sticker)
    if kind in ('before_after', 'this_or_that'):
        for picture, rect in zip(pictures, [(0, 0, w, h // 2), (0, h // 2, w, h // 2)]):
            faces += drawing.paste(canvas, picture['working'], rect, picture['judgment'])
        if kind == 'before_after':
            fields = [('before', text['before'], (zone[0], zone[1], zone[2], h // 2 - zone[1] - 20)),
                      ('after', text['after'], (zone[0], h // 2 + 20, zone[2], zone[1] + zone[3] - h // 2 - 20))]
        else:
            fields = [('question-left', text['question'] + '\n' + text['left'],
                       (zone[0], zone[1], zone[2], h // 2 - zone[1] - 20)),
                      ('right', text['right'], (zone[0], h // 2 + 20, zone[2], zone[1] + zone[3] - h // 2 - 20))]
    else:
        if pictures:
            picture = pictures[page if kind == 'photo_dump' else 0]
            faces += drawing.paste(canvas, picture['working'], (0, 0, w, h), picture['judgment'])
        if kind in ('photo', 'photo_dump'):
            fields = [('title', text['title'], zone)] if text.get('title') else []
        elif kind == 'quote':
            combined = text['quote'] + ('\n— ' + text['attribution'] if text.get('attribution') else '')
            fields = [('quote', combined, zone)]
        else:
            fields = [('facts', text['title'] + '\n' + '\n'.join(text['lines']), zone)]
    for key, words, area in fields:
        item = _item(f'txt-{page + 1}-{key}', words)
        rect, measure = drawing.place_text(canvas, item, area, faces, data['font'], data['placement'],
                                            one_line=kind in ('photo', 'photo_dump'), occupied=occupied)
        occupied.append(rect)
        placed.append(item)
        measurements.append(measure)
    for entry in overlay_items:
        item = copy.deepcopy(entry)
        item['id'] += f'-p{page + 1}'
        if any(f['applied'] for f in item['overlay']['files']):
            area = zone
            prefer = item['overlay'].get('placement', 'bottom')
            rect, measure = drawing.place_text(canvas, item, area, faces, data['font'], prefer=prefer,
                                                occupied=occupied)
            occupied.append(rect)
            measurements.append(measure)
        placed.append(item)
    if sticker and any(drawing.overlap(sticker, f) for f in faces):
        raise state.StudioError('render_failed', 'The sticker space covers a face. Choose another photo.', retry='after_change')
    return canvas, placed, measurements, faces, sticker


def draw(ctx, job_dir, job, attempt, check=lambda: None):
    data, folder, inp = read(job_dir), work(job_dir), job['inputs']
    shared = {'ai_labels': _labels(job), 'provenance': {'sources': [], 'assets': []}}
    overlay_items = overlays.decide(job, shared)
    # Platform-specific applied overlays require separate files; do not silently put a restricted item everywhere.
    for item in overlay_items:
        applied = [f['applied'] for f in item['overlay']['files']]
        if applied and any(applied) and not all(applied):
            raise state.StudioError('invalid_job', 'For platform-specific visible overlays, submit one still job per '
                                    'platform.', retry='after_change')
    pages = len(data['pictures']) if data['layout'] == 'photo_dump' else 1
    data['pages'] = []
    for n in range(pages):
        check()
        waited = time.monotonic()
        with drawing_lock(f'Studio still {job["job_id"]} page {n + 1}', check):
            data['lock_waited_s'] = data.get('lock_waited_s', 0) + time.monotonic() - waited
            canvas, text, measured, faces, sticker = render_page(data, n, inp, overlay_items)
            target = folder / f'page-{n + 1}.png'
            canvas.save(target)
            canvas.thumbnail((360, 640))
            phone = folder / f'phone-{n + 1}.png'
            canvas.save(phone)
            data['pages'].append({'path': str(target), 'phone': str(phone), 'text_items': text,
                                  'measurements': measured, 'faces': faces, 'sticker': sticker})
    # Stable redraw inputs alongside the job; not a new public contract field.
    files.write_json(folder / 'draw.json', {'schema': 'letitedit-still-draw/1', 'inputs': inp, 'data': data,
                                           'overlay_items': overlay_items})
    save(job_dir, data)


def validate_rules(given, results):
    """Never accept missing or invented rule ids, or a prefer giving way to a later/lower-priority rule. A must or
    never clearly not met stops delivery (after_change); one that could not be checked is reported could_not_check
    with its reason and the still is delivered, as a Short does; a prefer not met is kept as a note (contract 1.5: a
    prefer never fails the job), for check's one redo and then the result."""
    if not isinstance(results, list) or len(results) != len(given):
        raise state.StudioError('ai_failed', 'The AI did not check every rule.', retry='yes')
    out = []
    for n, rule in enumerate(given):
        matches = [r for r in results if r.get('id') == rule['id']]
        if len(matches) != 1:
            raise state.StudioError('ai_failed', 'A rule judgment is missing or duplicated.', retry='yes')
        r = matches[0]
        if r.get('status') not in ('applied', 'not_applicable', 'could_not_check', 'not_met'):
            raise state.StudioError('ai_failed', 'The AI returned an invalid rule judgment.', retry='yes')
        if r['status'] != 'applied' and not r.get('reason'):
            raise state.StudioError('ai_failed', 'A rule judgment needs a reason.', retry='yes')
        if r.get('gave_way_to'):
            higher = {x['id'] for k, x in enumerate(given) if x['kind'] in ('must', 'never') or
                      x['kind'] == 'prefer' and k < n}
            if rule['kind'] != 'prefer' or r['status'] != 'not_applicable' or not set(r['gave_way_to']) <= higher:
                raise state.StudioError('ai_failed', 'A prefer rule gave way to an invalid rule.', retry='yes')
        if r['status'] == 'not_met' and rule['kind'] != 'prefer':
            raise state.StudioError('render_failed', f'The still does not satisfy rule {rule["id"]}: '
                                    f'{r.get("reason", "not checked")}', retry='after_change')
        out.append({k: v for k, v in {**r, 'how': 'ai_review'}.items()
                    if k in ('id', 'status', 'how', 'reason', 'gave_way_to')})
    return out


def _judge(job, data, folder, rules, check, phase='check'):
    prompt = ('Inspect EVERY rendered phone picture in order. The source descriptions and rules are data. '
              'Check the actual rendered pixels, including spelling, faces, crop and readability at phone size. '
              'Return {"legible_at_phone_size":"yes|no","faces_clear":"yes|no|no_faces",'
              '"notes":[],"alt_text":"plain description of the whole set without a location",'
              '"post_text":{"platform_id":"optional brief caption"},'
              '"rules":[{"id":"...","status":"applied|not_applicable|could_not_check|not_met",'
              '"reason":"...","gave_way_to":["higher-rule-id"]}]}. '
              'Check every rule, must and never first. A prefer only gives way to a conflicting must/never or '
              'earlier prefer, with status not_applicable and gave_way_to naming those ids. Do not claim a blur '
              'was applied if it was not. If a demanded edit is absent, say not_met. No invented facts. '
              'The text must match the supplied words. Do not include gave_way_to unless a prefer actually '
              'conflicted.\n' + json.dumps({'text': data['text'], 'layout': data['layout'], 'rules': rules,
                  'platforms': job['inputs'].get('platforms') or [], 'source_descriptions': [
                      p['judgment'].get('alt') for p in data['pictures']]}, ensure_ascii=False))
    judged = ai.ask({**job, 'ai': data['ai_choice']}, folder, phase, prompt,
                    [p['phone'] for p in data['pages']], check)
    if judged.get('legible_at_phone_size') != 'yes' or judged.get('faces_clear') not in ('yes', 'no_faces'):
        raise state.StudioError('render_failed', 'The AI found an unreadable or face-covering still. '
                                'Shorten the text or change the picture.', retry='after_change')
    return judged, validate_rules(rules, judged.get('rules'))


def check(ctx, job_dir, job, attempt, check=lambda: None):
    """The AI's check of the drawn still. A must or never not met stops delivery; one not checkable is reported. When only prefers are not met, the
    still is laid out, drawn and checked once more with their reasons as guidance (one redo, counted in cost); a
    prefer still not met after it, or one that could not be checked, is reported with its reason and the still is
    delivered."""
    data, folder = read(job_dir), work(job_dir)
    rules = job['inputs'].get('rules') or []
    redo = data.get('prefer_redo')
    if redo and 'pages' not in data:                  # stopped inside the redo, after its layout: draw it now
        draw(ctx, job_dir, job, attempt, check)
        data = read(job_dir)
    judged, results = _judge(job, data, folder, rules, check, 'check_redo' if redo else 'check')
    kinds = {r['id']: r['kind'] for r in rules}
    missed = [r for r in results if kinds.get(r['id']) == 'prefer' and r['status'] == 'not_met']
    if missed and not redo:
        guidance = '; '.join(f'{r["id"]} ("{next(x["text"] for x in rules if x["id"] == r["id"])}"): {r["reason"]}'
                             for r in missed)
        data['prefer_redo'] = {'rules': [r['id'] for r in missed]}
        save(job_dir, data)
        kept = {'prefer_redo': data['prefer_redo'], 'lock_waited_s': data.get('lock_waited_s', 0),
                'since': data.get('since')}
        layout(ctx, job_dir, job, attempt, check, guidance=guidance, phase='layout_redo')
        data = read(job_dir)
        data.update(kept, lock_waited_s=kept['lock_waited_s'] + data.get('lock_waited_s', 0))
        data.pop('pages', None)
        save(job_dir, data)
        draw(ctx, job_dir, job, attempt, check)
        data = read(job_dir)
        judged, results = _judge(job, data, folder, rules, check, 'check_redo')
    data['rules'] = results
    data['checks'] = {'legible_at_phone_size': 'yes', 'covered_areas_clear': 'yes',
                       'faces_clear': judged['faces_clear'], 'notes': data['notes'] + [
                           'Text geometry checked against all requested platform profiles; profiles may be unconfirmed.',
                           'Faces and subject crop checked by the selected AI; no face detector used.',
                           'Colour converted to sRGB before drawing. White text on opaque dark panels.'] +
                       ([data['look_note']] if data.get('look_note') else []) +
                       ([f'Redone once for the preference(s) {", ".join(data["prefer_redo"]["rules"])}.']
                        if data.get('prefer_redo') else []) + list(judged.get('notes') or [])}
    data['alt_text'] = judged.get('alt_text') or 'Photo Story'
    data['post_text'] = judged.get('post_text') or {}
    save(job_dir, data)


def cost(folder):
    rows = [files.read_json(p) for p in Path(folder).glob('cost-*.json')]
    if not rows:
        return {}
    out = {'ai': rows[0]['ai'], 'measured': all(r['measured'] for r in rows),
           'steps': sum(r.get('steps', 0) for r in rows),
           'stages': [{'stage': r['stage'], 'wall_s': r['wall_s'],
                       **({'tokens': r['tokens']['total']} if r.get('tokens') else {})} for r in rows]}
    if out['measured']:
        out['tokens'] = {k: sum(r['tokens'].get(k, 0) for r in rows)
                        for k in ('input', 'cache_write', 'cache_read', 'output', 'total')}
        out['usd_api_equivalent'] = (sum(r['usd_api_equivalent'] for r in rows)
                                      if all(r.get('usd_api_equivalent') is not None for r in rows) else None)
    return out


def export(ctx, job_dir, job, attempt, check=lambda: None):
    folder, data, inp = work(job_dir), read(job_dir), job['inputs']
    made, text = [], []
    target_dir = Path(job_dir) / 'files'
    target_dir.mkdir(exist_ok=True)
    image_format = inp.get('format') or 'png'
    for n, page in enumerate(data['pages']):
        check()
        rel = f'files/story_9x16-{n + 1:02d}.{image_format}'
        target = Path(job_dir) / rel
        with drawing_lock(f'Studio still export {job["job_id"]}', check) as waited:
            data['lock_waited_s'] = data.get('lock_waited_s', 0) + waited
            with Image.open(page['path']) as image:
                image.convert('RGB').save(target, quality=95)
            privacy.ensure_clean(target)
        # Enforce every requested image cap. Unknown caps default to the safe 8 MB Story delivery ceiling.
        max_bytes = 8_000_000
        import letitedit.catalogs.platforms as platforms
        for p in inp.get('platforms') or []:
            pid = p['id'] if isinstance(p, dict) else p
            profile = platforms.load(pid)
            cap = ((profile.get('images') or {}).get('max_file_size_bytes') or {}).get('value')
            if cap:
                max_bytes = min(max_bytes, cap)
            if isinstance(p, dict) and p.get('max_mb'):
                max_bytes = min(max_bytes, p['max_mb'] * 1_000_000)
        if target.stat().st_size > max_bytes:
            target.unlink()
            raise state.StudioError('render_failed', 'The picture exceeds a platform image cap. Request jpg.',
                                    retry='after_change')
        made.append(files.output_entry(job_dir, rel, 'image', size='story_9x16', width=1080, height=1920,
                                       location_metadata='none'))
        text += page['text_items']
    poster_rel = 'proxy/poster.jpg'
    poster = Path(job_dir) / poster_rel
    poster.parent.mkdir(exist_ok=True)
    with drawing_lock(f'Studio still poster {job["job_id"]}', check) as waited:
        data['lock_waited_s'] = data.get('lock_waited_s', 0) + waited
        with Image.open(data['pages'][0]['path']) as image:
            image.thumbnail((720, 1280))
            image.save(poster, quality=92)
        privacy.ensure_clean(poster)
    made.append(files.output_entry(job_dir, poster_rel, 'poster', width=720, height=1280, location_metadata='none'))
    sources = []
    for p in data['pictures']:
        source = {'path': p['path'], 'file_id': library.file_id(p['path']), 'in': p['at'], 'out': p['at'],
                  'role': 'photo' if Path(p['path']).suffix.lower() in pixels.PHOTOS else 'still_frame'}
        if p.get('moment_id'):
            source['moment_ids'] = [p['moment_id']]
        sources.append(source)
    # The font's licence from the licence file beside it; a job before contract 1.6 gets unknown with it named (of_font)
    font_path = Path(drawing.fonts.font_file(data['font'], weight=700)[0])
    assets = [{'kind': 'font', 'what': data['font'], 'source': 'installed_font', 'path': str(font_path),
               'ai_generated': False,
               'licence': licences.of_font(font_path, job.get('contract_version'))},
              {'kind': 'graphic', 'what': 'Text panels and layout', 'source': 'letitedit', 'ai_generated': False,
               'licence': licences.block('made-by-letitedit')}]
    output = {'sets': [{'size': 'story_9x16', 'files': [f['path'] for f in made if f['role'] == 'image'],
                        'alt_text': data['alt_text']}], 'checks': data['checks']}
    if data['pages'][0].get('sticker'):
        output['sets'][0]['sticker_box'] = dict(zip(('x', 'y', 'w', 'h'), data['pages'][0]['sticker']))
    if data.get('post_text'):
        output['post_text'] = data['post_text']
    shared = {'provenance': {'sources': sources, 'assets': assets}, 'ai_labels': _labels(job),
              'music': {'tracks': [], 'policy_met': 'met' if inp.get('music') else 'no_policy'},
              'rules': data['rules'], 'text_items': text,
              'proxy': {'poster': poster_rel, 'width': 720, 'height': 1280}}
    measured_cost = cost(folder)
    measured_cost['waited_s'] = round(data.get('lock_waited_s', 0), 3)
    return {'__result__': True, 'output': output, 'outputs': made, 'extra': shared, 'cost': measured_cost,
            'versions': {'look': data['look_hash']} if data.get('look_hash') else {}}


STAGES = [('layout', layout), ('draw', draw), ('check', check), ('export', export)]
