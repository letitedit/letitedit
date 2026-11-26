"""Scripts read as a shell would: .bat/.cmd/.ps1/.sh lines and .py files, their variables and calls.

Part of `edit_import` (letitedit/timeline/edit_import.py), which imports every name here back,
so `edit_import.X` is the same object it always was.
"""
from __future__ import annotations
import ast
import os
import re
import shlex
_FF_EXE = re.compile(r'^(?:.*[\\/])?ffmpeg(?:\.exe)?$', re.I)


# ============================================================================ ffmpeg: finding the calls

_SEPS = {'&&', '||', '|', ';', '&', '>', '>>', '2>', '1>', '2>&1', '2>>', '<', '>nul', '2>nul', '>NUL', '2>NUL'}


def _style_of(path, text):
    ext = path.suffix.lower() if path else ''
    if ext in ('.bat', '.cmd'):
        return 'bat'
    if ext == '.ps1':
        return 'ps1'
    if ext in ('.sh', '.bash', '.zsh'):
        return 'sh'
    if re.search(r'\s\^\s*$', text, re.M):
        return 'cmd'
    if re.search(r'\s`\s*$', text, re.M):
        return 'ps1'
    if re.search(r'[A-Za-z]:\\', text):
        return 'cmd'
    return 'sh'


def _joined_lines(text, style):
    """Logical lines: ^ (cmd), ` (PowerShell) and \\ (sh) at a line end continue it."""
    out, buf = [], ''
    for line in text.splitlines():
        st = line.rstrip()
        cont = None
        if st.endswith('^') and style in ('bat', 'cmd'):
            cont = st[:-1]
        elif re.search(r'\s[\^`\\]$', st):
            cont = st[:-1]
        elif st.endswith('`') and style == 'ps1':
            cont = st[:-1]
        elif st.endswith('\\') and style == 'sh' and not st.endswith('\\\\'):
            cont = st[:-1]
        if cont is not None:
            buf += cont + ' '
            continue
        out.append(buf + line)
        buf = ''
    if buf:
        out.append(buf)
    return out


def _uncaret(s):
    out, q, i = [], False, 0
    while i < len(s):
        c = s[i]
        if c == '"':
            q = not q
        if c == '^' and not q and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _expand(s, style, vars_, base_dir, batch=False):
    if style in ('bat', 'cmd'):
        s = s.replace('%~dp0', str(base_dir) + '\\')
        s = re.sub(r'%([A-Za-z_]\w*)%', lambda m: vars_.get(m.group(1).upper(), m.group(0)), s)
        s = re.sub(r'!([A-Za-z_]\w*)!', lambda m: vars_.get(m.group(1).upper(), m.group(0)), s)
        if batch:
            s = s.replace('%%', '%')
    elif style == 'ps1':
        vars_ = dict(vars_, psscriptroot=str(base_dir))
        out, q, i = [], None, 0
        pat = re.compile(r'\$\{?(?:env:)?([A-Za-z_]\w*)\}?')
        while i < len(s):
            c = s[i]
            if c in ('"', "'") and q in (None, c):
                q = None if q == c else c
            m = pat.match(s, i) if c == '$' and q != "'" else None
            if m and m.group(1).lower() in vars_:
                v = vars_[m.group(1).lower()]
                out.append(v if q == '"' or not re.search(r'\s', v) else f'"{v}"')
                i = m.end()
                continue
            out.append(c)
            i += 1
        s = ''.join(out)
    else:
        s = s.replace('$(dirname "$0")', str(base_dir)).replace('$(dirname $0)', str(base_dir))
        s = re.sub(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)', lambda m: vars_.get(m.group(1) or m.group(2), m.group(0)), s)
    return s


def _set_var(s, style, vars_, base_dir, batch):
    if style in ('bat', 'cmd'):
        m = re.match(r'(?i)^\s*set\s+"?([A-Za-z_]\w*)=(.*?)"?\s*$', s)
        if m:
            vars_[m.group(1).upper()] = _expand(m.group(2), style, vars_, base_dir, batch)
            return True
    elif style == 'ps1':
        m = re.match(r'^\s*\$(?:env:)?([A-Za-z_]\w*)\s*=\s*(["\'])(.*)\2\s*;?\s*$', s)
        if m:
            v = m.group(3)
            vars_[m.group(1).lower()] = _expand(v, style, vars_, base_dir) if m.group(2) == '"' else v
            return True
    else:
        m = re.match(r'^\s*(?:export\s+)?([A-Za-z_]\w*)=(["\']?)(.*?)\2\s*$', s)
        if m:
            v = m.group(3)
            vars_[m.group(1)] = _expand(v, style, vars_, base_dir) if m.group(2) != "'" else v
            return True
    return False


def _tokens(s, style):
    if style in ('bat', 'cmd'):
        s = _uncaret(s)
    lex = shlex.shlex(s, posix=True)
    lex.whitespace_split = True
    lex.commenters = ''
    if style in ('bat', 'cmd', 'ps1'):
        lex.escape = ''
    return list(lex)


def _py_value(node, consts):
    """A Python expression's value when it is built from literals and module-level constants, else None."""
    try:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    x = _py_value(v.value, consts)
                    if x is None:
                        return None
                    spec = _py_value(v.format_spec, consts) if v.format_spec is not None else ''
                    parts.append(format(x, spec or ''))
            return ''.join(parts)
        if isinstance(node, ast.BinOp):
            a, b = _py_value(node.left, consts), _py_value(node.right, consts)
            if a is None or b is None:
                return None
            ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
                   ast.Mod: lambda: a % b}
            f = ops.get(type(node.op))
            return f() if f else None
        if isinstance(node, (ast.List, ast.Tuple)):
            vals = [_py_value(e, consts) for e in node.elts]
            return None if any(v is None for v in vals) else vals
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
            args = [_py_value(a, consts) for a in node.args]
            if any(a is None for a in args):
                return None
            if name in ('str', 'Path', 'PurePath', 'fspath', 'abspath', 'normpath') and len(args) == 1:
                return str(args[0])
            if name == 'join' and isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Attribute):
                return os.path.join(*map(str, args))
            if name == 'join' and isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Constant) and args:
                return fn.value.value.join(map(str, args[0]))
            if name == 'format' and isinstance(fn, ast.Attribute):
                base = _py_value(fn.value, consts)
                return base.format(*args) if isinstance(base, str) else None
    except Exception:  # noqa: BLE001 - anything odd is simply unknown
        return None
    return None


def _parse_py(text):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return ast.parse(text)


def _py_calls(text):
    try:
        tree = _parse_py(text)
    except SyntaxError:
        return []
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = _py_value(node.value, consts)
            if v is not None:
                consts[node.targets[0].id] = v
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List))
              and isinstance(node.value, (ast.Tuple, ast.List)) and len(node.value.elts) == len(node.targets[0].elts)):
            for tg, val in zip(node.targets[0].elts, node.value.elts):
                if isinstance(tg, ast.Name):
                    v = _py_value(val, consts)
                    if v is not None:
                        consts[tg.id] = v
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first = _py_value(node.elts[0], consts)
            if isinstance(first, str) and _FF_EXE.match(first.strip()):
                argv = []
                for e in node.elts[1:]:
                    if isinstance(e, ast.Starred):
                        v = _py_value(e.value, consts)
                        argv += [str(x) for x in v] if isinstance(v, (list, tuple)) else ['<?>']
                    else:
                        v = _py_value(e, consts)
                        argv.append('<?>' if v is None else (f'{v:g}' if isinstance(v, float) else str(v)))
                calls.append({'argv': argv, 'line': node.lineno})
        elif isinstance(node, (ast.Constant, ast.JoinedStr)):
            v = _py_value(node, consts)
            if isinstance(v, str) and re.match(r'\s*"?[^\s"]*ffmpeg(\.exe)?"?\s+-', v, re.I):
                toks = _tokens(v, 'cmd' if re.search(r'[A-Za-z]:\\', v) else 'sh')
                calls.append({'argv': toks[1:], 'line': node.lineno})
    calls.sort(key=lambda c: c['line'])
    return calls


def _echo_lists(lines):
    """Concat-demuxer list files a script writes with echo (or a heredoc): {file name: [lines]}."""
    lists = {}
    heredoc = None
    for s in lines:
        if heredoc:
            if s.strip() == heredoc[1]:
                heredoc = None
            else:
                lists.setdefault(heredoc[0], []).append(s.strip())
            continue
        m = re.search(r'cat\s*>\s*["\']?([^\s"\'<]+)["\']?\s*<<-?\s*["\']?(\w+)', s)
        if m:
            heredoc = (os.path.basename(m.group(1)).lower(), m.group(2))
            lists[heredoc[0]] = []
            continue
        m = re.search(r'echo\s+\(?\s*(["]?)((?:file|inpoint|outpoint|duration)\s+.+?)\1\s*\)?\s*(>>?)\s*["\']?'
                      r'([^"\'\s)]+)', s, re.I)
        if m:
            key = os.path.basename(m.group(4)).lower()
            if m.group(3) == '>':
                lists[key] = []
            lists.setdefault(key, []).append(m.group(2).strip())
    return lists


def _find_calls(text, path, base_dir):
    ext = path.suffix.lower() if path else ''
    if ext == '.py' or (not path and re.search(r'^\s*(import|from)\s+\w+', text, re.M)):
        calls = _py_calls(text)
        if calls:
            return calls, {}, 'py'
    style = _style_of(path, text)
    batch = ext in ('.bat', '.cmd')
    lines = _joined_lines(text, style)
    vars_ = {}
    calls = []
    for n, line in enumerate(lines):
        s = line.strip()
        if not s or re.match(r'(?i)^(#|::|rem\s|@rem\s|@echo)', s):
            continue
        if _set_var(s, style, vars_, base_dir, batch):
            continue
        s = _expand(s, style, vars_, base_dir, batch)
        try:
            toks = _tokens(s, style)
        except ValueError:
            continue
        for k, tok in enumerate(toks):
            if _FF_EXE.match(tok.strip('"\'').lstrip('&').strip()):
                argv = []
                for t in toks[k + 1:]:
                    if t in _SEPS or re.fullmatch(r'\d?>>?.*', t):
                        break
                    argv.append(t)
                calls.append({'argv': argv, 'line': n + 1})
                break
    return calls, _echo_lists(lines), style
