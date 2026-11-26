"""MCP tool letitedit_motion: make a motion clip (animated title, lower third, kinetic text, count-up, chart, end
card...) from our own blocks or your own HTML/CSS/JS, rendered by the HyperFrames engine (motion.py).

    run(action, ...)   same as the tool, without MCP
    job(ctx)           the 'motion_tools:job' job kind (a long render as a background job)
"""
from __future__ import annotations

import json
from pathlib import Path

import letitedit.pictures.motion as motion

JOB_KIND = 'motion_tools:job'
JOB_OVER_S = 90.0       # job=None: estimated renders above this many seconds run as a background job

DOC = """Make a motion clip: an animated title, lower third, kinetic quote, word captions, count-up, bar chart, steps
checklist, location tag, callout, subscribe nudge, chapter card, stinger or end card - from our own blocks, or your
own HTML/CSS/JS - rendered frame by frame by the HyperFrames engine (headless Chrome, on this PC, nothing uploaded)
into a ProRes 4444 .mov with alpha that sits on an overlay track over the footage.

action 'blocks': every block with what it is for, its params and their defaults (start here).
action 'hands': optional drawing kits a canvas scene may call for a real medium's marks and paper; with block=<name>, that kit's guide.
action 'shaders': optional MIT-licensed WebGL ingredients (backgrounds, filters, transitions); block=<name> gives settings.
  A canvas scene calls M.shader.<name>(context2D, t, options). Only named shaders and their runtime are saved in the scene.
  With no WebGL: backgrounds use colorA, filters keep the source, transitions crossfade in 2D. Nothing is applied by default.
action 'preview': stills at `times` (seconds) or `count` (default 6) spread over the clip -> a frame sheet. Transparent
  parts show as a checkerboard, or put the graphic over the footage with background={clip, at} (a frame of that file
  at `at` s) or a colour. ~4 s. Look at it before rendering or placing.
action 'render': the whole clip at `size` (default [1920, 1080]) and `fps` (default 30), or at the project's size and
  frame rate with project= (written to <project folder>\\made). Returns the file, a frame sheet and the timeline item.
  job: None = a background job (letitedit_jobs) when the estimate is over 90 s; True/False = always/never.
  Renders hold the PC render lock (one heavy job at a time).

Placing it (letitedit_timeline_apply): add a video track above the picture, then
  {op: insert, track: <that track>, at: <timeline s>, item: {motion: {block, params, duration}, len?}}
The item renders on placement (cached by its recipe), draws in the project's Look (colours and fonts) unless it
names `look`, and stays editable: {op: set, id, motion: {params: {...}}} re-renders it. len cuts it shorter; the
clip's own `duration` sets its timing (exits play at the end of `duration`).

What it runs on: Node (motion\\node\\node.exe, else node on PATH) and a Chromium browser in headless mode - the
headless Chrome HyperFrames pins when it is in motion\\chrome, else the PC's own Microsoft Edge or Google Chrome
(LETITEDIT_MOTION_BROWSER names another); action 'blocks' says which, or why it can't run. Where it can't run, preview
and render return the reason, and a {motion: ...} item placed on a timeline is drawn as the nearest graphic template
instead, with a note in the edit's reply (location and lower_third -> lower_third, title -> title_card, chapter and
steps -> chapter_card, count_up and bar_chart -> big_number, end_card -> end_card, callout -> callout, subscribe ->
badge, kinetic_quote and word_captions -> word_captions, a stinger's text -> text_pop; nothing for custom code).

Spec (top-level arguments, or spec={...}; the arguments win):
  block   one of the blocks below, or 'custom'
  params  {...} the block's params (unknown keys are refused; colours are kit names - primary, secondary, accent,
          dark, light - or #rrggbb; fonts are kit names - heading, body, captions - or any bundled family name)
  duration  seconds (default: the block's)
  look    Look id for colours and fonts (default: the project's, or the neutral defaults)
  format  mov (ProRes 4444 + alpha, default) | mp4 (H.264, transparent parts black) | png (folder of RGBA frames)
Your own design (block 'custom'): html (put inside the stage), css, script. The script calls
  M.block('custom', (stage, p, c) => { ...build once...; return (t) => { ...set styles from t alone... } })
  with the runtime's helpers: M.prog(t, start, dur, ease), M.life(t, len, in, out), M.ease.{out, inOut, expoOut,
  backOut, elasticOut, bounceOut...}, M.set(el, {o, x, y, s, sx, sy, r, clip: [t, r, b, l], blur}), M.el(tag, opts,
  parent), M.split(el, 'words'|'chars'), M.fit(el, size, maxW, maxH), M.num(v, decimals, sep, prefix, suffix),
  M.rand(seed); c = {w, h, len, fps, u (px per 1080p px), portrait, color(ref), font(ref), style(el, font, size,
  color)}; p = params.
  Also in the runtime (motion-plus.js; the same names exist in code scenes):
    M.spring(t, {stiffness 170, damping 26, mass 1, from 0, to 1, delay}) a spring's value t s after it is let go
      (damping ratio = damping / (2 sqrt(stiffness x mass)): below 1 it overshoots, 1 is the fastest approach without)
    M.springSettle(opts) s until that spring rests within 0.2%; M.springEase(overshoot) an easing function, for M.prog,
      that arrives that far past the target (0.08 = 8%) and rests by x = 1; 0 is the fastest approach with none
    M.bezier(x1, y1, x2, y2) a CSS cubic-bezier as an easing function (y outside 0..1 overshoots)
    M.ease also has sineInOut, quartOut, quintOut, quartIn, quartInOut, circOut, smooth (zero speed and acceleration at
      both ends), backOutSoft (3% overshoot; backOut is 10%) and anticipate (winds back first, then overshoots)
    M.stagger(i, n, {each, total, from: start|end|center|edges|random, seed}) the delay in s of item i of n
    M.world.pictures({name: 'file:///...'}) at the top of the script loads real pictures before the first frame ({images, done, missing});
    M.world.path(keys [{t, x, y, z}], t) -> {x, y, z}, a camera through keys that never stops at one; M.world.offPage(keys, page, w, h, pxPerWorld,
    fps) -> the times the view leaves a page; M.world.back(heroes [[from, to, id]], id, t, fade) -> 0 while id is the hero, 1 once it is not.
    M.typed(str, t, start, rate) letters shown; M.camera(keys [{t, z, x, y, ease}], t) -> {x, y, z}, zoom eased in log
      space; M.parallax(cam, depth) -> {x, y, s} for a layer (0 does not move, 1 moves with the camera, above 1 is nearer)
  Canvas helpers, loaded when the script mentions M.draw (you write the scene; these are parts to use or ignore):
    M.draw.family = the font typeText/popText use; shade(hex, +-amount), rr, fillRR, disc, poly, tube, limb(g, a, b, w0, w1)
    M.draw.camera(g, t, {t0, t1, z0, z1, ox, oy, px, py}, w, h) a push or pan clamped so the plate's edge never shows
    M.draw.typeText(g, str, x, y, size, t, t0, colour, {rate, weight, align, family, alpha}) letters that arrive large and
      settle in 0.18 s, returns the end time; popText(...) a word that springs in; redX(...); splat(g, t, t0, {color, w, h})
      a 0.2 s in, 0.2 s out wipe; blur(g, drawFn, t, {n 3, shutter 0.5, fps}) averages n draws across part of a frame
      (n times the drawing time)
    M.draw.person(g, {x, y (ground), h, t, view front|side, dir, walk {phase}, arms [[x, y], [x, y]] hand targets, hands,
      look, speak, mouth, smile, brow, lean, hop, head, hair, seed, skin, shirt, pants, shoe}) -> {head, hand, shoulder, feet};
      a walker's feet stay planted when the body moves 1.5 leg lengths per phase 0..1 (leg = 38 x h / 100 px)
  A scene is plain code: it can be written from scratch in any look, with nothing below. Optional drawing kits (a medium's marks and
  paper) load when the script names one as M.look.<name>; action 'hands' lists them when asked.
  Fonts: a param named font or ending in font ("title_font") holds a bundled family name or {family, weight}; the page then
  declares it, and every declared face is loaded before the first frame, so a canvas can use it (ctx.font = '800 80px "Montserrat"'). Refused: GSAP (licence), any network URL or fetch, timers/rAF/clock reads, Math.random - every
  frame must be a function of t so renders are exact and repeatable. SVG, canvas (draw in render(t)), CSS
  transforms, clip-path, filters, gradients and blend modes all work.

Blocks:
"""


SPEC_KEYS = ('block', 'params', 'duration', 'look', 'format', 'html', 'css', 'script')


def _doc():
    try:
        return DOC + '\n'.join('  ' + ln for ln in motion.blocks_text().splitlines())
    except Exception as e:  # noqa: BLE001
        return DOC + f'  (blocks unavailable: {e})'


def _project_profile(project):
    import letitedit.timeline.edit_script as es
    doc = es.read(project)
    prof = doc['profile']
    return [int(prof['width']), int(prof['height'])], float(prof['fps']), Path(project).parent / 'made'


def build_spec(spec=None, **kw):
    s = dict(spec or {})
    if 'pack' in s or 'pack' in kw:
        raise ValueError('pack selection was removed; look takes a Look id')
    s.update({k: v for k, v in kw.items() if k in SPEC_KEYS and v is not None})
    return s


def job(ctx):
    inp = ctx.inputs
    r = motion.render(inp['spec'], inp['size'][0], inp['size'][1], inp['fps'], out_dir=inp.get('out_dir'),
                      out=inp.get('out'), progress=lambda f, m=None: ctx.progress(min(0.95, f), m))
    return {'file': r['path'], 'sheet': r.get('sheet'), 'item': {'motion': _item_spec(r['spec'])}}


def _item_spec(s):
    return {k: v for k, v in s.items() if k not in ('format', 'kit')}


def engine_text():
    """One line: what motion clips render with here, or why they can't."""
    st = motion.status()
    if not st['ready']:
        return f"can't render on this PC: {st['reason']}"
    b = next((x for x in st['browsers'] if x['path'] == st['browser']), {'kind': 'browser', 'version': ''})
    name = {'shell': 'headless Chrome (pinned)', 'edge': 'Microsoft Edge', 'chrome': 'Google Chrome'}.get(b['kind'],
                                                                                                       st['browser'])
    return f"ready: HyperFrames on Node {st.get('node_version') or ''} drawing with {name} {b['version']}".strip()


def _unavailable(norm):
    why = motion.available()
    if why:
        g = motion.fallback_graphic(norm)
        raise RuntimeError(f"motion clips can't render on this PC: {why}. Placed on a timeline, this block is drawn as "
                           + (f"the {g['template']} graphic instead." if g else 'an empty clip (no graphic stands in for it).'))


def _hands(name=None):
    """action 'hands': the drawing kits, or one's guide (block=<name>). The list only appears when asked for."""
    have = motion.hands()
    if name:
        guide = motion.LOOKS / f'{name}.md'
        if name not in have or not guide.is_file():
            raise ValueError(f"no drawing kit called {name!r} (have: {', '.join(have) or 'none'})")
        return {'text': guide.read_text(encoding='utf-8'), 'hand': name}
    try:
        about = json.loads((motion.LOOKS / 'catalogue.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        about = {}
    lines = ["Drawing kits: optional marks and paper a canvas scene may call. A scene doesn't need one: any scene can be written from "
             "scratch in code, in a look made for this video. In alphabetical order; block=<name> gives a kit's functions.", '']
    for n in have:
        row = about.get(n)
        if row:
            lines.append(f"{n}: {row['what']} Moves: {row['moves']} Can suit: {row['suits']} Speed: {row['speed']}")
        else:
            guide = motion.LOOKS / f'{n}.md'
            lines.append(f"{n}: {guide.read_text(encoding='utf-8').splitlines()[0].lstrip('# ') if guide.is_file() else n}")
    return {'text': '\n'.join(lines) if have else 'no drawing kits on this PC', 'hands': have}


def run(action='preview', spec=None, size=None, fps=None, project=None, out=None, count=6, times=None,
        background=None, job=None, **kw):
    if action == 'blocks':
        return {'text': motion.blocks_text() + '\n\nengine: ' + engine_text(),
                'blocks': {k: {x: v[x] for x in ('title', 'about', 'duration', 'params')}
                           for k, v in motion.blocks().items()},
                'engine': engine_text()}
    if action == 'hands':
        return _hands(kw.get('block'))
    if action == 'shaders':
        rows = json.loads((motion.SHADERS / 'catalogue.json').read_text(encoding='utf-8-sig'))
        name = kw.get('block')
        if name and name not in motion.shaders():
            raise ValueError(f'no shader called {name!r}')
        selected = [row for row in rows if not name or row['name'] == name]
        guide = (motion.SHADERS / 'README.md').read_text(encoding='utf-8')
        return {'text': guide + '\n\n' + '\n'.join(f"{row['name']} ({row['kind']}, MIT): {json.dumps(row['defaults'])}" for row in selected),
                'shaders': selected}
    s = build_spec(spec, **kw)
    out_dir = None
    if project:
        size, fps, out_dir = _project_profile(project)
        if not s.get('look') and not s.get('kit'):
            import letitedit.timeline.edit_script as es
            s['kit'] = motion.kit_snapshot(es.kit_for(es.read(project)))
    w, h = size or [1920, 1080]
    fps = float(fps or 30.0)
    norm = motion.normalise(s)
    if action in ('preview', 'render'):
        _unavailable(norm)
    if action == 'preview':
        r = motion.preview(norm, w, h, fps, count=count, times=times, background=background, out=out)
        text = (f"preview of {motion.describe(norm)}: {len(r['times'])} stills at {w}x{h}, {norm['duration']} s clip, "
                f"made in {r['seconds']} s\nsheet: {r['sheet']}"
                + (f"\nfonts not found (fallback used): {r['missing_fonts']}" if r.get('missing_fonts') else ''))
        return {'text': text, 'sheet': r['sheet'], 'times': r['times'], 'frames': r['frames'],
                'item': {'motion': _item_spec(norm)}}
    if action != 'render':
        raise ValueError("action must be 'blocks', 'hands', 'shaders', 'preview' or 'render'")
    est = motion.estimate_s(norm, w, h, fps)
    if job or (job is None and est > JOB_OVER_S):
        import letitedit.core.jobs as jobs
        st = jobs.submit(JOB_KIND, {'spec': norm, 'size': [w, h], 'fps': fps,
                                    'out_dir': str(out_dir) if out_dir else None, 'out': out},
                         label=f"motion clip {motion.describe(norm)}")
        return {'text': f"job {st.get('id') or st.get('job_id')} queued: {motion.describe(norm)}, {w}x{h} {fps:g} fps, "
                        f"{norm['duration']} s (estimate {est:.0f} s; letitedit_jobs to follow it)",
                'job': st, 'estimate_s': round(est), 'item': {'motion': _item_spec(norm)}}
    r = motion.render(norm, w, h, fps, out_dir=out_dir, out=out)
    text = (f"{'cached' if r['cached'] else 'rendered'} {r['path']} ({r['format']}"
            f"{', alpha' if r['alpha'] else ''}, {w}x{h}, {fps:g} fps, {norm['duration']} s"
            + (f", {r['seconds']} s" if r.get('seconds') is not None else '') + ')'
            + f"\nsidecar: {r['sidecar']}\nsheet: {r.get('sheet')}"
            + (f"\nfonts not found (fallback used): {r['missing_fonts']}" if r.get('missing_fonts') else '')
            + "\ntimeline item (letitedit_timeline_apply): {motion: <item in the result>}")
    return {'text': text, 'sheet': r.get('sheet'), 'file': r['path'], 'item': {'motion': _item_spec(norm)},
            'result': {k: v for k, v in r.items() if k != 'spec'}}


def register(mcp, Image):
    def letitedit_motion(action: str = 'preview', block: str | None = None, params: dict | None = None,
                         duration: float | None = None, look: str | None = None, format: str | None = None,
                         html: str | None = None, css: str | None = None, script: str | None = None,
                         spec: dict | None = None, size: list[int] | None = None, fps: float | None = None,
                         project: str | None = None, out: str | None = None, count: int = 6,
                         times: list[float] | None = None, background: str | dict | None = None,
                         job: bool | None = None) -> list:
        try:
            rep = run(action, spec=spec, size=size, fps=fps, project=project, out=out, count=count, times=times,
                      background=background, job=job, block=block, params=params, duration=duration, look=look,
                      format=format, html=html, css=css, script=script)
        except (FileNotFoundError, ValueError, KeyError, RuntimeError, TimeoutError) as e:
            return [{'error': f'{type(e).__name__}: {e}'}]
        outl = []
        if rep.get('sheet') and Path(rep['sheet']).exists():
            outl.append(Image(data=Path(rep['sheet']).read_bytes(), format='jpeg'))
        outl.append(rep['text'])
        outl.append({k: v for k, v in rep.items() if k not in ('text', 'blocks')} if action != 'blocks'
                    else {'engine': rep['engine']})
        return outl
    letitedit_motion.__doc__ = _doc()
    mcp.tool(structured_output=False)(letitedit_motion)
