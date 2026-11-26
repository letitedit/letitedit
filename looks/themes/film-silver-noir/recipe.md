# Silver noir

Monochrome with deep shadows, bright silver highlights and a natural, readable face. Simply removing colour, or adding a small contrast multiplier to flat grey, is not the finished treatment. Noir reads through separated light/dark planes and the direction and shape of existing light, not a black silhouette.

- **Light and grade:** remove chroma, then balance person and room separately with the live face window (face lifted, room pulled down). Deepen existing room shadows with an S-curve, lift existing practical reflections/highlights, and give the face a gentler curve. Keep cheek shape, eyes, hair and clothing separable. Hard directional light and shaped shadows are useful when recorded; a soft source cannot acquire a new lamp, hard blinds, cigarette smoke or cast shadow from this grade. Keep a bypassable original.
- **Pace and cuts:** hold an uncertain look or a significant detail long enough to read; a decisive hard cut can mark a turn. Use fewer decorative transitions. Do not make ordinary dialogue sinister by reordering its meaning.
- **Framing:** use existing diagonals, doorways or contrasting planes when they help. Give the subject room to look; do not cut off hands to force a film ratio. Wide delivery may use an intentional crop only after checking every shot.
- **Music feel:** sparse brush, piano or low sustained tones if the story calls for it; avoid the automatic saxophone cliche. Leave silence available around a meaningful line.
- **Captions:** white on a dark solid backing, with enough separation from bright silver highlights. No distressed type that damages letters.
- **Optional scene texture:** available film grain, very subtle at delivery size. Grain should not erase detail or make text shimmer; apply before caption layers.

**Evidence:** E1 and E3 support high-contrast/light-dark motifs associated with noir; E2 supports purposeful cut-ins. Exact contrast and score are creative choices, not a requirement to crush blacks. Apply shared limits in film-treatment-notes.md.

## Measured starting points, not a universal LUT

Read the picture at phone size and sample actual image regions at 1 fps, excluding captions, labels and letterbox bands. Measure display-referred RGB luma on a 0-1 scale, not camera exposure stops or IRE. A useful starting range for an already dark background is a low percentile around 0.01-0.03; a small existing bright reflection can approach 0.90-0.98. Do not force every shot's 99th percentile to white: sparse highlights may occupy much less than 1% of a restaurant frame. Avoid broad clipping below 0.02 or above 0.98 in expressive skin. Compare eyes, cheek modelling, hair and moving hands against the original, not only a histogram. [Creative starting points; low generalisability]



One reproducible room starting curve, after desaturation, is input/output `0/0, 0.18/0.055, 0.40/0.30, 0.60/0.80, 0.78/0.965, 1/1`. The gentler person curve is `0/0.006, 0.16/0.10, 0.40/0.40, 0.65/0.76, 0.85/0.94, 1/1`. The editor's live filters approximate it (Saturation, Levels, Color Grading lift, gamma and gain, the face window); record the parameters. Adapt per shot and match before styling, rather than copying numbers blindly. If the window edge shows on hair, collar or moving hands, reduce the difference or widen and soften the window; if protection cannot remain believable, use a gentler global curve and report the reduced separation. Do not regenerate faces or pretend a fixed mask follows an actor.
