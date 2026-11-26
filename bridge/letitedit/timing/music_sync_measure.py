"""Picture events, the measures, speech against music, song sections against story sections, SFX against impacts.

Part of `music_sync` (letitedit/timing/music_sync.py), which imports every name here back,
so `music_sync.X` is the same object it always was.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from letitedit.timing.music_sync_base import (  # noqa: E402
    MUSIC_NAME, SFX_NAME, _decode, _r, th
)


# ============================================================================ picture events

def _lane_events(lane_d, keys=('events', 'beats', 'visual_beats', 'motion_events', 'peaks')):
    """The event list of a lane (the first list of dicts with a frame) whatever its key."""
    if not isinstance(lane_d, dict) or lane_d.get('error'):
        return []
    for k in keys:
        v = lane_d.get(k)
        if isinstance(v, list) and (not v or isinstance(v[0], dict)):
            return v
    for k, v in lane_d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict) and ('f' in v[0] or 'f_peak' in v[0]):
            return v
    return []


def _fallback_motion(video, fps, frames, cut_frames, st_):
    """Motion energy per frame, motion peaks and visual beats from the residual frame difference after the camera
    move is undone (shots.features 'mad'), for when the motion lanes are not registered."""
    import letitedit.footage.shots as shots
    from scipy.signal import find_peaks
    feat = shots.features(video)
    t = np.asarray(feat['t'], float)
    mad = np.asarray(feat['mad'], float)
    e = np.full(frames, np.nan)
    idx = np.clip(np.round(t * fps).astype(int), 0, frames - 1)
    e[idx] = mad
    bad = np.zeros(frames, bool)
    for f in cut_frames:
        bad[max(0, f - 1):min(frames, f + 2)] = True
    e[bad] = np.nan
    good = np.isfinite(e)
    if good.sum() < 4:
        return {'energy': [None] * frames, 'peaks': [], 'visual_beats': []}
    e = np.interp(np.arange(frames), np.flatnonzero(good), e[good])
    k = np.ones(3) / 3
    es_ = np.convolve(e, k, mode='same')
    rel = float(th('sync.motion_peak_rel'))
    edges = [0] + sorted(set(int(f) for f in cut_frames)) + [frames]
    peaks, vbeats = [], []
    for a, b in zip(edges, edges[1:]):
        if b - a < 6:
            continue
        seg = es_[a:b]
        med = float(np.median(seg)) + 1e-6
        p, props = find_peaks(seg, height=rel * med, distance=max(3, int(0.3 * fps)), prominence=0.5 * med)
        for q in p:
            f = a + int(q)
            peaks.append({'f': f, 't': round(f / fps, 4), 'f_peak': f, 'strength': round(float(seg[q] / med), 2)})
            hi = min(b, f + int(0.5 * fps))
            m = f + int(np.argmin(es_[f:hi])) if hi > f + 1 else None
            if m is not None and es_[m] <= 0.5 * es_[f]:
                vbeats.append({'f': m, 't': round(m / fps, 4),
                               'strength': round(float((es_[f] - es_[m]) / (es_[f] + 1e-6)), 2)})
    return {'energy': [round(float(v), 3) for v in es_], 'peaks': peaks, 'visual_beats': vbeats,
            'method': 'fallback: residual frame difference after the camera move (shots.features mad, 0-255), '
                      'peaks over ' + f'{rel:g}x the shot median, visual beats where it falls by half within 0.5 s'}


def _sfx_onset_in_clip(clip, in_s, dur):
    """Seconds into the clip (from its in point) of the first strong onset (envelope within 12 dB of the clip's
    peak in its first 3 s), or 0."""
    try:
        y = _decode(clip, 16000, start=in_s, dur=min(3.0, max(0.1, dur)))
    except Exception:  # noqa: BLE001
        return 0.0
    if len(y) < 160:
        return 0.0
    hop = 80
    n = len(y) // hop
    env = 10 * np.log10(np.mean(y[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    pk = float(env.max())
    i = int(np.flatnonzero(env >= pk - 12.0)[0])
    return i * hop / 16000.0


def picture_events(sig, st_=None, music_lane=None):
    """{kind: [events]} of a signals() result: cuts, motion_peaks, visual_beats, text_pops, sfx (projects: clips on
    effects tracks; videos: strong sound onsets outside speech and off the beat grid). Each event {f, t, kind, ...}.
    Also returns notes on where each came from."""
    fps, frames = float(sig['fps']), int(sig['frames'])
    lanes = sig.get('lanes') or {}
    ed = lanes.get('edit') or {}
    notes, unsupported = {}, []
    out = {'cuts': [], 'motion_peaks': [], 'visual_beats': [], 'text_pops': [], 'sfx': [], 'caption_pops': []}
    for c in ed.get('cuts') or []:
        if c.get('detail') in ('from black', 'to black'):
            continue
        out['cuts'].append({'f': int(c['f']), 't': round(int(c['f']) / fps, 4), 'kind': c.get('kind', 'cut'),
                            'f0': c.get('f0'), 'f1': c.get('f1'), 'from_item': c.get('from_item'),
                            'to_item': c.get('to_item')})
    notes['cuts'] = ed.get('source_of_cuts') or ed.get('method')
    for p in ed.get('text_pops') or []:
        k = 'caption_pops' if p.get('kind') in ('caption', 'word') else 'text_pops'
        out[k].append({'f': int(p['f']), 't': round(int(p['f']) / fps, 4), 'kind': p.get('kind', 'text'),
                       'text': (p.get('text') or '')[:40], 'id': p.get('id')})
    notes['text_pops'] = 'edit lane text_pops: text and graphics appearing (captions are in caption_pops)'
    notes['caption_pops'] = 'edit lane text_pops of captions and caption words: they follow the speech, so they ' \
                            'are measured only when asked (options.kinds)'
    me = _lane_events(lanes.get('motion_events'), ('motion_events', 'events'))
    vb = _lane_events(lanes.get('visual_beats'), ('visual_beats', 'beats', 'events'))
    if me:
        for e in me:
            f = int(e.get('f_peak', e.get('f')))
            out['motion_peaks'].append({'f': f, 't': round(f / fps, 4), 'kind': 'motion_peak',
                                        'strength': e.get('strength'), 'f0': e.get('f0'), 'f1': e.get('f1')})
        notes['motion_peaks'] = (lanes.get('motion_events') or {}).get('method')
    if vb:
        for e in vb:
            f = int(e.get('f'))
            out['visual_beats'].append({'f': f, 't': round(f / fps, 4), 'kind': 'visual_beat',
                                        'strength': e.get('strength')})
        notes['visual_beats'] = (lanes.get('visual_beats') or {}).get('method')
    motion_energy = None
    if lanes.get('motion') and not lanes['motion'].get('error') and lanes['motion'].get('energy'):
        motion_energy = lanes['motion']['energy']
    if (not me or not vb or motion_energy is None) and (st_ or {}).get('fallback_motion', True):
        video = sig.get('render') or (sig.get('source') if sig.get('kind') == 'video' else None)
        if video and Path(video).exists():
            try:
                fb = _fallback_motion(video, fps, frames, [c['f'] for c in out['cuts']], st_ or {})
                if not me:
                    out['motion_peaks'] = [dict(p, kind='motion_peak') for p in fb['peaks']]
                    notes['motion_peaks'] = fb.get('method')
                if not vb:
                    out['visual_beats'] = [dict(v, kind='visual_beat') for v in fb['visual_beats']]
                    notes['visual_beats'] = fb.get('method')
                if motion_energy is None:
                    motion_energy = fb['energy']
                    notes['motion_energy'] = fb.get('method')
            except Exception as e:  # noqa: BLE001
                unsupported.append(f'motion could not be measured ({type(e).__name__}: {e})')
        else:
            unsupported.append('motion peaks and visual beats: no motion lanes and no picture to measure')
    # SFX
    if sig.get('kind') == 'project':
        for it in ed.get('items') or []:
            if it.get('kind') != 'audio' or not it.get('clip') or it.get('muted'):
                continue
            if not SFX_NAME.search(str(it.get('track') or '')) or MUSIC_NAME.search(str(it.get('track') or '')):
                continue
            dur = (it['f1'] - it['f0']) / fps
            on = _sfx_onset_in_clip(it['clip'], float(it.get('in_s') or 0.0), dur) / float(it.get('speed') or 1.0)
            f = int(round(it['f0'] + on * fps))
            out['sfx'].append({'f': f, 't': round(f / fps, 4), 'kind': 'sfx', 'id': it.get('id'),
                               'track': it.get('track'), 'clip': Path(it['clip']).name,
                               'onset_in_clip_s': round(on, 3)})
        notes['sfx'] = 'clips on effects tracks (sfx/fx/effect/sound/foley): item start + the first strong onset ' \
                       'in the clip (within 12 dB of its peak)'
    else:
        au = lanes.get('audio') or {}
        ons = au.get('onsets') if isinstance(au, dict) and not au.get('error') else None
        if ons:
            beats_t = np.asarray([b['t'] for b in (music_lane or {}).get('beats') or []], float)
            grid_t = np.sort(np.concatenate([beats_t, (beats_t[1:] + beats_t[:-1]) / 2])) if len(beats_t) > 1 \
                else beats_t           # beats and half-beats: music notes on the grid
            st_strong = sorted([o.get('strength') or 0 for o in ons])
            cut_s = st_strong[int(0.8 * (len(st_strong) - 1))] if st_strong else 0
            for o in ons:
                if (o.get('strength') or 0) < cut_s:
                    continue
                t = float(o['t'])
                if len(grid_t) and float(np.min(np.abs(grid_t - t))) < 0.04:
                    continue
                f = int(round(t * fps))
                out['sfx'].append({'f': f, 't': round(t, 4), 'kind': 'sound_onset', 'strength': o.get('strength')})
            notes['sfx'] = ('video: the strongest 20% of the audio lane\'s onsets that are not within 40 ms of a beat or '
                            'half-beat; speech onsets are removed later when the words are known; other music notes can '
                            'remain (no SFX stem exists): these are sound onsets, not known SFX')
        else:
            unsupported.append('SFX of a plain video: no audio lane onsets (sound effects are not separable from '
                               'music without an effects stem)')
    for k in out:
        out[k].sort(key=lambda e: e['f'])
    return out, notes, unsupported, motion_energy


# ============================================================================ measures

def _beat_arrays(music_lane):
    beats = music_lane.get('beats') or []
    t = np.asarray([b['t'] for b in beats], float)
    down = np.asarray([b['t'] for b in beats if b.get('downbeat')], float)
    return beats, t, down


def _nearest(tarr, t):
    if not len(tarr):
        return None, None, None
    i = int(np.searchsorted(tarr, t))
    cands = [j for j in (i - 1, i) if 0 <= j < len(tarr)]
    j = min(cands, key=lambda j: abs(tarr[j] - t))
    prev_j = i - 1 if i - 1 >= 0 else None
    next_j = i if i < len(tarr) else None
    return j, prev_j, next_j


def _period_at(tarr, j, med=None):
    """The beat period at beat j from the intervals beside it that belong to the same run of beats (a gap between
    music pieces or a drop-out is not a beat interval): within 0.6-1.6x the median interval; else the median."""
    if len(tarr) < 2:
        return None
    if med is None:
        d = np.diff(tarr)
        med = float(np.median(d)) if len(d) else None
    if not med:
        return None
    iv = []
    if j > 0:
        iv.append(float(tarr[j] - tarr[j - 1]))
    if j < len(tarr) - 1:
        iv.append(float(tarr[j + 1] - tarr[j]))
    iv = [x for x in iv if 0.6 * med <= x <= 1.6 * med]
    return float(np.mean(iv)) if iv else med


def _neighbour_ok(tarr, j, k, per):
    """Is beat k the beat next to j in the same run (not across a gap)?"""
    return 0 <= k < len(tarr) and abs(tarr[k] - tarr[j]) <= 1.6 * per


def measure_events(events, music_lane, fps, music_spans=None):
    """Adds to each event its offsets (frames) to the nearest beat and downbeat (signed: event - beat), the
    previous/next beat, the beat period there, the phase (offset / period, -0.5..0.5), and whether music plays."""
    beats, bt, dt = _beat_arrays(music_lane)
    spans = music_spans if music_spans is not None else music_lane.get('music_spans') or []
    med_all = float(np.median(np.diff(bt))) if len(bt) > 1 else None
    med_piece = {}                         # each piece's own median beat interval (songs differ in tempo)
    for pc in {b.get('piece') for b in beats}:
        pt = np.asarray([b['t'] for b in beats if b.get('piece') == pc], float)
        if len(pt) > 2:
            med_piece[pc] = float(np.median(np.diff(pt)))
    out = []
    for e in events:
        t = e['f'] / fps
        r = dict(e)
        inside = any(a - 0.05 <= t <= b + 0.05 for a, b in spans)
        r['music'] = bool(inside and len(bt))
        j, pj, nj = _nearest(bt, t)
        if j is not None and r['music']:
            b = beats[j]
            per = _period_at(bt, j, med_piece.get(b.get('piece'), med_all))
            if per is None or per <= 0 or abs(t - bt[j]) > 0.75 * per:
                r['music'] = False
            else:
                r['beat_offset_frames'] = round((t - bt[j]) * fps, 2)
                r['beat_t'] = round(float(bt[j]), 4)
                r['beat_pos'] = b.get('pos')
                r['beat_bar'] = b.get('bar')
                r['beat_period_frames'] = round(per * fps, 2)
                r['phase'] = round((t - bt[j]) / per, 3)
                def rel(k, j=j, t=t, per=per):
                    if k is None or (k != j and not _neighbour_ok(bt, j, k, per)):
                        return None          # no beat there in this run of beats (a gap between pieces)
                    return round((t - bt[k]) * fps, 2)
                r['prev_beat_frames'] = rel(pj)
                r['next_beat_frames'] = rel(nj)
                # the half-beat point on the event's side (eighth notes at the chosen level); at the edge of a run
                # of beats (a gap between pieces) the local period stands in for the missing neighbour
                k2 = j + 1 if t >= bt[j] else j - 1
                if _neighbour_ok(bt, j, k2, per):
                    hp = (bt[j] + bt[k2]) / 2
                else:
                    hp = bt[j] + (per / 2 if t >= bt[j] else -per / 2)
                r['half_beat_offset_frames'] = round((t - hp) * fps, 2)
                r['beat_audible'] = b.get('audible')
                r['beat_strength'] = b.get('strength')
                r['on_phrase'] = bool(b.get('phrase'))
                r['on_drop'] = bool(b.get('drop'))
                dj, _, _ = _nearest(dt, t)
                if dj is not None:
                    r['downbeat_offset_frames'] = round((t - dt[dj]) * fps, 2)
                    r['downbeat_t'] = round(float(dt[dj]), 4)
                    bar_s = float(np.median(np.diff(dt))) if len(dt) > 1 else None
                    r['bar_frames'] = round(bar_s * fps, 2) if bar_s else None
        out.append(r)
    return out


def _chance(periods_frames, k):
    """Share of events within k frames of the nearest beat if they fell at random phases (mean over the periods)."""
    p = [x for x in periods_frames if x]
    if not p:
        return None
    return round(float(np.mean([min(1.0, 2.0 * k / x) for x in p])), 3)


def summarize(events, fps, given=None):
    """Numbers of one kind of event against the grid (only events where music plays)."""
    on_k, near_k = float(th('sync.on_beat_frames', given)), float(th('sync.near_beat_frames', given))
    m = [e for e in events if e.get('music') and e.get('beat_offset_frames') is not None]
    res = {'n': len(events), 'n_with_music': len(m)}
    if not m:
        return res
    off = np.asarray([e['beat_offset_frames'] for e in m], float)
    per = [e.get('beat_period_frames') for e in m]
    res.update({
        'within_on_beat': int(np.sum(np.abs(off) <= on_k)), 'share_on_beat': round(float(np.mean(np.abs(off) <= on_k)), 3),
        'within_near_beat': int(np.sum(np.abs(off) <= near_k)),
        'share_near_beat': round(float(np.mean(np.abs(off) <= near_k)), 3),
        'chance_on_beat': _chance(per, on_k), 'chance_near_beat': _chance(per, near_k),
        'median_abs_offset_frames': round(float(np.median(np.abs(off))), 2),
        'median_offset_frames': round(float(np.median(off)), 2),
        'mean_beat_period_frames': round(float(np.mean([p for p in per if p])), 2) if any(per) else None})
    half = [e for e in m if abs(e['beat_offset_frames']) > on_k and e.get('half_beat_offset_frames') is not None]
    res['share_on_half_beat'] = round(float(np.mean([abs(e['half_beat_offset_frames']) <= on_k for e in half])) * (
        len(half) / len(m)), 3) if half else 0.0
    res['half_beat_about'] = ('share of all events (with music) that are off the beat but within the on-beat threshold '
                              'of the point halfway between two beats (eighth notes at the chosen tempo level); chance '
                              'about the same as chance_on_beat')
    ph = np.asarray([e['phase'] for e in m], float) * 2 * math.pi
    R = float(np.abs(np.mean(np.exp(1j * ph))))
    n = len(ph)
    z = n * R * R
    p_ray = math.exp(math.sqrt(1 + 4 * n + 4 * (n * n - z * n)) - (1 + 2 * n)) if n >= 2 else None
    res['phase_locking'] = {'vector_strength': round(R, 3), 'rayleigh_p': _r(p_ray, 4) if p_ray is not None else None,
                            'mean_phase': round(float(np.angle(np.mean(np.exp(1j * ph))) / (2 * math.pi)), 3),
                            'about': 'how tightly the events keep one place in the beat (0 = any phase, 1 = always the '
                                     'same); Rayleigh p: chance of that much locking at random phases; mean_phase in '
                                     'beats (0 = on the beat, +0.5 = half a beat after)'}
    d = [e for e in m if e.get('downbeat_offset_frames') is not None]
    if d:
        doff = np.asarray([e['downbeat_offset_frames'] for e in d], float)
        bars = [e.get('bar_frames') for e in d]
        res['downbeat'] = {'n': len(d), 'share_on': round(float(np.mean(np.abs(doff) <= on_k)), 3),
                           'share_near': round(float(np.mean(np.abs(doff) <= near_k)), 3),
                           'chance_on': _chance(bars, on_k), 'chance_near': _chance(bars, near_k),
                           'median_abs_offset_frames': round(float(np.median(np.abs(doff))), 2)}
    res['histogram_frames'] = _hist(off)
    return res


def _hist(off):
    if not len(off):
        return {}
    lo, hi = int(math.floor(off.min())), int(math.ceil(off.max()))
    bins = {}
    for v in off:
        k = int(round(v))
        bins[k] = bins.get(k, 0) + 1
    return {str(k): bins.get(k, 0) for k in range(lo, hi + 1)}


def monotony(cuts, given=None):
    """How regular the cutting is against the grid: on-beat share, the longest run of consecutive on-beat cuts,
    shot lengths in beats (are they always the same?)."""
    on_k = float(th('sync.on_beat_frames', given))
    m = [c for c in cuts if c.get('music') and c.get('beat_offset_frames') is not None]
    res = {'cuts_with_music': len(m), 'threshold_on_beat_frames': on_k,
           'share_threshold': th('sync.monotony_share', given), 'run_threshold': th('sync.monotony_run', given)}
    if not m:
        return res
    on = [abs(c['beat_offset_frames']) <= on_k for c in m]
    best, cur, start, best_span = 0, 0, None, None
    for c, o in zip(m, on):
        if o:
            if cur == 0:
                start = c
            cur += 1
            if cur > best:
                best, best_span = cur, (start['t'], c['t'])
        else:
            cur = 0
    don = [abs(c.get('downbeat_offset_frames', 99)) <= on_k for c in m]
    dbest, dcur = 0, 0
    for o in don:
        dcur = dcur + 1 if o else 0
        dbest = max(dbest, dcur)
    share = float(np.mean(on))
    lens = []
    for a, b in zip(m, m[1:]):
        per = a.get('beat_period_frames')
        if per:
            lens.append((b['f'] - a['f']) / per)
    res.update({'share_on_beat': round(share, 3), 'longest_on_beat_run': best,
                'longest_run_span_s': [round(best_span[0], 3), round(best_span[1], 3)] if best_span else None,
                'share_on_downbeat': round(float(np.mean(don)), 3), 'longest_on_downbeat_run': dbest,
                'flag_share': share >= float(th('sync.monotony_share', given)),
                'flag_run': best >= int(th('sync.monotony_run', given))})
    if len(lens) >= 3:
        L = np.asarray(lens)
        whole = np.abs(L - np.round(L)) <= 0.15
        vals, cnt = np.unique(np.round(L[whole]).astype(int), return_counts=True)
        top = int(vals[np.argmax(cnt)]) if len(vals) else None
        res['shot_lengths_beats'] = {
            'median': round(float(np.median(L)), 2), 'cv': round(float(np.std(L) / (np.mean(L) + 1e-9)), 3),
            'share_whole_beats': round(float(np.mean(whole)), 3),
            'most_common_whole': top, 'share_most_common': round(float(cnt.max() / len(L)), 3) if len(vals) else 0.0,
            'about': 'shot lengths (cut to cut) in beats: a low cv with one common whole number is a regular '
                     'pattern (every shot 4 beats)'}
    return res


def hard_hits(cuts, given=None):
    """Cuts on strong musical accents (a downbeat at least sync.hard_hit_min_strength strong, a phrase start or a
    drop) within sync.near_beat_frames: how far the sound leads the cut there (reference: about half a frame)."""
    near_k = float(th('sync.near_beat_frames', given))
    smin = float(th('sync.hard_hit_min_strength', given))
    ref = float(th('sync.hard_hit_sound_lead_frames', given))
    hits = []
    for c in cuts:
        if not c.get('music') or c.get('beat_offset_frames') is None:
            continue
        if abs(c['beat_offset_frames']) > near_k:
            continue
        strong = c.get('on_drop') or c.get('on_phrase') or (c.get('beat_pos') == 1 and (c.get('beat_strength') or 0)
                                                             >= smin)
        if strong:
            hits.append({'f': c['f'], 't': c['t'], 'sound_lead_frames': c['beat_offset_frames'],
                         'why': 'drop' if c.get('on_drop') else 'phrase start' if c.get('on_phrase') else
                         f'strong downbeat ({c.get("beat_strength")})'})
    res = {'n': len(hits), 'reference_sound_lead_frames': ref,
           'reference': 'AOTC Dune (letitedit-sound): on a hard hit the sound sits about half a frame before the cut; '
                        'a reference point, not a rule', 'hits': hits[:40]}
    if hits:
        lead = np.asarray([h['sound_lead_frames'] for h in hits])
        res.update(median_sound_lead_frames=round(float(np.median(lead)), 2),
                   share_sound_first=round(float(np.mean(lead > 0)), 3),
                   share_within_one_frame_of_reference=round(float(np.mean(np.abs(lead - ref) <= 1.0)), 3))
    return res


# ---------------------------------------------------------------------------- speech against music

def _speech(sig, given=None):
    """(spans [[t0, t1]], words [{w, t0, t1}], dialogue_lufs or None, how)."""
    lanes = sig.get('lanes') or {}
    sp = lanes.get('speech')
    if isinstance(sp, dict) and not sp.get('error') and sp.get('words'):
        words = [{'w': w.get('w'), 't0': float(w['t0']), 't1': float(w['t1'])} for w in sp['words']]
        import letitedit.sound.music as music
        spans = music.merge([[max(0.0, w['t0'] - music.WORD_PAD_IN), w['t1'] + music.WORD_PAD_OUT] for w in words],
                            gap=music.WORD_JOIN)
        return spans, words, None, 'speech lane words (prosody), padded like music.py'
    if sig.get('kind') == 'project' and sig.get('project'):
        try:
            import letitedit.timeline.edit_script as es
            import letitedit.sound.music as music
            script = es.read(sig['project'])
            info = {}
            spans, lufs = music.speech(script, info=info)
            how = 'music.speech: cached words where transcribed' + (', the voice detector for ' +
                                                                    str(len(info.get('voice', ())))
                                                                    + ' files' if info.get('voice') else '')
            return spans, info.get('timeline_words') or [], (lufs if lufs and math.isfinite(lufs) else None), how
        except Exception as e:  # noqa: BLE001
            return [], [], None, f'speech unknown ({type(e).__name__}: {e})'
    src = sig.get('source')
    try:
        import letitedit.footage.speech as speech_words
        import letitedit.sound.music as music
        ws = speech_words.cached_words(src)
        if ws:
            words = [{'w': w['w'], 't0': float(w['s']), 't1': min(float(w['e']), float(w['s']) + music.WORD_MAX_S)}
                     for w in ws]
            spans = music.merge([[max(0.0, w['t0'] - music.WORD_PAD_IN), w['t1'] + music.WORD_PAD_OUT]
                                 for w in words], gap=music.WORD_JOIN)
            return spans, words, None, 'cached transcript words of the video (speech.cached_words)'
        prof = music.voice_profile(src)
        return [list(v) for v in prof.get('voice') or []], [], None, 'voice detector (no transcript cached)'
    except Exception as e:  # noqa: BLE001
        return [], [], None, f'speech unknown ({type(e).__name__}: {e})'


def _level_at(lev, every, a, b):
    vals = [lev[j] for j in range(max(0, int(a / every)), min(len(lev), int(math.ceil(b / every))))
            if lev[j] is not None]
    if not vals:
        return None
    return 10 * math.log10(np.mean([10 ** (v / 10) for v in vals]))


def speech_vs_music(sig, music_lane, given=None):
    """Does the music rise in the pauses and stay under the words? Per speech gap (music.speech_gaps): the music
    level in the gap against its level under the words on each side (2 s), and the music under speech."""
    spans, words, dlg, how = _speech(sig, given)
    res = {'speech_from': how, 'speech_spans': len(spans)}
    lev = music_lane.get('level_db') or []
    every = float(music_lane.get('level_every_s') or 0.1)
    if not spans:
        res['note'] = 'no speech found: nothing to compare'
        return res
    if not any(v is not None for v in lev):
        res['note'] = 'no music level: nothing to compare'
        return res
    import letitedit.sound.music as music
    gaps = music.speech_gaps(spans, words)
    gmin = float(th('sync.gap_min_s', given))
    rise_min = float(th('sync.swell_rise_db', given))
    rows = []
    for g in gaps:
        if g['len'] < gmin:
            continue
        a, b = g['from'], g['to']
        inner = _level_at(lev, every, a + 0.1 * (b - a), b - 0.1 * (b - a))
        before = _level_at(lev, every, max(0, a - 2.0), a)
        after = _level_at(lev, every, b, b + 2.0)
        ref = [v for v in (before, after) if v is not None]
        if inner is None or not ref:
            continue
        under = 10 * math.log10(np.mean([10 ** (v / 10) for v in ref]))
        rise = inner - under
        rows.append({'id': g['id'], 't0': round(a, 3), 't1': round(b, 3), 'len_s': g['len'], 'pause_s': g['pause'],
                     'music_in_gap_db': round(inner, 1), 'music_under_words_db': round(under, 1),
                     'rise_db': round(rise, 1), 'swell': rise >= rise_min, 'after': g.get('after', '')[-40:],
                     'before': g.get('before', '')[:30]})
    res['gaps_checked'] = len(rows)
    res['gap_min_s'] = gmin
    res['swell_rise_db'] = rise_min
    if rows:
        res['gaps_with_swell'] = int(sum(r['swell'] for r in rows))
        res['share_gaps_with_swell'] = round(float(np.mean([r['swell'] for r in rows])), 3)
        res['median_rise_db'] = round(float(np.median([r['rise_db'] for r in rows])), 1)
        res['gaps'] = sorted(rows, key=lambda r: -r['len_s'])[:25]
    # music under the words
    talk = []
    for a, b in spans:
        v = _level_at(lev, every, a, b)
        if v is not None:
            talk.append((a, b, v))
    if talk and _music_against_voice():
        _music_against_voice_facts(res, sig, music_lane, spans, lev, every, dlg)
    elif talk:
        res['music_under_speech_db_median'] = round(float(np.median([v for _, _, v in talk])), 1)
        if dlg is not None:
            lim = float(th('sync.music_under_speech_db', given))
            close = [{'t0': round(a, 2), 't1': round(b, 2), 'music_db': round(v, 1),
                      'under_dialogue_db': round(dlg - v, 1)} for a, b, v in talk if dlg - v < lim]
            res['dialogue_lufs'] = round(dlg, 1)
            res['music_under_dialogue_db_median'] = round(float(np.median([dlg - v for _, _, v in talk])), 1)
            res['spans_closer_than'] = {'threshold_db': lim, 'n': len(close), 'spans': close[:20]}
    res['method'] = ('music level as heard (lane level_db: the songs\' K-weighted loudness + clip/track gain and '
                     'fades) averaged as power; a gap is between the padded words (music.speech_gaps); its middle 80% '
                     'against the 2 s of talk before and after')
    return res


def _music_against_voice():
    """T349, behind review_craft_checks (on by default): the music under the talk stated against the voice, in LU."""
    try:
        import letitedit.review.picture_words as picture_words
        return picture_words.enabled()
    except Exception:  # noqa: BLE001 - unreadable: as before
        return False


def _music_against_voice_facts(res, sig, music_lane, spans, lev, every, dlg):
    """The music under the talk, as letitedit_check_audio states it. music_under_speech_db: the music's own level over
    all the talk (power mean, every reading weighted the same, so a short span counts for its length, not as much as a
    long one). music_below_voice_while_talking_lu: how far the music sits under the voice (sound.music's rule, on the
    3 s readings of the video's separated music and voice); for a project, the dialogue's integrated loudness minus
    that level."""
    vals = []
    for a, b in spans:
        vals += [lev[j] for j in range(max(0, int(a / every)), min(len(lev), int(math.ceil(b / every))))
                 if lev[j] is not None]
    if vals:
        res['music_under_speech_db'] = round(10 * math.log10(np.mean([10 ** (v / 10) for v in vals])), 1)
    gap, how = None, None
    if sig.get('kind') == 'project':
        if dlg is not None and vals:
            gap, how = round(dlg - res['music_under_speech_db'], 1), ("the dialogue's integrated loudness minus the "
                                                                      "music's level over the talk")
    elif str(music_lane.get('stem') or '').startswith('music stem') and sig.get('source'):
        try:
            import letitedit.sound.model_tools as model_tools
            import letitedit.sound.music as music
            sep = model_tools.separate(sig['source'], parts=['music', 'vocals'], loudness_every_s=0.1)
            m, v = sep['loudness']['music']['short_term'], sep['loudness']['vocals']['short_term']
            start = float(sep.get('start') or 0.0)
            gap = music.music_below_voice_lu([(a[1], b[1]) for a, b in zip(m, v) if a[0] >= start + 3.0])
            how = ('the separated music and voice of the video, short-term (3 s) readings while the voice is over '
                   f"{music.TALK_ABOVE_LUFS:g} LUFS, the median of voice minus music (letitedit_check_audio's rule)")
        except Exception as e:  # noqa: BLE001 - said, never a number
            how = f'not measured ({type(e).__name__}: {e})'[:300]
    if gap is not None:
        res['music_below_voice_while_talking_lu'] = gap
    if how:
        res['music_below_voice_from'] = how
    res['music_level_note'] = ("music_under_speech_db is the music's own level (dB on its own stem or clips), not a "
                               'level against the mix; music_below_voice_while_talking_lu is how far it sits under the '
                               'voice, in LU, as letitedit_check_audio states it')


# ---------------------------------------------------------------------------- song sections against story sections

def story_sections(sig, options=None):
    """[{t0, t1, label, from}] story sections: chapter/section/beat markers, else the story plan mapped to the
    timeline (trajectory.plan_sections), else []."""
    marks = (sig.get('lanes') or {}).get('edit', {}).get('markers') or []
    if not marks and sig.get('project'):
        try:
            import letitedit.timing.timing_signals as timing_signals
            marks = timing_signals.read_markers(sig['project'])
        except Exception:  # noqa: BLE001
            marks = []
    fps = float(sig['fps'])
    dur = int(sig['frames']) / fps
    chap = [m for m in marks if m.get('kind') in ('chapter', 'section')]
    if len(chap) >= 2 or (chap and chap[0]['t'] > 0.5):
        starts = sorted({0.0} | {float(m['t']) for m in chap})
        labels = {float(m['t']): m.get('label') for m in chap}
        return [{'t0': a, 't1': b, 'label': labels.get(a, 'start'), 'from': 'chapter markers'}
                for a, b in zip(starts, starts[1:] + [dur]) if b - a > 0.2]
    try:
        import letitedit.timing.trajectory as trajectory
        secs, src, _ = trajectory.plan_sections(sig, options or {})
        if secs:
            return [dict(s, **{'from': src}) for s in secs]
    except Exception:  # noqa: BLE001
        pass
    return []


def sections_vs_story(sig, music_lane, options=None, given=None):
    """Each story boundary against the song's boundaries (energy-section starts, phrase starts, drops, joins between
    music pieces) in bars, and the music intensity per story section."""
    secs = story_sections(sig, options)
    res = {'story_sections_from': secs[0]['from'] if secs else None, 'n_story_sections': len(secs)}
    if not secs:
        res['note'] = 'no chapter/section markers and no story plan found: nothing to compare'
        return res
    beats = music_lane.get('beats') or []
    if not beats:
        res['note'] = 'no beat grid: nothing to compare'
        return res
    dt = np.asarray([b['t'] for b in beats if b.get('downbeat')], float)
    bar_s = float(np.median(np.diff(dt))) if len(dt) > 1 else None
    cands = {'section': [s['t0'] for s in music_lane.get('sections') or []],
             'phrase': [p['t'] for p in music_lane.get('phrases') or []],
             'drop': [d['t'] for d in music_lane.get('drops') or []],
             'join': [p['t0'] for p in music_lane.get('pieces') or []]}
    match_bars = float(th('sync.section_match_bars', given))
    rows = []
    for s in secs[1:]:
        t = s['t0']
        best = None
        for kind, ts in cands.items():
            for x in ts:
                d = t - x
                if best is None or abs(d) < abs(best[1]):
                    best = (kind, d, x)
        row = {'boundary_t': round(t, 3), 'into': s.get('label')}
        if best:
            row.update(nearest_song_boundary=best[0], song_t=round(best[2], 3), offset_s=round(best[1], 3),
                       offset_bars=round(best[1] / bar_s, 2) if bar_s else None,
                       aligned=bool(bar_s and abs(best[1]) <= match_bars * bar_s))
        if len(dt):
            j = int(np.argmin(np.abs(dt - t)))
            row['nearest_downbeat_offset_frames'] = round((t - dt[j]) * float(sig['fps']), 2)
        rows.append(row)
    res['boundaries'] = rows
    res['aligned'] = int(sum(1 for r in rows if r.get('aligned')))
    res['bar_s'] = _r(bar_s, 3)
    res['match_bars'] = match_bars
    inten = music_lane.get('intensity') or []
    lev = music_lane.get('energy') or []
    ev = float(music_lane.get('energy_every_s') or 0.5)
    per = []
    for s in secs:
        a, b = s['t0'], s['t1']
        iv = [v for v in inten[int(a / ev):int(math.ceil(b / ev))] if v is not None]
        lv = [v for v in lev[int(a / ev):int(math.ceil(b / ev))] if v is not None]
        per.append({'label': s.get('label'), 't0': round(a, 3), 't1': round(b, 3), 'gear': s.get('gear'),
                    'feel': s.get('feel'), 'music_intensity': _r(np.mean(iv), 3) if iv else None,
                    'music_level_db': _r(10 * math.log10(np.mean([10 ** (v / 10) for v in lv])), 1) if lv else None})
    res['sections'] = per
    gears = [(p['gear'], p['music_intensity']) for p in per if isinstance(p.get('gear'), (int, float))
             and p.get('music_intensity') is not None]
    if len(gears) >= 3:
        res['gear_vs_music_intensity_spearman'] = _r(_spearman([g for g, _ in gears], [m for _, m in gears]), 3)
    return res


def _spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None

    def rank(x):
        order = np.argsort(x, kind='stable')
        r = np.empty(len(x))
        r[order] = np.arange(len(x))
        for v in np.unique(x):
            m = x == v
            r[m] = r[m].mean()
        return r
    return float(np.corrcoef(rank(a), rank(b))[0, 1])


# ---------------------------------------------------------------------------- SFX against impacts

def sfx_vs_impacts(sfx, motion_peaks, cuts, fps, words=None, given=None):
    """For each SFX onset: the nearest motion peak or cut within sync.sfx_window_frames (the impact it belongs to)
    and the offset sfx - impact in frames (negative: the sound comes first)."""
    win = float(th('sync.sfx_window_frames', given))
    ok = float(th('sync.sfx_match_frames', given))
    rows = []
    wspans = [(w['t0'] - 0.05, w['t1'] + 0.05) for w in words or []]
    for s in sfx:
        if s.get('kind') == 'sound_onset' and any(a <= s['t'] <= b for a, b in wspans):
            continue
        best = None
        for kind, evs in (('motion_peak', motion_peaks), ('cut', cuts)):
            for e in evs:
                d = s['f'] - e['f']
                if abs(d) <= win and (best is None or abs(d) < abs(best[1])):
                    best = (kind, d, e)
        row = {'f': s['f'], 't': s['t'], 'kind': s.get('kind'), 'id': s.get('id'), 'clip': s.get('clip')}
        if best:
            row.update(impact=best[0], impact_f=best[2]['f'], offset_frames=int(best[1]),
                       on_impact=abs(best[1]) <= ok)
        else:
            row.update(impact=None, offset_frames=None, on_impact=False)
        rows.append(row)
    res = {'n': len(rows), 'window_frames': win, 'match_frames': ok, 'onsets': rows[:60]}
    m = [r for r in rows if r.get('impact')]
    res['with_impact'] = len(m)
    if m:
        offs = np.asarray([r['offset_frames'] for r in m], float)
        res.update(share_on_impact=round(float(np.mean(np.abs(offs) <= ok)), 3),
                   median_offset_frames=round(float(np.median(offs)), 2),
                   share_sound_first=round(float(np.mean(offs < 0)), 3))
    return res
