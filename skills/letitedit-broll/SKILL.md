---
name: letitedit-broll
description: 'Use b-roll well in a letitedit edit - which lines to cover and which to keep on the face, the kind of shot each line needs, short sequences instead of single shots, the sound under b-roll, the rhythm for shorts versus long videos, how much b-roll a genre or a Look wants, the person''s own reusable shots, and what to use when the footage has too little: stock, or b-roll letitedit makes (code scenes, drawn scenes, 3D, generated pictures, maps, graphics). Use in the rough and fine cuts, for a b-roll pass, when a Look sets a b-roll share, or when the person asks for more or less b-roll.'
metadata:
  version: 0.5.0
---

# B-roll: show what the words say

B-roll is picture that proves, explains or moves the talking forward. It is never filler: a shot that does not show
what is being said is worse than the face.

**Read by route:** `look:measured` (the Look has measured files: a learned Look, or a library Look with `visual.json`)
-> `references/measured-look.md`: picture-inverted caption Looks, the measured shot rhythm, cutaway slots, the Look's
b-roll character, inverted cut flashes (also when the person asks for them), measured camera moves and `broll_motion`,
measured negative-colour cut pulses, `b_roll_evidence`. When the route applies and the file isn't attached, read it in
full before choosing or placing b-roll. What `follow_motion` changes: `references/manual.md`.

## 1. What to cover, and what to keep on the face
**BROLL-1 Cover what the camera can show; keep the face where it carries the line.**
- **Cover:** a line that names something the camera can show (a part, a tool, a place, a step, a result, a number); a
  line that points at something to be seen ("you can see", "this one") over a whip, a fast pan or shake: the eyes look
  for the thing named as the word is said [STUDY Tanenhaus et al. 1995], so it goes on screen, steady; a jump cut or a
  retake seam; a talking head running past 20 s in a tutorial or vlog [HYP]; a list (one shot per item).
- **Keep the face:** the first second of the hook; credibility lines ("I've fixed a dozen of these"), jokes, emotion;
  the payoff reaction and the call to action.

## 2. The kind of shot each line needs
**BROLL-2 Pick the shot kind by the line's job.** A Look's measured individual shot rhythm takes precedence over these
generic ranges. How to carry it (`look:measured`): `references/measured-look.md`, "Shot rhythm".

| Kind | What it does | Length |
|---|---|---|
| Establishing (wide) | Where we are; a new place or a new day | 2-4 s |
| Detail / insert (close-up) | The exact thing named: the part, the tool, the screen | 1.5-3 s |
| Process | The action happening: hands working, the machine running | up to 6 s, cut on action inside it |
| Result / before-after | Proof: the noise is gone, it works, it is clean | 2-4 s, hold it |
| Reaction / cutaway | A person, a pet, the surroundings reacting | 1-2 s |
| Moving / POV | Energy and travel; transitions between parts | 2-4 s |
| Graphic stand-in | A map, diagram or screenshot when no footage shows it | as needed |

## 3. Sequences beat single shots
**BROLL-3 Cover a line with a short sequence.**
- **Shots per line:** 2-4 shots: wide, then medium, then close (or close to wide, to reveal).
- **Timing:** a shot comes in 0-300 ms before the keyword and goes out on a phrase gap [HYP]. Check against
  `letitedit_words(per_word=True)`.
- **Variety:** change the size or the angle (more than 30 degrees) between shots; no two near-identical shots back to
  back; never the same source range twice [RES].
- **Motion:** keep the direction of movement across a cut, and cut on action.

## 4. Sound under b-roll
**BROLL-4 The voice runs on; the shot's own sound sits under it.**
- **Talking continues under the shots:** J and L cuts; the voice may run 2-3 s over b-roll [HYP].
- **Natural sound sells the shot:** keep it 18-24 dB under the voice; let it come up in a pause (the drill, the click, the
  engine). A sound hit on a cut is fine.
- **A b-roll montage with nobody talking:** the shots' own sound sits under the music; Add music does this when it
  hears nobody talk.

## 5. Rhythm and amount
**BROLL-5 Rhythm and share by format, genre and Look.**
- **Shorts:** a picture change every 2-3 s; something new (angle, punch-in, b-roll) at least every 3-5 s [EXP]. B-roll
  may run under the whole voice-over, but the face carries the hook.
- **Long videos:** a framing change (b-roll, punch-in, graphic) every 20-40 s at least [HYP].
- **B-roll share of the runtime, by genre [HYP]:** talking or opinion 10-25%; DIY and tutorials 25-45%; travel and vlog
  40-60%; montage and opener close to 100%.
- **Measure it:** the share and the longest talking head in `letitedit_journal` (`stage:fine:done b-roll 32%, longest
  talking head 14 s`). Do not front-load coverage then leave a long face tail; do not inflate cutaway count with tiny
  talking-head flashes between otherwise contiguous shots.
- **Hold an insert long enough to read:** an insert (a cutaway from another file) stays on screen at least about 1 s,
  and about 1.5-2 s when the viewer must read it (a place, a label, a part): after a cut the eye takes about a third of
  a second to find and settle on the new shot [RES Smith 2012, Projections 6(1); Mital et al. 2011] [GEN]. A shorter
  clean stretch in the file: hold a frame or slow it rather than flash it, or put it under a line with room for it; a
  `flash:` marker says a flash is meant. Check: each insert's time on screen in the export's frames.
- **The chosen Look wins:** its b-roll amount and kinds override these numbers. **A Look's own level wins too:** its
  recipe (a learned Look's measured b-roll share and roles included) sets the share and what the cutaways do; reach it
  with section 6's order, not by holding the face longer than the Look does. A measured Look's cutaways a minute and
  shot lengths: `references/measured-look.md`, "Shot rhythm".

## 6. Finding the shots
**BROLL-6 Find each shot by the line's feeling, budget the sources, never fill with unrelated footage.**
- **The slots come from the tools** when the Look carries cutaway numbers (`letitedit_look_check` `cutaway_slots`):
  `references/measured-look.md`, "Cutaway slots".
- **Feeling first.** For each slot, in this order: (1) write the line the cutaway sits under; (2) name the feeling the
  line carries in a word or two (excitement, relief, curiosity, frustration, wonder, pride, doubt, closeness); (3)
  search and pick a shot that shows that feeling in the picture; (4) write why it fits in one sentence. If the only
  defence is a word the shot shares with the line, pick another. Hand the Look check `broll.feelings: {<clip id>:
  {feeling, why}}`; it keeps them in the project's `cutaway-notes.md` with each cutaway's line. The exception (section
  1): a line that is a plain fact the camera can show: show the fact.
- A picture-inverted caption Look: `references/measured-look.md`, "Picture-inverted captions".
- **Budget before building.** A learned Look: its semantic reference share and roles, not a face detector's cutaway
  estimate. Plan the new runtime and a shot ledger: spoken line, picture's job, suitable own shot, then any shortfall.
  Required coverage seconds = target share times runtime; subtract suitable own shots' visible seconds, not the source
  library's duration. Keep the face's hook, credibility, emotion, payoff and CTA slots reserved. The share is reached
  with the Look's count and lengths: cutaways per minute times the runtime, each about the Look's median length (a Look
  at 18 a minute and 58% of the time wants many short shots, a 20-second video about six or seven, not four long ones).
  Count the placed cutaways and their share before the check; fewer than the Look has means more shots, not longer ones.
- **Search:** `letitedit_search` (picture and words) over the project's footage and the person's library; confirm each
  pick with `letitedit_ask_frames` ("Does this show the <thing>? yes/no").
- **The person's own library:** topic-relevant coverage or the Look's idea/feeling illustrations. In travel videos,
  recurring shots (the channel's own sign, the vehicle on the road, a pet) can connect openers, chapters and endings,
  but are never filler for an unrelated line.
- **No shot for a line, or less b-roll than the Look needs?** Match the Look's amount with licensed stock or made
  coverage in the source kinds it permits. For a talking head about a topic, this order
  (own footage qualifies only when genuinely on topic):
  0. **A named real thing:** a line naming a specific app, brand, person, place, book or product shows that exact
     thing: `letitedit_real_picture` (search, then fetch; letitedit-graphics references/real-pictures.md says how to
     choose and how to make a sticker or card from it). Fetch it through the tool, never your own web tools, so an
     unattended run never stops on a permission prompt. A still gets a slow push-in or a pop so it isn't a dead hold.
  1. **Stock:** `letitedit_stock`, with a personal Pixabay key or an active supporter connection. Prefer the thing being
     said or a close visual analogue (typing, clicking, filming); keep its source, licence and credit receipt. For an
     idea/feeling Look, search meaning instead (anticipation, discovery, flow, relief, connection, transformation);
     choose cinematic people, nature, light and metaphor, colourful and mid-to-bright, with few literal anchors. Log the
     spoken idea each shot illustrates; illustration never proves a product claim.
     **Character of idea shots:** an idea shot carries the feeling of the line, found by "Feeling first"; the feeling
     decides the picture: relief is a long exhale, a window opening, shoulders dropping, light coming through;
     excitement is hands moving fast, a crowd turning, a run, sparks, a leap; curiosity is a face leaning in, a door
     ajar, something half seen; frustration is a tightened jaw, a tangle, a stalled machine; wonder is a wide sky, a
     glow, a face lifted. People, hands, faces, nature, light and
     motion all carry feeling; frame tight, in dim or saturated light, with a clear subject. A low-meaning word gets
     atmosphere (sky, water, dusk, texture). A noun in the line is not a reason for a shot: show the thing itself only
     when the line is about the thing (a tool, a place, a number), and then plainly. Judge the frames, not the search
     words: no clip that is only a workplace, a place or a thing, and no shot you could defend only by a word it shares
     with the line. No repeated asset or run of generic workstations. Write standalone properties, never
     source-dependent rules.
  2. **Screen recordings:** the footage's screens, or an actual recording of the product being discussed. Never record
     the person's screen or microphone unless they explicitly ask.
  3. **Made pictures:** `letitedit_image` prefers available, signed-in, permitted Antigravity, then the driving AI, a
     key and other permitted AIs. Never enable another-AI consent, download or sign in for the person. Each picture
     gets a slow push or parallax; a stationary image is not a moving cutaway.
  4. **Made scenes:** a code scene, motion clip, graphic, map or 3D shot; code-drawn scenes and graphics are available
     even when stock or drawing subscriptions are not. Match the line's job and the Look; read letitedit-motion and
     letitedit-graphics first. A process demonstration can show a selection becoming an edit, not a generic counter.
  - Reach the Look's share by budgeting these sources before building. Never accept or report "no b-roll source" as
    the reason to fall short: change the relevant shot plan and make the missing illustration, without padding with
    unrelated footage or pretending an illustration proves a real event.
  - Never an unrelated clip. Made and stock b-roll illustrate; they never pose as evidence of what happened (a drawn
    repair is not proof of the repair: letitedit-graphics). Say in the hand-off which shots were made or stock, never
    on the picture: no "illustration", "example footage" or similar labels in the video.
  - A reference's b-roll character (cinematic made b-roll graded like the Look): `references/measured-look.md`,
    "B-roll character".
  - Keep the face where section 1 says the face carries the line. Add any shot worth filming to the person's to-film
    list in `report.md`.

## 7. Check
**BROLL-7 Moves, media and the coverage ledger, checked on the export.**
- **Each cutaway's move, varied and aware of its own motion:** `{op: fx, camera_moves: true}`, called with no options,
  measures every cutaway's image motion first. A clip that already moves enough gets nothing; a still or a static shot
  always gets a move from the Look's measured spread (`pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `push_in`,
  `pull_out`), pans and tilts included; a clip that moves a little gets a move that does not work against it. No move
  repeats the one before it, in any mode; a move already used comes up less often. Read its reply (each clip's own
  motion, the move, the reason). Call it again after any cutaway is swapped or moved: it chooses every cutaway's move
  afresh. `follow_motion: true` only for a Look whose reference pans with the scene's own motion (its recipe says so),
  not a default (what it changes: the manual). Prefer licensed moving footage found by idea and feeling; do not fake
  orbit, depth or focus.
- **A measured Look's checks** (`look:measured`; inverted flashes on the cuts, also for any Look the person asks them
  on): `references/measured-look.md`, "Checks": inverted flashes (`{op: fx, cut_flashes: true, sync_sounds: true}`),
  named filmed moves and `broll_motion` against the learned rates, negative-colour cut pulses, and `b_roll_evidence`
  for private Look matching.
- **The medium for the job:** code/drawn scenes for processes or metaphors, 3D for spatial relationships, generated
  pictures with a slow move for an illustrative setting, maps for real geography, graphics for numbers and
  comparisons. Do not use every medium as a checklist. Match shot scale, rhythm and visual richness as well as share.
  Resolve a shortage with a relevant screen, moving picture or made scene, not filler or false evidence.
- **The export-bound shot log:** log the final export's visible intervals, including uncovered talking head and unknown
  spans. Full-frame cutaways count even with faces; captions, a crop of the same talking head, a tiny overlay and
  hidden timeline items do not. Check entrances, holds and exits with export frames; count transitions only while the
  cutaway is actually visible.
- Every covered line: verify visible content and explain its connection to the spoken idea. A Look may call for
  metaphor or feeling, not literal demonstration; record that distinction in the receipt, not on screen.
- After review trims or replacements, recompute the final visible coverage ledger against the final runtime: each
  covered line, its source and what the shot explains. Keep visual replacement share separate from relevant coverage:
  idea/feeling illustration supports a software or language-model line but cannot prove its claim.
  If a source is unavailable or downloads are forbidden, use a relevant moving process/result scene or available
  screen material; do not substitute unrelated library footage to meet the percentage. Refill relevant coverage lost
  to shortening, and report any remaining gap rather than quoting the earlier plan's share.
- A cutaway taken out after a review note leaves its coverage to refill: move it under a line it shows (the note may
  name one), or put another relevant shot in. When the footage has b-roll, a cut that shows none of it is a gap to
  fill, never the answer to a note; the review states it as a fact (`broll_unused`).
- No b-roll over credibility lines, jokes, the payoff or the call to action. No repeats. The share is within target and
  no talking head is longer than the target. The b-roll's sound sits under the voice. Waive a rule with
  `waive:<check>:<reason>`.
