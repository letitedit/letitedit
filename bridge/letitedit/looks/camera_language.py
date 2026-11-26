"""Camera language: a video's mix of shot sizes, of moving against static shots and of plain frames, shot by shot.

The same measure runs on a Look's reference video (when Learn analyses it) and on a finished cut (the Look check, on
the export), so both sides are read by one instrument.

classify(shot, zooms)     one importer shot (style_import.picture_events) and the importer's zoom ramps and forward
                          or back camera candidates over it -> its move: static, pan, tilt, push_in, pull_out,
                          handheld, whip or unknown. Image motion, not proof of a physical camera move.
measure(video, ...)       every shot of a video with its move and its size (wide, medium, close, detail, unknown),
                          and the profile (the mix); a shot the vision model judged keeps its facts (SHOT_FACTS). Sizes: the main face's height where a person fills enough of the
                          frame; otherwise the fact log's vision model when it is installed (never downloaded here).
                          Plain share: how much of a frame without a person is plain (open sky, bare walls).
profile(rows)             the mix: runtime shares of moves and sizes, the plain share, and the reference's own spread
                          over stretches.
from_shots(shots)         the moves alone, from an importer report that has no camera measure yet (sizes unknown).
check(references, rows)   the stretches of a cut that fall outside its reference's mix: (summary, problems); a plain
                          stretch also names its plainest shots, as many as would have to become fuller frames to
                          bring every stretch of it under the bar (plain_swaps).
The pace (shot lengths stretch by stretch) is measured from the same rows by letitedit.looks.pace.
recipe_line(profile)      one recipe line.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from pathlib import Path

FORMAT = 'letitedit-camera/1'
VERSION = 3                  # 2: the plain share of the frame; 3: a zoom covers at least 0.3 of the shot
MOVES = ('static', 'pan', 'tilt', 'push_in', 'pull_out', 'handheld', 'whip', 'unknown')
MOVING = ('pan', 'tilt', 'push_in', 'pull_out', 'handheld', 'whip')
SIZES = ('wide', 'medium', 'close', 'detail', 'unknown')

# Moves, from the importer's per-shot motion (style_import.motion_in_shots). Image drift in frame fractions per
# second; the importer counts a shot as moving at 0.03 and so does this.
DRIFT = 0.03                 # net image drift (pan or tilt)
JITTER = 0.03                # frame-to-frame shift without a net drift (camera_speed): handheld
SHAKE = 0.002                # high-frequency part of the camera path, frame widths (rms): handheld
# Push in and pull out come from the importer's zoom ramps and forward / back camera candidates (feature tracking
# over the shot, at least 3.5 % scale over 0.8 s), not from its per-shot zoom_over_shot: on still frames the phase
# correlation it uses scores a 2 % rescaled copy above the original, so a still shot can read as a 6 % zoom.
ZOOM_KINDS = {'push_in': 'push_in', 'camera_forward': 'push_in', 'pull_out': 'pull_out', 'camera_back': 'pull_out'}
ZOOM_OVERLAP = 0.4           # seconds of the shot (or half of a shorter one) a zoom must cover ...
ZOOM_SHARE = 0.3             # ... and at least this share of it: a short zoom inside a long shot does not name it
WHIP = 0.3                  # an untrackable shot moving at least this fast is a whip
SHORTEST = 0.2               # shots shorter than this (s) have too few frames to name a move (a whip still counts)
# Sizes from the main face's height as a share of the frame height: 0.28 and over a close-up (the importer's own
# close-up line, style_import_text.face_summary), 0.15-0.28 medium (waist up: the face about a fifth of the frame).
# Under 0.15 the person may be shown whole (a standing figure's head is about an eighth of its height, so a full
# figure filling the frame has a face of about 0.11), so the vision model judges the frame instead.
FACE_CLOSE = 0.28
FACE_MEDIUM = 0.15
VISION_SHOT = {'wide': 'wide', 'medium': 'medium', 'close-up': 'close', 'detail': 'detail'}
SHOT_FACTS = ('shot', 'people', 'subject', 'place', 'camera', 'face')   # the vision model's facts kept on a shot
MAX_VISION_SHOTS = 80        # faceless shots asked of the vision model in one video (spread evenly beyond)
# The plain share of a frame: 16 px tiles (on the 448 px frames) whose brightness barely varies (standard deviation
# under 4 of 255) and that are not dark (mean over 60): open sky, a bare wall, fog, a blown-out window. Dark areas
# (night) are not counted. Judged only on shots without a person filling the frame.
PLAIN_TILE = 16
PLAIN_STD = 4.0
PLAIN_MEAN = 60.0

# The bar (check): how far a cut may sit from its reference.
TOLERANCE_MOVING = 0.15      # the whole cut's moving share, under the reference's
TOLERANCE_STRETCH = 0.10     # a stretch's moving share under the reference's own lowest stretch
TOLERANCE_SIZES = 0.30       # total variation distance between the size mixes
TOLERANCE_ONE_SIZE = 0.10    # a stretch's one-size share over the reference's own highest
TOLERANCE_PLAIN = 0.15       # a stretch's (or the cut's) plain share over the reference's own highest (or its mean)
PLAIN_MARGIN = 0.03          # the swaps named for a plain stretch bring it this far under its bar
KIND_SHARE = 0.10            # a kind of move this much of the reference's time ...
KIND_FRACTION = 0.5          # ... is short in a cut that has under this fraction of it
MIN_KNOWN = 0.5              # a stretch (or a mix) is judged only when this share of it is measured
ENDING_SHOTS = 4             # the ending: the last picture shots before any end hold (a static, plain-less last row)
ENDING_LONGER = 1.5          # the cut's last picture shot is long when over this times the reference's longest there
ENDING_SECONDS = 1.0         # ... and over the reference's own last shot by this many seconds, or static where the
                             # reference's ending moves
FULLER_SIZE = {'wide': 0, 'medium': 1, 'close-up': 2, 'detail': 2}    # the fact log's shot sizes, by fullness
CANDIDATES = 6               # unused logged stretches named for one flagged stretch, at most two per file
MAX_LOGGED_FILES = 400
KIND_WORDS = {'pan': 'pans', 'tilt': 'tilts', 'push_in': 'push-ins or forward travel',
              'pull_out': 'pull-outs or travel back', 'handheld': 'handheld movement', 'whip': 'whips'}

METHOD = ('Moves: the importer\'s per-shot image alignment (phase correlation at the analysis frame rate; shake from '
          'the camera path\'s high-frequency part) and its zoom ramps and forward or back camera candidates (feature '
          'tracking, at least 3.5 % scale over 0.8 s). It names image motion: a '
          'subject that fills the frame moving reads as a move, a tracked subject against a plain sky as static. '
          'Sizes: the main face (OpenCV YuNet) on three frames of the shot where it is at least 0.15 of the frame '
          'height; otherwise the fact log\'s vision model answering wide, medium, close-up or detail on the '
          'same three frames. Plain share: the share of 16 px tiles of those frames (448 px wide) with brightness '
          'varying under 4 of 255 and a mean over 60 (open sky, bare walls), on shots without a person.')
LIMITS = ('Not measured: low, high or canted angles and foreground framing (no reliable instrument). Moves are '
          'image motion, not proof of a physical camera move. Without the vision model only person shots get a '
          'size. The plain share is not a sky detector: fog, bare walls and blown-out windows count, dark areas do '
          'not.')


# ------------------------------------------------------------------ one shot's move

def zoom_spans(zooms=(), camera_moves=()):
    """[(start, end, push_in | pull_out)] from the importer's zoom ramps and forward / back camera candidates (an
    editor's punch at a cut or inside a shot is a jump, not a move, and is left out)."""
    out = []
    for event in list(zooms or []) + list(camera_moves or []):
        kind = ZOOM_KINDS.get((event or {}).get('kind'))
        if kind and event.get('end') is not None and not event.get('at_cut'):
            out.append((float(event['t']), float(event['end']), kind))
    return out


def classify(shot, zooms=()):
    """The move of one importer shot ({start, len, camera_speed, shake_rms, named_motion}); zooms: zoom_spans()."""
    start = float(shot.get('start') or 0)
    length = float(shot.get('len') or (shot.get('end', 0) - start) or 0)
    end = start + length
    named = shot.get('named_motion') or {}
    speed = float(shot.get('camera_speed') or 0)
    if named.get('move') == 'unresolved_image_motion':
        return 'whip' if speed >= WHIP else 'unknown'
    if length < SHORTEST:
        return 'whip' if speed >= WHIP else 'unknown'
    covered = {}
    for a, b, kind in zooms or ():
        covered[kind] = covered.get(kind, 0.0) + max(0.0, min(b, end) - max(a, start))
    if covered:
        kind = max(covered, key=covered.get)
        if covered[kind] >= max(min(ZOOM_OVERLAP, length / 2), ZOOM_SHARE * length):
            return kind
    drift = float(named.get('frame_fraction_per_s') or 0)
    if drift >= DRIFT:
        return 'tilt' if named.get('move') == 'image_tilt_or_drift' else 'pan'
    if speed >= JITTER or float(shot.get('shake_rms') or 0) >= SHAKE:
        return 'handheld'
    return 'static'


def _row(shot, zooms=()):
    start, end = float(shot['start']), float(shot['end'])
    named = shot.get('named_motion') or {}
    return {'start_s': round(start, 3), 'end_s': round(end, 3), 'move': classify(shot, zooms), 'size': 'unknown',
            'size_by': None, 'drift_per_s': named.get('frame_fraction_per_s'),
            'jitter_per_s': shot.get('camera_speed'), 'shake_rms': shot.get('shake_rms')}


# ------------------------------------------------------------------ sizes

def vision_ready():
    """True when the fact log's vision model and its environment are already on this PC (nothing is downloaded) and
    its graphics card runs it (hardware.vision_unavailable)."""
    try:
        import letitedit.core.hardware as hardware
        if hardware.vision_unavailable() is not None:
            return False
        import letitedit.core.model_fetch as model_fetch
        import letitedit.sound.model_tools as model_tools
        if not Path(model_tools.MODELS_PYTHON).exists():
            return False
        plan = model_fetch.plan(['qwen3.5-4b'])
        return not plan['download_bytes'] and all(model['present'] for model in plan['models'])
    except Exception:  # noqa: BLE001 - no vision model: sizes come from faces only
        return False


def _shot_times(row):
    start, end = row['start_s'], row['end_s']
    return [round(start + (end - start) * f, 3) for f in (0.25, 0.5, 0.75)]


def face_size(height):
    """A shot's size from its main face height (share of the frame height); None when the face is too small to say."""
    if height is None:
        return None
    if height >= FACE_CLOSE:
        return 'close'
    if height >= FACE_MEDIUM:
        return 'medium'
    return None


def plain_share(frame):
    """The share of a BGR frame's PLAIN_TILE tiles that are plain (see PLAIN_STD and PLAIN_MEAN)."""
    import cv2
    import numpy as np
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    tile = PLAIN_TILE
    h, w = grey.shape[0] // tile * tile, grey.shape[1] // tile * tile
    if not h or not w:
        return None
    blocks = grey[:h, :w].reshape(h // tile, tile, w // tile, tile)
    return float(((blocks.std(axis=(1, 3)) < PLAIN_STD) & (blocks.mean(axis=(1, 3)) > PLAIN_MEAN)).mean())


def size_rows(video, rows, info=None, vision=None, width=448, ask=None):
    """Sizes and plain shares on the rows (in place) from three frames per shot: faces first, then the vision model on
    the faceless ones (vision None: when installed). ask(image_lists) -> [(facts, raw)] replaces the model (tests).
    Returns {'by': 'faces' | 'faces+vision', 'vision': {...} | None}."""
    import letitedit.looks.style_import as style_import
    import letitedit.looks.style_import_text as style_import_text
    info = info or style_import.probe(video)
    wanted = [row for row in rows if row['end_s'] - row['start_s'] > 0]
    times = sorted({t for row in wanted for t in _shot_times(row)})
    folder = Path(tempfile.mkdtemp(prefix='camera-'))
    try:
        import cv2
        frames = style_import.frames_at(video, times, width, info)
        paths, plain = {}, {}
        for t, frame in frames.items():
            path = folder / f'{t:010.3f}.jpg'
            cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            paths[t] = str(path)
            plain[t] = plain_share(frame)
        for row in wanted:
            shares = [plain[t] for t in _shot_times(row) if plain.get(t) is not None]
            row['plain'] = round(statistics.median(shares), 3) if shares else None
        track, have_faces = style_import_text.faces(sorted(paths.items()))
        faces_at = {t: found for t, found in track}
        faceless = []
        for row in wanted:
            heights = [found[0]['box'][3] - found[0]['box'][1] for t in _shot_times(row)
                       for found in [faces_at.get(round(t, 3)) or faces_at.get(t) or []] if found]
            height = statistics.median(heights) if heights else None
            row['face_height'] = round(height, 4) if height is not None else None
            size = face_size(height)
            if size:
                row['size'], row['size_by'] = size, 'face'
            else:
                faceless.append(row)
        use_vision = vision_ready() if vision is None else vision
        result = {'by': 'faces', 'faces_available': bool(have_faces), 'vision': None}
        if faceless and (use_vision or ask):
            asked = faceless
            if len(asked) > MAX_VISION_SHOTS:
                step = len(asked) / MAX_VISION_SHOTS
                asked = [asked[int(i * step)] for i in range(MAX_VISION_SHOTS)]
            lists = [[paths[t] for t in _shot_times(row) if t in paths] for row in asked]
            pairs = [(row, images) for row, images in zip(asked, lists) if images]
            try:
                if ask is None:
                    import letitedit.footage.factlog as factlog
                    answers, reply = factlog.ask([images for _, images in pairs])
                    model = reply.get('model')
                else:
                    answers, model = ask([images for _, images in pairs]), 'supplied'
                for (row, _), (facts, _raw) in zip(pairs, answers):
                    size = VISION_SHOT.get(str((facts or {}).get('shot', '')).strip().lower())
                    if size:
                        row['size'], row['size_by'] = size, 'vision'
                    kept = {k: (facts or {}).get(k) for k in SHOT_FACTS if (facts or {}).get(k) is not None}
                    if kept:
                        row['facts'] = kept       # what the shot shows (letitedit.looks.shot_mix reads it)
                result.update(by='faces+vision', vision={'model': model, 'asked': len(pairs), 'of': len(faceless)})
            except Exception as error:  # noqa: BLE001 - the vision model is extra; faces still stand
                result['vision'] = {'error': f'{type(error).__name__}: {error}'[:300]}
        for row in faceless:
            if row['size'] == 'unknown' and row.get('face_height') is not None:
                row['size'], row['size_by'] = 'wide', 'small_face'     # a person in it, small in the frame
        return result
    finally:
        for path in folder.glob('*'):
            path.unlink(missing_ok=True)
        folder.rmdir()


# ------------------------------------------------------------------ the mix

def _span_share(rows, key, wanted, start=None, end=None):
    """(share of the known time where rows[key] is in wanted, known seconds, all seconds) over [start, end)."""
    known = total = hit = 0.0
    for row in rows:
        a, b = row['start_s'], row['end_s']
        if start is not None:
            a, b = max(a, start), min(b, end)
        seconds = b - a
        if seconds <= 0:
            continue
        total += seconds
        if row[key] == 'unknown':
            continue
        known += seconds
        if row[key] in wanted:
            hit += seconds
    return (hit / known if known else None), known, total


def _shares(rows, key, names, start=None, end=None):
    known = {}
    for name in names:
        if name == 'unknown':
            continue
        share, seconds, _ = _span_share(rows, key, (name,), start, end)
        known[name] = round(share, 4) if share is not None else None
    return known


def window_seconds(rows):
    """The stretch length the reference is judged over: eight median shots, 8-30 s."""
    lengths = [row['end_s'] - row['start_s'] for row in rows if row['end_s'] > row['start_s']]
    median = statistics.median(lengths) if lengths else 1.0
    return round(min(30.0, max(8.0, 8 * median)), 2)


def windows(rows, seconds):
    """Overlapping stretches [(start, end)] of the given length, a quarter apart, over the rows' span."""
    if not rows:
        return []
    first, last = rows[0]['start_s'], rows[-1]['end_s']
    if last - first <= seconds:
        return [(first, last)]
    step = seconds / 4
    out = []
    t = first
    while t + seconds <= last + 1e-6:
        out.append((round(t, 3), round(t + seconds, 3)))
        t += step
    if out[-1][1] < last - 1e-6:
        out.append((round(last - seconds, 3), round(last, 3)))
    return out


def _one_size_share(rows, start, end):
    """(the share of the known-size time taken by its most common size, that size, known share) over a stretch."""
    shares = _shares(rows, 'size', SIZES, start, end)
    _, known, total = _span_share(rows, 'size', SIZES, start, end)
    shares = {name: share for name, share in shares.items() if share is not None}
    if not shares:
        return None, None, 0.0
    name = max(shares, key=shares.get)
    return shares[name], name, (known / total if total else 0.0)


def _plain(rows, start=None, end=None):
    """(time-weighted plain share of the shots without a person, their share of the stretch) over [start, end)."""
    seconds = weighted = total = 0.0
    for row in rows:
        a, b = row['start_s'], row['end_s']
        if start is not None:
            a, b = max(a, start), min(b, end)
        if b <= a:
            continue
        total += b - a
        if row.get('plain') is None or row.get('size_by') == 'face':
            continue
        seconds += b - a
        weighted += (b - a) * row['plain']
    return (weighted / seconds if seconds else None), (seconds / total if total else 0.0)


def profile(rows, sizes_by=None):
    """The mix of a video's shots (rows from measure or from_shots)."""
    rows = sorted(rows, key=lambda row: row['start_s'])
    moving, known_move, total = _span_share(rows, 'move', MOVING)
    _, known_size, _ = _span_share(rows, 'size', SIZES)
    seconds = window_seconds(rows)
    moving_by_stretch, one_size, plain_by_stretch = [], [], []
    for start, end in windows(rows, seconds):
        share, known, span = _span_share(rows, 'move', MOVING, start, end)
        if share is not None and span and known / span >= MIN_KNOWN:
            moving_by_stretch.append(share)
        top, _, known_share = _one_size_share(rows, start, end)
        if top is not None and known_share >= MIN_KNOWN:
            one_size.append(top)
        plain, known_share = _plain(rows, start, end)
        if plain is not None and known_share >= MIN_KNOWN:
            plain_by_stretch.append(plain)
    plain, _ = _plain(rows)
    lengths = [row['end_s'] - row['start_s'] for row in rows]
    return {'shots': len(rows), 'seconds': round(total, 3),
            'median_shot_s': round(statistics.median(lengths), 3) if lengths else None,
            'move_measured_share': round(known_move / total, 4) if total else 0.0,
            'moving_share': round(moving, 4) if moving is not None else None,
            'moves': _shares(rows, 'move', MOVES),
            'size_measured_share': round(known_size / total, 4) if total else 0.0,
            'sizes': _shares(rows, 'size', SIZES), 'sizes_by': sizes_by,
            'stretch_s': seconds,
            'stretch_moving_min': round(min(moving_by_stretch), 4) if moving_by_stretch else None,
            'stretch_one_size_max': round(max(one_size), 4) if one_size else None,
            'plain_share': round(plain, 4) if plain is not None else None,
            'stretch_plain_max': round(max(plain_by_stretch), 4) if plain_by_stretch else None}


def from_shots(shots, zooms=(), camera_moves=()):
    """A moves-only measure from an importer report's shots, zooms and camera moves (no frames read; sizes unknown)."""
    spans = zoom_spans(zooms, camera_moves)
    rows = [_row(shot, spans) for shot in shots or [] if shot.get('end', 0) > shot.get('start', 0)]
    return {'format': FORMAT, 'version': VERSION, 'shots': rows, 'profile': profile(rows),
            'method': METHOD, 'limits': LIMITS + ' Sizes were not measured for this reference.'}


# ------------------------------------------------------------------ one video

def _cache_file(video, vision):
    import letitedit.footage.footage_notes as footage_notes
    import letitedit.looks.style_import as style_import
    folder = Path(os.environ.get('LETITEDIT_CAMERA_CACHE') or (Path(style_import.CACHE).parent / 'camera'))
    return folder / f'{footage_notes.key(str(video))}-v{VERSION}-{"vision" if vision else "faces"}.json'


def measure(video, info=None, picture=None, vision=None, sizes=True, ask=None, cache=True):
    """Every shot of a video with its move and size, and its profile. picture: the importer's picture events for this
    video ({shots, zooms, camera_moves}: its report), else the importer's picture pass runs here (the same per-shot
    motion). Cached per file content when the picture pass runs here."""
    import letitedit.looks.style_import as style_import
    video = Path(video)
    use_vision = (vision_ready() if vision is None else bool(vision)) if sizes else False
    target = _cache_file(video, use_vision) if cache and picture is None and ask is None else None
    if target is not None and target.exists():
        try:
            return json.loads(target.read_text(encoding='utf-8-sig'))
        except ValueError:
            pass
    info = info or style_import.probe(video)
    info.setdefault('path', str(video))
    if picture is None:
        import letitedit.core.render_lock as render_lock
        with render_lock.slot('Look camera language', timeout_s=3600):
            picture = style_import.picture(video, info)
    spans = zoom_spans(picture.get('zooms'), picture.get('camera_moves'))
    rows = [_row(shot, spans) for shot in picture.get('shots') or [] if shot.get('end', 0) > shot.get('start', 0)]
    by = {'by': None}
    if sizes and rows:
        by = size_rows(video, rows, info, vision=use_vision, ask=ask)
    result = {'format': FORMAT, 'version': VERSION, 'file': str(video),
              'video_sha256': _sha256(video) if target is not None else None,
              'shots': rows, 'profile': profile(rows, by.get('by')), 'sizes': by, 'method': METHOD, 'limits': LIMITS}
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(result, indent=1), encoding='utf-8')
        temporary.replace(target)
    return result


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate(camera, duration=None):
    """A measured camera block (visual.json reference 'camera'), checked; returns it."""
    if not isinstance(camera, dict) or camera.get('format') != FORMAT:
        raise ValueError(f'camera must have format {FORMAT}')
    rows = camera.get('shots')
    if not isinstance(rows, list):
        raise ValueError('camera needs its measured shots')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('camera shots must be objects')
        start, end = row.get('start_s'), row.get('end_s')
        if (type(start) not in (int, float) or type(end) not in (int, float) or not 0 <= start < end
                or (duration is not None and end > duration + 0.5)):
            raise ValueError('camera shots need ordered spans inside the video')
        if row.get('move') not in MOVES or row.get('size') not in SIZES:
            raise ValueError('camera shot move or size is not a known name')
        plain = row.get('plain')
        if plain is not None and (type(plain) not in (int, float) or not 0 <= plain <= 1):
            raise ValueError('camera shot plain share must be 0-1')
    if not isinstance(camera.get('profile'), dict):
        raise ValueError('camera needs its profile')
    return camera


# ------------------------------------------------------------------ the check

def _comparable(rows, faces_only):
    """Rows with only the sizes both sides could measure (faces only when either side had no vision model)."""
    if not faces_only:
        return rows
    return [{**row, 'size': row['size'] if row.get('size_by') in ('face', 'small_face') else 'unknown'} for row in rows]


def _clock(seconds):
    return f'{int(seconds // 60)}:{seconds % 60:04.1f}'


def _merge(spans):
    out = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _items(script, start, end):
    """The footage clips of a timeline under a stretch of the export (ids, in time order)."""
    if not script:
        return []
    import letitedit.looks.grade as grade
    import letitedit.timeline.edit_script as edit_script
    found = []
    try:
        for _, item in grade._footage(script):
            at = edit_script.to_seconds(item['at'])
            if at < end - 1e-6 and at + float(item.get('len') or 0) > start + 1e-6:
                found.append((at, str(item['id'])))
    except Exception:  # noqa: BLE001 - the stretch's times stand without the clip names
        return []
    return list(dict.fromkeys(identity for _, identity in sorted(found)))


def _mix_words(shares):
    return ', '.join(f'{name.replace("_", " ")} {share:.0%}' for name, share in
                     sorted(((n, s) for n, s in shares.items() if s), key=lambda pair: -pair[1]))


def footage_log(script, folders=()):
    """The logged stretches of the footage behind a timeline: every video file in the folders of its footage clips
    (and `folders`), read from the fact log and the picture pass already cached (nothing is measured here).
    Returns {'stretches': [{file, path, from, to, shot, people, subject, moving, used_s, used}], 'unlogged': [file
    names]}: `used_s` the seconds of it the timeline's clips already show, `used` when they show most of it."""
    import letitedit.footage.factlog as factlog
    import letitedit.footage.perception as perception
    import letitedit.looks.grade as grade
    import letitedit.timeline.edit_script as edit_script
    used, places = {}, [Path(folder) for folder in folders or () if folder]
    try:
        for _, item in grade._footage(script or {'tracks': []}):
            path = Path(item['clip'])
            places.append(path.parent)
            start = edit_script.to_seconds(item.get('in') or 0)
            end = start + float(item.get('len') or 0) if item.get('out') is None else edit_script.to_seconds(item['out'])
            used.setdefault(os.path.normcase(str(path.resolve())), []).append((start, end))
    except Exception:  # noqa: BLE001 - without the timeline's clips, the folders given still stand
        pass
    files = []
    for place in dict.fromkeys(os.path.normcase(str(p.resolve())) for p in places):
        try:
            files += sorted(p for p in Path(place).iterdir() if p.suffix.lower() in factlog.VIDEO and p.is_file())
        except OSError:
            continue
    out = {'stretches': [], 'unlogged': []}
    for path in files[:MAX_LOGGED_FILES]:
        try:
            entry = factlog.facts(path, build=False)
        except Exception:  # noqa: BLE001 - an unreadable cache entry is a file not logged
            entry = None
        if not entry:
            out['unlogged'].append(path.name)
            continue
        spans = []
        try:
            if perception.is_cached('motion', path):
                spans = perception.picture(path).get('spans') or []
        except Exception:  # noqa: BLE001 - the moves are extra; the facts stand without them
            spans = []
        mine = used.get(os.path.normcase(str(path.resolve())), [])
        for stretch in entry.get('stretches') or []:
            a, b = float(stretch.get('from', 0)), float(stretch.get('to', 0))
            if b <= a:
                continue
            facts = stretch.get('facts') or {}
            moving = None
            if spans:
                moving = sum(max(0., min(b, s[1]) - max(a, s[0])) for s in spans
                             if s[2] not in ('steady', 'slight drift')) > .5 * (b - a)
            covered = sum(max(0., min(b, end) - max(a, start)) for start, end in mine)
            out['stretches'].append({'file': path.name, 'path': str(path), 'from': round(a, 2), 'to': round(b, 2),
                                     'shot': facts.get('shot'), 'people': facts.get('people'),
                                     'subject': facts.get('subject'), 'moving': moving,
                                     'used_s': round(covered, 2), 'used': covered > .5 * (b - a)})
    return out


def _fullness(stretch):
    return (2 * (str(stretch.get('people') or '0') != '0') + FULLER_SIZE.get(stretch.get('shot'), 0)
            + (1 if stretch.get('moving') else 0))


def candidates(log, kind):
    """Logged stretches mostly unused by the cut that would change a flagged stretch of this kind ('plain' or
    'one_size': people in view or a closer size; 'static': moving), fullest and least used first, at most two per
    file."""
    if not log:
        return []
    if kind == 'static':
        wanted = [s for s in log['stretches'] if not s['used'] and s.get('moving')]
    else:
        wanted = [s for s in log['stretches'] if not s['used'] and (str(s.get('people') or '0') != '0'
                                                                   or FULLER_SIZE.get(s.get('shot'), 0) > 0)]
    wanted.sort(key=lambda s: (-_fullness(s), s.get('used_s') or 0, s['file'], s['from']))
    out, per_file = [], {}
    for stretch in wanted:
        if per_file.get(stretch['file'], 0) >= 2:
            continue
        per_file[stretch['file']] = per_file.get(stretch['file'], 0) + 1
        out.append(stretch)
        if len(out) >= CANDIDATES:
            break
    return out


def _candidate_words(stretch):
    bits = [stretch.get('shot') or 'size not logged']
    people = str(stretch.get('people') or '0')
    bits.append('no people' if people == '0' else f"{people} {'person' if people == '1' else 'people'}")
    if stretch.get('moving') is not None:
        bits.append('moving' if stretch['moving'] else 'steady')
    if stretch.get('used_s'):
        bits.append(f"{stretch['used_s']:.1f} s of it in the cut, "
                    f"{max(0.0, stretch['to'] - stretch['from'] - stretch['used_s']):.1f} s not")
    return f"{stretch['file']} {_clock(stretch['from'])}-{_clock(stretch['to'])} ({', '.join(bits)})"


def _with_candidates(text, log, kind):
    """A flagged stretch's problem with the footage log's unused fuller (or moving) stretches named after it."""
    if log is None:
        return text, []
    found = candidates(log, kind)
    what = 'moving' if kind == 'static' else 'closer or with people'
    if found:
        text += (f"; stretches the footage's fact log names as {what}, mostly not in the cut: "
                 + '; '.join(map(_candidate_words, found)))
    elif log['stretches']:
        text += f"; the footage's fact log has no stretch {what} that the cut doesn't mostly show already"
    if log['unlogged']:
        text += (f"; {len(log['unlogged'])} file(s) not in the fact log ({', '.join(log['unlogged'][:4])}; "
                 "letitedit_footage with facts logs them)")
    return text, [{k: s[k] for k in ('file', 'from', 'to', 'shot', 'people', 'moving', 'used_s')} for s in found]


def plain_swaps(rows, limit, fill, start=None, end=None, seconds=None):
    """The plainest shots without a person over [start, end) (the whole cut without them) whose change to a fuller
    frame (plain share `fill`) brings the stretch's plain share under `limit` (with seconds, every stretch of that
    length inside it), plainest first: (shots, share after: the highest left). Every such shot when even all of them
    would not."""
    shots = [row for row in rows if row.get('plain') is not None and row.get('size_by') != 'face'
             and (start is None or (row['start_s'] < end and row['end_s'] > start))]
    spans = [(start, end)]
    if seconds and start is not None:
        spans = [(a, b) for a, b in windows(rows, seconds) if a >= start - 1e-6 and b <= end + 1e-6] or spans

    def highest(changed):
        shares = [_plain(changed, a, b)[0] for a, b in spans]
        shares = [share for share in shares if share is not None]
        return max(shares) if shares else None

    chosen, changed = [], set()
    after = highest(rows)
    for row in sorted(shots, key=lambda r: (-r['plain'], r['start_s'])):
        if after is None or after < limit:
            break
        changed.add(id(row))
        chosen.append(row)
        after = highest([{**r, 'plain': min(r['plain'], fill)} if id(r) in changed else r for r in rows])
    return chosen, after


def _swap_words(chosen, after, script, total, seconds):
    """The shots to change, in words: how many, which (with their clips), and the share they bring it to."""
    if not chosen:
        return ''
    named = []
    for row in chosen[:8]:
        ids = _items(script, row['start_s'] + 0.05, row['end_s'] - 0.05)
        named.append(f"{ids[0] + ' ' if ids else ''}{_clock(row['start_s'])} ({row['end_s'] - row['start_s']:.1f} s, "
                     f"{row['plain']:.0%} plain)")
    held = sum(row['end_s'] - row['start_s'] for row in chosen)
    return (f"; {len(chosen)} of its {total} shots without a person, the plainest ({held:.1f} s), would have to "
            f"become fuller frames to bring every {seconds:g} s of it to {after:.0%} or under: " + ', '.join(named)
            + (f" and {len(chosen) - 8} more" if len(chosen) > 8 else ''))


def ending(rows):
    """The shape of a video's ending: an end hold (a last row that is static or unknown with no plain share measured
    or none at all: black, a held card) set apart, then the last ENDING_SHOTS picture shots' moves and lengths."""
    rows = sorted(rows or [], key=lambda row: row['start_s'])
    if not rows:
        return None
    hold = 0.
    if len(rows) > 1 and rows[-1]['move'] in ('static', 'unknown') and not rows[-1].get('plain'):
        hold, rows = rows[-1]['end_s'] - rows[-1]['start_s'], rows[:-1]
    last = rows[-ENDING_SHOTS:]
    return {'hold_s': round(hold, 3), 'start_s': last[0]['start_s'],
            'shots': [{'move': row['move'], 'seconds': round(row['end_s'] - row['start_s'], 3)} for row in last]}


def _ending_problem(refs_rows, cut_rows, script):
    """The cut's last picture shot against the ending of the references (their own last shots)."""
    mine = ending(cut_rows)
    theirs = [shape for shape in (ending(rows) for rows in refs_rows) if shape]
    if not mine or not theirs:
        return None, None
    final = mine['shots'][-1]
    longest = max(shot['seconds'] for shape in theirs for shot in shape['shots'])
    own_last = max(shape['shots'][-1]['seconds'] for shape in theirs)
    moving_ref = all(sum(shot['move'] in MOVING for shot in shape['shots']) * 2 > len(shape['shots'])
                     for shape in theirs)
    summary = {'reference': theirs, 'cut': mine}
    long_final = final['seconds'] > ENDING_LONGER * longest and final['seconds'] > own_last + ENDING_SECONDS
    still_final = moving_ref and final['move'] not in MOVING and final['seconds'] > own_last
    if not (long_final or still_final):
        return summary, None
    end = cut_rows[-1]['end_s'] - mine['hold_s'] if cut_rows else 0
    ids = _items(script, end - final['seconds'], end)
    shape = theirs[0]
    text = (f"the cut's last picture shot ({_clock(end - final['seconds'])}-{_clock(end)}) holds {final['seconds']:.1f} s "
            f"{final['move'].replace('_', ' ')}; the reference's last {len(shape['shots'])} shots are "
            + ', '.join(f"{shot['move'].replace('_', ' ')} {shot['seconds']:.1f} s" for shot in shape['shots'])
            + (f", then a {shape['hold_s']:.1f} s end hold" if shape['hold_s'] else '')
            + (f" ({', '.join(ids)})" if ids else ''))
    return summary, text


def check(references, measured, script=None, folders=()):
    """The cut's camera language (measured: measure()'s result on its export) against its references' (each a
    visual.json 'camera' block). Returns (summary, problems): each problem names the stretch and, with the timeline
    (script), its items, and the unused stretches of the footage's fact log that are fuller or move (folders: the
    footage folders beyond those of the timeline's clips); the ending is the cut's last picture shot against the
    references' last shots."""
    references = [ref for ref in references or [] if ref and ref.get('shots')]
    rows = sorted(measured.get('shots') or [], key=lambda row: row['start_s'])
    if not references or not rows:
        return None, []
    faces_only = ('vision' not in str((measured.get('profile') or {}).get('sizes_by') or '')
                  or any('vision' not in str((ref.get('profile') or {}).get('sizes_by') or '') for ref in references))
    refs = [profile(_comparable(ref['shots'], faces_only), (ref.get('profile') or {}).get('sizes_by'))
            for ref in references]
    seconds = max(ref['stretch_s'] for ref in refs)
    cut_rows = _comparable(rows, faces_only)
    cut = profile(cut_rows, (measured.get('profile') or {}).get('sizes_by'))
    problems = []
    summary = {'reference': refs, 'cut': cut, 'stretch_s': seconds, 'sizes_compared': 'faces' if faces_only else
               'faces+vision', 'stretches': []}
    cache = []

    def logged():
        # the footage's fact log, read once and only when a stretch is flagged
        if not cache:
            try:
                cache.append(footage_log(script, folders) if script else None)
            except Exception:  # noqa: BLE001 - the stretch stands without its candidates
                cache.append(None)
        return cache[0]

    # moving against static, over the whole cut and stretch by stretch
    targets = [ref['moving_share'] for ref in refs if ref['moving_share'] is not None
               and ref['move_measured_share'] >= MIN_KNOWN]
    if targets and cut['moving_share'] is not None and cut['move_measured_share'] >= MIN_KNOWN:
        target = min(targets)
        if cut['moving_share'] < target - TOLERANCE_MOVING:
            problems.append(f"the cut is {cut['moving_share']:.0%} moving shots ({_mix_words(cut['moves'])}) against "
                            f"the reference's {target:.0%} ({_mix_words(refs[targets.index(target)]['moves'])}): "
                            "choose moving shots first, or give static ones a slow move")
        # a kind of move the reference relies on, missing from the cut
        for kind in MOVING:
            shares = [ref['moves'].get(kind) or 0 for ref in refs if ref['move_measured_share'] >= MIN_KNOWN]
            wanted = min(shares) if shares else 0
            have = cut['moves'].get(kind) or 0
            if wanted >= KIND_SHARE and have < KIND_FRACTION * wanted:
                problems.append(f"the reference has {KIND_WORDS[kind]} {wanted:.0%} of its time, the cut {have:.0%}"
                                + (': choose shots that move that way, or give static ones a slow push in'
                                   if kind == 'push_in' else ': choose shots that move that way'))
        floors = [ref['stretch_moving_min'] for ref in refs if ref['stretch_moving_min'] is not None]
        floor = min(floors) if floors else None
        if floor is not None:
            flagged = []
            for start, end in windows(cut_rows, seconds):
                share, known, span = _span_share(cut_rows, 'move', MOVING, start, end)
                if share is not None and span and known / span >= MIN_KNOWN and share < floor - TOLERANCE_STRETCH:
                    flagged.append((start, end))
            for start, end in _merge(flagged):
                share, _, _ = _span_share(cut_rows, 'move', MOVING, start, end)
                ids = _items(script, start, end)
                text, found = _with_candidates(
                    f"{_clock(start)}-{_clock(end)} is {share:.0%} moving; no {seconds:g} s of the reference is under "
                    f"{floor:.0%}" + (f" ({', '.join(ids[:8])})" if ids else ''), logged(), 'static')
                summary['stretches'].append({'kind': 'static', 'start_s': start, 'end_s': end,
                                             'moving_share': round(share, 3), 'items': ids, 'candidates': found})
                problems.append(text)

    # shot sizes: the mix, and stretches held at one size
    sized = [ref for ref in refs if ref['size_measured_share'] >= MIN_KNOWN]
    if sized and cut['size_measured_share'] >= MIN_KNOWN:
        best = None
        for ref in sized:
            names = [name for name in SIZES if name != 'unknown']
            distance = 0.5 * sum(abs((ref['sizes'].get(n) or 0) - (cut['sizes'].get(n) or 0)) for n in names)
            if best is None or distance < best[0]:
                best = (distance, ref)
        summary['size_distance'] = round(best[0], 3)
        if best[0] > TOLERANCE_SIZES:
            problems.append(f"shot sizes: the cut is {_mix_words(cut['sizes'])} against the reference's "
                            f"{_mix_words(best[1]['sizes'])}: vary the sizes the reference uses")
        ceilings = [ref['stretch_one_size_max'] for ref in sized if ref['stretch_one_size_max'] is not None]
        ceiling = max(ceilings) if ceilings else None
        if ceiling is not None and ceiling + TOLERANCE_ONE_SIZE < 1.0:
            flagged = []
            for start, end in windows(cut_rows, seconds):
                top, name, known_share = _one_size_share(cut_rows, start, end)
                if top is not None and known_share >= MIN_KNOWN and top > ceiling + TOLERANCE_ONE_SIZE:
                    flagged.append((start, end))
            for start, end in _merge(flagged):
                top, name, _ = _one_size_share(cut_rows, start, end)
                ids = _items(script, start, end)
                text, found = _with_candidates(
                    f"{_clock(start)}-{_clock(end)} is {top:.0%} {name} shots; no {seconds:g} s of the reference holds "
                    f"one size over {ceiling:.0%}" + (f" ({', '.join(ids[:8])})" if ids else ''), logged(), 'one_size')
                summary['stretches'].append({'kind': 'one_size', 'size': name, 'start_s': start, 'end_s': end,
                                             'share': round(top, 3), 'items': ids, 'candidates': found})
                problems.append(text)

    # how plain the frame is (open sky, bare walls) on shots without a person
    plains = [ref for ref in refs if ref.get('plain_share') is not None]
    if plains and cut.get('plain_share') is not None:
        mean = max(ref['plain_share'] for ref in plains)
        if cut['plain_share'] > mean + TOLERANCE_PLAIN:
            chosen, after = plain_swaps(cut_rows, mean + TOLERANCE_PLAIN, mean)
            total = sum(1 for row in cut_rows if row.get('plain') is not None and row.get('size_by') != 'face')
            summary['plain_swaps'] = {'shots': len(chosen), 'of': total,
                                      'after': round(after, 3) if after is not None else None}
            problems.append(f"the cut's frames without a person are {cut['plain_share']:.0%} plain (open sky, bare "
                            f"walls) against the reference's {mean:.0%}: choose fuller frames (closer, with foreground "
                            "or more in them) or crop in toward the subject"
                            + (f"; {len(chosen)} of its {total} shots without a person, the plainest, would have to "
                               f"become fuller frames to bring the cut to {after:.0%}" if chosen else ''))
        ceilings = [ref['stretch_plain_max'] for ref in plains if ref.get('stretch_plain_max') is not None]
        ceiling = max(ceilings) if ceilings else None
        if ceiling is not None:
            flagged = []
            for start, end in windows(cut_rows, seconds):
                share, known_share = _plain(cut_rows, start, end)
                if share is not None and known_share >= MIN_KNOWN and share > ceiling + TOLERANCE_PLAIN:
                    flagged.append((start, end))
            for start, end in _merge(flagged):
                share, _ = _plain(cut_rows, start, end)
                ids = _items(script, start, end)
                # the shots to change: the plainest, as many as bring the stretch under its bar with fuller frames
                chosen, after = plain_swaps(cut_rows, ceiling + TOLERANCE_PLAIN - PLAIN_MARGIN, mean, start, end, seconds)
                total = sum(1 for row in cut_rows if row.get('plain') is not None and row.get('size_by') != 'face'
                            and row['start_s'] < end and row['end_s'] > start)
                text, found = _with_candidates(
                    f"{_clock(start)}-{_clock(end)} is {share:.0%} plain frame; no {seconds:g} s of the reference is "
                    f"over {ceiling:.0%}" + (f" ({', '.join(ids[:8])})" if ids else '')
                    + _swap_words(chosen, after, script, total, seconds), logged(), 'plain')
                swaps = [{'start_s': row['start_s'], 'end_s': row['end_s'], 'plain': row['plain'],
                          'items': _items(script, row['start_s'] + 0.05, row['end_s'] - 0.05)} for row in chosen]
                summary['stretches'].append({'kind': 'plain', 'start_s': start, 'end_s': end,
                                             'plain_share': round(share, 3), 'items': ids, 'candidates': found,
                                             'swaps': swaps,
                                             'after_swaps': round(after, 3) if after is not None else None})
                problems.append(text)

    # the ending: the cut's last picture shot against the references' last shots
    if all(ref['move_measured_share'] >= MIN_KNOWN for ref in refs) and cut['move_measured_share'] >= MIN_KNOWN:
        shape, text = _ending_problem([ref['shots'] for ref in references], rows, script)
        if shape:
            summary['ending'] = shape
        if text:
            problems.append(text)
    return summary, problems


def recipe_line(camera):
    """One line for the recipe's measured visual profile."""
    mix = (camera or {}).get('profile') or {}
    if mix.get('moving_share') is None:
        return None
    sizes = {name: share for name, share in (mix.get('sizes') or {}).items() if share}
    return ('- Camera language: ' + f"{mix['moving_share']:.0%} of the measured time moving ({_mix_words(mix['moves'])})"
            + (f"; sizes {_mix_words(sizes)}" if sizes and mix.get('size_measured_share', 0) >= MIN_KNOWN else
               '; sizes not measured')
            + (f"; over any {mix['stretch_s']:g} s at least {mix['stretch_moving_min']:.0%} moving"
               if mix.get('stretch_moving_min') is not None else '')
            + (f"; frames without a person {mix['plain_share']:.0%} plain (open sky, bare walls), at most "
               f"{mix['stretch_plain_max']:.0%} over any {mix['stretch_s']:g} s"
               if mix.get('plain_share') is not None and mix.get('stretch_plain_max') is not None else '')
            + '. visual.json camera has every shot. The Look check measures the export against it.')
