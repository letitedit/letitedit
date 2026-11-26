---
name: letitedit-graphics
description: The 'explain this clearly' pass and on-screen design for a letitedit edit - for each key claim or step a proving shot, a detail crop, a freeze-and-label, an arrow or ring that follows the object (letitedit_annotate), a step label, a matched before/after, a simple diagram or map, or an honest missing-footage note; illustration kept apart from evidence; titles, lower thirds (names and roles) and chapter cards; restraint with effects and transitions (straight cut by default, dissolves and cards for time, stylised moves only with a reason, repeated devices counted); every graphic checked at feed size. Use when an edit explains, labels, titles or styles anything, or on notes like 'less flashy' or 'I couldn't see what you meant'.
metadata:
  version: 0.2.0
---

# Graphics: explain clearly, label honestly, style with restraint

**The decision:** for each thing the viewer must understand, the most honest device that shows it, and which devices
to leave out. **Inputs:** the brief (`mode`, `claims`, `must_keep`, `audience`, `feel`), the story plan (key claims,
steps, sections), the log and selects (which shots prove what), the Look (`letitedit_looks(action='get', id=...)`).
Elsewhere: jump-off points, time passing, the repetition ledger (letitedit-craft); placing and spelling words
(letitedit-captions); the first frame (letitedit-shorts); how a scene moves (letitedit-motion); track order and aiming
an effect (letitedit-layers). How-to defaults here are [GEN]; explanatory text clarifies the story, never merely
decorates it [OURS]. Read by pointer: calls, references/devices.md; generated pictures, references/images.md; stock,
references/stock.md; a lifted or outlined object, references/object-in-scene.md; why each rule holds, worked examples and tool
details, `references/manual.md`.

## 1. The explain pass
- **A Look's graphic kit first** (graphic-kit.json): place its frozen families with letitedit_learn(action='kit_plan'),
  never redraw them; the new video's words fill its slots (a reference's acronym, headline or topic diagram is content,
  not style: a content-shaped device only when the new video's own words naturally need it); its speech/explanation/CTA
  hierarchy and measured rates take precedence over the devices below. After placement, kit_check measures every native
  rendered frame: any graphic ink
  inside a detected face box fails, even one pixel in one frame; missing measurement is not a pass; fix placement
  before export.
- **List** every key claim (brief `claims`, the plan), every step a viewer would copy, every "this", "here" or "that
  part" the speaker points at. Each gets the first device that works, most honest first:

| # | Device | Use when | How |
|---|---|---|---|
| 1 | Proving shot | the footage shows it clearly | the shot itself, landing before the line about it |
| 2 | Detail crop | the thing is small in a good shot | `zoom` effect, or annotate `magnify` |
| 3 | Freeze and label | it flashes past or needs naming | annotate `freeze`, or a `freeze` item and a label |
| 4 | Pointer that follows | the viewer can't find it in a busy frame | `letitedit_annotate` ring, arrow or box, `follow: 'track'` |
| 4b | The object, out of the shot | the line is about one solid thing whose shape, part, length or gap matters ("see this crack") | `letitedit_object`, `{op: lift}`, or outlined in place; before either, read references/object-in-scene.md in full |
| 5 | Step label or counter | the viewer must keep count | a label designed for this video, updated per step |
| 6 | Matched before/after | a change is the claim | same angle and framing, cut or side by side |
| 7 | Simple diagram or map | footage can't show how or where | a drawn graphic, labelled as one; `letitedit_map` |
| 8 | Missing-footage note | nothing honest shows it | say so; a pickup or a text bridge |

- Not: emotional lines (keep the face; never label a feeling), a poetic opening, a shot that already reads (a label on
  the obvious is noise). Check: every item has a device or a stated reason for none; a muted reviewer can say what each
  step was [OURS].
- **A lifted object (4b)** only when its explanation fits on it in two or three labels (more needs a proper scene or a
  cut to the work itself); not for a thing the person is using (the hand and the action are the point), a thing the
  viewer already understands, more than a couple of times a video, or the same lift twice in a row. The object stays
  evidence; the drawing around it is illustration. A rigid thing held still about 6 s reads as a dead stretch: land
  something every couple of seconds, lift it no longer than the explanation takes, and lift it off on the word just
  before the point [OURS].
- **The proof lands before the comment:** a new shot about 0.5-1 s before the line that judges it; tell-then-show or
  show-then-tell on purpose; cut to the example on "let me show you". Check each start against the line's first word
  (`letitedit_words(project=...)`) [ITE WOX-WdXSOOc 47:27; ITE 9jRZIqPQHm8 01:50; ITE hwecWg2IR18 03:59; GEN timing].
- **One idea per beat,** each with its own device and a little space; no label or diagram carries two new ideas
  [ITE pRpaqx_5jD8 04:59].
- **Plain words:** about a 5th-grade reading level, jargon defined the first time; read each label aloud: a ten-year-old
  would follow it [JH 3:55].

## 2. Illustration is not evidence
- Evidence is footage of this event (the actual part, fault, result or measurement); illustration is a diagram, an
  animation, a generic or stock shot, a shot from another day, a re-enactment. Never present illustration as proof:
  label a diagram as a diagram; "the same kind of part" is not the part; never show or imply a result the footage
  doesn't contain; counters and dates use real numbers. Check: each device's `why:` marker says `evidence` or
  `illustration`; the reviewer finds no illustration where a line claims proof [ITE KAO0n3C0kAg 12:09; GEN; OURS].
- **Missing footage: say so;** never cover it with an almost-right clip: `missing:<claim>: <the shot that would prove
  it>` in the journal and the hand-off, with a pickup (shot size, the action, a 5-8 s hold) or an honest text bridge
  (at most two short sentences) [ITE FOJhAl9IyPg 08:07; ITE WlS5f8Plyl0 18:00].

## 3. Making each device
- **Detail crop** inside the source's real resolution (about 1.25x on 1080p footage; 4K about 2x on a 1080 timeline),
  sharp and centred; repeated zooms count as a device (section 5) [GEN; ITE 4s7WdcyV1H4 05:32].
- **Freeze and label:** hold words / 3.5 + 0.5 s, at least 1.5 s; it stops time, so only the one moment that needs
  it, never inside a fast montage; `freeze=True` holds the frame while the sound runs on [GEN].
- **Pointer:** look at `letitedit_annotate`'s preview frames and lost ranges, then apply (`plan_id`, `apply=True`);
  after its clip is trimmed or moved, `letitedit_annotate(project, refresh=True, apply=True)`. One pointer at a time.
  Check: its measured check finds the pointer on the object in the rendered frames [GEN; letitedit_annotate].
- **Step labels and counters:** numbered the way the speaker counts; one place and one look; updated as each step
  completes; no promised step missing [JH 15:23; AOTC GNIP; OURS].
- **Before/after:** the same angle, framing and exposure (`letitedit_match_shots`), labelled, cut or side by side (a
  graphic with a `source` splits the screen); different angles are no fair comparison. Check: the two frames side by
  side share framing and exposure [GEN; FEP 4D].
- **Diagram or map:** few elements, labelled, built up one idea at a time, drawn for this video (`letitedit_graphic`
  `custom`, or an `{ass}` text layer); maps from clips' GPS or coordinates (`letitedit_map`) [GEN; AOTC MI; AOTC
  Porcelain].
- **Stock, code drawing, a made picture and the person's own footage are all open;** the choice is yours. Before using
  stock (`letitedit_stock`), references/stock.md; note each item's source (`letitedit_note`, tag `licence:<ref>`); never
  imply a person or brand shown endorses anything; if the tool isn't active, carry on with what's here without asking
  and mention it only if the person asks for stock [OURS].
- **Real pictures of named things: the default.** When the words name a real thing the viewer would recognise (an app
  or a logo, a person, a place, a book, a product, an animal, a food) and a picture would show it, get that exact thing
  with `letitedit_real_picture` before drawing anything: a made-up logo, cover or face reads as wrong [OURS; GEN]. A
  board: a matching screen recording or screenshot in the footage folder first, then a real picture of the named app
  or product, then stock, then a finished filled graphic; the same order inside code scenes (the code draws the
  container and movement, not a substitute for the content). Screenshot text readable, example clips big enough to see
  what they prove; an empty outline with a label is never a finished board; a made alternative has specific filled
  content and is clearly an illustration.
- **Fetch through the tool, never your own web tools** (a web fetch or shell download can stop an unattended run on a
  prompt). Before the first fetch, read references/real-pictures.md in full: which candidate, making a graphic from it
  (a logo's shape and colours kept, no AI changes to a real face), the credit line each picture keeps (`made_from` for
  a file you make yourself), non-commercial licences said plainly, and offline or nothing found. [OURS]
- **Fonts beyond the bundled ones** (`letitedit_fonts`; its ranking is a shortlist to pick from by eye): before a
  search, a match or a download, references/fonts.md. [OURS]

## 4. Titles, names and chapters
- **Lower third** (name and role, or place and date) the first time someone the viewer doesn't know appears, never again
  for that person; about 3-5 s, inside the uncovered area, off the mouth and the captions; not the channel's own host
  unless asked. Check: every new person has one at first sight, none twice [AOTC GNIP; GEN].
- **Chapter and title cards** at real turns (a new step, day or place), landed after a win, never in the middle of a
  tension build; the same design and length each time; dates and times only move forward [AOTC Invite; AOTC MI; AOTC
  GNIP; FEP 4D].
- **One design family, made for this video:** the person's Look first (its fonts, colours, saved templates), else
  `custom` or `{ass}` in the kit colours and fonts; one typeface family (two at most); the same look across a series.
  Check: one sheet of every graphic (`letitedit_check_frames(times_s=...)`) reads as one family [AOTC Top Gun; JH 10:00;
  OURS].
- **A graphic must carry meaning the footage can't,** fit the picture's world, and never outrank the story; heavy
  graphics over thin emotion plateau [AOTC Porcelain; AOTC Skeleton Crew; ITE DycpviHSeX4 02:25].

### Scenes made with code
How a scene moves is letitedit-motion: read it before writing one. What makes a scene worth drawing [OURS]:
- **At least one, on the strongest line,** on talking-head or other visually thin footage, unless the notes say not to
  or Motion graphics is None (`letitedit-firstcut`). Resolve the story plan's `visual_decision` before placing
  graphics. Every new scene fresh in HyperFrames custom code (`letitedit_code_scene(create)`); do not search My scenes
  or reuse another video's code unless the person asks for a saved scene; do not settle for what is quick to draw.
- **What the line says, visibly happening:** a stranger with the sound off can point at it and name it. A reflective
  line may be one image from its feeling; a talk that explains or claims: usually the thing itself (a list arriving item by
  item on its words, a line climbing as they say it climbs, the feared disaster happening). Invented for this line: a video about something else should not get it.
  Drawn charts, screens, icons and a few words count when they move on the words; a still card, bullet list or panel
  to stop and read is a graphic, not a scene; an object changing shape or brightness, or a speck, says nothing a viewer
  can name: the thing of the moment is big and bright enough to draw the eye at phone size.
- **Depth and life** (letitedit-motion section 6): background, middle and foreground at different speeds, light and
  atmosphere (glow, fog, rain, stars, particles), something changing in every frame; flat shapes on a gradient read as
  a slide.
- **Timed to the words** (letitedit-motion section 8): before any code, a beat list, one row per thing said (word, what
  appears, what it does); each key word lands on a visible event; the scene changes as the thought changes, so a frame
  from each part of the talk looks different.
- **A real way in and out:** the world opens behind the speaker through a shape, a light or a move that starts from
  something in the shot, then hands back; never a rectangle that pops on and off.
- **The person in it:** in front, through a `cutout` on a track above the scene, while their delivery matters
  (`letitedit_code_scene(create, behind_person=true)` for a talking head; it doesn't follow a scene you later move or
  trim). The whole frame only for a beat, about 3-8 s in a Short, then the face comes back; keep the face when its
  expression is the point; a full takeover without the person is fine when the scene is the point (letitedit-layers).
- **Sound with it:** a music phrase, natural sound or short effect for the entrance, movement and exit, never over
  important speech.
- **Honest:** a scene is an illustration, never proof that an event occurred; a screen plainly drawn as a drawing is
  fine with no real recording, nothing that passes for a recording, and the demonstration stays on the pickup list.
- **A generated picture** may be a still plate where code alone would look like clip art (camera, words and moving
  parts in code); `letitedit_image(action='status')` may say nothing can draw, so never depend on it. When, how many
  (one per place, reused), plates, character sheets, never a real person: references/images.md.
- **Check after every scene change:** look at the scene `letitedit_code_scene` returns (entrance, strongest moment,
  exit; at feed size, the person in front) and keep improving it: a first draft rarely reaches the bar; a slide or clip
  art is rewritten (`revise`, one Undo, no render). A frame labelled "NOT drawn" is a scene that could not be drawn,
  not an empty background.
- **Further scenes need their own strong line.** Motion graphics, 3D, Courage and "How much is going on?" are
  ceilings: None means none of that element; a high setting permits bold, dimensional scenes. Leave quiet stretches.

## 5. Effects and transitions: restraint
- **Custom sliders are ceilings, not quotas.** Read the Look's `custom.sliders` first (transitions, punch-ins, emoji,
  captions, 3D, motion graphics, overlays, cutting speed, b-roll): each allows up to that intensity when footage and
  story warrant it. An absent slider was left at "AI decides": choose from the footage, story and brief. An amount
  slider at `0` means **None**: add none. A high slider requires nothing. Cutting speed and dialogue are two-sided
  choices, not amounts; `pauses` sets how talk is tightened in the fine cut. Courage raises how bold, unusual or
  dimensional a motivated choice may be, and never excuses a graphic over a face or a noisy cut with no story reason.
  Each strong effect's reason goes in the journal.
- **Transitions and stylised devices: letitedit-craft X1** (straight cut by default, every other transition and every
  stylised device with its reason, one use per video unless each use escalates, "less flashy" removes them first) and
  the device ledger, L1.
- **Animation is a device too:** one entrance style for the video's graphics; repeated title animations are counted
  [ITE art:why-repetition-in-editing-kills-impact] (arrivals: letitedit-motion sections 2, 3 and 7).

## 6. Check at feed size
- Every graphic, fully on and mid-animation: `letitedit_check_frames(times_s=[...], width=360, platform=...)` vertical
  (480 wide). It passes when it reads at a glance at that size in the time it is up (words / 3.5 + 0.5 s); sits inside
  the uncovered area and outside every box where the request says letitedit adds overlay words after the export (they
  cover whatever is under them in the posted file); covers no caption or the object it explains, and no face unless a
  Look, its reference or the moment calls for it (the router's Faces rule); keeps its contrast on the busiest frame
  behind it (an outline or a panel); matches the video's other graphics. Collisions also show in the review bundle's
  project checks and `letitedit_annotate`'s preview.
- After the final export: frames at the entrance, strongest motion and exit of every item against the union of Shorts,
  TikTok and Reels covered areas (`platform='phone'`), every caption and each face; move, shorten or remove any item
  touching them, apart from a face cover the Look, its reference or the moment calls for. Then watch muted: the explain
  pass reads without sound [GEN; OURS].
- Generated-picture b-roll (Antigravity's permission, the other routes, a moving still, provenance): references/images.md
  section 8. Picture-coloured caption letters (one caption system, blend on the letters-only layer, any readability aid on every
  caption): letitedit-captions' references/look-captions.md.

## 7. Hand-off
Journal note `stage:graphics:done`: the explain list (claim or step -> device -> evidence or illustration), the
missing-footage notes and pickups, device counts, the feed-size check.
