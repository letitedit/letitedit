# Generated pictures: when, how many, and how to make them move

`letitedit_image` draws with whatever on this PC can draw. `action='status'` says who, and it may be nobody. The plate-and-sheet approach is a creative starting point [GEN].

## 1. Image or code?

The video always finishes. Pictures raise the look; they are never what the video depends on. Decide per picture, ask nobody.

| Draw it with | When |
|---|---|
| **Code** (`letitedit_code_scene`, `letitedit_graphic`, `letitedit_motion`) | it moves in its own parts, must be read exactly (words, numbers, charts), must land on a word, or `status` shows nothing that can draw |
| **An image** | a rich place, a person or object with real detail, a texture or style code draws poorly: anything that would look like clip art in code |
| **An image, with code on top** (the usual answer for an explainer) | a still plate gives the world; code gives the camera, the text, the moving parts and the timing |

Nothing can draw, or the maker runs out part way (`made` below `count`, or `route: none`): keep going in code for the rest, without
stopping, and tell the person once at the end what was drawn in code and why. A mix is fine; match the palette so it doesn't show.

Text in a generated picture is unreliable, and an image can't be corrected without another run: leave signs and screens blank
in the image and write on them in code.

## 2. How many

A picture is a place, not a shot. **One picture per place, reused** across every shot there with a different crop, push or pan.
A separate pose only when the action can't be drawn with the sheet you have. Rough numbers for a 60 s explainer with a new shot
every 2-4 s: 6-12 places, 1-4 characters. Part 1's estimate of 25-35 was for one image per shot, and reuse needs far fewer; we
haven't measured a whole video at this count.

Time is the real cost: 30-60 s per picture, three at once. Each call takes up to 6 (`count`), a few minutes at most. Make what
the plan needs in one early pass, before the scenes. Each variation is another full picture, so ask for more than one only when you'll
truly choose. Images use the person's allowance 3-5x faster than other turns (OpenAI's words) and have limits of their own we can't
see; 24 pictures moved the weekly gauge by under a point once.

## 3. Plates to animate over

Ask for an **empty** place: straight on, no people, open floor, nothing cut off at the frame's edge, blank signs and screens. Then:
- Push or pan it in code, 2-4% a shot, so it's never a still. Give a plate room: a wide image pushed 4% still has to fill the frame.
- Use `url` from the reply as the image's address in a scene (`img.src = url`). letitedit copies it beside the scene's page, so
  it works in `look`, the live player and the export. Any other way of naming a file on disk fails in the export.
  The plain way is a page element: `const i = M.el('img', {}, stage); i.src = url;`, sized to the frame and moved with `M.set(i, {s: zoom})` in
  the frame function. A canvas works too, if it is added to the stage and the picture has loaded before it draws; a canvas left off the
  stage is what "the scene is blank" meant in one real run [OURS].
- Write the words onto the blank signs in code, and light or colour over it with code.
- Characters go on as separate pictures with transparent or green backgrounds, and move in code.

**Size.** The tool's own route usually gives 1672x941 or 941x1672 whatever the words say (the reply gives the real size), so a full-frame plate on a 1920x1080 video scales up
about 15%, and a 4K video about 130%. The reply gives `scale_to_fill`, and `fit_path`, a smooth copy at the video's size for the timeline.
Flat art takes this well; a photo-like plate softens, so don't push it close. An API key gives exact sizes up to 3840.

## 4. Characters

- **Make a sheet first:** `character='Mara'`, words asking for front, side and back on a plain background. Words alone drift
  (shorter scarf, other shoes, younger face), but a sheet held for 8 of 8 shots [OURS].
- **Attach the sheet on every call**, by name (`characters=['Mara']`; the tool also attaches it when the words name her). **Never chain from the
  last scene:** by the third step a chained woman became someone else, and the same words with the sheet were right [OURS].
- Two characters in one picture stayed themselves from two sheets (one try). Three references (person, prop, place) held too (one try). The limit is 5.
- For a character who gestures a lot, ask for no arms on plain green: code draws the arms (letitedit-motion section 9). Everyone else: the exact pose.
- Transparent backgrounds are real on the program route (seen at 1024x1536 and 941x1672). Plain green (#00B140, nothing green on anyone) can be keyed
  in code as a fallback. There's no ground shadow either way, so add one in code or she floats.
- An edit (`edit=<id>`): say exactly what changes and what stays. "Change only the scarf" kept 97% of the change inside it (one try).

## 5. People and honesty

- **Never generate a real person,** the person in the video or anyone else: no likeness, no "looks like", no reference photo of them,
  even when asked. OpenAI's Usage Policies bar someone's likeness without their consent. Invent characters. A real person's picture comes from real footage.
- An image is an illustration, never proof that something happened (section "Honest" above). Don't make a fake document, screenshot or news photo.
- AI-made pictures owe a line: `letitedit_export_job` and `letitedit_review_bundle` list it. Tell the person and put it in the description.
  OpenAI's sharing policy asks for a clear label and that a person reviews what's shared. The person has the last look; say which shots are AI-made.

## 6. If you are Codex and drawing yourself

The tool draws nothing for you: its reply gives the words, the reference paths and a request id. Draw with your own `image_gen__imagegen`
in `exec`, with the first-line `@exec` directive for 120 s, and `generatedImage(result)` to see the picture; without that call you see
nothing and may think it failed. One call, one picture. Then `letitedit_image(action='file', request=...)` files it beside the video
and gives back the same details as any other route.

## 7. If you are Antigravity and drawing yourself

The reply gives the words, reference paths and a request id. Draw with your own `generate_image` (`Prompt`, `ImageName`, `AspectRatio`, `ImagePaths`
up to 3), one call per picture, then `letitedit_image(action='file', request=...)`. It gives JPEGs of about 1 megapixel (wide 1376x768), so
below full HD; it has no transparency, and its flat green isn't exact, so a key has to allow for that. A reference image kept the same invented
woman, and "change only the scarf" changed only the scarf (one try each). On a free Google plan 7 pictures locked it for about a week, and a limit
shows only as the tool failing: go on in code, and say which shots are plainer.

## 8. Generated-picture b-roll (letitedit-graphics section 6)
For generated-picture b-roll, `letitedit_image` tries permitted Antigravity first; its absence or the person's
other-AI switch being off is not consent to install or enable it. Continue through the available routes, or make
a scene in code. Give a still a restrained push-in or parallax, tied to the line, rather than a static hold. Keep
generated and stock illustration provenance in the report, not labels over the picture. 
