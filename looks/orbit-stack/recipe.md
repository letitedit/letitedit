# Look: Orbit Stack

Style: talking head. Flavour: a commercial for a piece of software. The person stays on screen and talks, while cards cut from a real recording of the software float
around and behind them, and words and callouts land on what they say. 9:16 first. They give the recording once, and nobody is asked anything after that.

## What the viewer sees
- The person, in their real place, natural, tightly cut. They are always the anchor.
- **Cards from the real recording, with the software moving in them:** dark or muted rounded panels playing a real stretch of the recording (a clip being cut on the timeline, a reply arriving in the chat, a note being drawn), not a still. A card that only shows a picture of the software is the weakest use of this Look. Each card is big: at least about 40% of the frame's width on a 9:16, so what moves in it can be followed at phone size. They drift beside the person; **at least one really passes behind the person's head and comes round in front of their shoulder or body**, so they feel in the same space as them: the "orbit".
- Short punchy phrases in bold geometric type, landing on the words that matter.
- Rounded pills naming a feature or a step, as it's named.
- A little light abstract shape or sparkle in the product's colours, only where it moves with an event (bursting when a card lands, say). **Nothing decorative stays on screen for the whole video, and nothing a viewer couldn't explain:** a ring, dot or line that sits in one place for seconds reads as a stray mark. If it isn't a card, a phrase, a pill or a mark on the thing being named, it goes.
- Now and then a brief full-screen moment of the software in use, when the line calls for it, then back to the person.
- Something visibly from the product, or a strong phrase, in the first 1 to 3 s.

## What makes this Look this Look
The viewer sees the real product, sold by a real person, in one space. Plenty is going on around the person, and nothing on them. Everything graphic takes its colour from this product, so no two videos share a palette. It must feel like a commercial, but **everything it shows and says must be true of the software.**

## What it works from
`letitedit_looks(action='inputs', project=project, inputs='read')` gives the boxes. Nothing is asked of the person, at any point.
- **The footage folder is the talking head.** It's the timeline: cuts, graphics and pace follow its words. If the recording is in the folder too, it isn't a talking head: never cut it in as one.
- **product** is the recording, and maybe screenshots or a logo. Look at it before you plan a card: `letitedit_look`, with a frame sheet across its whole length. Note what each stretch really shows.
- **about** is optional, and holds the product's name as it's spelled and anything else they wrote. Use their spelling in every caption and graphic; a speech recogniser will get it wrong.

A person with no footage isn't offered this Look, and it can't start without a recording, because the box is required. A recording that can't be read (a Drive file that won't download, say): don't invent one. Make the video from the person, type and pills, and the hand-over says so plainly.

## Nothing false (the strictest part)
- **Never invent the interface.** No drawn or generated screens, buttons, dashboards, charts or results that stand for the software. A card's picture always comes from the recording or their screenshots. `letitedit_image` may make only abstract shapes here, and nothing that shows the software.
- **Every claim comes from what they said, what they wrote or what the recording shows.** No invented numbers, speeds, savings, prices, customers, reviews, logos, guarantees or awards. A pill names only a feature that's said or shown. Write each claim in `finish_pass.md`, with where it came from.
- **A mark claims something.** A ring or arrow on a card sits on the thing named, and that thing is really in the frame.
- **Don't let a loop lie.** Cutting out a wait or speeding up a loop to make it read is normal, unless the line is about speed. When it is, play that moment at its real speed.
- **Check for private things in the recording:** an email address, a name, a key, a customer's data. Pick a different moment or crop it out. In a full-screen moment where you can't, blur it (`{vfx: {effect: blur, source, params: {box, at}}}`).

## The person
- **Graphics stay off the face where they can.** Don't colour-grade the person to match the recording: a screen's colours aren't lighting, and pulling skin towards them looks ill. Leave their picture natural. A mic in shot stays.
- A step closer on an emphasis point, as in the Clean recipe (no more than about 1.2 times). Keep it when graphics are up too, unless it crowds them.
- Cut tighter than a relaxed talking head: dead air, fillers and false starts go. Cut in the room tone, measured on the sound, as Clean says.
- **Keep clear of the mouth and face at every moment,** not just most of them. Anything in front of the person stays below the chin and clear of the hands when they matter. A graphic that needs that space moves or waits.

## Colour
Measure from this video, never carry one over from a sample. Sample the recording (its main hues, its strongest accent, how warm it is) and the room, and write the colours into the plan.
- The strongest accent goes to moving type and callouts. Dark or neutral tones from the product go behind card content, for contrast. Everything else generated takes its colour from the same few.
- Readable first: if the accent can't be read over the room, use a darker panel behind it. If the recording is grey or low in contrast, keep to a clean high-contrast treatment made of what's there, rather than adding an outside colour.

## Choosing the moments
Get word times (`letitedit_words`, per word) and go through the speech for claims, benefits and features named. Each gets at most one graphic event, at the word or just after.
- A viewer can follow one new thing at a time: a card arrives, or a phrase lands, not both at once. Let what's already up drift quietly.
- Keep at least some stretches with only the person and one quiet card, or the commercial reads as noise. The first thing cut is whatever depicts nothing the line says.
- **A recording is usually wide and the frame tall,** so a whole screen in a card is unreadable on a phone. Crop to the one area the line is about, and test that it reads at phone size. If the line needs the whole screen, use a full-screen moment.

## How it's built
**The stack, bottom to top:** footage, scene behind, the person's cut-out, clip in front, captions. Build it in that order, because each new track depends on what's already there.
- **Behind:** `letitedit_code_scene(create, behind_person=true)` holds the cards, shapes and sparkle that pass behind. Its reply gives `behind_person.room` (top of the person, head width, where the shoulders start): compose from those numbers, and put the orbit's path around this person's outline as Scenes Behind You describes. A first matte takes tens of seconds per second of footage.
- **In front:** moving type, pills and anything that passes before them go in a rendered clip with a see-through background, not a second scene. First `{op: add_track, name: 'Cards in front', kind: video}`, which adds it on top, then `{motion: {block: 'custom', script, duration}, len}` on that track, at the same time as the scene. A rendered clip should play the same in the live player and the export. **Don't use `letitedit_code_scene(create, track=<a new name>)` for this:** a new scene track goes just above the bottom track, under the person. An orbit is its back half in the scene and its front half in the clip, on the same path and with the same start time, so a card can go behind them and come round. Changing the clip means rendering it again, so settle what it does with previews first.
- **A card's picture, moving:** the simplest way to show the software moving is a clip of the recording on its own track: `{op: insert, track, at, item: {clip, in, out, effects: [{size_position: {keys: ...}}, mute]}}`, with `size_position` keyed so the card drifts along its path. The app's `ffmpeg` can cut the clip to the one area the line is about and round its corners first (`{ffmpeg: "..."}` on the clip, or a made clip). **Track order is what puts it behind or in front:** a track between the footage and the person's cut-out is behind them; a track above the cut-out is in front. One card can be two clips on the same path and clock, one on each side, handed over where the card is off the person. Nothing has tested this stack; look at frames around the hand-over. A code scene can't play video, only pictures, so for a card inside a scene a short loop is a run of stills (8 to 12 a second, each chosen by `t`); that's the second choice.
- **Full-screen:** the recording itself on a track above everything, unrounded, for a moment that fills the frame. **Always mute any clip of the recording.** A cutaway above the person hides them, so keep it brief.
- **Depth:** drawn on a 2D canvas: size, softness and speed change with distance. No 3D engine needed. Drawing kits are optional: `letitedit_motion(action='hands')` lists them, and none is expected here.
- Look with everything in place after each change, around each event: frames before, on and after. Then frames of the export, to compare with what `look` showed.

## Captions
Caption the speech in one calm style, as in Clean, using the product's spelling (`letitedit_caption_fit`). Captions draw over everything, so keep cards and moving phrases out of their band, and place the captions themselves clear of the person's hands and mouth where they can go (`letitedit_caption_fit` measures hands; use its answer, and tell the review what it couldn't clear). A phrase in big type is said at the same moment as the caption shows it; that's accepted here because it's the Look's main device.

## Sound
Clean the voice with the default `{fix: {kind: voice}}`. Music under it, about 15 LU under the voice and with more drive than Clean, written or real at your own call, fading at the end. Sound effects punch graphic entrances and the big cuts, about 9 dB down, peak on the frame, never over a word that matters. The recording's own sound stays out.

## The first-cut stages and brief
The usual stages. The brief: `mode: product`, `look: orbit-stack`, `claims` holding the product's name as spelled and any exact claim. `finish_pass.md` lists every claim and its source.

## What it needs
A talking head who stays roughly in place, about this software, with a clean outline. A recording of the software doing the things they talk about: 15 to 60 s of clear moments, with large enough type to be read cropped.

## Must not
- No interface, result or screen that isn't in the recording. No invented number or testimonial.
- No graphic over the face or mouth where it can sit elsewhere. No grade on the person taken from the recording's colours. No recording sound.
- No personal data from the recording on screen. No sped-up loop under a claim about speed.
- No questions, and no approval asked for anything.

## How it's judged (the review reads this)
By design, not faults: tighter cuts than other talking heads; moving type and pills; a palette that comes from the recording rather than the room; cards covering the room; a brief full-screen cutaway without the person; big phrases said as they show.

Faults to find, with the time:
1. **Anything on screen standing for the software that isn't in the recording, or a claim not said, written or shown.** The worst fault. The review has what they gave under `look_inputs`, and that names the recording: look at it.
2. **A graphic over the face or mouth, even for a moment, or a tinted, dimmed or graded person.** As bad.
3. Private data readable in a card. The recording's sound audible.
4. A card nobody can read at phone size, or a card that isn't about the line being said.
5. A graphic late for its word, or more than one thing arriving at once. Moving type colliding with a card or caption.
6. Too much at once: no quiet stretch in the whole video, or so little that it looks like the Clean Look with a card on it. **A card that is only a still, or is too small to follow what moves in it.** **Any ring, dot or line that stays in one place for seconds and means nothing.**
7. A card that pops, jerks, or stops dead; a picture from the front and back scenes on different clocks; a seam around the person.
8. A wrong spelling of the product's name.

The measured check doesn't confirm that a `product` file was used, because it only lists `show` files, so the critic has to look.

## Weak spots
- Use larger moving cards, with one visibly passing behind the head; no stray rings or dots. Check the complete layered motion, not just a still.
- **The live player may differ from the export,** because it draws a scene over the picture and takes out what's above it with masks. The export is what counts; say so when it's different.
- Loops as a run of stills add files to a scene, and it's unknown how far that can go before it slows the live player.
- The look depends on what the recording shows. A plain or text-heavy tool gives dull cards, and a tall speaker in a tight frame leaves little room.
