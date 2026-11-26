"""Fast, truthful checks of a saved timeline, rendered by melt (the same engine as the final export).

Nothing here needs the editor window or changes the project:
  frames(project, ...)  -> labelled contact sheet of exactly what the export shows at chosen moments
  range_clip(project, ...) -> small low-res MP4 of a range plus a filmstrip, for motion
  audio(project, ...)   -> loudness report (whole mix, optional music/dialogue stems), quiet gaps, peaks, graph
  qc(project, ...)      -> automatic findings: missing media, risky filters, blank/black/squeezed frames, captions
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import letitedit.core.font_env as font_env
import letitedit.timeline.timeline_model as tm

font_env.ensure()  # melt loads the font library itself (LETITEDIT_FONT_DIRS), whatever Windows loaded at sign-in

APP = Path((_SAI_ROOT + '\\app'))
MELT = APP / 'melt.exe'
FFMPEG = APP / 'ffmpeg.exe'
FFPROBE = APP / 'ffprobe.exe'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------- project resolution

READ_STATE: dict[str, dict] = {}   # a snapshot resolve() read -> what it was (state_of); T298


def resolve(project, saved=False):
    """Accept a .mlt path, a managed episode/cut folder, or 'live' (the open editor, unsaved changes included).
    Returns (Timeline, path_used). A project that is open in a letitedit window is read as that window shows it now,
    unsaved changes included (a snapshot file; T298), so every check sees what timeline_read sees; saved=True reads
    the saved file whatever is open. state_of(path_used) says which state was read."""
    if str(project).strip().lower() in ('live', 'current', 'editor'):
        return _live_snapshot()
    path = Path(project)
    if path.is_dir():
        from letitedit.timeline import episodes as p
        root, data = p.load(path)
        if not data.get('timeline'):
            raise ValueError('This episode/cut has no timeline yet')
        path = p.owned(root, data['timeline'])
    if not path.is_file():
        raise FileNotFoundError(f'No project at {path}')
    if not saved:
        import letitedit.app.live_edit as live_edit
        row = live_edit.window_for(path)
        if row:
            snap, rev = live_edit.snapshot(row['instance_id'])
            import letitedit.pictures.code_scenes as code_scenes
            code_scenes.SNAPSHOT_OF[str(snap)] = str(path)   # where this window's scenes are kept
            READ_STATE[str(snap)] = {**live_edit.state_of(row, rev), 'project': str(path)}
            return tm.load(snap), Path(snap)
    return tm.load(path), path


@contextlib.contextmanager
def as_window_shows(project):
    """Inside it, every edit-script read of `project` (es.read, and so cut_words, edge_pins, ending_findings,
    false_starts, edit_quality_findings, audio_signature and the rest) reads the project as the letitedit window that
    has it open shows it now, unsaved changes included, from one snapshot taken on entry; the same state an export
    renders. With no window (or no .mlt project), the saved file, as always. Yields the state read (state_of)."""
    import letitedit.timeline.edit_script as es
    source, state = None, {'state': 'saved'}
    if project and str(project).lower().endswith('.mlt') and Path(project).is_file():
        try:
            import letitedit.app.live_edit as live_edit
            snap, read = live_edit.current(project)
            if read.get('state') == 'live':
                source, state = snap, read
        except Exception:  # noqa: BLE001 - no window to read: the saved file, as before
            source = None
    if source is None:
        yield state
        return
    READ_STATE[str(source)] = state
    with es.reading_as(project, source):
        yield state


def state_of(path_used):
    """Which state a resolve() read (T298): {'state': 'live', 'window', 'unsaved_changes', 'revision', 'project'} for
    an open window's snapshot, else {'state': 'saved'}."""
    return dict(READ_STATE.get(str(path_used)) or {'state': 'saved'})


def reported(path_used):
    """A reply's project and read fields (T298): the saved project's path (never a snapshot's) and which state."""
    st = state_of(path_used)
    project = st.pop('project', None) or str(path_used)
    return {'project': project, 'read': st}


def _live_snapshot():
    import letitedit.timeline.letitedit_extras as extras
    from letitedit.app.letitedit_client import ShotcutBridge
    with ShotcutBridge(timeout=30) as b:
        state = b.call('state')
        xml = b.call('project_xml')
    profile = state.get('profile') or {}
    xml = extras.inject_profile(xml if isinstance(xml, str) else xml.get('xml', ''),
                                {'width': profile.get('width', 1920), 'height': profile.get('height', 1080), 'fps': profile.get('fps', 30)})
    out = CACHE / 'live' / f'live-{uuid.uuid4().hex[:8]}.mlt'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding='utf-8')
    if state.get('project'):
        import letitedit.pictures.code_scenes as code_scenes
        code_scenes.SNAPSHOT_OF[str(out)] = state['project']   # where this window's scenes are kept
    READ_STATE[str(out)] = {'state': 'live', 'window': 'main', 'unsaved_changes': bool(state.get('modified')),
                            **({'project': state['project']} if state.get('project') else {})}
    return tm.load(out), out


def _work(kind):
    d = CACHE / kind / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    d.mkdir(parents=True, exist_ok=True)
    import letitedit.core.cache_budget as cache_budget
    cache_budget.trim_soon(CACHE)     # T95: every new folder trims old ones, beside this call
    return d


def _run(args, timeout=1800, cwd=None):
    """Run a program; a melt run (a render: frames, a range, the mix) holds the PC render lock, one at a time in this
    process, on the export's thread cap at below-normal priority (render_lock.run_render)."""
    import letitedit.core.render_lock as render_lock
    r = render_lock.run_render([str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                               cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f'{Path(str(args[0])).name} failed ({r.returncode}): {(r.stderr or r.stdout)[-1500:]}')
    return r


def fmt(seconds):
    seconds = max(0.0, seconds)
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def _profile_xml(profile, width=None, height=None):
    w = width or profile['width']
    h = height or profile['height']
    g = math.gcd(w, h)
    return (f'<profile width="{w}" height="{h}" progressive="{profile["progressive"]}" sample_aspect_num="1" sample_aspect_den="1" '
            f'display_aspect_num="{w // g}" display_aspect_den="{h // g}" frame_rate_num="{profile["frame_rate_num"]}" '
            f'frame_rate_den="{profile["frame_rate_den"]}" colorspace="{profile["colorspace"]}"/>')


# ---------------------------------------------------------------------------- frames

def render_frames(timeline, path, frames, out_dir, size=None):
    """Render exact frames of the saved timeline with one melt run. Returns list of PNG paths in order. size: (width,
    height) to draw them smaller (the export engine scales the whole picture, as a preview export does)."""
    frames = [max(0, min(timeline.frames - 1, int(f))) for f in frames]
    import letitedit.pictures.code_scenes as code_scenes
    path = code_scenes.looks_path(path, frames=frames, work=out_dir)   # a code scene in view is shown, not left empty
    wrapper = out_dir / 'frames.mlt'
    entries = '\n'.join(f'    <entry producer="cut" in="{f}" out="{f}"/>' for f in frames)
    wrapper.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C">\n  ' + _profile_xml(timeline.profile) + '\n'
        f'  <producer id="cut"><property name="resource">{_xml_escape(str(Path(path).resolve()))}</property>'
        '<property name="mlt_service">xml</property></producer>\n'
        f'  <playlist id="sheet">\n{entries}\n  </playlist>\n</mlt>\n', encoding='utf-8')
    try:
        _run([MELT, '-quiet', wrapper, '-consumer', f'avformat:{out_dir / "f_%04d.png"}', 'vcodec=png', 'an=1', 'audio_off=1',
              *(__import__('letitedit.timeline.render_queue', fromlist=["*"]).preview_args(timeline.profile, size) if size else [])],
             timeout=120 + 6 * len(frames))
    finally:
        shutil.rmtree(out_dir / 'scene-look', ignore_errors=True)   # melt's input only: no reply names these (T95)
    pngs = sorted(out_dir.glob('f_*.png'))
    if len(pngs) < len(frames):
        raise RuntimeError(f'melt rendered {len(pngs)} of {len(frames)} frames')
    return pngs[:len(frames)]


def _xml_escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _label_for(timeline, frame):
    it = timeline.item_at(frame)
    return f'{fmt(frame / timeline.fps)}  {it.name[:28] if it else "(nothing)"}'


def contact_sheet(images, labels, cols=4, tile_w=480, flag=None):
    from PIL import Image, ImageDraw
    tiles = []
    for i, p in enumerate(images):
        im = Image.open(p).convert('RGB')
        th = round(im.height * tile_w / im.width)
        im = im.resize((tile_w, th))
        d = ImageDraw.Draw(im)
        text = labels[i]
        d.rectangle((0, 0, 7 * len(text) + 8, 15), fill=(0, 0, 0))
        d.text((4, 2), text, fill=(255, 230, 0))
        if flag and flag[i]:
            d.rectangle((0, 0, tile_w - 1, th - 1), outline=(255, 40, 40), width=4)
        tiles.append(im)
    th = tiles[0].height
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * tile_w, rows * th), (28, 28, 28))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * tile_w, (i // cols) * th))
    return sheet


def pick_frames(timeline, times_s=None, every_s=None, count=None, at_cuts=False):
    if times_s:
        return [round(t * timeline.fps) for t in times_s]
    if at_cuts:
        v1 = timeline.v1()
        return [it.start + it.length // 2 for it in v1.items] if v1 else [0]
    if every_s:
        step = max(1, round(every_s * timeline.fps))
        return list(range(step // 2, timeline.frames, step))
    n = count or 12
    return [round((i + 0.5) * timeline.frames / n) for i in range(n)]


def frames(project, times_s=None, every_s=None, count=None, at_cuts=False, cols=4, tile_w=480, max_frames=None,
           per_page=48):
    """Contact sheets of exactly what the export will show, `per_page` frames to an image.
    Returns (jpeg bytes of the first page, info); info['sheets'] lists every page's file."""
    pages, info = frame_pages(project, times_s, every_s, count, at_cuts, cols, tile_w, max_frames, per_page)
    return pages[0], info


def frame_pages(project, times_s=None, every_s=None, count=None, at_cuts=False, cols=4, tile_w=480, max_frames=None,
                per_page=48, platform=None, zone_alpha=0.38):
    """([jpeg bytes per page], info) for frames of the timeline (any number; max_frames only if given).
    platform: a platform profile id/name (platforms.py): the sheet shows each frame with that platform's covered
    areas drawn over it (platforms.safe_zone_overlay, fill opacity zone_alpha); the plain frames stay saved too."""
    timeline, path = resolve(project)
    picks = pick_frames(timeline, times_s, every_s, count, at_cuts)
    if max_frames:
        picks = picks[:max_frames]
    if not picks:
        raise ValueError('No frames picked')
    work = _work('frames')
    started = time.monotonic()
    pngs = render_frames(timeline, path, picks, work)
    import letitedit.pictures.code_scenes as code_scenes
    labels = code_scenes.scene_labels(work, picks, [_label_for(timeline, f) for f in picks])
    shown, zones = pngs, None
    if platform:
        import letitedit.catalogs.platforms as platforms
        prof = platforms.load(platform)
        shown = [Path(platforms.safe_zone_overlay(p, platform, alpha=zone_alpha,
                                                  out=str(Path(p).with_suffix('')) + f'.{prof["id"]}-zones.png'))
                 for p in pngs]
        sz = prof.get('safe_zones') or {}
        ep = prof.get('export_preset') or {}
        zones = {'platform': prof['id'], 'name': prof['name'], 'zones': sz.get('value'),
                 **{k: sz.get(k) for k in ('confidence', 'status', 'source', 'checked', 'note') if sz.get(k)},
                 'frame_size': f"{timeline.profile['width']}x{timeline.profile['height']}",
                 'platform_size': (f"{ep['width']['value']}x{ep['height']['value']}"
                                   if 'width' in ep and 'height' in ep else None), 'zone_alpha': zone_alpha}
    per_page = max(1, int(per_page or len(picks)))
    pages, sheets = [], []
    for k in range(0, len(picks), per_page):
        sheet = contact_sheet(shown[k:k + per_page], labels[k:k + per_page], cols=cols, tile_w=tile_w)
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=85)
        name = work / ('sheet.jpg' if k == 0 else f'sheet_{k // per_page + 1}.jpg')
        name.write_bytes(buf.getvalue())
        pages.append(buf.getvalue())
        sheets.append(str(name))
    info = {**reported(path), 'frames': [{'frame': f, 'time': fmt(f / timeline.fps), 'shows': labels[i].split('  ', 1)[1],
                                              'png': str(pngs[i]),
                                              **({'zones_png': str(shown[i])} if zones else {})}
                                             for i, f in enumerate(picks)],
            'rendered_by': 'melt (export engine)', 'seconds': round(time.monotonic() - started, 1), 'sheet': sheets[0],
            'sheets': sheets}
    if (work / 'scenes.json').exists():
        info['code_scenes'] = code_scenes._json(work / 'scenes.json')
    if zones:
        info['covered_areas'] = zones
    return pages, info


def add_stack(project, info):
    """Each frame in frame_pages' info gets the layers at that moment, from the same file its picture came from."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.stack as stack
    path = info['project']
    script, doc = es.read(path), es.Doc(path)
    fps = float((script.get('profile') or {}).get('fps') or 30)
    blends = stack.track_blends(doc)
    for row in info['frames']:
        row['stack'] = stack.block(script, row['frame'] / fps, blends)
    return info


def _picture_rect(item, profile):
    """Where a main-track clip's footage sits in the frame when it is fitted whole (x0, y0, x1, y1), or None when it
    fills (nearly) the whole frame or isn't plain footage."""
    if 'clip' not in item:
        return None
    try:
        import letitedit.server.core_tools as core_tools
        info = core_tools.probe(item['clip'])
    except Exception:  # noqa: BLE001 - no rect: the whole frame is shown
        return None
    w, h = info.get('width') or 0, info.get('height') or 0
    W, H = profile['width'], profile['height']
    if not (w and h):
        return None
    k = min(W / w, H / h)
    pw, ph = w * k, h * k
    if pw >= 0.9 * W and ph >= 0.9 * H:
        return None
    return (round((W - pw) / 2), round((H - ph) / 2), round((W + pw) / 2), round((H + ph) / 2))


def _outside_is_fill(images, rect):
    """True when everything outside rect is black or much softer than inside it (a fill behind fitted footage), so
    cropping to rect leaves out nothing but the fill."""
    import numpy as np
    x0, y0, x1, y1 = rect
    for im in images:
        g = np.asarray(im.convert('L'), dtype=float)
        H, W = g.shape
        detail = np.abs(np.diff(g, axis=1))
        pad = max(2, W // 100)
        inside = detail[y0:y1, x0 + pad:x1 - pad]
        outside = np.concatenate([detail[:, :max(0, x0 - pad)].ravel(), detail[:, x1 + pad:].ravel(),
                                  detail[:max(0, y0 - pad), :].ravel(), detail[y1 + pad:, :].ravel()])
        if outside.size == 0 or inside.size == 0:
            continue
        out_px = np.concatenate([g[:, :max(0, x0 - pad)].ravel(), g[:, x1 + pad:].ravel()])
        if out_px.size and out_px.mean() < 20:
            continue                                   # black sides
        if outside.mean() > 0.5 * inside.mean():
            return False                               # sharp picture outside the rect: the footage fills more
    return True


def storyboard(project, per_page=15, tile_h=340, page_w=1800, per_shot=3, start_s=None, end_s=None):
    """Every clip on the main picture track (or those overlapping start_s-end_s) as per_shot frames (3: its first,
    middle and last; 1: its middle; more: spread through it), rendered by melt with everything on top, labelled with
    its id, time and the words said in it. When the footage doesn't fill the frame (a phone video in a 16:9 project),
    the tiles show its picture area, tile_h px tall, and leave the sides out. Returns ([jpeg_bytes per page], info)."""
    from PIL import Image, ImageDraw, ImageFont
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout, main_track
    from letitedit.timeline.timeline_speech import add_said
    timeline, path = resolve(project)
    started = time.monotonic()
    script = add_said(es.read(path))
    main = main_track(script)
    shots = [(it, s, e) for it, s, e in layout(main) if e - s > 0.05] if main else []
    if start_s is not None or end_s is not None:
        lo, hi = float(start_s or 0), float(end_s) if end_s is not None else float('inf')
        shots = [(it, s, e) for it, s, e in shots if e > lo and s < hi]
    if not shots:
        raise ValueError('No clips on the main picture track' + (' in that range' if start_s or end_s else ''))
    fps = timeline.fps
    last = timeline.frames - 1
    per_shot = max(1, int(per_shot))
    picks = []
    for it, s, e in shots:
        a, b = round(s * fps), max(round(s * fps), round(e * fps) - 1)
        if per_shot == 1:
            picks += [min(last, (a + b) // 2)]
        elif per_shot == 3:
            picks += [min(last, a + 2), min(last, (a + b) // 2), min(last, max(a, b - 2))]
        else:
            picks += [min(last, a + round((b - a) * (k + 0.5) / per_shot)) for k in range(per_shot)]
    work = _work('storyboard')
    pngs = render_frames(timeline, path, picks, work)
    W, H = timeline.profile['width'], timeline.profile['height']
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 15)
        bold = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', 15)
    except OSError:
        font = bold = ImageFont.load_default()
    text_h, gap = 44, 8
    # each shot's three tiles: its picture area when the footage is fitted inside a fill, else the whole frame
    cells, cropped = [], 0
    for i, (it, s, e) in enumerate(shots):
        ims = [Image.open(pngs[per_shot * i + f]).convert('RGB') for f in range(per_shot)]
        rect = _picture_rect(it, timeline.profile)
        if rect and _outside_is_fill(ims, rect):
            ims = [im.crop(rect) for im in ims]
            cropped += 1
            th = tile_h
        else:
            th = round(tile_h * 0.56) if W > H else tile_h
        tw = max(1, round(th * ims[0].width / ims[0].height))
        cells.append(([im.resize((tw, th)) for im in ims], tw, th))
    # flow the shots into rows across the page, per_page shots per image
    pages, info = [], []
    for k in range(0, len(shots), per_page):
        group = list(range(k, min(k + per_page, len(shots))))
        rows, row, row_w = [], [], 0
        for i in group:
            cw = per_shot * cells[i][1]
            if row and row_w + gap + cw > page_w:
                rows.append(row)
                row, row_w = [], 0
            row.append(i)
            row_w += (gap if row_w else 0) + cw
        if row:
            rows.append(row)
        widths = [sum(per_shot * cells[i][1] for i in r) + gap * (len(r) - 1) for r in rows]
        heights = [max(cells[i][2] for i in r) + text_h for r in rows]
        sheet = Image.new('RGB', (max(widths), sum(heights)), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        y0 = 0
        for r, rh in zip(rows, heights):
            x0 = 0
            for i in r:
                it, s, e = shots[i]
                tiles, tw, th = cells[i]
                for f, im in enumerate(tiles):
                    sheet.paste(im, (x0 + f * tw, y0))
                said = it.get('said') or ''
                kind = next((key for key in ('graphic', 'color', 'ffmpeg', 'freeze', 'vfx', 'ass') if key in it), '')
                src = os.path.basename(it.get('clip', '')) or kind
                head = f"{i + 1}. {it.get('id')}  {fmt(s)}-{fmt(e)}  ({e - s:.1f} s)  {src}"
                if it.get('recorded'):
                    head += f"  rec {it['recorded'][5:19]}"
                room = max(20, int(per_shot * tw / 7.5))
                d.text((x0 + 4, y0 + rh - text_h + 3), head[:room], fill=(255, 220, 0), font=bold)
                d.text((x0 + 4, y0 + rh - text_h + 22), (said[:room - 3] + ('...' if len(said) > room - 3 else ''))
                       or '(no speech)', fill=(235, 235, 235), font=font)
                info.append({'n': i + 1, 'id': it.get('id'), 'at': fmt(s), 'len': round(e - s, 2), 'source': src,
                             'said': said, **({'recorded': it['recorded']} if it.get('recorded') else {})})
                x0 += per_shot * tw + gap
            y0 += rh
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=82)
        (work / f'storyboard_{len(pages) + 1}.jpg').write_bytes(buf.getvalue())
        pages.append(buf.getvalue())
    out = {**reported(path), 'shots': info, 'pages': len(pages), 'folder': str(work),
           'rendered_by': 'melt (export engine)', 'seconds': round(time.monotonic() - started, 1)}
    if cropped:
        out['tiles'] = (f'{cropped} of {len(shots)} shots show only their picture area (the footage is fitted inside '
                        f'the {W}x{H} frame; the sides are left out). letitedit_check_frames(times_s=...) shows whole frames.')
    return pages, out


# ---------------------------------------------------------------------------- short range clip

def range_clip(project, start_s, duration_s=10.0, width=640, strip=6):
    """Render an MP4 of a timeline range (with audio) at `width` px and a filmstrip of `strip` frames.
    Returns (jpeg_bytes, info)."""
    timeline, path = resolve(project)
    if not duration_s > 0:
        raise ValueError('duration_s must be more than 0')
    width = max(64, min(int(width), timeline.profile['width'])) // 2 * 2
    strip = max(1, int(strip))
    first = max(0, round(start_s * timeline.fps))
    last = min(timeline.frames - 1, first + round(duration_s * timeline.fps) - 1)
    if last < first:
        raise ValueError('Range starts after the end of the timeline')
    work = _work('ranges')
    out = work / f'range-{fmt(start_s).replace(":", "m")}.mp4'
    p = timeline.profile
    height = round(p['height'] * width / p['width'] / 2) * 2
    started = time.monotonic()
    import letitedit.pictures.code_scenes as code_scenes
    where = reported(path)
    path = code_scenes.looks_path(path, span=(first, last), width=width, work=work)   # scenes drawn at this width
    _run([MELT, '-quiet', path, f'in={first}', f'out={last}', '-consumer', f'avformat:{out}', 'vcodec=libx264', 'crf=28',
          'preset=veryfast', 'pix_fmt=yuv420p', 'acodec=aac', 'ab=128k', f'width={width}', f'height={height}',
          f'progressive={p["progressive"]}', f'frame_rate_num={p["frame_rate_num"]}', f'frame_rate_den={p["frame_rate_den"]}',
          'sample_aspect_num=1', 'sample_aspect_den=1', f'display_aspect_num={width}', f'display_aspect_den={height}',
          'real_time=-1'], timeout=600)
    shutil.rmtree(work / 'scene-look', ignore_errors=True)   # melt's input only: no reply names these (T95)
    n = last - first + 1
    picks = [round((i + 0.5) * n / strip) for i in range(strip)]
    pngs = []
    for i, f in enumerate(picks):
        png = work / f's_{i:02d}.png'
        _run([FFMPEG, '-v', 'error', '-y', '-ss', f'{f / timeline.fps:.3f}', '-i', out, '-frames:v', '1', png], timeout=60)
        pngs.append(png)
    labels = code_scenes.scene_labels(work, picks, [_label_for(timeline, first + f) for f in picks])
    sheet = contact_sheet(pngs, labels, cols=min(strip, 3 if strip <= 9 else 6), tile_w=min(width, 480))
    buf = io.BytesIO()
    sheet.save(buf, 'JPEG', quality=85)
    info = {**where, 'clip': str(out), 'range': [fmt(first / timeline.fps), fmt((last + 1) / timeline.fps)],
            'seconds': round(time.monotonic() - started, 1), 'rendered_by': 'melt (export engine)'}
    if (work / 'scenes.json').exists():
        info['code_scenes'] = code_scenes._json(work / 'scenes.json')
    return buf.getvalue(), info


# ---------------------------------------------------------------------------- audio

def _variant(path, timeline, keep_tracks):
    """Copy of the project where only the given track indices keep their audio."""
    tree = ET.parse(path)
    root = tree.getroot()
    tractors = [e for e in root if e.tag == 'tractor']
    marked = [t for t in tractors if tm.props(t).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    for i, tr in enumerate(main.findall('track')):
        if tr.get('producer') == 'background':
            continue
        if i not in keep_tracks:
            hide = tr.get('hide', '')
            tr.set('hide', 'both' if hide in ('video', 'both') else 'audio' if hide == '' else 'both')
    # Written outside the user's folders; relative media paths still resolve against the original folder.
    root.set('root', str(Path(path).resolve().parent))
    out = _work('audio-variants') / f'{Path(path).stem}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


def render_audio(path, out_wav, first=None, last=None, timeout=7200):
    args = [MELT, '-quiet', path]
    if first is not None:
        args += [f'in={first}', f'out={last}']
    args += ['-consumer', f'avformat:{out_wav}', 'vn=1', 'video_off=1', 'acodec=pcm_s16le', 'ar=48000', 'channels=2', 'real_time=-1']
    _run(args, timeout=timeout)
    return out_wav


def loudness_series(wav):
    """Short-term loudness every 0.1 s plus integrated/LRA/true peak, via ffmpeg ebur128."""
    r = subprocess.run([str(FFMPEG), '-hide_banner', '-nostats', '-i', str(wav), '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    series = []
    num = lambda v: float(v) if v not in ('-inf', 'inf', 'nan') else -120.0  # digital silence prints nan/-inf
    for m in re.finditer(r't:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-?inf|nan)\s+S:\s*(-?[\d.]+|-?inf|nan)', r.stderr):
        series.append((float(m.group(1)), num(m.group(2)), num(m.group(3))))
    summ = r.stderr[r.stderr.rfind('Summary:'):]
    def grab(rx):
        m = re.search(rx, summ)
        return float(m.group(1)) if m else None
    return series, {'integrated_lufs': grab(r'I:\s+(-?[\d.]+) LUFS'), 'range_lu': grab(r'LRA:\s+([\d.]+) LU'),
                    'true_peak_dbfs': grab(r'Peak:\s+(-?[\d.]+|-inf) dBFS')}


def _median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


def _graph(series_map, seconds, marks, width=1400, height=300):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (width, height), (24, 24, 28))
    d = ImageDraw.Draw(im)
    lo, hi = -60.0, -5.0
    y = lambda v: height - 20 - (min(hi, max(lo, v)) - lo) / (hi - lo) * (height - 40)
    for db in (-14, -23, -30, -40, -50):
        d.line((0, y(db), width, y(db)), fill=(60, 60, 70))
        d.text((4, y(db) - 12), f'{db}', fill=(140, 140, 150))
    for t in marks:
        x = t / seconds * width
        d.line((x, height - 20, x, height - 12), fill=(110, 110, 120))
    colors = {'mix': (235, 235, 235), 'music': (255, 150, 60), 'dialogue': (90, 180, 255)}
    for name, series in series_map.items():
        pts = [(t / seconds * width, y(s)) for t, _, s in series[::5]]
        if len(pts) > 1:
            d.line(pts, fill=colors.get(name, (200, 200, 200)), width=2)
    x = 60
    for name in series_map:
        d.text((x, 4), name, fill=colors.get(name, (200, 200, 200)))
        x += 90
    for k in range(0, int(seconds) + 1, 60):
        d.text((k / seconds * width + 2, height - 14), f'{k // 60}m', fill=(150, 150, 160))
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def _tones(wav, offset=0.0):
    """Sustained narrow tones (howl, whistle, feedback, a pure lead) in a rendered file (tonal_check); None if unreadable."""
    try:
        import letitedit.sound.tonal_check as tonal_check
        result = tonal_check.scan_file(wav)
    except Exception:  # noqa: BLE001 - the loudness report stands without it
        return None
    for e in result['events']:
        e['start_s'] = round(e['start_s'] + offset, 2)
        e['end_s'] = round(e['end_s'] + offset, 2)
    result['flagged'] = tonal_check.flagged(result)
    return result


def _tone_finding(result, label):
    import letitedit.sound.tonal_check as tonal_check
    if not result.get('flagged'):
        return ''
    return (tonal_check.summary_line(result, label) + '. A held, pure tone like this reads as a howl, whine or feedback; '
            'a different song or section avoids it unless the Look or the person wants that sound.')


def far_from_typical_line(odd, mid):
    """The finding for clips whose loudness sits 8+ LU from the clips' median: which, and the op that levels speech."""
    return (f'{len(odd)} clip(s) sit 8+ LU away from the typical level ({mid:.1f} LUFS), e.g. '
            + ', '.join(f"{x['clip']} at {x['at']} ({x['median_lufs']})" for x in odd[:5])
            + ". {op: level} (letitedit_timeline_apply) sets each speech clip's gain to bring its speech to the clips' "
            'median, in one change')


def _check_stem_balance(stems, timeline, music_tracks, path, work, first, last, offset, report, findings, graph_series):
    """Measure isolated music and dialogue, retaining variant cleanup and report ordering."""
    if stems:
        names = {t.index: t.name for t in timeline.tracks}
        music = set(music_tracks or [t.index for t in timeline.audio_tracks() if re.match(r'(?i)music', t.name)])
        sfx = {t.index for t in timeline.audio_tracks() if re.match(r'(?i)sfx|sound', t.name)}
        dialogue = {t.index for t in timeline.tracks} - music - sfx
        if music:
            mv = _variant(path, timeline, music)
            dv = _variant(path, timeline, dialogue)
            try:
                music_wav = render_audio(mv, work / 'music.wav', first, last)
                mser, msum = loudness_series(music_wav)
                music_tones = _tones(music_wav, offset)
                if music_tones:
                    report.setdefault('tones', {})['music'] = music_tones
                    line = _tone_finding(music_tones, 'the music')
                    if line:
                        findings.append(line)
                dser, dsum = loudness_series(render_audio(dv, work / 'dialogue.wav', first, last))
                mser = [(t + offset, m, st) for t, m, st in mser]
                dser = [(t + offset, m, st) for t, m, st in dser]
            finally:
                for f in (mv, dv):
                    f.unlink(missing_ok=True)
            graph_series.update(music=mser, dialogue=dser)
            # short-term readings once the 3 s window has filled (before that the opening reads as silence)
            filled = [(m, d) for m, d in zip(mser, dser) if m[0] >= offset + 3.0]
            talk = [(m[2], d[2]) for m, d in filled if d[2] > -35]
            quiet_talk = [m[2] for m, d in filled if d[2] <= -45]
            talk = talk if len(talk) >= 20 else []                # 2 s of readings or more
            quiet_talk = quiet_talk if len(quiet_talk) >= 20 else []
            report['music_tracks'] = [names[i] for i in sorted(music)]
            report['music_integrated_lufs'] = msum['integrated_lufs']
            # where is there no music at all?
            gaps, start = [], None
            for t, m, s in mser:
                if (s if t >= offset + 3.0 else m) < -50:
                    start = t if start is None else start
                else:
                    if start is not None and t - start >= 5:
                        gaps.append((start, t))
                    start = None
            if start is not None and mser and mser[-1][0] - start >= 5:
                gaps.append((start, mser[-1][0]))
            silent = sum(b - a for a, b in gaps)
            report['music_silent_stretches'] = [f'{fmt(a)}-{fmt(b)}' for a, b in gaps[:30]]
            if gaps:
                findings.append(f'The music tracks are silent for {silent / max(1, timeline.seconds):.0%} of the timeline: '
                                + ', '.join(report['music_silent_stretches'][:6]))
            report['dialogue_integrated_lufs'] = dsum['integrated_lufs']
            if talk:
                import letitedit.sound.music as music_level      # the one rule the timing map states too
                gap = music_level.music_below_voice_lu([(m[2], d[2]) for m, d in filled])
                report['music_below_voice_while_talking_lu'] = gap
                if gap < 0:
                    findings.append(f'Music is {-gap:.1f} LU louder than the voice while people talk (aim for 10-18 LU under it).')
                elif gap < 8:
                    findings.append(f'Music is only {gap:.1f} LU under the voice while people talk (aim for 10-18).')
                elif gap > 22:
                    findings.append(f'Music is {gap:.1f} LU under the voice while people talk; it may be inaudible.')
            if quiet_talk:
                lvl = _median(quiet_talk)
                report['music_level_without_talking_lufs'] = round(lvl, 1)
                if lvl < -28:
                    findings.append(f'Where nobody talks, the music sits around {lvl:.1f} LUFS, so montages/time-lapses will feel empty.')
                elif dsum['integrated_lufs'] is not None and lvl > dsum['integrated_lufs'] + 2:
                    findings.append(f"Where nobody talks, the music sits around {lvl:.1f} LUFS, "
                                    f"{lvl - dsum['integrated_lufs']:.1f} LU louder than the voice ({dsum['integrated_lufs']} "
                                    f"LUFS), so those stretches jump out.")
        else:
            findings.append('No track named Music*; stems skipped.')


def audio(project, stems=None, music_tracks=None, target_lufs=-14.0, start_s=None, end_s=None, every_s=None,
          quiet_lu=15.0, mix_wav=None):
    """Loudness report for the saved timeline, or its start_s-end_s range. stems=True also renders music-only and
    dialogue-only passes (tracks named like Music* are music; Sfx*/SFX* are effects; everything else carrying audio is
    dialogue); None (the default) does when the timeline has a track named Music*. every_s: also the momentary and
    short-term loudness every every_s seconds (timeline times). quiet_lu: a stretch of 2 s+ this far under the mix's
    typical short-term loudness (or under -40 LUFS) is reported as quiet; None for -40 LUFS only. mix_wav: the whole
    timeline's mix already rendered (an export's sound before its loudness finish), used instead of rendering it."""
    timeline, path = resolve(project)
    if stems is None:
        stems = bool(music_tracks) or any(re.match(r'(?i)music', t.name) for t in timeline.audio_tracks())
    work = _work('audio')
    started = time.monotonic()
    first = last = None
    offset = 0.0
    if start_s is not None or end_s is not None:
        first = max(0, round(float(start_s or 0) * timeline.fps))
        last = min(timeline.frames - 1, round(float(end_s) * timeline.fps) - 1) if end_s is not None else timeline.frames - 1
        if last < first:
            raise ValueError('end_s must be after start_s')
        offset = first / timeline.fps
    mix = Path(mix_wav) if mix_wav and first is None else render_audio(path, work / 'mix.wav', first, last)
    series, summary = loudness_series(mix)
    if offset:
        series = [(t + offset, m, st) for t, m, st in series]
    report = {**reported(path), 'duration': fmt(timeline.seconds), **summary, 'target_lufs': target_lufs}
    typical = _median([st for t, m, st in series if t >= offset + 3.0 and st > -70])
    floor = max(-40.0, typical - float(quiet_lu)) if quiet_lu is not None and typical is not None else -40.0
    report['settings'] = {'stems': stems, 'quiet_lu': quiet_lu, 'quiet_below_lufs': round(floor, 1),
                          'typical_short_term_lufs': None if typical is None else round(typical, 1)}
    if first is not None:
        report['range'] = f'{fmt(first / timeline.fps)}-{fmt((last + 1) / timeline.fps)}'
    if every_s:
        step, nxt, rows = max(0.1, float(every_s)), None, []
        for t, m, st in series:
            if nxt is None:
                nxt = t
            if t + 1e-6 >= nxt:
                rows.append(f'{fmt(t)} M {m:.1f} S {st:.1f}' if st > -70 or t - offset >= 3 else f'{fmt(t)} M {m:.1f}')
                nxt += step
        report['readings'] = rows
        report['readings_note'] = 'LUFS: M = momentary (0.4 s window), S = short-term (3 s window)'
    findings = []
    if summary['integrated_lufs'] is not None and abs(summary['integrated_lufs'] - target_lufs) > 1.5:
        findings.append(f"Overall loudness {summary['integrated_lufs']} LUFS in the mix; letitedit_export brings the whole "
                        f"mix to {target_lufs} LUFS with plain gain (loudness='off' leaves it as it is).")
    if summary['true_peak_dbfs'] is not None and summary['true_peak_dbfs'] > -1.0:
        findings.append(f"True peak {summary['true_peak_dbfs']} dBFS in the mix; letitedit_export's true-peak limiter holds "
                        f"peaks at -1 dBTP (its true_peak sets that; loudness='off' leaves them).")
    # quiet stretches: loudness under the floor (quiet_lu under the typical level, or -40 LUFS) for 2 s or more
    # (momentary loudness until the 3 s short-term window has filled, or the opening reads as silence)
    quiet, start = [], None
    for t, m, s in series:
        if (s if t >= offset + 3.0 else m) < floor:
            start = t if start is None else start
        else:
            if start is not None and t - start >= 2.0:
                quiet.append((start, t))
            start = None
    if start is not None and series and series[-1][0] - start >= 2.0:
        quiet.append((start, series[-1][0]))
    report['quiet_stretches'] = [f'{fmt(a)}-{fmt(b)}' for a, b in quiet[:40]]
    if quiet:
        findings.append(f'{len(quiet)} stretch(es) where the mix drops below {floor:.1f} LUFS for 2 s+ ('
                        + (f'{quiet_lu:g} LU under its typical {typical:.1f}' if floor > -40 else 'nearly silent')
                        + '): ' + ', '.join(report['quiet_stretches'][:8]))
    # per V1 clip loudness
    v1 = timeline.v1()
    per = []
    if v1:
        for it in v1.items:
            a, b = it.start / timeline.fps, it.end / timeline.fps
            # short-term loudness (3 s window) only once the window lies inside the clip and the programme; short
            # clips use momentary loudness (0.4 s) instead, or a 1.6 s opening clip reads as silence
            if b - a >= 4.0:
                vals = [s for t, m, s in series if max(a + 3.0, offset + 3.0) <= t <= b]
            else:
                vals = [m for t, m, s in series if a + 0.4 <= t <= b and m > -70]
            if vals:
                per.append({'clip': it.name, 'at': fmt(a), 'median_lufs': round(_median(vals), 1)})
    meds = [x['median_lufs'] for x in per]
    if meds:
        mid = _median(meds)
        odd = [x for x in per if abs(x['median_lufs'] - mid) > 8]
        report['clips_far_from_typical_level'] = odd[:20]
        if odd:
            findings.append(far_from_typical_line(odd, mid))
    graph_series = {'mix': series}
    tones = _tones(mix, offset)
    if tones:
        report['tones'] = {'mix': tones}
        line = _tone_finding(tones, 'the mix')
        if line:
            findings.append(line)
    _check_stem_balance(stems, timeline, music_tracks, path, work, first, last, offset, report, findings, graph_series)

    report['findings'] = findings or ['No audio problems found by measurement (listening is still the real test).']
    report['seconds'] = round(time.monotonic() - started, 1)
    marks = [it.start / timeline.fps for it in (v1.items if v1 else [])]
    graph = _graph(graph_series, max(1.0, timeline.seconds), marks)
    (work / 'loudness.png').write_bytes(graph)
    report['graph'] = str(work / 'loudness.png')
    with open(work / 'report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=1)
    return graph, report


# ---------------------------------------------------------------------------- QC

def _frame_problems(png, profile):
    """Classify a rendered frame: blank/checkerboard, black, pillarbox/squeezed. Returns list of strings."""
    import numpy as np
    from PIL import Image
    im = Image.open(png).convert('RGB').resize((192, 108))
    a = np.asarray(im).astype(np.float32)
    luma = a.mean(axis=2)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    problems = []
    if luma.mean() < 10 and luma.std() < 6:
        problems.append('black frame')
        return problems
    if sat.mean() < 0.02 and 40 < luma.mean() < 230 and luma.std() < 40:
        # transparent/checkerboard placeholders render as flat grey tiles
        problems.append('grey or checkerboard frame (missing picture)')
    cols = luma.mean(axis=0)
    dark = cols < 8
    left = int(np.argmax(~dark)) if (~dark).any() else 0
    right = int(np.argmax(~dark[::-1])) if (~dark).any() else 0
    # real bars are flat black; a blur pad of dark footage is dark but not flat (the inner edge can hold picture)
    outer = (np.concatenate([luma[:, :max(1, left - 4)], luma[:, 192 - max(1, right - 4):]], axis=1)
             if left and right else None)
    flat = outer is not None and np.percentile(outer, 99) < 14 and outer.std() < 2.5
    if left > 192 * 0.2 and right > 192 * 0.2 and flat:
        width = 192 - left - right
        problems.append(f'black sides frame: the picture fills {width / 192:.0%} of the width')
    elif luma.mean() < 28:
        problems.append(f'very dark frame (average brightness {luma.mean() / 2.55:.0f}%)')
    elif luma.mean() > 235 and luma.std() < 12:
        problems.append(f'washed-out frame (average brightness {luma.mean() / 2.55:.0f}%, little detail)')
    else:
        # detail in the middle of the frame (where the picture usually is): a smeared / out-of-focus shot
        mid = luma[:, 66:126]
        lap = np.abs(4 * mid[1:-1, 1:-1] - mid[:-2, 1:-1] - mid[2:, 1:-1] - mid[1:-1, :-2] - mid[1:-1, 2:]).mean()
        if lap < 7 and mid.std() > 6:
            problems.append(f'blurry frame (little detail in the middle of the picture: {lap:.1f})')
    return problems


NO_TALK_S = 4.0           # stretches without speech at least this long are listed
PICTURE_MIN_S = 1.0       # whips and blur shorter than this in the cut aren't listed (shaky handheld: twice this)


def footage_picture(project):
    """[{'at', 'item', 'severity', 'problem'}]: stretches of the main picture track whose footage the picture
    analysis (letitedit_footage, cached) marks as shaky handheld, fast whips or blurry. Clips not analysed yet are
    skipped (nothing is analysed here)."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.perception as pc
    from letitedit.timeline.edit_sync import layout, main_track
    timeline, path = resolve(project)
    script = es.read(path)
    main = main_track(script)
    v1 = timeline.v1()
    out = []
    for it, s, e in (layout(main) if main else []):
        if 'clip' not in it or not pc.is_cached('motion', it['clip']):
            continue
        res = pc.picture(it['clip'])
        if res.get('none'):
            continue
        a, b = float(it.get('in', 0)), float(it.get('out', 0))
        speed = abs(float(it.get('speed', 1) or 1))
        if it.get('reverse') or b <= a:
            continue
        marks = [(x, y, lab) for x, y, lab, *_ in res.get('spans', []) if lab in ('shaky handheld', 'fast whip')]
        marks += [(x, y, kind) for x, y, kind in res.get('blurry', [])]
        mid = round((s + e) / 2 * timeline.fps)
        item = next((x for x in (v1.items if v1 else []) if x.start <= mid < x.end and x.service != 'transition'), None)
        found = []
        for x, y, lab in sorted(marks):
            lo, hi = max(a, float(x)), min(b, float(y))
            if (hi - lo) / speed < (PICTURE_MIN_S * 2 if lab == 'shaky handheld' else PICTURE_MIN_S):
                continue
            t0, t1 = s + (lo - a) / speed, s + (hi - a) / speed
            what = {'shaky handheld': 'shaky handheld camera', 'fast whip': 'fast whip-pan',
                    'motion blur': 'motion blur', 'out of focus?': 'soft focus (out of focus?)'}.get(lab, lab)
            found.append((t0, t1, lab, what))
        if found:
            parts = ', '.join(f'{what} {fmt(t0)}-{fmt(t1)}' for t0, t1, _, what in sorted(found))
            out.append({'at': round(min(f[0] for f in found), 2), 'item': item,
                        'severity': 'info' if all(f[2] == 'shaky handheld' for f in found) else 'warning',
                        'problem': f'in the footage of {it.get("id")} ({os.path.basename(it["clip"])}, '
                                   f'{fmt(s)}-{fmt(e)}): {parts}'})
    return sorted(out, key=lambda f: f['at'])


FIX_CHANGES, FIX_CHANGES_ENV = 'review_fix_changes', 'LETITEDIT_REVIEW_FIX_CHANGES'


def fix_changes_on():
    """T362's switch (settings.json review_fix_changes, default false; LETITEDIT_REVIEW_FIX_CHANGES, 1 or 0, wins): a
    clip-edge finding's suggested times are whole frames of the project, and a finding whose edge has one clean place
    carries it as a ready trim (`change`), which the review bundle's reply collects as one changes list."""
    forced = os.environ.get(FIX_CHANGES_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(FIX_CHANGES) is True
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: off
        return False


def _project_fps(project):
    """The project's frame rate with fix_changes_on, else None (suggested edge times as measured)."""
    if not fix_changes_on():
        return None
    try:
        import letitedit.timeline.edit_script as es
        return float((es.read(project).get('profile') or {}).get('fps') or 0) or None
    except Exception:  # noqa: BLE001 - an unreadable profile: times as measured
        return None


def _ready_trim(it, ws, src, side, fps):
    """(change, how) that makes a clip edge at source time src clean on a whole frame (cutpoints.clean_edge with the
    project's fps: the measure letitedit_timeline_apply's trim guard uses), or None when no clean place is in reach
    or the clip would be left with no length."""
    import letitedit.timeline.cutpoints as cutpoints
    if not fps or not it.get('id'):
        return None
    try:
        e = cutpoints.clean_edge(it['clip'], src, side, ws=ws, fps=fps)
    except Exception:  # noqa: BLE001 - unreadable sound: no ready change
        return None
    at = e.get('at')
    if not e.get('clean') or at is None or abs(at - src) < 1e-4:
        return None
    a, b = float(it['in']), float(it['out'])
    if (side == 'out' and at <= a + 1 / fps) or (side == 'in' and at >= b - 1 / fps):
        return None
    return {'op': 'trim', 'id': it['id'], side: round(at, 4)}, e.get('how') or 'clean'


def _with_ready(finding, ready, side):
    if not ready:
        return finding
    change, how = ready
    return {**finding, 'change': change,
            'fix': f"{side}: {change[side]:.2f}, {how} (one of fix_changes)"}


def _offer(clip, ws, t, side, keep_from=None, keep_to=None, fps=None):
    """A suggested edge time that passes the same three tests the check runs (word, tail, sound), or None: a time that
    fails is moved to the nearest clean place (cutpoints.clean_edge), kept only if it stays in [keep_from, keep_to]
    so the suggestion still keeps (or drops) the word it names. fps (fix_changes_on): the time is a whole frame,
    measured where the engine cuts."""
    import letitedit.timeline.cutpoints as cutpoints
    try:
        if fps:
            t = round(t * fps) / fps
        if not cutpoints.edge_problem(clip, ws, t, side):
            return t
        e = cutpoints.clean_edge(clip, t, side, ws=ws, fps=fps)
    except Exception:  # noqa: BLE001 - unreadable sound: offer the plain time
        return t
    if not (e.get('clean') or e.get('between_words')):
        return None
    if (keep_from is not None and e['at'] < keep_from) or (keep_to is not None and e['at'] > keep_to):
        return None
    return e['at']


def _ways(key, offers):
    return ', '.join(f"{key}: {t:.2f} {what}" for t, what in offers if t is not None)


def _pause_ways(clip, ws, t, side, g, verb, fps=None):
    """The pauses either side of an edge in sound, as suggested edge times, each checked with the word and tail tests
    too (a recogniser's word can run over a quiet stretch); one that fails is moved to its nearest clean place."""
    out = []
    for at, where in ((g.get('earlier'), 'the pause before'), (g.get('later'), 'the next pause')):
        if at is None:
            continue
        ok = _offer(clip, ws, at, side, fps=fps)
        if ok is None:
            continue
        line = f"{side}: {ok:.2f} {verb} in {where}" if abs(ok - at) < .005 else f"{side}: {ok:.2f} {verb} clean, near {where}"
        if line not in out:
            out.append(line)
    return out


def _no_pause(clip, ws, t, side, verb, fps=None):
    """The fix text for an edge in sound with no pause within 0.5 s: the quietest moment between two words, when the
    tools find one (where the cut goes through no word), else a plain 'somewhere else'."""
    import letitedit.timeline.cutpoints as cutpoints
    try:
        e = cutpoints.clean_edge(clip, t, side, ws=ws, fps=fps)
    except Exception:  # noqa: BLE001
        e = {}
    if e.get('between_words') or e.get('clean'):
        return (f"no pause within 0.5 s either way (the words run on); {side}: {e['at']:.2f} is "
                + (e.get('how') or 'clean'))
    return f"no pause within 0.5 s either way (the words run on): {verb} it somewhere else"


def _runs_on(it, at, verb, g):
    """A clip edge in sound that runs on (no pause within 0.5 s that keeps the clip's words: a pause past another
    word would add or drop it), placed at the quietest moment between two words: no word is cut, so it is a minor
    note, not a clipped word."""
    return {'at': round(at, 2), 'id': it.get('id'), 'severity': 'minor',
            'problem': f"{it.get('id')} {verb} where the sound runs on (no pause within 0.5 s that keeps the same words): the cut is at the quietest "
                       f"moment between \"{str(g['after']).strip()}\" and \"{str(g['before']).strip()}\", so no word is cut; "
                       "listen to the join, and move it to a sentence end if it jumps"}


def edge_sound(clip, ws, t, side):
    """How a clip edge at source time t meets the sound, measured as the review measures every clip edge (side 'out':
    the clip ends at t; 'in': it starts there); ws: speech.sound_words around it. None when the edge sits in a
    pause, else {'kind': ...}:
    - 'word': the edge is inside a spoken word (cutpoints.cut_inside_word's word, with 'kept' and 'cut' seconds of its
      voiced sound when measured);
    - 'word_tail': it clips a word's tail or soft opening ('tail': cutpoints.cut_in_tail's {w, tail, dropped});
    - 'runs_on': it goes through sound with no pause within 0.5 s that keeps the clip's words, at the quietest moment
      between two words ('gap': {after, before, ...}, 'sound': cutpoints.cut_in_sound's measure);
    - 'sound': it goes through a sound ('sound': cutpoints.cut_in_sound's {kept_db, gone_db, earlier, later})."""
    import letitedit.timeline.cutpoints as cutpoints
    w = cutpoints.cut_inside_word(ws, t, side, clip)
    if w:
        return {'kind': 'word', 'word': w}
    tl = cutpoints.cut_in_tail(clip, ws, t, side)
    if tl:
        return {'kind': 'word_tail', 'tail': tl}
    g = cutpoints.cut_in_sound(clip, t, side)
    if not g:
        return None
    between = not cutpoints.word_keeping_pauses(ws, t, g) and cutpoints.at_quietest_between_words(clip, ws, t)
    if between:
        return {'kind': 'runs_on', 'gap': between, 'sound': g}
    return {'kind': 'sound', 'sound': g}


def _speech_edges(project, lo=None, hi=None):
    """(item, timeline start, timeline end, words, side, edge_sound(...)) for every clip edge the review checks: the
    clips of the speech tracks at normal speed, unmuted and not reversed; an edge a split edit covers on purpose is
    left out (the sound runs on through its moved-sound clip: J, the incoming clip's in and the outgoing clip's out;
    L, the reverse; the moved sound's far edge, the real sound cut, stays checked). lo, hi: only the edges whose
    timeline time is within them are measured (and yielded)."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import NOT_SPEECH, _muted
    script = es.read(project)
    skip = set()
    try:
        import letitedit.timeline.split_edit as split_edit
        for _t, br, r in split_edit.records_of(script):
            skip |= {(r.get('into'), 'in'), (r.get('out_of'), 'out')}
            skip.add((br.get('id'), 'out' if 'lead' in r else 'in'))
    except Exception:  # noqa: BLE001 - no split edits (or an older project): check every edge
        skip = set()

    def inside(x):
        return (lo is None or x >= lo - 0.05) and (hi is None or x <= hi + 0.05)
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            if 'clip' not in it or it.get('reverse') or _muted(it) or float(it.get('speed', 1)) != 1:
                continue
            sides = [(side, src) for side, src, at in (('out', float(it['out']), e), ('in', float(it['in']), s))
                     if (it.get('id'), side) not in skip and inside(at)]
            if not sides:
                continue
            a, b = float(it['in']), float(it['out'])
            ws = speech.sound_words(it['clip'], a - 2, b + 2, cached=True)
            if not ws:
                continue
            for side, src in sides:
                yield it, s, e, ws, side, edge_sound(it['clip'], ws, src, side)


def cut_words(project):
    """[{'at', 'id', 'problem'}]: clip starts and ends that cut a spoken word or go through a sound (timeline
    seconds). Words are measured on their sound (speech.sound_words): the transcript's own times run over the pauses,
    so a clean cut in a pause would read as one inside the word next to it. The measurement is edge_sound's.
    With fix_changes_on (T362), suggested times are whole frames, and an edge in a sound or a word's tail with a clean
    place in reach also carries `change` (a ready trim to it) and `fix` (what it does)."""
    import letitedit.timeline.cutpoints as cutpoints
    fps = _project_fps(project)
    out = []
    for it, s, e, ws, side, f in _speech_edges(project):
        if not f:
            continue
        a, b = float(it['in']), float(it['out'])
        if side == 'out':
            if f['kind'] == 'word':
                w = f['word']
                vs, ve = w.get('voiced', (w['s'], w['e']))
                said = (f"{w['kept']:.2f} s of it is heard, {w['cut']:.2f} s cut off" if 'kept' in w
                        else f"it ends {w['e'] - b:.2f} s later in the source")
                out.append({'at': round(e, 2), 'id': it.get('id'),
                            'problem': f"{it.get('id')} ends in the middle of the word \"{w['w'].strip()}\" ({said}); "
                                       + (_ways('out', [(_offer(it['clip'], ws, ve + 0.08, 'out', keep_from=ve, fps=fps), 'keeps the word'),
                                                         (_offer(it['clip'], ws, max(a, vs - 0.03), 'out', keep_to=vs, fps=fps), 'ends before it')])
                                          or 'no clean place keeps or drops it whole: end it at another word')})
            elif f['kind'] == 'word_tail':
                tl = f['tail']
                out.append(_with_ready({'at': round(e, 2), 'id': it.get('id'),
                            'problem': f"{it.get('id')} ends before the word \"{tl['w'].strip()}\" has finished sounding "
                                       f"(its last sound, the end of the word, runs on {tl['dropped']:.2f} s past the cut, "
                                       f"to {tl['tail']:.2f})"
                                       + ''.join(f"; out: {t:.2f} keeps it" for t in
                                                 [_offer(it['clip'], ws, tl['tail'] + 0.04, 'out', keep_from=tl['tail'], fps=fps)] if t is not None)},
                                       _ready_trim(it, ws, b, 'out', fps), 'out'))
            elif f['kind'] == 'runs_on':
                out.append(_runs_on(it, e, 'ends', f['gap']))
            else:
                g = f['sound']
                ways = _pause_ways(it['clip'], ws, b, 'out', g, 'ends', fps)
                out.append(_with_ready({'at': round(e, 2), 'id': it.get('id'),
                            'problem': f"{it.get('id')} ends while a sound is still going (the {cutpoints.SOUND_GONE_S * 1000:.0f} ms "
                                       f"cut off is {g['gone_db']:.0f} dB over the room): "
                                       + ('; '.join(x for x in ways if x) or _no_pause(it['clip'], ws, b, 'out', 'end', fps))},
                                       _ready_trim(it, ws, b, 'out', fps), 'out'))
        else:
            if f['kind'] == 'word':
                w = f['word']
                vs, ve = w.get('voiced', (w['s'], w['e']))
                said = (f"{w['kept']:.2f} s of it is heard, {w['cut']:.2f} s cut off" if 'kept' in w
                        else f"it starts {a - w['s']:.2f} s earlier in the source")
                out.append({'at': round(s, 2), 'id': it.get('id'),
                            'problem': f"{it.get('id')} starts in the middle of the word \"{w['w'].strip()}\" ({said}); "
                                       + (_ways('in', [(_offer(it['clip'], ws, max(0, vs - 0.05), 'in', keep_to=vs, fps=fps), 'keeps the word'),
                                                        (_offer(it['clip'], ws, min(b, ve + 0.02), 'in', keep_from=ve, fps=fps), 'starts after it')])
                                          or 'no clean place keeps or drops it whole: start it at another word')})
            elif f['kind'] == 'word_tail':
                tl = f['tail']
                keep = max(0, tl['tail'] - 0.03)
                keep = math.floor(keep * fps + 1e-6) / fps if fps else keep    # the frame at or before it
                out.append(_with_ready({'at': round(s, 2), 'id': it.get('id'), 'severity': 'minor',
                            'problem': f"{it.get('id')} starts after the soft opening of \"{tl['w'].strip()}\" has begun "
                                       f"({tl['dropped']:.2f} s of it, from {tl['tail']:.2f}, is cut off); "
                                       f"in: {keep:.2f} keeps it"}, _ready_trim(it, ws, a, 'in', fps), 'in'))
            elif f['kind'] == 'runs_on':
                out.append(_runs_on(it, s, 'starts', f['gap']))
            else:
                g = f['sound']
                ways = _pause_ways(it['clip'], ws, a, 'in', g, 'starts', fps)
                out.append(_with_ready({'at': round(s, 2), 'id': it.get('id'),
                            'problem': f"{it.get('id')} starts in the middle of a sound (the {cutpoints.SOUND_GONE_S * 1000:.0f} ms "
                                       f"before it is {g['gone_db']:.0f} dB over the room): "
                                       + ('; '.join(x for x in ways if x) or _no_pause(it['clip'], ws, a, 'in', 'start', fps))},
                                       _ready_trim(it, ws, a, 'in', fps), 'in'))
    return out


EDGE_SEVERITY = {('word', 'out'): 'major', ('word', 'in'): 'major', ('word_tail', 'out'): 'major',
                 ('word_tail', 'in'): 'minor', ('sound', 'out'): 'major', ('sound', 'in'): 'major',
                 ('runs_on', 'out'): 'minor', ('runs_on', 'in'): 'minor'}


def edge_sounds(project, start_s=None, end_s=None):
    """Facts about the sound at the clip edges of a project's speech tracks between start_s and end_s (timeline
    seconds), measured as the review bundle's edge check measures them (edge_sound): {checked, at: [{t, clip, side
    ('start' | 'end'), kind, word?, review ('major' | 'minor': how the review bundle counts it), text}]}. An edge that
    sits in a pause is counted in `checked` and not listed. Facts only: what sound the edge goes through and how far
    it runs, never what to change."""
    import letitedit.timeline.cutpoints as cutpoints
    gone_ms = f'{cutpoints.SOUND_GONE_S * 1000:.0f} ms'
    checked, rows = 0, []
    for it, s, e, _ws, side, f in _speech_edges(project, start_s, end_s):
        checked += 1
        if not f:
            continue
        clip, a, b = it.get('id'), float(it['in']), float(it['out'])
        end = side == 'out'
        row = {'t': round(e if end else s, 2), 'clip': clip, 'side': 'end' if end else 'start', 'kind': f['kind'],
               'review': EDGE_SEVERITY[(f['kind'], side)]}
        if f['kind'] == 'word':
            w = f['word']
            row['word'] = w['w'].strip()
            said = (f"{w['kept']:.2f} s of its sound is heard and {w['cut']:.2f} s is cut off" if 'kept' in w
                    else (f"the word ends {w['e'] - b:.2f} s later in the source" if end
                          else f"the word starts {a - w['s']:.2f} s earlier in the source"))
            row['text'] = f"{clip} {'ends' if end else 'starts'} inside the word \"{row['word']}\": {said}"
        elif f['kind'] == 'word_tail':
            tl = f['tail']
            row['word'] = tl['w'].strip()
            row['text'] = (f"{clip} ends before the sound of \"{row['word']}\" has finished: it runs on "
                           f"{tl['dropped']:.2f} s past the end" if end else
                           f"{clip} starts {tl['dropped']:.2f} s into the soft opening of \"{row['word']}\"")
        elif f['kind'] == 'runs_on':
            gap = f['gap']
            row['text'] = (f"{clip} {'ends' if end else 'starts'} where the sound runs on, at the quietest moment "
                           f"between \"{str(gap.get('after')).strip()}\" and \"{str(gap.get('before')).strip()}\" "
                           f"(no pause within 0.5 s keeps the same words)")
        else:
            g = f['sound']
            if end:
                later = g.get('later')
                runs = (f"; it runs on for less than {later - b:.2f} s, into the next pause" if later is not None
                        else '; it runs on past 0.5 s: no pause within 0.5 s after the end')
                row['text'] = (f"{clip} ends while a sound is still going: the {gone_ms} after the end is "
                               f"{g['gone_db']:.0f} dB over the room{runs}")
            else:
                earlier = g.get('earlier')
                runs = (f"; it began less than {a - earlier:.2f} s before the start, after a pause"
                        if earlier is not None else '; it began more than 0.5 s before: no pause within 0.5 s before '
                                                    'the start')
                row['text'] = (f"{clip} starts in the middle of a sound: the {gone_ms} before the start is "
                               f"{g['gone_db']:.0f} dB over the room{runs}")
        rows.append(row)
    rows.sort(key=lambda r: r['t'])
    return {'checked': checked, 'at': rows}


def edge_pins(project):
    """{(clip id, 'in' | 'out'): pin} for clip edges kept as given with edge_mode: exact (the journal's 'pin' entries)
    that are still at the time pinned; pin = {'at', 'reason'?, 'label'?, 'time'}. "Still at the time" is within half a
    frame of the project (at least 0.01 s): the saved file keeps a clip's edge on a whole frame, so an edge pinned at
    4.82 s reads back as 4.8333 at 30 fps and is the same edge (T362: the 0.01 s it was before lost such pins, and the
    review flagged a deliberate edge as a fresh major)."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.project_journal as project_journal
    pins = {}
    for e in project_journal.entries(project, limit=None):
        if e.get('kind') != 'pin':
            continue
        for p in e.get('pins') or []:
            pins[(p.get('id'), p.get('side'))] = {**p, 'label': e.get('label'), 'time': e.get('time')}
    if not pins:
        return {}
    now = {}
    script = es.read(project)
    for t in script['tracks']:
        for it in t.get('items') or []:
            if it.get('id') and 'clip' in it:
                now[(it['id'], 'in')], now[(it['id'], 'out')] = it.get('in'), it.get('out')
    try:
        fps = float((script.get('profile') or {}).get('fps') or 0)
    except (TypeError, ValueError):
        fps = 0.0
    near = max(0.01, 0.5 / fps + 1e-6) if fps > 0 else 0.01
    out = {}
    for key, p in pins.items():
        try:
            if key in now and abs(float(es.to_seconds(now[key])) - float(es.to_seconds(p['at']))) < near:
                out[key] = p
        except (TypeError, ValueError):
            continue
    return out


def pin_note(finding, pins):
    """The words a cut-edge finding gets when its edge was pinned by hand: who kept it and why."""
    m = re.match(r'(\S+) (ends|starts)\b', str(finding.get('problem') or ''))
    if not m:
        return ''
    pin = pins.get((m.group(1), 'out' if m.group(2) == 'ends' else 'in'))
    if not pin:
        return ''
    why = pin.get('reason') or (f"no edge_reason given; the edit was \"{pin['label']}\"" if pin.get('label')
                                else 'no edge_reason given')
    return f"; this edge was kept as given with edge_mode: exact ({why})"


def ending_words(project, all_ends=False):
    """[{'at', 'id', 'problem'}]: the video's last spoken line (every clip end with all_ends) stops where the source
    carries straight on (the next word within a third of a second, no sentence end): it may read as cut off mid-thought.
    Measured on the words only (endings.py); pitch and the sound after the cut are not used to flag."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.endings as endings
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import NOT_SPEECH, _muted
    script = es.read(project)
    ends = []
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            if 'clip' in it and not it.get('reverse') and not _muted(it) and float(it.get('speed', 1)) == 1:
                ends.append((e, it))
    ends.sort(key=lambda x: x[0])
    out = []
    for e, it in (ends if all_ends else ends[-1:]):
        b = float(it['out'])
        ws = speech.sound_words(it['clip'], b - 3, b + 3, cached=True)
        r = endings.ending(it['clip'], b, ws) if ws else None
        if r and r['open']:
            out.append({'at': round(e, 2), 'id': it.get('id'),
                        'problem': f"{it.get('id')} ends on \"{r['word']}\" but the thought may not be finished: "
                                   + endings.describe(r) + "; end on a line that lands, or find a take that does"})
    return out


def ending_findings(project, talk_long=False):
    """[{'at', 'id', 'problem', 'severity'}] on the video's ending. A last line the source carries straight on from
    (ending_words) is minor; in a long talk video (a conversation, an interview or a podcast) it is major, and so is
    the source's own goodbye left out just after the cut (endings.goodbye: "see you guys later, bye" starts within
    30 s of the last clip's out point and the cut's last 20 s hold no sign-off). Words only."""
    out = [{**f, 'severity': 'major' if talk_long else 'minor'} for f in ending_words(project)]
    if not talk_long:
        return out
    import letitedit.timeline.edit_script as es
    import letitedit.footage.endings as endings
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import NOT_SPEECH, _muted
    ends = []
    for t in es.read(project)['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        ends += [(e, it) for it, s, e in layout(t)
                 if 'clip' in it and not it.get('reverse') and not _muted(it) and float(it.get('speed', 1)) == 1]
    if not ends:
        return out
    e, it = max(ends, key=lambda x: x[0])
    b = float(it['out'])
    ws = speech.sound_words(it['clip'], b - endings.GOODBYE_BEFORE_S, b + endings.GOODBYE_AFTER_S + 3, cached=True)
    g = endings.goodbye(ws or [], b)
    if g:
        out.append({'at': round(e, 2), 'id': it.get('id'), 'severity': 'major',
                    'problem': f"the video stops before the talk's own goodbye: in the source \"{g['phrase']}\" starts "
                               f"{g['after_s']:g} s after {it.get('id')} ends (\"{g['said']}\", over at {g['ends_at']:g} s "
                               f"in the source), and the cut's last {endings.GOODBYE_BEFORE_S:g} s hold no sign-off: end "
                               "on a closing line (that goodbye, or a line that wraps the talk up)"})
    return out


# Said twice on purpose: a doubled word from this list, or a repeat joined by one of these words ("again and again").
_EMPHATIC_WORDS = {'very', 'really', 'so', 'no', 'yes', 'yeah', 'ok', 'okay', 'go', 'hey', 'bye', 'ha', 'hmm', 'more', 'now',
                   'wow', 'oh', 'please', 'too', 'never', 'right', 'that', 'had', 'is', 'wait', 'come', 'on', 'knock',
                   'tick', 'tock', 'many', 'much', 'long', 'far', 'big', 'little', 'again', 'run', 'stop', 'look'}
_REPEAT_JOINS = {'and', 'or', 'by', 'after', 'to', 'upon', 'over'}
_EMPHATIC_PHRASES = {('i', 'know'), ('come', 'on'), ('no', 'way'), ('right', 'now'), ('thank', 'you'), ('oh', 'my'),
                     ('let', 'me'), ('you', 'know'), ('i', 'mean'), ('look', 'at'), ('go', 'on'), ('hold', 'on')}
_RESTART_LONGEST = 5    # words of a first try: a longer stretch that comes back is a refrain, not a restart
_RESTART_ADDED = 2      # words the second try may add to the first
_RESTART_GAP_S = 0.3    # a pause or a cut this long between the tries counts against "said so on purpose"


def _spoken_token(word):
    return re.sub(r"[^\w']", '', str(word)).lower()


def restart_phrases(words, gaps=None):
    """[(i, j, end)]: indexes into words (strings) where a phrase begun at i is dropped and begun again at j, up to end
    (exclusive): the first try's words all come back, in order, at the start of the second, which may add a word or two
    ("without the LLM, without risking the LLM"; "the the"). gaps[j]: seconds of pause or a cut before word j, when known;
    an exact completed sentence repeated with no gap is taken as said twice on purpose, but a second try adding
    corrective words is still checked. Pure text: no sound, no times."""
    tokens = [_spoken_token(w) for w in words]
    out, i, n, refrain_end = [], 0, len(tokens), 0
    while i < n - 1:
        found = None
        for j in range(i + 1, min(n, i + _RESTART_LONGEST + 1)):
            if not tokens[i] or tokens[j] != tokens[i]:
                continue
            first = tokens[i:j]
            if len(first) == 1 and first[0] in _EMPHATIC_WORDS:
                break
            if len(first) == 2 and first[1] in _REPEAT_JOINS:
                break                                   # again and again, step by step
            if len(first) == 2 and first[0] in _REPEAT_JOINS and i and tokens[i - 1] == first[1]:
                break                                   # the same, read from the second word
            if tuple(first) in _EMPHATIC_PHRASES:
                break
            gap = gaps[j] if gaps else 0.0
            sentence_end = str(words[j - 1]).rstrip().endswith(('.', '?', '!'))
            at, k = 0, j
            while k < n and at < len(first) and k - j < len(first) + _RESTART_ADDED:
                if tokens[k] == first[at]:
                    at += 1
                k += 1
            if at == len(first):
                if sentence_end and gap < _RESTART_GAP_S and k - j == len(first):
                    break
                # the same words twice with nothing added, three or more times over, is a refrain
                if (tokens[k:k + len(first)] == first and k - j == len(first)
                        and (not gaps or all((gaps[x] or 0) < _RESTART_GAP_S for x in (j, k) if x < n))):
                    while tokens[k:k + len(first)] == first:
                        k += len(first)
                    refrain_end = k
                    break
                found = (i, j, k)
            break
        if found:
            out.append(found)
            i = found[2]
        else:
            i = max(i + 1, refrain_end)
    return out


def _kept_speech(project):
    """The spoken words the cut keeps, in timeline order, each word once: [{'w', 'at', 'gap', 'id', 'word', 'clip',
    'a', 'b', 's'}]; 'at' is timeline seconds, 'gap' the pause or cut before it (the sound-measured times; a cut counts as
    a second)."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import NOT_SPEECH, _muted
    out, seen = [], set()
    pieces = []
    for t in es.read(project)['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            if 'clip' in it and not it.get('reverse') and not _muted(it) and float(it.get('speed', 1)) == 1:
                pieces.append((s, e, it))
    pieces.sort(key=lambda p: p[0])
    for s, e, it in pieces:
        a, b = float(it['in']), float(it['out'])
        before = None
        # by the word's sound: the transcript's own start can sit in the pause before it, so a range by that loses it
        for w in speech.sound_words(it['clip'], a - 3, b + 3, cached=True) or []:
            ws, we = float(w['s']), float(w['e'])
            if min(we, b) - max(ws, a) < 0.5 * (we - ws) and not (speech.stretched(w) and min(we, b) > max(ws, a)):
                continue
            key = (it['clip'], round(float(w.get('asr_s', ws)), 2))
            if key in seen:         # one word over a cut shows in the pieces on both sides
                continue
            seen.add(key)
            gap = 1.0 if before is None else max(0.0, ws - before)
            before = we
            out.append({'w': w['w'], 'at': round(s + max(0.0, ws - a), 2), 'gap': gap, 'id': it.get('id'), 'word': w,
                        'clip': it['clip'], 'a': a, 'b': b, 's': s})
    return out


def _folded_restarts(kept):
    """Stretched words (speech.stretched) whose kept part holds separate sounds: the transcriber folded a pause and more
    speech into one word, so the words alone can't show a restart that is still in the cut."""
    import letitedit.footage.speech as speech
    out = []
    for k in kept:
        w = k['word']
        if not speech.stretched(w):
            continue
        s0, e0 = max(float(w['s']), k['a']), min(float(w['e']), k['b'])
        if e0 <= s0:
            continue
        try:                # a wider stretch, so the level's floor comes from the real pauses
            spans = speech.bursts(k['clip'], max(0.0, s0 - 2), e0 + 2)
        except Exception:   # noqa: BLE001 - no sound to measure: the check says nothing
            continue
        inside = [(max(a, s0), min(b, e0)) for a, b in spans if min(b, e0) - max(a, s0) >= 0.12]
        apart = [y[0] - x[1] for x, y in zip(inside, inside[1:])]
        if len(inside) < 2 or max(apart) < 0.25:
            continue
        out.append({'at': round(k['s'] + inside[0][0] - k['a'], 2), 'id': k['id'], 'said': w['w'].strip(), 'folded': True,
                    'problem': f"{k['id']} may keep a restart: the transcript's \"{w['w'].strip()}\" lasts "
                               f"{speech.stretched(w):g} s at source {s0:.2f}-{e0:.2f} and holds {len(inside)} separate sounds "
                               f"(at {', '.join(f'{a:.2f}-{b:.2f}' for a, b in inside)}), so more was said there than the words show; "
                               f"letitedit_hear(source, start={s0:.2f}, end={e0:.2f}) has what's said; in: {inside[-1][0] - 0.06:.2f} "
                               "starts on the last try"})
    return out


def false_starts(project):
    """[{'at', 'id', 'problem'}]: restarts left in the cut (timeline seconds), a phrase begun, dropped and begun again, from
    the words the cut keeps (restart_phrases) and from words the transcript stretched over other sound. Measures only what
    is already transcribed; said twice on purpose reads the same to it, so the finding says what was found and where."""
    kept = _kept_speech(project)
    out = _folded_restarts(kept)
    for i, j, end in restart_phrases([k['w'] for k in kept], [k['gap'] for k in kept]):
        said = ' '.join(k['w'].strip() for k in kept[i:end])
        out.append({'at': kept[i]['at'], 'id': kept[i]['id'], 'said': said, 'first': j - i,
                    'open_end': _spoken_token(kept[j - 1]['w']) in OPEN_ENDS, 'added': (end - j) - (j - i),
                    'problem': f"a phrase is begun and begun again at {fmt(kept[i]['at'])}: \"{said}\" "
                               f"(the first try ends where \"{kept[j]['w'].strip()}\" comes back, {fmt(kept[j]['at'])})"})
    return sorted(out, key=lambda f: f['at'])


KEPT_LINE = re.compile(r'\bkept\b|\bkeep\b|\bkeeps\b|on purpose|deliberate|emphasis|emphatic', re.I)


def kept_on_purpose(project, said):
    """The line of the project's fine or finish notes (fine_pass.md, finish_pass.md) that keeps these words on purpose
    ("kept on purpose: 'pretty, pretty freaking magical' (emphasis)"), or None: a line that says kept, on purpose,
    deliberate or emphasis and quotes the words, punctuation aside."""
    import letitedit.timeline.project_journal as project_journal
    words = lambda text: [w.strip("'") for w in re.findall(r"[\w']+", text.lower().replace('’', "'")) if w.strip("'")]
    want = words(str(said))
    if not want:
        return None
    for name in ('fine_pass.md', 'finish_pass.md'):
        path = project_journal.folder(project) / name
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for line in text.splitlines():
            if not KEPT_LINE.search(line):
                continue
            # the part of the line from "kept" on, so a "Cut: ..." list earlier on the same line doesn't count
            part = line[KEPT_LINE.search(line).start():]
            got = words(part)
            if any(got[k:k + len(want)] == want for k in range(len(got) - len(want) + 1)):
                return line.strip()
    return None


# Words a sentence can't stop on: a first try that ends on one was abandoned mid-sentence ("we're pretty sure he...").
OPEN_ENDS = {'a', 'an', 'the', 'my', 'our', 'your', 'his', 'her', 'their', 'its', 'this', 'these', 'those', 'to',
             'of', 'in', 'on', 'at', 'for', 'with', 'from', 'by', 'about', 'into', 'and', 'but', 'or', 'because', 'if',
             'when', 'i', 'we', 'you', 'he', 'she', 'they', "i'm", "we're", "you're", "they're", "he's", "she's",
             "it's", "i've", "we've", "they've", "i'd", "we'd", 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has',
             'had', 'do', 'does', 'did', 'will', 'would', 'can', 'could', 'should', 'gonna', 'wanna', 'gotta', 'very',
             'really', 'more', 'most', 'not', "don't", "didn't", "can't", "won't"}
CLEAR_START_WORDS = 3       # a first try this long that stops mid-sentence and is begun again is a false start a viewer hears
# Kinds of video whose talk is a conversation (the brief's mode, as letitedit-modes names them)
CONVERSATION_MODES = {'interview', 'podcast', 'podcast_excerpt', 'conversation', 'panel', 'talk_show', 'livestream',
                      'roundtable', 'debate'}
TALK_KINDS = ('natural', 'clean')


def _mode_key(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return re.sub(r'[\s/-]+', '_', str(value or '').strip().lower())


def talk_kind(project, brief=None):
    """(kind, why): how clean the cut's talk should be. 'natural' for a conversation (the brief's `talk`, else its
    Look's `talk`, else the brief's mode is an interview or podcast, else the cut switches between angles of one talk),
    where doubled words and quick self-corrections are left in and only a clear false start is cut; 'clean' otherwise
    (a scripted video or a talking head: every restart is cut or kept on purpose)."""
    try:
        import letitedit.review.brief_check as brief_check
        data = brief_check.load(brief, project) if (brief or project) else None
    except Exception:  # noqa: BLE001 - no brief read: the cut itself still says
        data = None
    data = data if isinstance(data, dict) else {}
    talk = str(data.get('talk') or '').lower()
    if talk in TALK_KINDS:
        return talk, f"the brief says talk: {talk}"
    look = data.get('look')
    if look not in (None, '', 'auto', 'none', 'freestyle'):
        try:
            import letitedit.looks.looks as looks
            card = looks.offered(look) or {}
        except Exception:  # noqa: BLE001
            card = {}
        if card.get('talk') in TALK_KINDS:
            return card['talk'], f"the Look \"{card.get('label') or look}\" keeps its talk {card['talk']}"
    mode = _mode_key(data.get('mode') or data.get('genre'))
    if mode in CONVERSATION_MODES:
        return 'natural', f"the brief's mode is {mode.replace('_', ' ')}"
    if project and str(project).lower().endswith('.mlt'):
        try:
            import letitedit.timeline.edit_script as es
            if any(isinstance(item.get('multicam'), dict) for track in es.read(project).get('tracks') or []
                   for item in track.get('items') or []):
                return 'natural', 'the cut switches between camera angles of one talk'
        except Exception:  # noqa: BLE001
            pass
    return 'clean', ''


def clear_false_start(finding):
    """True for a restart a viewer hears as a false start even in a conversation: a first try of three words or more
    that stops on a word a sentence can't end on, then is begun again ("we're pretty sure he, we're pretty sure he").
    Doubled words ("the the"), a phrase said twice whole ("rat traps, rat traps") and a quick self-correction that adds
    words ("not a mouse, not a tiny little mouse") are not; nor is a word the transcript stretched over other sound."""
    return (not finding.get('folded') and finding.get('first', 0) >= CLEAR_START_WORDS
            and bool(finding.get('open_end')))


def restarts_left(project):
    """The restarts false_starts finds in the cut that the fine or finish notes don't keep on purpose; in natural talk
    (talk_kind) only the clear false starts."""
    natural = talk_kind(project)[0] == 'natural'
    return [f for f in false_starts(project) if (not natural or clear_false_start(f))
            and not kept_on_purpose(project, f.get('said', ''))]


# Sound labels a transcriber writes for what isn't speech: "(bell ringing)", "[Music]", music notes.
SOUND_LABEL = re.compile(r'\([^()]*\)|\[[^\[\]]*\]|[♪♫♬]+')


def spoken_restarts(cues):
    """[{'at', 'problem'}]: the same check on a render's own transcript [(start, end, text)], which hears what the editing
    transcript folded away. Times are the cue's; there are no pauses to measure, so a sentence end reads as on purpose.
    Sound labels in brackets or parentheses and music notes are not words, so they are left out."""
    words = []
    for s, e, text in cues:
        said = SOUND_LABEL.sub(' ', str(text)).split()
        words += [(w, s + (e - s) * n / len(said)) for n, w in enumerate(said)]
    out = []
    for i, j, end in restart_phrases([w for w, _ in words]):
        said = ' '.join(w for w, _ in words[i:end])
        out.append({'at': round(words[i][1], 2),
                    'problem': f"a phrase is begun and begun again near {fmt(words[i][1])} in the render's own transcript: \"{said}\""})
    return out


def audio_signature(project, moved=()):
    """A short hash of what can change the sound: every clip's source, in and out points, speed and place on the timeline
    on every track that plays sound, the audio tracks and the effects that touch level or sound (volume, fades, fixes,
    ducking). Picture-only effects, captions and graphics don't count. The journal's sound_check carries it, so the review
    can tell whether the mix was measured on the cut it is looking at.

    Each source is named by what it is, not where it is (export_checks.file_identity, T347), so a project that is
    moved keeps its signature; the signature starts AUDIO_PREFIX. A signature without it is an older one
    (audio_signature_legacy). `moved` [(folder then, folder now)]: a project moved with its files whose saved paths
    still name the old folder (export_checks.project_moves)."""
    import hashlib
    return AUDIO_PREFIX + hashlib.sha256(audio_content(project, moved).encode('utf-8')).hexdigest()[:16]


def audio_content(project, moved=()):
    """What audio_signature hashes, as text (export_checks.located_text of the sound's rows)."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.export_checks as export_checks
    return export_checks.located_text(_audio_rows(es.read(project)), export_checks.project_folder(project), moved)


AUDIO_PREFIX = 'v2-'


def audio_signature_legacy(script):
    """The sound signature as it was before T347, from an edit script: each clip's source as its path is written. The
    journal's older sound_checks carry it."""
    import hashlib
    rows = _audio_rows(script)
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _audio_rows(script):
    from letitedit.timeline.edit_sync import layout
    rows = []
    for track in script.get('tracks') or []:
        for item, a, b in layout(track):
            if 'clip' not in item:
                continue
            fx_ = [e for e in item.get('effects') or []
                   if re.search(r'vol|gain|level|fade|audio|duck|declick|fix|score|mute|pan', json.dumps(e, default=str), re.I)]
            rows.append([track.get('name'), item.get('clip'), item.get('in'), item.get('out'), item.get('speed'),
                         round(a, 3), round(b, 3), fx_])
    return rows


def _audio_key(project, stems, target_lufs, start_s, end_s, every_s, quiet_lu):
    """What a mix measurement depends on besides the cut: the settings, with stems=None resolved the way audio()
    resolves it (a track named Music*)."""
    if stems is None:
        timeline, _ = resolve(project)
        stems = any(re.match(r'(?i)music', t.name) for t in timeline.audio_tracks())
    num = lambda v: None if v is None else round(float(v), 3)
    return json.dumps([bool(stems), num(target_lufs), num(start_s), num(end_s), num(every_s), num(quiet_lu)])


def _audio_store(project):
    import letitedit.timeline.project_journal as project_journal
    return project_journal.folder(project) / 'sound_check.json'


def audio_measured(project, signature, stems=None, target_lufs=-14.0, start_s=None, end_s=None, every_s=None,
                   quiet_lu=15.0):
    """(png bytes, report) of the last measurement with these settings on a cut with this sound signature
    (audio_signature), or None: the same cut measured again gives the same numbers, so it isn't rendered again."""
    try:
        key = _audio_key(project, stems, target_lufs, start_s, end_s, every_s, quiet_lu)
        kept = json.loads(_audio_store(project).read_text(encoding='utf-8-sig')).get(key)
        if kept and kept.get('signature') == signature and Path(kept['png']).is_file():
            return Path(kept['png']).read_bytes(), kept['report']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def audio_keep(project, signature, png, report, stems=None, target_lufs=-14.0, start_s=None, end_s=None, every_s=None,
               quiet_lu=15.0):
    """Remember a measurement for audio_measured (beside the project, the last 8 settings)."""
    try:
        store = _audio_store(project)
        store.parent.mkdir(parents=True, exist_ok=True)
        key = _audio_key(project, stems, target_lufs, start_s, end_s, every_s, quiet_lu)
        png_path = store.with_name(f"sound_check-{hashlib.sha1(key.encode()).hexdigest()[:8]}.png")
        png_path.write_bytes(png)
        try:
            kept = json.loads(store.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            kept = {}
        kept.pop(key, None)
        kept[key] = {'signature': signature, 'png': str(png_path), 'report': report}
        kept = dict(list(kept.items())[-8:])
        tmp = store.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(kept, indent=1, default=str), encoding='utf-8')
        tmp.replace(store)
    except (OSError, TypeError, ValueError):
        pass        # the measurement stands without the memory


SUBTITLE_MIN_S = 5 / 6     # the shortest a subtitle cue should stay up (Netflix Timed Text Style Guide: 5/6 s)


def _caption_reading_findings(script, es, add):
    """Check caption phrases and summarize upload-subtitle reading speed."""
    fast_subtitles = []        # (characters a second, start, text) on tracks not drawn on the picture
    short_subtitles = []       # (seconds on screen, start, text) on those tracks, under SUBTITLE_MIN_S
    for cap in script.get('captions') or []:
        for q in cap.get('cues') or []:
            a, b = es.to_seconds(q['start']), es.to_seconds(q['end'])
            text = str(q.get('text') or '').replace('\n', ' ').strip()
            if re.search(r'[.!?]\s+\w', text):
                add(a, f'caption combines separate sentences: "{text[:75]}"')
            # a sentence's own last word ("what our bodies can adapt to.") ends the thought: not a broken phrase
            if text.split() and not re.search(r'[.!?…]["\'”’)\]]*$', text) and re.sub(
                    r'[^\w]+', '', text.split()[-1].lower()) in {
                    'a', 'an', 'the', 'to', 'of', 'for', 'with', 'and', 'but', 'my', 'our', 'your'}:
                add(a, f'caption ends on a dangling word: "{text[:75]}"')
            if b > a and len(text) / (b - a) > 20:
                if cap.get('burn_in', True):
                    add(a, f'caption reads at {len(text) / (b - a):.0f} characters a second: "{text[:60]}"')
                else:
                    fast_subtitles.append((len(text) / (b - a), a, text))
            if not cap.get('burn_in', True) and text and 0 < b - a < SUBTITLE_MIN_S:
                short_subtitles.append((b - a, a, text))
    if short_subtitles:
        # what does make upload subtitles hard to read: a cue gone before it can be read (Netflix's minimum, 5/6 s)
        add(min(a for _, a, _ in short_subtitles),
            f'{len(short_subtitles)} subtitle cue(s) for upload are on screen for less than {SUBTITLE_MIN_S:.2f} s, too short '
            'to read; the shortest: ' + '; '.join(f'{fmt(a)} for {d:.2f} s "{text[:40]}"'
                                                 for d, a, text in sorted(short_subtitles)[:3])
            + '. Merge each into the cue beside it, or make the subtitles from whole phrases')
    if fast_subtitles:
        # Subtitles for upload (not drawn on the picture) are turned on by the viewer and follow the speech word for
        # word: a fast talker's subtitles run past 20 characters a second whatever the cue breaks, so one count, not a
        # major per cue (captions on the picture, which every viewer reads, stay one finding each)
        worst = sorted(fast_subtitles, reverse=True)[:3]
        add(min(a for _, a, _ in fast_subtitles),
            f'{len(fast_subtitles)} subtitle cue(s) for upload (not on the picture) read faster than 20 characters a '
            'second, as fast speech does word for word; the fastest: '
            + '; '.join(f'{fmt(a)} at {cps:.0f} a second "{text[:40]}"' for cps, a, text in worst), 'minor')


def _caption_position_findings(script, es, frame, layout, project, cue_ink, add):
    """Check measured caption ink against faces and available vertical space."""
    # Where the captions' own ink is, caption by caption (a word-by-word caption is a chunk of its own with its own
    # moment), against the face as the viewer sees it: the detector's face box and landmarks, the same measure
    # caption_fit uses (caption_layout.covers_face_part). The neck and the chest are not the face.
    entries = []                                  # (start, end, ink box in pixels, text)
    for cap in script.get('captions') or []:
        if cap.get('burn_in') is False:
            continue
        for q in cap.get('cues') or []:
            a, b = es.to_seconds(q['start']), es.to_seconds(q['end'])
            ink = cue_ink(cap, q)
            boxes = [ink] if ink else frame.captions_at(a, b)       # no measurable ink: where the caption is laid out
            for box in boxes:
                entries.append((a, b, (box[0] * frame.w, box[1] * frame.h, box[2] * frame.w, box[3] * frame.h),
                                str(q.get('text') or '').replace('\n', ' ').strip()))
    try:
        import letitedit.pictures.caption_layout as cl
        wc = cl.WordCaptions(es.kit_for(script), cl.frame_spec(script['profile']))
        for track in script['tracks']:
            if track.get('kind', 'video') != 'video' or track.get('hide') in ('video', 'both'):
                continue
            for item, a, b in layout(track):
                g = item.get('graphic') or {}
                if g.get('template') != 'word_captions':
                    continue
                params = wc.normalise(g.get('params') or {}, b - a)
                ink = wc.record(params, b - a).get('ink')
                if ink:
                    entries.append((a, b, tuple(ink), ' '.join(str(w[0]) for w in params.get('words') or [])))
    except Exception:  # noqa: BLE001 - a caption that can't be measured is not called a fault
        pass
    seen = {}
    try:
        import letitedit.pictures.caption_layout as cl
        seen = cl.faces_detail_at(project, [round((a + b) / 2, 2) for a, b, _, _ in entries], max_frames=400)
    except Exception:  # noqa: BLE001 - the source-frame check below still runs
        seen = {}
    for a, b, ink, text in sorted(entries):
        mid = round((a + b) / 2, 2)
        faces = seen.get(mid)
        if faces is None:
            known = frame.faces((a + b) / 2)
            faces = None if known is None else [((x0 * frame.w, y0 * frame.h, x1 * frame.w, y1 * frame.h), None)
                                                  for x0, y0, x1, y1 in known]
        import letitedit.pictures.caption_layout as cl
        if any(cl.covers_face_part(ink, box, pts) for box, pts in faces or []):
            add(a, f'caption covers the face or mouth: "{text[:60]}"')
    # Where the room is: below the lowest chin in the video, down to the area TikTok and Shorts leave free (Reels' ad
    # guidance, the bottom 35%, is not applied here). Captions sitting well above the middle of that room, close under
    # the face, are one finding for the video, with the place to put them.
    try:
        import letitedit.pictures.caption_layout as cl
        chins = [box[3] for faces in seen.values() for box, _ in faces]
        if chins and entries and frame.h > frame.w * 1.05:
            top, bottom = max(chins), cl.frame_spec(script['profile'], 'tiktok').safe[3]
            centre = (top + bottom) / 2
            heights = sorted(ink[3] - ink[1] for _, _, ink, _ in entries)
            if bottom - top >= 1.5 * heights[len(heights) // 2]:
                high = [(a, ink) for a, _, ink, _ in sorted(entries) if (ink[1] + ink[3]) / 2 < centre - 0.05 * frame.h]
                if high:
                    mid = sorted((ink[1] + ink[3]) / 2 for _, ink in high)[len(high) // 2]
                    add(high[0][0], f'captions sit high: {len(high)} of {len(entries)} are centred at about '
                        f'{100 * mid / frame.h:.0f}% of the frame height, close under the face, while the room below '
                        f'the lowest chin ({100 * top / frame.h:.0f}%) down to where the apps cover the picture '
                        f'({100 * bottom / frame.h:.0f}%) has its middle at {100 * centre / frame.h:.0f}%; '
                        f'put them there, one place for the whole video (letitedit_caption_fit places them at '
                        f'"free"; this check cannot see a hand or a graphic that needs that spot)')
    except Exception:  # noqa: BLE001 - a placement this cannot measure is not called a fault
        pass


def _effect_quality_findings(script, layout, fx, frame, words, add):
    """Check effect overlap, speech timing, crowding and heavy glitches over faces."""
    effects = []
    for track in script['tracks']:
        if track.get('kind', 'video') == 'audio':
            continue      # sound effects (`fx-sfx-N`, `<id>-sfx`): their timing is measured against what they are for
        for item, a, b in layout(track):
            iid = str(item.get('id') or '')
            if not iid.startswith(('fx-', 'pop-')) or iid.endswith('-sfx'):
                continue
            g = item.get('graphic') or {}
            p = g.get('params') or {}
            kind = 'text_pop' if p.get('text') else 'popup'
            box = fx._placed_box(item, frame)
            effects.append((iid, a, b, kind))
            if p.get('text') and fx._same_caption(p['text'], frame.caption_words_at(a, b)):
                add(a, f'{iid} repeats the caption words: "{p["text"]}"')
            if box and any(fx._inter(box, c) > 0.02 * min(fx._area(box), fx._area(c))
                           for c in frame.captions_at(a, b)):
                add(a, f'{iid} covers the captions')
            if any(w['t0'] + 0.04 < a < w['t1'] - 0.04 for w in words):
                add(a, f'{iid} starts in the middle of a spoken word')
    effects.sort(key=lambda x: x[1])
    for (iid, a, b, _), (next_id, next_a, _, _) in zip(effects, effects[1:]):
        if next_a - a < 0.35:
            add(next_a, f'{next_id} starts {next_a - a:.2f} s after {iid}; effects are crammed together')
    for track in script['tracks']:
        for item, start, end in layout(track):
            if 'clip' not in item:
                continue
            for effect in item.get('effects') or []:
                if not isinstance(effect, dict) or effect.get('filter') != 'glitch':
                    continue
                amount = effect.get('params', {}).get('0')
                keys = amount.get('keys') if isinstance(amount, dict) else None
                if not keys or max(float(k[1]) for k in keys) < 0.4:
                    continue
                at = start + float(keys[0][0])
                if frame.faces(at + min(0.15, (end - at) / 2)):
                    add(at, f'{item.get("id")} has a heavy glitch over a face')


def edit_quality_findings(project):
    """Measured caption and effect faults on a project, using cached words and source frames."""
    import letitedit.timeline.edit_script as es
    import letitedit.looks.fx as fx
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import timeline_words

    script = es.read(project)
    frame = fx.Frame(script, es.kit_for(script))
    words = timeline_words(script, cached_only=True)
    out = []
    def cue_ink(cap, cue):
        """Use the cue's text, not its whole alignment rectangle, for face checks."""
        try:
            import letitedit.pictures.caption_layout as cl
            style = cap['style']
            profile = script['profile']
            frame_spec = cl.frame_spec(profile)
            rect = cl.parse_geometry(style['geometry'], frame_spec.width, frame_spec.height)
            ink = cl.QtText(style, frame_spec).block(str(cue.get('text') or '').split('\n'), rect)['ink']
            if ink:
                return (ink[0] / frame_spec.width, ink[1] / frame_spec.height,
                        ink[2] / frame_spec.width, ink[3] / frame_spec.height)
        except (KeyError, TypeError, ValueError, OSError):
            pass
        return None
    def add(at, problem, severity=None):
        out.append({'at': round(at, 2), 'problem': problem, **({'severity': severity} if severity else {})})
    _caption_reading_findings(script, es, add)

    _caption_position_findings(script, es, frame, layout, project, cue_ink, add)

    _effect_quality_findings(script, layout, fx, frame, words, add)

    for start, item in _shrunk_into_fill(script):
        add(start, f'{item.get("id")} shrinks footage that already fills the frame into a blurred border: remove that '
                   'effect, let the footage fill the frame and move the caption instead')
    return out


def caption_text_boxes(project):
    """[(start_s, end_s, (x0, y0, x1, y1) fractions, text)]: where each burned-in caption's text sits on screen. A
    caption track's cue is its text's own box (its ink), else its alignment rectangle; a word-by-word caption block is
    the box the caption template lays it out in."""
    import letitedit.timeline.edit_script as es
    import letitedit.looks.fx as fx
    script = es.read(project)
    profile = script['profile']
    w, h = float(profile['width']), float(profile['height'])
    out, spans = [], []
    for cap in script.get('captions') or []:
        if cap.get('burn_in') is False:
            continue
        style = cap.get('style') or {}
        for cue in cap.get('cues') or []:
            s, e = es.to_seconds(cue['start']), es.to_seconds(cue['end'])
            spans.append((round(s, 3), round(e, 3)))
            box = None
            try:
                import letitedit.pictures.caption_layout as cl
                frame_spec = cl.frame_spec(profile)
                rect = cl.parse_geometry(style['geometry'], frame_spec.width, frame_spec.height)
                ink = cl.QtText(style, frame_spec).block(str(cue.get('text') or '').split('\n'), rect)['ink']
                if ink:
                    box = (ink[0] / frame_spec.width, ink[1] / frame_spec.height,
                           ink[2] / frame_spec.width, ink[3] / frame_spec.height)
                elif rect:
                    box = (rect[0] / w, rect[1] / h, (rect[0] + rect[2]) / w, (rect[1] + rect[3]) / h)
            except (KeyError, TypeError, ValueError, OSError):
                box = None
            if box:
                out.append((s, e, box, str(cue.get('text') or '')))
    # the frame's caption boxes are the caption tracks' rectangles and then the word-by-word blocks: keep the blocks
    left = list(spans)
    for s, e, box in fx.Frame(script, es.kit_for(script)).captions:
        key = (round(s, 3), round(e, 3))
        if key in left:
            left.remove(key)
            continue
        out.append((s, e, box, 'word captions'))
    # subtitles drawn into a layer of their own (an .ass script the engine renders to a transparent clip)
    import letitedit.timeline.made as made
    for t in script.get('tracks') or []:
        if t.get('kind', 'video') != 'video' or 'video' in str(t.get('hide') or ''):
            continue
        for it in t.get('items') or []:
            doc = it.get('ass')
            if isinstance(doc, dict):
                doc = doc.get('script')
            if not doc:
                continue
            at = es.to_seconds(it.get('at') or 0)
            length = es.to_seconds(it['len']) if it.get('len') is not None else None
            for s, e, box, text in ass_boxes(made.ass_document(str(doc), int(w), int(h))):
                if length is None or s < length:
                    out.append((at + s, at + (min(e, length) if length is not None else e), box, text))
    return sorted(out, key=lambda b: b[0])


_ASS_TIME_RE = re.compile(r'(\d+):(\d\d):(\d\d(?:\.\d+)?)')


def ass_boxes(doc):
    """[(start_s, end_s, (x0, y0, x1, y1) fractions, text)] for an .ass document's Dialogue lines, from its own layout:
    the style's alignment, margins and font size, a line's own margins, and \\pos and \\an overrides. The width is
    estimated from the longest line (about 0.55 of the font size a character); a line drawn twice at one place (a halo
    under the text) is one box."""
    res, styles, fmt_style, fmt_event, out, seen = {'x': 384.0, 'y': 288.0}, {}, None, None, [], set()
    for raw in doc.splitlines():
        line = raw.strip()
        key, _, rest = line.partition(':')
        if key == 'PlayResX':
            res['x'] = float(rest)
        elif key == 'PlayResY':
            res['y'] = float(rest)
        elif key == 'Format' and fmt_style is None and 'Fontsize' in rest:
            fmt_style = [x.strip() for x in rest.split(',')]
        elif key == 'Format' and 'Text' in rest:
            fmt_event = [x.strip() for x in rest.split(',')]
        elif key == 'Style' and fmt_style:
            vals = [x.strip() for x in rest.split(',')]
            styles[vals[0]] = dict(zip(fmt_style, vals))
        elif key == 'Dialogue' and fmt_event:
            vals = rest.split(',', len(fmt_event) - 1)
            ev = dict(zip(fmt_event, [v.strip() for v in vals]))
            st = styles.get(ev.get('Style')) or next(iter(styles.values()), {})
            text = ev.get('Text') or ''
            plain = re.sub(r'\{[^}]*\}', '', text).replace('\\h', ' ')
            lines = [x for x in re.split(r'\\[Nn]', plain)]
            if not plain.strip():
                continue
            times = [_ASS_TIME_RE.fullmatch(ev.get(k, '')) for k in ('Start', 'End')]
            if not all(times):
                continue
            s, e = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) for m in times)
            def num(name, default=0.0):
                try:
                    v = float(ev.get(name) or 0)
                    return v if v else float(st.get(name) or default)
                except ValueError:
                    return default
            size = float(st.get('Fontsize') or 0.06 * res['y'])
            align = int(st.get('Alignment') or 2)
            an = re.search(r'\\an(\d)', text)
            align = int(an.group(1)) if an else align
            bw = max(len(x) for x in lines) * size * 0.55
            bh = len(lines) * size * 1.2
            pos = re.search(r'\\pos\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)', text)
            col, row = (align - 1) % 3, (align - 1) // 3          # 0 left / centre / right; 0 bottom / middle / top
            if pos:
                ax, ay = float(pos.group(1)), float(pos.group(2))
            else:
                ml, mr, mv = num('MarginL'), num('MarginR'), num('MarginV')
                ax = (ml, (ml + res['x'] - mr) / 2, res['x'] - mr)[col]
                ay = (res['y'] - mv, res['y'] / 2, mv)[row]
            x0 = (ax, ax - bw / 2, ax - bw)[col]
            y0 = (ay - bh, ay - bh / 2, ay)[row]
            box = (max(0.0, x0 / res['x']), max(0.0, y0 / res['y']),
                   min(1.0, (x0 + bw) / res['x']), min(1.0, (y0 + bh) / res['y']))
            mark = (round(s, 2), round(e, 2), plain, tuple(round(v, 3) for v in box))
            if mark in seen:
                continue
            seen.add(mark)
            out.append((s, e, box, plain.replace('\\N', ' ')))
    return out


def _fill_effect(effect):
    """An effect that puts the picture inside a blurred fill: blur_pad, or an ffmpeg graph that overlays over a blur."""
    if effect == 'blur_pad' or (isinstance(effect, dict) and 'blur_pad' in effect):
        return True
    graph = effect.get('ffmpeg') if isinstance(effect, dict) else None
    text = graph.get('video') if isinstance(graph, dict) else graph
    return isinstance(text, str) and 'overlay' in text and bool(re.search(r'(box|g|avg|smart)blur', text))


def _shrunk_into_fill(script):
    """[(start, item)] on the main track: footage shaped like the frame (within 3%) inside a blurred fill. Footage of
    another shape, such as wide footage on a vertical frame, may use one."""
    import letitedit.server.core_tools as core_tools
    from letitedit.timeline.edit_sync import layout, main_track
    prof = script.get('profile') or {}
    shape = float(prof.get('width', 1920)) / float(prof.get('height', 1080))
    found = []
    main = main_track(script)
    for item, start, _ in (layout(main) if main else []):
        if not item.get('clip') or not any(_fill_effect(e) for e in item.get('effects') or []):
            continue
        try:
            info = core_tools.probe(item['clip'])
            w, h = float(info.get('width') or 0), float(info.get('height') or 0)
        except (OSError, ValueError):
            continue
        if w and h and abs((w / h) / shape - 1) < 0.03:
            found.append((start, item))
    return found


def _graphic_bbox(path, t):
    """Box (x0, y0, x1, y1) of the visible pixels of a rendered graphic file at t seconds, or None."""
    from PIL import Image
    if str(path).lower().endswith('.png'):
        img = Image.open(path)
    else:
        for at in (t, t - 0.1, t - 0.25):          # a time in the last frame of the file gives no picture
            r = subprocess.run([str(FFMPEG), '-v', 'error', '-ss', f'{max(0.0, at):.3f}', '-i', str(path), '-frames:v', '1',
                                '-pix_fmt', 'rgba', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                               capture_output=True, creationflags=NO_WINDOW)
            if r.stdout:
                break
        else:
            return None
        img = Image.open(io.BytesIO(r.stdout))
    return img.convert('RGBA').getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox()


def _secs(clock_text):
    """'1:02.5' -> 62.5"""
    try:
        m, sec = str(clock_text).split(':')
        return int(m) * 60 + float(sec)
    except ValueError:
        return -99.0


def _graphics(timeline):
    """[(track, item, recipe)] for every Python-drawn graphic whose rendered file exists."""
    import json as _json
    out = []
    for t in timeline.video_tracks():
        for it in t.items:
            raw = tm.props(it.elem).get('letitedit_ai:graphic') if it.elem is not None else None
            if not raw:
                continue
            try:
                g = _json.loads(raw)
            except ValueError:
                continue
            if g.get('file') and os.path.exists(g['file']):
                out.append((t, it, g))
    return out


def _graphic_label(g):
    p = g.get('params') or {}
    words = p.get('words')
    if words and isinstance(words, list):
        return 'caption "' + ' '.join(str(w[0]) for w in words if w)[:40] + '"'
    text = p.get('title') or p.get('text') or p.get('big') or p.get('label') or ''
    return f"{g.get('template')} '{str(text)[:40]}'" if text else str(g.get('template'))


def graphic_overlaps(timeline, graphics=None, limit=40):
    """[(message, frame)] where two graphics on different tracks are on screen at the same time and their visible
    pixels overlap (text over text)."""
    graphics = graphics if graphics is not None else _graphics(timeline)
    out, fps = [], timeline.fps
    for i, (ta, a, ga) in enumerate(graphics):
        for tb, b, gb in graphics[i + 1:]:
            if ta is tb or a.start >= b.end or b.start >= a.end:
                continue
            lo, hi = max(a.start, b.start), min(a.end, b.end)
            mid = (lo + hi) / 2
            box_a = _graphic_bbox(ga['file'], (mid - a.start) / fps)
            box_b = _graphic_bbox(gb['file'], (mid - b.start) / fps)
            if not box_a or not box_b:
                continue
            ix = min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])
            iy = min(box_a[3], box_b[3]) - max(box_a[1], box_b[1])
            if ix > 8 and iy > 8:
                out.append((f'{_graphic_label(ga)} on {ta.name} and {_graphic_label(gb)} on {tb.name} overlap on screen '
                            f'{fmt(lo / fps)}-{fmt(hi / fps)}', int(mid)))
                if len(out) >= limit:
                    return out
    return out


YUNET = Path(os.environ.get('LETITEDIT_VFX', (_SAI_ROOT + '\\vfx'))) / 'models' / 'yunet_2023mar.onnx'


_FACE_DETECTORS = {}


def faces_available():
    try:
        import cv2
    except ImportError:
        return False
    if not YUNET.exists():                          # first use: OpenCV Zoo face models (38 MB)
        try:
            import letitedit.core.first_use as first_use
            first_use.optional(['opencv-zoo-faces-tracking'], feature='faces in frame checks')
        except ImportError:
            pass
    return YUNET.exists() and hasattr(cv2, 'FaceDetectorYN')


def faces_in(png, width=960):
    """Face boxes (x0, y0, x1, y1) in a rendered frame (OpenCV's YuNet face detector), [] when it isn't available."""
    if not faces_available():
        return []
    import cv2
    img = cv2.imread(str(png))
    if img is None:
        return []
    scale = width / img.shape[1]
    small = cv2.resize(img, (width, round(img.shape[0] * scale)))
    size = (small.shape[1], small.shape[0])
    det = _FACE_DETECTORS.get(size)
    if det is None:
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        det = _FACE_DETECTORS[size] = cv2.FaceDetectorYN.create(str(YUNET), '', size, 0.75, 0.3, 20)
    _, found = det.detect(small)
    if found is None:
        return []
    return [(float(f[0]) / scale, float(f[1]) / scale, float(f[0] + f[2]) / scale, float(f[1] + f[3]) / scale)
            for f in found if f[2] >= 14]


def _pictures_without(path, hide):
    """Copy of the project with the pictures of the given track indices hidden (sound unchanged)."""
    tree = ET.parse(path)
    root = tree.getroot()
    tractors = [e for e in root if e.tag == 'tractor']
    marked = [t for t in tractors if tm.props(t).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    for i, tr in enumerate(main.findall('track')):
        if i in hide:
            tr.set('hide', 'both' if tr.get('hide', '') in ('audio', 'both') else 'video')
    root.set('root', str(Path(path).resolve().parent))
    out = _work('face-variants') / f'{Path(path).stem}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


def graphic_collisions_with_faces(timeline, path, frames, graphics=None, limit=20, max_frames=120):
    """[(message, frame)] where a graphic covers a quarter or more of a face. Faces are found in the picture under
    the graphics (their tracks hidden), so a title across someone's eyes still counts."""
    graphics = graphics if graphics is not None else _graphics(timeline)
    if not graphics or not faces_available():
        return []
    live_at = [(f, [(t, it, g) for t, it, g in graphics if it.start <= f < it.end]) for f in sorted(set(frames))]
    live_at = [(f, live) for f, live in live_at if live]
    if not live_at:
        return []
    if len(live_at) > max_frames:
        step = len(live_at) / max_frames
        live_at = [live_at[int(i * step)] for i in range(max_frames)]
    variant = _pictures_without(path, {t.index for t, _, _ in graphics})
    try:
        pngs = render_frames(timeline, variant, [f for f, _ in live_at], _work('qc-faces'))
    finally:
        variant.unlink(missing_ok=True)
    out, seen, fps = [], set(), timeline.fps
    for (f, live), png in zip(live_at, pngs):
        live = [x for x in live if id(x[1]) not in seen]
        if not live:
            continue
        for fx0, fy0, fx1, fy1 in faces_in(png):
            area = (fx1 - fx0) * (fy1 - fy0)
            for t, it, g in live:
                if id(it) in seen:
                    continue
                box = _graphic_bbox(g['file'], (f - it.start) / fps)
                if not box:
                    continue
                ix = min(box[2], fx1) - max(box[0], fx0)
                iy = min(box[3], fy1) - max(box[1], fy0)
                if ix > 0 and iy > 0 and ix * iy >= 0.25 * area:
                    seen.add(id(it))
                    out.append((f'{_graphic_label(g)} on {t.name} covers {min(100, round(100 * ix * iy / area))}% of a '
                                f'face at {fmt(f / fps)}', f))
                    if len(out) >= limit:
                        return out
    return out


def graphic_caption_collisions(timeline):
    """[(message, frame)] where a Python-drawn graphic covers burnt-in captions that are on screen at the same time."""
    import json as _json
    out = []
    burns = [fp for fp in timeline.burn_filters if fp.get('mlt_service') == 'subtitle' and fp.get('letitedit_ai:role') != 'shadow']
    if not burns:
        return out
    for t in timeline.video_tracks():
        for it in t.items:
            raw = tm.props(it.elem).get('letitedit_ai:graphic') if it.elem is not None else None
            if not raw:
                continue
            g = _json.loads(raw)
            if not g.get('file') or not os.path.exists(g['file']):
                continue
            mid = (it.length / 2) / timeline.fps
            box = _graphic_bbox(g['file'], mid)
            if not box:
                continue
            a, b = it.start / timeline.fps, it.end / timeline.fps
            for fp in burns:
                cues = timeline.subtitle_feeds.get(fp.get('feed'), [])
                hits = [(s, e) for s, e, _ in cues if s < b and e > a]
                if not hits:
                    continue
                try:
                    x, y, w, h = [float(v) for v in str(fp.get('geometry')).split()[:4]]
                except ValueError:
                    continue
                if box[0] < x + w and box[2] > x and box[1] < y + h and box[3] > y:
                    label = g.get('params', {}).get('title') or g.get('params', {}).get('text') or g.get('template')
                    out.append((f"{g.get('template')} '{label}' on {t.name} covers captions ({fp.get('feed')}) between "
                                f"{fmt(max(a, hits[0][0]))} and {fmt(min(b, hits[-1][1]))}: move it (params position / "
                                f"margin_y) or the captions (style position)", it.start))
    return out


def _qc_structure(timeline, add):
    """Check track gaps, source bounds and risky filter ordering."""
    # --- structure
    long_cache = {}
    for t in timeline.tracks:
        prev_end = 0
        for it in t.items:
            if t.kind == 'video' and t is timeline.v1() and it.start > prev_end + 1:
                add('warning', prev_end, f'gap of {(it.start - prev_end) / timeline.fps:.2f} s on {t.name}', it)
            if it.service in ('color', 'transition', 'blank'):
                prev_end = it.end
                continue
            res = it.resource
            if res and not res.startswith(('color:', '#')) and it.service not in ('color',) and not os.path.exists(res):
                add('error', it.start, f'source file missing: {res}', it)
            length = tm.props(it.elem).get('length') if it.elem is not None else None
            if length:
                try:
                    n = tm.clock_to_frames(length, timeline.fps)
                    if it.out >= n:
                        add('error', it.start, f'clip runs past the end of its source ({it.out} >= {n} frames)', it)
                except ValueError:
                    pass
            ids = [f['id'] or f['service'] for f in it.filters]
            for f in it.filters:
                fp = f['props']
                if f['id'] == 'affineSizePosition' and 'blur_pad' in ids and ids.index('blur_pad') < ids.index('affineSizePosition'):
                    add('warning', it.start, 'Size/Position comes after Blur: Pad, so the picture renders as a squeezed strip; '
                                             'put Size/Position first (letitedit_timeline_apply writes them in that order)', it)
                if f['service'] == 'timeremap':
                    fr = tm.props(it.elem).get('meta.media.frame_rate_num') if it.elem is not None else None
                    src_len = tm.props(it.elem).get('length') if it.elem is not None else None
                    try:
                        long_src = src_len and tm.clock_to_frames(src_len, timeline.fps) > 20 * 60 * timeline.fps
                    except ValueError:
                        long_src = False
                    if long_src or (fr and int(fr) > 60000):
                        add('warning', it.start, 'Speed/Time Remap on a long or high-frame-rate source can export blank frames; '
                                                 'use clip speed (Properties) or a pre-rendered speed-up', it)
                    else:
                        add('info', it.start, 'Speed/Time Remap filter: has exported blank frames on this PC before; '
                                              'the frame check below covers its midpoint only', it)
            prev_end = it.end


def _qc_captions(timeline, add):
    """Check caption timing, size and embedded sound tags."""
    # --- captions
    for feed, cues in timeline.subtitle_feeds.items():
        last_end = -1
        for s, e, text in cues:
            f = round(s * timeline.fps)
            lines = text.split('\n')
            if max(len(x) for x in lines) > 42 or len(lines) > 2:
                add('warning', f, f'caption may overflow ({len(lines)} line(s), longest {max(len(x) for x in lines)} chars): "{text[:60]}"')
            if e - s > 0 and len(text) / (e - s) > 22:
                add('info', f, f'caption reads fast ({len(text) / (e - s):.0f} chars/s): "{text[:50]}"')
            if re.search(r'[\(\[][a-z ]{3,}[\)\]]', text, re.I):
                add('warning', f, f'caption contains a sound tag: "{text[:60]}"')
            if s < last_end - 0.05:
                add('info', f, f'caption overlaps the previous one: "{text[:40]}"')
            if e > timeline.seconds + 0.1:
                add('warning', f, 'caption runs past the end of the timeline')
            last_end = e


def _qc_fonts(timeline, add):
    """Report unavailable or ignored text weights without duplicating findings."""
    # --- fonts: not installed (silent fallback) or a weight the text engine ignores
    try:
        import letitedit.catalogs.fonts as fonts
        seen = set()
        text_services = ('dynamictext', 'subtitle', 'text')
        for t in timeline.tracks:
            for it in t.items:
                for f in it.filters:
                    if f['service'] in text_services:
                        pr = fonts.text_weight_problem(f['props'])
                        if pr and (pr, it.name) not in seen:
                            seen.add((pr, it.name))
                            add('warning', it.start, f"text '{f['props'].get('argument', '')[:30]}': {pr}", it)
        for fp in timeline.burn_filters + timeline.master_filters:
            if fp.get('mlt_service') in text_services:
                pr = fonts.text_weight_problem(fp)
                if pr and pr not in seen:
                    seen.add(pr)
                    add('warning', None, f"captions ({fp.get('feed', '')}): {pr}")
    except ImportError:
        pass


def _qc_frames(timeline, every_s, max_frames, path, add, findings, sheet_bytes):
    """Sample frames, merge adjacent picture findings and write flagged evidence."""
    v1 = timeline.v1()
    picks = []
    for t in timeline.video_tracks():
        for it in t.items:
            if it.service in ('color', 'blank'):
                continue
            picks.append(it.start + min(it.length - 1, max(0, it.length // 2)))
    main_end = max((it.end for it in v1.items), default=0) if v1 else 0
    step = max(1, round(timeline.fps * float(every_s or 2.0)))
    picks += list(range(min(step, round(timeline.fps)), main_end, step))
    picks = sorted(set(picks))
    if max_frames and len(picks) > max_frames:
        step = len(picks) / max_frames
        picks = [picks[int(i * step)] for i in range(max_frames)]
    work = _work('qc')
    pngs = render_frames(timeline, path, picks, work)
    flagged = []
    track_padded = v1 is not None and v1.elem is not None and (any(
        pr.get('name') == 'mlt_service' and (pr.text or '') == 'pillar_echo'
        for fl in v1.elem.findall('filter') for pr in fl.findall('property'))
        or bool(tm.props(v1.elem).get('letitedit_ai:fx')))
    for f, png in zip(picks, pngs):
        probs = _frame_problems(png, timeline.profile)
        main = next((it for it in v1.items if it.start <= f < it.start + it.length), None) if v1 else None
        padded = main is not None and (track_padded or any(fl['id'] == 'blur_pad' or fl['service'] == 'pillar_echo'
                                                           for fl in main.filters)
                                       or bool(tm.props(main.elem).get('letitedit_ai:fx') if main.elem is not None else False))
        for pr in probs:
            if pr.startswith('black sides frame') and padded:
                add('warning', f, 'very dark frame: the footage and what fills its sides are nearly black here', main)
                continue
            top = timeline.item_at(f)
            add('error' if 'missing' in pr else 'warning', f, pr, main or top)
        flagged.append(bool(probs))
    # text over text and text over faces (graphics drawn by the tools)
    try:
        graphics = _graphics(timeline)
        for msg, at in graphic_overlaps(timeline, graphics):
            add('warning', at, msg)
        for msg, at in graphic_collisions_with_faces(timeline, path, picks, graphics):
            add('warning', at, msg)
    except Exception as exc:  # noqa: BLE001 - a layout hint must never break QC
        add('info', None, f'text overlap check skipped: {exc}')
    # neighbouring dark / washed-out frames read as one stretch
    merged = []
    for fnd in findings:
        kind = next((k for k in ('very dark frame', 'washed-out frame', 'blurry frame', 'black sides frame')
                     if fnd['problem'].startswith(k)), None)
        prev = merged[-1] if merged else None
        if kind and prev and prev.get('_kind') == kind and _secs(fnd['at']) - prev['_to'] <= 2.6:
            prev['_to'] = _secs(fnd['at'])
            prev['problem'] = f"{kind}s from {prev['at']} to {fnd['at']}"
            continue
        if kind:
            fnd = dict(fnd, _kind=kind, _to=_secs(fnd['at']))
        merged.append(fnd)
    findings[:] = [{k: v for k, v in f.items() if not k.startswith('_')} for f in merged]
    show = [i for i, fl in enumerate(flagged) if fl][:24]
    if show:
        sheet = contact_sheet([pngs[i] for i in show], [_label_for(timeline, picks[i]) for i in show], cols=4, tile_w=400,
                              flag=[True] * len(show))
        buf = io.BytesIO()
        sheet.save(buf, 'JPEG', quality=85)
        sheet_bytes = buf.getvalue()
        (work / 'flagged.jpg').write_bytes(sheet_bytes)
    return picks, sheet_bytes


def qc(project, frames=True, audio_pass=False, max_frames=240, every_s=2.0, no_talk_s=None):
    """Automatic checks. Rendered frames: the middle of every clip and one every every_s seconds, at most max_frames
    (None: no cap). No-talk stretches from no_talk_s seconds (default NO_TALK_S). Returns (jpeg_bytes_or_None, report)."""
    no_talk_s = NO_TALK_S if no_talk_s is None else float(no_talk_s)
    timeline, path = resolve(project)
    started = time.monotonic()
    findings = []
    def add(sev, at_frame, what, item=None):
        findings.append({'severity': sev, 'at': fmt(at_frame / timeline.fps) if at_frame is not None else '',
                         'clip': item.name if item else '', 'track': next((t.name for t in timeline.tracks if item and t.index == item.track), ''),
                         'problem': what})
    _qc_structure(timeline, add)

    _qc_captions(timeline, add)

    # --- picture coverage: a timeline that runs on in black after the main picture ends
    v1 = timeline.v1()
    if v1 is not None and v1.items:
        pic_end = max(it.end for it in v1.items)
        if timeline.frames - pic_end > timeline.fps:
            longest = max((it for t in timeline.tracks if t is not v1 for it in t.items), key=lambda it: it.end, default=None)
            add('warning', pic_end, f'the picture ends at {fmt(pic_end / timeline.fps)} but the timeline runs to '
                                    f'{fmt(timeline.frames / timeline.fps)} (black)' +
                (f"; longest item: {longest.name} on {next((t.name for t in timeline.tracks if t.index == longest.track), '')}"
                 if longest else ''))
    # --- graphics drawn over the captions
    try:
        for msg, at in graphic_caption_collisions(timeline):
            add('warning', at, msg)
    except Exception as exc:  # noqa: BLE001 - a layout hint must never break QC
        add('info', None, f'graphic/caption overlap check skipped: {exc}')
    _qc_fonts(timeline, add)

    # camera shake, whip-pans and blur in the footage that's in the cut (from the cached picture analysis)
    try:
        for f in footage_picture(path):
            add(f['severity'], round(f['at'] * timeline.fps), f['problem'], f['item'])
    except Exception as exc:  # noqa: BLE001 - an analysis problem must never break QC
        add('info', None, f'footage picture check skipped: {exc}')
    # stretches where nobody talks (from word timings already transcribed)
    try:
        import letitedit.timeline.edit_script as _es
        from letitedit.timeline.timeline_speech import timeline_words
        ws = sorted(timeline_words(_es.read(path)), key=lambda w: w['t0'])
        if ws:
            marks = [0.0] + [x for w in ws for x in (w['t0'], w['t1'])] + [timeline.seconds]
            for a, b in zip(marks[0::2], marks[1::2]):
                if b - a >= no_talk_s:
                    add('info', round(a * timeline.fps), f'no one talks from {fmt(a)} to {fmt(b)} ({b - a:.1f} s)')
    except Exception:  # noqa: BLE001 - a timeline the script reader can't read: skip this check
        pass
    # cuts that land inside a spoken word (from word timings already transcribed; nothing is transcribed here)
    try:
        for f in cut_words(path):
            add('warning', round(f['at'] * timeline.fps), f['problem'])
    except Exception:  # noqa: BLE001 - a timeline the script reader can't read: skip this check
        pass
    try:
        for f in edit_quality_findings(path):
            add('warning', round(f['at'] * timeline.fps), f['problem'])
    except Exception as exc:  # noqa: BLE001 - report any incomplete check
        add('info', None, f'caption/effect quality check skipped: {exc}')
    sheet_bytes = None
    if frames:
        picks, sheet_bytes = _qc_frames(timeline, every_s, max_frames, path, add, findings, sheet_bytes)

    report = {**reported(path), 'duration': fmt(timeline.seconds), 'frames_checked': len(picks) if frames else 0,
              'errors': sum(1 for f in findings if f['severity'] == 'error'),
              'warnings': sum(1 for f in findings if f['severity'] == 'warning'), 'findings': findings[:200]}
    if audio_pass:
        _, areport = audio(project if not str(project).lower().startswith('live') else path)
        report['audio'] = {k: areport[k] for k in ('integrated_lufs', 'true_peak_dbfs', 'range_lu', 'findings')}
    report['seconds'] = round(time.monotonic() - started, 1)
    return sheet_bytes, report


def sound_change(video, every_s=2.0, apart_lu=4.0, min_s=3.0):
    """How the loudness of a finished video moves: short-term loudness (3 s window) every `every_s` seconds, the
    integrated level, loudness range and true peak, and the stretches of `min_s` seconds or more where it sits
    `apart_lu` or more above or below its typical (median) level."""
    series, summary = loudness_series(video)
    every_s, apart_lu, min_s = float(every_s), float(apart_lu), float(min_s)
    filled = [(t, st) for t, m, st in series if t >= 3.0]
    typical = _median([st for t, st in filled if st > -70])
    clock = lambda x: f'{int(x // 60)}:{x % 60:04.1f}'
    readings, nxt = [], 3.0
    for t, st in filled:
        if t + 1e-6 >= nxt:
            readings.append(f'{clock(t)} {st:.1f}')
            nxt += every_s
    stretches = {'louder': [], 'quieter': []}
    if typical is not None:
        for kind, test in (('louder', lambda v: v >= typical + apart_lu), ('quieter', lambda v: v <= typical - apart_lu)):
            run = None
            for t, st in filled + [(float('inf'), typical)]:
                if test(st):
                    run = run or [t, t, []]
                    run[1] = t
                    run[2].append(st)
                else:
                    if run and run[1] - run[0] >= min_s - 1e-6:
                        # the 3 s window lags: a stretch read at t covers t-3..t
                        stretches[kind].append({'from': clock(max(0.0, run[0] - 3.0)), 'to': clock(run[1]),
                                                'lufs': round(sum(run[2]) / len(run[2]), 1)})
                    run = None
    tones = _tones(video)
    return {**summary, 'typical_short_term_lufs': None if typical is None else round(typical, 1),
            **({'tones': tones, 'tones_finding': _tone_finding(tones, 'the finished sound') or None} if tones else {}),
            'louder_stretches': stretches['louder'], 'quieter_stretches': stretches['quieter'],
            'readings': readings,
            'settings': {'every_s': every_s, 'apart_lu': apart_lu, 'min_s': min_s},
            'what': 'short-term loudness (LUFS, 3 s window) every every_s seconds; a louder/quieter stretch sits '
                    'apart_lu or more from the typical (median) level for min_s or more'}


def picture_change(video, every_s=0.5, still_below=4.0, min_s=3.0, start_s=None, end_s=None, cut_above='shots'):
    """How much the picture changes over a video, and where it stays nearly still.

    Every `every_s` seconds a 64x64 grey copy of the frame is compared with the one before (mean absolute difference,
    0-255). A still stretch is where that stays under `still_below` for `min_s` seconds or more. Returns the readings,
    their median and quartiles, the still stretches (from, to, seconds) longest first, and the settings used.
    Shots: the shot boundaries, their lengths, median and the longest shots. cut_above 'shots' (default): the
    camera-move-aware detector (shots.detect: hard cuts, punch-ins, dissolves and fades; a pan or a whip is not a cut,
    a change in part of the frame such as footage over a blurred copy of itself is); a number (0-1): the older
    measure, where ffmpeg's scene score passes it; None skips this."""
    import subprocess
    import numpy as np
    import letitedit.timeline.made as made
    ff = str(made.ffmpeg_exe())
    every_s, still_below, min_s = float(every_s), float(still_below), float(min_s)
    args = [ff, '-v', 'error']
    if start_s is not None:
        args += ['-ss', f'{float(start_s):.3f}']
    args += ['-i', str(video)]
    if end_s is not None:
        args += ['-t', f'{float(end_s) - float(start_s or 0):.3f}']
    args += ['-vf', f'fps=1/{every_s:.4f},scale=64:64,format=gray', '-f', 'rawvideo', '-']
    r = subprocess.run(args, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    frames = np.frombuffer(r.stdout, np.uint8)
    if frames.size < 2 * 64 * 64:
        raise ValueError(f'could not read frames from {video}')
    frames = frames[:frames.size // 4096 * 4096].reshape(-1, 64, 64).astype(np.float32)
    change = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    t0 = float(start_s or 0)
    stills, run = [], None
    for i, c in enumerate(change):
        t = t0 + (i + 1) * every_s
        if c < still_below:
            run = run or [t - every_s, t]
            run[1] = t
        else:
            if run and run[1] - run[0] >= min_s - 1e-6:
                stills.append(run)
            run = None
    if run and run[1] - run[0] >= min_s - 1e-6:
        stills.append(run)
    stills.sort(key=lambda r: r[0] - r[1])
    clock = lambda s: f'{int(s // 60)}:{s % 60:04.1f}'
    q = [round(float(np.percentile(change, p)), 1) for p in (25, 50, 75)]
    shots = None
    if cut_above is not None:
        end = t0 + len(change) * every_s + every_s
        method = None
        if cut_above == 'shots':
            import letitedit.footage.shots as _shots
            # 2 pieces x 2 decode threads keeps it light on the PC; per-frame measures are cached per file
            det = _shots.detect(str(video), start_s, end_s, settings={'workers': 2, 'picture_area': 'auto'})
            cuts = [c['t'] for c in det['cuts']]
            end = det['range'][1] if det.get('range') else end
            kinds = {}
            for c in det['cuts']:
                kinds[c['kind']] = kinds.get(c['kind'], 0) + 1
            method = {'method': 'shots.detect', 'kinds': kinds}
        else:
            import re as _re
            sargs = [ff, '-hide_banner'] + args[3:args.index('-vf')] + [
                '-vf', f"select='gt(scene,{float(cut_above):.3f})',showinfo", '-an', '-f', 'null', '-']
            sr = subprocess.run(sargs, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            cuts = [t0 + float(x) for x in _re.findall(r'pts_time:([\d.]+)', sr.stderr)]
        edges = [t0] + [c for c in cuts if t0 < c < end] + [end]
        spans = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.05]
        lengths = sorted(b - a for a, b in spans)
        shots = {'count': len(spans), 'median_s': round(lengths[len(lengths) // 2], 1) if lengths else None,
                 'longest': [{'from': clock(a), 'to': clock(b), 's': round(b - a, 1)}
                             for a, b in sorted(spans, key=lambda r: r[0] - r[1])[:6]], **(method or {})}
    return {'shots': shots,
            'still_stretches': [{'from': clock(a), 'to': clock(b), 's': round(b - a, 1)} for a, b in stills],
            'still_s': round(sum(b - a for a, b in stills), 1), 'change_median': q[1], 'change_quartiles': [q[0], q[2]],
            'readings': [round(float(c), 1) for c in change],
            'settings': {'every_s': every_s, 'still_below': still_below, 'min_s': min_s, 'cut_above': cut_above},
            'what': ('shots: boundaries from the camera-move-aware detector (cuts, punch-ins, dissolves, fades; a camera '
                     'move is not a cut)' if cut_above == 'shots' else
                     'shots: the picture cuts to another view where the scene score passes cut_above') +
                    '; change: mean frame-to-frame change of a 64x64 grey copy (0-255) every every_s seconds; a still '
                    'stretch stays under still_below for min_s or more'}
