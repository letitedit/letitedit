"""Build the bundled font library from Google Fonts (all OFL / Apache / UFL licensed, free to ship and use).

Picks the most popular Latin families per category plus a must-have list, downloads their TTFs and licence files
from github.com/google/fonts into C:\\LetItEdit\\fonts\\library\\<family>, and writes catalog.json.
Re-runnable: already downloaded files are skipped, families no longer chosen are removed from the library.
Japanese/Korean/Chinese families are left out (huge files; captions here are Latin script). Each family gets the
Google Fonts mood/shape tags (Playful, Rounded, Vintage, Handwritten...) with scores 0-100 for searching.
"""
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(os.environ.get('LETITEDIT_FONTS', (_SAI_ROOT + '/fonts')))
LIB = HERE / 'library'
CJK = {'japanese', 'korean', 'chinese-simplified', 'chinese-traditional', 'chinese-hongkong'}
RAW = 'https://raw.githubusercontent.com/google/fonts/main/'
PER_CATEGORY = {'Sans Serif': 120, 'Display': 95, 'Serif': 45, 'Handwriting': 35, 'Monospace': 10}
MUST = ['Sniglet', 'Shrikhand', 'Bowlby One', 'Caprasimo', 'Coustard', 'Oswald', 'Bangers', 'Luckiest Guy', 'Lilita One',
        'Anton', 'Bebas Neue', 'Archivo Black', 'Montserrat', 'Poppins', 'Inter', 'Roboto', 'Open Sans', 'Lato', 'Nunito',
        'Fredoka', 'Baloo 2', 'Rubik', 'Bungee', 'Titan One', 'Righteous', 'Russo One', 'Permanent Marker', 'Pacifico',
        'Lobster', 'Playfair Display', 'Abril Fatface', 'Alfa Slab One', 'Ultra', 'Chewy', 'Passion One', 'Teko',
        'Barlow Condensed', 'Kanit', 'Black Ops One', 'Rubik Mono One', 'Rammetto One', 'Paytone One', 'Knewave',
        'Bevan', 'Monoton', 'Sigmar One', 'Bungee Shade', 'Rye', 'Lexend', 'Space Grotesk', 'Work Sans', 'DM Sans',
        'Archivo', 'Komika Axis', 'Chango', 'Dela Gothic One', 'Climate Crisis', 'Lalezar']


def main():
    meta = open(HERE / 'gf-metadata.json', encoding='utf-8-sig').read()
    meta = json.loads(meta[meta.index('{'):])['familyMetadataList']
    tree = json.load(open(HERE / 'gf-tree.json', encoding='utf-8-sig'))['tree']
    paths = [t['path'] for t in tree if t['type'] == 'blob']
    dirs = {}
    for p in paths:
        parts = p.split('/')
        if len(parts) >= 3 and parts[0] in ('ofl', 'apache', 'ufl'):
            dirs.setdefault(parts[1], []).append(p)

    def usable(f):
        name = f['family']
        subsets = set(f.get('subsets', []))
        return ('latin' in subsets and not subsets & CJK and not name.startswith(('Noto ', 'Material'))
                or name in ('Noto Sans', 'Noto Serif'))

    chosen = {}
    for cat, n in PER_CATEGORY.items():
        fam = sorted([f for f in meta if f.get('category') == cat and usable(f)], key=lambda f: f.get('popularity', 9999))[:n]
        for f in fam:
            chosen[f['family']] = f
    by_name = {f['family']: f for f in meta}
    for name in MUST:
        if name in by_name:
            chosen[name] = by_name[name]
    LIB.mkdir(parents=True, exist_ok=True)
    tags = {}
    tag_file = HERE / 'gf-tags.csv'
    if not tag_file.exists():
        urllib.request.urlretrieve(RAW + 'tags/all/families.csv', tag_file)
    import csv
    for row in csv.reader(open(tag_file, encoding='utf-8')):
        if len(row) >= 4 and not row[1] and row[2].startswith('/'):
            try:
                score = float(row[3])
            except ValueError:
                continue
            if score >= 40 and not row[2].startswith('/Quality'):
                tags.setdefault(row[0], {})[row[2].strip('/').split('/')[-1]] = round(score)
    catalog, total, missing = [], 0, []
    for name, f in sorted(chosen.items()):
        key = re.sub(r'[^a-z0-9]', '', name.lower())
        files = dirs.get(key)
        if not files:
            missing.append(name)
            continue
        want = [p for p in files if p.endswith('.ttf') and '/static/' not in p]
        if not want:
            want = [p for p in files if p.endswith('.ttf')]
        lic = [p for p in files if re.search(r'/(OFL|LICENSE|UFL)\.txt$', p)]
        dest = LIB / re.sub(r'[\\/:*?"<>|]', '', name)
        dest.mkdir(exist_ok=True)
        got = []
        for p in want + lic:
            out = dest / p.split('/')[-1]
            if not out.exists():
                for attempt in range(3):
                    try:
                        urllib.request.urlretrieve(RAW + urllib.request.quote(p), out)
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt == 2:
                            print('failed', p, e)
                        time.sleep(1 + attempt)
            if out.exists():
                total += out.stat().st_size
                if out.suffix == '.ttf':
                    got.append(out.name)
        catalog.append({'family': name, 'category': f.get('category'), 'popularity': f.get('popularity'),
                        'weights': sorted(f.get('fonts', {}).keys()), 'variable_axes': [a.get('tag') for a in f.get('axes', [])],
                        'tags': dict(sorted(tags.get(name, {}).items(), key=lambda kv: -kv[1])),
                        'licence_folder': files[0].split('/')[0], 'files': got, 'folder': str(dest)})
        print(f'{len(catalog):3d} {name}: {len(got)} file(s)')
        sys.stdout.flush()
    keep = {Path(x['folder']).name for x in catalog}
    for d in LIB.iterdir():
        if d.is_dir() and d.name not in keep:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            print('removed', d.name)
    json.dump({'source': 'https://github.com/google/fonts', 'families': catalog}, open(HERE / 'catalog.json', 'w', encoding='utf-8'), indent=1)
    print('families', len(catalog), 'MB', round(total / 1e6, 1), 'missing', missing)


if __name__ == '__main__':
    main()
