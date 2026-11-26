# A learned reference's sound (letitedit-sound section 8)

Read in full when the selected Look has `sound_profile`, a sibling `sound.json` beside its recipe, or `sound.json` among its
`measured` files. Section 8's other rules (choose the function before the timbre, keep every effect on its purpose,
peaks of a whoosh or riser, over talking, bridges, one sound per job) apply as well.

When the selected Look has `sound_profile` (or sibling `sound.json` beside its recipe), read it before the sound pass.
Use the finished NEW picture's runtime, voice RMS and story anchors (`at` seconds, `role`: cut/broll/emphasis/reveal/
swell/drop/stop) with `letitedit_learn(action='sound_plan', reference=<sound.json>, result=<project>, package={
duration_s,voice_dbfs,anchors,audition:true})`. This is an explicit audition, not confirmation of uncertain detections.
Use its licensed candidate song with `letitedit_soundtrack` plan then apply, cut to this story's swells, bar/phrase hits,
dry beats and ending; apply the returned effect edits ONCE, after the music plan lands. Replan if the picture changes.
The plan's `opening` gives `reference_full_s`, the second from which the reference's music holds its main level, and
its sections keep only that long quiet. Another song or arrangement keeps the same opening both ways: up to that
second the music stays as quiet as the plan's first section (the song's own quiet start, or the music brought up over
those seconds; a hard entry at full level skips the reference's quiet start), and from that second it plays at its main
energy (a part of the song that is already full, not its intro or a long build); a swell anchored on a later peak
never makes the stretch before it quiet. When `full_after_opening` is true the reference
holds its main level within 3 dB of its loudest, with no build: the stretch after the opening asks for the song's full
part (`energy: high`) at the main level (`level: mid`), because a song's middling bars can sit 8 dB under its full
part. Check it on the export: `letitedit_export_job`'s
loudness over time, and the Look check's sound device with `video` names a cut that reaches its main level late, or
at its main level well before a reference whose music opens quiet; either one is fixed on the music's opening and
checked again on the new export.
**The reference's sound shape.** A Look's `sound.json` holds the reference's `shape` (a Look saved before has it
worked out when the Look check reads it): the first 5 s against the body, the level of every 5 s window against the
body and how far it dips and rises (`body_spread_db`), the ending (`held`, a `fade`, a `drop` or `silent` over its last
3 s) and the sharp hits (`hits.per_minute`, the share on cuts and on text arrivals). The Look check's `sound_shape`
finding (with `video`) names each part the export misses. Shape the score to it: an opening as far under the body as
the reference's; a level that moves as much through the body (sections at different energies, the music up in the
pauses and down under the voice, a key silence) rather than one flat bed; an ending of the same kind (a drop or silence
over the end card is the music stopped there, not a long fade). Hits: at the reference's rate per minute of the cut, on
what its hits land on (cuts, caption or title arrivals), each library sound's peak within an eighth of a second of what
it marks (a sound more than about 45 ms early or 125 ms late on its picture is noticeable: ITU-R BT.1359, strong), the
kind chosen by what it marks
(section 8's table). A reference with no hits gets none. A hit over speech stays, turned down under the voice.
What makes a hit read as one is the step, not the sound: the shape gives how quiet the second before the reference's
hits sits (`hits.before_under_body_db`) and how loud they land (`hits.level_vs_body_db`). A sound laid over steady talk
or a steady bed blends into it (a sound just after a louder one is heard less: forward masking, Moore, *An
Introduction to the Psychology of Hearing*, strong), so where the reference's hits come out of a quieter second, give
the hit its gap: the end of a pause or a breath, the music dropped out for about a second before it, and the hit at the
reference's level over the body. The check counts a rise of 9 LU within a second as a hit, a music fade from silence
over a second or less included; with a reference that has none, the music starts at its level or rises over several
seconds. Check again on the new export.
Before the final export, read the saved timeline again: compare its duration, visible cutaway entrances, emphasis
and resolving line against the sound map. Any later trim, replacement, scene move or review revision invalidates
the affected anchors, even when the total duration stayed the same. Remove or move the old planned effects before
applying replacements; never stack a second plan over the first. Rebuild the music's end and protection ranges too.
Check the final entrance, each effect peak and the last five seconds with `letitedit_check_range`, plus stems with
`letitedit_check_audio`. A multi-second dry ending needs a named story reason, not an obsolete drop/stop marker.
Record the final timeline duration and actual anchor times in the sound-stage note; an earlier plan call alone
does not prove that the exported picture carries the plan. Report any unlistened sound as unassessed.
Measured integrated stem LUFS difference overrides the generic 18-LU bed; never substitute an RMS dB difference for LUFS.
Effect gain uses the measured loud part, not a silent tail's median. Check waveform alignment, not just a binned RMS maximum.
Candidate rate is a provisional audition budget, NOT proven reference density. Fit effects to visible/semantic jobs;
do not turn dubious bells/roars into facts or scatter one effect per cut. Reference nonvoice RMS only bounds an audition
level: music contaminates it. Check voice/music/effect stems, peak alignment, density and short full-mix/isolated clips.
Listen with the person where hearing is unavailable; musical likeness and clarity remain unassessed, not a preference claim.
Audition proposals use role-matched library sounds (b-roll: whoosh; reveal: riser; emphasis: hit; cut: click).
An anchor's optional `sound` overrides this with whoosh/hit/riser/click/ambience. These are design proposals, not
identified reference effects. Empty roles are skipped; never substitute a voice or unrelated bell for room tone.
Missing/changed local assets require re-matching (`sound_reference`), not reference extraction or an unapproved download.

**Sounds tied to the picture.** When the Look's `sound.json` has a `synced` block, its clicks are part of the Look: a
click on each cutaway transition (a camera-shutter click, sometimes a quick double click) and a soft single key tick on
each caption word. Apply them once, after the captions and cutaways are final and the music is scored:
`{op: fx, sync_sounds: true}` (or the `synced_sounds` op the sound plan returns). It places each at the Look's offset
and level against the speech level of the speaker clips, which it measures itself (leave `voice_dbfs` out; pass it only
for a level you measured another way). Each sound is set by its own 5 kHz-and-up peak where the rule gives one
(`hf_peak_over_voice_db`; music cannot hide that reading) and by its full peak, the quieter of the two. It leaves out a tick that would sit within 0.18 s of another or
within 0.12 s of a click, and rotates the library sounds so no two in a row are the same file. Ticks are felt more than
heard: if one stands out over the voice, lower `peak_over_voice_db` in the rules you pass. Sounds placed this way do
not follow later picture changes: after moving cutaways or captions, take the old 'Effect sounds' items out and apply it
again. Account for both in the Look check as `sound_accents`, with their item ids, and check
a few joins with `letitedit_check_range`; the person judges how natural they sound.
