---
name: letitedit-finish
description: Finish a letitedit edit after the fine cut - match exposure and white balance across a scene's shots with letitedit_match_shots, clean the speech gently, run the sound pass with letitedit-sound and the captions with letitedit-captions (graphics first when the edit explains or labels), keep text and subjects out of each platform's covered areas, export each deliverable with its own settings (size, loudness, true peak, captions burned or as SRT), then hand every export to letitedit-gate. Use after the fine cut.
metadata:
  version: 0.2.0
---

# Finish

**Decision:** is the fine cut ready to deliver, deliverable by deliverable? Finishing changes how the video looks
and sounds and where text sits; it never changes the story. Load one presentation skill at a time: sound, then
graphics when the plan needs them, then captions.

**Inputs:** the fine-cut project, saved; `brief.json` (deliverables and platforms, `claims`, `narration`,
`protected`); `story_plan.json` (sections, feel); `log.json` (room tone, protected sound). Evidence tags as in the
skills README; documents in `references/sources.md`.

**Light the speaker** when the Look has measured lighting or the person asks: `{op: fx, lighting: true}` once the picture is final
(live editor filters on every speaker clip, tuned to the Look; letitedit-lighting). No cut-out and no model relighting.

## 1. Match the shots
**FINISH-1 One reference per scene.** Do: run `letitedit_match_shots` with the scene's best-exposed, most neutral clip
as `reference`; read the proposal and its frames, then apply it (one undo step; it writes an editable colour effect
on each clip and never touches the footage; `letitedit_guide('letitedit_match_shots')`). Give a neutral region on
something grey or white when the white balance guesses wrong; leave screens and lamps out (`ignore_regions`). When:
shots of one place and time whose exposure or colour shifts between cuts (auto exposure, two cameras, a passing
cloud). Not: shots whose look is the point (golden hour, night, a stylised grade, light that tells the time of day),
graphics and screen recordings; never across scenes. Check: `letitedit_check_frames` before and after at the joins;
the clips the tool left alone are listed with its reason. [GEN] [AOTC Porcelain War]

**FINISH-1a Steady a shot only when shake is the problem.** When: handheld b-roll meant to be steady, a walking shot
that wobbles, about 2 px or more of `shake_px` in the clip's `letitedit_fix` shake result. Not: tripod or already-steady
talking heads, a pan or a deliberate handheld feel, shots where something big moves in the frame. Do: read
references/steady-and-speed.md first (the reading, the engine and `smoothing`, the crop, the after-value, revert). The
first use downloads the vid.stab engine (184 MB): ask the person first on a new PC. [OURS]

**FINISH-1b Speed changes: pitch, sound and slow motion.** When: a time-lapse stretch, a punchline beat, a quick montage
cut. Not: speech the viewer must follow, a change with no job. The clip's own sound changes pitch with `speed` and keeps
no compensation, and captions made before a speed change are not re-timed by it. Do: read references/steady-and-speed.md
first (lengths, muting or an ffmpeg item for speech, slow motion and frame interpolation, ramps, the re-checks). [OURS]

## 2. Sound
**FINISH-2 Speech first, gently.** Do, on every cut: `letitedit_check_audio(project, stems=True)` once, and `letitedit_fix`
voice on the clips where someone talks (`fix: 'voice'`), all of them in one call: `item` = the list of their clip ids,
or `track` = the speech track (one undo step, one line per clip in the reply; `wait_s` waits for the job). Leave a clip only when
the facts say so, and write why in `finish_pass.md` (the gate reads it): nobody talks in it, it already
has the voice fix, or the floor is already -50 dB or quieter (`measures.floor_db`). Let the default,
`separate: auto`, decide per clip without asking. A sound actually playing between the words needs
separation; the subject of the dialogue alone is not evidence that the sound is present.
**What `auto` measures.** The gaps between the words: the median level of 0.1 s windows more
than 0.15 s from any word, in dB over the quietest tenth (the same fact as `letitedit_words`' `gaps:` clause). It
separates when that median reaches 3 dB in the clip's range or in the whole source file (so a trim can't turn it off); the
median only, not the 90th percentile. Separating room-only sound keeps some noise; cleaning a whole mix can suppress a sound the story needs.
No speech in the range = separate; speech
with too few gaps to measure = the whole mix, and the result says so. The apply result states what `auto` chose and
both numbers.
  **When to override** (an explicit `separate: true` or `false` always wins): the story says otherwise. A steady hum or
  fan the story is about, or ambience the brief protects (`protected`, `must_keep`), stays even where `auto` read room
  only: `separate: true`. A sound that `auto` kept because it is only noise nobody refers to: `separate: false`. To find
  what a high reading is, take the gaps of 0.5 s or more, read one with `letitedit_check_audio` (`start_s`/`end_s` on the
  gap) against the quietest gap of the clip, and `letitedit_hear` it (on plain room it returns weak music-like labels: read
  that as "nothing"). A clip that is talking almost without a gap can't be read this way: decide from the words and the log.
  Say which clips `auto` or you protected, and why, in your reply. Don't ask.
- **Room only: the whole mix (what `auto` chooses there).** DeepFilterNet 3 on the whole mix, `separate` false, `dereverb` false,
  the 18 dB limit [OURS].
- **A sound plays: `separate: true`** (what `auto` chooses there; Demucs keeps the voice and "the rest" apart; only the voice is
  cleaned and the rest is remixed at `rest_gain_db` 0). Separation also keeps noise classified as
  the rest and costs extra processing [OURS]. `rest_gain_db` -12 lowers the whole rest stem, the sounds that matter with the hiss.
- **Another way to protect a sound:** apply the clean-up only to the clips where speech is what matters and leave the
  sound-led clips alone. Name the choice in the brief's note, so the review knows the room was cleaned on purpose.
- Compare before and after: floor, speech level, range, the spectrogram in the result's sheet and, for anything the
  person will judge, a short before/after clip: only their ears settle how it sounds. For a sound that matters, run
  `letitedit_check_audio` with `start_s`/`end_s` on the stretch where it plays, before and after: its level should
  stay within about 3 dB. `speech_db` is the 95th percentile of 50 ms readings: with only a few words in the range
  it can fall for reasons that aren't the voice, so read the speech level inside the words' times too.
- Never `rest_gain_db` -120 under picture: it creates digital silence. Keep some room tone; check the
  quiet stretches and listen to the result, rather than targeting a sample's floor.
- Never dereverb a noisy whole mix (`separate: false`, `dereverb: true`): it can damage speech and sound harsh.
  Turn `dereverb` on only for a reverberant
  room, and then with `separate: true`, which is the combination the old default used.
- For low rumble that the voice fix does not reduce, use a high-pass
  engine effect (`letitedit_effects`), not this tool.
Raise `atten_lim_db` only while the noise still beats the voice (12-18 light, 30 medium; 100 risks underwater-sounding speech). When: phone, wind, hum, fan or noisy-room speech. Not: clean recordings; over-suppression; a sound the story
needs and `separate` false. Check: the floor falls by 10 dB or more while the speech level in the words moves by about
1 dB  [GEN, tightened by OURS];
the transcript's unsure words `(?)` don't increase (`letitedit_words` before and after); every protected sound keeps
its level. Revert with `action: revert` if the result sounds worse.

**FINISH-3 The rest of the mix: letitedit-sound.** Do: load letitedit-sound for music (chosen for the feeling, cut
on bars, peaks in the gaps between lines, real endings), natural and protected sound, bridges between scenes,
effects restraint and ducking (`letitedit_soundtrack`, the `score` op, Add music). Keep the order: speech cleanup,
speech levels, music and ambience, one master at export. When: every edit with sound. Not: never level or limit
clip by clip after the master. Check: letitedit-sound's checks; `letitedit_check_audio` (music against voice) keeps
speech on top wherever it must be heard; protected ranges stay audible. [GEN]

## 3. Graphics and captions
**FINISH-4 Graphics before captions.** Do: when the plan explains, labels or styles (steps, callouts, arrows, maps,
titles, names), run the letitedit-graphics pass first (`letitedit_annotate` points at things from the source picture),
so the captions can then be placed clear of it. When: tutorials, products, names in interviews and documentaries,
any labelled detail. Not: no graphic without a job the footage can't do. Check: letitedit-graphics' checks.
[AOTC Porcelain War] [GEN]

**FINISH-5 Captions: letitedit-captions.** Do: load letitedit-captions for spoken captions and on-screen words (the
style from the deliverable, chunking and reading speed, names and numbers from the brief's `claims` spelled exactly,
placement with `letitedit_caption_fit`), and always write a plain SRT for upload as well. When: every deliverable with
speech, and every platform watched muted first. Not: don't burn captions into a deliverable that wants them only as
a file. Check: letitedit-captions' checks; an SRT next to each export. [JH 29:50] [GEN]

## 4. Safe zones
**FINISH-6 Nothing important under the app's buttons.** Do: for each target platform, check the frames that carry
text, graphics or the key subject with `letitedit_check_frames(platform=...)`, which draws that app's covered areas
(the facts and their sources are in `letitedit_platforms`); move the text, or reframe, when anything that matters sits
under them. When: vertical shorts, and any platform that draws over the video. Not: when deliverables are separate
per platform, check each against its own app, not the union of all of them. Check: frames at every caption cue and
graphic start show no caption, label, face or product under a covered area. [YT] [GEN]

## 5. Export each deliverable
**FINISH-7 One export per deliverable, with its own settings.** Do: export each with `letitedit_export` (`preset`,
`loudness`, `true_peak`, `platform`; `letitedit_guide('letitedit_export')`), then `letitedit_export_job` until done. Size
and frame rate come from `letitedit_platforms`; other sizes are linked versions (`letitedit_versions`), each checked on
its own; per-platform shorts are separate edits (letitedit-shorts). Loudness and true peak come from the
deliverable, as letitedit-sound's loudness table sets them (the single source; if this line ever differs, that table
wins): web and social -14 LUFS, podcast -16, broadcast -23, true peak at most -1 dBTP. Master once on the whole mix
(the export's loudness), never per clip. When: every export. Not: never re-upload another app's download as a
platform version. Check: the export's measured loudness and true peak (`letitedit_measure` on the file) match its
deliverable; size and frame rate match the platform. [GEN] [RES Apple] [RES EBU R128]

## 6. Hand off to the gate
**FINISH-8 letitedit-gate decides; review.md speaks.** Do: run letitedit-gate on each export:
`letitedit_review_bundle` with the project, the brief and `critic='run'`. Its `review.md` is the
final word to the person; fix its findings and export again (two full rounds; the code counts them). When: every deliverable. Not: never
send your own summary instead, and never call a render ready that the bundle didn't see; passing measured checks does not override the critic's findings. Check: a `review.md` per export, newer than
the export. [OURS] [RES Timeline-Bench]

Write `finish_pass:` with the shots matched (and those skipped, with reasons), the sound, graphics and caption
passes, safe-zone checks per platform, and each export's path and settings. The journal saves `finish_pass.md`.
Then add a separate `letitedit_journal` note `stage:finish:done`.
