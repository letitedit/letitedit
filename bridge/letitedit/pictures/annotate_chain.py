"""The clip's picture chain as data, the target in source pixels, and source times as timeline frames.

Part of `annotate` (letitedit/pictures/annotate.py), which imports every name here back,
so `annotate.X` is the same object it always was.
"""
from __future__ import annotations
import json
import math
import os
import re
from pathlib import Path
from letitedit.pictures.annotate_geometry import (  # noqa: E402
    IDENTITY, Unsupported, _frames_attr, _norm_angle, _props, anim_number, anim_values, box_inter, map_box,
    mat_inv, mat_mul, mat_rot, mat_rotation_of, mat_scale, mat_scale_of, mat_translate, media_info, parse_rect,
    rotate_map
)


# ============================================================================ the clip's picture chain, as data

MODELED = {'crop': 'crop', 'affine': 'affine', 'avfilter.hflip': 'flip_h', 'avfilter.vflip': 'flip_v'}
RETIMING = {'timeremap': 'Time Remap changes the clip\'s speed', 'choppy': None}
# effects that move, warp or shake the picture in ways this module does not model: annotating through them is refused
GEOMETRY_UNSUPPORTED = {
    'mirror': 'Mirror (reflection)', 'dance': 'Dance (moves with the sound)', 'frei0r.c0rners': 'Corner Pin',
    'frei0r.defish0r': 'Defish', 'frei0r.distort0r': 'Distort', 'frei0r.elastic_scale': 'Elastic Scale',
    'frei0r.lenscorrection': 'Lens Correction', 'frei0r.vertigo': 'Vertigo', 'frei0r.camerashake': 'Camera Shake',
    'frei0r.nosync0r': 'Old TV (vertical roll)', 'oldfilm': 'Old Film (jitter)', 'vidstab': 'Stabilize',
    'wave': 'Wave', 'avfilter.crop': 'crop (FFmpeg)', 'avfilter.scale': 'scale (FFmpeg)',
    'avfilter.zoompan': 'zoompan (FFmpeg)', 'avfilter.rotate': 'rotate (FFmpeg)', 'avfilter.transpose': 'transpose',
    'avfilter.perspective': 'perspective', 'avfilter.lenscorrection': 'lenscorrection (FFmpeg)',
    'avfilter.v360': 'v360', 'avfilter.deshake': 'deshake', 'avfilter.vidstabtransform': 'vidstabtransform',
    'avfilter.pad': 'pad (FFmpeg)', 'avfilter.scroll': 'scroll', 'avfilter.shear': 'shear',
    'frei0r.scale0tilt': 'Scale0Tilt', 'frei0r.3dflippo': '3dflippo', 'frei0r.flippo': 'Flippo',
    'frei0r.perspective': 'Perspective', 'frei0r.rotozoom': 'Rotozoom', 'movit.rect': 'Size and Position (GPU)',
    'movit.flip': 'Flip (GPU)', 'movit.mirror': 'Mirror (GPU)', 'affineRotate_3d': '3D rotation',
}
GEOMETRY_UNSUPPORTED_PREFIX = ('frei0r.bigsh0t', 'avfilter.v360')
# common effects known to leave the picture where it is (colour, light, blur, text, masks, sound); anything else that
# isn't modelled or refused is reported as 'assumed to keep the picture in place'
NEUTRAL = {
    'brightness', 'volume', 'panner', 'audiolevelgraph', 'audiowaveform', 'audiospectrum', 'avfilter.eq', 'avfilter.hue',
    'avfilter.vibrance', 'avfilter.lut3d', 'avfilter.gblur', 'avfilter.smartblur', 'avfilter.deband', 'avfilter.noise',
    'avfilter.hqdn3d', 'avfilter.vaguedenoiser', 'avfilter.fspp', 'avfilter.chromahold', 'avfilter.colorbalance',
    'avfilter.colorchannelmixer', 'avfilter.curves', 'avfilter.unsharp', 'avfilter.tmix', 'avfilter.haas',
    'avfilter.adeclick', 'box_blur', 'boxblur', 'charcoal', 'dynamictext', 'qtext', 'subtitle', 'frei0r.IIRblur',
    'frei0r.alpha0ps', 'frei0r.alphaspot', 'frei0r.coloradj_RGB', 'frei0r.colorhalftone', 'frei0r.dither',
    'frei0r.glow', 'frei0r.hqdn3d', 'frei0r.levels', 'frei0r.pixeliz0r', 'frei0r.posterize', 'frei0r.premultiply',
    'frei0r.rgbnoise', 'frei0r.saturat0r', 'frei0r.sharpness', 'frei0r.select0r', 'frei0r.bluescreen0r',
    'frei0r.keyspillm0pup', 'frei0r.spillsupress', 'frei0r.colgate', 'frei0r.cairogradient', 'frei0r.scanline0r',
    'gradientmap', 'grain', 'hslprimaries', 'hslrange', 'invert', 'lift_gamma_gain', 'lines', 'dust', 'mask_apply',
    'mask_start', 'outline', 'dropshadow', 'pillar_echo', 'qtcrop', 'sepia', 'spot_remover', 'strobe', 'tcolor',
    'threshold', 'vignette', 'gpsgraphic', 'gpstext', 'timer', 'opencv.tracker', 'loudness', 'dynamic_loudness',
    'rbpitch', 'rnnoise', 'audioseam', 'mono', 'channelcopy', 'autofade', 'cairoblend_mode', 'qtblend_mode',
    'lightshow', 'greyscale', 'grayscale', 'avfilter.random', 'frei0r.glitch0r', 'frei0r.rgbsplit0r',
}


def _effect_name(fp):
    import letitedit.timeline.edit_effects as ee
    try:
        return ee.name_of(fp)
    except Exception:  # noqa: BLE001 - the raw service names it well enough
        return fp.get('shotcut:filter') or fp.get('mlt_service') or '?'


def _clip_effect_steps(prod, iid, fps, notes):
    """The clip's effects in order: the ones that move its picture become steps, the rest are listed with
    their role; effects that can't be mapped are refused."""
    steps, effects, crops, affines = [], [], 0, 0
    for el in prod:
        if el.tag not in ('filter', 'link'):
            continue
        fp = _props(el)
        if fp.get('_loader') == '1':
            continue
        fsvc = fp.get('mlt_service', '')
        name = _effect_name(fp)
        hidden = fp.get('shotcut:hidden') == '1' or bool(fp.get('letitedit_ai:part'))
        fin = _frames_attr(el.get('in'), fps)
        fout = _frames_attr(el.get('out'), fps)
        if fp.get('disable') == '1':
            effects.append({'effect': name, 'role': 'off'})
            continue
        if RETIMING.get(fsvc):
            raise Unsupported(f'{iid}: {RETIMING[fsvc]}; retimed clips are refused (source and timeline time differ)')
        if fsvc == 'choppy':
            notes.append('Choppy holds frames: a tracked pointer can lag the picture by a few frames')
        if fsvc in GEOMETRY_UNSUPPORTED or fsvc.startswith(GEOMETRY_UNSUPPORTED_PREFIX):
            raise Unsupported(f'{iid}: the effect {GEOMETRY_UNSUPPORTED.get(fsvc, fsvc)} moves or warps the picture in a '
                              'way this tool does not map; remove or disable it, annotate, then put it back (or point '
                              'by frame coordinates with letitedit_graphic)')
        if el.tag == 'link':
            raise Unsupported(f'{iid}: the link effect {name} may change time or picture; only plain effects are mapped')
        role = MODELED.get(fsvc)
        if fsvc == 'crop' and fp.get('active') == '1':
            role = None
        if fsvc == 'affine':
            unsup = [k for k in ('transition.fix_rotate_y', 'transition.fix_rotate_z', 'transition.rotate_y',
                                 'transition.rotate_z', 'transition.fix_shear_x', 'transition.fix_shear_y',
                                 'transition.fix_shear_z', 'transition.shear_x', 'transition.shear_y',
                                 'transition.shear_z', 'transition.scale', 'transition.keyed', 'transition.cycle',
                                 'transition.mirror')
                     if fp.get(k) not in (None, '', '0', '0.0')]
            if unsup:
                raise Unsupported(f'{iid}: Size/Position/Rotate uses {", ".join(unsup)} (3-D turns, shear, cycles), '
                                  'which this tool does not map')
            affines += 1
        if fsvc == 'crop' and role:
            crops += 1
        if role:
            steps.append({'step': role, 'props': fp, 'in': fin, 'out': fout, 'effect': name})
            effects.append({'effect': name, 'role': 'mapped' + (' (hidden part)' if hidden else '')})
        else:
            effects.append({'effect': name, 'role': 'no geometry' if fsvc in NEUTRAL or fsvc == 'crop'
                            else 'assumed to keep the picture in place (not a known geometry effect)'})
    if affines > 1:
        raise Unsupported(f'{iid} has {affines} Size/Position/Rotate effects; the engine stacks them in a way this tool '
                          'does not map (combine them into one)')
    if crops > 1:
        raise Unsupported(f'{iid} has {crops} Crop: Source effects; only the last would take effect - keep one')
    return steps, effects


def _check_track_and_master(place, doc, iid, notes):
    """Refuses a whole-track effect that moves pictures; notes whole-video effects that move the final
    picture."""
    # whole-track effects that move the picture of every clip on the track are not modelled
    for el in place['playlist'].findall('filter'):
        fp = _props(el)
        fsvc = fp.get('mlt_service', '')
        if fp.get('disable') == '1' or fp.get('shotcut:trackVolume'):
            continue
        if fsvc in MODELED or fsvc in GEOMETRY_UNSUPPORTED or fsvc.startswith(GEOMETRY_UNSUPPORTED_PREFIX):
            raise Unsupported(f"{iid}: the track {place['track']} has a whole-track effect that moves pictures "
                              f'({_effect_name(fp)}); move it onto the clips, then annotate')
    master = []
    for el in doc.main.findall('filter'):
        fp = _props(el)
        fsvc = fp.get('mlt_service', '')
        if fsvc in MODELED or fsvc in GEOMETRY_UNSUPPORTED or fsvc.startswith(GEOMETRY_UNSUPPORTED_PREFIX) or \
                fp.get('shotcut:filter') == 'reframe':
            master.append(_effect_name(fp))
    if master:
        notes.append(f'whole-video effect(s) {", ".join(master)} move the final picture; the annotation goes through '
                     'them with the picture (it stays on target), but frame-edge and label checks are made before them')


def clip_chain(doc, place):
    """The clip's picture chain as data: where the source picture's pixels go, step by step, read from the project
    file. Raises Unsupported for clips and effects this module can't map honestly (with the reason)."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.made as made
    prod = place['producer']
    if prod is None:
        raise Unsupported(f"{place['id']}: the clip's media element is missing from the project")
    p = _props(prod)
    W, H, fps = doc.width, doc.height, doc.fps
    iid = place['id']
    if place['track_kind'] != 'video':
        raise Unsupported(f'{iid} is on the audio track {place["track"]}; annotations point at pictures')
    if prod.tag == 'tractor':
        raise Unsupported(f'{iid} is a nested timeline/transition, not a source clip')
    if p.get(es.GRAPHIC_PROP):
        raise Unsupported(f'{iid} is a graphic, not footage; draw on it with letitedit_graphic instead')
    if p.get(made.MADE_PROP):
        try:
            kind = json.loads(p[made.MADE_PROP]).get('kind')
        except ValueError:
            kind = '?'
        if kind == 'reverse':
            raise Unsupported(f'{iid} plays its source in reverse: a reversed clip can\'t be annotated in source '
                              'coordinates (its time runs backwards); annotate the forward clip, then reverse it')
        raise Unsupported(f'{iid} is a made clip ({kind}): its picture is a rendered file, not the source footage')
    if p.get(made.FX_PROP):
        raise Unsupported(f'{iid} plays through an ffmpeg effect graph (a rendered copy); its geometry can\'t be mapped '
                          'from the source. Remove that effect, annotate, then add it back')
    svc = p.get('mlt_service', prod.tag)
    speed = float(p.get('warp_speed') or 1.0)
    if svc == 'timewarp' or abs(speed - 1.0) > 1e-9:
        raise Unsupported(f'{iid} plays at {speed:g}x speed: speed-changed clips are refused (source time and timeline '
                          'time would drift apart). Annotate it at normal speed, or annotate by timeline time on a '
                          'normal-speed copy')
    if svc == 'color':
        raise Unsupported(f'{iid} is a colour clip; there is no source picture to point into')
    res = p.get('warp_resource') or p.get('resource') or ''
    if not res or not os.path.isfile(res):
        raise Unsupported(f'{iid}: its source file is missing ({res})')
    info = media_info(res)
    if info['mirrored']:
        raise Unsupported(f'{Path(res).name}: its orientation flag mirrors the picture as well as turning it; '
                          'mirrored orientation flags are not supported')
    if info['image'] and Path(res).suffix.lower() in ('.jpg', '.jpeg', '.heic', '.tif', '.tiff'):
        try:
            from PIL import Image as _Img
            with _Img.open(res) as im:
                exif_orient = (im.getexif() or {}).get(274, 1)
        except Exception:  # noqa: BLE001
            exif_orient = 1
        if exif_orient not in (None, 1):
            raise Unsupported(f'{Path(res).name} has an EXIF orientation ({exif_orient}); photos turned by EXIF are '
                              'not supported yet')
    cw, ch = info['coded']
    file_theta = 0 if info['image'] else info['rotation']
    engine_theta = file_theta
    notes = []
    if p.get('rotate') not in (None, ''):
        try:
            engine_theta = int(_norm_angle(float(p['rotate'])))
        except ValueError:
            engine_theta = file_theta
        if engine_theta not in (0, 90, 180, 270):
            raise Unsupported(f'{iid}: the editor rotation override ({p["rotate"]}) is not a quarter turn')
        if engine_theta != file_theta:
            notes.append(f'the editor turns this file {engine_theta} deg (its own flag says {file_theta} deg); the '
                         'target is given in the picture as players show the file')
    if p.get('autorotate') == '0':
        engine_theta = 0
        if file_theta:
            notes.append('the editor shows this file without turning it upright (autorotate off)')
    if engine_theta not in (0, 90, 180, 270) or file_theta not in (0, 90, 180, 270):
        raise Unsupported(f'{Path(res).name}: orientation {file_theta} deg is not a quarter turn')
    pic_w, pic_h = (ch, cw) if engine_theta in (90, 270) else (cw, ch)
    if ((engine_theta in (90, 270) and cw == 1088) or (engine_theta not in (90, 270) and ch == 1088)) \
            and abs(W / H - 16 / 9) < 1e-6:
        raise Unsupported(f'{Path(res).name} is a 1088-line encoding; the engine trims it to 1080 lines by its own '
                          'workaround, which this module does not model')
    force = float(p.get('force_aspect_ratio') or 0)
    sar = force if force > 0 else float(info['sar'] or 1.0)
    if engine_theta in (90, 270) and abs(sar - 1.0) > 1e-3:
        raise Unsupported(f'{Path(res).name}: a turned picture with non-square pixels (pixel aspect {sar:g}) is not '
                          'supported')
    orient = mat_mul(rotate_map(engine_theta, cw, ch), mat_inv(rotate_map(file_theta, cw, ch)))
    steps, effects = _clip_effect_steps(prod, iid, fps, notes)
    _check_track_and_master(place, doc, iid, notes)
    return {'clip': iid, 'file': res, 'media': info, 'profile': [W, H], 'fps': fps, 'picture': [pic_w, pic_h],
            'sar': sar, 'engine_rotation': engine_theta, 'file_rotation': file_theta, 'orient': orient,
            'steps': steps, 'effects': effects, 'notes': notes}


def _crop_values(fp, mw, mh, sar, W, H):
    """Crop: Source as filter_crop.c computes it (integer arithmetic included): (left, right, top, bottom)."""
    def i(k):
        try:
            return int(float(fp.get(k) or 0))
        except ValueError:
            return 0
    left, right, top, bottom = i('left'), i('right'), i('top'), i('bottom')
    if fp.get('use_profile') == '1':
        top, bottom = int(top * mh / H), int(bottom * mh / H)
        left, right = int(left * mw / W), int(right * mw / W)
    if fp.get('center') == '1':
        ar = sar or 1.0
        input_ar = ar * mw / mh
        output_ar = W / H
        bias = i('center_bias')
        if input_ar > output_ar:
            left = right = int((mw - _rint(output_ar * mh / ar)) / 2)
            if fp.get('use_profile') == '1':
                bias = int(bias * mw / W)
            if abs(bias) > left:
                bias = -left if bias < 0 else left
            left -= bias
            right += bias
        else:
            top = bottom = int((mh - _rint(ar * mw / output_ar)) / 2)
            if fp.get('use_profile') == '1':
                bias = int(bias * mh / H)
            if abs(bias) > top:
                bias = -top if bias < 0 else top
            top -= bias
            bottom += bias
    left += (mw - left - right) & 1
    if mw - left - right < 8:
        left = right = 0
    if mh - top - bottom < 8:
        top = bottom = 0
    return left, right, top, bottom


def _rint(x):
    """C rint (round half to even)."""
    return float(round(x))


def _align(text):
    """transition_affine.c alignment_parse."""
    if text is None or text == '':
        return 0.0
    if text[0].isdigit():
        m = re.match(r'\d+', text)
        return float(int(m.group(0))) if m else 0.0
    if text[0] in 'cm':
        return 1.0
    if text[0] in 'rb':
        return 2.0
    return 0.0


def _affine_matrix(fp, pos, length, fps, mw, mh, sar, W, H):
    """Size, Position & Rotate (the affine filter) at a position, as transition_affine.c computes it: the matrix from
    the current picture's coordinates (mw x mh) to the output frame, and the rect used."""
    rect_text = fp.get('transition.rect')
    if rect_text:
        x, y, w, h, o = anim_values(rect_text, pos, fps, length, lambda v: tuple(parse_rect(v, W, H)))
    else:
        x, y, w, h, o = 0.0, 0.0, float(W), float(H), 1.0
    if w <= 0 or h <= 0:
        raise Unsupported('Size/Position/Rotate has a zero-size rectangle here')
    # the affine transition's own defaults (transition_affine_init): fill 1, distort 0, a full-frame rect
    fill = int(float(fp['transition.fill'])) if fp.get('transition.fill') not in (None, '') else 1
    distort = int(float(fp.get('transition.distort') or 0))
    b_ar = sar or 1.0
    consumer_ar = 1.0
    b_dar = b_ar * mw / mh
    gw, gh = w, h
    rw, rh = w, h
    if not fill:
        geometry_dar = w * consumer_ar / h
        if b_dar > geometry_dar:
            rw = min(w, mw * b_ar / consumer_ar)
            rh = rw * consumer_ar / b_dar
        else:
            rh = min(h, mh)
            rw = rh * b_dar / consumer_ar
    if fill or distort or mw > rw or mh > rh:
        b_h = int(min(max(rh, 1), 16000))
        b_w = int(max(b_h * b_dar / b_ar, 1))
        if b_w > 16000:
            b_w = int(min(max(rw, 1), 16000))
            b_h = int(max(b_w * b_ar / b_dar, 1))
    else:
        b_w, b_h = mw, mh
    geom_sx, geom_sy = b_w / rw, b_h / rh
    sxp = anim_number(fp.get('transition.scale_x'), pos, fps, length, 0.0)
    syp = anim_number(fp.get('transition.scale_y'), pos, fps, length, 0.0)
    if int(float(fp.get('transition.invert_scale') or 0)):
        sxp = 1.0 / sxp if sxp else float('inf')
        syp = 1.0 / syp if syp else float('inf')
    sxp = sxp if sxp != 0 else 1.0
    syp = syp if syp != 0 else 1.0
    if not (math.isfinite(sxp) and math.isfinite(syp)):
        raise Unsupported('Rotate and Scale has a zero scale')
    if distort:
        sx, sy = geom_sx * sxp, geom_sy * syp
    else:
        consumer_dar = consumer_ar * W / H
        if b_dar > consumer_dar:
            sx, sy = geom_sx * sxp, geom_sx * syp * (b_ar / consumer_ar)
        else:
            sx, sy = geom_sy * sxp * (consumer_ar / b_ar), geom_sy * syp
    theta = anim_number(fp.get('transition.fix_rotate_x'), pos, fps, length, 0.0, angle=True)
    theta += float(fp.get('transition.rotate_x') or 0) * pos
    ox = anim_number(fp.get('transition.ox'), pos, fps, length, 0.0)
    oy = anim_number(fp.get('transition.oy'), pos, fps, length, 0.0)
    if fp.get('transition.halign') not in (None, '') or fp.get('transition.valign') not in (None, ''):
        ha, va = _align(fp.get('transition.halign')), _align(fp.get('transition.valign'))
        a_out = (x + gw * ha / 2.0, y + gh * va / 2.0)
        a_b = (ha * b_w / 2.0, va * b_h / 2.0)
    else:
        a_out = (x + rw / 2.0, y + rh / 2.0)
        a_b = (b_w / 2.0, b_h / 2.0)
    # engine: b_index = M (out_index - a_out) + (ox, oy) + a_b, with b_index = b_c - 0.5 and b_c = src * (b_w/mw).
    # affine_multiply(A, B) computes A * B^T, so the rotation the engine applies is R(-theta): M = R(-theta) S
    to_b = mat_scale(b_w / mw, b_h / mh)
    rs = mat_mul(mat_rot(-theta), mat_scale(sx, sy))
    m = mat_mul(mat_translate(-0.5, -0.5), to_b)                                    # picture -> b index
    m = mat_mul(mat_translate(-a_b[0] - ox, -a_b[1] - oy), m)
    m = mat_mul(mat_inv(rs), m)                                                      # -> out index - a_out
    m = mat_mul(mat_translate(a_out[0] + 0.5, a_out[1] + 0.5), m)                   # -> out (continuous)
    return m, {'rect': [round(x, 3), round(y, 3), round(w, 3), round(h, 3)], 'rotation': round(theta, 3),
               'opacity': round(o, 4), 'mode': 'distort' if distort else 'fill' if fill else 'fit',
               'b_size': [b_w, b_h], 'scale': [round(sx, 6), round(sy, 6)]}


def _fit_matrix(mw, mh, sar, W, H):
    """The engine's fit of a picture into the frame (filter_resize.c: aspect kept, centred, whole pixels)."""
    input_ar = (sar or 1.0) * mw / mh
    output_ar = W / H
    sw = int(_rint(input_ar * W / output_ar))
    sh = H
    if sw > W:
        sw = W
        sh = int(_rint(output_ar * H / input_ar))
    x0, y0 = (W - sw) // 2, (H - sh) // 2
    return mat_mul(mat_translate(x0, y0), mat_scale(sw / mw, sh / mh)), [x0, y0, sw, sh]


def chain_at(chain, pos):
    """The chain evaluated at producer frame `pos` (the clip's own frame number, as the engine counts it): the
    matrix from source DISPLAY pixels (the picture as players show the file) to output pixels, the picture's
    corners in the output, and what each step did."""
    W, H = chain['profile']
    fps = chain['fps']
    sar = chain['sar']
    m = chain['orient']
    mw, mh = chain['picture']
    applied = []

    def active(st):
        return (st['in'] is None or pos >= st['in']) and (st['out'] is None or pos <= st['out'])

    def local(st):
        start = st['in'] or 0
        length = (st['out'] - start + 1) if st['out'] is not None else 2 ** 30
        return pos - start, length
    crop = next((st for st in chain['steps'] if st['step'] == 'crop' and active(st)), None)
    if crop:
        l, r, t, b = _crop_values(crop['props'], mw, mh, sar, W, H)
        if l or r or t or b:
            m = mat_mul(mat_translate(-l, -t), m)
            mw, mh = mw - l - r, mh - t - b
            applied.append({'step': 'crop', 'left': l, 'right': r, 'top': t, 'bottom': b, 'picture': [mw, mh]})
    pic = IDENTITY                       # cropped picture coordinates -> current coordinates
    canvas = False
    for st in chain['steps']:
        if st['step'] == 'crop' or not active(st):
            continue
        if st['step'] in ('flip_h', 'flip_v'):
            w_, h_ = (W, H) if canvas else (mw, mh)
            f = ([[-1.0, 0.0, float(w_)], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] if st['step'] == 'flip_h' else
                 [[1.0, 0.0, 0.0], [0.0, -1.0, float(h_)], [0.0, 0.0, 1.0]])
            m, pic = mat_mul(f, m), mat_mul(f, pic)
            applied.append({'step': st['step'], 'on': 'frame' if canvas else 'picture'})
        elif st['step'] == 'affine':
            p, length = local(st)
            a, info = _affine_matrix(st['props'], p, length, fps, mw, mh, sar, W, H)
            m, pic = mat_mul(a, m), mat_mul(a, pic)
            canvas = True
            applied.append({'step': 'size_position', **info})
    if not canvas:
        f, placed = _fit_matrix(mw, mh, sar, W, H)
        m, pic = mat_mul(f, m), mat_mul(f, pic)
        applied.append({'step': 'fit', 'placed': placed})
    qbox, quad = map_box(pic, (0, 0, mw, mh))
    return {'m': m, 'quad': quad, 'picture_box': box_inter(qbox, (0, 0, W, H)), 'applied': applied,
            'scale': mat_scale_of(m), 'rotation': mat_rotation_of(m), 'crop_size': [mw, mh]}


def point_in_quad(x, y, quad, margin=0.0):
    """True when (x, y) is inside the convex quad (shrunk by margin pixels)."""
    sign = 0
    n = len(quad)
    for k in range(n):
        (ax, ay), (bx, by) = quad[k], quad[(k + 1) % n]
        cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        length = math.hypot(bx - ax, by - ay) or 1.0
        d = cross / length
        if abs(d) < margin:
            return False
        s = 1 if d > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


# ============================================================================ the target, in source pixels

def target_box(target, info, space='display', units='fraction'):
    """A target [x0, y0, x1, y1] (box) or [x, y] (point) in the clip's own picture -> (box in DISPLAY pixels,
    'box' | 'point'). space: 'display' (upright, as players and frame tools show the file) or 'coded' (the stored
    pixel grid before the orientation flag). units: 'fraction' (0-1 of that picture) or 'px'."""
    if not isinstance(target, (list, tuple)) or len(target) not in (2, 4):
        raise ValueError('target is a box [x0, y0, x1, y1] or a point [x, y] in the clip\'s own picture')
    vals = [float(v) for v in target]
    dw, dh = info['display']
    cw, ch = info['coded']
    if space not in ('display', 'coded'):
        raise ValueError("space is 'display' (the upright picture, default) or 'coded' (before the orientation flag)")
    w, h = (dw, dh) if space == 'display' else (cw, ch)
    if units == 'fraction':
        if any(v < -0.05 or v > 1.05 for v in vals):
            raise ValueError(f'target {target} is not in 0-1 fractions of the picture (units="px" for source pixels)')
        vals = [v * (w if k % 2 == 0 else h) for k, v in enumerate(vals)]
    elif units != 'px':
        raise ValueError("units is 'fraction' (default) or 'px'")
    kind = 'point' if len(vals) == 2 else 'box'
    box = (vals[0], vals[1], vals[0], vals[1]) if kind == 'point' else \
        (min(vals[0], vals[2]), min(vals[1], vals[3]), max(vals[0], vals[2]), max(vals[1], vals[3]))
    if space == 'coded' and info.get('rotation'):
        box = map_box(rotate_map(info['rotation'], cw, ch), box)[0]
    x0, y0, x1, y1 = box
    if x1 < 0 or y1 < 0 or x0 > dw or y0 > dh:
        raise ValueError(f'target {target} is outside the {dw}x{dh} picture')
    return (max(0.0, x0), max(0.0, y0), min(float(dw), x1), min(float(dh), y1)), kind


# ============================================================================ time: source range -> timeline frames

def clip_span(place):
    """Timeline frames where the clip is seen [first, end): its own frames plus transitions into and out of it."""
    return place['start'] - place['lead'], place['start'] + place['frames'] + place['tail']


def src_time(place, F, fps):
    """Source seconds shown at timeline frame F (normal speed)."""
    return (place['in'] + F - place['start']) / fps


def timeline_frame(place, t_src, fps):
    return place['start'] + int(round(t_src * fps)) - place['in']


def resolve_range(place, fps, source_range=None, timeline_range=None, at=None, duration=3.0):
    """[F0, F1) timeline frames for the annotation and the source time of the target (`at`), from a source range, a
    timeline range or a start time plus duration; clipped to where the clip is seen. Returns (F0, F1, at, notes)."""
    first, end = clip_span(place)
    notes = []
    if source_range is not None and timeline_range is not None:
        raise ValueError('give source_range or timeline_range, not both')
    if timeline_range is not None:
        a, b = [float(v) for v in timeline_range]
        F0, F1 = int(round(a * fps)), int(round(b * fps))
    elif source_range is not None:
        a, b = [float(v) for v in source_range]
        F0, F1 = timeline_frame(place, a, fps), timeline_frame(place, b, fps)
    else:
        F0 = timeline_frame(place, float(at), fps) if at is not None else place['start']
        F1 = F0 + max(1, int(round(float(duration or 3.0) * fps)))
    if F1 <= F0:
        raise ValueError('the range ends before it starts')
    s_first, s_end = src_time(place, first, fps), src_time(place, end, fps)
    if F1 <= first or F0 >= end:
        raise Unsupported(f"the range is not where {place['id']} is seen: the clip shows source "
                          f'{s_first:.3f}-{s_end:.3f} s at timeline {first / fps:.3f}-{end / fps:.3f} s '
                          '(trimmed away or elsewhere on the timeline)')
    if F0 < first or F1 > end:
        notes.append(f'range clipped to where {place["id"]} is seen: source '
                     f'{src_time(place, max(F0, first), fps):.3f}-{src_time(place, min(F1, end), fps):.3f} s')
        F0, F1 = max(F0, first), min(F1, end)
    half = 0.5 / fps + 1e-6                   # times are on the project's frame grid: allow half a frame of rounding
    if at is None:
        at = src_time(place, F0, fps)
    elif not (src_time(place, F0, fps) - half <= float(at) <= src_time(place, F1, fps) + half):
        raise ValueError(f'at ({at} s) is outside the annotated source range '
                         f'{src_time(place, F0, fps):.3f}-{src_time(place, F1, fps):.3f} s')
    if F0 < place['start'] or F1 > place['start'] + place['frames']:
        notes.append('part of the range is inside a transition (the picture is mixed with the next/previous clip)')
    return F0, F1, float(at), notes
