"""Scan every file the installer ships for private data and for folders that must never ship. Read-only.

    python -I check_private.py                 # the files letitedit.iss names (file_list.py), as build.ps1 runs it
    python -I check_private.py --dir <folder>  # every file under a folder (an installed copy, a fixture)
    python -I check_private.py --json out.json # also write the findings

Blocking (exit 1, the build stops):
- a path into a person's own user folder (C:\\Users\\<name>, /home/<name>/, /Users/<name>/), a Google Drive folder,
  the home server's storage folder;
- one of the owner's names, accounts or his user folder's name from tools/release/private-terms.txt (its blocking
  terms, and its review terms that are part of one); his public brand names (its other review terms) are listed
  "to review", not blocking;
- a key or token (the value is never printed);
- a file from a folder that never ships: looks-library/ (other people's repositories, no licences kept), tests/,
  test-footage/, dev-history/, style-references/, shared-looks-inbox/, the legacy style packs, a person's own
  Looks, the private Looks this PC lists in settings.local.json, the chat panel's own settings (chat/panel.json).
Text files are read whole; programs and other binary files are searched for the owner's terms and user folder, in
plain and UTF-16 text. Reviewed exceptions: private-allow.txt beside this file ("file-glob | text | why").
E-mail addresses are counted, not blocking (upstream packages carry their authors' addresses).
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TERMS = ROOT / 'tools' / 'release' / 'private-terms.txt'
ALLOW = HERE / 'private-allow.txt'
CHUNK = 32 * 1024 * 1024
PATH_HINTS = ('users', 'drive', '/home/', '/srv')
EXTRA = ['/srv/storage/', 'my drive']   # in programs too: the home server's storage, a Google Drive folder
NEVER_SHIP = [  # (folder glob relative to the source root, why)
    ('looks-library/**', "other people's repositories, no licences kept"),
    ('**/looks-library/**', "other people's repositories, no licences kept"),
    ('tests/**', 'test runs and their notes'),
    ('test-footage/**', "the owner's footage and private reference videos"),
    ('dev-history/**', 'development notes'),
    ('style-references/**', 'reference material'),
    ('shared-looks-inbox/**', 'untrusted shared Looks'),
    ('problem-reports-inbox/**', "people's problem reports"),
    ('style-packs/**', 'legacy style packs: not shipped'),
    ('looks/mine-*/**', "a person's own Look"),
    ('chat/panel.json', "the chat panel's own settings"),
]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot = _load('letitedit_source_snapshot', ROOT / 'tools' / 'release' / 'make_source_snapshot.py')


def private_look_rules(roots=None):
    """NEVER_SHIP rows for the Looks this PC keeps private: the settings.local.json of the source folder (in a git
    worktree, also of its main checkout) names them, as bridge/letitedit/looks/look_settings.py reads them."""
    if roots is None:
        roots = _load('installer_file_list_roots', HERE / 'file_list.py').allowed_roots()
    names = []
    for root in roots:
        local = Path(root) / 'settings.local.json'
        if not local.is_file():
            continue
        data = json.loads(local.read_text(encoding='utf-8-sig') or '{}')    # unreadable: the scan stops, loudly
        for key in ('private_packs', 'private_packs_hidden'):
            value = data.get(key) or []
            names += [value] if isinstance(value, str) else value
    return [('looks/%s/**' % name.strip().lower(), 'a private Look this PC lists')
            for name in dict.fromkeys(names) if isinstance(name, str) and name.strip()]


def terms(path=TERMS):
    """(personal, brand): the owner's names, accounts, user folder and server from private-terms.txt (its blocking
    terms, and its review terms that are part of one: his first and last name), which block; and the rest of its
    review terms (his public brands), which are listed for review."""
    block, review = snapshot.load_terms(str(path))
    block = [t for t in block if t]
    personal = block + [t for t in review if t and any(t.lower() in b.lower() for b in block)]
    brand = [t for t in review if t and t not in personal]
    return personal, brand


def allow_rules(path=ALLOW):
    """private-allow.txt: 'file-glob | text | why'. A hit whose line (in a program: the 200 bytes around it) holds
    that text, in a file matching the glob, was read by a person and is fine. A why starting 'TEMPORARY' is a known
    leak waiting for its fix: allowed in a test installer, listed in every run, blocking with --public."""
    rules = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                parts = [x.strip() for x in line.split('|')]
                if len(parts) >= 2:
                    temporary = len(parts) > 2 and parts[2].upper().startswith('TEMPORARY')
                    rules.append((parts[0].replace(chr(92), '/').lower(), parts[1].lower(), temporary))
    return rules


def _variants(term):
    term = term.lower()
    return {term, term.replace(chr(92), '/')}


def never_ship(rel, private=()):
    low = rel.lower()
    for glob, why in [*NEVER_SHIP, *private]:
        if fnmatch.fnmatchcase(low, glob) or fnmatch.fnmatchcase(low, glob.replace('/**', '')):
            return why
    return None


def _scan_binary(fh, rel, personal, brand, allowed):
    """A program or data file: the terms as plain text, and as UTF-16 text (found in the file's even and odd bytes,
    which is where UTF-16 keeps ASCII letters)."""
    out = []
    words = [(w.encode('utf-8'), 'block') for t in personal + EXTRA for w in _variants(t)] + \
            [(t.lower().encode('utf-8'), 'review') for t in brand]
    found = set()
    tail = b''
    while True:
        block = fh.read(CHUNK)
        if not block:
            break
        data = (tail + block).lower()
        for view in (data, data[0::2], data[1::2]):
            for w, kind in words:
                if w in found:
                    continue
                i = view.find(w)
                what = 'a program or data file holds ' + ('a private term' if kind == 'block' else
                                                            'a brand name') + ' (%s...)' % w[:3].decode()
                while i != -1:
                    around = view[max(0, i - 200):i + 200].decode('latin-1')
                    rule = next((temp for a, temp in allowed if a in around), None)
                    if rule is None:
                        found.add(w)
                        out.append((kind, rel, 0, what))
                        break
                    if rule and (w, 'temporary') not in found:
                        found.add((w, 'temporary'))
                        out.append(('temporary', rel, 0, what))
                    i = view.find(w, i + 1)
        tail = block[-1024:]
    return out


def scan_file(path, rel, personal, brand, allow, private=()):
    """Findings for one file: [(kind, rel, line, what)]; kind 'block', 'review' or 'count'."""
    out = []
    why = never_ship(rel, private)
    if why:
        out.append(('block', rel, 0, 'a file from a folder that never ships (%s)' % why))
    low_rel = rel.lower()
    for term in personal:
        if term.lower() in low_rel:
            out.append(('block', rel, 0, 'the file name contains a private term (%s...)' % term[:3]))
    allowed = [(rule[1].lower(), len(rule) > 2 and rule[2]) for rule in allow if fnmatch.fnmatchcase(low_rel, rule[0])]
    with open(path, 'rb') as fh:
        if not snapshot.is_text(fh.read(8192)):
            fh.seek(0)
            return out + _scan_binary(fh, rel, personal, brand, allowed)
        fh.seek(0)
        text = fh.read().decode('utf-8', 'replace')
    low = text.lower()

    def hit(kind, i, what):
        start = text.rfind('\n', 0, i) + 1
        end = text.find('\n', i)
        line = low[start:end if end != -1 else len(text)]
        rule = next((temp for a, temp in allowed if a in line), None)
        if rule is None or rule:
            out.append((kind if rule is None else 'temporary', rel, text.count('\n', 0, i) + 1, what))

    for what, rx in snapshot.SECRETS:
        for m in rx.finditer(text):
            hit('block', m.start(), 'looks like %s (value not shown)' % what)
    if any(h in low for h in PATH_HINTS):
        for what, rx in snapshot.PRIVATE_PATHS:
            for m in rx.finditer(text):
                hit('block', m.start(), 'names %s' % what)
    for kind, group in (('block', personal), ('review', brand)):
        for term in group:
            for w in _variants(term):
                i = low.find(w)
                while i != -1:
                    hit(kind, i, 'contains %s (%s...)' % ('a private term' if kind == 'block' else 'a brand name',
                                                         term[:3]))
                    i = low.find(w, i + 1)
    emails = 0
    if '@' in text:
        for m in snapshot.EMAIL.finditer(text):
            local, dom, tld = m.group(1), m.group(2), m.group(3).lower()
            if tld in snapshot.EMAIL_NOT_TLD or local.lower() in snapshot.EMAIL_SAFE_LOCAL \
                    or snapshot.EMAIL_SAFE_DOMAIN.search(dom):
                continue
            emails += 1
    if emails:
        out.append(('count', rel, 0, '%d e-mail address(es)' % emails))
    return out


def shipped_files(root=ROOT):
    """[(path, rel)] for every file letitedit.iss ships; rel is relative to the source root."""
    inventory = _load('installer_file_list', HERE / 'file_list.py')
    files, missing = inventory.collect()
    out = []
    for f in files:
        p = Path(f)
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        out.append((p, rel))
    return out, missing


def folder_files(folder):
    folder = Path(folder)
    return [(Path(d, n), Path(d, n).relative_to(folder).as_posix())
            for d, _, names in os.walk(folder) for n in names]


def scan(files, term_lists=None, allow=None, private=None):
    personal, brand = terms() if term_lists is None else term_lists
    allow = allow_rules() if allow is None else allow
    private = private_look_rules() if private is None else private
    findings = []
    for path, rel in files:
        findings.extend(scan_file(path, rel, personal, brand, allow, private))
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir')
    ap.add_argument('--json')
    ap.add_argument('--public', action='store_true', help='a public installer: TEMPORARY exceptions block too')
    a = ap.parse_args(argv)
    if a.dir:
        files, missing = folder_files(a.dir), []
    else:
        files, missing = shipped_files()
    findings = scan(files)
    blocking = [f for f in findings if f[0] == 'block' or (a.public and f[0] == 'temporary')]
    temporary = [f for f in findings if f[0] == 'temporary']
    review = [f for f in findings if f[0] == 'review']
    emails = sum(int(f[3].split()[0]) for f in findings if f[0] == 'count')
    for kind, rel, line, what in blocking[:200]:
        print(f'BLOCK {rel}:{line}: {what}')
    if not a.public:
        for kind, rel, line, what in temporary[:200]:
            print(f'TEMPORARY {rel}:{line}: {what} (allowed in a test installer only; private-allow.txt)')
    for kind, rel, line, what in review[:200]:
        print(f'REVIEW {rel}:{line}: {what}')
    print(f'check_private: {len(files)} files scanned, {len(blocking)} blocking, '
          + ('' if a.public else f'{len(temporary)} known leaks waiting for a fix (NOT publishable), ')
          + f'{len(review)} to review (brand names), '
          f'{emails} e-mail addresses in {sum(1 for f in findings if f[0] == "count")} files (not blocking)'
          + (f', {len(missing)} inputs missing' if missing else ''))
    if a.json:
        Path(a.json).write_text(json.dumps({'files': len(files), 'findings': findings}, indent=1), encoding='utf-8')
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
