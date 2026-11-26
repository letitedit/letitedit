r"""letitedit installer step: fit the installed copy to its folder.

    python -I relocate.py <install folder> [--exe <editor exe file name>]

1. The tool server's modules, the guides and the Codex plugin name C:\LetItEdit (where letitedit was built). When
   the install folder is somewhere else, every such path in the installed copy is rewritten to the install folder:
   Python files token by token (raw and normal strings get the right escaping; every changed file is compiled and
   its string values are compared with the expected ones), other text files as text. The originals in the build
   folder are never touched; only files inside <install folder> change.
2. Always: app\ai-assist-executable.txt names the installed editor; the Codex plugin's server command is the
   install's own Python (env\Scripts\python.exe); the Codex marketplace is named 'letitedit'.
Writes setup\relocated.json (what changed). Safe to run again, and safe to stop at any moment: a file is either old or new, never half written (setup stops this
step if it gets stuck). If this ever sits there, setup\relocate-stuck.log says where: T76 saw it at 0 CPU for two hours once, cause unknown.
"""
from __future__ import annotations

import ast
import faulthandler
import io
import json
import os
import re
import shutil
import sys
import time
import tokenize
from pathlib import Path

OLD = 'C:\\LetItEdit'
TEXT_DIRS = ('bridge', 'codex', 'style-packs', 'chat', 'creator', 'vfx', 'skills', 'platforms')
TEXT_SUFFIXES = {'.py', '.ps1', '.md', '.json', '.yaml', '.yml', '.txt', '.vbs', '.toml', '.cfg'}
TOP_FILES = ('GUIDE.md', 'GUIDE_V2.md', 'command-reference.json')
# a per-user Python a development PC may have left in a text (any user folder, any Python 3 version)
DEV_PYTHON = re.compile(r'[A-Za-z]:\\Users\\[^\\`\s"]+\\AppData\\Local\\Programs\\Python\\Python3\d*\\python\.exe', re.I)


def forms(new):
    """(old text, new text) pairs, most specific first. 'esc' = backslashes doubled (escaped string / JSON)."""
    esc = new.replace('\\', '\\\\')
    fwd = new.replace('\\', '/')
    return {'esc': [('C:\\\\LetItEdit', esc), ('C:\\LetItEdit', esc), ('C:/LetItEdit', fwd)],
            'raw': [('C:\\\\LetItEdit', esc), ('C:\\LetItEdit', new), ('C:/LetItEdit', fwd)],
            'value': [('C:\\\\LetItEdit', esc), ('C:\\LetItEdit', new), ('C:/LetItEdit', fwd)]}


def sub(text, pairs):
    # one pass so a replaced path is never matched again
    pat = re.compile('|'.join(re.escape(a) for a, _ in pairs))
    table = dict(pairs)
    # already the new path (an install folder like C:\LetItEdit2, on a second run): left alone
    return pat.sub(lambda m: m.group(0) if text.startswith(table[m.group(0)], m.start()) else table[m.group(0)], text)


def _consts(tree):
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def relocate_python(src, new):
    f = forms(new)
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    edits = []
    fprefix = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        name = tokenize.tok_name[tok.type]
        if name == 'FSTRING_START':
            fprefix.append(tok.string)
        elif name == 'FSTRING_END':
            fprefix.pop()
        if 'LetItEdit' not in tok.string:
            continue
        if name == 'STRING':
            prefix = re.match(r'[A-Za-z]*', tok.string).group(0).lower()
            pairs = f['raw'] if 'r' in prefix else f['esc']
        elif name == 'FSTRING_MIDDLE':
            pairs = f['raw'] if 'r' in fprefix[-1].lower() else f['esc']
            # braces inside an f-string middle are doubled in the source; a path has none
        elif name == 'COMMENT':
            pairs = f['raw']
        else:
            continue
        a = starts[tok.start[0] - 1] + tok.start[1]
        b = starts[tok.end[0] - 1] + tok.end[1]
        if name == 'FSTRING_MIDDLE':
            # FSTRING_MIDDLE text is the source text except doubled braces; locate it in the source span
            seg = src[a:b]
            edits.append((a, b, sub(seg, pairs)))
        else:
            edits.append((a, b, sub(tok.string, pairs)))
    out = src
    for a, b, t in sorted(edits, reverse=True):
        out = out[:a] + t + out[b:]
    return out


def check_python(old_src, new_src, new, name):
    old_tree = ast.parse(old_src)
    new_tree = ast.parse(new_src)        # SyntaxError -> caller reports
    compile(new_src, name, 'exec')
    want = [sub(c, forms(new)['value']) for c in _consts(old_tree)]
    got = _consts(new_tree)
    if want != got:
        bad = next((w, g) for w, g in zip(want, got) if w != g) if len(want) == len(got) else ('count', len(got))
        raise ValueError(f'{name}: string values differ after relocation: {bad!r}'[:300])


def newest_exe(app):
    exes = sorted((app / 'app').glob('letitedit-*.exe'))
    return exes[-1].name if exes else None


def put(path, text, work, newline=None):
    """Whole or not at all: written beside the rest of our work on this drive, then swapped in. Something scanning the file can hold it for a moment."""
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / f'{os.getpid()}-{path.name}'
    with open(tmp, 'w', encoding='utf-8', newline=newline) as f:
        f.write(text)
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    root = Path(argv[0]).resolve()
    work = root / 'setup' / 'relocating'
    shutil.rmtree(work, ignore_errors=True)     # what a stopped run left
    (root / 'setup').mkdir(exist_ok=True)
    stuck_log = root / 'setup' / 'relocate-stuck.log'
    stuck_file = open(stuck_log, 'w', encoding='utf-8')
    faulthandler.dump_traceback_later(120, file=stuck_file)
    exe = argv[argv.index('--exe') + 1] if '--exe' in argv else newest_exe(root)
    new = str(root)
    if any(c in new for c in '\'"'):
        print(f'The install folder may not contain quote marks: {new}')
        return 2
    changed, errors = [], []
    if new.lower() != OLD.lower():
        files = [root / t for t in TOP_FILES if (root / t).is_file()]
        for d in TEXT_DIRS:
            if (root / d).is_dir():
                files += [p for p in (root / d).rglob('*') if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
                          and '__pycache__' not in p.parts]
        for p in files:
            try:
                src = p.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            if 'LetItEdit' not in src:
                continue
            try:
                if p.suffix.lower() == '.py':
                    out = relocate_python(src, new)
                    check_python(src, out, new, str(p))
                elif p.suffix.lower() == '.json':
                    out = sub(src, forms(new)['esc'])
                    json.loads(out)
                else:
                    out = sub(src, forms(new)['raw'])
            except (SyntaxError, ValueError, tokenize.TokenError) as ex:
                errors.append(f'{p}: {ex}')
                continue
            if out != src:
                put(p, out, work, newline='')
                changed.append(str(p.relative_to(root)))
    # always: the editor pointer and the Codex plugin
    if exe:
        put(root / 'app' / 'ai-assist-executable.txt', str(root / 'app' / exe), work)
    py = str(root / 'env' / 'Scripts' / 'python.exe')
    plugin = root / 'codex' / 'plugins' / 'letitedit' / '.codex-plugin' / 'plugin.json'
    if plugin.is_file():
        d = json.loads(plugin.read_text(encoding='utf-8-sig'))
        srv = d.get('mcpServers', {}).get('letitedit')
        if srv is None:
            errors.append(f'{plugin}: no mcpServers.letitedit entry to point at this install')
        else:
            srv['command'] = py
            srv['args'] = [str(root / 'bridge' / 'letitedit_mcp.py')]
            put(plugin, json.dumps(d, indent=2) + '\n', work)
    market = root / 'codex' / '.agents' / 'plugins' / 'marketplace.json'
    if market.is_file():
        d = json.loads(market.read_text(encoding='utf-8-sig'))
        d['name'] = 'letitedit'
        d.setdefault('interface', {})['displayName'] = 'letitedit'
        put(market, json.dumps(d, indent=2) + '\n', work)
    skill = root / 'codex' / 'plugins' / 'letitedit' / 'skills' / 'letitedit-tools' / 'SKILL.md'
    if skill.is_file():
        t = skill.read_text(encoding='utf-8')
        t = DEV_PYTHON.sub(lambda m: py, t)
        t = re.sub(r'- Source footage under `[^`]*` is read-only;', '- Source footage is only read;', t)
        put(skill, t, work, newline='')
    rec = {'install_folder': new, 'editor': exe, 'python': py, 'changed': changed, 'errors': errors}
    put(root / 'setup' / 'relocated.json', json.dumps(rec, indent=1) + '\n', work)
    faulthandler.cancel_dump_traceback_later()
    stuck_file.close()
    if stuck_log.stat().st_size == 0:
        stuck_log.unlink()
    shutil.rmtree(work, ignore_errors=True)
    print(f'{len(changed)} files fitted to {new}' + (f'; {len(errors)} errors' if errors else ''))
    for e in errors:
        print('  ' + e)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
