"""What each indexed moment shows and sounds like (contract 1.2; CONTRACT.md section 6, "index", "Moment fields").

Five optional fields per moment, each value with `confidence` (0-1) and `how`; the value lists are open:
    shot      framing (close-up, medium, wide, detail, screen, talking head) and camera (still, handheld, pan, tilt,
              moving vehicle, drone, timelapse, slow motion)
    sound     speech yes/no; music yes/no and music_source (scene or added); ambient in a few words; events
    subjects  the main people, animals and objects seen
    setting   indoors_outdoors, place_kind (a kind of place in plain words, never a place's name) and time_of_day
    energy    calm, steady or lively; with b_roll_fit (yes/no) and best_frame_s (a time in the file)

Where each comes from:
- On every index, local and cheap: camera still, handheld, pan and tilt from letitedit's motion analysis
  (perception.picture); timelapse and slow motion from the file's frame rates and tags; framing close-up, medium,
  wide or talking head from the size of the largest face in the moment's best frame (OpenCV's YuNet, when its model is
  on the PC; no download); speech from the words or the voice detector; music present from the sound detector
  (perception.sounds); ambient and events in that detector's words (bangs, clicks, thuds, repeated hits, engine-like
  hums, steady noise, music, beeps, quiet); energy, b_roll_fit and best_frame_s from motion, sharpness, words and sound.
- Best effort, from letitedit's vision pass (the fact log, factlog.py: a local vision model, about 6 s of graphics card
  time per 8 s stretch): framing wide, detail and screen; camera moving vehicle; subjects; setting. Read when the
  file's fact log is already on the PC, or made when the job's steps include `vision`. Absent otherwise, and the
  result's steps_skipped says for how many files. Nothing tells a drone shot or where music comes from yet
  (music_source), so those are absent, and steps_skipped says so.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

DETECTOR, VISION, TRANSCRIPT, METADATA = 'detector', 'vision_model', 'transcript', 'file_metadata'
FACE_CLOSE, FACE_MEDIUM, FACE_WIDE = 0.28, 0.10, 0.02   # a face's height as a share of the frame's
SLOW_FPS, TIMELAPSE_FPS = 100.0, 10.0
EVENT_WORDS = {'bang': 'bang', 'clank': 'clank', 'click': 'click', 'thud': 'thud', 'hits': 'repeated hits',
               'tone': 'beep', 'quiet': 'quiet'}


def _v(value, confidence, how, **more):
    out = {'value': value, 'confidence': round(float(confidence), 2), 'how': how}
    out.update({k: v for k, v in more.items() if v is not None})
    return out


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ------------------------------------------------------------------ what the file holds, read once per file

def file_facts(path, kind, info, vision=False):
    """The analyses every moment of a file draws on: motion, sound, voice, the fact log (when it exists or `vision`
    asks for it), rates and tags. Each piece is None when it can't be read."""
    import letitedit.core.render_lock as render_lock
    import letitedit.footage.perception as perception
    out = {'path': str(path), 'kind': kind, 'info': info or {}, 'picture': None, 'sounds': None, 'voice': None,
           'facts': None, 'accuracy': {}}
    with render_lock.render_slot(f'index: the picture and sound of {Path(path).name}'):
        if kind == 'video':
            try:
                out['picture'] = perception.picture(str(path))
            except Exception:  # noqa: BLE001 - a field it would give is left out
                pass
        try:
            out['sounds'] = perception.sounds(str(path))
        except Exception:  # noqa: BLE001
            pass
    try:
        import letitedit.sound.music as music
        out['voice'] = music.voice_times(str(path))
    except Exception:  # noqa: BLE001
        pass
    if kind == 'video':
        try:
            import letitedit.footage.factlog as factlog
            out['facts'] = factlog.facts(str(path), build=bool(vision))
            out['accuracy'] = factlog.accuracy() or {}
        except Exception:  # noqa: BLE001 - the vision pass is best effort
            out['facts'] = None
    return out


# ------------------------------------------------------------------ per moment

def _seconds(ff, a, b):
    pic = ff.get('picture') or {}
    rows = pic.get('seconds') or []
    return [(s, rows[s]) for s in range(len(rows)) if _overlap(s, s + 1, a, b) >= 0.5 or (b - a < 1 and s == int(a))]


def _camera_word(label):
    label = str(label or '')
    if label in ('steady', 'slight drift'):
        return 'still'
    if 'pan' in label:
        return 'pan'
    if 'tilt' in label:
        return 'tilt'
    if 'handheld' in label or 'shak' in label or 'whip' in label:
        return 'handheld'
    return None


def _rates(ff):
    """slow motion or timelapse from the file's own rates and tags, or None."""
    info = ff.get('info') or {}
    tags = ' '.join(str(v) for v in list((info.get('tags') or {}).values())
                    + list((info.get('tags_video') or {}).values())).lower()
    fps = float(info.get('fps') or 0)
    if 'slow' in tags and 'motion' in tags or 'slo-mo' in tags or fps >= SLOW_FPS:
        return _v('slow motion', 0.85 if fps >= SLOW_FPS else 0.7, METADATA)
    if 'time-lapse' in tags or 'timelapse' in tags or 0 < fps <= TIMELAPSE_FPS:
        return _v('timelapse', 0.8 if ('lapse' in tags) else 0.6, METADATA)
    return None


def camera(ff, a, b):
    rated = _rates(ff)
    if rated:
        return rated
    words = [_camera_word(row[0]) for _, row in _seconds(ff, a, b)]
    words = [w for w in words if w]
    if not words:
        return None
    best = max(set(words), key=words.count)
    share = words.count(best) / len(words)
    return _v(best, 0.5 + 0.35 * share, DETECTOR)


def _face_model():
    import letitedit.review.checks as checks
    return checks.YUNET if checks.YUNET.is_file() else None


def face_boxes(path, times, width=640):
    """Every face seen at the given times of a video, as boxes [x, y, w, h] (fractions of the frame); [] when none is
    seen or there is no face model on the PC (none is downloaded)."""
    model = _face_model()
    if model is None:
        return []
    import cv2
    import letitedit.core.media as media
    out = []
    with tempfile.TemporaryDirectory(prefix='studio-faces-') as tmp:
        for n, at in enumerate(times):
            png = Path(tmp) / f'f{n}.png'
            try:
                subprocess.run([str(media.ffmpeg()), '-y', '-v', 'error', '-nostdin', '-ss', f'{max(0.0, at):.3f}',
                                '-i', str(path), '-frames:v', '1', '-vf', f'scale={width}:-2', str(png)],
                               capture_output=True, timeout=60, creationflags=0x08000000 if os.name == 'nt' else 0)
            except (OSError, subprocess.SubprocessError):
                continue
            img = cv2.imread(str(png))
            if img is None:
                continue
            h, w = img.shape[:2]
            det = cv2.FaceDetectorYN.create(str(model), '', (w, h), 0.75, 0.3, 20)
            _, found = det.detect(img)
            for f in found if found is not None else []:
                if f[2] >= 10:
                    out.append([round(float(f[0]) / w, 4), round(float(f[1]) / h, 4), round(float(f[2]) / w, 4),
                                round(float(f[3]) / h, 4)])
    return out


def largest_face(path, at, width=640):
    """The largest face's height as a share of the frame's at `at` seconds, 0.0 for none, None when it can't be told
    (no face model on the PC: none is downloaded)."""
    model = _face_model()
    if model is None:
        return None
    import cv2
    import letitedit.core.media as media
    with tempfile.TemporaryDirectory(prefix='studio-face-') as tmp:
        png = Path(tmp) / 'f.png'
        try:
            subprocess.run([str(media.ffmpeg()), '-y', '-v', 'error', '-nostdin', '-ss', f'{max(0.0, at):.3f}', '-i',
                            str(path), '-frames:v', '1', '-vf', f'scale={width}:-2', str(png)], capture_output=True,
                           timeout=60, creationflags=0x08000000 if os.name == 'nt' else 0)
        except (OSError, subprocess.SubprocessError):
            return None
        img = cv2.imread(str(png))
    if img is None:
        return None
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(str(model), '', (w, h), 0.75, 0.3, 20)
    _, found = det.detect(img)
    heights = [float(f[3]) for f in (found if found is not None else []) if f[2] >= 10]
    return round(max(heights) / h, 3) if heights else 0.0


def _majority(stretches, key):
    votes = {}
    for s, weight in stretches:
        v = (s.get('facts') or {}).get(key)
        if isinstance(v, list):
            for x in v:
                votes[x] = votes.get(x, 0) + weight
        elif v not in (None, ''):
            votes[v] = votes.get(v, 0) + weight
    if not votes:
        return None, 0.0
    best = max(votes, key=votes.get)
    return best, votes[best] / max(1e-6, sum(w for _, w in stretches))


def _stretches(ff, a, b):
    facts = ff.get('facts') or {}
    out = []
    for s in facts.get('stretches') or []:
        o = _overlap(float(s.get('from', 0)), float(s.get('to', 0)), a, b)
        if o > 0:
            out.append((s, o))
    return out


def framing(ff, a, b, face, talking, cam):
    """From the face first (people); then the vision pass's shot and subject for wide, detail and screen."""
    st = _stretches(ff, a, b)
    acc = ff.get('accuracy') or {}
    shot, share = _majority(st, 'shot')
    subject, sshare = _majority(st, 'subject')
    if subject == 'screen' and sshare >= 0.5:
        return _v('screen', min(0.9, acc.get('subject', 0.7)) * sshare, VISION)
    if face:
        if talking and face >= FACE_MEDIUM and (cam or {}).get('value') == 'still':
            return _v('talking head', 0.75, DETECTOR)
        if face >= FACE_CLOSE:
            return _v('close-up', 0.75, DETECTOR)
        if face >= FACE_MEDIUM:
            return _v('medium', 0.7, DETECTOR)
        if face >= FACE_WIDE:
            return _v('wide', 0.55, DETECTOR)
    if shot in ('wide', 'detail', 'close-up', 'medium'):
        return _v(shot, min(0.9, acc.get('shot', 0.7)) * share, VISION)
    return None


def _speech_share(ff, a, b, words):
    if words is not None:
        spoken = sum(_overlap(w['s'], w['e'], a, b) for w in words)
        return spoken / max(0.2, b - a), TRANSCRIPT
    voice = ff.get('voice')
    if voice is None:
        return None, None
    return sum(_overlap(float(x), float(y), a, b) for x, y in voice) / max(0.2, b - a), DETECTOR


def _event_word(e):
    kind = e.get('kind')
    if kind == 'sustained':
        d = str(e.get('desc') or '')
        if 'music' in d:
            return 'music'
        if 'hum' in d or 'motor' in d or 'grinding' in d or 'whirr' in d or 'machine' in d:
            return 'engine-like hum'
        if 'rumble' in d:
            return 'rumble'
        return 'steady noise'
    return EVENT_WORDS.get(kind, kind)


def sound(ff, a, b, words):
    s = ff.get('sounds') or {}
    out = {}
    share, how = _speech_share(ff, a, b, words)
    if share is not None:
        out['speech'] = _v('yes' if share >= 0.15 else 'no', 0.85 if how == TRANSCRIPT else 0.7, how)
    if not s:
        return out or None
    events = []
    for e in s.get('events') or []:
        t0, t1 = float(e.get('t0', e.get('t', 0))), float(e.get('t1', e.get('t', 0)))
        if _overlap(t0, max(t1, t0 + 0.05), a, b) <= 0:
            continue
        word = _event_word(e)
        if word is None:
            continue
        ev = _v(word, 0.6, DETECTOR)
        if 't' in e:
            ev['at'] = round(float(e['t']), 2)
        else:
            ev['from'], ev['to'] = round(max(t0, a), 2), round(min(t1, b), 2)
        events.append(ev)
    music = any(ev['value'] == 'music' for ev in events)
    out['music'] = _v('yes' if music else 'no', 0.6, DETECTOR)
    room = s.get('room_db')
    hums = [ev for ev in events if ev['value'] in ('engine-like hum', 'rumble', 'steady noise')]
    if music:
        ambient = 'music'
    elif hums:
        ambient = hums[0]['value']
    elif any(ev['value'] == 'quiet' for ev in events) or (room is not None and room <= -55):
        ambient = 'quiet'
    elif room is not None and room >= -35:
        ambient = 'loud room'
    else:
        ambient = 'room tone'
    out['ambient'] = _v(ambient, 0.55, DETECTOR)
    shown = [ev for ev in events if ev['value'] != 'quiet' or ambient != 'quiet']
    if shown:
        out['events'] = shown[:12]
    return out


def subjects(ff, a, b):
    st = _stretches(ff, a, b)
    if not st:
        return None
    acc = ff.get('accuracy') or {}
    votes = {}
    total = sum(w for _, w in st)
    for s, w in st:
        f = s.get('facts') or {}
        for x in (f.get('subject') if isinstance(f.get('subject'), list) else [f.get('subject')]):
            if x and x != 'other':
                votes[x] = votes.get(x, 0) + w
        people = f.get('people')
        if people not in (None, '', '0', 0):
            votes['person'] = votes.get('person', 0) + w
    out = [_v(k, min(0.9, acc.get('subject', 0.7)) * min(1.0, v / total), VISION)
           for k, v in sorted(votes.items(), key=lambda kv: -kv[1]) if v / total >= 0.25]
    return out[:5] or None


def setting(ff, a, b):
    st = _stretches(ff, a, b)
    if not st:
        return None
    acc = ff.get('accuracy') or {}
    out = {}
    io, share = _majority(st, 'io')
    if io:
        out['indoors_outdoors'] = _v(io, min(0.95, acc.get('io', 0.8)) * share, VISION)
    place, share = _majority(st, 'place')
    if place and place != 'other':
        out['place_kind'] = _v(place, min(0.9, acc.get('place', 0.6)) * share, VISION)
    light, share = _majority(st, 'light')
    if light:
        out['time_of_day'] = _v({'low light': 'dusk or dark'}.get(light, light), min(0.9, acc.get('light', 0.7)) * share,
                                VISION)
    return out or None


def moving_vehicle(ff, a, b, cam):
    place, share = _majority(_stretches(ff, a, b), 'place')
    if place in ('inside a vehicle', 'road') and share >= 0.5 and (cam or {}).get('value') in ('handheld', 'pan', 'still'):
        motion = [row[1] for _, row in _seconds(ff, a, b) if len(row) > 1]
        if place == 'inside a vehicle' or (motion and sum(motion) / len(motion) >= 0.15):
            return _v('moving vehicle', 0.5 * share, VISION)
    return None


def best_frame(ff, a, b):
    """The sharpest second of the moment that is neither dark nor blown out: its middle, in file seconds."""
    pic = ff.get('picture') or {}
    per = pic.get('per_second') or {}
    sharp = per.get('sharp') or []
    bad = set()
    for x0, x1, *_ in (pic.get('dark') or []) + (pic.get('bright') or []):
        bad.update(range(int(x0), int(x1) + 1))
    cand = [s for s, _ in _seconds(ff, a, b) if s < len(sharp) and s not in bad]
    if not cand:
        return _v(round((a + b) / 2, 2), 0.3, DETECTOR)
    s = max(cand, key=lambda k: sharp[k])
    return _v(round(min(b, max(a, s + 0.5)), 2), 0.6, DETECTOR)


def energy(ff, a, b, words, snd):
    rows = [row for _, row in _seconds(ff, a, b) if len(row) > 1]
    motion = sum(float(r[1]) for r in rows) / len(rows) if rows else 0.0
    wps = (sum(1 for w in words if a <= w['s'] < b) / max(0.5, b - a)) if words else 0.0
    loud = sum(1 for ev in (snd or {}).get('events') or [] if ev['value'] in ('bang', 'clank', 'repeated hits', 'thud'))
    if motion >= 0.25 or wps >= 3.2 or loud >= 3:
        word = 'lively'
    elif motion <= 0.04 and wps <= 2.0 and loud == 0:
        word = 'calm'
    else:
        word = 'steady'
    return _v(word, 0.55 if rows or words else 0.35, DETECTOR)


def b_roll(ff, a, b, snd, cam):
    speech = ((snd or {}).get('speech') or {}).get('value')
    pic = ff.get('picture') or {}
    dark = sum(_overlap(x0, x1, a, b) for x0, x1, *_ in pic.get('dark') or [])
    blurry = sum(_overlap(x0, x1, a, b) for x0, x1, *_ in pic.get('blurry') or [])
    usable = (b - a) >= 1.5 and dark + blurry < 0.5 * (b - a)
    fit = usable and speech != 'yes' and ff.get('kind') == 'video'
    return _v('yes' if fit else 'no', 0.6 if speech is not None else 0.45, DETECTOR)


def for_moment(ff, a, b, words=None):
    """The moment fields for [a, b] of a file (file_facts' ff); words: the file's words when it was transcribed."""
    out = {}
    if ff.get('kind') == 'video':
        cam = camera(ff, a, b)
        vehicle = moving_vehicle(ff, a, b, cam)
        if vehicle and (cam is None or cam['how'] != METADATA):
            cam = vehicle
        best = best_frame(ff, a, b)
        face = largest_face(ff['path'], best['value'])
        talking = bool(words) and any(a <= w['s'] < b for w in words)
        shot = {}
        fr = framing(ff, a, b, face, talking, cam)
        if fr:
            shot['framing'] = fr
        if cam:
            shot['camera'] = cam
        if shot:
            out['shot'] = shot
        out['best_frame_s'] = best
    snd = sound(ff, a, b, words)
    if snd:
        out['sound'] = snd
    subj = subjects(ff, a, b)
    if subj:
        out['subjects'] = subj
    st = setting(ff, a, b)
    if st:
        out['setting'] = st
    out['energy'] = energy(ff, a, b, words or [], snd)
    out['b_roll_fit'] = b_roll(ff, a, b, snd, out.get('shot', {}).get('camera'))
    return out


FIELDS = ('shot', 'sound', 'subjects', 'setting', 'energy', 'b_roll_fit', 'best_frame_s')
