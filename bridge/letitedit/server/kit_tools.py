"""MCP tools: fonts, Look defaults, Python graphics and the engine's effects catalogue.

Placing graphics, restyling captions, scoring music and adding effects are edits, done with letitedit_timeline_apply;
these tools are for choosing: which fonts exist, what a kit looks like, what a graphic or an effect will look like
before it goes in.
"""
from __future__ import annotations

from pathlib import Path

import letitedit.timeline.effects_catalog as effects_catalog
import letitedit.catalogs.fonts as fonts
import letitedit.pictures.graphics as graphics
import letitedit.looks.look_library as look_library


HOOK_APPROACHES = ('result_first', 'question', 'stakes', 'number', 'quote', 'mid_action')


def _hook_text(entry):
    text = entry.get('text')
    text = [text] if isinstance(text, str) else list(text or [])
    text = [str(x).strip() for x in text if str(x).strip()]
    if not 1 <= len(text) <= 3:
        raise ValueError(f'a hook to add needs 1-3 text options (text: [...]): {entry!r}')
    return text


def _add_hooks(project, entries):
    """letitedit_hooks' add: the AI's own candidates written into hooks.json (footage/hooks.py's format). Returns the
    ids written (new ones, or the ids whose text was rewritten)."""
    import letitedit.footage.hooks as hooks
    if not isinstance(entries, list):
        raise ValueError('add is a list of candidates: [{from | id | source, text: [...]}, ...]')
    built = hooks.build(project)
    path = Path(built['project'])        # the project's .mlt, as hooks.json names it
    written = []
    with hooks.locked(path):
        data = hooks.load(path) or built
        cands = data['candidates']
        by_id = {c['id']: c for c in cands}
        n = max((int(c['id'][1:]) for c in cands if str(c.get('id', '')).startswith('h') and c['id'][1:].isdigit()),
                default=0) + 1
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f'a hook to add is a dict: {entry!r}')
            text, by = _hook_text(entry), str(entry.get('by') or 'ai')
            if entry.get('id'):
                c = by_id.get(str(entry['id']))
                if c is None or c['id'] == 'h0':
                    raise ValueError(f"no hook candidate {entry['id']!r} to rewrite (h0 is the cut's own opening)")
                c.update(text=text, by=by, status='new')
                for k in ('preview', 'preview_sheet', 'preview_key'):
                    c.pop(k, None)
                written.append(c['id'])
                continue
            if entry.get('from'):
                base = by_id.get(str(entry['from']))
                if base is None:
                    raise ValueError(f"no hook candidate {entry['from']!r} to add text to")
                c = {k: v for k, v in base.items() if k not in ('preview', 'preview_sheet', 'preview_key')}
            else:
                src = entry.get('source') or {}
                if not (isinstance(src, dict) and src.get('clip') and float(src.get('out', 0)) > float(src.get('in', 0))):
                    raise ValueError(f'a hook to add needs from: <id> or source: {{clip, in, out}} with out after in: {entry!r}')
                approach = entry.get('approach') or 'quote'
                if approach not in HOOK_APPROACHES:
                    raise ValueError(f"approach is one of {', '.join(HOOK_APPROACHES)}")
                c = {'approach': approach, 'label': str(entry['label']) if entry.get('label_given') and entry.get('label')
                     else approach.replace('_', ' '),
                     'source': {'clip': str(src['clip']), 'in': round(float(src['in']), 3),
                                'out': round(float(src['out']), 3)},
                     'timeline': None, 'in_cut': False, 'item_id': None, 'said': entry.get('said') or '',
                     'score': 0.0, 'signals': {}, 'effects': []}
            c.update(id=f'h{n}', text=text, by=by, status='new', order=len(cands),
                     why=str(entry.get('why') or c.get('why') or ''))
            n += 1
            cands.append(c)
            by_id[c['id']] = c
            written.append(c['id'])
        hooks.save(path, data)
    return written


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_fonts(query: str | None = None, category: str | None = None, families: list[str] | None = None,
                      text: str | None = None, offset: int = 0, limit: int = 30, features: dict | None = None,
                      like: str | None = None, picture: str | None = None, invert: bool | None = None,
                      get: str | None = None, where: str = 'all') -> list:
        """Fonts you can use anywhere (captions, titles, graphics): ~300 bundled open-licence families, Windows' own,
        and every Google Fonts family (about 1,950, open licences), which comes down to this PC when chosen.
        - Search by mood or shape (query: 'rounded', 'playful loud', 'handwritten', 'vintage', 'condensed',
          'stencil', 'futuristic', 'brush'...), category (Sans Serif | Serif | Display | Handwriting | Monospace),
          features (measured shape, every one must hold: weight (a number or 'bold', 'black'...: the family offers it),
          italic, script ('latin', 'cyrillic', 'devanagari'...), monospace, serif, slab, rounded, heaviness
          (light|normal|heavy), width (condensed|normal|wide), x_height (small|normal|tall), contrast
          (low|medium|high), slant (upright|slanted)), like (a family: nearest in measured shape first), or name
          `families`. where: 'all', 'pc' (on this PC now) or 'google'.
        - picture (a crop of real text, one line is best) with text (exactly what it says, capitals as shown): every
          Google Fonts family drawn with that text and ranked against the crop (shape, width, ink, stroke), with the
          weight that fits best. The sheet shows the crop above each match.
        - get: a Google Fonts family's files and licence come down to this PC (once; then it stays), where exports and
          the editor's preview draw it; open editor windows load it.
        Returns a sheet (each family drawn in itself or in `text`) and the list: family, weights, source ('library',
        'windows', 'on-demand' or 'google' = not on this PC yet), on_pc, shape, scripts, licence. A Google family
        used by name in an edit or a graphic before get also comes down then. Offline: the reply says so."""
        import letitedit.catalogs.google_fonts as google_fonts
        if get:
            res = google_fonts.fetch(get)
            if res.get('offline'):
                return [res]
            return [Image(data=fonts.sample_sheet([res['family']], text=text, limit=1), format='jpeg'), res]
        if picture:
            if not text:
                raise ValueError('say what the crop says (text), capitals as they appear')
            res = google_fonts.match_picture(picture, text, limit=max(1, min(limit, 20)), invert=invert,
                                             category=category, features=features, candidates=families)
            if not res['families']:
                return [res]
            return [Image(data=google_fonts.match_sheet(picture, res['families'], text, invert=invert), format='jpeg'), res]
        if families and not (features or like):
            pc = {r['family'].lower(): r for f in families for r in fonts.search(f, limit=200)['families']
                  if r['family'].lower() == f.lower()}
            rows = []
            for f in families:
                if f.lower() in pc:
                    rows.append(pc[f.lower()] | {'on_pc': True})
                elif google_fonts.entry(f):
                    rows.append(google_fonts.describe(google_fonts.entry(f)))
            res = {'total': len(rows), 'families': rows}
        elif features or like or where == 'google':
            res = google_fonts.search(query, category, features, like, limit=limit, offset=offset)
            if where == 'pc':
                res['families'] = [r for r in res['families'] if r['on_pc']]
        else:
            pc = fonts.search(query, category, limit=10000)
            pc_rows = [r | {'on_pc': True} for r in pc['families']]
            seen = {r['family'].lower() for r in pc_rows}
            gf = google_fonts.search(query, category, limit=10000) if where != 'pc' else {'families': []}
            extra = [r for r in gf['families'] if r['family'].lower() not in seen]
            rows = pc_rows + extra
            res = {'total': len(rows), 'on_pc': len(pc_rows), 'google_only': len(extra),
                   'families': rows[offset:offset + limit]}
        names = [r['family'] for r in res['families']]
        if not names:
            return [{'total': 0, 'families': [], 'note': 'No match; try a broader word, fewer features or a category.'}]
        sheet = fonts.sample_sheet(names, text=text, limit=limit)
        return [Image(data=sheet, format='jpeg'), res]

    @mcp.tool(structured_output=False)
    def letitedit_looks(action: str = 'list', id: str | None = None, kind: str | None = None,
                       title: str | None = None, changes: dict | None = None, expected_revision: str | None = None,
                       project: str | None = None, inputs: str | None = None, unused: dict | None = None,
                       popups: list | None = None, assets: dict | None = None, sheet: bool = True) -> list:
        """Looks: recipes and defaults for captions, fonts, colours, graphics, effects, pop-ups, hooks, b-roll,
        lighting, editing, music and export. Each edit can override the defaults. LOOK-SETTINGS.md describes them.
        - action='list': offered library and personal Looks, with content-fit, kind, recipe and example paths.
          kind='short' or 'long' filters by length. Unapproved, removed and private library entries stay hidden.
        - action='get', id=<Look id>: the full recipe, measured sibling files and settings. A library Look's values are
          only the ones it sets itself; a personal Look's are resolved in full. With sheet=True, includes a contact
          sheet of the example when available. letitedit_look observes footage; this reads a Look.
          Archived ids remain readable for existing projects; this does not approve them for new selections.
          Unmigrated personal preferences are read-only and marked as such; reading never copies their files.
        - action='settings', id=<Look id>: the same settings with portable file mappings; omit id for the neutral
          defaults, which fill in code whatever a Look doesn't set.
        - action='copy', id=<Look id>, title=<optional name>: a new private personal Look in My Looks, using Learn's
          store. The source is unchanged. Private Looks remain private even after a copy or update.
        - action='update', id=<personal id>, changes={...}, title=<optional name>: a new immutable revision. Nested
          objects merge; lists, scalars and null replace. Other settings, recipes and measurements are kept.
          expected_revision detects a changed source. assets maps relative resource references to local files copied
          into the new revision. No upload, project edit or migration runs.
        - action='inputs', project=<.mlt>, inputs=<record path or 'read'>: the Look's collected files and roles beside
          the project; unused={file path: reason} records why a supplied file was not used.
        - action='popups', project=<.mlt>, popups=[{words, asset, ...}]: read or replace project-specific pop-ups;
          popups=[] clears them. Omit popups to read.
        A project selects a Look with {op: look, id: <id or null>}; null selects neutral defaults.
        fx, popups and hook edits use its resolved defaults without removing their generic options."""
        import letitedit.looks.look_library as look_library
        result = look_library.query(action, id, kind=kind, title=title, changes=changes,
                                    expected_revision=expected_revision, project=project, inputs=inputs,
                                    unused=unused, popups=popups, assets=assets)
        import letitedit.server.next_step_replies as next_step_replies         # T345 C2, behind its own switch
        short = next_step_replies.looks_get_reply if action == 'get' else (lambda r: r)
        if action == 'get' and sheet and result.get('preview'):
            import letitedit.looks.looks as looks
            picture = looks.sample_sheet(id)
            if picture:
                return [short({**result, 'sample_sheet': picture}), Image(path=picture)]
        return [short(result)]

    @mcp.tool(structured_output=False)
    def letitedit_hooks(project: str, count: int = 6, exclude: list[str] | None = None, more: bool = False,
                      refresh: bool = False, preview: list[str] | None = None, mark: dict | None = None,
                      add: list[dict] | None = None) -> list:
        """Opening candidates for a project, in about a second, from what this PC already knows (the cut's own
        source files' cached transcripts, cached emotion graphs and picture facts when they exist, the cut itself):
        each a moment (source clip, in, out; where it plays in the cut now, if it does), 2-3 on-screen text options
        in the speaker's words, the approach (result_first, question, stakes, number, quote, mid_action), why, the
        signals and a score (a ranking for showing order, not a quality judgement). Candidates are distinct: the
        approaches take turns and no two use the same words. Returns the next `count` not shown yet, how many are
        left after them, and the cut's own opening as 'h0'. Listing marks nothing, so the person's New hook button
        in the app still offers them; page on with exclude, record what you showed or ruled out with mark.
        Kept in <project stem>.letitedit/hooks.json (LOOK-SETTINGS.md, 'Hooks'), which the app's Regenerate button reads; you
        may rewrite a candidate's text or add your own there (by: claude | codex).
        - more=True: search deeper (shorter cuts of good lines, weaker lines); also happens by itself when few left.
        - refresh=True: score again (it happens by itself when the cut changed; marks are kept).
        - exclude: candidate ids not to return.
        - preview: candidate ids to render: a low-res MP4 of the opening with that hook and a frame strip each (the
          export engine, under the PC render lock; about 20 s each, cached).
        - mark: {id: 'rejected' | 'new' | 'shown'}.
        - add: candidates of your own, written into hooks.json in this call (status 'new', so the app's New hook
          button offers them too): each {from: <candidate id>, text: [1-3 options]} (that candidate's moment with
          your text), {id: <candidate id>, text: [...]} (that candidate's text rewritten), or {source: {clip, in,
          out}, text: [...], approach?, why?}; by: 'claude' | 'codex' | another name (default 'ai'). The reply's
          `added` names their ids; they are not listed again among the candidates.
        mark and add are written before the candidates are listed.
        Swap the opening with letitedit_timeline_apply {op: hook, candidate: <id>, text: <option index>} (one undo
        step; 'h0' takes an added hook out again)."""
        import letitedit.footage.hooks as hooks
        if mark:
            for cid, status in mark.items():
                hooks.mark(project, [cid], status)
        if add:
            import letitedit.server.next_step_replies as next_step_replies     # T345 C2, behind its own switch
            add = next_step_replies.fit_hooks(add, HOOK_APPROACHES)
        added = _add_hooks(project, add) if add else []
        out = hooks.candidates(project, count=count, exclude=list(exclude or ()) + added, refresh=refresh, more=more,
                               mark_shown=False)
        if add:
            out['added'] = added
        pics = []
        for cid in preview or []:
            r = hooks.preview(project, cid)
            pics.append(Image(path=r['sheet']))
            out.setdefault('previews', {})[cid] = r
        return pics + [out]

    @mcp.tool(structured_output=False)
    def letitedit_graphic(template: str | None = None, params: dict | None = None, len: float | None = None,
                        look: str | None = None, code: str | None = None, times: list[float] | None = None,
                        background: str | None = None, width: int = 1920, height: int = 1080,
                        background_at: float | None = None) -> list:
        """Python-drawn graphics. Without template: what can be drawn: 'custom' (your own draw(ctx) code, with the
        ctx helpers), 'word_captions' (captions that follow the words) and the Look's own saved templates, each
        with its params. With template: frames of it at `times` (default in, middle, out) over a checkerboard or a
        picture (background = an image file, or a video file with background_at = the frame's time, default its
        middle), to see it before placing it.
        template 'custom' takes `code` defining draw(ctx) (ctx helpers are listed under custom); it runs in its own
        process with a time limit (120 s plus 0.5 s per frame). A frame that can't change (draw doesn't read ctx.t or
        ctx.frame and no anim_in/anim_out is in progress) is drawn once and held, so a long, mostly still graphic
        renders about as fast as a short one. Colours/fonts in params can be kit names (primary, accent, dark, light / heading,
        body, captions) or literal values. Place with letitedit_timeline_apply:
          {op: insert, track: Graphics, after: <id> | at_start: true, item: {graphic: {template, params}, len: 4}}
        and change later with {op: set, id, graphic: {params: {...}}} (it re-renders)."""
        kit = look_library.kit(look)
        if not template:
            return [{'templates': graphics.template_info(kit)}]
        recipe = {'template': template, 'params': params or {}}
        if len:
            recipe['len'] = len
        if code:
            recipe['code'] = code
        img = graphics.preview(recipe, width, height, 30.0, kit=kit, times=times, background=background or 'checker',
                               background_at=background_at)
        return [Image(data=img, format='jpeg'), {'recipe': graphics.normalise(recipe, kit)}]

    @mcp.tool(structured_output=False)
    def letitedit_effects(query: str | None = None, name: str | None = None, params: dict | None = None,
                        preview_clip: str | None = None, at_s: float | None = None, kind: str | None = None) -> list:
        """Every effect the editor's engine can apply (~760: the editor's own filters (as in Shotcut), frei0r, MLT, LADSPA/SoX audio,
        FFmpeg avfilter.*): find one, read its settings, see it. Add it to a clip's `effects` with
        letitedit_timeline_apply as
          {filter: NAME, params: {prop: value, prop2: {keys: [[t, v], [t, v, ease], ...]}}}
        t = seconds from the clip's start (the timeline's, for track/master effects); ease (optional) = how the value
        moves on to the next key: linear (default), hold, smooth, ease_in, ease_out, ease_in_out, ... List only the
        settings you change; the rest keep the engine's defaults. NAME = a name listed here (vignette, blur_gaussian,
        audio_compressor, frei0r.glow, avfilter.eq...) or the editor's display name. Values: numbers, '#rrggbb' or
        '#aarrggbb' colours, rectangles 'x y w h' in pixels or 'x%/y%:w%xh%'.
        - no args: categories with a short list of effects in each (kind='video' | 'audio' narrows any listing)
        - query='film grain': matching effects, one line each: name | title | what it does | keyframable settings
        - name='vignette': every setting (type, range, default, keyframable), what it needs, an example entry;
          with params, also flags setting names it doesn't have
        - name + preview_clip=<media file> (+ at_s, params): before/after of one frame rendered by the export
          engine (audio effects: waveforms and levels before/after)."""
        if kind and kind not in ('video', 'audio'):
            raise ValueError("kind is 'video' or 'audio'")
        if name and preview_clip:
            img = effects_catalog.preview(name, params, preview_clip, at_s=at_s)
            return [Image(data=img, format='jpeg'), effects_catalog.describe(name, params)]
        if name:
            return [effects_catalog.describe(name, params)]
        if query:
            return [effects_catalog.listing(query, kind=kind)]
        return [effects_catalog.overview(kind)]

    @mcp.tool()
    def letitedit_vfx_effects(effect: str | None = None) -> str:
        """Shot effects and narration you can put on the timeline as items (made clips): things that follow an object
        (arrow, circle, box, spotlight), blur/pixelate faces or plates, erase an object, new background behind a person,
        text behind a person, clone, person cut-out, sky replacement, speed ramps, Blender 3D (tool pop-up, explosion
        behind you, moving landscape, your own Blender script), light leaks, and a narrated line in a local voice. Lists every
        effect with its params, defaults and what it makes, plus all made-item forms. Insert with
        letitedit_timeline_apply, e.g. {op: insert, track: V1, after: <id>, item: {vfx: {effect, source: {clip, in, out},
        params: {...}}}} or {op: insert, track: A1, item: {voice: {text: '...'}}}. effect: only that effect."""
        import letitedit.timeline.made as made
        import letitedit.pictures.vfx_items as vfx_items
        if effect:
            return vfx_items.describe_one(effect)
        lines = (made.__doc__ or '').splitlines()
        start = next((i for i, ln in enumerate(lines) if ln.startswith('    {')), len(lines))
        end = next((i for i in range(start, len(lines)) if not lines[i].strip()), len(lines))
        forms = '\n'.join(ln[2:] for ln in lines[start:end])
        return 'MADE ITEMS (clips made from clips; insert/set like any clip):\n' + forms + '\n\n' + vfx_items.describe()
