TITLE = 'Title card'
DESCRIPTION = ('Big title (and optional subtitle) with an accent underline. Full-frame background colour, or '
               "background: none to lay it over the picture. Eases in, holds, fades out.")
PARAMS = {'title': 'Title', 'subtitle': '', 'background': 'dark', 'font': 'heading', 'subtitle_font': 'body',
          'size': 132, 'subtitle_size': 54, 'fill': 'light', 'subtitle_fill': 'primary', 'accent': 'accent',
          'outline': None, 'outline_width': 0, 'shadow': None}
ANIMATED = True
DEFAULT_LEN = 3.5


def draw(ctx):
    p = ctx.p
    vis_out = ctx.anim_out(0.45)
    if p.get('background') not in (None, 'none', ''):
        ctx.rect([0, 0, ctx.w, ctx.h], fill=ctx.color(p['background'], alpha=min(ctx.anim_in(0.25), vis_out)))
    max_w = ctx.w * 0.84
    size = ctx.fit_size(p['title'], p['font'], p['size'], max_w)
    grow = ctx.anim_in(0.55, ease='back')
    cx, cy = ctx.w / 2, ctx.h / 2 - (ctx.s(p['subtitle_size']) * 0.7 if p.get('subtitle') else 0)
    a = min(ctx.anim_in(0.35), vis_out)
    ctx.text((cx, cy), p['title'], p['font'], size * (0.9 + 0.1 * grow), fill=p['fill'], anchor='mm', align='center',
             outline=p.get('outline'), outline_width=p.get('outline_width', 0), shadow=p.get('shadow'), opacity=a)
    tw, th = ctx.measure(p['title'], p['font'], size)
    bar = ctx.anim_in(0.5, delay=0.2) * min(tw, ctx.w * 0.5) * 0.5
    by = cy + th / 2 + ctx.s(22)
    ctx.rect([cx - bar, by, cx + bar, by + ctx.s(10)], fill=ctx.color(p['accent'], alpha=vis_out), radius=5)
    if p.get('subtitle'):
        sa = min(ctx.anim_in(0.4, delay=0.3), vis_out)
        rise = (1 - ctx.anim_in(0.45, delay=0.3)) * ctx.s(24)
        ctx.text((cx, by + ctx.s(40) + rise), p['subtitle'], p['subtitle_font'], p['subtitle_size'],
                 fill=p['subtitle_fill'], anchor='ma', align='center', shadow=p.get('shadow'), shadow_offset=(2, 3),
                 opacity=sa)
