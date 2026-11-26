"""Write name, version, licence of every package in the running Python environment as TSV; flag copyleft ones.

    python -I licence_scan.py out.tsv
"""
import sys
from importlib import metadata

COPYLEFT = ('AGPL', 'Affero', 'GPL', 'GNU GENERAL', 'GNU LESSER', 'LGPL', 'MPL', 'Mozilla', 'EUPL', 'SSPL')


def licence(d):
    m = d.metadata
    expr = m.get('License-Expression')
    if expr:
        return expr
    lic = (m.get('License') or '').strip().splitlines()
    if lic and len(lic[0]) < 80:
        return lic[0]
    cls = [c.split('::')[-1].strip() for c in (m.get_all('Classifier') or []) if c.startswith('License ::')]
    return '; '.join(cls) or (lic[0][:80] if lic else 'UNKNOWN')


def main(out):
    rows = []
    for d in metadata.distributions():
        name = d.metadata.get('Name') or '?'
        lic = licence(d)
        flag = 'copyleft' if any(k.lower() in lic.lower() for k in COPYLEFT) else ''
        if 'AGPL' in lic or 'Affero' in lic:
            flag = 'AGPL'
        rows.append((name.lower(), name, d.version, lic.replace('\t', ' '), flag))
    rows.sort()
    with open(out, 'w', encoding='utf-8') as f:
        f.write('name\tversion\tlicence\tflag\n')
        for _, n, v, l, fl in rows:
            f.write(f'{n}\t{v}\t{l}\t{fl}\n')
    bad = [r for r in rows if r[4] == 'AGPL']
    print(f'{len(rows)} packages; copyleft: {", ".join(r[1] for r in rows if r[4]) or "none"}')
    if bad:
        print('AGPL present:', ', '.join(r[1] for r in bad))
        sys.exit(2)


if __name__ == '__main__':
    main(sys.argv[1])
