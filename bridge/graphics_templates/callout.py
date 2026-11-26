TITLE = 'Callout'
DESCRIPTION = ('Points at something in the picture: a pulsing ring at target_x/target_y (fractions of the frame), a '
               'line drawn out to a label that pops in. The label goes on the roomier side unless side is given.')
PARAMS = {'text': 'Look here', 'target_x': 0.5, 'target_y': 0.5, 'side': 'auto', 'font': 'body', 'size': 46,
          'fill': 'dark', 'label': 'secondary', 'line': 'secondary', 'ring': 'secondary', 'distance': 0.22}
ANIMATED = True
DEFAULT_LEN = 3.5


def draw(ctx):
    p = ctx.p
    tx, ty = ctx.x(float(p['target_x'])), ctx.y(float(p['target_y']))
    side = p['side']
    if side == 'auto':
        side = 'left' if tx > ctx.w / 2 else 'right'
    up = ty > ctx.h * 0.5
    d = ctx.w * float(p['distance'])
    lx = tx - d if side == 'left' else tx + d
    ly = ty - d * 0.45 if up else ty + d * 0.45
    out = ctx.anim_out(0.3)
    # ring at the target
    ring_r = 26 + 10 * (1 - ctx.anim_in(0.5, ease='out'))
    ctx.circle((tx, ty), ring_r, outline=ctx.color(p['ring'], alpha=out), width=7)
    ctx.circle((tx, ty), 7, fill=ctx.color(p['ring'], alpha=out))
    # line grows from the target to the label
    k = ctx.anim_in(0.35, delay=0.15)
    ctx.line([(tx, ty), (tx + (lx - tx) * k, ty + (ly - ty) * k)], fill=ctx.color(p['line'], alpha=out), width=6)
    # label pops
    pop = ctx.anim_in(0.4, delay=0.4, ease='back')
    if pop <= 0:
        return
    w, h = ctx.measure(p['text'], p['font'], p['size'])
    pad_x, pad_y = ctx.s(26), ctx.s(16)
    bw, bh = (w + 2 * pad_x) * pop, (h + 2 * pad_y) * pop
    bx = lx - bw if side == 'left' else lx
    by = ly - bh / 2
    bx = min(max(bx, ctx.w * 0.03), ctx.w * 0.97 - bw)
    by = min(max(by, ctx.h * 0.04), ctx.h * 0.96 - bh)
    ctx.rect([bx, by, bx + bw, by + bh], fill=ctx.color(p['label'], alpha=out), radius=14)
    if pop > 0.6:
        ctx.text((bx + bw / 2, by + bh / 2), p['text'], p['font'], p['size'] * min(1.0, pop), fill=p['fill'], anchor='mm',
                 opacity=out)
