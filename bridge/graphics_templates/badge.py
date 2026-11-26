TITLE = 'Badge'
DESCRIPTION = ('A small pill of text in a corner ("$42 part", "2 hours later", "Day 3"); pops in and out. '
               'position: a named place (top-right...) or [x, y], the centre as fractions of the frame.')
PARAMS = {'text': 'Badge', 'position': 'top-right', 'font': 'heading', 'size': 48, 'fill': 'dark', 'background': 'secondary',
          'outline': None, 'icon': ''}
ANIMATED = True
DEFAULT_LEN = 3.0


def draw(ctx):
    p = ctx.p
    label = (p['icon'] + '  ' if p.get('icon') else '') + str(p['text'])
    w, h = ctx.measure(label, p['font'], p['size'])
    pad_x, pad_y = ctx.s(30), ctx.s(16)
    bw, bh = w + 2 * pad_x, h + 2 * pad_y
    pos = p['position']
    if isinstance(pos, (list, tuple)):        # [x, y]: the centre as fractions of the frame, kept inside it
        x, y = ctx.x(float(pos[0])) - bw / 2, ctx.y(float(pos[1])) - bh / 2
        x = min(max(x, ctx.w * 0.04), ctx.w * 0.96 - bw)
    else:
        x, y = ctx.place(bw, bh, pos)
    k = min(ctx.anim_in(0.45, ease='back'), ctx.anim_out(0.3, ease='in'))
    if k <= 0:
        return
    cx, cy = x + bw / 2, y + bh / 2
    sw, sh = bw * k, bh * k
    ctx.rect([cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2], fill=p['background'], radius=bh / 2 / ctx.scale,
             outline=p.get('outline'), width=3 if p.get('outline') else 0)
    if k > 0.5:
        ctx.text((cx, cy), label, p['font'], p['size'] * min(1.0, k), fill=p['fill'], anchor='mm', opacity=min(1.0, k))
