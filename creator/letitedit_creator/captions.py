"""Animated word-by-word captions ("TikTok / MrBeast style").

Each phrase is rendered as its own short transparent clip so the user can delete or nudge a single
caption on the 'AI Captions' track.
Styles: pop (words appear as spoken, active word pops + colour), highlight (whole phrase visible,
active word on a coloured box), karaoke (phrase visible, spoken words fill with colour).
"""

import re
from pathlib import Path

from PIL import Image

from . import common, graphics as g
from .overlay import OverlayWriter

STYLES = ("pop", "highlight", "karaoke")


def group_phrases(words, max_words=3, max_gap=0.55, max_chars=22):
    phrases, cur = [], []
    for w in words:
        if w.get("skip"):
            continue
        if cur:
            gap = w["start"] - cur[-1]["end"]
            chars = sum(len(x["text"]) + 1 for x in cur) + len(w["text"])
            if gap > max_gap or len(cur) >= max_words or chars > max_chars or re.search(r"[.!?]$", cur[-1]["text"]):
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return phrases


def _clean(text, upper, strip_punct):
    t = text.strip()
    if strip_punct:
        t = re.sub(r"[.,!?;:]+$", "", t)
    return t.upper() if upper else t


def render(words, out_dir, fps, width, height, style="pop", position_y=None, font_scale=1.0,
           text_color="white", active_color="yellow", box_color="orange", upper=True,
           strip_punct=True, max_words=None, drop_fillers=True, min_hold=0.35):
    """Render phrase clips; returns [{'start','end','path','text','frames'}] (seconds)."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    vertical = height > width
    max_words = max_words or (3 if vertical else 5)
    usable = [w for w in words if not (drop_fillers and w.get("filler"))]
    phrases = group_phrases(usable, max_words=max_words, max_chars=22 if vertical else 36)
    size = int((width * 0.074 if vertical else height * 0.068) * font_scale)
    fnt = g.font(size, "black")
    stroke = max(3, size // 9)
    cy = (position_y if position_y is not None else (0.68 if vertical else 0.82)) * height
    max_w = width * 0.86
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fill, active, box = g.color(text_color), g.color(active_color), g.color(box_color)
    results = []
    for pi, phrase in enumerate(phrases):
        start = phrase[0]["start"]
        nxt = phrases[pi + 1][0]["start"] if pi + 1 < len(phrases) else phrase[-1]["end"] + 0.6
        end = min(max(phrase[-1]["end"] + 0.12, start + min_hold), max(nxt - 0.02, start + 0.1))
        frames = max(1, int(round((end - start) * fps)))
        tokens = [_clean(w["text"], upper, strip_punct) for w in phrase]
        space = g.text_size(" ", fnt)[0] + size * 0.12
        line_h = size * 1.18
        # layout uses true glyph widths (word images carry outline/shadow padding)
        gw = [g.text_size(t, fnt, stroke)[0] for t in tokens]
        lines, cur, cur_w = [], [], 0.0
        for i, wdt in enumerate(gw):
            add = wdt + (space if cur else 0)
            if cur and cur_w + add > max_w:
                lines.append(cur)
                cur, cur_w = [], 0.0
                add = wdt
            cur.append(i)
            cur_w += add
        if cur:
            lines.append(cur)
        # pre-render each word in its two looks
        plain = [g.text_image(t, fnt, fill, stroke=stroke, shadow=max(2, size // 18)) for t in tokens]
        hot = [g.text_image(t, fnt, active, stroke=stroke, shadow=max(2, size // 18)) for t in tokens]
        path = out_dir / f"cap_{pi:04d}.mov"
        with OverlayWriter(path, width, height, fps) as wr:
            for f in range(frames):
                t = start + f / fps
                canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                total_h = line_h * len(lines)
                for li, line in enumerate(lines):
                    lw = sum(gw[i] for i in line) + space * (len(line) - 1)
                    x = width / 2 - lw / 2
                    y = cy - total_h / 2 + li * line_h + line_h / 2
                    for i in line:
                        w = phrase[i]
                        spoken = t >= w["start"] - 0.02
                        is_active = w["start"] - 0.02 <= t < (phrase[i + 1]["start"] if i + 1 < len(phrase) else end)
                        img = plain[i]
                        scale = 1.0
                        opacity = 1.0
                        if style == "pop":
                            if not spoken:
                                x += gw[i] + space
                                continue
                            age = t - w["start"]
                            scale = 0.6 + 0.65 * g.ease_out_back(age / 0.14, 3.0) - 0.25 * g.clamp01((age - 0.14) / 0.1)
                            img = hot[i] if is_active else plain[i]
                        elif style == "highlight":
                            if is_active:
                                pad = size * 0.18
                                bw, bh = gw[i] + pad * 2, size * 1.25
                                canvas.alpha_composite(g.rounded_rect((int(bw), int(bh)), int(size * 0.22), box),
                                                       (int(x + gw[i] / 2 - bw / 2), int(y - bh / 2)))
                                age = t - w["start"]
                                scale = 1.0 + 0.08 * (1 - g.clamp01(age / 0.12))
                        elif style == "karaoke":
                            img = hot[i] if spoken else plain[i]
                        g.paste_center(canvas, g.scaled(img, max(scale, 0.05)), x + gw[i] / 2, y, opacity)
                        x += gw[i] + space
                wr.write(canvas)
        results.append({"start": round(start, 3), "end": round(start + frames / fps, 3), "frames": frames,
                        "path": str(path), "text": " ".join(tokens)})
    return results


class _IndexFont:
    """Adapter so graphics.wrap_words can wrap word indices using the real token widths."""

    def __init__(self, fnt, tokens, stroke):
        self.fnt, self.tokens, self.stroke = fnt, tokens, stroke

    def getbbox(self, text, stroke_width=0):
        idx = [int(i) for i in text.split()]
        return self.fnt.getbbox(" ".join(self.tokens[i] for i in idx), stroke_width=self.stroke)


def preview_sheet(results, out_path, fps, count=6):
    """Contact sheet: a mid-phrase frame from several caption clips."""
    from .overlay import filmstrip
    picks = results[:: max(1, len(results) // count)][:count] or results[:1]
    tmp = common.WORK / f"capsheet-{common.stamp()}"
    tmp.mkdir(parents=True, exist_ok=True)
    sheets = [filmstrip(r["path"], tmp / f"{k}.png", count=1, width=270) for k, r in enumerate(picks)]
    imgs = [Image.open(s) for s in sheets]
    w = sum(i.width for i in imgs)
    h = max(i.height for i in imgs)
    sheet = Image.new("RGB", (w, h), (20, 20, 20))
    x = 0
    for i in imgs:
        sheet.paste(i, (x, 0))
        x += i.width
    sheet.save(out_path)
    return Path(out_path)
