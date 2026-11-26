TITLE = 'Text pop'
DESCRIPTION = 'One punchy word or phrase ("NO WAY", "Finally!") that pops onto the screen with a bounce and shadow.'
PARAMS = {'text': 'WOW', 'position': 'center', 'font': 'heading', 'size': 160, 'fill': 'secondary', 'outline': 'dark',
          'outline_width': 8, 'shadow': 'accent', 'tilt': -4}
ANIMATED = True
DEFAULT_LEN = 1.6


def draw(ctx):
    p = ctx.p
    k = min(ctx.anim_in(0.35, ease='back'), ctx.anim_out(0.2, ease='in'))
    if k <= 0.02:
        return
    size = ctx.fit_size(p['text'], p['font'], p['size'], ctx.w * 0.8)
    w, h = ctx.measure(p['text'], p['font'], size, stroke=p.get('outline_width', 0))
    x, y = ctx.place(w, h, p['position'])
    lay = ctx.layer()
    ctx.text((x + w / 2, y + h / 2), p['text'], p['font'], size * (0.6 + 0.4 * k), fill=p['fill'], anchor='mm',
             outline=p.get('outline'), outline_width=p.get('outline_width', 0), shadow=p.get('shadow'),
             shadow_offset=(8, 10), on=lay)
    tilt = float(p.get('tilt', 0))
    if tilt:
        lay = lay.rotate(tilt * k, center=(x + w / 2, y + h / 2), resample=3)
    ctx.paste(lay, opacity=min(1.0, k * 1.5))
