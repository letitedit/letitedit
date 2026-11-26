"""Finish an exported video's sound the way letitedit_export does (render_queue.finish_audio): ONE measured, constant gain
to the loudness target, then a true-peak limiter, so the balance inside the mix (voice over music, quiet pauses,
a music swell) stays exactly as it was mixed. Nothing is compressed or levelled over time.

    python loudness_finish.py <video> [--target -14] [--true-peak -1] [--out <file>]
        measures the file's integrated loudness (EBU R128) and true peak, brings it to --target LUFS with plain gain and
        a limiter at (--true-peak - 1) dBTP on 4x oversampled audio (AAC raises peaks), joins the new sound to the
        untouched picture (video copied), measures the result and, while its true peak is over --true-peak, limits
        again lower (up to 4 tries). Replaces <video> (or writes --out). Prints a JSON report.
    python loudness_finish.py <video> --measure-only
        the measured loudness and true peak, nothing changed.

The app's Export runs it after the encode (under the PC render lock); the report's after.integrated_lufs is what the
export screen shows, so the number it reports is measured on the finished file, not promised by a setting.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = _paths.CODE_ROOT
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
THREADS = str(max(1, min(4, (os.cpu_count() or 2) - 1)))


def _tool(name):
    for d in (ROOT / 'app', Path(shutil.which(name) or '').parent):
        exe = Path(d) / (name + ('.exe' if os.name == 'nt' else ''))
        if exe.is_file():
            return str(exe)
    return name


FFMPEG, FFPROBE = _tool('ffmpeg'), _tool('ffprobe')


def _run(args):
    r = subprocess.run([FFMPEG, '-v', 'error', '-threads', THREADS, *map(str, args)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError('ffmpeg failed: ' + r.stderr[-800:])
    return r


def measure(path):
    """(integrated LUFS, true peak dBTP) of a file's sound; None for silence or no sound."""
    r = subprocess.run([FFMPEG, '-hide_banner', '-nostats', '-threads', THREADS, '-i', str(path), '-vn', '-af',
                        'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    summary = r.stderr[r.stderr.rfind('Summary:'):]

    def num(rx):
        m = re.search(rx, summary)
        return float(m.group(1)) if m and m.group(1) not in ('-inf', 'nan') else None
    return num(r'I:\s+(-?[\d.]+|-inf|nan) LUFS'), num(r'Peak:\s+(-?[\d.]+|-inf|nan) dBFS')


def _audio_info(path):
    r = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                        'stream=bit_rate,sample_rate,channels', '-of', 'json', str(path)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    try:
        streams = json.loads(r.stdout or '{}').get('streams') or []
    except ValueError:
        streams = []
    return streams[0] if streams else None


def _limited(wav, out, gain, ceiling):
    limit = 10 ** (ceiling / 20)
    _run(['-y', '-i', wav, '-af', f'volume={gain:.2f}dB,aresample=192000,alimiter=limit={limit:.4f}:attack=5:release=80:'
          'level=false:latency=true,aresample=48000', '-c:a', 'pcm_f32le', out])


def finish(video, target=-14.0, true_peak=-1.0, out=None):
    video = Path(video)
    before_lufs, before_peak = measure(video)
    report = {'file': str(video), 'target_lufs': target, 'true_peak_max': true_peak,
              'before': {'integrated_lufs': before_lufs, 'true_peak_dbtp': before_peak}}
    info = _audio_info(video)
    if info is None or before_lufs is None:
        report.update(changed=False, after=report['before'], note='no sound to adjust: the file is left as it is')
        return report
    work = Path(tempfile.mkdtemp(prefix='letitedit-sound-'))
    try:
        wav = work / 'mix.wav'
        _run(['-y', '-i', video, '-vn', '-c:a', 'pcm_f32le', wav])      # the mix as encoded, decoded once
        gain = target - before_lufs
        ceiling = (true_peak if true_peak is not None else -1.0) - 1.0
        finished = work / 'finished.wav'
        joined = work / ('joined' + video.suffix)
        bitrate = int(info.get('bit_rate') or 0)
        abr = f'{max(192, min(512, round(bitrate / 1000) or 320))}k'
        tries = []
        for _ in range(4):
            # gain first; the limiter takes a little level, so the gain is corrected once or twice
            for _ in range(3):
                _limited(wav, finished, gain, ceiling)
                lufs, _ = measure(finished)
                if lufs is None or abs(target - lufs) <= 0.4 or gain > 24:
                    break
                gain += target - lufs
            _run(['-y', '-i', video, '-i', finished, '-map', '0', '-map', '-0:a', '-map', '1:a:0', '-c', 'copy',
                  '-c:a', 'aac', '-b:a', abr, '-ar', str(info.get('sample_rate') or 48000), '-map_metadata', '0',
                  '-map_chapters', '0', '-movflags', '+faststart', joined])
            lufs, peak = measure(joined)
            tries.append({'gain_db': round(gain, 2), 'limiter_dbtp': round(ceiling, 2), 'lufs': lufs,
                          'true_peak_dbtp': peak})
            if true_peak is None or peak is None or peak <= true_peak:
                break
            ceiling -= (peak - true_peak) + 0.3
        dest = Path(out) if out else video
        tmp = dest.with_name(dest.stem + '.finishing' + dest.suffix)
        shutil.copyfile(joined, tmp)
        os.replace(tmp, dest)
        report.update(changed=True, out=str(dest), gain_db=round(gain, 2), tries=tries,
                      after={'integrated_lufs': tries[-1]['lufs'], 'true_peak_dbtp': tries[-1]['true_peak_dbtp']},
                      peak_passed=true_peak is None or tries[-1]['true_peak_dbtp'] is None
                      or tries[-1]['true_peak_dbtp'] <= true_peak)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _main(argv):
    if not argv or argv[0].startswith('-'):
        raise SystemExit(__doc__)

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default
    video = argv[0]
    if not Path(video).is_file():
        raise SystemExit(f'no such file: {video}')
    if '--measure-only' in argv:
        lufs, peak = measure(video)
        return {'file': video, 'changed': False, 'after': {'integrated_lufs': lufs, 'true_peak_dbtp': peak}}
    tp = opt('--true-peak', '-1')
    return finish(video, float(opt('--target', '-14')), None if str(tp).lower() == 'off' else float(tp), opt('--out'))


if __name__ == '__main__':
    print(json.dumps(_main(sys.argv[1:]), ensure_ascii=False, indent=1))
