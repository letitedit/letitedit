TITLE = 'End card'
DESCRIPTION = ('Closing screen with fitted title and subtitle. Optional YouTube end-screen slots (video_slots 0-2) '
               'are drawn only when requested.')
PARAMS = {'title': 'Thanks for watching!', 'subtitle': 'Subscribe for the next one', 'background': 'dark',
          'font': 'heading', 'subtitle_font': 'body', 'size': 100, 'subtitle_size': 48, 'fill': 'light',
          'subtitle_fill': 'primary', 'accent': 'accent', 'video_slots': 0}
ANIMATED = True
DEFAULT_LEN = 8.0


def draw(ctx):
    p = ctx.p
    a = min(ctx.anim_in(0.6), ctx.anim_out(0.6))
    if p.get('background') not in (None, 'none', ''):
        ctx.rect([0, 0, ctx.w, ctx.h], fill=ctx.color(p['background'], alpha=a))
    slots = max(0, min(2, int(p.get('video_slots', 0))))
    top = ctx.h * (0.2 if slots else 0.4)
    max_w = ctx.w * .86
    size = ctx.fit_size(p['title'], p['font'], p['size'], max_w, min_size=24)
    title = '\n'.join(ctx.wrap(p['title'], p['font'], size, max_w))
    ctx.text((ctx.w / 2, top), title, p['font'], size,
             fill=p['fill'], anchor='mm', opacity=a)
    if p.get('subtitle'):
        sub_size = ctx.fit_size(p['subtitle'], p['subtitle_font'], p['subtitle_size'], max_w, min_size=20)
        subtitle = '\n'.join(ctx.wrap(p['subtitle'], p['subtitle_font'], sub_size, max_w))
        ctx.text((ctx.w / 2, top + ctx.s(size) * .85), subtitle, p['subtitle_font'], sub_size,
                 fill=p['subtitle_fill'], anchor='mm', opacity=min(a, ctx.anim_in(0.6, delay=0.3)))
    rule_y = top + ctx.s(size) * (1.6 if p.get('subtitle') else .85)
    rule_w = min(ctx.w * .28, ctx.s(240)) * ctx.anim_in(.6, delay=.25)
    ctx.rect([(ctx.w-rule_w)/2, rule_y, (ctx.w+rule_w)/2, rule_y+max(2,ctx.s(7))],
             fill=ctx.color(p['accent'], alpha=a), radius=3)
    if slots:
        # YouTube end-screen video elements are 16:9; leave room for two side by side
        w = ctx.w * 0.34
        h = w * 9 / 16
        gap = ctx.w * 0.05
        total = slots * w + (slots - 1) * gap
        y = ctx.h * 0.45
        for i in range(slots):
            x = (ctx.w - total) / 2 + i * (w + gap)
            k = ctx.anim_in(0.5, delay=0.25 + 0.12 * i, ease='back')
            ins = (1 - k) * ctx.s(30)
            ctx.rect([x + ins, y + ins, x + w - ins, y + h - ins], outline=ctx.color(p['accent'], alpha=a), width=6, radius=18)
