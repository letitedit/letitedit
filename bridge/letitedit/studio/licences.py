"""The licence a Studio result gives each asset and each song: one id from a closed list, with whether a credit is owed
and what the licence says about commercial use (contract/CONTRACT.md, "Licences").

The ids and their terms are LICENCES. Everything else here finds an asset's id from the facts that name it:
    library assets     the library's own manifest for that file (assets/manifest/*.json: its licence, per source or
                       per item), read through letitedit.catalogs.assets
    songs              the library's manifest, or the csv of a song folder that has no manifest entry
    stock              the sidecar beside the downloaded file (the source it came from: Pixabay, Pexels)
    on-demand songs    the sidecar beside the downloaded file (the licence the catalogue stated)
    made here          the producer's receipt (receipts.py): generated pictures and voices, drawn scenes, motion clips
    pictures from the  the real-picture record kept with the file (pictures/real_pictures.py): the rights are not
    web                known, so `unknown`, with the page it came from
Anything these facts do not settle is `unknown`. The credit text for a licence that asks for one is the text
letitedit_export_job and letitedit_review_bundle already list for a project (catalogs/assets.credits).

This is a reading of each licence's text as the packs ship it, not legal advice.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

# id: commercial_use, attribution_required (None: not known), the limits a field cannot hold
LICENCES = {
    'own': ('allowed', False,
            "The person's own file. The rights are theirs to state; letitedit has not checked them."),
    'CC0-1.0': ('allowed', False, None),
    'public-domain': ('allowed', False, None),
    'MIT': ('allowed', False,
            "The licence asks that its copyright notice stay with copies of the files themselves. A video that only "
            "shows the drawn picture owes no line in letitedit's credit list."),
    'CC-BY-4.0': ('allowed_with_credit', True,
                  'Free to use, share and adapt, including commercially, if the creator is credited and a link to the '
                  'licence is given.'),
    'lottie-simple-licence': ('allowed', False,
                              'Attribution is not required and is strongly encouraged. The licence also binds anyone '
                              'who distributes the animation files themselves.'),
    'pixabay-content-licence': ('allowed', False,
                                'Free for commercial use inside an edited work; credit is not required. Not allowed: '
                                'selling or giving the file away unaltered, or implying that a person or brand shown '
                                'endorses something. Take care with identifiable people and brands.'),
    'pexels-licence': ('allowed', False,
                       'Free for commercial use inside an edited work; credit is not required. Not allowed: selling '
                       'or giving the file away unaltered, or implying that a person or brand shown endorses '
                       'something. Take care with identifiable people and brands.'),
    'generated': ('allowed', False,
                  "AI-made by an image service. The makers' terms give the output to the person who asked for it; "
                  'whether AI-made output can be copyrighted is unsettled in some places, and the platforms ask for a '
                  "label on realistic AI media (the result's ai_labels)."),
    'made-by-letitedit': ('allowed', False,
                          "Drawn by letitedit's own code for this video (a scene, a motion clip, a graphic)."),
    'written-for-this-video': ('allowed', False, 'Music written as a score for this video by letitedit.'),
    'made-on-this-pc': ('allowed', False,
                        "Made for this video by a model running on the person's PC. The models' licences (MIT or "
                        'Apache-2.0) allow commercial use; the licences of the data they learned from are not '
                        'assessed.'),
    # 1.6: the bundled and on-demand fonts' licences (SINCE): each lets a font draw a picture or a video's words for
    # any use, commercial included, with no credit owed; their conditions bind the font files themselves
    'OFL-1.1': ('allowed', False,
                'SIL Open Font License 1.1. Pictures and videos drawn with the font may be used commercially with no '
                'credit; the conditions (keep the licence with the font, no selling the font on its own, reserved '
                'names) bind the font files, not what is made with them.'),
    'Apache-2.0': ('allowed', False,
                   'Apache License 2.0. Pictures and videos drawn with the font may be used commercially with no '
                   'credit; the notice conditions bind copies of the font files, not what is made with them.'),
    'Ubuntu-font-1.0': ('allowed', False,
                        'Ubuntu Font Licence 1.0. Pictures and videos drawn with the font may be used commercially '
                        'with no credit; the conditions (keep the licence with the font, no selling the font on its '
                        'own, the Ubuntu names) bind the font files, not what is made with them.'),
    'unknown': ('unknown', None,
                "letitedit could not tell what licence this has, so nothing is claimed. Treat it as not cleared."),
}
IDS = tuple(LICENCES)
COMMERCIAL_USE = ('allowed', 'allowed_with_credit', 'forbidden', 'unknown')
# ids a later minor added: a job of an earlier contract_version gets `unknown` with the licence named in `note` instead
SINCE = {'OFL-1.1': (1, 6), 'Apache-2.0': (1, 6), 'Ubuntu-font-1.0': (1, 6)}
NAMES = {'OFL-1.1': 'SIL Open Font License 1.1', 'Apache-2.0': 'Apache License 2.0',
         'Ubuntu-font-1.0': 'Ubuntu Font Licence 1.0'}


def block(lid, note=None, attribution_text=None, content_id=None):
    """The `licence` object a result carries for this id: the id, whether a credit is owed, commercial use and the
    note; `note` adds to the id's own (a source page, what is known of it)."""
    use, credit, own_note = LICENCES[lid]
    out = {'id': lid, 'commercial_use': use}
    if credit is not None:
        out['attribution_required'] = credit
    if credit and attribution_text:
        out['attribution_text'] = attribution_text
    text = ' '.join(x for x in (own_note, note) if x)
    if text:
        out['note'] = text
    if content_id:
        out['content_id_registered'] = content_id
    return out


def version(text):
    """(major, minor) of a contract_version string; (1, 0) for anything that isn't one (the oldest a job can be)."""
    m = re.fullmatch(r'\s*(\d+)\.(\d+)\s*', str(text or ''))
    return (int(m.group(1)), int(m.group(2))) if m else (1, 0)


def for_version(lic, contract_version):
    """A licence block as a job of this contract_version may see it: an id from a later minor than the job's
    (SINCE) becomes `unknown`, with the licence it is named in `note`, so a caller never meets an id it doesn't know.
    Anything else is returned as it is."""
    lid = (lic or {}).get('id')
    since = SINCE.get(lid)
    if not since or version(contract_version) >= since:
        return lic
    v = version(contract_version)
    return block('unknown', note=f'{NAMES[lid]} ({lid}, read from {_FONT_SOURCE.get(lid, "its licence")}). Contract '
                                 f'{v[0]}.{v[1]} has no id for it ({since[0]}.{since[1]} adds {lid}), so the id is '
                                 f'unknown.')


_FONT_SOURCE = {'OFL-1.1': "the font's own OFL.txt", 'Apache-2.0': "the font's own LICENSE.txt",
                'Ubuntu-font-1.0': "the font's own UFL.txt"}
# what each font licence's own text says first, and the words Google Fonts' metadata uses for it
_FONT_TEXTS = (('OFL-1.1', 'OFL.txt', 'SIL Open Font License, Version 1.1', 'OFL'),
               ('Apache-2.0', 'LICENSE.txt', 'Apache License', 'APACHE2'),
               ('Ubuntu-font-1.0', 'UFL.txt', 'UBUNTU FONT LICENCE Version 1.0', 'UFL'))
FONT_RECORD = 'letitedit-font.json'     # what google_fonts.fetch writes beside an on-demand family


def font_id(path):
    """The licence id of a font file, read from the licence file that ships beside it (the bundled library and the
    Google Fonts families fetched on demand both keep it in the family's folder; an on-demand family's own record
    names which file it is). `unknown` when no licence file there says one of the three (a Windows font, say)."""
    folder = Path(path).parent
    record = _read_json(folder / FONT_RECORD) or {}
    for lid, name, words, meta in _FONT_TEXTS:
        if record.get('licence') and str(record['licence']).upper() != meta:
            continue
        f = folder / (record.get('licence_file') if record.get('licence') else name)
        try:
            text = f.read_text(encoding='utf-8-sig', errors='replace')
        except OSError:
            continue
        if words in text and (lid != 'Apache-2.0' or 'Version 2.0' in text):
            return lid
    return 'unknown'


def of_font(path, contract_version):
    """The licence block of a font file for a job of this contract_version (font_id, then for_version)."""
    lid = font_id(path)
    if lid == 'unknown':
        return block('unknown', note='No licence file beside the font names a licence letitedit knows.')
    return for_version(block(lid), contract_version)


def fonts_for_version(provenance, contract_version):
    """A carried provenance (a retext's, overlays.carry_media) as this job's contract_version may see it, in place: a
    font id from a later minor than the job's becomes `unknown` with the licence named (for_version). It only maps
    down: an `unknown` carried from an earlier result stays as it was, so a retext's provenance equals the earlier
    result's whenever the job may read it."""
    for a in (provenance or {}).get('assets') or []:
        if isinstance(a, dict) and isinstance(a.get('licence'), dict):
            a['licence'] = for_version(a['licence'], contract_version)
    return provenance


def for_job(doc, contract_version):
    """Every `licence` object anywhere in a result (provenance assets, music tracks, batch items) as a job of this
    contract_version may see it, in place: what state.write_result does to each result before it is written, so no
    kind, carried or new, can send an id the job's version doesn't know."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == 'licence' and isinstance(v, dict):
                doc[k] = for_version(v, contract_version)
            else:
                for_job(v, contract_version)
    elif isinstance(doc, list):
        for v in doc:
            for_job(v, contract_version)
    return doc


def library_id(text):
    """The id for a licence as a library manifest, a song csv or a download's sidecar words it ('CC0-1.0', 'Public
    domain', 'MIT', 'Lottie Simple License (FL 9.13.21)', 'Pixabay Content License', 'CC0 1.0 (public domain
    dedication)'); `unknown` for anything else."""
    t = re.sub(r'\s+', ' ', str(text or '')).strip().lower()
    if t.startswith('cc0'):
        return 'CC0-1.0'
    if t.startswith('public domain') or t == 'public-domain':
        return 'public-domain'
    if t == 'mit':
        return 'MIT'
    if t in ('cc-by-4.0', 'cc by 4.0') or t.startswith(('cc-by-4.0 ', 'cc by 4.0 ')):
        return 'CC-BY-4.0'
    if t.startswith('lottie simple licen'):
        return 'lottie-simple-licence'
    if 'pixabay' in t:
        return 'pixabay-content-licence'
    if 'pexels' in t:
        return 'pexels-licence'
    return 'unknown'


def _read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _credit_line(entry_id):
    """The credit text the project credit list gives this library asset (catalogs/assets.credits), or None."""
    try:
        import letitedit.catalogs.assets as assets
        found = assets.credits([entry_id])
    except Exception:  # noqa: BLE001 - a credit line never stops a result
        return None
    return found[0]['line'] if found else None


def library_entry(ref):
    """The library entry a path, an entry id or a reference names, or None."""
    try:
        import letitedit.catalogs.assets as assets
        return assets.entry_of_ref(str(ref))
    except Exception:  # noqa: BLE001 - a library that cannot be read knows nothing
        return None


def of_entry(entry):
    """The licence block of a library entry, from its manifest."""
    lid = library_id(entry.get('licence'))
    text = _credit_line(entry['id']) if LICENCES[lid][1] else None
    if LICENCES[lid][1] and not text:                 # a credit is owed and the manifest gave none: say what is known
        text = f"{entry.get('name') or entry['id']} ({entry.get('licence')})"
    return block(lid, attribution_text=text)


_CSV = {}


def _song_csv_licence(path):
    """The id a song's own folder list (library.csv in its music-library or starter-music folder) gives it, or None."""
    p = Path(str(path))
    for parent in p.parents:
        if parent.name.lower() in ('music-library', 'starter-music'):
            csv_path = parent / 'library.csv'
            try:
                key = (str(csv_path), csv_path.stat().st_mtime_ns)
            except OSError:
                return None
            rows = _CSV.get(key)
            if rows is None:
                try:
                    with csv_path.open(encoding='utf-8-sig', newline='') as fh:
                        rows = {(r.get('File') or '').replace('\\', '/').lower(): r.get('License') or ''
                                for r in csv.DictReader(fh)}
                except OSError:
                    rows = {}
                _CSV[key] = rows
            rel = p.relative_to(parent).as_posix().lower()
            return library_id(rows[rel]) if rel in rows else None
    return None


def of_song(source, path=None):
    """The licence block of a music track: its source (the result's music source) and its file."""
    if source == 'written':
        return block('written-for-this-video', content_id='no')
    if source == 'ai_made':
        return block('made-on-this-pc', content_id='no')
    if source in ('person_file', 'in_source_footage'):
        return block('own', content_id='unknown')
    if source == 'pixabay':
        return block('pixabay-content-licence', content_id='unknown')
    if source == 'letitedit_library':
        entry = library_entry(path) if path else None
        lid = library_id(entry.get('licence')) if entry and entry.get('kind') == 'music' else None
        if lid is None and path:
            lid = _song_csv_licence(path)
        lid = lid or 'unknown'
        return block(lid, content_id='no' if lid != 'unknown' else 'unknown')
    if source == 'youtube_audio_library':
        return block('unknown', note="A YouTube Audio Library track carries its own terms (some ask for a credit); "
                                     "they are not read here.", content_id='unknown')
    return block('unknown', content_id='unknown')


def _web_origins(path):
    """The pictures fetched from the web that a file is or was made from (their records), [] for none."""
    if not path or not os.path.isabs(str(path)):
        return []
    try:
        import letitedit.pictures.real_pictures as real_pictures
        return real_pictures.origins_of(str(path))
    except Exception:  # noqa: BLE001 - an unreadable record says nothing
        return []


def web_origin_note(origins):
    """What is known of pictures fetched from the web, for a note: where each came from and the licence its source
    stated, which letitedit has not checked."""
    bits = []
    for o in origins[:3]:
        bits.append(str(o.get('credit_line') or o.get('title') or '').strip())
    more = f' (and {len(origins) - 3} more)' if len(origins) > 3 else ''
    return ('Made from a picture fetched from the web, whose rights are not known. Its source stated: '
            + ' | '.join(b for b in bits if b) + more + '.')


def in_my_assets(path):
    """Whether a file is the person's own, kept in My assets: a path under that folder (the hidden .letitedit folder
    left out) or a `mine:<id>` reference to one of its items."""
    text = str(path or '')
    if not text:
        return False
    try:
        import letitedit.catalogs.my_assets as my_assets
        if text.lower().startswith('mine:'):
            want = text[5:].strip().lower()
            return any(want in (str(i['id']).lower(), str(i['name']).lower(), str(i['rel']).lower())
                       for i in my_assets.items(measure=False))
        if not os.path.isabs(text):
            return False
        root = os.path.normcase(os.path.normpath(str(my_assets.folder())))
        here = os.path.normcase(os.path.normpath(text))
        if not here.startswith(root + os.sep):
            return False
        return not any(part.startswith('.') for part in Path(here[len(root) + 1:]).parts)
    except Exception:  # noqa: BLE001 - a folder that can't be read claims nothing
        return False


def of_asset(x):
    """The licence block of an entry of the result's `provenance.assets` (kind, source, path, ai_generated), from the
    facts that name it. `unknown` when they do not settle it."""
    path = x.get('path')
    kind = str(x.get('kind') or '')
    origins = _web_origins(path)
    if origins:                                       # the rights of a web picture are not known, nor of what it is in
        return block('unknown', note=web_origin_note(origins))
    if in_my_assets(path):                            # the person's own file: no credit line
        return block('own')
    name = Path(str(path)).name.lower() if path else ''
    if name.startswith('stock-') and path:
        row = _read_json(Path(str(path)).with_suffix('.json')) or {}
        lid = library_id(row.get('licence'))
        if lid != 'unknown':
            return block(lid)
    if name.startswith('ondemand-song-') and path:
        row = _read_json(str(path) + '.json') or {}
        return block(library_id(row.get('licence')))
    if kind.startswith('library_') or x.get('source') == 'letitedit_library':
        entry = library_entry(path) if path else None
        if entry:
            return of_entry(entry)
        return block('unknown', note="The file is not in letitedit's asset library.")
    if kind in ('drawn_scene', 'motion_clip', 'graphic') and not x.get('ai_generated'):
        credit = x.get('attribution')
        if credit and 'cc by' in str(credit).lower():       # a map whose place names are CC BY (the picture shows it)
            return block('CC-BY-4.0', attribution_text=str(credit))
        return block('made-by-letitedit')
    if kind in ('generated_voice', 'generated_music'):
        return block('made-on-this-pc')
    if x.get('ai_generated') or kind in ('generated_picture', 'generated_video'):
        return block('generated')
    return block('unknown')


def stock_source(path):
    """(source, page address, title) of a downloaded stock item, from its sidecar; None when it has none."""
    row = _read_json(Path(str(path)).with_suffix('.json')) if path else None
    if not row or not row.get('source'):
        return None
    return str(row['source']), str(row.get('page_url') or ''), str(row.get('title') or '')


def web_picture(path):
    """(source, page address, title) of a picture fetched from the web, from its record; None for any other file."""
    origins = _web_origins(path)
    if not origins:
        return None
    first = origins[0]
    return str(first.get('source') or 'web'), str(first.get('source_page') or ''), str(first.get('title') or '')


def graphic_assets(graphic, span):
    """The library assets a graphic recipe names (its params: asset, image, emoji) as result assets, over `span`:
    each is placed in the video even though no clip names it."""
    params = (graphic or {}).get('params') if isinstance(graphic, dict) else None
    out, seen = [], set()
    for key in ('asset', 'image', 'emoji'):
        ref = (params or {}).get(key)
        if not isinstance(ref, str) or not ref or ref in seen:
            continue
        seen.add(ref)
        entry = library_entry(ref)
        if not entry:
            continue
        try:
            import letitedit.catalogs.assets as assets
            path = assets.abspath(entry['file'])
        except Exception:  # noqa: BLE001
            path = entry.get('file')
        sound = entry.get('kind') in ('sfx', 'music')
        out.append({'kind': 'library_sound' if sound else 'library_sticker', 'what': entry.get('name') or entry['id'],
                    'source': 'letitedit_library', 'path': path, 'ai_generated': False, 'ranges': span,
                    'licence': of_entry(entry)})
    return out
