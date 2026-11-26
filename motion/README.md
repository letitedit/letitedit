# Motion clips (letitedit_motion)

Animated titles, lower thirds, kinetic text, count-ups, charts, end cards and the like, written as HTML/CSS/JS and
rendered frame by frame by the **HyperFrames** engine (Apache-2.0, HeyGen) into a ProRes 4444 `.mov` with alpha that
sits on an overlay track. Code: `bridge\motion.py` (engine, pages, render, timeline item), `bridge\motion_tools.py`
(the MCP tool), tests `bridge\tests\pictures\test_motion.py`.

| Folder | What | Versioned |
|---|---|---|
| `runtime\looks\<name>.js`, `.md` | Drawing hands: a medium's marks and paper for a canvas scene, loaded and hashed only when a script says `M.look.<name>`; the guide is `letitedit_motion(action='hands', block=<name>)`. Built from `runtime\looks-src` with `node runtime\looks-src\build.mjs` (our esbuild, at build time only). Based on anidoodle, Apache-2.0. | yes |
| `runtime\motion.js` | Our animation runtime (`M`): easing, `M.prog`, `M.set`, text split/fit, seek hookup. Every frame is a function of t. | yes |
| `blocks\*.js` | Our 14 blocks. Each starts with a `/*@block {json} @*/` header (title, about, duration, params, docs) that the tool reads. | yes |
| `engine\` | `npm install hyperframes@0.8.214` (package.json + package-lock.json versioned, node_modules not) | lock only |
| `chrome\` | chrome-headless-shell 152.0.7977.30 (the version HyperFrames 0.8.214 pins), via @puppeteer/browsers. Optional: this PC only, never shipped | no |
| `node\` | portable Node 22.12+ (`node\node.exe`; the installer puts the build PC's there); else Node on PATH | no |
| `LICENSE-hyperframes.txt` | Apache-2.0 text for the engine (the npm package ships none) | yes |
| `LICENSE-node.txt` | Node.js's licence, shipped as `node\LICENSE.txt` | yes |

## The browser it draws with

Optional shaders are in `runtime\shaders\`, with their MIT licence copies and source catalogue. A custom scene calls
`M.shader.<name>(context2D, t, options)`; `letitedit_motion(action="shaders")` lists the operations and settings.
Only named ingredients are loaded and saved into that scene's page. No shader is enabled by default.
`runtime\shaders\README.md` describes the canvas inputs, settings, status and non-WebGL fallback.

HyperFrames draws each frame in a Chromium browser in headless mode. On Windows it captures frames as screenshots
(its BeginFrame mode is Linux-only), which every Chromium browser does, so `motion.browser_exe()` takes, in order:
`LETITEDIT_MOTION_BROWSER` (any Chromium browser's exe), the pinned chrome-headless-shell when `chrome\` holds it, the
PC's own **Microsoft Edge** (on every Windows 10/11 PC), then **Google Chrome** (found through Windows' App Paths entries
and their usual folders; builds older than 140 are skipped). `python bridge\motion.py status` says what it uses.
Puppeteer starts the browser with its own temporary profile, so the person's Edge or Chrome windows, profile and
sign-ins are never touched.

Measured 30 Oct 2026 (`tools\motion\compare_browsers.py`, all 13 blocks at 540x960 30 fps, 1,953 frames; each run
drew through ANGLE on Direct3D 11, the GPU HyperFrames' "auto" mode picks on this PC): Edge 156.0.4314.50 and Chrome
156.0.8078.76 drew the same frames as the pinned headless Chrome 152.0.7977.30, 86% of them bit for bit; the rest
differ on at most 0.1% of the pixels, on anti-aliased glyph edges. The location tag at 1080x1920 as ProRes 4444 came
out as the same 12,138,007-byte file from all three. Edge took 8-22% longer than the pinned shell, Chrome 4-15%.

## When it can't run

No Node, no engine, no browser (or a render that stops): `letitedit_motion` preview and render return the reason, and
a `{motion: ...}` item placed on a timeline (directly, by a style's effect or a pop-up) is drawn as its nearest graphic
template instead (`motion.FALLBACKS`: location and lower_third -> lower_third, title -> title_card, chapter and steps
-> chapter_card, count_up and bar_chart -> big_number, end_card, callout, subscribe -> badge, kinetic_quote and
word_captions -> word_captions, a stinger's text -> text_pop; nothing stands in for custom code), with a note in the
edit's reply. `style_pack.py --check` lists motion presets under `notes`, not `problems`, while motion can't render.

## Rules

- **No GSAP.** Its licence is not GPL-compatible, so no HyperFrames catalog blocks and no GSAP in our pages.
  `motion.check_code` refuses GSAP, network URLs/fetch, timers/rAF/clock reads and `Math.random` in custom code;
  `test_motion` holds our own blocks to the same rules.
- **Nothing leaves the PC.** Every engine run sets `HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`,
  `HYPERFRAMES_NO_UPDATE_CHECK=1`, `HYPERFRAMES_NO_AUTO_INSTALL=1`, `HYPERFRAMES_SKIP_SKILLS=1`, and
  `python bridge\motion.py setup` also writes `telemetry disable` into its config. Fonts are copied from the
  bundled library next to each page.
- **One heavy job at a time.** Renders hold the PC render lock; 2 Chrome workers.

## Setting it up on a new PC

The installer ships `blocks\`, `runtime\`, `engine\` (node_modules without type definitions, source maps and readmes)
and `node\node.exe`; nothing to set up. For a development copy, from the letitedit folder:

```
cd motion\engine && npm ci --ignore-scripts && cd ..\..
python bridge\motion.py setup
```

The pinned headless Chrome is optional (Edge or Chrome draw the same frames); to have it anyway, from the letitedit folder:
`node -e "import('@puppeteer/browsers').then(b=>b.install({browser:b.Browser.CHROMEHEADLESSSHELL,buildId:'152.0.7977.30',cacheDir:'motion/chrome'}))"`

The engine keeps its own small files in the person's home folder: `.hyperframes\` (its config with telemetry off, and
a list of recent runs) and `.cache\hyperframes\` (run history). They are not removed on uninstall.

## Measured (29 Oct 2026, Ryzen 7 3700X / RTX 2070 Super)

- 2 s at 1080p30, transparent ProRes: 8 s. A preview of 6 stills: ~4 s.
- Nine clips (37 s of motion) at 1080x1920, 59.94 fps placed by one `letitedit_timeline_apply`: 309 s the first time,
  35 s again with only one block changed (cache by recipe + block source + runtime + kit).
