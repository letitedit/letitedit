"""Dense videos: what the eye and ear follow, event by event, measured in code before any reviewer looks.

Events are the cuts on the main picture track, graphics, motion clips, text and cutaways arriving and leaving on the
tracks above it (caption arrivals and clip-effect targets are checked but excluded from density), and the
sound effects. Their number a second is the video's density; a dense video gets more of the review's attention on
motion and graphics (the frame-by-frame strips and the timing sheet below).

The checks, each measured, each with where its limit comes from:
- landing: an element whose words are said near its arrival arrives on the word: later than the word's start by more
  than two frames (word times are good to a frame or two), or earlier than it by more than 0.15 s, is off the word
  (letitedit-motion section 8; sound ahead of the picture is noticed at about 45 ms, behind it at about 125 ms,
  ITU-R BT.1359-1).
- reading time: words on screen for less than their reading time, words / 3.5 + 0.5 s and at least 1.5 s, 0.6 s for a
  single word or number (letitedit-graphics section 3, letitedit-motion section 2).
- at once: three or more elements arriving within a quarter second, or more than three on screen together
  (letitedit-motion section 4: one focal point at a time).
- stutter: on the export, a frame repeated in the middle of motion where the frames around it all change (a dropped or
  doubled frame), not the steady repeats of footage filmed at a lower frame rate.
- flashes: more than three flashes in any one second over a part of the picture (WCAG 2.3.1, general flash threshold:
  a pair of opposing changes of at least 10% relative luminance where the darker is below 0.80).
- sound on the hit: each effect sound's loudest 10 ms against its recorded target (including caption arrivals),
  else its own graphic or the nearest picture event within half a second. Offsets beyond 125 ms either way and
  sounds without a target are findings. Whooshes and risers use their peak, not their file start.

None of this judges how the motion or the sound feels: that is the reviewer's, and the person's ears.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

DENSE_PER_S = 0.75          # events a second from which a video counts as dense (a talking head cut every 4 s: 0.25;
                            # a retention Short, a cut every 1.5 s, a pop-up every 3 s with its sound: about 1.5)
LATE_FRAMES = 2             # an arrival this many frames after the word's start is still on it (recogniser precision)
EARLY_S = 0.15              # an arrival up to this much before the word is on it
NEAR_WORD_S = 1.0           # a word said within this of an arrival is the word it was placed on
READ_WPS, READ_PAD_S, READ_MIN_S, ONE_WORD_S = 3.5, 0.5, 1.5, 0.6
LABEL_CHARS, LABEL_S = 12, 1.0      # a two-word label: the top of the skill's 0.6-1.0 s for a word that is the point
ARRIVE_S = 0.25             # an animated arrival takes about this long before its words can be read
AT_ONCE, AT_ONCE_S, MOST_ON_SCREEN = 3, 0.25, 3
FLASH_SWING, FLASH_DARK, FLASHES_PER_S = 0.10, 0.80, 3
GRID = 3                    # flashes are counted per cell of a 3 x 3 grid (a cell is about 11% of the picture)
SMALL_W, SMALL_H = 48, 27
STILL_DIFF, MOVING_DIFF = 0.35, 2.0     # mean grey difference (0-255) of a repeated frame / of moving frames
STEADY_REPEATS = 0.15       # repeats in the half second around: above this share, the footage's own frame rate
STRIP_BEFORE, STRIP_AFTER = 4, 12       # frames around an arrival or exit in a strip
MAX_STRIPS, STRIPS_PER_PAGE, MAX_TEXT_FRAMES = 24, 6, 8
TEXT_KEYS = ('title', 'text', 'subtitle', 'kicker', 'name', 'role', 'label', 'line_one', 'line_two', 'line_three',
             'headline', 'caption', 'number', 'value')
STOP = {'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'with', 'is', 'it', 'you', 'your', 'my', 'our',
        'this', 'that', 'are', 'was', 'be', 'at', 'by', 'from', 'as', 'we', 'i'}


def fmt(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:05.2f}'


def _norm(word):
    return re.sub(r"[^\w']+", '', str(word).lower()).strip("'")


def _is_caption(item, track_name):
    g = item.get('graphic') or {}
    m = item.get('motion') or {}
    kit = (g.get('params') or {}).get('_look_kit') or {}
    return bool(re.search(r'caption|subtitle', track_name or '', re.I)
                or g.get('template') == 'word_captions' or m.get('block') == 'word_captions'
                or 'caption' in str(kit.get('family') or ''))


def _kind(item):
    for key in ('motion', 'graphic', 'code_scene', 'text', 'image'):
        if item.get(key):
            return key
    return 'cutaway' if item.get('clip') else None


def _words_of(item):
    """The words an element shows on screen, from its parameters."""
    out = []
    for key in ('graphic', 'motion'):
        params = (item.get(key) or {}).get('params') or {}
        for name in TEXT_KEYS:
            value = params.get(name)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    if isinstance(item.get('text'), str):
        out.append(item['text'])
    elif isinstance(item.get('text'), dict) and item['text'].get('text'):
        out.append(str(item['text']['text']))
    return ' '.join(out).replace('\n', ' ').strip()


def _is_sfx(item, track_name):
    return bool(item.get('clip')) and (item.get('sound_target') or str(item.get('id') or '').endswith('-sfx')
                                       or re.search(r'sfx|sound effect|effect sound|learned effects|\bfx\b', track_name or '', re.I))


def events(script):
    """[{t, kind, what, id, track, end?, text?, sound?}] in time order, and the overlay elements [(item, start, end,
    track name, kind)]."""
    from letitedit.timeline.edit_sync import layout
    from letitedit.looks import sound_targets
    fps = float((script.get('profile') or {}).get('fps') or 30)
    out, elements = [], []
    video = [t for t in script['tracks'] if t.get('kind', 'video') == 'video']
    main = video[0] if video else None
    if main is not None:
        for item, a, b in layout(main, fps):
            if a > 0.01 and (item.get('clip') or item.get('graphic') or item.get('code_scene')):
                out.append({'t': round(a, 3), 'kind': 'cut', 'what': 'cut', 'id': item.get('id'), 'track': main.get('name')})
    for track in video[1:]:
        if track.get('hide') in ('video', 'both'):
            continue
        name = track.get('name') or ''
        for item, a, b in layout(track, fps):
            kind = _kind(item)
            if not kind or _is_caption(item, name):
                continue
            text = _words_of(item)
            label = (item.get('motion') or {}).get('block') or (item.get('graphic') or {}).get('template') or ''
            elements.append((item, a, b, name, kind))
            out.append({'t': round(a, 3), 'kind': 'in', 'what': f'{kind} {label}'.strip(), 'id': item.get('id'),
                        'track': name, 'end': round(b, 3), **({'text': text} if text else {})})
            out.append({'t': round(b, 3), 'kind': 'out', 'what': f'{kind} {label}'.strip(), 'id': item.get('id'),
                        'track': name})
    for track in script['tracks']:
        if track.get('kind', 'video') != 'audio' or track.get('hide') in ('audio', 'both'):
            continue
        name = track.get('name') or ''
        for item, a, b in layout(track, fps):
            if _is_sfx(item, name):
                out.append({'t': round(a, 3), 'kind': 'sound', 'what': Path(str(item['clip'])).stem, 'id': item.get('id'),
                            'track': name, 'end': round(b, 3), 'sound': item})
    out.extend(sound_targets.caption_events(script))
    out.extend(sound_targets.effect_events(script))
    out.sort(key=lambda e: (e['t'], e['kind']))
    return out, elements


def density(evts, seconds):
    return round(sum(event['kind'] not in ('caption_word', 'effect') for event in evts) / seconds, 3) if seconds > 0 else 0.0


def _finding(at, check, problem, severity='minor'):
    return {'at': round(at, 2), 'check': check, 'problem': problem, 'severity': severity}


def landing(evts, words, fps):
    """(findings, rows): arrivals with words on screen against the same words said near them."""
    findings, rows = [], []
    late = LATE_FRAMES / fps
    spoken = [(w, _norm(w.get('w'))) for w in words or []]
    for e in evts:
        if e['kind'] != 'in' or not e.get('text'):
            continue
        shown = {_norm(w) for w in e['text'].split()} - STOP
        shown = {w for w in shown if len(w) >= 3 or w.isdigit()}
        near = [w for w, n in spoken if n in shown and abs(float(w['t0']) - e['t']) <= NEAR_WORD_S]
        if not near:
            continue
        word = min(near, key=lambda w: float(w['t0']))          # the element arrives when it is first named
        off = e['t'] - float(word['t0'])
        e['landing'] = {'word': word['w'], 'word_at': round(float(word['t0']), 3), 'off_s': round(off, 3)}
        rows.append(e)
        if off > late:
            findings.append(_finding(e['t'], 'landing', f'{e["what"]} "{e["text"][:40]}" arrives {off:.2f} s '
                                     f'({off * fps:.0f} frames) after "{word["w"]}" is said at {fmt(word["t0"])}: move it '
                                     f'onto the word or up to two frames before'))
        elif off < -EARLY_S:
            findings.append(_finding(e['t'], 'landing', f'{e["what"]} "{e["text"][:40]}" arrives {-off:.2f} s before '
                                     f'"{word["w"]}" is said at {fmt(word["t0"])}: it shows what is named before it is '
                                     'named; move it onto the word'))
    return findings, rows


def reading_time(evts):
    findings = []
    for e in evts:
        if e['kind'] != 'in' or not e.get('text') or e.get('end') is None:
            continue
        n = len(e['text'].split())
        single = n == 1 or re.fullmatch(r'[\d.,%$€£+-]+\w{0,2}', e['text'].strip() or 'x')
        label = n == 2 and len(e['text']) <= LABEL_CHARS          # "DAY 2", "2 TABS": read at a glance, like one word
        need = ONE_WORD_S if single else LABEL_S if label else max(READ_MIN_S, n / READ_WPS + READ_PAD_S)
        shown = e['end'] - e['t']
        readable = shown - (ARRIVE_S if not single else 0.0)
        e['reading'] = {'words': n, 'on_screen_s': round(shown, 2), 'needs_s': round(need, 2)}
        if readable < need:
            findings.append(_finding(e['t'], 'reading time', f'{e["what"]} "{e["text"][:40]}" ({n} words) is on screen '
                                     f'{shown:.2f} s; reading it needs about {need:.1f} s after it settles: hold it '
                                     'longer or cut words', 'major' if readable < need / 2 else 'minor'))
    return findings


def at_once(evts, elements):
    findings = []
    arrivals = [e for e in evts if e['kind'] == 'in']
    i = 0
    while i < len(arrivals):
        group = [e for e in arrivals[i:] if e['t'] - arrivals[i]['t'] <= AT_ONCE_S]
        if len(group) >= AT_ONCE:
            findings.append(_finding(arrivals[i]['t'], 'at once', f'{len(group)} elements arrive within '
                                     f'{AT_ONCE_S:g} s ({", ".join(e["what"] for e in group)}): one focal point at a '
                                     'time; stagger them in the order they should be read'))
            i += len(group)
        else:
            i += 1
    edges = sorted([(a, 1) for _, a, b, _, _ in elements] + [(b, -1) for _, a, b, _, _ in elements])
    count, since, worst = 0, None, None
    for t, step in edges:
        count += step
        if count > MOST_ON_SCREEN and since is None:
            since = t
        elif count <= MOST_ON_SCREEN and since is not None:
            if t - since >= 0.5 and worst is None:
                worst = (since, t)
            since = None
    if worst:
        findings.append(_finding(worst[0], 'at once', f'more than {MOST_ON_SCREEN} elements on screen together from '
                                 f'{fmt(worst[0])} to {fmt(worst[1])}: the eye has no one place to go'))
    return findings


def _decode(video, fps):
    """Every frame of the video, small and grey (frames, height, width), at its own frame rate."""
    import numpy as np
    import letitedit.review.final_check as final_check
    r = final_check._run([final_check._ffmpeg(), '-v', 'error', '-nostats', '-i', video, '-an', '-fps_mode', 'passthrough',
                          '-vf', f'scale={SMALL_W}:{SMALL_H},format=gray', '-f', 'rawvideo', '-'])
    data = np.frombuffer(r.stdout, np.uint8)
    n = len(data) // (SMALL_W * SMALL_H)
    if r.returncode != 0 or n < 2:
        raise RuntimeError(f'ffmpeg read {n} frames: ' + (r.stderr or b'').decode('utf-8', 'replace')[-300:])
    return data[:n * SMALL_W * SMALL_H].reshape(n, SMALL_H, SMALL_W)


def stutter(frames, fps, cuts=()):
    """Repeated frames in the middle of motion that the frames around them don't explain: [(time, frames)]."""
    import numpy as np
    if len(frames) < 5:
        return []
    f = frames.astype(np.int16)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))         # d[i]: frame i to frame i + 1
    repeat = d < STILL_DIFF
    half = max(2, round(fps / 2))
    near_cut = {round(c * fps) + k for c in cuts for k in range(-2, 3)}
    out = []
    for i in range(1, len(d) - 1):
        if not repeat[i] or d[i - 1] < MOVING_DIFF or d[i + 1] < MOVING_DIFF or i + 1 in near_cut:
            continue
        lo, hi = max(0, i - half), min(len(d), i + half + 1)
        if repeat[lo:hi].mean() > STEADY_REPEATS:            # the footage's own lower frame rate, steady
            continue
        out.append(round((i + 1) / fps, 3))
    return out


def flashes(frames, fps):
    """[(time, flashes in that second, cell)] where a cell of the picture flashes more than FLASHES_PER_S times."""
    import numpy as np
    if len(frames) < 3:
        return []
    h, w = frames.shape[1] // GRID, frames.shape[2] // GRID
    lum = (frames[:, :h * GRID, :w * GRID].astype(np.float32) / 255.0) ** 2.2
    cells = lum.reshape(len(frames), GRID, h, GRID, w).mean(axis=(2, 4))
    found = []
    for r in range(GRID):
        for c in range(GRID):
            series = cells[:, r, c]
            turns, ref, direction = [], series[0], 0         # opposing swings of FLASH_SWING or more (hysteresis)
            lo = hi = series[0]
            for i, v in enumerate(series):
                lo, hi = min(lo, v), max(hi, v)
                if direction >= 0 and hi - v >= FLASH_SWING and min(v, hi) < FLASH_DARK:
                    turns.append(i)
                    direction, lo, hi = -1, v, v
                elif direction <= 0 and v - lo >= FLASH_SWING and min(v, lo) < FLASH_DARK:
                    turns.append(i)
                    direction, lo, hi = 1, v, v
            j = 0
            for k, i in enumerate(turns):
                while turns[j] < i - fps:
                    j += 1
                count = (k - j + 1) / 2
                if count > FLASHES_PER_S:
                    found.append((round(turns[j] / fps, 2), count, (r, c)))
    found.sort()
    merged = []
    for t, count, cell in found:
        if merged and t - merged[-1][0] < 1.0:
            if count > merged[-1][1]:
                merged[-1] = (merged[-1][0], count, cell)
            continue
        merged.append((t, count, cell))
    return merged


FLASH_EFFECTS = re.compile(r'glitch|flash|strobe|invert|negative|flicker|shake|lightning', re.I)


def made_flash(script, evts, a, b):
    """What in the edit makes the picture flash in [a, b): an effect of that kind on a clip there, or two or more cuts,
    arrivals or exits in that second; '' when nothing of the edit's does (the footage itself)."""
    from letitedit.timeline.edit_sync import layout
    for track in script['tracks']:
        if track.get('kind', 'video') != 'video':
            continue
        for item, start, end in layout(track):
            if end <= a or start >= b:
                continue
            for effect in item.get('effects') or []:
                name = effect if isinstance(effect, str) else (effect.get('filter') or effect.get('vfx') or
                                                                next(iter(effect), '') if isinstance(effect, dict) else '')
                if FLASH_EFFECTS.search(str(name)) or FLASH_EFFECTS.search(str(item.get('id') or '')):
                    return f'the {name} effect on {item.get("id") or "a clip"}'
            if item.get('vfx') and FLASH_EFFECTS.search(json.dumps(item['vfx'])):
                return f'the effect {item.get("id")}'
    edges = [e for e in evts if e['kind'] in ('cut', 'in', 'out') and a <= e['t'] < b]
    return f'{len(edges)} picture changes in that second' if len(edges) >= 2 else ''


def sound_hits(evts, fps):
    """Findings and per-sound receipts, including missing targets and unreadable sounds."""
    from letitedit.looks import sound_targets
    findings = []
    for e in evts:
        if e['kind'] != 'sound':
            continue
        hit = e['hit'] = sound_targets.measure(e, evts, fps)
        if hit['status'] == 'off_target':
            off = hit['off_s']
            findings.append(_finding(hit['peak_at'], 'sound on the hit',
                f'the sound "{e["what"]}" ({e["id"]}) peaks {abs(off) * 1000:.0f} ms '
                f'{"before" if off < 0 else "after"} its target ({hit["picture"]} at '
                f'{fmt(hit["picture_at"])}); limit 125 ms either way'))
        elif hit['status'] != 'pass':
            findings.append(_finding(e['t'], 'sound on the hit',
                f'the sound "{e["what"]}" ({e["id"]}): {hit["reason"]}; what is the sound for?'))
    return findings


def strips(video, evts, fps, out_dir, portrait):
    """Pages of frame-by-frame strips from the video around arrivals and exits; [paths]."""
    from PIL import Image
    import letitedit.review.review_bundle as review_bundle
    import letitedit.review.final_check as final_check
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob('*.jpg')) + list(out_dir.glob('frames/*.jpg')):
        old.unlink()
    chosen = [e for e in evts if e['kind'] == 'in'][:MAX_STRIPS]
    chosen += [e for e in evts if e['kind'] == 'out'][:max(0, MAX_STRIPS - len(chosen))]
    chosen.sort(key=lambda e: e['t'])
    width = 90 if portrait else 120
    windows = []
    for e in chosen:
        first = max(0, round(e['t'] * fps) - STRIP_BEFORE)
        windows.append((e, list(range(first, first + STRIP_BEFORE + STRIP_AFTER))))
    wanted = sorted({f for _, frames in windows for f in frames})
    if not wanted:
        return []
    ranges, lo = [], wanted[0]                    # one pass over the video: every window's frames, each once
    for prev, cur in zip(wanted, wanted[1:] + [None]):
        if cur != prev + 1:
            ranges.append((lo, prev))
            lo = cur
    pick = '+'.join(f'between(n\\,{a}\\,{b})' for a, b in ranges)
    folder = out_dir / 'frames'
    folder.mkdir(exist_ok=True)
    final_check._run([final_check._ffmpeg(), '-v', 'error', '-y', '-i', video, '-an', '-fps_mode', 'passthrough', '-vf',
                      f'select={pick},scale={width}:-2', '-fps_mode', 'passthrough', '-q:v', '4',
                      str(folder / 'f_%05d.jpg')])
    files = sorted(folder.glob('f_*.jpg'))
    by_frame = dict(zip(wanted, files))
    made = []
    for e, frames in windows:
        shots = [Image.open(by_frame[f]).convert('RGB') for f in frames if f in by_frame]
        if not shots:
            continue
        strip_img = Image.new('RGB', (len(shots) * (shots[0].width + 2) + 2, shots[0].height + 28), (255, 255, 255))
        for i, shot in enumerate(shots):
            strip_img.paste(shot, (2 + i * (shot.width + 2), 26))
        label = f'{fmt(e["t"])} {e["what"]} {"arrives" if e["kind"] == "in" else "leaves"}' + (
            f' "{e["text"][:30]}"' if e.get('text') else '') + f' | frames {-STRIP_BEFORE}..+{STRIP_AFTER - 1}'
        made.append((strip_img, label))
    for f in files:
        f.unlink(missing_ok=True)
    pages = []
    for p in range(0, len(made), STRIPS_PER_PAGE):
        tiles = [review_bundle._label(img, label[:110], 15) for img, label in made[p:p + STRIPS_PER_PAGE]]
        page = Image.new('RGB', (max(t.width for t in tiles) + 8, sum(t.height + 6 for t in tiles) + 6), (255, 255, 255))
        y = 6
        for t in tiles:
            page.paste(t, (4, y))
            y += t.height + 6
        target = out_dir / f'motion-strips-{len(pages) + 1:02d}.jpg'
        page.save(target, quality=88)
        pages.append(str(target))
    return pages


def sheet(result, evts, path):
    lines = [f"# Motion and graphics timing\n",
             f"{result['events_per_s']} events a second ({len(evts)} in {result['seconds']:.1f} s: "
             + ', '.join(f'{v} {k}' for k, v in result['counts'].items()) + ')'
             + ('; a dense video' if result['dense'] else '') + '.',
             'Measured on the timeline (and the export for stutter and flashes). How the motion and the sound feel is '
             'not judged here.\n',
             '| time | event | what | on screen | words / landing |', '|---|---|---|---|---|']
    for e in evts[:200]:
        bits = []
        if e.get('text'):
            bits.append(f'"{e["text"][:40]}"')
        if e.get('reading'):
            bits.append(f"{e['reading']['words']} words, needs {e['reading']['needs_s']} s")
        if e.get('landing'):
            bits.append(f"said \"{e['landing']['word']}\" at {fmt(e['landing']['word_at'])}, off {e['landing']['off_s']:+.2f} s")
        if e.get('hit') and 'off_s' in e['hit']:
            bits.append(f"loudest {e['hit']['off_s'] * 1000:+.0f} ms from {e['hit']['picture']}")
        elif e.get('hit'):
            bits.append(e['hit']['status'] + ': ' + e['hit']['reason'])
        shown = f"{e['end'] - e['t']:.2f} s" if e.get('end') is not None and e['kind'] != 'out' else ''
        lines.append(f"| {fmt(e['t'])} | {e['kind']} | {e['what']} | {shown} | {'; '.join(bits)} |")
    if len(evts) > 200:
        lines.append(f'\n[{len(evts) - 200} more events not listed]')
    if result['findings']:
        lines += ['\n## Found', *[f"- {fmt(f['at'])} {f['check']} ({f['severity']}): {f['problem']}"
                                  for f in result['findings']]]
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


def analyse(project, video=None, out=None, words=None, pictures=None):
    """The events, density and checks of a project, with its export when given. pictures: True for strips (the
    default: when the video is dense and a video is given). Returns {events_per_s, dense, counts, seconds, findings,
    measured, not_measured, sheet, strips, text_moments}."""
    import letitedit.timeline.edit_script as es
    script = es.read(project)
    fps = float((script.get('profile') or {}).get('fps') or 30)
    evts, elements = events(script)
    from letitedit.timeline.edit_sync import layout
    seconds = max([b for t in script['tracks'] for _, _, b in layout(t)] or [0.0])
    if words is None:
        try:
            from letitedit.timeline.timeline_speech import timeline_words
            words = timeline_words(script, cached_only=True)
        except Exception:  # noqa: BLE001 - no words cached: landing is not measured, said so
            words = []
    counts = {'cuts': sum(e['kind'] == 'cut' for e in evts),
              'arrivals and exits': sum(e['kind'] in ('in', 'out') for e in evts),
              'sound effects': sum(e['kind'] == 'sound' for e in evts)}
    rate = density(evts, seconds)
    findings, measured, not_measured = [], [], []
    land, _ = landing(evts, words, fps)
    findings += land
    (measured if words else not_measured).append('landing on the word' + ('' if words else ' (no words cached)'))
    findings += reading_time(evts)
    findings += at_once(evts, elements)
    measured += ['reading time', 'elements at once']
    findings += sound_hits(evts, fps)
    measured.append('effect sound peaks against their recorded targets or legacy nearest picture/caption events')
    strip_pages = []
    if video and Path(video).is_file():
        try:
            frames = _decode(video, fps)
            cuts = [e['t'] for e in evts if e['kind'] in ('cut', 'in', 'out')]
            repeats = stutter(frames, fps, cuts)
            if repeats:
                findings.append(_finding(repeats[0], 'stutter', f'{len(repeats)} frame(s) repeat in the middle of motion '
                                         '(a dropped or doubled frame): at ' + ', '.join(fmt(t) for t in repeats[:6])))
            for t, count, cell in flashes(frames, fps):
                place = f'row {cell[0] + 1}, column {cell[1] + 1} of a 3 x 3 grid'
                made = made_flash(script, evts, t, t + 1.0)
                if made:
                    findings.append(_finding(t, 'flashes', f'{count:g} flashes within one second in part of the picture '
                                             f'({place}) from {made}: more than three a second can trigger seizures '
                                             '(WCAG 2.3.1); slow it or soften the change', 'major'))
                else:
                    findings.append(_finding(t, 'flashes', f'the footage itself flickers {count:g} times within one second '
                                             f'in part of the picture ({place}; something moving or blinking in the shot, '
                                             'not an effect of the edit): over the three a second of WCAG 2.3.1; a shorter or '
                                             'calmer shot avoids it if the video must meet it'))
            measured += ['stutter', 'flashes']
        except Exception as exc:  # noqa: BLE001 - the timeline checks stand
            not_measured.append(f'stutter and flashes ({type(exc).__name__})')
        dense_now = rate >= DENSE_PER_S
        if (pictures if pictures is not None else dense_now) and out:
            portrait = script['profile'].get('height', 0) > script['profile'].get('width', 0)
            strip_pages = strips(video, evts, fps, Path(out) / 'motion-strips', portrait)
    else:
        not_measured.append('stutter and flashes (no export given)')
    not_measured.append('how the motion and the sound feel (no code judges it)')
    text_moments = [(min(e['end'] - 0.05, e['t'] + max(0.5, ARRIVE_S + 0.2)), f'text: {e["text"][:30]}')
                    for e in evts if e['kind'] == 'in' and e.get('text') and e.get('end') is not None][:MAX_TEXT_FRAMES]
    findings.sort(key=lambda f: f['at'])
    result = {'events_per_s': rate, 'dense': rate >= DENSE_PER_S, 'counts': counts, 'seconds': round(seconds, 2),
              'findings': findings, 'measured': measured, 'not_measured': not_measured, 'strips': strip_pages,
              'text_moments': text_moments, 'sheet': None}
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        result['sheet'] = sheet(result, evts, Path(out) / 'motion-timing.md')
        (Path(out) / 'motion-timing.json').write_text(json.dumps(
            {**result, 'events': [{k: v for k, v in e.items() if k != 'sound'} for e in evts]}, indent=1, default=str),
            encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('project')
    ap.add_argument('--video')
    ap.add_argument('--out')
    a = ap.parse_args()
    r = analyse(a.project, a.video, a.out)
    print(json.dumps({k: r[k] for k in ('events_per_s', 'dense', 'counts', 'measured', 'not_measured', 'strips')}, indent=1))
    for f in r['findings']:
        print(fmt(f['at']), f['check'], f['severity'], f['problem'])
