TITLE = 'Lower third'
DESCRIPTION = 'Name and role (or place and date) on a panel with an accent bar; slides in, holds, slides out.'
PARAMS = {'title': 'Name', 'subtitle': '', 'position': 'bottom-left', 'font': 'heading', 'subtitle_font': 'body',
          'size': 64, 'subtitle_size': 40, 'fill': 'light', 'subtitle_fill': 'primary', 'panel': 'dark',
          'panel_opacity': 0.82, 'accent': 'accent', 'margin_y': 0.22}
ANIMATED = True
DEFAULT_LEN = 4.5


def draw(ctx):
    p = ctx.p
    pad_x, pad_y, gap = ctx.s(34), ctx.s(22), ctx.s(8)
    tw, th = ctx.measure(p['title'], p['font'], p['size'])
    sw, sh = ctx.measure(p['subtitle'], p['subtitle_font'], p['subtitle_size']) if p.get('subtitle') else (0, 0)
    bar_w = ctx.s(12)
    box_w = bar_w + pad_x * 2 + max(tw, sw)
    box_h = pad_y * 2 + th + (gap + sh if sh else 0)
    # sits above a two-line caption block by default (margin_y from the frame edge)
    x, y = ctx.place(box_w, box_h, p['position'], margin_y=float(p.get('margin_y', 0.22)))
    grow_in = ctx.anim_in(0.4)
    grow = min(grow_in, ctx.anim_out(0.35))
    right_side = 'right' in p['position']
    shown_w = bar_w + (box_w - bar_w) * grow
    x0 = x + (box_w - shown_w if right_side else 0)
    layer = ctx.layer()
    ctx.rect([x0, y, x0 + shown_w, y + box_h], fill=ctx.color(p['panel'], alpha=p['panel_opacity']), radius=10, on=layer)
    bx = x + box_w - bar_w if right_side else x
    ctx.rect([bx, y, bx + bar_w, y + box_h], fill=p['accent'], on=layer)
    text_a = min(ctx.anim_in(0.3, delay=0.18), ctx.anim_out(0.3))
    slide = (1 - ctx.anim_in(0.4, delay=0.12)) * ctx.s(-40 if not right_side else 40)
    tx = x + (pad_x if right_side else bar_w + pad_x) + slide
    ctx.text((tx, y + pad_y), p['title'], p['font'], p['size'], fill=p['fill'], opacity=text_a, on=layer)
    if p.get('subtitle'):
        ctx.text((tx, y + pad_y + th + gap), p['subtitle'], p['subtitle_font'], p['subtitle_size'], fill=p['subtitle_fill'],
                 opacity=text_a, on=layer)
    # keep text inside the growing panel
    from PIL import Image, ImageDraw
    mask = Image.new('L', layer.size, 0)
    ImageDraw.Draw(mask).rectangle([x0, y, x0 + shown_w, y + box_h], fill=255)
    clipped = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), mask)
    ctx.paste(clipped)
