# Look: You + Visuals On Top

Style: talking head, for Shorts/Reels/TikTok (9:16) and YouTube videos (16:9). Flavour: the person sits low in the frame, in a window onto their real room, and
a paper panel above draws what they're talking about as they name it. The "explain it" option.

The sections below describe the Short. When the request's `Format:` is YouTube video, read "On a YouTube video (16:9)"
near the end as well: where it differs (layout, structure, captions, sound, vertical footage), it wins. The drawing
rules (timed to the word, one idea at a time, truthful) hold in both.

## What the viewer sees
- Top part: a light panel with one simple drawing at a time, which builds piece by piece on the spoken words.
- Lower part: the person, about 85% size, in a rounded window with the head breaking out over its top edge. Nothing blurred, nothing behind them but the real room.
- Captions on the chest, inside the window, clear of the chin.
- It reads with the sound off: you could follow the idea from the drawings alone.

## What makes this Look this Look
The drawing is timed to the sentence. Nothing is there before the word that names it (the eye should get it as the ear does).
Each piece that lands is a word the speaker actually said, so the panel adds understanding, not decoration. One idea on the panel at a time: when the idea changes, the old drawing leaves.

## How to choose what to draw
Read the lines and ask what shape each idea has.
- A process or who-does-what: boxes and arrows ("The LLM drives the software, you direct").
- Two things or an order: stacked blocks ("a software that's AI first": AI lands on top of software).
- A problem: a little picture of it ("Editing is the reason most people quit": a wall called EDITING, people walking up to it, most dropping, content creation out of reach beyond).
- A name: the words, big, one at a time on the words ("LET IT EDIT").
- Show a verb as an action: on "edits" a clip is cut from a small timeline and the rest close up.
Two or three drawings in 15 s. Fewer words in the drawing than in the sentence. If there's nothing to draw for a line, hold the last drawing.

## It's truthful
Draw concepts, not evidence. Never invent a number, a chart, a screenshot or a result. "Most people" shows most of the little figures dropping, with no count and no percentage. If a claim needs proof, leave it out or put it on the person's list to supply.

## Layout (1080x1920)
- Person: 0.85 size, 918 px wide, 81 px margin each side, top of the picture at y 505, so eyes sit about y 1100, chin about y 1440.
- Window: x 81 to 999, top edge at y 970, near the eye line, rounded corners, running off the bottom of the frame. Below the head, nothing of the person's body goes past the window, because the source's edges are the window's edges.
- Drawing area: y 150 to about 720. Beside the head you can use down to about y 940 at x below 300 and above 780. Keep out of the top 120 px and the right-hand 96 px where the apps put buttons.
- Words in drawings no smaller than about 50 px, boxes no thinner than about 130 px tall. Captions at about 60 px centred at y 1536: a caption can wrap onto two lines around that point, so leave room above it for the chin and below it for the phone's bar (y 1620).

## Colour
The first Look's rule, turned around, measured from this video (sample the room as in step 1 of `looks\big-letters-behind-you\recipe.md` and write the measured colours into the plan; no colour carries over from a sample, which is why this recipe gives no colour codes): the paper is the near-white of the room's hue, ink is the room-drop dark, accent is the room's accent (filled, with dark text on it). Accent is too light for text on paper, so accent words use a deeper version of the hue. A warm brass room gave a cream paper and amber; a blue beach would give a cool paper and a blue accent.

## How the AI makes it
- Three stacked layers: the main clips, resized and moved (`{size_position}`); a code scene over the whole video, opaque paper with a hole cut for the window, drawn from the playhead; above it the person's cut-out (`{vfx: cutout}`) with the same size and position, so the head comes out over the paper.
- All the timing is one list of word times at the top of the scene (`letitedit_words`, per word). Boxes pop with a small overshoot, arrows draw themselves, labels rise in.
- Sound: soft ticks on what lands, about 14 dB down, a light rhythmic track about 15 LU under the voice.
- **Don't use `caption_fit` on this layout:** it can't tell that the paper is a bad place for captions, and with the face and the phone apps' covered areas ruled out, the paper is the only room left. Set the captions' `position` by hand.

## What footage it needs
A steady talking head with headroom. Lines that have a shape: lists, processes, comparisons, a problem and its answer. A purely emotional story has nothing to draw, so choose another Look.

## Must not
- No blurred border or stretched background around the person; nothing on the face.
- Nothing appears before it's said (the panel itself excepted). No slide-deck bullets. No two ideas on the panel together.
- No made-up numbers or results.

## On a YouTube video (16:9)
A wide frame has room beside the speaker, so the drawings move there and the person stays full size. Everything not
named here stays as above.
- **Layout: full frame, the drawings beside.** The person is never shrunk or put in a window on a YouTube video. Find
  the face on frames across the clip (`letitedit_footage`, `letitedit_check_frames`). When the free side of the frame
  (from the face box plus a margin of half a face width to the frame edge) is at least about 35% of the width, the
  paper panel sits there: a rounded card on that side, from about 8% to 80% of the height (the caption band below
  stays clear), never over the face box or its margin, built over the real room. A hand that gestures behind the card
  is fine; the face never is. When there isn't that room (the speaker centred), a drawing is shown as a
  full-frame cutaway of paper for that one idea while the voice carries on, then back to the speaker: a few seconds,
  not minutes. A punch-in that moves the face to one third (1.0 to 1.2 times, as in the Clean Look) can make the room;
  never a smaller picture or a blurred border. No cut-out is needed: nothing comes out over the panel.
- **Structure.** A few sections, each one idea, a `chapter:<name>` marker at each turn (`letitedit_bin`): YouTube
  builds chapters from a description list that starts at 0:00, has at least three entries and gives each at least
  10 s [YT]. A section's drawing builds piece by piece as in the Short and is cleared when the section turns. A
  cold open on the strongest line or the result in the first seconds, so the first 30 s deliver what the title
  promised, then one plain line on what the video covers [YT-hook]. Keep it as long as the material, never padded [RES-Guo].
- **How many drawings.** About one drawing per idea, not a quota per 15 s: on a long video the panel holds a built
  drawing while the person explains it and changes when the idea changes. Stretches with nothing to draw stay on the
  full-frame person with no empty panel. The mix of the person's face with drawings is what holds viewers better than
  pictures alone [RES-Guo]; words go next to the part they name and land when they're said, with fewer words than
  the sentence [RES-Mayer].
- **Sizes at 1920x1080.** Words in drawings no smaller than about 40 px, boxes no thinner than about 90 px tall, lines
  at least 4 px; keep drawings inside the central 90% of the frame [RES-EBU]. A drawing that can't be read at that size
  in the panel needs fewer parts or the full-frame cutaway.
- **Captions.** Burned in, calm, low in the frame below the panel's bottom edge, about 46 to 52 px [OURS], the bottom
  line's baseline about 8% above the bottom edge, one or two lines of up to 42 characters, at most about 20 characters
  a second [GEN-Netflix]; `chunk: 'sentence'`. Over a full-frame drawing, captions keep the same place. Set the
  position by hand, as in the Short. Also write an SRT beside the export, for search and translation (uploaded as
  YouTube captions as well, it would double the burned line when a viewer turns captions on).
- **Sound.** Soft ticks only on the pieces that matter most, not on every box over minutes. Music about 15-17 LU under
  the voice, dropping out under a dense explanation and back at a chapter turn. Export at -14 LUFS / -1 dBTP.
- **Colour** follows the same rule as the Short (measured from this video's room); the panel's paper is opaque so the
  drawing reads over any room.

**Vertical clips on a YouTube video.** A phone held upright gives a 9:16 picture. Cropping it to fill a 16:9 frame
would cut the head or chin and soften it; shrinking it or framing it in a blurred copy is never done. This Look has a
good answer: the clip at full height on the left or right third, never smaller than full height, and the panel in the
rest of the frame. Say in the hand-off that the clips were vertical and that the same material also makes a Short.

**Evidence for this section.**
- [YT] YouTube Help, "Video chapters": timestamps listed from 0:00, at least three, each chapter at least 10 s
  (platform rule; strong). https://support.google.com/youtube/answer/9884579
- [YT-hook] YouTube Help, "Measure key moments for audience retention", Intros: YouTube measures the share of
  viewers still watching after the first 30 s, and advises that those 30 s match the expectation the title and
  thumbnail set (platform guidance; medium).
  https://support.google.com/youtube/answer/9314415
- [RES-Guo] Guo, Kim and Rubin (2014), "How video production affects student engagement", ACM Learning at Scale:
  6.9 million viewing sessions; videos mixing the speaker's face with slides held viewers better than slides alone,
  hand-drawn tablet explanations better than slides, and engagement fell as videos got longer (large observational
  study of lecture videos, not creator videos; medium).
- [RES-Mayer] Mayer, Multimedia Learning (2nd ed., 2009): spatial and temporal contiguity (words beside the picture
  they name, shown as they're said), segmenting and coherence (one idea at a time, nothing extra) (a body of
  controlled experiments on learning; strong for learning, applied here to attention).
- [RES-EBU] EBU R 95, "Safe areas for 16:9 television production": graphics inside the central 90% of width and height
  (broadcast standard; a reasonable margin for a web player whose controls cover the bottom when shown).
- [GEN-Netflix] Netflix Timed Text Style Guide (English): up to 42 characters a line, two lines, up to 20 characters a
  second for adult programmes (industry practice; strong for subtitles).
- [OURS] the 35% free-side threshold, sizes and caption size are starting points to adjust by eye, not measured results.

## Weak spots
- It's the least "magic" of the four, and looks closest to a slide if the drawings get wordy.
- The person is 15% smaller: less intimate than the full-size Looks.
- Only one clip. Every video needs its diagrams worked out from what's said; the AI's taste in diagrams is untested on anything else.
- Sound is unheard.
