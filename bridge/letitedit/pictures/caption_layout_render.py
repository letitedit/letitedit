"""Fonts and measuring text, real renders with the export engine, and the word-caption template recorded.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import copy
import hashlib
import math
import re
import subprocess
from pathlib import Path
from letitedit.pictures.caption_layout_frame import (  # noqa: E402
    MELT, NO_WINDOW, _geom_text, _pad, _shift, _union, parse_geometry
)


# ============================================================================ fonts and native caption measurement

_FONTS = {}
_METRICS = {}


def _pil_font(path, idx, var, size):
    key = (path, idx, tuple(sorted((var or {}).items())), int(round(size)))
    f = _FONTS.get(key)
    if f is None:
        from PIL import ImageFont
        f = ImageFont.truetype(path, max(4, key[3]), index=idx)
        if var:
            try:
                import letitedit.catalogs.fonts as _fonts
                axes = f.get_variation_axes()
                tags = _fonts._axis_tags(path, idx)
                f.set_variation_by_axes([var.get(tags[i], a['default']) if i < len(tags) else a['default']
                                         for i, a in enumerate(axes)])
            except Exception:  # noqa: BLE001 - default instance
                pass
        if len(_FONTS) > 300:
            _FONTS.clear()
        _FONTS[key] = f
    return f


def _qt_vmetrics(path, idx):
    """(ascent, descent, line gap) per em as Qt on Windows reports them (OS/2 typo metrics when the font asks for
    them, else the Windows metrics; hhea line gap)."""
    key = (path, idx)
    if key not in _METRICS:
        try:
            from fontTools.ttLib import TTFont
            ft = TTFont(path, fontNumber=idx, lazy=True)
            upm = float(ft['head'].unitsPerEm)
            os2, hh = ft['OS/2'], ft['hhea']
            if os2.fsSelection & (1 << 7):
                asc, desc, gap = os2.sTypoAscender, -os2.sTypoDescender, os2.sTypoLineGap
            else:
                asc, desc, gap = os2.usWinAscent, os2.usWinDescent, max(0, hh.lineGap)
            _METRICS[key] = (asc / upm, desc / upm, gap / upm)
        except Exception:  # noqa: BLE001 - a font fontTools can't read: typical values
            _METRICS[key] = (0.93, 0.24, 0.0)
    return _METRICS[key]


def resolve_font(family, style=None, weight=None):
    """(path, index, variation, description) of the face Shotcut's text engine draws for a caption style: a weight
    in the family name ('Segoe UI Black') first, then a named style ('Bold'), then the weight property."""
    import letitedit.catalogs.fonts as fonts
    fam, w_name, it_name = fonts.parse_name(family)
    st = str(style or 'normal')
    italic = bool(it_name) or st[:1].lower() == 'i' or 'italic' in st.lower()
    try:
        weight = int(float(weight or 400))
    except ValueError:
        weight = 400
    if weight > 1000:
        weight = (weight - 10) // 10
    named = {s['style'].lower(): s for s in fonts.styles(fam)} if fonts.family(fam) else {}
    if w_name:
        weight = w_name
    elif st.lower() in named:
        weight, italic = named[st.lower()]['weight'], named[st.lower()]['italic']
    try:
        path, idx, var = fonts.font_file(fam, weight, italic)
    except KeyError:
        path, idx, var = fonts.font_file('Arial', weight, italic)
        fam = f'Arial (fallback for {family})'
    return path, idx, var, f'{fam} {weight}{" italic" if italic else ""}'


class QtText:
    """Predicts how MLT qtext lays a caption out: lines split only at newlines; the block (lines plus pad and half
    the outline on every side) placed in the geometry rect by halign/valign, and scaled down to fit when it is wider
    or taller than the rect. Widths come from Pillow with the same font file (corrected by melt measurement)."""

    def __init__(self, style, frame):
        self.style = style
        self.W, self.H = frame.width, frame.height
        self.size = max(4, int(round(float(style.get('size', 48)))))
        self.outline = max(0, int(float(style.get('outline', 0) or 0)))
        self.pad = max(0, int(float(style.get('pad', 0) or 0)))
        self.offset = self.pad + self.outline // 2
        self.path, self.idx, self.var, self.face = resolve_font(style.get('family', 'Sans'), style.get('style'),
                                                                style.get('weight'))
        self.font = _pil_font(self.path, self.idx, self.var, self.size)
        a, d, g = _qt_vmetrics(self.path, self.idx)
        self.ascent = round(a * self.size)
        self.descent = round(d * self.size)
        self.line_spacing = round(g * self.size) + self.ascent + self.descent
        self.space = self.font.getlength(' ')
        sh = style.get('shadow') if isinstance(style.get('shadow'), dict) else None
        self.shadow = (float(sh.get('x', 0)), float(sh.get('y', 0))) if sh else (0.0, 0.0)
        bg = str(style.get('bgcolour') or '#00000000')
        self.box_visible = len(bg) == 9 and bg[1:3].lower() != '00'
        self.halign = str(style.get('halign') or 'left')[:1].lower()
        self.valign = str(style.get('valign') or 'top')[:1].lower()
        self.width_scale = 1.0          # melt-measured / predicted widths (calibrate())
        self._ink = {}

    def variant(self, **kw):
        m = copy.copy(self)
        for k, v in kw.items():
            setattr(m, k, v)
        m.offset = m.pad + m.outline // 2
        return m

    def ink(self, text):
        """Ink box of text (no outline) relative to its pen position on the baseline."""
        if text not in self._ink:
            if not text.strip():
                self._ink[text] = None
            else:
                im, off = self.font.getmask2(text, mode='L', anchor='ls')
                bb = im.getbbox()
                self._ink[text] = None if bb is None else (bb[0] + off[0], bb[1] + off[1], bb[2] + off[0], bb[3] + off[1])
        return self._ink[text]

    def advance(self, text):
        return self.font.getlength(text) * self.width_scale

    def line_width(self, line):
        """qtext's width of a line: its advance, plus the first glyph's overhang on the left and the last glyph's on
        the right."""
        if not line:
            return 0.0
        w = self.advance(line)
        first, last = self.ink(line[0]), self.ink(line[-1])
        if first and first[0] < 0:
            w -= first[0]
        if last:
            over = last[2] - self.font.getlength(line[-1])
            if over > 0:
                w += over
        return w

    def space_width(self):
        return self.space * self.width_scale

    def max_line_width(self, rect_w):
        """The widest line that fits a rect rect_w wide without being shrunk (3% kept for measurement error)."""
        return rect_w * 0.97 - 2 * self.offset

    def block(self, lines, rect):
        """Where a cue's lines land in rect (x, y, w, h): {'scale' (< 1: qtext shrinks the cue to fit), 'ink',
        'words': [[(token, box), ...] per line], 'path': (w, h), 'eff_size'}."""
        widths = [self.line_width(l) for l in lines]
        width = max(widths) if widths else 0.0
        pw = width + 2 * self.offset
        ph = self.line_spacing * len(lines) + 2 * self.offset + 2
        rx, ry, rw, rh = rect
        s = 1.0
        if pw > rw:
            s *= rw / pw
        if ph * s > rh:
            s *= rh / (ph * s)
        dx = rx + {'c': (rw - s * pw) / 2, 'r': rw - s * pw}.get(self.halign, 0.0)
        dy = ry + {'m': (rh - s * ph) / 2, 'b': rh - s * ph}.get(self.valign, 0.0)
        half = self.outline / 2.0
        words, inks = [], []
        y = self.ascent + self.offset
        for line, lw in zip(lines, widths):
            x = self.offset
            first = self.ink(line[0]) if line else None
            if first and first[0] < 0:
                x -= first[0]
            x += {'c': (width - lw) / 2, 'r': width - lw}.get(self.halign, 0.0)
            row = []
            for m in re.finditer(r'\S+', line):
                bb = self.ink(m.group(0))
                if not bb:
                    continue
                px = x + self.advance(line[:m.start()])
                box = (dx + s * (px + bb[0] - half), dy + s * (y + bb[1] - half),
                       dx + s * (px + bb[2] + half), dy + s * (y + bb[3] + half))
                row.append((m.group(0), box))
                inks.append(box)
            words.append(row)
            y += self.line_spacing
        ink = _union(inks)
        if ink and (self.shadow[0] or self.shadow[1]):
            ink = _union([ink, _shift(ink, self.shadow[0], self.shadow[1])])
        if self.box_visible:
            ink = _union([ink, (dx, dy, dx + s * pw, dy + s * ph)])
        return {'scale': s, 'ink': ink, 'words': words, 'path': (pw, ph), 'eff_size': self.size * s}

    def gaps(self, block):
        """[(left word, right word, gap px)] between neighbouring words of each line (ink with outline; a shadow
        falling to the right narrows the gap)."""
        out = []
        for row in block['words']:
            for (ta, a), (tb, b) in zip(row, row[1:]):
                out.append((ta, tb, b[0] - (a[2] + max(0.0, self.shadow[0]) * block['scale'])))
        return out


# ============================================================================ melt: real renders

def _esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _srt_ms(ms):
    ms = int(round(ms))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def _mlt_rgba(c):
    """'#AARRGGBB' (MLT), '#RRGGBB' or '0xRRGGBBAA' -> (r, g, b, a)."""
    c = str(c or '').strip()
    try:
        if c.startswith('#') and len(c) == 9:
            return int(c[3:5], 16), int(c[5:7], 16), int(c[7:9], 16), int(c[1:3], 16)
        if c.startswith('#') and len(c) == 7:
            return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), 255
        if c.lower().startswith('0x') and len(c) == 10:
            return int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16), int(c[8:10], 16)
    except ValueError:
        pass
    return 255, 255, 255, 255


def _css(mlt):
    r, g, b, a = _mlt_rgba(mlt)
    return f'#{r:02X}{g:02X}{b:02X}{a:02X}'


def _background_for(colours):
    """A flat colour far from every colour the text uses, so its ink can be told apart."""
    cands = [(255, 0, 255), (0, 255, 0), (0, 0, 255), (128, 128, 128), (255, 128, 0)]
    cols = [_mlt_rgba(c)[:3] for c in colours if c and _mlt_rgba(c)[3] > 0]
    return max(cands, key=lambda bg: min([sum(abs(a - b) for a, b in zip(bg, col)) for col in cols] or [999]))


def _run(args, timeout=600):
    """Run a program; a melt run holds the PC render lock, one at a time in this process, on the export's thread cap at
    below-normal priority (render_lock.run_render)."""
    import letitedit.core.render_lock as render_lock
    r = render_lock.run_render([str(a) for a in args], capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f'{Path(str(args[0])).name} failed ({r.returncode}): {(r.stderr or r.stdout)[-800:]}')
    return r


CAPTION_RENDER_KEYS = ('family', 'size', 'weight', 'style', 'fgcolour', 'olcolour', 'outline', 'bgcolour', 'pad',
                       'halign', 'valign', 'opacity')


def melt_text_blocks(style, items, frame, work):
    """Render caption texts with Shotcut's own subtitle burn-in (melt, the export engine): items = [(text, geometry)],
    one frame each over a flat colour. Returns [{'ink': box or None, 'mask': bool array of the box}] in order. The
    track's shadow copy (style['shadow'] = {fgcolour, x, y}) is drawn too. With caption_fit_reuse on (T362,
    caption_reuse), a block already measured for the same text, place, style, frame size, font file and text engine
    is read back instead (each frame shows one block alone, so the rest render as before)."""
    import letitedit.pictures.caption_reuse as caption_reuse
    if not items or not caption_reuse.enabled():
        return _render_text_blocks(style, items, frame, work)
    memo = {}
    try:
        keys = [caption_reuse.block_key(style, text, geom, frame, memo) for text, geom in items]
    except Exception:  # noqa: BLE001 - no keys: every block rendered, as before
        return _render_text_blocks(style, items, frame, work)
    out = [caption_reuse.read_block(k) for k in keys]
    todo = [i for i, b in enumerate(out) if b is None]
    if todo:
        for i, block in zip(todo, _render_text_blocks(style, [items[i] for i in todo], frame, work)):
            out[i] = block
            caption_reuse.write_block(keys[i], block)
    return out


def _render_text_blocks(style, items, frame, work):
    import numpy as np
    from PIL import Image
    if not items:
        return []
    W, H = frame.width, frame.height
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    for f in work.glob('t_*.png'):
        f.unlink()
    shadow = style.get('shadow') if isinstance(style.get('shadow'), dict) else None
    bg = _background_for([style.get('fgcolour'), style.get('olcolour'), style.get('bgcolour'),
                          shadow.get('fgcolour') if shadow else None])
    groups = {}
    for k, (text, geom) in enumerate(items):
        groups.setdefault(geom, []).append((k, text))
    filters = []
    for geom, cues in groups.items():
        srt = '\n\n'.join(f'{n + 1}\n{_srt_ms(k * 100)} --> {_srt_ms(k * 100 + 100)}\n{text}'
                          for n, (k, text) in enumerate(cues)) + '\n'
        base = {k: style[k] for k in CAPTION_RENDER_KEYS if style.get(k) not in (None, '')}
        layers = []
        if shadow:
            x, y, w, h = parse_geometry(geom, W, H)
            spread = {}
            if shadow.get('spread'):      # a soft halo: the text's outline plus the spread
                spread = {'outline': round(float(base.get('outline') or 0) + float(shadow['spread']))}
            layers.append({**base, 'fgcolour': shadow.get('fgcolour', '#ff000000'),
                           'olcolour': shadow.get('fgcolour', '#ff000000'), **spread,
                           'geometry': _geom_text(x + float(shadow.get('x', 0)), y + float(shadow.get('y', 0)), w, h)})
        layers.append({**base, 'geometry': geom})
        for props in layers:
            p = ''.join(f'<property name="{_esc(k)}">{_esc(v)}</property>' for k, v in props.items())
            filters.append(f'<filter><property name="mlt_service">subtitle</property>'
                           f'<property name="text">{_esc(srt)}</property>{p}</filter>')
    n = len(items)
    hexbg = '0x{:02x}{:02x}{:02x}ff'.format(*bg)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C">\n'
           f'<profile width="{W}" height="{H}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
           f'display_aspect_num="{W}" display_aspect_den="{H}" frame_rate_num="10" frame_rate_den="1" '
           f'colorspace="709"/>\n'
           f'<producer id="bg" in="0" out="{n - 1}"><property name="length">{n}</property>'
           f'<property name="mlt_service">color</property><property name="resource">{hexbg}</property>\n'
           + '\n'.join(filters) + f'\n</producer>\n<playlist id="pl"><entry producer="bg" in="0" out="{n - 1}"/>'
           f'</playlist>\n</mlt>\n')
    doc = work / 'blocks.mlt'
    doc.write_text(xml, encoding='utf-8')
    _run([MELT, '-quiet', doc, '-consumer', f'avformat:{work / "t_%05d.png"}', 'vcodec=png', 'an=1', 'audio_off=1'],
         timeout=120 + 2 * n)
    pngs = sorted(work.glob('t_*.png'))
    if len(pngs) < n:
        raise RuntimeError(f'melt rendered {len(pngs)} of {n} caption blocks')
    out = []
    ref = np.array(bg, dtype=np.int16)
    for png in pngs[:n]:
        with Image.open(png) as im:
            a = np.asarray(im.convert('RGB'), dtype=np.int16)
        m = np.abs(a - ref).max(axis=2) > 48
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            out.append({'ink': None, 'mask': None})
            continue
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        out.append({'ink': box, 'mask': m[box[1]:box[3], box[0]:box[2]]})
    return out


def column_gaps(mask, box, predicted_rows):
    """Measured gaps between words of a rendered caption: for each predicted (left word, right word) pair, the widest
    run of empty columns in that line's band near the predicted gap. mask/box: the rendered ink and where it sits;
    predicted_rows: [[(token, box), ...] per line] in frame coordinates. Returns [(a, b, gap px)]."""
    out = []
    if mask is None:
        return out
    x0, y0 = box[0], box[1]
    for row in predicted_rows:
        if len(row) < 2:
            continue
        ry0 = max(0, int(min(b[1] for _, b in row)) - y0)
        ry1 = min(mask.shape[0], int(math.ceil(max(b[3] for _, b in row))) - y0)
        if ry1 <= ry0:
            continue
        # above the baseline: descenders that lean toward the next word ('my job') don't make words read as one;
        # outlines that meet anywhere above it do (capitals included: 'it Without')
        h = ry1 - ry0
        cols = mask[ry0:ry0 + max(1, int(0.8 * h))].any(axis=0)
        for (ta, a), (tb, b) in zip(row, row[1:]):
            centre = (a[2] + b[0]) / 2 - x0
            reach = max(4.0, abs(b[0] - a[2]) / 2 + 0.2 * (a[3] - a[1]))
            lo, hi = int(max(0, centre - reach)), int(min(len(cols), centre + reach + 1))
            best = run = 0
            for c in range(lo, hi):
                run = run + 1 if not cols[c] else 0
                best = max(best, run)
            out.append((ta, tb, float(best)))
    return out


def _profile_xml(profile, width, height):
    g = math.gcd(width, height)
    return (f'<profile width="{width}" height="{height}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
            f'display_aspect_num="{width // g}" display_aspect_den="{height // g}" '
            f'frame_rate_num="{profile["frame_rate_num"]}" frame_rate_den="{profile["frame_rate_den"]}" '
            f'colorspace="{profile.get("colorspace", "709")}"/>')


def render_frames(project, profile, frames, out_dir, prefix='f'):
    """Exact frames of a project rendered by melt at the project's own size (a consumer-side smaller size
    letterboxes the picture, so positions would not map back). Returns PNG paths in order."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob(f'{prefix}_*.png'):
        f.unlink()
    if not frames:
        return []
    W, H = int(profile['width']), int(profile['height'])
    entries = '\n'.join(f'    <entry producer="cut" in="{int(f)}" out="{int(f)}"/>' for f in frames)
    wrapper = out_dir / f'{prefix}.mlt'
    wrapper.write_text('<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C">\n  ' + _profile_xml(profile, W, H)
                       + f'\n  <producer id="cut"><property name="resource">{_esc(str(Path(project).resolve()))}'
                         '</property><property name="mlt_service">xml</property></producer>\n'
                       f'  <playlist id="sheet">\n{entries}\n  </playlist>\n</mlt>\n', encoding='utf-8')
    _run([MELT, '-quiet', wrapper, '-consumer', f'avformat:{out_dir / (prefix + "_%05d.png")}', 'vcodec=png', 'an=1',
          'audio_off=1'], timeout=180 + 8 * len(frames))
    pngs = sorted(out_dir.glob(f'{prefix}_*.png'))
    if len(pngs) < len(frames):
        raise RuntimeError(f'melt rendered {len(pngs)} of {len(frames)} frames')
    return pngs[:len(frames)]


# ============================================================================ word captions: the template, recorded

_RECORDER = {}


def _band_extent(im, off, xy, anchor, font, box):
    """(x0, x1) of a word's ink (outline included) above the baseline: where two neighbouring words must stay
    apart to read as two. Descenders that lean toward the next word ('my job') don't count; capitals and ascenders
    do ('it Without' touch at the top of the W). None when it can't be measured (the full box is used then)."""
    if box is None:
        return None
    try:
        import numpy as np
        from PIL import Image
        arr = np.asarray(Image.Image()._new(im)) > 24
        asc, desc = font.getmetrics()
        v = anchor[1:2] or 'a'
        base = {'m': xy[1] + (asc - desc) / 2, 's': xy[1], 'a': xy[1] + asc, 'd': xy[1] - desc,
                't': xy[1] + asc, 'b': xy[1] - desc}.get(v, xy[1] + asc)
        top = xy[1] + off[1]
        r1 = int(round(base + 0.04 * font.size - top))
        rows = arr[:max(0, min(arr.shape[0], r1))]
        cols = np.nonzero(rows.any(axis=0))[0] if rows.size else []
        if len(cols) == 0:
            return None
        return (xy[0] + off[0] + float(cols[0]), xy[0] + off[0] + float(cols[-1]) + 1)
    except Exception:  # noqa: BLE001
        return None


def _recorder_class():
    """A graphics.Ctx that records instead of drawing: each word's ink box (outline included, at the size it is drawn
    in that frame), its shadow, and any box/highlight rectangle."""
    if 'cls' in _RECORDER:
        return _RECORDER['cls']
    import letitedit.pictures.graphics as graphics
    from PIL import Image
    blank = Image.new('RGBA', (1, 1))

    class Recorder(graphics.Ctx):
        def __init__(self, W, H, fps, length, t, frame, params, kit):
            super().__init__(1, 1, fps, length, t, frame, params, kit)
            self.w, self.h, self.scale = W, H, H / 1080.0
            self.canvas = blank
            self.log = []

        def layer(self):
            return blank

        def paste(self, *a, **k):
            return None

        def rect(self, box, fill=None, radius=0, outline=None, width=0, on=None):
            self.log.append(('rect', tuple(float(v) for v in box)))

        def text(self, xy, text, font_ref='body', size=54, fill='light', anchor='la', align='left', outline=None,
                 outline_width=0, shadow=None, shadow_offset=(4, 5), shadow_blur=0, opacity=1.0, on=None):
            f = self.font(font_ref, size)
            sw = int(round(self.s(outline_width))) if outline else 0
            im, off = f.getmask2(str(text), mode='L', anchor=anchor, stroke_width=sw)
            bb = im.getbbox()
            box = None if bb is None else (xy[0] + off[0] + bb[0], xy[1] + off[1] + bb[1],
                                           xy[0] + off[0] + bb[2], xy[1] + off[1] + bb[3])
            sh = None
            if shadow and box:
                pad = 3 * self.s(shadow_blur) + 4 if shadow_blur else 0
                sh = _pad(_shift(box, self.s(shadow_offset[0]), self.s(shadow_offset[1])), pad)
            band = _band_extent(im, off, xy, anchor, f, box)
            self.log.append(('text', str(text), float(size), box, sh, (float(xy[0]), float(xy[1])), band))
            return box or (xy[0], xy[1], xy[0], xy[1])
    _RECORDER['cls'] = Recorder
    return Recorder


class WordCaptions:
    """Measures word_captions graphics exactly as the template draws them (the template module of the project's
    style pack, else the built-in one)."""

    def __init__(self, kit, frame):
        import letitedit.pictures.graphics as graphics
        self.kit, self.frame = kit, frame
        self.mod = graphics._resolve_template({'template': 'word_captions'}, kit)
        src = getattr(self.mod, '__file__', None)
        self.src_hash = hashlib.sha1(Path(src).read_bytes()).hexdigest()[:12] if src else ''
        self.defaults = dict(getattr(self.mod, 'PARAMS', {}))

    def normalise(self, params, length):
        import letitedit.pictures.graphics as graphics
        return graphics.normalise({'template': 'word_captions', 'params': params, 'len': length}, self.kit)['params']

    def ctx(self, params, length, t=0.0, i=0):
        F = self.frame
        return _recorder_class()(F.width, F.height, F.fps, length, t, i, params, self.kit)

    def geometry(self, params, length):
        """{size (1080p units, after shrink-to-fit), lines [[word index...]], block_h, top, line_h} as draw() lays the
        caption out (the template's own _layout and shrink-to-fit)."""
        p = params
        words = [[str(w[0]).upper() if p.get('uppercase') else str(w[0]), float(w[1]), float(w[2])] for w in p['words']]
        c = self.ctx(p, length)
        font, size = p.get('font', 'captions'), float(p.get('size', 84))
        max_w = c.w * float(p.get('max_width', 0.82))
        lines, space = self.mod._layout(c, words, font, size, max_w)
        widest = max(lw for _, lw in lines) if lines else 0
        if p.get('shrink_to_fit', True) and widest > max_w > 0:
            size *= max_w / widest
            lines, space = self.mod._layout(c, words, font, size, max_w)
        line_h = c.s(size) * 1.22
        block_h = line_h * len(lines)
        pos = p.get('position', 'bottom')
        thirds = {'lower-third': 0.72, 'lower third': 0.72, 'lower_third': 0.72, 'upper-third': 0.28,
                  'upper third': 0.28, 'upper_third': 0.28}
        if isinstance(pos, str) and pos.strip().lower() in thirds:
            pos = thirds[pos.strip().lower()]
        my = c.h * float(p.get('margin_y', 0.12))
        try:
            top = c.h * min(0.95, max(0.05, float(pos))) - block_h / 2
        except (TypeError, ValueError):
            top = my if pos == 'top' else (c.h - block_h) / 2 if pos in ('middle', 'center') else c.h - my - block_h
        return {'size': size, 'lines': [[i for i, _, _ in line] for line, _ in lines], 'block_h': block_h, 'top': top,
                'line_h': line_h}

    def risk_frames(self, params, length):
        """Frames where the picture can change: each word's first 0.42 s (pop, bounce, highlight), the first and
        last frames and the middle."""
        fps = self.frame.fps
        n = max(1, int(round(length * fps)))
        idx = {0, n - 1, n // 2}
        for w in params['words']:
            a = int(math.floor(float(w[1]) * fps))
            for k in range(a, a + int(math.ceil(0.42 * fps)) + 1):
                if 0 <= k < n:
                    idx.add(k)
        return sorted(idx)

    def record(self, params, length, frames=None):
        """Every word's box at each risk frame: {'frames': [(t, [(index, text, size, box, shadow, y)], rects)],
        'ink' (union over the frames: peaks included), 'rest' (last frame), 'gaps': [(t, i, j, gap px)],
        ...geometry()}."""
        fps = self.frame.fps
        geo = self.geometry(params, length)
        row_of = {i: r for r, line in enumerate(geo['lines']) for i in line}
        texts = [str(w[0]).upper() if params.get('uppercase') else str(w[0]) for w in params['words']]
        out_frames, inks, gaps = [], [], []
        for k in (frames if frames is not None else self.risk_frames(params, length)):
            t = k / fps
            c = self.ctx(params, length, t, k)
            self.mod.draw(c)
            placed, used = [], set()
            for entry in c.log:
                if entry[0] != 'text':
                    continue
                _, text, size, box, sh, xy, band = entry
                idx = next((i for i, tx in enumerate(texts) if tx == text and i not in used), None)
                if idx is None:
                    continue
                used.add(idx)
                placed.append((idx, text, size, box, sh, xy[1], band))
            rects = [e[1] for e in c.log if e[0] == 'rect']
            boxes = [p[3] for p in placed if p[3]] + [p[4] for p in placed if p[4]] + rects
            if boxes:
                inks.append(_union(boxes))
            byrow = {}
            for p in placed:
                byrow.setdefault(row_of.get(p[0], 0), []).append(p)
            for ws in byrow.values():
                ws.sort(key=lambda p: p[0])
                for a, b in zip(ws, ws[1:]):
                    if a[3] and b[3] and b[0] == a[0] + 1:
                        ra = a[6][1] if a[6] else a[3][2]
                        lb = b[6][0] if b[6] else b[3][0]
                        if a[4]:                     # a shadow falling to the right narrows the gap
                            ra += max(0.0, a[4][2] - a[3][2])
                        gaps.append((t, a[0], b[0], lb - ra))
            for rb in rects:              # a highlight box reaching into the next word fuses them just the same
                for p in placed:
                    if p[3] and not (rb[0] <= p[3][0] and rb[2] >= p[3][2]):
                        ov = min(rb[2], p[3][2]) - max(rb[0], p[3][0])
                        if ov > 2 and min(rb[3], p[3][3]) - max(rb[1], p[3][1]) > 2:
                            gaps.append((t, -1, p[0], -ov))
            out_frames.append((t, placed, rects))
        rest = _union([p[3] for p in out_frames[-1][1] if p[3]]) if out_frames else None
        return {**geo, 'frames': out_frames, 'ink': _union(inks), 'rest': rest, 'gaps': gaps, 'texts': texts}

    def slim(self, params):
        """Params without the template's own defaults (what an inserted item needs to say)."""
        return {k: v for k, v in params.items() if v is not None and (k == 'words' or k not in self.defaults
                                                                       or self.defaults[k] != v)}
