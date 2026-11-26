# Look: Flat Explainer (made with code, no footage; not approved)

Style: made with code. Flavour: a voice explains one thing while a run of illustrated places acts it out, each one busy, each one
built for the line being said. The person gives a topic. Everything else is your call, and nobody is asked anything.

## What the viewer sees
- A new place every 2 to 4 s: a street, a workshop, a classroom, inside a machine. Never a diagram on a plain background.
- People and things in that place doing what the line says: the arm reaches the thing named, the head turns, the crowd reacts.
- Life behind the action that nobody needs to read: far-off people, birds, steam, a passing van, a flag in the wind.
- Words that belong to the place: painted on a sign, chalked on a board, lit on a screen in the scene, typed on as they are said.
- Now and then, a big moment: one bold headline on flat colour, a red X crossing out a wrong idea, a counter climbing.
- A camera that is never still, a hard cut when the idea changes, and a bold paint-like wipe between large sections.

## What makes this Look this Look
The explanation is acted, not presented. If a frame could be a corporate slide, or the words could be taken away and leave a plain
backdrop, it has failed. **The bar is "an illustration of a real place with a lot going on", not "tidy clip art".** Avoid rows of rectangles, bean-shaped heads and thin, empty distance.

## What it works from
`letitedit_looks(action='inputs', project=project, inputs='read')` gives the boxes. Nothing is asked of the person, at any point.
- **about** is the topic, and any facts the person gives. It may be one line. Choose the angle yourself.
- **voiceover**: their voice is the narration, `letitedit_words` on it gives the times, and the video runs its length. Never the
  microphone. Empty: write the script and read it with `letitedit_voice`.

## Nothing false (read this before the script)
Never put an unsupported number or ruler into a diagram. Check every factual label against the supplied material and verified sources; do not invent precision.

## The story
Open by turning over something the viewer assumes, acted out literally. Then, as far as the length and the facts allow: why it matters;
the subject shown and named; where it came from; its parts arriving one at a time; a short turn into "how?"; the mechanism acted out in two or
three places; what it leads to, with people reacting; a twist that returns to the opening; a last line that hands the viewer a question.
- That's the long version, for a minute or so. **At 15 to 20 s, keep three moves:** the upended assumption, one mechanism, the return to the opening.
- A request's length comes first. Otherwise let the facts you could support set it.
- About 3 words a second. Write the shot table for yourself in `story_plan.json` (nobody approves it): time, line, place, what acts, the word it lands on.
- **Every cut, sign and gesture lands on a real word** from `letitedit_words`. A repeated word has to be found by which occurrence it is, or the cut lands on the wrong line.

## Making the places rich
`letitedit-motion` section 9 has the craft for people, and section 7 for typed text. What took a first round to a good one, so you don't need a note for it:
- **Each place is specific to this line.** Four to six depth planes, one low light, shade on every shape, long shadows, and busy far planes. A plain row of shapes is the clip-art tell.
- **Use a place at most twice in a video.**
- **People are the weakest part so far.** Draw them in the same medium as the place, not as stick limbs on a bean head: side views, seated, from behind, a pose that suits the scene. Everyone in frame moves; a figure standing still while the line describes an action reads as a mannequin.
- **The thing the line is about is the largest, clearest thing in its shot.** In a crowd, the one who does the action is bigger or brighter, apart from the rest, with a short trail or glow. If a viewer can't find the subject in the first half second of its shot, raise it or clear the others. Small figures at the edge of a place are scenery: they don't carry a line.
- **A wipe is a thing, not a colour.** Wipe with something drawn in this world (a swarm, a brush of paint, a paper tear) that reveals the next place from the first frame on; a plain flat colour held for more than a few frames reads as a blank slide.
- **A sign is never empty while the viewer can read it.** Start typing near the top of its shot, or lose the sign.
- **Everything in the picture has to read at once.** If what you've drawn needs its label to be understood, redraw it.

**Drawing kits are optional.** `M.look.flatVector` may suit this well: it paints crisp outline-free shapes with planes, grain and long shadows. `letitedit_motion(action='hands', block='flatVector')` gives its guide. It's a suggestion. Invent another way of drawing if this topic wants it. The kit gives a finish, never a picture, and the people and subjects are yours either way. `letitedit_motion(action='hands')` lists the others.

**Where something on this PC can draw** (`letitedit_image(action='status')`), a still plate can give the place while code gives the camera, words and moving parts; `letitedit-graphics`, `references/images.md`, says how. Nobody approves a picture. Where nothing can draw, all of it stays in code, and the video still finishes.

## Motion and words
- Camera always moving, a few percent over a shot, and never showing a plate's edge. Arrivals have weight (they bounce, squash or burst into place) and never fade up.
- Typed letters: use the numbers in `letitedit-motion` section 7, and hold a line long enough to read after it settles.
- **No captions and no word-by-word subtitles.** Words live on things in the world. A headline on flat colour is the only text outside it, a few times a video at most.
- **A frame's shape gets its own layout.** A wide video uses wide places. A tall (9:16) one stacks the place upward, with larger people and signs on two or three lines. Don't crop one into the other: the signs and the subject get cut off.

## How it's built
- No footage folder, so the project goes in the person's Videos folder: `<Videos>\letitedit\<a short name>\<a short name> - first cut.mlt`, made with `letitedit_project_new`.
- One `letitedit_code_scene` the whole length, with every shot a function of time.
- Check your own work before any export: `look` at a frame from every shot, then either side of each cut, each sign and each arrival. Fix empty boards, overflowing text, stray numbers, covered faces, frozen stretches and plate edges. Then look at the export's frames.

## Sound
Voice as above; no voice clean-up on a voice this PC made. Music under it, about 11 LU under the voice, written or real at your own call. Small effects placed by their peaks (`letitedit_assets`): a soft click on typed signs, a whoosh on wipes, a pop on arrivals, a hit on the red X. Finish at -14 LUFS.

## The first-cut stages
There is no footage to log. Story: `story_plan.json` (for a Short, `deliverables.short` as usual) and `pickups.md`. Rough: the script read by the voice and the scene drawn, with `render:<a frame sheet from the look>`. Fine: `fine_pass.md`. Finish: `finish_pass.md`, with the claims and their sources.

The brief: `mode: tutorial`, `look: flat-explainer`, `narration: ai voice ok` (or `own voice`). `must_keep` holds only words the person quoted. `claims` holds exact names and figures.

## What it needs
A topic: a "why does this happen", a "how does this work", a what-if or a true story. There is no footage to give; it's offered only on the no-footage path. It suits a subject that has places and actions in it. A purely abstract one (a tax rule) gives you little to act.

## Must not
- No captions, floating interface panels, code editors, glass cards, checklists, emoji, or any channel's logo or frames.
- No shot held still longer than a second, and no character who doesn't move.
- No fact, figure or date without a source, spoken or drawn. No sign, X or word over a face, even a drawn one.
- No questions, and no approval asked for the topic, script, shot plan or any picture.

## How it's judged (the review reads this)
By design, not faults: no captions; text only on things in the world; a hard cut every 2 to 4 s; simplified drawn people; a bold wipe between sections; a voice from this PC with no clean-up.

Faults to find, with the time:
1. **Any figure, date, name or claim, spoken or drawn, that the person's words and the sources in `finish_pass.md` don't support.** The worst fault, and it includes numbers on props.
2. A shot that reads as a slide or tidy clip art: a plain backdrop, a row of shapes, nothing happening behind the action. A place used more than twice.
3. A figure standing still while the line describes an action. A frame with no movement for over a second.
4. A sign that's empty on screen, words too small to read on the frame's shape, or typed words still moving when they should be read.
5. A cut, sign or gesture that misses its word by more than a few frames. Something popping on with no hit behind it.
6. A plate's edge or black gap in view. A wide layout cropped into a tall one.
7. A picture that doesn't read without its label.

## Weak spots

- Vertical layout support remains unverified; build for the requested frame rather than cropping a wide composition.
- Detailed drawing and revisions can be expensive. Do not promise a fixed production time.
- Without web search the facts are only what the person typed, so a one-line topic may make a short, general video.
