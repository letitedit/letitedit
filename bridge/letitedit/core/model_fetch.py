r"""Local models and data from the letitedit model manifest: what is on this PC, how big, and downloading one from
its origin (the URL in its SOURCE.md record) with every file's size and SHA-256 checked.

    status(id)            -> {'id', 'title', 'present', 'size_bytes', 'missing_bytes', 'size_text', 'missing_text', ...}
    listing(tier=None)    -> [status for every model] (tier: 'gpu8' | 'gpu4' | 'cpu' keeps the ones that tier runs)
    plan(ids)             -> {'models': [...], 'download_bytes', 'download_text', 'disk_free_bytes'} (adds 'requires')
    fetch(ids, progress=None) -> {'fetched': [...], 'already_present': [...]}; raises FetchError (nothing half-written)
    ensure(id)            -> the model's folder when present; else downloads it when settings 'model_downloads' is
                             'auto' (the default), otherwise ('ask' | 'never') raises ModelMissing whose text names
                             the size, origin and how to get it

Files that change upstream (GeoNames' daily dump, BtbN's rolling FFmpeg build) carry check = {'rule': 'rolling',
size range, format}: a pinned dated URL (exact SHA-256) is tried first where one exists; a rolling URL's file is
accepted when its hash differs only if it passes that rule (see check_rule), and the record says so.
    remove(id)            -> deletes only the files this module downloaded for it (downloaded.json)

Manifest: LETITEDIT_MODEL_MANIFEST, else <models>\manifest.json, else <root>\release\installer\models-manifest.json
(made by release\installer\make_manifest.py from the SOURCE.md files). <root> is the folder above this bridge folder;
<models> = LETITEDIT_MODELS_HOME or <root>\models; vfx\models and maps\ entries go under LETITEDIT_VFX / <root>\vfx
and LETITEDIT_MAPS / <root>\maps. A file is downloaded to <name>.part next to its place, hashed while it streams,
and moved into place only when its size and SHA-256 match the manifest. Zips marked extract_to are unpacked beside
them (members checked when the manifest lists them). Hugging Face hub entries are written in the hub cache layout
(hub\models--org--name\snapshots\<revision>\..., refs\main).

Command line (run with the tool server's Python):
    python model_fetch.py list [--tier gpu8|gpu4|cpu]
    python model_fetch.py fetch <id> [<id> ...] [--yes]     shows the sizes and asks first unless --yes
    python model_fetch.py status|verify|remove <id>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from letitedit.core import windows_trust  # noqa: E402  (a clean PC: Windows checks the certificates)
windows_trust.use()

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT))
MODELS_HOME = Path(os.environ.get('LETITEDIT_MODELS_HOME', ROOT / 'models'))
VFX = Path(os.environ.get('LETITEDIT_VFX', ROOT / 'vfx'))
MAPS = Path(os.environ.get('LETITEDIT_MAPS', ROOT / 'maps'))
MANIFEST = os.environ.get('LETITEDIT_MODEL_MANIFEST')
SETTINGS = Path(os.environ.get('LETITEDIT_SETTINGS', ROOT / 'settings.json'))
USER_AGENT = 'letitedit-model-fetch/1'
CHUNK = 1 << 20


class FetchError(RuntimeError):
    pass


class ModelMissing(RuntimeError):
    pass


def human(n):
    for unit, k in (('GB', 1 << 30), ('MB', 1 << 20), ('KB', 1 << 10)):
        if n >= k:
            return f'{n / k:.1f} {unit}'
    return f'{n} bytes'


def manifest_path():
    for p in (MANIFEST, MODELS_HOME / 'manifest.json', ROOT / 'release' / 'installer' / 'models-manifest.json'):
        if p and Path(p).is_file():
            return Path(p)
    raise FileNotFoundError('no model manifest (models\\manifest.json)')


def manifest():
    return json.loads(manifest_path().read_text(encoding='utf-8-sig'))


def entry(model_id):
    for e in manifest()['models']:
        if e['id'] == model_id:
            return e
    raise KeyError(f'unknown model {model_id!r}; known: ' + ', '.join(e['id'] for e in manifest()['models']))


def dest_dir(e):
    d = e['dest'].replace('\\', '/')
    head, _, rest = d.partition('/')
    base = {'models': MODELS_HOME, 'vfx': VFX, 'maps': MAPS}.get(head)
    if base is None:
        return ROOT / d
    return base / rest if rest else base


def file_dir(e):
    if e.get('layout') == 'hf-cache':
        return dest_dir(e) / 'hub' / ('models--' + e['repo'].replace('/', '--')) / 'snapshots' / e['revision']
    return dest_dir(e)


def _present(e, f):
    """The file is on this PC: its size matches the manifest. A file that changes upstream (f['check'] rule
    'rolling') counts when its size is in the rule's range, under its name or a name in f['accept_existing']."""
    rule = f.get('check') or {}
    for name in [f['path']] + list(f.get('accept_existing') or []):
        p = file_dir(e) / name
        if not p.is_file():
            continue
        size = p.stat().st_size
        if f.get('bytes') is None or size == f['bytes']:
            return True
        if rule.get('rule') == 'rolling' and rule.get('bytes_min', 0) <= size <= rule.get('bytes_max', 1 << 62):
            return True
    return False


def check_rule(path, rule):
    """For a file that changes upstream: (ok, reason). Checks the size range and the format:
    'zip' (a readable zip; zip_has: names or *-globs that must be members), 'tsv' (UTF-8 text; at least min_rows
    data lines with at least tsv_fields tab-separated fields, '#' lines skipped), plus for a zip with tsv_member the
    same tsv check on that member."""
    import fnmatch
    size = Path(path).stat().st_size
    lo, hi = rule.get('bytes_min', 0), rule.get('bytes_max', 1 << 62)
    if not lo <= size <= hi:
        return False, f'size {size} outside {lo}..{hi}'

    def tsv_ok(lines):
        n = 0
        for line in lines:
            if not line.strip() or line.startswith('#'):
                continue
            if len(line.rstrip('\r\n').split('\t')) < rule.get('tsv_fields', 2):
                return False, f'a line has fewer than {rule.get("tsv_fields")} tab-separated fields: {line[:80]!r}'
            n += 1
            if n >= rule.get('min_rows', 1) and n >= 200:
                break
        if n < min(rule.get('min_rows', 1), 200):
            return False, f'only {n} data lines'
        return True, 'ok'

    fmt = rule.get('format')
    if fmt == 'zip':
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                for want in rule.get('zip_has', []):
                    if not any(fnmatch.fnmatch(n, want) for n in names):
                        return False, f'zip has no {want}'
                if rule.get('tsv_member'):
                    with z.open(rule['tsv_member']) as fh:
                        text = (fh.readline().decode('utf-8') for _ in range(400))
                        ok, why = tsv_ok(l for l in text if l)
                        if not ok:
                            return False, f"{rule['tsv_member']}: {why}"
                bad = z.testzip() if rule.get('test_zip', True) and size < (300 << 20) else None
                if bad:
                    return False, f'zip member {bad} is damaged'
        except (zipfile.BadZipFile, OSError, KeyError, UnicodeDecodeError) as ex:
            return False, f'not a usable zip: {ex}'
    elif fmt == 'tsv':
        try:
            with open(path, encoding='utf-8') as fh:
                ok, why = tsv_ok(fh)
            if not ok:
                return False, why
        except (OSError, UnicodeDecodeError) as ex:
            return False, f'not UTF-8 text: {ex}'
    return True, 'ok'


def status(model_id):
    e = entry(model_id) if isinstance(model_id, str) else model_id
    missing = [f for f in e['files'] if not _present(e, f)]
    mb = sum(f.get('bytes') or 0 for f in missing)
    return {'id': e['id'], 'title': e.get('title'), 'features': e.get('features'), 'tiers': e.get('tiers'),
            'licence': e.get('licence'), 'origin': e.get('origin'), 'present': not missing,
            'size_bytes': e.get('size_bytes'), 'size_text': human(e.get('size_bytes') or 0),
            'missing_bytes': mb, 'missing_text': human(mb), 'folder': str(dest_dir(e)), 'requires': e.get('requires', [])}


def listing(tier=None):
    return [status(e) for e in manifest()['models'] if tier is None or tier in (e.get('tiers') or [])]


def _with_requires(ids):
    out = []
    for i in ids:
        for r in entry(i).get('requires', []) + [i]:
            if r not in out:
                out.append(r)
    return out


def plan(ids):
    ids = _with_requires(list(ids))
    st = [status(i) for i in ids]
    need = sum(s['missing_bytes'] for s in st)
    try:
        free = shutil.disk_usage(MODELS_HOME if MODELS_HOME.exists() else MODELS_HOME.anchor or '.').free
    except OSError:
        free = None
    return {'models': st, 'download_bytes': need, 'download_text': human(need), 'disk_free_bytes': free,
            'disk_free_text': human(free) if free is not None else None}


def _sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(CHUNK), b''):
            h.update(b)
    return h.hexdigest()


def _download_file(f, target, progress=None, label=''):
    """Download one manifest file. Checked by size + SHA-256; a file marked check.rule 'rolling' (it changes
    upstream) whose hash no longer matches is accepted only when it passes the rule (size range + format) - and its
    other URLs (fallback_urls) are tried when the first fails. Returns how it was checked: 'sha256' | 'rule: ...'."""
    rule = f.get('check') or {}
    urls = [f['url']] + list(f.get('fallback_urls') or [])
    errors = []
    for n, url in enumerate(urls):
        try:
            # the first URL is exact (pinned) unless the rule says it is itself the rolling one
            allow = rule.get('rule') == 'rolling' and (n > 0 or rule.get('first_url_rolling'))
            _download(url, target, f.get('bytes'), f.get('sha256'), progress, label, rule=rule if allow else None)
            return 'sha256' if not target.with_name(target.name + '.rule').exists() else \
                target.with_name(target.name + '.rule').read_text(encoding='utf-8')
        except FetchError as ex:
            errors.append(str(ex))
    raise FetchError(' / '.join(errors))


def _download(url, target, nbytes, sha256, progress=None, label='', rule=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    note = target.with_name(target.name + '.rule')
    note.unlink(missing_ok=True)
    rolling = (rule or {}).get('rule') == 'rolling'
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, 'wb') as out:
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                out.write(b)
                h.update(b)
                got += len(b)
                if progress:
                    progress(label, got, nbytes)
    except Exception as ex:  # noqa: BLE001
        part.unlink(missing_ok=True)
        raise FetchError(f'{label}: download from {url} failed: {type(ex).__name__}: {ex}') from ex
    exact = (nbytes is None or got == nbytes) and (not sha256 or h.hexdigest() == sha256)
    if not exact and rolling:
        ok, why = check_rule(part, rule)
        if not ok:
            part.unlink(missing_ok=True)
            raise FetchError(f'{label}: the file from {url} changed upstream (SHA-256 {h.hexdigest()[:16]}...) and '
                             f'does not pass the check for it ({why}); nothing kept')
        os.replace(part, target)
        note.write_text(f'rule: {got} bytes, SHA-256 {h.hexdigest()} (the manifest has {sha256}); '
                        f'{rule.get("why", "changes upstream")}; checked by size range and format', encoding='utf-8')
        return
    if nbytes is not None and got != nbytes:
        part.unlink(missing_ok=True)
        raise FetchError(f'{label}: {got} bytes received from {url}, the manifest says {nbytes}; nothing kept')
    if sha256 and h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise FetchError(f'{label}: SHA-256 {h.hexdigest()} does not match the manifest ({sha256}); nothing kept')
    os.replace(part, target)


def _extract(zpath, into, members):
    into = into.resolve()
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            out = (into / m.filename).resolve()
            if not str(out).startswith(str(into)):
                raise FetchError(f'{zpath.name}: member {m.filename!r} would land outside {into}')
        z.extractall(into)
    for m in members or []:
        p = into / m['path']
        if not p.is_file() or (m.get('sha256') and _sha256(p) != m['sha256']):
            raise FetchError(f'{zpath.name}: extracted {m["path"]} is missing or its SHA-256 does not match')


def _record_path():
    return MODELS_HOME / 'downloaded.json'


def _record():
    p = _record_path()
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def _save_record(rec):
    p = _record_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(rec, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def fetch(ids, progress=None):
    """Download the models (and what they require) that are not complete on this PC."""
    done, already = [], []
    need = sum(status(i)['missing_bytes'] for i in _with_requires(list(ids)))
    if need:
        import letitedit.core.cache_budget as cache_budget
        cache_budget.need_room(MODELS_HOME, need, 'download this model')
    for i in _with_requires(list(ids)):
        e = entry(i)
        missing = [f for f in e['files'] if not _present(e, f)]
        if not missing:
            already.append(i)
            continue
        written, extracted, checked = [], [], {}
        for f in missing:
            target = file_dir(e) / f['path']
            how = _download_file(f, target, progress, f"{i}: {f['path']}")
            target.with_name(target.name + '.rule').unlink(missing_ok=True)
            checked[f['path']] = how
            written.append(str(target))
            if f.get('extract_to'):
                into = target.parent / f['extract_to'] if f['extract_to'] != '.' else target.parent
                _extract(target, into, f.get('members'))
                extracted.append(str(into) if f['extract_to'] != '.' else None)
        if e.get('layout') == 'hf-cache':
            ref = dest_dir(e) / 'hub' / ('models--' + e['repo'].replace('/', '--')) / 'refs' / 'main'
            if not ref.exists():
                ref.parent.mkdir(parents=True, exist_ok=True)
                ref.write_text(e['revision'], encoding='utf-8')
                written.append(str(ref))
        rec = _record()
        old = rec.get(i, {})
        rec[i] = {'files': sorted(set(old.get('files', []) + written)),
                  'extracted': sorted({x for x in old.get('extracted', []) + extracted if x}),
                  'bytes': e.get('size_bytes'), 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'origin': e.get('origin'),
                  'checked': {**old.get('checked', {}), **checked}}
        _save_record(rec)
        done.append(i)
    return {'fetched': done, 'already_present': already}


def verify(model_id):
    """Every file of a model hashed against the manifest: {'ok', 'bad': [paths], 'missing': [paths], 'by_rule':
    {path: reason}}. A file that changes upstream (check.rule 'rolling') whose hash differs passes when it passes
    its rule (size range + format); it is listed under by_rule."""
    e = entry(model_id)
    bad, missing, by_rule = [], [], {}
    for f in e['files']:
        p = next((file_dir(e) / n for n in [f['path']] + list(f.get('accept_existing') or [])
                  if (file_dir(e) / n).is_file()), None)
        if p is None:
            missing.append(f['path'])
        elif f.get('sha256') and _sha256(p) != f['sha256']:
            rule = f.get('check') or {}
            ok, why = check_rule(p, rule) if rule.get('rule') == 'rolling' else (False, 'hash differs')
            if ok:
                by_rule[p.name] = 'size range and format (' + rule.get('why', 'changes upstream') + ')'
            else:
                bad.append(f['path'])
    return {'id': model_id, 'ok': not bad and not missing, 'bad': bad, 'missing': missing, 'by_rule': by_rule}


def remove(model_id):
    """Delete what fetch() wrote for this model (never files it did not download)."""
    rec = _record()
    r = rec.pop(model_id, None)
    if not r:
        return {'id': model_id, 'removed': [], 'note': 'nothing downloaded by letitedit for this model'}
    gone = []
    for d in r.get('extracted', []):
        if d and Path(d).is_dir():
            shutil.rmtree(d, ignore_errors=True)
            gone.append(d)
    for f in r.get('files', []):
        p = Path(f)
        if p.is_file():
            p.unlink()
            gone.append(f)
    _save_record(rec)
    return {'id': model_id, 'removed': gone}


def _setting():
    try:
        return str(json.loads(SETTINGS.read_text(encoding='utf-8-sig')).get('model_downloads', 'auto')).lower()
    except (OSError, ValueError, AttributeError):
        return 'auto'


def ensure(model_id, progress=None):
    """The model's folder when it is on this PC. Otherwise: settings.json model_downloads 'auto' (the default)
    downloads it now; 'ask' and 'never' raise ModelMissing with the size and the way to download it."""
    p = plan([model_id])
    if not p['download_bytes'] and all(s['present'] for s in p['models']):
        return Path(status(model_id)['folder'])
    if _setting() == 'auto':
        fetch([model_id], progress)
        return Path(status(model_id)['folder'])
    s = status(model_id)
    raise ModelMissing(
        f"{s['title']} ({p['download_text']} to download) is not on this PC. It comes from {s['origin']} "
        f"({s['licence']}). Download it with the setup window, or: python {Path(__file__).name} fetch {model_id}")


def _progress(label, got, total):
    pct = f'{100 * got / total:5.1f}%' if total else ''
    sys.stdout.write(f'\r  {label[:60]:<60} {human(got):>9} {pct}')
    sys.stdout.flush()
    if total and got >= total:
        sys.stdout.write('\n')


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    yes = '--yes' in rest
    rest = [a for a in rest if a != '--yes']
    if cmd == 'list':
        tier = rest[rest.index('--tier') + 1] if '--tier' in rest else None
        for s in listing(tier):
            print(f"{s['id']:<28} {s['size_text']:>9}  {'on this PC' if s['present'] else 'not downloaded':<15} "
                  f"{', '.join(s['features'] or [])}")
        return 0
    if cmd == 'status':
        print(json.dumps([status(i) for i in rest], indent=1))
        return 0
    if cmd == 'verify':
        r = [verify(i) for i in rest]
        print(json.dumps(r, indent=1))
        return 0 if all(x['ok'] for x in r) else 1
    if cmd == 'remove':
        print(json.dumps([remove(i) for i in rest], indent=1))
        return 0
    if cmd == 'fetch':
        p = plan(rest)
        for s in p['models']:
            print(f"{s['title']}: {s['missing_text'] if not s['present'] else 'already on this PC'} from {s['origin']} "
                  f"({s['licence']})")
        print(f"To download: {p['download_text']} (free on the disk: {p['disk_free_text']})")
        if not p['download_bytes']:
            return 0
        if not yes:
            if input('Download now? Type yes: ').strip().lower() not in ('y', 'yes'):
                print('Nothing downloaded.')
                return 1
        try:
            r = fetch(rest, _progress)
        except FetchError as ex:
            print(f'\nNot downloaded: {ex}')
            return 2
        print(json.dumps(r))
        return 0
    print(f'unknown command {cmd!r}')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
