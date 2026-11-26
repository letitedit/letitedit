TITLE = 'Big number'
DESCRIPTION = 'A number that counts up ("$1,240 spent", "38 screws", "4.5 hours") with a label under it.'
PARAMS = {'value': 100, 'prefix': '', 'suffix': '', 'decimals': 0, 'label': '', 'position': 'center', 'font': 'heading',
          'size': 170, 'label_font': 'body', 'label_size': 50, 'fill': 'secondary', 'label_fill': 'light',
          'outline': 'dark', 'outline_width': 6, 'count_seconds': 1.2}
ANIMATED = True
DEFAULT_LEN = 3.0


def draw(ctx):
    p = ctx.p
    value = float(p['value'])
    k = ctx.anim_in(float(p['count_seconds']), ease='out')
    shown = value * k
    dec = int(p.get('decimals', 0))
    text = f"{p.get('prefix', '')}{shown:,.{dec}f}{p.get('suffix', '')}"
    final = f"{p.get('prefix', '')}{value:,.{dec}f}{p.get('suffix', '')}"
    w, h = ctx.measure(final, p['font'], p['size'], stroke=p.get('outline_width', 0))
    lh = ctx.s(p['label_size']) * 1.3 if p.get('label') else 0
    x, y = ctx.place(w, h + lh, p['position'])
    a = min(ctx.anim_in(0.25), ctx.anim_out(0.35))
    ctx.text((x + w / 2, y + h / 2), text, p['font'], p['size'], fill=p['fill'], anchor='mm', outline=p.get('outline'),
             outline_width=p.get('outline_width', 0), opacity=a)
    if p.get('label'):
        ctx.text((x + w / 2, y + h + ctx.s(16)), p['label'], p['label_font'], p['label_size'], fill=p['label_fill'],
                 anchor='ma', outline=p.get('outline'), outline_width=3, opacity=min(a, ctx.anim_in(0.4, delay=0.3)))
