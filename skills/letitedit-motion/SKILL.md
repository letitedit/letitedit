---
name: letitedit-motion
description: How things move in a letitedit video - the timing of arrivals, holds and exits in frames, easing, overshoot and springs chosen by weight and feeling, one focal point at a time, staggering and choreography, a camera and parallax through one continuous world so connected scenes feel like a film, kinetic type, landing a move on the spoken word and the sound (letitedit_words, sound peaks), and the checks that catch cheap-looking motion on the AI's own frames. For video, not app interfaces. Use whenever a code scene, a motion block (letitedit_motion), an animated title, a moving label or a moving caption is written or revised, or on notes like 'it looks cheap', 'it feels stiff', 'too busy', 'it pops in', 'the timing is off'.
metadata:
  version: 0.1.0
---

# Motion: timing, weight, focus, camera, type, sync

A personal Look's graphic-kit.json contains its executable motion as well as its layout. New video places
those frozen families with kit_plan; do not reinterpret their animation in a new code scene or motion block.
Learn checks each family's rendered entry, hold and exit against private reference crops, adjusting the
portable drawing before saving the Look. Content slots change words, not timing curves or visual hierarchy.

For filmed shots and editorial transitions, read `references/camera-moves.md`
first. It names supported image moves, stock-only physical moves and honest
limitations. The selected Look's durations and measured speeds take precedence.
The generated-world advice below does not require generating a scene or moving
every filmed shot; a filmed-only Look stays filmed-only.

**The decision:** for each thing that moves, what the viewer should look at, when it arrives, how it settles, and what
else stays still while it does.
**Inputs:** the line being said (`letitedit_words`), the story plan's beat for it, the brief's `feel`, the style or Look
recipe, the video's frame rate (`letitedit_footage`), the sound under it. The footage and the words decide *whether* a
scene or title earns its place (letitedit-graphics); this skill is *how it moves* once it does.
**Tools:** `letitedit_code_scene`, `letitedit_motion` (its tool text lists the runtime: `M.prog`, `M.spring`,
`M.springEase`, `M.bezier`, extra `M.ease` curves, `M.stagger`, `M.camera`, `M.parallax`, and canvas parts under
`M.draw` such as typed text, a red X, a wipe, motion blur and people). They are parts to use or ignore. You write each
scene fresh for its line; nothing here is a preset, and no number below is a look.
Optional drawing kits (the marks and paper of a real medium: pencil, ink, paint, print, paper craft, pixels and the like) are listed by `letitedit_motion(action='hands')`; a scene needs none.
**Evidence tags** (full list and what each rests on: references/sources.md): [STUDY] measured in published research,
[STD] a published industry standard, [BOOK] established animation teaching, [PRACT] practitioner habit with no
measurement behind it, [OURS] local editing practice, [GEN] reasoning. Most motion numbers are [PRACT]:
treat them as starting points to check on frames, never as limits. Numbers: references/numbers.md.

## 1. Start from the line, not the effect
Write one sentence before any code: what the viewer should see change on which word, and why that word. Give the piece
three beats - setup (the world is there), action (the thing that matters moves), resolution (it settles and the eye
rests) - roughly 25 / 35 / 40% of its time [PRACT], and leave 0.1-0.2 s of stillness before the next move. A scene that
cannot be said in one muted sentence ("the dial turns as the speaker says *increase*") moves too much [PRACT; OURS]. Animation helps most when its motion *is* the change it explains (a number growing, a
route drawn, a part sliding in) and helps least as decoration on things that did not change [STUDY: Tversky,
Morrison and Betrancourt 2002, congruence and apprehension]; so motion that depicts nothing the line says is the first to cut.

## 2. Timing: arrive, hold, leave
Count in frames: at 30 fps one frame is 33 ms (24 fps: 42 ms; 60 fps: 17 ms). Starting points [PRACT]:
- **Marks and small things** (a tick, an X stroke, a dot): 3-6 frames. **Labels, cards, normal elements:** 8-15 frames.
  **Hero objects and whole-scene changes:** 18-30 frames; further or bigger travels take longer.
- **Leave faster than you arrive:** an exit is about 65-75% of its entrance. Same-speed in and out reads mechanical.
- **A hold starts when the move settles, not when it starts.** Words that must be read: letitedit-graphics section 3
  (words / 3.5 + 0.5 s, at least 1.5 s) counted from the settle. People read silent text at about 238 words a minute
  and aloud at 183 [STUDY: Brysbaert 2019, plain text without competing video]; words on screen beside a voice and a moving
  picture should be given more time than that, not less [GEN]. A single word or number that is the point can
  hold 0.6-1.0 s.
- **Do not animate in one- or two-frame steps** unless it is a hit: a thing that goes from nothing to full in one
  frame reads as a glitch, except on a hit sound or a hard cut [PRACT].
- **Fast moves strobe** at 24-30 fps. A shape that travels more than about 8% of the frame per frame needs blur
  (`M.draw.blur`: 3 samples across half a frame, the film habit of a 180-degree shutter [PRACT]) or a slower move. The 8% is
  our estimate [GEN]. Blur costs n times the drawing time.

## 3. How things settle: easing, overshoot, springs, weight
Motion without acceleration looks mechanical because nothing real starts or stops instantly; slow-in and slow-out is
the oldest rule of animation [BOOK: Thomas and Johnston]. Choose by what the thing is:
- **Arrivals ease out** (fast then settling), **exits ease in**, **moves between two resting places ease in and out**
  (`smooth` for a big shape or a camera), **linear only** for steady things (a rotation, a progress bar, a ticker)
  [BOOK; PRACT].
- **Weight is overshoot.** How far a thing passes its target and comes back says what it is made of: none for
  something rigid or glassy, about 3% for paper or a card, 5-10% for a label or button, 15-25% for rubber, 40%+ for a
  toy [PRACT]. `M.springEase(overshoot)` gives exactly that; `M.spring(t, {stiffness, damping, mass})` is the physical
  version (a damping ratio under 1 overshoots). Use a spring for things that land (a sign, a pop, a character's hop)
  and a curve for things that glide (a camera, a wipe, a fade).
- **Anticipation and follow-through** make a big move believable: a small move the other way 3-6 frames before it
  (`M.ease.anticipate`), and parts that settle a beat after the body (delay a child 2-4 frames behind its parent)
  [BOOK].
- **One family per video.** Pick the overshoot and curve for the kinds of thing in it and reuse them; a different bounce
  on every element looks like a template picker, and repeated devices are counted (letitedit-graphics section 5) [OURS; PRACT].
- Never end on an almost-arrival: ends must be exact (`M.prog` and `M.springEase` return exactly 0 and 1 at the ends).

## 4. One focal point at a time
Something that starts moving, or appears, pulls the eye before anything else does [STUDY: abrupt onsets and motion
onset capture attention - Yantis and Jonides 1984, Abrams and Christ 2003; the later work shows jerky motion drives
much of it, so smooth drifts capture less]. Use that on purpose:
- **Start the thing you want read first.** Order of arrival is order of attention: the sentence or main object first,
  supporting detail after, never the reverse [PRACT].
- **Keep everything else quiet while it lands.** Ambient motion (drift, particles, a slow breathing camera) is low in
  contrast and slow; a hero moves several times the distance and speed of what supports it [PRACT]. With three or
  more moving things, let no more than about a third be mid-move at once, and have the first settle as the last starts [PRACT].
- **Hand the eye on:** finish A (it settles), start B within 0.1-0.2 s, in the direction the eye is already
  travelling, or the direction a person in the shot looks [PRACT/GEN].
- **Show a new element when it is named, not before.** Words and the picture that goes with them landing together
  teach better than either alone or one after the other [STUDY: Mayer's temporal contiguity and signaling
  principles; signaling effect about d = 0.4-0.5 in meta-analyses - secondary figures, see sources].
- **Exits finish before the next element lands in the same place.** Two things in one spot at once is the most common
  fault in the scenes we have looked at (a word on top of the fading previous word) [OURS].

## 5. Staggering and choreography
When several things arrive for one reason, give them one trigger and different landing times: they start within a
frame or two of the cause and finish at different times, with the *same curve* and only the start time changed [PRACT].
- `M.stagger(i, n, {each, total, from})`: 1-3 frames between neighbours (0.03-0.09 s), whole stagger capped by `total`
  (about 0.4-0.6 s) so the last item is not late for its word [PRACT]. Reading order for lists, `center` for a hero,
  `end` or reverse for exits, `random` (seeded) for organic things like sparks [PRACT].
- **One origin.** Elements that travel in come from the same side or the same point; mixed directions read as chaos [PRACT].
- **Break a long travel:** nothing crosses more than about a third of the frame in one straight move without a change
  of direction, speed or an arc [PRACT].
- **Counter-motion is depth:** a background that drifts 20-30% against a hero's move makes the move read larger [PRACT].

## 6. Camera and depth: one continuous world
A run of separate pictures that fade or slide in turn is a slide deck, whatever the polish of each. Scenes feel like a
film when one world persists and the **camera or the world moves** to change what we see [PRACT: Bang Motion; OURS].
- **Keep a camera on every shot**: a slow push or pan of 3-5% over the shot, clamped so the plate's edge never shows
  (`M.draw.camera`; or `M.camera` with keys for your own world). Frozen shots are the first thing viewers read as cheap [OURS].
- **Change scene by moving:** push through something, pan to the next, pull back to reveal, or carry one object from
  the old moment into the new (the same shape, now a different thing). A hard cut on a new idea is fine too; a fade
  between two unrelated cards is the slide-deck tell [PRACT/OURS].
- **Depth from different speeds.** Relative motion is a real depth cue [STUDY: Rogers and Graham 1979]; the ratios are
  habit [PRACT]: far layers move about 0.1-0.3 of the camera's move, middle 0.5-0.7, near 1.0-1.5
  (`M.parallax(cam, depth)`). Put fog, rain and dust in front, not just behind.
- **Zoom in log space** (`M.camera` does) so the move looks even; don't zoom in and straight back out; one deliberate
  camera move per beat, not a different one on every cut.
- **Never slide the world so far that its edge or a black gap shows.**
- **Into and out of the speaker's shot:** the scene grows out of something in the footage (light, a shape, a move)
  and hands back the same way; letitedit-graphics section 4 and letitedit-layers cover the person in front.
- **Behind a person, compose to their outline:** the world's main shape follows the room their outline leaves (a curve that
  rises beside the shoulders and passes over the head, not level layers the person stands in front of), with a dark margin
  around them and events big enough to read in the strips and the band at phone size. `behind_person.room` from
  `letitedit_code_scene` gives the numbers [OURS].

## 7. Kinetic type
Type is read, so it must be still long enough to read. Most of the craft is hierarchy and timing; little needs motion.
- **Say it with the voice.** Show each word or short phrase as it is spoken, onset on the word (section 8), so the eye
  is not ahead of or behind the ear. Showing words faster than speech (about 150-190 words a minute) buys nothing:
  rapid one-word presentation comprehension peaks near 170-250 words a minute in the studies found, and phrase-sized
  chunks held up better than single words, though that evidence is mostly Chinese text and thin [STUDY, weak].
- **Emphasis by size, weight and colour on one word per line;** the rest stays calm. Motion on every word is no emphasis [PRACT].
- **Typed letters:** 26-34 letters a second, each arriving about 1.45x size and 0.7 em to the side and settling in
  0.18 s, was the largest "feels right" gain in the code-drawn explainer [OURS]. Word by word: 3-4 frames
  between words, each rising from a mask (translate 100% inside a clipped box) or scaling from 0.9 [PRACT].
- **Settle before the read.** Text still moving cannot be read; the reading hold (section 2) starts at the settle.
- **Not:** every title with the same entrance, rotation while being read, bounce on every word, all caps for long lines,
  text over a busy area without a panel or outline. Feed-size and contrast checks: letitedit-graphics section 6;
  placement away from faces and covered areas: letitedit-captions.

## 8. Land the move on the word and the sound
- **The ear forgives picture-early more than picture-late.** In listening tests viewers notice sound ahead of the picture by
  about 45 ms and sound behind it by about 125 ms [STD: ITU-R BT.1359-1 detectability; ATSC's recommendation is tighter:
  sound no more than 15 ms early or 45 ms late]. So land the visible event on the word's onset or up to about two frames
  *before* it; never a frame after.
- **Recogniser word times are estimates**, good to about a frame or two. For a hit that has to look synced, check the
  onset on the sound (`letitedit_hear`, `letitedit_check_audio`), and take a sound effect's peak time from
  `letitedit_assets` so the peak, not the file start, meets the contact frame [GEN].
- **Prepare, then hit.** Get the scene's structure ready about six frames before a line starts; reveal each new fact on the exact
  word that names it; several events can land inside one line [PRACT: iart; OURS].
- **A hit has three parts:** wind-up (3-6 frames), contact on the word, settle (spring or follow-through). Sound goes with
  contact. A whoosh or riser builds before its target and peaks on the transition midpoint, cut or reveal; the tail
  may follow. Use the sound skill's peak-alignment rule and source, not the file start as the sync point.
- **On music**, hits and cuts go on the beat or the bar (letitedit-sound owns the grid); lower effects under speech without moving their hits.

## 9. Code-drawn pictures when there is no footage
`M.draw` holds the parts that took the code-drawn explainer the longest to get right [OURS]: people with arms that
reach and faces that blink and talk, walkers whose planted feet do not slide, typed signs, a red X, a wipe, a camera
that never shows an edge. Use them or write your own. Art, props and acting are the scene's own work each time.
- A character acts the line: the arm reaches the thing named, the head turns toward it, the mouth moves on the words
  (`speak`), a blink every 3-4 s. A figure that stands still while the words describe an action reads as a mannequin.
- Walkers: advance `x` by 1.5 leg lengths per phase cycle (leg is 38% of the height), or the feet slide.
- Limits seen: the people are plain (big heads, simple limbs), so give them scale and staging rather than close-ups.
- Where `letitedit_image` can draw, a still plate or a character sheet can carry the art and code the movement: push or pan the plate 2-4%,
  write on its blank signs, draw the arms on an armless figure (letitedit-graphics, references/images.md). Where nothing can draw, all of it stays in code.

## 10. Checks the AI runs on its own frames
Looking is cheap: `letitedit_code_scene(look, times=[...])` accepts any seconds, so sample *around* each event (frames
before, on and after) as well as across the scene, then `letitedit_check_range` on the export. Fail the scene on any:
1. **Slide test.** Take a mid-scene frame: could it be a corporate slide as is? Does it have a world behind the text? Rewrite.
2. **Dead stretch.** Frames 0.5 s apart that are identical (the look flags frozen scenes only when the whole scene is still).
   Add drift, light or a camera move; allow a stillness only as a chosen resolution (under 1 s).
3. **Collision.** Two text elements, or text over the previous exit, on any frame; check the frames where one leaves and
   another lands.
4. **Pop.** An element at full strength on the frame after it was absent, with no hit sound or hard cut.
5. **Same move.** List each entrance's curve, length and direction; three alike in a row, or every title identical, is a template tell.
6. **Wrong weight.** Overshoot on rigid things, none on playful ones, bounce on body text, linear arrivals.
7. **Everything moves.** On a contact strip at 3-frame spacing across a move, more than about a third of the elements
   changing together, or a background as lively as the hero.
8. **Edge or gap.** A frame at each camera extreme: no black, transparent or plate edge showing.
9. **Strobe.** Frames one apart showing a shape jumping by more than about 8% of the width.
10. **Off the word.** The event frame against `letitedit_words`: later than the onset, or more than about 0.15 s early.
11. **Unreadable.** Text still moving when it should be read; shorter than its reading time; contrast fails at feed size.
12. **Flat.** Every layer moving at the same speed; no atmosphere in front.
13. **Dead ending.** The scene stops with nothing leaving or handing back; the last second is the same as the one before.
Then fix the single worst fault first and look again; a first draft is rarely the one that reaches the bar.
