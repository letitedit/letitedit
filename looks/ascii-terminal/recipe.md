# Theme: ASCII terminal

There is no drawing kit for this Theme: draw it with plain Canvas 2D in a code scene (`letitedit_code_scene`), with the motion runtime's helpers. This is a drawing treatment, not a source-footage grade. `scene.js` beside this recipe draws the Theme's grid picture, the same small boat every drawing Theme draws (its shape names and `X`, `Y`, `K` come from that picture's shared subject): read it as a worked example of the marks, not as a layout.

## What it is
One monochrome terminal screen: every image, title and caption is made of real characters on a monospace grid, chosen by ink density and glowing in amber (or green) phosphor on dark curved glass.

## The marks
- Draw the picture first in grey levels on a hidden canvas aligned exactly to the character grid, average it per cell (draw it down to one pixel per cell with high-quality smoothing) and pick a glyph from a density ramp (` .,:;-~=+*o#%@`).
- Leave dark areas blank: subtract a small threshold before picking, so empty sky and water stay empty. Negative space is what makes ASCII art readable. Prefer clear silhouettes; shadow sides only sparse dots.
- Glyphs in one monospace font (Consolas or Cascadia Mono) drawn to their own canvas, then the same canvas blurred and added twice for the phosphor glow.
- The glass: fine scanlines, a faint rolling band, dark curved corners and a rounded bezel; no RGB grille.
- A prompt line, a status line and a blinking block cursor are characters too.

## Colour
One phosphor carries everything, in its own brightness ramp. At most one soft second colour for one thing, switched on once.

## Movement
Rows are typed in; a cursor blinks as suspense. The only camera is the grid: bigger characters push in, smaller ones pull out. Text that disappears fades quickly like phosphor.

## What it suits
Tech, software, AI, hacking and security stories, retro computing, data.

## Watch-outs
Every dark pixel turned into a character makes a noisy wall: threshold it. Noisy subjects read as blobs: simplify to silhouettes. It is dim at card size: keep the glow generous and the subject large. The scanlines and bezel belong to the drawn screen, never over the person.

Live drawing needs a graphics-capable PC; full-frame blurs, glows and per-piece textures cost time. Draw what does not change once to its own canvas and move the finished canvas. Check the live player and the prepared export at delivery size.

The grid picture is a generated drawing study, not camera footage or approval of a complete video.

## Behind a person
Change only the illustration and backdrop. Keep the person above the drawing; their picture (its size, grade and lighting) is the Look's, and drawn pieces and effects stay off their face where they can. Keep their recorded voice. See the shared drawing-treatment notes for the layer route.

Credit: adapted in our own words from the ASCII / CRT Terminal style recipe by LemoLab (lemo-opuscar, MIT), as collected in cinecode by Sarp Yıldız (MIT). See THIRD-PARTY-NOTICES.md.
