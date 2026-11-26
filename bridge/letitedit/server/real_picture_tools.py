"""MCP tool: real pictures of named things (bridge/real_pictures.py) - a logo or app, a person, a place, a book, a
product, an animal, a food - from open sources that need no key, fetched into the video's own folder with their record.
Every fetch happens inside this tool's process, so it never needs a permission prompt in any AI."""
from __future__ import annotations

import io
from pathlib import Path

import letitedit.pictures.real_pictures as real_pictures

DOC = """Real pictures of named things (a logo or app, a person, a place, a book, a product, an animal, a food), from open sources that need no key or sign-up: Wikipedia page pictures, Wikimedia Commons files (logos drawn from their SVG to PNG), Openverse, Open Library covers, or an address you found yourself. The fetch runs inside this tool on this PC.

action:
- search: query (the thing's name), kind ('any', 'logo', 'app', 'brand', 'person', 'place', 'book', 'product', 'animal', 'food', 'thing': sets which sources are asked first), sources (a list from wikipedia, commons, openverse, openlibrary), limit (per source, 2-12). Returns a sheet of numbered candidates and for each: ref, source, title, what, page_url, licence, author and restrictions (such as 'trademarked') where the source states them.
- fetch: ref (from search) or url (a Wikipedia, Commons, Openverse or Open Library page, any web page with an og:image picture, or a picture's own address) with page (the page it was on, for the record), project (.mlt) or folder, name (for the file name). Saves the picture in <project>.letitedit/pictures/real-picture-<n>-<name>.jpg|png beside a .json record: source page, picture address, licence as stated, author, restrictions, size, sha256, when fetched. Returns path (usable as a clip, a pop-up or a graphic's image), the record and a preview.
- list: project or folder. Every real picture fetched for that video, with its record.
- made_from: path (a file you made) and from_files (the files you made it from). For a file made outside letitedit's own tools (your own script, another program): records the real pictures behind it in <path>.origin, so their credit lines follow it into exports and reviews. Replies with the originals it carries (none when from_files holds no real picture and nothing made from one).

Facts: only pictures are taken (the bytes are checked: JPEG, PNG, GIF, WebP, BMP or TIFF; SVG only through Wikimedia's PNG drawing), 25 MB and 60 megapixels at most, from public addresses only, saved only into the video's pictures folder. Exports (letitedit_export_job) and reviews (letitedit_review_bundle) list a credit line for every real picture a project uses, from its record, once each, and for what is made from one: letitedit_image (references and edits) and letitedit_motion write a <file>.origin record beside what they make from a real picture; graphics, motion items, shot effects and code scenes in a project are read for the pictures they draw. The record holds the originals' credit lines whole, so it works through chains and after the original is deleted. Offline: the reply says so (offline True) and nothing is saved."""


def _preview(path, size=640):
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        im.thumbnail((size, size))
        bg = PILImage.new('RGB', im.size, (200, 200, 200))
        rgba = im.convert('RGBA')
        bg.paste(rgba, mask=rgba)
        buf = io.BytesIO()
        bg.save(buf, 'JPEG', quality=85)
        return buf.getvalue()


def run(action='search', query=None, kind='any', sources=None, limit=6, ref=None, url=None, page=None, project=None,
        folder=None, name=None, path=None, from_files=None, Image=None):
    """The tool's reply as a list: pictures (when Image is given) then one dict."""
    if action == 'search':
        res = real_pictures.search(query, kind, sources, limit)
        if res.get('candidates') and Image is not None:
            return [Image(data=real_pictures.sheet(res['candidates']), format='jpeg'), res]
        return [res]
    if action == 'fetch':
        res = real_pictures.fetch(ref=ref, url=url, page=page, project=project, folder=folder, name=name)
        if res.get('path') and Image is not None and Path(res['path']).exists():
            return [Image(data=_preview(res['path']), format='jpeg'), res]
        return [res]
    if action == 'list':
        rows = real_pictures.history(project, folder)
        return [{'count': len(rows), 'pictures': rows}]
    if action == 'made_from':
        if not path or not from_files:
            raise ValueError('made_from needs path (the file you made) and from_files (the files it was made from)')
        row = real_pictures.made_from(path, from_files, tool='letitedit_real_picture', strict=True)
        if row is None:
            return [{'recorded': False, 'path': path, 'note': 'None of from_files is a real picture or made from one, so nothing was recorded.'}]
        return [{'recorded': True, 'path': path, 'record': str(path) + real_pictures.ORIGIN_SUFFIX,
                 'credits': [o['credit_line'] for o in row['origins']]}]
    raise ValueError("action is 'search', 'fetch', 'list' or 'made_from'")


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_real_picture(action: str = 'search', query: str | None = None, kind: str = 'any',
                               sources: list[str] | None = None, limit: int = 6, ref: str | None = None,
                               url: str | None = None, page: str | None = None, project: str | None = None,
                               folder: str | None = None, name: str | None = None, path: str | None = None,
                               from_files: list[str] | None = None) -> list:
        return run(action, query, kind, sources, limit, ref, url, page, project, folder, name, path, from_files, Image=Image)

    letitedit_real_picture.__doc__ = DOC
