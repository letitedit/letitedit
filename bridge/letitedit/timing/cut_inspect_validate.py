"""The validation: real cuts against the same cuts moved.

Part of `cut_inspect` (letitedit/timing/cut_inspect.py), which imports every name here back,
so `cut_inspect.X` is the same object it always was.
"""
from __future__ import annotations
import os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from letitedit.timing.cut_inspect_base import (  # noqa: E402
    _cv2, _jsonable, _r, _settings, _sizes, decode_at_times, decode_frames, thresholds
)
from letitedit.timing.cut_inspect_frames import (  # noqa: E402
    _subset, analyse_side, snap_cut
)
from letitedit.timing.cut_inspect_join import (  # noqa: E402
    measure_join, verdict
)
from letitedit.timing.cut_inspect_cuts import (  # noqa: E402
    project_cuts
)


# ------------------------------------------------------------------ validation: real cuts vs the same cuts moved

FEATURES = {
    # name: (getter, a-priori expectation for a well-placed cut, unit)
    'eye_jump': (lambda m: m['eye_trace']['jump'], 'lower', 'diag'),
    'eye_jump_first': (lambda m: m['eye_trace']['jump_first_frame'], 'lower', 'diag'),
    'a_end_speed': (lambda m: m['rhythm']['a_end_speed'], 'higher', 'diag/s'),
    'b_start_speed': (lambda m: m['rhythm']['b_start_speed'], 'higher', 'diag/s'),
    'pre_motion': (lambda m: m['rhythm']['pre_motion'], 'higher', 'diag/s'),
    'post_motion': (lambda m: m['rhythm']['post_motion'], 'higher', 'diag/s'),
    'motion_across': (lambda m: m['rhythm']['motion_across'], 'higher', 'diag/s'),
    'angle_change': (lambda m: m['screen_direction']['angle_change'], 'lower', 'deg'),
    'framing_sim': (lambda m: m['space']['framing_sim'], 'none', 'NCC'),
    'layout_sim': (lambda m: m['space']['layout_sim'], 'none', 'NCC'),
    'luma_jump_abs': (lambda m: abs(m['extra']['luma_jump']) if m['extra']['luma_jump'] is not None else None,
                      'lower', 'luma'),
    'colour_shift': (lambda m: m['extra']['colour_shift_de'], 'lower', 'dE'),
}


def _features(m, sev=None):
    out = {}
    for k, (g, _, _) in FEATURES.items():
        try:
            v = g(m)
        except (KeyError, TypeError):
            v = None
        out[k] = None if v is None else float(v)
    if sev is not None:
        out['severity'] = float(sev)
    return out


def shift_test(video, cuts, shifts=(2, 4, 8), modes=('trim_out', 'trim_in', 'trim_both'), settings=None,
               workers=1, label=None, progress=None):
    """Pardo et al. 2021 ('Learning to Cut by Watching Movies') as a check on these measures: for each real cut of an
    edited video, the join is measured as edited and with the cut moved by frame indexing in the render itself:
    'trim_out' k = A ends k frames earlier (B unchanged), 'trim_in' k = B starts k frames later (A unchanged),
    'trim_both' = both. Every alternative is a cut the editor could have made from frames in the edit and did not.
    cuts: [{'f': first frame of the new shot, 'prev': previous cut frame or None, 'next': next cut frame or None}].
    Returns {'per_cut': [{f, real: features, variants: {mode_k: features}}], 'video', 'skipped': [...]}."""
    import letitedit.footage.shots as shots
    st = _settings(settings)
    thr = thresholds((settings or {}).get('thresholds'))
    info = shots.probe(video)
    fps = float(info['fps'])
    frames = int(info['frames'] or round(info['duration'] * fps))
    kmax = max(shifts)
    need = max(int(st['att_a_frames']), int(round(float(st['motion_window_s']) * fps)),
               int(round(float(st['att_b_s']) * fps))) + 1
    ctx = max(int(round(float(st['context_s']) * fps)), need)
    dsize, _ = _sizes(info['w'], info['h'], st['decode_px'], st['flow_px'])
    out, skipped = [], []

    def run(c):
        f = f_given = int(c['f'])
        prev = int(c['prev']) if c.get('prev') is not None else 0
        nxt = int(c['next']) if c.get('next') is not None else frames
        if f - max(prev, f - ctx - kmax) < need + kmax or min(nxt, f + ctx + kmax) - f < need + kmax:
            return None, {'f': f, 'why': f'shots too short for a {kmax}-frame shift (A {f - prev}, B {nxt - f} frames)'}
        fr = decode_frames(video, max(prev, f - ctx - kmax - 2), min(nxt + 2, f + ctx + kmax + 2), dsize, info)
        if c.get('snap', True):
            f = snap_cut(fr, f)
        a0 = max(prev, f - ctx - kmax)
        b1 = min(nxt, f + ctx + kmax)
        if f - a0 < need + kmax or b1 - f < need + kmax:
            return None, {'f': f, 'why': f'shots too short for a {kmax}-frame shift (A {f - prev}, B {nxt - f} frames)'}
        af = [i for i in range(a0, f) if i in fr]
        bf = [i for i in range(f, b1) if i in fr]
        if len(af) < need + kmax or len(bf) < need + kmax:
            return None, {'f': f, 'why': 'decode came up short'}
        A = analyse_side([fr[i] for i in af], fps, st, thr, frames=af)
        B = analyse_side([fr[i] for i in bf], fps, st, thr, frames=bf)
        nA, nB = len(af), len(bf)
        summary = {}

        def feat(ka, kb):
            # every variant sees the same context: ctx frames before its cut point and ctx after it
            sa = _subset(A, max(0, nA - ka - ctx), nA - ka)
            sb = _subset(B, kb, min(nB, kb + ctx))
            # shot lengths are left out: trimming shortens a shot, which is not about where the cut falls
            m = measure_join(sa, sb, fps, st, thr, shot_frames=None)
            v = verdict(m, 'cut', None, thr)
            if not ka and not kb:
                summary['_measures'] = _jsonable({k: v for k, v in m.items() if k not in ('_draw', 'per_frame')})
                rh, sd, sp = m['rhythm'], m['screen_direction'], m['space']
                summary.update(verdict=v['verdict'], reasons=v['reasons'][:3], a_phase=rh['a_phase'].get('phase'),
                               b_phase=rh['b_phase'].get('phase'), a_motion=rh['a_motion'], b_motion=rh['b_motion'],
                               cut_on_action=rh['cut_on_action'], action_share=rh['action_share_before_cut'],
                               eye_basis=[m['eye_trace']['a'].get('basis'), m['eye_trace']['b'].get('basis')],
                               horizontal=sd['horizontal'], camera=[sd['camera_a']['label'], sd['camera_b']['label']],
                               size=[sp['size_a'], sp['size_b']], jump_cut=sp['jump_cut'], punch_in=sp['punch_in'],
                               scene_change=sp['scene_change'], masks=v['masks'],
                               shot_frames=[f - prev, nxt - f])
            return _features(m, v['severity'])
        rec = {'f': f, 'video': str(video), 'label': label, 'real': feat(0, 0), 'variants': {}}
        if f != f_given:
            rec['snapped_from'] = f_given
        rec['real_measures'] = summary.pop('_measures', None)
        rec['real_summary'] = summary
        for k in shifts:
            if 'trim_out' in modes:
                rec['variants'][f'trim_out_{k}'] = feat(k, 0)
            if 'trim_in' in modes:
                rec['variants'][f'trim_in_{k}'] = feat(0, k)
            if 'trim_both' in modes:
                rec['variants'][f'trim_both_{k}'] = feat(k, k)
        return rec, None
    with ThreadPoolExecutor(max(1, int(workers))) as ex:
        for i, (rec, sk) in enumerate(ex.map(run, cuts)):
            if rec:
                out.append(rec)
            if sk:
                skipped.append(sk)
            if progress:
                progress(i + 1, len(cuts))
    return {'video': str(video), 'label': label, 'fps': fps, 'per_cut': out, 'skipped': skipped,
            'shifts': list(shifts), 'modes': list(modes)}


def roll_test(project, shifts=(2, 4, 8), settings=None, workers=1, label=None, cut_filter=None):
    """The cut moved earlier and later on the timeline (a roll edit: A's out point and B's in point move together),
    measured from frames of the source clips at the edit's frame rate. Only cuts between two plain clips (speed 1, no
    ffmpeg effect) are tested; every variant, the real cut included, is measured from the source frames, so the
    project's own effects (crop, colour, captions) are the same (absent) in all of them.
    Returns the same shape as shift_test with variants 'roll_early_k' and 'roll_late_k'."""
    import letitedit.footage.shots as shots
    st = _settings(settings)
    thr = thresholds((settings or {}).get('thresholds'))
    meta, cut_list = project_cuts(project)
    fps = float(meta['fps'])
    kmax = max(shifts)
    need = max(int(st['att_a_frames']), int(round(float(st['motion_window_s']) * fps)),
               int(round(float(st['att_b_s']) * fps))) + 1
    ctx = max(int(round(float(st['context_s']) * fps)), need)
    out, skipped = [], []

    def plain(c):
        return (c['kind'] == 'cut' and c.get('from_clip') and c.get('to_clip') and c.get('from_out_s') is not None
                and c.get('to_in_s') is not None and abs(float(c.get('from_speed') or 1) - 1) < 1e-6
                and abs(float(c.get('to_speed') or 1) - 1) < 1e-6 and 'ffmpeg' not in (c.get('from_effects') or [])
                and 'ffmpeg' not in (c.get('to_effects') or []) and os.path.exists(str(c['from_clip']))
                and os.path.exists(str(c['to_clip'])))
    todo = [c for c in cut_list if plain(c) and (cut_filter is None or cut_filter(c))]
    for c in cut_list:
        if c not in todo:
            skipped.append({'f': c['f'], 'why': 'not a plain clip-to-clip cut (speed, effects, gap or transition)'})

    def run(c):
        ia, ib = shots.probe(c['from_clip']), shots.probe(c['to_clip'])
        dsize, _ = _sizes(ia['w'], ia['h'], st['decode_px'], st['flow_px'])
        dsb, _ = _sizes(ib['w'], ib['h'], st['decode_px'], st['flow_px'])
        if dsb != dsize:
            dsb = dsize
        out_s = float(c['from_out_s'])            # source time of A's first frame NOT shown (A ends just before)
        in_s = float(c['to_in_s'])                # source time of B's first frame shown
        ta = [out_s + (i - ctx - kmax) / fps for i in range(ctx + 2 * kmax)]      # A frames up to out + kmax
        tb = [in_s + (i - kmax) / fps for i in range(ctx + 2 * kmax)]             # B frames from in - kmax
        if ta[0] < 0 or tb[0] < 0 or ta[-1] > ia['duration'] - 1.0 / fps or tb[-1] > ib['duration'] - 1.0 / fps:
            return None, {'f': c['f'], 'why': 'source clip too short around the cut for the shift'}
        fa = decode_at_times(c['from_clip'], ta, dsize, ia)
        fb = decode_at_times(c['to_clip'], tb, dsb, ib)
        if any(x is None for x in fa) or any(x is None for x in fb):
            return None, {'f': c['f'], 'why': 'source frames missing'}
        fb = [b if b.shape[:2] == fa[0].shape[:2] else _cv2().resize(b, (fa[0].shape[1], fa[0].shape[0]))
              for b in fb]
        A = analyse_side(fa, fps, st, thr)
        B = analyse_side(fb, fps, st, thr)
        na_real = ctx + kmax                      # A frames [0, na_real) end at the real out point
        nb_off = kmax                             # B frames from index kmax start at the real in point

        def feat(da):                            # da > 0: cut later by da; < 0: earlier
            ea = na_real + da
            sb = nb_off + da
            sa = _subset(A, max(0, ea - ctx), ea)
            sbb = _subset(B, sb, sb + ctx)
            m = measure_join(sa, sbb, fps, st, thr)
            v = verdict(m, 'cut', None, thr)
            return _features(m, v['severity'])
        rec = {'f': c['f'], 'video': str(project), 'label': label, 'real': feat(0), 'variants': {},
               'from_clip': c['from_clip'], 'to_clip': c['to_clip']}
        for k in shifts:
            rec['variants'][f'roll_early_{k}'] = feat(-k)
            rec['variants'][f'roll_late_{k}'] = feat(k)
        return rec, None
    with ThreadPoolExecutor(max(1, int(workers))) as ex:
        for rec, sk in ex.map(run, todo):
            if rec:
                out.append(rec)
            if sk:
                skipped.append(sk)
    return {'video': str(project), 'label': label, 'fps': fps, 'per_cut': out, 'skipped': skipped,
            'shifts': list(shifts), 'modes': ['roll_early', 'roll_late']}


def separation(per_cut, n_boot=1000, seed=7):
    """For every feature and variant: the paired AUC P(real > variant) over cuts (ties 0.5) with a bootstrap 95%
    interval over cuts, and the unpaired AUC (Mann-Whitney) of real values against all variants of that kind.
    AUC 0.5 = the measure does not tell the real cut from the moved one; the a-priori expectation (FEATURES) says
    which side a well-placed cut should be on."""
    rng = np.random.default_rng(seed)
    keys = sorted({k for r in per_cut for k in r['variants']})
    feats = sorted({f for r in per_cut for f in r['real']})
    out = {}
    for fname in feats:
        row = {}
        for vk in keys:
            pairs = []
            for r in per_cut:
                a = r['real'].get(fname)
                b = (r['variants'].get(vk) or {}).get(fname)
                if a is None or b is None:
                    continue
                pairs.append(1.0 if a > b + 1e-9 else 0.0 if a < b - 1e-9 else 0.5)
            if len(pairs) < 5:
                continue
            p = np.asarray(pairs)
            boots = [float(p[rng.integers(0, len(p), len(p))].mean()) for _ in range(n_boot)]
            row[vk] = {'auc_real_higher': _r(float(p.mean())), 'ci95': [_r(np.percentile(boots, 2.5)),
                                                                         _r(np.percentile(boots, 97.5))],
                       'n': len(p), 'ties': int((p == 0.5).sum())}
        out[fname] = row
    return out
