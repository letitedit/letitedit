# The real object in a scene (letitedit-graphics device 4b)

Read before lifting an object out of its shot or marking one in place.

**The real object in a scene.** When the line is about one solid thing, nothing else makes the viewer look at it the way lifting it out of its shot does: the
room falls away, the thing itself hangs there, and the drawing explains it. It is the real object, so it stays evidence that the drawing around it isn't. Nobody
needs to ask for it: use it when all of these hold [OURS]:
- The words name one thing and say something about its shape, size, a part of it, or where it goes.
- The shot shows it sharp, whole and fairly still for the moment you want, and it keeps its shape and shows one side. `letitedit_object` refuses the rest and says why;
  then use a pointer, a freeze and label, or a drawn version.
- Its explanation fits on it in two or three labels. If it needs more, it needs a proper scene or a cut to the work itself.
Not for: something the person is using, where the hand and the action are the point (leave the shot alone); a thing the viewer already understands; more than a couple of times in a
video (repeated devices are counted, letitedit-graphics section 5); the same lift twice for two objects in a row.
Steps and fields: letitedit-layers section 6. The scene behind it follows letitedit-graphics' Scenes made with code, and the moves follow letitedit-motion. **Mind the hold (letitedit-motion
sections 2 and 10):** a rigid thing holding still for 6 s reads as a dead stretch unless something new arrives. Land something every couple of seconds or cut the pause in the speech,
and don't lift it for longer than the explanation takes. Lift it off on the word just before the point, so the thing is there when the word is said.

**Marking an object in place.** To say "this one" without leaving the shot: `{vfx: {effect: object, params: {object, show: outline}}}` (or `glow`, `recolour`) on a track above the
footage, from the same id. Darken the rest with `{op: adjust, below: <that track>}`. It holds its edge better than a ring, and costs more: when a ring would do (device 4), use a ring.
