"""Rendered playback previews: the timeline drawn once at a light size, in cached chunks, for smooth playback.

The editor starts one worker per window and talks to it in JSON lines. On stdin it sends the timeline as it is now
(its original-media XML, never the playback copies): {"plan": {"xml": text, "generation": n, "render": bool,
"force": bool, "focus": frame}}, {"focus": frame}, {"render": bool}, {"force": true}, {"yield": bool} (the player
plays frames it draws live: no chunk is started and a running encode is paused in place) or {"stop": true}. On stdout the
worker says which chunks exist: {"event": "plan", ...}, {"event": "ready", ...}, {"event": "done", ...},
{"event": "paused", "why": ...}.

A chunk is a stretch of about CHUNK_S seconds, snapped to the main track's cuts as an export's chunks are, keyed by
the fingerprint of everything that draws its frames (timeline_model.range_fingerprint) and this recipe. An edit
changes only the fingerprints of the chunks it touched, so only those are drawn again. A chunk comes from, in order:
this cache; an export's or a review render's own chunk of the same pictures (render_queue's cache, read only), made
smaller; or the export engine (melt) at the light size. Picture only: the sound is always the timeline's own, on the
same frame.

Every encode takes its own PC-lock turn at below-normal priority, steps aside when another job waits for the lock,
stops while a spoken note is being written down (the editor's letitedit-speech-<pid>.busy marker) and when its window
closes. The cache is the app's own local folder with a size cap, an age limit and a free-space floor; exports and the
AI's checks never read it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401,E402  (no console windows)
import letitedit.core.render_lock as render_lock  # noqa: E402

GIB = 1024 ** 3
CACHE_LIMIT = 4 * GIB
MAX_AGE_S = 14 * 86400
SHORT_SIDE = 540
CHUNK_S = 8.0
RECIPE = 'pb2'                 # in every chunk's key: a change to how chunks are made starts afresh
STEP_ASIDE_BEFORE = 0.7        # a chunk less far along than this is stopped when another job waits for the lock
POLL_S = 0.1            # the encode loop answers commands this often (a pause for the player within a frame or three)
AUDIO_ONLY = {'volume', 'panner', 'mono', 'channelcopy', 'audiolevel', 'audiowaveform', 'loudness', 'dynamic_loudness',
              'lift_gamma_gain_audio', 'audioseam'}
HEAVY_FILTERS = 6              # picture filters at or above this: drawn from the start
HEAVY_TRACKS = 4               # or this many shown picture tracks
PREVIEW_ENV = 'LETITEDIT_PLAYBACK_PREVIEW'   # 'always' draws every timeline; 'off' none


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def command_lines(stream, poll_s=0.05):
    """The lines the editor sends. On Windows a pipe is read only when bytes are waiting in it: a thread blocked in a
    read on the stdin pipe stalls a library loading in another thread (numpy's start-up asks Windows about the
    standard handles and waits for that read to finish), so the reader never leaves a read pending."""
    handle = None
    if sys.platform == 'win32':
        try:
            import msvcrt
            import _winapi
            fd = stream.fileno()
            handle = msvcrt.get_osfhandle(fd)
            if _winapi.GetFileType(handle) != _winapi.FILE_TYPE_PIPE:
                handle = None
        except (AttributeError, OSError, ValueError, ImportError):
            handle = None
    if handle is None:
        yield from stream
        return
    pending = b''
    while True:
        try:
            waiting = _winapi.PeekNamedPipe(handle, 0)[0]
        except OSError:           # the editor closed its end
            break
        if not waiting:
            time.sleep(poll_s)
            continue
        data = os.read(fd, waiting)
        if not data:
            break
        pending += data
        *lines, pending = pending.split(b'\n')
        for line in lines:
            yield line.decode('utf-8', 'replace')
    if pending.strip():
        yield pending.decode('utf-8', 'replace')


def default_cache():
    from letitedit.footage.playback_copies import local_path
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise ValueError('LOCALAPPDATA is required for the playback preview cache')
    return local_path(Path(base) / 'letitedit' / 'playback-previews')


def light_size(width, height, short_side=SHORT_SIDE):
    """The preview's size: the shorter side at short_side (never larger than the project), even numbers."""
    import letitedit.timeline.render_queue as render_queue
    return render_queue.preview_size(width, height, short_side)


def x264():
    """The playback copies' picture settings (preset, CRF, keyframe spacing): a chunk looks as clean as a copy."""
    from letitedit.footage.playback_copies import X264_CRF, X264_GOP, X264_PRESET
    return X264_PRESET, X264_CRF, X264_GOP


def gop(fps=None):
    """A keyframe every few frames: a start in the middle of a chunk, or playing backwards, decodes only a few."""
    return x264()[2]


def heaviness(timeline):
    """How much the live player has to draw for each frame: picture filters and shown picture tracks."""
    import letitedit.timeline.timeline_model as tm
    filters = 0
    for element in timeline.root.iter('filter'):
        service = tm.props(element).get('mlt_service', '')
        if service and service not in AUDIO_ONLY:
            filters += 1
    for element in timeline.root.iter('link'):
        service = tm.props(element).get('mlt_service', '')
        if service and service not in AUDIO_ONLY and not service.startswith('timeremap'):
            filters += 1
    shown = [t for t in timeline.video_tracks() if 'video' not in (t.hide or '') and t.items]
    composites = sum(1 for tr in timeline.main.findall('transition')
                     if tm.props(tr).get('mlt_service', '') not in ('mix', ''))
    return {'picture_filters': filters, 'picture_tracks': len(shown), 'composites': composites,
            'heavy': filters >= HEAVY_FILTERS or len(shown) >= HEAVY_TRACKS}


def plan_chunks(timeline, size, chunk_s=CHUNK_S):
    """The chunks of the whole timeline: [{'i', 'a', 'b', 'fp', 'key'}], a and b timeline frames, b exclusive."""
    import letitedit.timeline.render_queue as render_queue
    last = timeline.frames - 1
    if last < 0:
        return []
    bounds = render_queue._plan_chunks(timeline, 0, last, chunk_s)
    out = []
    for i, (a, b) in enumerate(bounds):
        # stable: the same chunk keys whether the editor's playback copies are in or not (T220)
        fp = timeline.range_fingerprint(a, b, video=True, audio=False, visible_only=True, stable=True)
        out.append({'i': i, 'a': a, 'b': b, 'fp': fp, 'key': f'{fp}-{RECIPE}-{size[0]}x{size[1]}'})
    return out


_CANDIDATES = {}   # an export chunk's path, size, date and expected receipt -> whether it checked out


def _candidate(path, expected):
    import letitedit.timeline.chunk_cache as chunk_cache
    stat = path.stat()
    memo = (str(path), stat.st_size, stat.st_mtime_ns, json.dumps(expected, sort_keys=True))
    if memo not in _CANDIDATES:
        _CANDIDATES[memo] = chunk_cache.candidate(path, expected)
    return _CANDIDATES[memo]


def export_sources(timeline, chunks, chunks_dir=None, app=None):
    """For each chunk, an export's own validated chunk that draws the same pictures and covers it (render_queue's
    cache, any quality; read only), as {chunk index: {'file', 'a', 'b'}}. An export splits the timeline with one of
    render_queue.CHUNK_STEPS, so every step's split is fingerprinted and looked up."""
    import letitedit.timeline.chunk_cache as chunk_cache
    import letitedit.timeline.render_queue as render_queue
    folder = Path(chunks_dir) if chunks_dir else render_queue.CHUNKS
    if not folder.is_dir() or not chunks:
        return {}
    last = timeline.frames - 1
    renderer = chunk_cache.renderer_signature(Path(app) if app else render_queue.APP)
    found = {}
    wanted = {c['i']: c for c in chunks}
    for step in render_queue.CHUNK_STEPS:
        if not wanted:
            break
        if step > max(render_queue.CHUNK_STEPS[0], timeline.seconds):
            break
        for a, b in render_queue._plan_chunks(timeline, 0, last, step):
            inside = [c for c in wanted.values() if a <= c['a'] and c['b'] <= b]
            if not inside:
                continue
            fp = timeline.range_fingerprint(a, b, video=True, audio=False)
            for path in sorted(folder.glob(f'{fp}-*.mp4')):
                if '.partial.' in path.name:
                    continue
                expected = {'fingerprint': path.stem, 'renderer': renderer, 'frames': b - a}
                try:
                    if not _candidate(path, expected):
                        continue
                except Exception:  # noqa: BLE001  (a chunk being removed meanwhile)
                    continue
                for c in inside:
                    found[c['i']] = {'file': str(path), 'a': a, 'b': b}
                    wanted.pop(c['i'], None)
                break
    return found


def skeleton(timeline):
    """Every track's clips as (start, end, in, out, service): what a saved file and the window's timeline share."""
    import letitedit.timeline.timeline_model as tm
    return [(t.kind, t.index, t.hide, [(it.start, it.end, it.in_, it.out, tm.props(it.elem).get('mlt_service'))
                                       for it in t.items]) for t in timeline.tracks]


def saved_timeline(spec, timeline):
    """The project file the window has open, when the window has no unsaved changes and the file has the same clips
    in the same places: an export made from the file draws the same pictures."""
    import letitedit.timeline.timeline_model as tm
    project = spec.get('project')
    if not project or spec.get('modified') is not False or not Path(project).is_file():
        return None
    saved = tm.load(project)
    if saved.frames != timeline.frames or saved.profile != timeline.profile or skeleton(saved) != skeleton(timeline):
        return None
    return saved


STREAM_PROPERTIES = ('video_index', 'audio_index', 'vstream', 'astream')


def copies_folder():
    """The playback copies' folder the editor uses (LETITEDIT_PLAYBACK_CACHE, else the app's own)."""
    from letitedit.footage.playback_copies import default_cache, local_path
    folder = os.environ.get('LETITEDIT_PLAYBACK_CACHE')
    return local_path(folder) if folder else default_cache()


def ready_copy(folder, identity, size, rate, keep_rate=False):
    """A playback copy's file for this source at this size, by its receipt and length (the copy worker checked its
    bytes when it made it, and the editor plays it): one at the timeline's rate, else one at the source's own rate
    when that is no more than the timeline's (any rate for a clip played slowed: keep_rate)."""
    from letitedit.footage.playback_copies import cache_key, frame_rate, recipe
    for wanted in (((),) if keep_rate else ((rate[0],), ())):
        key = cache_key(identity, size, *wanted)
        path, receipt = Path(folder) / f'{key}.mp4', Path(folder) / f'{key}.json'
        try:
            record = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if (record.get('source') != identity or record.get('recipe') != recipe(size, *wanted)
                    or path.stat().st_size != record.get('copy_bytes')):
                continue
        except (OSError, ValueError, AttributeError):
            continue
        if not wanted and not keep_rate:
            video = next((s for s in record.get('streams', []) if s.get('codec_type') == 'video'), {})
            if frame_rate(video) > rate[1] + 0.01:
                return None
        return path
    return None


def copies_render_xml(xml, out, short_side, profile, folder=None):
    """The plan's timeline with every plain media clip drawn from its ready playback copy of the preview's size, as
    the live player draws it: chunks are drawn several times faster than from the originals (Rat: 4K and 60 fps
    phone footage). The chunks keep the originals' fingerprints. Returns the file, or None when no copy is ready.
    A clip played slowed (timewarp below 1x) takes a copy at its source's own rate, as the live player does."""
    import xml.etree.ElementTree as ET
    from letitedit.footage.playback_copies import SIZES, source_identity
    if short_side not in SIZES:
        return None
    try:
        folder = Path(folder) if folder else copies_folder()
    except ValueError:
        return None
    if not folder.is_dir():
        return None
    from letitedit.footage.playback_copies import parse_rate
    rate = parse_rate(f'{profile.get("frame_rate_num")}/{profile.get("frame_rate_den") or 1}')
    if not rate:
        return None
    tree = ET.parse(xml)
    found, swapped = {}, 0
    for element in tree.getroot().iter():
        if element.tag not in ('producer', 'chain'):
            continue
        properties = {p.get('name'): p for p in element.findall('property')}
        service = (properties.get('mlt_service').text or '') if 'mlt_service' in properties else ''
        warp = service == 'timewarp'
        resource = properties.get('warp_resource' if warp else 'resource')
        if (not warp and not service.startswith('avformat')) or resource is None or not (resource.text or '').strip():
            continue
        source = resource.text.strip()
        slowed = False
        if warp:
            try:
                slowed = abs(float(properties['warp_speed'].text or 1)) < 0.999 if 'warp_speed' in properties else False
            except ValueError:
                continue
        if (source, slowed) not in found:
            try:
                found[source, slowed] = ready_copy(folder, source_identity(source), short_side, rate, slowed)
            except OSError:
                found[source, slowed] = None
        copy = found[source, slowed]
        if not copy:
            continue
        resource.text = str(copy)
        if warp and 'resource' in properties:   # "<speed>:<file>"
            text = properties['resource'].text or ''
            properties['resource'].text = (text.split(':', 1)[0] + ':' if ':' in text else '') + str(copy)
        for name, element_property in properties.items():
            if name in STREAM_PROPERTIES or name.startswith('meta.'):
                element.remove(element_property)
        swapped += 1
    if not swapped:
        return None
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


SERVICES = ('producer', 'chain', 'playlist', 'tractor')


def slice_render_xml(render_file, out, a, b, margin=2):
    """The timeline melt draws one chunk from: every main-track entry away from frames a..b (and a margin) becomes a
    blank of its length, and the clips nothing then plays are left out. Positions don't move, so the chunk's frames
    are the same; melt opens a few files and their effects instead of the whole timeline's (Rat: 52 files and 123
    colour lookup tables, about a minute before each chunk's first frame). Returns the file, or None (the whole
    timeline is drawn instead)."""
    import xml.etree.ElementTree as ET
    import letitedit.timeline.timeline_model as tm
    tree = ET.parse(render_file)
    root = tree.getroot()
    profile = root.find('profile')
    if profile is None:
        return None
    fps = int(profile.get('frame_rate_num', 30)) / int(profile.get('frame_rate_den', 1))
    elements = {e.get('id'): e for e in root if e.get('id')}
    tractors = [e for e in root if e.tag == 'tractor']
    if not tractors:
        return None
    marked = [e for e in tractors if tm.props(e).get('shotcut') == '1']
    main = (marked or tractors)[-1]
    for track in main.findall('track'):
        playlist = elements.get(track.get('producer'))
        if playlist is None or playlist.tag != 'playlist':
            continue
        position = 0
        for index, entry in enumerate(list(playlist)):
            if entry.tag == 'blank':
                position += tm.clock_to_frames(entry.get('length'), fps) or 0
                continue
            if entry.tag != 'entry':
                continue
            source = elements.get(entry.get('producer'))
            first = tm.clock_to_frames(entry.get('in'), fps) or 0
            last = tm.clock_to_frames(entry.get('out'), fps)
            if last is None and source is not None:
                last = tm.clock_to_frames(source.get('out'), fps)
            if last is None:
                return None
            length = last - first + 1
            if position + length <= a - margin or position >= b + margin:
                blank = ET.Element('blank', length=str(length))
                blank.tail = entry.tail
                playlist.remove(entry)
                playlist.insert(index, blank)
            position += length
    kept, stack = set(), [main]
    if root.get('producer') in elements:
        stack.append(elements[root.get('producer')])
    while stack:
        element = stack.pop()
        if element.get('id') in kept:
            continue
        kept.add(element.get('id'))
        for child in element.iter():
            if child.tag in ('track', 'entry') and child.get('producer') in elements:
                stack.append(elements[child.get('producer')])
    for element in list(root):
        if element.tag in SERVICES and element.get('id') not in kept:
            root.remove(element)
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out


YIELD_HOLD_S = 10.0


def suspend(process, on):
    """Pause (on) or resume an encode in place; True when done. Windows only (elsewhere it keeps running)."""
    if os.name != 'nt':
        return False
    import ctypes
    try:
        call = ctypes.windll.ntdll.NtSuspendProcess if on else ctypes.windll.ntdll.NtResumeProcess
        return call(ctypes.c_void_p(int(process._handle))) == 0
    except (AttributeError, OSError, ValueError):
        return False


def count_frames(path, ffprobe):
    result = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                             'stream=nb_read_packets,width,height', '-of', 'json', str(path)], capture_output=True,
                            text=True, timeout=120, creationflags=render_lock.background_flags())
    try:
        stream = json.loads(result.stdout)['streams'][0]
        return int(stream['nb_read_packets']), (int(stream['width']), int(stream['height']))
    except (ValueError, KeyError, IndexError, TypeError):
        return -1, None


class Cache:
    """The preview chunks: <key>.mp4 with a <key>.json receipt, leases for the windows using them, a cap and a floor."""

    def __init__(self, folder, limit=CACHE_LIMIT, free_floor=None, owner_pid=None):
        from letitedit.footage.playback_copies import local_path
        import letitedit.core.cache_budget as cache_budget
        if free_floor is None:          # the drive room kept free: letitedit's own (cache_budget.reserve_bytes)
            free_floor = cache_budget.reserve_bytes()
        self.folder = local_path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.limit, self.free_floor, self.owner_pid = limit, free_floor, owner_pid
        self._verified = {}

    def path(self, key):
        return self.folder / f'{key}.mp4'

    def ready(self, chunk):
        """The chunk's file when its receipt matches it (the bytes' digest once per file and date)."""
        path, receipt = self.path(chunk['key']), self.folder / f'{chunk["key"]}.json'
        try:
            record = json.loads(receipt.read_text(encoding='utf-8-sig'))
            stat = path.stat()
            if (record.get('key') != chunk['key'] or record.get('frames') != chunk['b'] - chunk['a']
                    or record.get('bytes') != stat.st_size):
                return None
            stamp = (stat.st_size, stat.st_mtime_ns)
            if self._verified.get(str(path)) != stamp:
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != record.get('sha256'):
                        return None
                self._verified[str(path)] = stamp
            return record
        except (OSError, ValueError, AttributeError):
            return None

    def touch(self, chunks):
        for chunk in chunks:
            try:
                os.utime(self.path(chunk['key']), None)
                self._verified[str(self.path(chunk['key']))] = (self.path(chunk['key']).stat().st_size,
                                                                 self.path(chunk['key']).stat().st_mtime_ns)
            except OSError:
                pass

    def publish(self, part, chunk, record):
        target = self.path(chunk['key'])
        with part.open('rb') as stream:
            record['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        record['bytes'] = part.stat().st_size
        os.replace(part, target)
        receipt = self.folder / f'{chunk["key"]}.json.partial'
        receipt.write_text(json.dumps(record), encoding='utf-8')
        os.replace(receipt, self.folder / f'{chunk["key"]}.json')
        stat = target.stat()
        self._verified[str(target)] = (stat.st_size, stat.st_mtime_ns)
        return record

    def lease(self, keys):
        if not self.owner_pid:
            return
        lease = self.folder / f'lease-{self.owner_pid}-{os.getpid()}.json'
        partial = lease.with_suffix('.partial')
        partial.write_text(json.dumps({'pid': self.owner_pid, 'keys': sorted(keys)}), encoding='utf-8')
        os.replace(partial, lease)

    def drop_lease(self):
        if self.owner_pid:
            (self.folder / f'lease-{self.owner_pid}-{os.getpid()}.json').unlink(missing_ok=True)

    def used(self):
        total = 0
        for path in self.folder.rglob('*'):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                pass
        return total

    def free(self):
        return shutil.disk_usage(self.folder).free

    def cleanup(self, protected=(), reserve=0):
        """Remove chunks past the age limit, then the least recently used until the cache is under its cap and the
        disk above its floor, never a chunk a live window's lease names. False when that still isn't enough."""
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
        for leftover in list(self.folder.glob('work-*')) + list(self.folder.glob('*.partial*')):
            try:
                if time.time() - leftover.stat().st_mtime > 86400:
                    shutil.rmtree(leftover) if leftover.is_dir() else leftover.unlink()
            except OSError:
                pass
        entries = []
        for path in self.folder.glob('*.mp4'):
            try:
                entries.append((path.stat().st_mtime, path))
            except OSError:
                pass
        used = self.used()
        for mtime, path in sorted(entries):
            if path.stem in protected:
                continue
            old = time.time() - mtime > MAX_AGE_S
            if not old and used + reserve <= self.limit and self.free() - reserve >= self.free_floor:
                continue
            try:
                size = path.stat().st_size
                path.unlink()
                path.with_suffix('.json').unlink(missing_ok=True)
                used -= size
                self._verified.pop(str(path), None)
            except OSError:
                pass
        return used + reserve <= self.limit and self.free() - reserve >= self.free_floor


class Worker:
    def __init__(self, cache, app, owner_pid=None, out=None, chunks_dir=None):
        self.cache = cache
        self.app = Path(app)
        self.melt = self.app / 'melt.exe'
        self.ffmpeg = self.app / 'ffmpeg.exe'
        self.ffprobe = self.app / 'ffprobe.exe'
        self.owner_pid = owner_pid
        self.out = out or sys.stdout
        self.chunks_dir = chunks_dir
        self.commands = queue.Queue()
        self.work = self.cache.folder / f'work-{os.getpid()}'
        self.work.mkdir(parents=True, exist_ok=True)
        self.plan = None                # the newest plan: {'generation', 'xml', 'chunks', 'size', 'fps', ...}
        self.render = True
        self.force = os.environ.get(PREVIEW_ENV) == 'always'
        self.never = os.environ.get(PREVIEW_ENV) == 'off'
        self.focus = 0
        self.stopping = False
        self.failed = {}                # chunk key -> times it failed
        self.sources = {}
        self.copies = os.environ.get('LETITEDIT_PLAYBACK_CACHE') or None  # None: the app's own copies folder
        # T220: the player is playing frames it draws live: drawing gives way (no new chunk; a running one is paused)
        self.yielding = False

    # ------------------------------------------------------------------ talking to the editor
    def say(self, **event):
        try:
            self.out.write(json.dumps(event) + '\n')
            self.out.flush()
        except (OSError, ValueError):
            self.stopping = True

    def read_commands(self, stream):
        for line in command_lines(stream):
            line = line.strip()
            if not line:
                continue
            try:
                self.commands.put(json.loads(line))
            except ValueError:
                continue
        self.commands.put({'stop': True})

    def owner_alive(self):
        return not self.owner_pid or render_lock.pid_alive(self.owner_pid)

    def speech_busy(self):
        return bool(self.owner_pid and (Path(tempfile.gettempdir()) /
                                        f'letitedit-speech-{self.owner_pid}.busy').exists())

    def handle(self, command):
        """Apply one command; True when it changed the plan."""
        if command.get('stop'):
            self.stopping = True
            return True
        changed = False
        if 'render' in command:
            self.render = bool(command['render'])
        if 'yield' in command:
            self.yielding = bool(command['yield'])
        if command.get('force'):
            self.force = True
        if 'focus' in command:
            try:
                self.focus = max(0, int(command['focus']))
            except (TypeError, ValueError):
                pass
        plan = command.get('plan')
        if isinstance(plan, dict):
            for name in ('render', 'focus'):
                if name in plan:
                    self.handle({name: plan[name]})
            # each plan says whether a light timeline is drawn too (the editor's sharp ahead draws one in the main player,
            # Review keeps the light preview it was made with)
            self.force = bool(plan.get('force')) or os.environ.get(PREVIEW_ENV) == 'always'
            self.new_plan(plan)
            changed = True
        return changed

    def drain(self, block_s=0.0):
        """Take every waiting command; True when one changed the plan or stops the worker."""
        changed = False
        try:
            command = self.commands.get(timeout=block_s) if block_s else self.commands.get_nowait()
        except queue.Empty:
            return False
        while True:
            changed = self.handle(command) or changed
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return changed

    # ------------------------------------------------------------------ the plan
    def new_plan(self, spec):
        import letitedit.timeline.timeline_model as tm
        generation = int(spec.get('generation') or 0)
        xml = self.work / f'plan-{generation}.mlt'
        text = spec.get('xml') or ''
        if spec.get('xml_file'):
            text = Path(spec['xml_file']).read_text(encoding='utf-8')
        xml.write_text(text, encoding='utf-8')
        render_xml = None
        if spec.get('render_xml'):
            render_xml = self.work / f'plan-{generation}-render.mlt'
            render_xml.write_text(spec['render_xml'], encoding='utf-8')
        try:
            timeline = tm.load(xml)
        except Exception as error:  # noqa: BLE001
            self.plan = None
            self.say(event='error', generation=generation, error=f'{type(error).__name__}: {error}'[:300])
            return
        # the size of the editor's Settings > Playback Quality (the copies' size); 540 for an editor that doesn't say
        short = spec.get('short_side') if spec.get('short_side') in (540, 720, 1080) else SHORT_SIDE
        copies = 0
        if render_xml is None and spec.get('short_side') in (540, 720, 1080):
            try:
                render_xml = copies_render_xml(xml, self.work / f'plan-{generation}-render.mlt', short,
                                               timeline.profile, self.copies)
            except Exception:  # noqa: BLE001  (drawn from the originals instead)
                render_xml = None
            copies = 1 if render_xml else 0
        for old in self.work.glob('plan-*.mlt'):
            if old not in (xml, render_xml) and (not self.plan or str(old) != self.plan.get('render_file')):
                old.unlink(missing_ok=True)
        size = light_size(timeline.profile['width'], timeline.profile['height'], short)
        chunks = plan_chunks(timeline, size)
        weight = heaviness(timeline)
        for chunk in chunks:
            chunk['file'] = str(self.cache.path(chunk['key']))
            chunk['ready'] = self.cache.ready(chunk) is not None
        self.cache.touch([c for c in chunks if c['ready']])
        self.cache.lease({c['key'] for c in chunks})
        self.sources = {}
        missing = [c for c in chunks if not c['ready']]
        # an export of the window's own timeline, then, when the window has no unsaved changes, of the saved file
        # (the editor writes the same timeline differently from the file, so their fingerprints differ)
        for lookup in (lambda: timeline, lambda: saved_timeline(spec, timeline)):
            wanted = [c for c in missing if c['i'] not in self.sources]
            if not wanted:
                break
            try:
                source = lookup()
                if source is not None:
                    self.sources.update(export_sources(source, wanted, self.chunks_dir, self.app))
            except Exception:  # noqa: BLE001  (a look-up that fails only costs a render)
                pass
        self.plan = {'generation': generation, 'xml': str(xml), 'render_file': str(render_xml or xml),
                     'chunks': chunks, 'size': size, 'fps': timeline.fps,
                     'profile': timeline.profile, 'weight': weight, 'started': time.monotonic(), 'rendered': 0,
                     'reused': 0, 'announced_done': False}
        self.say(event='plan', generation=generation, size=list(size), fps=timeline.fps, frames=timeline.frames,
                 light=not self.wanted(), weight=weight, from_copies=bool(copies),
                 chunks=[{k: c[k] for k in ('i', 'a', 'b', 'file', 'ready')} for c in chunks],
                 exports=sorted(self.sources))
        self.announce_done()

    def wanted(self):
        """Whether this timeline gets a preview drawn: heavy to draw live, or asked for."""
        if self.never or not self.plan:
            return False
        return self.force or self.plan['weight']['heavy']

    def next_chunk(self):
        if not self.plan:
            return None
        pending = [c for c in self.plan['chunks'] if not c['ready'] and self.failed.get(c['key'], 0) < 2]
        if not pending:
            return None
        ahead = [c for c in pending if c['b'] > self.focus]
        behind = [c for c in pending if c['b'] <= self.focus]
        return (ahead + list(reversed(behind)))[0]

    def publish_ready(self, key):
        """Tell the editor about a chunk just made, in the plan as it is now (it may have changed meanwhile)."""
        if not self.plan:
            return
        for chunk in self.plan['chunks']:
            if chunk['key'] != key or chunk['ready']:
                continue
            record = self.cache.ready(chunk) or {}
            if not record:
                continue
            chunk['ready'] = True
            self.plan['rendered'] += 1
            if record.get('made_by') == 'export':
                self.plan['reused'] += 1
            self.say(event='ready', generation=self.plan['generation'], i=chunk['i'], a=chunk['a'], b=chunk['b'],
                     file=chunk['file'], made_by=record.get('made_by'), seconds=record.get('seconds'))
        self.announce_done()

    def announce_done(self):
        plan = self.plan
        if plan and not plan['announced_done'] and all(c['ready'] for c in plan['chunks']):
            plan['announced_done'] = True
            self.say(event='done', generation=plan['generation'], seconds=round(time.monotonic() - plan['started'], 3),
                     rendered=plan['rendered'], reused=plan['reused'],
                     bytes=sum(Path(c['file']).stat().st_size for c in plan['chunks'] if Path(c['file']).exists()))

    # ------------------------------------------------------------------ making a chunk
    def command_for(self, chunk, part):
        plan = self.plan
        size, fps = plan['size'], plan['fps']
        source = self.sources.get(chunk['i'])
        preset, crf, keyframes = x264()
        if source and Path(source['file']).exists():
            offset = (chunk['a'] - source['a'] - 0.5) / fps
            command = [str(self.ffmpeg), '-nostdin', '-hide_banner', '-v', 'error', '-threads', '4']
            if chunk['a'] > source['a']:
                command += ['-ss', f'{max(0.0, offset):.6f}']
            command += ['-i', source['file'], '-map', '0:v:0', '-an', '-frames:v', str(chunk['b'] - chunk['a']),
                        '-vf', f'scale={size[0]}:{size[1]}:flags=bicubic', '-c:v', 'libx264', '-preset', preset,
                        '-crf', str(crf), '-g', str(keyframes), '-bf', '0', '-pix_fmt', 'yuv420p',
                        '-threads:v', '4', '-movflags', '+faststart', '-f', 'mp4', str(part)]
            return 'export', command
        import letitedit.timeline.render_queue as render_queue
        args = render_queue.preview_args(plan['profile'], size)
        timeline = plan['render_file']
        try:
            timeline = slice_render_xml(timeline, self.work / f'chunk-{chunk["key"]}.mlt', chunk['a'], chunk['b'])                 or timeline
        except Exception:  # noqa: BLE001  (the whole timeline instead)
            pass
        command = [str(self.melt), '-progress', str(timeline), f'in={chunk["a"]}', f'out={chunk["b"] - 1}',
                   '-consumer', f'avformat:{part}', 'vcodec=libx264', f'preset={preset}', f'crf={crf}',
                   f'g={keyframes}', 'bf=0', 'pix_fmt=yuv420p', 'movflags=+faststart', *args, 'an=1', 'audio_off=1',
                   'real_time=-2', 'threads=4']
        return 'melt', command

    def make(self, chunk):
        """Make one chunk in a PC-lock turn of its own. Returns 'ready', 'again' (stopped to make way; try again)
        or 'failed'."""
        generation = self.plan['generation']
        if not self.cache.cleanup({c['key'] for c in self.plan['chunks']}, reserve=64 * 1024 ** 2):
            self.say(event='paused', why='space', generation=generation)
            return 'space'
        part = self.work / f'{chunk["key"]}.partial.mp4'
        how, command = self.command_for(chunk, part)
        started = time.monotonic()

        def give_up():
            return (self.stopping or not self.owner_alive() or self.speech_busy() or self.drain()
                    or not self.render)

        try:
            holder = render_lock.acquire('letitedit playback preview', timeout_s=None, poll_s=2,
                                         caller_pids=render_lock.ancestors(), cancelled=give_up)
        except render_lock.Cancelled:
            return 'again'
        try:
            if give_up():
                return 'again'
            outcome = self.run(command, part, step_aside=how == 'melt')
        finally:
            render_lock.release(holder)
            (self.work / f'chunk-{chunk["key"]}.mlt').unlink(missing_ok=True)
        if outcome != 'ok':
            part.unlink(missing_ok=True)
            if outcome == 'failed':
                self.failed[chunk['key']] = self.failed.get(chunk['key'], 0) + 1
                if how == 'export':
                    self.sources.pop(chunk['i'], None)       # draw it with the engine instead
                    self.failed[chunk['key']] -= 1
                self.say(event='failed', generation=generation, i=chunk['i'], how=how)
                return 'failed'
            return 'again'
        frames, size = count_frames(part, self.ffprobe)
        if frames != chunk['b'] - chunk['a'] or (size and list(size) != list(self.plan['size'])):
            part.unlink(missing_ok=True)
            self.failed[chunk['key']] = self.failed.get(chunk['key'], 0) + 1
            if how == 'export':
                self.sources.pop(chunk['i'], None)
                self.failed[chunk['key']] -= 1
            self.say(event='failed', generation=generation, i=chunk['i'], how=how, frames=frames)
            return 'failed'
        record = {'version': 1, 'key': chunk['key'], 'fingerprint': chunk['fp'], 'recipe': RECIPE,
                  'frames': chunk['b'] - chunk['a'], 'size': list(self.plan['size']), 'fps': self.plan['fps'],
                  'made_by': how, 'seconds': round(time.monotonic() - started, 3), 'created': now()}
        self.cache.publish(part, chunk, record)
        return 'ready'

    def run(self, command, part, step_aside=True):
        """Run one encode, polling: 'ok', 'failed', or 'again' when it was stopped (speech, a newer plan, the window
        closed, another job waiting for the lock early in the chunk)."""
        progress = [0]
        log = self.work / 'encode.log'
        with log.open('w', encoding='utf-8', errors='replace') as sink:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, cwd=str(self.app), text=True, encoding='utf-8',
                                       errors='replace', creationflags=render_lock.background_flags())

            def pump():
                buffer = ''
                for text in iter(lambda: process.stdout.read(256), ''):
                    buffer += text
                    lines = re.split(r'[\r\n]', buffer)
                    buffer = lines.pop()
                    for line in lines:
                        found = re.search(r'percentage:\s*(\d+)', line)
                        if found:
                            progress[0] = int(found.group(1))
                        elif line.strip():
                            sink.write(line + '\n')
            reader = threading.Thread(target=pump, daemon=True)
            reader.start()
            checked = 0.0
            paused_since = None
            try:
                while process.poll() is None:
                    time.sleep(POLL_S)
                    if self.stopping or not self.owner_alive() or self.speech_busy() or not self.render:
                        return 'again'
                    # the player plays live frames: the encode waits, suspended, and goes on where it was (T220)
                    if self.yielding and paused_since is None and suspend(process, True):
                        paused_since = time.monotonic()
                    elif not self.yielding and paused_since is not None:
                        suspend(process, False)
                        paused_since = None
                    if self.drain() and self.plan_drops(part):
                        return 'again'
                    if time.monotonic() - checked > 1.0:
                        checked = time.monotonic()
                        try:
                            waiting = render_lock.info().get('waiting')
                        except Exception:  # noqa: BLE001
                            waiting = 0
                        if step_aside and waiting and progress[0] < STEP_ASIDE_BEFORE * 100:
                            return 'again'
                        # paused for a while with another job waiting for the PC lock: let it go
                        if waiting and paused_since is not None and time.monotonic() - paused_since > YIELD_HOLD_S:
                            return 'again'
                reader.join(5)
                return 'ok' if process.returncode == 0 and part.exists() else 'failed'
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                reader.join(5)

    def plan_drops(self, part):
        """After a new plan: True when the chunk being made is no longer in it."""
        if self.stopping or not self.plan:
            return True
        key = part.name.split('.partial')[0]
        return not any(c['key'] == key and not c['ready'] for c in self.plan['chunks'])

    # ------------------------------------------------------------------ the loop
    def loop(self):
        while not self.stopping:
            if not self.owner_alive():
                break
            chunk = self.next_chunk() if (self.render and self.wanted() and not self.yielding) else None
            if chunk is None or self.speech_busy():
                self.drain(block_s=0.5)
                continue
            outcome = self.make(chunk)
            if outcome == 'ready':
                self.publish_ready(chunk['key'])
            elif outcome == 'space':
                self.drain(block_s=30)
            elif outcome == 'again':
                self.drain(block_s=0.5)
        self.cache.drop_lease()
        shutil.rmtree(self.work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-pid', type=int)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--app', type=Path, help='the folder with melt.exe, ffmpeg.exe and ffprobe.exe')
    parser.add_argument('--chunks', type=Path, help="an export cache's chunks folder to reuse (read only)")
    args = parser.parse_args(argv)
    render_lock.below_normal()
    import letitedit.timeline.render_queue as render_queue     # the fonts the engine draws with (font_env), and the export engine's settings
    import letitedit.timeline.chunk_cache as chunk_cache      # noqa: F401  (loaded before the reader starts: numpy's libraries load here, not later)
    import letitedit.timeline.timeline_model as timeline_model   # noqa: F401
    app = args.app or render_queue.APP
    cache = Cache(args.cache or default_cache(), owner_pid=args.owner_pid)
    worker = Worker(cache, app, owner_pid=args.owner_pid, chunks_dir=args.chunks)
    reader = threading.Thread(target=worker.read_commands, args=(sys.stdin,), daemon=True)
    reader.start()
    worker.say(event='hello', cache=str(cache.folder), pid=os.getpid())
    worker.loop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
