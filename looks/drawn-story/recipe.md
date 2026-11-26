# Look: Drawn Story (made with code, no footage; not approved)

Style: made with code. Flavour: a story told by a voice over a comic or a storybook that the AI draws for this one story, with the
camera diving out of the page into full-frame moments and back. 9:16 first. The person tells the story. Every drawing call is yours, and nobody is asked anything.

## What the viewer sees
- A page that's clearly made by hand for this story: comic panels with gutters, or a painted storybook spread. You choose which, or something
  of your own that does the same job. A storybook whose big moment bursts into comic panels is fine.
- **Close moments.** The camera pushes into a panel or picture until it fills the frame, and the moment plays out there, full size and alive, then the camera pulls back
  or travels to the next one. A page turn or a jump to a new page marks a real change of time or place.
- The same character throughout, recognisable at a glance, acting every line.
- More going on than the story needs: rain in the next panel, a neighbour at a window, a cat that keeps turning up, a sky that changes as time passes.
- One thing that returns (an object, a gesture, a phrase), so that the ending feels earned.

## What makes this Look this Look
The drawing is the world, and the page is what holds the world together. It must never read as pictures fading into each other with a voice on top. Story comes before richness: a lovely drawing cannot carry no story. Use rich, busy drawing rather than simple clip art; **a panel that isn't the hero still has something moving in it.**

## What it works from
`letitedit_looks(action='inputs', project=project, inputs='read')` gives the boxes. Nothing is asked of the person, at any point.
- **about** is the story. It may be a full telling or one line.
- **voiceover**: their voice is the narration, `letitedit_words` on it gives the times, and the video runs its length. Never the microphone. Empty: write the script and read it with `letitedit_voice`.

## True or made up
Decide this first, from what they wrote. Don't ask.
- **Made up** (they say so, or it's plainly a fable or a premise with no claim that it happened): invent freely, including names, events, dialogue and an ending.
- **True** (they say so, or it's told as something that happened: "my", "we", real names, real places): every event, name, date, figure and quotation comes from their words. Don't add any because it sounds right. Dialogue in a balloon or a line of narration may say only what they wrote, or something plainly general ("It was a long night", if they told you it was). You may draw the setting, the weather and the small things around it, because a drawing is plainly a drawing, but nothing that changes what happened. If the telling is thin, make the video shorter.
- **Either way:** no invented documents, sources or "based on a true story" labels. A figure, date or name appears on a drawn prop, a sign or a calendar only if the story gives it. A real person is never drawn to look like themselves: draw a character. A drawing never passes for a photograph or a record of what happened.

## The story
One change, one payoff, one returning thing. Write the beats for yourself in `story_plan.json` (nobody approves it): time, line, what's on the page, the cutaway, the word it lands on.
- The character wants something in the first line. The ending pays that off, and the returning thing comes back in the last beat.
- One idea a line, 2 to 4 s a line, about 2.5 words a second. On a video of 15 to 20 s, that's about 6 beats. A request's length comes first; otherwise the story sets it.
- **Something changes every second.** A held panel still has weather, a blink, a slow camera. Silence and stillness are for one chosen moment at most.
- Every panel landing, balloon and gesture lands on a real word from `letitedit_words`.

## Drawing it
- **The character is one function.** Features, proportions and colours are decided once, and every shot calls it in a new pose. Never redraw them from scratch in each panel. If they look different in beat 5 from beat 1, the viewer loses the story.
- **Acting.** Character faces change with the line, with heads turning and arms reaching for what's named (`letitedit-motion` section 9). Draw them for the shot: from behind, small in a wide landscape, huge in a close-up.
- **The page is always bigger than the view,** so no edge shows when the camera's on it. `M.world.path` moves without stopping at each key, and `M.world.offPage` tests that the view stays on the page.
- **Comic:** panels of different sizes, not a grid of equal boxes. Something breaks out of a panel at the peak. Drawn sound words may land on a real hit.
- **Storybook:** a painted place that fills the spread, with paper showing at its edges. Layers move at different speeds inside it, so the picture feels deep. A line or two of hand-lettered text is fine.
- **Words on the page are few.** A balloon has a few words and is read in the time it holds (`letitedit-motion` section 2). No word-by-word captions. Letter in the page's own hand, and say a phrase or show it, rarely both.
- **Frame shape.** Tall: stack panels down the page and move down it. Wide: panels or a spread side by side, moving across. Don't crop one to make the other.

**Drawing checks:**
- **An action is acted with the body.** Walking is legs that alternate with weight, a knee that bends, a foot placed on the step before the body follows; climbing on is a hand on a rail and a foot up. Never stand in for an action with a fade, a shrink or a see-through character. If you can't draw the action convincingly, stage it instead: cut on the start of it and show the result, show it from behind or from far away, or let something else in the frame (a door, a shadow) say it.
- **Faces have three or more states** (neutral, speaking, reacting) and change on the word: brows move, eyes look at what's named, the mouth opens on the line, a blink every two or three seconds. A face that holds one expression through a beat reads as a mask.
- **A prop that carries the story has to read from its outline alone.** Draw it large on a plain ground first and look: if someone could name it as something else, redraw it. A mitten is a flat shape with a thumb gap and a cuff, not a ball on a stick.
- **A balloon says what the voice doesn't:** a sound, a thought, a picture, or nothing. Never put in a balloon the words the voice says in that beat.
- **Fill the frame.** Crop each panel to its action; no large empty or unlit band across an edge (a dark dashboard, bare ground). A big dark area is a bad crop.
- **Keep the whole character in view unless a close-up is the point.** Before a camera move is final, look at its first, middle and last frame and test that the character's bounds sit inside the view; a character cut by the frame edge while still talking is a fault.

**Drawing kits are optional.** `letitedit_motion(action='hands')` lists what's on this PC. A kit's marks (paper, ink, wash, print dots) are slow to get right from nothing, so one may help, for example a folk-tale hand for a storybook or a halftone hand for a comic. They are suggestions. If this story wants a look nobody listed, invent it. That stays a full choice, and two stories shouldn't come out looking alike. A kit gives a finish, never a picture: the characters and scenes are always yours.

**Where something on this PC can draw** (`letitedit_image(action='status')`), a still background can give a richer place, with code giving the panels, character motion, camera and words (`letitedit-graphics`, `references/images.md`, including its character sheets). Nobody approves a picture. Where nothing can draw, all of it stays in code, and the video still finishes.

## How it's built
- No footage folder, so the project goes in the person's Videos folder: `<Videos>\letitedit\<a short name>\<a short name> - first cut.mlt`, made with `letitedit_project_new`.
- One `letitedit_code_scene` the whole length, on one camera.
- Check your own work before any export: `look` at a frame from every beat, either side of every cutaway, and at phone size. Fix a character who changed, an unreadable balloon, a dead panel, an edge in view. Then look at the export's frames.

## Sound
Voice as above; no voice clean-up on a voice this PC made. Music under it, about 14 LU under the voice, written or real at your own call, following the story's one change. Small effects for the page and the drawn world: a page turn, the hit behind a sound word, rain in the panel with rain.

## The first-cut stages
There is no footage to log. Story: `story_plan.json` (for a Short, `deliverables.short` as usual, with its `payoff_line`) and `pickups.md`. Rough: the script read by the voice and the scene drawn, with `render:<a frame sheet from the look>`. Fine: `fine_pass.md`. Finish: `finish_pass.md`, saying whether you took the story as true or made up, and, if true, where each fact came from.

The brief: `mode: story`, `look: drawn-story`, `narration: ai voice ok` (or `own voice`). `must_keep` holds only words the person quoted; a summary of yours goes in `purpose`.

## What it needs
A story, from one line up: who it's about, what happens, how it ends, and whether it really happened. There is no footage to give; it's offered only on the no-footage path. Someone wanting drawings around themselves talking has Scenes Behind You.

## Must not
- No pictures fading from one to the next with no page, camera or event joining them.
- No character who changes between beats, or who stands still while the line describes an action.
- No invented fact in a true story, in the voice, a balloon or on a prop. No drawing passed off as a record. No real person's likeness.
- No word-by-word captions. No balloon or word over a drawn face where it can sit beside it.
- No questions, and no approval asked for the story, the script or any picture.

## How it's judged (the review reads this)
By design, not faults: no captions; a single continuous camera with few detected cuts, so the cut-rate and long-hold checks are off; plainly drawn people; a voice from this PC with no clean-up; invented detail in a made-up story.

Faults to find, with the time:
1. **In a story told as true, anything in the voice, a balloon or a prop that the person's words (under `look_inputs`) don't support.** The worst fault. A likeness of a real person is as bad.
2. A character who looks like someone else later on.
3. A stretch of a second or more where nothing changes, or a panel that's a still picture with a voice over it. A stretch that reads as a slide show.
4. A story with no payoff: nothing returns, the ending just stops.
5. A balloon or lettering that can't be read in its time at phone size, or that sits on a face.
6. A panel, balloon or gesture that misses its word by more than a few frames.
7. A page edge or empty background in view, or a move that stops dead or jerks.

## Weak spots

- Believable acting from code is hard, and a story depends on it more than an explainer does.
- Check character consistency across poses. Drawing and revisions can be expensive; do not promise a fixed production time.
