"""The previews: comparison sheets, clips and reels.

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from letitedit.footage.takes_words import (  # noqa: E402
    FFMPEG, NO_WINDOW, _is_filler
)
from letitedit.footage.takes_sources import (  # noqa: E402
    clock
)
from letitedit.footage.takes_measure import (  # noqa: E402
    HOP_S
)
from letitedit.footage.takes_groups import (  # noqa: E402
    _measure_bits
)


# ------------------------------------------------------------------ previews

_FONT_CACHE = {}


def _font(px, bold=False):
    key = (int(px), bool(bold))
    if key not in _FONT_CACHE:
        from PIL import ImageFont
        for name in (('segoeuib.ttf', 'arialbd.ttf') if bold else ('segoeui.ttf', 'arial.ttf')):
            try:
                _FONT_CACHE[key] = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts',
                                                                   name), int(px))
                break
            except OSError:
                continue
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


COLORS = {'number': (240, 80, 80), 'negation': (255, 150, 40), 'name': (200, 130, 255), 'opposite': (255, 90, 200),
          'wording': (255, 220, 0), 'function': (170, 200, 255), 'number_format': (120, 220, 160),
          'filler': (130, 130, 140), 'restart': (80, 210, 230), 'text': (235, 235, 235)}
_PRIORITY = ['number', 'negation', 'name', 'opposite', 'wording', 'number_format', 'function']


def _grab(path, t, out, height):
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-ss', f'{max(0.0, float(t)):.3f}', '-i', str(path),
                        '-frames:v', '1', '-vf', f'scale=-2:{int(height)}:flags=area', '-q:v', '3', str(out)],
                       capture_output=True, creationflags=NO_WINDOW, timeout=120)
    return str(out) if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) else None


def _anchor_times(t, g, n):
    """Times of frames at the same words of every take: reference token positions spread over the passage, mapped
    through each take's alignment (the nearest word it says when it skips that one)."""
    R = len(g['rtoks'])
    if R == 0 or n <= 0:
        return []
    ref_pos = [round(i * (R - 1) / max(1, n - 1)) for i in range(n)] if n > 1 else [R // 2]
    pairs = []                                       # (ref index, take index) of equal tokens
    for tag, i1, i2, j1, j2 in t['ops']:
        if tag == 'equal':
            pairs += [(i1 + k, j1 + k) for k in range(i2 - i1)]
    nd = t['node']
    ws = nd.unit.doc.ws
    out = []
    for rp in ref_pos:
        if pairs:
            ri, ti = min(pairs, key=lambda p: abs(p[0] - rp))
            exact = ri == rp
        else:
            ti, exact = 0, False
        ti = max(0, min(len(t['ttoks']) - 1, ti))
        w = ws[nd.unit.tw0[t['tlo'] + ti]]
        out.append((round((float(w['s']) + float(w['e'])) / 2, 3), exact))
    return out


def _word_styles(t, context=3):
    """[(word text, colour)] for a take's words: differences by kind, words the take leaves out as [-...], fillers
    grey, restarts cyan, and a few words of its line before and after (dim, in brackets)."""
    nd, u = t['node'], t['node'].unit
    ws = u.doc.ws
    tl = t['tlo']
    style, gaps = {}, {}
    for j1, j2, kinds, left_out in t.get('diff_spans') or []:
        kind = next((k for k in _PRIORITY if k in kinds), 'wording')
        if left_out is not None:                      # words the reference says and this take does not
            at = u.tw0[tl + j1] if tl + j1 < len(u.toks) else t['k1'] + 1
            gaps.setdefault(at, []).append(('[-' + left_out + ']', COLORS[kind]))
            continue
        for j in range(j1, j2):
            for k in range(u.tw0[tl + j], u.tw1[tl + j] + 1):
                if k not in style or _PRIORITY.index(kind) < _PRIORITY.index(style[k]):
                    style[k] = kind
    restart_k = t.get('_restart_k') or set()
    dim = (110, 110, 120)
    out = []
    before = [str(ws[k]['w']).strip() for k in range(max(0, t['k0'] - context), t['k0'])]
    if before:
        out.append(('(…' + ' '.join(before) + ')', dim))
    for k in range(t['k0'], t['k1'] + 2):
        for g in gaps.get(k, []):
            out.append(g)
        if k > t['k1']:
            break
        w = str(ws[k]['w']).strip()
        if _is_filler(w):
            c = COLORS['filler']
        elif k in style:
            c = COLORS[style[k]]
        elif k in restart_k:
            c = COLORS['restart']
        else:
            c = COLORS['text']
        out.append((w, c))
    after = [str(ws[k]['w']).strip() for k in range(t['k1'] + 1, min(len(ws), t['k1'] + 1 + context))]
    if after:
        out.append(('(' + ' '.join(after) + '…)', dim))
    return out


def _draw_words(d, x0, y0, width, items, font, line_h, max_lines):
    x, y, lines = x0, y0, 1
    for k, (text, color) in enumerate(items):
        w = d.textlength(text + ' ', font=font)
        if x + w > x0 + width and x > x0:
            if lines >= max_lines:
                d.text((x, y), '\u2026', fill=COLORS['filler'], font=font)
                return y + line_h
            x, y, lines = x0, y + line_h, lines + 1
        d.text((x, y), text, fill=color, font=font)
        x += w
    return y + line_h


def _env_strip(d, x0, y0, w, h, t, envd, doc):
    from PIL import Image  # noqa: F401 - Pillow present
    d.rectangle((x0, y0, x0 + w, y0 + h), fill=(36, 36, 42))
    if envd is None:
        d.text((x0 + 4, y0 + 4), 'no sound measured', fill=COLORS['filler'], font=_font(12))
        return
    env, a = envd['env'], envd['a']
    t0, t1 = a, a + len(env) * HOP_S
    X = lambda tt: x0 + (tt - t0) / max(1e-6, t1 - t0) * w
    for k in range(max(0, t['k0'] - 8), min(len(doc.ws), t['k1'] + 9)):
        s, e = float(doc.ws[k]['s']), float(doc.ws[k]['e'])
        if e < t0 or s > t1:
            continue
        inside = t['k0'] <= k <= t['k1']
        d.rectangle((X(max(s, t0)), y0 + h - 7, X(min(e, t1)), y0 + h - 2),
                    fill=(90, 150, 210) if inside else (70, 70, 80))
    lo, hi = -70.0, max(-10.0, float(np.percentile(env, 99)) + 3)
    pts = [(X(t0 + (i + 0.5) * HOP_S), y0 + h - 9 - (min(hi, max(lo, v)) - lo) / (hi - lo) * (h - 12))
           for i, v in enumerate(env)]
    step = max(1, len(pts) // (2 * w))
    d.line(pts[::step], fill=(120, 220, 120), width=1)
    for xx in (X(t['start']), X(t['end'])):
        d.line((xx, y0, xx, y0 + h), fill=(255, 220, 0), width=1)
    p = ((t.get('components') or {}).get('delivery') or {}).get('pauses') or {}
    for at, ln in p.get('at') or []:
        d.rectangle((X(at), y0 + 2, X(at + ln), y0 + 6), fill=(240, 80, 80))


def _sheet(g, gi, folder, st, envs, frames_n):
    """The comparison sheet of one group: a JPEG path."""
    from PIL import Image, ImageDraw
    W = 1700
    takes = g['takes_out']
    vertical = []
    for t in takes:
        info = t['_info']
        vertical.append(bool(info.get('height') and info.get('width') and info['height'] > info['width']))
    fh = 150
    fw = 84 if all(vertical) else 267
    if any(t['_info'].get('media') != 'video' for t in takes):
        frames_n = frames_n if any(t['_info'].get('media') == 'video' for t in takes) else 0
    left = max(320, frames_n * (fw + 4)) if frames_n else 320
    head_font, body, small, bold = _font(22, True), _font(16), _font(13), _font(15, True)
    # frames
    jobs = []
    for ti, t in enumerate(takes):
        if t['_info'].get('media') != 'video' or not frames_n:
            t['_frames'] = []
            continue
        t['_frames'] = []
        for fi, (at, exact) in enumerate(_anchor_times(t['_raw'], g, frames_n)):
            dest = folder / f"{g['group_id']}-{t['label']}-f{fi + 1}.jpg"
            t['_frames'].append([at, exact, dest])
            jobs.append((t['file'], at, dest))
    with ThreadPoolExecutor(max_workers=6) as pool:
        got = list(pool.map(lambda j: _grab(j[0], j[1], j[2], fh), jobs))
    ok = {str(j[2]): r for j, r in zip(jobs, got)}
    rows_h = []
    for t in takes:
        rows_h.append(fh + 56 + 8)
    title = f"{g['group_id']}  {g['pattern']}  {len(takes)} takes  " + (
        'same claim' if g['same_claim'] else f"DIFFERENT CLAIMS ({', '.join(sorted(g['claim_kinds']))})")
    passage = g['passage']['text']
    H = 70 + 22 * 2 + sum(rows_h) + 40
    img = Image.new('RGB', (W, H), (24, 24, 28))
    d = ImageDraw.Draw(img)
    d.text((12, 10), title, fill=(255, 220, 0), font=head_font)
    q = 'script: ' if g.get('query') else 'reference: '
    _draw_words(d, 12, 42, W - 24, [(w, (220, 220, 225)) for w in (q + passage).split()], body, 22, 2)
    y = 90
    for t in takes:
        x = 12
        if t['_frames']:
            for at, exact, dest in t['_frames']:
                p = ok.get(str(dest))
                if p:
                    with Image.open(p) as im:
                        im = im.convert('RGB')
                        im.thumbnail((fw, fh))
                        img.paste(im, (x, y))
                d.text((x + 2, y + fh - 16), ('' if exact else '~') + clock(at), fill=(255, 255, 255), font=small)
                x += fw + 4
            t['frames'] = [str(f[2]) for f in t['_frames'] if ok.get(str(f[2]))]
        _env_strip(d, 12, y + fh + 4, left - 16, 44, t['_raw'], envs.get(t['take']), t['_raw']['doc'])
        tx = 12 + left + 8
        lab = (f"{t['label']}{' (reference)' if t['reference'] else ''}  {t['name']}  {t['clock']}  "
               f"{t['completeness']}  variant {t['variant']}  cov {t['coverage']:.2f}  sim {t['similarity']:.2f}")
        d.text((tx, y), lab, fill=(255, 220, 0) if t['reference'] else (230, 230, 230), font=bold)
        yy = _draw_words(d, tx, y + 22, W - tx - 12, _word_styles(t['_raw']), body, 21, 5)
        meas = ' | '.join(_measure_bits(t))
        _draw_words(d, tx, max(yy + 2, y + fh - 10), W - tx - 12, [(w, (160, 160, 170)) for w in meas.split()],
                    small, 17, 3)
        y += fh + 56 + 8
        d.line((12, y - 5, W - 12, y - 5), fill=(50, 50, 58))
    legend = [('number', 'number'), ('negation', 'negation'), ('name', 'name'), ('opposite', 'opposite'),
              ('wording', 'wording'), ('number_format', 'same number, other form'), ('function', 'small words'),
              ('filler', 'filler'), ('restart', 'restart')]
    x = 12
    for k, text in legend:
        d.rectangle((x, H - 26, x + 12, H - 14), fill=COLORS[k])
        d.text((x + 16, H - 30), text, fill=(200, 200, 205), font=small)
        x += 30 + int(d.textlength(text, font=small))
    d.text((W - 520, H - 30), 'frames at the same words of each take (~ = nearest word said); yellow lines = take',
           fill=(150, 150, 160), font=small)
    out = folder / f"{gi:02d}-{g['group_id']}-sheet.jpg"
    img.save(out, 'JPEG', quality=84)
    return str(out)


def _label_png(text, W, path):
    from PIL import Image, ImageDraw
    f = _font(max(12, W // 30), True)
    tw = int(ImageDraw.Draw(Image.new('RGB', (1, 1))).textlength(text, font=f))
    im = Image.new('RGBA', (min(W - 8, tw + 16), f.size + 12), (0, 0, 0, 170))
    ImageDraw.Draw(im).text((8, 4), text, fill=(255, 220, 0, 255), font=f)
    im.save(path)
    return path


def _card_png(title, sub, W, H, path):
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (W, H), (14, 14, 18))
    d = ImageDraw.Draw(im)
    f, fs = _font(max(16, min(W, H) // 10), True), _font(max(11, min(W, H) // 24))
    d.text(((W - d.textlength(title, font=f)) / 2, H / 2 - f.size), title, fill=(255, 220, 0), font=f)
    sub = sub if d.textlength(sub, font=fs) <= W - 20 else sub[:max(4, int(len(sub) * (W - 20) / max(1, d.textlength(sub, font=fs)))) - 1] + '\u2026'
    d.text(((W - d.textlength(sub, font=fs)) / 2, H / 2 + 6), sub, fill=(200, 200, 205), font=fs)
    im.save(path)
    return path


_ENC = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p', '-r', '30', '-c:a', 'aac',
        '-b:a', '128k', '-ar', '48000', '-ac', '2', '-threads', '2', '-movflags', '+faststart']


def _clip(t, W, H, folder, st):
    """A short MP4 of a take with context before/after, its label burned in. Returns the path or None."""
    a = max(0.0, t['start'] - st['context_s'])
    dur_f = t['_raw']['doc'].duration
    b = t['end'] + st['context_s'] if not dur_f else min(dur_f, t['end'] + st['context_s'])
    out = folder / f"{t['_gid']}-{t['label']}.mp4"
    tag = _label_png(f"{t['_gid']} {t['label']}  {t['name']} {clock(t['start'])}  variant {t['variant']}", W,
                     folder / f"{t['_gid']}-{t['label']}-tag.png")
    is_video = t['_info'].get('media') == 'video'
    cmd = [str(FFMPEG), '-v', 'error', '-y', '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', t['file']]
    if is_video:
        cmd += ['-i', str(tag), '-filter_complex',
                f'[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                f'fps=30[v0];[v0][1:v]overlay=8:8,format=yuv420p[v];[0:a]aformat=sample_rates=48000:'
                f'channel_layouts=stereo[a]', '-map', '[v]', '-map', '[a]']
    else:
        cmd += ['-f', 'lavfi', '-t', f'{b - a:.3f}', '-i', f'color=c=0x18181c:s={W}x{H}:r=30', '-i', str(tag),
                '-filter_complex', '[1:v][2:v]overlay=8:8,format=yuv420p[v];[0:a]aformat=sample_rates=48000:'
                                   'channel_layouts=stereo[a]', '-map', '[v]', '-map', '[a]', '-shortest']
    r = subprocess.run(cmd + _ENC + [str(out)], capture_output=True, creationflags=NO_WINDOW, timeout=600)
    return str(out) if r.returncode == 0 and out.exists() and out.stat().st_size else None


def _reel(g, clips, W, H, folder):
    """The group's takes back to back, a title card before each: one MP4 (or None)."""
    parts = []
    for t, c in clips:
        if not c:
            continue
        card = _card_png(f"{t['label']} of {len(g['takes_out'])}" + (' (reference)' if t['reference'] else ''),
                         f"{t['name']} {t['clock']} | {t['completeness']} | variant {t['variant']}", W, H,
                         folder / f"{g['group_id']}-{t['label']}-card.png")
        cmp4 = folder / f"{g['group_id']}-{t['label']}-card.mp4"
        r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-loop', '1', '-framerate', '30', '-t', '0.8', '-i',
                            str(card), '-f', 'lavfi', '-t', '0.8', '-i',
                            'anullsrc=channel_layout=stereo:sample_rate=48000', '-vf', 'format=yuv420p', '-shortest']
                           + _ENC + [str(cmp4)], capture_output=True, creationflags=NO_WINDOW, timeout=120)
        if r.returncode == 0 and cmp4.exists():
            parts.append(cmp4)
        parts.append(Path(c))
    if len(parts) < 2:
        return None
    lst = folder / f"{g['group_id']}-reel.txt"
    lst.write_text(''.join("file '" + str(p).replace('\\', '/').replace("'", "'\\''") + "'\n" for p in parts),
                   encoding='utf-8')
    out = folder / f"{g['group_id']}-reel.mp4"
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy',
                        '-movflags', '+faststart', str(out)], capture_output=True, creationflags=NO_WINDOW, timeout=600)
    return str(out) if r.returncode == 0 and out.exists() else None
