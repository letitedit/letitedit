"""The strips drawn.

Part of `music_sync` (letitedit/timing/music_sync.py), which imports every name here back,
so `music_sync.X` is the same object it always was.
"""
from __future__ import annotations
import math
import time
import uuid
from letitedit.timing.music_sync_base import (  # noqa: E402
    CACHE_ROOT, _clock
)


# ============================================================================ drawing

COL = {'bg': (250, 250, 248), 'ink': (25, 25, 30), 'mute': (120, 120, 128), 'grid': (215, 215, 220),
       'beat': (175, 175, 185), 'down': (60, 60, 75), 'phrase': (200, 120, 0), 'cut': (210, 30, 40),
       'motion_peak': (235, 130, 20), 'visual_beat': (130, 60, 190), 'text_pop': (20, 140, 70),
       'sfx': (25, 100, 200), 'speech': (190, 215, 245), 'music': (255, 235, 190), 'story': (90, 90, 90),
       'on': (20, 150, 60), 'off': (210, 30, 40)}
KIND_COL = {'cuts': COL['cut'], 'motion_peaks': COL['motion_peak'], 'visual_beats': COL['visual_beat'],
            'text_pops': COL['text_pop'], 'sfx': COL['sfx'], 'caption_pops': (110, 110, 110)}
KIND_LABEL = {'cuts': 'cuts', 'motion_peaks': 'motion peaks', 'visual_beats': 'visual beats', 'text_pops': 'text pops',
              'sfx': 'SFX onsets', 'caption_pops': 'captions'}
DEFAULT_KINDS = ('cuts', 'motion_peaks', 'visual_beats', 'text_pops', 'sfx')


def font(px, bold=False):
    from PIL import ImageFont
    for name in (('arialbd.ttf', 'segoeuib.ttf') if bold else ('arial.ttf', 'segoeui.ttf')):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _out_dir(kind):
    d = CACHE_ROOT / 'timing' / 'views' / kind / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fmt_off(v):
    """Frames with one decimal under 3 (where on/off the beat is decided), whole frames beyond."""
    if v is None:
        return '?'
    v = float(v)
    if abs(v) < 3:
        r = round(v, 1)
        return '0' if r == 0 else f'{r:+.1f}'
    return f'{round(v):+d}'


def draw_overview(path, title, summaries, mono, music_info, kinds, events_measured, labels=None, caution=None):
    """Page 1: the numbers and the offset histograms (frames from the nearest beat) per kind of event."""
    from PIL import Image, ImageDraw
    labels = labels or KIND_LABEL
    W = 1600
    rows = [k for k in kinds if summaries.get(k, {}).get('n_with_music')]
    H = 330 + 230 * max(1, len(rows))
    img = Image.new('RGB', (W, H), COL['bg'])
    d = ImageDraw.Draw(img)
    f_t, f_b, f_s = font(30, True), font(22), font(18)
    d.text((24, 16), title, fill=COL['ink'], font=f_t)
    y = 60
    for line in music_info:
        d.text((24, y), line, fill=COL['ink'], font=f_b)
        y += 30
    if caution:
        d.text((24, y), caution, fill=(200, 110, 0), font=font(22, True))
        y += 30
    y += 8
    if mono and mono.get('cuts_with_music'):
        txt = (f"cuts on the beat (<= {mono['threshold_on_beat_frames']:g} frame): {round(100 * mono['share_on_beat'])}%"
               f"   longest run of on-beat cuts: {mono['longest_on_beat_run']}"
               f"   on the downbeat: {round(100 * mono.get('share_on_downbeat', 0))}%")
        if mono.get('shot_lengths_beats'):
            sl = mono['shot_lengths_beats']
            txt += f"   shot length median {sl['median']} beats (cv {sl['cv']})"
        d.text((24, y), txt, fill=COL['ink'], font=f_b)
        y += 34
    if not rows:
        d.text((24, y + 10), 'No picture event falls where music plays: no offsets to show.', fill=COL['off'],
               font=f_b)
        img.save(path)
        return path
    for k in rows:
        s = summaries[k]
        evs = [e for e in events_measured.get(k, []) if e.get('music') and e.get('beat_offset_frames') is not None]
        per = s.get('mean_beat_period_frames') or 15
        half = max(3, int(math.ceil(per / 2)))
        x0, x1 = 300, W - 40
        top, bot = y + 30, y + 190
        d.text((24, y + 6), f"{labels.get(k, k)}  n={s['n_with_music']}", fill=KIND_COL.get(k, COL['ink']),
               font=font(24, True))
        d.text((24, y + 40), f"on beat (<=1 fr): {round(100 * s['share_on_beat'])}%", fill=COL['ink'], font=f_s)
        d.text((24, y + 64), f"  chance: {round(100 * (s.get('chance_on_beat') or 0))}%", fill=COL['mute'], font=f_s)
        d.text((24, y + 88), f"within 2 fr: {round(100 * s['share_near_beat'])}% (chance "
                             f"{round(100 * (s.get('chance_near_beat') or 0))}%)", fill=COL['ink'], font=f_s)
        d.text((24, y + 112), f"median offset {s['median_offset_frames']:+.1f} fr", fill=COL['ink'], font=f_s)
        pl = s.get('phase_locking') or {}
        d.text((24, y + 136), f"locking {pl.get('vector_strength')} (p {pl.get('rayleigh_p')})", fill=COL['ink'],
               font=f_s)
        if s.get('downbeat'):
            d.text((24, y + 160), f"on downbeat: {round(100 * s['downbeat']['share_on'])}% (chance "
                                  f"{round(100 * (s['downbeat'].get('chance_on') or 0))}%)", fill=COL['ink'], font=f_s)
        counts = {}
        for e in evs:
            v = int(round(max(-half, min(half, e['beat_offset_frames']))))
            counts[v] = counts.get(v, 0) + 1
        mx = max(counts.values()) if counts else 1
        nb = 2 * half + 1
        bw = (x1 - x0) / nb
        d.rectangle([x0, top, x1, bot], outline=COL['grid'])
        for i, v in enumerate(range(-half, half + 1)):
            bx = x0 + i * bw
            if v == 0:
                d.rectangle([bx, top, bx + bw, bot], fill=(232, 245, 234))
            c = counts.get(v, 0)
            if c:
                hgt = (bot - top - 22) * c / mx
                d.rectangle([bx + 2, bot - 22 - hgt, bx + bw - 2, bot - 22], fill=KIND_COL.get(k, COL['ink']))
                d.text((bx + bw / 2 - 6, bot - 22 - hgt - 20), str(c), fill=COL['ink'], font=f_s)
            if v % 2 == 0 or nb <= 21:
                d.text((bx + bw / 2 - 8, bot - 20), f'{v:+d}' if v else '0', fill=COL['mute'], font=f_s)
        ch = s.get('chance_on_beat')
        if ch:
            exp = len(evs) / nb
            hy = bot - 22 - (bot - top - 22) * exp / mx
            d.line([x0, hy, x1, hy], fill=COL['mute'], width=1)
        d.text((x0, top - 26), 'frames from the nearest beat (event - beat; + = picture after the beat); grey line: '
                               'what random placement gives per bin', fill=COL['mute'], font=f_s)
        y += 230
    img.save(path)
    return path


def draw_strips(out_dir, sig, music_lane, events_measured, speech_spans, story, t0, t1, secs_per_row=12.0,
                rows_per_page=5, max_pages=6, impacts=None, on_k=1.0):
    """Pages of strips: the beat grid (thin beats, thick downbeats, orange phrase starts) with the music level,
    speech, story boundaries and every picture event marked with its offset in frames (green: within on_k)."""
    from PIL import Image, ImageDraw
    fps = float(sig['fps'])
    impacts = impacts or {}
    beats = music_lane.get('beats') or []
    lev = music_lane.get('level_db') or []
    every = float(music_lane.get('level_every_s') or 0.1)
    vals = [v for v in lev if v is not None]
    lo_l, hi_l = (min(vals), max(vals)) if vals else (-60, -10)
    if hi_l - lo_l < 6:
        lo_l = hi_l - 6
    kinds = [k for k in KIND_LABEL if events_measured.get(k)]
    labels = dict(KIND_LABEL)
    if sig.get('kind') == 'video':
        labels['sfx'] = 'sound onsets'           # a video has no effects track: onsets, not known SFX
    W = 1800
    L, R = 120, 30
    lane_h = 38
    row_h = 70 + lane_h * max(1, len(kinds)) + 40
    pages = []
    t = t0
    page = 0
    while t < t1 - 1e-6 and page < max_pages:
        H = 70 + row_h * rows_per_page
        img = Image.new('RGB', (W, H), COL['bg'])
        d = ImageDraw.Draw(img)
        f_h, f_s, f_m = font(24, True), font(17), font(15)
        d.text((20, 14), f'beat grid and picture events, {_clock(t)} - {_clock(min(t1, t + secs_per_row * rows_per_page))}'
                         '   (numbers: frames from the nearest beat)', fill=COL['ink'], font=f_h)
        lx = 1000
        for k in kinds:
            d.rectangle([lx, 46, lx + 14, 60], fill=KIND_COL[k])
            d.text((lx + 18, 43), labels[k], fill=COL['ink'], font=f_s)
            lx += 30 + 9 * len(labels[k])
        for r in range(rows_per_page):
            a = t + r * secs_per_row
            if a >= t1:
                break
            b = a + secs_per_row
            y0 = 70 + r * row_h
            gy0, gy1 = y0 + 30, y0 + 70

            def X(tt, a=a):
                return L + (tt - a) / secs_per_row * (W - L - R)
            # music band: level curve
            pts = []
            for j in range(int(a / every), int(b / every) + 1):
                if j < len(lev) and lev[j] is not None:
                    v = (lev[j] - lo_l) / (hi_l - lo_l)
                    pts.append((X(j * every), gy1 - v * (gy1 - gy0)))
            bend = min(b, t1)
            d.rectangle([L, gy0, X(bend), gy1], fill=(246, 244, 236))
            pts = [p for p in pts if p[0] <= X(bend) + 1]
            if len(pts) > 1:
                d.line(pts, fill=(225, 175, 80), width=2)
            for s0, s1 in speech_spans:
                if s1 < a or s0 > bend:
                    continue
                d.rectangle([X(max(a, s0)), gy1 - 8, X(min(bend, s1)), gy1], fill=COL['speech'])
            for bt in beats:
                if a <= bt['t'] <= bend:
                    xx = X(bt['t'])
                    if bt.get('phrase'):
                        d.line([xx, gy0 - 8, xx, y0 + row_h - 34], fill=COL['phrase'], width=3)
                    elif bt.get('downbeat'):
                        d.line([xx, gy0 - 4, xx, y0 + row_h - 34], fill=COL['down'], width=2)
                    else:
                        d.line([xx, gy0, xx, y0 + row_h - 34], fill=COL['beat'], width=1)
            for s in story:
                if a <= s['t0'] <= b and s['t0'] > 0:
                    xx = X(s['t0'])
                    for yy in range(int(y0), int(y0 + row_h - 30), 8):
                        d.line([xx, yy, xx, yy + 4], fill=COL['story'], width=2)
                    d.text((xx + 4, y0 + 2), str(s.get('label') or '')[:30], fill=COL['story'], font=f_m)
            d.text((10, gy0 + 6), _clock(a), fill=COL['ink'], font=f_s)
            for i, k in enumerate(kinds):
                ly = gy1 + 6 + i * lane_h
                d.text((10, ly + 4), labels[k][:13], fill=KIND_COL[k], font=f_m)
                last = [-1e9, -1e9]           # right end of the last label on each of two sub-rows
                for e in sorted(events_measured[k], key=lambda x: x['f']):
                    te = e['f'] / fps
                    if not (a <= te < b):
                        continue
                    xx = X(te)
                    d.polygon([(xx - 7, ly + 2), (xx + 7, ly + 2), (xx, ly + 14)], fill=KIND_COL[k])
                    label = ''
                    if e.get('music') and e.get('beat_offset_frames') is not None:
                        label = _fmt_off(e['beat_offset_frames'])
                    imp = impacts.get(e['f']) if k == 'sfx' else None
                    extra = f" | {imp['impact'].replace('_', ' ')} {_fmt_off(imp['offset_frames'])}" if imp else ''
                    if not label and not extra:
                        continue
                    wtxt = 9 * len(label + extra) + 4
                    row = 0 if xx + 6 > last[0] + 3 else 1 if xx + 6 > last[1] + 3 else None
                    if row is None:
                        continue              # no room: the marker stays, its number is in the result
                    yy = ly + 6 + 13 * row
                    if label:
                        on = abs(e['beat_offset_frames']) <= on_k
                        d.text((xx + 6, yy), label, fill=COL['on'] if on else COL['off'], font=f_s)
                    if extra:
                        d.text((xx + 8 + 9 * len(label), yy), extra, fill=KIND_COL[k], font=f_m)
                    last[row] = xx + 6 + wtxt
            # seconds ticks
            for s in range(int(math.ceil(a)), int(bend) + 1):
                xx = X(s)
                d.line([xx, y0 + row_h - 34, xx, y0 + row_h - 28], fill=COL['mute'])
                if s % 2 == 0:
                    d.text((xx - 10, y0 + row_h - 27), f'{s}s', fill=COL['mute'], font=f_m)
        p = out_dir / f'sync-strips-{page + 1}.png'
        img.save(p)
        pages.append(str(p))
        page += 1
        t += secs_per_row * rows_per_page
    return pages
