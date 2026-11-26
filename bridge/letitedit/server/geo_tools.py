"""MCP tool: GPS coordinates and nearest place of media files (geo.place)."""
from __future__ import annotations

import letitedit.footage.geo as geo


def places(path, min_population=0, limit=500):
    """{'files': [{'file', 'lat', 'lon', 'alt_m', 'source', 'place': {...}, 'text'} or {'file', 'gps': None}],
    'places': [{'place', 'files'}], 'text'} for a folder (not searched below), a list of paths, or one file."""
    import letitedit.server.core_tools as core_tools
    files, _, _ = core_tools._collect(path)
    files = [f for f in files if core_tools._kind(f) in ('video', 'image', 'audio')]
    shown = files[:max(1, int(limit))]
    rows, groups, lines = [], {}, []
    for f in shown:
        got = geo.place(f, min_population=min_population)
        if not got:
            rows.append({'file': str(f), 'gps': None})
            lines.append(f'{f.name}  no GPS')
            continue
        rows.append({'file': str(f), **got})
        where = f"{got['lat']:.5f}, {got['lon']:.5f}" + (f" alt {got['alt_m']:.0f} m" if got.get('alt_m') is not None
                                                          else '')
        lines.append(f"{f.name}  {where}" + (f"  {got['text']}" if got.get('text') else ''))
        if got.get('text'):
            key = geo.place_text({**got['place'], 'km': 0}).rsplit(' (', 1)[0]
            groups.setdefault(key, []).append(f.name)
    with_gps = sum(1 for r in rows if r.get('gps', True) is not None)
    head = [f'{len(shown)} media files' + (f' (first {len(shown)} of {len(files)}; limit={limit})'
                                           if len(files) > len(shown) else '')
            + f': {with_gps} with GPS in their metadata, {len(shown) - with_gps} without']
    if groups:
        head.append('Nearest places: ' + '; '.join(f'{k} ({len(v)} files)' for k, v in
                                                   sorted(groups.items(), key=lambda kv: -len(kv[1]))))
    if not geo.available():
        head.append(f'No places dataset in {geo.DATA}: coordinates only.')
    head.append(f'Places: GeoNames {geo._source_file().name if geo.available() else "(missing)"} '
                f'(CC BY 4.0), nearest by great-circle distance'
                + (f', population >= {min_population}' if min_population else '') + '.')
    return {'files': rows, 'places': [{'place': k, 'files': v} for k, v in groups.items()],
            'min_population': min_population, 'text': '\n'.join(head + [''] + lines)}


def register(mcp, Image):
    @mcp.tool(structured_output=False)
    def letitedit_places(path: str | list[str], min_population: int = 0, limit: int = 500) -> list:
        """Where media files were recorded, from their own metadata: GPS coordinates (QuickTime/MP4 location tags
        such as com.apple.quicktime.location.ISO6709 and 'location', or a photo's EXIF GPS) and the nearest place
        (name, admin1 region, country code, distance in km) from the offline GeoNames cities1000 dataset (places of
        1000+ people and admin seats; CC BY 4.0). path: a folder (not searched below), a list of files, or one file.
        min_population (default 0) leaves out smaller places when picking the nearest. limit (default 500) files.
        Files without GPS are listed as 'no GPS'. Cached per file content. Also shown as 'place:' in
        letitedit_footage."""
        try:
            rep = places(path, min_population=min_population, limit=limit)
        except FileNotFoundError as e:
            return [{'error': str(e)}]
        return [rep['text'], {k: v for k, v in rep.items() if k != 'text'}]
