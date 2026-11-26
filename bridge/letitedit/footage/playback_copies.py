"""Local playback-copy preparation for the editor's automatic Shotcut proxies.

Run this worker in a background process, never on the editor's UI thread. Each file
takes its own render-lock turn. Projects and original media are never written.

The copies are made at the size the editor's Playback quality setting asks for (--size: the shorter side at 540, 720
or 1080, never larger than the original), each size with copies of its own; --size auto runs a short test of this PC
once (pc_test) and picks the sharpest size it decodes fast enough.
"""
import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import time

import letitedit.core.quiet_subprocess as quiet_subprocess
import letitedit.core.render_lock as render_lock
import letitedit.core.cache_budget as cache_budget

GIB = 1024 ** 3
CACHE_LIMIT = 8 * GIB
MAX_AGE_S = 30 * 86400
SIZES = (540, 720, 1080)
DEFAULT_SIZE = 540
# The picture settings, shared with the rendered playback preview (T214). veryfast keeps x264's deblocking filter and
# CABAC (ultrafast turns both off: the v2 copies were blocky on faces); a keyframe every 15 frames keeps a paused
# seek to at most 14 decoded frames; no B-frames. tests/t214/REPORT.md has the measurements.
X264_PRESET, X264_CRF, X264_GOP = 'veryfast', 20, 15


def recipe(size=DEFAULT_SIZE, rate=None):
    """rate: the frame rate a copy is made at when it is lower than the source's (the timeline's, T220); None keeps the
    source's own rate, as every copy before T220 did (those keep their keys)."""
    return f'h264-gop15-{size}-v3' if not rate else f'h264-gop15-{size}-r{rate}-v4'


RECIPE = recipe()
# The PC test for --size auto: decoding 8 s of a 1920x1080 clip made with the copies' own settings (light camera-like
# grain: about 14 Mbit/s, between a calm talking head's 1080 copy and a grainy phone clip's), on as many threads as
# this process may use, up to four. A size is picked when that speed, scaled by the size's pixels, is at least
# PC_TEST_MARGIN times a 60 fps source in real time. The margin was set from playback measured in the app on a long
# graded project (tests/t214/REPORT.md): decoding is only part of what playing costs, so the margin is wide. The editor
# also steps Automatic down when its own 1x playback skips frames.
PC_TEST_VERSION = 2
PC_TEST_MARGIN = 14.0


def scale_filter(size):
    """The shorter side at size, never enlarged, even numbers, the picture's own shape (stored orientation)."""
    return (f"scale=w='if(gte(iw,ih),-2,trunc(min({size},iw)/2)*2)'"
            f":h='if(gte(iw,ih),trunc(min({size},ih)/2)*2,-2)'")


def local_path(path):
    path = Path(path).resolve()
    if os.name == 'nt':
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))
        cloud = any(part.lower() in {'my drive', 'onedrive', 'dropbox'} or
                    part.lower().startswith('onedrive - ') for part in path.parts)
        if drive_type != 3 or cloud:
            raise ValueError('Playback copies require a local fixed disk outside cloud folders')
    return path


def default_cache():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise ValueError('LOCALAPPDATA is required for the playback cache')
    return local_path(Path(base) / 'letitedit' / 'playback-copies')


def source_identity(source):
    source = Path(source).resolve(strict=True)
    stat = source.stat()
    return {'path': str(source), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def cache_key(identity, size=DEFAULT_SIZE, rate=None):
    return hashlib.sha256(json.dumps([recipe(size, rate), identity], sort_keys=True).encode('utf-8')).hexdigest()


def parse_rate(text):
    """'30', '30000/1001' or '29.97' -> (text for ffmpeg, frames a second), or None"""
    if not text:
        return None
    try:
        if '/' in str(text):
            numerator, denominator = (int(part) for part in str(text).split('/'))
            value = numerator / denominator if denominator > 0 and numerator > 0 else 0
            label = f'{numerator}/{denominator}' if denominator != 1 else str(numerator)
        else:
            value = float(text)
            label = ('%.6f' % value).rstrip('0').rstrip('.')
    except (ValueError, ZeroDivisionError):
        return None
    return (label, value) if value > 0 else None


def copy_rate(source_stream, timeline_rate, keep_rate=False):
    """The rate a copy is made at: the timeline's when the source has more frames a second than it needs (Rat's 60 fps
    cameras on a 30 fps timeline), else None (the source's own rate). A source played slowed somewhere keeps its own
    rate: the slowed clip shows frames the timeline's rate would drop."""
    if keep_rate or not timeline_rate:
        return None
    label, value = timeline_rate
    return label if frame_rate(source_stream) > value + 0.01 else None


def usable_cpus():
    """The logical processors this process may run on (its affinity on Windows, which a smaller PC's count matches)."""
    if os.name == 'nt':
        try:
            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            mine, system = ctypes.c_size_t(), ctypes.c_size_t()
            if kernel.GetProcessAffinityMask(ctypes.c_void_p(kernel.GetCurrentProcess()), ctypes.byref(mine),
                                             ctypes.byref(system)) and mine.value:
                return bin(mine.value).count('1')
        except (AttributeError, OSError):
            pass
    return (os.process_cpu_count() if hasattr(os, 'process_cpu_count') else os.cpu_count()) or 1


def pc_test(folder, ffmpeg):
    """This PC's pick for --size auto, measured once and kept in the cache folder (again when the processor changes)."""
    record_file = Path(folder) / 'pc-test.json'
    cpus = usable_cpus()
    threads = max(1, min(4, cpus))
    identity = {'version': PC_TEST_VERSION, 'processor': platform.processor(), 'cpus': cpus}
    try:
        record = json.loads(record_file.read_text(encoding='utf-8-sig'))
        if record.get('identity') == identity and record.get('size') in SIZES:
            return record
    except (OSError, ValueError, AttributeError):
        pass
    with tempfile.TemporaryDirectory(prefix='pending-pc-test-', dir=folder) as temporary:
        clip = Path(temporary) / 'test.mp4'
        with render_lock.slot('playback copies: PC test', timeout_s=900, poll_s=2, caller_pids=render_lock.ancestors()):
            subprocess.run([str(ffmpeg), '-nostdin', '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=1920x1080:rate=30:duration=8,noise=alls=4:allf=t', '-c:v', 'libx264',
                            '-preset', X264_PRESET, '-crf', str(X264_CRF), '-g', str(X264_GOP), '-bf', '0',
                            '-pix_fmt', 'yuv420p', '-threads', '4', str(clip)],
                           check=True, timeout=300, creationflags=render_lock.background_flags())
            best = None
            for _ in range(2):
                started = time.monotonic()
                result = subprocess.run([str(ffmpeg), '-nostdin', '-hide_banner', '-benchmark', '-threads', str(threads),
                                         '-i', str(clip), '-f', 'null', '-'], check=True, timeout=300, capture_output=True,
                                         text=True, errors='replace', creationflags=render_lock.background_flags())
                seconds = time.monotonic() - started
                # the decoding itself, without the program's start (ffmpeg's own clock), when it says
                timed = re.findall(r'rtime=([0-9.]+)s', result.stderr or '')
                if timed and float(timed[-1]) > 0:
                    seconds = float(timed[-1])
                best = seconds if best is None else min(best, seconds)
    fps_1080 = 240 / best
    fits = [size for size in SIZES if fps_1080 * (1080 / size) ** 2 >= PC_TEST_MARGIN * 60]
    record = {'identity': identity, 'decode_fps_1080': round(fps_1080, 1), 'threads': threads, 'margin': PC_TEST_MARGIN,
              'size': max(fits) if fits else min(SIZES), 'measured': time.strftime('%Y-%m-%dT%H:%M:%S')}
    temporary = record_file.with_suffix('.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    temporary.replace(record_file)
    return record


def probe(source, ffprobe):
    result = subprocess.run([str(ffprobe), '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(source)], capture_output=True, timeout=60, check=True)
    return json.loads(result.stdout)


def frame_rate(stream):
    numerator, denominator = stream.get('avg_frame_rate', '0/1').split('/')
    return float(numerator) / float(denominator) if float(denominator) else 0


def heavy_reasons(info, source):
    videos = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'video'
              and not stream.get('disposition', {}).get('attached_pic')]
    if not videos:
        return []
    video = videos[0]
    reasons = []
    if max(video.get('width', 0), video.get('height', 0)) > 1920 or min(
            video.get('width', 0), video.get('height', 0)) > 1080:
        reasons.append('larger than 1080p')
    if frame_rate(video) > 30.01:
        reasons.append('more than 30 fps')
    if video.get('codec_name') in {'hevc', 'h265'}:
        reasons.append('HEVC')
    path = str(source).replace('\\', '/').lower()
    cloud = any(part in path for part in ('/my drive/', '/onedrive', '/dropbox/'))
    network = path.startswith('//')
    if os.name == 'nt' and Path(source).anchor:
        network = network or ctypes.windll.kernel32.GetDriveTypeW(str(Path(source).anchor)) == 4
    if cloud or network:
        reasons.append('cloud or network drive')
    return reasons


def compatible(original, copy, rate=None):
    """rate: the frame rate the copy was made at, when not the source's own (frames a second)"""
    for kind in ('video', 'audio'):
        sources = [stream for stream in original['streams'] if stream.get('codec_type') == kind]
        copies = [stream for stream in copy['streams'] if stream.get('codec_type') == kind]
        if len(sources) != len(copies):
            return False
        for source_stream, copy_stream in zip(sources, copies):
            if kind == 'video' and (copy_stream.get('codec_name') != 'h264' or
                                   abs((rate or frame_rate(source_stream)) - frame_rate(copy_stream)) > 0.01):
                return False
            if kind == 'video':
                def rotation(stream):
                    return next((float(item['rotation']) % 360 for item in stream.get('side_data_list', [])
                                 if 'rotation' in item), 0)
                if abs(rotation(source_stream) - rotation(copy_stream)) > 0.1:
                    return False
            if source_stream.get('index') != copy_stream.get('index'):
                return False
            for field in ('start_time', 'duration'):
                if field not in source_stream or field not in copy_stream:
                    return False
                if abs(float(source_stream[field]) - float(copy_stream[field])) > 0.05:
                    return False
    return True


class Cache:
    def __init__(self, folder, limit=CACHE_LIMIT, free_floor=None, owner_pid=None, size=DEFAULT_SIZE,
                 stop_file=None):
        self.folder = local_path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        # free_floor: the drive room kept free (default: letitedit's own, cache_budget.reserve_bytes)
        self.limit = limit
        self.free_floor = cache_budget.reserve_bytes() if free_floor is None else free_floor
        self.owner_pid = owner_pid
        self.stop_file = Path(stop_file) if stop_file else None
        if size not in SIZES:
            raise ValueError(f'Playback copy size must be one of {SIZES}')
        self.size = size

    def stopped(self):
        """The editor asked this run to stop (another Playback Quality was chosen): its stop file exists."""
        return bool(self.stop_file and self.stop_file.exists())

    def check_owner(self):
        if self.owner_pid and not render_lock.pid_alive(self.owner_pid):
            raise InterruptedError("Playback window closed; preparation stopped")
        if self.stopped():
            raise InterruptedError("Another playback quality was chosen; preparation stopped")

    def speech_busy(self):
        return bool(self.owner_pid and (Path(tempfile.gettempdir()) /
                    f'letitedit-speech-{self.owner_pid}.busy').exists())

    @contextmanager
    def work_turn(self, source):
        while True:
            self.check_owner()
            while self.speech_busy():
                self.check_owner()
                time.sleep(0.1)
            with render_lock.slot('playback copy: ' + Path(source).name, timeout_s=900, poll_s=2,
                                  caller_pids=render_lock.ancestors()):
                self.check_owner()
                if self.speech_busy():
                    continue
                yield
                return

    def used(self):
        return sum(path.stat().st_size for path in self.folder.rglob('*') if path.is_file())

    def cleanup(self, protected=(), reserve=0):
        protected = set(protected)
        for lease in self.folder.glob('lease-*.json'):
            try:
                record = json.loads(lease.read_text(encoding='utf-8-sig'))
                if render_lock.pid_alive(record['pid']):
                    protected.update(record['keys'])
                else:
                    lease.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        for pending in self.folder.glob('pending-*'):
            if pending.is_dir() and time.time() - pending.stat().st_mtime > 86400:
                shutil.rmtree(pending)
        entries = sorted((path for path in self.folder.glob('*.mp4')
                          if re.fullmatch(r'[0-9a-f]{64}', path.stem)),
                         key=lambda path: path.stat().st_mtime)
        for path in entries:
            if path.stem in protected:
                continue
            old = time.time() - path.stat().st_mtime > MAX_AGE_S
            enough_room = self.used() + reserve <= self.limit
            enough_free = shutil.disk_usage(self.folder).free - reserve >= self.free_floor
            if not old and enough_room and enough_free:
                continue
            path.unlink()
            path.with_suffix('.json').unlink(missing_ok=True)
        if self.used() + reserve > self.limit or shutil.disk_usage(self.folder).free - reserve < self.free_floor:
            raise OSError('Playback cache paused: its size cap, or the drive is down to the room letitedit keeps free')

    def ready(self, identity, rate=None):
        key = cache_key(identity, self.size, rate)
        path, receipt = self.folder / f'{key}.mp4', self.folder / f'{key}.json'
        try:
            record = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if not isinstance(record, dict):
                return None
            if record['source'] == identity and record['recipe'] == recipe(self.size, rate) and path.stat().st_size == record['copy_bytes']:
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                        return None
                os.utime(path, None)
                return record
        except (OSError, ValueError, KeyError):
            pass
        return None

    def lookup(self, identity, timeline_rate=None, keep_rate=False):
        """A ready copy for this source: one made at the timeline's rate, else one at the source's own rate when that
        is no more than the timeline needs (or the source plays slowed somewhere)."""
        if timeline_rate and not keep_rate:
            record = self.ready(identity, timeline_rate[0])
            if record:
                return record
        record = self.ready(identity)
        if record and timeline_rate and not keep_rate:
            video = next((s for s in record.get('streams', []) if s.get('codec_type') == 'video'), {})
            if frame_rate(video) > timeline_rate[1] + 0.01:
                return None
        return record

    def prepare(self, source, ffmpeg, ffprobe, protected=(), timeline_rate=None, keep_rate=False):
        self.check_owner()
        started = time.monotonic()
        identity = source_identity(source)
        cached = self.lookup(identity, timeline_rate, keep_rate)
        if cached:
            return dict(cached, cached=True, lookup_seconds=round(time.monotonic() - started, 3))
        with self.work_turn(source):
            self.check_owner()
            identity = source_identity(source)
            cached = self.lookup(identity, timeline_rate, keep_rate)
            if cached:
                return dict(cached, cached=True)
            info = probe(source, ffprobe)
            reasons = heavy_reasons(info, source)
            if not reasons:
                return {'source': identity, 'state': 'original', 'reasons': [], 'size': self.size}
            videos = [stream for stream in info['streams'] if stream.get('codec_type') == 'video']
            audio = [stream for stream in info['streams'] if stream.get('codec_type') == 'audio']
            if (len(videos) != 1 or len(audio) > 1 or
                    videos[0].get('pix_fmt', '').startswith(('yuva', 'rgba', 'argb', 'bgra', 'abgr'))):
                return {'source': identity, 'state': 'unsupported', 'reasons': reasons}
            media = sorted(videos + audio, key=lambda stream: stream['index'])
            if [stream['index'] for stream in media] != list(range(len(media))):
                return {'source': identity, 'state': 'unsupported', 'reasons': reasons}
            rate = copy_rate(videos[0], timeline_rate, keep_rate)
            key = cache_key(identity, self.size, rate)
            self.cleanup(protected, reserve=min(self.limit // 4, 256 * 1024 ** 2))
        with tempfile.TemporaryDirectory(prefix='pending-', dir=self.folder) as temporary:
            pending = Path(temporary) / 'copy.mp4'
            duration = float(videos[0].get('duration', 0))
            segments = []
            ranges = list(range(0, int(duration) + 1, 60)) if duration > 180 else [0]
            for offset in ranges:
                self.check_owner()
                cached = self.ready(identity, rate)
                if cached:
                    if source_identity(source) != identity:
                        raise ValueError('Playback source changed; original remains in use')
                    return dict(cached, cached=True)
                if duration > 180 and offset >= duration:
                    break
                part = Path(temporary) / f'part-{offset}.mov' if duration > 180 else pending
                command = [str(ffmpeg), '-nostdin', '-hide_banner', '-v', 'error', '-threads', '4']
                if duration > 180:
                    command += ['-ss', str(offset)]
                command += ['-noautorotate', '-i', str(source)]
                if duration > 180:
                    command += ['-t', str(min(60, duration - offset))]
                for stream in media:
                    command.extend(['-map', '0:' + str(stream['index'])])
                command += ['-vf', scale_filter(self.size) + (f',fps={rate}' if rate else ''),
                            '-c:v', 'libx264', '-preset', X264_PRESET, '-crf', str(X264_CRF), '-g', str(X264_GOP), '-bf', '0',
                            '-threads:v', '4', '-filter_threads', '4', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
                            '-c:a', 'pcm_s16le' if duration > 180 else 'aac']
                if duration <= 180:
                    command += ['-b:a', '192k']
                command += ['-map_metadata', '0', '-movflags', '+faststart', str(part)]
                self.encode(command, Path(temporary) / 'ffmpeg.log', source, protected)
                segments.append(part)
            if duration > 180:
                listing = Path(temporary) / 'parts.txt'
                listing.write_text(''.join("file '" + part.name + "'\nduration " + str(min(60, duration - index * 60)) + "\n"
                                           for index, part in enumerate(segments)), encoding='utf-8')
                command = [str(ffmpeg), '-nostdin', '-hide_banner', '-v', 'error', '-threads', '4',
                           '-f', 'concat', '-safe', '0', '-i', str(listing)]
                for stream in media:
                    command.extend(['-map', '0:' + str(stream['index'])])
                command += ['-c:v', 'copy',
                           '-c:a', 'aac', '-b:a', '192k', '-threads:a', '4', '-map_metadata', '0',
                           '-movflags', '+faststart', str(pending)]
                self.encode(command, Path(temporary) / 'join.log', source, protected)
                for part in segments:
                    part.unlink()
            copied = probe(pending, ffprobe)
            if not compatible(info, copied, parse_rate(rate)[1] if rate else None) or source_identity(source) != identity:
                raise ValueError('Playback copy timing differs or the source changed; original remains in use')
            size = pending.stat().st_size
            self.cleanup(protected, reserve=16384)
            target = self.folder / f'{key}.mp4'
            with pending.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            record = {'source': identity, 'copy': str(target), 'state': 'ready', 'reasons': reasons,
                      'recipe': recipe(self.size, rate), 'size': self.size, 'rate': rate, 'copy_bytes': size, 'seconds': round(time.monotonic() - started, 3),
                      'streams': copied['streams'], 'sha256': digest}
            pending.replace(target)
            receipt = Path(temporary) / 'receipt.json'
            receipt.write_text(json.dumps(record), encoding='utf-8')
            receipt.replace(target.with_suffix('.json'))
            return dict(record, cached=False)

    def encode(self, command, log_file, source, protected=()):
        self.check_owner()
        while True:
            with self.work_turn(source):
                if self.encode_turn(command, log_file, protected):
                    return

    def encode_turn(self, command, log_file, protected):
        self.check_owner()
        with log_file.open('wb') as log:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log,
                                       creationflags=render_lock.background_flags())
            deadline = time.monotonic() + 240
            try:
                while process.poll() is None:
                    self.check_owner()
                    if self.speech_busy():
                        return False
                    if time.monotonic() > deadline:
                        raise TimeoutError('Playback copy chunk exceeded four minutes; original remains in use')
                    if self.used() > self.limit or shutil.disk_usage(self.folder).free < self.free_floor:
                        self.cleanup(protected)
                        if self.used() > self.limit or shutil.disk_usage(self.folder).free < self.free_floor:
                            raise OSError('Playback copy stopped at the disk-space limit')
                    time.sleep(0.25)
                if process.returncode:
                    raise RuntimeError('Playback copy encoder failed; original remains in use')
                return True
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='*')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--owner-pid', type=int)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--ffprobe', type=Path, required=True)
    parser.add_argument('--size', default=str(DEFAULT_SIZE), choices=[str(size) for size in SIZES] + ['auto'],
                        help='the shorter side of the copies; auto: the PC test picks it')
    parser.add_argument('--stop-file', type=Path, help='stop (and stop the encoder) once this file exists')
    parser.add_argument('--fps', help="the timeline's frame rate ('30', '30000/1001'): a source with more frames a "
                                      "second gets a copy at this rate, unless the manifest says it plays slowed")
    args = parser.parse_args()
    keep = set()
    if args.manifest:
        # each entry: a path, or {"path": ..., "keep_rate": true} for a source played slowed somewhere
        for entry in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
            if isinstance(entry, dict):
                args.sources.append(entry['path'])
                if entry.get('keep_rate'):
                    keep.add(entry['path'])
            else:
                args.sources.append(entry)
    timeline_rate = parse_rate(args.fps)
    render_lock.below_normal()
    folder = local_path(args.cache or default_cache())
    folder.mkdir(parents=True, exist_ok=True)
    if args.size == 'auto':
        try:
            test = pc_test(folder, args.ffmpeg)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            test = {'size': DEFAULT_SIZE, 'error': str(error)}
        size = test['size']
        print(json.dumps({'state': 'size', 'size': size, 'pc_test': test}), flush=True)
    else:
        size = int(args.size)
    cache = Cache(folder, owner_pid=args.owner_pid, size=size, stop_file=args.stop_file)
    protected = []
    for source in args.sources:
        try:
            identity = source_identity(source)
            protected.append(cache_key(identity, size))
            if timeline_rate:
                protected.append(cache_key(identity, size, timeline_rate[0]))
        except OSError:
            pass
    if args.owner_pid and render_lock.pid_alive(args.owner_pid):
        lease = cache.folder / f'lease-{args.owner_pid}-{os.getpid()}.json'
        lease.write_text(json.dumps({'pid': args.owner_pid, 'keys': protected}), encoding='utf-8')
    failed = False
    for source in args.sources:
        if args.owner_pid and not render_lock.pid_alive(args.owner_pid) or cache.stopped():
            break
        try:
            result = cache.prepare(source, args.ffmpeg, args.ffprobe, protected, timeline_rate, source in keep)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            result = {'source': str(source), 'state': 'error', 'error': str(error)}
            failed = True
        print(json.dumps(result), flush=True)
    if cache.stopped():
        args.stop_file.unlink(missing_ok=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
