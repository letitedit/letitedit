"""Validation receipts for encoded chunks, tied to the bytes and render inputs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import letitedit.core.quiet_subprocess as quiet_subprocess
import numpy as np

VERSION = 2
SIDE = 64


def receipt_path(path):
    return Path(path).with_suffix('.verified.json')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _receipt(path, expected):
    try:
        receipt = json.loads(receipt_path(path).read_text(encoding='utf-8-sig'))
        if (isinstance(receipt, dict) and type(receipt.get('verified')) is bool
                and receipt == {'version': VERSION, 'inputs': expected, 'sha256': digest(path),
                                'verified': receipt['verified']}):
            return receipt
    except (OSError, ValueError):
        pass
    return None


def candidate(path, expected):
    return _receipt(path, expected) is not None


def reusable(path, expected):
    receipt = _receipt(path, expected)
    return receipt is not None and receipt['verified']


def record(path, expected, verified=True):
    from letitedit.timeline.render_queue import _write
    _write(receipt_path(path), {'version': VERSION, 'inputs': expected, 'sha256': digest(path), 'verified': verified})


def renderer_signature(app):
    paths = [Path(app) / 'melt.exe', *Path(app).glob('*.dll'), *Path(app).glob('lib/mlt-7/*.dll')]
    stats = [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(set(paths))]
    return hashlib.sha256(json.dumps(stats).encode()).hexdigest()


def decode(path, samples=None):
    from letitedit.timeline.render_queue import FFMPEG, NO_WINDOW
    filters = [f'scale={SIDE}:{SIDE}:flags=area']
    if samples is not None:
        selection = '+'.join(f'eq(n,{index})' for index in samples)
        filters.insert(0, f"select='{selection}'")
    result = subprocess.run([str(FFMPEG), '-v', 'error', '-xerror', '-err_detect', 'explode', '-threads', '4',
                             '-i', str(path), '-map', '0:v:0', '-an', '-vf', ','.join(filters),
                             '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-threads', '4', '-'],
                            capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=300)
    if result.returncode or result.stderr.strip():
        raise RuntimeError(f'Chunk decode failed: {result.stderr.decode(errors="replace")[-1000:]}')
    return np.frombuffer(result.stdout, dtype=np.uint8)


def compare(encoded, reference, frames):
    """Compare every decoded frame against an independent serial render, allowing compression noise."""
    pictures = []
    pixels = SIDE * SIDE * 3
    for path in (encoded, reference):
        picture = decode(path)
        if picture.size != frames * pixels:
            raise RuntimeError(f'{Path(path).name} decoded {picture.size // pixels} frames, expected {frames}')
        pictures.append(picture.reshape(frames, pixels))
    worst = 0.0
    for index, (actual, wanted) in enumerate(zip(*pictures)):
        error = float(np.abs(actual.astype(np.int16) - wanted.astype(np.int16)).mean())
        if error > 8.0:
            raise RuntimeError(f'Chunk picture differs from serial render at frame {index} (mean error {error:.2f}/255)')
        worst = max(worst, error)
    return {'frames_checked': frames, 'max_mean_error': round(worst, 3)}


def run_up_frames(timeline):
    """How long a played reference runs before its sample: half a second."""
    return max(2, round(timeline.fps / 2))


def render_samples(worker, timeline, chunks, only=None, run_up=0):
    """Draw the candidate chunks' absolute sample frames in one native-size serial run.

    Each sample is a seek to its own frame. `only` ({chunk index: offsets}) limits it to those samples. With `run_up`
    frames, a sample is instead played in order from up to that many frames before it, and only its own picture is kept,
    which is how a chunk is drawn: past the last picture of a clip the engine holds that picture while playing, but a
    seek there draws something else (a 24, 25 or 29.97 fps clip in a 60 fps project ends 1 or 2 project frames before
    the clip does; a clip whose picture is shorter than its sound, well before). A good chunk was read as wrong (T180)
    wherever that happens; `played_references` draws those samples again this way."""
    if not chunks:
        return {}
    root = copy.deepcopy(timeline.root)
    identifiers = {element.get('id') for element in root.iter()}
    identifier = 'cache_samples'
    while identifier in identifiers:
        identifier += '_'
    playlist = ET.SubElement(root, 'playlist', {'id': identifier})
    root.set('producer', identifier)
    addresses = []   # (chunk index, offset, position in the run of the sample's own frame)
    drawn = 0
    for chunk in chunks:
        frames = chunk['b'] - chunk['a']
        for offset in sorted({0, frames // 4, frames // 2, 3 * frames // 4, frames - 1}):
            if only is not None and offset not in only.get(chunk['i'], ()):
                continue
            frame = chunk['a'] + offset
            lead = min(offset, run_up)
            ET.SubElement(playlist, 'entry', {'producer': timeline.main.get('id'), 'in': str(frame - lead), 'out': str(frame)})
            drawn += lead + 1
            addresses.append((chunk['i'], offset, drawn - 1))
    if not addresses:
        return {}
    with tempfile.TemporaryDirectory(prefix='chunk-samples-', dir=worker.dir) as directory:
        document = Path(directory) / 'samples.mlt'
        output = Path(directory) / 'samples.mkv'
        ET.ElementTree(root).write(document, encoding='utf-8', xml_declaration=True)
        worker.melt([str(document), 'in=0', f'out={drawn - 1}', '-consumer', f'avformat:{output}',
                     'vcodec=ffv1', 'pix_fmt=yuv420p', 'an=1', 'audio_off=1', 'real_time=-1', 'threads=4'])
        pictures = decode(output, samples=[position for _, _, position in addresses] if run_up else None)
    pixels = SIDE * SIDE * 3
    if pictures.size != len(addresses) * pixels:
        raise RuntimeError(f'Chunk reference decoded {pictures.size // pixels} frames, expected {len(addresses)}')
    references = {}
    for (index, offset, _), picture in zip(addresses, pictures.reshape(len(addresses), pixels)):
        references.setdefault(index, {})[offset] = picture
    return references


def failing_samples(encoded, references):
    """The sample frames of `encoded` that differ from their reference by more than compression noise (as
    compare_samples reads them); empty when it fails for another reason or passes."""
    samples = sorted(references)
    pixels = SIDE * SIDE * 3
    picture = decode(encoded, samples=samples)
    if not samples or picture.size != len(samples) * pixels:
        return []
    out = []
    for index, actual in zip(samples, picture.reshape(len(samples), pixels)):
        reference = references[index]
        wanted = reference if isinstance(reference, np.ndarray) else decode(reference)
        if wanted.size == pixels and float(np.abs(actual.astype(np.int16) - wanted.astype(np.int16)).mean()) > 8.0:
            out.append(index)
    return out


def played_references(worker, timeline, chunk, references, encoded):
    """`references` for one chunk with the samples `encoded` fails redrawn by playing them in order (a seek at the end
    of a clip's picture draws something else than the played chunk). Only those samples are drawn again, so a chunk that
    passes costs nothing more; a picture that is really wrong fails against this reference as well. Returns
    (references, the offsets redrawn)."""
    bad = failing_samples(encoded, references)
    if not bad:
        return references, []
    again = render_samples(worker, timeline, [chunk], only={chunk['i']: set(bad)}, run_up=run_up_frames(timeline))
    return {**references, **again.get(chunk['i'], {})}, bad


def compare_samples(encoded, references):
    samples = sorted(references)
    pixels = SIDE * SIDE * 3
    picture = decode(encoded, samples=samples)
    if not samples or picture.size != len(samples) * pixels:
        raise RuntimeError(f'Chunk decoded {picture.size // pixels} samples, expected {len(samples)}')
    worst = 0.0
    for index, actual in zip(samples, picture.reshape(len(samples), pixels)):
        reference = references[index]
        wanted = reference if isinstance(reference, np.ndarray) else decode(reference)
        if wanted.size != pixels:
            raise RuntimeError(f'Chunk reference sample at frame {index} decoded {wanted.size // pixels} frames, expected 1')
        error = float(np.abs(actual.astype(np.int16) - wanted.astype(np.int16)).mean())
        if error > 8.0:
            raise RuntimeError(f'Chunk picture differs from serial render at frame {index} (mean error {error:.2f}/255)')
        worst = max(worst, error)
    return {'frames_checked': len(samples), 'sample_frames': samples, 'max_mean_error': round(worst, 3)}
