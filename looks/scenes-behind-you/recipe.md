# Look: Scenes Behind You

Style: talking head, Shorts/Reels/TikTok (9:16). Flavour: the wall behind the person opens and a world drawn for this video
plays out behind them, full size and in front, while they talk. The "magic" option.

## What the viewer sees
- The opening line, in the real room for only a second or two. Then, on that line's strongest word, the room parts behind the person's head and a world is there.
- One continuous world, not a run of pictures. It moves like a camera travelling past it, and it changes because something happens in it.
- Things keep happening, each on the exact word that names it, and a stranger with the sound off can point at each one and say what it is. The scene answers what the person is saying. The viewer wonders what comes next.
- At the end the world closes the same way it opened, and they get a last beat in the real room.

## What makes this Look this Look
Keep the world busy and responsive to the named things, calm on the person, with effects kept off the face where they can. Three things decide whether it works:
1. **The thing they say is the thing you see, on the word.** Get word times first (`letitedit_words`, per word) and write a beat list before any code, in the story plan's `visual_decision`: `word -> what appears, that a stranger could name -> what it does`. A noun gets the thing itself. A list gets one thing per item, each arriving on its own word. A number gets a count, a claim about growth gets something that grows, a fear gets the disaster actually happening. Say it plainly first: reach for a metaphor only when it's clearer than the thing and still reads muted. Something new and nameable about every 2-4 s, several inside one sentence when the sentence names several things. The world gets ready about 6 frames early and the thing lands on the word. What still matters carries on into the next beat instead of being redrawn. Changing one object's shape or brightness doesn't count as a new thing: a viewer can't tell what it means.
2. **One world that keeps turning.** One place and one drawing style, with something the viewer gets to know if the video has one (a small character who reacts, an object that returns). Change it because the camera or the world moves, never by fading between cards. When the thought turns, the place turns with it, by a camera move or a change of light and colour, so a frame from each part of the talk looks different. A backdrop that barely changes for 20 s has failed, however good it looks.
3. **Real depth.** Far background moves about 0.1-0.3 times the camera, middle layers 0.5-0.7, foreground 1-1.5. Add a thing passing behind the head: nothing sells the person being in the world like being hidden by them for a moment.

## How to invent it
Write it fresh for these words. A video about something else should not get this world, and don't settle for the first symbol of the subject repeated over and over. Turn each line into something happening. For a baker's video, say: on "the oven died" an oven coughs smoke and a little door falls off; on "three hundred loaves" loaves stack up and a counter spins; on "my sister" she walks in and waves; on "rising prices" a price tag climbs a ladder. Those are for a baker: yours come from your words.
A drawn chart, a drawn screen, icons and a few words are welcome when they belong to a thing and move on the words: the name arriving in big letters as it's said, a sign, a chat bubble, an axis on a line that climbs. Keep them drawn, so nobody takes them for a recording. What doesn't work is a still card, a list to stop and read, or the caption's words repeated in the world.

## Where things go
The person hides most of the frame. On a full-size talking head only the two strips beside the head (about 290 px each at 1080 wide), the band above the cap (about 250 px) and the area above the shoulders are visible. Measure them on a frame. Put every event there.
Never put a road's vanishing point or anything important behind the head, except on purpose for a pass behind it. Keep the bright thing away from the face so the eye isn't pulled off them.

**Compose the world to the room around this person's outline.**
- **One big shape fits the outline.** An arch from shoulder height at both frame edges over the cap can use both side strips and the band above. Adapt the shape to this person rather than laying level layers whose events vanish behind the neck.
- **Leave air around the outline.** Keep brightness outside a dark margin rather than pressing it against the head.
- **Its events are big enough at phone size.** Each is one thing in a strip or the band, seen whole, not a small object that the head half hides. The thing of the moment fills its place: most of a strip's width (about 200-290 px on a 1080-wide frame) or most of the band above the cap, and it's the biggest, brightest thing in the world while its words are said. Props of 60-120 px read as specks on a phone. Check on a frame at feed size that the eye finds it.

**Measure, then draw.** `letitedit_code_scene(behind_person=true)` replies with `behind_person.room`: the top of the person, the head's width and where the shoulders start, in frame pixels, measured on their cut-out. Before there is a cut-out, read the same things off a frame. Write the world's main curve and its positions from those numbers (a person who sits lower or off centre gets a different world), then look with the person in front and `revise` if the shape doesn't follow them. This is how the Look composes; what the world is stays the video's own invention.

## Captions
Big enough to read over a busy world without competing with it: see `letitedit-captions` for talking-head shorts. A calm world doesn't mean quiet captions.

## Colour
The first Look's rule: the accents come from this video's environment. Measure this video before choosing a colour (sample the room as in step 1 of `looks\big-letters-behind-you\recipe.md`) and write the measured colours into the plan. No colour here or in a sample carries over to another video: that is why this recipe gives no colour codes. A warm room and a blue beach need different palettes.
The dark of the sky and a cold opening can depart from the room's colour on purpose when that colour is also in the video. A warm world also suits warm room light on the speaker's face; a cold one looks pasted on, so keep any cold stretch short.

## How the AI makes it
- **`letitedit_code_scene(create, behind_person=true)`, one call.** It places the scene on its own track and the person's cut-out on a track above it, one piece per clip, over exactly the scene's seconds, in one Undo. The scene is already there? `revise` with `behind_person=true` adds the person. Placing pieces by hand gets the same picture and only adds room for pieces out of step. The scene is transparent until it opens, so the real room is underneath.
- **Look at it with the person in front of it, after every change.** Check opening brightness and avoid hard-edged clip-art rays.
- What took it from clip art to a picture: light drawn small and scaled up (no hard edges on rays or beams), the picture itself added back faintly as a glow, a little film grain, ridges lit along the top and falling into haze, and fog between the layers.
- Way in: a shape behind the head, opening outward (here, two doors parting from the centre with a line of light on their edges, 0.5 s). Way out: the same in reverse, starting after the last word.
- Sound: a low hit on the opening, a riser into the big change, a whoosh for the thing passing, about 9 dB down. The music stays low until the world wakes, then comes up about 13 LU under the voice. Add effects after captions and the music mix (see Weak spots).

## What footage it needs
A steady talking head who stays roughly in place, with a clean outline. Hands and fast movement are untried. It costs about 40 s of matte making per second of video the first time on this PC (cached after that).

## Must not
- No shrinking the person into a box or a blurred border: in this Look they stay full size, in front of the scene.
- Don't open it on the first word: a second or two of the real room first, so the change is an event. Not much more: the opening line's strongest word is where it opens.
- It's an illustration, never proof that something happened.

## Weak spots
- Drawn, not photographic: it reads as a rich illustration. The speaker's recorded lighting may not match the drawn world, especially when its lighting changes.
- One clip, one world; another subject needs a new invention, which costs real AI effort. Sound is unheard.
- The busy strips sit close to the speaker's shoulders, so a lot of the action is small. A tighter or more central speaker leaves even less room.
