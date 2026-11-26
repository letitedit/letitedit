import math


TITLE = 'Word captions'
DESCRIPTION = ('Captions that follow the words as they are said (CapCut/TikTok style). words: [[text, start, end], ...] '
               'in seconds from the start of the graphic; center_x (0-1) is where the lines are centred across the width. size is in pixels of a 1080-high frame, so a 1920-high vertical frame draws it 1.78 times larger (size 60 is 107 px there); max_width is a share of the frame width. style: pop (each word pops in), karaoke (all shown, the '
               'current word lights up), highlight (current word on a coloured box), typewriter (words appear), '
               'bounce (current word jumps). weight optionally overrides the font weight (100-900). Pop starts at pop_scale and settles to the requested size; it has no smaller entrance scale. shrink_to_fit (default true): a caption with a word wider than max_width is set smaller so it stays in the frame. blend: normal or an engine glyph blend such as difference/exclusion; nonnormal modes require no box, shadow or highlight. protected: timed normalized boxes the letters cannot overlap. Made by {op: captions, from_speech: true, animate: <style>}.')
PARAMS = {'words': [['Captions', 0.0, 0.6], ['that', 0.6, 0.9], ['follow', 0.9, 1.3], ['the', 1.3, 1.45],
                    ['words', 1.45, 2.0]],
          'style': 'pop', 'font': 'captions', 'weight': None, 'size': 84, 'fill': 'light', 'highlight': 'accent', 'outline': 'dark',
          'outline_width': 7, 'shadow': None, 'position': 'bottom', 'margin_y': 0.12, 'max_width': 0.82, 'center_x': 0.5,
          'uppercase': False, 'box': None, 'pop_scale': 1.15, 'shrink_to_fit': True,
          'blend': 'normal', 'protected': []}
ANIMATED = True
DEFAULT_LEN = 2.2


_cache = {}


def _layout(ctx, words, font, size, max_w):
    """Lines of (index, text, width) wrapped to max_w pixels, plus the space width (same for every frame)."""
    peak = float(ctx.p.get('pop_scale', 1.15)) if ctx.p.get('style', 'pop') == 'pop' else (
        1.08 if ctx.p.get('style') == 'karaoke' else 1.0)
    grow = 1 + (peak - 1) * 0.4   # room for a word growing from its centre; the space between words takes the rest
    key = (tuple(w[0] for w in words), repr(font), size, round(max_w), ctx.w, ctx.h, grow)
    if key not in _cache:
        if len(_cache) > 512:
            _cache.clear()
        _cache[key] = _measure_layout(ctx, words, font, size, max_w, grow)
    return _cache[key]


def _measure_layout(ctx, words, font, size, max_w, grow=1.0):
    f = ctx.font(font, size)
    space = max(f.getlength(' '), ctx.s(size) * 0.26)
    lines, line, lw = [], [], 0.0
    for i, (text, _, _) in enumerate(words):
        w = ctx.measure(text, font, size)[0] * grow   # room for the word to grow while it is said
        add = w if not line else lw + space + w
        if line and add > max_w:
            lines.append((line, lw))
            line, lw = [(i, text, w)], w
        else:
            line.append((i, text, w))
            lw = add
    if line:
        lines.append((line, lw))
    if 1 < len(lines) <= 3:
        lines = _balanced(lines, space, max_w)
    return lines, space


def _balanced(lines, space, max_w):
    """The same number of lines, broken so the widest is as narrow as it can be (no lone word left on the last line)."""
    items = [x for line, _ in lines for x in line]
    n, k = len(items), len(lines)

    def width(a, b):
        return sum(x[2] for x in items[a:b]) + space * (b - a - 1)
    best = None
    cuts = [(c,) for c in range(1, n)] if k == 2 else [(c, d) for c in range(1, n) for d in range(c + 1, n)]
    for cut in cuts:
        bounds = (0,) + cut + (n,)
        widths = [width(bounds[i], bounds[i + 1]) for i in range(k)]
        if max(widths) > max_w:
            continue
        if best is None or max(widths) < best[0]:
            best = (max(widths), bounds, widths)
    if best is None:
        return lines
    _, bounds, widths = best
    return [(items[bounds[i]:bounds[i + 1]], widths[i]) for i in range(k)]


# The caption fades over its last moments. Chunks follow each other 0.03 s apart, so a long fade made the last
# fifth of a short chunk a dim ghost (a 1 s sample caught 'allow our' half faded); 0.05 s is under two frames at 30 fps.
FADE_OUT_S = 0.05
# The captions op and caption fit both use a 0.15 s hold after the last word.
MIN_WORD_HOLD_S = 0.15


def _timing(ctx, words):
    """The spoken word, whether all words must now be visible, and the caption's opacity."""
    t = ctx.t
    starts = [float(w[1]) for w in words]
    current = max((i for i, start in enumerate(starts) if start <= t), default=-1)
    if ctx.p.get('_legacy_word_fade'):
        return current, False, ctx.anim_out(FADE_OUT_S)
    fps = ctx.fps
    last_frame = max(0, round(ctx.len * fps) - 1)
    hold_frames = math.ceil(MIN_WORD_HOLD_S * fps)
    progressive = ctx.p.get('style', 'pop') in ('pop', 'typewriter')
    last_spoken = max(starts, default=0.0) if progressive else 0.0
    spoken_frame = math.ceil(last_spoken * fps)
    normal_end = math.floor((ctx.len - FADE_OUT_S) * fps + 1e-9)
    opaque_end = min(last_frame, max(normal_end, spoken_frame + hold_frames - 1))
    fade = ctx.anim_out(min(FADE_OUT_S, ctx.len - opaque_end / fps))
    # At a cut there may be no room to hold after speech. Show the late words in their resting style
    # as late as possible, then still animate them on their original spoken starts.
    reveal_all = max(0, opaque_end - hold_frames + 1) / fps <= t < last_spoken
    return current, reveal_all, fade


def frame_key(ctx):
    """Frames only differ while a word is animating or the caption fades out."""
    words = ctx.p['words']
    t = ctx.t
    current, reveal_all, fade = _timing(ctx, words)
    since = t - float(words[current][1]) if current >= 0 else 0.0
    moving = since < 0.4
    from kinetic_type import protected_regions
    active = tuple(index for index, region in enumerate(protected_regions(ctx.p))
                   if region.get('start', 0) <= t < region.get('end', 1e10))
    return (current, round(since * ctx.fps) if moving else -1, reveal_all, round(fade, 2), active)


def draw(ctx):
    p = ctx.p
    words = [[str(w[0]).upper() if p.get('uppercase') else str(w[0]), float(w[1]), float(w[2])] for w in p['words']]
    if not words:
        return
    style = p.get('style', 'pop')
    font, size = p.get('font', 'captions'), float(p.get('size', 84))
    if p.get('weight') is not None:
        font = {**ctx.kit.font(font), 'weight': p['weight']}
    max_w = ctx.w * float(p.get('max_width', 0.82))
    lines, space = _layout(ctx, words, font, size, max_w)
    widest = max(lw for _, lw in lines)
    if p.get('shrink_to_fit', True) and widest > max_w > 0:
        # a word wider than the line (it can't wrap) would run off the frame: the caption is set smaller instead
        size *= max_w / widest
        lines, space = _layout(ctx, words, font, size, max_w)
    line_h = ctx.s(size) * 1.22
    block_h = line_h * len(lines)
    pos = p.get('position', 'bottom')
    # the usual names for the thirds: where the middle of the caption block sits
    thirds = {'lower-third': 0.72, 'lower third': 0.72, 'lower_third': 0.72,
              'upper-third': 0.28, 'upper third': 0.28, 'upper_third': 0.28}
    if isinstance(pos, str) and pos.strip().lower() in thirds:
        pos = thirds[pos.strip().lower()]
    mid_x = ctx.w * float(p.get('center_x', 0.5))       # the lines' horizontal centre, as a share of the width
    my = ctx.h * float(p.get('margin_y', 0.12))
    try:
        # a number is where the middle of the caption block sits, as a share of the frame height (0.62 = a bit
        # below the middle)
        top = ctx.h * min(0.95, max(0.05, float(pos))) - block_h / 2
    except (TypeError, ValueError):
        if pos not in ('top', 'middle', 'center', 'bottom'):
            raise ValueError(f"caption position {pos!r}: use 'top', 'middle', 'bottom', 'lower-third', "
                             f"'upper-third' or a share of the frame height such as 0.62")
        top = my if pos == 'top' else (ctx.h - block_h) / 2 if pos in ('middle', 'center') else ctx.h - my - block_h
    from kinetic_type import glyph_blend, overlaps, protected_regions
    glyph_blend(p)
    bounds = [(mid_x - widest / 2) / ctx.w, top / ctx.h,
              (mid_x + widest / 2) / ctx.w, (top + block_h) / ctx.h]
    peak = max(1, float(p.get('pop_scale', 1.15))) if style == 'pop' else 1.08 if style == 'karaoke' else 1
    padding = (ctx.s(float(p.get('outline_width') or 0)) + max(widest, block_h) * (peak - 1) / 2
               + (ctx.s(size) * .22 if style == 'bounce' else 0)) / min(ctx.w, ctx.h)
    bounds = [bounds[0] - padding, bounds[1] - padding, bounds[2] + padding, bounds[3] + padding]
    for region in protected_regions(p):
        if region.get('start', 0) <= ctx.t < region.get('end', 1e10) and overlaps(bounds, region['box']):
            raise ValueError('word_captions: no face-safe placement; move the caption outside the protected box')
    current, reveal_all, fade = _timing(ctx, words)
    t = ctx.t
    lay = ctx.layer() if fade < 0.999 else ctx.canvas
    if p.get('box'):
        widest = max(lw for _, lw in lines)
        pad = ctx.s(18)
        ctx.rect((mid_x - widest / 2 - pad, top - pad * 0.6, mid_x + widest / 2 + pad, top + block_h + pad * 0.2),
                 fill=p['box'], radius=16, on=lay)
    for row, (line, lw) in enumerate(lines):
        x = mid_x - lw / 2
        cy = top + row * line_h + line_h / 2
        for i, text, w in line:
            start = words[i][1]
            cx = x + w / 2
            x += w + space
            said, now = start <= t, i == current
            fill, scale, dy = p.get('fill', 'light'), 1.0, 0.0
            if style in ('pop', 'typewriter'):
                if not said and not reveal_all:
                    continue
                if style == 'pop':
                    if now:
                        scale *= 1 + (float(p.get('pop_scale', 1.15)) - 1) * max(0.0, 1 - (t - start) / 0.35)
                        fill = p.get('highlight', fill)
            elif style in ('karaoke', 'highlight', 'bounce'):
                if now:
                    if style == 'karaoke':
                        fill, scale = p.get('highlight', fill), 1.08
                    elif style == 'highlight':
                        hw, hh = ctx.s(size) * 0.18, ctx.s(size) * 0.12
                        ctx.rect((cx - w / 2 - hw, cy - line_h * 0.42 - hh / 2, cx + w / 2 + hw, cy + line_h * 0.42),
                                 fill=p.get('highlight', 'accent'), radius=12, on=lay)
                    else:
                        dy = -ctx.s(size) * 0.22 * (1 - abs(1 - 2 * min(1.0, (t - start) / 0.3)))
                        fill = p.get('highlight', fill)
                elif not said and style == 'karaoke':
                    fill = p.get('fill', 'light')
            ctx.text((cx, cy + dy), text, font, size * scale, fill=fill, anchor='mm', outline=p.get('outline'),
                     outline_width=p.get('outline_width', 0), shadow=p.get('shadow'), on=lay)
    if lay is not ctx.canvas:
        ctx.paste(lay, opacity=fade)
