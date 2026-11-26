"""Still inputs: upright SDR pixels in sRGB, with no source metadata in the working PNG.

Apple gain-map HEICs use the primary SDR rendition. HLG/PQ bases are refused. Tiled HEIC
decoding is a separate step, before ICC conversion, because ffmpeg assembles its own tile graph.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

from PIL import Image, ImageOps

import letitedit.core.media as media
import letitedit.studio.delivery as delivery
import letitedit.studio.media_privacy as privacy
import letitedit.studio.state as state

GAIN = b'urn:com:apple:photo:2020:aux:hdrgainmap'
PHOTOS = {'.heic', '.heif', '.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp'}


def icc_profiles(data):
    """ICC colour properties in the HEIF property container, never EXIF/XMP or pixel bytes."""
    out = []

    def boxes(start, end):
        while start + 8 <= end:
            size, kind = struct.unpack_from('>I4s', data, start)
            head = 8
            if size == 1:
                if start + 16 > end:
                    raise ValueError('short HEIF box')
                size, head = struct.unpack_from('>Q', data, start + 8)[0], 16
            if size == 0:
                size = end - start
            if size < head or start + size > end:
                raise ValueError('invalid HEIF box')
            body, stop = start + head, start + size
            if kind in (b'meta', b'iprp', b'ipco'):
                boxes(body + (4 if kind == b'meta' else 0), stop)
            elif kind == b'colr' and data[body:body + 4] in (b'prof', b'rICC'):
                profile = data[body + 4:stop]
                if profile not in out:
                    out.append(profile)
            start = stop
    boxes(0, len(data))
    return out


def check_transfer(streams):
    # The first picture stream is a tile of the primary image (auxiliary gains are separate).
    base = next((s for s in streams if s.get('codec_type') == 'video'), {})
    if base.get('color_transfer') in ('arib-std-b67', 'smpte2084'):
        raise state.StudioError('hdr_not_supported', 'This photo has an HLG or PQ base. Export an SDR photo and '
                                'send it again.', retry='after_change', stage='layout')
    return base


def decode(source, destination, at=None):
    """(upright width, height, notes) after a decode and sRGB conversion. Source is read only."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    notes = []
    if source.suffix.lower() in ('.heic', '.heif'):
        probe = delivery._run([media.ffprobe(), '-v', 'error', '-show_streams', '-of', 'json', source],
                              'the HEIC colour information', heavy=False, timeout=60)
        base = check_transfer(json.loads(probe.stdout)['streams'])
        data = source.read_bytes()
        if GAIN in data:
            notes.append('HDR photo: its SDR rendition used')
        try:
            # Auxiliary gain planes may have a grayscale ICC too; only an RGB profile describes base pixels.
            profiles = [p for p in icc_profiles(data) if p[16:20] == b'RGB ']
        except ValueError as exc:
            raise state.StudioError('source_unreadable', 'The HEIC colour properties could not be read.',
                                    retry='after_change') from exc
        if len(profiles) > 1:
            raise state.StudioError('hdr_not_supported', 'This HEIC has ambiguous colour profiles. Send an sRGB '
                                    'copy.', retry='after_change')
        intermediate = destination.with_name(destination.stem + '-decoded.png')
        # No -vf here: auto assembly handles the tiles and rotation, then we convert colour separately.
        delivery._run([media.ffmpeg(), '-v', 'error', '-nostdin', '-y', '-threads', '4', '-filter_threads', '4',
                       '-filter_complex_threads', '4', '-i', source, '-frames:v', '1', '-threads', '4', intermediate],
                      'the HEIC SDR image', timeout=120)
        if profiles:
            with Image.open(intermediate) as image:
                image.save(intermediate.with_suffix('.icc.png'), icc_profile=profiles[0])
            tagged = intermediate.with_suffix('.icc.png')
            privacy.copy_clean(tagged, destination)
            tagged.unlink()
        elif base.get('color_primaries') == 'bt709':
            delivery._run([media.ffmpeg(), '-v', 'error', '-nostdin', '-y', '-threads', '4', '-i', intermediate,
                           '-vf', 'zscale=pin=bt709:tin=bt709:min=gbr:p=bt709:t=iec61966-2-1:m=gbr,format=rgb24',
                           '-frames:v', '1', '-threads', '4', destination], 'the sRGB photo', timeout=120)
            privacy.make_clean(destination)
        else:
            raise state.StudioError('hdr_not_supported', 'The HEIC colour profile is missing or unknown. Send '
                                    'an sRGB copy.', retry='after_change')
        intermediate.unlink(missing_ok=True)
    elif source.suffix.lower() in PHOTOS:
        with Image.open(source) as image:
            profile = image.info.get('icc_profile')
            upright = ImageOps.exif_transpose(image).convert('RGB')
            upright.save(destination, icc_profile=profile) if profile else upright.save(destination)
        privacy.make_clean(destination)
    else:
        info = delivery.probe(source)
        if not info:
            raise state.StudioError('source_unreadable', 'The picture source could not be opened.', retry='after_change')
        if info.get('hdr') not in ('sdr',):
            raise state.StudioError('hdr_not_supported', 'Send an SDR video for a still frame.', retry='after_change')
        # Frame extraction is two steps too: colour conversion follows the decoded intermediate.
        intermediate = destination.with_name(destination.stem + '-decoded.png')
        delivery._run([media.ffmpeg(), '-v', 'error', '-nostdin', '-y', '-threads', '4', '-ss', str(at or 0),
                       '-i', source, '-frames:v', '1', '-threads', '4', intermediate], 'the video frame', timeout=120)
        delivery._run([media.ffmpeg(), '-v', 'error', '-nostdin', '-y', '-threads', '4', '-i', intermediate,
                       '-vf', 'zscale=pin=bt709:tin=bt709:min=gbr:p=bt709:t=iec61966-2-1:m=gbr,format=rgb24',
                       '-frames:v', '1', '-threads', '4', destination], 'the sRGB frame', timeout=120)
        privacy.make_clean(destination)
        intermediate.unlink(missing_ok=True)
    with Image.open(destination) as image:
        return image.width, image.height, notes
