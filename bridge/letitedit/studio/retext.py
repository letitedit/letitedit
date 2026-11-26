"""Text-only Studio revisions. No window, AI, transcript, score or review is started.

Work on a private copy and patch the stored XML properties, rather than compiling the whole timeline: compilation
can fit captions and rebuild effects unrelated to the requested word. A rejected item rolls back its own patch.
The export and delivery engines take their own PC-lock tickets.
"""
from __future__ import annotations

import copy
import html
import json
import os
import re
import shutil
import hashlib
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import letitedit.studio.capabilities as capabilities
import letitedit.studio.delivery as delivery
import letitedit.studio.files as files
import letitedit.studio.licences as licences
import letitedit.studio.media_privacy as privacy
import letitedit.studio.overlays as overlays
import letitedit.studio.short as short
import letitedit.studio.state as state


def _get(node, name, default=''):
    p = node.find(f"property[@name='{name}']")
    return p.text or default if p is not None else default


def _set(node, name, value):
    p = node.find(f"property[@name='{name}']")
    if p is None:
        p = ET.SubElement(node, 'property', name=name)
    p.text = str(value)


def _plain(text):
    return ' '.join(str(text).split())


def _time(value):
    return short._secs(str(value).replace(',', '.'))


class Refused(Exception):
    def __init__(self, reason, message):
        self.reason, self.message = reason, message


def _unusable(message):
    raise state.StudioError('from_job_unusable', message, stage='apply')


def earlier(job):
    import letitedit.studio.service as service
    folder = service.find(short._home(), job.get('from_job', ''))
    before = files.read_json(folder / 'result.json') if folder else None
    if not before or before.get('state') != 'done' or before.get('kind') not in ('short', 'revise', 'retext', 'still'):
        _unusable('Retext needs a finished Short, revision, text revision or batch item with its editable project.')
    if overlays.is_still(before):
        _unusable("Retext of a still is not installed yet. Its picture has not been changed.")
    return folder, before


def _platforms(job, before, earlier_job):
    given = (job.get('inputs') or {}).get('platforms') or (earlier_job.get('inputs') or {}).get('platforms')
    if given:
        return given
    # Older retexts may have no effective-target sidecar. Follow their specs rather than discarding inherited
    # max_mb caps when a revision's job.json names only changes. A platform file's record alone has no cap.
    import letitedit.studio.service as service
    seen = set()
    ref = earlier_job.get('from_job') or before.get('from_job')
    for _ in range(64):
        if not ref or ref in seen:
            break
        seen.add(ref)
        folder = service.find(short._home(), ref)
        if not folder:
            _unusable('The earlier delivery settings cannot be found. Retext cannot guess inherited platform size caps.')
        spec = files.read_json(folder / 'job.json') or {}
        given = (spec.get('inputs') or {}).get('platforms')
        if given:
            return given
        ref = spec.get('from_job')
    return [f['platform'] for f in before['output'].get('files', [])] or ['youtube_shorts']


def _inside(box, platform):
    x0, y0, x1, y1 = delivery.uncovered(platform)
    return (box['x'] >= x0 - 0.001 and box['y'] >= y0 - 0.001 and
            box['x'] + box['w'] <= x1 + 0.001 and box['y'] + box['h'] <= y1 + 0.001)


def _font(family, size, weight=400):
    import letitedit.catalogs.fonts as fonts
    # Never fetch a missing font during a word fix.
    if not fonts.family(family):
        raise Refused('font_missing_glyph', f'The saved font {family} is not installed; the item was left alone.')
    return fonts.pil_font(family, max(1, round(size)), weight)


def _glyphs(font, text):
    from fontTools.ttLib import TTFont
    with TTFont(str(font.path), fontNumber=getattr(font, 'index', 0)) as face:
        cmap = face.getBestCmap() or {}
        if any(ord(c) not in cmap for c in text if not c.isspace()):
            raise Refused('font_missing_glyph', 'The saved font cannot draw every character; the item was left alone.')


def _fits(text, font, width, height):
    from PIL import Image, ImageDraw
    _glyphs(font, text)
    b = ImageDraw.Draw(Image.new('L', (1, 1))).multiline_textbbox((0, 0), text or ' ', font=font, spacing=4)
    if b[2] - b[0] > width + 1 or b[3] - b[1] > height + 1:
        raise Refused('too_long', 'The new words would overflow the saved box; the item was left alone.')


def _overlay_layout(items, platforms, width, height, master=None, project=None):
    """Freeze every earlier item's placement before changing any text, including per-platform/proxy boxes."""
    layouts = {}
    for plat in platforms:
        preset = next((p for p in capabilities.platforms_list() if p['id'] == plat['id']), {})
        w, h = int(preset.get('width') or width), int(preset.get('height') or height)
        for key, ww, hh in ((plat['id'], w, h), ('proxy', 720 if width < height else 1280,
                                               1280 if width < height else 720)):
            if key in layouts:
                continue
            selected = [t for t in items if t.get('overlay') and
                        (not t['overlay'].get('platforms') or plat['id'] in t['overlay']['platforms']) and
                        any(f.get('applied') for f in t['overlay'].get('files', [])
                            if f.get('platform') == plat['id'] or f.get('proxy'))]
            laid = delivery.overlay_layout([(t['text'], t['overlay'].get('placement')) for t in selected], plat['id'],
                                           ww, hh, faces=short._faces(master) if master else (),
                                           zone=short._caption_zone(project) if project else None)
            layouts[key] = {'width': ww, 'height': hh, 'platform': plat['id'], 'items': {
                t['id']: {'x': x, 'y': y, 'size': size, 'box': box, 'note': note}
                for t, (x, y, size, box, _, note) in zip(selected, laid)}}
    return layouts


def _fit_overlay(item, text, layouts):
    for layout in layouts.values():
        got = layout['items'].get(item['id'])
        if not got or not got['box']:
            continue
        box = got['box']
        if not _inside(box, layout['platform']):
            raise Refused('too_long', 'The saved box overlaps this platform\'s buttons; the item was left alone.')
        pad = max(10, int(layout['height'] * 0.008))
        _fits(text, delivery._pil_font(got['size']), box['w'] * layout['width'] - 2 * pad,
              box['h'] * layout['height'] - 2 * pad)


def _srt_patch(text, item, new):
    """Replace exactly one matching cue, preserving its number, times and every other byte."""
    pat = re.compile(r'(?m)^(\d+\r?\n)([^\n]+ --> [^\n]+\r?\n)(.*?)(?=\r?\n\r?\n|\Z)', re.S)
    changed = False
    def patch(m):
        nonlocal changed
        a, b = m[2].strip().split(' --> ')
        if abs(_time(a) - item['start']) < 0.04 and abs(_time(b) - item['end']) < 0.3 and \
                _plain(m[3]) == _plain(item['text']):
            changed = True
            return m[1] + m[2] + _line_breaks(m[3], new)
        return m[0]
    return pat.sub(patch, text), changed


def _line_breaks(old, new):
    if '\n' in new or '\n' not in old:
        return new
    words, lines = new.split(), []
    for line in old.splitlines()[:-1]:
        n = len(line.split())
        lines.append(' '.join(words[:n]))
        words = words[n:]
    return '\n'.join(lines + [' '.join(words)])


def _ass_patch(script, item, new, width, height):
    styles, changed = {}, False
    for line in script.splitlines():
        if line.startswith('Style: '):
            p = line[7:].split(',')
            styles[p[0]] = p
    out = []
    for line in script.splitlines(keepends=True):
        if line.startswith('Dialogue: '):
            p = line.rstrip('\r\n')[10:].split(',', 9)
            visible = re.sub(r'\{[^}]*\}', '', p[9]).replace('\\N', '\n').replace('\\n', '\n')
            if abs(_time(p[1]) - item['start']) < 0.04 and abs(_time(p[2]) - item['end']) < 0.3 and \
                    _plain(visible) == _plain(item['text']):
                st = styles.get(p[3])
                if not st:
                    _unusable('The caption\'s saved ASS style is missing.')
                font = _font(st[1], float(st[2]), 600 if st[7] not in ('0', 'false') else 400)
                margin_l, margin_r = float(st[19]), float(st[20])
                wrapped = _line_breaks(visible, new)
                _fits(wrapped, font, width - margin_l - margin_r, height)
                if any(c in new for c in ('{', '}', '\\')):
                    raise Refused('font_missing_glyph', 'ASS control characters cannot be used as literal words here.')
                tags = ''.join(re.findall(r'\{[^}]*\}', p[9]))
                p[9] = tags + wrapped.replace('\n', '\\N')
                line = 'Dialogue: ' + ','.join(p) + ('\n' if line.endswith('\n') else '')
                changed = True
        out.append(line)
    return ''.join(out), changed


def _replace_leaf(value, old, new):
    """Only a complete stored text value (or a quoted source literal), never a substring in unrelated code."""
    count = 0
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ('file', 'path', 'source', 'clip', 'kit', '_look_kit'):
                out[k] = v
            else:
                out[k], n = _replace_leaf(v, old, new)
                count += n
        return out, count
    if isinstance(value, list):
        out = []
        for v in value:
            v, n = _replace_leaf(v, old, new)
            out.append(v)
            count += n
        return out, count
    if isinstance(value, str):
        if _plain(value) == _plain(old):
            return new, 1
        for quote in ('"', "'", '`'):
            literal = quote + old.replace('\\', '\\\\').replace(quote, '\\' + quote) + quote
            if value.count(literal) == 1:
                encoded = new.replace('\\', '\\\\').replace(quote, '\\' + quote).replace('\n', '\\n')
                if quote == '`':
                    encoded = encoded.replace('${', '\\${')
                return value.replace(literal, quote + encoded + quote), 1
        literal = '>' + html.escape(old) + '<'
        if value.count(literal) == 1:
            return value.replace(literal, '>' + html.escape(new) + '<'), 1
    return value, 0


def _render(recipe, prop, doc, project):
    import letitedit.pictures.graphics as graphics
    import letitedit.timeline.made as made
    import letitedit.core.render_lock as lock
    import letitedit.looks.look_library as look_library
    if prop == 'letitedit_ai:graphic':
        with lock.slot('Studio retext graphic'):
            return graphics.render(recipe, doc.width, doc.height, doc.fps,
                                   kit=look_library.project_kit({prop.get('name'): prop.text for prop in doc.main.findall('property')}),
                                   out_dir=project.parent / 'graphics')
    # motion's engine takes the lock itself; ASS's direct renderer needs a ticket.
    if recipe.get('kind') == 'motion':
        result = made.render(recipe, doc.width, doc.height, doc.fps, project.parent / 'made')
        if result.get('fallback') or result.get('notes'):
            _unusable('The saved motion could not be redrawn exactly: ' + '; '.join(result.get('notes') or []))
        return result
    if recipe.get('kind') != 'ass':
        _unusable('This drawn item has no supported text recipe.')
    out = project.parent / 'made' / ('retext-' + hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16] + '.mov')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=project.parent) as tmp:
        script = Path(tmp) / 'layer.ass'
        script.write_text(made.ass_document(recipe['script'], doc.width, doc.height), encoding='utf-8')
        vf = 'subtitles=layer.ass:alpha=1'
        fonts = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
        if fonts.is_dir():
            vf += ":fontsdir='" + str(fonts).replace('\\', '/').replace(':', '\\:') + "'"
        # The delivery runner caps the encoder to four threads and takes its own PC-lock ticket.
        import letitedit.core.render_lock as render_lock
        r = render_lock.run_render([made.ffmpeg_exe(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                                   f'color=c=black@0.0:s={doc.width}x{doc.height}:r={doc.fps}:d={recipe["len"]:.3f},format=rgba',
                                   '-vf', vf, '-c:v', 'qtrle', '-pix_fmt', 'argb', '-threads', '4', str(out)],
                                  what='Studio retext caption layer', heavy=True, cwd=tmp, timeout=1800,
                                  capture_output=True, text=True, creationflags=delivery._flags())
        if r.returncode:
            raise state.StudioError('render_failed', 'The caption layer could not be redrawn.', detail=r.stderr[-1500:])
    return {'path': str(out)}


def _ink_box(path, at, width, height, folder):
    from PIL import Image
    import letitedit.core.media as media
    out = Path(folder) / 'ink.png'
    delivery._run([media.ffmpeg(), '-v', 'error', '-y', '-ss', str(max(0, at)), '-i', str(path), '-frames:v', '1',
                   '-vf', 'alphaextract', '-threads', '4', str(out)], 'retext ink check')
    with Image.open(out) as im:
        b = im.point(lambda v: 255 if v > 16 else 0).getbbox()
    if not b:
        _unusable('The changed text did not draw any visible ink.')
    return dict(zip(('x', 'y', 'w', 'h'), (b[0] / width, b[1] / height, (b[2] - b[0]) / width,
                                          (b[3] - b[1]) / height)))


def _check_box(box, item, platforms):
    for p in platforms:
        if not _inside(box, p['id']):
            raise Refused('too_long', 'The new words would overlap the platform\'s covered area; the item was left alone.')
    saved = item.get('box')
    if saved and (box['x'] < saved['x'] - 0.002 or box['y'] < saved['y'] - 0.002 or
                  box['x'] + box['w'] > saved['x'] + saved['w'] + 0.002 or
                  box['y'] + box['h'] > saved['y'] + saved['h'] + 0.002):
        raise Refused('too_long', 'The new words would overflow the saved box; the item was left alone.')


def _changed_ink(old, new, doc, item, platforms, folder, start=0, duration=1):
    """Check the actual redraw at three times: its changed pixels must stay inside the item's saved box. This also
    catches code that moves a neighboring label when its string grows; font metrics alone cannot catch that."""
    from PIL import Image, ImageChops
    import letitedit.core.media as media
    union = None
    stills = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
    if not Path(old).is_file() or not Path(new).is_file():
        _unusable('The earlier drawn source or its redraw is missing; its fit cannot be compared.')
    for n, fraction in enumerate((.2, .5, .8)):
        pictures = []
        for label, src in [('old', old), ('new', new)]:
            p = Path(src)
            if p.suffix.lower() not in stills:
                p = Path(folder) / f'retext-{label}-{n}.png'
                delivery._run([media.ffmpeg(), '-v', 'error', '-y', '-ss', str(start + duration * fraction),
                               '-i', str(src), '-frames:v', '1', '-pix_fmt', 'rgba', '-threads', '4', str(p)],
                              'retext redraw fit')
            with Image.open(p) as im:
                pictures.append(im.convert('RGBA'))
        diff = ImageChops.difference(*pictures).split()
        mask = diff[0]
        for channel in diff[1:]:
            mask = ImageChops.lighter(mask, channel)
        b = mask.point(lambda v: 255 if v > 16 else 0).getbbox()
        if b:
            union = b if union is None else (min(union[0], b[0]), min(union[1], b[1]),
                                             max(union[2], b[2]), max(union[3], b[3]))
    if union:
        _check_box({'x': union[0] / doc.width, 'y': union[1] / doc.height,
                    'w': (union[2] - union[0]) / doc.width, 'h': (union[3] - union[1]) / doc.height}, item, platforms)


def _scene_patch(prod, doc, project, item, text, platforms):
    import letitedit.pictures.code_scenes as scenes
    import letitedit.pictures.motion as motion
    marker = json.loads(_get(prod, 'letitedit_ai:code_scene'))
    old = scenes.revision_dir(project, marker['id'], marker['revision'])
    data = files.read_json(old / 'scene.json') or {}
    spec, n = _replace_leaf(data.get('spec') or {}, item['text'], text)
    if n == 0:
        return False
    if n != 1:
        _unusable(f"{item['id']} matches more than one value in its saved scene.")
    box = item.get('box')
    if not box:
        _unusable(f"{item['id']} has no saved text box for its scene.")
    _check_box(box, item, platforms)
    p = spec.get('params') or {}
    _fits(text, _font(p.get('font_family') or 'Montserrat', p.get('font_size') or 54),
          box['w'] * doc.width, box['h'] * doc.height)
    page = old / 'page'
    saved = motion.saved_parts(page, data['spec'])
    revision = motion.digest(spec, doc.width, doc.height, doc.fps, saved=saved)
    folder = scenes.revision_dir(project, marker['id'], revision)
    if not (folder / 'scene.json').exists():
        files.write_json(folder / 'scene.json', {'format': 'letitedit-code-scene/1', 'spec': spec,
                                               'width': doc.width, 'height': doc.height, 'fps': doc.fps,
                                               'revision': revision})
        motion.build_page(spec, doc.width, doc.height, doc.fps, folder / 'page', saved=saved, earlier=page)
    # The same cut-out masks are needed: changing a word never changes the person in front of the scene.
    for masks in old.glob('masks*'):
        if masks.is_dir() and not (folder / masks.name).exists():
            shutil.copytree(masks, folder / masks.name)
    old_movie = scenes.render_full(project, marker)['file']
    new_movie = scenes.render_full(project, dict(id=marker['id'], revision=revision))['file']
    _changed_ink(old_movie, new_movie, doc, item, platforms, project.parent,
                 duration=float(spec.get('duration') or 1))
    _set(prod, 'letitedit_ai:code_scene', json.dumps(dict(id=marker['id'], revision=revision)))
    return True


def _has_text(prod, item, project):
    for f in prod.findall('filter'):
        if _get(f, 'mlt_service') in ('dynamictext', 'qtext') and _plain(_get(f, 'argument')) == item['text']:
            return True
    for prop in ('letitedit_ai:made', 'letitedit_ai:graphic'):
        if _get(prod, prop) and _replace_leaf(json.loads(_get(prod, prop)), item['text'], item['text'])[1]:
            return True
    if _get(prod, 'letitedit_ai:code_scene'):
        import letitedit.pictures.code_scenes as scenes
        marker = json.loads(_get(prod, 'letitedit_ai:code_scene'))
        data = files.read_json(scenes.revision_dir(project, marker['id'], marker['revision']) / 'scene.json') or {}
        return bool(_replace_leaf(data.get('spec', {}), item['text'], item['text'])[1])
    return False


def patch_item(doc, project, item, text, platforms):
    """Patch only matching properties. A caller uses a fresh Doc per item, so a refusal commits nothing."""
    touched, rendered = False, False
    if item['kind'] == 'caption':
        for f in doc.main.findall('filter'):
            if _get(f, 'mlt_service') == 'subtitle_feed':
                value, found = _srt_patch(_get(f, 'text'), item, text)
                if found:
                    _set(f, 'text', value)
                    touched = True
    # Bind to the played occurrence, not an unused producer in the bin or another occurrence with the same words.
    for _, pl, _, _ in doc.tracks():
        pos = 0
        for kind, entry, frames in doc.entries(pl):
            if kind == 'blank':
                pos += frames
                continue
            prod = doc.elements[entry.get('producer')]
            a = doc.f(entry.get('in')) or 0
            b = doc.f(entry.get('out'))
            b = b if b is not None else doc.f(prod.get('out')) or 0
            start, end = pos / doc.fps, (pos + b - a + 1) / doc.fps
            pos += b - a + 1
            if not start - 0.04 <= item['start'] < end:
                continue
            if item['kind'] != 'caption' and not _has_text(prod, item, project):
                continue
            references = doc.root.findall(f".//entry[@producer='{prod.get('id')}']")
            # A producer may be played twice. Its property change belongs to only this played occurrence.
            if len(references) > 1 and item['kind'] != 'caption':
                clone = copy.deepcopy(prod)
                clone.set('id', prod.get('id') + '-retext-' + hashlib.sha256(item['id'].encode()).hexdigest()[:8])
                doc.root.insert(list(doc.root).index(doc.main), clone)
                doc.elements[clone.get('id')] = clone
                entry.set('producer', clone.get('id'))
                prod = clone
            if _get(prod, 'letitedit_ai:code_scene') and _scene_patch(prod, doc, project, item, text, platforms):
                touched = rendered = True
            for prop in ('letitedit_ai:made', 'letitedit_ai:graphic'):
                raw = _get(prod, prop)
                if not raw:
                    continue
                recipe = json.loads(raw)
                if recipe.get('kind') == 'ass':
                    local = dict(item, start=item['start'] - start + a / doc.fps,
                                 end=item['end'] - start + a / doc.fps)
                    value, found = _ass_patch(recipe['script'], local, text, doc.width, doc.height)
                    recipe['script'] = value
                else:
                    recipe, count = _replace_leaf(recipe, item['text'], text)
                    found = count == 1
                    if count > 1:
                        _unusable(f"{item['id']} matches more than one stored text value; no ambiguous redraw was made.")
                if not found:
                    continue
                result = _render(recipe, prop, doc, project)
                if recipe.get('kind') == 'ass':
                    at = (local['start'] + min(local['end'], local['start'] + 0.5)) / 2
                    box = _ink_box(result['path'], at, doc.width, doc.height, project.parent)
                    _check_box(box, item, platforms)
                else:
                    # General graphics must have a known box and a font, so fitting never silently invents a layout.
                    p = recipe.get('params') or recipe.get('spec', {}).get('params') or {}
                    box = item.get('box')
                    if not box:
                        _unusable(f"{item['id']} has no saved text box; its redraw cannot be checked safely.")
                    _check_box(box, item, platforms)
                    font = _font(p.get('font_family') or p.get('font') or 'Montserrat', p.get('font_size') or 54)
                    _fits(text, font, box['w'] * doc.width, box['h'] * doc.height)
                    _changed_ink(_get(prod, 'resource'), result['path'], doc, item, platforms, project.parent,
                                 start=a / doc.fps, duration=(b - a + 1) / doc.fps)
                _set(prod, prop, json.dumps(recipe, ensure_ascii=False))
                _set(prod, 'resource', result['path'])
                if prop == 'letitedit_ai:graphic':
                    recipe['file'] = result['path']
                    _set(prod, prop, json.dumps(recipe, ensure_ascii=False))
                touched = rendered = True
            for f in prod.findall('filter'):
                if _get(f, 'mlt_service') not in ('dynamictext', 'qtext') or _plain(_get(f, 'argument')) != item['text']:
                    continue
                geometry = re.findall(r'-?[\d.]+', _get(f, 'geometry'))
                if len(geometry) < 4:
                    _unusable(f"{item['id']} has no saved text geometry.")
                x, y, w, h = map(float, geometry[:4])
                box = {'x': x / doc.width, 'y': y / doc.height, 'w': w / doc.width, 'h': h / doc.height}
                _check_box(box, item, platforms)
                font = _font(_get(f, 'family') or 'Montserrat', float(_get(f, 'size') or 54))
                _fits(text, font, w, h)
                _set(f, 'argument', text)
                touched = True
    if not touched:
        _unusable(f"{item['id']} cannot be matched to its saved text source; nothing was guessed.")
    return 'redrawn' if rendered and item['editable'] == 'remake' else 'changed'


def apply(ctx, job_dir, job, attempt, check=lambda: None):
    import letitedit.timeline.edit_script as es
    before_dir, before = earlier(job)
    project = before_dir / before['output'].get('project', '')
    if not project.is_file() or project.suffix.lower() != '.mlt':
        _unusable('The earlier editable project is missing; its delivered video cannot be used to change words.')
    old, new = project.parent, Path(job_dir) / 'work' / 'project'
    if new.resolve().is_relative_to(old.resolve()):
        _unusable('The new job must be outside the earlier project folder; it cannot be copied inside itself.')
    if new.exists():
        shutil.rmtree(new)
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(old, new, ignore=shutil.ignore_patterns('lease.json', '*.export.json'))
    short._rewrite(new, old, new)
    project = new / project.name
    original = project.read_bytes()
    earlier_job = files.read_json(before_dir / 'job.json') or {}
    targets = (job.get('inputs') or {}).get('platforms') or files.read_json(old / 'retext-targets.json') or \
        _platforms(job, before, earlier_job)
    plats = [p if isinstance(p, dict) else {'id': p} for p in targets]
    items = copy.deepcopy(before.get('text_items') or [])
    doc = es.Doc(project)
    old_master = before_dir / next((o['video'] for o in before['output'].get('files', []) if o.get('video')), '')
    saved = files.read_json(old / 'retext-layouts.json')
    layouts = _overlay_layout(items, plats, doc.width, doc.height,
                              old_master if old_master.is_file() else None, project)
    # Retexts retain their original boxes and type size, even after a shorter word made room in them.
    layouts.update({k: v for k, v in (saved or {}).items() if k in layouts})
    applied = []
    for change in job['inputs']['changes']:
        check()
        item = next((t for t in items if t['id'] == change['id']), None)
        entry = {'id': change['id']}
        try:
            if not item:
                raise Refused('unknown_id', 'There is no text item with this id in the earlier job.')
            if item['text'] == change['text']:
                entry['status'] = 'unchanged_same_text'
            elif item['editable'] == 'baked':
                raise Refused('baked', 'These words are inside a picture or footage, without a saved drawing source.')
            elif item.get('max_chars') is not None and len(change['text']) > item['max_chars']:
                raise Refused('too_long', 'The new words exceed this item\'s saved character limit.')
            elif item.get('overlay'):
                _fit_overlay(item, change['text'], layouts)
                entry['status'] = 'changed'
                item['text'] = change['text']
            else:
                doc = es.Doc(project)
                entry['status'] = patch_item(doc, project, item, change['text'], plats)
                doc.tree.write(project, encoding='utf-8', xml_declaration=True)
                item['text'] = change['text']
        except Refused as e:
            entry.update(status='refused', reason=e.reason, message=e.message)
        applied.append(entry)
    files.write_json(new / 'retext-layouts.json', layouts)
    files.write_json(new / 'retext-targets.json', plats)
    (new / 'before-retext.mlt').write_bytes(original)
    run = {'project': str(project), 'folder': str(new), 'from': str(before_dir), 'before': before,
           'earlier_job': {**earlier_job, 'inputs': {**earlier_job.get('inputs', {}), 'platforms': plats}},
           'items': items, 'applied': applied, 'layouts': layouts, 'since': time.time()}
    # Contract overlays are drawn only by delivery. Reuse the clean earlier master for an overlay-only fix: an
    # old unsaved project (such as T283's rough cut) must never replace the actual delivered picture and sound.
    changed = {a['id'] for a in applied if a['status'] in ('changed', 'redrawn')}
    overlay_ids = {t['id'] for t in items if t.get('overlay')}
    if changed <= overlay_ids:
        clean = before_dir / 'master.mp4' if before.get('kind') == 'retext' else short.final_export(old, 0)
        if clean and Path(clean).is_file():
            run['reuse_master'] = str(clean)
    short._save_run(ctx, run)


def _decide(job, run, made, proxy=False):
    job = short._overlay_job(job, run)
    view = {**overlays.carry_media(run['before']), 'output': {'files': made}}
    if proxy:
        view['proxy'] = {'video': 'proxy/proxy.mp4'}
    decided = overlays.decide(job, view, given=overlays.carried(run['items']),
                              duration_s=(run['before'].get('choices') or {}).get('duration_s'))
    for old, new in zip([t for t in run['items'] if t.get('overlay')], decided):
        new['id'] = old['id']
        if 'max_chars' in old:
            new['max_chars'] = old['max_chars']
        if old.get('box'):
            new['box'] = old['box']
    return decided


def _drawn(decided, layout, key):
    out = []
    for t in decided:
        f = next((f for f in t['overlay']['files'] if (key == 'proxy' and f.get('proxy')) or
                  (key != 'proxy' and f.get('platform') == key)), None)
        got = layout['items'].get(t['id'])
        if f and f.get('applied') and got and got.get('box'):
            out.append((t['text'], got['x'], got['y'], got['size']))
            t['box'] = got['box']
        elif f and f.get('applied'):
            short._note_placement(f, delivery.NOT_PLACED, False)
    return out


def export(ctx, job_dir, job, attempt, check=lambda: None):
    run = short._run(ctx)
    project = Path(run['project'])
    master = Path(job_dir) / 'master.mp4'
    if run.get('reuse_master'):
        shutil.copy2(run['reuse_master'], master)
    else:
        # A full-frame alpha caption layer can commit several GB in each picture renderer. Retext keeps one picture
        # chunk (the unchanged mix is already cached), rather than launching several copies of that layer at once.
        duration = float((run['before'].get('choices') or {}).get('duration_s') or 1)
        master = short._export_project(project, master, check, chunk_s=max(60, duration + 1))
    info = delivery.probe(master) or {}
    plats = short._platforms(job, run)
    decided = _decide(job, run, [{'platform': p['id'], 'status': 'made'} for p in plats])
    presets = {p['id']: p for p in capabilities.platforms_list()}
    made, outs = [], []
    for p in plats:
        check()
        preset = presets.get(p['id'], {})
        w, h = int(preset.get('width') or 1080), int(preset.get('height') or 1920)
        if (w > h) != (info['width'] > info['height']):
            made.append({'platform': p['id'], 'status': 'refused', 'reason': 'shape_differs'})
            continue
        if preset.get('max_seconds') and info['duration_s'] > preset['max_seconds'] + 0.05:
            made.append({'platform': p['id'], 'status': 'refused', 'reason': 'too_long_for_platform'})
            continue
        dst = Path(job_dir) / 'files' / f"{p['id']}.mp4"
        cap = int(p['max_mb'] * 1_000_000) if p.get('max_mb') else preset.get('max_bytes')
        layout = run['layouts'][p['id']]
        got = delivery.fit_under(master, dst, w, h, preset.get('fps') or 30, cap,
                                 _drawn(decided, layout, p['id']), what=f"the {p['id']} retext file")
        if got['status'] != 'made':
            made.append({'platform': p['id'], 'status': 'refused', 'reason': got['reason'], 'message': got['why']})
            continue
        privacy.ensure_clean(dst)
        delivery.check_sdr(dst)
        entry = {'platform': p['id'], 'status': 'made', 'video': short._rel(job_dir, dst)}
        if got.get('tonemapped'):
            entry['tonemapped'] = True
        made.append(entry)
        outs.append(files.output_entry(job_dir, entry['video'], 'video', location_metadata='none',
                                       **delivery.describe(dst, p['id'])))
    deliver = run['earlier_job'].get('inputs', {}).get('deliver') or {}
    captions = [(t['start'], t['end'], t['text']) for t in run['items'] if t['kind'] == 'caption']
    for field, role, name in [('srt', 'srt', 'captions.srt'), ('cover', 'cover', 'cover.jpg')]:
        if not deliver.get(field, True) or (field == 'srt' and not captions):
            continue
        dst = Path(job_dir) / 'files' / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if field == 'srt':
            dst.write_text(short._srt(captions), encoding='utf-8')
        else:
            delivery.frame(master, min(0.5, info['duration_s'] / 2), dst, width=1080)
            privacy.ensure_clean(dst)
        outs.append(files.output_entry(job_dir, short._rel(job_dir, dst), role,
                                       **({'location_metadata': 'none'} if field == 'cover' else {})))
        for entry in made:
            if entry['status'] == 'made':
                entry[field] = short._rel(job_dir, dst)
    run.update(master=str(master), made=made, outs=outs)
    short._save_run(ctx, run)


def proxy(ctx, job_dir, job, attempt, check=lambda: None):
    check()
    run = short._run(ctx)
    before = run['before']
    decided = _decide(job, run, run['made'])
    proxy_items = _decide(job, run, [], proxy=True)
    # Decide conditions again for the proxy itself, even when platform delivery was refused.
    for t in proxy_items:
        t['overlay']['files'] = [f for f in t['overlay']['files'] if f.get('proxy')]
    vid, poster = Path(job_dir) / 'proxy' / 'proxy.mp4', Path(job_dir) / 'proxy' / 'poster.jpg'
    layout = run['layouts']['proxy']
    got = delivery.proxy(run['master'], vid, poster, overlays=_drawn(proxy_items, layout, 'proxy'))
    for p in (vid, poster):
        privacy.ensure_clean(p)
    delivery.check_sdr(vid)
    for t, p in zip(decided, proxy_items):
        t['overlay']['files'] += p['overlay']['files']
    outs = run['outs'] + [files.output_entry(job_dir, short._rel(job_dir, vid), 'proxy', location_metadata='none',
                                            **delivery.describe(vid)),
                          files.output_entry(job_dir, short._rel(job_dir, poster), 'poster', location_metadata='none'),
                          files.output_entry(job_dir, short._rel(job_dir, run['project']), 'project')]
    changed = sum(a['status'] in ('changed', 'redrawn') for a in run['applied'])
    output = {k: copy.deepcopy(v) for k, v in before['output'].items()
              if k in ('post_text', 'left_out', 'summary')}
    output.update(files=run['made'], project=short._rel(job_dir, run['project']), applied=run['applied'],
                  revision_of=job['from_job'], what_changed=f'{changed} text item(s) changed. Cut, picture and sound kept.')
    extra = {**overlays.carry_media(before), 'rules': copy.deepcopy(before.get('rules') or []),
             'choices': copy.deepcopy(before.get('choices') or {}),
             'text_items': [t for t in run['items'] if not t.get('overlay')] + decided,
             'review': {'verdict': 'not_reviewed', 'plain': 'Only text changed. No AI or review ran.'},
             'proxy': {'video': short._rel(job_dir, vid), 'poster': short._rel(job_dir, poster),
                       'width': got['width'], 'height': got['height'], 'bytes': vid.stat().st_size}}
    # a font the earlier result lists carries its licence as this job's contract_version may see it (contract 1.6)
    licences.fonts_for_version(extra.get('provenance'), job.get('contract_version'))
    # Review evidence belongs to the earlier job; keep those relative paths usable without editing its files.
    for rule in extra['rules']:
        for frame in rule.get('frames') or []:
            src = Path(run['from']) / frame['path']
            dst = Path(job_dir) / 'evidence' / (hashlib.sha256(frame['path'].encode()).hexdigest()[:8] + '-' +
                                               Path(frame['path']).name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            frame['path'] = short._rel(job_dir, dst)
            outs.append(files.output_entry(job_dir, frame['path'], 'evidence', location_metadata='none'))
    return {'__result__': True, 'output': output, 'extra': extra, 'outputs': outs, 'warnings': [],
            'versions': {k: v for k, v in before.get('versions', {}).items() if k == 'look'},
            'cost': {'tokens': dict(input=0, cache_write=0, cache_read=0, output=0, total=0),
                     'steps': 0, 'usd_api_equivalent': 0, 'measured': True}}


STAGES = [('apply', apply), ('export', export), ('proxy', proxy)]
