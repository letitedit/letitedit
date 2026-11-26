"""Measured craft facts for the review (T346): the cuts a viewer can see, an insert held too briefly to read, how busy
the opening picture is against the rest of the video, and how long the picture runs after the last word.

Behind a switch, on by default: settings.json `review_craft_checks` (the environment variable
LETITEDIT_REVIEW_CRAFT_CHECKS, 1 or 0, wins). Off, the review runs exactly as before.

enabled()                        the switch.
visible_cuts(script, duration)   (cut times, note): where the picture a viewer sees changes. A main-track edge under an
                                 item on a higher shown video track that fills the frame is not a cut; that item's own
                                 edges are. The gate's project_cuts uses it while the switch is on.
visible_shots(script)            [{t0, t1, id, track, file}]: the runs of the topmost picture.
visible_frames(script)           (fps, [the topmost picture's item per frame]): what visible_shots runs on. A cover
                                 counts where the picture under it is seen: the whole frame, or the same window.
insert_holds(script)             findings: a shot from another file than both its neighbours (an insert, a cutaway) on
                                 screen for less than INSERT_MIN_S.
slivers(script)                  findings (T361): any shot on screen for less than SLIVER_S between two cuts, whatever
                                 its file (a leftover sliver of a trim reads as a flash).
opening_busy(video, ffmpeg)      a finding and its facts: the first second's edge density against the video's own.
speech_tail(project)             the seconds of picture after the last spoken word, measured on the cut's own words.
measured_music(project)          check_audio's own music-under-voice figure, when it was measured on this cut.
findings(project, video, ffmpeg) every finding above, as the review bundle's rows; facts(...) the plain line it shows.
"""
from __future__ import annotations

import os
import statistics
import subprocess
from pathlib import Path

SETTING = 'review_craft_checks'
FACTS_FILE = 'craft-facts.json'      # the numbers the critic reads beside the gate's (in the review folder)
ENV = 'LETITEDIT_REVIEW_CRAFT_CHECKS'

# An insert (a cutaway from another file) shorter than this reads as a flash, not a shot. [GEN] editors hold an insert
# long enough to be read; eye-tracking studies report that gaze takes about a third of a second to settle after a
# cut (Smith 2012, "The attentional theory of cinematic continuity"; Mital et al. 2011), so a 0.5 s insert leaves
# about 0.2 s to look at it. The reviewer's own fixes ask 1.3-1.8 s for a shot the viewer must read [OURS].
INSERT_MIN_S = 1.0
# Any shot between two cuts shorter than this is a sliver: the eye has not settled on it before it is gone (the same
# third of a second of gaze settling as above; Smith 2012, Mital et al. 2011) [STUDY for the direction]. The cut
# inspector's own scale agrees: 3 frames or fewer is a flash frame, 8 or fewer (0.27 s at 30 fps) noticeable
# (timing.cut_inspect_base, cuts.flash_frames / cuts.short_shot_frames). Set on the finished Shorts under tests/
# (T361): every shot under it was a visible flash in the export (Run 2's whip at 8.6 s, T327's 1 frame at 2.03 s,
# T301's at 6.3 s and 22.17 s), and the shortest deliberate shots measured 0.47-0.57 s [OURS].
SLIVER_S = 0.3
# The opening second against the video's own pictures: edge density, one of the standard measures of visual clutter
# (Rosenholtz, Li and Nakano 2007, "Measuring visual clutter", Journal of Vision 7(2)) [STUDY for the measure]. The
# first frame is designed like a thumbnail, the most recognisable thing of the premise [JH 2:34]; how busy is too
# busy is a judgment, so this is a minor finding with its numbers [HYP threshold].
BUSY_RATIO = 1.3          # the first second's edge density over the median second's
BUSY_TOP_SHARE = 0.25     # and among the busiest quarter of the video's seconds
EDGE_STEP = 24.0          # grey-level step between neighbouring pixels that counts as an edge (0-255, at 180x320)
# The picture after the last word: under this the video ends on the word itself [GEN: "keep a beat after the payoff
# line", letitedit-fine; a Look's recipe may ask for about half a second].
TAIL_MIN_S = 0.25

# effects that leave an item's picture whole and opaque (sound, colour, a zoom in): it still hides what is under it
SAFE_KEYS = {'fix', 'fade_in_audio', 'fade_out_audio', 'gain', 'floor_db', 'filter', 'params', 'grade', 'look',
             'speed', 'voice', 'denoise', 'eq', 'level'}
SAFE_FILTERS = {'color', 'lift_gamma_gain', 'brightness_level', 'saturation', 'white_balance', 'sharpen', 'denoise',
                'grade', 'lut', 'curves', 'levels', 'contrast', 'hue'}
GRAPHIC_MARKS = ('\\graphics\\', '/graphics/')
CAPTION_NAMES = ('word_captions', 'ass-', 'caption')
PICTURE_EXT = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.mpg', '.mpeg', '.wmv',
               '.jpg', '.jpeg', '.png', '.heic', '.webp', '.tif', '.tiff', '.gif', '.bmp'}


def enabled():
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


# ---------------------------------------------------------------------------- what the viewer sees

def _secs(value):
    import letitedit.timeline.edit_script as es
    return float(es.to_seconds(value))


def _rect_covers(value, width, height):
    """True when a size_position value ("x y w h [opacity]", or {'keys': [[t, value], ...]}) fills the whole frame,
    opaque, at every key."""
    values = [k[1] for k in value.get('keys') or []] if isinstance(value, dict) else [value]
    if not values:
        return False
    for v in values:
        parts = str(v).replace('%', '').split()
        if len(parts) < 4 or '%' in str(v):
            return False
        try:
            x, y, w, h = (float(p) for p in parts[:4])
            opacity = float(parts[4]) if len(parts) > 4 else 1.0
        except ValueError:
            return False
        if x > 0.5 or y > 0.5 or x + w < width - 0.5 or y + h < height - 0.5 or opacity < 0.99:
            return False
    return True


def _zoom_covers(value):
    values = [k[1] for k in value.get('keys') or []] if isinstance(value, dict) else [value]
    try:
        return bool(values) and all(float(v) >= 1.0 for v in values)
    except (TypeError, ValueError):
        return False


def _source(item):
    """The picture file an item shows, or None when it isn't footage or a still (a graphic, a caption, a title)."""
    freeze = item.get('freeze')
    clip = item.get('clip') or (freeze.get('clip') if isinstance(freeze, dict) else None)
    if item.get('color'):
        c = str(item['color'])
        return None if (len(c) == 9 and c.startswith('#') and c[1:3].lower() != 'ff') else f'color:{c}'
    if not clip:
        return None
    p = str(clip).replace('/', '\\').lower()
    name = os.path.basename(p)
    if os.path.splitext(name)[1] not in PICTURE_EXT or any(m.replace('/', '\\') in p for m in GRAPHIC_MARKS) or \
            name.startswith(CAPTION_NAMES):
        return None
    return str(clip)


def fills_frame(item, width, height):
    """True when an item on a higher track hides everything under it: footage or a still, whole frame, opaque."""
    return _opaque(item, width, height, whole=True)


def _opaque(item, width, height, whole):
    """True when the item is footage or a still drawn opaque, with nothing that lets the picture under it show
    through; whole: and it fills the frame (else its size_position may put it anywhere)."""
    if _source(item) is None or item.get('transition'):
        return False
    for e in item.get('effects') or []:
        if isinstance(e, str):
            if e not in ('mute',):
                return False
            continue
        if not isinstance(e, dict):
            return False
        for key, value in e.items():
            if key == 'size_position':
                if whole and not _rect_covers(value, width, height):
                    return False
                if not whole and _rects(item, width, height) is None:
                    return False
            elif key == 'zoom':
                if not _zoom_covers(value):
                    return False
            elif key == 'focus':
                continue
            elif key == 'filter':
                if str(value) not in SAFE_FILTERS:
                    return False
            elif key not in SAFE_KEYS:
                return False
    return True


def _rects(item, width, height):
    """[(x0, y0, x1, y1)] in pixels, clipped to the frame: where the item's picture is drawn at each key of its
    size_position, the whole frame without one; None when a key can't be read (a percentage, a short value) or draws
    the picture less than opaque."""
    out = None
    for e in item.get('effects') or []:
        if not (isinstance(e, dict) and 'size_position' in e):
            continue
        value = e['size_position']
        values = [k[1] for k in value.get('keys') or []] if isinstance(value, dict) else [value]
        if not values:
            return None
        out = []
        for v in values:
            parts = str(v).split()
            if len(parts) < 4 or '%' in str(v):
                return None
            try:
                x, y, w, h = (float(q) for q in parts[:4])
                opacity = float(parts[4]) if len(parts) > 4 else 1.0
            except ValueError:
                return None
            if opacity < 0.99:
                return None
            out.append((max(0.0, x), max(0.0, y), min(width, x + w), min(height, y + h)))
    return out if out is not None else [(0.0, 0.0, width, height)]


def holds(mine, theirs, slack=0.5):
    """True when every rectangle of mine contains every rectangle of theirs (pixels; slack for rounding)."""
    return bool(mine) and bool(theirs) and all(a[0] <= b[0] + slack and a[1] <= b[1] + slack and a[2] >= b[2] - slack
                                               and a[3] >= b[3] - slack for a in mine for b in theirs)


def visible_frames(script):
    """(fps, [rec or None per timeline frame]): each frame's topmost picture, rec = {id, track, file, f0, in_s, speed,
    frame, rects} of the item shown (in_s None for a held frame; rects where it is drawn, _rects). The main (first)
    video track always shows; an item on a higher shown video track shows over it when it fills the frame
    (fills_frame), or (T352) when it is opaque footage or a still drawn over the whole of the rectangle where the
    picture under it is seen: a cover in the same window of a Look that puts every shot in a window. A main-track item
    that comes in through a 'cut' transition shows from the transition's middle (T361: the engine switches there)."""
    prof = script.get('profile') or {}
    fps = float(prof.get('fps') or 30)
    width, height = float(prof.get('width') or 1920), float(prof.get('height') or 1080)
    total = int(round(_secs(script.get('length') or 0) * fps))
    tracks = [t for t in script.get('tracks') or [] if t.get('kind', 'video') == 'video'
              and t.get('hide') not in ('video', 'both')]
    top = [None] * max(0, total)
    for order, t in enumerate(tracks):
        for it in t.get('items') or []:
            if 'at' not in it or 'len' not in it:
                continue
            whole = True
            if order == 0:
                if _source(it) is None:
                    continue
            elif not fills_frame(it, width, height):
                if not _opaque(it, width, height, whole=False):
                    continue
                whole = False            # a windowed cover: over the frames whose shown picture it holds
            f0 = int(round(_secs(it['at']) * fps))
            f1 = min(total, f0 + int(round(float(it['len']) * fps)))
            rec = {'id': it.get('id'), 'track': t.get('name'), 'file': _source(it), 'f0': f0,
                   'in_s': it.get('in') if 'freeze' not in it else None, 'speed': float(it.get('speed') or 1.0),
                   'frame': _framing(it), 'rects': _rects(it, width, height) or [(0.0, 0.0, width, height)]}
            shown = f0 + (_cut_switch(it, fps) if order == 0 else 0)
            for f in range(max(0, shown), f1):
                if whole or (top[f] is not None and holds(rec['rects'], top[f]['rects'])):
                    top[f] = rec
    return fps, top


def _cut_switch(item, fps):
    """Frames into an item at which a 'cut' transition into it switches the picture: the middle of the overlap (the
    engine's luma wipe on a flat mid-grey map, edit_script_transitions), else 0 (a dissolve or a wipe starts showing
    the item from its first frame)."""
    import letitedit.timeline.edit_script as es
    try:
        spec = es.transition_spec(item.get('transition'))
    except (TypeError, ValueError):
        return 0
    if not spec or spec.get('type') != 'cut':
        return 0
    return (int(round(float(spec.get('len') or 0) * fps)) + 1) // 2


def visible_shots(script):
    """[{t0, t1, id, track, file}] in order: each run of the topmost picture (visible_frames)."""
    fps, top = visible_frames(script)
    shots = []
    for f, rec in enumerate(top):
        if shots and _continues(shots[-1]['rec'], rec, f, fps):
            shots[-1]['f1'] = f + 1
            continue
        shots.append({'rec': rec, 'f0': f, 'f1': f + 1})
    return [{'t0': round(s['f0'] / fps, 4), 't1': round(s['f1'] / fps, 4), 'id': (s['rec'] or {}).get('id'),
             'track': (s['rec'] or {}).get('track'), 'file': (s['rec'] or {}).get('file')} for s in shots]


def _framing(item):
    """The item's framing (its size_position and zoom effects), so a punch-in on the same take is still a cut."""
    return repr([{k: v for k, v in e.items() if k in ('size_position', 'zoom', 'focus')}
                 for e in item.get('effects') or [] if isinstance(e, dict) and ({'size_position', 'zoom'} & set(e))])


def _continues(prev, rec, f, fps):
    """True when frame f's picture carries straight on from the previous frame's (the same item, or the same file at
    the next source moment: a cut nobody sees)."""
    if prev is rec:
        return True
    if prev is None or rec is None or prev['file'] != rec['file'] or prev['in_s'] is None or rec['in_s'] is None \
            or abs(prev['speed'] - rec['speed']) > 1e-6 or prev.get('frame') != rec.get('frame'):
        return False
    a_src = float(prev['in_s']) + (f - prev['f0']) * prev['speed'] / fps
    b_src = float(rec['in_s']) + (f - rec['f0']) * rec['speed'] / fps
    return abs(a_src - b_src) <= 1.5 / fps


def visible_cuts(script, duration):
    """(cut times, note) of the picture a viewer sees: the gate's project_cuts with the covered edges left out."""
    shots = visible_shots(script)
    if not shots:
        return [], ''
    length = shots[-1]['t1']
    if abs(length - duration) > 1.0:
        return [], f"the project's picture ({length:.1f} s) isn't this export's length ({duration:.1f} s), so its cuts weren't used"
    cuts = [round(s['t0'], 3) for s in shots[1:] if s['file'] is not None and 0 < s['t0'] < duration]
    return cuts, ''


def hidden_edges(script):
    """Main-track edges the viewer never sees (an item on a higher track hides them): the times the gate counted before
    the switch and doesn't now."""
    from letitedit.timeline.edit_sync import layout, main_track
    main = main_track(script)
    if main is None:
        return []
    pieces = list(layout(main))
    old = []
    for (a, _, _), (b, start, _) in zip(pieces, pieces[1:]):
        same = a.get('clip') and a.get('clip') == b.get('clip') and abs(float(b.get('in', 0)) - float(a.get('out', 0))) <= 0.05
        if not same:
            old.append(round(float(start), 3))
    seen = [s['t0'] for s in visible_shots(script)]
    return [t for t in old if not any(abs(t - s) <= 0.05 for s in seen)]


def _inserts(script):
    """The visible shots from another file than the shots on both sides of them."""
    shots = [s for s in visible_shots(script) if s['file'] is not None]
    return [s for prev, s, nxt in zip([None] + shots[:-1], shots, shots[1:] + [None])
            if prev is not None and nxt is not None and s['file'] not in (prev['file'], nxt['file'])]


def insert_holds(script, markers=()):
    """[{'at', 'severity', 'what', 'fix', 'check'}]: an insert (a shot from another file than the shots on both
    sides of it) on screen for less than INSERT_MIN_S. A `flash:` marker inside it says the flash is meant."""
    out = []
    for s in _inserts(script):
        held = s['t1'] - s['t0']
        if held >= INSERT_MIN_S:
            continue
        if any(s['t0'] - 0.05 <= float(t) <= s['t1'] + 0.05 and str(text).lower().startswith('flash:')
               for t, text in markers):
            continue
        name = os.path.basename(str(s['file']))
        out.append({'at': s['t0'], 'severity': 'major', 'check': 'insert_hold',
                    'what': f"the insert from {name} ({s['id']}) is on screen for {held:.2f} s "
                            f"({s['t0']:.2f}-{s['t1']:.2f}), between shots of another file: under {INSERT_MIN_S:g} s "
                            "an insert reads as a flash",
                    'fix': 'Hold it longer (a steadier stretch of the file, a held frame, or a slower speed), move it '
                           'under a line with room for it, or leave it out; a `flash:` marker says a flash is meant.'})
    return out


def _flash_meant(shot, markers):
    return any(shot['t0'] - 0.05 <= float(t) <= shot['t1'] + 0.05 and str(text).lower().startswith('flash:')
               for t, text in markers)


def slivers(script, markers=()):
    """[{'at', 't1', 'severity', 'what', 'fix', 'check'}]: a shot of footage or a still on screen for less than
    SLIVER_S between two cuts in what the viewer sees (visible_shots), from any file: a leftover sliver of a trim, a
    clip that ends a few frames after a cover starts. A `flash:` marker inside it says the flash is meant."""
    fps = float((script.get('profile') or {}).get('fps') or 30)
    shots = visible_shots(script)
    out = []
    for prev, s, nxt in zip(shots, shots[1:], shots[2:]):
        held = s['t1'] - s['t0']
        if s['file'] is None or held >= SLIVER_S - 1e-6 or _flash_meant(s, markers):
            continue
        frames = max(1, int(round(held * fps)))
        side = [f"{x['id']} ({os.path.basename(str(x['file']))})" if x['file'] else 'no picture' for x in (prev, nxt)]
        out.append({'at': s['t0'], 't1': s['t1'], 'severity': 'major', 'check': 'sliver_shot',
                    'what': f"a {frames}-frame shot ({held:.2f} s, {s['t0']:.2f}-{s['t1']:.2f}) of "
                            f"{os.path.basename(str(s['file']))} ({s['id']}) between {side[0]} and {side[1]}: under "
                            f"{SLIVER_S:g} s the eye can't settle on a shot, so it reads as a flash",
                    'fix': 'Take the sliver out: run the shot before it on to the next cut, or start the shot after '
                           'it that much earlier (a cover that starts a few frames after a cut can start on the cut); '
                           'a `flash:` marker says a flash is meant.'})
    return out


# ---------------------------------------------------------------------------- the opening picture

def edge_density_seconds(video, ffmpeg, fps=4, size=(180, 320)):
    """[edge density per second of the video] at a small size: the share of pixels whose grey step to a neighbour is
    over EDGE_STEP."""
    import numpy as np
    w, h = size
    raw = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(video), '-vf',
                          f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=disable,format=gray',
                          '-f', 'rawvideo', '-'], capture_output=True, timeout=600,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    frames = np.frombuffer(raw, np.uint8)
    if frames.size < w * h:
        return []
    frames = frames[:frames.size // (w * h) * (w * h)].reshape(-1, h, w).astype(np.float32)
    per_frame = []
    for f in frames:
        gx = np.abs(np.diff(f, axis=1))[:-1, :]
        gy = np.abs(np.diff(f, axis=0))[:, :-1]
        per_frame.append(float((np.hypot(gx, gy) > EDGE_STEP).mean()))
    return [round(sum(per_frame[i:i + fps]) / len(per_frame[i:i + fps]), 4) for i in range(0, len(per_frame), fps)]


def opening_busy_from(seconds):
    """(finding or None, facts) from the per-second edge densities."""
    if len(seconds) < 4:
        return None, {}
    first, median = seconds[0], statistics.median(seconds)
    rank = sorted(seconds, reverse=True).index(first) + 1
    facts = {'first_second': first, 'median_second': median, 'ratio': round(first / median, 2) if median else None,
             'rank': rank, 'seconds': len(seconds)}
    busy = median > 0 and first >= BUSY_RATIO * median and rank <= max(1, int(len(seconds) * BUSY_TOP_SHARE))
    if not busy:
        return None, facts
    return {'at': 0.0, 'severity': 'minor', 'check': 'opening_busy',
            'what': f"the opening second is one of the busiest pictures in the video: edge density {first:.3f} against "
                    f"the median second's {median:.3f} ({facts['ratio']}x; busiest {rank} of {len(seconds)}): a "
                    "small subject in a wide, cluttered frame reads slowly on a phone",
            'fix': 'Look at frames 0 and 1 s at full size: when the subject is small in a busy frame, open on the '
                   'tightest steady shot of it (a muted cover over the same words), or say why the busy picture is '
                   'the subject.'}, facts


# ---------------------------------------------------------------------------- the end

def _muted(item):
    """A clip whose sound is off (as the ending checks read it: a 'mute' effect)."""
    return any(e == 'mute' or (isinstance(e, dict) and 'mute' in e) for e in item.get('effects') or [])


def speech_tail(project):
    """{'tail_s', 'last_word', 'word_end_s', 'end_s', 'id'} or None: seconds from the end of the cut's last spoken word
    to the end of the video, on the cut's own words (the speech tracks' clips, as the ending checks read them)."""
    import letitedit.timeline.edit_script as es
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import layout
    from letitedit.timeline.timeline_speech import NOT_SPEECH
    script = es.read(project)
    end_s = _secs(script.get('length') or 0)
    last = None
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            if 'clip' not in it or it.get('reverse') or _muted(it) or float(it.get('speed', 1)) != 1:
                continue
            a, b = float(it['in']), float(it['out'])
            ws = speech.sound_words(it['clip'], a - 0.5, b + 0.5, cached=True) or []
            inside = [w for w in ws if float(w['s']) < b - 0.02 and float(w['e']) > a + 0.02]
            if not inside:
                continue
            w = inside[-1]
            at = s + (min(float(w['e']), b) - a)
            if last is None or at > last['word_end_s']:
                last = {'word_end_s': round(at, 3), 'last_word': w.get('w'), 'id': it.get('id')}
    if last is None:
        return None
    return dict(last, end_s=round(end_s, 3), tail_s=round(end_s - last['word_end_s'], 3))


# ---------------------------------------------------------------------------- for the review bundle

def project_markers(project):
    """[(start_s, text)] of a project's timeline markers (Shotcut's shotcut:markers)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(project)).getroot()
    except (OSError, ET.ParseError):
        return []
    out = []
    for group in root.iter('properties'):
        if group.get('name') != 'shotcut:markers':
            continue
        for m in group.findall('properties'):
            vals = {p.get('name'): (p.text or '') for p in m.findall('property')}
            try:
                out.append((_secs(vals.get('start') or 0), vals.get('text', '')))
            except Exception:  # noqa: BLE001 - an unreadable marker is no waiver
                continue
    return out


def findings(project, video, ffmpeg, numbers=False):
    """(findings, facts line): the slivers, the insert holds, the opening picture and the speech tail, for the review
    bundle; with numbers=True also {name: value} of what was measured, for the critic's measurements."""
    import letitedit.timeline.edit_script as es
    out, facts, nums = [], [], {}
    script = es.read(project)
    markers = project_markers(project)
    slim = slivers(script, markers)
    out += slim
    holds = [h for h in insert_holds(script, markers) if not any(abs(h['at'] - s['at']) < 1e-3 for s in slim)]
    out += holds
    hidden = hidden_edges(script)
    nums['hidden_main_track_edges_s'] = hidden
    nums['shortest_insert_s'] = min((round(s['t1'] - s['t0'], 3) for s in _inserts(script)), default=None)
    between = [s for s in visible_shots(script)[1:-1] if s['file'] is not None]
    nums['shortest_shot_between_cuts_s'] = min((round(s['t1'] - s['t0'], 3) for s in between), default=None)
    nums['shots_under_%gs' % SLIVER_S] = [[round(s['at'], 3), round(s['t1'], 3)] for s in slim]
    facts.append(f"{len(slim)} shot(s) under {SLIVER_S:g} s between two cuts"
                 + (f" (shortest {nums['shortest_shot_between_cuts_s']:.2f} s)"
                    if nums['shortest_shot_between_cuts_s'] is not None else ''))
    facts.append(f"{len(holds)} insert(s) under {INSERT_MIN_S:g} s"
                 + (f"; main-track edges hidden under a cover, not counted as cuts: {', '.join(f'{t:.2f}' for t in hidden)}"
                    if hidden else ''))
    try:
        finding, busy = opening_busy_from(edge_density_seconds(video, ffmpeg))
        if finding:
            out.append(finding)
        if busy:
            nums.update(opening_edge_density=busy['first_second'], median_second_edge_density=busy['median_second'],
                        opening_busiest_rank=f"{busy['rank']} of {busy['seconds']}")
            facts.append(f"opening second's edge density {busy['first_second']:.3f}, the median second's "
                         f"{busy['median_second']:.3f} (busiest {busy['rank']} of {busy['seconds']})")
    except Exception as e:  # noqa: BLE001 - said, never a pass
        facts.append(f'opening picture not measured ({type(e).__name__})')
    tail = None
    try:
        tail = speech_tail(project)
    except Exception as e:  # noqa: BLE001 - said, never a pass
        facts.append(f'speech tail not measured ({type(e).__name__})')
    if tail:
        nums['speech_tail_s'] = tail['tail_s']
        facts.append(f"the last word (\"{tail['last_word']}\", {tail['id']}) ends {tail['tail_s']:.2f} s before the end "
                     "(measured on the cut's words; the gate's tail_silence_s counts the whole mix, music included)")
        if tail['tail_s'] < TAIL_MIN_S:
            out.append({'at': tail['word_end_s'], 'severity': 'minor', 'check': 'speech_tail',
                        'what': f"the video ends {tail['tail_s']:.2f} s after its last word (\"{tail['last_word']}\"): "
                                "no beat after the payoff",
                        'fix': "Let the picture run on past the voice (an L-cut: a cover or the same shot held, with "
                               "room tone or the music), never by running the voice clip into the source's next sound."})
    return (out, '; '.join(facts), nums) if numbers else (out, '; '.join(facts))


MUSIC_KEY = "music_below_voice_while_talking_lu (letitedit_check_audio on this cut's own music and voice tracks)"


def measured_music(project):
    """{MUSIC_KEY: LU} from letitedit_check_audio(stems=True)'s stored measurement when it was made on this very cut
    (the same sound signature), else {}: the music level as the check states it, without a new render (T349)."""
    import letitedit.review.checks as checks
    settings = {'stems': True, 'target_lufs': -14.0, 'start_s': None, 'end_s': None, 'every_s': None, 'quiet_lu': 15.0}
    hit = checks.audio_measured(str(project), checks.audio_signature(str(project)), **settings)
    gap = (hit[1] or {}).get('music_below_voice_while_talking_lu') if hit else None
    return {} if gap is None else {MUSIC_KEY: gap}


def critic_numbers(numbers, craft):
    """The critic's measurements with the craft numbers: tail_silence_s named for what it measures (the whole mix,
    music included) and the time after the last word beside it."""
    out = dict(numbers)
    if 'tail_silence_s' in out:
        out['tail_silence_s (the whole mix, music included)'] = out.pop('tail_silence_s')
    out.update(craft or {})
    return out


def gate_tail_note():
    """The gate's tail_silence_s note while the switch is on."""
    return ('end soon after the payoff; silence at the end of the whole mix, music included (with music under the '
            'ending it stays near 0 whatever the speech does): the time after the last word is measured apart')
