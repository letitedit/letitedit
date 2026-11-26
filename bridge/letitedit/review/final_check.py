"""The final export against the preview that was reviewed: a short technical check of the final file (its length,
loudness and true peak, black or frozen stretches, sound and picture in step with the preview, the picture the same as
the preview's, a few full-size frames), written into the final's own review folder with the preview's review.

The review (the gate's measurements, the critic, the project's checks) ran on a preview the export engine drew smaller
with the final's sound. The final is rendered once from the same timeline; this check shows it is the video that was
reviewed: what differs is listed as a finding and sets the verdict.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

GRAY_W, GRAY_H = 64, 36         # the size both files are compared at: encoding and scaling differences vanish there
ENVELOPE_HZ = 100               # the sound's level, every 10 ms
PICTURE_LIMIT = 12.0            # mean difference (0-255) of the small grey pictures that counts as a different picture
PICTURE_HOLD_S = 0.5            # ... for at least this long
LOUDNESS_LIMIT_LU = 0.5         # the final's loudness may differ from the reviewed preview's this much
PEAK_SLACK_DB = 0.2             # true peak over the export's limit by more than this is a finding
SYNC_LIMIT_FRAMES = 1


def _ffmpeg():
    import letitedit.review.review_bundle as review_bundle
    return review_bundle._gate().FFMPEG


def _run(args, timeout=3600):
    import letitedit.core.render_lock as render_lock
    return render_lock.run_render([str(a) for a in args], what=f'final check: {Path(str(args[0])).stem}', heavy=True,
                                  capture_output=True, timeout=timeout,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def picture_signal(video, fps):
    """The video as small grey pictures at fps, plus its black and frozen stretches (ffmpeg blackdetect, freezedetect)."""
    import numpy as np
    r = _run([_ffmpeg(), '-v', 'info', '-nostats', '-i', video, '-an', '-vf',
              f'fps={fps},blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=2,scale={GRAY_W}:{GRAY_H},format=gray',
              '-f', 'rawvideo', '-'])
    frames = np.frombuffer(r.stdout, np.uint8)
    frames = frames[:len(frames) // (GRAY_W * GRAY_H) * GRAY_W * GRAY_H].reshape(-1, GRAY_H, GRAY_W)
    err = r.stderr.decode('utf-8', 'replace')
    import re
    black = [(float(a), float(b)) for a, b in re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', err)]
    starts = [float(x) for x in re.findall(r'freeze_start: ([\d.]+)', err)]
    ends = [float(x) for x in re.findall(r'freeze_end: ([\d.]+)', err)]
    frozen = [(s, ends[i] if i < len(ends) else None) for i, s in enumerate(starts)]
    return frames, black, frozen


def sound_signal(video):
    """The sound's level (RMS, mono) every 1/ENVELOPE_HZ s."""
    import numpy as np
    rate = 8000
    r = _run([_ffmpeg(), '-v', 'error', '-i', video, '-vn', '-ac', '1', '-ar', str(rate), '-f', 'f32le', '-'])
    samples = np.frombuffer(r.stdout, np.float32)
    step = rate // ENVELOPE_HZ
    samples = samples[:len(samples) // step * step].reshape(-1, step)
    return np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=1)) if len(samples) else np.zeros(0)


def best_lag(a, b, most):
    """The shift of b against a (in samples, -most..most) where the two line up best, and how well (correlation)."""
    import numpy as np
    n = min(len(a), len(b))
    if n < 8:
        return 0, None
    a, b = np.asarray(a[:n], float), np.asarray(b[:n], float)
    best = (0, -2.0)
    for lag in range(-most, most + 1):
        x, y = (a[lag:], b[:n - lag]) if lag >= 0 else (a[:n + lag], b[-lag:])
        if len(x) < 8 or x.std() == 0 or y.std() == 0:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if c > best[1]:
            best = (lag, c)
    return best[0], (round(best[1], 4) if best[1] > -2 else None)


def different_stretches(final, preview, fps):
    """Where the final's picture differs from the preview's for PICTURE_HOLD_S or more: [(start_s, end_s, mean diff)]."""
    import numpy as np
    n = min(len(final), len(preview))
    diff = np.abs(final[:n].astype(np.int16) - preview[:n].astype(np.int16)).mean(axis=(1, 2))
    out, start = [], None
    for i, d in enumerate(list(diff) + [0.0]):
        if d > PICTURE_LIMIT and start is None:
            start = i
        elif d <= PICTURE_LIMIT and start is not None:
            if (i - start) / fps >= PICTURE_HOLD_S:
                out.append((round(start / fps, 2), round(i / fps, 2), round(float(diff[start:i].mean()), 1)))
            start = None
    return out, (round(float(np.median(diff)), 2) if n else None)


def _new(stretches, known, slack=0.5):
    return [s for s in stretches if not any(abs(s[0] - k[0]) <= slack for k in known)]


def compare(final, preview, target_peak=-1.0):
    """Measure the final against the preview. Returns {'matches', 'problems': [{what, at_s}], 'measured': {...}}."""
    import letitedit.review.review_bundle as review_bundle
    gate = review_bundle._gate()
    fi, pi = gate.probe(Path(final)), gate.probe(Path(preview))
    fps = fi['fps'] or pi['fps'] or 30.0
    problems, measured = [], {'final': {k: fi[k] for k in ('duration', 'width', 'height', 'fps')},
                              'preview': {k: pi[k] for k in ('duration', 'width', 'height', 'fps')}}

    def problem(what, at=None):
        problems.append({'what': what, 'at_s': at})

    if abs(fi['duration'] - pi['duration']) > 1.5 / fps:
        problem(f"the final is {fi['duration']:.2f} s long and the reviewed preview {pi['duration']:.2f} s")
    if abs((fi['fps'] or 0) - (pi['fps'] or 0)) > .01:
        problem(f"the final runs at {fi['fps']:.3f} frames a second and the preview at {pi['fps']:.3f}")
    # loudness and true peak
    if fi['has_audio'] != pi['has_audio']:
        problem('the final ' + ('has' if fi['has_audio'] else 'has no') + ' sound and the preview '
                + ('has' if pi['has_audio'] else 'has none'))
    if fi['has_audio']:
        (fl, fp), (pl, pp) = gate.loudness(Path(final)), gate.loudness(Path(preview))
        measured['loudness'] = {'final_lufs': fl, 'final_true_peak_db': fp, 'preview_lufs': pl, 'preview_true_peak_db': pp}
        if fl is None or (pl is not None and abs(fl - pl) > LOUDNESS_LIMIT_LU):
            problem(f'the final is {fl} LUFS and the reviewed preview {pl} LUFS')
        if fp is not None and target_peak is not None and fp > target_peak + PEAK_SLACK_DB:
            problem(f'the final peaks at {fp} dBTP, over the {target_peak} dBTP limit')
    # picture: the same frames, black and frozen stretches only the final has
    ff, fblack, ffrozen = picture_signal(final, fps)
    pf, pblack, pfrozen = picture_signal(preview, fps)
    measured['frames'] = {'final': len(ff), 'preview': len(pf)}
    measured['black'] = {'final': fblack, 'preview': pblack}
    measured['frozen'] = {'final': ffrozen, 'preview': pfrozen}
    for s, e in _new(fblack, pblack):
        problem(f'black from {s:.1f} to {e:.1f} s in the final only', s)
    for s, e in _new(ffrozen, pfrozen):
        problem(f"the picture stands still from {s:.1f} s{f' to {e:.1f} s' if e else ' to the end'} in the final only", s)
    video_lag, video_corr = best_lag(_motion(ff), _motion(pf), max(2, round(fps / 2)))
    if video_lag:
        problem(f'the final\'s picture is {video_lag} frame(s) {"late" if video_lag > 0 else "early"} against the preview')
    else:
        stretches, median = different_stretches(ff, pf, fps)
        measured['picture_difference'] = {'median': median, 'stretches': stretches, 'limit': PICTURE_LIMIT}
        for s, e, d in stretches[:10]:
            problem(f'the picture from {s:.1f} to {e:.1f} s is not the one reviewed (difference {d})', s)
    # sound against picture: both line up with the preview by the same shift
    if fi['has_audio'] and pi['has_audio']:
        audio_lag, audio_corr = best_lag(sound_signal(final), sound_signal(preview), ENVELOPE_HZ // 2)
        measured['sync'] = {'picture_lag_frames': video_lag, 'picture_match': video_corr,
                            'sound_lag_ms': round(audio_lag * 1000 / ENVELOPE_HZ), 'sound_match': audio_corr}
        if abs(audio_lag / ENVELOPE_HZ - video_lag / fps) > SYNC_LIMIT_FRAMES / fps:
            problem(f'sound and picture are out of step by {round((audio_lag / ENVELOPE_HZ - video_lag / fps) * 1000)} ms '
                    'against the reviewed preview')
        if audio_corr is not None and audio_corr < .9:
            problem(f'the final\'s sound is not the one reviewed (its level follows the preview\'s at {audio_corr})')
    return {'matches': not problems, 'problems': problems, 'measured': measured}


def _motion(frames):
    import numpy as np
    if len(frames) < 2:
        return np.zeros(len(frames))
    return np.concatenate([[0.0], np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))])


def identity(video):
    import hashlib
    video = Path(video)
    return {'file': str(video), 'bytes': video.stat().st_size, 'modified': time.ctime(video.stat().st_mtime),
            'sha1_first_mb': hashlib.sha1(video.read_bytes()[:1 << 20]).hexdigest()}


def run(final, preview, project=None, out=None, target_peak=-1.0):
    """Check the final against the reviewed preview and write the final's review folder ('<final> review' by default):
    the preview's review with the final named as its video, this check's findings added, and full-size frames of the
    final. Returns that review's result (as review_bundle.bundle does), with 'final_check'."""
    import letitedit.review.review_bundle as review_bundle
    t0 = time.monotonic()
    final, preview = Path(final).resolve(), Path(preview).resolve()
    for path in (final, preview):
        if not path.is_file():
            raise FileNotFoundError(f'No video at {path}')
    reviewed = preview.parent / f'{preview.stem} review'
    if not (reviewed / 'review_bundle.json').is_file():
        raise FileNotFoundError(f'{preview.name} has no review: letitedit_review_bundle on the preview first '
                                f'(its review is in "{reviewed.name}")')
    out = Path(out) if out else final.parent / f'{final.stem} review'
    if out.resolve() != reviewed.resolve():
        shutil.copytree(reviewed, out, dirs_exist_ok=True)
    result = json.loads((reviewed / 'review_bundle.json').read_text(encoding='utf-8-sig'))
    check = compare(final, preview, target_peak)
    # by what the video is made of (T347): a move or a save of markers or notes after the preview is no change
    if project and Path(project).is_file() and review_bundle.export_freshness(project, preview)[0]:
        check['problems'].append({'what': 'the project changed after the preview was made: the final may not be the '
                                          'video that was reviewed', 'at_s': None})
        check['matches'] = False
    info = review_bundle._gate().probe(final)
    portrait = (info['height'] or 0) > (info['width'] or 0)
    duration = info['duration']
    moments = [(0.5, 'opening'), (duration / 2, 'middle'), (max(0.0, duration - 0.6), 'ending')]
    moments += [(f['at_s'], f"final: {f['what'][:40]}") for f in check['problems'] if f.get('at_s') is not None][:5]
    frames = review_bundle.detail_page(review_bundle._gate().FFMPEG, final, moments, out / 'final-frames.jpg', portrait)
    check['frames'] = frames
    check['seconds'] = round(time.monotonic() - t0, 1)
    (out / 'final-check.json').write_text(json.dumps(check, indent=1, default=str), encoding='utf-8')
    findings = [f for f in result.get('findings', []) if f.get('source') != 'final file']
    findings += [review_bundle._finding('final file', 'major', p['what'], p.get('at_s'), 'final-check.json',
                                        'export again from the reviewed timeline and check it again')
                 for p in check['problems']]
    result['findings'] = findings
    result['counts'] = {s: sum(1 for f in findings if f['severity'] == s) for s in review_bundle.SEVERITIES}
    result['coverage'] = [c for c in result.get('coverage', []) if c.get('check') != 'final file'] + [{
        'check': 'final file', 'state': 'done', 'required': True,
        'detail': ('the final matches the reviewed preview: ' if check['matches'] else 'the final differs from the '
                   'reviewed preview: ') + 'length, loudness and true peak, black and frozen stretches, sound and '
                   'picture in step, the same picture (compared small); full-size frames in final-frames.jpg'}]
    result['verdict'] = review_bundle.verdict(findings, result['coverage'])
    result['reviewed_preview'] = result.get('video')
    result['video'] = identity(final)
    result['size'] = f"{info['width']}x{info['height']}"
    result['final_check'] = check
    result['files'] = {**(result.get('files') or {}), 'final_frames': frames, 'final_check': str(out / 'final-check.json')}
    (out / 'review_bundle.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    (out / 'review.md').write_text(review_bundle.markdown(result), encoding='utf-8')
    result['report'] = str(out / 'review.md')
    return result
