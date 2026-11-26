# Sound tool recipes

The bridge modules `soundtrack.py`, `soundtrack_tools.py`, `music.py`, `op_specs.py` and `edit_code.py`
define these operations. Confirm current field names with `letitedit_guide('letitedit_soundtrack')`.
Times are timeline seconds (or `'m:ss.s'`) unless a field is named `song_*`.

## 1. `letitedit_soundtrack`: one song arranged around the edit

Order: `mode='song'` (analyse) -> `'plan'` (propose; nothing changes; listen to its preview mp3) -> `'apply'` with
`plan_id` (one undo step, or the saved file with a history copy; refused if the project, the song or the footage changed
since the plan: plan again, or `force=true`) -> `'measure'` with `plan_id` (the current mix against the plan's ranges,
after hand edits too). `'apply'` without `plan_id` plans and applies at once. `background=true` runs long timelines as a
job (`letitedit_jobs`).
- It plans from the saved file: a window's unsaved changes are refused, so save first.
- It replaces every clip on its track (default `Music`, made if missing), including Add music's clips.
- `{op: score}` writes the same gain keys: running score afterwards erases the soundtrack's section levels and deep
  ducks. One or the other per music track; speech levelling alone (`{op: level}`) is compatible.

| Field | Shape | Default | When to set it |
|---|---|---|---|
| `song` | path | - | the chosen track (`letitedit_library`) |
| `start`, `end` | seconds | the whole timeline | where the music plays at all |
| `sections` | `[{from, to, energy: low/mid/high/0-1, level?, name?}]` | none (unlisted time takes any material and the `none` level) | from the sound map: energy follows each section's gear |
| `hits` | `[{at, kind, approach?, tolerance_ms?, song_at?, name?}]` (or `[at, kind]`, or a number) | none | the 3-4 duet events per scene, hard hits; at least 0.25 s apart |
| `protect` | `[{from, to, mode, level?, fade_out?, fade_in?, entry?, name?}]` | none | natural sound, punchlines, the brief's protected ranges |
| `ending` | `auto`, `song`, `fade`, `stop` | `auto` (the song's own ending when it has one and it fits, else a fade) | `song` to resolve; `stop` ends on a bar line for a hard out |
| `entry` | `fade`, `hard` | `fade` (may start mid-bar so the first hit lands) | `hard` (on a downbeat) when the music enters on a story moment |
| `song_range` | `[from, to]` song seconds | the whole song | keep to one part of the song |
| `max_stretch` | 0-0.12 | 0 (never) | a small speed change to land hits; 0.02 moves the pitch 34 cents |
| `repeat` | `{max_uses, min_gap_s, loops, loop_bars}` | as needed + 1, 20 s, false (no block of up to `loop_bars` bars twice back to back), 8 | allow loops for a short bed under a long video |
| `levels` | dB vs the dialogue (after the song is matched to it; with nobody talking, vs -14 LUFS) | talk -18, none -6, low -9, mid -6.5, high -4, duck_deep -20 (vs the natural sound) | taste, after a listen |
| `track` | name | `Music` | |
| `options` | see below | | |
| `plan_id`, `force`, `background` | | | apply or measure an earlier plan; override a stale plan; run as a job |

`options` (defaults): `crossfade_s` 0.1 at a join on the beat grid (`weak_crossfade_s` 0.15 when the beat is weak,
`coarse_crossfade_s` 1.5 when the song has no steady beat), `fade_in_s` 1.5, `fade_out_s` 3, `drop_fade_out_s` 1,
`drop_fade_in_s` 0.5, `break_fade_s` 0.1, `tolerance_ms` 25, `attack_s` 0.35, `preroll_s` 0.1, `hold_s` 0.3,
`release_s` 1.0 (the dips under speech, as Add music), `merge_gap_s` 4 (speech pauses shorter than this stay dipped),
`section_ramp_s` 1, `duck` true, `beats_per_bar` 4, `beam` 96, `min_run_s` 2, `peak_ceiling_dbfs` -2 (the music on its
own stays under it), `preview_audio` true.

Hits. `kind` is what lands at `at`: `downbeat`; `bar` (any bar line); `phrase` (a 4-bar phrase start or an energy-
section start); `drop` (a bar where the music gets 3 dB or more louder into a loud stretch; the biggest rise when the
song has none); `beat` (treated as a bar line). `song_at` lands that song moment instead. `approach`: `auto` (the
cheapest), `join` (whole beats, the last cut short: a join right on the hit), `stretch` (the stretch before it sped up
or slowed by at most `max_stretch`), `break` (the music stops on a beat and silence leads into the hit: a button),
`none` (no edit; reports where the nearest event lands). Music already within `tolerance_ms` of the hit needs no edit.

Protect. `duck_deep`: the music held `level` dB (default -20) under that range's own measured sound (20 dB under the
talk level when it can't be measured). `drop_out`: the music fades out to finish at `from` (`fade_out` 1 s) and returns
at `to` (`fade_in` 0.5 s, `entry` fade or hard) on a fresh phase, so a hit right after it can land.

Read the plan before applying: warnings and findings; `song.beat_quality` (clear, weak, none: `none` means coarse
units of about 2 s, long crossfades and approximate hit times); every hit's `lands_at`, `error_ms` and `by` (natural,
join, stretch, break), and `without_edit` (where moving the picture cut instead would land with no music edit: often
the better fix); joins (`from_on` / `to_on`: downbeat, beat or between beats); sections (energy asked vs got); repeats;
the preview picture and the mp3 of the planned bed. After apply (or `measure`): `measurements` give the true peak, the
integrated loudness of the mix and of the music, music under speech (median and minimum LU over speech spans, spans
under 10 or over 24 LU), each protected range (music under the natural sound and a verdict), each hit's measured error,
each join's offset and level dip, and loops. Measurements can't certify taste: listen.

Example plan (JSON). The second hit is a hard hit on a picture cut at 70.0 s: half a frame early at 30 fps.
```json
{"project": "D:/edits/fan fix.mlt", "song": "D:/music/calm piano.mp3", "mode": "plan", "start": 0, "end": 92,
 "sections": [{"from": 0, "to": 24, "energy": "low", "name": "the problem"},
              {"from": 24, "to": 70, "energy": "mid", "name": "the fix"},
              {"from": 70, "to": 92, "energy": "high", "name": "it works"}],
 "hits": [{"at": 23.6, "kind": "phrase", "name": "gap after 'and then it quit on me'"},
          {"at": 69.983, "kind": "drop", "tolerance_ms": 15, "name": "cut to the fan running"}],
 "protect": [{"from": 70.0, "to": 74.5, "mode": "duck_deep", "name": "the fan spinning up"}],
 "ending": "song"}
```
Then `{"project": ..., "mode": "apply", "plan_id": "<from the plan>"}`.

## 2. `score`: open the gaps the music answers

Levels (dB vs the dialogue): talk -18, montage -6 (also the level wherever nobody talks and no zone is set), quiet -24,
swell -3, end -4. Speech is where the words are (cached transcripts; the voice detector only for files with none, with a
warning and `speech_from` in the result), so transcribe first. `merge_gap` (4 s) keeps the music dipped through
ordinary pauses; `answer` opens the ones you choose:
```
{op: score, answer: [{after: 'and then it quit on me'}, {after: "that's the sound I wanted"}]}
```
An answer can also be a pause id from the result's `gaps` (run it with dry_run first to read them), a time, or
`'auto'` (pauses of 2 s or more after a sentence, 20 s apart). The music rises after the last word and is back down
before the next one, with ramps scaled to the pause; pauses under about 1 s are refused (widen them with picture
first), and answers closer than 8 s get a pumping note. Zones still work for spans (a montage, a quiet stretch) and may
carry their own `attack` and `release`. Then `letitedit_check_audio(project, stems=True, every_s=0.5, start_s=...,
end_s=...)` around each answer and listen with `letitedit_check_range`.

Other score facts: it levels the speech clip by clip first (`level_voice: false` leaves clip gains); it switches off a
music track's auto-duck and resets very large track gains so nothing stacks; tracks named music/song/score/bed/sfx/
effect/sound/foley/ambience are never speech; it warns when the master has a dynamic loudness normaliser.

## 3. Add music (the person's button)

One click picks a song (long enough, not among the last 12 used, matching the person's music words) from their folder
and the free CC0 library, puts it on a Music track and ducks it by word times: Low / Medium / High = 22 / 18 / 14 LU
under talking and 10 / 6 / 3 dB under the dialogue level in gaps; each dip is complete 0.1 s before the first word and
holds 0.3 s after the last; pauses under 4 s stay dipped. With nobody talking it plays the music 4 / 8 / 12 dB over the
shots' own sound and doesn't duck. Remove pauses refits its music. Measured: 18.4-18.8 LU under the voice on three
projects; word-timed ducking cut false ducks from 76% to 5% on a 9.5-minute story (`BACKLOG-HISTORY.md`).

## 4. Protected ranges: from the brief's source ranges to timeline seconds
```python
import os
want = [{"source": "D:/footage/IMG_0412.MOV", "from": 31.0, "to": 36.5}]   # brief.json "protected"
out = []
for t in timeline['tracks']:
    for it, s, e in layout(t['name']):
        if 'clip' not in it:
            continue
        for p in want:
            if os.path.normcase(os.path.abspath(it['clip'])) != os.path.normcase(os.path.abspath(p['source'])):
                continue
            sp, a0 = float(it.get('speed', 1.0)), seconds(it['in'])
            a, b = max(p['from'], a0), min(p['to'], seconds(it['out']))
            if b > a:
                out.append({'from': round(s + (a - a0) / sp, 2), 'to': round(s + (b - a0) / sp, 2), 'mode': 'duck_deep'})
print(out)       # pass to letitedit_soundtrack(protect=...) or use as score zones at 'quiet'
```
A spoken punchline: `find("the punchline")` gives its timeline range; protect it plus the laugh after it.

## 5. Split edits (J and L cuts)
`{op: split_edit, id: <incoming clip>, lead: s}` is a J cut (the incoming sound starts s seconds before its picture);
`lag: s` is an L cut (the outgoing sound runs s seconds under the new picture). `move: 'sound'` (default) keeps the
picture cut and reaches into the source beyond the clip's edge; `move: 'picture'` keeps the sound cut and moves the
picture cut (the usual dialogue J cut: the listener holds while the next line starts). `fade` [0.1 s] is the
crossfade at the sound cut; the moved sound goes on the `J/L cuts` audio track (`track` to rename it), the covered
sound is silenced with `split_mute`, and both stay in sync with their pictures. It refuses at a gap, a transition, a
speed change, a reversed or soundless clip, past the source handles, or over words (the message names the words and
the longest split that keeps them; `drop_words: true` allows it). Later trims and ripples rebuild it; `lead: 0` or
`lag: 0` removes it. Never two voices at once.
- **Audio crossfade at a hard picture cut:** `transition: {type: cut, len: 0.25}` on the incoming clip: the picture
  cuts in the middle of the overlap, the sound crossfades across all of it (letitedit-fine decides where).

## 6. Loudness at export
- Web: `letitedit_export(project, loudness=-14, true_peak=-1)` (the defaults). Podcast: `loudness=-16`. Broadcast:
  `loudness=-23`. `loudness='off'` keeps the mix as it is.
- Then `letitedit_measure(<exported file>)`: integrated LUFS, loudness range, true peak, louder and quieter stretches.
- The export renders a float mix, limits true peak and re-limits lower until the encoded AAC is under the ceiling; a
  file still over is kept with a note. If that happens with a quiet mix and hot peaks, put a limiter on the master
  (`{op: master, effects: [{limiter: {limit_db: -1.5}}]}`) and measure again with `letitedit_check_audio`.
- A dynamic loudness normaliser on the master (`{loudness: {...}}`) lifts quiet stretches and pumps; prefer the limiter
  and let the export set the final level.

## 7. Listening and measuring
- `letitedit_check_audio(project, stems=True, every_s=0.5, start_s, end_s)`: loudness and true peak of the mix before
  export, quiet stretches, clips far from the typical level, and with stems how far the music sits under talking and
  how loud it is where nobody talks.
- `letitedit_check_range(project, start_s, duration_s)`: an MP4 of a range with its sound: the only real listen.
- `letitedit_hear(source, labels)`: what a stretch sounds like (CLAP labels: speech, machine, music, crowd...).
- `letitedit_separate(file, parts)`: stems (vocals, drums, bass, other) to find a song's entries or to clean a bed.
- `letitedit_footage(<song>)`: a song's beats, downbeats and energy sections; `letitedit_library(kind='music', query)`:
  songs with tempo and beat strength (a weak beat gives coarse cuts in soundtrack).
- `letitedit_fit_music(song, length, hits, land)`: a new audio file cut on the song's beats to a length or to hit times
  (for a bed outside a project, or a short that needs an exact length).
