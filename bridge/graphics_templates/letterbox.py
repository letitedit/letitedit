TITLE = 'Letterbox bars'
DESCRIPTION = ('Bars across the top and bottom of the frame for a widescreen, filmed look: ratio is the shape of the '
               'picture left between them (width / height, e.g. 2.39), or bar is each bar\'s share of the frame height '
               '(used when ratio is empty). Lay it over the footage for as long as the look lasts, under any titles and '
               'captions (titles may sit in the bars).')
PARAMS = {'ratio': None, 'bar': 0.1, 'color': '#000000', 'opacity': 1.0}
ANIMATED = False
DEFAULT_LEN = 10.0


def bar_px(ctx):
    """Each bar's height in pixels of this canvas."""
    p = ctx.p
    if p.get('ratio'):
        return max(0.0, (ctx.h - ctx.w / float(p['ratio'])) / 2)
    return max(0.0, ctx.h * float(p.get('bar') or 0))


def draw(ctx):
    h = bar_px(ctx)
    if h < 0.5:
        return
    col = ctx.color(ctx.p.get('color') or '#000000', alpha=float(ctx.p.get('opacity', 1.0)))
    ctx.rect([0, 0, ctx.w, h], fill=col)
    ctx.rect([0, ctx.h - h, ctx.w, ctx.h], fill=col)
