# Numbers for letitedit-motion

Starting points to check on frames, not limits. Tags are those of `sources.md`. Nearly all are [PRACT] (practitioner habit)
or [OURS]; where a number is measured research or a standard it says so. Change one when the frames say it is wrong.

## Frames and seconds

| fps | 1 frame | 3 frames | 6 frames | 12 frames |
|---|---|---|---|---|
| 24 | 42 ms | 0.125 s | 0.25 s | 0.5 s |
| 30 | 33 ms | 0.10 s | 0.20 s | 0.40 s |
| 60 | 17 ms | 0.05 s | 0.10 s | 0.20 s |

The tools give `c.fps` to a scene; write times in seconds and convert frame counts with it.

## Arrive, hold, leave [PRACT unless noted]

| Thing | Arrives | Leaves |
|---|---|---|
| Small mark (tick, X stroke, dot, pop) | 0.10-0.20 s | 0.08-0.15 s |
| Label, card, text line, icon | 0.25-0.50 s | 0.15-0.35 s |
| Hero object, big shape | 0.6-1.0 s | 0.35-0.6 s |
| Whole-scene change, camera push | 1.0-2.5 s | same move continuing |
| Wipe or flash transition | 0.15-0.25 s in, 0.15-0.25 s out | |

Exit = about 65-75% of entrance. Longer for further travel (half the screen takes about 1.5x a short hop).
Hold for reading: letitedit-graphics section 3 (words / 3.5 + 0.5 s, at least 1.5 s), counted from the settle. A single
word or number that is the point: 0.6-1.0 s. Silent reading is about 238 words a minute for non-fiction, aloud 183 [STUDY].
Subtitle standards put a floor under any text event: Netflix asks for at least 5/6 s (20 frames at 24 fps) [STD].

## Overshoot by weight [PRACT] and the tool that makes it

| Feels like | Overshoot | Call |
|---|---|---|
| Rigid, glass, precise, premium calm | 0 | `M.springEase(0)` or `quartOut` / `quintOut` |
| Paper, card | 0.03 | `M.springEase(0.03)` or `M.ease.backOutSoft` |
| Label, button, sign | 0.05-0.10 | `M.springEase(0.08)` |
| Rubber, friendly, bouncy | 0.15-0.25 | `M.springEase(0.2)` |
| Toy, cartoon impact | 0.4+ | `M.springEase(0.4)`, rarely more |
| Error or wrong: none | 0 | a hard stop, or a short shake instead of a bounce |

Physical version: damping ratio = damping / (2 sqrt(stiffness x mass)). Under 1 overshoots by exp(-pi z / sqrt(1 - z^2))
(checked in `test_motion_runtime.js`); 1 is the quickest arrival with none; above 1 is a slow crawl. A spring with
stiffness 170 / damping 26 (the defaults) has ratio 1 and settles in about 0.65 s; stiffness 300 / damping 30 settles in
about 0.46 s with a 0.4% overshoot; stiffness 120 / damping 12 overshoots 13% and settles in about 1.06 s (measured with
`M.springSettle`, within 0.2%) [PRACT, from spring presets in common UI libraries].

## Curves

| Use | Curve |
|---|---|
| Arrival | `out`, `quartOut`, `quintOut`, `expoOut` (very decisive), or a spring |
| Exit | `in`, `quartIn` |
| Move between rests | `inOut`, `quartInOut`, `smooth` (calmest; zero speed and acceleration at both ends) |
| Camera, big shape, wipe | `smooth` or `sineInOut` |
| Steady (rotation, progress, ticker) | `linear` |
| Wind-up then go | `anticipate` |
| Your own | `M.bezier(x1, y1, x2, y2)`, e.g. (0.2, 0, 0, 1) is a standard decisive arrival, (0.34, 1.56, 0.64, 1) overshoots |

## Stagger and choreography [PRACT]

- Between neighbours: 1-3 frames (0.03-0.09 s). Whole stagger at most 0.4-0.6 s (`total`). Wave or random: 0.03-0.06 s.
- Same curve for every item; only the start differs. The last item may take a little more overshoot as punctuation.
- Three or more movers: no more than about a third mid-move together. A background counter-move of 20-30% of the hero's
  speed makes the hero read bigger.
- Distance: no single straight move longer than about a third of the frame without a change of direction, speed or arc.
- Beats: setup 25%, action 35%, resolution 40%; 0.1-0.2 s of stillness before the next move.

## Camera and depth

- Drift on every shot: 3-5% push or pan over the shot, clamped to the plate [OURS].
- Parallax speed against the camera's move: far 0.1-0.3, middle 0.5-0.7, near 1.0-1.5 [PRACT]. Direction of depth as a cue is [STUDY].
- Punch-in on a face or detail: practitioners use about 1.1-1.25x and cap near 1.25x on 1080p footage [PRACT];
  the source's real resolution is the hard limit (letitedit-graphics section 3).
- Camera moves that carry a scene change: 1-2.5 s; one deliberate move per beat.

## Typed and kinetic text

- Typed letters: 26-34 a second, each at 1.45x size, 0.7 em to the side, settling in 0.18 s [OURS].
- Per word: 3-4 frames between words, rising from a mask or scaling from 0.9 [PRACT].
- Words faster than speech (about 150-190 words a minute) gain nothing; around 170-250 a minute was best in the few rapid-presentation studies found [STUDY, weak, Chinese text].
- Red X: two round strokes of 0.11 s each, about 30 px at 1080p; the sting on the second stroke [OURS].
- Splat or flash wipe: 0.2 s in (covers), cut on full cover, 0.2 s out [OURS].
- Blink: 0.14 s every 2.7-4.2 s; head nod +-0.035 rad: a face stays alive on almost no code [OURS].

## Sync

- Visual event on the word's onset or up to 2 frames (about 0.07 s) before it; not after [STD for the tolerance: sound
  early 45 ms / late 125 ms detectable, ITU-R BT.1359-1].
- Get the structure ready about 6 frames (0.2 s) before a line, reveal the fact on the word [PRACT].
- A hit: wind-up 3-6 frames, contact on the beat of the word, settle 8-15 frames [PRACT].
- Walk: the body moves 1.5 leg lengths per stride; planted feet then do not slide (measured: movement of a planted foot below 1e-6 px over 237 frame pairs) [OURS].
