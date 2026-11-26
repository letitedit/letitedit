"""The files a Studio job hands over, made from a finished video (CONTRACT.md sections 6 and 7): each platform's file
under its size cap, the phone proxy and its poster, a cover, evidence frames, and the HDR rule.

The HDR rule (CONTRACT.md section 6, "HDR footage"). Every video the Studio delivers is SDR: H.264, 8-bit 4:2:0,
BT.709 primaries, transfer and matrix, tagged so. letitedit's renderer does no tone mapping (it writes an HLG picture's
signal as it is and tags it BT.709), so HLG footage (what phones such as the iPhone record) is edited from SDR working
copies in the job's own folder, tone-mapped here (sdr_copy), and PQ or unrecognised wide-colour footage is refused before
anything is made (short.check_sources: `hdr_not_supported`). A video that would still be HDR when a file is encoded (a
PQ or HLG transfer, BT.2020 primaries or more than 8 bits a sample) is tone-mapped too. A delivered file made from
tone-mapped footage says `tonemapped: true`. After the location stripper, every delivered video is probed again: one
that isn't plain SDR is not delivered (`hdr_not_delivered`), so a file whose HDR signalling was stripped while its
picture stays HDR can never be handed over.

Every encode runs under the PC lock in the job's lane (render_lock.run_render), below normal priority, with no console
window. Nothing here writes outside the job folder it is given.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import letitedit.core.media as media
import letitedit.core.render_lock as render_lock
import letitedit.studio.state as state

NO_WINDOW = 0x08000000
HDR_TRANSFERS = {'smpte2084': 'pq', 'arib-std-b67': 'hlg'}
SDR_TRANSFERS = {'bt709', 'bt470bg', 'bt470m', 'smpte170m', 'iec61966-2-1', 'gamma22', 'gamma28', 'bt601'}
PROXY_W, PROXY_H, PROXY_MAX = 720, 1280, 8_000_000
EVIDENCE_W = 360
AUDIO_KBPS = 160
MAX_VIDEO_KBPS = 16_000          # a 1080p30 Short needs no more; a smaller file posts faster
MIN_VIDEO_KBPS = 300             # below this a 1080p picture breaks up: the file is refused instead
FIT_MARGIN = 0.94                # aim under the cap: container overhead and rate control
TONEMAP = ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,'
           'zscale=t=bt709:m=bt709:r=tv,format=yuv420p')
SDR_TAGS = ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv']
_FONT = None


def _flags():
    return NO_WINDOW if os.name == 'nt' else 0


def _run(args, what, heavy=True, timeout=3600):
    """An ffmpeg run: under the PC lock (heavy) or as it is (a probe)."""
    run = render_lock.run_render([str(a) for a in args], what=what, heavy=heavy, timeout=timeout, capture_output=True,
                                 text=True, encoding='utf-8', errors='replace', creationflags=_flags())
    if run.returncode != 0:
        raise state.StudioError('render_failed', f'letitedit could not make {what}; sending the job again may work.',
                                detail=(run.stderr or '')[-1500:])
    return run


# ------------------------------------------------------------------ probing and the HDR rule

def probe(path):
    """{duration_s, width, height, fps, vcodec, pix_fmt, bits, transfer, primaries, matrix, hdr, has_audio, bytes} of a
    file, or None when it can't be read. hdr: sdr, hlg, pq or unknown (CONTRACT.md: index's `hdr`)."""
    try:
        run = subprocess.run([str(media.ffprobe()), '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                              str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                             timeout=60, creationflags=_flags())
        data = json.loads(run.stdout or '{}')
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if run.returncode != 0 or not data.get('streams'):
        return None
    v = next((s for s in data['streams'] if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    a = next((s for s in data['streams'] if s.get('codec_type') == 'audio'), None)
    fmt = data.get('format') or {}
    out = {'duration_s': _num(fmt.get('duration')) or _num((v or a or {}).get('duration')),
           'bytes': int(fmt.get('size') or 0) or (Path(path).stat().st_size if Path(path).exists() else 0),
           'has_audio': a is not None, 'acodec': (a or {}).get('codec_name'), 'tags': fmt.get('tags') or {}}
    if v:
        rate = v.get('avg_frame_rate') or v.get('r_frame_rate') or '0/1'
        n, _, d = rate.partition('/')
        fps = (float(n) / float(d)) if d and float(d) else _num(n)
        pix = v.get('pix_fmt') or ''
        bits = int(v.get('bits_per_raw_sample') or 0) or (10 if re.search(r'p10|p12|p16', pix) else 8 if pix else 0)
        rot = _rotation(v)
        w, h = int(v.get('width') or 0), int(v.get('height') or 0)
        if rot in (90, 270):
            w, h = h, w
        out.update(width=w, height=h, fps=round(fps, 3) if fps else None, vcodec=v.get('codec_name'), pix_fmt=pix,
                   bits=bits, transfer=v.get('color_transfer'), primaries=v.get('color_primaries'),
                   matrix=v.get('color_space'), rotation=rot, tags_video=v.get('tags') or {})
        out['hdr'] = hdr_of(out)
    return out


def _rotation(v):
    for side in v.get('side_data_list') or []:
        if 'rotation' in side:
            return int(abs(float(side['rotation']))) % 360
    try:
        return int(abs(float((v.get('tags') or {}).get('rotate', 0)))) % 360
    except ValueError:
        return 0


def _num(x):
    try:
        return round(float(x), 3)
    except (TypeError, ValueError):
        return None


def hdr_of(info):
    """sdr, hlg, pq or unknown, from a probe's video stream: the transfer first (what phones write), then the
    primaries (a BT.2020 picture with no SDR transfer said is unknown, never assumed SDR). A 10-bit BT.709 picture is
    SDR."""
    if not info or not info.get('width'):
        return 'unknown'
    t = (info.get('transfer') or '').lower()
    if t in HDR_TRANSFERS:
        return HDR_TRANSFERS[t]
    wide = (info.get('primaries') or '').lower().startswith('bt2020')
    if t in SDR_TRANSFERS:
        return 'sdr'
    return 'unknown' if wide else 'sdr'


def needs_tonemap(info):
    """True when encoding this picture to 8-bit BT.709 needs a tone map (HLG or PQ, or BT.2020 primaries)."""
    return bool(info) and (hdr_of(info) in ('hlg', 'pq') or (info.get('primaries') or '').lower().startswith('bt2020'))


def plain_sdr(info):
    """A delivered video's check: H.264, 8-bit 4:2:0, BT.709 (or unset) primaries, transfer and matrix."""
    if not info or not info.get('width'):
        return False, 'it has no picture that could be read'
    problems = []
    if info.get('vcodec') != 'h264':
        problems.append(f"the codec is {info.get('vcodec')}, not H.264")
    if (info.get('bits') or 8) > 8 or info.get('pix_fmt') not in ('yuv420p', 'yuvj420p'):
        problems.append(f"the samples are {info.get('pix_fmt')}, not 8-bit 4:2:0")
    for key, ok in (('transfer', {'bt709', None, '', 'unknown'}), ('primaries', {'bt709', None, '', 'unknown'}),
                    ('matrix', {'bt709', None, '', 'unknown', 'smpte170m', 'bt470bg'})):
        if (info.get(key) or None) not in ok:
            problems.append(f'its {key} is {info.get(key)}')
    return (not problems), '; '.join(problems)


def check_sdr(path):
    """Raise hdr_not_delivered when a delivered video isn't plain SDR (after stripping, before it is handed over)."""
    ok, why = plain_sdr(probe(path))
    if not ok:
        Path(path).unlink(missing_ok=True)
        raise state.StudioError('hdr_not_delivered', 'A made video was not plain SDR after it was cleaned, so it was not '
                                'delivered. This is a letitedit fault; sending the job again may work.',
                                detail=f'{path}: {why}')


# ------------------------------------------------------------------ placing overlay text

def _font():
    global _FONT
    if _FONT is None:
        import letitedit.core.paths as paths
        for cand in (Path(paths.ROOT_TEXT) / 'fonts' / 'library' / 'Inter' / 'Inter[opsz,wght].ttf',
                     Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'arialbd.ttf'):
            if cand.is_file():
                _FONT = cand
                break
    return _FONT


def uncovered(platform_id):
    """(x0, y0, x1, y1) as fractions: the part of a platform's frame no app control covers (its safe_zones), the whole
    frame when the profile has none."""
    x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    try:
        import letitedit.catalogs.platforms as platforms
        zones = ((platforms.load(platform_id).get('safe_zones') or {}).get('value')) or []
    except Exception:  # noqa: BLE001 - an unknown platform has no covered areas
        zones = []
    for z in zones:
        x, y, w, h = (float(z.get(k, 0)) for k in ('x', 'y', 'w', 'h'))
        if w >= 0.5 and y <= 0.01:
            y0 = max(y0, y + h)
        elif w >= 0.5 and y + h >= 0.99:
            y1 = min(y1, y)
        elif h >= 0.5 and x + w >= 0.99:
            x1 = min(x1, x)
        elif h >= 0.5 and x <= 0.01:
            x0 = max(x0, x + w)
    return x0, y0, x1, y1


def _pil_font(size):
    from PIL import ImageFont
    font = _font()
    try:
        f = ImageFont.truetype(str(font), size) if font else ImageFont.load_default()
        try:
            f.set_variation_by_name('Bold')
        except Exception:  # noqa: BLE001 - a static font has no named instances
            pass
        return f
    except OSError:
        return ImageFont.load_default()


def _text_size(text, width, height, area_w, area_h=None):
    """(font_px, box_w, box_h) in pixels: the words on one line in their panel, shrunk to fit the area's width (and
    its height, when given), down to the smallest size."""
    pad = max(10, int(height * 0.008))
    size = max(24, int(height * 0.03))
    while True:
        l, t, r, b = _pil_font(size).getbbox(text or ' ')
        tw, th = (r - l) + 2 * pad, (b - t) + 2 * pad
        if size <= 24 or (tw <= area_w * 0.92 and (area_h is None or th <= area_h)):
            break
        size -= 2
    return size, min(tw, area_w * 0.96), th


def _hits(y, h, x, w, faces):
    """The faces (boxes as fractions) a box at (x, y, w, h) would cover."""
    return [f for f in faces or () if x < f[0] + f[2] and f[0] < x + w and y < f[1] + f[3] and f[1] < y + h]


def _clear(y, h, x, w, boxes, gap=0.0):
    """Whether a box at (x, y, w, h) keeps clear of every box in boxes ([x, y, w, h] fractions) by gap."""
    return not any(x < b[0] + b[2] + gap and b[0] < x + w + gap and y < b[1] + b[3] + gap and b[1] < y + h + gap
                   for b in boxes)


def _spot(region, h, x, w, taken, faces, downward, step=0.0025):
    """The first y in region (y0, y1) where a box of height h fits whole, clear of the boxes taken (with a gap) and
    of the faces, searched from the region's top down or from its bottom up; None when there is none."""
    r0, r1 = region
    if r1 - r0 < h:
        return None
    n = int((r1 - r0 - h) / step) + 1
    ys = [r0 + k * step for k in range(n)] + [r1 - h]
    for y in (ys if downward else reversed(ys)):
        if _clear(y, h, x, w, taken, 0.01) and _clear(y, h, x, w, faces):
            return y
    return None


NOT_PLACED = "it doesn't fit in the part of the frame the apps don't cover, so it isn't placed"


def overlay_layout(items, platform_id, width, height, faces=(), zone=None):
    """One layout for every overlay item of a file, the same for the proxy and the platform files: [(x, y, font_px,
    box, used, note)], x and y in pixels, box as fractions of the frame, used the placement it got and note what had
    to give way (None when nothing did). items: [(text, placement)] in order. An item that can't be placed comes back
    as (None, None, font_px, None, None, note): no box is ever outside the uncovered area.
    - Every box is whole inside the platform's uncovered area, and no two boxes overlap: each item takes the first
      free place in its own region, with the boxes already placed and the faces (boxes [x, y, w, h] as fractions,
      from the video's own frames) kept clear.
    - `top` and `safe_area` search the uncovered area from its top down, `bottom` from its bottom up, `caption_zone`
      the part of the Look's caption zone (zone: (y0, y1) as fractions) inside the uncovered area, from its top down.
    - When that can't be met, in this order, the note giving every reason:
      1. a `caption_zone` item with no zone, or no free place clear of faces in it: the first free place clear of
         faces in the uncovered area (used `safe_area`);
      2. no place clear of a face: the first place in its own region clear of the other words, over the face;
      3. for a `caption_zone` item, then the first place in the uncovered area clear of the other words, over the
         face (used `safe_area`);
      4. no free place at all: the start of its region, over another item;
      5. too big for the uncovered area even at the smallest size: not placed."""
    x0, y0, x1, y1 = uncovered(platform_id)
    margin = max(0.0, min(0.02, (y1 - y0) / 4))     # a small uncovered area keeps its margins from crossing
    area = (y0 + margin, y1 - margin)
    area_w = (x1 - x0) * width
    faces = [list(f) for f in faces or ()]
    taken, out = [], []
    for text, placement in items:
        asked = placement or 'safe_area'
        size, tw, th = _text_size(text, width, height, area_w, (y1 - y0) * height)
        w, h = tw / width, th / height
        if h > y1 - y0 + 1e-9 or w > x1 - x0 + 1e-9:
            out.append((None, None, size, None, None, NOT_PLACED))
            continue
        x = x0 + ((x1 - x0) - w) / 2
        room = area if h <= area[1] - area[0] else (y0, y1)     # it fits only without the margins
        down = asked != 'bottom'
        region = room
        if asked == 'caption_zone':
            region = (max(room[0], zone[0]), min(room[1], zone[1])) if zone else None
            if region and region[1] - region[0] < h:
                region = None
        left_zone = ('the Look has no caption zone, so it is in the safe area' if not zone else
                     "its caption zone has no room clear of faces, the apps' buttons and the other words, so it is "
                     'in the safe area')
        over_face = 'there is no room clear of the face, so it is over the face'
        y, used, why = None, asked, []
        if region:                                   # its own region, clear of the other words and of faces
            y = _spot(region, h, x, w, taken, faces, down)
        if y is None and asked == 'caption_zone':    # the uncovered area, clear of the words and faces
            y = _spot(room, h, x, w, taken, faces, True)
            used, why = 'safe_area', [left_zone]
        if y is None and region:                     # its own region, clear of the words, over a face
            y = _spot(region, h, x, w, taken, (), down)
            used, why = asked, [over_face]
        if y is None and asked == 'caption_zone':    # the uncovered area, clear of the words, over a face
            y = _spot(room, h, x, w, taken, (), True)
            used, why = 'safe_area', [left_zone, over_face]
        if y is None:                                # no free room at all: over another item, still inside
            own = region or room
            y = own[0] if down else own[1] - h
            used = asked if region else 'safe_area'
            why = ([left_zone] if used != asked else []) + ['there is no free room left, so it overlaps another '
                                                            'overlay item']
        taken.append([x, y, w, h])
        box = {'x': round(x, 4), 'y': round(y, 4), 'w': round(w, 4), 'h': round(h, 4)}
        out.append((int(x * width), int(y * height), size, box, used, '; '.join(why) or None))
    return out


def overlay_box(platform_id, placement, text, width, height, below=0.0):
    """One item alone (overlay_layout): (x, y, font_px, box)."""
    x, y, size, box, _, _ = overlay_layout([(text, placement)], platform_id, width, height)[0]
    if box is None:
        return None, None, size, None
    if below and placement != 'bottom' and box['y'] < below + 0.02:
        y = int((below + 0.02) * height)
        box = dict(box, y=round(y / height, 4))
    return x, y, size, box


def overlay_picture(items, width, height, path):
    """One transparent PNG the size of the frame with every applied overlay item drawn in its box: white words on a
    dark rounded panel. items: [(text, x, y, size)] as overlay_box placed them."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(10, int(height * 0.008))
    for text, x, y, size in items:
        font = _pil_font(size)
        l, t, r, b = font.getbbox(text or ' ')
        w, h = (r - l) + 2 * pad, (b - t) + 2 * pad
        draw.rounded_rectangle([x, y, x + w, y + h], radius=pad, fill=(0, 0, 0, 150))
        draw.text((x + pad - l, y + pad - t), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return Path(path)


# ------------------------------------------------------------------ the files

def caption_picture(text, width, height, path):
    """A draft caption as a transparent PNG the size of the frame: white words on a dark panel in the lower middle
    (about where a Short's captions sit, above the apps' bottom controls)."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = max(22, int(height * 0.034))
    font = _pil_font(size)
    lines, cur = [], ''
    for w in text.split():
        trial = (cur + ' ' + w).strip()
        if cur and font.getlength(trial) > width * 0.8:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    pad = max(8, size // 3)
    y = int(height * 0.64)
    for line in lines[:3]:
        l, t, r, b = font.getbbox(line)
        w, h = (r - l) + 2 * pad, (b - t) + 2 * pad
        x = (width - w) // 2
        draw.rounded_rectangle([x, y, x + w, y + h], radius=pad, fill=(0, 0, 0, 160))
        draw.text((x + pad - l, y + pad - t), line, font=font, fill=(255, 255, 255, 255))
        y += h + pad // 2
    img.save(path)
    return Path(path)


def _video_args(info, width, height, fps, kbps, overlays, tmp, captions=()):
    """(extra inputs, output args): the picture tone-mapped when HDR, fitted to width x height, at fps, with the
    overlay picture on top and each caption picture shown for its time; the filter graph read from a file, so no
    path is read as filter syntax."""
    chain = []
    if needs_tonemap(info):
        chain.append(TONEMAP)
    chain.append(f'scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,'
                 f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')
    if fps:
        chain.append(f'fps={fps}')
    inputs, steps, last = [], [f"[0:v]{','.join(chain)}[s0]"], 's0'
    if overlays:
        inputs += ['-i', str(overlay_picture(overlays, width, height, Path(tmp) / 'overlay.png'))]
        steps.append(f'[{last}][1:v]overlay=0:0:format=auto[s1]')
        last = 's1'
    for n, (a, b, text) in enumerate(captions or ()):
        k = len(inputs) // 2 + 1
        inputs += ['-i', str(caption_picture(text, width, height, Path(tmp) / f'caption-{n}.png'))]
        steps.append(f"[{last}][{k}:v]overlay=0:0:format=auto:enable='between(t,{float(a):.3f},{float(b):.3f})'"
                     f'[c{n}]')
        last = f'c{n}'
    steps.append(f'[{last}]format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited[v]')
    graph = ';'.join(steps)
    script = Path(tmp) / 'filters.txt'
    script.write_text(graph, encoding='utf-8')
    rate = ['-b:v', f'{kbps}k', '-maxrate', f'{int(kbps * 1.25)}k', '-bufsize', f'{int(kbps * 2)}k'] if kbps \
        else ['-crf', '18', '-maxrate', f'{MAX_VIDEO_KBPS}k', '-bufsize', f'{MAX_VIDEO_KBPS * 2}k']
    return inputs, ['-/filter_complex', str(script), '-map', '[v]', '-c:v', 'libx264', '-threads', '4', '-preset', 'medium',
                    '-profile:v', 'high', '-pix_fmt', 'yuv420p', *rate, *SDR_TAGS]


def sdr_copy(src, dst, what=None):
    """dst (an .mp4): an SDR working copy of an HLG or wide-colour video, for New video to edit: tone-mapped to 8-bit
    BT.709 at its own size, frame timing and sound, with its metadata kept (dates and camera, which New video reads; the
    copy stays in the job's folder, and every delivered file goes through the location stripper). Written beside dst
    and renamed when whole, so a stopped copy is never taken for a finished one."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.stem + '.part.mp4')
    base = [media.ffmpeg(), '-y', '-v', 'error', '-nostdin', '-i', str(src), '-map', '0:v:0', '-map', '0:a?',
            '-vf', TONEMAP, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', *SDR_TAGS,
            '-fps_mode', 'passthrough', '-map_metadata', '0', '-movflags', '+faststart']
    what = what or f'an SDR copy of {Path(src).name}'
    try:
        _run([*base, '-c:a', 'copy', str(part)], what, timeout=4 * 3600)
    except state.StudioError:                          # a sound format mp4 can't hold as it is
        _run([*base, '-c:a', 'aac', '-b:a', '256k', str(part)], what, timeout=4 * 3600)
    os.replace(part, dst)
    return dst


def encode(src, dst, width, height, fps=30, kbps=None, overlays=(), what=None, audio=True, captions=(), audio_file=None):
    """dst: src as H.264 SDR at width x height (letterboxed when the shape differs), fps, kbps (None: quality-led under
    MAX_VIDEO_KBPS), with the overlay items drawn; AAC sound. Returns {'tonemapped': bool}."""
    info = probe(src)
    if not info or not info.get('width'):
        raise state.StudioError('render_failed', 'letitedit could not read the finished video to make the files.',
                                detail=str(src))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='studio-enc-') as tmp:
        extra, video = _video_args(info, width, height, fps, kbps, overlays, tmp, captions)
        audio_index = 1 + len(extra) // 2
        if audio_file:
            extra += ['-i', str(audio_file)]
        args = [media.ffmpeg(), '-y', '-v', 'error', '-nostdin', '-threads', '4',
                '-filter_complex_threads', '4', '-i', str(src), *extra, *video]
        if audio and audio_file:
            args += ['-map', f'{audio_index}:a:0', '-c:a', 'copy']
        else:
            args += (['-map', '0:a:0', '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k', '-ar', '48000']
                     if audio and info.get('has_audio') else ['-an'])
        args += ['-map_metadata', '-1', '-map_chapters', '-1', '-movflags', '+faststart', str(dst)]
        _run(args, what or f'the {dst.stem} file')
    return {'tonemapped': needs_tonemap(info)}


def fit_under(src, dst, width, height, fps, cap_bytes, overlays=(), what=None, captions=(), audio_file=None):
    """Encode src to dst under cap_bytes (None: no cap), lowering the bitrate to fit. Returns {'status': 'made',
    'tonemapped', 'bytes', 'kbps'} or {'status': 'refused', 'reason': 'cannot_fit_size', 'why'} (dst removed)."""
    info = probe(src) or {}
    dur = max(0.5, float(info.get('duration_s') or 0.5))
    budget = None if not cap_bytes else int(cap_bytes * FIT_MARGIN * 8 / dur / 1000) - (AUDIO_KBPS if info.get('has_audio') else 0)
    if budget is not None and budget < MIN_VIDEO_KBPS:
        return {'status': 'refused', 'reason': 'cannot_fit_size',
                'why': f'{cap_bytes / 1e6:.1f} MB holds under {MIN_VIDEO_KBPS} kbit/s of picture for {dur:.0f} s.'}
    kbps = None if budget is None or budget >= MAX_VIDEO_KBPS else budget
    for _ in range(3):
        audio_kw = {'audio_file': audio_file} if audio_file else {}
        made = encode(src, dst, width, height, fps, kbps, overlays, what, captions=captions, **audio_kw)
        size = Path(dst).stat().st_size
        if not cap_bytes or size <= cap_bytes:
            return {'status': 'made', 'tonemapped': made['tonemapped'], 'bytes': size, 'kbps': kbps}
        kbps = int((kbps or MAX_VIDEO_KBPS) * cap_bytes / size * 0.9)
        if kbps < MIN_VIDEO_KBPS:
            break
    Path(dst).unlink(missing_ok=True)
    return {'status': 'refused', 'reason': 'cannot_fit_size',
            'why': f'Even at the lowest usable bitrate the file was over {cap_bytes / 1e6:.1f} MB.'}


def proxy(src, video_dst, poster_dst, at_s=None, overlays=(), max_bytes=PROXY_MAX, captions=()):
    """The phone proxy (about 720x1280, or 1280x720 for a landscape video; H.264; under max_bytes) and its poster JPG;
    captions: [(start, end, text)] drawn on it (a preview's draft captions)."""
    info = probe(src) or {}
    w, h = (PROXY_H, PROXY_W) if (info.get('width') or 0) > (info.get('height') or 1) else (PROXY_W, PROXY_H)
    made = fit_under(src, video_dst, w, h, 30, max_bytes, overlays, what='the phone proxy', captions=captions)
    if made['status'] != 'made':
        raise state.StudioError('render_failed', 'letitedit could not make the phone proxy small enough.',
                                detail=made.get('why'))
    frame(video_dst, at_s if at_s is not None else min(1.0, (info.get('duration_s') or 2) / 2), poster_dst, width=w)
    return {'width': w, 'height': h, 'bytes': Path(video_dst).stat().st_size, 'tonemapped': made['tonemapped']}


def frame(src, at_s, dst, width=EVIDENCE_W, tonemap=None):
    """One JPG frame of src at at_s seconds, width px wide (SDR: tone-mapped from HDR)."""
    info = probe(src) or {}
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    chain = ([TONEMAP] if (needs_tonemap(info) if tonemap is None else tonemap) else []) + [f'scale={width}:-2']
    _run([media.ffmpeg(), '-y', '-v', 'error', '-nostdin', '-ss', f'{max(0.0, float(at_s)):.3f}', '-i', str(src),
          '-frames:v', '1', '-vf', ','.join(chain), '-q:v', '3', '-map_metadata', '-1', str(dst)],
         f'a frame of {Path(src).name}', heavy=False, timeout=120)
    if not dst.is_file():
        raise state.StudioError('render_failed', 'letitedit could not take a frame of the video.', detail=str(src))
    return dst


def loudness(path):
    """(integrated LUFS, true peak dBTP) of a file's sound, or (None, None)."""
    try:
        run = _run([media.ffmpeg(), '-v', 'info', '-nostdin', '-i', str(path), '-vn', '-af', 'ebur128=peak=true',
                    '-f', 'null', '-'], f'the loudness of {Path(path).name}')
    except state.StudioError:
        return None, None
    text = run.stderr or ''
    tail = text[text.rfind('Summary:'):] if 'Summary:' in text else text
    i = re.search(r'I:\s*(-?[\d.]+) LUFS', tail)
    p = re.search(r'Peak:\s*(-?[\d.]+|-inf) dBFS', tail)
    lufs = float(i.group(1)) if i else None
    tp = (None if not p else (-math.inf if p.group(1) == '-inf' else float(p.group(1))))
    return lufs, (None if tp is None or tp == -math.inf else tp)


def describe(path, platform=None):
    """An outputs entry's media fields for a made video (CONTRACT.md section 7, `outputs`)."""
    info = probe(path) or {}
    out = {'width': info.get('width'), 'height': info.get('height'), 'fps': info.get('fps'),
           'duration_s': info.get('duration_s'), 'codec': info.get('vcodec')}
    if info.get('has_audio'):
        lufs, tp = loudness(path)
        if lufs is not None:
            out['loudness_lufs'] = round(lufs, 1)
        if tp is not None:
            out['true_peak_dbtp'] = round(tp, 1)
    if platform:
        out['platform'] = platform
    return {k: v for k, v in out.items() if v is not None}
