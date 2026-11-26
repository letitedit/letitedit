"""A join measured, its verdict, and the sound across it.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import math
import numpy as np
from letitedit.timing.cut_inspect_base import (  # noqa: E402
    _angle_diff, _circ_mean, _cv2, _dir_word, _face_recognizer, _r, _settings, thresholds
)
from letitedit.timing.cut_inspect_frames import (  # noqa: E402
    _attention, _median_point, _phase_in, _phase_out, _static_overlay
)


# ------------------------------------------------------------------ the join

def _size_class(face_h):
    if face_h is None:
        return 'unknown'
    if face_h >= 0.45:
        return 'extreme closeup'
    if face_h >= 0.25:
        return 'closeup'
    if face_h >= 0.15:
        return 'medium closeup'
    if face_h >= 0.07:
        return 'medium'
    return 'wide'


_SIZE_ORDER = ['wide', 'medium', 'medium closeup', 'closeup', 'extreme closeup']


def _yuv_hist(bgr):
    cv2 = _cv2()
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV)
    hs = []
    for c, bins in ((0, 32), (1, 16), (2, 16)):
        hh = np.bincount((yuv[..., c] >> (8 - int(math.log2(bins)))).ravel(), minlength=bins).astype(np.float32)
        hs.append(hh / max(1.0, hh.sum()))
    return hs


def _textured_cells_changed(ga, gb, M, grid=6):
    """Share of the grid cells textured in both frames whose pattern changed (NCC < 0.5 after the camera estimate M),
    or None when fewer than 3 cells are textured. Flat cells (blurred side panels, sky, walls) are left out: they
    match between any two pictures of similar colour."""
    cv2 = _cv2()
    H, W = gb.shape
    wa = ga if M is None else cv2.warpAffine(ga, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    ch, cw = H // grid, W // grid
    tex = changed = 0
    for j in range(grid):
        for i in range(grid):
            a = wa[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw].astype(np.float32)
            b = gb[j * ch:(j + 1) * ch, i * cw:(i + 1) * cw].astype(np.float32)
            if a.std() < 8 or b.std() < 8:
                continue
            tex += 1
            changed += int(_ncc(a, b) < 0.5)
    return None if tex < 3 else changed / float(tex)


def _ncc(a, b):
    a = a.astype(np.float32) - a.mean()
    b = b.astype(np.float32) - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 0.0


def _join_rhythm(act, side_a, side_b, sp_a, sp_b, thr, win):
    # ---- rhythm / action
    def mean_last(xs, k):
        v = [x for x in xs[-k:] if x is not None]
        return float(np.mean(v)) if v else None

    def mean_first(xs, k):
        v = [x for x in xs[:k] if x is not None]
        return float(np.mean(v)) if v else None
    a_end = mean_last(sp_a, 3)
    b_start = mean_first(sp_b, 3)
    pre = mean_last(sp_a, win)
    post = mean_first(sp_b, win)
    ph_a = _phase_out(sp_a, act)
    ph_b = _phase_in(sp_b, act)
    on_action = a_end is not None and b_start is not None and a_end >= act and b_start >= act
    split = None
    if on_action and 'motion_frames_before_cut' in ph_a and 'motion_frames_after_cut' in ph_b:
        fa, fb = ph_a['motion_frames_before_cut'], ph_b['motion_frames_after_cut']
        split = fa / float(fa + fb)
    wide = float(thr['cuts.frame_wide_share'])

    def spread(motions, speed):
        sh = [m['share'] for m in motions if m]
        if not sh or speed is None or speed < act:
            return 'none', (_r(float(np.median(sh))) if sh else None)
        s = float(np.median(sh))
        return ('frame-wide (camera parallax or a frame-filling subject)' if s >= wide else 'local'), _r(s)
    a_kind, a_share = spread(side_a['motion'][-3:], a_end)
    b_kind, b_share = spread(side_b['motion'][:3], b_start)
    sharp = side_a.get('sharp') or []
    blur_ratio = None
    if len(sharp) >= 4:
        ref = max(sharp[-win * 2:]) if sharp[-win * 2:] else 0.0
        if ref > 1e-6:
            blur_ratio = float(np.mean(sharp[-2:])) / ref
    rhythm = {'a_end_speed': _r(a_end), 'b_start_speed': _r(b_start), 'pre_motion': _r(pre), 'post_motion': _r(post),
              'a_energy_end': _r(mean_last([m['energy'] if m else None for m in side_a['motion']], 3)),
              'b_energy_start': _r(mean_first([m['energy'] if m else None for m in side_b['motion']], 3)),
              'a_motion': a_kind, 'b_motion': b_kind, 'a_moving_share': a_share, 'b_moving_share': b_share,
              'a_blur_ratio': _r(blur_ratio),
              'a_phase': ph_a, 'b_phase': ph_b, 'cut_on_action': bool(on_action),
              'motion_across': _r(min(a_end, b_start)) if a_end is not None and b_start is not None else None,
              'action_share_before_cut': _r(split), 'unit': 'diag/s', 'window_frames': win,
              'threshold': {'cuts.action_speed': act, 'cuts.frame_wide_share': wide}}
    return rhythm, wide


def _join_screen_direction(act, att_a_n, att_b_n, fps, na, nb, pa, pb, side_a, side_b, thr, wide, win):
    # ---- screen direction
    cmin = float(thr['cuts.direction_min_coherence'])

    def side_dir(motions):
        """Direction of LOCAL motion (a subject); frame-wide motion is the camera's (see camera_a/b)."""
        angs, wts = [], []
        for m in motions:
            if m and m['dir'] is not None and m['coh'] >= cmin and m['speed'] >= act and m['share'] < wide:
                angs.append(m['dir'])
                wts.append(m['coh'] * m['speed'])
        if len(angs) < 2:
            return None, 0.0, len(angs)
        d, r = _circ_mean(angs, wts)
        return d, r, len(angs)
    da, ra, ka = side_dir(side_a['motion'][-win:])
    db, rb, kb = side_dir(side_b['motion'][:win])
    ang = _angle_diff(da, db)

    def horiz(d):
        if d is None:
            return 0
        c = math.cos(math.radians(d))
        return 0 if abs(c) < 0.5 else (1 if c > 0 else -1)
    ha, hb = horiz(da), horiz(db)
    horizontal = None if not ha or not hb else ('same' if ha == hb else 'reversed')

    def cam(motions):
        ms = [m['cam'] for m in motions if m]
        if not ms:
            return {'label': 'unknown'}
        dx = float(np.median([c['dx'] for c in ms]))
        dy = float(np.median([c['dy'] for c in ms]))
        z = float(np.median([c['zoom'] for c in ms]))
        zr = (z - 1.0) * fps
        sp = math.hypot(dx, dy)
        ps = float(thr['cuts.pan_speed'])
        if sp >= ps and abs(dx) >= abs(dy):
            label = 'pan right' if dx < 0 else 'pan left'      # the picture slides the other way
        elif sp >= ps:
            label = 'tilt up' if dy < 0 else 'tilt down'
        elif abs(zr) >= 0.08:
            label = 'zoom in' if zr > 0 else 'zoom out'
        else:
            label = 'static'
        return {'label': label, 'content_dx': _r(dx), 'content_dy': _r(dy), 'zoom_per_s': _r(zr),
                'inliers': _r(float(np.median([c['inliers'] for c in ms])))}
    cam_a, cam_b = cam(side_a['motion'][-win:]), cam(side_b['motion'][:win])
    pan = None
    if cam_a['label'].startswith('pan') and cam_b['label'].startswith('pan'):
        pan = 'same' if cam_a['label'] == cam_b['label'] else 'reversed'

    def subject(side, idxs):
        xs, facing = [], []
        for i in idxs:
            fs = side['faces'][i]
            if fs:
                xs.append((fs[0]['box'][0] + fs[0]['box'][2]) / 2)
                facing.append(fs[0]['facing'])
        if xs:
            return float(np.median(xs)), max(set(facing), key=facing.count), 'face'
        return None, None, None
    sa_x, fa_, basis_a = subject(side_a, range(max(0, na - att_a_n), na))
    sb_x, fb_, basis_b = subject(side_b, range(0, min(nb, att_b_n)))
    if sa_x is None and pa:
        sa_x, basis_a = pa['x'], pa['basis']
    if sb_x is None and pb:
        sb_x, basis_b = pb['x'], pb['basis']

    def side_word(x):
        return None if x is None else 'left' if x < 0.42 else 'right' if x > 0.58 else 'centre'
    direction = {'a_dir': _r(da, 1), 'a_dir_word': _dir_word(da), 'a_coherence': _r(ra), 'a_frames': ka,
                 'b_dir': _r(db, 1), 'b_dir_word': _dir_word(db), 'b_coherence': _r(rb), 'b_frames': kb,
                 'angle_change': _r(ang, 1), 'horizontal': horizontal, 'camera_a': cam_a, 'camera_b': cam_b,
                 'pan': pan, 'subject_a_x': _r(sa_x), 'subject_b_x': _r(sb_x), 'subject_a_side': side_word(sa_x),
                 'subject_b_side': side_word(sb_x), 'subject_basis': [basis_a, basis_b],
                 'same_side': None if sa_x is None or sb_x is None else side_word(sa_x) == side_word(sb_x),
                 'facing_a': fa_, 'facing_b': fb_, 'unit': 'degrees (0 = screen right, 90 = up)',
                 'threshold': {'cuts.direction_min_coherence': cmin,
                               'cuts.direction_reversed_deg': thr['cuts.direction_reversed_deg'],
                               'cuts.direction_same_deg': thr['cuts.direction_same_deg'],
                               'cuts.pan_speed': thr['cuts.pan_speed']}}
    return direction


def _join_space(H, W, att_a_n, att_b_n, cv2, ga, gb, na, nb, shots, side_a, side_b, thr):
    # ---- 3D space
    pr = shots.measure_pair(ga, gb, shots.FEATURE_DEFAULTS)
    _, _, zoom, roll = shots._mparams(pr.M, W)
    tg = (max(8, W // 8), max(8, H // 8))
    ta = cv2.GaussianBlur(cv2.resize(ga, tg, interpolation=cv2.INTER_AREA).astype(np.float32), (0, 0), 1.0)
    tb = cv2.GaussianBlur(cv2.resize(gb, tg, interpolation=cv2.INTER_AREA).astype(np.float32), (0, 0), 1.0)
    layout = _ncc(ta, tb)
    hist_d = float(np.mean([0.5 * np.abs(x - y).sum() for x, y in zip(_yuv_hist(side_a['bgr'][-1]),
                                                                       _yuv_hist(side_b['bgr'][0]))]))

    def face_h(side, idxs):
        hs = [side['faces'][i][0]['h'] for i in idxs if side['faces'][i]]
        return float(np.median(hs)) if len(hs) * 2 >= len(list(idxs)) else None
    fha = face_h(side_a, range(max(0, na - att_a_n), na))
    fhb = face_h(side_b, range(0, min(nb, att_b_n)))
    ratio = fhb / fha if fha and fhb else None
    size_a, size_b = _size_class(fha), _size_class(fhb)
    steps = (_SIZE_ORDER.index(size_b) - _SIZE_ORDER.index(size_a)) if fha and fhb else None
    same_person = cos = None
    rec = _face_recognizer()
    if rec and side_a['faces'][-1] and side_b['faces'][0]:
        try:
            fa_feat = rec.feature(rec.alignCrop(side_a['bgr'][-1], side_a['faces'][-1][0]['row']))
            fb_feat = rec.feature(rec.alignCrop(side_b['bgr'][0], side_b['faces'][0][0]['row']))
            cos = float(rec.match(fa_feat, fb_feat, cv2.FaceRecognizerSF_FR_COSINE))
            same_person = cos >= float(thr['cuts.same_person_cos'])
        except Exception:  # noqa: BLE001
            same_person = cos = None
    tex_changed = _textured_cells_changed(ga, gb, pr.M)
    cells_ok = pr.cells <= float(thr['cuts.jump_max_cells']) and \
        (tex_changed is None or tex_changed <= float(thr['cuts.jump_max_cells']))
    same_frame = ((pr.sim >= float(thr['cuts.jump_framing_sim']) and pr.trusted) or
                  layout >= float(thr['cuts.jump_layout_sim'])) and cells_ok
    srat = float(thr['cuts.same_size_ratio'])
    same_size = ratio is None or (1.0 / srat <= ratio <= srat)
    punch = same_frame and (zoom >= float(thr['cuts.punch_zoom']) or zoom <= 1.0 / float(thr['cuts.punch_zoom'])
                            or (ratio is not None and not same_size and bool(same_person)))
    jump_cut = same_frame and same_size and not punch
    space = {'framing_sim': _r(pr.sim), 'framing_sim_raw': _r(pr.sim_raw), 'framing_trusted': bool(pr.trusted),
             'cells_changed': _r(pr.cells), 'textured_cells_changed': _r(tex_changed), 'layout_sim': _r(layout),
             'reframe_zoom': _r(zoom),
             'hist_change': _r(hist_d), 'face_h_a': _r(fha), 'face_h_b': _r(fhb), 'size_a': size_a, 'size_b': size_b,
             'size_ratio': _r(ratio), 'size_steps': steps, 'same_person': same_person, 'face_match_cos': _r(cos),
             'jump_cut': bool(jump_cut), 'punch_in': bool(punch),
             'scene_change': bool(hist_d >= float(thr['cuts.scene_hist']) and pr.sim < 0.3 and layout < 0.4),
             'threshold': {'cuts.jump_framing_sim': thr['cuts.jump_framing_sim'],
                           'cuts.jump_layout_sim': thr['cuts.jump_layout_sim'],
                           'cuts.jump_max_cells': thr['cuts.jump_max_cells'],
                           'cuts.same_size_ratio': srat, 'cuts.punch_zoom': thr['cuts.punch_zoom']}}
    return space


def _join_extra(cv2, shot_frames, side_a, side_b, thr):
    # ---- extra
    la, lb = float(side_a['small'][-1].mean()), float(side_b['small'][0].mean())
    lab_a = cv2.cvtColor(side_a['bgr'][-1].astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(0)
    lab_b = cv2.cvtColor(side_b['bgr'][0].astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB).reshape(-1, 3).mean(0)
    fs = float(thr['cuts.blank_flat_share'])

    def blank(g):            # digitally flat (black, white, one colour); a caption on it does not count
        med = float(np.median(g))
        return bool(float((np.abs(g.astype(np.int16) - med) <= 2).mean()) >= fs)
    blank_a = [blank(g) for g in side_a['small']]
    blank_b = [blank(g) for g in side_b['small']]
    # a short run of blank frames ending A or starting B after/before real picture on that side (a glitch); a side
    # that is flat all along (a title card, a deliberate black) is not counted
    nba = 0
    for x in reversed(blank_a):
        if not x:
            break
        nba += 1
    nbb = 0
    for x in blank_b:
        if not x:
            break
        nbb += 1
    if nba == len(blank_a) or nba > 3:
        nba = 0
    if nbb == len(blank_b) or nbb > 3:
        nbb = 0
    extra = {'luma_a': _r(la, 1), 'luma_b': _r(lb, 1), 'luma_jump': _r(lb - la, 1),
             'colour_shift_de': _r(float(np.linalg.norm(lab_b - lab_a)), 1),
             'blank_a': bool(nba), 'blank_b': bool(nbb), 'blank_frames_at_join': nba + nbb,
             'flat_side': [bool(all(blank_a)), bool(all(blank_b))],
             'shot_a_frames': shot_frames[0] if shot_frames else None,
             'shot_b_frames': shot_frames[1] if shot_frames else None,
             'unit': 'luma 0-255; colour shift CIE76 dE of the mean colour',
             'threshold': {k: thr[k] for k in ('cuts.luma_jump_noticeable', 'cuts.luma_jump_jarring',
                                               'cuts.flash_frames', 'cuts.short_shot_frames',
                                               'cuts.blank_flat_share')}}
    return extra


def measure_join(side_a, side_b, fps, settings=None, thr=None, shot_frames=None, kind='cut'):
    """The measures of one join. side_a: analyse_side() of the frames before the cut (chronological, its last frame
    is the last one shown before the cut); side_b: of the frames from the cut on. shot_frames: (A's length, B's
    length) in frames when known. Returns {rhythm, eye_trace, screen_direction, space, extra, per_frame}."""
    cv2 = _cv2()
    import letitedit.footage.shots as shots
    st = _settings(settings)
    thr = thr or thresholds()
    na, nb = len(side_a['bgr']), len(side_b['bgr'])
    if not na or not nb:
        raise ValueError('a join needs frames on both sides')
    h, w = side_a['bgr'][0].shape[:2]
    H, W = side_a['small'][0].shape
    win = max(2, int(round(float(st['motion_window_s']) * fps)))
    att_a_n = max(1, int(st['att_a_frames']))
    att_b_n = max(1, int(round(float(st['att_b_s']) * fps)))
    act = float(thr['cuts.action_speed'])
    sp_a = [m['speed'] if m else None for m in side_a['motion']]
    sp_b = [m['speed'] if m else None for m in side_b['motion']]
    ga, gb = side_a['small'][-1], side_b['small'][0]
    mask, mask_share = _static_overlay(ga, gb, thr)

    rhythm, wide = _join_rhythm(act, side_a, side_b, sp_a, sp_b, thr, win)

    # ---- attention
    att_a = [_attention(side_a['sal'][i], side_a['motion'][i], side_a['faces'][i], mask, thr, w, h)
             for i in range(max(0, na - max(att_a_n, st['before'])), na)]
    att_b = [_attention(side_b['sal'][i], side_b['motion'][i], side_b['faces'][i], mask, thr, w, h)
             for i in range(0, min(nb, max(att_b_n, st['after'])))]
    pa = _median_point(att_a[-att_a_n:])
    pb = _median_point(att_b[:att_b_n])
    pb0 = att_b[0] if att_b else None
    diag = math.hypot(w, h)

    def dist(p, q):
        if p is None or q is None:
            return None
        return math.hypot((q['x'] - p['x']) * w, (q['y'] - p['y']) * h) / diag
    eye = {'a': {k: _r(v) if k != 'basis' else v for k, v in (pa or {}).items()},
           'b': {k: _r(v) if k != 'basis' else v for k, v in (pb or {}).items()},
           'jump': _r(dist(pa, pb)), 'jump_first_frame': _r(dist(pa, pb0)),
           'dx': _r(pb['x'] - pa['x']) if pa and pb else None, 'dy': _r(pb['y'] - pa['y']) if pa and pb else None,
           'unit': 'frame diagonals (dx in widths, dy in heights)', 'overlay_masked_share': _r(mask_share),
           'threshold': {'cuts.eye_jump_noticeable': thr['cuts.eye_jump_noticeable'],
                         'cuts.eye_jump_jarring': thr['cuts.eye_jump_jarring']}}

    direction = _join_screen_direction(act, att_a_n, att_b_n, fps, na, nb, pa, pb, side_a, side_b, thr, wide,
        win)

    space = _join_space(H, W, att_a_n, att_b_n, cv2, ga, gb, na, nb, shots, side_a, side_b, thr)

    extra = _join_extra(cv2, shot_frames, side_a, side_b, thr)
    per_frame = {'a_speed': [_r(x) for x in sp_a], 'b_speed': [_r(x) for x in sp_b],
                 'a_attention': [[_r(p['x']), _r(p['y']), p['basis']] for p in att_a],
                 'b_attention': [[_r(p['x']), _r(p['y']), p['basis']] for p in att_b]}
    return {'rhythm': rhythm, 'eye_trace': eye, 'screen_direction': direction, 'space': space, 'extra': extra,
            'per_frame': per_frame, '_draw': {'att_a': att_a, 'att_b': att_b, 'pa': pa, 'pb': pb, 'mask': mask}}


# ------------------------------------------------------------------ the verdict

# B3's joins flags (joins.py: a measure over its 'joins.*' threshold) and how a flag counts in this verdict: an
# audible glitch (a click, a hole of digital silence, a word cut in half) is jarring, any other flag noticeable.
SOUND_FLAG_SEVERITY = {'click': 2, 'silence_gap': 2, 'word_cut': 2, 'level_jump': 1, 'speech_level_jump': 1,
                       'room_tone_jump': 1, 'spectral_jump': 1, 'room_spectral_jump': 1, 'pitch_jump': 1,
                       'tight_after_word': 1, 'tight_before_word': 1}
SOUND_FLAG_WORDS = {'click': 'a click at the join', 'silence_gap': 'a hole of digital silence at the join',
                    'word_cut': 'a word cut by the join', 'level_jump': 'the loudness jumps',
                    'speech_level_jump': 'the speech level jumps', 'room_tone_jump': 'the room tone (noise floor) jumps',
                    'spectral_jump': 'the voice colour jumps', 'room_spectral_jump': 'the room tone colour jumps',
                    'pitch_jump': 'the speaking pitch jumps', 'tight_after_word': 'the cut clips the last word',
                    'tight_before_word': 'the cut clips the next word'}


def _sound_findings(sound, thr):
    """Findings from B3's joins entry for this cut: its flags (each with B3's own value and threshold), else a
    verdict word it may give."""
    out = []
    if not sound or not isinstance(sound, dict) or sound.get('status') == 'unchecked':
        return out
    flags = sound.get('flags')
    if isinstance(flags, list):
        for fl in flags:
            name = fl if isinstance(fl, str) else str((fl or {}).get('check') or fl)
            meas = sound.get(name) if isinstance(sound.get(name), dict) else {}
            val, unit = meas.get('value'), meas.get('unit')
            sev = SOUND_FLAG_SEVERITY.get(name, 1)
            words = SOUND_FLAG_WORDS.get(name, name.replace('_', ' '))
            txt = f'sound: {words}' + (f' ({val} {unit or ""}'.rstrip() + f' >= {meas.get("threshold")})'
                                       if val is not None and meas.get('threshold') is not None else '')
            if name == 'word_cut' and isinstance(sound.get('words'), dict) and sound['words'].get('word_cut'):
                txt += f': "{sound["words"]["word_cut"]}"'
            out.append({'part': 'sound', 'measure': f'joins.{name}', 'value': val, 'unit': unit, 'severity': sev,
                        'threshold': {'joins view': meas.get('threshold')}, 'text': txt})
        return out
    sev_words = {'smooth': 0, 'ok': 0, 'clean': 0, 'fine': 0, 'noticeable': 1, 'minor': 1, 'warning': 1,
                 'jarring': 2, 'major': 2, 'bad': 2, 'critical': 2, 'problem': 1}
    v = sound.get('verdict') or sound.get('severity') or sound.get('rating')
    if isinstance(v, str) and v.lower() in sev_words:
        sev = sev_words[v.lower()]
        why = sound.get('reasons') or sound.get('why') or sound.get('problems') or []
        if isinstance(why, (list, tuple)):
            why = '; '.join(str(x if not isinstance(x, dict) else x.get('text') or x.get('why') or x) for x in why[:3])
        if sev:
            out.append({'part': 'sound', 'measure': 'joins', 'value': v, 'unit': None, 'severity': sev,
                        'threshold': 'joins view', 'text': f'sound across the join: {v}' + (f' ({why})' if why else '')})
        return out
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        sev = int(max(0, min(2, v)))
        if sev:
            out.append({'part': 'sound', 'measure': 'joins', 'value': v, 'unit': None, 'severity': sev,
                        'threshold': 'joins view', 'text': f'sound across the join: severity {v}'})
        return out
    probs = sound.get('problems') or sound.get('flags') or sound.get('issues')
    if probs:
        txt = '; '.join(str(p if not isinstance(p, dict) else p.get('text') or p.get('why') or p.get('kind'))
                        for p in probs[:3])
        out.append({'part': 'sound', 'measure': 'joins', 'value': len(probs), 'unit': 'problems', 'severity': 1,
                    'threshold': 'joins view', 'text': f'sound across the join: {txt}'})
        return out
    lj = sound.get('level_jump_db')
    if isinstance(lj, dict):
        lj = lj.get('value')
    if isinstance(lj, (int, float)) and abs(lj) >= float(thr['cuts.sound_level_jump_db']):
        out.append({'part': 'sound', 'measure': 'level_jump_db', 'value': _r(lj, 1), 'unit': 'dB', 'severity': 1,
                    'threshold': {'cuts.sound_level_jump_db': thr['cuts.sound_level_jump_db']},
                    'text': f'sound level jumps {lj:+.1f} dB across the join (>= {thr["cuts.sound_level_jump_db"]:g})'})
    if sound.get('click') is True or (isinstance(sound.get('click'), dict) and sound['click'].get('found')):
        out.append({'part': 'sound', 'measure': 'click', 'value': True, 'unit': None, 'severity': 1,
                    'threshold': 'joins view', 'text': 'a click at the join (joins)'})
    return out


def verdict(m, kind='cut', sound=None, thr=None, gap_frames=None):
    """smooth / noticeable / jarring from the measures of measure_join(), with every finding behind it.
    Returns {'verdict', 'severity' 0-2, 'findings': [...], 'masks': [...], 'reasons': [plain lines]}."""
    thr = thr or thresholds()
    F, masks = [], []
    gradual = kind in ('dissolve', 'fade', 'wipe')
    rh, ey, sd, sp, ex = m['rhythm'], m['eye_trace'], m['screen_direction'], m['space'], m['extra']

    def add(part, measure, value, unit, sev, text, threshold):
        F.append({'part': part, 'measure': measure, 'value': value, 'unit': unit, 'severity': int(sev),
                  'threshold': threshold, 'text': text})
    # eye-trace
    j = ey.get('jump')
    if j is not None and not gradual:
        tn, tj = float(thr['cuts.eye_jump_noticeable']), float(thr['cuts.eye_jump_jarring'])
        if j >= tj:
            add('eye_trace', 'jump', j, 'diag', 2, f'eye-trace jumps {j:.2f} of the frame diagonal (>= {tj:g}): '
                f'{ey["a"].get("basis")} -> {ey["b"].get("basis")}', {'cuts.eye_jump_jarring': tj})
        elif j >= tn:
            add('eye_trace', 'jump', j, 'diag', 1, f'eye-trace jumps {j:.2f} of the frame diagonal (>= {tn:g}): '
                f'{ey["a"].get("basis")} -> {ey["b"].get("basis")}', {'cuts.eye_jump_noticeable': tn})
        else:
            add('eye_trace', 'jump', j, 'diag', 0, f'eye-trace continues: jump {j:.2f} (< {tn:g})',
                {'cuts.eye_jump_noticeable': tn})
    # screen direction
    ang = sd.get('angle_change')
    if ang is not None and not gradual:
        tr = float(thr['cuts.direction_reversed_deg'])
        if ang >= tr:
            add('screen_direction', 'angle_change', ang, 'deg', 1,
                f'screen direction reverses: {sd["a_dir_word"]} -> {sd["b_dir_word"]} ({ang:.0f} deg >= {tr:g})',
                {'cuts.direction_reversed_deg': tr})
        elif ang <= float(thr['cuts.direction_same_deg']):
            add('screen_direction', 'angle_change', ang, 'deg', 0,
                f'motion keeps its direction ({sd["a_dir_word"]}, {ang:.0f} deg)',
                {'cuts.direction_same_deg': thr['cuts.direction_same_deg']})
    if sd.get('pan') == 'reversed' and not gradual:
        add('screen_direction', 'pan', 'reversed', None, 1,
            f'camera pans reverse: {sd["camera_a"]["label"]} -> {sd["camera_b"]["label"]}',
            {'cuts.pan_speed': thr['cuts.pan_speed']})
    # 3D space
    if sp.get('punch_in'):
        add('space', 'reframe_zoom', sp.get('reframe_zoom'), 'x', 1,
            f'punch-in: the same picture reframed ({sp.get("reframe_zoom")}x, framing similarity '
            f'{sp.get("framing_sim")}): visible by design', {'cuts.punch_zoom': thr['cuts.punch_zoom']})
    elif sp.get('jump_cut') and kind != 'gap':
        add('space', 'framing_sim', sp.get('framing_sim'), 'NCC', 1,
            f'jump cut: same framing (similarity {sp.get("framing_sim")}, layout {sp.get("layout_sim")}) and size'
            + (f' (ratio {sp.get("size_ratio")})' if sp.get('size_ratio') else ''),
            {'cuts.jump_framing_sim': thr['cuts.jump_framing_sim'], 'cuts.jump_layout_sim': thr['cuts.jump_layout_sim'],
             'cuts.same_size_ratio': thr['cuts.same_size_ratio']})
    # extras
    lj = ex.get('luma_jump')
    if lj is not None and not gradual:
        tn, tj = float(thr['cuts.luma_jump_noticeable']), float(thr['cuts.luma_jump_jarring'])
        if abs(lj) >= tj:
            add('extra', 'luma_jump', lj, 'luma 0-255', 2, f'brightness jumps {lj:+.0f} (>= {tj:g}): a flash',
                {'cuts.luma_jump_jarring': tj})
        elif abs(lj) >= tn:
            add('extra', 'luma_jump', lj, 'luma 0-255', 1, f'brightness jumps {lj:+.0f} (>= {tn:g})',
                {'cuts.luma_jump_noticeable': tn})
    nb = ex.get('blank_frames_at_join') or (1 if (ex.get('blank_a') or ex.get('blank_b')) else 0)
    if nb and kind not in ('fade', 'gap'):
        add('extra', 'blank', nb, 'frames', 2, f'{nb} blank (flat) frame(s) right at the join: a flash of black',
            {'cuts.blank_flat_share': thr['cuts.blank_flat_share']})
    if sp.get('scene_change'):
        add('space', 'scene_change', sp.get('hist_change'), '0-1', 0,
            f'a new place or subject (colour change {sp.get("hist_change")}, framing unrelated)',
            {'cuts.scene_hist': thr['cuts.scene_hist']})
    if kind == 'gap' and gap_frames is not None:
        tg = int(thr['cuts.gap_jarring_frames'])
        add('extra', 'gap_frames', gap_frames, 'frames', 2 if gap_frames < tg else 1,
            f'{gap_frames} empty (black) frame(s) between the shots' + (' (a glitch)' if gap_frames < tg else ''),
            {'cuts.gap_jarring_frames': tg})
    for side, n in (('A', ex.get('shot_a_frames')), ('B', ex.get('shot_b_frames'))):
        if n is None:
            continue
        if n <= int(thr['cuts.flash_frames']):
            add('extra', f'shot_{side.lower()}_frames', n, 'frames', 2, f'shot {side} lasts {n} frame(s): a flash frame',
                {'cuts.flash_frames': thr['cuts.flash_frames']})
        elif n <= int(thr['cuts.short_shot_frames']):
            add('extra', f'shot_{side.lower()}_frames', n, 'frames', 1, f'shot {side} lasts only {n} frames',
                {'cuts.short_shot_frames': thr['cuts.short_shot_frames']})
    # rhythm (informational findings: what the cut does with the action)
    act = float(thr['cuts.action_speed'])
    if rh.get('cut_on_action'):
        kinds = sorted({str(rh.get('a_motion', '')).split(' (')[0], str(rh.get('b_motion', '')).split(' (')[0]})
        add('rhythm', 'motion_across', rh.get('motion_across'), 'diag/s', 0,
            f'cut on action: motion on both sides (A {rh["a_end_speed"]:.2f}, B {rh["b_start_speed"]:.2f} diag/s '
            f'>= {act:g}; A {rh["a_phase"]["phase"]}; {"/".join(k for k in kinds if k)})',
            {'cuts.action_speed': act, 'cuts.frame_wide_share': thr['cuts.frame_wide_share']})
    elif rh.get('a_end_speed') is not None and rh.get('b_start_speed') is not None:
        add('rhythm', 'motion_across', rh.get('motion_across'), 'diag/s', 0,
            f'no motion across the cut (A {rh["a_phase"]["phase"]}, B {rh["b_phase"]["phase"]})',
            {'cuts.action_speed': act})
    # sound
    for f in _sound_findings(sound, thr):
        F.append(f)
    # masks: a subject's motion running across the cut draws the eye and hides the cut (edit blindness). Only local
    # motion counts: frame-wide motion (camera shake, parallax) does not lead the eye anywhere.
    pm = float(thr['cuts.post_motion_masks'])
    masked = False
    local_a = rh.get('a_motion') == 'local'
    local_b = rh.get('b_motion') == 'local'
    if rh.get('cut_on_action') and local_a and local_b and \
            (sd.get('angle_change') is None or sd['angle_change'] < float(thr['cuts.direction_reversed_deg'])):
        masks.append(f'a subject\'s motion continues across the cut (A {rh["a_end_speed"]:.2f}, B '
                     f'{rh["b_start_speed"]:.2f} diag/s, local): eye-trace and direction findings one step lower')
        masked = True
    elif local_b and rh.get('post_motion') is not None and rh['post_motion'] >= pm:
        masks.append(f'local motion right after the cut ({rh["post_motion"]:.2f} diag/s >= {pm:g}, Smith & '
                     'Martin-Portugues 2017): eye-trace findings one step lower')
        masked = 'eye'
    elif rh.get('a_blur_ratio') is not None and rh['a_blur_ratio'] <= float(thr['cuts.blur_mask_ratio']) and \
            (rh.get('a_end_speed') or 0) >= act:
        masks.append(f"A ends in motion blur (sharpness {rh['a_blur_ratio']:.2f} of its sharpest frame <= "
                     f"{thr['cuts.blur_mask_ratio']:g}, a whip): eye-trace findings one step lower")
        masked = 'eye'
    for f in F:
        f['severity_before_mask'] = f['severity']
        if masked and f['severity'] > 0 and (f['part'] == 'eye_trace' or (masked is True and
                                                                         f['part'] == 'screen_direction')):
            f['severity'] -= 1
            f['masked'] = True
    sev = max([f['severity'] for f in F] or [0])
    many = int(thr['cuts.many_noticeable'])
    n1 = sum(1 for f in F if f['severity'] == 1)
    if sev < 2 and n1 >= many:
        sev = 2
        F.append({'part': 'summary', 'measure': 'noticeable_findings', 'value': n1, 'unit': 'findings', 'severity': 2,
                  'threshold': {'cuts.many_noticeable': many}, 'text': f'{n1} noticeable findings together'})
    word = ['smooth', 'noticeable', 'jarring'][sev]
    order = sorted(F, key=lambda f: (-f['severity'], ['eye_trace', 'screen_direction', 'space', 'extra', 'sound',
                                                       'rhythm', 'summary'].index(f['part'])))
    reasons = [f['text'] + (' [masked by motion]' if f.get('masked') else '') for f in order
               if f['severity'] > 0 or f.get('masked')]
    if not reasons:
        reasons = [f['text'] for f in order][:2]
    if gradual:
        reasons.append(f'{kind}: a gradual transition (eye-trace and direction not scored)')
    return {'verdict': word, 'severity': sev, 'findings': order, 'masks': masks, 'reasons': reasons}


# ------------------------------------------------------------------ sound across the join (B3's joins view)

def _joins(source, sel, fps, options, warnings):
    """B3's sound measures for the selected cuts only (joins.measure), or the registered 'joins' view when the module
    API is not there. Returns (entries, why-not)."""
    if options.get('sound') is False:
        return None, 'not asked (options.sound = false)'
    if not sel:
        return [], None
    want = []
    for c in sel:
        d = {'f': int(c['f']), 't': c['f'] / fps, 'kind': c.get('kind', 'cut')}
        if c.get('a_end') is not None and c.get('b_start') is not None and c['b_start'] > c['a_end']:
            d['span'] = [c['a_end'] / fps, c['b_start'] / fps]
        for k in ('from_item', 'to_item', 'from_clip', 'to_clip'):
            if c.get(k):
                d[k] = c[k]
        want.append(d)
    try:
        import letitedit.timing.joins as joins
        has_measure = hasattr(joins, 'measure')
    except Exception:  # noqa: BLE001 - B3's module is optional
        has_measure = False
    try:
        if has_measure:
            res = joins.measure(str(source), cuts=want, settings=options.get('settings'))
        else:
            import letitedit.timing.timing_views as timing_views
            fn = timing_views.get('joins')
            res = fn(source, None, None, None, [d['t'] for d in want], dict(options or {}, images=0), 'brief')
    except KeyError:
        return None, 'the joins view is not registered'
    except Exception as ex:  # noqa: BLE001
        warnings.append(f'sound across the joins not measured ({type(ex).__name__}: {str(ex)[:160]})')
        return None, f'joins failed ({type(ex).__name__})'
    if not isinstance(res, dict):
        return None, 'joins gave no result'
    for w in res.get('warnings') or []:
        warnings.append(f'joins: {w}')
    for key in ('joins', 'cuts', 'items', 'results'):
        if isinstance(res.get(key), list):
            return res[key], None
    return None, 'joins result has no per-cut list'


def _match_sound(entries, c, fps):
    if not entries:
        return None
    best, bd = None, None
    for e in entries:
        if not isinstance(e, dict):
            continue
        f = e.get('f', e.get('frame'))
        if f is None and e.get('t') is not None:
            f = float(e['t']) * fps
        if f is None:
            continue
        dd = abs(float(f) - c['f'])
        if dd <= 1.5 and (bd is None or dd < bd):
            best, bd = e, dd
    return best
