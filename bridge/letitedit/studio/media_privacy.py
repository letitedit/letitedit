"""No location in any file the Studio makes (CONTRACT.md section 1, 'No location in any file letitedit makes').

Phones write where a clip was filmed into the file: QuickTime's location.ISO6709 and ©xyz, EXIF GPS and IPTC places
in pictures, XMP fields (sometimes compressed), metadata tracks. Every file a Studio job delivers passes through
make_clean(): its metadata is removed whether or not any location was seen (pictures rebuilt from the segments or chunks
that draw them, a picture with a colour profile converted to sRGB and saved without it; video and sound remuxed with
picture and sound streams only and no metadata, then every box letitedit doesn't know inside the sample descriptions
blanked, with the compressor and handler names), and then the written file is checked by location_check.verify_clean,
which shares no parsing code with this module. A file that fails the check, or can't be checked, is not delivered
(StudioError 'location_not_removed'). A colour profile that can't be read is a picture that can't be delivered.

    strip_location(src, dst) -> dst without metadata (JPEG and PNG losslessly; MP4, MOV, M4V, M4A by stream copy)
    make_clean(path)         -> strips in place, verifies, raises StudioError when it can't be proved clean
    ensure_clean(path)       -> make_clean, deleting the file when it can't be made clean
    copy_clean(src, dst)     -> a clean copy of src at dst (src is never changed)
    find_location(path)      -> the kinds of location a file carries (location_check.inspect's 'found')
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

import letitedit.core.media as media
import letitedit.studio.location_check as location_check
import letitedit.studio.state as state

NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
SUPPORTED = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.m4v', '.m4a'}
JPEG_KEEP_APP = {0xE0: (b'JFIF\x00',), 0xEE: (b'Adobe',)}
JPEG_TABLES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF, 0xC4, 0xDB, 0xDD, 0xCC}
PNG_KEEP = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'sBIT', b'pHYs', b'bKGD',
            b'acTL', b'fcTL', b'fdAT'}


def _flags():
    return (NO_WINDOW | BELOW_NORMAL) if os.name == 'nt' else 0


def find_location(path):
    """The kinds of location in a file (never their values), sorted; empty when none was found. A file that couldn't be
    read through gives ['unknown: <why>'], never an empty list."""
    r = location_check.inspect(path)
    return r['found'] if r['state'] != 'unknown' else [f'unknown: {r["why"]}']


def _strip_jpeg(data):
    """The segments that draw the picture, and nothing after its end marker."""
    if data[:2] != b'\xff\xd8':
        raise ValueError('not a JPEG')
    out, i, n = bytearray(b'\xff\xd8'), 2, len(data)
    while i + 2 <= n:
        if data[i] != 0xFF:
            raise ValueError(f'unreadable JPEG at byte {i}')
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xD9:
            out += b'\xff\xd9'
            return bytes(out)
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        seg_end = i + 2 + length
        if seg_end > n:
            raise ValueError('JPEG segment past the end')
        body = data[i + 4:seg_end]
        keep = marker == 0xDA or marker in JPEG_TABLES or any(body.startswith(sig) for sig in JPEG_KEEP_APP.get(marker, ()))
        if marker == 0xE0 and keep:            # the JFIF header alone: version, units and density, no thumbnail
            if len(body) < 12:
                raise ValueError('a JFIF header cut short')
            out += b'\xff\xe0\x00\x10' + body[:12] + b'\x00\x00'
            i = seg_end
            continue
        if marker == 0xEE and keep and len(body) != 12:
            keep = False
        if marker == 0xDA:
            j = seg_end
            while j + 1 < n and not (data[j] == 0xFF and data[j + 1] not in (0x00, 0xFF) and not 0xD0 <= data[j + 1] <= 0xD7):
                j += 1
            out += data[i:j]
            i = j
            continue
        if keep:
            out += data[i:seg_end]
        i = seg_end
    raise ValueError('JPEG without an end marker')


def _strip_png(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    out, i = bytearray(data[:8]), 8
    while i + 12 <= len(data):
        length, kind = struct.unpack('>I4s', data[i:i + 8])
        chunk = data[i:i + 12 + length]
        if kind in PNG_KEEP:
            out += chunk
        if kind == b'IEND':
            return bytes(out)
        i += 12 + length
    raise ValueError('PNG without an end chunk')


def _has_profile(data, suffix):
    if suffix == '.png':
        i = 8
        while i + 12 <= len(data):
            length, kind = struct.unpack('>I4s', data[i:i + 8])
            if kind == b'iCCP':
                return True
            if kind == b'IEND':
                return False
            i += 12 + length
        return False
    return b'\xff\xe2' in data and b'ICC_PROFILE\x00' in data


def _to_srgb(src, dst, suffix):
    """A picture with a colour profile: its pixels converted to sRGB and saved without the profile (or anything else).
    Raises ValueError when the profile can't be read or used (such a picture isn't delivered)."""
    import io
    from PIL import Image, ImageCms
    with Image.open(src) as im:
        if getattr(im, 'is_animated', False):
            raise ValueError('an animated picture with a colour profile')
        profile = im.info.get('icc_profile')
        if not profile:
            raise ValueError('a colour profile that could not be read')
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        except Exception as e:  # noqa: BLE001 - anything that isn't a usable profile
            raise ValueError(f'a colour profile that is not a usable one ({e})') from e
        im.load()
        alpha = im.getchannel('A') if 'A' in im.getbands() else None
        mode = 'RGB'
        try:
            rgb = ImageCms.profileToProfile(im.convert('CMYK') if im.mode == 'CMYK' else
                                            im.convert('L') if im.mode in ('L', 'LA', 'I;16') else im.convert('RGB'),
                                            source, ImageCms.createProfile('sRGB'), outputMode=mode)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f'the colour profile could not be applied ({e})') from e
        if alpha is not None and suffix == '.png':
            rgb.putalpha(alpha)
        if suffix == '.png':
            rgb.save(dst, 'PNG')
        else:
            rgb.save(dst, 'JPEG', quality=95, subsampling=0)


# SEI messages: the free-form data an H.264 or HEVC picture stream may carry beside its pictures (an encoder's
# settings, a camera's user data, which can name a place). Removed by NAL unit type, without re-encoding.
SEI_TYPES = {'h264': '6', 'hevc': '39|40'}
HEVC_KEEP = {32, 33, 34}            # what an hvcC keeps: the parameter sets (VPS, SPS, PPS), never SEI


def _video_codecs(src):
    """The codec of each picture stream in src, in order (ffprobe)."""
    probe = media.ffprobe()
    try:
        run = subprocess.run([str(probe), '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=codec_name',
                              '-of', 'json', str(src)], capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=120, creationflags=_flags())
        if run.returncode != 0:
            raise OSError((run.stderr or '').strip()[-800:])
        return [s.get('codec_name') for s in (json.loads(run.stdout or '{}').get('streams') or [])]
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise state.StudioError('location_not_removed', f'{Path(src).name} could not be read to remove its metadata, '
                                'so it was not delivered.', retry='no', detail=str(e)[-800:]) from e


def _sei_filters(src):
    """ffmpeg's filter_units for each picture stream, dropping its SEI units during the copy. A picture stream of
    another codec isn't delivered: letitedit can't take its in-stream metadata out."""
    out = []
    for i, codec in enumerate(_video_codecs(src)):
        if codec not in SEI_TYPES:
            raise state.StudioError('location_not_removed', f'{Path(src).name} has {codec or "unknown"} video, and '
                                    'letitedit removes the metadata inside a video only from H.264 and HEVC, so it was '
                                    'not delivered.', retry='no')
        out += [f'-bsf:v:{i}', f'filter_units=remove_types={SEI_TYPES[codec]}']
    return out


def strip_location(src, dst):
    """Write dst: src without its metadata, location or not. Pictures losslessly; video and sound by stream copy with
    picture and sound streams only (phones' timed metadata tracks, which can carry location, are left out), the
    picture stream's SEI units dropped on the way (H.264 and HEVC; other video codecs are refused)."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    if suffix not in SUPPORTED:
        raise state.StudioError('location_not_removed', f'letitedit cannot remove metadata from a {suffix} file, so '
                                f'{src.name} was not delivered.', retry='no')
    try:
        if suffix in ('.jpg', '.jpeg', '.png'):
            data = src.read_bytes()
            if _has_profile(data, suffix):
                _to_srgb(src, dst, suffix)
                data = dst.read_bytes()
            dst.write_bytes(_strip_png(data) if suffix == '.png' else _strip_jpeg(data))
            return dst
    except (ValueError, OSError) as e:
        raise state.StudioError('location_not_removed', f'{src.name} could not be read to remove its metadata ({e}), '
                                'so it was not delivered.', retry='no') from e
    ffmpeg = media.ffmpeg()
    if not ffmpeg.is_file():
        raise state.StudioError('internal', "letitedit's ffmpeg is missing, so location metadata can't be removed.",
                                detail=str(ffmpeg))
    cmd = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(src), '-map', '0:v?', '-map', '0:a?',
           '-c', 'copy', *_sei_filters(src), '-map_metadata', '-1', '-map_metadata:s', '-1', '-map_chapters', '-1',
           '-fflags', '+bitexact', '-dn', '-sn', str(dst)]
    run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=3600,
                         creationflags=_flags())
    if run.returncode != 0 or not dst.is_file():
        raise state.StudioError('render_failed', f'Removing location metadata from {src.name} failed.',
                                detail=(run.stderr or '')[-1500:])
    _blank_metadata_boxes(dst)
    return dst


BOX_PARENTS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'dinf'}
BLANK = {b'udta', b'meta', b'uuid', b'XMP_'}
PICTURE_FORMATS = {b'avc1', b'avc3', b'hvc1', b'hev1', b'av01', b'vp08', b'vp09', b'mp4v', b'jpeg', b'mjpa', b'mjpb',
                   b'apch', b'apcn', b'apcs', b'apco', b'ap4h', b'ap4x', b'dvh1', b'dvhe'}
SOUND_FORMATS = {b'mp4a', b'ac-3', b'ec-3', b'Opus', b'fLaC', b'alac', b'lpcm', b'sowt', b'twos', b'ipcm', b'fpcm',
                 b'in24', b'in32', b'fl32', b'fl64', b'raw '}
PICTURE_KEEP = {b'avcC', b'hvcC', b'av1C', b'vpcC', b'esds', b'pasp', b'btrt', b'colr', b'clap', b'fiel', b'gama',
                b'mdcv', b'clli', b'cclv', b'amve', b'dvcC', b'dvvC', b'glbl', b'chrm'}
SOUND_KEEP = {b'esds', b'dOps', b'dfLa', b'alac', b'dac3', b'dec3', b'btrt', b'chan', b'wave', b'srat', b'pcmC'}
WAVE_KEEP = {b'frma', b'mp4a', b'esds', b'enda', b'alac', b'chan', b'\x00\x00\x00\x00'}


def _blank_metadata_boxes(path):
    """ffmpeg still writes an (empty) udta/meta box: turn every udta, meta and uuid box inside moov into a free box of
    the same size, filled with zeros (no offsets move)."""
    with open(path, 'r+b') as f:
        f.seek(0, 2)
        end = f.tell()

        def walk(start, stop, inside):
            pos = start
            while pos + 8 <= stop:
                f.seek(pos)
                size, kind = struct.unpack('>I4s', f.read(8))
                head = 8
                if size == 1:
                    size, head = struct.unpack('>Q', f.read(8))[0], 16
                elif size == 0:
                    size = stop - pos
                if size < head or pos + size > stop:
                    raise ValueError(f'box {kind!r} at {pos} runs past its parent')
                if inside and kind in BLANK:
                    blank(pos, head, size)
                elif kind in BOX_PARENTS:
                    walk(pos + head, pos + size, True)
                elif kind == b'hdlr' and size > head + 24:      # the handler's name: free text
                    f.seek(pos + head + 24)
                    f.write(bytes(size - head - 24))
                elif kind == b'stsd':
                    descriptions(pos + head + 8, pos + size)
                pos += size

        def blank(pos, head, size):
            f.seek(pos + 4)
            f.write(b'free')
            f.seek(pos + head)
            f.write(bytes(size - head))

        def hvcc(pos, head, size):
            f.seek(pos + head)
            body = f.read(size - head)
            if len(body) < 23:
                raise ValueError('hvcC cut short')
            arrays, at, kept = body[22], 23, []
            for _ in range(arrays):
                kind, count = body[at] & 0x3F, struct.unpack('>H', body[at + 1:at + 3])[0]
                end = at + 3
                for _ in range(count):
                    end += 2 + struct.unpack('>H', body[end:end + 2])[0]
                if end > len(body):
                    raise ValueError('hvcC runs past its box')
                if kind in HEVC_KEEP:
                    kept.append(body[at:end])
                at = end
            new = body[:22] + bytes([len(kept)]) + b''.join(kept) + body[at:]
            freed = len(body) - len(new)
            if freed == 0:
                return
            if freed < 8:
                raise ValueError('an SEI in hvcC too small to take out in place')
            f.seek(pos)
            f.write(struct.pack('>I4s', head + len(new), b'hvcC') + new)
            f.write(struct.pack('>I4s', freed, b'free') + bytes(freed - 8))

        def children(start, stop, keep):
            for pos, head, size, kind in boxes(start, stop):
                if kind == b'hvcC' and head == 8:
                    hvcc(pos, head, size)
                elif kind == b'colr':
                    f.seek(pos + head)
                    if f.read(4) not in (b'nclx', b'nclc'):
                        blank(pos, head, size)                  # an ICC profile in a video: not delivered
                elif kind == b'wave':
                    children(pos + head, pos + size, WAVE_KEEP)
                elif kind not in keep:
                    blank(pos, head, size)

        def descriptions(start, stop):
            for pos, head, size, kind in boxes(start, stop):
                a = pos + head
                if kind in PICTURE_FORMATS and size - head >= 78:
                    f.seek(a + 42)
                    f.write(bytes(32))                          # the compressor name: free text
                    children(a + 78, pos + size, PICTURE_KEEP)
                elif kind in SOUND_FORMATS and size - head >= 28:
                    f.seek(a + 8)
                    fixed = {0: 28, 1: 44, 2: 64}.get(struct.unpack('>H', f.read(2))[0])
                    if fixed and size - head >= fixed:
                        children(a + fixed, pos + size, SOUND_KEEP)

        def boxes(start, stop):
            found, pos = [], start
            while pos + 8 <= stop:
                f.seek(pos)
                size, kind = struct.unpack('>I4s', f.read(8))
                head = 8
                if size == 1:
                    size, head = struct.unpack('>Q', f.read(8))[0], 16
                elif size == 0:
                    size = stop - pos
                if size < head or pos + size > stop:
                    raise ValueError(f'box {kind!r} at {pos} runs past its parent')
                found.append((pos, head, size, kind))
                pos += size
            return found
        try:
            walk(0, end, False)
        except (ValueError, struct.error) as e:
            raise state.StudioError('location_not_removed', f'{Path(path).name} could not be read to remove its '
                                    f'metadata boxes ({e}).', retry='no') from e


def _verified(path, name):
    problems = location_check.verify_clean(path)
    if problems:
        raise state.StudioError('location_not_removed', f'{name} could not be proved free of location metadata after '
                                f'it was removed ({"; ".join(problems[:3])}), so it was not delivered.', retry='no',
                                detail='; '.join(problems))


def make_clean(path):
    """Strip a file's metadata in place and verify the result independently. Returns the path; raises StudioError
    'location_not_removed' when it can't be proved clean (the file is left as it was; ensure_clean deletes it)."""
    path = Path(path)
    tmp = path.with_name(f'.clean-{os.getpid()}-{os.urandom(3).hex()}-{path.name}')
    try:
        strip_location(path, tmp)
        _verified(tmp, path.name)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def ensure_clean(path):
    """Every file letitedit writes for a job: stripped and verified, always (not only when a location was seen).
    Deletes the file and raises when it can't be made clean. Returns the path."""
    try:
        return make_clean(path)
    except state.StudioError:
        Path(path).unlink(missing_ok=True)
        raise


def copy_clean(src, dst):
    """Copy a file into a job folder without its metadata (the Studio's one way of delivering a file it didn't render
    itself); the copy is verified, src is never changed."""
    dst = Path(dst)
    try:
        strip_location(src, dst)
        _verified(dst, Path(src).name)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return dst
