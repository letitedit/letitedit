"""The drawing, which runs in the graphics sandbox.

Part of `annotate` (letitedit/pictures/annotate.py), which imports every name here back,
so `annotate.X` is the same object it always was.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from letitedit.pictures.annotate_geometry import (  # noqa: E402
    box_center, box_grow, box_h, box_union, box_w, mat_inv, mat_mul, mat_scale, mat_translate
)
from letitedit.pictures.annotate_screen import (  # noqa: E402
    _arrow_tip, _closest_on_box, _edge_toward, _ring_radius, expand_geom, label_box_at, solve_layout, style_of
)


# ============================================================================ drawing (runs in the graphics sandbox)

_STATE = {}


class _SS:
    """Supersampled drawing in one region of the canvas: give canvas coordinates; drawn at k x, then scaled down."""

    def __init__(self, box, W, H, k=3):
        from PIL import Image, ImageDraw
        x0, y0 = max(0, int(math.floor(box[0])) - 2), max(0, int(math.floor(box[1])) - 2)
        x1, y1 = min(W, int(math.ceil(box[2])) + 2), min(H, int(math.ceil(box[3])) + 2)
        self.ok = x1 > x0 and y1 > y0
        self.ox, self.oy, self.k = x0, y0, k
        self.size = (max(1, x1 - x0), max(1, y1 - y0))
        self.img = Image.new('RGBA', (self.size[0] * k, self.size[1] * k), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def p(self, x, y):
        return ((x - self.ox) * self.k - 0.5, (y - self.oy) * self.k - 0.5)

    def r(self, v):
        return v * self.k

    def circle(self, c, radius, fill=None, outline=None, width=0):
        x, y = self.p(*c)
        rr = self.r(radius)
        self.d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=fill, outline=outline, width=int(round(self.r(width))))

    def line(self, a, b, color, width):
        pa, pb = self.p(*a), self.p(*b)
        w = self.r(width)
        self.d.line([pa, pb], fill=color, width=max(1, int(round(w))))
        for q in (pa, pb):
            self.d.ellipse([q[0] - w / 2, q[1] - w / 2, q[0] + w / 2, q[1] + w / 2], fill=color)

    def polygon(self, pts, fill=None, outline=None, width=0):
        self.d.polygon([self.p(*q) for q in pts], fill=fill, outline=outline, width=int(round(self.r(width))))

    def rrect(self, box, radius, fill=None, outline=None, width=0):
        a, b = self.p(box[0], box[1]), self.p(box[2], box[3])
        self.d.rounded_rectangle([a[0], a[1], b[0], b[1]], radius=self.r(radius), fill=fill, outline=outline,
                                 width=int(round(self.r(width))))

    def paste(self, layer):
        from PIL import Image
        if not self.ok:
            return
        small = self.img.resize(self.size, Image.LANCZOS)
        layer.alpha_composite(small, (self.ox, self.oy))


def _ease_out_back(x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _params_key(p, W, H):
    return hashlib.sha1(json.dumps([p, W, H], sort_keys=True, default=str).encode()).hexdigest()


def _setup(ctx):
    """Layout and per-frame data, once per recipe (draw is called for every frame in one process)."""
    p = ctx.p
    key = _params_key(p, ctx.w, ctx.h)
    if _STATE.get('key') == key:
        return _STATE
    st = style_of(p)
    font = st['font']

    def measure(text, size):
        return ctx.measure(text, font, size)
    frames = expand_geom(p['geom'])
    lay = solve_layout({**p, 'size': [ctx.w, ctx.h]}, measure, ctx.fps)
    _STATE.clear()
    _STATE.update(key=key, st=st, frames=frames, lay=lay, last=None, freeze=None, still=None, reader=None)
    fz = (p.get('freeze') or {}).get('png')
    if fz and os.path.exists(fz):
        from PIL import Image
        img = Image.open(fz).convert('RGBA')
        if img.size != (ctx.w, ctx.h):
            img = img.resize((ctx.w, ctx.h), Image.LANCZOS)
        _STATE['freeze'] = img
    return _STATE


def _source_picture(p, i, fps, live):
    """The source frame (display orientation, full size) for the magnifier: one still at `at`, or frame by frame."""
    import letitedit.pictures.graphics as graphics
    src = p['source']
    dw, dh = src['display']
    if not live:
        if _STATE.get('still') is None:
            _STATE['still'] = graphics.still(src['file'], float(src['at']), (dw, dh))
        return _STATE['still']
    t = float(p['src_t0']) + i / fps
    rd = _STATE.get('reader')
    if rd is None or rd['next'] != i:
        if rd is not None:
            rd['gen'].close()
        gen = graphics.source_frames({'clip': src['file'], 'in': t, 'out': t + (p['geom']['n'] - i + 2) / fps},
                                     dw, dh, fps)
        rd = _STATE['reader'] = {'gen': gen, 'next': i}
    img = next(rd['gen'], None)
    rd['next'] = i + 1
    return img if img is not None else graphics.still(src['file'], t, (dw, dh))


def draw(ctx):
    """Draw one frame of an annotation recipe (the 'custom' graphic's code calls this; see CODE)."""
    from PIL import Image
    S = _setup(ctx)
    p, st, frames, lay = ctx.p, S['st'], S['frames'], S['lay']
    W, H, fps = ctx.w, ctx.h, float(ctx.fps)
    s = H / 1080.0
    n = len(frames)
    i = max(0, min(n - 1, int(ctx.frame)))
    if S['freeze'] is not None:
        ctx.canvas.alpha_composite(S['freeze'])
    a = lay['alpha'][i] if i < len(lay['alpha']) else 0.0
    f = frames[i]
    if a <= 0.004 or f is None:
        return
    t = i / fps
    pop = bool(st['pop'])
    k_ring = _ease_out_back(t / 0.35) if pop else 1.0
    k_grow = _ease_out(t / 0.3) if pop else 1.0
    k_label = _ease_out_back((t - (0.45 if p['kind'] == 'magnify' else 0.15)) / 0.3) if pop else 1.0
    k_inset = _ease_out((t - 0.12) / 0.35) if pop else 1.0
    phase = (round(k_ring, 3), round(k_grow, 3), round(k_label, 3), round(k_inset, 3))
    live = bool(st.get('live')) and p['kind'] == 'magnify'
    key = (round(a, 3), tuple(round(v, 2) for v in (f[1], f[2], *f[3])), phase, i if live else None)
    if S['last'] is not None and S['last'][0] == key:
        ctx.canvas.alpha_composite(S['last'][1])
        return
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    _draw_annotation(ctx, layer, p, st, lay, frames, i, f, s, k_ring, k_grow, k_label, k_inset, live)
    if a < 0.999:
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * a)))
    S['last'] = (key, layer)
    ctx.canvas.alpha_composite(layer)


def _draw_spotlight(layer, st, kind, point, c, radius, box, s, W, H):
    """Darkens the layer everywhere but a soft hole around the ring or the box."""
    from PIL import Image, ImageDraw, ImageFilter
    mask = Image.new('L', (W, H), int(255 * min(0.85, float(st['dim']))))
    md = ImageDraw.Draw(mask)
    rr = radius * 1.15 if kind in ('ring', 'magnify', 'label') or point else 0
    if rr:
        md.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=0)
    else:
        gb = box_grow(box, (st['stroke'] + 12) * s)
        md.rounded_rectangle(list(gb), radius=14 * s, fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(10 * s))
    shade = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    shade.putalpha(mask)
    layer.alpha_composite(shade)


def _arrow_geometry(lay, f, c, lbox, s, point, radius, region):
    """The arrow's tail and tip (from the label, or along the layout's direction and length) and the region
    grown to hold it."""
    if lbox:
        lc = box_center(lbox)
        tip = _arrow_tip(f, c, lc, s, point, radius)
        tail = _closest_on_box(box_grow(lbox, 6 * s), tip)
    else:
        ux, uy = lay['arrow']['dir']
        tip = _arrow_tip(f, c, (c[0] + ux * 1000, c[1] + uy * 1000), s, point, radius)
        L = lay['arrow']['length']
        tail = (tip[0] + ux * L, tip[1] + uy * L)
    arrow_geom = (tail, tip)
    region = list(box_union([tuple(region), (min(tail[0], tip[0]) - 60 * s, min(tail[1], tip[1]) - 60 * s,
                                             max(tail[0], tip[0]) + 60 * s, max(tail[1], tip[1]) + 60 * s)]))
    return arrow_geom, region


def _draw_arrow(pen, arrow_geom, k_grow, s, edge, dark, acc):
    """Draws the arrow grown k_grow of the way from its tail: a shaft and head in the pointer colour on a dark
    edge."""
    tail, tip = arrow_geom
    L = math.hypot(tip[0] - tail[0], tip[1] - tail[1]) or 1.0
    ux, uy = (tip[0] - tail[0]) / L, (tip[1] - tail[1]) / L
    cur_tip = (tail[0] + ux * L * k_grow, tail[1] + uy * L * k_grow)
    head_l, head_w = 34 * s, 32 * s
    base = (cur_tip[0] - ux * head_l, cur_tip[1] - uy * head_l)
    px, py = -uy, ux
    head = [cur_tip, (base[0] + px * head_w / 2, base[1] + py * head_w / 2),
            (base[0] - px * head_w / 2, base[1] - py * head_w / 2)]
    shaft_end = (base[0] + ux * 2 * s, base[1] + uy * 2 * s)
    width = 10 * s
    pen.line(tail, shaft_end, dark, width + 2 * edge)
    pen.polygon(head, fill=dark, outline=dark, width=2 * edge)
    pen.line(tail, shaft_end, acc, width)
    pen.polygon(head, fill=acc)


def _draw_inset_detail(layer, ctx, p, i, live, c, inset, D, cc):
    """Pastes the magnifier's round, zoomed detail of the source picture at the inset's current place."""
    from PIL import Image, ImageDraw
    # live: this frame's picture around where the object is now; otherwise the still at `at` around where the object
    # was then (a frozen detail shows the object as it was when it was named)
    mag = p.get('mag') or {}
    if live:
        mrow, centre = _matrix_at(p['geom'], i), c
    else:
        mrow, centre = mag.get('m'), tuple(mag['c']) if mag.get('c') else c
    if mrow is not None:
        src = _source_picture(p, i, ctx.fps, live)
        m = [[mrow[0], mrow[1], mrow[2]], [mrow[3], mrow[4], mrow[5]], [0.0, 0.0, 1.0]]
        z = float(inset['zoom'])
        # inset pixels -> output pixels around the target -> source pixels
        to_out = mat_mul(mat_translate(centre[0], centre[1]),
                         mat_mul(mat_scale(1 / z, 1 / z), mat_translate(-D / 2, -D / 2)))
        inv = mat_mul(mat_inv(m), to_out)
        size = max(2, int(round(D)))
        detail = src.transform((size, size), Image.AFFINE,
                               data=(inv[0][0], inv[0][1], inv[0][2], inv[1][0], inv[1][1], inv[1][2]),
                               resample=Image.BICUBIC)
        k = 3
        mk = Image.new('L', (size * k, size * k), 0)
        ImageDraw.Draw(mk).ellipse([0, 0, size * k - 1, size * k - 1], fill=255)
        mk = mk.resize((size, size), Image.LANCZOS)
        alpha = Image.composite(detail.getchannel('A'), Image.new('L', (size, size), 0), mk)
        detail.putalpha(alpha)
        layer.alpha_composite(detail, (int(round(cc[0] - size / 2)), int(round(cc[1] - size / 2))))


def _draw_label(layer, ctx, st, lbox, tx, k_label, s, acc, W, H):
    """Draws the label's box and words, growing and fading in with k_label."""
    sc = 0.6 + 0.4 * k_label
    lc = box_center(lbox)
    bw, bh = box_w(lbox) * sc, box_h(lbox) * sc
    b = (lc[0] - bw / 2, lc[1] - bh / 2, lc[0] + bw / 2, lc[1] + bh / 2)
    lp = _SS(box_grow(b, 4), W, H)
    fill = ctx.color(st['label_fill'], alpha=float(st['label_opacity']))
    lp.rrect(b, 14 * s * sc, fill=fill, outline=acc, width=3 * s)
    lp.paste(layer)
    # the words grow and fade in with their box (no empty box while it pops)
    ctx.text(lc, '\n'.join(tx['lines']), st['font'], tx['size'] * min(1.0, sc), fill=st['label_text'],
             anchor='mm', align='center', on=layer, opacity=min(1.0, 0.25 + k_label))


def _draw_annotation(ctx, layer, p, st, lay, frames, i, f, s, k_ring, k_grow, k_label, k_inset, live):
    W, H = ctx.w, ctx.h
    kind = p['kind']
    point = p.get('point', False)
    acc = ctx.color(st['color'])
    dark = ctx.color(st['outline'])
    stroke, edge = float(st['stroke']) * s, 3.0 * s
    c = (f[1], f[2])
    box = f[3]
    radius = _ring_radius(box, st, s, point)
    margin = float(st['margin']) * min(W, H)
    tx = lay.get('text')
    label_size = None
    if tx:
        label_size = (tx['block'][0] + 2 * tx['pad'][0], tx['block'][1] + 2 * tx['pad'][1])
    lbox = label_box_at(lay, i, frames, s, W, H, margin, label_size, kind, radius) if label_size else None
    # spotlight: darken everything but the target (and the label / inset)
    if float(st.get('dim') or 0) > 0:
        _draw_spotlight(layer, st, kind, point, c, radius, box, s, W, H)
    region = [c[0] - radius * 1.5 - 60 * s, c[1] - radius * 1.5 - 60 * s, c[0] + radius * 1.5 + 60 * s,
              c[1] + radius * 1.5 + 60 * s]
    if kind in ('box', 'arrow'):
        region = list(box_union([tuple(region), box_grow(box, 80 * s)]))
    if lbox:
        region = list(box_union([tuple(region), box_grow(lbox, 20 * s)]))
    arrow_geom = None
    if kind == 'arrow':
        arrow_geom, region = _arrow_geometry(lay, f, c, lbox, s, point, radius, region)
    inset = lay.get('inset')
    if inset:
        region = list(box_union([tuple(region), box_grow(tuple(inset['box']), 20 * s)]))
    pen = _SS(region, W, H)
    # the pointer
    if kind in ('ring', 'magnify'):
        rr = radius * (1.0 + 0.35 * (1.0 - k_ring))
        pen.circle(c, rr + stroke / 2 + edge / 2, outline=dark, width=stroke + 2 * edge)
        pen.circle(c, rr + stroke / 2 + edge / 2, outline=acc, width=stroke)
    elif kind == 'box':
        shape, geo = _box_outline(f, st, s, bool(p['geom'].get('rotated')), 1.0 + 0.25 * (1.0 - k_ring))
        if shape == 'quad':
            pen.polygon(geo, outline=dark, width=stroke + 2 * edge)
            pen.polygon(geo, outline=acc, width=stroke)
        else:
            pen.rrect(geo, 12 * s, outline=dark, width=stroke + 2 * edge)
            pen.rrect(geo, 12 * s, outline=acc, width=stroke)
    elif kind == 'label':
        pen.circle(c, 9 * s + edge, fill=dark)
        pen.circle(c, 9 * s, fill=acc)
    if arrow_geom:
        _draw_arrow(pen, arrow_geom, k_grow, s, edge, dark, acc)
    # leader from the ring / dot / box to the label (arrows are their own leader)
    if lbox and kind in ('ring', 'label', 'box') and k_label > 0:
        lc = box_center(lbox)
        start = _edge_toward(c, radius + stroke + edge, lc) if kind != 'box' else _arrow_tip(f, c, lc, s, point, radius)
        if kind == 'label':
            start = _edge_toward(c, 9 * s + edge, lc)
        end = _closest_on_box(lbox, start)
        if math.hypot(end[0] - start[0], end[1] - start[1]) > 6 * s:
            pen.line(start, end, dark, 4 * s + 2 * edge)
            pen.line(start, end, acc, 4 * s)
    # magnifier: the detail, its border, and a connector
    if inset and k_inset > 0:
        ib = tuple(inset['box'])
        icx, icy = box_center(ib)
        D = box_w(ib) * (0.3 + 0.7 * k_inset)
        cc = (c[0] + (icx - c[0]) * k_inset, c[1] + (icy - c[1]) * k_inset)
        _draw_inset_detail(layer, ctx, p, i, live, c, inset, D, cc)
        rcon = radius + stroke / 2 + edge
        a0 = _edge_toward(c, rcon, cc)
        a1 = _edge_toward(cc, D / 2, c)
        if math.hypot(a1[0] - a0[0], a1[1] - a0[1]) > 4 * s:
            pen.line(a0, a1, dark, 4 * s + 2 * edge)
            pen.line(a0, a1, acc, 4 * s)
        pen.circle(cc, D / 2 + stroke / 2, outline=dark, width=stroke + 2 * edge)
        pen.circle(cc, D / 2 + stroke / 2, outline=acc, width=stroke)
    pen.paste(layer)
    # the label (text drawn at 1x: Pillow already smooths glyphs)
    if lbox and tx and k_label > 0:
        _draw_label(layer, ctx, st, lbox, tx, k_label, s, acc, W, H)


def _box_outline(f, st, s, rotated, grow=1.0):
    """The box pointer's outline: ('rect', box) or, when the picture is turned, ('quad', 4 corners) - the target's
    own corners pushed out from its centre."""
    g = (6 + float(st['pad']) * 30) * s * grow
    quad = f[4]
    if quad and rotated:
        cx, cy = f[1], f[2]
        out = []
        for x, y in quad:
            d = math.hypot(x - cx, y - cy) or 1.0
            out.append((x + (x - cx) / d * g * 1.4142, y + (y - cy) / d * g * 1.4142))
        return 'quad', out
    return 'rect', box_grow(f[3], g)


def _matrix_at(geom, i):
    """The source->output matrix (6 numbers) on frame i, when the recipe carries it (magnifier)."""
    best = None
    for k in geom['keys']:
        if k[0] <= i and len(k) > 9 and k[9]:
            best = k[9]
        elif k[0] > i:
            break
    return best
