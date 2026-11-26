"""Read a saved Shotcut/MLT project into a small model that tools can reason about without the editor.

Gives the profile, every track with its items at absolute timeline positions, subtitle feeds and
timeline-level filters, plus stable fingerprints of any time range (used by the chunked render cache).
Pure Python; never modifies the project.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Properties that change without changing what a frame looks like.
VOLATILE = {'xml', 'shotcut:hash', 'shotcut:caption', 'shotcut:detail', 'meta.shotcut.vui', 'shotcut:skipConvert',
            'shotcut:projectFolder', 'shotcut:projectAudioChannels', 'shotcut:processingMode', 'xml_retain',
            'letitedit_ai:id'}
# Properties a clip may or may not carry with the value it has anyway (the editor writes them when it reads a clip
# again); a stable fingerprint counts them only when they say something else.
STABLE_DEFAULTS = {'astream': '0', 'vstream': '0'}


# canon's full text is built up to this many characters copied (ordinary projects stay far below it); past it, a graph
# that shares elements is fingerprinted element by element instead (see Timeline.canon)
CANON_BUDGET = 8_000_000
UNAVAILABLE = '<unavailable '

# What a frame reads from files: every property whose value names a file (a clip's video or picture, a colour grade's
# look-up table, a mask, a luma, a caption or font file, anything else) adds a mark of that file to canon's text. A file
# up to CONTENT_HASH_BYTES is marked by its size and the digest of its bytes, so new bytes under the same name, size or
# date count and a file written again with the same bytes doesn't; a bigger one (footage) by its size and date, as
# before (reading gigabytes of footage at every export would cost more than it saves). A value that looks like a file
# and isn't one is marked missing, so the file appearing later counts too; one that can't be read is marked so it
# matches nothing (fail closed). Digests are kept for the process by path, size and date (_DIGESTS).
CONTENT_HASH_BYTES = 20 * 1024 * 1024
_DIGESTS = {}
_DIGESTS_KEPT = 4096
_DRIVE_OR_ROOT = re.compile(r'^(?:[A-Za-z]:[\\/]|[\\/])')
_EXTENSION = re.compile(r'\.[A-Za-z][A-Za-z0-9]{0,7}$')


def _content_digest(path, st):
    key = (path, st.st_size, st.st_mtime_ns)
    found = _DIGESTS.get(key)
    if found is None:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        found = h.hexdigest()[:32]
        if len(_DIGESTS) >= _DIGESTS_KEPT:
            _DIGESTS.clear()
        _DIGESTS[key] = found
    return found


# canon writes names and values between its own separators ("|" between parts, "@" before an attribute, "=" after a
# name, "{...}" around an effect, "<entry ...>" before what it points at and _END after it, "#" before a digest or a
# file mark), and the text reads back one way only. A name holding a separator is escaped with a character XML can
# never hold. A value ends at the next "|", at a "}" it didn't open, or at _END, so a value holding "|", that character
# or braces that don't pair is escaped whole; one with paired braces (JSON) or none is written as it always was. So no
# value can pass for structure ("Title|size=100" as one value is not "Title" and a "size" property; a label can't pass
# for an effect's digest), and what an entry or track points at ends with _END (a track's own effect is not its last
# clip's). A cut's own effects (an <entry> holding filters) follow what it points at after _CUT, and each property is
# written with the value the engine reads (property_value: a `value` attribute, the text, or nested XML); a project
# with neither is written as it always was.
_ESCAPE = '\x01'
_END = _ESCAPE + 'e'
_CUT = _ESCAPE + 'c'      # before an entry's own effects (written only when it has any)
_IN_VALUE = str.maketrans({_ESCAPE: _ESCAPE + '0', '|': _ESCAPE + '1', '{': _ESCAPE + '2', '}': _ESCAPE + '3'})
_IN_NAME = str.maketrans({_ESCAPE: _ESCAPE + '0', '|': _ESCAPE + '1', '{': _ESCAPE + '2', '}': _ESCAPE + '3',
                          '=': _ESCAPE + '4', '#': _ESCAPE + '5', '<': _ESCAPE + '6', '>': _ESCAPE + '7',
                          ',': _ESCAPE + '8', '@': _ESCAPE + '9'})


def _paired(text):
    depth = 0
    for character in text:
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _value(text):
    text = str(text)
    if '|' in text or _ESCAPE in text or (('{' in text or '}' in text) and not _paired(text)):
        return text.translate(_IN_VALUE)
    return text


def _name(text):
    return str(text).translate(_IN_NAME)


class _CanonTooBig(Exception):
    pass


def unavailable():
    """A canonical text for what can't be described in full (too deep to follow): unique, so it matches nothing."""
    import uuid
    return f'{UNAVAILABLE}{uuid.uuid4().hex}>'


# The engine's number reading (C, ASCII only): atoi/strtol skip leading white space, take a sign and the digits that
# follow; strtod also takes a point, a fraction and an exponent (the C locale: a comma ends the number)
_C_SPACE = ' \t\n\v\f\r'
_C_INT = re.compile(r'[+-]?[0-9]+', re.ASCII)
_C_FLOAT = re.compile(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', re.ASCII)


def _c_int(text):
    match = _C_INT.match(text.lstrip(_C_SPACE))
    return int(match.group()) if match else 0


def _c_float(text):
    match = _C_FLOAT.match(text.lstrip(_C_SPACE))
    return float(match.group()) if match else 0.0


def _split_last(text, separator):
    head, _, tail = text.rpartition(separator)
    return head, tail


def clock_to_frames(value, fps):
    """MLT time value -> frame number, as the engine reads a position (mlt_property.c, mlt_property_atoi): with a ":"
    and a "." or "," a clock, H:M:S.s (floor of the hours' frames, plus floor of the minutes' frames, plus the
    seconds' frames rounded half to even); with a ":" and neither a timecode, H:M:S:F (floor, floor, the seconds'
    frames rounded up, plus the frames; a ";" may stand before the frames); anything else a whole number of frames,
    the digits it starts with ("12.7" is 12). Fewer parts fill from the right ("02:02.005" is minutes and seconds,
    "10:05" seconds and frames). Text with no number in front is 0, as the engine reads it ("abc", other scripts'
    digits), and "0x.." hex. None for no value; ValueError for a colour ("#...")."""
    if value is None or value == '':
        return None
    text = str(value)
    if text.startswith('#'):                            # a colour to the engine, never a time
        raise ValueError(f'Unrecognised MLT time: {value}')
    if text.startswith('0x'):                           # hex (strtoul)
        match = re.match(r'[0-9a-fA-F]+', text[2:])
        return int(match.group(), 16) if match else 0
    if fps > 0 and ':' in text:
        if '.' in text or ',' in text:                  # time_clock_to_frames
            rest, seconds = _split_last(text, ':')
            seconds = _c_float(seconds)
            hours, minutes = _split_last(rest, ':') if ':' in rest else ('0', rest)
            hours, minutes = _c_int(hours), _c_int(minutes)
            return math.floor(fps * hours * 3600) + math.floor(fps * minutes * 60) + round(fps * seconds)
        rest, frames = _split_last(text, ';' if ';' in text else ':')     # time_code_to_frames
        hours = minutes = seconds = 0
        if ':' in rest:
            rest, seconds = _split_last(rest, ':')
            if ':' in rest:
                hours, minutes = _split_last(rest, ':')
            else:
                minutes = rest
        else:
            seconds = rest
        hours, minutes, seconds, frames = (_c_int(str(x)) for x in (hours, minutes, seconds, frames))
        return (math.floor(fps * hours * 3600) + math.floor(fps * minutes * 60) + math.ceil(fps * seconds)
                + frames)
    return _c_int(text)                                 # strtol, base 10: the digits it starts with, else 0


def frames_to_clock(frames, fps):
    """Frame number -> "HH:MM:SS.mmm", as the engine writes a clock (mlt_property.c, time_clock_from_frames): whole
    hours and minutes first, then the seconds left, so clock_to_frames (and the engine) reads it back as the same
    frame at any rate. A negative or fractional frame is written as its time in milliseconds, as before."""
    if frames < 0 or frames != int(frames) or not fps > 0:
        ms = int(round(frames * 1000 / fps))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}'
    frames = int(frames)
    original = frames
    hours = int(min(max(frames / (fps * 3600), 0), 999999))
    frames -= math.floor(hours * 3600 * fps)
    minutes = int(min(max(frames / (fps * 60), 0), 60))
    if minutes == 60:
        hours += 1
        frames = original - math.floor(hours * 3600 * fps)
        minutes = 0
    before = frames
    frames -= math.floor(minutes * 60 * fps)
    seconds = min(max(frames / fps, 0), 60)
    if seconds >= 60.0:
        minutes += 1
        frames = before - math.floor(minutes * 60 * fps)
        seconds = frames / fps
    return f'{hours:02d}:{minutes:02d}:{seconds:06.3f}'


def property_value(prop):
    """A <property>'s value as the engine reads it (producer_xml.c: on_start_property sets the `value` attribute, or
    nothing; on_characters appends the text; on_end_property replaces it with nested XML, written out, when there is
    any). A property written as plain text (all the editor writes) gives its text, as it always has."""
    if len(prop):
        return '<?xml version="1.0"?>\n' + ''.join(ET.tostring(child, encoding='unicode') for child in prop)
    return (prop.get('value') or '') + (prop.text or '')


def props(elem):
    return {p.get('name'): property_value(p) for p in elem.findall('property')}


def parse_srt(text):
    """SRT text -> [(start_s, end_s, text)]."""
    cues = []
    for block in re.split(r'\n\s*\n', (text or '').replace('\r', '').strip()):
        lines = block.strip().split('\n')
        for i, line in enumerate(lines):
            m = re.match(r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', line)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                cues.append((a, b, '\n'.join(lines[i + 1:]).strip()))
                break
    return cues


@dataclass
class Item:
    track: int
    start: int            # timeline frame where the item begins
    length: int           # frames on the timeline
    producer_id: str
    in_: int
    out: int
    service: str = ''
    resource: str = ''
    caption: str = ''
    speed: float = 1.0
    filters: list = field(default_factory=list)   # [{'service','id','props'}]
    elem: ET.Element | None = None
    entry: ET.Element | None = None   # the playlist's <entry> (its own effects, when it has any)

    @property
    def end(self):
        return self.start + self.length

    @property
    def name(self):
        return self.caption or os.path.basename(self.resource) or self.service


@dataclass
class Track:
    index: int            # position in the main tractor (0 is the background)
    name: str
    kind: str             # 'video' or 'audio'
    hide: str
    items: list = field(default_factory=list)
    elem: ET.Element | None = None


class Timeline:
    def __init__(self, path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()
        prof = self.root.find('profile')
        if prof is None:
            raise ValueError('Project has no <profile>')
        num, den = int(prof.get('frame_rate_num', 30)), int(prof.get('frame_rate_den', 1))
        self.profile = {'width': int(prof.get('width')), 'height': int(prof.get('height')), 'fps': num / den,
                        'frame_rate_num': num, 'frame_rate_den': den,
                        'progressive': prof.get('progressive', '1'), 'colorspace': prof.get('colorspace', '709'),
                        'sample_aspect_num': prof.get('sample_aspect_num', '1'), 'sample_aspect_den': prof.get('sample_aspect_den', '1'),
                        'display_aspect_num': prof.get('display_aspect_num'), 'display_aspect_den': prof.get('display_aspect_den')}
        self.fps = self.profile['fps']
        self.elements = {e.get('id'): e for e in self.root if e.get('id')}
        tractors = [e for e in self.root if e.tag == 'tractor']
        if not tractors:
            raise ValueError('Project has no tractor (not a multitrack timeline)')
        marked = [t for t in tractors if props(t).get('shotcut') == '1']
        self.main = (marked or tractors)[-1]
        self.tracks = []
        for i, tr in enumerate(self.main.findall('track')):
            pl = self.elements.get(tr.get('producer'))
            if pl is None or pl.tag != 'playlist' or tr.get('producer') == 'background':
                continue
            pp = props(pl)
            hide = tr.get('hide', '')
            kind = 'audio' if (pp.get('shotcut:audio') == '1' or hide == 'video') else 'video'
            track = Track(index=i, name=pp.get('shotcut:name', f'T{i}'), kind=kind, hide=hide, elem=pl)
            pos = 0
            for e in pl:
                if e.tag == 'blank':
                    pos += clock_to_frames(e.get('length'), self.fps)
                elif e.tag == 'entry':
                    src = self.elements.get(e.get('producer'))
                    a = clock_to_frames(e.get('in'), self.fps) or 0
                    b = clock_to_frames(e.get('out'), self.fps)
                    if b is None and src is not None:
                        b = (clock_to_frames(src.get('out'), self.fps) or 0)
                    n = b - a + 1
                    sp = props(src) if src is not None else {}
                    service = sp.get('mlt_service', src.tag if src is not None else '')
                    resource = sp.get('warp_resource') or sp.get('resource', '')
                    speed = float(sp.get('warp_speed') or 1.0)
                    flt = []
                    if src is not None:
                        for f in list(src.findall('filter')) + list(src.findall('link')):
                            fp = props(f)
                            flt.append({'service': fp.get('mlt_service', ''), 'id': fp.get('shotcut:filter', ''), 'props': fp, 'tag': f.tag})
                    track.items.append(Item(track=i, start=pos, length=n, producer_id=e.get('producer'), in_=a, out=b,
                                            service=service if src is None or src.tag != 'tractor' else 'transition',
                                            resource=resource, caption=sp.get('shotcut:caption', ''), speed=speed,
                                            filters=flt, elem=src, entry=e))
                    pos += n
            self.tracks.append(track)
        self.frames = (clock_to_frames(self.main.get('out'), self.fps) or 0) - (clock_to_frames(self.main.get('in'), self.fps) or 0) + 1
        if self.frames <= 1:
            self.frames = max([t.items[-1].end for t in self.tracks if t.items] or [0])
        self.subtitle_feeds, self.burn_filters, self.master_filters = {}, [], []
        for f in self.main.findall('filter'):
            fp = props(f)
            svc = fp.get('mlt_service', '')
            if svc == 'subtitle_feed':
                self.subtitle_feeds[fp.get('feed', 'Subtitles')] = parse_srt(fp.get('text', ''))
            elif svc == 'subtitle':
                self.burn_filters.append(fp)
            else:
                self.master_filters.append(fp)

    # ------------------------------------------------------------------ helpers
    @property
    def seconds(self):
        return self.frames / self.fps

    def video_tracks(self):
        return [t for t in self.tracks if t.kind == 'video']

    def audio_tracks(self):
        return [t for t in self.tracks if t.kind == 'audio']

    def v1(self):
        vids = self.video_tracks()
        return vids[0] if vids else None

    def item_at(self, frame, track=None):
        """Topmost visible video item at a frame (or the item on a given track)."""
        tracks = [track] if track is not None else list(reversed(self.video_tracks()))
        for t in tracks:
            if 'video' in (t.hide or ''):
                continue
            for it in t.items:
                if it.start <= frame < it.end and it.service != 'blank':
                    return it
        return None

    def cut_points(self):
        """Frames where a V1 clip starts (excluding 0)."""
        v1 = self.v1()
        return sorted({it.start for it in v1.items if it.start > 0}) if v1 else []

    # ------------------------------------------------------------------ fingerprints
    def canon(self, elem, depth=0, stable=False):
        """Canonical text of an element and everything it references (ids and volatile properties removed).
        stable: also the same when the clip is written another way: its properties in any order, a length as a clock
        time, a path with forward slashes, a creation time, a default stream number (the editor's playback copies swap a clip
        in by the copy's own XML; T220). Exports keep the plain form, so their caches keep their keys.
        At any depth. Up to CANON_BUDGET characters copied it is the full text (as it has always been); a graph that
        shares elements so much that the full text would be bigger is given as 'merkle:' and a digest in which each
        element is fingerprinted once and referred to by its digest. A graph too deep to follow gives an UNAVAILABLE
        text that matches nothing, so every cache keyed on it misses (fail closed)."""
        try:
            try:
                return self._canon_full(elem, stable, {}, set(), [CANON_BUDGET])
            except _CanonTooBig:
                return 'merkle:' + self._canon_merkle(elem, stable, {}, set())
        except RecursionError:
            return unavailable()

    def _canon_full(self, elem, stable, memo, opened, budget):
        if elem is None:
            return ''
        key = id(elem)
        if key in memo:
            text = memo[key]
        elif key in opened:
            return '<loop>'
        else:
            opened.add(key)
            try:
                text = self._canon(elem, stable, lambda child: self._canon_full(child, stable, memo, opened, budget))
            finally:
                opened.discard(key)
            memo[key] = text
        budget[0] -= len(text)              # what this copy costs; a shared graph copies each element many times
        if budget[0] < 0:
            raise _CanonTooBig
        return text

    def _canon_merkle(self, elem, stable, memo, opened):
        if elem is None:
            return ''
        key = id(elem)
        if key in memo:
            return memo[key]
        if key in opened:
            return '<loop>'
        opened.add(key)
        try:
            text = self._canon(elem, stable, lambda child: '#' + self._canon_merkle(child, stable, memo, opened))
        finally:
            opened.discard(key)
        memo[key] = hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()
        return memo[key]

    def file_mark(self, text):
        """The mark canon adds for a property value that names a file ('' when it doesn't look like one): see
        CONTENT_HASH_BYTES. A relative path is read as the engine reads it, from the project's root folder (the
        <mlt root> attribute, else the project's own folder), else from the working folder as before."""
        text = str(text or '').strip()
        if not text or len(text) > 1024 or '\n' in text or '\r' in text:
            return ''
        absolute = bool(_DRIVE_OR_ROOT.match(text))
        named = bool(_EXTENSION.search(text))
        if not (absolute or named):
            return ''
        candidates = [text] if absolute else [os.path.join(self.root.get('root') or str(self.path.parent), text), text]
        for path in candidates:
            try:
                st = os.stat(path)
            except (OSError, ValueError):       # not there, or not a name a file can have (text that ends ".app")
                continue
            if not stat.S_ISREG(st.st_mode):
                return ''                                   # a folder: nothing read from it here
            if st.st_size > CONTENT_HASH_BYTES:
                return f'#file={st.st_size}:{st.st_mtime_ns}'
            try:
                return f'#file={st.st_size}:sha={_content_digest(os.path.abspath(path), st)}'
            except OSError:
                return '#unreadable:' + unavailable()
        return '#missing' if named else ''

    def _canon(self, elem, stable, sub):
        out = [elem.tag]
        for k, v in sorted((k, v) for k, v in elem.attrib.items() if k not in ('id', 'producer')):
            out.append(f'@{_name(k)}={_value(v)}')
        properties, children = [], []
        for child in elem:
            if child.tag == 'property':
                name = child.get('name')
                if name in VOLATILE or name.startswith('meta.') or name.startswith('_'):
                    continue
                text = property_value(child)
                if stable and (name == 'creation_time' or STABLE_DEFAULTS.get(name) == text):
                    continue
                if stable and name == 'length' and ':' in text:
                    text = str(clock_to_frames(text, self.fps))
                elif stable and name in ('resource', 'warp_resource') and os.name == 'nt':
                    text = text.replace('/', os.sep)
                entry = [f'{_name(name)}={_value(text)}']
                mark = self.file_mark(text)
                if mark:
                    entry.append(mark)
                (properties if stable else out).extend(entry if not stable else ['|'.join(entry)])
            elif child.tag in ('filter', 'link', 'transition'):
                (children if stable else out).append('{' + sub(child) + '}')
            elif child.tag in ('entry', 'track'):
                ref = self.elements.get(child.get('producer'))
                attrs = ','.join(f'{_name(k)}={_name(v)}' for k, v in sorted(child.attrib.items()) if k != 'producer')
                # a cut's own effects (an <entry> holding filters): after what it points at, marked as its own
                own = (_CUT + '{' + sub(child) + '}') if len(child) else ''
                (children if stable else out).append(f'<{child.tag} {attrs}>' + sub(ref) + own + _END)
            elif child.tag == 'blank':
                (children if stable else out).append(f'blank{_name(child.get("length"))}')
        if stable:
            out += sorted(properties) + children
        return '|'.join(out)

    def range_fingerprint(self, a, b, video=True, audio=False, visible_only=False, stable=False):
        """Hash of everything that can affect frames [a, b) relative to a. Shifting a whole section in time keeps
        its fingerprint, so re-rendering after an earlier insert/delete reuses the cache. visible_only leaves out the
        out point of a clip that goes on past b (it draws none of these frames), so trimming the end of a long overlay
        changes only the range it ends in. stable: see canon (the rendered playback preview's keys)."""
        h = hashlib.sha256()
        h.update(repr(sorted(self.profile.items())).encode())
        h.update(f'len={b - a}'.encode())
        for t in self.tracks:
            if t.kind == 'audio' and not audio:
                continue
            if t.kind == 'video' and not video:
                continue
            h.update(f'track:{t.kind}:{t.hide}:{t.index}'.encode())
            for it in t.items:
                if it.end <= a or it.start >= b:
                    continue
                # a clip that goes on past b: where it ends draws none of these frames
                out = 'on' if visible_only and it.end > b else it.out
                h.update(f'item:{it.start - a}:{it.in_}:{out}'.encode())
                h.update(self.canon(it.elem, stable=stable).encode('utf-8', 'replace'))
                if it.entry is not None and len(it.entry):       # the cut's own effects (only when it has any)
                    # its effects alone: the cut's in and out are in the item line above, its out masked when it goes
                    # on past b (visible_only), so trimming its end doesn't touch earlier ranges
                    for child in it.entry:
                        h.update((_CUT + self.canon(child, stable=stable)).encode('utf-8', 'replace'))
        # transitions between tracks (compositing) and timeline-level filters
        for tr in self.main.findall('transition'):
            h.update(self.canon(tr, stable=stable).encode())
        for fp in self.burn_filters + self.master_filters:
            h.update(repr(sorted((k, v) for k, v in fp.items() if k not in VOLATILE)).encode())
            # the files they read (a look-up table on the whole video, a captions file), only when they name any
            marks = [f'{_name(k)}{m}' for k, v in sorted(fp.items()) if k not in VOLATILE and (m := self.file_mark(v))]
            if marks:
                h.update(('#files:' + '|'.join(marks)).encode('utf-8', 'replace'))
        # only subtitles a burn filter draws: a feed for upload alone never reaches the picture, and counting it made a
        # subtitle re-timing change every chunk, so the whole video rendered again
        burned = {fp.get('feed', 'Subtitles') for fp in self.burn_filters}
        for feed, cues in sorted(self.subtitle_feeds.items()):
            if feed not in burned:
                continue
            for s, e, text in cues:
                if e * self.fps > a and s * self.fps < b:
                    h.update(f'cue:{feed}:{s * self.fps - a:.2f}:{e * self.fps - a:.2f}:{text}'.encode())
        return h.hexdigest()[:24]


def load(path):
    return Timeline(path)
