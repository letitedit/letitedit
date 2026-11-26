"""The strips drawn.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from letitedit.timing.cut_inspect_base import (  # noqa: E402
    _clock, _cv2
)


# ------------------------------------------------------------------ drawing

_FONTS = {}


def _font(size, bold=False):
    from PIL import ImageFont
    key = (size, bold)
    if key in _FONTS:
        return _FONTS[key]
    names = (['arialbd.ttf', 'segoeuib.ttf'] if bold else []) + ['arial.ttf', 'segoeui.ttf', 'DejaVuSans.ttf']
    f = None
    for nm in names:
        try:
            f = ImageFont.truetype(nm, size)
            break
        except OSError:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:
            f = ImageFont.load_default()
    _FONTS[key] = f
    return f


VCOL = {'smooth': (60, 185, 90), 'noticeable': (240, 165, 30), 'jarring': (225, 55, 55), 'unknown': (150, 150, 150)}
COL_A, COL_B, COL_MOVE, COL_FACE, COL_CUT = (255, 220, 0), (0, 215, 255), (255, 120, 0), (120, 255, 120), (255, 40, 40)


def _arrow(d, x0, y0, x1, y1, col, width=2, head=6, outline=True):
    if outline:
        d.line([(x0, y0), (x1, y1)], fill=(0, 0, 0), width=width + 2)
    d.line([(x0, y0), (x1, y1)], fill=col, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    pts = [(x1, y1), (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45)),
           (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))]
    if outline:
        d.polygon(pts, fill=col, outline=(0, 0, 0))
    else:
        d.polygon(pts, fill=col)


def _dot(d, x, y, col, r=6):
    d.ellipse([x - r - 1, y - r - 1, x + r + 1, y + r + 1], fill=(0, 0, 0))
    d.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _tile_size(w, h, n):
    if w >= h:
        tw = min(256, 1536 // max(1, n))
        th = int(round(tw * h / w))
    else:
        th = min(320, int(1536 // max(1, n) * h / w))
        tw = int(round(th * w / h))
    return max(32, tw // 2 * 2), max(32, th // 2 * 2)


def _draw_tile(bgr, size, motion, att, faces, col, thr, label, sub=None, border=None):
    from PIL import Image, ImageDraw
    cv2 = _cv2()
    tw, th = size
    im = Image.fromarray(cv2.cvtColor(cv2.resize(bgr, (tw, th), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(im)
    for f in faces or []:
        x0, y0, x1, y1 = f['box']
        d.rectangle([x0 * tw, y0 * th, x1 * tw, y1 * th], outline=COL_FACE, width=1)
    if motion:
        act = float(thr['cuts.action_speed'])
        gx = 6 if tw >= th else 4
        cell = min(tw, th) / (gx if tw < th else 4)
        for cx, cy, u, v in motion.get('grid') or []:
            sp = math.hypot(u, v)
            L = cell * 0.45 * min(1.0, max(0.35, sp / (2 * act)))
            ux, uy = u / sp, -v / sp
            x0, y0 = cx * tw - ux * L / 2, cy * th - uy * L / 2
            _arrow(d, x0, y0, x0 + ux * L, y0 + uy * L, COL_MOVE, width=2, head=5)
        c = motion.get('cam') or {}
        sp = math.hypot(c.get('dx', 0.0), c.get('dy', 0.0))
        if sp >= float(thr['cuts.pan_speed']):
            ux, uy = c['dx'] / sp, -c['dy'] / sp
            x0, y0 = tw - 22, th - 22
            _arrow(d, x0 - ux * 10, y0 - uy * 10, x0 + ux * 10, y0 + uy * 10, (200, 200, 255), width=2, head=5)
    if att:
        _dot(d, att['x'] * tw, att['y'] * th, col, r=5)
    f = _font(12, bold=True)
    tb = d.textbbox((0, 0), label, font=f)
    d.rectangle([0, 0, tb[2] + 6, tb[3] + 4], fill=(0, 0, 0))
    d.text((3, 1), label, fill=(255, 255, 255), font=f)
    if sub:
        f2 = _font(12)
        tb = d.textbbox((0, 0), sub, font=f2)
        d.rectangle([0, th - tb[3] - 5, tb[2] + 6, th], fill=(0, 0, 0))
        d.text((3, th - tb[3] - 3), sub, fill=(255, 210, 120), font=f2)
    if border:
        d.rectangle([0, 0, tw - 1, th - 1], outline=border, width=3)
    return im


def _chart(size, a_speed, b_speed, thr, n_before, n_after):
    from PIL import Image, ImageDraw
    W, H = size
    im = Image.new('RGB', (W, H), (22, 22, 26))
    d = ImageDraw.Draw(im)
    a = [x for x in a_speed]
    b = [x for x in b_speed]
    n = len(a) + len(b)
    if n < 2:
        return im
    vals = [x for x in a + b if x is not None]
    act0 = float(thr['cuts.action_speed'])
    top = max(2.0 * act0, (float(np.percentile(vals, 90)) * 1.25) if vals else 0.0)   # spikes are clipped
    L, R, T, B = 34, 8, 18, 18
    pw, ph = W - L - R, H - T - B

    def X(i):
        return L + pw * i / max(1, n - 1)

    def Y(v):
        return T + ph * (1 - min(v, top) / top)
    f = _font(11)
    d.text((L, 2), 'subject speed (diag/s)', fill=(200, 200, 200), font=f)
    act = float(thr['cuts.action_speed'])
    for xx in range(L, L + pw, 8):
        d.line([(xx, Y(act)), (xx + 4, Y(act))], fill=(130, 130, 130))
    d.text((2, Y(act) - 7), f'{act:g}', fill=(160, 160, 160), font=f)
    d.text((2, T - 6), f'{top:.1f}', fill=(160, 160, 160), font=f)
    xa0 = X(max(0, len(a) - n_before))
    xb1 = X(min(n - 1, len(a) + n_after - 1))
    d.rectangle([xa0, T, xb1, T + ph], outline=(70, 70, 90))

    def line(series, off, col):
        pts = [(X(off + i), Y(v)) for i, v in enumerate(series) if v is not None]
        if len(pts) > 1:
            d.line(pts, fill=col, width=2)
        for p in pts:
            d.ellipse([p[0] - 1.5, p[1] - 1.5, p[0] + 1.5, p[1] + 1.5], fill=col)
    line(a, 0, COL_A)
    line(b, len(a), COL_B)
    xc = (X(len(a) - 1) + X(len(a))) / 2
    d.line([(xc, T - 2), (xc, T + ph + 2)], fill=COL_CUT, width=2)
    d.text((xc + 3, T + ph + 2), 'cut', fill=COL_CUT, font=f)
    d.text((L, T + ph + 2), f'-{len(a)}f', fill=(160, 160, 160), font=f)
    d.text((L + pw - 22, T + ph + 2), f'+{len(b)}f', fill=(160, 160, 160), font=f)
    return im


def _measure_lines(c):
    m = c['measures']
    rh, ey, sd, sp, ex = m['rhythm'], m['eye_trace'], m['screen_direction'], m['space'], m['extra']

    def f2(x):
        return '-' if x is None else f'{x:.2f}'
    lines = [f'rhythm: A {rh["a_phase"]["phase"]} ({f2(rh["a_end_speed"])}) -> B {rh["b_phase"]["phase"]} '
             f'({f2(rh["b_start_speed"])}); on action: {"yes" if rh["cut_on_action"] else "no"}; '
             f'post-cut {f2(rh["post_motion"])} diag/s',
             f'eye-trace: A ({f2(ey["a"].get("x"))},{f2(ey["a"].get("y"))} {ey["a"].get("basis")}) -> B '
             f'({f2(ey["b"].get("x"))},{f2(ey["b"].get("y"))} {ey["b"].get("basis")}): jump {f2(ey["jump"])} diag',
             f'direction: A {sd["a_dir_word"]} -> B {sd["b_dir_word"]}'
             + (f' ({sd["angle_change"]:.0f} deg)' if sd.get('angle_change') is not None else '')
             + f'; camera {sd["camera_a"]["label"]} -> {sd["camera_b"]["label"]}; subject '
             f'{sd["subject_a_side"] or "-"} -> {sd["subject_b_side"] or "-"}',
             f'space: framing {f2(sp["framing_sim"])}, layout {f2(sp["layout_sim"])}, zoom {f2(sp["reframe_zoom"])}; '
             f'size {sp["size_a"]} -> {sp["size_b"]}'
             + (f' ({sp["size_ratio"]:.2f}x)' if sp.get('size_ratio') else '')
             + ('; JUMP CUT' if sp['jump_cut'] else '; PUNCH-IN' if sp['punch_in'] else ''),
             f'extra: luma {ex["luma_a"]:.0f} -> {ex["luma_b"]:.0f}; shots {ex.get("shot_a_frames") or "?"}f / '
             f'{ex.get("shot_b_frames") or "?"}f',
             'sound: ' + _sound_line(c.get('sound'))]
    return lines


def _sound_line(s):
    if not s or s.get('status') == 'unchecked':
        return 'unchecked' + (f' ({s.get("why")})' if s and s.get('why') else '')
    b = sound_brief(s)
    parts = ['flags: ' + (', '.join(b.get('flags') or []) or 'none')]
    for k in ('click', 'speech_level_jump', 'room_tone_jump', 'spectral_jump'):
        if b.get(k) is not None:
            parts.append(f'{k} {b[k]}')
    w = b.get('words') or {}
    if w.get('last_word') or w.get('next_word'):
        parts.append(f'"{w.get("last_word") or ""}" | "{w.get("next_word") or ""}"')
    return '; '.join(parts)


def sound_brief(s):
    """B3's joins entry in short: its flags, the main values and the words around the join."""
    if not s or not isinstance(s, dict) or s.get('status') == 'unchecked':
        return s
    out = {'flags': list(s.get('flags') or [])}
    for k in ('click', 'level_jump', 'speech_level_jump', 'room_tone_jump', 'spectral_jump', 'pitch_jump'):
        v = s.get(k)
        if isinstance(v, dict):
            v = v.get('value')
        if v is not None:
            out[k] = v
    w = s.get('words')
    if isinstance(w, dict):
        out['words'] = {k: w.get(k) for k in ('last_word', 'next_word', 'word_cut', 'pause_across_s',
                                              'thought_end', 'breath_in_pause') if w.get(k) is not None}
    for k in ('fine_cut', 'sound_at_cut'):
        if s.get(k):
            out[k] = s[k]
    return out


def _wrap(d, text, font, width):
    words = text.split(' ')
    lines, cur = [], ''
    for wd in words:
        t = (cur + ' ' + wd).strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def draw_strip(c, A, B, st, thr, out_path, video=None):
    """The strip image of one cut (see the module docstring). A, B: the analysed sides (all their frames)."""
    from PIL import Image, ImageDraw
    cv2 = _cv2()
    nb_, na_ = int(st['before']), int(st['after'])
    a_idx = list(range(max(0, len(A['bgr']) - nb_), len(A['bgr'])))
    b_idx = list(range(0, min(len(B['bgr']), na_)))
    h, w = A['bgr'][0].shape[:2]
    tw, th = _tile_size(w, h, max(nb_, na_))
    ncol = max(nb_, na_)
    title_h = 30
    band_h = max(240, int(th * (1.5 if w >= h else 1.0)) + 8)
    width = max(ncol * tw, 980)
    height = title_h + 2 * th + 4 + band_h
    sheet = Image.new('RGB', (width, height), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    v = c['verdict']
    col = VCOL.get(v['verdict'], VCOL['unknown'])
    d.rectangle([0, 0, width, title_h], fill=(34, 34, 40))
    d.rectangle([0, 0, 120, title_h], fill=col)
    d.text((8, 6), v['verdict'].upper(), fill=(0, 0, 0), font=_font(15, bold=True))
    names = ''
    if c.get('from_clip') or c.get('to_clip'):
        names = f'  {Path(str(c.get("from_clip") or "?")).name[:28]} -> {Path(str(c.get("to_clip") or "?")).name[:28]}'
    title = f'cut {c["n"]}  {_clock(c["t"])}  f{c["f"]}  {c["kind"]}{names}'
    d.text((130, 6), title, fill=(235, 235, 235), font=_font(15, bold=True))
    draw = c['measures'].get('_draw') or {}
    att_a, att_b = draw.get('att_a') or [], draw.get('att_b') or []
    # attention lists cover the last max(att_a_n, before) frames of A and the first of B
    off_a = len(A['bgr']) - len(att_a)
    y0 = title_h
    for k, i in enumerate(a_idx):
        att = att_a[i - off_a] if 0 <= i - off_a < len(att_a) else None
        mo = A['motion'][i]
        rel = i - len(A['bgr'])
        im = _draw_tile(A['bgr'][i], (tw, th), mo, att, A['faces'][i], COL_A, thr,
                        f'{rel}  f{c["a_frames"][i] if c.get("a_frames") else ""}',
                        sub=f'{mo["speed"]:.2f}' if mo else None, border=COL_CUT if rel == -1 else None)
        sheet.paste(im, ((ncol - len(a_idx) + k) * tw, y0))
    y1 = y0 + th + 4
    d.text((4, y1 - 4), '', fill=COL_CUT)
    for k, i in enumerate(b_idx):
        att = att_b[i] if i < len(att_b) else None
        mo = B['motion'][i]
        im = _draw_tile(B['bgr'][i], (tw, th), mo, att, B['faces'][i], COL_B, thr,
                        f'+{i}  f{c["b_frames"][i] if c.get("b_frames") else ""}',
                        sub=f'{mo["speed"]:.2f}' if mo else None, border=COL_CUT if i == 0 else None)
        sheet.paste(im, (k * tw, y1))
    # band: blend of the join + chart + numbers
    yb = y1 + th + 4
    jw = int(tw * (1.5 if w >= h else 1.0)) // 2 * 2
    jh = int(round(jw * h / w)) // 2 * 2
    if jh > band_h - 8:
        jh = band_h - 8
        jw = int(round(jh * w / h)) // 2 * 2
    ga = cv2.resize(A['bgr'][-1], (jw, jh), interpolation=cv2.INTER_AREA)
    gb = cv2.resize(B['bgr'][0], (jw, jh), interpolation=cv2.INTER_AREA)
    blend = Image.fromarray(cv2.cvtColor(cv2.addWeighted(ga, 0.5, gb, 0.5, 0), cv2.COLOR_BGR2RGB))
    bd = ImageDraw.Draw(blend)
    pa, pb = draw.get('pa'), draw.get('pb')
    if pa and pb:
        _arrow(bd, pa['x'] * jw, pa['y'] * jh, pb['x'] * jw, pb['y'] * jh, (255, 255, 255), width=2, head=8)
    if pa:
        _dot(bd, pa['x'] * jw, pa['y'] * jh, COL_A, r=6)
    if pb:
        _dot(bd, pb['x'] * jw, pb['y'] * jh, COL_B, r=6)
    lab = 'join: A last + B first'
    tb = bd.textbbox((0, 0), lab, font=_font(12, bold=True))
    bd.rectangle([0, 0, tb[2] + 6, tb[3] + 4], fill=(0, 0, 0))
    bd.text((3, 1), lab, fill=(255, 255, 255), font=_font(12, bold=True))
    sheet.paste(blend, (4, yb + 4))
    cx0 = jw + 12
    cw = width - cx0 - 6
    chart_h = 104
    ch = _chart((cw, chart_h), c['measures']['per_frame']['a_speed'], c['measures']['per_frame']['b_speed'], thr,
                nb_, na_)
    sheet.paste(ch, (cx0, yb + 4))
    f = _font(13)
    ty = yb + 8 + chart_h
    reasons = '; '.join(v['reasons'][:3])
    lines = [f'{v["verdict"]}: {reasons}'] + _measure_lines(c)
    for ln in lines:
        for wl in _wrap(d, ln, f, cw - 6):
            if ty > height - 15:
                break
            d.text((cx0 + 2, ty), wl, fill=(235, 235, 235) if ln is lines[0] else (200, 200, 205), font=f)
            ty += 16
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=88)
    return str(out_path)
