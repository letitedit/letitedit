## What makes a drawing-kit Look
The person chose this medium for this one video. That is all the choice means: the marks and the paper are settled, and everything else is yours. A kit gives a finish, never a picture. It has no story, no characters, no places and no timing in it. What the viewer should come away with is this video's subject, seen through a real medium, not a demonstration of the medium. If the subject wants something the kit doesn't have (a camera move, a drawn sign, a bit of a different mark), write it in the scene. The kit's guide is in `read_also`, which `letitedit_looks(action='get', id=<this Look>)` lists; read it in full before drawing anything.

## What it works from
`letitedit_looks(action='inputs', project=project, inputs='read')` gives the boxes. Nothing is asked of the person, at any point.
- **about** is what the video is about. It may be a full telling or one line.
- **voiceover**: their voice is the narration, `letitedit_words` on it gives the times, and the video runs its length. Never the microphone. Empty: write the script and read it with `letitedit_voice`.

## True or made up
Decide this first, from what they wrote. Don't ask.
- **Made up** (they say so, or it's plainly a fable or a premise): invent freely.
- **True, or about the real world:** every event, name, date, figure and quotation comes from their words, or from a page you opened and read during this run. Don't add one because it sounds right. If the facts run out, make the video shorter.
- **Either way:** no invented documents or sources. A figure, date or name appears on a drawn prop only if it is supported or the story is made up. A real person is never drawn to look like themselves. A drawing never passes for a photograph or a record of what happened.

## The video
- The story, its shape and its length are your call; a request's length comes first. Something a viewer wants to see the end of, and an ending that pays it off.
- About 2.5 words a second. Write the beats for yourself in `story_plan.json` (nobody approves it): time, line, what's drawn, what moves, the word it lands on from `letitedit_words`.
- **Something changes at least every second:** a mark going down, a character acting, weather, a camera. A beat that's a still picture with a voice over it has failed, however nice the picture.
- **Everything reads at phone size within a second.** If what you've drawn needs its label to be understood, redraw it. Hold the subject large; a medium's texture is no reason to make it small.
- **A character is one function:** decided once, called in a new pose each shot, and acting what the line says. It must be the same character at the end.
- **Words live in the drawing,** in the medium's own hand, few and large. No word-by-word captions and no caption track. Say a phrase or letter it, rarely both.
- **A frame's shape gets its own layout.** 9:16 first: stack the place upward. Wide: its own wide layout. Never crop one into the other. No edge of a plate or sheet in view unless the sheet is the point.

## How it's built
- No footage folder, so the project goes in the person's Videos folder: `<Videos>\letitedit\<a short name>\<a short name> - first cut.mlt`, made with `letitedit_project_new`.
- `letitedit_code_scene` for the whole length, one scene or several, with the kit called by its full name as the guide shows.
- Marks that are seen going down are the charm of most media and the slowest thing to draw: bake once, and move what's finished. Keep a big full-frame mark from running through every shot.
- Check your own work before any export: `look` at a frame from every beat, then frames either side of each change, then at phone size. Fix a character who changed, a dead stretch, unreadable words, an edge in view. Then look at the export's frames.

## Sound
Voice as above; no voice clean-up on a voice this PC made. Music under it, about 14 LU under the voice, written or real at your own call. A few small effects that belong to the drawn world, placed by their peaks. Finish at -14 LUFS.

## The first-cut stages
There is no footage to log. Story: `story_plan.json` (for a Short, `deliverables.short` as usual, with its `payoff_line`, the exact closing line of your script) and `pickups.md`. Rough: the script read by the voice and the scene drawn, with `render:<a frame sheet from the look>`. Fine: `fine_pass.md`. Finish: `finish_pass.md`, saying whether you took it as true or made up and, if true, where each fact came from. New hook candidates don't apply: the opening is the first picture.

The brief: `mode: creative`, `look: <this Look's id>`, `narration: ai voice ok` (or `own voice`). `must_keep` holds only words the person quoted; your summary goes in `purpose`.

**In Turbo:** the kit stays, on small pictures with few marks and no full-frame fill. The rules for facts and faces stay too.

## Must not
- No invented fact in anything true, spoken or drawn. No real person's likeness. No drawing passed off as a record.
- No word-by-word captions. Words, balloons and marks stay off faces, drawn ones too, where they can sit beside them.
- No questions, and no approval asked for the script, the beats or any picture.

## How it's judged (the review reads this)
By design, not faults: no captions; few detected cuts where one camera carries the video, so the cut-rate and long-hold checks are off; plainly drawn people; a voice from this PC with no clean-up; invented detail in something made up.

Faults to find, with the time:
1. **Anything told as true, spoken or drawn, that the person's words (under `look_inputs`) and the sources in `finish_pass.md` don't support.** The worst fault. A likeness of a real person is as bad.
2. A picture that doesn't read at phone size within a second, or that needs its label.
3. A second or more where nothing changes, or a run of still pictures with a voice over them.
4. A character who looks like someone else later on, or stands still while the line describes an action.
5. Nothing to see the end of, or an ending that just stops.
6. A mark, gesture or word that misses its spoken word by more than a few frames. Words that can't be read in their time.
7. A plate's edge or empty background in view, or a move that stops dead or jerks.
8. A finish that doesn't look like the medium this Look names (see its own list above): the person chose it, so if it reads as smooth vector with a name on it, that is a fault.

## Weak spots of every drawing-kit Look
Each has been made on one made-up story, with one voice, at one effort. Whether people act believably in code is still the hard part. A kit's marks cost time: a full-frame fill runs long at its first draw.
