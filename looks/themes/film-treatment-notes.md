# Film treatments: shared limits and evidence

These are recipes, not one-click filters or promises of new physical lighting. The Look owns cuts, timing, framing and music; a treatment owns colour, light and texture. Its pace, framing and music notes are suggestions for what the Look leaves open, never a reason to re-cut or reframe the Look's edit. Read the selected treatment with the video's Style, Look and brief. The brief wins; leave out an ingredient that harms the actual footage. Start from the source, keep a bypassable copy, and record omitted ingredients in the review.

## Light without replacing the person

Light and grade with the editor's live filters only, the way the letitedit-lighting skill does it: a soft oval window that follows the face lifts it a little and the room outside a wider oval is pulled down (`{op: fx, lighting: ...}`). A treatment's room colour (cooler, warmer, softer) goes on the same kind of feathered, face-following oval with the mask inverted (`{op: aim, on: clip, region: {shape: ellipse, path, soft, invert: true}}`), so the face keeps its own colour unless the treatment means to change it. Never grade through a cut-out or matte, and no model relighting or depth shaping. No generative face replacement and no new model downloads. Keep original facial shading and skin texture. A whole-picture grade reaches the face too, as the treatment means it to; keep it gentle enough that skin still reads as skin (its hue near the skin-tone line, its detail intact). This does not move the original lights, remove their shadows, recover clipped detail or rebuild lighting.

The room oval also covers hair, shoulders and clothes. Check moving hair, glasses and hands at the beginning, middle, end and fastest motion, and a zoomed crop of the neck, collar and hairline: no line may show where the window ends. If one does, widen the window, soften the feather or reduce the room change, and report it.

On footage, texture is the editor's live filters on the clip (Grain, Vignette), used only when the selected recipe calls for it; a vignette stays at the edges, off the face. The code-scene API offers film grain, vignette and filmBurn transitions for drawn scenes and graphic handovers, not a glow helper. A canvas shader treats that scene's pixels, not the footage below it: never insert an opaque shader background over the person. Grain stays subtle at final delivery size; bypass effects when they cover captions or faces, or fail in the export. Do not require an uncommitted helper or write a new engine effect.

## Captions and delivery

Use exact spoken words, phrase-sized groups and enough reading time; keep names together. Prefer white type on a near-opaque dark backing, clear of eyes, hands demonstrating something and platform buttons. Keep type neutral across all six treatments so the content remains readable. A starting caption style is Inter, 23 px at 360 px width, on #14171c. Refit position and size to the picture; this is not a platform compliance certificate. Refit for each aspect ratio. Never put captions in a letterbox bar that the platform crops away.

Do not add widescreen bars to a vertical talking head just to signal cinema. On a wide film delivery, use an intentional crop only after checking faces, hands and objects in every shot. A treatment must not rewrite the spoken claim or turn ordinary footage into an invented time, place or event.

## Evidence ledger

- **[Educational / medium] E1:** Yale Film Analysis, Cinematography: lighting contrast, foreground/background relationships and repeated colour patterns are film-language tools; colour has no exclusive universal meaning. https://filmanalysis.yale.edu/cinematography/
- **[Educational / medium] E2:** Yale Film Analysis, Editing: cut-ins can direct attention, establishing/re-establishing shots orient space, and dissolves connect shots. These describe choices, not a mandatory cut frequency. https://filmanalysis.yale.edu/editing/
- **[Critical history / medium] E3:** BFI / Sight and Sound, How the French birthed film noir: bands of light and darkness are a recurring noir motif. This is not evidence for crushing blacks or manufacturing blinds across a face. https://www.bfi.org.uk/sight-and-sound/features/how-french-birthed-film-noir
- **[Film studies / medium] E4:** Hugo Jordan, Universite Gustave Eiffel, September 2025: frontal views, geometry and symmetry can be deliberate framing language. Use the principles, not a director's name as a quality claim. https://reflexscience.univ-gustave-eiffel.fr/en/read/articles/wes-anderson-the-craft-of-cinema-takes-centre-stage-in-an-exhibition-at-the-cinematheque-francaise
- **[Practitioner / medium, one production] E5:** Steve Hullfish interviews Brendan Bellomo about Porcelain War, Art of the Cut, 13 February 2025: subjects and emotional structure inform pace. Do not generalise one documentary's choices into a universal rule. https://borisfx.com/blog/aotc/art-of-the-cut-porcelain-war/
- **[Standard / strong for web contrast, adapted to video] E6:** W3C WCAG 2.2 contrast minimum: 4.5:1 for ordinary text, 3:1 for large text. Here 4.5:1 is a useful design check, not a claim of formal moving-video conformance. https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
Live window grading needs no download; no depth or relighting model is used, and none can undo baked-in shadows.

Exact grade strengths, palettes, musical descriptions and suggested shot holds below are **[Creative starting points / low]**, not experimentally proved emotion or engagement effects. No universal BPM, seconds-per-cut or retention promise is implied. Change them for the story and performance.

## What the previews demonstrate

Previews compare grading, not finished stories, scores, long-video consistency or all-platform delivery. Approval is set in the app.
