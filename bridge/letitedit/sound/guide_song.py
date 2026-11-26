"""A song the video is cut to but that is never in the upload (T72): the person adds it in the phone app when posting.

The song sits on one audio track with a fixed name, TRACK_NAME, as one uncut clip from the start of the timeline (a phone
app can only start a song at one point and play it on, so a re-cut song could never be lined up again). The name is the
rule: every export leaves a track of that name out, muted or not (render_queue.submit through strip_file; the app's Export
dialog does the same with the name). The track is muted as well, so the window plays what the export will have.

    parts(song, length_s=None)            which stretches of a song could be used: starts on phrases and drops, and the song's
                                          very start, with tempo, how sure the beat finder is and energy
    place(project, song, start_s)         puts the song on the track (replacing an earlier one) and returns its beats
                                          in timeline time
    state(script) / find(script)          the track and what is wrong with it for a phone app
    check(project)                        cuts against the song's beats, words clipped by cuts
    song_in_sound(video, song, start_s)   measures whether the song is in a file's sound, with a positive control
    finish(project, upload, ...)          the measurement, the preview with the song, the facts for the posting note
    mix(upload, song, start_s, ...)       what the person's last step produces (offset_ms: lined up that far off)
    strip_file(source) / strip_tree(tree) the MLT without the song
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import numpy as np

TRACK_NAME = 'Song (not in the export)'
_NAME = re.compile(r'^\s*song \(not in the export\)', re.I)
PREVIEW_SUFFIX = " - PREVIEW with the song, don't upload"
UPLOAD_SUFFIX = ' - upload this (no song)'
RATE = 16000            # the measurement's sample rate: 8000 lost songs under a voice in short files (tests/t72/REPORT.md)
FOUND_SCORE = 1.5       # calibrated in tests/t72/REPORT.md: clean files stay under this
CONTROLS_DB = (0, -12, -18, -24)
MAX_SONG_S = 600
EVENT_REACH_S = 0.15   # a picture event further than this from a beat was put there on purpose: left alone
TAIL_PAD_S = 0.06       # a cut stays this far from a word's sound
_SMOOTH = np.ones(129) / 129
UNDER_VOICE_LU = 18.0   # the song this far under a talking video's own level (Add music's Medium: 18.4-18.8 LU)
OVER_SOUND_LU = 8.0     # with nobody talking: this far over the shots' own sound (Add music's Medium)

CRITIC_NOTE = ("This file has no song on purpose. The person adds the song in the phone app when posting, because a trending "
               "song's reach and licence come from the app's sound picker. So: don't report 'no music', a thin mix or a missing bed "
               "as faults; judge the voice and any natural sound as the viewer will hear them with a song on top. Cuts and moves on "
               "the song's beats are deliberate; song-added-when-posting.json has the measurements.")

# What each platform's own help pages said on 4 Nov 2026. The phone apps change; `source` says where to check.
PLATFORMS = {
    'tiktok': {'name': 'TikTok', 'how': 'Upload the file, tap Sound, add the song, then tap the sound clip to trim it and '
                                        'set its volume.',
               'start_control': 'a slider you drag; no typed time',
               'account': 'Business accounts see only the Commercial Music Library, so the song may not be there.',
               'source': 'https://support.tiktok.com/en/using-tiktok/creating-videos/sounds'},
    'reels': {'name': 'Instagram Reels', 'how': 'Upload the file, tap Audio, pick the song, slide the timeline at the bottom '
                                                'to the part you want, tap Done.',
              'start_control': 'a timeline you slide; no typed time',
              'account': "Some songs aren't available for every account type or country; Instagram then offers its Sound "
                         'Collection instead.',
              'source': 'https://about.instagram.com/blog/tips-and-tricks/how-to-add-music-to-instagram-reels'},
    'shorts': {'name': 'YouTube Shorts', 'how': 'Add the file in the Shorts camera, tap Sound and pick the song, use Adjust '
                                                'to choose the part, and Volume to balance it against your video.',
               'start_control': 'an Adjust tool; the page mentions no typed time',
               'account': "A song from outside YouTube's tools may get a Content ID claim, so add it there, not before.",
               'source': 'https://support.google.com/youtube/answer/12948448'},
}
_ALIASES = {'instagram': 'reels', 'instagram reels': 'reels', 'instagram_reels': 'reels', 'reel': 'reels', 'youtube': 'shorts',
            'youtube shorts': 'shorts', 'youtube_shorts': 'shorts', 'short': 'shorts', 'yt': 'shorts'}


def is_guide_name(name) -> bool:
    return bool(_NAME.match(str(name or '')))


def find(script):
    """The song's track in an edit script, or None."""
    return next((t for t in script.get('tracks') or [] if is_guide_name(t.get('name'))), None)


def _clock(t) -> str:
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:04.1f}'


def state(script) -> dict | None:
    """The song on the timeline: file, where it starts in the song, and what a phone app couldn't reproduce."""
    t = find(script)
    if not t:
        return None
    import letitedit.timeline.edit_sync as edit_sync
    clips = [(it, s, e) for it, s, e in edit_sync.layout(t) if it.get('clip')]
    problems = []
    if not clips:
        return {'track': t['name'], 'song': None, 'problems': ['the track has no song on it']}
    it, s, e = clips[0]
    if len(clips) > 1:
        problems.append(f'the song is in {len(clips)} pieces; a phone app plays it in one piece')
    if abs(s) > 1e-3:
        problems.append(f'the song starts {s:.2f} s into the video; a phone app starts it with the video')
    if abs(float(it.get('speed') or 1.0) - 1.0) > 1e-4 or it.get('reverse'):
        problems.append("the song's speed is changed; a phone app plays it at its own speed")
    return {'track': t['name'], 'song': it['clip'], 'start_s': float(it.get('in') or 0.0), 'id': it.get('id'),
            'length_s': round(e - s, 3), 'muted': t.get('hide') in ('audio', 'both'), 'problems': problems}


# ------------------------------------------------------------------------------------------------ keeping it out


def strip_tree(tree) -> dict | None:
    """Empty and mute the song's track in a parsed MLT (track order and indexes stay, so mixes still point right). The
    song's producers go too, unless something else uses them, so an export never opens the file. Returns what it did,
    or None when there is no such track."""
    root = tree.getroot()
    playlists = {p.get('id'): p for p in root.iter('playlist')}
    done = None
    for tr in root.iter('track'):
        pl = playlists.get(tr.get('producer'))
        if pl is None:
            continue
        name = next((x.text for x in pl.findall('property') if x.get('name') == 'shotcut:name'), None)
        if not is_guide_name(name):
            continue
        was_heard = tr.get('hide') not in ('audio', 'both')
        tr.set('hide', 'both')
        gone = set()
        for entry in list(pl):
            if entry.tag == 'entry':
                gone.add(entry.get('producer'))
            if entry.tag in ('entry', 'blank'):
                pl.remove(entry)
        done = {'track': name, 'was_heard': was_heard or bool(done and done['was_heard'])}
        used = {e.get('producer') for e in root.iter('entry')} | {e.get('producer') for e in root.iter('track')}
        for parent in root.iter():
            for child in list(parent):
                if child.tag in ('producer', 'chain') and child.get('id') in gone and child.get('id') not in used:
                    parent.remove(child)
    return done


def strip_file(source) -> tuple[Path, dict] | None:
    """A copy of a project without the song, beside the given folder's temp space, with its media paths still resolving;
    (path, what was done), or None when the project has no song track (the file is then left alone)."""
    source = Path(source)
    tree = ET.parse(source)
    done = strip_tree(tree)
    if not done:
        return None
    root = tree.getroot()
    if not root.get('root'):
        root.set('root', str(source.resolve().parent))
    out = Path(tempfile.gettempdir()) / f'letitedit-no-song-{uuid.uuid4().hex[:10]}.mlt'
    tree.write(out, encoding='utf-8', xml_declaration=True)
    return out, done


# ------------------------------------------------------------------------------------------------ choosing a part


def _grid(song, refresh=False) -> dict:
    import letitedit.timing.music_sync as music_sync
    return music_sync.song_grid(str(song), refresh=refresh)


def _sure(grid) -> dict:
    """How far the beats can be trusted, in plain words."""
    quality, conf = grid.get('beat_quality'), grid.get('beat_confidence')
    out = {'beat_finder': grid.get('tracker'), 'bpm': grid.get('bpm'), 'beat_quality': quality, 'beat_confidence': conf,
           'beats_per_bar': grid.get('beats_per_bar')}
    if grid.get('beat_finder_error'):
        out['note'] = f"The beat finder couldn't run on this song, so there are no beats to cut to: {grid['beat_finder_error']}"
    elif not grid.get('beats'):
        out['note'] = "No steady beat found in this song, so nothing can land on its beats."
    elif quality in ('weak', 'none'):
        out['note'] = f"The beat finder is unsure of this song's beats (quality {quality}): cuts placed on them may look off."
    return out


def parts(song, length_s=None, limit=8, refresh=False) -> dict:
    """Stretches of a song that start on something strong. energy: dB against the song's loudest section."""
    import letitedit.sound.audio_library as audio_library
    song = audio_library.song_file(song)
    if not Path(song).is_file():
        raise FileNotFoundError(f'No such song file: {song}')
    g = _grid(song, refresh)
    bars = [b[0] for b in g.get('bars') or []]
    energy = g.get('energy_by_bar') or []
    loud = g.get('loud_db_by_bar') or []
    beats = np.asarray(g.get('beats') or [], float)
    dur = float(g.get('duration') or 0.0)

    def section_at(t):
        return next((s for s in g.get('sections') or [] if s[0] <= t < s[1]), None)

    starts = {}
    for t in [bars[j] for j in g.get('phrases') or [] if j < len(bars)]:
        starts.setdefault(round(float(t), 3), set()).add('phrase')
    for d in g.get('drops') or []:
        starts.setdefault(round(float(d['t']), 3), set()).add('drop')
    for s in g.get('sections') or []:
        t = float(s[0])
        if len(beats):                 # a section's start, moved to the next beat
            later = beats[beats >= t - 0.05]
            t = float(later[0]) if len(later) else t
        starts.setdefault(round(t, 3), set()).add('section')
    rows = []
    for t, why in starts.items():
        end = t + float(length_s) if length_s else None
        if end and end > dur + 0.5:
            continue
        idx = [j for j, b in enumerate(bars) if t - 0.01 <= b and (end is None or b < end)]
        mean_e = float(np.mean([energy[j] for j in idx if j < len(energy)])) if idx and energy else None
        sec = section_at(t)
        n = int(((beats >= t - 0.01) & (beats < (end or dur))).sum()) if len(beats) else 0
        first = next((j for j, b in enumerate(bars) if b >= t - 0.01), None)
        entrance = round(loud[first] - loud[first - 1], 1) if first and first < len(loud) else None
        rows.append({'start_s': t, 'at': _clock(t), 'why': sorted(why), 'entrance_db': entrance, 'section': sec[2] if sec else None,
                     'section_energy_db': sec[3] if sec else None, 'mean_bar_energy': round(mean_e, 3) if mean_e is not None
                     else None, 'beats_in_it': n})
    rows.sort(key=lambda r: (-('drop' in r['why']), -(r['mean_bar_energy'] or 0.0), r['start_s']))
    first = float(beats[0]) if len(beats) else None
    return {'song': str(song), 'duration_s': dur, **_sure(g), 'first_beat_s': first, 'parts': rows[:int(limit)],
            'from_the_very_start': {'start_s': 0.0, 'first_beat_s': first,
                                    'fact': 'The help pages describe a control you drag, with no typed time, so dragging it all the way back should '
                                            'reach this start exactly and any other start is by eye. Not tried on a phone.'},
            'warnings': list(g.get('warnings') or [])}


def _timeline_beats(g, start_s, length_s, limit=400) -> dict:
    """The song's beats in timeline time for a song started at start_s."""
    beats, pos = g.get('beats') or [], g.get('pos') or []
    all_b = [round(b - start_s, 3) for b in beats if start_s - 1e-3 <= b < start_s + length_s]
    down = [round(b - start_s, 3) for b, p in zip(beats, pos) if p == 0 and start_s - 1e-3 <= b < start_s + length_s]
    return {'beats': all_b[:limit], 'downbeats': down[:limit], 'beats_total': len(all_b)}


def place(project, song, start_s=0.0, length_s=None) -> dict:
    """Put the song on its track as one uncut clip from the timeline's start, muted. A second call replaces the first."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.edit_sync as edit_sync
    import letitedit.server.timeline_tools as timeline_tools
    import letitedit.sound.audio_library as audio_library
    song = audio_library.song_file(song)
    if not Path(song).is_file():
        raise FileNotFoundError(f'No such song file: {song}')
    path = es._resolve(project)
    live = timeline_tools._live_state(path)
    script = es.read(path)
    g = _grid(song)
    dur = float(g.get('duration') or 0.0)
    start_s = float(start_s or 0.0)
    if start_s < 0 or (dur and start_s >= dur):
        raise ValueError(f'start_s {start_s} is outside the song ({dur:.1f} s long)')
    main = edit_sync.main_track(script)
    picture = max((e for _, _, e in edit_sync.layout(main)), default=0.0) if main else 0.0
    length = float(length_s) if length_s else picture
    if length <= 0:
        length = min(60.0, dur - start_s)     # nothing cut yet: a montage is cut to the song
    warnings = []
    end = start_s + length
    if dur and end > dur:
        warnings.append(f'The song ends {end - dur:.1f} s before the video does, from this start.')
        end = dur
    old = find(script)
    ops = []
    if old:
        ops += [{'op': 'delete', 'id': it['id']} for it in old['items'] if it.get('id') and it.get('clip')]
    else:
        ops += [{'op': 'add_track', 'name': TRACK_NAME, 'kind': 'audio'}]
        if not live:
            ops += [{'op': 'track', 'name': TRACK_NAME, 'hide': 'both'}]
    ops += [{'op': 'insert', 'track': old['name'] if old else TRACK_NAME, 'at': 0,
             'item': {'clip': str(song), 'in': round(start_s, 3), 'out': round(end, 3)}}]
    result, _ = timeline_tools.apply_project(str(path), changes=ops, check=False, label='Song to cut to (not in the export)')
    if live and not old:        # a new track in an open window comes in sounding: mute it there
        _mute_live(live['instance_id'])
    after = state(es.read(path)) or {}
    out = {'track': TRACK_NAME, 'song': str(song), 'start_s': start_s, 'at': _clock(start_s), 'length_s': round(end - start_s, 3),
           **_sure(g), **_timeline_beats(g, start_s, end - start_s), 'problems': after.get('problems') or [],
           'changes': result.get('changes'), 'warnings': warnings + list(g.get('warnings') or [])}
    return out


def _mute_live(instance_id) -> None:
    import letitedit.app.live_edit as live_edit
    with live_edit._bridge(instance_id) as b:
        for row in ((b.call('state') or {}).get('timeline') or {}).get('tracks') or []:
            if is_guide_name(row.get('name')):
                if not row.get('mute'):
                    b.call('set_track', {'track': row.get('index'), 'mute': True})
                return


# ------------------------------------------------------------------------------------------------ measuring


def _ffmpeg() -> str:
    import letitedit.sound.music as music
    return str(music.FFMPEG)


def _decode(path, start_s=0.0, seconds=None) -> np.ndarray:
    args = [_ffmpeg(), '-v', 'error', '-nostdin']
    if start_s:
        args += ['-ss', f'{float(start_s):.3f}']
    if seconds:
        args += ['-t', f'{float(seconds):.3f}']
    args += ['-i', str(path), '-vn', '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-']
    run = subprocess.run(args, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise RuntimeError(f"Could not read the sound of {path}: {run.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(run.stdout, dtype=np.float32).astype(np.float64)


class _Matcher:
    """How strongly a sound matches somewhere in a song, against a fair baseline. A smoothed-whitened cross-correlation lets every
    frequency count by whether its phase lines up, not by how loud it is, so a voice on top hardly hides a song. How high a peak
    chance reaches depends on the song and the file, so the baseline is the same file played backwards, which has the same
    sound but can't match: a score is the peak over that baseline, about 1 for a file without the song."""

    def __init__(self, song, length):
        self.n = 1 << int(np.ceil(np.log2(len(song) + length)))
        self.song = np.fft.rfft(song - song.mean(), self.n)
        self.song_power = np.convolve(np.abs(self.song) ** 2, _SMOOTH, 'same')

    def _peak(self, x) -> tuple[float, int]:
        a = np.fft.rfft(x - x.mean(), self.n)
        weight = np.sqrt(np.convolve(np.abs(a) ** 2, _SMOOTH, 'same') * self.song_power) + 1e-9
        r = np.abs(np.fft.irfft(self.song * np.conj(a) / weight, self.n))
        centre = float(np.median(r))
        spread = 1.4826 * float(np.median(np.abs(r - centre))) or 1e-12
        k = int(np.argmax(r))
        return (float(r[k]) - centre) / spread, (k if k < self.n // 2 else k - self.n)

    def baseline(self, sound) -> float:
        back = sound[::-1]
        return max(self._peak(back)[0], self._peak(np.roll(back, len(back) // 3))[0])

    def score(self, sound, baseline) -> tuple[float, int]:
        z, lag = self._peak(sound)
        return z / (baseline or 1e-9), lag


def song_in_sound(video, song, start_s=None) -> dict:
    """Is any of this song in this file's sound? Searches the whole song, not only where it was meant to start, then repeats the
    search with the song mixed in on purpose, as controls: catches_down_to_db is the quietest control found, and `proven` says one
    as loud as the file itself was found (an unmuted song would be at least that). A file with no sound holds no song."""
    try:
        sound = _decode(video)
    except RuntimeError as exc:
        if 'does not contain any stream' not in str(exc):
            raise
        sound = np.zeros(0)
    track = _decode(song)
    method = (f'{RATE} Hz mono, smoothed-whitened cross-correlation against the whole song; score = the peak over the same file '
              f'played backwards; found at {FOUND_SCORE} or more; controls mix the song in at {CONTROLS_DB} dB against the file')
    if not len(track):
        return {'song_found': None, 'proven': False, 'note': 'the song has no sound to compare', 'method': method}
    if not len(sound) or float(np.sqrt(np.mean(sound ** 2))) < 1e-4:
        return {'song_found': False, 'proven': True, 'note': 'this file has no sound', 'method': method}
    if len(track) > MAX_SONG_S * RATE:        # a very long file: half the rate keeps this to seconds, and costs some reach
        sound, track = sound[::2], track[::2]
        rate = RATE // 2
    else:
        rate = RATE
    m = _Matcher(track, len(sound))
    base = m.baseline(sound)
    score, lag = m.score(sound, base)
    found = score >= FOUND_SCORE
    frm = int(max(0.0, float(start_s or 0.0)) * rate)
    part = track[frm:frm + len(sound)]
    rms = float(np.sqrt(np.mean(sound ** 2))) or 1e-4
    part_rms = float(np.sqrt(np.mean(part ** 2))) or 1e-4
    controls = {}
    for db in CONTROLS_DB:
        mixed = sound.copy()
        mixed[:len(part)] += part * (rms / part_rms) * 10 ** (db / 20)
        controls[db] = round(m.score(mixed, base)[0], 2)
    caught = [db for db, v in controls.items() if v >= FOUND_SCORE]
    return {'song_found': found, 'score': round(score, 2), 'found_at': FOUND_SCORE, 'at_song_s': round(lag / rate, 3) if found else None,
            'controls': {f'{k} dB': v for k, v in controls.items()}, 'catches_down_to_db': min(caught) if caught else None,
            'proven': 0 in caught, 'method': method}


def _picture_events(script, fps) -> list:
    """Starts of what lies over the main picture: pop-ups, text, graphics, b-roll, scenes (visible video tracks other than the main one; not captions)."""
    import letitedit.timeline.edit_sync as edit_sync
    main = edit_sync.main_track(script)
    out = set()
    for t in script.get('tracks') or []:
        if t is main or t.get('kind') == 'audio' or t.get('hide') in ('video', 'both') or re.search(r'caption', str(t.get('name')), re.I):
            continue
        out |= {round(s * fps) / fps for it, s, _ in edit_sync.layout(t) if ('gap' not in it)}
    for it, s, _ in (edit_sync.layout(main) if main else []):      # a punch-in or a shake: a keyed effect on the clip, where its first key says
        for e in it.get('effects') or []:
            for v in (e.values() if isinstance(e, dict) else []):
                keys = v.get('keys') if isinstance(v, dict) else None
                if keys and float(keys[0][0]) > 0.02:
                    out.add(round((s + float(keys[0][0])) * fps) / fps)
    return sorted(out)


def _cuts(script, fps) -> list:
    """Picture cuts of the main track, in seconds on the frame grid."""
    import letitedit.timeline.edit_sync as edit_sync
    main = edit_sync.main_track(script)
    if not main:
        return []
    return sorted({round(s * fps) / fps for _, s, _ in edit_sync.layout(main) if s > 1e-3})


def offsets(cuts, beats, fps) -> dict:
    """Cuts against beats, in frames; chance: the share of evenly spread times that would land within a frame anyway."""
    cuts, beats = np.asarray(cuts, float), np.asarray(beats, float)
    if not len(cuts) or not len(beats):
        return {'cuts': int(len(cuts)), 'within_one_frame': None, 'note': 'no cuts or no beats to compare'}
    nearest = np.abs(cuts[:, None] - beats[None, :]).min(axis=1)
    gap = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.0
    return {'cuts': int(len(cuts)), 'within_one_frame': int((nearest <= 1.0 / fps + 1e-6).sum()),
            'share_within_one_frame': round(float((nearest <= 1.0 / fps + 1e-6).mean()), 3),
            'chance_share': round(min(1.0, 2.0 / fps / gap), 3) if gap else None,
            'median_off_frames': round(float(np.median(nearest)) * fps, 2)}


def check(project) -> dict:
    """Cuts against the song's beats and words clipped by the cuts. The song's level isn't a fault here: it isn't in the file."""
    import letitedit.review.checks as checks
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.timeline_model as tm
    path = es._resolve(project)
    script = es.read(path)
    st = state(script)
    if not st or not st.get('song'):
        return {'song': None, 'note': f'No {TRACK_NAME!r} track with a song on it.'}
    fps = float(tm.load(path).fps)
    g = _grid(st['song'])
    tb = _timeline_beats(g, st['start_s'], st['length_s'], limit=100000)
    out = {**st, **_sure(g), 'cuts_on_beats': offsets(_cuts(script, fps), tb['beats'], fps),
           'picture_events_on_beats': offsets(_picture_events(script, fps), tb['beats'], fps)}
    try:
        clipped = checks.cut_words(str(path))
        out['words_clipped'] = {'count': len(clipped), 'where': [str(c)[:160] for c in clipped[:8]]}
    except Exception as exc:  # noqa: BLE001 - the beats still count without this
        out['words_clipped'] = {'count': None, 'note': f'{type(exc).__name__}: {exc}'[:200]}
    return out


def review_facts(project, video) -> dict | None:
    """For letitedit_review_bundle: the song against this file and the cuts against its beats; None without a song."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.timeline_model as tm
    path = es._resolve(project)
    script = es.read(path)
    st = state(script)
    if not st or not st.get('song'):
        return None
    fps = float(tm.load(path).fps)
    g = _grid(st['song'])
    beats = _timeline_beats(g, st['start_s'], st['length_s'], limit=100000)['beats']
    return {**st, **_sure(g), 'song_in_file': song_in_sound(video, st['song'], st['start_s']),
            'cuts_on_beats': offsets(_cuts(script, fps), beats, fps)}


def land(project, max_move_s=None) -> dict:
    """Moves each cut of the main picture track to a beat by lengthening or shortening the outgoing clip's tail, one undo step. A tail
    only moves inside the pause after its last word: a cut that can't reach a beat without touching a word stays where it is, with the
    reason. Each move shifts everything after it, so the cuts are worked through in order. max_move_s [half a beat]."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.edit_sync as edit_sync
    import letitedit.footage.speech as speech
    import letitedit.timeline.timeline_model as tm
    import letitedit.server.timeline_tools as timeline_tools
    path = es._resolve(project)
    script = es.read(path)
    st = state(script)
    if not st or not st.get('song'):
        raise ValueError(f'This project has no {TRACK_NAME!r} track with a song on it.')
    fps = float(tm.load(path).fps)
    g = _grid(st['song'])
    beats = np.asarray([b - st['start_s'] for b in g.get('beats') or [] if b >= st['start_s'] - 1e-3], float)
    if not len(beats):
        return {**_sure(g), 'moved': [], 'stayed': [], 'note': 'No beats to land on.'}
    gap = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
    reach = float(max_move_s) if max_move_s is not None else gap / 2 + 1.0 / fps
    main = edit_sync.main_track(script)
    clips = [(it, s, e) for it, s, e in edit_sync.layout(main) if it.get('clip')]
    ops, moved, stayed, shift = [], [], [], 0.0
    for it, s, e in clips[:-1]:
        cut = e + shift
        if float(it.get('speed') or 1.0) != 1.0 or it.get('reverse') or 'in' not in it or 'out' not in it:
            stayed.append({'id': it.get('id'), 'at': round(cut, 3), 'why': 'a changed speed or no source range'})
            continue
        out = float(it['out'])
        try:
            ws = speech.sound_words(it['clip'], float(it['in']) - 1, out + 2 + reach, cached=True) or []
        except Exception:  # noqa: BLE001 - no words known: nothing to protect
            ws = []
        ws = [w for w in ws if w.get('e') is not None and w.get('s') is not None]
        low = max([float(w['e']) + TAIL_PAD_S for w in ws if float(w['s']) < out], default=float(it['in']) + 0.1)
        high = min([float(w['s']) - TAIL_PAD_S for w in ws if float(w['s']) >= out], default=out + reach)
        try:
            high = min(high, float(es.probe(it['clip']).get('duration') or high))
        except Exception:  # noqa: BLE001 - length unknown: the edit's own check still refuses a clip past its end
            pass
        wanted = sorted(beats[np.abs(beats - cut) <= reach], key=lambda b: abs(b - cut))
        done = False
        for b in wanted:
            dt = round(float(b) * fps) / fps - cut
            if low <= out + dt <= high:
                if abs(dt) > 0.5 / fps:
                    ops.append({'op': 'trim', 'id': it['id'], 'out': round(out + dt, 4), 'edge_mode': 'exact'})
                    moved.append({'id': it.get('id'), 'from': round(cut, 3), 'to': round(cut + dt, 3), 'moved_ms': round(dt * 1000)})
                    shift += dt
                done = True
                break
        if not done:
            stayed.append({'id': it.get('id'), 'at': round(cut, 3),
                           'why': 'no beat within reach without touching a word' if wanted else 'no beat within reach'})
    if ops:
        timeline_tools.apply_project(str(path), changes=ops, check=False, label='Cuts moved to the song\'s beats')
        place(path, st['song'], st['start_s'])      # the picture's length changed
    # a moved cut carries what follows it along, so those events may need as far back as the cuts went
    far = max([abs(m['moved_ms']) / 1000 for m in moved], default=0.0)
    events = _land_events(path, beats, fps, max(min(reach, EVENT_REACH_S), min(reach, far + 1.0 / fps)))
    after = check(path)
    return {**_sure(g), 'moved': moved, 'stayed': stayed, 'events_moved': events, 'cuts_on_beats': after.get('cuts_on_beats'),
            'picture_events_on_beats': after.get('picture_events_on_beats'), 'words_clipped': after.get('words_clipped')}


def _land_events(path, beats, fps, reach) -> list:
    """Punch-ins and other keyed effects on main-track clips, and what lies over the main picture, moved to the nearest beat when one is within reach:
    an edit made after they were placed shifts them off it. A move stays inside its clip, and its keys keep their spacing."""
    import letitedit.timeline.edit_script as es
    import letitedit.timeline.edit_sync as edit_sync
    import letitedit.server.timeline_tools as timeline_tools
    script = es.read(path)
    main = edit_sync.main_track(script)
    moved, ops = [], []

    def nearest(t):
        b = round(float(beats[np.abs(beats - t).argmin()]) * fps) / fps
        return b if 0.5 / fps < abs(b - t) <= reach else None
    for it, s, e in edit_sync.layout(main) if main else []:
        changed, effects = False, []
        for fx in it.get('effects') or []:
            new = fx
            for name, v in (fx.items() if isinstance(fx, dict) else []):
                keys = v.get('keys') if isinstance(v, dict) else None
                if not keys or float(keys[0][0]) <= 0.02:
                    continue
                t = s + float(keys[0][0])
                b = nearest(t)
                if b is None or b - s <= 0.02 or b + (float(keys[-1][0]) - float(keys[0][0])) >= e:
                    continue
                d = b - t
                new = {**fx, name: {**v, 'keys': [[round(float(k[0]) + d, 3), *k[1:]] for k in keys]}}
                moved.append({'id': it.get('id'), 'kind': name, 'from': round(t, 3), 'to': round(b, 3)})
                changed = True
            effects.append(new)
        if changed:
            ops.append({'op': 'set', 'id': it['id'], 'effects': effects})
    for t in script.get('tracks') or []:
        if t is main or t.get('kind') == 'audio' or t.get('hide') in ('video', 'both') or re.search(r'caption', str(t.get('name')), re.I):
            continue
        for it, s, _ in edit_sync.layout(t):
            b = nearest(s) if it.get('id') and 'gap' not in it else None
            if b is not None:
                ops.append({'op': 'move', 'id': it['id'], 'track': t['name'], 'at': round(b, 3)})
                moved.append({'id': it.get('id'), 'kind': 'overlay', 'from': round(s, 3), 'to': round(b, 3)})
    if ops:
        timeline_tools.apply_project(str(path), changes=ops, check=False, label='Picture events moved to the song\'s beats')
    return moved


# ------------------------------------------------------------------------------------------------ the two files


def _lufs(path, start=0.0, end=None) -> float:
    import letitedit.sound.music as music
    return float(music.loudness(str(path), start, end))


def _duration(path) -> float:
    run = subprocess.run([str(Path(_ffmpeg()).with_name('ffprobe.exe')), '-v', 'error', '-show_entries', 'format=duration', '-of',
                          'csv=p=0', str(path)], capture_output=True, text=True,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return float(run.stdout.strip() or 0.0)


def mix(upload, song, start_s, out, gain_db=0.0, offset_ms=0.0, overwrite=True) -> Path:
    """What the person's last step produces: the upload's picture untouched, the song from start_s at gain_db on top of its
    sound. offset_ms > 0: the person started the song that much later in the song than planned. The song is stream-mixed
    with no video encode, so this is seconds of work, not a render."""
    start = float(start_s) + float(offset_ms) / 1000.0
    pad = ''
    if start < 0:                     # the planned start is the song's very start: an early offset means silence first
        pad = f',adelay={int(round(-start * 1000))}:all=1'
        start = 0.0
    graph = (f'[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={float(gain_db):.3f}dB{pad}[s];'
             '[0:a]aformat=sample_rates=48000:channel_layouts=stereo[v];'
             '[v][s]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false[a]')
    args = [_ffmpeg(), '-v', 'error', '-nostdin', '-y' if overwrite else '-n', '-i', str(upload), '-ss', f'{start:.3f}', '-i',
            str(song), '-filter_complex', graph, '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k',
            '-movflags', '+faststart', str(out)]
    run = subprocess.run(args, capture_output=True, text=True, errors='replace',
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise RuntimeError(f'Could not mix the song in: {run.stderr[:400]}')
    return Path(out)


def _talks(script) -> bool:
    import letitedit.timeline.timeline_speech as timeline_speech
    try:
        return bool(timeline_speech.timeline_words(script, cached_only=True))
    except Exception:  # noqa: BLE001 - no transcript yet reads as nobody talking only if there are none at all
        return False


def _platform_ids(platforms) -> list:
    ids = []
    for p in ([platforms] if isinstance(platforms, str) else platforms or []):
        k = str(p).strip().casefold()
        k = _ALIASES.get(k, k)
        if k in PLATFORMS and k not in ids:
            ids.append(k)
    return ids or list(PLATFORMS)


def finish(project, upload, platforms=None, song_level_lu=None, preview=True, out=None) -> dict:
    """The upload measured against the song, the preview beside it, and the facts of the posting note. song_level_lu: the
    song's loudness against the file's own, in LU [talking: -18; nobody talking: +8]."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    script = es.read(path)
    st = state(script)
    if not st or not st.get('song'):
        raise ValueError(f'This project has no {TRACK_NAME!r} track with a song on it.')
    upload = Path(upload)
    if not upload.is_file():
        raise FileNotFoundError(f'No such file: {upload}')
    song, start = st['song'], st['start_s']
    measured = song_in_sound(upload, song, start)
    result = {'upload': str(upload), 'song': song, 'start_s': start, 'at': _clock(start), 'song_in_upload': measured,
              'problems': st.get('problems') or []}
    if measured.get('song_found'):
        result['preview'] = None
        result['problem'] = 'The song IS in this file: it must not be uploaded as it is. Export it again with letitedit_export.'
        return result
    length = _duration(upload) or st['length_s']
    own = _lufs(upload)
    full = _lufs(song, start, start + length)
    talks = _talks(script)
    level = float(song_level_lu) if song_level_lu is not None else (-UNDER_VOICE_LU if talks else OVER_SOUND_LU)
    gain = level + own - full
    g = _grid(song)
    first = next((b - start for b in g.get('beats') or [] if b >= start - 1e-3), None)
    import letitedit.timeline.timeline_model as tm
    fps = float(tm.load(path).fps)
    cuts = _cuts(script, fps)
    tb = _timeline_beats(g, start, length, limit=100000)
    near = lambda c, xs: bool(xs) and min(abs(c - x) for x in xs) <= 1.0 / fps + 1e-6     # noqa: E731
    # a moment to check by eye must really be on a beat: a downbeat if one has a cut on it, and none rather than a wrong one
    moments = sorted(set(cuts) | set(_picture_events(script, fps)))
    landmark = next((c for c in moments if near(c, tb['downbeats'])), next((c for c in moments if near(c, tb['beats'])), None))
    if preview:
        target = Path(out) if out else upload.with_name(re.sub(re.escape(UPLOAD_SUFFIX) + '$', '', upload.stem) + PREVIEW_SUFFIX + '.mp4')
        mix(upload, song, start, target, gain_db=gain)
        result['preview'] = str(target)
    beat_gap = float(np.median(np.diff(g['beats']))) if len(g.get('beats') or []) > 1 else None
    result.update({
        **_sure(g), 'talks': talks, 'song_level_lu': round(level, 1), 'song_gain_db': round(gain, 1),
        'volume_percent_if_linear': int(round(min(100.0, 100 * 10 ** (min(gain, 0.0) / 20)))),
        'volume_note': "No platform says how its volume control maps to loudness, so the percent is a starting point: judge by ear "
                       'against the preview.',
        'first_beat_in_video_s': round(first, 3) if first is not None else None,
        'cuts_on_beats': offsets(cuts, tb['beats'], fps),
        'picture_events_on_beats': offsets(_picture_events(script, fps), tb['beats'], fps),
        'start_is_the_songs_very_start': start < 0.05,
        'check_at_s': round(landmark, 2) if landmark is not None else None,
        'check_at': _clock(landmark) if landmark is not None else None,
        'beat_gap_ms': round(beat_gap * 1000) if beat_gap else None,
        'worst_case_off_ms': round(beat_gap * 500) if beat_gap else None,
        'worst_case_note': 'Beats repeat, so a song started a whole number of beats off still lands on beats; the furthest a '
                           'start can be from a beat is half a beat. A quarter-second was plainly visible on a montage to the one viewer who has judged it.' if beat_gap else None,
        'platforms': [dict(PLATFORMS[p], id=p) for p in _platform_ids(platforms)]})
    return result
