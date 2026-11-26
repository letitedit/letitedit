---
name: letitedit-learn
description: Learn a reusable personal Look and optional Theme from one to three supplied reference video files, or from a finished letitedit project (Make a Look from this video), then compare a test edit part by part and improve only evidenced gaps. Takes a link to a video as well as files (fetched privately with letitedit_fetch). Not for importing footage or copying reference media.
metadata:
  version: 0.1.0
---

# Learn a personal Look

The person supplies files they may analyse. Learn the way of editing, never its footage,
music, graphics, logos, font files, voice or exact script. Given a link instead of a file, fetch the
video with `letitedit_fetch(action='reference', url=...)`: it runs inside letitedit's own tool, needs no
permission from the person and never signs in, and returns `path`, the private reference file in the
person's own working folder (with its record of link, title and uploader). Use that path as the reference
video from there on. A whole video longer than the fetch's cap (a podcast, a talk, a long YouTube video)
comes back `reason: too_long` with `duration_s` and `chapters`. Don't ask the person; fetch parts of it
yourself with `start` and `end`, each part as its own reference (they count among the one to three):
the opening, from 0:00 through the teaser, title card and intro (the chapters show where the talk begins;
about 3-5 minutes), and one stretch of the body, 4-6 minutes inside a single chapter about a third of
the way in, away from ad reads (with no chapters: 0:00-5:00 and 5 minutes from a third of the way in), and,
as a third part, its last 3-4 minutes: how it closes (a wrap-up, a sign-off, an end screen) is seen nowhere else.
A long video's opening holds its one-off devices and its body holds the everyday cutting, so a Look
learned from the opening alone over-weights the devices. Tell the person in one line which parts you
learned from. For any other `ok: False`, tell the person the `error` in plain words (a playlist, needs
a sign-in, offline) and ask for another link or a file; never fetch with a shell,
a browser or any other program. The fetched file is a private working copy: never ship it, copy it into a
library or use it as footage, and never fetch songs or sound alone. Keep reference frames, sound and comparisons private and outside
shipped catalogs. Use the person's connected AI; no second subscription is necessary.
Read the tools' current descriptions before calling them. `letitedit_learn` stores personal
Looks independently of the installation; it does not perform AI analysis or choose scores.

## Build the reusable kit before saving

Design around the face in the full-frame source picture: the kit's pieces stay off the face where they can, as the
reference's do. Don't shrink, dim or letterbox footage that already fits its canvas just to clear graphics; an inset or
split screen belongs in the Look when the reference has one. When footage and canvas have different shapes, preserve a usable face crop
or use the person's own blurred room behind a full-height picture; this is format adaptation, not a licence to
make the person smaller for type. Record supported shapes and layout alternatives in the recipe. What a person asks
for their own face wins for that video; if no alternative fits it, disclose the incompatibility.

A learned Look with on-screen type or graphics includes an executable graphic kit, not just a description.
Read letitedit_learn's kit_build schema and the custom letitedit_graphic drawing API. Build portable families
for the visible hierarchy: ordinary subtitles, fixed headings, occasional emphasis and any reusable callout.
Carry layout, type, colour, spacing and motion, not the reference's topic. Its headline wording, acronym and
letter-tile explanation are content, not required style families. Never force an acronym onto unrelated words.
Use invented sample content in slots; code contains no reference wording, pixels, paths, logos or assets.
For boards, separate the reusable container from its picture content. The recipe includes a source order:
matching screen recording or screenshot in the footage folder, a real picture of the named app or product via
letitedit_real_picture, stock, then a finished filled graphic. This applies to code scenes as well as kit families.
Sample cards demonstrate filled content and readable hierarchy; an empty outline and label is not a board.

Each family specifies job, rate_per_min [minimum,maximum] OR count_per_video [minimum,maximum], duration_s [minimum,maximum], placement,
never_covers (['face'], the default: its pieces are placed clear of faces; [] when the reference's own pieces sit
over faces), slots and a self-contained custom draw(ctx). Frozen style contains bundled font family
names and colours. Use ctx.w/ctx.h-relative geometry for the intended canvas; ctx.p supplies content slots,
ctx.t and ctx.len supply time. Inspect the actual graphics API for drawing signatures, not guessed ones.
Text changes must not change hierarchy. Keep speech small when the reference does; a headline is not a caption.
Use count_per_video for an opening, closing card or persistent header; these are not per-minute devices.
A zero lower bound makes a family optional. Actual rates must lie inside the range without a half-count allowance.
Use a layout/bar family only for the black areas it draws, never an opaque rectangle covering the person.

**Letters that follow the picture.** Some references composite white letters with a Difference (or Exclusion)
blend: the letters show the inverse of whatever is under them, so one word can be white over a dark microphone,
near black over a pale shirt, blue over skin and orange over blue water, and its colours shift as the camera pans
or the shot changes. Look for it across several big words over different pictures, not one frame: over near-black
or a flat dark blur the inverted letters look like ordinary pale or tinted type, and a single colour sample looks
like a fill. Signs: the colours inside a word are the picture's opposites, they change with the shot within one
word's life, and texture from the picture (grain, halftone, edges) shows inside the letters. That is one family
drawn white with `blend: difference`, not a fixed colour, gradient or "colour sweep", and not a white family plus a
coloured family picked per caption. Words that stay plain white over a mid-tone or coloured picture (where an
inverted word would not be white) are a plain family. Give a blend family's build example a moment where its
letters sit over an even, mid-to-bright coloured part of the picture (inverted letters then show one clear colour
and the letter-blend row can be fitted); kit_build's letter-blend row confirms or refuses it, and gives no row when
the picture behind is too even or busy to tell. The visual review's caption blend_candidates likewise come from
what the words show over different pictures or a blend fit, never "normal" by default.

Call letitedit_learn(action='kit_build', out=<private folder>, package={kit,size:[360,640],
reference_video:<the reference file>,examples:[{family,content,seconds,reference_frame:<private native PNG>,
times:[entry,hold,exit],span_s:[start,end],parts:[...]}]}). Each family needs an example and parts: one text part
per line or word group of the piece (box tight around the letters in reference-frame pixels, text exactly as shown,
the slot that carries it, plate true when it sits on a plate), mark parts for accents and separators, picture parts
for picture boxes. The import report's typography evidence has OCR word boxes as frame fractions; multiplied by
the frame size they give pixel boxes to check on the frame. span_s is when that piece is on screen in the reference.
A picture slot in a build example can hold any real picture (a private crop of the reference frame is fine there). The tool draws the family with the
reference's own words at the reference frame's size and measures both sides with the same numbers: text height,
stroke weight, width per letter, slant, colours, plate, corner radius, padding, place, marks, pictures and time on
screen. A family is saveable only when every row is inside tolerance; Save refuses the rest.
Read every row that is out. For type, change the face to the ranked font matches the tool returns (weight and
italic included), then size, colour, plate and place, and build again. Matching letters beats a similar mood:
a rounded bold sans is not a thin geometric one, and a chunky italic serif is not a regular sans. When no bundled
face comes inside tolerance, say which open-licence family would, in the limitations. Repeat until every family is
inside, within this one Learn. A family that still can't be matched after a fair number of builds is left out of the
kit and named in the limitations; never loosen a box or a part to make a number pass.
Persistence: a header or label that stays to the end is `stays`; pieces that each stay and build up (thumbnails
that collect in a row) are `accumulates` (the drawing reads ctx.p['kit_index'] for its position); the rest are
`transient`. A box that shows a picture of the thing being talked about is a picture slot (a slot named ...picture,
drawn with ctx.image); the cut fills it with a real picture of what the new video names, never a blank tile.
Place by the speaker: when a piece's place follows the person (a caption on the chest below the chin, a line above
the head) rather than the frame (a corner tag, a full-width band), give its vertical centre a slot (`centre_y`, a
share of the frame's height) and the family `anchor: {to: speaker, slot: centre_y}`. kit_build measures the
reference's place in face heights from the chin or brow and as a share of the visible body; kit_plan then puts it on
the same place of a new speaker's body (the same share of the way down when the new shot is closer), clear of the
face and the apps' covered edges. A place that is a fixed share of the frame in the reference stays a fixed share.
Inspect the likeness sheets too; numbers in tolerance and your eye should agree.
Save the returned kit as package.graphic_kit with the Look, and `fits`: the reference's format in plain words,
starting "Fits videos that ..." (what the video does with its content and what that content needs, such as "Fits videos that
compare a few options and pick one, with a picture of each option"). Reference crops stay private; the stored kit
has only reusable drawings/specs. Record missing evidence honestly. A Look must not depend on its reference.

## Measure, then look for yourself

Read **letitedit-lighting** for each reference after reviewing picture roles. Its `lighting_reference` pass
adds the measured face window and room appearance (face detector, no matte), each insert grade and the reference's
face-to-room separation, which is what the live lighting is tuned to; keep that enriched report through save.
The same samples carry the reference's colour grade (black level, highlights, colour strength, the lean of shadows,
mid-tones and highlights). Saving the lighting saves `grade.json` beside it and a Measured grade section: the grade is
the Look's colour for every clip of footage, faces or not, and the recipe and Theme describe it rather than restate its
numbers. A Look saved before grades were kept has its grade worked out from its lighting.json when it is read.

1. Confirm the one to three files and a brief about what the person likes. Probe their lengths
   and inspect opening/middle/ending frames. Explain footage fit: a single face cannot supply
   a two-person split; launch coverage cannot reproduce runners, product details or a camera move.
2. Run `letitedit_learn(action='measure', package={videos: [...]})` once on the files. Follow that job with
   `letitedit_learn(action='measure', job_id=...)` rather than launching duplicates. Keep its report paths,
   measurements and warnings. Measurement publishes no Look; the existing save step below does that.
3. Call `letitedit_learn(action='prepare', reports=[...])`. Read its facts and provenance.
   Inspect the original at 1 fps from start to end with `letitedit_look`/`letitedit_stills`, in
   manageable sheets; inspect denser frames around cuts, word arrivals, zooms, stickers and
   split/inset changes. Listen separately to the original audio using available audio evidence;
   if your tools cannot listen, say so and leave those judgments unassessed. A classifier is not
   listening. Missing detector evidence is unknown, not an absence or a match.
4. Record your own timestamped observations for every reference. Separate measured facts,
   visual/audio observations, uncertainty and intentional substitutions. Correct a detector
   claim in the recipe only with an observation explaining the disagreement. Keep one-off
   content separate from shared editing grammar; give ranges when references disagree.

## From a finished project

A finished letitedit project holds what a video file only hints at: the timeline the video was exported from
(caption font, size, colours, outline and box; graphics and their fonts; stickers, split screens, speed changes,
sound effects, music levels and fades, transitions, grade and lighting filters, every clip length), how it was
made, and which choices were the person's own. When the request names a project (`.mlt`), with or without one of
its videos ("Make a Look from this video"), learn from it this way; everything else in this skill still applies.

1. Call `letitedit_learn(action='project', reference=<the project>, result=<the video named, if any>,
   out=<a new private folder>)`. With `no_export`, tell the person the project has no exported video yet and offer
   to export it first; make nothing until they say. Never ask which version: the request names one, or the newest
   final is used. Say in one line which video the Look comes from, and when `other_versions` lists more, name them
   by file name so the person can say "use v2 instead".
2. `exact` is the finished timeline as it stands. Tried-and-undone edits are gone from it and count for nothing.
   With `exact: null` no timeline matches that video: learn it from the video alone, as for any reference, and say
   so in one line.
3. Measure that one video as the reference, as above: the importer, `prepare`, your own frames and listening
   (a long video in parts, as for any long reference). Where the timeline gives a value exactly, it beats the
   measurement; say which values are exact and which measured. Look for yourself at what a timeline can't say:
   framing, faces, motion, the feel of the cutting.
4. `provenance` says who set each value in the finished timeline: `person`, `ai` or `both`. Values the person set
   by hand weigh more than the AI's own (the counts already lean their way). Write them as preferences that carry
   more weight, never as a must or a never.
5. `instructions` holds what the person told the AI while editing, with their "always ..." and "never ..."
   sentences picked out. Only those can become rules, in their own words, passed as `package.rules`
   ([{words, said_at}], words exactly as recorded). Keep a sentence only when it is about style (how the video
   looks, sounds or is cut: "never use red captions"), never about this video's content (what is said or shown,
   people, places, products, prices: "never mention the price"). When a later sentence contradicts an earlier one,
   keep only the later.
6. `made_with` names the Look the video was made with: say in the recipe that this Look grew from it and what the
   finished video does differently.
7. Save with `package.project` (the evidence file `project` wrote) and the version's importer report in `reports`.
   Save keeps `project.json` beside the recipe and adds the exact values section when your recipe has none: keep it,
   tighten it, or write your own with the same heading. The example clip comes from that video.

## Where it fits in letitedit

Every Learn works out, from the references alone and with no input from the person, where the Look sits in
letitedit and how to make a new video in it. A reference is a look and a format: forcing a format onto footage that
doesn't have it looks wrong, so New video checks a person's clips against what you save here.

1. Run `letitedit_learn(action='place_evidence', reference=<each reference video>)`. It counts what the words and
   footage supply (list items, named things, numbers, questions, steps, group words, contrasts, story moments, calls
   to action, talk share, people, footage kind) with quoted evidence: the same measures the fit check runs on a
   person's clips, so the needs you write can be checked. The counts are heuristics; correct them from what you watched.
2. **Subject**, one line: what this reference itself is about. It is content, kept apart.
3. **Pattern**: the general pattern a person could reuse, named from letitedit's side: who or what is on screen, how
   it is told, what drives it (speech, music, text), the repeating device. Name the pattern, not the subject: "one
   person doing an activity, full frame, music-led, big quotes over it", not "a dancing video". Test it by swapping in
   three unrelated topics: if the sentence still holds, it is the pattern.
4. **Uses**: every kind of content the pattern could honestly dress, as wide as it goes (4-16): think "what could
   someone film that this would make look good?" across topics, activities and niches. The reference's own topic is
   one use among many. Put near misses that would break it in `not_for`.
5. **Kinds of video** (`styles`): a Style is what was filmed. Reuse a Style when it really fits: `talking-head` (one
   person to the camera), `conversation` (two or more people talking), `activity` (action or activity, little talk to
   the camera), `screen` (a screen recording), the 100% AI Styles `ai-explainer`, `ai-story`, `ai-scrapbook` for a Look
   made without footage, and the person's own learned Styles (`letitedit_learn(action='list')` returns them). List every
   one the pattern fits, main first, and only those: a Style belongs when footage of that kind alone could make this
   video (a talking head can't make a voiceover film of objects; a place montage isn't "action or activity"; mock-up
   graphics aren't a screen recording). Only when none fits, add `{new: {title, filmed, blurb}}`, named in general words
   ("Podcast", "Action with fast transitions"), never the reference's subject: it is kept with the person's Looks and
   reused by its title next time, so the list stays short.
6. **Length** is letitedit's format, the shape as well as the running time: `short` (a vertical Short, about 3 minutes
   or less), `long` (a wide YouTube video: chapters and sections, not a 60-second arc) or `both`. A wide 30-second
   ad is `long` or `both`, never `short`; `place_evidence` gives the reference's `frame`. `seconds` is the range the
   format works at. A reference that starts or stops mid-sentence is an excerpt: mark the sections you didn't see
   optional and say in their `does` that they are inferred; an ending you didn't see is unknown, never "ends on the
   talk": say so, and New video follows the mode's own ending. **Role**: `look` (layout and format),
   `theme` (how it is drawn: palette, type, a film treatment) or `both`; theme and both save the Theme too.
7. **Footage**: `kinds` (what the footage must be: talking-head, conversation, activity, screen, or none for made
   pictures), `speech` (needed, optional, none), `people` [min, max] when the format needs a number of people, and
   `what` in plain words.
8. **Structure**: the format as sections in order, each with its job (hook, setup, item, sort, payoff, call to action,
   chapter...), what it does, the need ids it uses, its seconds and how often it repeats (`repeats` [3, 12] for list
   items), optional or not; `arc`, `opening` and `ending` in a line each; `chapters` for long form.
9. **Needs**: distinguish content from format with kind: content|format. Topic-shaped lists, announced parts,
   examples, named things, prices, offers and questions are content: must:false and a plain without note describing
   the cut when absent (one clear explanation, no agenda or numbered chapters, the same headlines and rhythm).
   Announced parts in a tutorial do not turn every new talk into a multi-part lesson. A real format need stays
   required: a talking head needs talk; a Short keeps its short vertical format. Only a deliberately chosen list
   or story format needs those items or events as its spine; mark kind:format and explain why the pattern itself
   cannot work without it, not merely that the reference contains it. Point at the smallest measured signal that
   works, or ai when no measure fits. Named things needing pictures say so in what. Never invent speech to meet a need.
10. **Devices**: each device of the Look, marked `style` (any video can wear it: caption type and place, colour, cut
    rhythm, transitions, light, music handling) or `content` (used only when the new video's words have it: letters of
    an acronym explained one by one, a sorting header, a count-up, a before/after split), with `when` naming the words
    that call for it. A device bound to the reference's topic is content, and so is one that needs a particular line
    or person (a card for the one key question, a split screen of the listener reacting): its look can be style, its
    use is content.

Check it with `letitedit_learn(action='place_check', package={place, reports})`, fix what it refuses, and save it as
`package.place` with the Look. A Look with a graphic kit can't be saved without one, and Learn isn't finished
(`learn_job.py done` refuses) until the Look has its place.

## Write and save

Read `letitedit-motion/references/camera-moves.md` when describing movement.
The importer measures the camera language of each reference shot by shot (its report's `camera`; prepare and save
keep it in visual.json, and the recipe gets its line): each shot's move (static, pan, tilt, push in, pull out,
handheld, whip; image motion), size (from the main face, else the fact log's vision model when installed) and plain
share of the frame (open sky, bare walls), and the mix. Check a few shots against your own frames; where moves or sizes are unknown or wrong, say so in the recipe
rather than guess. Write in the footage needs what the camera language asks of new footage (moving shots, close
shots and details, people close to the lens). Angles (low, high, canted) and foreground framing are not measured:
describe what you see in the recipe.
Name image drift/pan, tilt, digital push/pull and editorial zoom punches separately
from possible filmed travel. Record direction, frame-fraction/second displacement,
log-scale/second, duration and uncertainty. Alignment alone cannot prove a dolly,
orbit, handheld capture or physical camera movement; keep ambiguous movement unknown.

Write a recipe of reproducible numbers and choices, not "copy creator X". Include:
- Footage needs, orientation, driver, shot selection and narrative progression; what this
  footage cannot supply and the chosen honest alternative.
- Cutting rate and shot-length quartiles, short/long holds, action/beat placement, transition
  timing; punch scale/duration/ease versus actual camera movement.
- A type system by role, not one caption preset: linking versus emphasis;
  opening headline, linking speech, question/callout and occasional emphasis are separate roles.
  Inventory every distinct graphic family across opening, middle and ending: containers/pills,
  symbols/icons, interface diagrams and cards, including brief non-caption overlays. Record each
  family's timestamps, normalized geometry, palette, density, entry/hold/exit and story function.
  Preserve recurring grammar, not branded assets or the reference's exact content. An omitted
  detector event needs a visual observation, not a claim that the family is absent.
  For boxed text, state the unit explicitly (letter, word or phrase), corner-radius/tile-height,
  padding/glyph-height and gap/tile-width; do not turn separate letter tiles into word boxes.
  Record role-specific accent colours and when a headline or emphasis replaces ordinary speech.
  Use nearest bundled
  font candidates with same-word mask overlap (not confidence), weight, case, letter spacing
  in em, line spacing, glyph height/frame height and font em/frame height separately. Preserve
  per-word fill/highlight, outline/shadow, line breaks, anchors, stacking and deliberate overlap.
  Inspect native-resolution entry/hold/exit crops and dense brackets, including fragments
  and text pops that coarse OCR did not label captions. For frame-accurate teardown, importer
  setting typography_native:true retains every decoded frame (typography_native_band defaults
  to the full frame; typography_native_start_s/typography_native_end_s bound a test). Read its inventory and limitations;
  no watermark/scene exclusion applies. A cropped band proves nothing outside it. Correct OCR before font fits.
  State each word's scale/slide/reveal, onset, hold, exit, duration and easing; leave an
  unmeasured easing or exact font unknown rather than inventing a match. Keep faces/buttons readable.
- Use the caption track only for what it actually draws faithfully. For independently sized,
  coloured, positioned or moving words use the motion block `kinetic_type` or a code scene,
  driven by the person's actual word timings, never the reference's wording. `kinetic_type`
  takes role defaults and per-word overrides: x/y frame fractions, size em/frame height,
  bundled font/weight, spacing em, fill, start/end seconds, entry/exit, scale, slide and reveal.
  Supply phrases:[{words:[...],end}] with explicit line indexes, role settings and protected
  face rectangles over their time spans. The compiler lays out final word positions, holds
  each through the phrase, and preserves the supplied onsets; appending never recentres earlier
  words. layout supplies canvas, safe bounds and preferred centres. It includes overshoot,
  travel and font advances, checks browser dimensions, and refuses rather than shrinking or
  wrapping silently. This is geometry, not emphasis or line-group guessing. Manual words remain available.
  runs:[{text,fill,font,start}] can colour inside a word, mix fonts or reveal explicit syllables
  with reveal:runs; reveal:letters uses grapheme stagger. Use only the motion actually observed,
  not every available effect. If changing colours follow the live background, test compositing
  separately from fill animation; a sampled blue is not proof of blue type. Never invert the person.
  Inspect/export dense boundary frames and alpha against faces; a static fallback is not faithful.
  Enrich the importer report with letitedit_learn(action='visual_reference', reference=<report.json>,
  out=<new private folder>, package={review, blend_samples}) when native picture evidence is needed.
  It decodes native frames, including two-frame effects a coarse sample misses; inspect candidate boundaries
  independently and do not mistake a negative pulse for a zoom, blur, sound or b-roll-only transition.
  For lettering, blend_samples takes aligned background/observed/mask PNG paths; the mask is opaque glyph
  interiors picked independently of the fit. Compare all reported modes. A moving or contaminated clean plate
  may leave the fit unresolved. White Difference and Exclusion cannot be distinguished from baked pixels;
  preserve both candidates rather than inventing a uniquely identified source-editor setting.
  Calibrate sizes with same-word native-pixel crops before saving: em is not glyph height.
  Preserve distinct medium/large emphasis roles; readability enlargement is an adaptation,
  not a universal default. Align entry elapsed frames and hold/exit phases separately.
- Sticker/graphic frequency, size, place, entrance and purpose; split/inset and b-roll share.
- Save a separate base-picture inventory with `letitedit_learn(action='source_reference', reference=<report>,
  out=<new private folder>, package={segments,overlays,overlay_coverage})`. Cover the runtime without gaps:
  segments use start_s/end_s, kind, status reviewed|unknown, evidence and optional frame paths. Production kinds
  are live_action, film_footage, stop_motion, ai_video, avatar, cg_3d, code_render, anim_2d, screen_capture,
  still_motion, static_hold or unknown. Review provenance; pixels alone cannot reliably distinguish filmed,
  generated and 3D footage. Missing faces, text, sound detections or models prove no absence. Keep uncertain
  segments unknown. Captions, negative pulses and punch-ins over filmed footage do not change its source family.
  Record overlays separately: caption, sticker, pip or sound_effect; start_s/end_s, reviewed|candidate status,
  evidence, and a meaningful story anchor. A reviewed pip also needs source_kind. Give every overlay kind
  coverage unassessed|partial|complete. Candidate stickers can be label lettering or background texture;
  inspect their crop in the whole shot before promoting them.
  For stickers and split screens, call `letitedit_learn(action='picture_sheets', reference=<report>, out=<new private
  folder>)`, look at every sheet it lists (with `letitedit_look` or your own image viewer, a few sheets at a time),
  answer its question for those tiles, and pass every answer to source_reference as package.picture_marks
  {request, pages:[{tiles:[first,last], items}]}. It times each mark from the pixels and adds the sticker and pip
  overlays; coverage is complete only when every tile was answered. Mark only what you see; leave doubts sure:false. Candidate sound effects require listening.
  Prepare/save the enriched report, or pass its sources profile explicitly; sources.json and the private HTML
  preserve each event and its limits. Compare the film/stock, generate, render and screen routes, not a single
  majority label. Keep the existing native caption/blend, lighting, motion and sound evidence alongside it.
- Record the kinds of shot sources the reference actually uses: filmed footage, screen recording,
  AI-generated pictures/video, 3D or animation, code or graphics. Keep to those kinds; add a kind absent
  from the reference only if the person asks. Record the b-roll share and roles: showing an idea,
  setting a place, carrying a feeling or metaphor. Use suitable own footage first, then licensed stock
  within those source kinds. Search more and wider when coverage is thin; do not fill a missing filmed
  shot with a made scene or generated picture. Disclose a shortfall rather than inventing a source kind.
- Record semantic cutaway intervals and their line jobs from the visible reference; face absence alone is not b-roll.
  The visual review records reviewer, intervals (start_s/end_s/role/subject), transitions and caption events,
  including unknown font, motion or audio evidence. Roles are talking_head/broll/primary/graphics/unknown;
  primary product shots and full-screen title animation are not automatically b-roll. Cover the full decoded
  runtime before claiming a full share; uncovered or unknown time keeps it unknown. Save the enriched reports
  so prepare/save retain every reviewed event in visual.json, not just a majority style. Catalog visual_profile
  identifies that file. Reviewed semantics are the reviewing AI's work, not automatic pixel recognition.
  Before the new rough cut, budget target share times runtime against suitable own coverage and available
  licensed sources of the recorded kinds. Broaden searches when needed; unavailable stock remains a
  disclosed coverage gap, not permission to invent another source kind. Measure the final visible export with the
  export-bound shot log in letitedit-broll section 7; report unknowns and any shortfall. Share is not visual likeness.
- Colour, exposure, grade, music tempo/energy/drop shape, relative voice/music levels,
  loudness, sound-effect kind/placement, the opening and ending. State unknowns explicitly.
- For a sound-led reference, call `letitedit_learn(action='sound_reference', reference=<report.json>, out=<private folder>)`.
  It separates installed Demucs stems and ranks local CC0 music/effects by audio CLAP, tempo and dynamics. Read its
  coverage/errors, energy curve, stem LUFS, character hypotheses and uncertain event matches. Nonvocals still contain
  music AND effects: neither a transient nor a classifier label proves an effect, its name or its isolated level.
  Keep confirmed count unknown until listening establishes it. Judge instruments, key, masking and taste only with
  evidence; do not infer sidechain ducking from music levels in story-confounded gaps. Save the returned measured
  profile as `package.sound`; updates preserve it when omitted, explicit null removes it. At New video's sound pass,
  follow letitedit-sound's learned-profile section; never transplant reference media or its event timestamps.

Keep the reusable recipe to current instructions and key numbers, at most 1,000 words including
added visual, lighting, sound and known-limit sections. Put raw per-sample measurements and uncertainty
in evidence.json, visual.json, lighting.json, grade.json and sound.json, not prose dumps. No task numbers,
development anecdotes, personal quotes, handoff notes or assigned source-file paths belong in the
recipe or Theme. Describe footage needs and conditional adaptations generally, so each New video
uses its own supplied sources and save folder. Save refuses contaminated or over-limit instructions;
shorten the prose without discarding the underlying data.

Where there is a separable surface treatment, write a Theme: palette, bundled type,
graphic language or film treatment, with concrete application rules. `kit` is illustrated
elements; `film` is a treatment. No Theme is better than inventing one without evidence.
The Look must remain understandable with no explicit Theme selected.
Use `letitedit_fonts` and the licensed library instead of extracting reference assets.
Never turn a reference slogan, logo or spoken claim into a reusable default.

Save with `letitedit_learn(action='save', package={...})`. Package fields:
`id` (`mine-...`), `title`, `line`, `needs`, `works_with` (`footage` normally), `recipe`
(Markdown), `reports` (the 1-3 report paths), `observations`
(`[{reference:0,at_s:1.2,part:'captions',observation:'...'}]`), `limitations` (text array),
`place` (Where it fits, above), optional `asks` and `theme` (`{kind:'kit'|'film',title,recipe}`). Use each reference's
zero-based index and real source seconds. An empty limitation list is not a claim of perfection.
You name the Look; the person doesn't type a name and can rename it from its card later. `title` is two
to five plain words saying what it looks like ("Bold words over cutaways"), general enough to reuse, never
the reference's creator, channel, show or subject. `line` is one sentence a newcomer to editing
understands: what the viewer sees and hears. When `done` runs, the Look gets a short example clip from the
first reference, kept private on this PC beside the Look.
An update requires `expected_revision` from `action='list'`; re-read on conflict, never
overwrite somebody else's update. Immutable recipe, Theme and evidence revisions stay on disk.
To update a Look, start from its current `recipe.md` and change only the lines the update is for; leave
out of the package every part you are not changing (lighting, visual, sound, sources, place, kit, Theme,
asks): the save carries each over exactly, files and recipe sections alike. Give a part (or `null`) only
to change or remove it; `lighting_only:true` re-measures the lighting and its grade.
Personal cards appear under **Your Looks** in New video.

## Learn, test, check, fix

Make a short test on genuinely suitable footage through normal New video, with the learned
Look (and its Theme, if present) explicitly selected. Do not substitute a hand-made timeline
for this proof. Follow `letitedit-firstcut` and the normal stage skills, not Turbo unless the
person requested it. Respect `Save video in:` from the New video request/progress record;
never guess the output folder from the source footage's parent. Never change the originals.

After normal frame/audio checks and `letitedit_review_bundle`, measure the actual final export
with the importer. Call `letitedit_learn(action='match', reference=...,result=...,out=...,
render=True)`. It writes a private side-by-side MP4, ordered 1fps pages, measured deltas and
an independent-critic brief. Pictures use the same elapsed second, not matched story beats;
the shorter becomes black after it ends. Reference audio is left, result right; listen to
the originals separately. Examine opening/ending and dense event boundaries as well as pages.
The match also writes role/phase-aligned text crop pages. Compare emphasis against emphasis,
not the same elapsed second alone. Common source-width scaling preserves size differences;
use full frames/boxes for absolute layout. Require separate `text_parts` scores for fonts,
sizes, layout, colour and movement, with timecoded evidence and limitations. The caption total cannot
exceed its weakest text sub-score; unknown text subparts mean no total. A shared blue or a
uniform pop never earns 7/10 when the reference has a different type hierarchy and choreography.

Have a separate fresh critic conversation on the person's same AI read that brief, both
originals, every page and the measurements. It must assess cutting, captions, zooms, stickers,
colour, music, loudness, sound effects, b-roll, opening and ending individually (0-10, or
null with a reason). Require reference/result timecodes, what didn't carry and why, the exact
`report_sha256` pair, and actual engine/model/effort. Never infer scores from detector deltas
or fill a score your critic did not return. Save that JSON with `action='match',scores=...`.
"Assessed" means reviewed, not approved; the person decides whether the resemblance succeeds.

Change the recipe only for a gap supported by this check. Preserve the previous revision,
the test outputs, measurements and scores; make at most two further test attempts. A mismatch
caused by missing footage stays a stated limitation, not a request to invent shots or claims.
Stop when the person accepts or the two retries are exhausted; don't silently keep spending.

Record elapsed measurement, own inspection, learning, generation and checking time separately,
plus AI model/effort, rendered seconds and machine. For a new input, give only a measured
range from comparable runs, identify queued work, and show stage progress. Without comparable
timings, say the estimate is not calibrated yet; never invent a fast completion promise.

## Progress the editor shows

When the request names a progress file and a `learn_job.py` command, the editor shows the person
the stages from that file, so report each as you reach it: `measure` (the importer measuring),
`look` (your own frame inspection), `write` (writing the recipe), `save` (saving it). When the
Look is saved run `done` with its id; if you cannot finish run `fail` with a few plain words.
That request is only for learning: do not start a video from it.
