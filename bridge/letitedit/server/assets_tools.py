"""MCP tool: the asset library (bridge/assets.py) - emoji, icons, stickers, graphics, transitions, sound effects and
music letitedit can place, searched in one index with their licences."""
from __future__ import annotations

import letitedit.catalogs.assets as assets


def _snippets(r):
    """Edits that place a resolved asset (letitedit_timeline_apply), for the one-asset view."""
    at = 5.0
    if r['kind'] in assets.SOUND:
        out = round(min(float(r.get('duration_s') or 2.0), 8.0 if r['kind'] == 'sfx' else 30.0), 3)
        peak = r.get('peak_s')
        return {'sound_at_a_moment': {'op': 'insert', 'track': 'Effect sounds' if r['kind'] == 'sfx' else 'Music 1',
                                      'at': at, 'item': {'clip': r['file'], 'in': 0, 'out': out}},
                'fx_item': {'at': at, 'kind': 'sfx', 'sfx': r['file'],
                            **({'sfx_offset_s': -round(float(peak), 3)} if peak and r['kind'] == 'sfx' else {})},
                'note': ('peak_s is where the sound is loudest: start it peak_s before the moment to land the hit on '
                         'it (fx: sfx_offset_s = -peak_s). Make the track first if it is missing: '
                         "{op: add_track, name: 'Effect sounds', kind: audio}.")}
    if r.get('graphic'):
        g = r['graphic']
        return {'popup_fx_item': {'at': at, 'kind': 'popup', 'len': 2.0, 'asset': {'graphic': g}},
                'insert': {'op': 'insert', 'track': 'Effects', 'at': at,
                           'item': {'graphic': g, 'len': 2.0 if r['kind'] != 'transition' else
                                    float(r.get('duration_s') or 2.0)}},
                'note': ('asset_sticker params: x, y (0-1), size, fit (sticker | width | cover | contain), in/out '
                         '(pop, fade, slide_*, drop, spin, shrink, none), loop, speed, texts (a graphic\'s own '
                         "texts), shadow, outline. A transition goes over the cut: start it len/2 before. Make the "
                         "track first if it is missing: {op: add_track, name: 'Effects', kind: video}.")}
    return {'popup_fx_item': {'at': at, 'kind': 'popup', 'asset': {'image': r['file']}},
            'popup_entry': {'words': '<a word said>', 'asset': {'image': r['file']}},
            'note': 'A still picture: the pop-up sticker draws it (size, position, in/out, outline, shadow).'}


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_assets(query: str = '', kinds: list[str] | None = None, limit: int = 24, offset: int = 0,
                         id: str | None = None, animated: bool | None = None, credit_ok: bool = True,
                         size_px: int | None = None, color: str | None = None, style: str | None = None,
                         sheet: bool = True) -> list:
        """The asset library: everything letitedit can drop into a video, searched in one index, each with its
        licence. Kinds: emoji (Microsoft Fluent Emoji, still, 3d/color/flat; Google's Noto animated emoji),
        icon (Tabler line and filled icons, any colour), sticker (animated arrows, stars, boxes, speech/thought/shout
        bubbles, subscribe button), graphic (animated title boxes, lower third, banner; their texts replaceable),
        transition (animated full-frame wipes), sfx (CC0 sound effects: pops, whooshes, risers, glitches, impacts,
        dings, cash, cheers, laughs, record scratches, clicks, voices, animals, stings...), music (CC0 songs by
        genre and mood).
        - query: words to find ('fire', 'whoosh fast', 'thumbs up', 'cash register', 'speech bubble', or an emoji
          character), kinds: limit to some kinds, animated: True/False for animated or still only; credit_ok=False
          leaves out assets whose videos owe a credit line (Noto animated emoji: CC BY 4.0).
          Returns a sheet (pictures as tiles, animations marked, sounds as loudness curves with their peak) and
          one line per result: id, name, kind, length, licence.
        - id (or a ref like 'emoji:rocket', 'sfx:whoosh', 'anim:party'): that asset ready to place - its file (a
          PNG for pictures: SVGs drawn by the export engine at size_px in `color`, Tabler outline/filled or Fluent
          3d/color/flat by `style`), length, where a sound peaks, licence, credit, and edits that place it with
          letitedit_timeline_apply ({op: fx} pop-ups and sounds, {op: insert} on an overlay track).
        - nothing: what the library holds (counts per kind and source, licences, what ships).
        Styles name assets the same way (asset: 'emoji:fire', sfx: 'whoosh'); STYLES.md section 7."""
        if id:
            r = assets.resolve(id, size_px=size_px, color=color, style=style)
            info = {k: v for k, v in r.items() if k not in ('tags',)}
            info['tags'] = r.get('tags', [])[:20]
            info['place'] = _snippets(r)
            if r.get('credit'):
                info['credit_note'] = 'A video that shows this owes the credit line in its description or credits.'
            pics = []
            if sheet and not str(r['id']).startswith('file:'):
                pic = assets.strip(r['id']) if r.get('animated') else assets.preview([r['id']], title=r['id'])
                pics.append(Image(path=pic))
            return pics + [info]
        if not query and not kinds:
            st = assets.stats()
            st['refs'] = ("emoji:<name> | anim:<name> | icon:<name> | sticker:<name> | graphic:<name> | "
                          "transition:<name> | sfx:<words> | music:<words> | an id | a file path")
            return [st]
        res = assets.search(query, kinds=kinds, limit=limit, offset=offset, animated=animated, credit_ok=credit_ok)
        lines = []
        for e in res['results']:
            bits = [e['id'], e['kind'], e['name']]
            if e.get('duration_s'):
                bits.append(assets._fmt_s(e['duration_s']) + (f" (peak {e['peak_s']:.2f} s)" if e.get('peak_s')
                                                              is not None and e['kind'] == 'sfx' else ''))
            if e.get('animated'):
                bits.append('animated')
            bits.append(e.get('licence') or '')
            if e.get('credit'):
                bits.append('credit needed')
            lines.append(' | '.join(str(b) for b in bits if b))
        out = {'query': query, 'total': res['total'], 'by_kind': res['by_kind'], 'shown': len(lines),
               'offset': offset, 'results': lines}
        if res['partial']:
            out['note'] = 'Nothing matched every word; these match some of them.'
        if not lines:
            out['close'] = assets.suggestions(query, kinds)
            return [out]
        if sheet:
            return [Image(path=assets.preview(res['results'], title=f"{query or 'all'} ({res['total']})")), out]
        return [out]
