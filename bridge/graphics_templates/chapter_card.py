from PIL import ImageFilter

TITLE = 'Chapter card'
DESCRIPTION = ('Chapter number and title over the picture (optionally on a translucent band); slides in from the left '
               'with a little overshoot. Good for "Step 2: Pulling the old fan".')
PARAMS = {'number': 1, 'title': 'Chapter title', 'kicker': '', 'position': 'left', 'font': 'heading',
          'number_size': 150, 'size': 76, 'kicker_size': 34, 'fill': 'light', 'accent': 'accent', 'band': True,
          'band_color': 'dark', 'band_opacity': 0.55, 'outline': 'dark', 'outline_width': 3}
ANIMATED = True
DEFAULT_LEN = 3.0


def draw(ctx):
    p = ctx.p
    num = f"{int(p['number']):02d}" if str(p.get('number', '')).isdigit() else str(p.get('number', ''))
    max_w = ctx.w * .88
    number_size = ctx.fit_size(num, p['font'], p['number_size'], max_w * .28) if num else 0
    nw, nh = ctx.measure(num, p['font'], number_size) if num else (0, 0)
    gap = min(ctx.s(30), ctx.w * .035)
    title_w = max_w - nw - gap
    title_size = ctx.fit_size(p['title'], p['font'], p['size'], title_w, min_size=24)
    lines = ctx.wrap(p['title'], p['font'], title_size, title_w)
    while len(lines) > 2 and title_size > 24:
        title_size -= 2
        lines = ctx.wrap(p['title'], p['font'], title_size, title_w)
    title = '\n'.join(lines)
    tw, th = ctx.measure(title, p['font'], title_size)
    box_w, box_h = min(max_w, nw + gap + tw), max(nh, th + ctx.s(p['kicker_size']) * 1.4)
    x, y = ctx.place(box_w, box_h, p['position'] if p['position'] != 'left' else 'left')
    out = ctx.anim_out(0.35)
    if p.get('band'):
        band_a = min(ctx.anim_in(0.3), out) * p['band_opacity']
        pad = ctx.s(36)
        panel = [max(0, x-pad), y-pad, min(ctx.w, x+box_w+pad), y+box_h+pad]
        shadow = ctx.layer()
        ctx.rect([panel[0]+ctx.s(8), panel[1]+ctx.s(12), panel[2]+ctx.s(8), panel[3]+ctx.s(12)],
                 fill=ctx.color('dark', alpha=band_a*.55), radius=26, on=shadow)
        ctx.canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(ctx.s(18))))
        ctx.rect(panel, fill=ctx.color(p['band_color'], alpha=band_a),
                 outline=ctx.color('light', alpha=band_a*.25), width=2, radius=26)
        ctx.rect([panel[0], panel[1]+ctx.s(22), panel[0]+ctx.s(8), panel[3]-ctx.s(22)],
                 fill=ctx.color(p['accent'], alpha=band_a), radius=4)
    slide = (1 - ctx.anim_in(0.55, ease='back')) * -ctx.w * 0.35
    lay = ctx.layer()
    if num:
        ctx.text((x, y + box_h / 2), num, p['font'], number_size, fill=p['accent'], anchor='lm',
                 outline=p.get('outline'), outline_width=p.get('outline_width', 0), on=lay)
    tx = x + nw + gap
    kicker = p.get('kicker')
    if kicker:
        ctx.text((tx, y + box_h / 2 - th / 2 - ctx.s(8)), kicker.upper(), 'body', p['kicker_size'], fill=p['accent'],
                 anchor='lb', on=lay)
    ctx.text((tx, y + box_h / 2), title, p['font'], title_size, fill=p['fill'], anchor='lm',
             outline=p.get('outline'), outline_width=p.get('outline_width', 0),
             shadow='dark', shadow_blur=8, on=lay)
    ctx.paste(lay, dx=slide, opacity=out)
