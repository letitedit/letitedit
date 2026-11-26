---
name: letitedit-lighting
description: Match measured scene lighting with live editor filters, keeping natural references natural, with no cut-out or model relighting, and put a Look's measured colour grade on every clip of footage. Use during Learn, and at the finish of New video when a Look includes measured lighting or a measured grade.
---

# Learn and match scene appearance

Read the Look recipe and the current tool descriptions. Copy the way of lighting, never reference media.
This is a display-picture adaptation, not recovered physical studio illumination. Large differences in light,
surroundings and composition can prevent an exact reference match. Say what remains different.

**One process, for every Look:** lighting uses live editor filters on the speaker's clips
(Mask: Simple Shape and Color Grading), and what differs between Looks is
the settings. Importing a style measures how far the reference's face sits above its room and the Look keeps that number;
making a video reaches it from each clip's own separation. The person is never cut out and no model relights the picture.
A naturally unseparated reference stays natural: do not invent a face lift or darker room. A near-zero
measured target uses neutral live settings unless the person explicitly requests another treatment.
A cut-out exists only for layering the person asks for, such as text behind them (letitedit-layers).

## Learn

**When:** Learn, after the importer and the visual-role review. **Do:** read references/learn.md in full: the
`lighting_reference` call and its enriched `report.json`, reviewed role boundaries, the frames and window images you inspect
yourself, `live.reference_stops`, subject and background compared separately, and saving with the conflict guard
(`lighting`, `lighting_only`).

## Make

**Do: light every speaker clip, once.** Work on a copy. Apply the measured treatment on **every clip of the speaker**, not a sample: one
change, after the picture is final (cuts, cutaways, punch-ins, any trim) and before captions:

```yaml
- op: fx
  lighting: true      # or {face_ev: 0.03, face_gamma: 1.2, room_ev: -1.3, window: [1.7, 2.0], feather: 0.8}
```

**What the op does.** It puts live engine filters on each main-track clip that plays a video file, keeping the clip as it is: **Mask: Simple
Shape** and **Color Grading** (the editor shows both and the person can change them by hand, one Undo each). A soft
oval "power window", keyframed from face detections every quarter second, follows the biggest face and lifts it; a wider,
lower oval with the mask inverted darkens the room outside it. The reply names the clips. One test clip is never the
delivery: the Look check names any speaker clip left unlit. A clip with no face found is left unlit and named. Keyframe
times follow the clip's in point, so run the op again after trimming; a second call replaces the earlier lighting.

**Tuned to the Look.** With no settings given, the op reads the project's Look: a `live_settings` block in its lighting.json
is used as it stands; otherwise `live.reference_stops` is the separation to reach, each clip's own separation is measured on
its frames (face window against room), and `room_ev` becomes what takes the clip there (the reply lists each clip's
measured separation, the Look's, and the `room_ev` chosen). A clip already as separated as the reference gets no darkening.
Settings you give (`face_ev`, `face_gamma`, `room_ev`, `window`, `feather`) win.

**Why these settings.** This is how a colourist separates a subject: a window on the face with a gentle lift and a feathered edge, the
surround pulled down. A key-to-fill ratio of 2:1 is one stop and 4:1 two; a lit talking head usually sits between
about one and two stops brighter than its room. Measure the reference's separation in `lighting.json`
(`subject_background_stops`, face and background median luma) and set `room_ev` (and `face_ev`/`face_gamma`) toward it.
Gain is one multiplier on all three channels, so hue and colour strength hold and the face keeps its contrast; a
gamma-only lift reads hazy and flat. Warm skin reaches full red early, so a strong gain clips it: the face lift is
small, and the room's darkening does most of the separating. `face_ev` is 0 to 1 EV of gain, `face_gamma` 1 to 1.5,
`room_ev` 0 to -3, `window` the oval's width and height in face widths and heights, `feather` 0.05 to 1.

**The live lighting only lifts a face, by design.** It is one-sided: on every frame it makes the face brighter and
clearer or leaves it, never darker (mean and median luma change at or above 0); its hue shifts no more than 3 degrees,
its colour strength (chroma over lightness) no more than 15%, its median luma stays at or under 0.80 (unless it was
higher), and no more than 1% of its skin pixels newly clip. Taking a face darker or warmer toward the reference's faces
is the grade's job (below), not the lighting's. Natural skin sits on the vectorscope's skin-tone line; lit
skin usually reads 65-75 IRE (50-65 for darker skin, up to about 80). Check it on the export engine's picture:
`lighting.check_live(project)` renders the main track with and without the lighting at the same moments and measures
the face box and the room's change; if it fails, lower `face_ev` or `face_gamma`, or widen `window`. A face missed on a
frame takes the nearest detection. Effects stay off the face where they can.

## The grade: the Look's colour, on all footage

**When: every clip of footage, a speaker or not.** Light and colour are two jobs. Lighting shapes how a face sits against its room, so it needs a face. The grade is the
Look's colour: where its blacks sit, how bright its highlights reach, how strong its colours are and which way its
shadows, mid-tones and highlights lean. It belongs on every clip of footage, a speaker or not; a video with nobody
talking still wears its Look's colour. A Look measured from a reference has a grade (`grade.json`, or worked out from
its `lighting.json` for a Look saved earlier); `letitedit_look_check` lists it as its own device.

```yaml
- op: fx
  grade: true          # or {strength: 0.7}; {remove: true} takes it off
```

**What the op does.** After the picture is final (cuts, cutaways, trims) and after any lighting, one change puts a **LUT (3D)** filter on each
clip of footage on every picture track, fitted to that clip. Colourists balance each shot first and then lay one look
over all of them, matching each shot to the look by eye on the scopes; this does the same from measurements: each clip
is matched to the reference shots nearest it in brightness (a dark shot to its dark shots), through one smooth tone
curve, a colour-strength scale and a lean per brightness band. Faces take the Look's grade too, aimed at the
reference's own faces: when the Look measured faces (its `lighting.json`), on a clip with a detected face, pixels
keyed as skin by their colour and tone take a skin grade inside the same LUT, toward the reference's skin brightness,
lean and colour strength, brighter or darker, so the room moves toward the reference's room and the face toward its
faces, as a colourist isolates skin with a qualifier and grades it to its own target (Van Hurkman, *Color Correction
Handbook*, the chapter on skin tone: strong). A clip without a detected face takes the picture grade alone (warm sand,
wood or a sunset is not skin). A colourist softens a qualifier's matte; a LUT can't, so the skin grade is mixed in only
as far as three checks on the written LUT allow, after any live lighting: on each face no more than 1% of skin newly
clipped; on the clip as a whole (its faces' skin pooled with every pixel the key takes) camera noise grown, in
brightness and colour, no more than twice what the grade itself makes of it, and each keyed pixel no more than half a
stop from where the picture grade alone puts it. A check with too few pixels to measure never passes (skin keeps its
own tones there at most); failing the checks, the picture grade itself goes part of the way on that clip, never all
the way off just to keep some skin grade, and the Look check names that room as held back, not as the footage's
limit. Where skin lands against the reference's skin, and its hue and colour
strength against the range the reference's own skin covers, are measured and named, not enforced.
Without measured faces, skin-tone hues (the vectorscope's skin line, with orange and red) keep most of their colour
and their own colour strength where the curve darkens them. The reply gives each clip's median, highlights and saturation before and after;
pictures, graphics and made clips are left alone.

**Different light.** Footage under different light from the reference (an overcast sky against a sunny or neon reference) still takes the
Look's character where the footage allows it, the way a colourist grades flat footage: a clip far flatter than the
reference gets a steeper curve, and a clip that stays much greyer leans further toward the Look's colour (scaling the
colour of grey leaves it grey; a lean in the Look's direction does not), while strong colours in the shot (a red jacket, a
yellow sign) keep their own. The reply says on how many clips faces were checked, their median level before and
after, where skin landed against the reference's, which clips took the skin grade part of the way, and says so when
faces weren't measured. When skin reads wrong on a frame,
check that line first. Lowering the grade's strength for the whole video takes the Look off every clip to fix a few,
which is how a grade ends up flat and grey; keep full strength and name any clip the reply says still drifts.

**Not: a hand-built grade.** Do not hand-build a LUT or a whole-video adjustment-layer grade for a Look that has a measured grade: one curve over
everything crushes some shots and leaves others flat, and an adjustment layer also tints captions and graphics. A
Look with no grade (a library Look) keeps its colour in its recipe and Theme. Run the op again after trimming.
Check the grade on rendered frames (`letitedit_check_frames`): the reference's highlights should still read bright
and its colours as strong, and its blacks as deep; say what remains different (a grey sky cannot become a sunset or a
night).

## What a person asks for their own face

**Do: what they ask, in their words.** A person's own words about their face win for that video, done as they mean them in ordinary words, without their
having to name a technical step. "Unchanged", "untouched", "as recorded" or "don't change how I look" keeps the grade,
the lighting and effects off their face; "don't make my face darker" keeps a darker grade off it. "Full size" or
"uncovered" alone is about size and cover: it doesn't forbid a grade, lighting or a punch-in that keeps the face full
size and uncovered. Check what they asked on the export's frames (the grade's reply gives the faces' level before
and after it), and where the Look's grade or lighting would go against it, take that treatment off or down on their
clips and say so. Neither is mandatory: use only the Look's measured treatment
and the brief's permitted moves. "Natural" is not permission to add contrast the reference did not have. If a
measurement shows the lighting made the face darker or off natural skin, lower the light and say so.

## Prove before handoff

**Check: a before/after through the export path.** Render a short before/after through the same canvas and export path. Inspect frames, including motion edges and a zoomed crop of the neck, collar and hairline: no line may show where the window ends.
Measure a reviewed face box independently of any matte, per frame: mean and median luma change (never below 0), hue
shift, chroma change, clipped share. Final delivery encoding may change pixels: compare like-for-like encoded controls,
disclose drift, and never count a face the lighting made darker or tinted as a lighting match. A neutral measured treatment need not
introduce a visible difference; its before/after proves the natural picture was preserved.
Use check_frames, check_audio and the review bundle before handing over a finished edit. A technical two-second
lighting experiment is not a finished New video and is not a claim that the whole Look matches.
