"""Measured scene appearance and face-limited, baked lighting adjustments."""
from __future__ import annotations

import letitedit.core.quiet_subprocess as quiet_subprocess
import json
import math
from pathlib import Path
import subprocess

import cv2
import numpy as np

FORMAT = "letitedit-lighting/1"
WEIGHTS = np.array([.2126, .7152, .0722], np.float32)
ROLES = {"talking_head", "broll", "primary", "graphics", "unknown"}
PARAMS = {"exposure_ev": 0., "contrast": 1., "black": 0., "saturation": 1.,
          "tint_rgb": [1., 1., 1.], "vignette": 0., "strength": 1.,
          "mode": "whole", "target": None, "face_light": 0., "face_warmth": 0., "room_ev": 0.}
_DETECTORS = {}


def number(value, name, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return float(value)


def rgb_frame(frame):
    frame = np.asarray(frame)
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must be RGB uint8 HxWx3")
    return frame


def matte_array(matte, shape):
    matte = np.asarray(matte, np.float32)
    if matte.shape != shape or not np.isfinite(matte).all() or matte.min() < 0 or matte.max() > 1:
        raise ValueError("matte must be finite HxW in [0,1]")
    return matte


def window_matte(shape, faces, window=(1.7, 2.0), room=(2.2, 1.8), drop=.05):
    """What the importer measures against, with no model: 1 inside the lighting's own oval around the biggest face, 0 outside
    the wider oval that the room is darkened beyond, 0.5 between. Nothing is cut out: clothing, hair and a bright wall are not
    told apart from the window and the room."""
    height, width = shape
    if not faces:
        return np.zeros(shape, np.float32)
    left, top, w, h = max(faces, key=lambda b: b[2] * b[3])
    cx, cy = left + w / 2, top + h / 2
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)

    def radius(wmul, hmul, drop_by):
        return np.sqrt(((xx - cx) / (w * wmul / 2)) ** 2 + ((yy - cy - drop_by * h) / (h * hmul / 2)) ** 2)
    inner = radius(window[0], window[1], drop)
    outer = radius(window[0] * room[0], window[1] * room[1], drop + .1)
    return np.where(inner <= 1., 1., np.where(outer >= 1., 0., .5)).astype(np.float32)


def face_boxes(frame):
    import letitedit.pictures.vfx_items as vfx_items
    model = vfx_items.VFX_DIR / "models" / "yunet_2023mar.onnx"
    if not model.is_file() or not hasattr(cv2, "FaceDetectorYN"):
        raise ValueError("lighting needs the installed YuNet face guard; no download was started")
    height, width = frame.shape[:2]
    scale = min(1., 640 / width)
    small = cv2.resize(frame, (round(width * scale), round(height * scale)))
    size = (small.shape[1], small.shape[0])
    detector = _DETECTORS.get(size)
    if detector is None:
        detector = cv2.FaceDetectorYN.create(str(model), "", size, .6, .3, 100)
        _DETECTORS[size] = detector
    _, found = detector.detect(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
    return [] if found is None else [list(map(float, box[:4] / scale)) for box in found]


def box_mask(shape, boxes, margin=0.):
    mask = np.zeros(shape, bool)
    height, width = shape
    for box in boxes:
        if len(box) != 4 or not all(math.isfinite(float(value)) for value in box):
            raise ValueError("face boxes must be finite x,y,width,height")
        left, top, box_width, box_height = box
        if box_width <= 0 or box_height <= 0:
            raise ValueError("face boxes need positive width and height")
        x0, y0 = max(0, math.floor(left - margin * box_width)), max(0, math.floor(top - margin * box_height))
        x1 = min(width, math.ceil(left + box_width * (1 + margin)))
        y1 = min(height, math.ceil(top + box_height * (1 + margin)))
        mask[y0:y1, x0:x1] = True
    return mask


def skin_mask(frame):
    colour = cv2.cvtColor(frame, cv2.COLOR_RGB2YCrCb)
    return ((colour[..., 0] > 25) & (colour[..., 1] >= 130) & (colour[..., 1] <= 180)
            & (colour[..., 2] >= 75) & (colour[..., 2] <= 135))


def region_stats(frame, mask):
    pixels = frame[mask].astype(np.float32) / 255
    if len(pixels) < 32:
        return None
    luminance = pixels @ WEIGHTS
    percentiles = np.percentile(luminance, [5, 10, 50, 90, 95])
    hsv = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    mean_rgb = pixels.mean(axis=0)
    bright = pixels[luminance >= percentiles[3]]
    return {"pixels": len(pixels), "luma_p05": float(percentiles[0]),
            "luma_p50": float(percentiles[2]), "luma_p95": float(percentiles[4]),
            "contrast_p90_p10": float(percentiles[3] - percentiles[1]),
            "saturation_p50": float(np.median(hsv[:, 1])),
            "mean_rgb": mean_rgb.tolist(),
            "chromaticity": (mean_rgb / max(.001, float(mean_rgb.sum()))).tolist(),
            "bright_rgb_proxy": bright.mean(axis=0).tolist()}


def measure(frame, matte, faces=(), exclude=None):
    frame = rgb_frame(frame)
    matte = matte_array(matte, frame.shape[:2])
    valid = np.ones(matte.shape, bool) if exclude is None else ~np.asarray(exclude, bool)
    if valid.shape != matte.shape:
        raise ValueError("exclude mask has wrong shape")
    subject = (matte >= .9) & valid
    background = (matte <= .02) & valid
    face = box_mask(matte.shape, faces) & valid
    skin = skin_mask(frame) & face
    height, width = matte.shape
    horizontal, vertical = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    radius = horizontal ** 2 + vertical ** 2
    corners = region_stats(frame, background & (radius > 1.1))
    centre = region_stats(frame, background & (radius < .35))
    result = {name: region_stats(frame, mask) for name, mask in
              (("picture", valid), ("subject", subject), ("background", background),
               ("face", face), ("skin", skin), ("background_left", background & (horizontal < -.25)),
               ("background_right", background & (horizontal > .25)))}
    result["subject_fraction"] = float(subject.mean())
    result["person_evidence"] = "face detected; matte subject remains estimated" if faces else "unverified; matte may select objects or lettering"
    if not faces:
        result["subject"] = None
    result["matte_uncertain_fraction"] = float(((matte > .02) & (matte < .9)).mean())
    result["subject_background_stops"] = (math.log2(max(.001, result["subject"]["luma_p50"]) /
                                                  max(.001, result["background"]["luma_p50"]))
                                               if result["subject"] and result["background"] else None)
    result["corner_centre_ratio_proxy"] = (corners["luma_p50"] / max(.001, centre["luma_p50"])
                                             if corners and centre else None)
    return result


def settings(params):
    if not isinstance(params, dict) or set(params) - set(PARAMS):
        raise ValueError("unknown lighting parameter")
    result = {**PARAMS, **params}
    for name, low, high in (("exposure_ev", -4, 2), ("contrast", .5, 2), ("black", -.1, .1),
                            ("saturation", 0, 1.5), ("vignette", 0, .7), ("strength", 0, 1),
                            ("face_light", 0, 1), ("face_warmth", 0, .06), ("room_ev", -1.5, 0)):
        result[name] = number(result[name], name, low, high)
    if result["mode"] not in ("whole", "background", "broll"):
        raise ValueError("mode is whole, background or broll")
    if not isinstance(result["tint_rgb"], (list, tuple)) or len(result["tint_rgb"]) != 3:
        raise ValueError("tint_rgb needs three channel gains")
    result["tint_rgb"] = [number(value, "tint_rgb", .25, 2) for value in result["tint_rgb"]]
    if result["target"] is not None:
        validate_target(result["target"])
    return result


def validate_target(target):
    if not isinstance(target, dict):
        raise ValueError("target must be a measured region")
    for name in ("luma_p05", "luma_p50", "luma_p95", "contrast_p90_p10", "saturation_p50"):
        number(target.get(name), name, 0, 1)
    if not target["luma_p05"] <= target["luma_p50"] <= target["luma_p95"]:
        raise ValueError("target luma percentiles must be ordered")
    colour = target.get("mean_rgb")
    if not isinstance(colour, list) or len(colour) != 3:
        raise ValueError("target mean_rgb needs three channels")
    for value in colour:
        number(value, "mean_rgb", 0, 1)
    return target


def plan(target, source):
    validate_target(target)
    validate_target(source)
    tint = np.array(target["mean_rgb"]) / np.maximum(.02, source["mean_rgb"])
    tint /= max(.001, float(tint @ WEIGHTS))
    return {"exposure_ev": float(np.clip(math.log2(max(.01, target["luma_p50"]) /
                                                         max(.01, source["luma_p50"])), -3, 1)),
            "contrast": float(np.clip(target["contrast_p90_p10"] /
                                             max(.04, source["contrast_p90_p10"]), .7, 1.5)),
            "black": float(np.clip(target["luma_p05"] - source["luma_p05"], -.06, .06)),
            "saturation": float(np.clip(target["saturation_p50"] /
                                               max(.05, source["saturation_p50"]), .5, 1.3)),
            "tint_rgb": np.clip(tint, .6, 1.5).tolist()}


def protect(frame, matte, faces):
    person = (matte > .02) | box_mask(matte.shape, faces)
    reach = max(2, round(min(matte.shape) * .008))
    neighbourhood = cv2.dilate(person.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (reach * 2 + 1, reach * 2 + 1))).astype(bool)
    skin = skin_mask(frame) & neighbourhood if faces else skin_mask(frame)
    protected = person | skin
    radius = max(1, round(min(matte.shape) * .002))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    core = cv2.dilate(protected.astype(np.uint8), kernel).astype(bool)
    feather = cv2.GaussianBlur(core.astype(np.float32), (0, 0), max(1., min(matte.shape) * .006))
    return np.maximum(core, feather)


def apply(frame, matte, params, faces=()):
    frame = rgb_frame(frame)
    params = settings(params)
    if params['mode'] == 'whole':
        return whole_picture(frame, params, faces)
    matte = matte_array(matte, frame.shape[:2])
    if params["target"] is not None:
        raise ValueError("resolve target once with plan before applying frames")
    weight = (1 - protect(frame, matte, faces)) * params["strength"]
    picture = frame.astype(np.float32) / 255
    adjusted = picture * 2 ** params["exposure_ev"]
    adjusted = (adjusted - .18) * params["contrast"] + .18 + params["black"]
    grey = adjusted @ WEIGHTS
    adjusted = grey[..., None] + (adjusted - grey[..., None]) * params["saturation"]
    adjusted *= np.array(params["tint_rgb"], np.float32)
    height, width = frame.shape[:2]
    horizontal, vertical = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    adjusted *= (1 - params["vignette"] * np.clip((horizontal ** 2 + vertical ** 2) / 2, 0, 1))[..., None]
    output = np.clip(np.rint((picture + (np.clip(adjusted, 0, 1) - picture) * weight[..., None]) * 255), 0, 255).astype(np.uint8)
    output[weight == 0] = frame[weight == 0]
    return output


def room_edge_mask(shape, faces):
    height, width = shape
    horizontal, vertical = np.meshgrid(np.linspace(-1, 1, width), np.linspace(-1, 1, height))
    radius = np.clip((horizontal ** 2 + vertical ** 2) / 2, 0, 1) ** 2
    if faces:
        outside = (~box_mask(shape, faces)).astype(np.uint8)
        distance = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
        feather = np.clip(distance / max(1, min(shape) * .12), 0, 1)
        radius *= feather * feather * (3 - 2 * feather)
    return radius


def _smooth(mask, shape, reach):
    """A 0/1 mask softened outward over `reach` of the shorter side: 1 inside, falling smoothly to 0."""
    distance = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
    feather = np.clip(1 - distance / max(1, min(shape) * reach), 0, 1)
    return feather * feather * (3 - 2 * feather)


def subject_zone(shape, faces):
    """Where the person is, without a cut-out: each face box widened to the shoulders and carried down to the bottom
    of the picture, softened at its edges. 1 on the person, 0 in the room."""
    zone = np.zeros(shape, bool)
    height, width = shape
    for left, top, box_width, box_height in faces:
        x0, x1 = max(0, math.floor(left - 1.0 * box_width)), min(width, math.ceil(left + 2.0 * box_width))
        y0 = max(0, math.floor(top - .6 * box_height))
        zone[y0:height, x0:x1] = True
    return _smooth(zone, shape, .08) if zone.any() else np.zeros(shape, np.float32)


def light_mask(shape, faces):
    """Where the key light falls: 1 on every face box and a little beyond, softening to 0 over a tenth of the picture."""
    return _smooth(box_mask(shape, faces, .15), shape, .1) if faces else np.zeros(shape, np.float32)


def lift(picture, face_light, face_warmth):
    """The face with a key light on it: its brightness raised along a gamma curve (shadows and mid-tones rise most,
    white stays white) by one gain per pixel on all three channels, so hue and colour strength stay put and nothing
    clips; then a little warmth (red up, blue down). picture: float RGB 0-1."""
    out = picture
    if face_light:
        luma = np.maximum(picture @ WEIGHTS, 1e-4)
        peak = picture.max(axis=-1)
        room = np.clip((1 - peak) / .25, 0, 1)            # a shoulder: pixels near white are left where they are
        gain = 1 + (luma ** (2 ** -face_light) / luma - 1) * room * room * (3 - 2 * room)
        gain = np.minimum(gain, 1 / np.maximum(peak, 1e-4))
        out = picture * gain[..., None]
    if face_warmth:
        out = out * np.array([1 + face_warmth, 1, 1 - face_warmth], np.float32)
    return np.clip(out, 0, 1)


def _gain_map(shape, faces, params):
    """The room's exposure and vignette as one multiplier per pixel. Both are smooth, so on a large picture they are
    worked out on a quarter-size copy and scaled up."""
    k = max(1, min(shape) // 270)
    small = (shape[0] // k, shape[1] // k) if k > 1 else shape
    scaled = [[v / k for v in box] for box in faces] if k > 1 else faces
    gain = 1 - params['vignette'] * room_edge_mask(small, scaled)
    if faces and params['room_ev']:
        gain = gain * 2 ** (params['room_ev'] * (1 - subject_zone(small, scaled)))
    gain = gain.astype(np.float32)
    return cv2.resize(gain, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR) if k > 1 else gain


def _graded(picture, params, faces):
    """The gentle grade of the picture (curve, shadows black and tint, saturation) at the grade's strength."""
    grey = picture @ WEIGHTS
    shadows = np.clip((.6 - grey) / .6, 0, 1) ** 2
    exposure = float(np.clip(params['exposure_ev'], -.25, .25))
    adjusted = picture * 2 ** (exposure if faces else max(0., exposure))     # no face seen: never darker
    curve = np.clip(params['contrast'] - 1, -.15, .15)
    adjusted += curve * picture * (1 - picture) * (2 * picture - 1)
    adjusted += np.clip(params['black'], -.02, .02) * shadows[..., None]
    adjusted += (np.array(params['tint_rgb'], np.float32) - 1) * .12 * shadows[..., None]
    adjusted_grey = adjusted @ WEIGHTS
    adjusted = adjusted_grey[..., None] + (adjusted - adjusted_grey[..., None]) * np.clip(params['saturation'], .9, 1.1)
    return picture + (np.clip(adjusted, 0, 1) - picture) * params['strength']


def whole_picture(frame, params, faces=()):
    params = settings(params)
    if params['target'] is not None:
        raise ValueError('resolve target once before applying frames')
    picture = rgb_frame(frame).astype(np.float32) / 255
    shape = frame.shape[:2]
    plain = (params['exposure_ev'], params['contrast'], params['black'], params['saturation'],
             tuple(params['tint_rgb'])) == (0., 1., 0., 1., (1., 1., 1.))
    adjusted = picture if plain else _graded(picture, params, faces)
    if params['vignette'] or (faces and params['room_ev']):
        adjusted = adjusted * _gain_map(shape, faces if faces else [], params)[..., None]
    if faces:       # the face is never graded: the key light (or the untouched face) replaces the grade on it
        weight = light_mask(shape, faces)
        rows, columns = np.nonzero(weight)
        if len(rows):
            y0, y1, x0, x1 = rows.min(), rows.max() + 1, columns.min(), columns.max() + 1
            w = weight[y0:y1, x0:x1, None]
            adjusted[y0:y1, x0:x1] = (adjusted[y0:y1, x0:x1] * (1 - w) +
                                      lift(picture[y0:y1, x0:x1], params['face_light'], params['face_warmth']) * w)
    return np.clip(np.rint(adjusted * 255), 0, 255).astype(np.uint8)


# What a face may do. One-sided: it may get brighter, clearer and a little warmer; it may not get darker, and its
# colour may not leave natural skin. The numbers rest on outside practice (the tool text states it): skin sits on the
# vectorscope's skin-tone line, and lit skin usually reads 65-75 IRE and up to about 80.
FACE_LIMITS = {'min_luma_delta': -.0005, 'max_hue_shift_deg': 3., 'max_chroma_change': .15,
               'max_median_luma': .8, 'max_clipped_gain': .01}


def _box_pixels(frame, face):
    """The (y0, y1, x0, x1) of a face box inside the picture, the same pixels box_mask would select."""
    height, width = frame.shape[:2]
    left, top, box_width, box_height = face
    y0, x0 = max(0, math.floor(top)), max(0, math.floor(left))
    y1, x1 = min(height, math.ceil(top + box_height)), min(width, math.ceil(left + box_width))
    if y1 <= y0 or x1 <= x0:
        raise ValueError('face box outside picture')
    return y0, y1, x0, x1


def face_change(frame, output, faces):
    """Per face, what the picture did to the face box: mean-luma change (positive is brighter), median luma, the hue
    shift of the mean colour in degrees (CIELAB h*ab), the relative change in chroma per unit of lightness (C*/L*) and the added share of clipped
    pixels."""
    from letitedit.review.shot_match import srgb_to_lab, delta_e2000
    rows = []
    for face in faces:
        y0, y1, x0, x1 = _box_pixels(frame, face)
        before_px = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32) / 255
        after_px = output[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32) / 255
        before, after = before_px.mean(axis=0), after_px.mean(axis=0)
        lab0, lab1 = srgb_to_lab(before), srgb_to_lab(after)
        h0, h1 = math.degrees(math.atan2(lab0[2], lab0[1])), math.degrees(math.atan2(lab1[2], lab1[1]))
        # colour strength at the same lightness: chroma over L*, so a brighter face is not read as a tinted one
        c0 = math.hypot(lab0[1], lab0[2]) / max(1., lab0[0])
        c1 = math.hypot(lab1[1], lab1[2]) / max(1., lab1[0])
        median_before, median_after = np.median(before_px @ WEIGHTS), np.median(after_px @ WEIGHTS)
        rows.append({'luma_delta': float((after - before) @ WEIGHTS),
                     'median_luma_after': float(median_after), 'median_luma_before': float(median_before), 'median_luma_delta': float(median_after - median_before),
                     'hue_shift_deg': float(abs((h1 - h0 + 180) % 360 - 180)),
                     'chroma_change': float((c1 - c0) / max(1e-6, c0)),
                     'clipped_gain': float((after_px.max(axis=1) >= .98).mean() - (before_px.max(axis=1) >= .98).mean()),
                     'delta_e2000': float(delta_e2000(lab0, lab1))})
    return {'faces': len(rows), 'rows': rows,
            'min_luma_delta': min((r['luma_delta'] for r in rows), default=0.),
            'min_median_luma_delta': min((r['median_luma_delta'] for r in rows), default=0.),
            'max_median_luma': max((r['median_luma_after'] for r in rows), default=0.),
            'max_hue_shift_deg': max((r['hue_shift_deg'] for r in rows), default=0.),
            'max_chroma_change': max((abs(r['chroma_change']) for r in rows), default=0.),
            'max_clipped_gain': max((r['clipped_gain'] for r in rows), default=0.),
            'max_delta_e2000': max((r['delta_e2000'] for r in rows), default=0.)}


def face_within_limits(change):
    limits = FACE_LIMITS
    return (change['min_luma_delta'] >= limits['min_luma_delta'] and
            change['min_median_luma_delta'] >= limits['min_luma_delta'] and
            change['max_hue_shift_deg'] <= limits['max_hue_shift_deg'] and
            change['max_chroma_change'] <= limits['max_chroma_change'] and
            all(r['median_luma_after'] <= max(limits['max_median_luma'], r['median_luma_before']) + 1e-6
                for r in change['rows']) and
            change['max_clipped_gain'] <= limits['max_clipped_gain'])


def face_safe_light(frame, params, faces):
    """How much of the requested face light and warmth keeps every detected face inside FACE_LIMITS on this frame:
    the light is kept as far as it can be (1, 0.75, 0.5, 0.25, 0) and, at that light, as much warmth (1, 0.5, 0). Only the face boxes are computed:
    inside them the picture is the lifted face. Returns ((light share, warmth share), change)."""
    picture = rgb_frame(frame)
    if not faces or not (params['face_light'] or params['face_warmth']):
        return (1., 1.), face_change(picture, picture, faces)
    ladder = [(light, warm) for light in (1., .75, .5, .25, 0.) for warm in (1., .5, 0.)]
    for light_share, warm_share in ladder:
        output = picture.copy()
        for face in faces:
            y0, y1, x0, x1 = _box_pixels(picture, face)
            crop = picture[y0:y1, x0:x1].astype(np.float32) / 255
            output[y0:y1, x0:x1] = np.rint(lift(crop, params['face_light'] * light_share,
                                                params['face_warmth'] * warm_share) * 255)
        change = face_change(picture, output, faces)
        if face_within_limits(change):
            return (light_share, warm_share), change
    raise ValueError('face light failed its own measurement at zero')


def filled_faces(rows):
    """Face boxes per frame, a missed detection filled from the nearest frame that has one."""
    known = [i for i, faces in enumerate(rows) if faces]
    if not known:
        return rows
    return [faces or rows[min(known, key=lambda k: abs(k - i))] for i, faces in enumerate(rows)]


def render_whole(job, source, params):
    import letitedit.pictures.vfx_items as vfx_items
    shots = vfx_items._creator('shots')
    requested = {'face_light': params['face_light'], 'face_warmth': params['face_warmth']}
    face_rows, share = [], (1., 1.)
    reader = shots.FrameReader(source.path, source.start, source.frames, job.fps, job.W, job.H)
    try:
        last = []
        for frame_index, frame in enumerate(reader):
            faces = face_boxes(frame)
            face_rows.append(faces)
            if frame_index == 0 and params['target'] is not None:
                measured = region_stats(frame, np.ones(frame.shape[:2], bool))
                params = {**params, **plan(params['target'], measured), 'target': None}
            last = faces or last
            got = face_safe_light(frame, params, last)[0]
            share = (min(share[0], got[0]), min(share[1], got[1]))
    finally:
        reader.close()
    if len(face_rows) != source.frames:
        raise ValueError('lighting preflight did not decode every frame')
    detected = sum(1 for faces in face_rows if faces)
    face_rows = filled_faces(face_rows)
    if not any(face_rows):
        params = {**params, 'vignette': 0., 'room_ev': 0., 'face_light': 0., 'face_warmth': 0.}
    params = {**params, 'face_light': params['face_light'] * share[0], 'face_warmth': params['face_warmth'] * share[1]}
    intermediate = job.work / 'lighting.mov'
    command = [str(vfx_items.made.ffmpeg_exe()), '-v', 'error', '-y', '-threads', '4',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{job.W}x{job.H}', '-r', str(job.fps),
               '-i', '-', '-an', '-c:v', 'qtrle', '-threads', '4', '-pix_fmt', 'rgb24', str(intermediate)]
    receipt = {'mode': 'whole', 'matte_used': False, 'requested': requested,
               'face_light': params['face_light'], 'face_warmth': params['face_warmth'], 'share_of_request': {'light': share[0], 'warmth': share[1]},
               'room_ev': params['room_ev'], 'vignette': params['vignette'], 'limits': dict(FACE_LIMITS),
               'vignette_protection': 'union of every detected face box; feather outside only',
               'frames': [], 'min_luma_delta': None, 'max_hue_shift_deg': 0., 'max_chroma_change': 0.,
               'max_median_luma': 0., 'max_clipped_gain': 0., 'max_delta_e2000': 0.}
    with (job.work / 'encoder.log').open('wb') as errors:
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        reader = shots.FrameReader(source.path, source.start, source.frames, job.fps, job.W, job.H)
        try:
            for frame_index, frame in enumerate(reader):
                output = whole_picture(frame, params, face_rows[frame_index])
                change = face_change(frame, output, face_rows[frame_index])
                if not face_within_limits(change):
                    raise ValueError(f'constant face light exceeded its limits on frame {frame_index}')
                receipt['frames'].append({'frame': frame_index, **{k: v for k, v in change.items() if k != 'rows'}})
                low = change['min_luma_delta']
                receipt['min_luma_delta'] = low if receipt['min_luma_delta'] is None else min(receipt['min_luma_delta'], low)
                for metric in ('max_hue_shift_deg', 'max_chroma_change', 'max_median_luma', 'max_clipped_gain',
                               'max_delta_e2000'):
                    receipt[metric] = max(receipt[metric], change[metric])
                encoder.stdin.write(output.tobytes())
            encoder.stdin.close()
            if encoder.wait(timeout=120):
                raise RuntimeError('lighting encoder failed')
            if len(receipt['frames']) != source.frames:
                raise ValueError('lighting bake did not decode every frame')
            receipt['frames_without_detected_face'] = source.frames - detected
            (job.work / 'face-check.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            if hasattr(job, 'out'):
                job.out.with_suffix('.face-check.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            job.notes.append(f"Whole-picture lighting, no cut-out; face light {params['face_light']:.3f} EV and warmth "
                             f"{params['face_warmth']:.3f} ({share[0]:.2f} of the light and {share[1]:.2f} of the warmth requested), room {params['room_ev']:.2f} EV. "
                             f"Every-frame face check: the face only lifted (smallest luma change {receipt['min_luma_delta'] or 0:+.5f}), "
                             f"hue shift at most {receipt['max_hue_shift_deg']:.2f} degrees, chroma change at most "
                             f"{receipt['max_chroma_change']:.3f}; {receipt['frames_without_detected_face']} frames "
                             "without a detected face took the nearest frame's face box.")
            vfx_items._mux(job, intermediate, source, source.frames, tag=False)
        finally:
            reader.close()
            if encoder.poll() is None:
                encoder.kill()
                encoder.wait()
            intermediate.unlink(missing_ok=True)
    return source.frames


def edge_guard(frame, output, matte):
    person = matte > .02
    if not person.any() or person.all():
        return {'safe': True, 'new_edge_step': 0.}
    radius = max(2, round(min(matte.shape) * .015))
    distance = cv2.distanceTransform((~person).astype(np.uint8), cv2.DIST_L2, 3)
    near = (distance > 0) & (distance <= radius * 2)
    delta = (output.astype(np.float32) - frame.astype(np.float32)) / 255
    residuals = []
    for scale in (1, 2, 4):
        width = radius * scale * 2 + 1
        outer = cv2.blur(delta, (width, width))
        residual = delta - outer
        luma = np.abs(residual @ WEIGHTS)
        chroma = np.max(residual, axis=2) - np.min(residual, axis=2)
        residuals.append(float(np.percentile(np.maximum(luma, chroma)[near], 95)))
    step = max(residuals) if near.any() else 0.
    return {'safe': step <= .035, 'new_edge_step': step, 'limit': .035,
            'measurement': 'multiscale_absolute_luma_and_chroma', 'scales': residuals}


def guarded_plan(frame, matte, params, faces=()):
    params = settings(params)
    requested = params['strength']
    for fraction in (1., .75, .5, .25, .125):
        candidate = {**params, 'strength': requested * fraction}
        output = apply(frame, matte, candidate, faces)
        edge = edge_guard(frame, output, matte)
        if edge['safe']:
            return candidate, output, edge
    raise ValueError('background lighting refused: no useful constant strength avoids matte-edge glow')


def reference_separation(profile):
    """{'reference_stops', 'samples'}: how much brighter the face window is than the room in the reference's talking-head
    samples (median of log2(face / room) over samples with a face and without a native effect on them); None values when
    there are none."""
    stops = []
    for scene in profile.get("scenes", []):
        if scene.get("role") not in ("talking_head", "primary"):
            continue
        for sample in scene.get("samples", []):
            value = (sample.get("metrics") or {}).get("subject_background_stops")
            if value is not None and sample.get("faces") and not sample.get("native_effects_at_sample"):
                stops.append(float(value))
    if not stops:
        return {"reference_stops": None, "samples": 0}
    stops.sort()
    return {"reference_stops": round(stops[len(stops) // 2], 3), "samples": len(stops)}


def clip_separation(path, rows, start, speed=1.0, frames=3):
    """Stops between the face window and the room in a clip of footage, from `frames` frames spread over its face rows
    (the same window and room ovals the lighting uses); None when it cannot be read."""
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        picks = sorted({rows[min(len(rows) - 1, int(i * (len(rows) - 1) / max(1, frames - 1)))][0] for i in range(frames)}) \
            if len(rows) > 1 else [rows[0][0]]
        values = []
        for t in picks:
            row = min(rows, key=lambda r: abs(r[0] - t))
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            scale = min(1., 480 / width)
            small = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
            h, w = small.shape[:2]
            box = [(row[1] - row[3] / 2) * w, (row[2] - row[4] / 2) * h, row[3] * w, row[4] * h]
            matte = window_matte((h, w), [box])
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            stats = measure(rgb, matte, [box])
            if stats.get("subject_background_stops") is not None:
                values.append(stats["subject_background_stops"])
        if not values:
            return None
        values.sort()
        return round(values[len(values) // 2], 3)
    finally:
        cap.release()


def look_lighting(script):
    """The chosen Look's lighting for the project: {'settings': explicit live settings or None, 'reference_stops': float or
    None, 'look': id} from its lighting.json; {} when no Look or none with lighting."""
    try:
        import json as _json
        import letitedit.looks.look_inputs as look_inputs
        import letitedit.review.brief_check as brief_check
        import letitedit.looks.looks as looks
        chosen = ((look_inputs.read(script.get("project")) or {}).get("look") or
                  (brief_check.load(project=script.get("project")) or {}).get("look"))
        if not chosen:
            return {}
        path = Path(looks.read(chosen)["recipe"]).with_name("lighting.json")
        if not path.is_file():
            return {}
        profiles = _json.loads(path.read_text(encoding="utf-8-sig"))
        profiles = [profiles] if isinstance(profiles, dict) else profiles
        explicit = next((p["live_settings"] for p in profiles if p.get("live_settings")), None)
        stops = [(p.get("live") or reference_separation(p)).get("reference_stops") for p in profiles]
        stops = [v for v in stops if v is not None]
        return {"look": chosen, "settings": explicit, "reference_stops": sorted(stops)[len(stops) // 2] if stops else None}
    except Exception:  # noqa: BLE001 - no Look lighting: the plain defaults
        return {}


# how much of a nominal room_ev shows in the room's brightness (the soft oval's edge and the face window's overlap)
ROOM_SHOWS = .7


def tuned_room_ev(reference_stops, clip_stops, face_ev=.03):
    """The room darkening that takes a clip's own face/room separation to the Look's, in nominal EV (0 to -3)."""
    need = float(reference_stops) - float(clip_stops) - float(face_ev)
    return round(-max(0., min(3., need / ROOM_SHOWS)), 2)


def validate(profile, references=None):
    if not isinstance(profile, dict) or profile.get("format") != FORMAT:
        raise ValueError("lighting profile must be letitedit-lighting/1")
    if not isinstance(profile.get("file"), str) or not profile["file"]:
        raise ValueError("lighting source file missing")
    duration = number(profile.get("duration_s"), "duration_s", .001, 1e7)
    if references is not None and not any(item["file"] == profile["file"] and
                                         abs(item["duration_s"] - duration) < .001 for item in references):
        raise ValueError("lighting source differs from Look reports")
    scenes = profile.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("lighting needs measured scenes")
    previous = 0.
    for scene in scenes:
        start = number(scene.get("start_s"), "scene start", previous, duration)
        end = number(scene.get("end_s"), "scene end", start, duration)
        if end <= start or scene.get("role") not in ROLES:
            raise ValueError("lighting scene needs ordered times and reviewed role or unknown")
        previous = end
        samples = scene.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("lighting scene needs samples")
        for sample in samples:
            at = number(sample.get("at_s"), "sample at", start, end)
            if at >= end:
                raise ValueError("lighting sample outside half-open scene")
            if not isinstance(sample.get("metrics"), dict) or not sample["metrics"].get("picture"):
                raise ValueError("lighting sample needs measured picture statistics")
            for region in ("picture", "subject", "background", "skin", "face", "background_left", "background_right"):
                value = sample.get("metrics", {}).get(region)
                if value is not None:
                    validate_target(value)
        json.dumps(scene, allow_nan=False)
    return profile


def recipe(profile):
    validate(profile)
    lines = ["## Measured lighting", "",
             "Display-RGB luma (0-1), not scene-linear exposure. The face window and the room outside it are measured;",
             "clothing affects subject brightness. RGB key/side values describe visible colour, not lamp CCT.",
             "Skin is a face-box chroma proxy, not a diagnosis or an identity. Missing skin/subject is unknown.",
             "Vignette is only corner/centre appearance; composition can cause it. Haze/bloom are unmeasured.",
             "", "Default: `{op: fx, lighting: true}` on every speaker clip (live filters); settings face_ev, face_gamma, room_ev, window, feather.",
             "Match only the measured face/room separation; a natural reference keeps neutral live-filter settings, with no invented face lift or room darkening.",
             "The live lighting lifts the face window and darkens the room; its check measures every frame's detected face",
             "box (luma change, hue shift <=3 degrees, chroma change <=15%); no cut-out.",
             "Disclose reduced light and missed faces. A Look's grade, not the lighting, sets the face's colour.",
             ""]
    live = profile.get("live") or {}
    if live.get("reference_stops") is not None:
        natural = live["reference_stops"] <= .15
        treatment = ("keep face_ev=0, face_gamma=1 and room_ev=0; preserve natural lighting." if natural else
                     "tune room_ev from each clip's own separation; keep face_ev and face_gamma small.")
        lines.insert(-1, f"Measured separation of the face window from the room: {live['reference_stops']:.2f} stops "
                         f"(median of {live['samples']} talking-head samples); {treatment}")
    for index, scene in enumerate(profile["scenes"]):
        sample = scene["samples"][len(scene["samples"]) // 2]["metrics"]
        lines.append(f"- Scene {index}: {scene["start_s"]:.3f}-{scene["end_s"]:.3f}s; {scene["role"]} "
                     f"({scene.get("role_evidence", "unknown")}).")
        for sampled in scene["samples"]:
            if sampled.get("native_effects_at_sample"):
                lines.append(f"  Sample {sampled["at_s"]:.3f}s overlaps native effects "
                             f"{sampled["native_effects_at_sample"]}; do not use as a steady lighting target.")
        for name in ("picture", "subject", "background", "face", "skin", "background_left", "background_right"):
            value = sample.get(name)
            if value:
                colour = ",".join(f"{channel:.3f}" for channel in value["mean_rgb"])
                lines.append(f"  {name}: median luma {value["luma_p50"]:.3f}, black p05 {value["luma_p05"]:.3f}, "
                             f"contrast {value["contrast_p90_p10"]:.3f}, saturation {value["saturation_p50"]:.3f}, RGB {colour}.")
                if value.get("bright_rgb_proxy"):
                    bright = ",".join(f"{channel:.3f}" for channel in value["bright_rgb_proxy"])
                    lines.append(f"  {name} bright-pixel RGB appearance proxy: {bright} (not an illuminant estimate).")
        stops = sample.get("subject_background_stops")
        lines.append(f"  Subject/background ratio: {stops:.2f} display-luma stops." if stops is not None
                     else "  Subject/background ratio: unknown; no trustworthy separation.")
        corners = sample.get("corner_centre_ratio_proxy")
        lines.append(f"  Background corner/centre median-luma ratio: {corners:.3f}; composition-confounded."
                     if corners is not None else "  Vignette proxy: unknown; insufficient background in both regions.")
    return "\n".join(lines) + "\n"


def analyse_report(report, out, samples_per_scene=3, max_scenes=24, roles=None, model="auto"):
    import letitedit.pictures.vfx_items as vfx_items
    import letitedit.core.render_lock as render_lock
    from PIL import Image
    loaded = json.loads(Path(report).read_text(encoding="utf-8-sig")) if not isinstance(report, dict) else report
    duration = number(loaded.get("duration_s"), "duration_s", .001, 1e7)
    video = Path(loaded["file"]).resolve(strict=True)
    if type(samples_per_scene) is not int or not 1 <= samples_per_scene <= 5:
        raise ValueError("samples_per_scene is 1-5")
    if type(max_scenes) is not int or not 1 <= max_scenes <= 100:
        raise ValueError("max_scenes is 1-100")
    folder = Path(out).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    shots = loaded.get("shots") or [{"start": 0., "end": duration}]
    roles = roles if roles is not None else loaded.get("visual_review", {}).get("intervals", [])
    info = vfx_items._probe(str(video))
    intervals = []
    previous = 0.
    for shot in shots:
        start = number(shot.get("start", shot.get("start_s")), "shot start", previous, duration)
        # the video stream can outlast the container's duration by part of a frame (the importer's last shot then ends
        # there): up to one frame over is the end of the video
        end = number(shot.get("end", shot.get("end_s", start + shot.get("len", 0))), "shot end", start,
                     duration + 1. / max(1., float(info.get("fps") or 30.)))
        end = min(end, duration)
        if end <= start:
            raise ValueError("empty lighting scene")
        intervals.append((start, end))
        previous = end
    native_rate = info["fps"]
    boundaries = sorted({min(duration, round(value * native_rate) / native_rate)
                         for value in ({value for interval in intervals for value in interval} |
                                       {float(item[key]) for item in roles for key in ("start_s", "end_s")
                                        if 0 <= item[key] <= duration})})
    intervals = [(start, end) for start, end in zip(boundaries, boundaries[1:])
                 if end - start >= .5 / native_rate and
                 any(left - .5 / native_rate <= start and right + .5 / native_rate >= end
                     for left, right in intervals)]
    profile = {"format": FORMAT, "file": str(video), "duration_s": duration, "scenes": [],
               "sampling": {"width_limit": 640, "samples_per_scene": samples_per_scene, "scene_limit": max_scenes,
                            "omitted_scenes": max(0, len(intervals) - max_scenes)},
               "limitations": ["Sparse scene samples, not continuous relighting reconstruction.",
                               "The face window and the room are measured with the face detector, not a person matte.",
                               "Visible colour proxies cannot identify illuminants, material reflectance, haze or bloom.",
                               "A missed face is unknown, not proof of b-roll or no person."]}
    with render_lock.slot("lighting measurements", timeout_s=600):
        source_width, source_height = info["size"]
        width = min(640, source_width)
        height = round(source_height * width / source_width)
        shots_module = vfx_items._creator("shots")
        for index, (start, end) in enumerate(intervals[:max_scenes]):
            role_info = next((item for item in (roles or []) if item.get("start_s", 0) <= (start + end) / 2
                              < item.get("end_s", 0)), None)
            role = role_info.get("role", "unknown") if role_info else "unknown"
            if role not in ROLES:
                raise ValueError("invalid reviewed scene role")
            scene = {"start_s": start, "end_s": end, "role": role,
                     "role_evidence": role_info.get("evidence", "caller review") if role_info else "unreviewed",
                     "samples": []}
            for sample_index in range(samples_per_scene):
                at = start + (end - start) * (sample_index + .5) / samples_per_scene
                reader = shots_module.FrameReader(video, at, 1, info["fps"], width, height)
                try:
                    frame = next(iter(reader))
                finally:
                    reader.close()
                faces = face_boxes(frame)
                matte = window_matte((height, width), faces)
                excluded = np.zeros((height, width), np.uint8)
                for event in loaded.get("text_events", []):
                    box = event.get("box")
                    if event.get("t", -10) <= at < event.get("end", -10) and box and len(box) == 4:
                        excluded |= box_mask((height, width), [[box[0] * width, box[1] * height,
                                                               (box[2] - box[0]) * width,
                                                               (box[3] - box[1]) * height]]).astype(np.uint8)
                metrics = measure(frame, matte, faces, excluded)
                import letitedit.looks.grade as grade
                metrics["grade"] = grade.stats(frame[excluded == 0].astype(np.float32) / 255)
                stem = f"scene-{index:03d}-{sample_index}"
                Image.fromarray(frame).save(folder / f"{stem}.png")
                Image.fromarray(np.rint(matte * 255).astype(np.uint8)).save(folder / f"{stem}-window.png")
                scene["samples"].append({"at_s": at, "faces": faces, "metrics": metrics,
                                          "native_effects_at_sample": sorted({event.get("kind", "unknown")
                                              for event in loaded.get("native_effects", {}).get("events", [])
                                              if event.get("t", -10) <= at < event.get("end", -10)}),
                                          "frame": f"{stem}.png", "window": f"{stem}-window.png"})
            profile["scenes"].append(scene)
    profile["live"] = reference_separation(profile)
    validate(profile)
    path = folder / "lighting.json"
    path.write_text(json.dumps(profile, indent=2, allow_nan=False), encoding="utf-8")
    (folder / "lighting.md").write_text(recipe(profile), encoding="utf-8")
    enriched = folder / "report.json"
    enriched.write_text(json.dumps({**loaded, "lighting": profile}, indent=2, allow_nan=False), encoding="utf-8")
    return {"profile": str(path), "report": str(enriched), "scenes": len(profile["scenes"]),
            "omitted_scenes": profile["sampling"]["omitted_scenes"]}


def without_section(text, heading):
    if heading not in text:
        return text.rstrip()
    before, section = text.split(heading, 1)
    following = section.find("\n## ")
    return (before.rstrip() + (section[following:] if following >= 0 else "")).rstrip()


def preserve_evidence(package, current, directory):
    if package.get("lighting_only") is not True or not current:
        raise ValueError("lighting_only needs an existing guarded Look revision")
    version = Path(directory) / "revisions" / current["revision"]
    evidence = json.loads((version / "evidence.json").read_text(encoding="utf-8-sig"))
    for field in ("id", "title", "line", "needs", "works_with", "asks"):
        if package.get(field, "footage" if field == "works_with" else [] if field == "asks" else None) != current[field]:
            raise ValueError(f"lighting_only cannot change {field}")
    for field in ("observations", "limitations"):
        if package.get(field) != evidence.get(field):
            raise ValueError(f"lighting_only cannot change {field}")
    if [str(Path(path).resolve()) for path in package["reports"]] != [
            str(Path(item["report"]).resolve()) for item in evidence["references"]]:
        raise ValueError("lighting_only cannot change reports")
    for field in ("sound", "visual", "sources", "graphic_kit"):
        previous = version / ("graphic-kit.json" if field == "graphic_kit" else f"{field}.json")
        expected = json.loads(previous.read_text(encoding="utf-8-sig")) if previous.is_file() else None
        if package.get(field, expected) != expected:
            raise ValueError(f"lighting_only cannot change {field}")
        package[field] = expected
    theme = current.get("theme")
    expected_theme = {**theme, "recipe": (version / "theme.md").read_text(encoding="utf-8")} if theme else None
    if package.get("theme") != expected_theme:
        raise ValueError("lighting_only cannot change theme")
    previous_recipe = (version / "recipe.md").read_text(encoding="utf-8")
    def unrelated(text):
        return without_section(without_section(without_section(without_section(text, "## Known limits"),
                                                               "## Measured lighting"), "## Measured grade"),
                               "## Shot sources and overlays")
    if unrelated(package["recipe"]) != unrelated(previous_recipe):
        raise ValueError("lighting_only cannot change unrelated recipe text")
    return evidence


def for_save(package, current, directory, references):
    profiles = package.get("lighting")
    if "lighting" not in package:
        profiles = [item["lighting"] for item in references if item.get("lighting") is not None] or None
        if not profiles and current:
            previous = Path(directory) / "revisions" / current["revision"] / "lighting.json"
            profiles = json.loads(previous.read_text(encoding="utf-8-sig")) if previous.is_file() else None
    if profiles is None:
        return None
    profiles = [profiles] if isinstance(profiles, dict) else profiles
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("lighting must contain one or more measured profiles, or null to remove")
    for profile in profiles:
        validate(profile, references)
    return profiles


def save_revision(version, text, profiles):
    """The recipe with its Measured lighting and Measured grade sections written from `profiles`; lighting.json and
    grade.json saved beside it (the grade is the Look's colour, worked out from the same measured samples)."""
    text = without_section(without_section(text, "## Measured lighting"), "## Measured grade")
    if profiles is not None:
        (Path(version) / "lighting.json").write_text(json.dumps(profiles, indent=2, allow_nan=False), encoding="utf-8")
        text += ("\n\n## Measured lighting\n"
                 "Read the sibling `lighting.json` for measured regions and limits. Apply measured lighting "
                 "with live editor filters (`{op: fx, lighting: true}`), tuned to the reference separation; "
                 "a natural reference stays natural, without an invented darker room or face lift. "
                 "the live lighting only lifts the face. Measurements are display RGB 0-1; skin is a proxy; vignette is "
                 "composition-confounded; haze and bloom are unmeasured. This is light on a speaker's face; the "
                 "Look's colour is its grade, below.")
        import letitedit.looks.grade as grade
        measured = grade.profile(profiles)
        if measured is not None:
            (Path(version) / "grade.json").write_text(json.dumps(measured, indent=2, allow_nan=False), encoding="utf-8")
            text += ("\n\n## Measured grade\n"
                     "The sibling `grade.json` is the Look's colour: black level, highlights, colour strength and the "
                     "lean of shadows, mid-tones and highlights, measured on the reference's own shots. It belongs on "
                     "every clip of footage, with or without a face: `{op: fx, grade: true}` fits a LUT (3D) filter "
                     "to each clip from the reference shots nearest it in brightness, after the cut is final; "
                     "skin-tone hues keep most of their colour.")
    return text


def render_job(job):
    import letitedit.pictures.vfx_items as vfx_items
    params = settings(job.p)
    source = job.src()
    if params['mode'] == 'whole':
        return render_whole(job, source, params)
    portrait = vfx_items._vfx("portrait_matte")
    shots = vfx_items._creator("shots")
    stream = portrait.MatteStream()
    intermediate = job.work / "lighting.mov"
    command = [str(vfx_items.made.ffmpeg_exe()), "-v", "error", "-y", "-threads", "4",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{job.W}x{job.H}", "-r", str(job.fps),
               "-i", "-", "-an", "-c:v", "qtrle", "-threads", "4", "-pix_fmt", "rgb24",
               str(intermediate)]
    frames = 0
    with (job.work / "encoder.log").open("wb") as errors:
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        reader = shots.FrameReader(source.path, source.start, source.frames, job.fps, job.W, job.H)
        try:
            with portrait.cache_for():
                for frame in reader:
                    matte = stream(frame)
                    faces = face_boxes(frame)
                    if params["mode"] == "background" and not faces and np.mean(matte > .9) < .01:
                        raise ValueError("no person found; background lighting refused instead of guessing")
                    if params["target"] is not None:
                        region = "background" if params["mode"] == "background" else "picture"
                        measured = measure(frame, matte, faces)[region]
                        if measured is None:
                            raise ValueError("no region to match")
                        params = {**params, **plan(params["target"], measured), "target": None}
                        job.notes.append("Lighting target fitted once on first frame; person and skin preserved.")
                    if frames == 0 and params['mode'] == 'background':
                        requested = params['strength']
                        params, output, edge = guarded_plan(frame, matte, params, faces)
                        job.notes.append(f"Lighting edge-safe constant strength {params['strength']:.4f}; requested {requested:.4f}. Reduced strength is a partial match, not a full match.")
                    else:
                        output = apply(frame, matte, params, faces)
                    edge = edge_guard(frame, output, matte)
                    if params['mode'] == 'background' and not edge['safe']:
                        raise ValueError(f"background lighting refused: new matte-edge glow {edge['new_edge_step']:.4f} exceeds {edge['limit']}; person protection was not eroded")
                    encoder.stdin.write(output.tobytes())
                    frames += 1
            encoder.stdin.close()
            if encoder.wait(timeout=120):
                raise RuntimeError("lighting encoder failed")
            if frames != source.frames:
                raise ValueError(f"lighting decoder returned {frames}/{source.frames} frames")
            vfx_items._mux(job, intermediate, source, frames, tag=False)
        finally:
            reader.close()
            if stream.worker is not None:
                stream.worker.close()
            if encoder.poll() is None:
                encoder.kill()
                encoder.wait()
            if intermediate.exists():
                intermediate.unlink()
    return frames


COVER_DEFAULTS = {'mode': 'whole', 'face_light': .6, 'face_warmth': .015, 'room_ev': -.9, 'vignette': .25}
LIVE_TAG = 'letitedit_ai:lighting'
# a soft oval window that follows the face: the lift inside it, the room outside a wider one. Sizes are multiples of the
# face box (width, height); the window is centred a little below the face's centre (fractions of the face height).
LIVE_DEFAULTS = {'face_ev': .03, 'face_gamma': 1.2, 'room_ev': -1.3, 'window': [1.7, 2.0], 'feather': .8}
LIVE_KEYS = {'face_ev': (0., 1.), 'face_gamma': (1., 1.5), 'room_ev': (-3., 0.), 'feather': (.05, 1.)}
LIVE_ROOM = {'window': [2.2, 1.8], 'drop': .1, 'feather': .6}     # the room's oval: the window times this, lower by `drop`
LIVE_WINDOW_DROP = .05
LIVE_STEP_S = .25


def _live_settings(given):
    out = {**LIVE_DEFAULTS, **given}
    for key, (low, high) in LIVE_KEYS.items():
        out[key] = number(out[key], key, low, high)
    window = out['window']
    if not (isinstance(window, (list, tuple)) and len(window) == 2):
        raise ValueError('window is [width, height] in face widths and heights')
    out['window'] = [number(window[0], 'window width', 1., 4.), number(window[1], 'window height', 1., 4.)]
    return out


def face_windows(path, start, end, speed=1.0, step=LIVE_STEP_S):
    """Where the biggest face is across a stretch of a video file: rows [t, cx, cy, w, h], t in the file's seconds and the
    rest fractions of the frame, one every `step` s. A missed detection takes the nearest row that has one; the centre
    and size are median-smoothed over five rows. [] when no face is found anywhere in the stretch."""
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if end is None:
            end = frames / fps if frames else start + 1.
        times, boxes = [], []
        t = start
        while True:
            t = min(t, end)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
            ok, frame = cap.read()
            if ok:
                height, width = frame.shape[:2]
                found = face_boxes(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                big = max(found, key=lambda b: b[2] * b[3]) if found else None
                times.append(t)
                boxes.append(None if big is None else [(big[0] + big[2] / 2) / width, (big[1] + big[3] / 2) / height,
                                                       big[2] / width, big[3] / height])
            if t >= end - 1e-6:
                break
            t += step * speed
    finally:
        cap.release()
    known = [i for i, b in enumerate(boxes) if b]
    if not known:
        return []
    rows = [boxes[i] or boxes[min(known, key=lambda k: abs(k - i))] for i in range(len(boxes))]
    arr = np.array(rows, float)
    smooth = np.array([np.median(arr[max(0, i - 2):i + 3], axis=0) for i in range(len(arr))])
    return [[round(t, 3), *[round(float(v), 5) for v in row]] for t, row in zip(times, smooth)]


def _oval(rows, wmul, hmul, drop):
    out = []
    for t, x, y, w, h in rows:
        hw, hh, yy = w * wmul / 2, h * hmul / 2, y + drop * h
        out.append([t, max(0., x - hw), max(0., yy - hh), min(1., x + hw), min(1., yy + hh)])
    return out


def live_effects(item, rows, settings):
    """The live lighting of one clip as engine effects, mask first: the room darkened outside a wide oval, the face lifted
    inside a smaller one, both keyframed to follow the face. Gain is a plain multiplier on all three channels, so
    hue and colour strength stay and the face keeps its contrast."""
    import letitedit.timeline.aim as aim

    def gain(ev, gamma=1.):
        g = round(2 ** ev, 4)
        params = {'gain_r': g, 'gain_g': g, 'gain_b': g}
        if gamma != 1.:
            params.update({'gamma_r': gamma, 'gamma_g': gamma, 'gamma_b': gamma})
        return {'filter': 'lift_gamma_gain', 'params': params}
    window = settings['window']
    pieces = []
    for effect, wmul, hmul, drop, soft, invert in (
            (gain(settings['room_ev']), window[0] * LIVE_ROOM['window'][0], window[1] * LIVE_ROOM['window'][1],
             LIVE_WINDOW_DROP + LIVE_ROOM['drop'], LIVE_ROOM['feather'], True),
            (gain(settings['face_ev'], settings['face_gamma']), window[0], window[1], LIVE_WINDOW_DROP, settings['feather'], False)):
        if abs(effect['params']['gain_r'] - 1) < 1e-3 and 'gamma_r' not in effect['params']:
            continue
        trio = aim._region_effects({'shape': 'ellipse', 'path': _oval(rows, wmul, hmul, drop), 'soft': soft,
                                    'invert': invert}, effect, item, 30.)
        trio[0] = {**trio[0], 'params': {**trio[0]['params'], LIVE_TAG: 1}}
        pieces.extend(trio)
    return pieces


def _live_pieces(effects):
    """Index ranges (start, stop) of the lighting's mask trios inside a clip's effect list."""
    spans, i = [], 0
    while i < len(effects):
        e = effects[i]
        if isinstance(e, dict) and e.get('filter') == 'mask_start' and (e.get('params') or {}).get(LIVE_TAG):
            spans.append((i, i + 3))
            i += 3
        else:
            i += 1
    return spans


def live_face_light(item):
    """(gain, gamma) of a clip's live face light (the lift_gamma_gain inside its lighting's face window, the one with a
    gamma), or None when the clip has none."""
    effects = item.get('effects') or []
    for start, stop in _live_pieces(effects):
        inner = (effects[start + 1] or {}).get('params') or {}
        if 'gamma_r' in inner:
            return float(inner.get('gain_r', 1.)), float(inner['gamma_r'])
    return None


def live_face_pixels(pixels, light):
    """Face pixels (N x 3 display RGB, 0-1) as the live face light leaves them: the engine's lift_gamma_gain is
    (gain x)^(1/gamma) in linear light, which in display values (gamma 2.2) is gain^(1/(2.2 gamma)) x^(1/gamma); the
    whole face box is taken as inside the face window. Unchanged without a light."""
    pixels = np.clip(np.asarray(pixels, float).reshape(-1, 3), 0, 1)
    if not light:
        return pixels
    gain, gamma = light
    return np.clip(gain ** (1 / (2.2 * gamma)) * np.power(pixels, 1 / gamma), 0, 1)


def is_live_lit(item):
    return bool(_live_pieces(item.get('effects') or []))


def cover_speaker(script, spec, baked_ok=True):
    """{op: fx, lighting: true | {face_ev?, room_ev?, window?, feather?}}: live lighting on every clip of the main picture
    track that plays a video file (the speaker): engine filters on the clip, a soft oval that follows the face and
    lifts it, the room outside a wider oval darkened (Mask: Simple Shape and Color Grading, both open in the editor).
    A clip already lit live is lit again from the current settings; a baked lighting clip is left alone.
    `bake: true`, or any whole-picture setting (face_light, face_warmth, vignette, exposure_ev, contrast, black,
    saturation, tint_rgb, strength, target), makes a baked lighting clip instead.
    Returns {'lit': [ids], 'already': [ids], 'skipped': [why], 'params': ...}."""
    from letitedit.timeline.edit_sync import layout, main_track, to_seconds
    spec = {} if spec is True else dict(spec or {})
    given = dict(spec.pop('params', None) or {})
    bake = bool(spec.pop('bake', False))
    live_given = {k: spec.pop(k) for k in list(spec) if k in LIVE_DEFAULTS}
    given.update({k: spec.pop(k) for k in list(spec) if k in PARAMS})
    live_given.update({k: given.pop(k) for k in list(given) if k in LIVE_DEFAULTS and k != 'room_ev'})
    if spec:
        raise ValueError(f"fx lighting: unknown {', '.join(sorted(spec))}; the settings are "
                         f"{', '.join(sorted(LIVE_DEFAULTS))}, or bake: true with {', '.join(sorted(PARAMS))}")
    if (bake or given.keys() - {'mode', 'room_ev'}) and not baked_ok:
        raise ValueError('fx lighting: lighting is live editor filters (face_ev, face_gamma, room_ev, window, feather); '
                         'a baked render, a cut-out or a whole-picture setting is not offered')
    if bake or given.keys() - {'mode', 'room_ev'}:
        bake = True
        if live_given.get('room_ev') is not None:
            given['room_ev'] = live_given.pop('room_ev')
    elif 'room_ev' in given:
        live_given['room_ev'] = given.pop('room_ev')
    main = main_track(script)
    if main is None:
        raise ValueError('fx lighting: the project has no picture track')
    import letitedit.looks.grade as grade_module
    intro = grade_module.own_intro(script)
    if bake:
        params = settings({**COVER_DEFAULTS, **given})
        params = {k: v for k, v in params.items() if k != 'target' or v is not None}
        report = {'lit': [], 'already': [], 'skipped': [], 'params': params, 'how': 'baked'}
    else:
        from_look = look_lighting(script) if not live_given else {}
        base = {**(from_look.get('settings') or {}), **live_given}
        if not base and from_look.get('reference_stops') is not None and from_look['reference_stops'] <= .15:
            base = {'face_ev': 0, 'face_gamma': 1, 'room_ev': 0}
        live = _live_settings(base)
        tune = from_look.get('reference_stops') if 'room_ev' not in base else None
        report = {'lit': [], 'already': [], 'skipped': [], 'params': live, 'how': 'live filters',
                  'look': from_look.get('look'), 'tuned': []}
    for item, start, end in layout(main):
        if isinstance(item.get('vfx'), dict):
            if item['vfx'].get('effect') == 'lighting':
                report['already'].append(item.get('id'))
            continue
        clip = item.get('clip')
        if not clip:
            continue
        if str(clip).lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')):
            report['skipped'].append(f"{item.get('id')}: a picture, not footage of the speaker")
            continue
        if grade_module.is_own_intro(clip, intro):
            report['skipped'].append(f"{item.get('id')}: the Look's own intro, played unchanged")
            continue
        if not bake:
            a = to_seconds(item.get('in') or 0)
            b = None if item.get('out') is None else to_seconds(item['out'])
            rows = face_windows(clip, a, b, float(item.get('speed') or 1.0))
            kept = list(item.get('effects') or [])
            for lo, hi in reversed(_live_pieces(kept)):
                del kept[lo:hi]
            if not rows:
                item['effects'] = kept
                report['skipped'].append(f"{item.get('id')}: no face found, so no light was put on it")
                continue
            clip_live = live
            if tune is not None:
                own = clip_separation(clip, rows, a, float(item.get('speed') or 1.0))
                if own is not None:
                    clip_live = _live_settings({**base, 'room_ev': tuned_room_ev(tune, own, live['face_ev'])})
                    report['tuned'].append({'id': item.get('id'), 'clip_stops': own, 'look_stops': tune,
                                            'room_ev': clip_live['room_ev']})
            item['effects'] = live_effects(item, rows, clip_live) + kept
            report['lit'].append(item.get('id'))
            continue
        source = {'clip': clip, 'in': item.get('in', 0)}
        if item.get('out') is not None:
            source['out'] = item['out']
        if item.get('speed') not in (None, 1, 1.0):
            source['speed'] = item['speed']
        for key in ('clip', 'in', 'out', 'speed'):
            item.pop(key, None)
        item['vfx'] = {'effect': 'lighting', 'source': source, 'params': dict(params)}
        report['lit'].append(item.get('id'))
    return report


def uncovered_speaker_clips(script):
    """Ids of main-track clips that play a video file and carry no lighting: the speaker clips still unlit."""
    from letitedit.timeline.edit_sync import main_track
    main = main_track(script)
    if main is None:
        return []
    return [str(item.get('id')) for item in main['items']
            if item.get('clip') and not isinstance(item.get('vfx'), dict) and not is_live_lit(item)
            and not str(item['clip']).lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'))]


def _only_main(script, strip):
    import copy
    from letitedit.timeline.edit_sync import main_track
    out = copy.deepcopy(script)
    main = main_track(out)
    out['tracks'] = [t for t in out['tracks'] if t['name'] == main['name']]
    out.pop('master', None)
    for t in out['tracks']:
        t.pop('effects', None)
        if strip:
            for item in t['items']:
                kept = list(item.get('effects') or [])
                for lo, hi in reversed(_live_pieces(kept)):
                    del kept[lo:hi]
                item['effects'] = kept
    return out


LIVE_CACHE_FORMAT = 1


def _live_key(script, entries, index, step_s):
    """What a lit clip's measured rows depend on: the clip itself (source, in/out, speed, its effects), its source file's
    size and dates, the picture size, the step, and its neighbours when a transition joins them. The check renders the
    main track alone without master or track effects, so nothing else reaches these frames."""
    import hashlib

    def clean(item):
        return {k: v for k, v in item.items() if k not in ('id', 'at')} if item else None
    item = entries[index][0]
    source = None
    try:
        details = Path(str(item.get('clip'))).stat()
        source = [details.st_size, details.st_mtime_ns]
    except OSError:
        pass
    parts = {'format': LIVE_CACHE_FORMAT, 'item': clean(item), 'profile': script.get('profile'), 'step': step_s,
             'source': source}
    after = entries[index + 1][0] if index + 1 < len(entries) else None
    if item.get('transition') or (after or {}).get('transition'):
        parts['neighbours'] = [clean(entries[index - 1][0]) if index else None, clean(after)]
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _live_cache(project):
    import letitedit.timeline.project_journal as project_journal
    return Path(project_journal.folder(project)) / 'live-lighting.json'


def check_live(project, step_s=.5, out_dir=None):
    """The live lighting measured on what the export engine draws: the main picture track alone, rendered with the lighting
    and again without it, at the same moments (every `step_s` s of every lit clip); the face box of each frame (found on the
    unlit picture) is compared with FACE_LIMITS, and the room's change in brightness is measured outside a wide box around
    the face. Each lit clip's rows are kept beside the project (live-lighting.json, keyed by what the clip's frames
    depend on): only clips that changed are drawn and measured again. Returns {'passed', 'frames': n, 'face': {...worst
    values}, 'room': {...}, 'rows': [...], 'measured_clips', 'reused_clips'}."""
    import shutil
    import tempfile
    import letitedit.review.checks as checks
    import letitedit.timeline.edit_script as edit_script
    from letitedit.timeline.edit_sync import layout, main_track
    script = edit_script.read(project)
    main = main_track(script)
    if main is None:
        raise ValueError('check_live: no picture track')
    entries = list(layout(main))
    spans = [(index, item, s, e) for index, (item, s, e) in enumerate(entries) if is_live_lit(item)]
    if not spans:
        return {'passed': False, 'frames': 0, 'problem': 'no clip carries live lighting'}
    cache_file = _live_cache(project)
    try:
        cache = json.loads(cache_file.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        cache = {}
    keys = {index: _live_key(script, entries, index, step_s) for index, _, _, _ in spans}
    todo = [(index, item, s, e) for index, item, s, e in spans if keys[index] not in cache]
    times = [(index, round(s + (k + .5) * step_s, 3)) for index, _, s, e in todo
             for k in range(max(1, int((e - s) / step_s))) if s + (k + .5) * step_s < e]
    if times:
        work = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix='live-light-'))
        try:
            frames = {}
            for name, strip in (('lit', False), ('plain', True)):
                folder = work / name
                shutil.rmtree(folder, ignore_errors=True)
                folder.mkdir(parents=True)
                mlt = folder / 'main.mlt'
                shutil.copy2(edit_script._resolve(project), mlt)
                edit_script.compile_script(_only_main(script, strip), base=mlt, out=mlt, force=True)
                timeline, path = checks.resolve(mlt)
                fps = timeline.profile['frame_rate_num'] / timeline.profile['frame_rate_den']
                # full size: clipped skin is counted pixel by pixel, and smaller frames average highlights away
                # (at half size it read 0.0004 where full size read 0.0043, the limit being 0.01)
                frames[name] = checks.render_frames(timeline, path, [round(t * fps) for _, t in times], folder)
            fresh = {index: [] for index, _, _, _ in todo}
            starts = {index: s for index, _, s, _ in todo}
            for (index, t), plain, lit in zip(times, frames['plain'], frames['lit']):     # a pair at a time in memory
                plain, lit = (cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB) for p in (plain, lit))
                fresh[index].append({**_live_row(t, plain, lit), 't': round(t - starts[index], 3)})
            for index, rows in fresh.items():
                cache[keys[index]] = rows
        finally:
            if not out_dir:
                shutil.rmtree(work, ignore_errors=True)
        live = set(keys.values())
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix('.tmp')
            temporary.write_text(json.dumps({k: v for k, v in cache.items() if k in live}), encoding='utf-8')
            temporary.replace(cache_file)
        except OSError:
            pass
    rows = [{**row, 't': round(row['t'] + s, 3)} for index, _, s, _ in spans for row in cache[keys[index]]]
    worst = {'min_luma_delta': 1., 'max_hue_shift_deg': 0., 'max_chroma_change': 0., 'max_clipped_gain': 0.,
             'max_median_luma': 0.}
    room_changes = [row['room_ev'] for row in rows if 'room_ev' in row]
    for row in rows:
        if 'within_limits' not in row:
            continue
        worst['min_luma_delta'] = min(worst['min_luma_delta'], row['worst']['min_luma_delta'],
                                      row['worst']['min_median_luma_delta'])
        for key in ('max_hue_shift_deg', 'max_chroma_change', 'max_clipped_gain', 'max_median_luma'):
            worst[key] = max(worst[key], row['worst'][key])
    measured = [r for r in rows if r.get('face') is not False and 'within_limits' in r]
    result = {'passed': bool(measured) and all(r['within_limits'] for r in measured), 'frames': len(rows),
              'with_face': len(measured), 'limits': dict(FACE_LIMITS), 'face': worst,
              'room': {'mean_ev_change': float(np.mean(room_changes)) if room_changes else 0.},
              'rows': [{k: v for k, v in r.items() if k != 'worst'} for r in rows],
              'measured_clips': len(todo), 'reused_clips': len(spans) - len(todo)}
    if out_dir:
        result['folder'] = str(out_dir)
    return result


def _live_row(t, plain, lit):
    """One moment of a lit clip: the face's change (FACE_LIMITS) and the room's, or face None when none is found."""
    faces = face_boxes(plain)
    if not faces:
        return {'t': t, 'face': None}
    change = face_change(plain, lit, faces)
    # clipping is counted on skin: a bright cap or collar inside the box is not the face
    skin = skin_mask(plain)
    for face, row in zip(faces, change['rows']):
        y0, y1, x0, x1 = _box_pixels(plain, face)
        keep = skin[y0:y1, x0:x1]
        if keep.sum() >= 32:
            a, b = plain[y0:y1, x0:x1][keep], lit[y0:y1, x0:x1][keep]
            row['clipped_gain'] = float((b.max(axis=1) >= 250).mean() - (a.max(axis=1) >= 250).mean())
    change['max_clipped_gain'] = max((r['clipped_gain'] for r in change['rows']), default=0.)
    zone = box_mask(plain.shape[:2], faces, margin=.35)
    before, after = (plain.astype(np.float32) @ WEIGHTS)[~zone].mean(), (lit.astype(np.float32) @ WEIGHTS)[~zone].mean()
    room = float(np.log2(max(after, 1e-3) / max(before, 1e-3)))
    return {'t': t, 'luma_delta': change['min_luma_delta'], 'median_luma_delta': change['min_median_luma_delta'],
            'hue_shift_deg': change['max_hue_shift_deg'], 'chroma_change': change['max_chroma_change'],
            'clipped_gain': change['max_clipped_gain'], 'median_luma_after': change['max_median_luma'],
            'within_limits': bool(face_within_limits(change)), 'room_ev': room,
            'worst': {key: float(change[key]) for key in ('min_luma_delta', 'min_median_luma_delta', 'max_hue_shift_deg',
                                                          'max_chroma_change', 'max_clipped_gain', 'max_median_luma')}}
