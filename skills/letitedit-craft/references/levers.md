# Revision levers: plain notes into concrete changes

Read this first, in full, when the person gives feedback on a cut. The two rules (V1, V2) and the short table come
first, then the full one, with what each note usually means, the levers in the order to try them, the tools that move
them, the check that shows it worked, and what not to do. Rule ids (P2, C3, ...) point to SKILL.md. Tool parameters: `letitedit_guide('<tool>')`.

The levers come from the sources (cut rate, action in shot, shot scale and camera movement, space around lines, music:
ITE CdyTIng0M8Q 09:17, KAO0n3C0kAg 26:29; holds and reactions: ITE pRpaqx_5jD8 09:36, D2iBdbNej78 04:49; setups and
duplicate information: AOTC invite L310-314, AOTC mi L126-134). The mapping from words like "less flashy" to levers is
our synthesis [GEN] of those sources; nobody in the library publishes such a table (ITE's glossary poster is not in it).

## The rules and the short table (letitedit-craft section 8)

- **V1 Note to levers.** Find where the note applies on the render (ask only if you can't tell), map it with the table
  (the full one below), change those levers, keep structure and information unless asked, copy the project
  before a structural change, and say plainly what changed. "Keep everything else as it is" keeps the content and
  choices, not their faults: a clipped word, a cut through a sound or another fault a review finds there is a repair,
  so fix it and say so. A note's measurable target (a length, "cut the last 2 seconds", a level, a size) is kept:
  fix joins within it, at the clean cut point nearest the target, and take any time a repair needs from elsewhere,
  never from the note; say "partly" only when no clean cut point is near, and miss by the least. *When:* every note.
  *Not:* if it breaks the story, do it and say the cost once. *Check:* `letitedit_check_range`, then
  `letitedit_review_bundle`. [ITE KAO0n3C0kAg 26:29] [GEN]
- **V2 Two destinations.** For an open note or brief, offer a second version: same structure, another feeling (music,
  cut rate, shots per action, camera movement, spacing; a slower one runs ~1.3-1.6x), compared with `letitedit_try`.
  *When:* open notes. *Not:* clear ones. *Check:* same structure, other levers. [ITE KAO0n3C0kAg 16:00] [AOTC topgun]

| Note | First levers (rules) | Tools |
|---|---|---|
| "Less flashy" | drop stylised devices and repeats; fewer shots per action; steadier, wider shots; slightly lower cut rate; calmer music (X1, L1, P2) | `letitedit_timeline_read`, `letitedit_timeline_apply`, `letitedit_soundtrack` |
| "More energy", "punchier" | cut dead time; speech sooner; closer shots, more motion, more shots per action; hard cuts on peaks (P5, P2, P4) | `letitedit_timeline_apply`, `letitedit_soundtrack` |
| "It drags" (a stretch) | trim the setup feeding it; merge repeats; cut almost-right lines; open a loop or raise the stake; change its gear (C1, S2, T1, P3) | `letitedit_words`, `letitedit_search`, `letitedit_timeline_apply` |
| "Too slow" (overall) | raise the gear on three or more levers; enter sections later; rebuild the opening (P2, C4, C3) | `letitedit_measure`, `letitedit_timeline_apply` |
| "More breathing room", "let it land" | slow into it; image before the line; hold after; longer reaction; a music phrase in the gap (T4, B3, B4) | `letitedit_timeline_apply`, `letitedit_soundtrack` |
| "Rushed", "too fast" | restore breaths; widen gaps after key lines; one idea at a time; fewer cuts (P5, D3, P4) | `letitedit_words`, `letitedit_timeline_apply` |
| "Confusing" | premise and stakes earlier; literal pictures early; linear order; context where needed; a label (T2, S5, B1) | `letitedit_timeline_apply`, `letitedit_annotate` |
| "Too long" | whole beats that don't pay off before trims inside lines; merge repeats; in later, out earlier (S2, C4) | `letitedit_find_takes`, `letitedit_timeline_apply` |
| "Choppy", "robotic" | hear the joins; crossfades and room tone; restore breaths; re-pick takes; cover jumps (D4, D3, D2, D6) | `letitedit_check_range`, `letitedit_timeline_apply` |

## How to run a revision

1. **Locate.** Find where the note applies: the person's timecode, the section they name, or the place the render
   shows it (`letitedit_overview` shows the whole edit in lanes; `letitedit_check_frames` for frames). Ask only when the
   note could mean two different places and the render doesn't say which.
2. **Diagnose before changing.** Decide which lever is off. Measure it rather than guess: cut rate and shot lengths
   (`letitedit_measure`, or the export's picture_change from `letitedit_export_job`), gaps around lines (`letitedit_words`
   on the project, per word), music level and coverage (`letitedit_check_audio`), devices (the ledger, L1).
3. **Plan the smallest change that answers the note.** Change levers, not structure or information, unless the note
   asks for structure (ITE KAO0n3C0kAg 00:27: re-engineering a scene to a director's note is the core skill).
4. **Copy before structural work.** Moving, dropping or reordering beats: copy the project first
   (`letitedit_project_new` makes a copy). Small trims need no copy.
5. **Apply as one undoable change.** `letitedit_timeline_apply` (it checks every change before anything lands, so no
   `dry_run` first; `letitedit_timeline_undo` reverts).
6. **Check the lever moved.** Re-render the changed range with sound (`letitedit_check_range`) and run the note's check
   below. A note about feel is not answered until you have watched the range.
7. **Say what changed** in one or two plain lines (what moved, how much, what it cost), and update `why:` markers.
8. **Before delivery** run `letitedit_review_bundle` again; the final word is `review.md`.

**Conflicting notes** ("punchier" and "give the reveal more room"): apply each at its own scale. Energy in the
sections around the moment, space at the moment itself; that contrast is the gear variation P3 asks for [GEN].

**A note that would break the story or the brief** (cut the setup a payoff needs, drop a must-keep line): do it if the
person insists, and say once what it costs (audit FC15; ITE KAO0n3C0kAg 00:27).

**A note you can't parse** ("make it pop", "not quite right"): offer two versions with different destinations (V2)
rather than guessing one. Name what differs between them.

## The notes

### "Less flashy" (tone it down, too busy, too much going on, calmer, cleaner)
- **Usually:** stylised devices, camera movement and cut rate run above the intended feeling (P1); devices repeat.
- **Levers, in order:** (1) remove or replace stylised devices and repeats first: glitches, digital zoom punches,
  whips, crash zooms, whooshes, flashy title moves (X1, L1); (2) fewer shots per action, steadier and wider shots,
  more locked-off framing (P2); (3) a slightly lower cut rate; (4) calmer music or fewer hits (letitedit-sound);
  (5) a little more space around lines; (6) fewer visible jump cuts (D6); simpler captions (letitedit-captions).
- **Tools:** `letitedit_timeline_read` (find effects, transitions, scale keyframes, SFX clips), `letitedit_timeline_apply`
  (`delete`, `effects`, `set`, `trim`), `letitedit_soundtrack` or Add music for a calmer cue, `letitedit_caption_fit`.
- **Check after:** ledger counts fell; camera-motion share and cut rate fell (`letitedit_measure`); structure unchanged.
- **Don't:** only lengthen clips (P2: speed is several levers); strip the plain cuts that carry the story.
  ITE KAO0n3C0kAg 26:29-35:43; ITE A2RYo1xNSA4 10:57-11:14; ITE 4s7WdcyV1H4 11:04-13:09.

### "More energy" (punchier, faster, it's boring, wake it up)
- **Usually:** dead time, or a gear below the feeling.
- **Levers, in order:** (1) cut dead time: warm-up, search pauses, tails (P5); (2) speech starts sooner, tighter gaps
  inside thoughts (D3); (3) closer shots, more movement in frame, more shots per action (P2); (4) hard cuts on energy
  peaks instead of letting them die off (P4; AOTC dune L72-80); (5) music with drive and a few hits on picture moments
  (letitedit-sound); (6) a stake or loop earlier (T1, S3).
- **Tools:** `letitedit_timeline_apply` (`trim`, `delete`, `gap`, `tighten` for a first pass), `letitedit_soundtrack`.
- **Check after:** three or more levers moved; key lines still have their space (P4); breaths at thought ends remain.
- **Don't:** fake energy with effects (X1); strip every breath (P5: over-tight reads as insecure and can feel longer).

### "It drags" (sags in the middle, loses me at 2:10, too much of the same)
- **Usually:** one stretch with no new change, question or stake; a setup that's too heavy; repeated information; the
  same gear as its neighbours.
- **Levers, in order:** (1) find the stretch (the person's time, or where a first-time viewer would ask "why are we
  still here?"); (2) look at the setup feeding the slow part and trim it (AOTC invite L310-314); (3) merge repeated
  information and the same action shown twice (S2); (4) cut almost-right lines (C1); (5) open a loop or raise the stake
  (T1, T3); (6) change its gear against the neighbours (P3); (7) enter later, leave earlier (C4).
- **Tools:** `letitedit_words` and `letitedit_search` (find the repeats), `letitedit_find_takes` (duplicate takes),
  `letitedit_timeline_apply`.
- **Check after:** the stretch now has a change or an open question; the gear list varies; report the time saved.
- **Don't:** speed the whole video up for one slow stretch.

### "Too slow" (the whole thing)
- **Usually:** the overall gear is below the feeling, or the opening is slow.
- **Levers, in order:** (1) raise the gear on three or more levers (P2); (2) rebuild the first 10 seconds (C3);
  (3) enter each section later and leave earlier (C4); (4) compress drag inside thoughts (D3); (5) compare with the
  `reference` if there is one (`letitedit_measure` on both).
- **Check after:** measured cut rate, words per minute and gaps moved toward the reference or the stated feeling.
- **Don't:** apply one global pause threshold (D3).

### "More breathing room" (let it land, give the reveal a moment, slow down here)
- **Usually:** a key line or reveal is followed too soon by the next line or cut.
- **Levers, in order:** (1) decelerate into the moment: longer shots, fewer cuts before it (T4); (2) show the reveal
  image first and bring the line in once it registers (B3; ITE WOX-WdXSOOc 47:27); (3) hold after the line or the
  reaction until the expression resolves (B4, R2); (4) move a music phrase into the gap after it, so the music answers
  the line (letitedit-sound, `letitedit_soundtrack` hits); (5) remove any new line in the same breath.
- **Tools:** `letitedit_timeline_apply` (`gap`, `trim`, `move`), `letitedit_soundtrack`, `letitedit_words` (measure gaps).
- **Check after:** the gap after the moment grew (P4's ~1.5 s in long-form is a floor, not a target [GEN]); the
  picture holds; any music phrase in the gap ends before the next word. Mark a long hold `hold:<reason>`.
- **Don't:** hold a frame where nothing changes (P4: a hold must stay alive).

### "Rushed" (too fast, breathless, I can't follow)
- **Levers, in order:** (1) restore breaths at thought ends (D3); (2) widen gaps after key or complex lines (P4);
  (3) one idea at a time with picture space between (P4); (4) fewer cuts, steadier shots (P2); (5) let new images
  register before the line that comments on them (B3).
- **Check after:** in-thought gaps intact, thought-boundary gaps uneven and present; no 30 s without a reset (P5).

### "Confusing" (I don't get what's happening, lost, who is that?)
- **Usually:** the premise or stakes come late; time jumps or non-linear order; context missing where it's needed.
- **Levers, in order:** (1) premise and stakes earlier (T2, S3); (2) literal pictures early (B1: see-and-say in cold
  opens, AOTC pop L60-70); (3) linear order unless out-of-order keeps the emotional order clear (T2; AOTC mi L62-64);
  (4) cut "when is this?" cutaways (AOTC mi L232-246); (5) thread the missing context in where it matters (S5);
  (6) a label, arrow or detail where a thing must be seen (letitedit-graphics, `letitedit_annotate`); plain on-screen
  words (letitedit-captions); a time card from the real recording date (X2).
- **Check after:** a first-time-viewer pass answers what is at stake, what just happened and who this is
  (checks.md, section 3).
- **Don't:** explain everything up front: withhold answers, never the premise (T2).

### "Too long" (cut it down, make it 60 s)
- **Levers, in order:** (1) whole beats or sections that don't pay off later (S2, S5); (2) repeated information and
  duplicate takes (`letitedit_find_takes`); (3) enter later, leave earlier (C4); (4) then compress drag inside thoughts
  (D3); keep breaths and the holds on key lines (P5, P4).
- **Check after:** length within the target; the setup-payoff list still pairs up (S5); key lines keep their space.
- **Don't:** hit the length by stripping all pauses (P5); cut a setup whose payoff stays.

### "Too short" (it ends abruptly, felt rushed at the end)
- **Levers:** one ending, landed: a short line or image, then a beat (C4); the payoff on screen, not only said;
  resolve the music or cut to black on a beat (X1, letitedit-sound); restore a held reaction (R2). In a Short, the
  abrupt end right after the payoff is usually correct (letitedit-shorts); check the payoff is visible first.

### "Choppy" (robotic, sounds cut up, jumpy)
- **Levers, in order:** (1) hear every join and fix broken melody or temperature (D4); (2) short crossfades and
  same-place room tone at joins (D4, letitedit-sound); (3) restore breaths (D3); (4) re-pick takes (D2); (5) cover
  visible jumps or change size (D6); (6) match movement across action cuts (X2).
- **Tools:** `letitedit_check_range` (listen), `letitedit_words` per word, `letitedit_timeline_apply`.
- **Check after:** a listening pass over the range with no broken join (checks.md, section 4).

### "More personal" (more emotional, I want to feel it, it's cold)
- **Levers:** face on the emotional lines (B4); a close-up when the speaker turns inward (ITE xZnHgyeZlsU 20:14);
  hold after key lines (P4); behaviour b-roll on emotional anchors (B3); keep personality lines and natural laughs
  (S2, D2); fewer music cues, or one that answers a line in a gap (letitedit-sound).
- **Don't:** add music to tell the viewer what to feel (AOTC invite L118-124).

### "More cinematic" (more like a film, more premium)
- **Levers:** a poetic opening (C3); longer, steadier shots and more establishing space (P2; ITE KAO0n3C0kAg 33:22);
  sound layered in before music (letitedit-sound); withheld details (T2); fewer stylised devices (X1); subtext b-roll
  after the opening (B1); fewer visible jump cuts (D6).

### "The opening is weak" (hook me, it starts slow, boring start)
- **Levers:** rebuild the first 10 seconds for a named feeling (C3); start later (C4); no greeting or fact-stack;
  a Short's premise readable muted from frame one (letitedit-shorts); two or three openings, made last, for the
  person to choose (C6, letitedit-firstcut).
- **Check after:** the muted 10-second test (checks.md, section 2).

### "The ending falls flat"
- **Levers:** one ending, the strongest payoff last (C4, S5); a short line or image to land on; music that resolves or
  a cut to black on a beat (X1); in a Short, end right after the payoff (letitedit-shorts).

### "Doesn't flow" (jumps around, disconnected, bitty)
- **Levers:** a reason at every boundary: pictorial bridge, verbal hand-off, question answered next (C5); sound
  bridges and J/L cuts (letitedit-sound); contrast at section starts (C5); varied gears (P3); the voice's emotional arc
  kept across reorders (D4).
- **Check after:** the boundary table names a reason for every boundary (checks.md, section 7).

### "Repetitive" (same thing again, predictable)
- **Levers:** read the device ledger and vary or escalate (L1); merge duplicated information and actions (S2); change
  consecutive reveal treatments (L1; ITE 4s7WdcyV1H4 06:04); vary section openings and endings (C5).

### "Feels fake" (staged, manipulative, too polished)
- **Levers:** fewer visible jump cuts (D6; ITE A2RYo1xNSA4 08:58); drop over-dramatised reveals and stings (L1, X1);
  keep real complications and natural moments (S6; AOTC pop L166-176); keep non-words that carry character (D2); audit
  D5 (no borrowed reactions, no fragments joined into new claims).

### "Too much talking" (show more, show don't tell)
- **Levers:** cover information-only bites with sequences (B2, B4); make space between islands with pictures (B1);
  cut almost-right lines (C1); let pictures carry a progression (C2). How much b-roll suits the mode: letitedit-modes.

### "I want to see the person" (less b-roll, more face)
- **Levers:** face on key and closing lines (B4); drop wallpaper and cover-only runs (B1); hide joins with a size
  change or a reaction instead of b-roll (D6).

### "Make it funnier"
- **Levers:** keep the line from setup to punchline clean of new information (T3; AOTC invite L188); one look may be
  enough, and never a reaction after every punchline (R2); leave room after the laugh (AOTC pop L270); cut the joke's
  explanation; hard cut out of the button (P4).

### "Make it like <video>"
- **Levers:** measure the reference (`letitedit_measure`: cuts and words per minute, speech, music and effects shares,
  loudness) and move the matching levers (P1, P2); keep your structure unless the reference's structure is the point.

### "Explain it more clearly" (tutorials, how-tos)
- **Levers:** one idea at a time with picture space (P4); the step shown in a chain, not one shot (B2); a visible count
  for steps (S4); labels, arrows and detail crops (letitedit-graphics, `letitedit_annotate`).

### Notes for other skills
- Music too loud, distracting, wrong mood: letitedit-sound (`letitedit_soundtrack`, `letitedit_check_audio`).
- Captions too big, too small, in the way: letitedit-captions (`letitedit_caption_fit`).
- Colours or brightness jump between shots: letitedit-finish (`letitedit_match_shots`).

## Lever index: what changes each lever and how to see it

| Lever | Changed with | Seen with |
|---|---|---|
| Cut rate, shots per action | `letitedit_timeline_apply` (`trim`, `delete`, `insert`, `move`) | `letitedit_measure`, `letitedit_export_job` picture_change |
| Action inside the shot | choice of take or range (`letitedit_search`, `letitedit_footage`) | `letitedit_check_frames` |
| Shot scale, camera movement | choice of shot; punch-ins via `set` (scale) | `letitedit_check_frames` (per shot), `letitedit_overview` |
| Space around lines, breaths | `trim`, `gap`; `tighten` as a first pass only | `letitedit_words` (project, per word) |
| Music energy, hits, dry stretches | `letitedit_soundtrack`, `letitedit_fit_music`, the `score` op (letitedit-sound) | `letitedit_check_audio`, `letitedit_overview` |
| Stylised devices, transitions | `effects`, `set`, `delete` | `letitedit_timeline_read`, the `devices:` ledger note |
| Face vs cover | b-roll items on an upper track (`insert`, `delete`) | `letitedit_check_frames` at key lines |
| Order, structure | `move`; a copy first (`letitedit_project_new`) | `letitedit_overview`, the story plan |
| Alternatives | scratch versions (`letitedit_try`) | `letitedit_try` side by side |
