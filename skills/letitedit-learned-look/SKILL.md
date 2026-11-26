---
name: letitedit-learned-look
description: Make a video in a measured Look (one learned from a reference video with Learn, whose card lists `measured` files beside its recipe) - every measured device placed or declined with evidence, the speaker lit as measured, faces graded with the Look, inverted captions, the Look's graphic kit placed and checked, a Look that is also a format fitted to the clips, its sources and b-roll receipts, and every device checked again on the exported file. Use with letitedit-firstcut whenever the chosen Look has measured files; a library Look never needs it.
metadata:
  version: 0.1.0
---

# A measured Look, placed and proved

Measured Look devices are placed unless an actual tool refuses or an explicit person rule forbids that device.
The Look check includes `punchins` and `sound_accents`, separately from opening and music. Never decline flashes
for face protection: put them only on the b-roll side. A big difference between the footage's light and the
reference's is what the lighting match is for, not a reason to skip it. Light the speaker with `{op: fx, lighting: true}` on **every speaker clip**
(letitedit-lighting), after the picture is final and before captions; never on one test clip only, which is not the
delivery. Live filters only: no cut-out and no model relighting. A natural reference stays natural, with neutral live
settings for a near-zero measured target. The live lighting only lifts a face, by design, as measured; the Look's grade
takes the face toward the reference's own faces, brighter or darker; disclose a partial match.
Effects stay off the face where they can.
A person's words about their face win for that video, done as they mean them in ordinary words, without their having
to name a technical step: "unchanged", "untouched", "as recorded" or "don't change how I look" keeps the grade, the
lighting and effects off their face (a `person_rule` for those devices). "Full size" or "uncovered" alone is about size
and cover: it doesn't forbid a grade, lighting or a punch-in that keeps the face full size and uncovered, and those
are placed as the Look says. Check what they asked on the export (the grade's reply gives the faces' median level
before and after it, its report each face's). If the Look's `sound.json` has a `synced` block, place its picture-synced sounds with
`{op: fx, sync_sounds: true}` after the cutaways and captions (letitedit-sound), and put a move on every cutaway with
`{op: fx, camera_moves: true}` (letitedit-broll, section 7). Before the cutaways, read the slots the Look's numbers plan
(`letitedit_look_check(project)` returns `cutaway_slots`) and fill them, each by the feeling of its line (letitedit-broll,
section 6); a Look with inverted cut flashes gets `{op: fx, cut_flashes: true}` with the clicks, in the same op as
`sync_sounds` (letitedit-broll, section 7). The light on the speaker is the live filters of letitedit-lighting, tuned to the Look.
Punch-ins and sound accents have no blanket conflict. For a decline supply `evidence.kind: tool_refusal`
with the actual result JSON `path`, `sha256`, `device`, `tool` and `attempt`; or `person_rule` with the exact
brief `quote` and the actual `conflict`. For a source-unit decline, `device` names the affected category.
Use `unmeasured` only when the source contains no such measurement.
Generic editorial preferences, a quiet style, cost, or not having tried are weak declines: their receipt rows stay open.
A measured device left out on purpose is `left_out` with the reason that holds (`receipt_forms` lists them). Missing
devices and weak declines are receipt rows (the record of the decisions, including _sources), not faults in the
video; what the timeline shows is. The graphic kit's measured family/face check reports faults in the video: repair
up to three times, then deliver with disclosed flaws.
For an inverted-then-white caption Look use `letitedit_caption_readability(inverted_then_white=true, apply=true)`;
pick the colour last, after all picture work. Retain the exact typography and motion. Choose white for the whole
caption only if an inverted word is below 3:1 at 360px on a fully-on frame; exclude entrance/exit and exact two-frame
negative flashes. Pick again after any later picture change; a stale choice is a major finding.
Never add an edge or box to that Look. Other Looks retain their own written caption policy.
A kit family with a `blend` (the recipe's kit line says its letters invert live) is that system drawn by the kit:
kit_plan puts the blend on every piece, so the letters invert whatever is under them frame by frame and change
with the shot, cutaway and pan. Keep every piece of it inverted; never imitate the inversion with a fixed colour or
by choosing between a white and a coloured family per caption. After all picture work, kit_check's inversion rows
say which pieces stay inverted and which go plain white (only those near invisible on more than half their
fully-on frames); make the edits its findings give, and check again after any later picture change.

For a measured Look,
read all returned source requirements,
including recipe.md, visual.json, lighting.json, sound.json and sources.json when present (`letitedit_look_check` names a
long one in `requirements_in_files` with its path: read it there). Account for captions, transitions, relevant b-roll,
lighting, sound, opening, punch-ins and sound accents, and the camera language when the Look has it. Each is placed
with current item IDs and evidence, or declined with the structured evidence above.
**Camera language.** When visual.json's references carry `camera` (every reference shot's move and size, and its
`profile`), the Look's picture is a mix: the share of moving shots and their kinds (pan, tilt, push in, pull out,
handheld, whip), the shot sizes (wide, medium, close, detail), how plain the frames without a person are
(`plain_share`: open sky, bare walls), and over any `stretch_s` seconds the least movement (`stretch_moving_min`),
the most of one size (`stretch_one_size_max`) and the plainest frames (`stretch_plain_max`) the reference ever
shows. Choose the footage to
that mix before cutting: each video's `picture:` line in the footage reply (steady, pans, shake) and the fact log
(`letitedit_footage(facts=True)`: `shot` wide, medium, close-up or detail) say which clips move and how close they
are. When the Look moves, take moving shots first, in the kinds of move it uses (push-ins and forward travel are not
pans); vary sizes as the reference does; prefer full frames (closer, with foreground) to a small subject in open sky
when the reference's frames are full; and never hold static shots, one size or plain frames longer than its
stretches do. Too few moving shots in the footage: give static ones a slow move
(`{op: fx, camera_moves: true}` on cutaways, a keyframed push-in on the main track) and vary sizes with crops that
keep faces and hands whole. Low, high or canted angles and foreground framing are not measured: take them from the
recipe and your own frames, and favour footage that has them when the recipe names them. With `video`, the Look
check measures the export the same way (`camera` device) and names each stretch outside the mix with its clips:
change those clips or their moves, check again, and say plainly what the footage could not give. A camera
receipt is placed with the footage clips chosen for it.
**Fuller shots first, crops second, then the footage's limit.** A plain or one-size stretch, or a far-off subject
small in open sky or on a bare wall, is not a footage limit until both of these were tried clip by clip and the export
checked again: (1) the folder's fuller shots: for each stretch the Look check flags, its reply lists stretches of the
footage's fact log that are closer, have people in view or move, least used first, with how much of each is not in
the cut yet, and it names the plainest shots in the stretch and how many of them have to become fuller frames to bring
every stretch of it under the bar. Change that many in one go, each named shot out and a fuller moment in at the same
length (one fuller stretch gives several different moments), before any crop: a swap or two in a long run moves it a
few points at most. A crop toward a small subject in a
big sky is still mostly sky, so shorten and thin the run of plain shots and cut fuller ones in among them: the same
moment from nearer, people or things in the foreground framing the action, the crowd and crew watching, a closer
subject of the same event. The section's own subject may change for a beat; a montage cuts between the action and the
people around it. Keep within the reference's stretch (`stretch_plain_max`, `stretch_one_size_max`) and keep the
story's order (a shot that gives away a later reveal waits for it); `letitedit_ask_frames` on the candidates judges
foreground framing. (2) a crop toward the subject on each wide shot that stays: `letitedit_fix` with
`{kind: punch, zoom, focus: 'track'}` follows a moving subject and redraws the enlargement with its upscaling model,
or a `{zoom: z, focus: [x, y]}` effect (keyed to follow it) for a lighter crop. Size the crop so the subject reaches
the sizes the reference uses (a far-off subject becomes a medium shot) and the frame fills with the subject, its
trail, the ground or people rather than empty sky. Keep within what the source can give: `letitedit_footage` gives
each source's size, a source smaller than the video's frame is already enlarged to fill it (720p in a 1080p video:
1.5x its own pixels) and a crop multiplies that. A plain zoom keeps to letitedit-fine's limit for punch-ins; `fix`
punch's model allows a closer crop (its engine note says which model goes how far). Judge each on its full-size
frames from the export engine (`letitedit_check_frames`) and back off where edges break up or detail smears. A stretch
is fixed when the Look check on the new export no longer flags it, not when its clips were changed (a stretch can move
rather than go). What is still plain or one size after both is the footage's limit only when the check's reply names no
fuller stretch for it (or every one it names was tried and placed); name those clips and what was tried.
**The ending's shape.** The camera device also compares the cut's last picture shot with the reference's last shots
(their moves and lengths, and any end hold to black): when it names the ending, end on shots like the reference's (a
run of short moving shots rather than one long hold, for example), on the music's last hit.
**Pace, section by section.** visual.json's camera shots are also the reference's shot lengths. Hold them through every
section of the cut, not only an opening burst: a viewer reads a channel's rhythm across the whole video, and the middle
is where a copy most often settles into longer, even shots. `letitedit_look_check(project)` returns `pace_targets`
before any export: the reference's median shot, the band its stretches' medians sit in (`stretch_band_s`, 25th to 75th
percentile), its cuts a minute and its ending. Put a shot-length target on every section of story_plan.json from them
(the band, not only the median, so sections breathe as the reference's do) and build the rough cut to it
(letitedit-rough). Where speech leads a section, its words set the cut points and keep their own rate: never cut
inside a phrase to reach a number. Where the picture leads, the section runs at the reference's band and its cuts a
minute, with uneven lengths (on a beat grid, one, two and three beats rather than one length repeated) and no more long
holds than the reference has. With `video`, the Look check's `pace` finding names each stretch outside them with its
shots and clips, the long holds over the reference's 90th percentile shot, the cuts a minute and how many shots a
stretch would hold at the reference's pace: cut it to that (shorter shots and more of them; the fuller moments the
camera device names are the material, so one change answers both) or make the stretch shorter.
**Pace built in, by code.** Where the picture leads, don't set lengths by hand and hope the middle holds: once the
rough cut's selects are on the main track, `{op: fx, pace: true}` cuts every footage clip of the body to the reference's
own shot lengths, read from the same place in the reference's body (its quick runs, its held shots, its slowing toward
night), so the cut starts with the reference's variety and the pace check passes before any review. It takes the pattern,
not the template: each quarter of the stretch keeps that quarter's lengths in a new order, so the cuts don't land on the
reference's own cut times, which reads as a remake of that video rather than a video in its style. An
opening hold longer than any body shot is kept; `keep` leaves a held reveal; `to` stops before an ending you placed by
the music; a stretch that runs to the end takes the reference's own ending, its last shots and its end hold in order, so
the cut slows into its close as the reference does instead of ending on the body's beat; `beat_s` (the song's beat, once the song is known) keeps every length to whole half-beats so the cuts stay on
the grid; `lengths` takes a story plan's own. The reference usually cuts faster than a first assembly: the reply says
how much shorter the stretch got and about how many more shots fill the time it had; add that many selects (of the
kinds the shot mix asks for, below) and run it again. Film editors build rhythm from varied shot lengths, not one
length repeated (Pearlman, *Cutting Rhythms*, 2nd ed.: moderate, an editor's account), and in measured films the run
of shot lengths varies the way attention does rather than sitting on one value (Cutting, DeLong and Nothelfer,
*Psychological Science* 2010, shot-length patterns in 150 films: strong).
**What the shots show.** A channel is recognised by what it points the camera at as much as by its grade: candid people
up close, details of things, wide views, transport, places. The Look check's `shot_mix` finding (with `video`) sorts the
export's shots and the reference's into those kinds with the same vision facts the fact log keeps, and names each kind
the cut has much less of than the reference, with unused stretches of that kind from the footage's log. Pick to the
mix from the log stage on: when the reference is people-centred, take the logged stretches with a person as the subject
(`letitedit_find_ranges` for faces, hands, gestures) before another wide of a street or a train, and cut a sequence
the way documentary shooters cover a moment: a wide, then a medium, then the face and the hands or the object (the
five-shot sequence of news and documentary training: moderate, common practice). When the footage's log holds fewer of
a kind than the reference's share asks for, the check says so: that is the footage's limit; say it in the hand-over
rather than filling the gap with more of what the reference avoids. Two more things the judges of a copy notice at
once: a place coming back after another shot a few seconds later (the same walk, the same stall, cut into several
clips and spread out), which reads as padding rather than coverage; and an ending whose shots change kind from the
reference's (a reference that closes on a held view of the city at night, closed with more street-level walking). The
Look check names each file shown again within six seconds after another shot, and each setup shown again anywhere (a
moment of a file within ten seconds of one the cut already showed: the same place from the same camera) (`near_repeats`);
replace the later ones with `shot_mix.replacement`'s logged stretch of the same kind (a file the cut doesn't show near
there, from a part of it the cut hasn't shown), or cut the returns. Consecutive clips of one file are one continuing scene, which a held ending often is. Build the ending from the
kind of shot the reference ends on, as a few held scenes of one subject each, and let the pace field give it the
reference's ending lengths (the repetition ledger of letitedit-craft; editors' practice: moderate).
**One grade.** A reference shot by one channel holds one colour from shot to shot, and viewers read a change of grade
between shots as a change of source. The Look's grade (`{op: fx, grade: true}`) gives every clip of footage one shared
colour when the reference holds one, bringing saturated clips down as well as grey ones up; skin keeps its own colour.
It also brings the cut's brightness from clip to clip inside the reference's spread across its shots: the cut's middle
to the reference's, a wider spread narrowed, each clip at most half a stop, a night or dark stretch kept below the day
shots by the reference's own gap; the blacks and the top of the highlights hold. Faces take the Look's grade too, aimed
at the reference's own faces: on a clip with a detected face, inside the same LUT, pixels keyed as skin by their
colour and tone take a skin grade toward the reference's skin (its brightness, lean and colour strength), brighter or
darker, while the room goes to the reference's pictures, the way a colourist isolates skin with a qualifier and grades
it to its own target (Van Hurkman, *Color Correction Handbook*, the chapter on skin tone: strong). A clip without a
detected face takes the picture grade alone, so sand, wood or a sunset is never graded as skin. A colourist softens a
qualifier's matte so its edge doesn't show; a LUT can't, so the skin grade is mixed in only as far as three checks on
the written LUT allow, after any live lighting: on each face, no more than 1% of skin newly clipped; and on the clip as
a whole (its faces' skin pooled with every pixel the key takes), camera noise grown, in brightness and in colour, no
more than twice what the grade itself makes of it (greyer skin on the key's edge would otherwise turn noise into
blotches; a contrast curve's own slope is not counted as noise), and each pixel the key takes no more than half a stop
from where the picture grade alone puts it. A check with too few pixels to measure never passes: such a clip keeps its
skin at its own tones at most, and the reply names it. When the face can't sit that far from its room, the picture
grade itself goes part of the way on that clip (never all the way off just to keep some skin grade). Where skin lands
against the reference's skin, and its hue and colour strength against the range the reference's own skin covers, are
measured and named in the reply, not enforced. The reply also says, with counts, how many faces were checked, which
clips took the skin grade or the picture grade part of the way, and says so when faces weren't measured. A gap the
grade's own fit could not close is named per shot in `grade_likeness.footage_limits` as the footage's limit; a gap left
by the room the face checks held back is named in `grade_likeness.held_back`, neither the footage's limit nor a fault
to fix by regrading; never push a face further another way to close either. A clip left under half the grade is named
as an outlier. With `video`, the Look check's `grade_likeness` finding
compares the export's footage shots with the reference: colour
strength, the lean (warmer or cooler), brightness, the tonal range (blacks lifted or crushed against the reference's),
the lean of the shadows and of the highlights (an open blue sky against an overcast one, sodium night against cyan
night), how much each changes from one shot to the next, and the shots furthest outside, by clip id and time. Shots are
matched blacks and highlights first, then the mid-tones (Van Hurkman, *Color Correction Handbook*: balance the black
and white points before the mids, strong); the grade does this for every clip. Fix the named clips first: a clip
whose source can't come close (a warm room, a clear blue sky in an overcast Look, mixed stock) is swapped for a shot
closer to the reference's light when the footage has one, or framed with less of what can't match; otherwise name it as
the footage's limit. Skin follows the reference's skin: a reference that grades its speaker cooler, warmer or darker
than the footage takes the footage's speaker toward it too, as far as those checks allow.
**The title.** When the recipe's title section gives numbers (the colour, the cap height and the second line's height
as shares of the frame, the place, a heavy weight, a plain area), the Look check's `title` finding (with `video`)
measures the opening title as it renders: each line's height, the strokes' width against the line's height (a heavy face
reads about 0.16 and over, a regular one about 0.11), and the picture behind it. Set it to those numbers on the drawn
result, not the font size: a script with shorter glyphs (Thai, Devanagari) needs a much larger size than Latin capitals
to reach the same height, so size each line by its measured height. In an .ass text layer a variable font's named weights
("Montserrat ExtraBold") draw as the regular face: set Bold -1, and for a heavier stroke add an outline of the fill's
own colour (`\bord3\3c` with the same colour) until the check reads the reference's weight. Put the title in the
plain area nearest the recipe's place (open sky, a bare wall near where the reference composed its title): the check
names that place when the picture behind the title is busy, or when the title sits far off in a plain corner while a
plain area lies nearer the recipe's place. A title composed into the frame's open space reads as designed for the shot;
one pushed to a far corner reads as an overlay (layout's figure and ground: moderate, design practice). When nothing near
the recipe's place is plain, open on a shot that has open space there before moving the title away from it.
**The sound's shape and its hits.** The sound reads as the channel's as much as the picture does: how the opening sits
under the body, how the level moves through it, how it ends (a fade, a drop, silence over the end card) and how often a
sharp hit lands. The Look check's `sound_shape` finding (with `video`) compares them with the reference's on the same
meter. Shape the music to it (letitedit-sound). When the reference has hits, place library hits and whooshes at its
rate (`sound_shape.hits.reference_per_minute`, per minute of the cut) on what its hits land on (`reference_on_cuts`,
`reference_on_text`: cuts, caption or title arrivals), each sound's peak within an eighth of a second of what it marks,
the kind chosen by what it marks (a whoosh into a cutaway, a hit on a word that lands), with the quiet second before it
and the level the reference's have (`before_under_body_db`, `level_vs_body_db`; letitedit-sound says how). A reference
with no hits gets none. Run the check on the fine cut's export, before the review rounds, and again on the new export.
Account for every returned `source_units` entry: put each exact key in decisions `_sources`, with placed/declined, a reason
covering every device in that unit, and current item IDs when placed (the reply gives each unit's opening; its whole text is
in the Look file the key names, and in the file `full_result` names). This prevents a six-category summary from
silently omitting another measured device in an arbitrary Look.
Include when the Look did not measure something. A category is not a substitute for checking every device inside it.
When the Look catalog exposes graphic_kit, read that saved graphic-kit.json. Place its drawings by reference
with letitedit_learn(action='kit_plan',reference=<kit file>,result=<project>,package={placements:[
{family,at,seconds,content:{text:<this video's own words>}}]}). Apply the returned changes with timeline_apply.
Use the exact slots the family declares. Plan the batch together; consecutive instances share a kit lane.
A slot named ...picture holds a real picture file of what this video names at that moment, never a blank tile.
For a named thing (a book, product, logo, app, person or place) use a picture of that exact item from the web,
fetched with `letitedit_real_picture` (it keeps the source and credit line, which follow the piece into the export's
credits); otherwise use stock, a frame of
the footage or the image generator under the b-roll rules. Families that stay or accumulate are placed without
seconds and run to the video end; each accumulating instance takes the next position by itself.
Do not redraw from prose, replace with native captions, or add unlisted graphic families. Keep the kit's frozen
layout/type/colour/motion and hierarchy: small speech remains small; headings and emphasis remain separate.
Reference wording, acronyms and topic-shaped tiles are not style. Use content-shaped devices only where the
new words naturally contain that structure. Never invent an acronym or copy the reference's hook.
Keep footage that already fits the canvas full frame unless the Look or the person calls for an inset or a split
screen; never shrink, inset or letterbox it just to clear graphics, and keep effects off the face where they can be. Check every source's displayed orientation, including rotation metadata,
against the Look and chosen output before laying out the person. For upright footage in a landscape Look,
compare export-engine frames of a face-safe subject crop with a full-height picture over the person's own
blurred room (blur_pad or a synchronized background copy). Pick from the Look's measured layout: a crop only
when the whole face and relevant hands survive; own-room blur when the source must stay fully visible and
the Look leaves side space. Pick room background rather than an oversized ghost of the speaker, and check
headline contrast against it. Never box the person into a narrow strip beside flat colour. A Short is an option
only when this Look has one and the requested deliverable permits it. Record the choice and frame evidence
in story_plan.json; explicit face/framing wishes win. Use the detected face box to find space for graphics;
when none fits, report the incompatibility rather than cover the person, or shrink them where the Look and the person
call for no inset.
Boards and example cards follow the same source order whether drawn by a kit or a code scene with no picture
container: matching screen recording or screenshot from the footage folder; a real picture of the named app or
product through letitedit_real_picture; stock; then a finished filled graphic. Keep the Look's card geometry,
palette and motion around that content. An empty outline with a label is never a finished board. A real UI
demonstration is not replaced by a fake timeline; any fallback illustration is filled, specific and labelled.
After picture, lighting and kit placement are final, run letitedit_learn(action='kit_check',reference=<kit>,
result=<project>). Read every number: family counts/rates/durations, face_overlap_frames and face_cover (one
measurement of all the kit's ink: frames, seconds, first frame and the pieces on screen then, not which one covered
the face). Kit ink on a detected face is a measured fact: a piece of a family placed clear of faces that was on
screen then moves where the frame has room, unless the Look's moment calls for it there, and what stays on a face is
said in the result. Missing detector/render evidence fails. Fix failed placement through the kit (new content/timing and allowed placement parameters), then recheck.
After at most three repair/check passes, export the video even if style checks still fail. Never end New video
without a video because of a kit finding. Keep every unresolved finding in the result and final review, say plainly
what did not fit and why, and never describe that export as passing. Do not drop the kit to hide a failure.
If a frozen layout cannot fit the face, record the incompatibility rather than covering the person, or shrinking them
where the Look and the person call for no inset.
No detection is not proof of absence. Save the check in run records.
A learned Look whose card has `place` (place.json beside its recipe) is a look and a format. After logging, run
`letitedit_learn(action='fit', reference=<the Look id>, result=<the chosen clips or folder>)` (a `Format fit:` line in
the request is the Look step's answer for the same clips; `Look use: look only` means the person chose only the look,
so format.fit is look-only and every section is left out with that reason) and read found, missing, unchecked and
which sections the clips can fill; judge
the unchecked needs yourself from the words and frames. Content-shaped needs stay optional: follow each
need's `without` note rather than invent announced parts or chapters for a one-point explanation. Request the
selected output with `package={format: 'short'}` (or `'long'`) and read `framing` for source shapes and layout options.
On `fits`, build the format from this footage's own content:
its sections in the format's order, each repeated within its range, the person's own items in their own words, their
own words for any groups, and a real picture of each named thing (`letitedit_real_picture`); a `fits` with `leaves`
lacks only optional content (a number card, a then-and-now, a closing question): build every section without it, leave
out a section that is nothing but that content, and say so in `left_out`. On `maybe` or `partly`,
build what the clips have and leave the rest out: never invent an item, name, group, question or claim to complete a
format, and use a content-shaped device (place.devices, kind content) only where these words have that content. On
`no`, or when only the look is wanted, use the style devices and cut the footage the way it suits (letitedit-modes).
Write `format` into story_plan.json: `{fit, sections:[{id, built, count, content:[the items, names or lines used],
at, why}], left_out, content_devices:[{name, because}]}`, one entry per place section (built false with `why` for
each one left out) and `left_out` in plain words for anything short of a full fit. Run
`letitedit_learn(action='plan_check', reference=<Look>, result=<story_plan.json>)` until it returns no problems; the
final message and the review say what was left out and why.
Without a saved kit, keep the Look's distinct typography roles and check native entry/hold/exit crops; do not
transplant topic-specific lettering as a mandatory graphic family. Record current item IDs in the Look receipt.
When source_profile is present, read sources.json before the story/coverage pass. Its base-picture kinds select
own filmed footage/licensed stock, screen capture, generated media or rendering. Keep the recorded family;
unknown never grants permission to generate. A code caption over filmed footage remains a separate overlay.
Use reviewed sticker/inset/sound durations and entrances on this story's anchors, never reference timestamps.
Keep candidate effects unassessed until picture review or listening; an incomplete inventory does not mean none.
In the shot_sources receipt declare every visible video item in sources by current ID, role base|overlay,
kind and evidence. Base kind is a production kind; overlay kind is caption|sticker|pip|sound_effect, with
source_kind for pip. The bottom picture track remains base. Include events keyed by the source plan's keys,
placed with new-story anchor/current IDs (audible audio-track IDs for sounds) or declined with structured refusal/person evidence; candidates use
unassessed with a reason. A coverage entry keyed reference-index:kind acknowledges each partial/unassessed
inventory with matching status and limits. The separate stickers device can be unassessed while no reviewed
sticker/inset is known and coverage is incomplete. Claim measured_absence only with a complete empty inventory.
The check hashes sources.json and invalidates receipts after evidence or timeline changes. Provenance statements
are reviewer declarations, not automatic pixel proof; inspect the export to substantiate them.
**The Look's own media.** When the Look's card has `own_media`, it names the person's own footage and intro.
`own_media.broll`: search those folders for cutaways before any other source, with `letitedit_search(files=
<broll.search_files>)` (its picture index is built in the background; `broll.index` says how far it is, and a
search over files not yet indexed builds them as it goes, so search the project's own footage first when time is
short), then confirm each pick with `letitedit_ask_frames`. Copy nothing out of those folders: insert the clip from
where it is. A line those folders can't show falls back to the order this Look's sources allow. `own_media.intro`:
place that file, whole and unchanged, where `where` says (`reference_at_s` and `seconds` are where and how long it
ran in the reference; `loudness_lufs` is its sound level there; `notes` says how the music and cut meet it), on the
main picture track as its own clip, and check it on the export. `own_media.logo`: the person's own logo, used
where `where` says, unchanged (never redrawn or recoloured).
For b-roll, record each shot's visible content and the narration it proves; off-topic own footage never counts toward
the share or rhythm. Match the Look's individual cutaways/minute and median/range, not just its coverage. Supply
ordered `visible_shots: [{id, start_s, end_s}]` for each actual full-frame shot in the broll receipt. Do not count
two-frame pulses as shots or label one long sequence as many shots without real picture changes.
Distribute those cutaways through the whole film, including the ending, not all near the beginning. When the Look
has `longest_talking_head_s`, keep every unbroken face stretch within it. The Look check derives uncovered primary
spans from visible cutaways, including the opening and tail; a matching total count does not excuse a long ending.
Cutaways show this video's own topic: never pictures of the person's other subjects (another series' or channel's
library) because they are at hand, even for made scenes or cards. For a video about software or editing, use
relevant typing, clicking, filming or screen stock, actual product recordings, or made scenes of the work.
For a picture-inverted Look, choose relevant strong-colour mid-to-bright cutaways and time the big inverted words
onto them. Avoid near-black screens and near-white areas behind the caption band, which make inversion merely
white or black. Small linking words may be white over the natural speaker. Inspect rendered caption-band colour;
do not replace the measured inverted system with ordinary coloured type or sacrifice relevance to colour.
Off-topic footage never counts toward
the measured share. Supply `share_target` as the Look's minimum fraction, or null when it has none; the check measures
the union of the declared relevant item spans. Record actual relevant seconds/share in the reason. Save decisions
and report unresolved faults in the video; never loop until everything passes. Caption evidence comes from `letitedit_caption_readability`
(the Look check reads its measurement of the current edit itself).
Lighting that exceeds the face limit is reduced, never forced. Missed faces are unverified, not a passing check.
After a reviewed export (the last preview the review reads, or the export you hand over), check all devices on those
bytes once and record `export: {sha256, observation}` for each placed device, given with that `video`; repeat caption
measurement with `video`. An observation given with its video carries to a later render of the same items (the
full-size final the last review renders), and the Look check's own measurements on the final's bytes (the camera
language, the sound's opening, caption contrast) stand as theirs; a device whose items changed after it was observed
needs a new one. A missing observation is a receipt row, never a reason to export again. The review lists faults in the video; receipt rows are counted on its Look line, not as faults.
A selected kit's failed or stale rendered family/face check is a fault in the video; after the bounded repair passes
export with disclosure; a kit check that could not run is a note.
