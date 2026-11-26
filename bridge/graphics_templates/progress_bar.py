TITLE = 'Progress bar'
DESCRIPTION = ('A bar that grows across the frame while the item plays (a thin line along the bottom or top edge), '
               'from empty at the start to full at the end: place it on its own track above the picture for the '
               "video's length (or the part it measures). color/background: style colour names or #hex.")
PARAMS = {'color': 'accent', 'position': 'bottom', 'thickness': 0.012, 'margin': 0, 'background': '',
          'background_opacity': 0.35, 'radius': 0, 'direction': 'right', 'start': 0.0, 'end': 1.0}
ANIMATED = True
DEFAULT_LEN = 30.0


def draw(ctx):
    """thickness: a share of the frame height; margin: pixels at 1080p from the edge; start / end: the share of the
    item's length over which the bar fills (0 and 1: the whole item); direction: right (left to right) or left."""
    p = ctx.p
    h = max(2, int(round(ctx.h * float(p.get('thickness') or 0.012))))
    m = int(round(ctx.s(float(p.get('margin') or 0))))
    y0 = m if str(p.get('position', 'bottom')).lower() == 'top' else ctx.h - m - h
    x0, x1 = m, ctx.w - m
    if p.get('background'):
        ctx.rect([x0, y0, x1, y0 + h], fill=ctx.color(p['background'], float(p.get('background_opacity', 0.35))),
                 radius=float(p.get('radius') or 0))
    a = max(0.0, min(1.0, float(p.get('start', 0.0))))
    b = max(a + 1e-6, min(1.0, float(p.get('end', 1.0))))
    span = max(1e-6, (b - a) * ctx.len)
    k = max(0.0, min(1.0, (ctx.t - a * ctx.len) / span))
    w = (x1 - x0) * k
    if w < 1:
        return
    box = [x1 - w, y0, x1, y0 + h] if str(p.get('direction', 'right')).lower() == 'left' else [x0, y0, x0 + w, y0 + h]
    ctx.rect(box, fill=p.get('color') or 'accent', radius=float(p.get('radius') or 0))
