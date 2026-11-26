import math

TITLE = 'Countdown'
DESCRIPTION = ('A timer that runs while it plays ("0:30" down to "0:00", or up when to_s is the larger): from_s at the '
               'start, to_s at the end of the item (real time when the item is that many seconds long); format m:ss, s '
               'or s.t; it turns warn_fill for the last warn_s seconds of a countdown and pulses as each second goes; '
               'an optional label over it ("TIME LEFT"). position: a named place (top-right...) or [x, y], the centre as '
               'fractions of the frame.')
PARAMS = {'from_s': 30, 'to_s': 0, 'format': 'm:ss', 'label': '', 'position': 'top-right', 'font': 'heading',
          'size': 96, 'label_font': 'body', 'label_size': 32, 'fill': 'light', 'warn_fill': '#FF3B30', 'warn_s': 5,
          'label_fill': 'secondary', 'panel': 'dark', 'panel_opacity': 0.72, 'pulse': 0.1}
ANIMATED = True
DEFAULT_LEN = 10.0


def _ends(p):
    return float(p.get('from_s', 30)), float(p.get('to_s', 0))


def _value(ctx):
    a, b = _ends(ctx.p)
    return a + (b - a) * min(1.0, ctx.t / max(ctx.len, 1e-6))


def _shown(p, v):
    """The whole second on the clock: a countdown shows 30 until a full second has gone, a count-up 0."""
    a, b = _ends(p)
    return math.floor(v + 1e-6) if b > a else math.ceil(v - 1e-6)


def _label(p, v):
    fmt = p.get('format', 'm:ss')
    if fmt == 's.t':
        return f'{max(0.0, v):.1f}'
    s = max(0, _shown(p, v))
    return str(s) if fmt == 's' else f'{s // 60}:{s % 60:02d}'


def _pulse(ctx, v):
    """1 -> 0 over the quarter second after the clock's second changes."""
    a, b = _ends(ctx.p)
    rate = abs(b - a) / max(ctx.len, 1e-6) or 1.0
    since = abs(v - _shown(ctx.p, v)) / rate
    return max(0.0, 1 - since / 0.25)


def frame_key(ctx):
    v = _value(ctx)
    return (_label(ctx.p, v), round(_pulse(ctx, v), 2), round(min(ctx.anim_in(0.25), ctx.anim_out(0.25)), 2))


def draw(ctx):
    p = ctx.p
    vis = min(ctx.anim_in(0.25), ctx.anim_out(0.25))
    if vis <= 0.02:
        return
    v = _value(ctx)
    a, b = _ends(p)
    text = _label(p, v)
    widest = max(_label(p, a), _label(p, b), key=len)
    warn = b < a and float(p.get('warn_s') or 0) > 0 and _shown(p, v) <= float(p['warn_s'])
    size = float(p['size']) * (1 + float(p.get('pulse') or 0) * _pulse(ctx, v) ** 2)
    w, h = ctx.measure(''.join('0' if ch.isdigit() else ch for ch in widest), p['font'], p['size'])
    lh = ctx.s(p['label_size']) * 1.35 if p.get('label') else 0
    pad_x, pad_y = ctx.s(34), ctx.s(20)
    bw, bh = w + 2 * pad_x, h + lh + 2 * pad_y
    pos = p.get('position', 'top-right')
    if isinstance(pos, (list, tuple)):
        x, y = ctx.x(float(pos[0])) - bw / 2, ctx.y(float(pos[1])) - bh / 2
    else:
        x, y = ctx.place(bw, bh, str(pos))
    if p.get('panel'):
        ctx.rect([x, y, x + bw, y + bh], fill=ctx.color(p['panel'], alpha=float(p.get('panel_opacity', 0.72)) * vis),
                 radius=24)
    if p.get('label'):
        ctx.text((x + bw / 2, y + pad_y), p['label'], p['label_font'], p['label_size'], fill=p['label_fill'],
                 anchor='ma', opacity=vis)
    ctx.text((x + bw / 2, y + pad_y + lh + h / 2), text, p['font'], size, fill=p['warn_fill'] if warn else p['fill'],
             anchor='mm', opacity=vis)
