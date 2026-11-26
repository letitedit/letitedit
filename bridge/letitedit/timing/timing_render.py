"""Preview renders of a project's timeline for the timing layer: what the viewer gets, at a small size, with sound,
on the timeline's own frame grid. Made by melt (the export engine) in chunks cached by content, so a small edit
re-renders only the chunks it touched.

    preview(project, timeline=None, f0=0, f1=None, px=640, refresh=False, chunk_s=None, parallel=None) -> info
    use_existing(project, video, timeline, rng) -> info for an existing full render of the project
    chunks_of(info) -> [{f0, f1, file, offset, key}] the pieces an analysis can cache per chunk

info: {video (joined preview .mp4: H.264 + AAC), audio (joined .wav, 48 kHz 16-bit stereo, sample-exact),
size [w, h], fps, frames, f0, f1, fingerprint, chunks: [{f0, f1, video, audio, vfp, afp, reused}], chunks_total,
chunks_reused, chunks_rendered, seconds, lock_wait_s, warnings, method}.

How: the range is split into pieces of about chunk_s seconds with boundaries snapped to main-track cuts
(render_queue._plan_chunks), so inserting or deleting upstream shifts whole chunks instead of changing them. A
chunk's picture is cached under timeline.range_fingerprint(a, b, video=True) (everything that can change its
pixels, relative to its start) + the preview settings; its sound under range_fingerprint(a, b, video=True,
audio=True). Pictures: x264 ultrafast, keyframe every 30 frames, at the profile's frame rate and the preview size
(melt renders the timeline at that size: filters with sizes in pixels scale with it). Sound: PCM. Chunks render
PARALLEL at a time; when more than 30 s of timeline must be rendered the PC render lock is held (render_lock.slot).
Every chunk's frame count is checked; the joined preview must have exactly the range's frames.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import math
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
MELT, FFMPEG, FFPROBE = APP / 'melt.exe', APP / 'ffmpeg.exe', APP / 'ffprobe.exe'
CACHE_ROOT = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
CHUNKS = CACHE_ROOT / 'timing' / 'chunks'
PREVIEWS = CACHE_ROOT / 'timing' / 'previews'
AUDIO = CACHE_ROOT / 'timing' / 'audio'
NO_WINDOW = 0x08000000
RENDER_VERSION = 1          # bump when the chunk encoding changes (part of every chunk's name)
LOCK_OVER_S = 30.0          # renders of more timeline than this hold the PC render lock
CHUNK_S = 20.0
# one melt at a time by default: the PC hard-crashed twice under combined render load (28 Oct); raise with care
PARALLEL = int(os.environ.get('LETITEDIT_TIMING_RENDER_PARALLEL', 1))
THREADS = int(os.environ.get('LETITEDIT_TIMING_RENDER_THREADS', 4))
_LOCKS = {}
_GLOBAL = threading.Lock()


def _even(x):
    return max(16, int(round(x / 2.0)) * 2)


def preview_size(profile, px):
    """(w, h) with the long side px (even numbers), keeping the profile's display shape."""
    w, h = int(profile['width']), int(profile['height'])
    s = float(px) / max(w, h)
    if s >= 1.0:
        return _even(w), _even(h)
    return _even(w * s), _even(h * s)


def _run(args, timeout):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, cwd=str(APP))
    if r.returncode != 0:
        raise RuntimeError(f'{Path(str(args[0])).name} failed ({r.returncode}): {(r.stderr or r.stdout)[-1200:]}')
    return r


def _melt(args, seconds):
    """melt with a timeout scaled to the length; melt has hung at start on this PC (no CPU used): tried twice."""
    timeout = max(180.0, 12.0 * seconds + 60.0)
    last = None
    for _ in (1, 2):
        try:
            return _run([MELT, '-quiet', *args], timeout)
        except subprocess.TimeoutExpired as e:
            last = e
    raise RuntimeError(f'melt timed out twice ({timeout:.0f} s): {last}')


def count_frames(path):
    """Video packets of a file (x264 ultrafast has no B-frames: packets = frames)."""
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                        'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                       creationflags=NO_WINDOW)
    try:
        return int((r.stdout or '0').strip().split(',')[0] or 0)
    except ValueError:
        return 0


def _wav_frames(path):
    import soundfile
    info = soundfile.info(str(path))
    return info.frames, info.samplerate, info.channels


def fsync(path):
    """Flush a written file to disk (a crash right after a rename must not leave an empty or torn file)."""
    try:
        with open(path, 'rb+') as fh:
            os.fsync(fh.fileno())
    except OSError:
        pass


_OK = {}


def video_ok(path, frames):
    """A cached picture file that reads back with exactly `frames` frames (checked once per file version)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (str(path), st.st_size, st.st_mtime_ns, int(frames))
    if key not in _OK:
        _OK[key] = st.st_size > 0 and count_frames(path) == int(frames)
    return _OK[key]


def audio_ok(path, seconds):
    """A cached WAV that reads back (its header and last samples) with about `seconds` of sound."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (str(path), st.st_size, st.st_mtime_ns, round(float(seconds), 3))
    if key not in _OK:
        try:
            import soundfile
            n, sr, ch = _wav_frames(path)
            soundfile.read(str(path), start=max(0, n - 4800), dtype='int16')
            _OK[key] = abs(n - seconds * sr) <= sr / 20.0
        except Exception:  # noqa: BLE001
            _OK[key] = False
    return _OK[key]


def _atomic(part, final):
    fsync(part)
    for _ in range(30):
        try:
            os.replace(part, final)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(part, final)


def _plan(timeline, f0, f1, chunk_s):
    import letitedit.timeline.render_queue as render_queue
    return render_queue._plan_chunks(timeline, f0, f1 - 1, chunk_s)


def _tag(px, size, fps_num, fps_den):
    return f'{RENDER_VERSION}-{size[0]}x{size[1]}-{fps_num}-{fps_den}'


def preview(project, timeline=None, f0=0, f1=None, px=640, refresh=False, chunk_s=None, parallel=None,
            lock_timeout_s=3600.0):
    """The project's timeline [f0, f1) rendered small with sound (see the module doc). Returns info."""
    import letitedit.timeline.timeline_model as tm
    t_start = time.time()
    project = Path(project)
    timeline = timeline or tm.load(project)
    F = int(timeline.frames)
    f1 = F if f1 is None else min(F, int(f1))
    f0 = max(0, int(f0))
    if f1 <= f0:
        raise ValueError(f'empty range {f0}-{f1} of a {F}-frame timeline')
    prof = timeline.profile
    fps = float(timeline.fps)
    size = preview_size(prof, px)
    tag = _tag(px, size, prof['frame_rate_num'], prof['frame_rate_den'])
    plan = _plan(timeline, f0, f1, float(chunk_s or CHUNK_S))
    CHUNKS.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    chunks = []
    for a, b in plan:
        vfp = timeline.range_fingerprint(a, b, video=True, audio=False)
        afp = timeline.range_fingerprint(a, b, video=True, audio=True)
        v = CHUNKS / f'v-{vfp}-{tag}.mp4'
        w = CHUNKS / f'a-{afp}-{RENDER_VERSION}-{prof["frame_rate_num"]}-{prof["frame_rate_den"]}-48k.wav'
        chunks.append({'f0': a, 'f1': b, 'vfp': vfp, 'afp': afp, 'video': str(v), 'audio': str(w),
                       'reused_video': not refresh and video_ok(v, b - a),
                       'reused_audio': not refresh and audio_ok(w, (b - a) / fps)})
    whole = hashlib.sha1(json.dumps([[c['vfp'], c['afp'], c['f1'] - c['f0']] for c in chunks] + [tag]).encode()
                         ).hexdigest()[:20]
    out_mp4 = PREVIEWS / f'{whole}.mp4'
    out_wav = PREVIEWS / f'{whole}.wav'
    warnings = []
    with _GLOBAL:
        lk = _LOCKS.setdefault(whole, threading.Lock())
    lock_wait = 0.0
    with lk:
        todo = [(c, 'video') for c in chunks if not c['reused_video']] + \
               [(c, 'audio') for c in chunks if not c['reused_audio']]
        if todo:
            todo_s = sum((c['f1'] - c['f0']) / fps for c, k in todo if k == 'video')
            import contextlib
            import letitedit.core.render_lock as render_lock
            lock = contextlib.nullcontext()
            if todo_s > LOCK_OVER_S:
                lock = render_lock.slot(f'letitedit timing preview {project.name} ({todo_s:.0f} s)',
                                        timeout_s=lock_timeout_s, poll_s=5, caller_pids=render_lock.ancestors())
            t_lock = time.time()
            with lock:
                lock_wait = time.time() - t_lock
                n_par = max(1, int(parallel or PARALLEL))
                errors = []

                def work(job):
                    c, kind = job
                    try:
                        if kind == 'video':
                            _render_video_chunk(project, c, size, prof, fps)
                        else:
                            _render_audio_chunk(project, c, fps)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f'chunk {c["f0"]}-{c["f1"]} {kind}: {e}')
                # longest first keeps the pool busy
                todo.sort(key=lambda j: -(j[0]['f1'] - j[0]['f0']) * (3 if j[1] == 'video' else 1))
                with ThreadPoolExecutor(n_par) as ex:
                    list(ex.map(work, todo))
                if errors:
                    raise RuntimeError('preview render failed: ' + ' | '.join(errors[:4]))
        if refresh or todo or not (video_ok(out_mp4, f1 - f0) and audio_ok(out_wav, (f1 - f0) / fps)):
            _join(chunks, out_mp4, out_wav, size, fps, f1 - f0)
        for c in chunks:
            for k in ('video', 'audio'):
                try:
                    os.utime(c[k])
                except OSError:
                    pass
    n_reused = sum(1 for c in chunks if c['reused_video'])
    info = {'video': str(out_mp4), 'audio': str(out_wav), 'size': list(size), 'fps': fps, 'frames': f1 - f0,
            'f0': f0, 'f1': f1, 'fingerprint': whole, 'px': px,
            'chunks': [{'f0': c['f0'], 'f1': c['f1'], 'video': c['video'], 'audio': c['audio'], 'vfp': c['vfp'],
                        'afp': c['afp'], 'reused': c['reused_video'], 'audio_reused': c['reused_audio']}
                       for c in chunks],
            'chunks_total': len(chunks), 'chunks_reused': n_reused, 'chunks_rendered': len(chunks) - n_reused,
            'audio_chunks_rendered': sum(1 for c in chunks if not c['reused_audio']),
            'seconds': round(time.time() - t_start, 2), 'lock_wait_s': round(lock_wait, 1), 'warnings': warnings,
            'method': f'melt (the export engine) at {size[0]}x{size[1]}, {fps:g} fps, in {len(chunks)} cached chunks'}
    if f0 > 0 or f1 < F:
        info['note'] = f'frames {f0}-{f1} of {F}: preview frame i is timeline frame {f0} + i'
    _prune()
    return info


def _render_video_chunk(project, c, size, prof, fps):
    a, b = c['f0'], c['f1']
    final = Path(c['video'])
    part = final.with_name(final.stem + f'.{uuid.uuid4().hex[:6]}.partial.mp4')
    w, h = size
    args = [str(project), f'in={a}', f'out={b - 1}', '-consumer', f'avformat:{part}', 'vcodec=libx264', 'crf=23',
            'preset=ultrafast', 'g=30', 'pix_fmt=yuv420p', 'an=1', 'audio_off=1', f'width={w}', f'height={h}',
            f'progressive={prof.get("progressive", "1")}', f'frame_rate_num={prof["frame_rate_num"]}',
            f'frame_rate_den={prof["frame_rate_den"]}', 'sample_aspect_num=1', 'sample_aspect_den=1',
            f'display_aspect_num={w}', f'display_aspect_den={h}', 'real_time=-1', f'threads={THREADS}']
    try:
        _melt(args, (b - a) / fps)
        got = count_frames(part)
        if got != b - a:
            raise RuntimeError(f'chunk {a}-{b} has {got} frames, expected {b - a}')
        _atomic(part, final)
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def _render_audio_chunk(project, c, fps):
    a, b = c['f0'], c['f1']
    final = Path(c['audio'])
    part = final.with_name(final.stem + f'.{uuid.uuid4().hex[:6]}.partial.wav')
    args = [str(project), f'in={a}', f'out={b - 1}', '-consumer', f'avformat:{part}', 'vn=1', 'video_off=1',
            'acodec=pcm_s16le', 'ar=48000', 'channels=2', 'real_time=-1']
    try:
        _melt(args, (b - a) / fps * 0.3)
        n, sr, ch = _wav_frames(part)
        want = (b - a) / fps * 48000.0
        if abs(n - want) > 48000.0 / fps:
            raise RuntimeError(f'audio chunk {a}-{b} has {n} samples, expected about {want:.0f}')
        _atomic(part, final)
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def _join(chunks, out_mp4, out_wav, size, fps, nframes):
    """Join the chunks: picture by stream copy, sound sample by sample, then one MP4 with AAC sound."""
    import numpy as np
    import soundfile
    tmpd = out_mp4.parent / f'join-{uuid.uuid4().hex[:8]}'
    tmpd.mkdir(parents=True, exist_ok=True)
    try:
        lst = tmpd / 'list.txt'
        lst.write_text(''.join("file '" + c['video'].replace('\\', '/') + "'\n" for c in chunks), encoding='utf-8')
        vid = tmpd / 'video.mp4'
        _run([FFMPEG, '-v', 'error', '-y', '-threads', '4', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', vid], 600)
        got = count_frames(vid)
        if got != nframes:
            raise RuntimeError(f'joined preview has {got} frames, expected {nframes}')
        wav_part = tmpd / 'audio.wav'
        with soundfile.SoundFile(str(wav_part), 'w', samplerate=48000, channels=2, subtype='PCM_16') as out:
            for c in chunks:
                y, sr = soundfile.read(c['audio'], dtype='int16', always_2d=True)
                if y.shape[1] == 1:
                    y = np.repeat(y, 2, axis=1)
                out.write(y[:, :2])
        mp4_part = tmpd / 'preview.mp4'
        _run([FFMPEG, '-v', 'error', '-y', '-threads', '4', '-i', vid, '-i', wav_part, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
              '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', mp4_part], 600)
        _atomic(wav_part, out_wav)
        _atomic(mp4_part, out_mp4)
    finally:
        for p in sorted(tmpd.glob('*'), reverse=True):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmpd.rmdir()
        except OSError:
            pass


def extract_audio(video, start_s=None, dur_s=None):
    """The sound of a video file as 48 kHz 16-bit stereo WAV, cached by content (+ range). None without sound."""
    import letitedit.footage.shots as shots
    ck = shots.content_key(str(video))
    tag = '' if start_s is None and dur_s is None else f'-{float(start_s or 0):.3f}-{float(dur_s or 0):.3f}'
    AUDIO.mkdir(parents=True, exist_ok=True)
    out = AUDIO / f'{ck}{tag}-48k.wav'
    if out.exists():
        return str(out)
    r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                        '-of', 'csv=p=0', str(video)], capture_output=True, text=True, creationflags=NO_WINDOW)
    if not (r.stdout or '').strip():
        return None
    part = out.with_name(out.stem + f'.{uuid.uuid4().hex[:6]}.partial.wav')
    args = [FFMPEG, '-v', 'error', '-y', '-threads', '4']
    if start_s:
        args += ['-ss', f'{float(start_s):.4f}']
    args += ['-i', str(video)]
    if dur_s:
        args += ['-t', f'{float(dur_s):.4f}']
    args += ['-vn', '-sn', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(part)]
    try:
        _run(args, 1800)
        _atomic(part, out)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    return str(out)


def use_existing(project, video, timeline, rng):
    """Analyse an existing full render of the project (e.g. its export) instead of a preview render: it must have
    the timeline's frame rate and frame count (+-1) and its shape."""
    import letitedit.footage.shots as shots
    video = str(Path(video).resolve())
    info = shots.probe(video)
    fps = float(timeline.fps)
    warnings = []
    if abs(float(info['fps']) - fps) > 0.01:
        raise ValueError(f'{video} runs at {info["fps"]:.3f} fps, the project at {fps:.3f}: not a render of it')
    n = count_frames(video)
    if abs(n - int(timeline.frames)) > 1:
        raise ValueError(f'{video} has {n} frames, the project {timeline.frames}: not a render of this revision')
    pw, ph = timeline.profile['width'], timeline.profile['height']
    if abs(info['w'] / info['h'] - pw / ph) > 0.02:
        raise ValueError(f'{video} is {info["w"]}x{info["h"]}, the project {pw}x{ph}')
    if n != int(timeline.frames):
        warnings.append(f'the render has {n} frames, the timeline {timeline.frames}')
    warnings.append('analysing an existing render: that it matches the current project revision is checked only by '
                    'frame rate, frame count and shape')
    ck = shots.content_key(video)
    audio = extract_audio(video)
    return {'video': video, 'audio': audio, 'size': [int(info['w']), int(info['h'])], 'fps': fps,
            'frames': int(timeline.frames), 'f0': 0, 'f1': int(timeline.frames), 'fingerprint': ck,
            'existing': True, 'existing_key': ck,
            'chunks': [{'f0': 0, 'f1': min(n, int(timeline.frames)), 'video': video, 'audio': audio, 'vfp': ck,
                        'afp': ck, 'reused': True}],
            'chunks_total': 1, 'chunks_reused': 1, 'chunks_rendered': 0, 'seconds': 0.0, 'lock_wait_s': 0.0,
            'warnings': warnings, 'method': 'an existing render of the project (settings store.video)'}


def chunks_of(ctx):
    """The pieces of the analysed source an analysis can cache per piece: [{f0, f1, file, offset, key, start_s}]
    (file frame `offset` is source frame f0). A project preview: its render chunks; a video: the file (or the
    analysed range of it)."""
    r = ctx.get('render')
    F = int(ctx['frames'])
    fps = float(ctx['fps'])
    if r and r.get('chunks'):
        base = int(r.get('f0', 0))
        out = []
        for c in r['chunks']:
            if r.get('existing'):
                out.append({'f0': c['f0'], 'f1': c['f1'], 'file': c['video'], 'offset': c['f0'], 'key': c['vfp'],
                            'start_s': None})
            else:
                out.append({'f0': c['f0'], 'f1': c['f1'], 'file': c['video'], 'offset': 0, 'key': c['vfp'],
                            'start_s': None})
        if base and not r.get('existing'):
            pass
        return out
    f0, f1 = ctx.get('range') or (0, F)
    key = (ctx.get('source_fingerprint') or {}).get(str(ctx['video'])) or Path(ctx['video']).name
    if f0 == 0 and f1 >= F:
        return [{'f0': 0, 'f1': F, 'file': ctx['video'], 'offset': 0, 'key': key, 'start_s': None}]
    return [{'f0': f0, 'f1': f1, 'file': ctx['video'], 'offset': f0, 'key': f'{key}-{f0}-{f1}',
             'start_s': f0 / fps}]


def _prune(limit_gb=6.0):
    """Keep the chunk and preview caches under limit_gb (least recently used go first)."""
    try:
        files = [p for d in (CHUNKS, PREVIEWS) if d.exists() for p in d.iterdir() if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        if total < limit_gb * 1e9:
            return
        for p in sorted(files, key=lambda p: p.stat().st_mtime):
            if total < 0.8 * limit_gb * 1e9:
                break
            try:
                sz = p.stat().st_size
                p.unlink()
                total -= sz
            except OSError:
                pass
    except OSError:
        pass
