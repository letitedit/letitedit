# B-roll with a measured Look

Read with letitedit-broll whenever the Look has measured files (a learned Look, or a library Look with `visual.json`),
and for inverted cut flashes on any Look the person asks them on. Every rule of letitedit-broll still applies; these
add to it. The section names match the pointers in SKILL.md.

## Picture-inverted captions (with section 6)
For a picture-inverted caption Look, prefer relevant strong-colour, mid-to-bright shots rather than near-black
screens or near-white picture areas behind the caption band. Check that band in rendered frames: rich teal,
blue, pink or orange picture gives the inverted letters visible colour. Relevance comes first; colour is not
permission to use unrelated footage. Land the big inverted keywords on those colourful cutaways. Small linking
words may stay white over the natural full-size speaker. Inspect the last-pass caption choice after the final picture is in place.

## Shot rhythm (sections 2 and 5)
A Look's measured individual shot rhythm takes precedence over the generic ranges of section 2. Carry that rhythm through
the ending as well as the opening. Measure its longest talking-head stretch from reviewed reference intervals,
and keep every uninterrupted primary-face stretch inside it.

- **Individual shot rhythm matters too.** Match the Look's measured cutaways/minute and shot-length median/range.
  Budget the rounded shot count for the new runtime as well as coverage. A long sequence can contain several real
  shots; mark each actual boundary in `visible_shots` (id/start_s/end_s), not flash frames or imaginary subdivisions.

## Cutaway slots (section 6)
- **The slots come from the tools.** `letitedit_look_check(project)` (no decisions: it only reads) returns `cutaway_slots`
  when the Look carries cutaway numbers: how many cutaways the runtime wants, each slot's time and length, and the words
  said there. Fill every slot before the export; `filled` and `open` say what is left, and a shortfall is a finding. It
  reports and never blocks the export. Move a slot to the nearest phrase gap if the picture needs it, but keep the
  count and the share.

## B-roll character (section 6)
- **Match the Look's b-roll character, not just its share.** If the reference's cutaways are cinematic (real-looking
  scenes, moody light, shallow depth, its grade), made b-roll is too: photographic generated pictures given a slow
  move, or a 3D scene, graded like the Look. Flat diagrams only where the Look itself uses diagrams.

## Checks (section 7)
- **Inverted flashes on the cuts (a Look that has them, and any Look the person asks for them on):** after the cutaways are
  placed, `{op: fx, cut_flashes: true, sync_sounds: true}` in one op. Every edge where an opaque, full-frame cutaway meets the
  speaker goes negative for two frames, in both directions (speaker to cutaway, cutaway to speaker), on both pictures: the
  editor's own Invert filter on the cutaway's first or last frames, and the same frames of the speaker (a block under the
  cutaway track; the speaker's face is inverted too, for those frames only; `sides: cutaway` leaves the speaker's side out); the
  transition click goes on the same edges. The edge between two
  touching cutaways, the video's start and end, and a cutaway that is not full-frame get none (the reply lists them). Run it
  again after a cutaway is moved or swapped. The Look check reads the pulses back.
- Read `letitedit-motion/references/camera-moves.md` for filmed moves. Name each
  shot's move (digital push/pull, image drift, or observed filmed travel),
  direction, duration and measured frame-fraction/second speed. Use the Look's
  lengths and rates, not generic long-move defaults.
- A Look's saved `broll_motion` describes coherent image drift, push/pull rates, moving share and static holds,
  not proven physical camera motion. Prefer moving stock; for static shots use slow Size/Position keyframes
  at the learned frame-fraction speed, retaining enough crop headroom to hide edges. Check native frames for
  unintended subject drift. Match movement across the entire cut, including its last third. Pass `visible_shots`
  and a rendered preview or final `video` to `letitedit_look_check`: missing required motion is major;
  untrackable motion stays unknown rather than a passing declaration.
- For a Look's measured negative-colour cut pulses, place `kind: transition`, `id: <b-roll clip>`,
  `transition: {type: cutaway_negative, edge: in|out, len: 0.05}` through `op: fx`; name the B-roll `track` if different.
  A `cutaway_negative` item itself inverts only its full-frame b-roll clip, never the talking-head side; the speaker's
  side comes from `cut_flashes`' own block. Place a verified whoosh/hit with `sfx` and
  `sfx_offset_s` so its peak meets the cut; narration continues. Check the cut's adjacent frames and sound after a
  main-track trim. `cut_flashes` inverts both sides by default (the bullet above), as a reference that inverts the
  speaker's side too does; pass `sides: cutaway` when the reference inverts only the cutaway, or when the person
  asks to keep their face out of it.
- For private Look matching, attach a b_roll_evidence object (format letitedit-broll-evidence/1) to each importer
  report: exact duration_s, actual media_sha256, method, reviewer, boundary_tolerance_s and ordered non-overlapping
  intervals. Each interval has start_s/end_s and kind b_roll, talking_head, other or unknown. Each b_roll interval
  also records provenance own/stock/made/reference, source, line, role, shows and illustration (true for made/stock).
  bridge/broll_evidence.py validates it; the match bundle verifies the media hash. Missing evidence is unknown,
  never zero. Report own/stock/made visible shares and longest talking head. Coverage alone earns no likeness score.
