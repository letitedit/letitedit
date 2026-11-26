TITLE = 'List card'
DESCRIPTION = ('A title over a short list that builds row by row on a panel: what is in the box, the specs, pros and '
               'cons, the rules, three reasons. items: text, or {text, mark, color}; mark: check | cross | dot | number | '
               'none (mark gives the default); a row appears every stagger seconds from start_s, or at times (seconds '
               'from the start of the item, one per row: rows that land on the words). position: left | right '
               '| center | top | bottom (and corners) or [x, y], the centre as fractions of the frame; width: a share of '
               'the frame width (0: about 0.42 on a wide frame, 0.84 on a tall one).')
PARAMS = {'title': '', 'items': ['First thing', 'Second thing'], 'mark': 'dot', 'position': 'left', 'width': 0,
          'font': 'heading', 'body_font': 'body', 'size': 44, 'title_size': 56, 'fill': 'light', 'title_fill': 'secondary',
          'check_color': '#34C759', 'cross_color': '#FF453A', 'mark_color': 'secondary', 'panel': 'dark',
          'panel_opacity': 0.84, 'radius': 22, 'start_s': 0.35, 'stagger': 0.45, 'times': None}
ANIMATED = True
DEFAULT_LEN = 5.0


def _rows(p):
    out = []
    for i, it in enumerate(p.get('items') or []):
        it = it if isinstance(it, dict) else {'text': str(it)}
        out.append({'text': str(it.get('text', '')), 'mark': it.get('mark') or p.get('mark') or 'dot',
                    'color': it.get('color'), 'n': i + 1})
    return out


def _timing(ctx):
    p = ctx.p
    k = ctx.anim_in(0.3, ease='out')
    out = ctx.anim_out(0.3)
    n = len(_rows(p))
    times = list(p.get('times') or [])
    at = [float(times[i]) if i < len(times) else float(p.get('start_s', 0.35)) + i * float(p.get('stagger', 0.45))
          for i in range(n)]
    ks = [ctx.anim_in(0.28, delay=a, ease='out') for a in at]
    return k, out, ks


def frame_key(ctx):
    k, out, ks = _timing(ctx)
    return (round(k, 3), round(out, 3), tuple(round(x, 3) for x in ks))


def _mark(ctx, kind, color, n, cx, cy, r, opacity):
    col = ctx.color(color, alpha=opacity)
    if kind == 'check':
        ctx.line([(cx - r * 0.75, cy + r * 0.02), (cx - r * 0.2, cy + r * 0.55), (cx + r * 0.8, cy - r * 0.6)], col,
                 width=max(3, r * 0.36 / ctx.scale))
    elif kind == 'cross':
        w = max(3, r * 0.34 / ctx.scale)
        ctx.line([(cx - r * 0.62, cy - r * 0.62), (cx + r * 0.62, cy + r * 0.62)], col, width=w)
        ctx.line([(cx - r * 0.62, cy + r * 0.62), (cx + r * 0.62, cy - r * 0.62)], col, width=w)
    elif kind == 'dot':
        ctx.circle((cx, cy), r * 0.32 / ctx.scale, fill=col)
    elif kind == 'number':
        ctx.circle((cx, cy), r * 0.78 / ctx.scale, fill=col)
        ctx.text((cx, cy), str(n), 'heading', r * 1.0 / ctx.scale, fill='dark', anchor='mm', opacity=opacity)


def draw(ctx):
    p = ctx.p
    k, out, ks = _timing(ctx)
    vis = min(k, out)
    if vis <= 0.02:
        return
    rows = _rows(p)
    share = float(p.get('width') or 0) or (0.84 if ctx.h > ctx.w else 0.42)
    bw = ctx.w * share
    pad = ctx.s(36)
    mark_w = ctx.s(float(p['size']) * 1.25)
    text_w = bw - 2 * pad - mark_w
    gap = ctx.s(float(p['size']) * 0.42)
    title = '\n'.join(ctx.wrap(p['title'], p['font'], p['title_size'], bw - 2 * pad)) if p.get('title') else ''
    th = ctx.measure(title, p['font'], p['title_size'])[1] + gap * 1.2 if title else 0
    lines = ['\n'.join(ctx.wrap(r['text'], p['body_font'], p['size'], text_w)) for r in rows]
    hs = [max(ctx.measure(t or ' ', p['body_font'], p['size'])[1], ctx.s(float(p['size']))) for t in lines]
    bh = 2 * pad + th + sum(hs) + gap * max(0, len(rows) - 1)
    pos = p.get('position', 'left')
    if isinstance(pos, (list, tuple)):
        x, y = ctx.x(float(pos[0])) - bw / 2, ctx.y(float(pos[1])) - bh / 2
    else:
        x, y = ctx.place(bw, bh, str(pos))
    x += (1 - k) * -ctx.s(40)
    if p.get('panel'):
        ctx.rect([x, y, x + bw, y + bh], fill=ctx.color(p['panel'], alpha=float(p.get('panel_opacity', 0.84)) * vis),
                 radius=float(p.get('radius', 22)))
    cy = y + pad
    if title:
        ctx.text((x + pad, cy), title, p['font'], p['title_size'], fill=p['title_fill'], opacity=vis)
        cy += th
    for r, text, h, kr in zip(rows, lines, hs, ks):
        o = min(vis, kr)
        if o > 0.02:
            dx = (1 - kr) * -ctx.s(30)
            color = r['color'] or {'check': p['check_color'], 'cross': p['cross_color']}.get(r['mark'], p['mark_color'])
            line_h = ctx.s(float(p['size'])) * 1.15
            _mark(ctx, r['mark'], color, r['n'], x + pad + mark_w * 0.42 + dx, cy + min(h, line_h) / 2,
                  ctx.s(float(p['size'])) * 0.5, o)
            ctx.text((x + pad + mark_w + dx, cy), text, p['body_font'], p['size'], fill=p['fill'], opacity=o)
        cy += h + gap
