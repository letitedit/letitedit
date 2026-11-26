# Optional shaders

`M.shader.<name>(context2D, t, options)` draws into a scene's 2D canvas. `t` is seconds on the scene's playhead, not a clock.
Nothing runs unless named. `letitedit_motion(action="shaders")` lists the catalogue; `block="film"` returns its settings.
The runtime and only the named shaders are copied into the saved scene page. Existing revisions keep those copies.

| Name | Picture operation | Options (defaults are in catalogue.json) |
|---|---|---|
| simplex2D | Moving 2D simplex noise mapped to two colours | scale, speed, colorA, colorB |
| classic2D | Moving classic 2D noise mapped to two colours | scale, speed, colorA, colorB |
| simplex3D | Animated slice through 3D simplex noise | scale, speed, colorA, colorB |
| film | Time-varying grain and optional grayscale | intensity, grayscale |
| vignette | Radial edge shading | offset, darkness |
| rgbShift | Offsets red and blue samples | amount (fraction), angle (radians) |
| horizontalBlur | Nine-sample horizontal blur | h (fraction of image width) |
| verticalBlur | Nine-sample vertical blur | v (fraction of image height) |
| crossWarp | Warped transition between images | progress |
| directionalWipe | Directional soft-edged wipe | progress, direction [x,y], smoothness |
| fade | Linear blend between images | progress |
| filmBurn | Film-burn transition | progress, Seed |

Colours are three RGB numbers in 0..1. Filters accept `source` (a canvas/image, default the destination canvas).
Transitions accept `from` and `to` (canvases/images) and `progress` (0..1). Every call accepts `x`, `y`, `width`, `height` in
destination canvas pixels; defaults cover the whole canvas. Source images are stretched to that rectangle. The caller's
2D transform, clipping and global alpha also apply. Filters process shader RGB directly; no colour-space conversion is added.

The return value, also `M.shader.last`, reports `{ok, name, renderer, reason?}`. When WebGL is unavailable, lost or cannot
compile/draw: backgrounds fill `colorA`; filters leave the existing canvas or draw `source`; transitions use a plain 2D
crossfade. Other scene layers continue drawing. A restored context recompiles on the next call. Software WebGL uses the same
shaders without requiring a discrete GPU. Browser/driver arithmetic may differ; fallback intentionally omits the effect.

```javascript
M.shader.simplex2D(g, t, {scale: 4, speed: 0.3, colorA: [0.04, 0.1, 0.2], colorB: [0.2, 0.6, 0.7]});
M.shader.film(g, t, {intensity: 0.15});
```

Sources, authors, pinned revisions and SHA-256 checksums: `catalogue.json`. Original files and MIT licence copies are beside it.
The `.shader.js` registrations wrap those sources for this canvas API; FilmShader's common include is replaced with local
rand/luminance functions. All other fragments retain their source equations; noise and transitions add uniform/main wrappers.
