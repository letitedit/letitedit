# Big words with mood cutaways

Style: talking head, for Shorts/Reels/TikTok (9:16) and YouTube videos (16:9). One person talks to the camera; the words that matter land big and inverted, and short filmed cutaways carry the feeling of each line.

The sections below describe the Short. When the request's `Format:` is YouTube video, read "On a YouTube video (16:9)" near the end as well: where it differs, it wins. The measurement files beside this recipe (visual.json, lighting.json, sound.json, sources.json) are the measured profile the tools read.

## Footage and cutting
Use filmed, cinematic, colourful cutaways chosen by the feeling of the spoken line: name that feeling first (excitement, relief, curiosity, frustration, wonder), then pick a shot that carries it in the picture (faces, hands, bodies, light, nature, motion), tight, in dim or saturated light. A noun in the line is not a reason for a shot; a plain fact the camera can show gets the thing itself. Search licensed stock with emotion words and record each cutaway's line, its feeling and why the shot fits in the Look check. No generated scenes, code scenes or AI pictures. Keep the original talking head and voice.

Spread short sequences throughout, including the ending. The tools lay the measured amount (see Camera vocabulary) on the timeline as slots: `letitedit_look_check` returns `cutaway_slots`. Fill every slot with many short cutaways, not a few long ones. Caption changes are not picture cuts. Every cut between the speaker and a cutaway flashes both sides, both ways: two 60 fps frames of the cutaway and the same two of the speaker, face included, go negative (`{op: fx, cut_flashes: true}`); never between cutaways or on every caption.

## Typography
Use the executable profile below with the new video's checked words and face regions. Link words are Inter Tight 800 at .043H; medium/emphasis Onest 900 at .063H/.095H, low centre .735H. Preserve meaningful groups, fixed-left append, selective hierarchy, .08 s linking entrances and immediate medium/emphasis arrivals.





White source glyphs use Difference. Keep inversion despite brief contrast dips and changing shot colours. Only rare sustained near-invisibility warrants normal white: median inverted ink contrast below 1.5:1 on more than half the fully-on native frames. Select one colour per caption lifetime after picture/lighting changes with `letitedit_caption_readability(project, inverted_then_white=true, apply=true)`; repeat against the export with `video`. Exclude entrances/exits and exact two-frame negatives. No outline, shadow, box, mid-caption switch or blanket white fallback. White over bright imagery can still fail; disclose it without adding forbidden aids.

## Lighting and sound
Light the person on every speaker clip with `{op: fx, lighting: true}` after the picture is final, with live filters and no cut-out: a lit face against a darker room; lighting.json carries this Look's own settings and its measured separation. The live lighting only lifts the face, with skin kept natural; the room takes the darkening. Speaker punches (1.08-1.12) and a slow push (1 to 1.10 over 1.5-3 s) go on earned thoughts, a few per video, each making the speaker larger. Score clean dialogue with a shaped licensed bed (voice/music -14.9/-26.7 LUFS, near 60 BPM). Shutter click on each cutaway transition, soft key tick on each caption word: `{op: fx, sync_sounds: true}`, in the same op as `cut_flashes`. Reconcile every measured device as placed or declined with evidence.

```kinetic_type_profile
{"font":{"family":"Inter Tight","weight":800},"roles":{"emphasis":{"ease":"linear","entry":0,"exit":0,"fade_in":false,"fill":"#ffffff","font":{"family":"Onest","weight":900},"reveal":"none","size":0.095,"spacing":-0.06},"linking":{"ease":"linear","entry":0.08,"exit":0,"fade_in":true,"fill":"#ffffff","font":{"family":"Inter Tight","weight":800},"reveal":"none","size":0.043,"spacing":0},"medium":{"ease":"linear","entry":0,"exit":0,"fade_in":false,"fill":"#ffffff","font":{"family":"Onest","weight":900},"reveal":"none","size":0.063,"spacing":-0.06}},"layout":{"canvas":[1080,1920],"centres":[0.735],"gap":0.008,"row_gap":0.012,"safe":[0.06,0.66,0.88,0.81]}}
```

## Camera vocabulary
Name moves with skills/letitedit-motion/references/camera-moves.md. Measured: 58.05% coverage, 18 cutaways/minute, median 1.983 s (0.6-3 s), longest face hold 4.067 s; ten of fourteen trackable cutaways move at a median 0.158 frame fractions/s. Call `{op: fx, camera_moves: true}`: it measures each clip's own motion, gives static shots a chosen move and never repeats one. Use direct or matched cuts, clean J/L handles or soft dissolves; cutaway negatives last exactly two native frames.
## Measured visual profile
visual.json keeps the measured evidence; its times are evidence, not placements in a new story.
- Individually reviewed b-roll: 16 shots, 18.00/min; median 1.983 s, range 0.600-3.000 s. Match count and lengths as well as share; inversion frames are not extra shots.
- Cut flashes: 10 of 26 cuts carry 2 whole-picture inversions of 2 frames (60 fps), one ending 1 before the cut, one starting 2 after it; talking head and b-roll 10 of 20 cuts, both ways; b-roll and b-roll 0 of 6.
- Native picture analysis: 20 inversion candidates, 2-2 frames at 60 fps. Outside a cut flash, do not tint or invert a new speaker.
- Picture roles: broll, talking_head. Primary product or graphic footage is not automatically b-roll.
- Preserve restrained fixed-left append and selective size hierarchy; serif is an exception, not every word.
- Two-native-frame inversions are picture events, not caption animation. cutaway_negative is a face-safe adaptation only.
- Mixed letter colour follows the picture; Difference/Exclusion remain candidates, not a confirmed source setting.
- Reviewed transition kinds: cut; lengths/directions are in visual.json, not assumed.

## Measured sound profile
The sibling `sound.json` carries measured music and effect evidence, licensed-library audio matches and uncertainty. At the sound pass, read it and use `letitedit_learn(action="sound_plan", reference=<sound.json>, result=<project>, package={duration_s, anchors:[{at,role}], voice_dbfs, audition:true})`. Anchors belong to this story: broll entrances, emphasis, reveals, swells, drops and stop; never copy measured timestamps. Plan/apply its soundtrack_request with letitedit_soundtrack and apply its effect changes once with letitedit_timeline_apply. Unconfirmed effects are auditions, not measured truth. Check stems and short listening clips; the person judges musical character, masking and taste. Missing assets mean re-match locally, not download. When sound.json has a `synced` block, the same plan returns `synced_sounds`: an `{op: fx, sync_sounds}` that places its clicks on transitions and ticks on caption words once the captions are on the timeline.

## Measured lighting
Read the sibling `lighting.json` for measured regions and limits. Light every speaker clip (`{op: fx, lighting: true}`: a live window on the face, a darker room), never one test clip; the live lighting only lifts the face. Measurements are display RGB 0-1; skin is a proxy; vignette is composition-confounded; haze and bloom are unmeasured.

## Shot sources and overlays
Read `sources.json`: film_footage, live_action. Preserve source families. Re-anchor reviewed overlays; audition candidates. Record provenance, event decisions and incomplete coverage in receipts.

## Picture and type treatment
Use the Look's Inter Tight 800 linking and Onest 900 medium/emphasis profile, sizes, layout and motion unchanged. Inverted captions change with the shot. White source glyphs use Difference. Keep inversion despite brief contrast dips and changing shot colours. Only rare sustained near-invisibility warrants normal white: median inverted ink contrast below 1.5:1 on more than half the fully-on native frames. Select one colour per caption lifetime after picture/lighting changes with `letitedit_caption_readability(project, inverted_then_white=true, apply=true)`; repeat against the export with `video`. Exclude entrances/exits and exact two-frame negatives. No outline, shadow, box, mid-caption switch or blanket white fallback. White over bright imagery can still fail; disclose it without adding forbidden aids.

Cutaways show the spoken idea or feeling through colourful cinematic filmed footage, own or licensed stock, with movement matching the Look's measured character. Search more and wider when stock is thin. No made/code scenes, AI-generated pictures, 3D or animation to fill coverage. Keep provenance in the handoff and shot log, not on-picture labels.

Use gentle whole-picture lighting, no cut-out or person matte. Preserve the natural face and skin, scene-specific warm/cool differences and readable highlights. Typography is the principal graphic language; no compulsory stickers, split screens or copied assets. The Look governs timing, shot selection, coverage and sound even without this Theme.

## On a YouTube video (16:9)
Everything above was measured on a Short. On a YouTube video the same parts stay (big key words, inverted captions,
filmed cutaways chosen by feeling, the two-frame negative flash at speaker/cutaway cuts, the shutter and key-tick
sounds, the live lighting), made for a viewer who chose to watch for minutes. Where this section differs, it wins.
- **Sections, not one arc.** Mark the sections where the subject turns and put a `chapter:<name>` marker at each one
  (`letitedit_bin`), named with words the person said: YouTube makes chapters from a list that starts at 0:00, has at
  least three entries and gives each at least 10 s [YT]. Keep the video as long as the material; viewing time drops as
  videos get longer [RES-Guo].
- **Opening at the measured rhythm.** The first 30-60 s run at this Look's measured density (about 18 cutaways a
  minute, median about 2 s, the face held at most about 4 s), opening on the strongest line or the question the video
  answers [YT-hook]. After it, each section opens with a short burst at that rhythm and then settles to about a third
  of it (roughly 5-8 cutaways a minute), so the face carries the explaining and the cutaways mark feelings and turns
  [OURS]. `letitedit_look_check` measures the opening against the Look's numbers; state the settled rate in the
  hand-off.
- **Big words, fewer of them.** Linking captions stay continuous; medium and emphasis words keep their sizes as a share
  of the height (.063H and .095H in a 1080-high frame) and their low centre (.735H), and stay inside the 90% graphics
  area [RES-EBU]. Emphasis goes on the one word a thought turns on, at most about one every 10-15 s after the opening
  [OURS]. On a wide frame the person usually sits off centre: keep the caption block on the side and height that stays
  clear of the face (`letitedit_caption_fit`), never across it.
- **Cutaways.** Same rules: filmed, cinematic, colourful, chosen by the feeling of the line, moving where the Look's
  shots move, no made scenes or AI pictures. 16:9 stock or the person's own filming fills the frame; never stretch a
  vertical clip. A long section without new cutaway ideas may hold the face, with one framing step (1.0-1.12) on a new
  thought.
- **Sound.** The shutter click stays on speaker/cutaway cuts and the key tick on caption words only where emphasis
  lands after the opening (a tick on every linking word for ten minutes tires the ear) [OURS]. Music sits under the
  voice as measured, may drop out under a long explanation and comes back at a chapter turn; export at -14 LUFS /
  -1 dBTP.
- **End** right after the last point lands, on the person's face; no tail they didn't say.

## Sources for the YouTube section
- [YT] YouTube Help, "Add chapters to your videos" (the platform's own rules; strong).
- [YT-hook] YouTube Creator Academy and YouTube's own creator guidance on the first 30 seconds and the promise of the
  title and thumbnail (platform guidance; moderate).
- [RES-Guo] Guo, Kim and Rubin (2014), "How video production affects student engagement" (edX viewing data: engagement
  falls with length; strong for instructional video, moderate elsewhere).
- [RES-EBU] EBU R 95, safe areas for 16:9 production (broadcast standard; strong for safe areas).
- [OURS] the settled cutaway rate, the emphasis spacing and the tick rule are starting points from this Look's
  measured Short, adapted for length; adjust by eye, not measured results on a long video.

## Known limits
- Camera versus subject motion and exact easing remain uncertain.
- Measurements and sampled observations do not prove complete audiovisual fidelity or approval.
