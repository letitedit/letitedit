# A Look's own caption system (letitedit-captions sections 1 and 7)

Read in full when the selected Look carries its own caption system: a learned Look's caption roles and measured arrivals, an
inverted-then-white or `caption_colour_policy` caption, picture-following letters (`blend: difference` or `exclusion`),
kinetic role captions (`kinetic_type`, phone-first kinetic captions), or timed `protected` face rectangles. The skill's
other rules (exact words, chunking, placement, the SRT) still hold.

## A learned Look's captions
- **A learned Look overrides generic styling, not exact words or face safety.** Read its role
  hierarchy and measured arrivals first. Sparse giant emphasis and tiny linking are not a uniform
  karaoke preset. Intentional one-word emphasis can stand alone; do not merge it merely to satisfy
  ordinary subtitle chunk rules. Use actual word onsets; check suspicious transcript timings rather
  than treating an ASR timestamp as ground truth. Fixed final phrase positions avoid recentring each
  time a word arrives. kinetic_type phrases plus role defaults/protected boxes carry this without
  hand coordinates; explicit rows/runs support stacks, mixed fonts, internal colour and syllables.
  Measure the full entry/overshoot/exit envelope. If it cannot fit clear of the face, use motivated
  coverage or change the group; shrinking the person to make room isn't a caption fix. Judge native text crops on font,
  size, layout, colour and movement separately; a still or shared accent colour is insufficient [OURS].
  To find a reference's caption font, give `letitedit_fonts` a tight crop of one line with `text` exactly as written:
  it ranks every Google Fonts family and the bundled ones and guesses the weight; pick from its sheet by eye and `get`
  the family if it isn't on this PC (letitedit-graphics section 3) [OURS].

## Whole-time readability for a Look's lettering
`letitedit_caption_readability` on the final edit at 360px (letitedit-captions section 7), then:
- For a Look requesting inverted-then-white lettering, pass `inverted_then_white=true, apply=true` before
  export, after ALL picture work, including cutaways, scenes, lighting and transitions. It chooses one colour
  for every group displayed together at the large-text 3:1 level, testing every fully-on word frame at 360px.
  Exclude the caption's entrance/exit and exact two-frame negative flashes at cuts. Any later picture change
  requires choosing again, not merely reusing a receipt; a stale choice is a major finding.
  Keep Difference when every measured word frame reaches 3:1; otherwise make that entire
  caption plain white. Keep the exact font, size, position, chunking, fades and movement. No added outline,
  edge, box, shadow or mid-caption colour switch; never replace the whole video's treatment with white.
  Read each caption's chosen colour and minimum contrast at 360px. White can still fail on a light picture;
  report that failure, never silently add an aid or pass it. The full-strength colour decision and actual
  delivered contrast are separate measurements, both over fully-on frames, not translucent fades.
  Recheck layout/protected regions without covering the person. Legacy edge options are not this Look's aid.
  `letitedit_look_check` reads that measurement of the current edit itself (or take it as `captions.contrast`), so
  measure after the last picture change and before the Look check; after export repeat it with
  `video` and update the receipt. Unsupported caption kinds need an independently measured conversion, not a pass.
- **Shot-dependent inversion:** when a Look explicitly supplies `caption_colour_policy.mode: shot_dependent`,
  keep inversion through brief contrast dips. Use `letitedit_caption_readability(inverted_then_white=True, apply=True)`
  after the picture is finished: it measures median glyph-core contrast on every fully-on native frame and turns
  a whole cue white only when inversion is below 1.5:1 on more than half those frames. Brief dips are not findings;
  sustained near-invisibility is minor. Missing measurement is not a pass. Preserve every shape, placement and
  animation parameter; no box, edge or shadow. This explicit Look policy overrides the strict 3:1 colour rule only.
- **Picture-following letters:** for a Look with evidenced compositing, use `blend: difference` on `word_captions`
  graphics or `kinetic_type` motion params, or in the captions op's `style`. White Difference and Exclusion have
  the same result; do not claim to know which editor mode the reference used. This is an engine glyph-layer blend,
  not a colour effect on the footage. Keep `box` off, `shadow: null`, no highlight box. Supply timed `protected`
  face rectangles (`box: [left, top, right, bottom]` in frame fractions); layout refuses glyphs entering them.
  Keep linking words readable at 360px, not merely smaller copies of the reference. Inspect busy and mid-grey
  backgrounds: Difference cannot contrast with 50% grey. Use one caption system throughout: the same font
  system, position band and movement over the speaker and b-roll alike. When the chosen Look requests
  inverted-then-white, only colour may differ between captions: choose it for the entire caption's lifetime
  from the whole-time check, not by shot or by one sampled still. Never add an outline to fix mid-grey.
  Keep the timed protected face rectangles on every cue, including linking words and animation peaks. Choose
  a common safe band or revise the layout for the whole system; never solve a collision by covering, dimming
  or colouring the person's face. Check ordinary and kinetic export frames at 360px across both shot types.
- **Readable kinetic roles [OURS]:** for phone-first kinetic captions, start linking words at no less than
  `0.043H` (about 83 px on a 1920-high canvas), then check actual letter ink at 360px. This is a starting floor,
  not proof of readability: increase it when the face, weight or compositing needs more. Preserve the role hierarchy
  by enlarging the system or regrouping, not by retaining unreadably tiny links. Words need a full-opacity readable
  hold; a faint entrance must not consume their reading window. Keep the same arrival treatment across shot types.
- **After the final recut:** regenerate timed protected face rectangles from the final speaker-visible intervals,
  including any newly exposed head before or after a shortened cutaway. Check every cue's movement envelope against
  the actual speaker intervals, not only against whichever old rectangles remain. An empty collision list is not
  evidence of face safety when the timed protection itself has gaps.

## Graphics with picture-coloured caption letters (letitedit-graphics section 6)
Caption glyph blend modes belong on their transparent letters-only layer: the blend changes the letters, not the picture under them.
For a Look with picture-coloured caption letters, keep one caption system across speaker and b-roll: the same
font system, position band and movement, with timed protected face rectangles throughout. Never substitute
solid captions on the speaker or on a mid-grey shot. Any tested readability aid applies equally to every
caption, not as a second style on selected shots; verify the aid after glyph compositing at feed size.
