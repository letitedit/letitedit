"""A tiny QML/JS evaluator: what a filter's settings panel offers.

Part of `effects_catalog` (letitedit/timeline/effects_catalog.py), which imports every name here back,
so `effects_catalog.X` is the same object it always was.
"""
from __future__ import annotations
import bisect
import math
import re
from letitedit.timeline.effects_catalog_yaml import (  # noqa: E402
    CONTROLS_QML
)


# =============================================================================== a tiny QML/JS evaluator

class _Bail(Exception):
    pass


class _Unknown:
    def __repr__(self):
        return '<?>'


_UNK = _Unknown()
_TOKEN_RE = re.compile(r'''(?P<ws>\s+|//[^\n]*|/\*.*?\*/)
    |(?P<num>0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)
    |(?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
    |(?P<name>[A-Za-z_$][\w$]*)
    |(?P<op>===|!==|==|!=|<=|>=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|=>|[-+*/%<>=!?:.,;(){}\[\]&|^~])
    |(?P<other>.)''', re.S | re.X)
_SPECIAL = {'true': True, 'false': False, 'null': None, 'undefined': None, 'filter.isNew': True,
            'application.OS': 'Windows', 'Font.Normal': 400, 'Font.Bold': 700, 'Font.Light': 300,
            'Font.Medium': 500, 'Font.DemiBold': 600, 'Math.PI': math.pi}
_OPEN = {'(': ')', '[': ']', '{': '}'}


def _unescape(s):
    def one(m):
        c = m.group(1)
        if c.startswith('u') and len(c) == 5:
            return chr(int(c[1:], 16))
        return {'n': '\n', 't': '\t', 'r': '\r'}.get(c, c)
    return re.sub(r'\\(u[0-9a-fA-F]{4}|.)', one, s, flags=re.S)


def _tokenize(src):
    out = []
    for m in _TOKEN_RE.finditer(src):
        kind = m.lastgroup
        if kind == 'ws':
            continue
        t = m.group()
        if kind == 'num':
            v = int(t, 16) if t[:2].lower() == '0x' else (float(t) if any(c in t for c in '.eE') else int(t))
        elif kind == 'str':
            v = _unescape(t[1:-1])
        else:
            v = t
        out.append((kind, v, m.start()))
    return out


def _known(*vals):
    return all(v is not _UNK for v in vals)


def _truthy(v):
    return not (v is None or v is False or v == 0 or v == '' or (isinstance(v, float) and math.isnan(v)))


def _js_str(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if v is None:
        return 'null'
    if isinstance(v, list):
        return ','.join(_js_str(x) for x in v)
    return str(v)


def _num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return _UNK
    return _UNK


def _binop(op, a, b):
    if not _known(a, b):
        return _UNK
    try:
        if op == '+':
            if isinstance(a, str) or isinstance(b, str):
                return _js_str(a) + _js_str(b)
            if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
                return _UNK
            return a + b
        if op in ('===', '=='):
            return a == b
        if op in ('!==', '!='):
            return a != b
        if op == '-':
            return a - b
        if op == '*':
            return a * b
        if op == '/':
            return a / b
        if op == '%':
            return math.fmod(a, b)
        if op == '<':
            return a < b
        if op == '>':
            return a > b
        if op == '<=':
            return a <= b
        if op == '>=':
            return a >= b
    except Exception:  # noqa: BLE001 - type errors etc. are simply unknown
        return _UNK
    return _UNK


def _rgba(args):
    if len(args) < 3 or not all(isinstance(a, (int, float)) for a in args[:4]):
        return _UNK
    r, g, b = args[:3]
    a = args[3] if len(args) > 3 else 1
    c = [max(0, min(255, int(round(x * 255)))) for x in (a, r, g, b)]
    return '#' + ''.join(f'{x:02x}' for x in c)


def _method(obj, meth, args):
    if not _known(obj, *args):
        return _UNK
    if isinstance(obj, str):
        if meth == 'arg' and args:
            nums = sorted(int(x) for x in re.findall(r'%(\d+)', obj))
            return obj.replace(f'%{nums[0]}', _js_str(args[0])) if nums else obj
        if meth == 'toLowerCase':
            return obj.lower()
        if meth == 'toUpperCase':
            return obj.upper()
        if meth == 'trim':
            return obj.strip()
        if meth == 'toString':
            return obj
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if meth == 'toFixed':
            return f'{obj:.{int(args[0]) if args else 0}f}'
        if meth == 'toString':
            return _js_str(obj)
    if isinstance(obj, list):
        if meth == 'slice':
            return list(obj[int(args[0]) if args else 0:int(args[1]) if len(args) > 1 else None])
        if meth == 'concat':
            out = list(obj)
            for a in args:
                out.extend(a if isinstance(a, list) else [a])
            return out
    return _UNK


_MATH = {'round': lambda x: math.floor(x + 0.5), 'floor': math.floor, 'ceil': math.ceil, 'abs': abs, 'sqrt': math.sqrt,
         'min': min, 'max': max, 'pow': math.pow, 'log': math.log, 'exp': math.exp}


class _JS:
    """Runs the parts of Shotcut's QML JavaScript that set filter properties: literals, symbols, arithmetic,
    string concat, qsTr/Qt.rgba/Math, if/else (unknown conditions take the if branch), simple counted for loops,
    var, filter.set(name, value) and filter.resetProperty(name). Anything else evaluates to 'unknown'."""

    def __init__(self, toks, sym, sets):
        self.t, self.sym, self.sets = toks, sym, sets
        self.i, self.active, self.ref = 0, False, None

    # ------------------------------------------------------------------ tokens
    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ('eof', None, -1)

    def at(self, v):
        k, val, _ = self.peek()
        return k in ('op', 'name') and val == v

    def take(self, v):
        if not self.at(v):
            raise _Bail(v)
        self.i += 1

    def skip_balanced(self):
        depth = 0
        while self.i < len(self.t):
            k, v, _ = self.t[self.i]
            self.i += 1
            if k == 'op' and v in _OPEN:
                depth += 1
            elif k == 'op' and v in (')', ']', '}'):
                depth -= 1
                if depth <= 0:
                    return

    def skip_statement(self):
        k, v, _ = self.peek()
        if k == 'eof':
            return
        if k == 'op' and v == '{':
            self.skip_balanced()
            return
        if k == 'name' and v in ('if', 'for', 'while', 'switch', 'with'):
            self.i += 1
            if self.at('('):
                self.skip_balanced()
            self.skip_statement()
            if v == 'if' and self.at('else'):
                self.i += 1
                self.skip_statement()
            return
        if k == 'name' and v == 'function':
            self.i += 1
            if self.peek()[0] == 'name':
                self.i += 1
            if self.at('('):
                self.skip_balanced()
            if self.at('{'):
                self.skip_balanced()
            return
        depth = 0
        while True:
            k, v, _ = self.peek()
            if k == 'eof':
                return
            if k == 'op' and v in _OPEN:
                depth += 1
            elif k == 'op' and v in (')', ']', '}'):
                if depth == 0:
                    return
                depth -= 1
            elif k == 'op' and v == ';' and depth == 0:
                self.i += 1
                return
            self.i += 1

    # ------------------------------------------------------------------ statements
    def statement(self, active):
        saved, start = self.active, self.i
        self.active = active
        try:
            self._statement()
        except (_Bail, RecursionError, IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            self.i = start
            self.skip_statement()
            if self.i == start:
                self.i += 1
        finally:
            self.active = saved

    def _statement(self):
        k, v, _ = self.peek()
        if k == 'op' and v == '{':
            self.i += 1
            while not self.at('}') and self.peek()[0] != 'eof':
                self.statement(self.active)
            if self.at('}'):
                self.i += 1
            return
        if k == 'op' and v == ';':
            self.i += 1
            return
        if k == 'name':
            if v == 'if':
                self.i += 1
                self.take('(')
                cond = self.expr()
                self.take(')')
                truth = None if cond is _UNK else _truthy(cond)
                self.statement(self.active and truth is not False)
                if self.at('else'):
                    self.i += 1
                    self.statement(self.active and truth is False)
                return
            if v == 'for':
                self.for_statement()
                return
            if v in ('while', 'switch', 'function', 'try', 'do', 'return', 'break', 'continue', 'throw', 'delete'):
                self.skip_statement()
                return
            if v in ('var', 'let', 'const'):
                self.i += 1
                while True:
                    kind, name, _ = self.peek()
                    if kind != 'name':
                        raise _Bail('var')
                    self.i += 1
                    val = _UNK
                    if self.at('='):
                        self.i += 1
                        val = self.expr()
                    if self.active:
                        self.sym[name] = val
                    if not self.at(','):
                        break
                    self.i += 1
                if self.at(';'):
                    self.i += 1
                return
        self.expr()
        while self.at(','):
            self.i += 1
            self.expr()
        if self.at(';'):
            self.i += 1

    def for_statement(self):
        self.i += 1
        if not self.at('('):
            raise _Bail('for')
        start = self.i
        self.skip_balanced()
        header = self.t[start + 1:self.i - 1]
        body = self.i
        parts, cur, depth = [], [], 0
        for tok in header:
            if tok[0] == 'op' and tok[1] in _OPEN:
                depth += 1
            elif tok[0] == 'op' and tok[1] in (')', ']', '}'):
                depth -= 1
            if tok[0] == 'op' and tok[1] == ';' and depth == 0:
                parts.append(cur)
                cur = []
            else:
                cur.append(tok)
        parts.append(cur)
        span = None
        if len(parts) == 3 and self.active:
            init, cond, _step = parts
            j = 1 if init and init[0][1] in ('var', 'let') else 0
            if len(init) > j + 2 and init[j][0] == 'name' and init[j + 1][1] == '=' and len(cond) > 2 \
                    and cond[0][1] == init[j][1] and cond[1][1] in ('<', '<='):
                first = _JS(init[j + 2:], self.sym, {}).value()
                bound = _JS(cond[2:], self.sym, {}).value()
                if isinstance(first, (int, float)) and isinstance(bound, (int, float)):
                    last = int(bound) + (1 if cond[1][1] == '<=' else 0)
                    if 0 <= last - int(first) <= 256:
                        span = (init[j][1], range(int(first), last))
        if span is None:
            self.statement(False)
            return
        name, rng = span
        if not rng:
            self.statement(False)
        for idx in rng:
            self.i = body
            self.sym[name] = idx
            self.statement(True)

    # ------------------------------------------------------------------ expressions
    def value(self):
        try:
            return self.expr()
        except (_Bail, RecursionError, IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            return _UNK

    def expr(self):
        val = self.ternary()
        k, v, _ = self.peek()
        if k == 'op' and v in ('=', '+=', '-=', '*=', '/='):
            target = self.ref
            self.i += 1
            rhs = self.expr()
            if self.active and target and not target.startswith('filter.'):
                self.sym[target] = rhs if v == '=' else _binop(v[0], self.sym.get(target, _UNK), rhs)
            return rhs
        return val

    def ternary(self):
        cond = self.logic_or()
        if self.at('?'):
            self.i += 1
            a = self.expr()
            self.take(':')
            b = self.expr()
            if cond is _UNK:
                return _UNK
            return a if _truthy(cond) else b
        return cond

    def logic_or(self):
        a = self.logic_and()
        while self.at('||'):
            self.i += 1
            b = self.logic_and()
            a = _UNK if a is _UNK else (a if _truthy(a) else b)
        return a

    def logic_and(self):
        a = self.equality()
        while self.at('&&'):
            self.i += 1
            b = self.equality()
            a = _UNK if a is _UNK else (b if _truthy(a) else a)
        return a

    def equality(self):
        a = self.relational()
        while self.peek()[0] == 'op' and self.peek()[1] in ('===', '!==', '==', '!='):
            op = self.peek()[1]
            self.i += 1
            a = _binop(op, a, self.relational())
        return a

    def relational(self):
        a = self.additive()
        while (self.peek()[0] == 'op' and self.peek()[1] in ('<', '>', '<=', '>=')) or self.at('in') \
                or self.at('instanceof'):
            op = self.peek()[1]
            self.i += 1
            b = self.additive()
            a = _binop(op, a, b) if op not in ('in', 'instanceof') else _UNK
        return a

    def additive(self):
        a = self.multiplicative()
        while self.peek()[0] == 'op' and self.peek()[1] in ('+', '-'):
            op = self.peek()[1]
            self.i += 1
            a = _binop(op, a, self.multiplicative())
        return a

    def multiplicative(self):
        a = self.unary()
        while self.peek()[0] == 'op' and self.peek()[1] in ('*', '/', '%'):
            op = self.peek()[1]
            self.i += 1
            a = _binop(op, a, self.unary())
        return a

    def unary(self):
        k, v, _ = self.peek()
        if k == 'op' and v in ('!', '-', '+', '~'):
            self.i += 1
            a = self.unary()
            self.ref = None
            if a is _UNK:
                return _UNK
            if v == '!':
                return not _truthy(a)
            n = _num(a)
            if n is _UNK:
                return _UNK
            return -n if v == '-' else (n if v == '+' else ~int(n))
        if k == 'op' and v in ('++', '--'):
            self.i += 1
            self.unary()
            return _UNK
        if k == 'name' and v in ('typeof', 'void'):
            self.i += 1
            self.unary()
            return _UNK
        return self.postfix()

    def postfix(self):
        val, path = self.primary()
        obj = meth = None
        while True:
            if self.at('.') and self.peek(1)[0] == 'name':
                name = self.peek(1)[1]
                self.i += 2
                obj, meth = val, name
                if path is not None:
                    path = f'{path}.{name}'
                    val = self.lookup(path)
                else:
                    val = self.member(val, name)
            elif self.at('['):
                self.i += 1
                idx = self.expr()
                self.take(']')
                val, path, obj, meth = self.index(val, idx), None, None, None
            elif self.at('('):
                self.i += 1
                args = []
                while not self.at(')'):
                    if self.peek()[0] == 'eof':
                        raise _Bail('args')
                    args.append(self.expr())
                    if self.at(','):
                        self.i += 1
                    elif not self.at(')'):
                        raise _Bail('args')
                self.i += 1
                val = self.call(path, obj, meth, args)
                path = obj = meth = None
            elif self.at('++') or self.at('--'):
                self.i += 1
            else:
                break
        self.ref = path
        return val

    def primary(self):
        k, v, _ = self.peek()
        if k in ('num', 'str'):
            self.i += 1
            return v, None
        if k == 'op' and v == '(':
            self.i += 1
            val = self.expr()
            while self.at(','):
                self.i += 1
                val = self.expr()
            self.take(')')
            return val, None
        if k == 'op' and v == '[':
            self.i += 1
            items = []
            while not self.at(']'):
                if self.peek()[0] == 'eof':
                    raise _Bail('array')
                items.append(self.expr())
                if self.at(','):
                    self.i += 1
                elif not self.at(']'):
                    raise _Bail('array')
            self.i += 1
            return items, None
        if k == 'op' and v == '{':
            self.i += 1
            obj = {}
            while not self.at('}'):
                kk, kv, _ = self.peek()
                if kk not in ('name', 'str', 'num'):
                    raise _Bail('object')
                self.i += 1
                self.take(':')
                obj[_js_str(kv)] = self.expr()
                if self.at(','):
                    self.i += 1
                elif not self.at('}'):
                    raise _Bail('object')
            self.i += 1
            return obj, None
        if k == 'name':
            if v == 'function':
                self.i += 1
                if self.peek()[0] == 'name':
                    self.i += 1
                if self.at('('):
                    self.skip_balanced()
                if self.at('{'):
                    self.skip_balanced()
                return _UNK, None
            if v == 'new':
                self.i += 1
                self.postfix()
                return _UNK, None
            self.i += 1
            return self.lookup(v), v
        raise _Bail(f'primary {v!r}')

    # ------------------------------------------------------------------ values
    def lookup(self, path):
        if path in self.sym:
            return self.sym[path]
        if path in _SPECIAL:
            return _SPECIAL[path]
        head, _, rest = path.partition('.')
        if rest and head in self.sym:
            val = self.sym[head]
            for part in rest.split('.'):
                val = self.member(val, part)
            return val
        return _UNK

    @staticmethod
    def member(val, name):
        if name == 'length' and isinstance(val, (list, str)):
            return len(val)
        if isinstance(val, dict):
            return val.get(name, _UNK)
        return _UNK

    @staticmethod
    def index(val, idx):
        if isinstance(val, list) and isinstance(idx, (int, float)) and not isinstance(idx, bool) \
                and 0 <= int(idx) < len(val):
            return val[int(idx)]
        if isinstance(val, dict) and isinstance(idx, str):
            return val.get(idx, _UNK)
        return _UNK

    def call(self, path, obj, meth, args):
        if path == 'filter.set':
            if self.active and len(args) == 2 and isinstance(args[0], str) and args[0] \
                    and isinstance(args[1], (bool, int, float, str)):
                self.sets[args[0]] = _clean_value(args[1])
            return _UNK
        if path == 'filter.resetProperty':
            if self.active and args and isinstance(args[0], str):
                self.sets.pop(args[0], None)
            return _UNK
        if path in ('qsTr', 'qsTrId'):
            return args[0] if args else _UNK
        if path == 'qsTranslate':
            return args[1] if len(args) > 1 else _UNK
        if path == 'Qt.rgba':
            return _rgba(args)
        if path == 'Qt.color':
            return args[0] if args and isinstance(args[0], str) else _UNK
        if path and path.startswith('Math.') and path[5:] in _MATH:
            nums = [_num(a) for a in args]
            if nums and _known(*nums):
                try:
                    return _MATH[path[5:]](*nums)
                except (TypeError, ValueError, OverflowError):
                    return _UNK
            return _UNK
        if path == 'String':
            return _js_str(args[0]) if args and _known(args[0]) else _UNK
        if path in ('Number', 'parseFloat'):
            return _num(args[0]) if args else _UNK
        if path == 'parseInt':
            n = _num(args[0]) if args else _UNK
            return int(n) if n is not _UNK else _UNK
        if path == 'application.audioChannels':
            return 2
        if path == 'fromDb':
            n = _num(args[0]) if args else _UNK
            return 10 ** (n / 20) if n is not _UNK else _UNK
        if path and '.' in path:
            head, meth = path.rsplit('.', 1)
            obj = self.lookup(head)
        if meth and obj is not None:
            return _method(obj, meth, args)
        return _UNK


def _clean_value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return int(v)
        return float(f'{v:.10g}')
    return v


class _Qml:
    """A QML file, tokenized once; evaluate expressions or run statements starting at character offsets."""

    def __init__(self, path):
        self.path = path
        self.text = path.read_text(encoding='utf-8', errors='replace')
        self.toks = _tokenize(self.text)
        self.pos = [t[2] for t in self.toks]

    def tok_at(self, offset):
        return bisect.bisect_left(self.pos, offset)

    def eval_at(self, offset, sym):
        js = _JS(self.toks, sym, {})
        js.i = self.tok_at(offset)
        return js.value()

    def run_at(self, offset, sym, sets):
        js = _JS(self.toks, sym, sets)
        js.i = self.tok_at(offset)
        js.statement(True)


_DECL = re.compile(r'(?m)^[ \t]*(?:(?:readonly|required|default)[ \t]+)*property[ \t]+[\w.<>]+[ \t]+(\w+)[ \t]*(:)?')
_ONCOMPLETED = re.compile(r'Component\.onCompleted\s*:')
_FILTER_CALL = re.compile(r'\bfilter\.(?:set|get|getDouble|getInt|getColor|getRect|getBool|resetProperty|'
                          r'keyframeCount|getKeyFrameType|setKeyFrameType)\s*\(')
_PRESET_PARAMS = re.compile(r'\bparameters\s*:')
_ARRAY_SYMBOLS = ('defaultParameters', 'keyframableParameters', 'allParams', 'allParameters', 'parameterList')


def _declare(q, sym, skip=()):
    """Evaluate `property <type> name: expr` declarations into sym. Returns every declared name."""
    names = set()
    for m in _DECL.finditer(q.text):
        names.add(m.group(1))
        if m.group(2) and m.group(1) not in skip:
            v = q.eval_at(m.end(), sym)
            if v is not _UNK or m.group(1) not in sym:
                sym[m.group(1)] = v
    return names


_base_sym_cache = None


def _base_symbols():
    """Symbols every filter UI can reference: textFilterUi.* from Shotcut.Controls' TextFilterUi."""
    global _base_sym_cache
    if _base_sym_cache is None:
        base = {}
        path = CONTROLS_QML / 'TextFilterUi.qml'
        if path.is_file():
            q = _Qml(path)
            local = {}
            _declare(q, local)
            _declare(q, local)
            base.update({f'textFilterUi.{k}': v for k, v in local.items() if v is not _UNK})
        _base_sym_cache = base
    return dict(_base_sym_cache)


def _ui_analysis(folder, ui_name):
    """(defaults a NEW filter gets, property names the UI touches) for one ui*.qml."""
    path = folder / ui_name if ui_name else None
    if not path or not path.is_file():
        return {}, []
    ui = _Qml(path)
    files = []
    root = re.search(r'(?m)^(\w+)\s*\{', re.sub(r'/\*.*?\*/', '', ui.text, flags=re.S))
    comp_path = folder / f'{root.group(1)}.qml' if root else None
    sym = _base_symbols()
    comp_names, overrides = set(), {}
    if comp_path and comp_path.is_file() and comp_path != path:
        comp = _Qml(comp_path)
        files.append(comp)
        comp_names = _declare(comp, sym)
    files.append(ui)
    _declare(ui, sym)
    _declare(ui, sym)
    if comp_names:
        for m in re.finditer(r'(?m)^[ \t]{1,12}(\w+)\s*:', ui.text):
            if m.group(1) in comp_names:
                v = ui.eval_at(m.end(), sym)
                if v is not _UNK:
                    overrides[m.group(1)] = v
        sym.update(overrides)
        _declare(files[0], sym, skip=set(overrides))
        sym.update(overrides)
    sets = {}
    for q in files:
        for m in _ONCOMPLETED.finditer(q.text):
            q.run_at(m.end(), sym, sets)
    touched = []
    for q in files:
        for m in _FILTER_CALL.finditer(q.text):
            v = q.eval_at(m.end(), sym)
            if isinstance(v, str):
                touched.append(v)
        for m in _PRESET_PARAMS.finditer(q.text):
            v = q.eval_at(m.end(), sym)
            if isinstance(v, list):
                touched.extend(x for x in v if isinstance(x, str))
    for nm in _ARRAY_SYMBOLS:
        v = sym.get(nm)
        if isinstance(v, list):
            touched.extend(x for x in v if isinstance(x, str))
    if 'TextFilterUi' in ui.text:
        touched.extend(x for x in sym.get('textFilterUi.parameterList') or [] if isinstance(x, str))
    return sets, touched


def _match_brace(text, i):
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return j
    return len(text)


def _parse_meta(path):
    """A Shotcut meta*.qml -> dict of its fields plus 'parameters' (the keyframable ones)."""
    q = _Qml(path)
    text = q.text
    params, spans = [], []
    for m in re.finditer(r'\bParameter\s*\{', text):
        end = _match_brace(text, m.end() - 1)
        spans.append((m.start(), end))
        fields = {}
        for f in re.finditer(r'(?m)^[ \t]*(\w+)[ \t]*:', text[m.end():end]):
            fields[f.group(1)] = q.eval_at(m.end() + f.end(), {})
        params.append(fields)
    meta = {'parameters': params}
    for f in re.finditer(r'(?m)^[ \t]*(\w+)[ \t]*:', text):
        if any(a <= f.start() < b for a, b in spans) or f.group(1) in meta:
            continue
        meta[f.group(1)] = q.eval_at(f.end(), {})
    t = re.search(r'\btype\s*:\s*Metadata\.(\w+)', text)
    meta['type'] = t.group(1) if t else 'Filter'
    return meta
