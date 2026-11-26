"""Chunked, cached, resumable exports that survive crashes, reboots and closed AI sessions.

How it works
  * The project is snapshotted when the export is queued, so later edits don't change a running export.
  * Video is rendered by melt in chunks (about a minute each, snapped to cuts). Each chunk is cached under a
    fingerprint of everything that can change its pixels, so a fix re-renders only the chunks it touched,
    and a dead render resumes from the last finished chunk.
  * Audio is rendered once for the whole range (no seams), then muxed with the joined video without re-encoding.
  * The worker runs detached from any console or AI session and honours the PC-wide one-render-at-a-time lock.

CLI (used by the detached worker):  python render_queue.py run <job_id>
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import letitedit.timeline.timeline_model as tm  # noqa: E402
import letitedit.core.render_lock as render_lock  # noqa: E402  the PC-wide render lock (shared with agents' own renders)
import letitedit.core.memory_room as memory_room  # noqa: E402  idle model helpers give their memory back first
import letitedit.core.font_env as font_env  # noqa: E402

font_env.ensure()  # melt loads the font library itself (LETITEDIT_FONT_DIRS), whatever Windows loaded at sign-in

APP = Path((_SAI_ROOT + '\\app'))
MELT = APP / 'melt.exe'
FFMPEG = APP / 'ffmpeg.exe'
FFPROBE = APP / 'ffprobe.exe'
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
JOBS = CACHE / 'exports'
CHUNKS = CACHE / 'chunks'
LOCK = render_lock.LOCK
LOCK_WAIT_S = float(os.environ.get('LETITEDIT_RENDER_LOCK_WAIT_S', render_lock.DEFAULT_TIMEOUT_S))
THREADS = os.environ.get('LETITEDIT_RENDER_THREADS', '4')
# T80: real_time=-1 draws one frame at a time; -2 draws two, byte-identical on a real project and 27% faster (-4 and -8 no
# faster: a serial stage, most likely the blend, sets the pace)
RENDER_RT = os.environ.get('LETITEDIT_RENDER_RT', '-2')
HOLD_S = render_lock.DEFAULT_HOLD_S    # an export offers the render lock to a waiting job after this many seconds (LETITEDIT_HOLD_S)
# melt renders one frame at a time per process, so several chunk renders side by side use the CPU far better.
# T241 (17 Nov: "at least 10 of the 16" threads): up to a third of the PC's threads in renders at once, 5 on 16
# threads (was a quarter, 4), as many as the memory free to promise holds (memory_slots). Pair B's 30 s 1080x1920 final:
# 2 at once 173 s (8 threads busy on average), 3 166 s, 4 151 s (10 threads), 5 145 s (11 threads; the PC 14 of 16).
PARALLEL = int(os.environ.get('LETITEDIT_RENDER_PARALLEL', max(1, (os.cpu_count() or 4) // 3)))
# How long an export's chunks are planned to be (auto_chunk_s) stays as before, for a quarter of the threads: the chunk
# boundaries, and so the chunk cache, are those of earlier exports.
PLAN_SLOTS = max(1, (os.cpu_count() or 4) // 4)
# T80: each melt of a 1080x1920 60 fps project with a scene and cut-out pieces peaked at 3.3 to 3.8 GB of memory; four at once made
# 9.3 GB of working set and 18.2 GB of committed memory (one chunk: 3.8 and 8.2). A PC with less memory free than that renders fewer chunks at once
PER_MELT_GB = 3.5
RESERVE_GB = 3.0        # left for Windows, the editor and the AI's own tools
# T238: Windows refuses memory past its commit limit (RAM plus the page file, less what every program has been promised),
# however much RAM is free, and the engine and x264 crash when refused (exit 0xC0000005, "malloc ... failed"). One chunk's
# melt of a 1080p 60 fps project with 68 clips committed 4.1-4.2 GB (1.9 GB of it in RAM); its 960x540 preview 3.5 GB:
# most of it is the clips' decoders, so it hardly depends on the picture size.
# T239b: with the engine settings below (memory_room.ENGINE_ENV, PICTURE_ENGINE_ENV for the picture chunks) the chunks
# of two such projects committed 2.1-3.0 GB at full size and 1.3-2.0 GB as a preview, the sound 1.2-1.7 GB. How many
# chunks render at once still counts 4.5 GB each.
PER_MELT_COMMIT_GB = memory_room.RENDER_GB      # 4.5: a render whose size isn't known
RESERVE_COMMIT_GB = memory_room.RESERVE_GB      # 1.5
# T241: the export counts each of its engine renders at what one was measured to commit with those settings, the
# heaviest of each kind (T239b and T241: two 60 fps projects of 61 and 68 clips, one to five renders at once): a picture
# chunk 2.11 GB at 540x960 (0.52 million pixels) and 2.99 GB at 1080x1920 (2.07 million), a line through the two (1.82
# GB and 0.566 GB per million pixels drawn) plus a margin; the sound's render 2.64 GB plus the margin. So a 1080p chunk
# counts 3.24 GB, a preview's 2.36 GB, a 4K chunk 6.76 GB, the sound 2.89 GB: never under what one was measured to
# commit. Five full-size renders at once peaked at 10.5 GB together, four at 8.9 GB, three at 7.4 GB.
CHUNK_BASE_GB = 1.8167
CHUNK_PER_MPX_GB = 0.5659
CHUNK_MARGIN_GB = 0.25
SOUND_RENDER_GB = 2.64 + CHUNK_MARGIN_GB


def chunk_commit_gb(width, height):
    """About what one picture chunk's engine render commits, drawn at width x height (T239b's measurements, with a
    margin)."""
    return round(CHUNK_BASE_GB + CHUNK_PER_MPX_GB * max(0, int(width)) * max(0, int(height)) / 1e6 + CHUNK_MARGIN_GB,
                 2)


def export_render_gb(spec, profile):
    """What each of an export's picture chunks is counted at, drawn at the preview's size or the project's. A size
    that can't be read: PER_MELT_COMMIT_GB."""
    try:
        size = (spec.get('preview') or {}).get('size') or (profile['width'], profile['height'])
        width, height = (int(v) for v in size)
    except (TypeError, ValueError, KeyError):
        return PER_MELT_COMMIT_GB
    if width <= 0 or height <= 0:
        return PER_MELT_COMMIT_GB
    return chunk_commit_gb(width, height)
# A chunk that ran out of memory is drawn again on its own once the others are done, after waiting at most this long for
# that much commit to be free (another program's model, say, closing on its idle timer).
MEMORY_WAIT_S = float(os.environ.get('LETITEDIT_RENDER_MEMORY_WAIT_S', '900'))
MEMORY_POLL_S = 5.0
MEMORY_TRIES = 2        # one-at-a-time tries per chunk after it first ran out
OUT_OF_MEMORY = re.compile(r'out of memory|cannot allocate memory|cannot allocate [\w ]*buffer|memory allocation|'
                           r'malloc of size \d+ failed|bad_alloc|'
                           r'error with video encode: -12\b|failed with -12\b', re.I)
STATUS_NO_MEMORY = (3221225495, -1073741801)     # 0xC0000017
ACCESS_VIOLATION = (3221225477, -1073741819)     # 0xC0000005: how the engine ends when an allocation is refused
# T238 (6): an engine render that stops making frames (no new frame, next to no CPU: seen on an upright 60 fps HEVC
# phone clip, two chunks started in the same second as the sound) is stopped after this long, and drawn again on its own
# once the others are done; stalled again, the export fails saying so. One frame never takes minutes, even at full size.
STALL_S = float(os.environ.get('LETITEDIT_RENDER_STALL_S', '300'))
STALL_TRIES = 1         # one-at-a-time tries for a piece that stalled
FRAME = re.compile(r'Current Frame:\s*(\d+)')


class Stalled(RuntimeError):
    """An engine render the watchdog stopped: no new frame for STALL_S."""


def memory_gb():
    """(physical memory free, commit free) now, in GB (memory_room.memory_gb); (None, None) where it can't be read."""
    return memory_room.memory_gb()


def available_gb():
    """Physical memory free now, in GB (Windows); None where it can't be read."""
    return memory_gb()[0]


def memory_slots(available=None, commit=None, render_gb=None, first_gb=None):
    """How many renders may run at once: PARALLEL, fewer when the free memory or the free commit can't hold that many
    melts (one at least). Read from the PC when neither is given. render_gb: what each render is counted at
    (export_render_gb; unknown: PER_MELT_GB of memory and PER_MELT_COMMIT_GB of commit); first_gb: one of them counted
    at this instead (the sound's render, SOUND_RENDER_GB, when it is drawn beside the chunks). LETITEDIT_RENDER_PARALLEL
    set by hand is taken as it is."""
    if 'LETITEDIT_RENDER_PARALLEL' in os.environ:
        return PARALLEL
    if available is None and commit is None:
        available, commit = memory_gb()

    def fit(free, reserve, each):
        if first_gb is None:
            return int((free - reserve) // each)
        return 0 if free - reserve < first_gb else 1 + int((free - reserve - first_gb) // each)
    slots = PARALLEL
    if available is not None:
        slots = min(slots, fit(available, RESERVE_GB, render_gb or PER_MELT_GB))
    if commit is not None:
        slots = min(slots, fit(commit, RESERVE_COMMIT_GB, render_gb or PER_MELT_COMMIT_GB))
    return max(1, slots)


def out_of_memory(error, commit_free=None):
    """True when a render's failure was the PC refusing it memory: the engine's own words, Windows' "no memory" exit, or
    its crash exit while less commit than one chunk needs is free."""
    text = str(error)
    if OUT_OF_MEMORY.search(text):
        return True
    m = re.match(r'melt exited (-?\d+)', text)
    rc = int(m.group(1)) if m else None
    if rc in STATUS_NO_MEMORY:
        return True
    return rc in ACCESS_VIOLATION and commit_free is not None and commit_free < PER_MELT_COMMIT_GB + RESERVE_COMMIT_GB
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

VIDEO_PRESETS = {
    'social_h264': ['vcodec=libx264', 'crf=20', 'preset=medium', 'pix_fmt=yuv420p'],
    # T80: x264 'slow' held a 252-frame chunk of a real project at 30.3 s against 19.1 s for 'medium' (the picture
    # graph alone: about 13 s); same crf, 47.3 dB between the two encodes, the same file size
    'high_quality_h264': ['vcodec=libx264', 'crf=16', 'preset=medium', 'pix_fmt=yuv420p'],
    # T80: Turbo ("sacrifices quality for speed"): the encoder stops being the slow part (14 s of the same 13 s graph)
    'turbo_h264': ['vcodec=libx264', 'crf=20', 'preset=veryfast', 'pix_fmt=yuv420p'],
    'draft_h264': ['vcodec=libx264', 'crf=28', 'preset=veryfast', 'pix_fmt=yuv420p'],
    # a preview to review before the final render: the engine draws it at PREVIEW_SHORT_SIDE (submit(preview=True)), a
    # fast encode; the sound is the final's (bitrate and loudness finishing), so the measured mix is the real one
    'preview_h264': ['vcodec=libx264', 'crf=24', 'preset=veryfast', 'pix_fmt=yuv420p'],
}
AUDIO_BITRATE = {'social_h264': '192k', 'high_quality_h264': '320k', 'draft_h264': '128k', 'turbo_h264': '192k',
                 'preview_h264': '320k'}
PREVIEW_SHORT_SIDE = 540        # the critic's contact pages are 160-256 px wide; small detail is checked full size
PREVIEW_SUFFIX = ' preview'


PREVIEW_PROFILE_VERSION = 2   # in the preview chunks' cache key: version 1 had the engine's default frame rate and pixel shape


def preview_args(profile, size):
    """The consumer settings that draw the project smaller: its size, and the rest of its profile. With only a width
    and height the engine falls back to its default profile for the rest: 25 fps and 16:15 pixels (a 30 fps preview
    of 1080x1920 came out at 25 fps with the picture squeezed)."""
    args = [f'width={size[0]}', f'height={size[1]}',
            f"frame_rate_num={profile['frame_rate_num']}", f"frame_rate_den={profile['frame_rate_den']}",
            f"sample_aspect_num={profile.get('sample_aspect_num') or 1}",
            f"sample_aspect_den={profile.get('sample_aspect_den') or 1}",
            f"progressive={profile.get('progressive') or 1}", f"colorspace={profile.get('colorspace') or 709}"]
    if profile.get('display_aspect_num') and profile.get('display_aspect_den'):
        args += [f"display_aspect_num={profile['display_aspect_num']}", f"display_aspect_den={profile['display_aspect_den']}"]
    return args


def preview_size(width, height, short_side=PREVIEW_SHORT_SIDE):
    """The preview's size: the shorter side at short_side (never larger than the project), even numbers."""
    scale = min(1.0, short_side / max(1, min(width, height)))
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)
BUFSIZE_FACTOR = 2.0   # x264 rate buffer = this x the bitrate cap


def _kbps(v):
    return None if v is None else float(str(v).lower().rstrip('k'))


def encode_settings(preset, timeline=None, platform=None, video_bitrate_kbps=None, max_video_bitrate_kbps=None,
                    audio_bitrate_kbps=None, sample_rate_hz=None):
    """The encoder settings of an export: {'video_args' (melt avformat properties), 'audio_bitrate', 'sample_rate',
    'key' (part of the chunk cache key), 'platform' (the platform's published values, which of them were applied and
    how the project compares) or None}.
    Applied from a platform profile (platforms.preset_for), unless the argument is given: a bitrate the platform
    publishes as a maximum -> max_video_bitrate_kbps (crf kept, rate capped); an audio bitrate published as a minimum
    -> the preset's or that, whichever is higher; its sample rate. Other published values (a recommended video
    bitrate, an audio bitrate without a kind, size, frame rate, length, loudness) are reported, not applied.
    video_bitrate_kbps: a target bitrate (replaces crf; capped at the same rate). max_video_bitrate_kbps: crf with
    the rate capped there. Buffer: BUFSIZE_FACTOR x the cap."""
    vargs = list(VIDEO_PRESETS[preset])
    abr = _kbps(audio_bitrate_kbps)
    rate = int(sample_rate_hz) if sample_rate_hz else None
    vmax = _kbps(max_video_bitrate_kbps)
    vtarget = _kbps(video_bitrate_kbps)
    plat = None
    if platform:
        import letitedit.catalogs.platforms as platforms
        p = platforms.preset_for(platform)
        notes = {k: (p['sources'].get(k) or {}).get('note') or '' for k in p['sources']}
        applied, reported = {}, {}
        vb = p.get('video_bitrate_kbps')
        if vb:
            if 'maximum' in notes.get('video_bitrate_kbps', '').lower():
                if vmax is None and vtarget is None:
                    vmax = float(vb)
                    applied['max_video_bitrate_kbps'] = vb
            else:
                reported['video_bitrate_kbps'] = {'value': vb, 'note': notes.get('video_bitrate_kbps') or None}
                if p.get('video_bitrate_kbps_high_fps'):
                    reported['video_bitrate_kbps_high_fps'] = p['video_bitrate_kbps_high_fps']
        ab = p.get('audio_bitrate_kbps')
        if ab and abr is None:
            if 'minimum' in notes.get('audio_bitrate_kbps', '').lower():
                abr = max(float(ab), _kbps(AUDIO_BITRATE[preset]))
                applied['audio_bitrate_kbps'] = abr
            else:
                reported['audio_bitrate_kbps'] = {'value': ab, 'note': notes.get('audio_bitrate_kbps') or None}
        if p.get('sample_rate_hz') and rate is None:
            rate = int(p['sample_rate_hz'])
            applied['sample_rate_hz'] = rate
        if p.get('loudness_lufs') is not None:
            reported['loudness_lufs'] = {'value': p['loudness_lufs'],
                                         'status': p['sources'].get('loudness_lufs', {}).get('status')}
        compare = {}
        if timeline is not None:
            pw, ph = timeline.profile['width'], timeline.profile['height']
            compare['size'] = {'project': f'{pw}x{ph}', 'platform': p['size'],
                               'same': (pw, ph) == (p.get('width'), p.get('height'))}
            compare['fps'] = {'project': round(timeline.fps, 3), 'platform': p.get('fps')}
            if p.get('max_length_s'):
                compare['length_s'] = {'project': round(timeline.seconds, 2), 'platform_max': p['max_length_s'],
                                       'within': timeline.seconds <= p['max_length_s']}
        plat = {'platform': p['platform'], 'name': p['name'], 'checked': p['checked'], 'applied': applied,
                'reported': reported, 'compare': compare, 'unconfirmed': p['unconfirmed'],
                'not_documented': p['not_documented']}
    if vtarget is not None:
        vargs = [a for a in vargs if not a.startswith('crf=')]
        cap = vmax if vmax is not None else vtarget
        vargs += [f'vb={vtarget:g}k', f'maxrate={cap:g}k', f'bufsize={cap * BUFSIZE_FACTOR:g}k']
    elif vmax is not None:
        vargs += [f'maxrate={vmax:g}k', f'bufsize={vmax * BUFSIZE_FACTOR:g}k']
    extra = [a for a in vargs if a not in VIDEO_PRESETS[preset]] + [a for a in VIDEO_PRESETS[preset] if a not in vargs]
    key = preset + ('-' + '-'.join(sorted(extra)).replace('=', '') if extra else '')
    return {'video_args': vargs, 'audio_bitrate': f'{abr:g}k' if abr is not None else AUDIO_BITRATE[preset],
            'sample_rate': rate, 'key': key, 'platform': plat}


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _write(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + f'.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a reader has it open on Windows; retry
            time.sleep(0.1)
    os.replace(tmp, path)


def _pid_alive(pid):
    """False only when the process is known to be gone (render_lock.pid_state): one that can't be read counts as
    running, so its export is never resumed beside it."""
    return render_lock.pid_alive(pid)


# ---------------------------------------------------------------------------- submit

def _project_path(project):
    path = Path(project)
    if path.is_dir():
        from letitedit.timeline import episodes as p
        root, data = p.load(path)
        if not data.get('timeline'):
            raise ValueError('This episode/cut has no timeline yet')
        return p.owned(root, data['timeline']), root
    if not path.is_file():
        if str(project).strip().lower() in ('live', 'current', 'editor'):
            raise FileNotFoundError(f"project '{project}' is for the tools that read or check the open window; export "
                                    "takes the project's .mlt path, and letitedit_editor gives it")
        import letitedit.core.long_paths as long_paths
        long_paths.check(path)          # there, perhaps, but under a path too long to open
        raise FileNotFoundError(f'No project at {path}; letitedit_project_new makes one')
    return path, None


def _default_output(project_path, episode_root, name):
    if episode_root is not None:
        folder = episode_root / '06 Exports'
    else:
        folder = project_path.parent
    stem = re.sub(r'[\\/:*?"<>|]+', '-', name or project_path.stem)
    return folder / f'{stem}.mp4'


def _files_beside(out, job_id):
    """The longest files an export to `out` writes there: the finished file, its copy on the way in, and its review's."""
    out = Path(out)
    return (out, out.with_name(out.stem + '.' + job_id + '.partial.mp4'),
            out.with_name(out.stem + ' review') / 'review-memory-for-critic.txt')


def _keep_older_version(out):
    """The plain name is always the newest export: an earlier file of that name, with its review folder, moves to the
    next free '<stem> (2)', '<stem> (3)'... Returns (the older file's new path or None, the path to write). If the old
    file can't move (a player has it open), this export takes the free name instead, so nothing is lost."""
    out = Path(out)
    if not out.exists():
        return None, out
    k = 2
    while (older := out.with_name(f'{out.stem} ({k}){out.suffix}')).exists():
        k += 1
    try:
        os.replace(out, older)
    except OSError:
        return None, older
    review = out.with_name(out.stem + ' review')
    if review.is_dir():
        try:
            os.replace(review, older.with_name(older.stem + ' review'))
        except OSError:
            pass
    return older, out


def _concat_list(chunks, fps):
    """The ffmpeg concat list for the finished chunks, each with its exact length in frames over fps. A chunk's mp4 stores
    its length rounded to a whole millisecond, so a chunk that isn't a whole number of milliseconds long (260 frames at
    30 fps is 8666.67 ms) pulled every chunk after it up to 0.7 ms early, and the joined file's average frame rate read
    30.0014 instead of 30 (T180). The list's `duration` lines place each chunk where its frames put it; the boundaries
    are rounded to the microsecond from the running total, so nothing builds up over many chunks."""
    lines, done, at = [], 0, 0
    for c in chunks:
        done += c['b'] - c['a']
        end = round(done / fps * 1_000_000)
        lines.append("file '" + c['file'].replace('\\', '/') + "'\n" + f'duration {(end - at) / 1_000_000:.6f}\n')
        at = end
    return ''.join(lines)


def _plan_chunks(timeline, first, last, chunk_s):
    """Split [first, last] into chunks of about chunk_s seconds, snapping each boundary to a nearby V1 cut so a
    later insert/delete upstream shifts whole chunks instead of changing all of them."""
    target = max(1, round(chunk_s * timeline.fps))
    cuts = [c for c in timeline.cut_points() if first < c <= last]
    bounds, a = [], first
    while last + 1 - a > target * 1.5:
        ideal = a + target
        near = [c for c in cuts if a + target * 0.6 <= c <= a + target * 1.4]
        b = min(near, key=lambda c: abs(c - ideal)) if near else ideal
        bounds.append((a, b))
        a = b
    bounds.append((a, last + 1))
    return bounds


def _loudness_target(path, loudness):
    """Integrated loudness to finish at: explicit value, else the project's Look (export.loudness), else -14
    (YouTube and most platforms turn louder videos down, but don't turn quieter ones up). None or 'off' keeps the mix."""
    if loudness in ('off', 'none', 'keep'):
        return None
    if loudness is not None:
        return float(loudness)
    try:
        import letitedit.timeline.edit_script as es
        return float(es.kit_for(es.read(path))['export'].get('loudness', -14.0))
    except Exception:  # noqa: BLE001
        return -14.0


def _true_peak(true_peak):
    """Highest true peak (dBTP) the encoded sound may reach; 'off' (or None) leaves the peaks as they are."""
    if true_peak is None or str(true_peak).lower() in ('off', 'none', 'keep'):
        return None
    return float(true_peak)


def _credits(snapshot):
    """The credit lines the exported video owes for library assets it uses (assets.project_credits): [] when none,
    None when they could not be worked out (a listing, never a reason to stop an export)."""
    try:
        import letitedit.catalogs.assets as assets
        return assets.project_credits(snapshot)
    except Exception:  # noqa: BLE001
        return None


def _credit_fields(credits):
    if not credits:
        return {}
    return {'credits': credits,
            'credits_note': "This video uses library assets that owe a credit line: tell the person and put these "
                            "lines in the video's description (YouTube, TikTok, Instagram...). A line that says no credit is "
                            "required is only there to record where something came from."}


def _mix_unmeasured(path, source, start_s, end_s):
    """The sound signature (checks.audio_signature) of a whole-video export whose cut letitedit_check_audio has not
    measured as a whole, so the export measures its mix from its own sound render; None when it has (or for a range)."""
    if start_s is not None or end_s is not None or not str(path).lower().endswith('.mlt'):
        return None
    try:
        import letitedit.review.checks as checks
        import letitedit.timeline.project_journal as project_journal
        signature = checks.audio_signature(source)
        whole = [e for e in project_journal.entries(path, limit=None) if e.get('kind') == 'sound_check'
                 and not e.get('range')]
        return None if whole and whole[-1].get('audio') == signature else signature
    except Exception:  # noqa: BLE001 - no measurement then; the review says so
        return None


def measure_mix(spec, wav):
    """The mix measured on the exported cut (checks.audio, speech against music when there is a Music track), the
    mix pass taken from the export's own sound render (before its loudness finish), recorded in the project's journal
    as letitedit_check_audio records it. Only when spec['measure_mix'] is set and the project still has that sound."""
    signature = spec.get('measure_mix')
    if not signature:
        return None
    try:
        import letitedit.review.checks as checks
        import letitedit.timeline.project_journal as project_journal
        project = spec['project']
        # the signature was taken from what the export renders (an open window's timeline, unsaved changes
        # included): compared with the project as that window shows it now, never with an older saved file
        with checks.as_window_shows(project):
            now = checks.audio_signature(project)
        if now != signature:
            return {'skipped': 'the project changed since this export was queued: '
                               'letitedit_check_audio measures the cut as it is now'}
        png, report = checks.audio(project, mix_wav=wav)
        checks.audio_keep(project, signature, png, report)
        project_journal.record(project, 'sound_check', text=f"integrated {report.get('integrated_lufs')} LUFS",
                               audio=signature, via='export')
        keep = ('integrated_lufs', 'true_peak_dbfs', 'music_below_voice_while_talking_lu',
                'music_level_without_talking_lufs', 'quiet_stretches', 'clips_far_from_typical_level', 'findings',
                'graph', 'seconds')
        return {'note': 'the mix of this cut, measured from the export\'s own sound before its loudness finish '
                        '(what letitedit_check_audio gives; it now returns this without a new render)',
                **{k: report[k] for k in keep if k in report}}
    except Exception as exc:  # noqa: BLE001 - a measurement that can't run is no reason to fail the export
        return {'error': f'{type(exc).__name__}: {exc}'[:300]}


def auto_chunk_s(timeline, first, last):
    """T80: chunks sized so all PLAN_SLOTS slots work (T241: the slots of before, so the chunks stay those of earlier
    exports; up to PARALLEL of them render at once): a video under a minute used to be ONE chunk, so one melt drew it
    while the other slots sat idle (a 20 s range: 108 s as one chunk against 87 s as four, x264 slow). Never over 60 s,
    never under 8 s (each chunk starts its own melt). The length is one of fixed steps (CHUNK_STEPS), the largest that
    still fills every slot: worked out from the video's length directly, a fix that trimmed a few frames moved every
    chunk boundary after it, so no later chunk matched its cached render and a small fix re-rendered most of the video."""
    seconds = (last + 1 - first) / max(1.0, timeline.fps)
    share = seconds / max(1, PLAN_SLOTS)
    return max([step for step in CHUNK_STEPS if step <= share] or [CHUNK_STEPS[0]])


CHUNK_STEPS = (8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0)


def submit(project, output=None, preset='high_quality_h264', chunk_s=None, start_s=None, end_s=None, name=None, qc=False,
           loudness=None, overwrite=False, true_peak=-1.0, platform=None, video_bitrate_kbps=None,
           max_video_bitrate_kbps=None, audio_bitrate_kbps=None, sample_rate_hz=None, preview=False):
    named = bool(output or name)          # the caller chose the file's name
    if preset in ('preview', 'preview_h264'):   # the preview's encode alone at full size would be neither
        preview = True
    if preview:
        preset = 'preview_h264'
    if preset not in VIDEO_PRESETS:
        raise ValueError(f'preset must be one of {sorted(VIDEO_PRESETS)}')
    path, episode_root = _project_path(project)
    # An open editor may have native Undo steps that are not saved yet. Export
    # its live snapshot, including the scene revision currently on its track.
    import letitedit.server.timeline_tools as timeline_tools
    live = timeline_tools._live_state(path)
    source = Path(__import__('letitedit.app.live_edit', fromlist=["*"]).snapshot(live['instance_id'])[0]) if live else path
    import letitedit.timeline.export_checks as export_checks
    try:
        preexport = export_checks.run(path, source)
    except Exception as error:
        preexport = export_checks.unavailable_result(error)
    # T72: a song the person adds when posting is never in an export, whatever its track's mute button says
    import letitedit.sound.guide_song as guide_song
    stripped = guide_song.strip_file(source)
    song_left_out = None
    if stripped:
        source, song_left_out = stripped
        if not output and not name:
            name = path.stem + guide_song.UPLOAD_SUFFIX
    timeline = tm.load(source)
    enc = encode_settings(preset, timeline, platform=platform, video_bitrate_kbps=video_bitrate_kbps,
                          max_video_bitrate_kbps=max_video_bitrate_kbps, audio_bitrate_kbps=audio_bitrate_kbps,
                          sample_rate_hz=sample_rate_hz)
    size = None
    if preview:
        size = preview_size(timeline.profile['width'], timeline.profile['height'])
        enc['video_args'] = list(enc['video_args']) + preview_args(timeline.profile, size)
        enc['key'] = enc['key'] + f'-{size[0]}x{size[1]}-p{PREVIEW_PROFILE_VERSION}'
        if not named:          # '<project> preview', or the upload's name (no song) with ' preview'
            name = (name or path.stem) + PREVIEW_SUFFIX
    first = 0 if start_s is None else max(0, round(start_s * timeline.fps))
    last = timeline.frames - 1 if end_s is None else min(timeline.frames - 1, round(end_s * timeline.fps) - 1)
    if last < first:
        raise ValueError('Empty export range')
    if not chunk_s:
        chunk_s = auto_chunk_s(timeline, first, last)
    job_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    job_dir = JOBS / job_id
    job_dir.mkdir(parents=True)
    # Snapshot: later edits don't affect this export; relative media still resolve against the original folder.
    tree = ET.parse(source)
    tree.getroot().set('root', str(path.resolve().parent))
    snapshot = job_dir / 'snapshot.mlt'
    tree.write(snapshot, encoding='utf-8', xml_declaration=True)
    if stripped:
        source.unlink(missing_ok=True)
    out = Path(output) if output else _default_output(path, episode_root, name)
    if output and out.exists() and not overwrite:
        raise FileExistsError(f'{out} already exists; choose another name, or overwrite=True to replace it when the '
                              'new render is finished')
    import letitedit.core.cache_budget as cache_budget
    need = cache_budget.export_need((last - first + 1) / timeline.fps)
    try:
        import letitedit.core.long_paths as long_paths
        long_paths.check(*_files_beside(out, job_id))
        # short of room, the export says at once how much to free (no wait: nothing of the job's own is running yet)
        cache_budget.need_room(CHUNKS, need, 'export this video', cache=CACHE, wait_s=0)   # the chunks and the joined file
        cache_budget.need_room(out, need // 2, 'export this video', wait_s=0)              # the finished file, if on another drive
    except OSError:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    spec = {'job_id': job_id, 'project': str(path), 'snapshot': str(snapshot), 'output': str(out), 'preset': preset,
            'preexport_checks': preexport,
            **({'measure_mix': mix_unmeasured} if (mix_unmeasured := _mix_unmeasured(path, source, start_s, end_s)) else {}),
            'auto_named': not output,
            'chunk_s': chunk_s, 'first': first, 'last': last, 'fps': timeline.fps, 'qc': qc, 'created': now(),
            'loudness': _loudness_target(path, loudness), 'true_peak': _true_peak(true_peak),
            'caller_pids': _ancestors(), 'encode': enc, 'credits': _credits(snapshot),
            **({'preview': {'size': list(size), 'full_size': [timeline.profile['width'], timeline.profile['height']]}}
               if preview else {}),
            **({'song_left_out': song_left_out} if song_left_out else {}),
            **({'env': {k: os.environ[k] for k in WORKER_TEST_ENV if k in os.environ}}
               if os.environ.get('LETITEDIT_QA_WORKER_ENV') else {}),
            'hold_s': HOLD_S}      # the worker is started by WMI and does not inherit this process's environment
    _write(job_dir / 'spec.json', spec)
    import letitedit.looks.project_look as project_look         # which exact timeline this export is made from (a Look can be learned from any version)
    project_look.note_export(path, out, snapshot, job_id=job_id, preview=preview)
    _write(job_dir / 'status.json', {'state': 'queued', 'message': 'Queued', 'progress': 0, 'updated': now()})
    launch(job_id)
    st = status(job_id)
    try:
        text = LOCK.read_text(errors='replace').strip()
        written = time.strftime('%H:%M:%S', time.localtime(LOCK.stat().st_mtime))
    except OSError:
        text = None
    try:        # renders already waiting for the lock go first (first come, first served); not this job's own ticket
        ahead = [w for w in render_lock.info(LOCK).get('queue') or [] if w.get('job_id') != job_id]
    except Exception:  # noqa: BLE001
        ahead = []
    line = (f' {len(ahead)} other render(s) already wait for it and go first (first come, first served).'
            if ahead else '')
    if text is not None and text.startswith('letitedit export'):
        st['note'] = f'Another letitedit export holds the PC render lock ({text[:80]}); this one starts after it.' + line
    elif text is not None and not lock_held_by(text, spec['caller_pids']):
        st['note'] = (f'The PC render lock {LOCK} exists ("{text[:80]}", written {written}), so this export waits for '
                      'it and starts by itself when it is free. A lock whose owner has gone clears by itself. (python '
                      'render_lock.py run --name <name> -- <command> runs a render of your own under this lock and '
                      'releases it when the command ends.)' + line)
    elif ahead:
        st['note'] = (f'{len(ahead)} render(s) wait for the PC render lock {LOCK}; this export starts after them '
                      '(first come, first served).')
    if enc['platform']:
        st['platform'] = enc['platform']
    if enc['key'] != preset:
        st['encode'] = {'video': enc['video_args'], 'audio_bitrate': enc['audio_bitrate'],
                        'sample_rate': enc['sample_rate']}
    return st


# T76: a sandbox test (LETITEDIT_QA_WORKER_ENV) hands its own home folders to the worker, which WMI would start with the real ones
WORKER_TEST_ENV = ('USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP', 'LETITEDIT_MOTION_BROWSER')


def launch(job_id):
    """Start the worker outside this process tree (WMI), so closing the AI session or a console Ctrl+C can't kill it."""
    pyw = Path(sys.executable).with_name('pythonw.exe')
    exe = pyw if pyw.exists() else Path(sys.executable)
    # The broker first (out of this process's jobs and tree, with the user's own environment; the worker uses this
    # cache), breakaway after; never started inside a job it would die with.
    return render_lock.start_independent([str(exe), str(_paths.BRIDGE / 'render_queue.py'), 'run', job_id, str(CACHE), _SAI_ROOT],
                                         cwd=str(_paths.BRIDGE), creationflags=DETACHED | render_lock.background_flags(),
                                         broker_first=True, inherit=False)


# ---------------------------------------------------------------------------- status / control

def status(job_id):
    job_dir = JOBS / job_id
    spec = _read(job_dir / 'spec.json')
    if spec is None:
        raise KeyError(f'Unknown export job {job_id}')
    st = _read(job_dir / 'status.json', {}) or {}
    if st.get('state') in ('rendering', 'waiting', 'waiting_space', 'joining', 'audio', 'checking') and not _pid_alive(st.get('pid')):
        st['state'] = 'interrupted'
        st['message'] = 'The export worker stopped (PC restart or crash). Resume it: finished chunks are reused.'
    chunks = st.get('chunks', [])
    done = sum(1 for c in chunks if c.get('state') == 'done')
    return {'job_id': job_id, 'state': st.get('state'), 'message': st.get('message'), 'progress': st.get('progress', 0),
            'chunks_done': done, 'chunks_total': len(chunks), 'chunks_reused': sum(1 for c in chunks if c.get('reused')),
            'output': (st.get('result') or {}).get('output') or spec['output'], 'project': spec['project'], 'updated': st.get('updated'),
            'result': st.get('result'), 'error': st.get('error'),
            'preexport_checks': spec.get('preexport_checks'),
            **({'measures_mix': 'letitedit_check_audio has not measured this cut as a whole, so the export measures its '
                                'mix (result.mix_check)'} if spec.get('measure_mix') else {}),
            **({'platform': (spec.get('encode') or {}).get('platform')} if (spec.get('encode') or {}).get('platform') else {}),
            **({'scenes_left_out': st['scenes_left_out']} if st.get('scenes_left_out') else {}),
            **({'redrawn_alone': st['redrawn_alone']} if st.get('redrawn_alone') else {}),
            **_credit_fields(spec.get('credits'))}


def resume(job_id):
    st = status(job_id)
    if st['state'] in ('rendering', 'waiting', 'waiting_space', 'joining', 'audio', 'checking'):
        return {**st, 'note': 'Already running'}
    if st['state'] == 'done':
        return {**st, 'note': 'Already finished'}
    (JOBS / job_id / 'cancel').unlink(missing_ok=True)
    launch(job_id)
    time.sleep(1.5)
    return status(job_id)


def cancel(job_id):
    (JOBS / job_id / 'cancel').write_text(now(), encoding='utf-8')
    return {'job_id': job_id, 'note': 'Cancel requested; the worker stops after killing the current melt run.'}


def list_jobs(limit=20):
    out = []
    for d in sorted(JOBS.glob('*'), reverse=True)[:limit]:
        try:
            out.append(status(d.name))
        except KeyError:
            continue
    return out


# the lock rules live in render_lock.py; these names stay for older callers and tests
_ancestors = render_lock.ancestors
lock_held_by = render_lock.lock_held_by
lock_is_stale = render_lock.lock_is_stale


ACTIVE_JOB_STALE_S = 7 * 86400


def active_job_files(jobs_dir=None, now_s=None):
    """The cache files (chunks and the sound) of every export that has not finished: the ones running, waiting for the
    PC lock or paused to let another job through. Another job's cleanup must leave them alone."""
    jobs_dir = Path(jobs_dir or JOBS)
    now_s = time.time() if now_s is None else now_s
    files = set()
    if not jobs_dir.exists():
        return files
    for d in jobs_dir.iterdir():
        sp = d / 'status.json'
        try:
            st = json.loads(sp.read_text(encoding='utf-8-sig'))
            if now_s - sp.stat().st_mtime > ACTIVE_JOB_STALE_S and not _pid_alive(st.get('pid')):
                continue
        except (OSError, ValueError):
            continue
        if st.get('state') in ('done', 'failed', 'cancelled'):
            continue
        files.update(str(c['file']) for c in st.get('chunks') or [] if c.get('file'))
        import letitedit.timeline.chunk_cache as chunk_cache
        files.update(str(chunk_cache.receipt_path(c['file'])) for c in st.get('chunks') or [] if c.get('file'))
        if st.get('audio_file'):
            files.add(str(st['audio_file']))
    return files


def prune_cache(keep=(), limit_gb=None, cache=None):
    """Keep the chunk cache under a size limit by deleting the least recently used files, never a file an unfinished
    export (this one or another) still needs."""
    chunks_dir = Path(cache) / 'chunks' if cache is not None else CHUNKS
    jobs_dir = Path(cache) / 'exports' if cache is not None else JOBS
    limit = float(limit_gb if limit_gb is not None else os.environ.get('LETITEDIT_RENDER_CACHE_GB', '4')) * 1024 ** 3
    shrink = limit_gb is None               # T95: on a small drive, a share of the room, as the other work folders
    if not chunks_dir.exists():
        return 0
    keep = set(keep) | active_job_files(jobs_dir)
    files = [f for f in chunks_dir.iterdir() if f.is_file() and not f.is_symlink()
             and '.partial.' not in f.name and str(f) not in keep]
    sizes = {f: f.stat().st_size for f in files}
    total = sum(sizes.values()) + sum(os.path.getsize(k) for k in keep if os.path.exists(k))
    if shrink:
        import letitedit.core.cache_budget as cache_budget
        limit = cache_budget.budget(chunks_dir, total, limit / cache_budget.GB)
    removed = 0
    for f in sorted(files, key=lambda f: f.stat().st_mtime):
        if total <= limit:
            break
        try:
            f.unlink()
            total -= sizes[f]
            removed += 1
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------------------- worker

def clean_leftovers(cache):
    """Remove job-owned intermediates only for terminal or abandoned, non-running exports."""
    root = Path(cache)
    removed = 0
    for folder in (root / 'exports').glob('*'):
        if not folder.is_dir() or folder.is_symlink() or getattr(folder.stat(), 'st_file_attributes', 0) & 0x400:
            continue
        data = _read(folder / 'status.json', {}) or {}
        if _pid_alive(data.get('pid')):
            continue
        try:
            age = time.time() - max((path.stat().st_mtime for path in folder.iterdir()), default=folder.stat().st_mtime)
        except OSError:
            continue
        if data.get('state') not in ('done', 'failed', 'cancelled') and age < ACTIVE_JOB_STALE_S:
            continue
        paths = [folder / name for name in ('concat.txt', 'export.partial.mp4', 'audio-limited.wav', 'audio-finished.wav')]
        paths.extend((root / 'chunks').glob('*.' + folder.name + '.partial.*'))
        for path in paths:
            try:
                if path.is_file() and not path.is_symlink() and not getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
    return removed


def _prepare_render(self, spec, cache_budget):
    """Wait for storage and the render lock, then prepare code scenes in the snapshot."""
    need = cache_budget.export_need((spec['last'] - spec['first'] + 1) / spec['fps'])
    self.wait_for_space(CHUNKS, need)
    self.wait_for_space(spec['output'], need // 2)
    self.update(state='waiting', message='Waiting for the render lock')
    self.acquire_lock()
    self._held_since = time.monotonic()
    self._pauses, self._paused_s = 0, 0.0
    # The transparent timeline clip is a live-player marker. Replace
    # it with the exact full alpha render in this immutable snapshot.
    import letitedit.pictures.code_scenes as code_scenes
    # the lock is ours: say so (the state used to stay 'waiting' while the scenes were drawn, minutes long)
    self.update(state='rendering', message='Preparing the export')
    import letitedit.pictures.motion as motion
    motion.cancel_check = self.cancelled      # Stop ends the scene's drawing and its browser, not only melt
    scenes = code_scenes.prepare_export(
        spec['snapshot'], spec['project'],
        progress=lambda i, n, scene: self.update(state='rendering',
                                                 message=f'Drawing code scene {i} of {n} at full quality'),
        note=lambda text: (self.say(text), self.update(state='rendering', message=text)),
        left_out=lambda text: (self.say(text), self.update(state='rendering', message=text, scenes_left_out=text)))
    if scenes:
        self.say('full code scene renders:', scenes)


def _prepare_cached_chunks(self, timeline, first, last, enc, spec, plan, chunk_cache, renderer):
    """Plan reusable picture chunks and the float-audio cache before pruning other entries."""
    chunks = []
    for i, (a, b) in enumerate(plan):
        fp = timeline.range_fingerprint(a, b, video=True, audio=False) + '-' + (enc.get('key') or spec['preset'])
        f = CHUNKS / f'{fp}.mp4'
        validation = {'fingerprint': fp, 'renderer': renderer, 'frames': b - a}
        reusable = chunk_cache.reusable(f, validation)
        chunks.append({'i': i, 'a': a, 'b': b, 'fp': fp, 'file': str(f),
                       'candidate': not reusable and chunk_cache.candidate(f, validation),
                       'validation': validation, 'state': 'done' if reusable else 'pending', 'reused': reusable})
    CHUNKS.mkdir(parents=True, exist_ok=True)
    total = last + 1 - first
    afp = timeline.range_fingerprint(first, last + 1, video=True, audio=True)
    wav = CHUNKS / f'audio-{afp}-f32.wav'   # float: a mix that sums past full scale isn't clipped here
    keep = {c['file'] for c in chunks} | {str(wav)}
    keep.update(str(chunk_cache.receipt_path(c['file'])) for c in chunks)
    self.update(audio_file=str(wav), chunks=chunks)   # other jobs' cache cleanup reads these
    for f in keep:
        if os.path.exists(f):
            os.utime(f)  # mark as recently used
    prune_cache(keep)
    return chunks, total, wav


def _render_one_chunk(self, c, pct, report, sizes, sample_references, timeline, spec, vargs, chunk_cache):
    """Render or validate one picture chunk and update its progress and receipt."""
    part = Path(c['file']).with_suffix('.' + self.job_id + '.partial.mp4')
    self._temporary.add(part)
    def cb(p, i=c['i']):
        pct[i] = p
        report()
    frames = sizes[c['i']]
    if c['candidate']:
        references = sample_references[c['i']]
        try:
            try:
                c['picture_check'] = chunk_cache.compare_samples(c['file'], references)
            except RuntimeError:
                # a sample the seek drew differently from the played chunk (the end of a clip's picture,
                # T180) is drawn again as the chunk is played; a wrong picture fails that too
                references, redrawn = chunk_cache.played_references(self, timeline, c, references, c['file'])
                if not redrawn:
                    raise
                self.say('chunk', c['i'], 'samples', redrawn, 'redrawn by playing the frames before them')
                c['picture_check'] = chunk_cache.compare_samples(c['file'], references)
                c['picture_check']['played_samples'] = redrawn
            c['reused'] = True
        except RuntimeError as error:
            self.say('chunk validation failed; retrying serially:', c['i'], error)
            self.melt([spec['snapshot'], f'in={c["a"]}', f'out={c["b"] - 1}', '-consumer',
                       f'avformat:{part}', *vargs, 'an=1', 'audio_off=1', 'real_time=-1', f'threads={THREADS}'],
                      env=memory_room.PICTURE_ENGINE_ENV)
            if self.count_frames(part) != frames:
                raise RuntimeError(f'Chunk {c["i"]} has the wrong frame count, expected {frames}')
            c['picture_check'] = chunk_cache.compare_samples(part, references)
            os.replace(part, c['file'])
        chunk_cache.record(c['file'], c['validation'])
    else:
        # the picture alone (no sound): the picture renders' settings, the same frames with less memory
        self.melt([spec['snapshot'], f'in={c["a"]}', f'out={c["b"] - 1}', '-consumer', f'avformat:{part}', *vargs,
                   'an=1', 'audio_off=1', f'real_time={RENDER_RT}', f'threads={THREADS}'], cb,
                  env=memory_room.PICTURE_ENGINE_ENV)
        if self.count_frames(part) != frames:
            raise RuntimeError(f'Chunk {c["i"]} has the wrong frame count, expected {frames}')
        os.replace(part, c['file'])
        chunk_cache.record(c['file'], c['validation'], verified=False)
    with self._lock:
        c['state'] = 'done'
        pct[c['i']] = 100
    report()


def _render_audio_track(self, wav, audio_pct, report, spec, first, last):
    """Render the continuous float-audio track and update its progress."""
    part = wav.with_suffix('.' + self.job_id + '.partial.wav')
    self._temporary.add(part)
    def cb(p):
        audio_pct[0] = p
        report()
    # Worker.melt's shared settings only: the sound keeps the clips' picture cache (turned off, it changed the sound)
    self.melt([spec['snapshot'], f'in={first}', f'out={last}', '-consumer', f'avformat:{part}', 'vn=1', 'video_off=1',
               'acodec=pcm_f32le', 'ar=48000', 'channels=2', 'real_time=-1'], cb)
    os.replace(part, wav)
    audio_pct[0] = 100
    report()


def _enter_render_slot(self, cv, gate, cache_budget):
    """Enter a chunk slot, yielding the render lock for storage or waiting jobs when needed."""
    with cv:
        while gate['paused']:
            cv.wait()
            if self.st.get('aborting'):
                raise RuntimeError('Cancelled')
        free, _ = cache_budget._free(CHUNKS)
        if free is None or free < cache_budget.reserve_bytes() + cache_budget.CHUNK_ROOM_BYTES:
            gate['paused'] = True
            try:
                while gate['inflight']:
                    cv.wait()
                self.release_lock()
                self.wait_for_space(CHUNKS, cache_budget.CHUNK_ROOM_BYTES)
                self.acquire_lock()
                self._held_since = time.monotonic()
            finally:
                gate['paused'] = False
                cv.notify_all()
        h = getattr(self, '_lock_holder', None)
        if (h is not None and h.owned and time.monotonic() - self._held_since >= float(self.spec.get('hold_s', HOLD_S))
                and render_lock.info(LOCK).get('waiting')):
            gate['paused'] = True
            try:
                while gate['inflight']:
                    cv.wait()
                secs = time.monotonic() - self._held_since
                held = f'{secs / 60:.0f} min' if secs >= 120 else f'{secs:.0f} s'
                t0 = time.monotonic()
                self.say('paused: another job waits for the render lock, letting it go after', held)
                self.release_lock()
                self.acquire_lock(paused=f'{held} of rendering')
                self._held_since = time.monotonic()
                self._pauses += 1
                self._paused_s += time.monotonic() - t0
                self.say('resumed after', f'{time.monotonic() - t0:.0f} s')
                self.update(state='rendering', message='Carrying on after a pause for another job')
            finally:
                gate['paused'] = False
                cv.notify_all()
        gate['inflight'] += 1


def _render_pending_chunks(self, chunks, wav, total, spec, first, last, timeline, vargs, cache_budget, chunk_cache):
    """Run pending picture/audio tasks behind the shared pause gate; keep audio retry available for the join."""
    pending = [c for c in chunks if c['state'] != 'done']
    self.st.pop('redrawn_alone', None)      # what this run drew again on its own (_render_one_at_a_time)
    # T241: each chunk counted at what one of its size was measured to commit, the sound at its own
    self.render_gb_each = export_render_gb(spec, timeline.profile)
    sound_gb = None if wav.exists() else max(SOUND_RENDER_GB, self.render_gb_each
                                             if self.render_gb_each == PER_MELT_COMMIT_GB else 0.0)
    _make_room(self, min(PARALLEL, len(pending) + (0 if wav.exists() else 1)), sound_gb)
    slots = memory_slots(render_gb=self.render_gb_each, first_gb=sound_gb)   # T80: fewer at once when memory is short
    pct = {c['i']: 0 for c in pending}
    audio_pct = [0 if not wav.exists() else 100]
    sizes = {c['i']: c['b'] - c['a'] for c in chunks}
    reused = sum(sizes[c['i']] for c in chunks if c['state'] == 'done')

    def report():
        with self._lock:
            done_frames = reused + sum(sizes[i] * p / 100 for i, p in pct.items())
            frac = 0.9 * done_frames / total + 0.02 * audio_pct[0] / 100
            finished = sum(1 for c in chunks if c['state'] == 'done')
            self.update(state='rendering', chunks=chunks, progress=round(frac, 3),
                        message=f'{finished}/{len(chunks)} chunks done ({sum(c["reused"] for c in chunks)} reused), '
                                f'audio {audio_pct[0]}%, {slots} at a time' + (' (memory)' if slots < PARALLEL else ''))

    cv = threading.Condition()
    gate = {'paused': False, 'inflight': 0}

    def step_in():
        """Before each chunk (and the sound): when this export has held the lock for HOLD_S and another job waits
                for it, let the lock go once the chunks already running are finished, queue again behind the waiter and
                carry on from the saved chunks."""
        _enter_render_slot(self, cv, gate, cache_budget)


    def step_out():
        with cv:
            gate['inflight'] -= 1
            cv.notify_all()

    short = []      # T238: what ran out of memory, and what hadn't started by then: drawn again one at a time at the end

    def guarded(name, inner):
        """Run one piece; when the PC refuses it memory, keep it (and every piece not yet started) for the end; when it
        stalled, keep it for the end (the others carry on)."""
        with self._lock:
            if short and not all(stalled for _, _, stalled in short):
                short.append((name, inner, False))
                return
        step_in()
        try:
            inner()
        except Stalled as error:
            _say_stalled(self, name, error)
            with self._lock:
                short.append((name, inner, True))
        except RuntimeError as error:
            if not _short_of_memory(self, name, error):
                raise
            with self._lock:
                short.append((name, inner, False))
        finally:
            step_out()

    def render_chunk(c):
        where = f'{c["a"] / timeline.fps:.1f}-{c["b"] / timeline.fps:.1f} s'
        guarded(f'chunk {c["i"]} ({where})', lambda: render_chunk_inner(c))

    def render_chunk_inner(c):
        _render_one_chunk(self, c, pct, report, sizes, sample_references, timeline, spec, vargs, chunk_cache)


    def render_audio():
        guarded('the sound', render_audio_inner)

    def render_audio_inner():
        _render_audio_track(self, wav, audio_pct, report, spec, first, last)


    report()
    sample_references = {}
    candidates = [c for c in pending if c['candidate']]
    if candidates:
        step_in()
        try:
            sample_references = chunk_cache.render_samples(self, timeline, candidates)
        finally:
            step_out()
    tasks = ([render_audio] if not wav.exists() else []) + [lambda c=c: render_chunk(c) for c in pending]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=slots) as pool:
        futures = [pool.submit(t) for t in tasks]
        try:
            for f in as_completed(futures):
                f.result()
        except Exception:
            self.st['aborting'] = True
            for f in futures:
                f.cancel()
            with self._lock:
                for proc in list(self.procs):
                    proc.kill()
            raise
    if short:
        _render_one_at_a_time(self, short, step_in, step_out)
    return render_audio_inner


def _make_room(self, renders, first_gb=None):
    """Before drawing: when the PC can't promise memory for this many engine renders at once (one of them counted at
    first_gb, the sound's), letitedit's idle model helpers end first (memory_room; this export holds the PC lock, so
    none is in a job). Returns its report."""
    if renders <= 0:
        return None
    each = _render_gb(self)
    need = (renders * each if first_gb is None else first_gb + (renders - 1) * each) + RESERVE_COMMIT_GB
    commit = memory_gb()[1]
    if commit is None or commit >= need:
        return None
    self.update(state='rendering', message=(
        f'Making room: {commit:.1f} GB of memory is free to promise and {renders} engine render(s) need about '
        f"{need:.0f} GB, so letitedit's idle model helpers are asked to end (they start again when needed)."))
    room = memory_room.make_room(need, f'export {getattr(self, "job_id", "")}'.strip())
    self.say('memory room:', room.get('note') or room)
    return room


def _render_gb(self):
    """What this export counts each engine render at (export_render_gb, set before drawing), else PER_MELT_COMMIT_GB."""
    value = getattr(self, 'render_gb_each', None)
    return value if isinstance(value, (int, float)) and value > 0 else PER_MELT_COMMIT_GB


def _short_of_memory(self, name, error):
    """True (and said in the log) when this piece's render failed because the PC refused it memory."""
    commit = memory_gb()[1]
    if not out_of_memory(error, commit):
        return False
    self.say(f'{name} ran out of memory ({"?" if commit is None else f"{commit:.1f}"} GB of commit free); '
             'drawing it again on its own once the others are done:', str(error)[:300])
    return True


def _say_stalled(self, name, error):
    """A stalled piece, in the log and the job's message (what letitedit_export_job shows the AI)."""
    self.say(f'{name} stalled:', str(error)[:300])
    self.update(state='rendering', message=(
        f'{name[:1].upper() + name[1:]} stopped making frames (no new frame for {STALL_S / 60:g} min), so it was '
        'stopped; it is drawn again on its own once the others are done.'))


def _wait_for_memory(self, need_gb):
    """Wait (at most MEMORY_WAIT_S) until need_gb of commit is free; returns the commit free at the end."""
    deadline = time.monotonic() + MEMORY_WAIT_S
    _make_room(self, 1)
    while True:
        commit = memory_gb()[1]
        if commit is None or commit >= need_gb or time.monotonic() >= deadline:
            return commit
        if self.cancelled():
            raise RuntimeError('Cancelled')
        self.update(state='rendering', message=(
            f'Waiting for memory: {commit:.1f} GB is free to promise and one chunk needs about {need_gb:.1f} GB. '
            f'Another program holds the rest; this export carries on by itself when it is freed (at most '
            f'{MEMORY_WAIT_S / 60:.0f} min), from the chunks already drawn.'))
        time.sleep(MEMORY_POLL_S)


def _render_one_at_a_time(self, short, step_in, step_out):
    """The pieces that ran out of memory (and those queued behind them), one at a time, each when there is room for it.
    A piece refused memory MEMORY_TRIES times more fails the export, saying so; the chunks already drawn are kept."""
    self.say('drawing', len(short), 'piece(s) one at a time:', ', '.join(name for name, _, _ in short))
    need = _render_gb(self) + RESERVE_COMMIT_GB
    for name, inner, stalled in short:
        tries = STALL_TRIES if stalled else MEMORY_TRIES
        for attempt in range(1, tries + 1):
            commit = _wait_for_memory(self, need)
            step_in()
            try:
                inner()
                break
            except Stalled as error:
                _say_stalled(self, name, error)
                if attempt == tries:
                    message = (f'The engine stopped making frames drawing {name}, again when drawn on its own '
                               f'({error}). The export was stopped; the chunks already drawn are kept, so exporting '
                               'again redraws only the rest. Stalling twice in the same place points at a clip there '
                               'the engine reads badly.')
                    raise RuntimeError(message[:2000]) from error
            except RuntimeError as error:
                if attempt == tries or not _short_of_memory(self, name, error):
                    if out_of_memory(error, memory_gb()[1]):
                        raise RuntimeError(
                            f'The PC ran out of memory drawing {name}, even on its own '
                            f'({"?" if commit is None else f"{commit:.1f}"} GB was free to promise; a chunk needs about '
                            f'{_render_gb(self):g} GB). Close a program that holds a lot of memory, or wait, and '
                            f'export again: the chunks already drawn are kept. {error}'[:2000]) from error
                    raise
            finally:
                step_out()
    self.update(redrawn_alone=[{'piece': name, 'why': 'stalled' if stalled else 'memory'} for name, _, stalled in short])


def _finish_export(self, chunks, fps, total, wav, render_audio_inner, cache_budget, spec, timeline, first, last):
    """Finish sound, check the joined video and publish the output before marking the job done."""
    # finish the sound (loudness, true-peak ceiling) and join it to the picture
    lst = self.dir / 'concat.txt'
    lst.write_text(_concat_list(chunks, fps), encoding='utf-8')
    seconds = total / fps
    if not wav.exists():   # the cache file went missing since it was drawn: draw the sound again rather than fail at the end
        self.say('the sound file is missing before the join; drawing it again:', wav)
        render_audio_inner()
    self.release_lock()
    # the pieces are on the disk by now: what is still to come is the joined file, about half of the whole estimate
    self.wait_for_space(self.dir, cache_budget.export_need(seconds) // 2)
    self.acquire_lock()
    joined, loud, audio_report = self.finish_audio(wav, spec, lst, seconds)
    if spec.get('measure_mix'):
        self.update(state='checking', message='Measuring the mix on this cut', progress=0.94)
    mix_check = measure_mix(spec, wav)
    # checks: decode, length, frames
    self.update(state='checking', message='Checking decode and length', progress=0.95)
    from letitedit.core import media as p
    prof = timeline.profile
    width, height = (spec.get('preview') or {}).get('size') or (prof['width'], prof['height'])
    checked = p.verify_video(joined, seconds, {'width': width, 'height': height, 'fps': fps,
                                               'progressive': prof['progressive'] == '1'})
    qc = self.output_qc(joined, timeline, first, last) if spec.get('qc') else None
    # T80: a Turbo export gets the lightest measured check that still catches a broken video (free: a few seconds, no AI)
    quick = None
    if spec.get('preset') == 'turbo_h264':
        try:
            import letitedit.review.turbo_check as turbo_check
            quick = turbo_check.check(joined, expect_seconds=seconds)
        except Exception as exc:  # noqa: BLE001 - a check that can't run is no reason to fail the export
            quick = {'ok': None, 'problems': [], 'notes': [f'the quick check could not run: {type(exc).__name__}: {exc}'[:300]]}
    out = Path(spec['output'])
    self.release_lock()
    self.wait_for_space(out, joined.stat().st_size)
    out.parent.mkdir(parents=True, exist_ok=True)
    older = None
    if spec.get('auto_named') and not spec.get('preview'):      # a new preview replaces the last one
        older, out = _keep_older_version(out)
    tmp_out = out.with_name(out.stem + '.' + self.job_id + '.partial.mp4')
    self._temporary.add(tmp_out)
    shutil.copyfile(joined, tmp_out)
    os.replace(tmp_out, out)
    joined.unlink(missing_ok=True)
    result = {'output': str(out), **({'older_version': str(older)} if older else {}),
              'seconds': round(seconds, 3), 'chunks': len(chunks),
              'chunks_reused': sum(c['reused'] for c in chunks), 'technical_checks': checked, 'audio_checks': audio_report,
              'pauses_for_other_jobs': self._pauses, 'paused_s': round(self._paused_s),
              'loudness': loud, **({'mix_check': mix_check} if mix_check else {}),
              'qc': qc, **({'quick_check': quick} if quick is not None else {}), 'finished': now()}
    self.update(state='done', message='Finished', progress=1, result=result)
    self.say('done', out)


class Worker:
    def __init__(self, job_id):
        self.job_id = job_id
        self.dir = JOBS / job_id
        self.spec = _read(self.dir / 'spec.json')
        self.st = _read(self.dir / 'status.json', {}) or {}
        self.log = open(self.dir / 'worker.log', 'a', encoding='utf-8', buffering=1)
        self.procs = set()
        self._lock = threading.RLock()
        self._temporary = set()

    def say(self, *a):
        with self._lock:
            self.log.write(time.strftime('%H:%M:%S ') + ' '.join(map(str, a)) + '\n')

    def update(self, **kw):
        with self._lock:
            self.st.update(kw, pid=os.getpid(), updated=now())
            _write(self.dir / 'status.json', self.st)

    def cancelled(self):
        return (self.dir / 'cancel').exists()

    # -------------------------------------------------------------- lock
    def acquire_lock(self, paused=None):
        def waiting(i):
            if paused:
                self.update(state='waiting', message=(
                    f'Paused: another job needed the PC, so this export stepped aside after {paused}. It carries on from '
                    f'its saved chunks when it has had its turn again. Now: {i["message"]} Paused {i["waited_s"]} s.'))
                return
            self.update(state='waiting', message=(
                f'Waiting for the PC render lock: {i["message"]} Waited {i["waited_s"]} s of {i["timeout_s"]:g} s '
                '(LETITEDIT_RENDER_LOCK_WAIT_S). It starts by itself when the lock is free; a lock whose owner has '
                'gone clears by itself.'))
        h = render_lock.acquire(f'letitedit export {self.job_id}', timeout_s=LOCK_WAIT_S, poll_s=15, path=LOCK,
                                job_id=self.job_id, caller_pids=self.spec.get('caller_pids'), on_wait=waiting,
                                cancelled=self.cancelled)
        self._lock_holder = h
        if getattr(h, 'cleared', None):
            self.say('removed stale render lock:', h.cleared)
        if not h.owned:
            # the process that started this export holds the lock itself: render under it, leave it in place
            self.say('render lock held by the process that started this export:', h.text)
            # the scenes and motion drawn inside this export ask for the lock again: they are the caller's work too
            os.environ[render_lock.CALLERS_ENV] = ','.join(str(p) for p in self.spec.get('caller_pids') or [])
            self.update(state='rendering', message='Rendering under the render lock its caller holds')

    def release_lock(self):
        render_lock.release(getattr(self, '_lock_holder', None))

    # -------------------------------------------------------------- melt
    def melt(self, args, progress_cb=None, env=None):
        """One engine render, with memory_room.ENGINE_ENV and the render's own env (the picture chunks: the picture
        renders' settings) over this process's environment."""
        cmd = [str(MELT), '-progress', *map(str, args)]
        self.say('melt', ' '.join(cmd)[:400])
        # tied at birth: the render ends with this export's process, so no render outlives the lock's owner
        proc = render_lock.popen_tied(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      creationflags=DETACHED | render_lock.background_flags(), cwd=str(APP), text=True,
                                      encoding='utf-8', errors='replace', bufsize=1,
                                      env={**os.environ, **memory_room.ENGINE_ENV, **(env or {})})
        with self._lock:
            self.procs.add(proc)
        import queue
        output = queue.Queue()

        def pump():          # the engine's output, read beside the watchdog (a stalled render writes nothing)
            import codecs
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            try:
                while True:      # whatever has arrived, not a fixed count: each frame's line is seen when it comes
                    data = proc.stdout.buffer.read1(4096)
                    if not data:
                        break
                    output.put(decoder.decode(data))
            except (OSError, ValueError):
                pass
            finally:
                output.put(None)
        threading.Thread(target=pump, name='melt-output', daemon=True).start()
        tail = []
        last = 0.0
        buf = ''
        frame, moved, stalled, looked, starved = -1, time.monotonic(), False, 0.0, []
        try:
            while True:
                try:
                    ch = output.get(timeout=1.0)
                except queue.Empty:
                    ch = ''
                if ch is None:
                    break
                buf += ch
                parts = re.split(r'[\r\n]', buf)
                buf = parts.pop()
                for line in parts:
                    if not line.strip():
                        continue
                    f = FRAME.search(line)
                    if f and int(f.group(1)) != frame:
                        frame, moved = int(f.group(1)), time.monotonic()
                    m = re.search(r'percentage:\s*(\d+)', line)
                    if m:
                        if progress_cb and time.monotonic() - last > 2:
                            last = time.monotonic()
                            progress_cb(int(m.group(1)))
                    else:
                        tail.append(line)
                        tail = tail[-30:]
                        if not starved and OUT_OF_MEMORY.search(line):
                            starved.append(line.strip()[:200])
                if proc.poll() is None and time.monotonic() - looked >= .5:
                    looked = time.monotonic()
                    if self.cancelled() or self.st.get('aborting'):
                        proc.kill()
                    elif looked - moved > STALL_S:
                        stalled = True
                        self.say(f'watchdog: no new frame for {STALL_S:g} s (last frame {frame}); stopping melt')
                        proc.kill()
            rc = proc.wait()
        finally:
            with self._lock:
                self.procs.discard(proc)
        if self.cancelled():
            raise RuntimeError('Cancelled')
        if stalled:
            at = 'before its first frame' if frame < 0 else f'after frame {frame}'
            raise Stalled(f'the engine stopped making frames {at}: no new frame for {STALL_S / 60:g} min, so it was '
                          'stopped' + (' | ' + ' | '.join(tail[-4:]) if tail else ''))
        if rc != 0:
            raise RuntimeError(f'melt exited {rc}: ' + ' | '.join(tail[-8:]))
        if starved:
            # T238: an engine refused memory can still exit 0, its file cut short (x264's frames dropped, the
            # producer ended early): a memory failure, not a finished piece
            raise RuntimeError(f'melt ran out of memory and its output is incomplete ({starved[0]}): '
                               + ' | '.join(tail[-6:]))

    # -------------------------------------------------------------- stages
    def run(self):
        spec = self.spec
        try:
            import letitedit.core.cache_budget as cache_budget
            _prepare_render(self, spec, cache_budget)

            timeline = tm.load(spec['snapshot'])
            fps = timeline.fps
            first, last = spec['first'], spec['last']
            enc = spec.get('encode') or {}
            vargs = enc.get('video_args') or VIDEO_PRESETS[spec['preset']]
            plan = _plan_chunks(timeline, first, last, spec['chunk_s'])
            import letitedit.timeline.chunk_cache as chunk_cache
            renderer = chunk_cache.renderer_signature(APP)
            chunks, total, wav = _prepare_cached_chunks(self, timeline, first, last, enc, spec, plan, chunk_cache, renderer)

            render_audio_inner = _render_pending_chunks(self, chunks, wav, total, spec, first, last, timeline, vargs, cache_budget, chunk_cache)

            _finish_export(self, chunks, fps, total, wav, render_audio_inner, cache_budget, spec, timeline, first, last)

        except Exception as exc:  # noqa: BLE001
            import traceback
            self.say(traceback.format_exc())
            state = 'cancelled' if isinstance(exc, InterruptedError) or str(exc) == 'Cancelled' else 'failed'
            self.update(state=state, message=str(exc)[:500], error=str(exc)[:2000])
        finally:
            try:
                with self._lock:
                    for proc in list(self.procs):
                        try:
                            if proc.poll() is None:
                                proc.kill()
                                proc.wait(timeout=15)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                self.st.pop('aborting', None)
            finally:
                try:
                    self.cleanup()
                finally:
                    self.release_lock()

    def wait_for_space(self, path, need):
        import letitedit.core.cache_budget as cache_budget
        cache_budget.need_room(path, need, 'export this video', cache=CACHE, cancelled=self.cancelled,
                               progress=lambda message: self.update(state='waiting_space', message=message))

    def cleanup(self):
        paths = set(getattr(self, '_temporary', ()))
        paths.update(self.dir / name for name in ('concat.txt', 'export.partial.mp4', 'audio-limited.wav',
                                                  'audio-finished.wav'))
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def ffmpeg(self, args):
        r = subprocess.run([str(FFMPEG), '-v', 'error', *map(str, args)], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise RuntimeError('ffmpeg failed: ' + r.stderr[-1500:])
        return r

    def finish_audio(self, wav, spec, lst, seconds):
        """Loudness (spec['loudness'], gain then a true-peak limiter) and the true-peak ceiling (spec['true_peak'] dBTP),
        both measured on the encoded file. The limiter starts 1 dB under the ceiling; when AAC still pushes the peaks
        over it, the limiter runs again lower by the overshoot, from the lossless mix, up to 4 tries. A file still over
        the ceiling is kept, with a note. Returns (joined mp4, loudness report, audio report)."""
        target = spec.get('loudness')
        peak_max = spec.get('true_peak', -1.0)
        ceiling = (peak_max if peak_max is not None else -1.0) - 1.0
        joined = self.dir / 'export.partial.mp4'
        loud, tries, lufs, tp = None, [], None, None
        for attempt in range(4):
            src, limiter = wav, None
            if target is not None:
                self.update(state='audio', message=f'Bringing the sound to {target:g} LUFS (limiter {ceiling:.1f} dBTP)',
                            progress=0.92)
                src, loud = self.finish_loudness(wav, float(target), ceiling=ceiling)
                limiter = round(ceiling, 2)
            elif attempt:
                self.update(state='audio', message=f'Limiting peaks at {ceiling:.1f} dBTP', progress=0.92)
                src, limiter = self.limit_peaks(wav, ceiling), round(ceiling, 2)
            self.update(state='joining', message='Joining chunks and audio', progress=0.93)
            self.ffmpeg(['-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', src, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                         '-c:a', 'aac', '-b:a', (spec.get('encode') or {}).get('audio_bitrate') or AUDIO_BITRATE[spec['preset']],
                         *(['-ar', str(spec['encode']['sample_rate'])] if (spec.get('encode') or {}).get('sample_rate') else []),
                         '-t', f'{seconds:.4f}', '-movflags', '+faststart', joined])
            lufs, tp = self.measure_loudness(joined)
            tries.append({'limiter_dbtp': limiter, 'lufs': lufs, 'true_peak_dbtp': tp})
            if peak_max is None or tp is None or tp <= peak_max:
                break
            ceiling -= (tp - peak_max) + 0.3
        passed = peak_max is None or tp is None or tp <= peak_max
        report = {'integrated_lufs': lufs, 'true_peak_dbtp': tp, 'true_peak_max': peak_max, 'peak_passed': passed,
                  'tries': tries}
        if not passed:
            report['note'] = (f'true peak {tp:.1f} dBTP is over the {peak_max:g} dBTP asked for after {len(tries)} tries; '
                              'the file is kept (true_peak sets the ceiling, \'off\' leaves peaks alone)')
        return joined, loud, report

    def limit_peaks(self, wav, ceiling):
        """The mix with only a true-peak limiter at `ceiling` dBTP (no gain)."""
        out = self.dir / 'audio-limited.wav'
        self.ffmpeg(['-y', '-i', wav, '-af', f'aresample=192000,alimiter=limit={10 ** (ceiling / 20):.4f}:attack=5:release=80:'
                     'level=false:latency=true,aresample=48000', '-c:a', 'pcm_f32le', out])
        return out

    def measure_loudness(self, wav):
        """(integrated LUFS, true peak dBTP) of an audio file (or a video file's sound)."""
        r = subprocess.run([str(FFMPEG), '-hide_banner', '-nostats', '-i', str(wav), '-vn', '-af', 'ebur128=peak=true', '-f',
                            'null', '-'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW,
                           stdin=subprocess.DEVNULL)
        summ = r.stderr[r.stderr.rfind('Summary:'):]

        def num(rx):
            m = re.search(rx, summ)
            return float(m.group(1)) if m and m.group(1) not in ('-inf', 'nan') else None
        return num(r'I:\s+(-?[\d.]+|-inf|nan) LUFS'), num(r'Peak:\s+(-?[\d.]+|-inf|nan) dBFS')

    def finish_loudness(self, wav, target, ceiling=-2.0):
        """Bring the mix to `target` integrated loudness with plain gain, catching peaks with a true-peak limiter at
        `ceiling` dBTP (2 dB of room, because AAC encoding raises peaks). The balance inside the mix is untouched.
        Returns (wav to use, report)."""
        before, peak = self.measure_loudness(wav)
        if before is None:
            return wav, {'target': target, 'note': 'silent mix: left as is'}
        out = self.dir / 'audio-finished.wav'
        gain, after, peak_after = target - before, before, peak
        for _ in range(3):
            limit = 10 ** (ceiling / 20)
            self.ffmpeg(['-y', '-i', wav, '-af', f'volume={gain:.2f}dB,aresample=192000,alimiter=limit={limit:.4f}:attack=5:'
                         f'release=80:level=false:latency=true,aresample=48000', '-c:a', 'pcm_f32le', out])
            after, peak_after = self.measure_loudness(out)
            if after is None or abs(target - after) <= 0.4 or gain > 24:
                break
            gain += target - after   # the limiter took some level: add it back once more
        return out, {'target': target, 'before_lufs': before, 'after_lufs': after, 'gain_db': round(gain, 2),
                     'true_peak_dbtp': peak_after, 'ceiling_dbtp': ceiling}

    def count_frames(self, path):
        r = subprocess.run([str(FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                            'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        try:
            return int(r.stdout.strip().split(',')[0])
        except ValueError:
            return -1

    def output_qc(self, mp4, timeline, first, last):
        """Sample the finished file at every V1 clip's middle and flag blank, black or squeezed frames."""
        import letitedit.review.checks as checks
        work = self.dir / 'qc'
        work.mkdir(exist_ok=True)
        picks = []
        v1 = timeline.v1()
        for it in (v1.items if v1 else []):
            f = it.start + it.length // 2
            if first <= f <= last:
                picks.append(f)
        problems = []
        for k, f in enumerate(picks[:200]):
            png = work / f'q_{k:03d}.png'
            subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-ss', f'{(f - first) / timeline.fps:.3f}', '-i', str(mp4), '-frames:v', '1',
                            '-vf', 'scale=384:-2', str(png)], creationflags=NO_WINDOW, capture_output=True)
            if png.exists():
                for pr in checks._frame_problems(png, timeline.profile):
                    it = timeline.item_at(f)
                    problems.append({'at': checks.fmt(f / timeline.fps), 'clip': it.name if it else '', 'problem': pr})
        return {'frames_checked': len(picks[:200]), 'problems': problems}


if __name__ == '__main__':
    os.environ.pop('LETITEDIT_TOOL_SERVER_PID', None)  # an export outlives the chat that queued it, and so do its model workers
    if len(sys.argv) >= 3 and sys.argv[1] == 'run':
        if len(sys.argv) >= 4:      # the cache of the process that queued the job
            os.environ['LETITEDIT_CACHE'] = sys.argv[3]
            CACHE = Path(sys.argv[3])
            JOBS, CHUNKS = CACHE / 'exports', CACHE / 'chunks'
        os.environ.update((_read(JOBS / sys.argv[2] / 'spec.json') or {}).get('env') or {})
        render_lock.below_normal()      # started through WMI at normal priority: melt and ffmpeg inherit this
        Worker(sys.argv[2]).run()
