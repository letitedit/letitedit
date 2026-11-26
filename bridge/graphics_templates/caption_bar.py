TITLE = 'Caption bar'
DESCRIPTION = ('Meme-style words on a full-width band over the clip ("me after fixing it once:"): dark text on a light '
               'band near the top (or the bottom), wrapped to the width and shrunk to fit max_lines; the band drops in '
               'over in_s. margin: the band\'s distance from that edge as a share of the frame height (clear of the '
               'phone apps\' top bar on a tall frame).')
PARAMS = {'text': 'me when', 'position': 'top', 'margin': 0.0, 'font': 'body', 'size': 62, 'fill': 'dark',
          'band': 'light', 'band_opacity': 1.0, 'pad': 30, 'max_lines': 3, 'align': 'left', 'in_s': 0.15, 'out_s': 0.1}
ANIMATED = True
DEFAULT_LEN = 3.0


def _k(ctx):
    return min(ctx.anim_in(float(ctx.p.get('in_s') or 0), ease='out'), ctx.anim_out(float(ctx.p.get('out_s') or 0)))


def frame_key(ctx):
    return round(_k(ctx), 3)


def draw(ctx):
    p = ctx.p
    k = _k(ctx)
    if k <= 0.02:
        return
    pad = ctx.s(float(p.get('pad', 30)))
    size = float(p['size'])
    lines = ctx.wrap(p['text'], p['font'], size, ctx.w - 2 * pad)
    while len(lines) > int(p.get('max_lines') or 3) and size > 24:
        size -= 2
        lines = ctx.wrap(p['text'], p['font'], size, ctx.w - 2 * pad)
    text = '\n'.join(lines)
    _, th = ctx.measure(text, p['font'], size)
    bh = th + 2 * pad
    top = str(p.get('position', 'top')) != 'bottom'
    edge = ctx.h * float(p.get('margin') or 0)
    y0 = edge if top else ctx.h - edge - bh
    y0 += (1 - k) * (-bh if top else bh) * 0.35
    ctx.rect([0, y0, ctx.w, y0 + bh], fill=ctx.color(p['band'], alpha=float(p.get('band_opacity', 1.0)) * k))
    align = p.get('align', 'left')
    x = pad if align == 'left' else ctx.w / 2
    ctx.text((x, y0 + pad), text, p['font'], size, fill=p['fill'], anchor='la' if align == 'left' else 'ma',
             align='left' if align == 'left' else 'center', opacity=k)
