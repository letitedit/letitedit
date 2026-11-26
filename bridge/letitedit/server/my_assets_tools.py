"""MCP tool: My assets (bridge/my_assets.py) - the person's own logo, intro, outro, colours, clips, sounds, pictures and
fonts, kept in one folder that works on every video."""
from __future__ import annotations

import letitedit.catalogs.my_assets as my_assets


def _place(it):
    """Edits that put an item in a video (letitedit_timeline_apply), for the one-item view."""
    ref, path = it['ref'], it['path']
    if it['kind'] in ('intro', 'outro', 'clip'):
        d = it.get('duration_s') or 5.0
        return {'insert': {'op': 'insert', 'track': '<a video track>', 'at': 0.0 if it['kind'] == 'intro' else '<end>',
                           'item': {'clip': path, 'in': 0, 'out': d}},
                'note': 'A clip is placed like footage; an intro goes first and an outro last, so the clips after '
                        'move along (picture changes on the main track carry the rest with them).'}
    if it['kind'] == 'sound':
        return {'sound_at_a_moment': {'op': 'insert', 'track': 'Effect sounds', 'at': 5.0,
                                      'item': {'clip': path, 'in': 0, 'out': round(min(it.get('duration_s') or 2.0, 8.0), 3)}},
                'fx_item': {'at': 5.0, 'kind': 'sfx', 'sfx': ref}}
    if it['kind'] in ('logo', 'picture'):
        return {'popup_fx_item': {'at': 5.0, 'kind': 'popup', 'len': 2.0, 'asset': {'image': path}},
                'overlay': {'op': 'insert', 'track': 'Effects', 'at': 5.0, 'item': {'image': path, 'len': 3.0}},
                'note': 'A logo or picture goes on an overlay track (position and size in the item) or as a pop-up '
                        'sticker; the ref works wherever a style or an op takes an asset.'}
    return {}


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_my_assets(id: str | None = None, note: str | None = None, description: str | None = None,
                            kind: str | None = None, add: list[str] | None = None, remove: str | None = None,
                            sheet: bool = True) -> list:
        r"""My assets: a folder where the person keeps their own logo, intro, outro, colours, clips, sounds, pictures and fonts
        (Documents\letitedit\My assets, or `my_assets_dir` in settings.json), the same folder whichever video is open, which
        stays when letitedit is reinstalled. The person's files are only read; adding copies a file in, removing moves
        its copy to the folder's hidden .letitedit
emoved.
        - nothing: what is there - per item an id, a ref (`mine:<id>`, which letitedit_assets, styles, pop-ups and
          graphics accept like any asset - licence 'own', no credit line; an edit's `clip` or `image` takes the item's `path`), its kind (logo, intro, outro, clip, sound, picture,
          font, colours) and where the kind came from (the file name, a guess from the file, or the person), length,
          size, transparency, the colours measured from the picture, and `text`: the person's note, else a description
          an AI saved, else a sentence built from the measured facts. Also the colours (a colour set's list, else the
          logos'), and a contact sheet of the pictures and clips. Empty is normal: most people have nothing there.
          Facts are measured once and kept; a file that is slow to open (still downloading from Google Drive) reads
          `problem` or `measuring` and is measured on a later call.
        - id (or `mine:<id>`, a file name): that item in full, a picture of it (a still on a chequer so a transparent
          logo shows, or a strip of frames for a clip) and edits that place it.
        - description (with id): what you saw, one sentence, kept with the item; kind (with id) sets its kind
          (the person's own kind outranks a guess); note (with id): the person's words, kept as they are, never
          overwritten by a description; an empty string clears a field.
        - add: file or folder paths copied in; remove: an id."""
        if add:
            r = my_assets.add(add)
            return [r]
        if remove:
            return [my_assets.remove(remove)]
        if id and (note is not None or description is not None or kind is not None):
            it = my_assets.set_note(id, note=note, description=description, kind=kind)
            return [{'saved': it['id'], 'kind': it['kind'], 'text': it['text']}]
        if id:
            it = my_assets.get(id)
            pics = []
            if sheet:
                pic = my_assets.look_picture(it['id'])
                if pic:
                    pics.append(Image(path=pic))
            info = {k: v for k, v in it.items() if k not in ('thumb', 'rel')}
            info['place'] = _place(it)
            return pics + [info]
        its = my_assets.items()
        out = my_assets.summary(its)
        if not its:
            out['note'] = ("Nothing in My assets yet: the person has not added a logo, intro, outro, clips, sounds "
                           "or colours. That is normal; carry on without.")
            return [out]
        pics = []
        if sheet:
            pic = my_assets.sheet(its)
            if pic:
                pics.append(Image(path=pic))
        return pics + [out]
