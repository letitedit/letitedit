"""Checking files for location, independently of the code that removes it (contract section 1, "No location in any file
letitedit makes").

Two questions, answered by parsers of their own (media_privacy strips with separate code, so a stripping bug can't hide
behind the same blind spot):

    verify_clean(path) -> []                 the problems that stop the file being delivered as location_metadata
                                             "none". An allow-list: a delivered JPEG or PNG may hold only the segments
                                             or chunks that draw the picture (no colour profile: a delivered picture is
                                             sRGB), and must decode whole; a delivered MP4 or MOV only plain picture and
                                             sound tracks whose every box, down into each sample description, is one it
                                             knows (no udta, meta or uuid anywhere, free text blank), ffprobe must run and
                                             report no metadata tags beyond the container's basic ones, every picture
                                             stream must be H.264 or HEVC with no SEI message left in it (read whole),
                                             and its first frame (or a moment of its sound) must decode: the rest of
                                             the stream is not decoded. A file it can't parse or decode, or a kind of
                                             file it doesn't know, is a problem: it fails closed. Sound streams are
                                             not read inside.
    inspect(path) -> {'state', 'found', 'why'}
                                             for inspect's report on a supplied file: 'present' (with the kinds of
                                             location found, never their values), 'none', or 'unknown' when the file
                                             couldn't be read through. Reads EXIF (GPS), IPTC (city, place, country),
                                             XMP (plain and compressed, in JPEG, PNG and MP4), QuickTime and MP4 boxes at
                                             any depth (udta, meta keys, uuid) and ffprobe's tags; in a HEIC, HEIF or
                                             AVIF its Exif item and its XMP (mime rdf+xml) items, found through meta,
                                             iinf and iloc (ffprobe is not run on them). A HEIF it can't read through
                                             (an odd iloc, an encrypted or outside item) is 'unknown'.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import letitedit.core.media as media

NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
PICTURES = {'.jpg', '.jpeg', '.png'}
VIDEOS = {'.mp4', '.mov', '.m4v', '.m4a'}
LOCATION_WORDS = ('gpslatitude', 'gpslongitude', 'exif:gps', 'locationshown', 'locationcreated', 'iptc4xmpext:city',
                  'iptc4xmpcore:location', 'photoshop:city', 'photoshop:state', 'photoshop:country', 'iso6709',
                  'location', 'xyz', 'latitude', 'longitude')
TAG_WORDS = ('location', 'gps', 'xyz', 'iso6709', 'latitude', 'longitude', 'xmp')
BASIC_TAGS = {'major_brand', 'minor_version', 'compatible_brands', 'handler_name', 'vendor_id', 'language'}

# ------------------------------------------------------------------ verify: JPEG

SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
JPEG_TABLES = SOF | {0xC4, 0xDB, 0xDD, 0xCC}


def _jpeg_problems(data):
    if data[:2] != b'\xff\xd8':
        return ['not a JPEG (no start marker)']
    problems, i, n = [], 2, len(data)
    frame = scans = 0
    while True:
        if i + 2 > n or data[i] != 0xFF:
            return problems + [f'unreadable JPEG structure at byte {i}']
        while i + 1 < n and data[i + 1] == 0xFF:          # fill bytes
            i += 1
        marker = data[i + 1]
        if marker == 0xD9:                                 # end of picture
            if any(data[i + 2:]):
                problems.append(f'{n - i - 2} bytes after the end of the picture')
            if not frame or not scans:
                problems.append('no picture in it (no frame header or no picture data)')
            return problems
        if i + 4 > n:
            return problems + ['JPEG cut short']
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        body = data[i + 4:i + 2 + length]
        if length < 2 or i + 2 + length > n:
            return problems + ['JPEG segment length past the end']
        if marker == 0xE0 and not (len(body) == 14 and body.startswith(b'JFIF\x00') and body[12:14] == b'\x00\x00'):
            problems.append('APP0 segment that is not a plain JFIF header (a thumbnail, an extension or more)')
        elif marker == 0xEE and not (len(body) == 12 and body.startswith(b'Adobe')):
            problems.append('APP14 segment that is not a plain Adobe colour marker')
        elif marker == 0xE2:
            problems.append('a colour profile (APP2): a delivered picture carries none')
        elif 0xE0 <= marker <= 0xEF and marker not in (0xE0, 0xEE):
            problems.append(f'metadata segment APP{marker - 0xE0}')
        elif marker == 0xFE:
            problems.append('comment segment')
        elif marker != 0xDA and marker not in JPEG_TABLES and not (0xE0 <= marker <= 0xEF):
            problems.append(f'unknown JPEG segment 0x{marker:02X}')
        frame += marker in SOF
        scans += marker == 0xDA
        i += 2 + length
        if marker == 0xDA:                                 # scan data: up to the next marker that isn't RSTn or 0xFF00
            while i + 1 < n:
                if data[i] == 0xFF and data[i + 1] != 0x00 and not 0xD0 <= data[i + 1] <= 0xD7 and data[i + 1] != 0xFF:
                    break
                i += 1
            else:
                return problems + ['JPEG picture data without an end marker']


# ------------------------------------------------------------------ verify: PNG

PNG_ALLOWED = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'sBIT', b'pHYs',
               b'bKGD', b'acTL', b'fcTL', b'fdAT'}            # no iCCP: a delivered picture is sRGB, without a profile
PNG_READ = PNG_ALLOWED | {b'iCCP'}


def _png_problems(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return ['not a PNG (no signature)']
    problems, i, n = [], 8, len(data)
    while True:
        if i + 12 > n:
            return problems + ['PNG cut short (no IEND)']
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        if i + 12 + length > n:
            return problems + [f'PNG chunk {kind!r} longer than the file']
        body = data[i + 8:i + 8 + length]
        crc = struct.unpack('>I', data[i + 8 + length:i + 12 + length])[0]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            problems.append(f'PNG chunk {kind.decode("latin-1")} with a bad checksum')
        if kind not in PNG_ALLOWED:
            problems.append(f'PNG chunk {kind.decode("latin-1")} (metadata or unknown)')
        i += 12 + length
        if kind == b'IEND':
            if any(data[i:]):
                problems.append(f'{n - i} bytes after the end of the picture')
            return problems


def _picture_problems(path, data):
    """The picture must decode whole, at the size its header states (Pillow, which letitedit ships)."""
    try:
        from PIL import Image
    except ImportError:
        return ['the picture could not be decoded to check it (Pillow is missing)']
    try:
        with Image.open(path) as im:
            im.load()
            size = im.size
    except Exception as e:  # noqa: BLE001 - anything the decoder refuses is a picture that can't be delivered
        return [f'the picture does not decode: {type(e).__name__}: {e}'[:300]]
    if size[0] < 1 or size[1] < 1:
        return ['the picture is empty']
    return []


# ------------------------------------------------------------------ verify: MP4 and MOV

CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'dinf', b'mvex'}
MOOV_ALLOWED = {b'mvhd', b'trak', b'iods', b'mvex', b'mehd', b'trex'}
TRAK_ALLOWED = {b'tkhd', b'edts', b'elst', b'mdia', b'tref', b'tapt', b'clef', b'prof', b'enof'}
MDIA_ALLOWED = {b'mdhd', b'hdlr', b'minf', b'elng'}
MINF_ALLOWED = {b'vmhd', b'smhd', b'dinf', b'dref', b'stbl', b'hdlr'}
STBL_ALLOWED = {b'stsd', b'stts', b'stss', b'ctts', b'stsc', b'stsz', b'stz2', b'stco', b'co64', b'sgpd', b'sbgp',
                b'sdtp', b'cslg', b'stps', b'subs', b'saiz', b'saio'}
ALLOWED_IN = {b'moov': MOOV_ALLOWED, b'trak': TRAK_ALLOWED, b'edts': {b'elst'}, b'mdia': MDIA_ALLOWED,
              b'minf': MINF_ALLOWED, b'dinf': {b'dref'}, b'stbl': STBL_ALLOWED, b'mvex': {b'mehd', b'trex'}}
TOP_ALLOWED = {b'ftyp', b'moov', b'mdat', b'free', b'skip', b'wide'}


def _boxes(f, start, end):
    """(type, payload start, payload end) for the boxes between start and end; raises ValueError when they don't fit."""
    pos = start
    while pos < end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            raise ValueError(f'box header cut short at {pos}')
        size, kind = struct.unpack('>I4s', head)
        payload = pos + 8
        if size == 1:
            big = f.read(8)
            if len(big) < 8:
                raise ValueError(f'64-bit box size cut short at {pos}')
            size = struct.unpack('>Q', big)[0]
            payload = pos + 16
        elif size == 0:
            size = end - pos
        if size < payload - pos or pos + size > end:
            raise ValueError(f'box {kind!r} at {pos} runs past its parent')
        yield kind, payload, pos + size
        pos += size


def _mp4_problems(path):
    problems = []
    size = os.path.getsize(path)
    try:
        with open(path, 'rb') as f:
            for kind, a, b in _boxes(f, 0, size):
                if kind not in TOP_ALLOWED:
                    problems.append(f'top-level box {kind.decode("latin-1")}')
                elif kind in (b'free', b'skip', b'wide'):
                    f.seek(a)
                    if b - a > 1 << 20 or any(f.read(b - a)):
                        problems.append(f'{kind.decode("latin-1")} box with content')
                elif kind == b'moov':
                    problems += _moov_problems(f, a, b)
    except (OSError, ValueError, struct.error) as e:
        problems.append(f'the file could not be read through: {e}')
    return problems


VISUAL_ENTRIES = {b'avc1', b'avc3', b'hvc1', b'hev1', b'av01', b'vp08', b'vp09', b'mp4v', b'jpeg', b'mjpa', b'mjpb',
                  b'apch', b'apcn', b'apcs', b'apco', b'ap4h', b'ap4x', b'dvh1', b'dvhe'}
AUDIO_ENTRIES = {b'mp4a', b'ac-3', b'ec-3', b'Opus', b'fLaC', b'alac', b'lpcm', b'sowt', b'twos', b'ipcm', b'fpcm',
                 b'in24', b'in32', b'fl32', b'fl64', b'raw '}
VISUAL_CHILDREN = {b'avcC', b'hvcC', b'av1C', b'vpcC', b'esds', b'pasp', b'btrt', b'colr', b'clap', b'fiel', b'gama',
                   b'mdcv', b'clli', b'cclv', b'amve', b'dvcC', b'dvvC', b'glbl', b'chrm'}
AUDIO_CHILDREN = {b'esds', b'dOps', b'dfLa', b'alac', b'dac3', b'dec3', b'btrt', b'chan', b'wave', b'srat', b'pcmC'}
WAVE_CHILDREN = {b'frma', b'mp4a', b'esds', b'enda', b'alac', b'chan', b'\x00\x00\x00\x00'}
EMPTY_NAMES = (b'', b'VideoHandler', b'SoundHandler', b'DataHandler', b'Core Media Video', b'Core Media Audio',
               b'Core Media Data Handler')


def _zero(f, a, b):
    f.seek(a)
    return b - a <= 1 << 20 and not any(f.read(b - a))


def _entry_children_problems(f, a, b, allowed, where):
    problems = []
    for kind, ca, cb in _boxes(f, a, b):
        name = kind.decode('latin-1')
        if kind in (b'free', b'skip'):
            if not _zero(f, ca, cb):
                problems.append(f'{name} box with content in {where}')
        elif kind not in allowed:
            problems.append(f'box {name} in {where}')
        elif kind == b'colr':
            f.seek(ca)
            if f.read(4) not in (b'nclx', b'nclc'):
                problems.append(f'a colour profile (colr) in {where}: a delivered video carries none')
        elif kind == b'wave':
            problems += _entry_children_problems(f, ca, cb, WAVE_CHILDREN, f'{where}/wave')
    return problems


def _stsd_problems(f, a, b):
    """Every sample description: a picture or sound format it knows, its fixed fields, a blank compressor name, and
    only boxes it knows inside (a uuid, XMP or anything unknown in there is a problem)."""
    problems = []
    f.seek(a)
    head = f.read(8)
    if len(head) < 8:
        return ['stsd cut short']
    count = struct.unpack('>I', head[4:8])[0]
    seen = 0
    for kind, ea, eb in _boxes(f, a + 8, b):
        seen += 1
        name = kind.decode('latin-1', 'replace')
        if kind in VISUAL_ENTRIES:
            if eb - ea < 78:
                problems.append(f'picture description {name} cut short')
                continue
            f.seek(ea + 42)                                    # 8 + 16 + 4 + 8 + 4 + 2 bytes: the compressor name
            if any(f.read(32)):
                problems.append(f'text in the compressor name of {name}')
            problems += _entry_children_problems(f, ea + 78, eb, VISUAL_CHILDREN, f'stsd/{name}')
        elif kind in AUDIO_ENTRIES:
            if eb - ea < 28:
                problems.append(f'sound description {name} cut short')
                continue
            f.seek(ea + 8)
            version = struct.unpack('>H', f.read(2))[0]
            fixed = {0: 28, 1: 44, 2: 64}.get(version)
            if fixed is None or eb - ea < fixed:
                problems.append(f'sound description {name} of a version letitedit does not read ({version})')
                continue
            problems += _entry_children_problems(f, ea + fixed, eb, AUDIO_CHILDREN, f'stsd/{name}')
        else:
            problems.append(f'sample description {name} (not a picture or sound format letitedit reads)')
    if seen != count:
        problems.append(f'stsd says {count} descriptions and holds {seen}')
    return problems


def _hdlr_problems(f, a, b):
    f.seek(a)
    body = f.read(min(b - a, 4096))
    name = body[24:].rstrip(b'\x00')
    if len(name) > 1 and name[0] == len(name) - 1:                # QuickTime writes a counted string
        name = name[1:]
    return [] if name in EMPTY_NAMES else ['text in a handler name']


def _dref_problems(f, a, b):
    problems = []
    for kind, ea, eb in _boxes(f, a + 8, b):
        f.seek(ea)
        flags = f.read(4)
        if kind not in (b'url ', b'alis') or flags[3:4] != b'\x01' or eb - ea != 4:
            problems.append('a data reference that is not "this file"')
    return problems


def _moov_problems(f, start, end, parent=b'moov'):
    problems = []
    for kind, a, b in _boxes(f, start, end):
        allowed = ALLOWED_IN.get(parent, set())
        if kind in (b'free', b'skip'):
            f.seek(a)
            if b - a > 1 << 20 or any(f.read(b - a)):
                problems.append(f'{kind.decode("latin-1")} box with content inside {parent.decode("latin-1")}')
            continue
        if kind not in allowed:
            problems.append(f'box {kind.decode("latin-1")} inside {parent.decode("latin-1")}')
            continue
        if kind == b'hdlr' and parent == b'mdia':
            f.seek(a + 8)
            handler = f.read(4)
            if handler not in (b'vide', b'soun'):
                problems.append(f'a {handler.decode("latin-1", "replace")} track (only picture and sound are kept)')
        if kind == b'hdlr':
            problems += _hdlr_problems(f, a, b)
        elif kind == b'stsd':
            problems += _stsd_problems(f, a, b)
        elif kind == b'dref':
            problems += _dref_problems(f, a, b)
        if kind in CONTAINERS:
            problems += _moov_problems(f, a, b, kind)
    return problems


def _ffprobe(path):
    """ffprobe's format, stream and chapter data, or raises RuntimeError when it can't give them."""
    probe = media.ffprobe()
    if not probe.is_file():
        raise RuntimeError(f'ffprobe is missing ({probe})')
    flags = (NO_WINDOW | BELOW_NORMAL) if os.name == 'nt' else 0
    try:
        run = subprocess.run([str(probe), '-v', 'error', '-show_entries', 'format_tags:stream_tags:chapters',
                              '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=120, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f'ffprobe did not run: {e}') from e
    if run.returncode != 0:
        raise RuntimeError(f'ffprobe could not read it: {(run.stderr or "").strip()[-300:]}')
    try:
        return json.loads(run.stdout or '{}')
    except ValueError as e:
        raise RuntimeError(f'ffprobe gave no readable answer: {e}') from e


def _decode_problems(path):
    """The first picture (or, for sound only, a moment of the sound) must decode: a file that only looks like a video
    is not delivered."""
    ff = media.ffmpeg()
    if not ff.is_file():
        return [f'could not be decoded to check it (ffmpeg is missing: {ff})']
    flags = (NO_WINDOW | BELOW_NORMAL) if os.name == 'nt' else 0
    for what in (['-map', '0:v:0', '-frames:v', '1'], ['-map', '0:a:0', '-t', '0.2']):
        try:
            run = subprocess.run([str(ff), '-v', 'error', '-nostdin', '-i', str(path), *what, '-f', 'null', '-'],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                                 creationflags=flags)
        except (OSError, subprocess.SubprocessError) as e:
            return [f'could not be decoded to check it: {e}']
        if run.returncode == 0 and not (run.stderr or '').strip():
            return []
        if 'matches no streams' not in (run.stderr or ''):
            return [f'does not decode: {(run.stderr or "").strip()[-300:]}']
    return ['no picture or sound in it']


def _tag_problems(data):
    problems = []
    groups = [('the file', (data.get('format') or {}).get('tags') or {})]
    groups += [(f'stream {i}', s.get('tags') or {}) for i, s in enumerate(data.get('streams') or [])]
    for where, tags in groups:
        for key in tags:
            if key.lower() not in BASIC_TAGS:
                problems.append(f'metadata tag "{key}" on {where}')
    if data.get('chapters'):
        problems.append('chapters')
    return problems


STREAM_SEI = {'h264': ('h264_mp4toannexb', 'h264', lambda b: b & 0x1F, {6}),
              'hevc': ('hevc_mp4toannexb', 'hevc', lambda b: (b >> 1) & 0x3F, {39, 40})}
SCAN_CHUNK = 1 << 20


def _video_codecs(path):
    probe = media.ffprobe()
    if not probe.is_file():
        raise RuntimeError(f'ffprobe is missing ({probe})')
    flags = (NO_WINDOW | BELOW_NORMAL) if os.name == 'nt' else 0
    run = subprocess.run([str(probe), '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=codec_name',
                          '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                         timeout=120, creationflags=flags)
    if run.returncode != 0:
        raise RuntimeError(f'ffprobe could not read it: {(run.stderr or "").strip()[-300:]}')
    return [s.get('codec_name') for s in (json.loads(run.stdout or '{}').get('streams') or [])]


def _nal_types(path, index, bsf, fmt, type_of):
    """Every NAL unit type in picture stream `index`, read whole as an Annex B stream (its codec setup box's units come
    first, so an SEI kept there is seen too). Streamed: the file is never held in memory."""
    ff = media.ffmpeg()
    if not ff.is_file():
        raise RuntimeError(f'ffmpeg is missing ({ff})')
    flags = (NO_WINDOW | BELOW_NORMAL) if os.name == 'nt' else 0
    proc = subprocess.Popen([str(ff), '-v', 'error', '-nostdin', '-i', str(path), '-map', f'0:v:{index}', '-c', 'copy',
                             '-bsf:v', bsf, '-f', fmt, '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, creationflags=flags)
    import threading
    timer = threading.Timer(1800, proc.kill)
    timer.start()
    err = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    reader.start()
    types, tail = set(), b''
    try:
        while True:
            chunk = proc.stdout.read(SCAN_CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            at = buf.find(b'\x00\x00\x01')
            while at >= 0 and at + 3 < len(buf):
                types.add(type_of(buf[at + 3]))
                at = buf.find(b'\x00\x00\x01', at + 3)
            tail = buf[-3:]
        proc.wait()
    finally:
        timer.cancel()
        proc.stdout.close()
        reader.join(5)
    if proc.returncode != 0:
        raise RuntimeError(f'its picture stream could not be read through: '
                           f'{(b"".join(err)).decode("utf-8", "replace").strip()[-300:]}')
    return types


def _stream_problems(path):
    """Inside each picture stream: H.264 and HEVC carry SEI messages beside the pictures (free-form user data that can
    name a place); any left is a problem. A picture stream of another codec can't be read inside, so it is a problem
    too (fails closed)."""
    problems = []
    try:
        codecs = _video_codecs(path)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as e:
        return [f'its picture streams could not be checked: {e}']
    for i, codec in enumerate(codecs):
        if codec not in STREAM_SEI:
            problems.append(f'picture stream {i} is {codec or "of an unknown codec"}: letitedit reads the metadata '
                            'inside H.264 and HEVC video only')
            continue
        bsf, fmt, type_of, sei = STREAM_SEI[codec]
        try:
            found = _nal_types(path, i, bsf, fmt, type_of) & sei
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            problems.append(f'picture stream {i} could not be checked: {e}')
            continue
        if found:
            problems.append(f'SEI messages (free-form data that can hold a location) inside picture stream {i}')
    return problems


def verify_clean(path):
    """The problems that stop path being delivered as location_metadata "none" (empty: clean). Fails closed."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix in ('.jpg', '.jpeg'):
            data = path.read_bytes()
            return _jpeg_problems(data) or _picture_problems(path, data)
        if suffix == '.png':
            data = path.read_bytes()
            return _png_problems(data) or _picture_problems(path, data)
        if suffix in VIDEOS:
            problems = _mp4_problems(path)
            try:
                problems += _tag_problems(_ffprobe(path))
            except RuntimeError as e:
                problems.append(f'could not be checked: {e}')
            return problems or _stream_problems(path) or _decode_problems(path)
    except OSError as e:
        return [f'could not be read: {e}']
    return [f'letitedit cannot check a {suffix or "file without an extension"} file for location']


# ------------------------------------------------------------------ inspect: what a supplied file carries

def _words_in(blob):
    text = blob.decode('utf-8', 'replace').lower() if isinstance(blob, bytes) else str(blob).lower()
    return sorted({w for w in LOCATION_WORDS if w in text})


def _tiff_gps(tiff):
    """True when an EXIF (TIFF) block's first IFD points at a GPS IFD."""
    if len(tiff) < 8 or tiff[:2] not in (b'II', b'MM'):
        raise ValueError('not an EXIF block')
    e = '<' if tiff[:2] == b'II' else '>'
    off = struct.unpack(e + 'I', tiff[4:8])[0]
    count = struct.unpack(e + 'H', tiff[off:off + 2])[0]
    for k in range(count):
        tag, _, _, value = struct.unpack(e + 'HHII', tiff[off + 2 + 12 * k: off + 14 + 12 * k])
        if tag == 0x8825:                                  # a GPS IFD: counted as location even when it looks empty
            return True
    return False


def _iptc_places(block):
    """IPTC datasets naming a place (2:90 city, 2:92 sublocation, 2:95 state, 2:100/101 country) in a Photoshop
    APP13 block."""
    found, i = set(), 0
    while True:
        i = block.find(b'\x1c\x02', i)
        if i < 0 or i + 5 > len(block):
            return found
        ds = block[i + 2]
        if ds in (90, 92, 95, 100, 101):
            found.add({90: 'IPTC city', 92: 'IPTC sublocation', 95: 'IPTC state', 100: 'IPTC country',
                       101: 'IPTC country'}[ds])
        i += 5 + struct.unpack('>H', block[i + 3:i + 5])[0]


def _inspect_jpeg(data):
    found, i, n = set(), 2, len(data)
    if data[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG')
    while i + 4 <= n and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker in (0xDA, 0xD9):
            break
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        body = data[i + 4:i + 2 + length]
        if marker == 0xE1 and body.startswith(b'Exif\x00\x00'):
            if _tiff_gps(body[6:]):
                found.add('EXIF GPS')
        elif marker == 0xE1:                               # XMP (standard or extended)
            found |= {f'XMP {w}' for w in _words_in(body)}
        elif marker == 0xED:
            found |= _iptc_places(body)
        elif 0xE2 <= marker <= 0xEF or marker == 0xFE:
            if marker != 0xE2 or not body.startswith(b'ICC_PROFILE'):
                found |= {f'APP{marker - 0xE0 if marker != 0xFE else "COM"} {w}' for w in _words_in(body)}
        i += 2 + length
    return found


def _inspect_png(data):
    found, i = set(), 8
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    while i + 12 <= len(data):
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        body = data[i + 8:i + 8 + length]
        if kind == b'eXIf' and _tiff_gps(body):
            found.add('EXIF GPS')
        elif kind == b'tEXt':
            found |= {f'PNG text {w}' for w in _words_in(body)}
        elif kind == b'zTXt':
            _, _, rest = body.partition(b'\x00')
            found |= {f'PNG text {w}' for w in _words_in(zlib.decompress(rest[1:]))}
        elif kind == b'iTXt':
            keyword, _, rest = body.partition(b'\x00')
            compressed = rest[0]
            rest = rest[2:]
            _, _, rest = rest.partition(b'\x00')           # language
            _, _, text = rest.partition(b'\x00')           # translated keyword
            text = zlib.decompress(text) if compressed else text
            found |= {f'PNG text {w}' for w in _words_in(keyword + b' ' + text)}
        elif kind == b'iCCP':
            name, _, rest = body.partition(b'\x00')
            found |= {f'PNG colour profile {w}' for w in _words_in(name + b' ' + zlib.decompress(rest[1:]))}
        elif kind not in PNG_READ:
            found |= {f'PNG {kind.decode("latin-1")} {w}' for w in _words_in(body)}
        if kind == b'IEND':
            break
        i += 12 + length
    return found


def _inspect_mp4(path):
    found = set()
    size = os.path.getsize(path)

    def walk(f, start, end, depth):
        for kind, a, b in _boxes(f, start, end):
            name = kind.decode('latin-1')
            if kind in (b'\xa9xyz', b'loci'):
                found.add(f'QuickTime {name}')
            if kind == b'mdat':
                continue
            if kind in (b'uuid', b'XMP_', b'keys', b'ilst', b'data', b'udta') or kind.startswith(b'\xa9'):
                f.seek(a)
                found.update(f'{name} {w}' for w in _words_in(f.read(min(b - a, 4 << 20))))
            if kind == b'meta':                         # MP4's meta is a full box (4 bytes first); QuickTime's isn't
                walk(f, a + 4 if _fits(f, a + 4, b) else a, b, depth + 1)
            elif kind == b'stsd':                       # inside each sample description, past its fixed fields
                f.seek(a)
                f.seek(a)
                f.read(8)
                for ek, ea, eb in _boxes(f, a + 8, b):
                    fixed = 78 if ek in VISUAL_ENTRIES else 28 if ek in AUDIO_ENTRIES else None
                    f.seek(ea)
                    blob = f.read(min(eb - ea, 4 << 20))
                    found.update(f'{ek.decode("latin-1", "replace")} {w}' for w in _words_in(blob))
                    if fixed is not None and _fits(f, ea + fixed, eb):
                        walk(f, ea + fixed, eb, depth + 1)
            elif depth < 12 and (kind in CONTAINERS or kind in (b'udta', b'moov', b'trak', b'ilst')):
                walk(f, a, b, depth + 1)

    with open(path, 'rb') as f:
        walk(f, 0, size, 0)
    return found


def _fits(f, start, end):
    try:
        for _ in _boxes(f, start, end):
            pass
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ inspect: HEIC, HEIF and AVIF

HEIF = {'.heic', '.heif', '.hif', '.avif'}
HEIF_BRANDS = {b'mif1', b'mif2', b'msf1', b'heic', b'heix', b'heim', b'heis', b'hevc', b'hevx', b'avif', b'avis',
               b'avio', b'MiHE', b'MiHA', b'MiHB', b'miaf'}
ITEM_LIMIT = 16 << 20                                       # an EXIF or XMP item larger than this is not read


def _full(f, a, b, need):
    """A full box's version, flags and the next `need` bytes of its payload; ValueError when they aren't there."""
    f.seek(a)
    head = f.read(4 + need)
    if b - a < 4 + need or len(head) < 4 + need:
        raise ValueError('a HEIF box cut short')
    return head[0], head[4:]


def _uint(raw, at, size):
    if size == 0:
        return 0, at
    if size not in (4, 8) or at + size > len(raw):
        raise ValueError(f'an iloc field of {size} bytes letitedit does not read')
    return int.from_bytes(raw[at:at + size], 'big'), at + size


def _iinf(f, a, b):
    """{item id: (type, content type, content encoding, protected)} from iinf."""
    version, head = _full(f, a, b, 2)
    count = struct.unpack('>H', head)[0] if version == 0 else struct.unpack('>I', _full(f, a, b, 4)[1])[0]
    items, seen = {}, 0
    for kind, ea, eb in _boxes(f, a + 4 + (2 if version == 0 else 4), b):
        if kind != b'infe':
            continue
        seen += 1
        f.seek(ea)
        body = f.read(min(eb - ea, 1 << 16))
        if len(body) < 8:
            raise ValueError('an item entry (infe) cut short')
        v = body[0]
        if v >= 2:
            id_size = 2 if v == 2 else 4
            item = int.from_bytes(body[4:4 + id_size], 'big')
            protected = int.from_bytes(body[4 + id_size:6 + id_size], 'big')
            item_type = body[6 + id_size:10 + id_size]
            if len(item_type) < 4 or not all(32 <= c < 127 for c in item_type):
                raise ValueError('an item entry (infe) with an unreadable item type')
            texts = body[10 + id_size:].split(b'\x00')         # name, then for mime: content type and encoding
            content = texts[1] if item_type == b'mime' and len(texts) > 1 else b''
            encoding = texts[2] if item_type == b'mime' and len(texts) > 2 else b''
        else:                                               # versions 0 and 1: no item type, a content type
            item, protected = struct.unpack('>HH', body[4:8])
            texts = body[8:].split(b'\x00')
            item_type, content = b'mime', texts[1] if len(texts) > 1 else b''
            encoding = texts[2] if len(texts) > 2 else b''
        items[item] = (item_type, content.decode('latin-1').strip().lower(), encoding.decode('latin-1').strip().lower(),
                       bool(protected))
    if seen != count:
        raise ValueError(f'iinf says {count} items and holds {seen}')
    return items


def _iloc(f, a, b):
    """{item id: (construction method, [(offset, length), ...] with the base offset added)} from iloc."""
    f.seek(a)
    raw = f.read(min(b - a, 4 << 20))
    if len(raw) < 8:
        raise ValueError('iloc cut short')
    version = raw[0]
    if version > 2:
        raise ValueError(f'an iloc of version {version} letitedit does not read')
    offset_size, length_size = raw[4] >> 4, raw[4] & 15
    base_size, index_size = raw[5] >> 4, (raw[5] & 15) if version else 0
    at = 6
    count_size = 4 if version == 2 else 2
    count, at = int.from_bytes(raw[at:at + count_size], 'big'), at + count_size
    places = {}
    for _ in range(count):
        id_size = 4 if version == 2 else 2
        if at + id_size > len(raw):
            raise ValueError('iloc cut short')
        item, at = int.from_bytes(raw[at:at + id_size], 'big'), at + id_size
        method = 0
        if version:
            method, at = struct.unpack('>H', raw[at:at + 2])[0] & 15, at + 2
        reference, at = struct.unpack('>H', raw[at:at + 2])[0], at + 2
        base, at = _uint(raw, at, base_size)
        extents, at = struct.unpack('>H', raw[at:at + 2])[0], at + 2
        parts = []
        for _ in range(extents):
            _, at = _uint(raw, at, index_size)
            offset, at = _uint(raw, at, offset_size)
            length, at = _uint(raw, at, length_size)
            parts.append((base + offset, length))
        places[item] = (method, parts, reference)
    return places


def _item_bytes(f, place, idat, size):
    method, parts, reference = place
    if reference != 0:
        raise ValueError('an item kept in another file')
    if method == 1:
        if idat is None:
            raise ValueError('an item in an idat box that is not there')
        start, end = idat
    elif method == 0:
        start, end = 0, size
    else:
        raise ValueError('an item made from another item (iloc construction method 2)')
    out = b''
    for offset, length in parts:
        a = start + offset
        length = (end - a) if length == 0 else length
        if a < start or length < 0 or a + length > end or len(out) + length > ITEM_LIMIT:
            raise ValueError('an item that runs past the end of the file, or too large to read')
        f.seek(a)
        out += f.read(length)
    return out


def _decode_item(blob, encoding):
    if encoding in ('', 'identity'):
        return blob
    if encoding == 'deflate':
        try:
            return zlib.decompress(blob)
        except zlib.error:
            return zlib.decompress(blob, -15)
    if encoding in ('gzip', 'x-gzip'):
        return zlib.decompress(blob, 31)
    raise ValueError(f'an item with a content encoding letitedit does not read ({encoding})')


def _exif_item_gps(blob):
    """An HEIF Exif item: a 4-byte offset to the TIFF header, then the EXIF block (often after 'Exif\\0\\0')."""
    if len(blob) < 4:
        raise ValueError('an Exif item cut short')
    skip = struct.unpack('>I', blob[:4])[0]
    tiff = blob[4 + skip:]
    if tiff[:2] not in (b'II', b'MM') and blob[4:10] == b'Exif\x00\x00':
        tiff = blob[10:]                                    # a writer that left the offset at 0 before 'Exif\0\0'
    return _tiff_gps(tiff)


def _inspect_heif(path):
    """(found, why) for an ISO base media picture file (HEIC, HEIF, AVIF): the EXIF item's GPS IFD and the location
    words in its XMP items (and in any uuid or xml box beside them). Raises ValueError for what it can't read."""
    found, size = set(), os.path.getsize(path)
    with open(path, 'rb') as f:
        top = list(_boxes(f, 0, size))
        if not top or top[0][0] != b'ftyp':
            raise ValueError('not a HEIF file (no ftyp box first)')
        f.seek(top[0][1])
        ftyp = f.read(min(top[0][2] - top[0][1], 1024))
        brands = {ftyp[i:i + 4] for i in range(0, len(ftyp) - 3, 4) if i != 4}
        if not brands & HEIF_BRANDS:
            raise ValueError('not a HEIF file (its brands are not HEIF brands)')
        metas = [(a, b) for kind, a, b in top if kind == b'meta']
        if len(metas) != 1:
            raise ValueError(f'{len(metas)} meta boxes at the top (letitedit reads a file with one)')
        for kind, a, b in top:
            if kind == b'uuid':
                f.seek(a)
                found |= {f'uuid {w}' for w in _words_in(f.read(min(b - a, 4 << 20)))}
        if any(kind == b'moov' for kind, _, _ in top):
            found |= _inspect_mp4(path)                     # an image sequence: its tracks as for a video
        a, b = metas[0]
        _full(f, a, b, 0)
        items = places = idat = None
        for kind, ca, cb in _boxes(f, a + 4, b):
            if kind == b'iinf':
                items = _iinf(f, ca, cb)
            elif kind == b'iloc':
                places = _iloc(f, ca, cb)
            elif kind == b'idat':
                idat = (ca, cb)
            elif kind in (b'xml ', b'XMP_', b'uuid'):
                f.seek(ca)
                found |= {f'{kind.decode("latin-1").strip()} {w}' for w in _words_in(f.read(min(cb - ca, 4 << 20)))}
        if items is None or places is None:
            raise ValueError('no item list (iinf) or no item locations (iloc) in its meta box')
        exif = xmp = 0
        for item, (item_type, content, encoding, protected) in sorted(items.items()):
            is_exif = item_type == b'Exif'
            is_xmp = item_type == b'mime' and ('rdf+xml' in content or 'xmp' in content)
            if not (is_exif or is_xmp):
                continue
            if protected:
                raise ValueError('an encrypted EXIF or XMP item')
            if item not in places:
                raise ValueError(f'item {item} has no location in iloc')
            blob = _item_bytes(f, places[item], idat, size)
            if is_exif:
                exif += 1
                if _exif_item_gps(_decode_item(blob, encoding)):
                    found.add('EXIF GPS')
            else:
                xmp += 1
                found |= {f'XMP {w}' for w in _words_in(_decode_item(blob, encoding))}
    why = '' if found else (f'Read its {exif} EXIF and {xmp} XMP item(s): no location in them.' if exif or xmp
                            else 'It has no EXIF or XMP item, so it carries no location.')
    return found, why


def inspect(path):
    """{'state': 'present'|'none'|'unknown', 'found': [kinds of location, never values], 'why': str}."""
    path = Path(path)
    suffix = path.suffix.lower()
    why = ''
    try:
        if suffix in ('.jpg', '.jpeg'):
            found = _inspect_jpeg(path.read_bytes())
        elif suffix == '.png':
            found = _inspect_png(path.read_bytes())
        elif suffix in HEIF:
            found, why = _inspect_heif(path)
        elif suffix in VIDEOS:
            found = _inspect_mp4(path)
            data = _ffprobe(path)
            groups = [(data.get('format') or {}).get('tags') or {}]
            groups += [s.get('tags') or {} for s in data.get('streams') or []]
            for tags in groups:
                found |= {k for k in tags if any(w in k.lower() for w in TAG_WORDS)}
        else:
            return {'state': 'unknown', 'found': [], 'why': f'letitedit does not read {suffix or "this"} files for location.'}
    except (OSError, ValueError, RuntimeError, struct.error, zlib.error, IndexError) as e:
        return {'state': 'unknown', 'found': [], 'why': f'The file could not be read through: {e}'}
    return {'state': 'present' if found else 'none', 'found': sorted(found), 'why': '' if found else why}
