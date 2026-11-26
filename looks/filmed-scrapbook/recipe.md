# Look: Filmed scrapbook (made with code, no footage)

Style: made with code. Flavour: a short told over one scrapbook page, with the person's own pictures taped on it, one unbroken
camera move, and a voice. It is not a documentary: no interviews, no filmed footage, no archive. 9:16 first. If it can't be told from what the person gave, say so rather
than filling the gap: this look makes things read as proof.

## What the viewer sees
- One page, never a cut, no slide change. The camera drifts from print to print, pushes in, pulls back to travel, and at the
  end pulls back far enough to show the prints together.
- One hero for each line of narration: a print of a real picture (taped, a little tilted, with a shadow), or one very large
  word. Everything else falls back for about a third of a second as the hero changes.
- A thin route line draws from print to print as the camera travels, so the move reads as a path. A pen rings or marks the thing
  the line names, on the word.
- The page is alive the whole time, not a still sheet with a camera over it, and the view is never bare paper (see "The page is alive").
- No word-by-word captions and no caption track in the project, even an unseen one: the review doesn't ask for it, and it makes the player
  draw masks. A phrase appears on screen once, or is said, not both: the hero words and the voice carry it. With the sound off the story should still mostly read.

## What makes this Look this Look
Everything lies on one surface and moves with one camera, so the viewer never feels a slide change. The person's pictures are
real and look real; everything else is drawn and looks drawn (paper, cut letters, pen). Nothing pretends to be a document, a source
or a date. A beat with no picture on it is the Look's weakness, not its plainness to be proud of.

## The page is alive
A person watching should feel a real page in a real room being worked on, filmed by someone. A camera sliding over still paper reads as calm to the point of plain. This
is your decision on every video; the things below are examples, not a list, and something you invent for this story beats all of them.
- **Always moving, a little:** paper and film texture that shifts frame by frame, dust drifting through the light, a soft light or a shadow travelling across the page (a window's
  light, a hand's shadow passing), the page's light warming or cooling as the story turns, a corner of a print lifting and settling.
- **Answering the words:** a print pressing down pushes dust out and nudges its neighbours, tape tears and smooths on after it, a word said hard gives the page a small knock, the pen
  leaves a scribble or an underline in the margin, the music's lift brings the light up. Give each beat at least one thing that happens because of what was just said.
- **Never bare paper:** at every moment the view holds a print, or most of one. Put the prints close enough that the next is in view before the last has gone, and shorten the travel
  rather than speeding it. Between prints the paper carries things that belong to the story's world, drawn and looking drawn: pencil lines, a torn corner, a pressed leaf, a coffee ring, the route line.
  Check it in frames: sample every half second, and move anything that leaves the view mostly empty.
- **Behind the hero:** all of it sits behind or around the print the line is about, and is lower in contrast than that print. Moving texture keeps off the people in a picture where it can: dust
  and light may pass over a print only at a strength that leaves the picture as it was, and go round a face unless the person or the moment calls for crossing it. If it pulls the eye off the hero, it's clutter: turn it down or take it out.
- **Words stay out of it:** this is texture and movement, not more to read. No extra labels, memos or text that asks to be read.
- **Cheap to draw:** bake textures once and move them, a few tiles of grain rather than per-pixel work, dust as under a couple of hundred small dots from `S.rng`, nothing random per frame.
  Run time should barely change; if a look at one frame gets much slower, you've built something too heavy.

## What it works from
`letitedit_looks(action='inputs', project=project, inputs='read')` gives the boxes. Nothing is asked of the person, at any point.
- **about** is the only source of facts, with the words of a `voiceover` and what the `show` pictures plainly show. Look at every
  picture yourself before writing a word: `letitedit_look(items=[<every show path>])` returns a sheet of them in its reply, labelled, and works on
  any AI. Note what each one actually shows. Don't stop because a look is slow: wait for it. Don't write about a picture you haven't seen.
- **show**: these become the prints. Use each one, or record why not (`unused={path: reason}`). A browser can't draw every format:
  a `.heic` or similar becomes a JPEG in the project's side folder first (the app's `ffmpeg`), and the original stays where it is.
  A file that isn't there or can't be read (a Drive file that won't download, say) is left out with its reason, and the hand-over says so.
- **style**: look at them for colour, paper, line and mood, then choose your own. They never appear, not as a print, a texture or a
  background, and their motifs don't either unless the story calls for them.
- **voiceover**: their voice is the narration; `letitedit_words` on it gives the line times and the video runs its length. Never
  the microphone. Empty: write the script and read it with `letitedit_voice`.
- **Empty show box:** draw the things you can draw honestly (`M.look` hands, `letitedit_image` if it can draw), mark them as drawn by
  how they look, and never make them pass for a photograph or a record of what happened.

## Nothing false (the strictest part)
- Every sentence has to come from the description, the voiceover or a picture. Don't add a figure, date, name, place, cause or
  quotation because it sounds right, however sure you are of it. A true outside fact the person didn't give is still left out,
  because nobody here can check it. If the description is thin, make the video shorter.
- No invented sources, mastheads, letterheads, dates, signatures, file numbers or "archive" labels. A stamp says only what the
  narration supports (FIXED, because the person says it was fixed). Body text on paper is soft grey lines nobody tries to read.
- A picture that doesn't look like its line (a pale road for "dusk") is not retouched into proof, and its colours stay its own. Word the line for what the picture shows, or let the
  page's own light carry the mood around it. Say in the hand-over what picture would do it better.
- A pen mark claims something: ring only what the line names, what the picture really shows there, and only where a viewer would otherwise not know which thing is meant. When the whole
  picture is the thing (a road, a view), no ring; it would be a mark for its own sake. Rings on about half the prints at most: other marks can do the rest (a tick, an underline in the margin). Never ring or mark a person's body:
  a red circle on someone's shirt or chest reads badly, whatever the line says. A feeling like "home" has no place to ring; leave it unmarked or use the stamp.
- Before you record a voice, write every factual claim in `finish_pass.md` next to where it came from. Cut any that has no source.
- Keep tape, rings, words and veils off a face in a picture where they can sit elsewhere, and don't crop through it. Let that print stay
  the hero until it moves off, or choose the moment the camera has moved past it to dim it.

## The beats
Write the beat table for yourself in `story_plan.json` (nobody approves it): time, narration, the one hero, any on-screen word, the
spoken word it lands on (from `letitedit_words` of the voice, never estimated).
- Read the script aloud in your head before the voice: no phrase said twice, unless the second time is the point and it's different enough to tell.
- One idea per line, 2 to 4 s a line, about 2.5 words a second. Let the description and the number of
  good pictures set the length; a request's length comes first.
- A line with a picture gets a print. A verdict may be one big word and a pen mark, but no more than one beat in five.
- Choose each print for its object. If a line needs a picture you weren't given, rewrite the line so it says what you can show.
- First print down inside the first half second. The last beat is a stamp or one word on a blank slip, then under half a second of hold.
- A print is pressed down on a word of its line and its mark lands on the noun. It fades in as it drops, never pops on one frame:
  `const q = S.lay(t, t0, dur, from); card.draw(g, {pose: q, alpha: q.alpha})`. A slip or word from an earlier beat is gone by the next hero, not lingering at the end.
- Type a phone can read in one second: a hero word is at least a fifth of the frame's width, labels are never tiny. Rings at least
  8 px wide at 1080 wide.

## Camera
- One move through one key per beat that doesn't slow to zero between keys (`M.world.path(keys, t)`, not `M.camera`, which eases to a stop
  at each key), with a slow sway of a few pixels and nothing random. During a hold it keeps drifting the way it is about to go.
- Zoom about 1.0 to 1.1 on a hero, about 0.7 at the end. Use motion blur only where motion actually needs it.
- **The page is always bigger than the view.** Size the page from the camera's path and the frame's shape, and test it in code, with
  any sway added to the margin: `M.world.offPage(keys, page, c.w, c.h, pxPerWorld, fps)` must come back empty (`console.error` what it finds, and
  the fast look lists it as a problem).
- A wide (16:9) video is its own layout, not the same page: a wider page, prints in a row or side by side so two share the frame (one
  portrait print on a wide frame leaves it half empty), the camera moving along it. Don't crop or stretch a 9:16 layout.

## How it's built
- There's no footage folder to sit beside, so the project goes in the person's Videos folder: `<Videos>\letitedit\<a short name>\<a short name> - first cut.mlt`.
- One code scene (`letitedit_code_scene`) the whole length, on a project made with `letitedit_project_new`, so it plays live and the
  normal Export draws it. `M.look.scrapbook` is the page's hand (read the file in `read_also`, which `letitedit_looks(action='get', id='filmed-scrapbook')` lists); another hand or
  your own drawing is fine if the story wants a map, a desk or a board. A real picture goes in as a whole `file:///` address in the scene's code, one string per picture.
- A card's face is baked the first time it is drawn, so load the pictures first: `const P = M.world.pictures({subject: 'file:///...'})` at the top
  of the script, outside `M.block`. In the frame function, `if (!P.done) return;`, then make the hand and the cards once, from `P.images.subject`.
  A picture that can't load is listed by the look.
- `S.print` is centred on its x and y and crops to fill, so give each card its picture's own shape: a wide picture on a tall card loses its
  sides, and perhaps a face. `M.world.back(heroes, id, t)` says how far a thing has fallen back. `S.ransom` centres a word with `cx` in place
  of `x`. A blank slip under a stamp lands no more than 0.2 s before it, or it reads as an empty box.
- Check your own work before any export: `letitedit_code_scene` look at a frame from every beat, then frames either side of each print
  landing and each camera move. Fix anything cluttered, hard to read, overlapping or stopping dead. Then a mid-beat frame of every print at phone size.

## Sound
- Voice as above; no voice clean-up on a voice this PC made. Music under it, about 14 LU under the voice, written or real at your own call,
  fading in over 1 s and out over 2 s. One soft thud (about -16 dB) as each print presses, one firmer hit on the stamp, peak on the frame.

## The first-cut stages
There is no footage to log: the log stage needs no files or note. Story: `story_plan.json` (with its beat table and, for a Short,
`deliverables.short` with `selected_story_s`, `length_reason` and `payoff_line`, the exact closing line of your script; set the length from the voice once it is read, not from a guess) and `pickups.md`
(a line for what a better picture would add). Rough: the script read by the voice and the scene drawn, with `render:<a frame sheet from the look>`.
Fine: `fine_pass.md`, how you retimed lines and marks. Finish: `finish_pass.md`, with the claims and their sources. New hook candidates
don't apply: the opening is the first print. A one-line "why" on the scene is enough for its clip.

The brief: `mode: creative`, `look: filmed-scrapbook`, `narration: ai voice ok` (or `own voice`). `must_keep` holds only words the person
quoted and wants said; your summary of the story goes in `purpose`, because a must-keep is checked word for word. `claims` holds exact names and
figures from their description.

## What it needs
A description and, far better, 4 to 8 sharp pictures that each show one clear thing. Blurred or samey pictures make a weak video, and
no picture makes a drawn one rather than this one.

## Must not
- No cuts, no slide changes, no word-by-word captions.
- No invented fact, source, date, signature or masthead, and no drawing passed off as a photograph or record.
- No `style` picture on screen. No mark over a face that could sit beside it. No page edge in view.
- No extra stamps, memos or labels. Texture and movement are welcome; things that ask to be read, or pull the eye from the hero, aren't.
- No questions, and no approval asked for the script or the beats.

## How it's judged (the review reads this)
By design, not faults: one continuous camera and therefore no cuts and no long-hold limit; no captions; a voice from this PC with no clean-up;
drawn paper, route line and rings; texture, dust, moving light and small things reacting on the page. The hero changes every 2 to 4 s; that is this Look's rhythm.

Faults to find, with the time:
1. A beat with no picture that reads as a text card, more than one in five, or a run of them.
2. A print that doesn't show what its line says, a ring off the thing it names or with no reason to be there, any mark on a person's body, a phrase said twice.
3. Any page edge in view; a stretch where the view is nearly bare paper; a stretch where the page just sits still under the camera; noise that competes with the hero or crosses a face it could go round; a hero not readable on a phone within a second; a slip lingering after its beat.
4. A move stopping dead, jerking, or a print popping on.
5. Any fact not in the description, voiceover or pictures (the review has the person's words, under `look_inputs`), any invented
   document or date, any drawing that reads as a photo, a face covered where the mark could sit beside it (not a cover the person asked
   for or the moment calls for). Facts are the worst of these.
6. A mark that misses its word by more than a few frames.

## Weak spots
- The pictures carry the story. The pictures carry it, and weak pictures show.
- Detailed drawing and revisions take time; do not promise a fixed production duration.
