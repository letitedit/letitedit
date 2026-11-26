"""Shot matching: bring clips toward a reference shot's exposure, white balance and (gently) tone, written as an
editable Color Grading effect on each clip (Shotcut's own lift/gamma/gain filter: change it in the filter panel,
with letitedit_timeline_apply, or take it off; the footage is never touched).

    match(project, reference, clips=None, ...)        -> report: a proposal (changes in the edit vocabulary, a plan
                                                         id, before/after frames rendered by melt, measured
                                                         differences before and after, abstentions with reasons)
    match(project, reference, ..., apply=True)        -> the same, then written through the shared apply path
    match(project, plan_id=..., apply=True)           -> a stored proposal written, if the project has not changed
    match(project, remove=True, clips=None)           -> the shot-match effects taken off those clips (all if None)

Measuring. Every clip is measured at `frames` times inside it (clear of transitions and fades), rendered by melt (the
export engine) from a copy of the project in which only that clip's track is visible, burnt-in captions and text
effects are off, and a clip's earlier shot-match effect is replaced by a neutral one (so before and after go through
the same colour conversion). The picture is cut to the footage's own area (black bars, Blur: Pad fills and flat dark
borders left out) and measured at 480 px: pixels with any channel at 94 % or more (blown) or at 3.5 % or less (too
dark for its colour to be measured) are left out of the colour measurements; ignore_regions leave out more.

Correcting. The correction is the filter's own model, per channel c on 0-1 code values:
    out_c = min(1, (gain_c * in_c) ** (1 / gamma))     (lift stays 0)
so exposure and white balance are the three gains (exposure = their luma-weighted mean, white balance = the
gains divided by it) and tone is one gamma for all channels.
 - 'correspondence': when the clip and the reference show the same surfaces (ORB features matched with a RANSAC
   homography between a frame of each), the gains are fitted by robust regression on the mean colours of patches
   that really line up (luma detail correlating over ALIGNED_NCC, which exposure and white balance cannot change);
   gamma too, only when the gains alone already fit closely (TONE_MAX_RESIDUAL). This is the precise mode.
 - 'statistics': otherwise, if the two pictures are similar by a scene test (cast-free colour histogram and contrast
   shape overlap), white balance comes from grey pixels (local log-contrast equal in R, G and B: illuminant-free
   neutral surfaces) or a neutral region you give, and exposure from luma percentiles neither picture has blown or
   crushed; no tone change, and only STATS_STRENGTH of the estimate is applied (gentle).
Every correction is bounded by `limits`, scaled by `strength`, rendered by melt and measured again; a clip whose
measured difference did not get smaller is left alone.

Abstaining (no change, with a reason code): unsupported input (HDR PQ/HLG, Dolby Vision, BT.2020 primaries, log
transfer or camera log tags, 10-bit with no transfer tag, a flat log-looking picture from an untagged source), a
project that is not SDR BT.709/601, too little measurable picture, scenes too different, intentional looks
(golden/sunset light or night against a shot without it, unless keep_looks=False), a difference over twice the
limits (likely real light, not a camera mismatch), light changing inside the clip, an already matched clip, or no
measured improvement. Nothing here grades for taste: matching measurements is not aesthetic equivalence.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import copy
import hashlib
import json
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
ALGORITHM = 'shot_match/1.0'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'shot-match'
FFPROBE = Path(_SAI_ROOT) / 'app' / 'ffprobe.exe'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

ROLE_PROP = 'letitedit_ai:role'           # hidden bookkeeping (edit_effects.HIDDEN): finds our own effect again
ROLE = 'shot_match'
INFO_PROP = 'letitedit_ai:shot_match'     # shown with the effect's settings: what it matched and when
FILTER = 'color'                        # Shotcut's Color Grading (mlt lift_gamma_gain), filter version 1
TEXT_SERVICES = {'dynamictext', 'qtext', 'richtext', 'kdenlivetitle', 'subtitle', 'gpstext', 'timer', 'qtcrop'}
TEXT_IDS = {'dynamicText', 'richText', 'text', 'timer', 'gpsText', 'subtitle', 'typewriter'}

DEFAULT_LIMITS = {'exposure_stops': 1.0, 'white_balance': 0.15, 'tone': 0.15}
CORRECTIONS = ('exposure', 'white_balance', 'tone')
STATS_STRENGTH = 0.6        # share of a statistics-mode estimate that is applied
ANALYSIS_LONG = 480         # px, long side of the measured picture
HI, LO = 0.94, 0.035        # colour measurements leave out pixels with a channel >= HI or every channel <= LO
BLOWN = 0.985               # a channel at or above this counts as blown (clipped share)
DECODE_GAMMA = 2.2          # stops = 2.2 * log2(code-value gain), as the filter itself assumes (gamma 2.2)
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)

# Deterministic thresholds (constraints, not calibrated probabilities). Measured on test-footage (see test_shot_match).
# Statistics mode needs both (calibration on test-footage: see test_shot_match.py, test_scene_threshold_calibration).
SIMILARITY_MIN = 0.80       # combined scene similarity (cast-free chroma + contrast shape histogram overlaps)
SIMILARITY_CHROMA_MIN = 0.76
CORR_MIN_INLIERS = 30
CORR_MIN_RATIO = 0.25
CORR_MIN_OVERLAP = 0.2
CORR_MIN_PAIRS = 400
CORR_MAX_RESIDUAL = 0.12    # log units (about 12 %) of the robust fit
CORR_MIN_FIT_INLIERS = 0.6  # share of colour pairs the robust fit keeps (two lights split them about in half)
TONE_MAX_RESIDUAL = 0.04    # tone (gamma) is fitted only when exposure + white balance alone leave less than this
GREY_MIN_PIXELS = 250
GREY_MAX_SPREAD = 0.12      # log units: grey pixels spread wider than this -> mixed light, white balance unreliable
UNSTABLE_STOPS = 1.2        # statistics mode: sampled frames' median luma differing more than this (stops) -> abstain
WOBBLY_STOPS = 0.6          # ... more than this -> half strength, noted
UNSTABLE_CAST = 0.12        # ... grey casts differing more than this (log units) -> abstain
PAIRS_UNSTABLE_STOPS = 0.6  # correspondence mode: frame pairs fitted alone disagreeing more than this -> abstain
PAIRS_WOBBLY_STOPS = 0.3    # ... more than this -> half strength
PAIRS_UNSTABLE_CAST = 0.08  # ... white balance disagreeing more than this (log units) -> abstain
NEGLIGIBLE = {'exposure_stops': 0.08, 'white_balance': 0.015, 'tone': 0.02}
MIN_MEASURABLE = 0.15       # share of the picture that must be measurable
MAX_CLIPS = 60
NEW_CLIP_BUDGET = 0.02      # brightening may blow at most this extra share of the picture


# ============================================================================ small helpers

def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def clock(s):
    s = max(0.0, float(s))
    return f'{int(s // 60)}:{s % 60:06.3f}'


def _stops(gain):
    return DECODE_GAMMA * math.log2(max(1e-6, float(gain)))


def _gain(stops):
    return 2.0 ** (float(stops) / DECODE_GAMMA)


# ============================================================================ colour math

def srgb_to_lab(rgb):
    """0-1 code values (treated as sRGB / BT.709, D65) -> CIE L*a*b*."""
    rgb = np.clip(np.asarray(rgb, np.float64), 0.0, 1.0)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    d = 6.0 / 29.0
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4.0 / 29.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e2000(lab1, lab2):
    """CIEDE2000 colour difference, element-wise over (..., 3) arrays."""
    L1, a1, b1 = (lab1[..., i] for i in range(3))
    L2, a2, b2 = (lab2[..., i] for i in range(3))
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm7 = ((c1 + c2) / 2) ** 7
    g = 0.5 * (1 - np.sqrt(cm7 / (cm7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dl, dc = L2 - L1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    zero = (c1p * c2p) == 0
    dh = np.where(zero, 0, dh)
    dhh = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    lm, cm = (L1 + L2) / 2, (c1p + c2p) / 2
    hs = h1p + h2p
    hm = np.where(zero, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    t = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm))
         + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    dtheta = 30 * np.exp(-(((hm - 275) / 25) ** 2))
    rc = 2 * np.sqrt(cm ** 7 / (cm ** 7 + 25.0 ** 7))
    sl = 1 + 0.015 * (lm - 50) ** 2 / np.sqrt(20 + (lm - 50) ** 2)
    sc = 1 + 0.045 * cm
    sh = 1 + 0.015 * cm * t
    rt = -np.sin(np.radians(2 * dtheta)) * rc
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def apply_model(rgb, gains, gamma=1.0):
    """What the Color Grading filter does to 0-1 code values with lift 0 (the filter's own formula)."""
    g = np.asarray(gains, np.float32).reshape((1,) * (np.ndim(rgb) - 1) + (3,))
    return np.clip(np.maximum(np.asarray(rgb, np.float32) * g, 0) ** (1.0 / float(gamma)), 0.0, 1.0)


def luma(rgb):
    return np.asarray(rgb, np.float32) @ LUMA


# ============================================================================ source colour metadata

_LOG_TAG = re.compile(r'(?i)\b(?:[svcfndlr]-?log\s?\d?|log-?c\d?|apple\s?log|v-?log|log3g10|logc[34]?|hlg|pq)\b')
HDR_TRANSFERS = {'smpte2084': 'PQ (HDR10)', 'arib-std-b67': 'HLG (HDR)'}
LOG_TRANSFERS = {'log100': 'logarithmic (100:1)', 'log316': 'logarithmic (316:1)'}
SDR_TRANSFERS = {'bt709', 'bt470bg', 'bt470m', 'smpte170m', 'iec61966-2-1', 'gamma22', 'gamma28', 'bt2020-10',
                 'bt2020-12', 'smpte240m', 'linear'}


def source_colour(path):
    """Colour facts of a media file from ffprobe (cached per file content): pix_fmt, bit depth, range, matrix,
    transfer, primaries, HDR side data, camera log tags."""
    import letitedit.footage.footage_notes as footage_notes
    path = str(path)
    try:
        key = footage_notes.key(path)
    except OSError:
        return {'file': path, 'error': 'file not found'}
    cf = CACHE / 'probe' / f'{key}.json'
    if cf.exists():
        try:
            return json.loads(cf.read_text(encoding='utf-8-sig'))
        except ValueError:
            pass
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-print_format', 'json', '-show_streams', '-show_format',
                        path], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, check=False)
    data = json.loads(r.stdout or '{}')
    v = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')), None)
    info = {'file': path, 'key': key}
    if v is None:
        info['error'] = 'no video stream'
        return info
    pix = v.get('pix_fmt') or ''
    m = re.search(r'p(9|10|12|14|16)', pix)
    bits = int(v.get('bits_per_raw_sample') or 0) or (int(m.group(1)) if m else 8)
    side = [sd.get('side_data_type', '') for sd in v.get('side_data_list') or []]
    tags = {**((data.get('format') or {}).get('tags') or {}), **(v.get('tags') or {})}
    log_tags = sorted({f'{k}={val}' for k, val in tags.items() if isinstance(val, str) and _LOG_TAG.search(val)
                       and 'encoder' not in k.lower() and 'handler' not in k.lower()})
    info.update(codec=v.get('codec_name'), pix_fmt=pix, bits=bits, range=v.get('color_range'),
                matrix=v.get('color_space'), transfer=v.get('color_transfer'), primaries=v.get('color_primaries'),
                side_data=side, log_tags=log_tags)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(info), encoding='utf-8')
    return info


def support(info, kind='video'):
    """(ok, code, text) for a source: SDR is supported; HDR, wide gamut, log and unverified high bit depth are not."""
    if kind == 'image':
        return True, None, None
    if info.get('error'):
        return False, 'unreadable', f"could not read the file's colour facts ({info['error']})"
    tr = (info.get('transfer') or '').lower()
    pr = (info.get('primaries') or '').lower()
    if tr in HDR_TRANSFERS:
        return False, 'unsupported_hdr', f'HDR source ({HDR_TRANSFERS[tr]} transfer): matching works on SDR only'
    if any('dovi' in s.lower() or 'dolby' in s.lower() for s in info.get('side_data') or []):
        return False, 'unsupported_hdr', 'Dolby Vision HDR source: matching works on SDR only'
    if any('mastering display' in s.lower() or 'content light' in s.lower() for s in info.get('side_data') or []):
        return False, 'unsupported_hdr', 'HDR mastering metadata on the source: matching works on SDR only'
    if pr == 'bt2020':
        return False, 'unsupported_wide_gamut', 'BT.2020 primaries (wide gamut / HDR): matching works on BT.709 only'
    if tr in LOG_TRANSFERS:
        return False, 'unsupported_log', f'log footage ({LOG_TRANSFERS[tr]} transfer): convert it to BT.709 first'
    if info.get('log_tags'):
        return False, 'unsupported_log', f"camera log tag ({info['log_tags'][0][:60]}): convert it to BT.709 first"
    if (info.get('bits') or 8) > 8 and tr in ('', 'unknown', 'unspecified', 'reserved'):
        return False, 'unverified_transfer', (f"{info.get('bits')}-bit source with no transfer tag: it may be log or "
                                              'HDR, so it is not matched')
    if tr and tr not in SDR_TRANSFERS and tr not in ('unknown', 'unspecified', 'reserved'):
        return False, 'unverified_transfer', f'unrecognised transfer {tr!r}'
    return True, None, None


def profile_support(profile):
    cs = str(profile.get('colorspace') or '709')
    if cs in ('709', '601', '170', '470', '240'):
        return True, None
    return False, f'the project colour space is {cs} (not SDR BT.709/601): shot matching is SDR-only'


# ============================================================================ picture statistics

def _grey_pixels(rgb, valid, frac=0.02):
    """Grey pixels (Yang, Gao & Li 2015): local contrast of log R, log G and log B equal, which an illuminant cannot
    change. Returns (picked rgb (N, 3), the grey index map)."""
    import cv2
    eps = 1.0 / 255
    lg = np.log(rgb + eps)
    con = np.empty_like(rgb)
    for c in range(3):
        g = cv2.GaussianBlur(lg[..., c], (0, 0), 1.2)
        con[..., c] = np.abs(cv2.Laplacian(g, cv2.CV_32F, ksize=3))
    m = con.mean(-1)
    gi = cv2.blur(con.std(-1) / (m + 1e-4), (5, 5))
    y = luma(rgb)
    ok = valid & (m > 0.015) & (y > 0.06) & (y < 0.9)
    idx = np.flatnonzero(ok.ravel())
    if idx.size == 0:
        return np.zeros((0, 3), np.float32), gi
    n = int(min(max(150, frac * ok.size), idx.size, 6000))
    order = np.argpartition(gi.ravel()[idx], n - 1)[:n]
    return rgb.reshape(-1, 3)[idx[order]], gi


def _cast(px):
    """(log R/G, log B/G) of the mean of pixels, and the robust spread of the pixels' own ratios."""
    if px is None or len(px) == 0:
        return None, None
    mean = px.mean(0)
    cast = (math.log(mean[0] / mean[1]), math.log(mean[2] / mean[1]))
    eps = 1.0 / 255
    u = np.log((px[:, 0] + eps) / (px[:, 1] + eps))
    v = np.log((px[:, 2] + eps) / (px[:, 1] + eps))
    spread = float(1.4826 * max(np.median(np.abs(u - np.median(u))), np.median(np.abs(v - np.median(v)))))
    return cast, spread


def _skin(rgb, valid):
    """Skin-like pixels (YCbCr box, Chai & Ngan) among valid ones."""
    r, g, b = rgb[..., 0] * 255, rgb[..., 1] * 255, rgb[..., 2] * 255
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cr = 0.713 * (r - y) + 128
    cb = 0.564 * (b - y) + 128
    return valid & (y > 50) & (cr > 135) & (cr < 175) & (cb > 85) & (cb < 128)


class Picture:
    """One measured frame: rgb (H, W, 3) float 0-1 at analysis size, the picture mask (ignore regions out) and the
    measurable mask (not blown, not crushed)."""

    def __init__(self, rgb, mask=None, time_s=None, png=None):
        self.rgb = np.ascontiguousarray(rgb, np.float32)
        self.mask = np.ones(self.rgb.shape[:2], bool) if mask is None else mask
        self.valid = self.mask & (self.rgb.max(-1) < HI) & (self.rgb.min(-1) > LO)
        self.t = time_s
        self.png = png


def frame_stats(pic, grey=None):
    rgb, mask, valid = pic.rgb, pic.mask, pic.valid
    y = luma(rgb)[mask]
    n = max(1, int(mask.sum()))
    if grey is None:
        grey, _ = _grey_pixels(rgb, valid)
    cast, spread = _cast(grey)
    vy = luma(rgb)[valid]
    return {'t': pic.t, 'median_luma': float(np.median(vy)) if vy.size else None,
            'blown': float((rgb.max(-1)[mask] >= BLOWN).sum()) / n,
            'crushed': float((y <= 0.03).sum()) / n,
            'measurable': float(valid.sum()) / n,
            'grey_cast': cast, 'grey_spread': spread, 'grey_n': len(grey)}


def clip_stats(pics, neutral=None):
    """Pooled measurements of a clip's frames. neutral: [(pic, box mask)] of a neutral region (overrides grey pixels)."""
    ys, greys, skins, valids, per = [], [], [], [], []
    for p in pics:
        ys.append(luma(p.rgb)[p.mask])
        g, _ = _grey_pixels(p.rgb, p.valid)
        greys.append(g)
        per.append(frame_stats(p, g))
        valids.append(p.rgb[p.valid])
        sk = _skin(p.rgb, p.valid)
        skins.append(p.rgb[sk])
    yall = np.concatenate(ys) if ys else np.zeros(0, np.float32)
    grey = np.concatenate(greys) if greys else np.zeros((0, 3), np.float32)
    vall = np.concatenate(valids) if valids else np.zeros((0, 3), np.float32)
    skin = np.concatenate(skins) if skins else np.zeros((0, 3), np.float32)
    n = max(1, yall.size)
    cast, spread = _cast(grey)
    source = 'grey pixels'
    if neutral:
        px = np.concatenate([p.rgb[m & p.valid] for p, m in neutral]) if neutral else np.zeros((0, 3))
        if len(px) >= 30:
            cast, spread = _cast(px)
            source = 'neutral region'
        else:
            source = 'grey pixels (the neutral region had too few measurable pixels)'
    qs = np.arange(0.05, 0.951, 0.05)
    st = {
        'frames': len(pics),
        'luma_q': np.quantile(yall, qs).astype(float).tolist() if yall.size else None,
        'q_levels': qs.round(2).tolist(),
        'median_luma': float(np.median(luma(vall))) if len(vall) else None,
        'blown': float(sum(f['blown'] * p.mask.sum() for f, p in zip(per, pics)) / n),
        'crushed': float(sum(f['crushed'] * p.mask.sum() for f, p in zip(per, pics)) / n),
        'measurable': float(len(vall)) / n,
        'grey_cast': cast, 'grey_spread': spread, 'grey_n': None if source == 'neutral region' else len(grey),
        'neutral_source': source,
        'skin_share': float(len(skin)) / n, 'skin_mean': skin.mean(0).tolist() if len(skin) >= 200 else None,
        'saturation': float(np.mean((vall.max(1) - vall.min(1)) / np.maximum(vall.max(1), 1e-3))) if len(vall) else 0.0,
        'per_frame': per,
    }
    st['hist_chroma'], st['hist_luma'] = _hists(pics, cast)
    st['looks'] = _looks(pics, st, grey)
    return st


def _hists(pics, cast):
    """Cast-free chroma histogram (log R/G, log B/G minus the clip's grey cast) and the luma-shape histogram (log2 of
    luma over its median); each frame weighted equally."""
    import cv2
    cu, cv_ = cast if cast else (0.0, 0.0)
    hc = np.zeros((20, 20), np.float64)
    hl = np.zeros(24, np.float64)
    eps = 1.0 / 255
    for p in pics:
        px = p.rgb[p.valid]
        if len(px) < 50:
            continue
        y = px @ LUMA
        keep = (y > 0.06) & (y < 0.92)
        px = px[keep]
        if len(px) < 50:
            continue
        u = np.log((px[:, 0] + eps) / (px[:, 1] + eps)) - cu
        v = np.log((px[:, 2] + eps) / (px[:, 1] + eps)) - cv_
        h, _, _ = np.histogram2d(np.clip(u, -0.79, 0.79), np.clip(v, -0.79, 0.79), bins=20, range=[[-0.8, 0.8], [-0.8, 0.8]])
        hc += h / max(1, h.sum())
        ya = luma(p.rgb)[p.mask]
        ya = ya[ya > 0.004]
        if ya.size:
            rel = np.log2(ya / np.median(ya))
            h1, _ = np.histogram(np.clip(rel, -3.99, 1.99), bins=24, range=(-4, 2))
            hl += h1 / max(1, h1.sum())
    hc = cv2.GaussianBlur(hc, (0, 0), 0.8)
    hl = np.convolve(hl, [0.25, 0.5, 0.25], mode='same')
    return (hc / hc.sum()).tolist() if hc.sum() else None, (hl / hl.sum()).tolist() if hl.sum() else None


def similarity(a, b):
    """Scene similarity of two clips' statistics, 0-1: the mean of the cast-free chroma histogram overlap and the
    luma-shape histogram overlap (histogram intersections). Exposure and white balance do not change it."""
    if not (a.get('hist_chroma') and b.get('hist_chroma') and a.get('hist_luma') and b.get('hist_luma')):
        return None, None, None
    sc = float(np.minimum(np.asarray(a['hist_chroma']), np.asarray(b['hist_chroma'])).sum())
    sl = float(np.minimum(np.asarray(a['hist_luma']), np.asarray(b['hist_luma'])).sum())
    return (sc + sl) / 2, sc, sl


GOLDEN = {'lit_warmth': 0.25, 'split': 0.12, 'median': 0.2}
NIGHT = {'median': 0.12, 'lights_min': 0.001, 'lights_max': 0.08}


def _looks(pics, st, grey=None):
    """Lighting character, measured on grey pixels (neutral surfaces, so object colours don't count): golden =
    low-sun light, the brighter neutral surfaces lit warm (log R/B over GOLDEN lit_warmth) and clearly warmer than the
    darker ones, which the blue sky lights (two illuminants; a camera's white balance error shifts both alike);
    night = dark with small bright lights; flat = lifted blacks, low highlights and low saturation (log-like)."""
    warm = None
    if st.get('grey_cast'):
        warm = st['grey_cast'][0] - st['grey_cast'][1]           # log(R/B) of the neutral estimate
    lit = shade = None
    if grey is not None and len(grey) >= 2 * GREY_MIN_PIXELS:
        gy = grey @ LUMA
        mid = np.median(gy)
        b, d = grey[gy >= mid], grey[gy < mid]
        lit = math.log(b[:, 0].mean() / b[:, 2].mean())
        shade = math.log(d[:, 0].mean() / d[:, 2].mean())
    px = np.concatenate([p.rgb[p.mask] for p in pics]) if pics else np.zeros((0, 3))
    if len(px):
        y = px @ LUMA
        med = float(np.median(y))
        lights = float(((y > 0.85)).mean())
    else:
        med, lights = None, 0.0
    split = (lit - shade) if (lit is not None and shade is not None) else None
    golden = bool(split is not None and lit > GOLDEN['lit_warmth'] and split > GOLDEN['split']
                  and (med or 0) > GOLDEN['median'])
    night = bool(med is not None and med < NIGHT['median'] and NIGHT['lights_min'] < lights < NIGHT['lights_max'])
    flat = None
    if st.get('luma_q'):
        q = st['luma_q']
        flat = bool(q[0] > 0.12 and q[-1] < 0.78 and st.get('saturation', 1) < 0.14)
    return {'golden': golden, 'night': night, 'flat': flat, 'neutral_warmth': _r(warm), 'lit_warmth': _r(lit),
            'shade_warmth': _r(shade), 'warmth_split': _r(split), 'median': _r(med), 'bright_share': _r(lights, 4)}


# ============================================================================ correspondence (same surfaces)

def _features(pic):
    import cv2
    g = np.clip(luma(pic.rgb) * 255, 0, 255).astype(np.uint8)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    orb = cv2.ORB_create(nfeatures=2500, scaleFactor=1.2, nlevels=8, edgeThreshold=15, patchSize=31, fastThreshold=10)
    m = (pic.mask.astype(np.uint8) * 255)
    kp, des = orb.detectAndCompute(g, m)
    return kp, des


def _feat(pic):
    if getattr(pic, '_feat', None) is None:
        pic._feat = _features(pic)
    return pic._feat


def _good_matches(fa, fb):
    """Descriptor matches passing Lowe's ratio test (0.8)."""
    import cv2
    kpa, da = fa
    kpb, db = fb
    if da is None or db is None or len(kpa) < 20 or len(kpb) < 20:
        return []
    knn = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    return [m[0] for m in knn if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]


def _homography(fa, fb, shape_a, shape_b, good=None):
    """Homography taking picture a to picture b (keypoints/descriptors fa, fb), with match counts, or None."""
    import cv2
    kpa, _ = fa
    kpb, _ = fb
    if good is None:
        good = _good_matches(fa, fb)
    if len(good) < 15:
        return None
    src = np.float32([kpa[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kpb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    thr = 0.008 * math.hypot(*shape_b[:2])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, thr, maxIters=3000, confidence=0.995)
    if H is None or inl is None:
        return None
    n_in = int(inl.sum())
    ha, wa = shape_a[:2]
    hb, wb = shape_b[:2]
    corners = np.float32([[0, 0], [wa, 0], [wa, ha], [0, ha]]).reshape(-1, 1, 2)
    quad = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    convex = bool(cv2.isContourConvex(quad.astype(np.float32)))
    det = float(np.linalg.det(H[:2, :2] / H[2, 2]))
    rect = np.float32([[0, 0], [wb, 0], [wb, hb], [0, hb]])
    overlap = 0.0
    if convex:
        area, _ = cv2.intersectConvexConvex(quad.astype(np.float32), rect)
        overlap = float(area) / float(wb * hb)
    return {'H': H, 'matches': len(good), 'inliers': n_in, 'ratio': n_in / len(good), 'overlap': overlap,
            'scale': math.sqrt(abs(det)) if det > 0 else 0.0, 'convex': convex}


def _good(h):
    return (h is not None and h['convex'] and h['inliers'] >= CORR_MIN_INLIERS and h['ratio'] >= CORR_MIN_RATIO
            and h['overlap'] >= CORR_MIN_OVERLAP and 0.33 <= h['scale'] <= 3.0)


PATCH = 11                  # px (analysis size): the patches whose mean colours are compared
ALIGNED_NCC = 0.9           # a patch counts as the same surface when its luma detail correlates this well


def _aligned(clip_pic, ref_pic, H):
    """Where the warped clip picture lines up with the reference: normalised cross-correlation of log luma over
    PATCH x PATCH windows (blind to exposure and white balance, which are gains) above ALIGNED_NCC, with some
    texture to judge by, inside both pictures. A homography only roughly aligns a handheld 3D scene (parallax, moving
    hands); this keeps the parts that really show the same surface. Returns (aligned mask, overlap mask)."""
    import cv2
    hb, wb = ref_pic.rgb.shape[:2]
    warped = cv2.warpPerspective(clip_pic.rgb, H, (wb, hb), flags=cv2.INTER_LINEAR)
    inside = cv2.warpPerspective(clip_pic.mask.astype(np.float32), H, (wb, hb), flags=cv2.INTER_NEAREST) > 0.5
    m = cv2.erode((inside & ref_pic.mask).astype(np.uint8), np.ones((PATCH, PATCH), np.uint8)).astype(bool)
    x, y = np.log(luma(warped) + 0.02), np.log(luma(ref_pic.rgb) + 0.02)
    k = (PATCH, PATCH)
    mx, my = cv2.blur(x, k), cv2.blur(y, k)
    vx, vy = cv2.blur(x * x, k) - mx * mx, cv2.blur(y * y, k) - my * my
    ncc = (cv2.blur(x * y, k) - mx * my) / np.sqrt(np.maximum(vx * vy, 1e-12))
    return m & (np.sqrt(np.maximum(vy, 0)) > 0.02) & (ncc > ALIGNED_NCC), m


def _pair_coords(clip_pic, ref_pic, H, limit=12000, seed=0, stride=3):
    """Reference-picture coordinates of aligned patch centres (every `stride` px, at most `limit`) and the aligned
    share of the overlap, or None when fewer than 50."""
    ok, inside = _aligned(clip_pic, ref_pic, H)
    sel = np.zeros_like(ok)
    sel[::stride, ::stride] = ok[::stride, ::stride]
    ys, xs = np.nonzero(sel)
    if len(ys) < 50:
        return None
    if len(ys) > limit:
        pick = np.random.default_rng(seed).choice(len(ys), limit, replace=False)
        ys, xs = ys[pick], xs[pick]
    return ys, xs, float(ok.sum()) / max(1.0, float(inside.sum()))


def _sample_pairs(clip_pic, ref_pic, H, coords):
    """(clip colours, reference colours): the mean colour of each aligned patch in both pictures."""
    import cv2
    hb, wb = ref_pic.rgb.shape[:2]
    warped = cv2.warpPerspective(clip_pic.rgb, H, (wb, hb), flags=cv2.INTER_LINEAR)
    ys, xs = coords[0], coords[1]
    k = (PATCH, PATCH)
    return cv2.blur(warped, k)[ys, xs], cv2.blur(ref_pic.rgb, k)[ys, xs]


def correspond(clip_pics, ref_pics, max_pairs=3, tries=8):
    """Find frame pairs that show the same surfaces: every clip frame against every reference frame by descriptor
    matches, then a RANSAC homography for the `tries` pairs with the most matches. Returns
    [{'ci', 'ri', 'h', 'coords'}] best first (may be [])."""
    cand = []
    for ci, a in enumerate(clip_pics):
        for ri, b in enumerate(ref_pics):
            good = _good_matches(_feat(a), _feat(b))
            if len(good) >= CORR_MIN_INLIERS:
                cand.append((len(good), ci, ri, good))
    cand.sort(key=lambda c: -c[0])
    found = []
    for _, ci, ri, good in cand[:tries]:
        h = _homography(_feat(clip_pics[ci]), _feat(ref_pics[ri]), clip_pics[ci].rgb.shape, ref_pics[ri].rgb.shape,
                        good)
        if _good(h):
            found.append({'ci': ci, 'ri': ri, 'h': h})
    found.sort(key=lambda f: -f['h']['inliers'] * f['h']['overlap'])
    out, used_c = [], set()
    for f in found:
        if f['ci'] in used_c:
            continue
        coords = _pair_coords(clip_pics[f['ci']], ref_pics[f['ri']], f['h']['H'])
        if coords is None:
            continue
        f['coords'] = coords
        out.append(f)
        used_c.add(f['ci'])
        if len(out) >= max_pairs:
            break
    return out


def _pairs_of(matches, clip_pics, ref_pics, per_match=False):
    """Pooled (clip, reference) colour pairs over the matched frame pairs, both measurable (per_match: also the
    list of each frame pair's own arrays)."""
    cs, rs = [], []
    for f in matches:
        c, r = _sample_pairs(clip_pics[f['ci']], ref_pics[f['ri']], f['h']['H'], f['coords'])
        ok = (c.max(1) < HI) & (c.min(1) > LO) & (r.max(1) < HI) & (r.min(1) > LO)
        cs.append(c[ok])
        rs.append(r[ok])
    if not cs:
        empty = (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32))
        return (empty, []) if per_match else empty
    pooled = (np.concatenate(cs), np.concatenate(rs))
    return (pooled, list(zip(cs, rs))) if per_match else pooled


def pair_agreement(per_match):
    """How much the frame pairs disagree about the correction (each fitted alone, exposure and white balance only):
    (exposure spread in stops, white-balance spread in log units, per-pair exposures). One static correction fits a
    clip whose frame pairs agree; light that changes inside the clip makes them disagree."""
    ex, wr, wb = [], [], []
    for c, r in per_match:
        if len(c) < CORR_MIN_PAIRS // 2:
            continue
        d = decompose(fit_pairs(c, r, tone=False)['gains'])
        ex.append(d['exposure_stops'])
        wr.append(math.log(d['wb'][0] / d['wb'][1]))
        wb.append(math.log(d['wb'][2] / d['wb'][1]))
    if len(ex) < 2:
        return 0.0, 0.0, ex
    return max(ex) - min(ex), max(max(wr) - min(wr), max(wb) - min(wb)), ex


def fit_pairs(clip_px, ref_px, tone=True, tone_limit=0.15, iters=10):
    """Robust fit of log ref_c = a_c + b * log clip_c (Tukey IRLS): gains_c = exp(a_c / b), gamma = 1 / b.
    Returns {'gains', 'gamma', 'residual', 'inliers', 'pairs'}."""
    x = np.log(np.asarray(clip_px, np.float64))
    y = np.log(np.asarray(ref_px, np.float64))
    n = len(x)
    w = np.ones(n)
    bmin, bmax = 1.0 / (1.0 + tone_limit), 1.0 + tone_limit
    b = 1.0
    a = np.zeros(3)
    spread = float(np.quantile(x @ LUMA, 0.9) - np.quantile(x @ LUMA, 0.1)) if n else 0.0
    use_tone = tone and spread > math.log(2.0)          # the slope needs a range of brightness to be measurable
    for _ in range(iters):
        sw = w.sum()
        if sw <= 0:
            break
        xm = (w[:, None] * x).sum(0) / sw
        ym = (w[:, None] * y).sum(0) / sw
        if use_tone:
            dx, dy = x - xm, y - ym
            b = float((w[:, None] * dx * dy).sum() / max(1e-9, (w[:, None] * dx * dx).sum()))
            b = min(bmax, max(bmin, b))
        a = ym - b * xm
        res = y - (a + b * x)
        rn = np.sqrt((res ** 2).mean(1))
        s = 1.4826 * float(np.median(np.abs(rn - np.median(rn)))) + 1e-4
        c = 4.685 * max(s, 0.01)
        w = np.where(rn < c, (1 - (rn / c) ** 2) ** 2, 0.0)
    res = y - (a + b * x)
    rn = np.sqrt((res ** 2).mean(1))
    inl = w > 0
    resid = float(np.sqrt((w * rn ** 2).sum() / max(1e-9, w.sum())))
    return {'gains': np.exp(a / b).tolist(), 'gamma': 1.0 / b, 'residual': resid, 'inliers': float(inl.mean()) if n else 0.0,
            'pairs': int(n), 'tone_measured': bool(use_tone)}


# ============================================================================ statistics mode estimates

def exposure_from_quantiles(clip, ref, margin=0.04):
    """log gain (code values) matching the luma quantiles that neither clip has blown or crushed, weighted toward
    the middle; None when fewer than 3 levels are usable."""
    if not (clip.get('luma_q') and ref.get('luma_q')):
        return None, 0
    qs = np.asarray(clip['q_levels'])
    lo = max(clip['crushed'], ref['crushed']) + margin
    hi = 1.0 - max(clip['blown'], ref['blown']) - margin
    tq, rq = np.asarray(clip['luma_q']), np.asarray(ref['luma_q'])
    use = (qs > lo) & (qs < hi) & (tq > 0.02) & (rq > 0.02) & (tq < 0.97) & (rq < 0.97)
    if use.sum() < 3:
        return None, int(use.sum())
    d = np.log(rq[use]) - np.log(tq[use])
    w = 1.0 - np.abs(qs[use] - 0.5) * 1.2
    order = np.argsort(d)
    cw = np.cumsum(w[order])
    return float(d[order][np.searchsorted(cw, cw[-1] / 2)]), int(use.sum())


def wb_from_casts(clip_cast, ref_cast):
    """Gains (luma-normalised) moving the clip's neutral cast onto the reference's."""
    g = np.array([math.exp(ref_cast[0] - clip_cast[0]), 1.0, math.exp(ref_cast[1] - clip_cast[1])])
    return g / float(g @ LUMA)


# ============================================================================ corrections: bounds, strength, report

def decompose(gains, gamma=1.0):
    g = np.asarray(gains, np.float64)
    e = float(g @ LUMA)
    w = g / e
    return {'exposure_stops': _stops(e), 'wb': w.tolist(), 'red_vs_green': w[0] / w[1] - 1, 'blue_vs_green': w[2] / w[1] - 1,
            'gamma': float(gamma)}


def compose(exposure_stops, wb, gamma):
    w = np.asarray(wb, np.float64)
    w = w / float(w @ LUMA)
    return (w * _gain(exposure_stops)).tolist(), float(gamma)


def bound(gains, gamma, limits, corrections, strength):
    """Apply which corrections are allowed, the limits and the strength. Returns (gains, gamma, notes, over) where over
    names corrections whose need was more than twice their limit."""
    d = decompose(gains, gamma)
    notes, over = [], []
    ex = d['exposure_stops'] if 'exposure' in corrections else 0.0
    wb = np.asarray(d['wb']) if 'white_balance' in corrections else np.ones(3)
    gm = d['gamma'] if 'tone' in corrections else 1.0
    lim_e, lim_w, lim_t = float(limits['exposure_stops']), float(limits['white_balance']), float(limits['tone'])
    if abs(ex) > 2 * lim_e:
        over.append('exposure')
    if abs(ex) > lim_e:
        notes.append(f'exposure limited to {lim_e:g} stop (needed {ex:+.2f})')
        ex = math.copysign(lim_e, ex)
    lw = np.log(wb / wb[1])
    if np.abs(lw).max() > 2 * math.log1p(lim_w):
        over.append('white_balance')
    if np.abs(lw).max() > math.log1p(lim_w):
        notes.append(f'white balance limited to {lim_w:.0%} per channel (needed red {math.exp(lw[0]) - 1:+.0%}, '
                     f'blue {math.exp(lw[2]) - 1:+.0%})')
        lw = np.clip(lw, -math.log1p(lim_w), math.log1p(lim_w))
    lt = math.log(gm)
    if abs(lt) > math.log1p(lim_t) + 1e-9:
        notes.append(f'tone limited to gamma {1 + lim_t:.2f}x')
        lt = math.copysign(math.log1p(lim_t), lt)
    s = float(strength)
    gains2, gamma2 = compose(ex * s, np.exp(lw * s), math.exp(lt * s))
    return gains2, gamma2, notes, over


def negligible(gains, gamma):
    d = decompose(gains, gamma)
    return (abs(d['exposure_stops']) < NEGLIGIBLE['exposure_stops']
            and max(abs(math.log(x)) for x in d['wb']) < NEGLIGIBLE['white_balance']
            and abs(math.log(d['gamma'])) < NEGLIGIBLE['tone'])


def describe_correction(gains, gamma):
    d = decompose(gains, gamma)
    parts = []
    if abs(d['exposure_stops']) >= 0.02:
        parts.append(f"exposure {d['exposure_stops']:+.2f} stop")
    warm = (d['red_vs_green'] - d['blue_vs_green']) / 2
    if abs(warm) >= 0.005:
        parts.append(f"{'warmer' if warm > 0 else 'cooler'} {abs(warm):.0%}")
    tint = -(d['red_vs_green'] + d['blue_vs_green']) / 2
    if abs(tint) >= 0.005:
        parts.append(f"{'greener' if tint > 0 else 'more magenta'} {abs(tint):.0%}")
    if abs(d['gamma'] - 1) >= 0.005:
        parts.append(f"midtones {'lifted' if d['gamma'] > 1 else 'deepened'} (gamma {d['gamma']:.3f})")
    return ', '.join(parts) or 'no change'


def filter_params(gains, gamma, info):
    """The Color Grading filter's settings for a correction (all keys a fresh Shotcut filter has)."""
    g = [round(float(x), 4) for x in gains]
    gm = round(float(gamma), 4)
    return {'lift_r': 0, 'lift_g': 0, 'lift_b': 0, 'gamma_r': gm, 'gamma_g': gm, 'gamma_b': gm,
            'gain_r': g[0], 'gain_g': g[1], 'gain_b': g[2], 'shotcut:filter_version': 1,
            ROLE_PROP: ROLE, INFO_PROP: json.dumps(info, separators=(',', ':'), sort_keys=True)}


IDENTITY = {'lift_r': 0, 'lift_g': 0, 'lift_b': 0, 'gamma_r': 1, 'gamma_g': 1, 'gamma_b': 1, 'gain_r': 1, 'gain_g': 1,
            'gain_b': 1, 'shotcut:filter_version': 1, ROLE_PROP: ROLE}


# ============================================================================ measured differences

def differences(clip, ref, pairs=None):
    """How a clip differs from the reference, measured. pairs: (clip colours, reference colours) of the same surfaces
    (correspondence) or None. Exposure in stops (+ = the clip is brighter), white balance as the clip's neutral
    relative to the reference's (+ red = the clip is redder), neutral_delta_e: CIEDE2000 between the two neutral
    estimates drawn as a mid grey; pairs_delta_e: mean CIEDE2000 over corresponding pixels."""
    out = {}
    if clip.get('median_luma') and ref.get('median_luma'):
        out['median_luma_stops'] = _r(DECODE_GAMMA * math.log2(clip['median_luma'] / ref['median_luma']), 3)
    lg, used = exposure_from_quantiles(clip, ref)
    if lg is not None:
        out['exposure_stops'] = _r(-lg * DECODE_GAMMA / math.log(2), 3)
        out['exposure_levels_used'] = used
    if clip.get('grey_cast') and ref.get('grey_cast'):
        dr = clip['grey_cast'][0] - ref['grey_cast'][0]
        db = clip['grey_cast'][1] - ref['grey_cast'][1]
        out['red_vs_green_pct'] = _r(100 * (math.exp(dr) - 1), 2)
        out['blue_vs_green_pct'] = _r(100 * (math.exp(db) - 1), 2)
        grey = 0.45
        a = srgb_to_lab(np.array([grey * math.exp(clip['grey_cast'][0]), grey, grey * math.exp(clip['grey_cast'][1])]) /
                        max(1.0, grey * math.exp(max(clip['grey_cast']))))
        b = srgb_to_lab(np.array([grey * math.exp(ref['grey_cast'][0]), grey, grey * math.exp(ref['grey_cast'][1])]) /
                        max(1.0, grey * math.exp(max(ref['grey_cast']))))
        a[0] = b[0] = 50.0
        out['neutral_delta_e'] = _r(float(delta_e2000(a, b)), 2)
    if clip.get('skin_mean') and ref.get('skin_mean'):
        la, lb = srgb_to_lab(np.array(clip['skin_mean'])), srgb_to_lab(np.array(ref['skin_mean']))
        out['skin_delta_e'] = _r(float(delta_e2000(la, lb)), 2)
        out['skin_hue_deg'] = _r(math.degrees(math.atan2(la[2], la[1])) % 360, 1)
        out['skin_hue_ref_deg'] = _r(math.degrees(math.atan2(lb[2], lb[1])) % 360, 1)
    if pairs is not None and len(pairs[0]) >= 50:
        c, r = pairs
        de = delta_e2000(srgb_to_lab(c), srgb_to_lab(r))
        out['pairs_delta_e'] = _r(float(np.mean(de)), 2)
        out['pairs_delta_e_median'] = _r(float(np.median(de)), 2)
        lc, lr = np.log(np.maximum(c, 1e-3)), np.log(np.maximum(r, 1e-3))
        out['pairs_exposure_stops'] = _r(DECODE_GAMMA * float(np.median(np.log2(np.maximum(c @ LUMA, 1e-3) /
                                                                               np.maximum(r @ LUMA, 1e-3)))), 3)
        dch = np.median(lc - lr, axis=0)
        out['pairs_red_vs_green_pct'] = _r(100 * (math.exp(dch[0] - dch[1]) - 1), 2)
        out['pairs_blue_vs_green_pct'] = _r(100 * (math.exp(dch[2] - dch[1]) - 1), 2)
        out['pairs'] = len(c)
    return out


def headline(d):
    """The one number that says how far apart two pictures are: mean CIEDE2000 of corresponding pixels when there
    are any, else neutral CIEDE2000 + 4 x |exposure stops| (a stop counts like a clearly visible colour difference)."""
    if d.get('pairs_delta_e') is not None:
        return float(d['pairs_delta_e'])
    e = d.get('exposure_stops')
    if e is None:
        e = d.get('median_luma_stops') or 0.0
    return float(d.get('neutral_delta_e') or 0.0) + 4.0 * abs(float(e))


# ============================================================================ the project

class StalePlan(Exception):
    """The project or a source file changed since the plan was made."""


def _resolve(project):
    if str(project).strip().lower() in ('live', 'current', 'editor'):
        raise ValueError("shot matching measures a saved project: pass its .mlt path or episode/cut folder (when it is "
                         "open in letitedit, applying still lands there as one undo step)")
    import letitedit.timeline.edit_script as es
    return es._resolve(project)


def _file_kind(path):
    import letitedit.server.core_tools as core_tools
    return core_tools._kind(path)


def timeline_clips(script):
    """Every item on the video tracks with its timeline span and the part safe to measure (clear of transitions
    and fades): [{'id', 'track', 'index', 'item', 'start', 'end', 'safe', 'file', 'kind', 'footage'}]."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.made as made
    from letitedit.timeline.edit_sync import layout, transition_len
    rows = []
    for t in script['tracks']:
        if t.get('kind', 'video') != 'video':
            continue
        lay = layout(t)
        for k, (it, s, e) in enumerate(lay):
            if 'id' not in it:
                continue
            tin = transition_len(it) if k > 0 else 0.0
            nxt = lay[k + 1] if k + 1 < len(lay) else None
            tout = transition_len(nxt[0]) if nxt is not None and nxt[1] < e - 1e-6 else 0.0
            fin = fout = 0.0
            for eff in it.get('effects') or []:
                if isinstance(eff, dict):
                    if 'fade_in' in eff:
                        fin = max(fin, es.to_seconds(eff['fade_in']))
                    if 'fade_out' in eff:
                        fout = max(fout, es.to_seconds(eff['fade_out']))
            lo, hi = s + max(tin, fin), e - max(tout, fout)
            if hi <= lo:
                lo, hi = s, e
            edge = min(0.25, (hi - lo) / 6)
            f = it.get('clip')
            kind = _file_kind(f) if f else ('graphic' if 'graphic' in it else 'color' if 'color' in it else 'other')
            footage = bool(f and kind in ('video', 'image') and not made.is_made(it) and 'graphic' not in it
                           and 'color' not in it)
            rows.append({'id': it['id'], 'track': t['name'], 'index': k, 'item': it, 'start': s, 'end': e,
                         'safe': (lo + edge, hi - edge), 'file': f, 'kind': kind, 'footage': footage})
    return rows


def sample_times(row, n):
    a, b = row['safe']
    if b - a < 0.15 or n <= 1:
        return [round((a + b) / 2, 3)]
    return [round(a + (k + 0.5) * (b - a) / n, 3) for k in range(n)]


def _is_text(f):
    import letitedit.timeline.edit_script as es
    return es._get(f, 'mlt_service') in TEXT_SERVICES or es._get(f, 'shotcut:filter') in TEXT_IDS


def _producer_map(doc):
    """{clip id: (entry element, producer element, track name)} and producer use counts (playlist entries)."""
    import letitedit.timeline.edit_script as es
    ids = es._ids_for(doc)
    where, uses = {}, {}
    for tr, pl, name, kind in doc.tracks():
        for i, (k, e, _) in enumerate(doc.entries(pl)):
            if k != 'entry':
                continue
            uses[e.get('producer')] = uses.get(e.get('producer'), 0) + 1
            if (name, i) in ids:
                where[ids[(name, i)]] = (e, doc.elements.get(e.get('producer')), name)
    return where, uses


def build_variant(path, out, inject=None, strip_text=(), isolate=None):
    """A copy of the project for measuring (the project itself is not changed): `inject` {clip id: Color Grading
    params} replaces each clip's shot-match effect (or adds one at the end), text effects come off the strip_text
    clips, only the `isolate` track's picture is shown, and burnt-in captions are off."""
    import letitedit.timeline.edit_effects as ee
    import letitedit.timeline.edit_script as es
    doc = es.Doc(path)
    where, uses = _producer_map(doc)
    inject = inject or {}
    for cid in set(inject) | set(strip_text):
        if cid not in where:
            continue
        e, prod, _ = where[cid]
        if prod is None or prod.tag == 'tractor':
            continue
        if cid in inject and uses.get(prod.get('id'), 0) > 1:      # shared with another clip: this clip gets its own
            prod = copy.deepcopy(prod)
            prod.set('id', es._new_id(doc, prod.tag))
            doc.root.insert(list(doc.root).index(doc.main), prod)
            doc.elements[prod.get('id')] = prod
            e.set('producer', prod.get('id'))
        for f in [c for c in prod if c.tag == 'filter']:
            if (cid in strip_text and _is_text(f)) or (cid in inject and es._get(f, ROLE_PROP) == ROLE):
                prod.remove(f)
        if cid in inject:
            el = ee.build({'filter': FILTER, 'params': inject[cid]}, doc.fps)
            el.set('id', es._new_id(doc, 'filter'))
            prod.append(el)
    if isolate is not None:
        for tr, pl, name, kind in doc.tracks():
            if kind == 'video' and name != isolate:
                tr.set('hide', 'both')
    for f in [f for f in doc.main.findall('filter') if es._get(f, 'mlt_service') == 'subtitle']:
        doc.main.remove(f)
    doc.root.set('root', str(Path(path).resolve().parent))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    doc.tree.write(out, encoding='utf-8', xml_declaration=True)
    return Path(out)


def render_times(variant, times, out_dir):
    """PNG paths of the variant's frames at timeline times (s), in order, rendered by melt in one run."""
    import letitedit.review.checks as checks
    import letitedit.timeline.timeline_model as tm
    tl = tm.load(variant)
    frames = [max(0, min(tl.frames - 1, round(t * tl.fps))) for t in times]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return checks.render_frames(tl, Path(variant), frames, out_dir)


def picture_area(row, profile, pngs):
    """(x0, y0, x1, y1) of the clip's own picture in the rendered frames, and how it was found: the fitted footage
    rectangle when the rest is a fill or bars, then flat dark borders trimmed (at most 35 % a side)."""
    from PIL import Image

    import letitedit.review.checks as checks
    ims = [Image.open(p).convert('RGB') for p in pngs]
    W, H = ims[0].size
    rect, how = (0, 0, W, H), 'whole frame'
    try:
        r = checks._picture_rect(row['item'], profile)
    except Exception:  # noqa: BLE001 - no rectangle: the whole frame
        r = None
    if r and checks._outside_is_fill(ims[:3], r):
        rect, how = tuple(int(v) for v in r), 'the footage area (fitted inside a fill or bars)'
    k = 4
    small = np.stack([np.asarray(im.crop(rect).reduce(k), np.float32) for im in ims])
    mx = small.max(axis=(0, 3))
    h, w = mx.shape

    def run(flags):
        n = 0
        while n < len(flags) and flags[n]:
            n += 1
        return n
    dark_r = np.quantile(mx, 0.99, axis=1) < 14
    dark_c = np.quantile(mx, 0.99, axis=0) < 14
    t, b = min(run(dark_r), int(0.35 * h)), min(run(dark_r[::-1]), int(0.35 * h))
    left, right = min(run(dark_c), int(0.35 * w)), min(run(dark_c[::-1]), int(0.35 * w))
    if t or b or left or right:
        x0, y0, x1, y1 = rect
        rect = (x0 + k * left, y0 + k * t, x1 - k * right, y1 - k * b)
        how += ', flat dark borders left out'
    return rect, how


def _box_mask(box, rect, shape, frame):
    """Analysis-size mask of a box given as fractions of the whole rendered frame."""
    W, H = frame
    h, w = shape[:2]
    x0, y0, x1, y1 = rect
    fx0, fy0, fx1, fy1 = (float(v) for v in box)
    cx0 = (fx0 * W - x0) / max(1, x1 - x0) * w
    cx1 = (fx1 * W - x0) / max(1, x1 - x0) * w
    cy0 = (fy0 * H - y0) / max(1, y1 - y0) * h
    cy1 = (fy1 * H - y0) / max(1, y1 - y0) * h
    m = np.zeros((h, w), bool)
    a, b = int(max(0, math.floor(min(cx0, cx1)))), int(min(w, math.ceil(max(cx0, cx1))))
    c, d = int(max(0, math.floor(min(cy0, cy1)))), int(min(h, math.ceil(max(cy0, cy1))))
    if b > a and d > c:
        m[c:d, a:b] = True
    return m


def load_pictures(pngs, times, rect, ignore=None):
    from PIL import Image
    pics = []
    for png, t in zip(pngs, times):
        im = Image.open(png).convert('RGB')
        frame = im.size
        im = im.crop(rect)
        s = ANALYSIS_LONG / max(im.size)
        if s < 1:
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BOX)
        rgb = np.asarray(im, np.float32) / 255.0
        mask = np.ones(rgb.shape[:2], bool)
        for box in ignore or []:
            mask &= ~_box_mask(box, rect, rgb.shape, frame)
        p = Picture(rgb, mask, t, str(png))
        p.frame = frame
        p.rect = rect
        pics.append(p)
    return pics


def _check_box(box, what):
    if not (isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
        raise ValueError(f'{what}: a region is [x0, y0, x1, y1] as fractions (0-1) of the frame, not {box!r}')
    if not all(-0.01 <= float(v) <= 1.01 for v in box) or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f'{what}: [x0, y0, x1, y1] must be fractions of the frame with x1 > x0 and y1 > y0, '
                         f'not {box!r}')
    return [float(v) for v in box]


def _neutral_spec(spec, cid):
    """A neutral region: [x0, y0, x1, y1] or {'box': [...], 'at_s': seconds from the clip's start}."""
    if isinstance(spec, dict):
        return _check_box(spec.get('box'), f'neutral_regions[{cid}]'), spec.get('at_s')
    return _check_box(spec, f'neutral_regions[{cid}]'), None


def effect_slots(path, script):
    """Per clip id: its effects as the edit script shows them, the indices of shot-match effects among them, and
    where the first text effect sits (a correction goes before text, so text keeps its colours)."""
    import letitedit.timeline.edit_script as es
    doc = es.Doc(path)
    where, _ = _producer_map(doc)
    items = {it['id']: it for t in script['tracks'] for it in t['items'] if 'id' in it}
    out = {}
    for cid, (e, prod, _) in where.items():
        if prod is None or cid not in items or prod.tag == 'tractor':
            continue
        uf = es._user_filters(prod)
        effects = list(items[cid].get('effects') or [])
        off = len(effects) - len(uf)
        if off < 0:
            continue
        ours = [off + k for k, f in enumerate(uf) if es._get(f, ROLE_PROP) == ROLE]
        text = [off + k for k, f in enumerate(uf) if _is_text(f)]
        out[cid] = {'effects': effects, 'ours': ours, 'text_at': min(text) if text else None}
    return out


def effects_op(cid, slot, effect):
    """{op: effects} putting `effect` in place of the clip's shot-match effect (before any text effect)."""
    effs = [e for i, e in enumerate(slot['effects']) if i not in slot['ours']]
    if effect is not None:
        pos = slot['text_at']
        if pos is None:
            effs.append(effect)
        else:
            effs.insert(pos - sum(1 for i in slot['ours'] if i < pos), effect)
    return {'op': 'effects', 'id': cid, 'effects': effs}


# ============================================================================ deciding, clip by clip

def _abstain(res, code, why):
    res.update(status='unchanged', reason=code, why=why)
    return res


def _stability(st):
    """(median-luma range in stops, grey-cast range in log units) across the clip's sampled frames."""
    lum = [f['median_luma'] for f in st['per_frame'] if f.get('median_luma')]
    lrange = DECODE_GAMMA * math.log2(max(lum) / min(lum)) if len(lum) > 1 and min(lum) > 0 else 0.0
    casts = [f['grey_cast'] for f in st['per_frame'] if f.get('grey_cast') and (f.get('grey_n') or 0) >= 100]
    crange = 0.0
    if len(casts) > 1:
        crange = max(max(c[0] for c in casts) - min(c[0] for c in casts),
                     max(c[1] for c in casts) - min(c[1] for c in casts))
    return lrange, crange


def _clip_guard(pics, gains, gamma, st, ref_blown=0.0):
    """Brightening may blow at most NEW_CLIP_BUDGET more of the picture than the reference has blown (the correction
    is scaled down until it does not); blown areas that would turn tinted or grey are noted."""
    notes = []
    g = np.asarray(gains, np.float64)
    px = np.concatenate([p.rgb[p.mask][::5] for p in pics]) if pics else np.zeros((0, 3), np.float32)
    if len(px) and float(np.max(g)) > 1.0:
        before = float((px.max(1) >= BLOWN).mean())
        budget = NEW_CLIP_BUDGET + max(0.0, float(ref_blown) - before)

        def extra(k):
            return float((apply_model(px, g ** k, gamma ** k).max(1) >= BLOWN).mean()) - before
        if extra(1.0) > budget:
            lo, hi = 0.0, 1.0
            for _ in range(14):
                mid = (lo + hi) / 2
                if extra(mid) > budget:
                    hi = mid
                else:
                    lo = mid
            g, gamma = g ** lo, gamma ** lo
            notes.append(f'scaled to {lo:.0%} of the correction so no more than {budget:.0%} more of the picture '
                         'blows out')
    if st.get('blown', 0) >= 0.03:
        white = np.minimum(1.0, g) ** (1.0 / gamma)
        if white.max() / max(1e-6, white.min()) > 1.04:
            notes.append(f"{st['blown']:.0%} of the picture is blown: those areas take a slight tint (white becomes "
                         f"RGB {tuple(round(float(v) * 255) for v in white)})")
        elif white.max() < 0.95:
            notes.append(f"{st['blown']:.0%} of the picture is blown: darkened, those areas turn light grey")
    return g.tolist(), float(gamma), notes


def _corr_summary(matches, fit, n_pairs, ref_pics, clip_pics):
    return {'frame_pairs': [{'clip_s': _r(clip_pics[f['ci']].t, 3), 'reference_s': _r(ref_pics[f['ri']].t, 3),
                             'matches': f['h']['matches'], 'inliers': f['h']['inliers'],
                             'inlier_ratio': _r(f['h']['ratio'], 3), 'overlap': _r(f['h']['overlap'], 3),
                             'aligned_share': _r(f['coords'][2], 3)}
                            for f in matches],
            'colour_pairs': int(n_pairs),
            'fit_residual': _r(fit['residual'], 4) if fit else None,
            'fit_inlier_share': _r(fit['inliers'], 3) if fit else None,
            'tone_measured': fit['tone_measured'] if fit else None,
            'rules': {'inliers': CORR_MIN_INLIERS, 'inlier_ratio': CORR_MIN_RATIO, 'overlap': CORR_MIN_OVERLAP,
                      'colour_pairs': CORR_MIN_PAIRS, 'max_residual': CORR_MAX_RESIDUAL,
                      'min_fit_inlier_share': CORR_MIN_FIT_INLIERS, 'aligned_patch_ncc': ALIGNED_NCC,
                      'tone_only_under_residual': TONE_MAX_RESIDUAL}}


def decide(tp, rp, ts, rs, cfg, sup, info):
    """The correction for one clip (pictures tp, statistics ts) toward the reference (rp, rs), or why there is none.
    Returns a dict: status 'proposed' (gains, gamma, mode) or 'unchanged' (reason, why), with evidence and notes."""
    res = {'status': 'unchanged', 'reason': None, 'why': None, 'mode': None, 'notes': [], 'evidence': {},
           'related': None}
    ev = res['evidence']
    if not sup[0]:
        return _abstain(res, sup[1], sup[2])
    if ts['measurable'] < MIN_MEASURABLE:
        return _abstain(res, 'unmeasurable', f"only {ts['measurable']:.0%} of the picture is measurable (the rest is "
                                             f'blown or crushed; at least {MIN_MEASURABLE:.0%} is needed)')
    tr = (info.get('transfer') or '').lower()
    if ts['looks'].get('flat'):
        if info.get('codec') and (tr in ('', 'unknown', 'unspecified', 'reserved') or (info.get('bits') or 8) > 8):
            return _abstain(res, 'looks_like_log', 'a flat, log-like picture (lifted blacks, low highlights, little '
                                                   'colour) from a source without a transfer tag')
        res['notes'].append('the picture looks flat (lifted blacks, little colour); the source is tagged SDR, so it '
                            'is matched as SDR')
    lrange, crange = _stability(ts)
    ev['stability'] = {'luma_range_stops': _r(lrange, 3), 'grey_cast_range': _r(crange, 4),
                       'rules': {'statistics_mode': {'abstain_over_stops': UNSTABLE_STOPS,
                                                     'half_strength_over_stops': WOBBLY_STOPS,
                                                     'abstain_over_cast': UNSTABLE_CAST},
                                 'correspondence_mode': {'abstain_over_stops': PAIRS_UNSTABLE_STOPS,
                                                         'half_strength_over_stops': PAIRS_WOBBLY_STOPS,
                                                         'abstain_over_cast': PAIRS_UNSTABLE_CAST}}}
    matches = correspond(tp, rp)
    fit = pairs = None
    if matches:
        (c, r), per_match = _pairs_of(matches, tp, rp, per_match=True)
        if len(c) >= CORR_MIN_PAIRS:
            fit = fit_pairs(c, r, tone=False)
            if 'tone' in cfg['correct'] and fit['residual'] <= TONE_MAX_RESIDUAL:   # the slope needs clean pairs
                with_tone = fit_pairs(c, r, tone=True, tone_limit=cfg['limits']['tone'])
                if with_tone['tone_measured']:
                    fit = with_tone
            if fit['residual'] <= CORR_MAX_RESIDUAL and fit['inliers'] >= CORR_MIN_FIT_INLIERS:
                res['mode'] = 'correspondence'
                pairs = (c, r)
        ev['correspondence'] = _corr_summary(matches, fit, len(c), rp, tp)
        if res['mode'] is None:
            ev['correspondence']['rejected'] = (
                'too few measurable colour pairs' if fit is None else
                'the shared surfaces do not follow one correction (residual over the limit): the light differs across '
                'the picture, not just the camera')
    else:
        ev['correspondence'] = {'frame_pairs': [], 'note': 'no frame pair showed the same surfaces (ORB features + '
                                                           'RANSAC homography)'}
    half = None                                           # why the strength is halved, if it is
    if res['mode'] == 'correspondence':
        espread, wspread, per_ex = pair_agreement(per_match)
        ev['stability'].update(frame_pairs_exposure_stops=[_r(x, 3) for x in per_ex],
                               frame_pairs_exposure_spread=_r(espread, 3), frame_pairs_wb_spread=_r(wspread, 4))
        if espread > PAIRS_UNSTABLE_STOPS or wspread > PAIRS_UNSTABLE_CAST:
            return _abstain(res, 'light_changes_in_clip',
                            f'the frame pairs need different corrections (exposure spread {espread:.2f} stop, colour '
                            f'{wspread:.3f}): the light changes inside the clip; split it and match the parts')
        if espread > PAIRS_WOBBLY_STOPS:
            half = f'the frame pairs disagree by {espread:.2f} stop'
    elif lrange > UNSTABLE_STOPS or crange > UNSTABLE_CAST:
        return _abstain(res, 'light_changes_in_clip',
                        f'the light changes inside the clip (sampled frames differ by {lrange:.2f} stop in brightness, '
                        f'{crange:.3f} in colour cast): one static correction cannot match all of it; split the clip')
    elif lrange > WOBBLY_STOPS:
        half = f'the clip brightens or darkens by {lrange:.2f} stop across its frames'
    s_all, s_chroma, s_luma = similarity(ts, rs)
    passes = s_all is not None and s_all >= SIMILARITY_MIN and s_chroma >= SIMILARITY_CHROMA_MIN
    ev['scene'] = {'similarity': _r(s_all), 'chroma_overlap': _r(s_chroma), 'contrast_overlap': _r(s_luma),
                   'passes': bool(passes), 'same_scene_given': cfg['same_scene'],
                   'rule': f'similarity >= {SIMILARITY_MIN} and chroma overlap >= {SIMILARITY_CHROMA_MIN}'}
    res['related'] = bool(res['mode'] or passes or cfg['same_scene'])
    if res['mode'] is None:
        if not (passes or cfg['same_scene']):
            return _abstain(res, 'too_different',
                            f'no shared surfaces and the scenes measure as different (similarity {s_all or 0:.2f}, '
                            f'chroma overlap {s_chroma or 0:.2f}): matching would force one scene onto another. If '
                            'they are the same scene, same_scene=True matches them gently')
        res['mode'] = 'statistics'
    lt, lr = ts['looks'], rs['looks']
    ev['looks'] = {'clip': lt, 'reference': lr}
    if cfg['keep_looks']:
        if lt['golden'] != lr['golden']:
            who = 'this clip has' if lt['golden'] else 'the reference has'
            return _abstain(res, 'intentional_look', f'{who} warm low-sun light (golden hour or sunset: lit neutral '
                                                      'surfaces warm, shaded ones cooler) and the other does not; '
                                                      'matching would remove or add it. keep_looks=False matches anyway')
        if lt['night'] != lr['night']:
            who = 'this clip' if lt['night'] else 'the reference'
            return _abstain(res, 'intentional_look', f'{who} is a night picture (dark with small bright lights) and '
                                                      'the other is not. keep_looks=False matches anyway')
    if res['mode'] == 'correspondence':
        gains, gamma = list(fit['gains']), float(fit['gamma'])
        if 'neutral region' in (ts['neutral_source'], rs['neutral_source']) and ts['grey_cast'] and rs['grey_cast']:
            d = decompose(gains, gamma)
            gains, gamma = compose(d['exposure_stops'], wb_from_casts(ts['grey_cast'], rs['grey_cast']), gamma)
            res['notes'].append('white balance from the neutral region')
    else:
        def wb_ok(st):
            return st['neutral_source'] == 'neutral region' or (
                (st['grey_n'] or 0) >= GREY_MIN_PIXELS and (st['grey_spread'] if st['grey_spread'] is not None else 1)
                <= GREY_MAX_SPREAD)
        ev['white_balance'] = {'clip': {'source': ts['neutral_source'], 'grey_pixels': ts['grey_n'],
                                        'spread': _r(ts['grey_spread'], 4)},
                               'reference': {'source': rs['neutral_source'], 'grey_pixels': rs['grey_n'],
                                             'spread': _r(rs['grey_spread'], 4)},
                               'rule': f'at least {GREY_MIN_PIXELS} grey pixels spread at most {GREY_MAX_SPREAD}'}
        if ts['grey_cast'] and rs['grey_cast'] and wb_ok(ts) and wb_ok(rs):
            wb = wb_from_casts(ts['grey_cast'], rs['grey_cast'])
        else:
            wb = [1.0, 1.0, 1.0]
            res['notes'].append('white balance left alone: too few neutral surfaces, or mixed light (the grey pixels '
                                'disagree); a neutral region would measure it')
        lg, used = exposure_from_quantiles(ts, rs)
        ev['exposure'] = {'quantile_levels_used': used}
        if lg is None:
            ex = 0.0
            res['notes'].append('exposure left alone: too few brightness levels are unclipped in both pictures')
        else:
            ex = lg * DECODE_GAMMA / math.log(2)
        gains, gamma = compose(ex, wb, 1.0)
    need = decompose(gains, gamma)
    res['needed'] = {'exposure_stops': _r(need['exposure_stops'], 3), 'red_vs_green_pct': _r(100 * need['red_vs_green'], 2),
                     'blue_vs_green_pct': _r(100 * need['blue_vs_green'], 2), 'gamma': _r(need['gamma'], 4)}
    full, full_gamma, _, over = bound(gains, gamma, cfg['limits'], cfg['correct'], 1.0)
    if over:
        return _abstain(res, 'difference_too_large',
                        f"the {' and '.join(o.replace('_', ' ') for o in over)} difference is more than twice its limit "
                        f"(needed {describe_correction(gains, gamma)}): more likely different light or an intended "
                        'look than a camera mismatch. Raise limits to match it anyway')
    if negligible(full, full_gamma):
        return _abstain(res, 'already_matched', f'already matches within the noise ({describe_correction(full, full_gamma)})')
    s = cfg['strength'] * (STATS_STRENGTH if res['mode'] == 'statistics' else 1.0)
    if res['mode'] == 'statistics':
        res['notes'].append(f'statistics mode: {STATS_STRENGTH:.0%} of the estimate applied (gentle)')
    if half:
        s *= 0.5
        res['notes'].append(f'{half}: half strength')
    gains, gamma, notes, _ = bound(gains, gamma, cfg['limits'], cfg['correct'], s)
    res['notes'] += notes
    gains, gamma, notes = _clip_guard(tp, gains, gamma, ts, rs.get('blown', 0.0))
    res['notes'] += notes
    g = np.clip(np.asarray(gains), 0.5, 2.0)
    if not np.allclose(g, gains):
        res['notes'].append("gains kept inside the Color Grading filter's range (0.5-2)")
    gains = g.tolist()
    gamma = min(2.0, max(0.5, gamma))
    if negligible(gains, gamma):
        return _abstain(res, 'negligible', f'after limits and strength the correction is too small to matter '
                                           f'({describe_correction(gains, gamma)})')
    res.update(status='proposed', gains=[float(x) for x in gains], gamma=float(gamma), pairs=pairs, matches=matches)
    return res


def improved(before, after):
    """True when the headline difference got clearly smaller (at least 5 % and 0.1)."""
    hb, ha = headline(before), headline(after)
    return ha <= hb * 0.95 and ha <= hb - 0.1


# ============================================================================ settings, previews, plans

def settings(frames=5, strength=1.0, limits=None, correct=None, same_scene=False, keep_looks=True):
    lim = dict(DEFAULT_LIMITS)
    for k, v in (limits or {}).items():
        if k not in lim:
            raise ValueError(f'limits: unknown key {k!r}; the keys are {", ".join(lim)}')
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f'limits.{k} must be a number >= 0, not {v!r}')
        lim[k] = float(v)
    if lim['exposure_stops'] > 2.0 or lim['white_balance'] > 0.5 or lim['tone'] > 0.5:
        raise ValueError("limits: at most exposure_stops 2, white_balance 0.5, tone 0.5 (the Color Grading filter's "
                         'gains and gamma run 0.5-2)')
    corr = list(correct) if correct else list(CORRECTIONS)
    bad = [c for c in corr if c not in CORRECTIONS]
    if bad:
        raise ValueError(f'correct: unknown {", ".join(map(str, bad))}; use any of {", ".join(CORRECTIONS)}')
    if not isinstance(frames, int) or not 1 <= frames <= 12:
        raise ValueError('frames: 1-12 frames per clip')
    strength = float(strength)
    if not 0.0 < strength <= 1.0:
        raise ValueError('strength: more than 0 and at most 1')
    return {'frames': frames, 'strength': strength, 'limits': lim, 'correct': corr, 'same_scene': bool(same_scene),
            'keep_looks': bool(keep_looks)}


def _font(size, bold=False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def preview_sheet(rows, out_base, title, tile_h=300, per_page=6):
    """JPEG pages: per clip one row [reference | before | after] cut to the picture area, with the numbers under it.
    rows: [{'tiles': [(label, png or None, rect)], 'lines': [str, ...]}]. Returns the page paths."""
    from PIL import Image, ImageDraw
    f, fb = _font(15), _font(16, True)
    pages = []
    for k in range(0, len(rows), per_page):
        built = []
        for row in rows[k:k + per_page]:
            tiles = []
            for label, png, rect in row['tiles']:
                if png:
                    im = Image.open(png).convert('RGB').crop(rect)
                    im = im.resize((max(1, round(im.width * tile_h / im.height)), tile_h), Image.LANCZOS)
                else:
                    im = Image.new('RGB', (round(tile_h * 0.6), tile_h), (44, 44, 48))
                    ImageDraw.Draw(im).text((10, tile_h // 2 - 8), 'no change', fill=(200, 200, 200), font=fb)
                d = ImageDraw.Draw(im)
                w = int(d.textlength(label, font=f)) + 10
                d.rectangle((0, 0, w, 20), fill=(0, 0, 0))
                d.text((5, 2), label, fill=(255, 225, 0), font=f)
                tiles.append(im)
            width = sum(t.width for t in tiles) + 6 * (len(tiles) - 1)
            text_h = 8 + 20 * len(row['lines'])
            measure = ImageDraw.Draw(tiles[0])
            width = max(width, max(int(measure.textlength(ln, font=fb if i == 0 else f)) + 12
                                   for i, ln in enumerate(row['lines'])))
            canvas = Image.new('RGB', (width, tile_h + text_h), (24, 24, 28))
            x = 0
            for t in tiles:
                canvas.paste(t, (x, 0))
                x += t.width + 6
            d = ImageDraw.Draw(canvas)
            for i, ln in enumerate(row['lines']):
                d.text((6, tile_h + 4 + 20 * i), ln, fill=(235, 235, 235) if i else (255, 255, 255), font=fb if i == 0 else f)
            built.append(canvas)
        W = max(b.width for b in built)
        H = sum(b.height for b in built) + 12 * len(built) + 34
        page = Image.new('RGB', (W, H), (16, 16, 18))
        ImageDraw.Draw(page).text((8, 8), title + (f'  (page {k // per_page + 1})' if len(rows) > per_page else ''),
                                  fill=(255, 255, 255), font=fb)
        y = 34
        for b in built:
            page.paste(b, (0, y))
            y += b.height + 12
        out = Path(f'{out_base}{"" if k == 0 else f"_{k // per_page + 1}"}.jpg')
        page.save(out, 'JPEG', quality=86)
        pages.append(str(out))
    return pages


def _plan_file(plan_id):
    if not re.fullmatch(r'[0-9a-f]{8,40}', str(plan_id or '')):
        raise ValueError(f'plan_id {plan_id!r} is not a shot-match plan id')
    return CACHE / 'plans' / f'{plan_id}.json'


def load_plan(plan_id):
    f = _plan_file(plan_id)
    if not f.exists():
        raise ValueError(f'No shot-match plan {plan_id} (plans are kept in {f.parent})')
    return json.loads(f.read_text(encoding='utf-8-sig'))


def _save_plan(report, suffix=''):
    f = _plan_file(report['plan_id'])
    if suffix:
        f = f.with_name(f'{f.stem}{suffix}.json')
    f.parent.mkdir(parents=True, exist_ok=True)
    report['report_file'] = str(f)
    f.write_text(json.dumps(report, indent=1), encoding='utf-8')
    return str(f)


BRIEF_METRICS = ('pairs_delta_e', 'pairs_exposure_stops', 'pairs_red_vs_green_pct', 'pairs_blue_vs_green_pct',
                 'exposure_stops', 'red_vs_green_pct', 'blue_vs_green_pct', 'neutral_delta_e', 'skin_delta_e',
                 'skin_hue_deg', 'skin_hue_ref_deg')


def brief(report):
    """The report without its bulk (per-frame evidence, frame lists, sampled ranges): what an agent reads first. The
    whole report is in report['report_file']."""
    keep = ('schema_version', 'tool', 'mode', 'project', 'project_revision', 'plan_id', 'summary', 'changes',
            'warnings', 'unsupported', 'applied', 'how_to', 'report_file', 'seconds', 'removed_from', 'note')
    out = {k: report[k] for k in keep if k in report}
    if report.get('preview_artifacts'):
        out['preview_sheets'] = report['preview_artifacts'].get('sheets')
    if report.get('reference'):
        ref = report['reference']
        out['reference'] = {k: ref.get(k) for k in ('id', 'file', 'timeline_s') if ref.get(k) is not None}
    clips = []
    for e in report.get('clips') or []:
        c = {k: e[k] for k in ('id', 'status', 'reason', 'why', 'mode', 'timeline_s', 'source_s') if e.get(k) is not None}
        if e.get('correction'):
            c['correction'] = {k: e['correction'][k] for k in ('text', 'exposure_stops', 'red_vs_green_pct',
                                                               'blue_vs_green_pct', 'gamma')}
        for k in ('measured_before', 'measured_after'):
            if e.get(k):
                c[k] = {m: e[k][m] for m in BRIEF_METRICS if e[k].get(m) is not None}
        for k in ('headline', 'notes', 'written_check'):
            if e.get(k):
                c[k] = e[k] if k != 'written_check' else {'max_mean_abs_diff_0_255': e[k].get('max_mean_abs_diff_0_255')}
        ev = e.get('evidence') or {}
        small = {}
        if ev.get('scene'):
            small['scene_similarity'] = ev['scene'].get('similarity')
            small['chroma_overlap'] = ev['scene'].get('chroma_overlap')
        corr = ev.get('correspondence') or {}
        if corr.get('frame_pairs'):
            small['shared_surfaces'] = {'frame_pairs': len(corr['frame_pairs']),
                                        'best_inliers': max(p['inliers'] for p in corr['frame_pairs']),
                                        'fit_residual': corr.get('fit_residual')}
        if small:
            c['evidence'] = small
        clips.append(c)
    if clips:
        out['clips'] = clips
    return out


def _fingerprints(files):
    import letitedit.footage.footage_notes as footage_notes
    out = {}
    for fpath in sorted({str(x) for x in files if x}):
        try:
            out[fpath] = footage_notes.key(fpath)
        except OSError:
            out[fpath] = None
    return out


def editor_state(path):
    """The letitedit window that has this project open ({'instance_id', 'modified', ...}) or None (read-only lookup)."""
    try:
        import letitedit.server.timeline_tools as timeline_tools
        return timeline_tools._live_state(path)
    except Exception:  # noqa: BLE001 - no editor running is normal
        return None


def current(path):
    """(file to measure, revision, read) of the project as it is now (T298): an open letitedit window's timeline,
    unsaved changes included (its revision), else the saved file (its hash). read says which (live_edit.state_of)."""
    import letitedit.app.live_edit as live_edit
    import letitedit.timeline.edit_script as es
    source, state = live_edit.current(path)
    read = {k: v for k, v in state.items() if k != 'project'}
    if read['state'] == 'live':
        return source, f"live:{read.get('window')}:{read.get('revision') or ''}", read
    return path, es.file_hash(path), read


def write_changes(path, changes, label):
    """Through the shared apply path (letitedit_timeline_apply's): one undo step in an open letitedit window (its
    unsaved changes kept, nothing saved or reloaded), else the saved file with a history copy for
    letitedit_timeline_undo. The measurements were made from the same state (current)."""
    import letitedit.server.timeline_tools as timeline_tools
    result, _ = timeline_tools.apply_project(str(path), changes=changes, check=False, label=label)
    return result


def _label(label, text):
    if label:
        return label
    try:
        import letitedit.timeline.project_journal as pj
        return f'{pj.label_prefix()}: {text}'
    except Exception:  # noqa: BLE001
        return f'letitedit: {text}'


# ============================================================================ the tool

def _entry(row):
    it = row['item']
    e = {'id': row['id'], 'file': row['file'], 'track': row['track'],
         'timeline_s': [_r(row['start'], 3), _r(row['end'], 3)], 'status': 'skipped', 'reason': None, 'why': None}
    if 'in' in it and 'out' in it:
        import letitedit.timeline.edit_script as es
        e['source_s'] = [_r(es.to_seconds(it['in']), 3), _r(es.to_seconds(it['out']), 3)]
    return e


def _correction_view(gains, gamma, mode):
    d = decompose(gains, gamma)
    return {'exposure_stops': _r(d['exposure_stops'], 3), 'red_vs_green_pct': _r(100 * d['red_vs_green'], 2),
            'blue_vs_green_pct': _r(100 * d['blue_vs_green'], 2), 'gamma': _r(gamma, 4),
            'gains': [_r(g, 4) for g in gains], 'mode': mode, 'text': describe_correction(gains, gamma)}


def _pairs_after(matches, after_pics, ref_pics):
    return _pairs_of(matches, after_pics, ref_pics) if matches else None


def _frame_diff(a_pngs, b_pngs):
    """Mean absolute difference (0-255) between two sets of renders of the same frames."""
    from PIL import Image
    diffs = []
    for a, b in zip(a_pngs, b_pngs):
        x = np.asarray(Image.open(a).convert('RGB'), np.float32)
        y = np.asarray(Image.open(b).convert('RGB'), np.float32)
        if x.shape != y.shape:
            return None
        diffs.append(float(np.abs(x - y).mean()))
    return max(diffs) if diffs else None


def _match_candidates(tl, ref, cands, exclude, reference):
    """Check candidate and reference colour support before measuring."""
    prof_ok, prof_why = profile_support(tl.profile)
    ref_info = source_colour(ref['file']) if ref['kind'] == 'video' else {}
    ref_sup = support(ref_info, ref['kind'])
    entries, infos, sups, measure = {}, {}, {}, []
    for r in cands:
        e = _entry(r)
        entries[r['id']] = e
        if r['id'] in exclude:
            e.update(reason='excluded', why='excluded by request')
        elif not r['footage']:
            e.update(reason='not_footage', why=f"a {r['kind']} item, not camera footage")
        else:
            infos[r['id']] = source_colour(r['file']) if r['kind'] == 'video' else {}
            sups[r['id']] = support(infos[r['id']], r['kind'])
            e['status'] = 'unchanged'
            if not prof_ok:
                e.update(reason='project_unsupported', why=prof_why)
            elif not ref_sup[0]:
                e.update(reason='reference_unsupported', why=f'the reference {reference}: {ref_sup[2]}')
            elif not sups[r['id']][0]:
                e.update(reason=sups[r['id']][1], why=sups[r['id']][2])
            else:
                measure.append(r)
    return entries, infos, sups, measure


def _measure_match_sources(ref, measure, cfg, neutral, tl, path, work, reference, ignore, entries):
    """Render and measure source pictures, including requested neutral regions."""
    # ---- measure: one melt run per track, only that track visible, a neutral effect on every clip to correct
    times, extra = {}, {}
    for r in [ref] + measure:
        times[r['id']] = sample_times(r, cfg['frames'])
        if r['id'] in neutral and neutral[r['id']][1] is not None:
            at = r['start'] + float(neutral[r['id']][1])
            extra[r['id']] = min(max(at, r['start']), r['end'] - 1.0 / tl.fps)
    by_track = {}
    for r in ([ref] + measure) if measure else []:
        by_track.setdefault(r['track'], []).append(r)
    shots = {}
    for k, (track, trs) in enumerate(by_track.items()):
        var = build_variant(path, work / f'before-{k}.mlt', inject={r['id']: IDENTITY for r in trs if r['id'] != reference},
                            strip_text=[r['id'] for r in trs], isolate=track)
        ts_all, owner = [], []
        for r in trs:
            ts_all += times[r['id']]
            owner += [(r['id'], 's')] * len(times[r['id']])
            if r['id'] in extra:
                ts_all.append(extra[r['id']])
                owner.append((r['id'], 'n'))
        for (cid, kind), png in zip(owner, render_times(var, ts_all, work / f'before-{k}')):
            shots.setdefault(cid, {'s': [], 'n': []})[kind].append(str(png))
    pics, stats, areas = {}, {}, {}
    for r in ([ref] + measure) if measure else []:
        cid = r['id']
        rect, how = picture_area(r, tl.profile, shots[cid]['s'])
        areas[cid] = {'rect': list(rect), 'how': how}
        pics[cid] = load_pictures(shots[cid]['s'], times[cid], rect, ignore.get(cid))
        npics = None
        if cid in neutral:
            box = neutral[cid][0]
            if cid in extra:
                p = load_pictures(shots[cid]['n'], [extra[cid]], rect, ignore.get(cid))[0]
                npics = [(p, _box_mask(box, rect, p.rgb.shape, p.frame))]
            else:
                npics = [(p, _box_mask(box, rect, p.rgb.shape, p.frame)) for p in pics[cid]]
        stats[cid] = clip_stats(pics[cid], npics)
    ref_stats = stats.get(reference)
    if ref_stats and ref_stats['measurable'] < MIN_MEASURABLE:
        for r in measure:
            entries[r['id']].update(reason='reference_unmeasurable', why=f"only {ref_stats['measurable']:.0%} of the "
                                    'reference picture is measurable (blown or crushed): choose another reference')
        measure = []
    return times, extra, by_track, shots, pics, stats, areas, ref_stats, measure


def _render_match_proposals(decisions, by_track, path, work, times):
    """Render each proposed correction for the second measurement."""
    proposed = [cid for cid, d in decisions.items() if d['status'] == 'proposed']
    after = {}
    for k, (track, trs) in enumerate(by_track.items()):
        mine = [r['id'] for r in trs if r['id'] in proposed]
        if not mine:
            continue
        var = build_variant(path, work / f'after-{k}.mlt',
                            inject={cid: filter_params(decisions[cid]['gains'], decisions[cid]['gamma'], {})
                                    for cid in mine},
                            strip_text=mine, isolate=track)
        ts_all, owner = [], []
        for cid in mine:
            ts_all += times[cid]
            owner += [cid] * len(times[cid])
        for cid, png in zip(owner, render_times(var, ts_all, work / f'after-{k}')):
            after.setdefault(cid, []).append(str(png))
    return after


def _match_previews(reference, times, entries, areas, shots, work, plan_id):
    """Build before and after preview rows from the measured decisions."""
    # ---- previews
    ref_mid = len(times[reference]) // 2 if reference in times else 0
    sheet_rows = []
    for cid in [c for c in entries if entries[c].get('measured_before') is not None]:
        e = entries[cid]
        mid = len(times[cid]) // 2
        ri = ref_mid
        pairs = (e.get('evidence') or {}).get('correspondence', {}).get('frame_pairs') or []
        if pairs:
            ri = times[reference].index(pairs[0]['reference_s']) if pairs[0]['reference_s'] in times[reference] else ref_mid
            mid = times[cid].index(pairs[0]['clip_s']) if pairs[0]['clip_s'] in times[cid] else mid
        rr, cr = tuple(areas[reference]['rect']), tuple(areas[cid]['rect'])
        short = lambda t: f'{int(t // 60)}:{t % 60:04.1f}'
        tiles = [(f'ref {reference} {short(times[reference][ri])}', shots[reference]['s'][ri], rr),
                 (f'before {cid} {short(times[cid][mid])}', shots[cid]['s'][mid], cr),
                 ('after (proposed)' if e['status'] == 'proposed' else 'after: no change',
                  e['after_pngs'][mid] if e['status'] == 'proposed' else None, cr)]
        if e['status'] == 'proposed':
            mb, ma = e['measured_before'], e['measured_after']
            lines = [f"{cid}: {e['correction']['text']}  [{e['mode']}]"]
            if mb.get('pairs_delta_e') is not None:
                lines.append(f"same surfaces: dE {mb['pairs_delta_e']} -> {ma.get('pairs_delta_e')};  exposure "
                             f"{mb.get('pairs_exposure_stops')} -> {ma.get('pairs_exposure_stops')} stop;  red/green "
                             f"{mb.get('pairs_red_vs_green_pct')} -> {ma.get('pairs_red_vs_green_pct')} %;  blue/green "
                             f"{mb.get('pairs_blue_vs_green_pct')} -> {ma.get('pairs_blue_vs_green_pct')} %")
            else:
                lines.append(f"whole picture: exposure {mb.get('exposure_stops')} -> {ma.get('exposure_stops')} stop;  "
                             f"neutral dE {mb.get('neutral_delta_e')} -> {ma.get('neutral_delta_e')};  red/green "
                             f"{mb.get('red_vs_green_pct')} -> {ma.get('red_vs_green_pct')} %;  blue/green "
                             f"{mb.get('blue_vs_green_pct')} -> {ma.get('blue_vs_green_pct')} %")
            key = [n for n in e.get('notes') or [] if any(w in n for w in ('blown', 'limited', 'half strength', 'scaled'))]
            if key:
                lines.append('note: ' + key[0][:140])
        else:
            lines = [f"{cid}: unchanged ({e['reason']})", (e['why'] or '')[:150]]
        sheet_rows.append({'tiles': tiles, 'lines': lines})
        e['preview'] = {'reference_png': tiles[0][1], 'before_png': tiles[1][1], 'after_png': tiles[2][1]}
    sheets = preview_sheet(sheet_rows, work / 'sheet', f'Shot match to {reference}: plan {plan_id}') if sheet_rows else []
    return sheets


def match(project, reference=None, clips=None, frames=5, strength=1.0, limits=None, correct=None, same_scene=False,
          keep_looks=True, neutral_regions=None, ignore_regions=None, exclude=None, apply=False, plan_id=None,
          remove=False, label=None, work_dir=None):
    """See the module doc and shot_match_tools.letitedit_match_shots. Returns the report (a dict); the preview sheet
    paths are in report['preview_artifacts']['sheets']."""
    started = time.monotonic()
    path = _resolve(project)
    if remove:
        return remove_matching(path, clips, label=label)
    if plan_id:
        plan = load_plan(plan_id)
        if Path(plan['project']).resolve() != Path(path).resolve():
            raise ValueError(f"plan {plan_id} is for {plan['project']}, not {path}")
        if not apply:
            plan['note'] = 'a stored proposal, not written; apply=True writes it if the project has not changed'
            return plan
        return apply_plan(path, plan, label=label)
    if not reference:
        raise ValueError('reference: the id of the clip the others should look like (letitedit_timeline_read lists ids)')
    cfg = settings(frames, strength, limits, correct, same_scene, keep_looks)
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.timeline_model as tm
    source, revision, read = current(path)     # an open window as it is now, unsaved changes included (T298)
    script = es.read(source)
    tl = tm.load(source)
    rows = timeline_clips(script)
    by_id = {r['id']: r for r in rows}
    if reference not in by_id:
        raise ValueError(f'No clip {reference!r} on a video track (ids: {", ".join(list(by_id)[:30])})')
    ref = by_id[reference]
    if not ref['footage']:
        raise ValueError(f'{reference} is a {ref["kind"]} item; the reference must be camera footage (a video or photo)')
    group = 'scene' if clips is None else clips
    if isinstance(group, str):
        if group not in ('scene', 'track'):
            raise ValueError("clips: a list of clip ids, 'scene' (the reference's neighbours on its track that measure "
                             "as the same scene) or 'track' (every clip on the reference's track)")
        cands = [r for r in rows if r['track'] == ref['track'] and r['id'] != reference]
    else:
        unknown = [c for c in group if c not in by_id]
        if unknown:
            raise ValueError(f'No clip {", ".join(map(repr, unknown))} on a video track')
        cands = [by_id[c] for c in dict.fromkeys(group) if c != reference]
    warnings = []
    if len(cands) > MAX_CLIPS:
        warnings.append(f'{len(cands)} clips asked for; the first {MAX_CLIPS} are measured, run again for the rest')
        cands = cands[:MAX_CLIPS]
    exclude = set(exclude or [])
    neutral = {cid: _neutral_spec(spec, cid) for cid, spec in (neutral_regions or {}).items()}
    ignore = {cid: [_check_box(b, f'ignore_regions[{cid}]') for b in boxes] for cid, boxes in (ignore_regions or {}).items()}
    for cid in list(neutral) + list(ignore):
        if cid not in by_id:
            raise ValueError(f'neutral_regions/ignore_regions: no clip {cid!r}')
    work = Path(work_dir) if work_dir else CACHE / 'runs' / f'{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
    work.mkdir(parents=True, exist_ok=True)

    entries, infos, sups, measure = _match_candidates(tl, ref, cands, exclude, reference)

    times, extra, by_track, shots, pics, stats, areas, ref_stats, measure = _measure_match_sources(ref, measure, cfg, neutral, tl, source, work, reference, ignore, entries)

    # ---- decide, then render the proposals and measure them again
    decisions = {}
    for r in measure:
        cid = r['id']
        decisions[cid] = decide(pics[cid], pics[reference], stats[cid], ref_stats, cfg, sups[cid], infos[cid])
    if group == 'scene':
        order = [r for r in rows if r['track'] == ref['track']]
        pos = next(i for i, r in enumerate(order) if r['id'] == reference)
        inside = set()
        for step in (-1, 1):
            i = pos + step
            while 0 <= i < len(order):
                cid = order[i]['id']
                # unknown (not measured: unsupported, excluded, not footage) does not end the scene; different does,
                # and keeps its own reason (too_different)
                if cid in decisions and decisions[cid]['related'] is False:
                    inside.add(cid)
                    break
                inside.add(cid)
                i += step
        for cid, e in entries.items():
            if cid not in inside:
                e.update(status='skipped', reason='outside_scene',
                         why="not in the reference's scene group (a neighbour between it and the reference measured as "
                             "a different scene); pass clips=[ids] or 'track' to include it")
                decisions.pop(cid, None)
    after = _render_match_proposals(decisions, by_track, source, work, times)

    # ---- report
    final = []
    for cid, d in decisions.items():
        e = entries[cid]
        e.update(status=d['status'], reason=d['reason'], why=d['why'], mode=d['mode'], notes=d['notes'],
                 evidence=d['evidence'], frames_s=times[cid], picture_area=areas[cid])
        if d.get('needed'):
            e['needed'] = d['needed']
        before_d = differences(stats[cid], ref_stats, d.get('pairs'))
        e['measured_before'] = before_d
        if d['status'] != 'proposed':
            continue
        apics = load_pictures(after[cid], times[cid], tuple(areas[cid]['rect']), ignore.get(cid))
        ast = clip_stats(apics, None if cid not in neutral or cid in extra else
                         [(p, _box_mask(neutral[cid][0], tuple(areas[cid]['rect']), p.rgb.shape, p.frame)) for p in apics])
        if cid in neutral and cid in extra:      # the neutral frame was not re-rendered: keep the measured cast shift
            shift = np.log(np.asarray(apply_model(np.array([[0.45, 0.45, 0.45]]), d['gains'], d['gamma'])[0]) / 0.45)
            ast['grey_cast'] = (stats[cid]['grey_cast'][0] + float(shift[0] - shift[1]),
                                stats[cid]['grey_cast'][1] + float(shift[2] - shift[1]))
        pa = _pairs_after(d.get('matches'), apics, pics[reference]) if d['mode'] == 'correspondence' else None
        after_d = differences(ast, ref_stats, pa)
        e['measured_after'] = after_d
        e['headline'] = {'metric': 'pairs_delta_e' if before_d.get('pairs_delta_e') is not None else
                         'neutral_delta_e + 4 x |exposure_stops|', 'before': _r(headline(before_d), 3),
                         'after': _r(headline(after_d), 3)}
        e['correction'] = _correction_view(d['gains'], d['gamma'], d['mode'])
        e['after_pngs'] = after[cid]
        if not improved(before_d, after_d):
            e.update(status='unchanged', reason='no_measured_improvement',
                     why=f"rendered and measured again, the difference did not get clearly smaller "
                         f"({e['headline']['before']} -> {e['headline']['after']}); left alone")
            e.pop('correction')
            continue
        final.append(cid)
    slots = effect_slots(source, script)
    corrections = {cid: [round(g, 4) for g in decisions[cid]['gains']] + [round(decisions[cid]['gamma'], 4)]
                   for cid in final if cid in slots}
    plan_core = {'project': str(path), 'revision': revision, 'reference': reference, 'settings': cfg,
                 'corrections': corrections, 'algorithm': ALGORITHM}
    plan_id = hashlib.sha1(json.dumps(plan_core, sort_keys=True).encode()).hexdigest()[:12]
    for cid in [c for c in final if c not in slots]:
        final.remove(cid)
        entries[cid].update(status='unchanged', reason='not_editable',
                            why="its effects could not be lined up with the project file's filters; nothing written")
        entries[cid].pop('correction', None)
    changes = []
    made_at = time.strftime('%Y-%m-%d %H:%M')
    for cid in final:
        d = decisions[cid]
        cv = entries[cid]['correction']
        info = {'v': SCHEMA_VERSION, 'reference': reference, 'mode': d['mode'], 'plan': plan_id, 'made': made_at,
                'exposure_stops': cv['exposure_stops'], 'red_vs_green_pct': cv['red_vs_green_pct'],
                'blue_vs_green_pct': cv['blue_vs_green_pct'], 'gamma': cv['gamma']}
        changes.append(effects_op(cid, slots[cid], {'filter': FILTER, 'params': filter_params(d['gains'], d['gamma'], info)}))
        entries[cid]['status'] = 'proposed'

    sheets = _match_previews(reference, times, entries, areas, shots, work, plan_id)

    report = _report(path, revision, plan_id, reference, ref, ref_stats, times, areas, entries, changes, cfg, sheets,
                     work, warnings, [ref['file']] + [entries[c]['file'] for c in entries], started)
    report['read'] = read
    for e in report['clips']:
        frames_after = e.pop('after_pngs', None)
        if frames_after and e['status'] == 'proposed':
            e.setdefault('preview', {})['after_frames'] = frames_after
    _save_plan(report)
    if apply:
        return apply_plan(path, report, label=label)
    return report


def _report(path, revision, plan_id, reference, ref, ref_stats, times, areas, entries, changes, cfg, sheets, work,
            warnings, files, started):
    clips = list(entries.values())
    n_prop = sum(1 for e in clips if e['status'] == 'proposed')
    reasons = {}
    for e in clips:
        if e['status'] != 'proposed':
            reasons[e['reason']] = reasons.get(e['reason'], 0) + 1
    summary = (f'{n_prop} of {len(clips)} clip(s) would be corrected toward {reference}'
               + (f"; left alone: {', '.join(f'{k} x{v}' for k, v in reasons.items())}" if reasons else ''))
    findings, checked, unchecked, unsupported = [], [], [], []
    for e in clips:
        if e.get('frames_s'):
            fs = e['frames_s']
            checked.append({'clip': e['id'], 'timeline_s': [fs[0], fs[-1]], 'frames_s': fs})
            unchecked.append({'clip': e['id'], 'timeline_s': [e['timeline_s'][0], fs[0]], 'why': 'before the first sample'})
            unchecked.append({'clip': e['id'], 'timeline_s': [fs[-1], e['timeline_s'][1]], 'why': 'after the last sample'})
        else:
            unchecked.append({'clip': e['id'], 'timeline_s': e['timeline_s'], 'why': e['reason'] or 'not measured'})
        if e['reason'] in ('unsupported_hdr', 'unsupported_log', 'unsupported_wide_gamut', 'unverified_transfer',
                           'looks_like_log', 'project_unsupported', 'reference_unsupported', 'unreadable'):
            unsupported.append({'clip': e['id'], 'reason': e['reason'], 'why': e['why']})
        text = (f"{e['correction']['text']} ({e['mode']}; difference {e['headline']['before']} -> {e['headline']['after']})"
                if e['status'] == 'proposed' else f"{e['status']}: {e['reason']}")
        findings.append({'clip': e['id'], 'timeline_s': e['timeline_s'], 'source_s': e.get('source_s'), 'text': text})
    if ref_stats and reference in times:
        fs = times[reference]
        checked.insert(0, {'clip': reference, 'timeline_s': [fs[0], fs[-1]], 'frames_s': fs, 'reference': True})
    ref_view = {'id': reference, 'file': ref['file'], 'timeline_s': [_r(ref['start'], 3), _r(ref['end'], 3)],
                'frames_s': times.get(reference), 'picture_area': areas.get(reference)}
    if ref_stats:
        ref_view['measurements'] = {'median_luma': _r(ref_stats['median_luma'], 4), 'blown': _r(ref_stats['blown'], 4),
                                    'crushed': _r(ref_stats['crushed'], 4), 'measurable': _r(ref_stats['measurable'], 3),
                                    'grey_cast_log_rg_bg': [_r(x, 4) for x in ref_stats['grey_cast']] if ref_stats['grey_cast'] else None,
                                    'neutral_source': ref_stats['neutral_source'], 'looks': ref_stats['looks']}
    return {
        'schema_version': SCHEMA_VERSION, 'tool': 'letitedit_match_shots', 'algorithm': ALGORITHM, 'mode': 'proposal',
        'project': str(path), 'project_revision': revision, 'plan_id': plan_id, 'summary': summary,
        'reference': ref_view, 'clips': clips, 'changes': changes,
        'preview_artifacts': {'sheets': sheets, 'folder': str(work),
                              'what': 'per clip: reference | before | after, each the clip\'s own picture rendered by '
                                      'melt with only its track showing'},
        'findings': findings, 'checked_ranges': checked, 'unchecked_ranges': unchecked,
        'warnings': warnings + ['measured at the sampled frames only; frames between them were not checked'],
        'unsupported': unsupported, 'source_fingerprints': _fingerprints(files),
        'settings': {**cfg, 'thresholds': {'similarity': SIMILARITY_MIN, 'chroma_overlap': SIMILARITY_CHROMA_MIN,
                                            'stats_strength': STATS_STRENGTH, 'blown': BLOWN, 'measured_range': [LO, HI],
                                            'new_blown_budget': NEW_CLIP_BUDGET}},
        'how_to': {'apply': f"letitedit_match_shots(project, plan_id='{plan_id}', apply=True)",
                   'undo': 'letitedit_timeline_undo(project) after applying (or Ctrl+Z in the open window)',
                   'remove': "letitedit_match_shots(project, remove=True, clips=[ids]) takes the shot-match effects off",
                   'edit': "the effect is a Color Grading filter ({filter: color}) on the clip: change gain_*/gamma_* "
                           'with letitedit_timeline_apply or in the filter panel'},
        'seconds': _r(time.monotonic() - started, 1),
    }


def apply_plan(path, plan, label=None):
    """Write a proposal (a report from match) if the project and its sources have not changed since it was made; then
    render the written clips and check they are the frames that were previewed."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.footage_notes as footage_notes
    _, now_rev, _ = current(path)
    if now_rev != plan['project_revision']:
        raise StalePlan(f"the project changed since plan {plan['plan_id']} was measured (revision "
                        f"{plan['project_revision']} -> {now_rev}); run letitedit_match_shots again")
    for f, key in (plan.get('source_fingerprints') or {}).items():
        try:
            now = footage_notes.key(f)
        except OSError:
            now = None
        if now != key:
            raise StalePlan(f'{f} changed (or is missing) since plan {plan["plan_id"]} was measured; run again')
    report = copy.deepcopy(plan)
    report['mode'] = 'applied'
    if not plan['changes']:
        report['applied'] = {'written': False, 'why': 'nothing to change'}
        _save_plan(report, '-applied')
        return report
    n = len(plan['changes'])
    result = write_changes(path, plan['changes'], _label(label, f"match {n} shot{'s' if n != 1 else ''} to "
                                                               f"{plan['reference']['id']}"))
    written_to_file = bool(result.get('history'))
    report['applied'] = {'written': True, 'where': result.get('editor') or result.get('where') or
                         ('the project file' if written_to_file else 'the open letitedit window'),
                         'history': result.get('history'), 'changes': result.get('changes'),
                         'undo_label': result.get('undo_label')}
    for e in report['clips']:
        if e['status'] == 'proposed':
            e['status'] = 'corrected'
    report['summary'] = report['summary'].replace('would be corrected', 'corrected')
    written = path if written_to_file else current(path)[0]   # the window as the change left it (T298)
    # verify: the written clips render exactly as previewed
    work = Path(plan['preview_artifacts']['folder'])
    corrected = [e for e in report['clips'] if e['status'] == 'corrected']
    by_track = {}
    for e in corrected:
        by_track.setdefault(e['track'], []).append(e)
    worst, unverified = 0.0, []
    for k, (track, es_) in enumerate(by_track.items()):
        var = build_variant(written, work / f'written-{k}.mlt', strip_text=[e['id'] for e in es_], isolate=track)
        ts_all, owner = [], []
        for e in es_:
            ts_all += e['frames_s']
            owner += [e['id']] * len(e['frames_s'])
        pngs = render_times(var, ts_all, work / f'written-{k}')
        got = {}
        for cid, png in zip(owner, pngs):
            got.setdefault(cid, []).append(str(png))
        for e in es_:
            prev = [p for p in (e.get('preview') or {}).get('after_frames') or [] if Path(p).exists()]
            diff = _frame_diff(prev, got[e['id']]) if len(prev) == len(got[e['id']]) else None
            e['written_check'] = {'max_mean_abs_diff_0_255': _r(diff, 3) if diff is not None else None,
                                  'frames': got[e['id']]}
            if diff is None:
                unverified.append(e['id'])
            else:
                worst = max(worst, diff)
    if unverified:
        report['applied']['verified'] = (f"the previewed frames of {', '.join(unverified)} are gone, so the written "
                                         'clips were rendered but not compared; check them with letitedit_check_frames')
    else:
        report['applied']['verified'] = (
            f'rendered from the written project (or the window it went to): the corrected clips match the previewed frames (largest mean '
            f'difference {worst:.2f} of 255)' if worst < 0.5 else
            f'rendered from the written project: the corrected clips differ from the preview by up to {worst:.2f} of '
            '255 (mean); check them with letitedit_check_frames')
    _save_plan(report, '-applied')
    return report


def remove_matching(path, clips=None, label=None):
    """Take the shot-match effects off the given clips (every clip that has one when clips is None or a string)."""
    import letitedit.timeline.edit_script as es
    source, revision, read = current(path)
    script = es.read(source)
    slots = effect_slots(source, script)
    ids = list(clips) if isinstance(clips, (list, tuple)) else [cid for cid, s in slots.items() if s['ours']]
    unknown = [c for c in ids if c not in slots]
    if unknown:
        raise ValueError(f'No clip {", ".join(map(repr, unknown))} with effects to change')
    changes, removed = [], []
    for cid in ids:
        if slots[cid]['ours']:
            changes.append(effects_op(cid, slots[cid], None))
            removed.append(cid)
    report = {'schema_version': SCHEMA_VERSION, 'tool': 'letitedit_match_shots', 'mode': 'removed', 'project': str(path),
              'project_revision': revision, 'read': read, 'removed_from': removed, 'changes': changes,
              'summary': f'shot-match effects taken off {len(removed)} clip(s)' if removed else
                         'no shot-match effects on those clips'}
    if changes:
        result = write_changes(path, changes, _label(label, f'remove shot matching from {len(removed)} clip(s)'))
        report['applied'] = {'written': True, 'history': result.get('history'), 'changes': result.get('changes')}
    return report
