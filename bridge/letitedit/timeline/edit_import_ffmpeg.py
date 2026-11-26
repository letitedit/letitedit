"""The ffmpeg form: command lines, their options and filter graphs rebuilt as tracks, the rest as made clips.

Part of `edit_import` (letitedit/timeline/edit_import.py), which imports every name here back,
so `edit_import.X` is the same object it always was.
"""
from __future__ import annotations
import ast
import copy
import math
import os
import re
import sys
from fractions import Fraction
from pathlib import Path
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import letitedit.timeline.edit_script as es  # noqa: E402
import letitedit.timeline.made as made  # noqa: E402
from letitedit.timeline.edit_import_common import (  # noqa: E402
    _ass_escape, _ass_time, _db, _find_media, _has_alpha, _image_size, _kind_of_file, _probe, _probe_cache, _r,
    _time, item_len
)
from letitedit.timeline.edit_import_scripts import (  # noqa: E402
    _find_calls
)


# ============================================================================ ffmpeg: one call

_BOOL_OPTS = {'-y', '-n', '-nostdin', '-stdin', '-hide_banner', '-shortest', '-an', '-vn', '-sn', '-dn', '-re', '-stats',
              '-nostats', '-copyts', '-start_at_zero', '-benchmark', '-benchmark_all', '-accurate_seek',
              '-noaccurate_seek', '-autorotate', '-noautorotate', '-ignore_unknown', '-copy_unknown', '-xerror',
              '-debug_ts', '-dump', '-hex', '-bitexact', '-vstats', '-psnr', '-find_stream_info', '-nofind_stream_info',
              '-autoscale', '-noautoscale', '-fix_sub_duration', '-report', '-print_graphs', '-seek_timestamp',
              '-qphist', '-nohide_banner'}
_GLOBAL_OPTS = {'-filter_complex', '-lavfi', '-filter_complex_script', '-/filter_complex', '-loglevel', '-v',
                '-filter_threads', '-filter_complex_threads', '-stats_period', '-progress', '-max_error_rate',
                '-print_graphs_file', '-print_graphs_format'}
_NULL_OUT = {'-', 'nul', '/dev/null', 'null'}


def _parse_call(argv):
    inputs, outputs, glob, pend = [], [], {}, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '-i' and i + 1 < len(argv):
            inputs.append({'raw': argv[i + 1], 'opts': pend, 'idx': len(inputs)})
            pend = []
            i += 2
            continue
        if a.startswith('-') and len(a) > 1 and not re.fullmatch(r'-[\d.]+', a):
            if a in _BOOL_OPTS:
                pend.append((a, True))
                i += 1
                continue
            if a in _GLOBAL_OPTS:
                glob[a] = argv[i + 1] if i + 1 < len(argv) else ''
                i += 2
                continue
            pend.append((a, argv[i + 1] if i + 1 < len(argv) else None))
            i += 2
            continue
        outputs.append({'path': a, 'opts': pend})
        pend = []
        i += 1
    if pend and outputs:
        outputs[-1]['opts'] += pend
    return {'inputs': inputs, 'outputs': outputs, 'global': glob}


def _opt(opts, *names, default=None):
    got = default
    for k, v in opts:
        if k in names:
            got = v
    return got


def _has(opts, name):
    return any(k == name for k, _ in opts)


# ------------------------------------------------------------------------ filter graph text

def _split_top(text, sep):
    out, cur, q, depth, i = [], [], False, 0, 0
    while i < len(text):
        c = text[i]
        if c == '\\' and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c == "'":
            q = not q
        elif not q and c == '[':
            depth += 1
        elif not q and c == ']':
            depth = max(0, depth - 1)
        if c == sep and not q and depth == 0:
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append(''.join(cur))
    return out


def _unquote(v):
    """A filter option value without its quotes and backslash escapes."""
    out, q, i = [], False, 0
    v = v.strip()
    while i < len(v):
        c = v[i]
        if c == "'":
            q = not q
            i += 1
            continue
        if c == '\\' and i + 1 < len(v):
            out.append(v[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _quote_path(p):
    """A file path as a filter option value."""
    s = str(p).replace('\\', '/').replace("'", "\\'").replace(':', '\\:')
    return f"'{s}'"


class _Node:
    def __init__(self, name, args, ins, outs):
        self.full = name
        self.name = name.split('@')[0].strip()
        self.args = args
        self.ins, self.outs = list(ins), list(outs)
        self.pos, self.kw = [], {}
        self._parse()

    def _parse(self):
        self.pos, self.kw = [], {}
        if self.args:
            for part in _split_top(self.args, ':'):
                m = re.match(r'^\s*([A-Za-z_][\w]*)\s*=(.*)$', part, re.S)
                if m:
                    self.kw[m.group(1)] = _unquote(m.group(2))
                else:
                    self.pos.append(_unquote(part))

    def set_arg(self, key, index, value):
        """Rewrite one option (by name, or positional index) with an already-escaped value."""
        parts = _split_top(self.args, ':') if self.args else []
        for k, part in enumerate(parts):
            m = re.match(r'^\s*([A-Za-z_][\w]*)\s*=', part)
            if m and m.group(1) == key:
                parts[k] = f'{key}={value}'
                break
        else:
            pos = [k for k, part in enumerate(parts) if not re.match(r'^\s*[A-Za-z_][\w]*\s*=', part)]
            if index is not None and index < len(pos):
                parts[pos[index]] = value
            else:
                parts.append(f'{key}={value}')
        self.args = ':'.join(parts)
        self._parse()

    @property
    def raw(self):
        return self.full + (f'={self.args}' if self.args else '')

    def text(self, ins=None, outs=None):
        ins = self.ins if ins is None else ins
        outs = self.outs if outs is None else outs
        return ''.join(f'[{x}]' for x in ins) + self.raw + ''.join(f'[{x}]' for x in outs)

    def opt(self, names, index=None, default=None):
        for n in names:
            if n in self.kw:
                return self.kw[n]
        if index is not None and index < len(self.pos):
            return self.pos[index]
        return default

    def __repr__(self):
        return f'<{self.text()}>'


AUDIO_FILTERS = {'volume', 'pan', 'loudnorm', 'highpass', 'lowpass', 'bandpass', 'bandreject', 'equalizer', 'bass',
                 'treble', 'dynaudnorm', 'compand', 'silenceremove', 'sidechaincompress', 'sidechaingate', 'stereotools',
                 'channelsplit', 'channelmap', 'join', 'firequalizer', 'rubberband', 'speechnorm', 'deesser',
                 'superequalizer', 'earwax', 'extrastereo', 'crystalizer', 'chorus', 'flanger', 'vibrato', 'tremolo',
                 'headphone', 'surround', 'silencedetect', 'volumedetect', 'replaygain', 'sine', 'anullsrc', 'ebur128',
                 'lowshelf', 'highshelf', 'compensationdelay', 'haas', 'dialoguenhance', 'virtualbass'}
NOT_AUDIO = {'alphaextract', 'alphamerge', 'amplify', 'atadenoise', 'avgblur', 'ass', 'addroi', 'avsynctest'}


def _is_audio_filter(name):
    return name in AUDIO_FILTERS or (name.startswith('a') and name not in NOT_AUDIO)


_INREF = re.compile(r'(\d+)(?::([vVa]))?(?::\d+)?\??')
_SOURCES = {'color', 'testsrc', 'testsrc2', 'smptebars', 'smptehdbars', 'nullsrc', 'anullsrc', 'sine', 'aevalsrc',
            'mandelbrot', 'gradients', 'cellauto', 'life', 'rgbtestsrc', 'allrgb', 'allyuv', 'yuvtestsrc', 'movie',
            'amovie', 'anoisesrc', 'colorchart', 'colorspectrum', 'pal75bars', 'pal100bars', 'haldclutsrc', 'buffer',
            'abuffer', 'zoneplate', 'ddagrab'}
_FILE_ARGS = {'subtitles': ('filename', 'f'), 'ass': ('filename', 'f'), 'lut3d': ('file',), 'movie': ('filename',),
              'amovie': ('filename',), 'drawtext': ('fontfile', 'textfile'), 'curves': ('psfile',)}


def _absolute_files(node, dirs):
    """Point a filter's file options (subtitles, lut3d, fontfile...) at absolute paths."""
    keys = _FILE_ARGS.get(node.name)
    if not keys:
        return
    for key in keys:
        val = node.kw.get(key)
        index = None
        if val is None and key in ('filename', 'file') and node.pos:
            val, index = node.pos[0], 0
        if not val or os.path.isabs(val):
            continue
        got = _find_media(val, dirs)
        if got:
            node.set_arg(key, index, _quote_path(got))


def _parse_graph(text, first_in=None, last_out=None, tag='g'):
    """Filter nodes with explicit labels. first_in: the label an unlabeled graph input reads (else '?');
    last_out: the label for the unlabeled graph output (else '_<tag>o<k>'). Returns (nodes, unlabeled outputs)."""
    nodes, outs_unl = [], []
    k = 0
    for chain in _split_top(text.strip().rstrip(';'), ';'):
        if not chain.strip():
            continue
        parsed = []
        for ftext in _split_top(chain, ','):
            s = ftext.strip()
            if not s:
                continue
            ins, outs = [], []
            while s.startswith('['):
                m = re.match(r'\[([^\]]*)\]\s*', s)
                ins.append(m.group(1).strip())
                s = s[m.end():]
            while s.endswith(']'):
                m = re.search(r'\[([^\[\]]*)\]\s*$', s)
                if not m:
                    break
                outs.insert(0, m.group(1).strip())
                s = s[:m.start()].rstrip()
            name, _, args = s.partition('=')
            parsed.append(_Node(name.strip(), args.strip(), ins, outs))
        for fi, node in enumerate(parsed):
            if fi > 0:
                prev = parsed[fi - 1]
                if not prev.outs:
                    k += 1
                    lab = f'_{tag}{k}'
                    prev.outs = [lab]
                    node.ins = node.ins + [lab]
            elif not node.ins and node.name not in _SOURCES:
                node.ins = [first_in or '?']
            if fi == len(parsed) - 1 and not node.outs:
                k += 1
                lab = last_out if (last_out and not outs_unl) else f'_{tag}o{k}'
                node.outs = [lab]
                outs_unl.append(lab)
        nodes += parsed
    return nodes, outs_unl


# ------------------------------------------------------------------------ expressions

_CONSTS = {'PI': math.pi, 'E': math.e, 'PHI': (1 + 5 ** 0.5) / 2}
_FUNCS = {'min': min, 'max': max, 'abs': abs, 'floor': math.floor, 'ceil': math.ceil, 'round': round,
          'trunc': math.trunc, 'sqrt': math.sqrt, 'pow': pow, 'mod': math.fmod, 'exp': math.exp, 'log': math.log,
          'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'clip': lambda x, a, b: min(max(x, a), b),
          '_if': lambda c, a, b=0: a if c else b, '_ifnot': lambda c, a, b=0: b if c else a,
          'between': lambda x, a, b: float(a <= x <= b), 'gte': lambda a, b: float(a >= b),
          'gt': lambda a, b: float(a > b), 'lte': lambda a, b: float(a <= b), 'lt': lambda a, b: float(a < b),
          'eq': lambda a, b: float(a == b), '_not': lambda x: float(not x), 'hypot': math.hypot}


def _calc(expr, names):
    """Value of an ffmpeg expression; NameError when it uses a name not in `names` (t, n...)."""
    e = str(expr).strip().strip("'")
    e = re.sub(r'\bif\(', '_if(', e)
    e = re.sub(r'\bifnot\(', '_ifnot(', e)
    e = re.sub(r'\bnot\(', '_not(', e)
    e = e.replace('^', '**')
    try:
        tree = ast.parse(e, mode='eval')
    except SyntaxError:
        raise NameError(e) from None

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in names:
                return float(names[n.id])
            if n.id in _CONSTS:
                return _CONSTS[n.id]
            raise NameError(n.id)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
                   ast.Mod: lambda: math.fmod(a, b), ast.Pow: lambda: a ** b}
            if type(n.op) not in ops:
                raise NameError('operator')
            return ops[type(n.op)]()
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return float(_FUNCS[n.func.id](*[ev(a) for a in n.args]))
        raise NameError(ast.dump(n)[:40])
    return ev(tree)


_TIMEVAR = re.compile(r'(?<![A-Za-z_0-9.])(t|n|T|N|pos|time|PTS|TB|FRAME_RATE|frame|on)(?![A-Za-z_0-9])')


def _time_dependent(node):
    if 'enable' in node.kw:
        return True
    for v in list(node.kw.values()) + node.pos:
        v = str(v)
        if _TIMEVAR.search(v) and (re.search(r'[()*+/\-]', v) or v.strip() in ('t', 'n', 'T', 'N')):
            return True
    return False


def _enable_window(expr):
    """(start, end) from an enable expression like between(t,2,5) or gte(t,2)*lte(t,5); None for anything else."""
    e = re.sub(r'\s+', '', str(expr)).strip("'")
    m = re.fullmatch(r'between\(t,([-\d.]+),([-\d.]+)\)', e)
    if m:
        return float(m.group(1)), float(m.group(2))
    a, b = 0.0, math.inf
    for part in e.split('*'):
        mm = re.fullmatch(r'(gte|gt)\(t,([-\d.]+)\)', part)
        if mm:
            a = float(mm.group(2))
            continue
        mm = re.fullmatch(r'(lte|lt)\(t,([-\d.]+)\)', part)
        if mm:
            b = float(mm.group(2))
            continue
        return None
    return a, b


# ------------------------------------------------------------------------ values

class _Fallback(Exception):
    """This part of the graph has no Shotcut equivalent (it becomes a made clip)."""


INF = math.inf


class _Inp:
    """One -i input."""

    def __init__(self, raw, opts, idx, base_dir, dirs, produced, lists, notes):
        self.raw, self.opts, self.idx = raw, opts, idx
        self.fmt = _opt(opts, '-f')

        def tm(name):
            v = _opt(opts, name)
            if v is None:
                return None
            try:
                return _time(v)
            except ValueError:
                notes.append(f'input {idx}: {name} {v} not read')
                return None
        self.ss = tm('-ss') or 0.0
        self.t = tm('-t')
        to = tm('-to')
        if self.t is None and to is not None:
            self.t = to - self.ss
        lp = _opt(opts, '-loop')
        self.loop = lp not in (None, '0', 0)
        try:
            self.stream_loop = int(_opt(opts, '-stream_loop') or 0)
        except ValueError:
            self.stream_loop = 0
        self.itsoffset = tm('-itsoffset') or 0.0
        self.lavfi = self.path = self.call = None
        self.entries = []
        self.size = None
        self.info = {}
        if self.fmt == 'lavfi':
            self.kind = 'lavfi'
            self.lavfi = raw
            return
        if self.fmt == 'concat':
            p = _find_media(raw, dirs) or (str(Path(base_dir) / raw) if not Path(raw).is_absolute() else raw)
            self.kind = 'concat'
            self.path = p
            text = Path(p).read_text(encoding='utf-8-sig', errors='replace') if os.path.isfile(p) else '\n'.join(
                lists.get(os.path.basename(raw).lower(), []))
            if not text.strip():
                raise ValueError(f'concat list {raw} not found')
            self.entries = self._concat_entries(text, Path(p).parent, dirs, notes, produced)
            return
        key = os.path.normcase(os.path.abspath(os.path.join(str(base_dir), raw)))
        if key in produced and not os.path.isfile(key):
            self.kind = 'intermediate'
            self.call = produced[key]
            self.path = key
            return
        p = _find_media(raw, dirs)
        if p is None:
            self.kind = 'missing'
            self.path = raw
            notes.append(f'input {idx} ({raw}) not found; it is a black placeholder')
            return
        self.path = p
        self.info = _probe(p)
        k = _kind_of_file(p)
        if k == 'image':
            self.kind = 'image'
            self.size = _image_size(p)
        elif k == 'audio' or not self.info.get('video'):
            self.kind = 'audio'
        else:
            self.kind = 'video'
            self.size = (self.info.get('width'), self.info.get('height'))

    def __deepcopy__(self, memo):
        return self

    @staticmethod
    def _concat_entries(text, folder, dirs, notes, produced=None):
        out, cur = [], None
        for line in text.splitlines():
            s = line.strip()
            m = re.match(r"file\s+(['\"]?)(.+?)\1\s*$", s)
            if m:
                name = m.group(2).replace("'\\''", "'")
                p = _find_media(name, [str(folder)] + list(dirs))
                cur = {'path': p or name, 'in': 0.0, 'out': None, 'found': p is not None}
                key = os.path.normcase(os.path.abspath(os.path.join(str(folder), name)))
                if p is None and produced and key in produced:
                    cur.update(call=produced[key], path=key)
                elif p is None:
                    notes.append(f'concat list file {name} not found (a black placeholder)')
                out.append(cur)
                continue
            m = re.match(r'(inpoint|outpoint|duration)\s+(\S+)', s)
            if m and cur is not None:
                v = _time(m.group(2))
                if m.group(1) == 'inpoint':
                    cur['in'] = v
                elif m.group(1) == 'outpoint':
                    cur['out'] = v
                else:
                    cur['dur'] = v
        return out

    def length(self):
        if self.t is not None:
            return self.t
        if self.kind == 'image':
            return INF if self.loop else 1 / 25.0
        d = self.info.get('duration') or 0.0
        return max(0.0, d - self.ss) if d else INF

    def lavfi_name(self):
        return re.split(r'[=,:]', self.lavfi.strip())[0] if self.lavfi else ''

    def has_video(self):
        if self.kind == 'lavfi':
            return not _is_audio_filter(self.lavfi_name())
        return self.kind in ('video', 'image', 'concat', 'missing', 'intermediate')

    def has_audio(self):
        if self.kind == 'lavfi':
            return _is_audio_filter(self.lavfi_name())
        if self.kind == 'concat':
            return any(e.get('call') or (e.get('found') and _probe(e['path']).get('audio')) for e in self.entries)
        if self.kind == 'intermediate':
            return True
        return bool(self.info.get('audio'))

    def recipe_input(self):
        d = {'clip': self.path, 'in': _r(self.ss)}
        if self.t is not None and self.kind != 'image':
            d['out'] = _r(self.ss + self.t)
        return d


class _Piece:
    """A stretch of one source on a sequence."""

    def __init__(self, kind, src=None, a=0.0, b=None, dur=None, speed=1.0, color=None, item=None, path=None):
        self.kind = kind            # clip | image | color | made | freeze | missing
        self.src = src
        self.path = path or (src.path if src is not None else None)
        self.a, self.b = a, b
        self._dur = dur
        self.speed = speed
        self.color = color
        self.item = item
        self.vchain, self.achain = [], []
        self.vfx, self.afx = [], []
        self.transition = None
        self.reverse = False
        self.origin = 0.0           # the stream time (t) at this piece's first frame, for time expressions
        self.what = ''

    def dur(self):
        if self.kind == 'clip':
            return (self.b - self.a) / self.speed
        return self._dur

    def cut(self, x, y):
        p = copy.deepcopy(self)
        full = self.dur()
        if p.kind == 'clip':
            p.a = self.a + x * self.speed
            p.b = self.a + y * self.speed
        else:
            p._dur = y - x
            if p.kind == 'made':
                p.item = _made_cut(p.item, x, y)
                if p.a is not None and p.b is not None:
                    p.a, p.b = self.a + x * self.speed, self.a + y * self.speed
            elif p.kind == 'freeze':
                pass
        p.origin = self.origin + x
        if x > 1e-9:
            p.transition = None
            p.vfx = [e for e in p.vfx if not (isinstance(e, dict) and 'fade_in' in e)]
            p.afx = [e for e in p.afx if not (isinstance(e, dict) and 'fade_in_audio' in e)]
        if full is not None and full != INF and y < full - 1e-6:
            p.vfx = [e for e in p.vfx if not (isinstance(e, dict) and 'fade_out' in e)]
            p.afx = [e for e in p.afx if not (isinstance(e, dict) and 'fade_out_audio' in e)]
        return p


def _made_cut(item, x, y):
    """A made clip's item showing only seconds x to y of it (the cut happens inside its recipe)."""
    it = copy.deepcopy(item)
    it.pop('skip', None)
    if x > 1e-9:
        if 'ass' in it:
            it['ass'] = _shift_ass(it['ass'] if '[Events]' in it['ass'] else it['ass'], x)
        elif 'ffmpeg' in it:
            f = it['ffmpeg']
            g = f.get('video') or ''
            if '[' in g:
                g = g.replace('[v]', '[mcut_v]') + f';[mcut_v]trim=start={x:.4f},setpts=PTS-STARTPTS[v]'
                if '[a]' in g:
                    g = g.replace('[a]', '[mcut_a]') + f';[mcut_a]atrim=start={x:.4f},asetpts=PTS-STARTPTS[a]'
            else:
                g = (g + ',' if g else '') + f'trim=start={x:.4f},setpts=PTS-STARTPTS'
                if isinstance(f.get('audio'), str):
                    f['audio'] = f['audio'] + f',atrim=start={x:.4f},asetpts=PTS-STARTPTS'
                elif f.get('audio') not in (False, None):
                    f['audio'] = f'atrim=start={x:.4f},asetpts=PTS-STARTPTS'
            f['video'] = g
        elif 'freeze' in it:
            pass
        else:
            it['skip'] = _r(x)
    it['len'] = _r(y - x)
    return it


def _tlen(p):
    t = p.transition
    return float(t['len']) if isinstance(t, dict) else float(t or 0)


class _V:
    def __init__(self, pieces, layers=None, pts0=0.0, size=None):
        self.pieces = list(pieces)
        self.layers = list(layers or [])
        self.pts0 = pts0
        self.size = size

    def spans(self):
        out, pos = [], 0.0
        for k, p in enumerate(self.pieces):
            if k and p.transition:
                pos -= _tlen(p)
            d = p.dur()
            out.append((p, pos, pos + d))
            pos += d
        return out

    def dur(self):
        return max((e for _, _, e in self.spans()), default=0.0)


class _Layer:
    def __init__(self, item, at, length, kind, what=''):
        self.item, self.at, self.len, self.kind, self.what = item, at, length, kind, what
        self.level = 0


class _Lane:
    def __init__(self, pieces, at=0.0, gain=0.0):
        self.pieces = list(pieces)
        self.at = at
        self.gain = gain

    def spans(self):
        out, pos = [], self.at
        for k, p in enumerate(self.pieces):
            if k and p.transition:
                pos -= _tlen(p)
            d = p.dur()
            out.append((p, pos, pos + d))
            pos += d
        return out

    def end(self):
        return max((e for _, _, e in self.spans()), default=self.at)


class _A:
    def __init__(self, lanes, pts0=0.0):
        self.lanes = list(lanes)
        self.pts0 = pts0

    def dur(self):
        return max((lane.end() for lane in self.lanes), default=0.0)


def _window_pieces(spans, x, y):
    out = []
    for p, s, e in spans:
        if e <= x + 1e-9 or s >= y - 1e-9:
            continue
        a, b = max(s, x), min(e, y)
        q = p.cut(a - s, b - s) if (a > s + 1e-9 or b < e - 1e-9) else copy.deepcopy(p)
        out.append(q)
    if out:
        out[0].transition = None
    return out


def _vwindow(v, x, y):
    pieces = _window_pieces(v.spans(), x, y)
    layers = []
    for L in v.layers:
        s, e = L.at, L.at + L.len
        if e <= x + 1e-9 or s >= y - 1e-9:
            continue
        a, b = max(s, x), min(e, y)
        it = dict(L.item)
        image = 'clip' in it and _kind_of_file(it['clip']) == 'image'
        if made.is_made(it) and 'clip' not in it:
            it = _made_cut(it, a - s, b - s)
        elif a > s + 1e-9 and 'clip' in it and not image:
            it['in'] = _r(it['in'] + (a - s) * float(it.get('speed', 1.0)))
        if made.is_made(it) and 'clip' not in it:
            pass
        elif 'clip' in it and image:
            it['out'] = _r(float(it.get('in', 0)) + (b - a))
        elif 'clip' in it and 'out' in it:
            it['out'] = _r(it['in'] + (b - a) * float(it.get('speed', 1.0)))
        else:
            it['len'] = _r(b - a)
        layers.append(_Layer(it, a - x, b - a, L.kind, L.what))
    return _V(pieces, layers, pts0=v.pts0 + x, size=v.size)


def _awindow(av, x, y):
    lanes = []
    for lane in av.lanes:
        sp = lane.spans()
        pieces = _window_pieces(sp, x, y)
        if not pieces:
            continue
        first = next((s for p, s, e in sp if e > x + 1e-9), lane.at)
        lanes.append(_Lane(pieces, at=max(first, x) - x, gain=lane.gain))
    return _A(lanes, pts0=av.pts0 + x)


# ------------------------------------------------------------------------ colours, sizes, text

_NAMED_COLORS = {'white': (255, 255, 255), 'black': (0, 0, 0), 'red': (255, 0, 0), 'green': (0, 128, 0),
                 'lime': (0, 255, 0), 'blue': (0, 0, 255), 'yellow': (255, 255, 0), 'cyan': (0, 255, 255),
                 'magenta': (255, 0, 255), 'gray': (128, 128, 128), 'grey': (128, 128, 128), 'orange': (255, 165, 0),
                 'purple': (128, 0, 128), 'pink': (255, 192, 203), 'brown': (165, 42, 42), 'silver': (192, 192, 192),
                 'gold': (255, 215, 0), 'navy': (0, 0, 128), 'darkgray': (169, 169, 169), 'lightgray': (211, 211, 211),
                 'violet': (238, 130, 238), 'teal': (0, 128, 128), 'maroon': (128, 0, 0), 'olive': (128, 128, 0)}


def _rgba(c):
    """(r, g, b, alpha 0-1) from an ffmpeg colour ('white', 'black@0.5', '0xRRGGBB[AA]', '#RRGGBB'), or None."""
    c = str(c or '').strip().strip("'")
    alpha = 1.0
    if '@' in c:
        c, al = c.split('@', 1)
        try:
            alpha = float(al) if not al.lower().startswith('0x') else int(al, 16) / 255
        except ValueError:
            return None
    low = c.lower()
    if low == 'transparent' or low == 'none':
        return (0, 0, 0, 0.0)
    if low in _NAMED_COLORS:
        return _NAMED_COLORS[low] + (alpha,)
    h = low[2:] if low.startswith('0x') else low[1:] if low.startswith('#') else low
    if re.fullmatch(r'[0-9a-f]{6}([0-9a-f]{2})?', h):
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if len(h) == 8:
            alpha *= int(h[6:8], 16) / 255
        return (r, g, b, alpha)
    return None


def _hex(rgba):
    """A Shotcut/MLT colour (#AARRGGBB)."""
    r, g, b, a = rgba
    return f'#{int(round(a * 255)):02x}{r:02x}{g:02x}{b:02x}'


def _mlt_rgba(color):
    """(r, g, b, alpha 0-1) from a Shotcut/MLT colour: #AARRGGBB, #RRGGBB, 0xRRGGBBAA or a name."""
    c = str(color or '').strip()
    h = c[1:] if c.startswith('#') else None
    if h and re.fullmatch(r'[0-9a-fA-F]{8}', h):
        return (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16) / 255)
    if h and re.fullmatch(r'[0-9a-fA-F]{6}', h):
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    return _rgba(c) or (0, 0, 0, 1.0)


def _ass_colour(rgba):
    r, g, b, a = rgba
    return f'&H{int(round((1 - a) * 255)):02X}{b:02X}{g:02X}{r:02X}'


def _size_opt(s):
    named = {'hd720': (1280, 720), 'hd1080': (1920, 1080), 'vga': (640, 480), 'qvga': (320, 240), 'svga': (800, 600),
             'xga': (1024, 768), 'uhd2160': (3840, 2160), '4k': (4096, 2160), '2k': (2048, 1080), 'ntsc': (720, 480),
             'pal': (720, 576), 'hd480': (852, 480)}
    if not s:
        return None
    s = str(s).strip().lower()
    if s in named:
        return named[s]
    m = re.fullmatch(r'(\d+)\s*[x*:]\s*(\d+)', s)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _even(x):
    return int(round(x / 2.0)) * 2


def _scale_size(size, node):
    iw, ih = size
    sz = _size_opt(node.kw.get('size') or node.kw.get('s'))
    if sz:
        w, h = sz
    else:
        we = node.opt(['w', 'width'], 0, 'iw')
        he = node.opt(['h', 'height'], 1, 'ih')
        names = {'iw': iw, 'ih': ih, 'in_w': iw, 'in_h': ih, 'a': iw / ih if ih else 1, 'sar': 1, 'dar': iw / ih if ih else 1,
                 'hsub': 2, 'vsub': 2}
        w = h = None
        for _ in range(2):
            try:
                if w is None:
                    w = _calc(we, dict(names, **({'oh': h, 'out_h': h} if h is not None else {})))
            except NameError:
                pass
            try:
                if h is None:
                    h = _calc(he, dict(names, **({'ow': w, 'out_w': w} if w is not None else {})))
            except NameError:
                pass
        if w is None or h is None:
            return size
        if w <= 0 and h <= 0:
            w, h = iw, ih
        elif w <= 0:
            w = h * iw / ih
            w = _even(w) if w and int(-w if w < 0 else 0) else round(w)
        elif h <= 0:
            h = w * ih / iw
        if w == 0:
            w = iw
        if h == 0:
            h = ih
    mode = node.kw.get('force_original_aspect_ratio')
    if mode in ('decrease', '1', 'increase', '2'):
        f = (min if mode in ('decrease', '1') else max)(w / iw, h / ih)
        w, h = iw * f, ih * f
    return (int(round(w)), int(round(h)))


def _chain_size(size, nodes):
    w, h = size
    for n in nodes:
        try:
            names = {'iw': w, 'ih': h, 'in_w': w, 'in_h': h, 'a': w / h if h else 1, 'sar': 1, 'dar': w / h if h else 1}
            if n.name == 'scale':
                w, h = _scale_size((w, h), n)
            elif n.name == 'crop':
                cw = _calc(n.opt(['w', 'out_w'], 0, 'iw'), names)
                ch = _calc(n.opt(['h', 'out_h'], 1, 'ih'), dict(names, out_w=cw, ow=cw))
                w, h = int(cw), int(ch)
            elif n.name == 'pad':
                pw = _calc(n.opt(['w', 'width'], 0, 'iw'), names)
                ph = _calc(n.opt(['h', 'height'], 1, 'ih'), dict(names, ow=pw, out_w=pw))
                w, h = int(pw or w), int(ph or h)
            elif n.name == 'transpose' and n.opt(['dir'], 0, 'cclock_flip') not in ('passthrough',):
                w, h = h, w
        except (NameError, ZeroDivisionError, TypeError, ValueError):
            pass
    return (w, h)


_FFMPEG_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&Hffffff,&Hffffff,&H0,&H0,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


_ASS_STYLE_FORMAT = next(ln for ln in _FFMPEG_ASS_HEADER.splitlines() if ln.startswith('Format: Name'))


def _srt_to_ass(text):
    """An .srt file as the .ass document ffmpeg's subtitles filter draws it with (its default style)."""
    lines = []
    blocks = re.split(r'\r?\n\s*\r?\n', text.strip())
    for b in blocks:
        rows = [r for r in b.splitlines() if r.strip() != '']
        k = next((i for i, r in enumerate(rows) if '-->' in r), None)
        if k is None:
            continue
        m = re.match(r'\s*([\d:,.]+)\s*-->\s*([\d:,.]+)', rows[k])
        if not m:
            continue
        a, e = (_time(x.replace(',', '.')) for x in m.groups())
        body = '\\N'.join(rows[k + 1:])
        body = re.sub(r'<\s*i\s*>', r'{\\i1}', body, flags=re.I)
        body = re.sub(r'<\s*/\s*i\s*>', r'{\\i0}', body, flags=re.I)
        body = re.sub(r'<\s*b\s*>', r'{\\b1}', body, flags=re.I)
        body = re.sub(r'<\s*/\s*b\s*>', r'{\\b0}', body, flags=re.I)
        body = re.sub(r'<[^>]+>', '', body)
        lines.append(f'Dialogue: 0,{_ass_time(a)},{_ass_time(e)},Default,,0,0,0,,{body}')
    return _FFMPEG_ASS_HEADER + '\n'.join(lines) + '\n'


def _force_style(doc, force):
    pairs = [p.split('=', 1) for p in re.split(r',(?=\s*\w+\s*=)', force or '') if '=' in p]
    if not pairs:
        return doc
    out, fmt, in_styles = [], None, False
    for line in doc.splitlines():
        s = line.strip()
        if s.startswith('['):
            in_styles = s.lower() in ('[v4+ styles]', '[v4 styles]')
        elif in_styles and s.lower().startswith('format:'):
            fmt = [f.strip().lower() for f in s[7:].split(',')]
        elif in_styles and s.lower().startswith('style:') and fmt:
            vals = [v.strip() for v in s[6:].split(',')]
            for k, v in pairs:
                k = k.strip().lower()
                if k in fmt and fmt.index(k) < len(vals):
                    vals[fmt.index(k)] = v.strip()
            line = 'Style: ' + ','.join(vals)
        out.append(line)
    return '\n'.join(out) + '\n'


def _shift_ass(doc, offset):
    """Every Dialogue line moved by -offset seconds (lines that end before 0 are left out)."""
    if not offset:
        return doc
    out = []
    for line in doc.splitlines():
        m = re.match(r'^(\s*Dialogue:\s*[^,]*,)\s*([\d:.]+)\s*,\s*([\d:.]+)(,.*)$', line)
        if m:
            a, b = _time(m.group(2)) - offset, _time(m.group(3)) - offset
            if b <= 0:
                continue
            line = f'{m.group(1)}{_ass_time(max(0, a))},{_ass_time(b)}{m.group(4)}'
        out.append(line)
    return '\n'.join(out) + '\n'


def _font_info(path):
    """(family name, cell height / em, style name) of a font file, or (None, None, '')."""
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(str(path), 1000)
        asc, desc = f.getmetrics()
        family, style = f.getname()
        return family, (asc + desc) / 1000.0, style or ''
    except Exception:  # noqa: BLE001
        return None, None, ''


# ------------------------------------------------------------------------ the translator

PIXELWISE = {'eq', 'hue', 'curves', 'lut3d', 'lut', 'lutrgb', 'lutyuv', 'colorbalance', 'colorchannelmixer', 'colorlevels',
             'colortemperature', 'vibrance', 'selectivecolor', 'exposure', 'negate', 'monochrome', 'huesaturation',
             'colorcorrect', 'colorize', 'grayworld', 'colorcontrast', 'tonemap', 'haldclut', 'pseudocolor'}
NOOP_V = {'setsar', 'setdar', 'settb', 'null', 'copy', 'fps', 'format', 'sar', 'dar', 'setfield', 'setparams',
          'colorspace_passthrough'}
NOOP_A = {'anull', 'aformat', 'aresample', 'asetnsamples', 'asettb', 'apad', 'asetrate_passthrough'}
GEOMETRY = {'scale', 'crop', 'pad', 'transpose', 'rotate', 'hflip', 'vflip', 'zoompan', 'scale2ref', 'perspective',
            'lenscorrection', 'v360', 'cropdetect'}
DURATION_CHANGING = {'loop', 'select', 'framestep', 'zoompan', 'aloop', 'aselect', 'silenceremove', 'asetrate',
                     'shuffleframes', 'mpdecimate', 'random', 'segment', 'asegment', 'tmix_drop', 'minterpolate_drop',
                     'trim_unknown'}
TIME_DEPENDENT = {'areverse'}


class _FFImport:
    def __init__(self, text, path, base_dir, output, notes, media_dir, _parent=None):
        self.notes, self.made = notes, (_parent.made if _parent else [])
        self.base_dir = Path(base_dir)
        self.dirs = [d for d in (str(self.base_dir), *(media_dir or []), str(Path.cwd())) if d]
        self.media_dir = media_dir
        if _parent is not None:
            return
        calls, self.lists, self.style = _find_calls(text, path, base_dir)
        if not calls:
            raise ValueError('no ffmpeg call found in this text')
        self.calls = []
        for c in calls:
            p = _parse_call(c['argv'])
            p.update(line=c['line'], argv=c['argv'])
            self.calls.append(p)
        self._choose(output)

    def _choose(self, hint):
        cands = [(c, o) for c in self.calls for o in c['outputs']
                 if o['path'].lower() not in _NULL_OUT and not o['path'].lower().startswith('pipe:')]
        if not cands:
            raise ValueError('no ffmpeg call here writes a file')
        pick = cands[-1]
        if hint:
            h = os.path.normcase(os.path.abspath(os.path.join(str(self.base_dir), str(hint))))
            hits = [(c, o) for c, o in cands if os.path.normcase(os.path.abspath(os.path.join(str(self.base_dir), o['path']))) == h
                    or os.path.basename(o['path']).lower() == os.path.basename(str(hint)).lower()]
            if not hits:
                raise ValueError(f'no ffmpeg call writes {hint}; the outputs are: ' +
                                 ', '.join(os.path.basename(o['path']) for _, o in cands))
            pick = hits[-1]
        self._use(*pick)
        if len(self.calls) > 1:
            self.notes.append(f'{len(self.calls)} ffmpeg calls; read the one on line {self.call["line"]} that writes '
                              f'{os.path.basename(self.out["path"])}')

    def _use(self, call, out):
        self.call, self.out = call, out
        idx = self.calls.index(call)
        self.produced = {}
        for c in self.calls[:idx]:
            for o in c['outputs']:
                if o['path'].lower() not in _NULL_OUT:
                    self.produced[os.path.normcase(os.path.abspath(os.path.join(str(self.base_dir), o['path'])))] = (c, o)
        if any('<?>' in a for a in call['argv']):
            self.notes.append('some arguments of the Python call could not be read without running it (shown as <?>)')
        self.inputs = [_Inp(i['raw'], i['opts'], i['idx'], self.base_dir, self.dirs, self.produced, self.lists, self.notes)
                       for i in call['inputs']]

    # -------------------------------------------------------------- phase 1: what the project should be
    def prepare(self):
        like = next((i.path for i in self.inputs if i.kind == 'video'), None)
        if like is None:
            for i in self.inputs:
                if i.kind == 'concat':
                    like = next((e['path'] for e in i.entries if e.get('found') and _kind_of_file(e['path']) == 'video'), None)
                    if like is None:
                        for e in i.entries:
                            if e.get('call'):
                                like = next((_find_media(x['raw'], self.dirs) for x in e['call'][0]['inputs']
                                             if _find_media(x['raw'], self.dirs) and _kind_of_file(x['raw']) == 'video'),
                                            None)
                            if like:
                                break
                elif i.kind == 'intermediate':
                    c, o = i.call
                    like = next((_find_media(x['raw'], self.dirs) for x in c['inputs']
                                 if _find_media(x['raw'], self.dirs) and _kind_of_file(x['raw']) == 'video'), None)
                if like:
                    break
        size = {}
        o = self.out['opts']
        s = _size_opt(_opt(o, '-s', '-video_size'))
        if s:
            size.update(width=s[0], height=s[1])
        r = _opt(o, '-r', '-framerate')
        if r:
            try:
                size['fps'] = float(Fraction(str(r))) if '/' in str(r) else float(r)
            except (ValueError, ZeroDivisionError):
                pass
        if 'width' not in size:
            text = ' '.join(str(v) for k, v in [*self.call['global'].items(), *o] if k in (
                '-filter_complex', '-lavfi', '-vf', '-filter:v'))
            counts = {}
            for m in re.finditer(r'\b(scale|pad)=(?:w=)?(\d{2,5})(?::|x)(?:h=)?(\d{2,5})\b', text):
                k = (int(m.group(2)), int(m.group(3)))
                counts[k] = counts.get(k, 0) + (2 if m.group(1) == 'pad' else 1)
            if counts:
                best = max(counts.items(), key=lambda kv: (kv[1], kv[0][0] * kv[0][1]))[0]
                size.update(width=best[0], height=best[1])
                self.notes.append(f'project size {best[0]}x{best[1]} read from the filters (width=/height= set another)')
        if 'fps' not in size:
            text = ' '.join(str(v) for k, v in [*self.call['global'].items(), *o] if k in ('-filter_complex', '-vf', '-lavfi'))
            m = re.findall(r'\bfps=(?:fps=)?([\d.]+(?:/[\d.]+)?)', text)
            if m:
                try:
                    size['fps'] = float(Fraction(m[-1]))
                except (ValueError, ZeroDivisionError):
                    pass
        return {'tracks': [], 'notes': self.notes, 'made': self.made, 'like': like, 'size': size}

    # -------------------------------------------------------------- phase 2: the timeline
    def translate(self, profile, project):
        self.W, self.H, self.fps = int(profile['width']), int(profile['height']), float(profile['fps'])
        self.made_dir = Path(project).parent / 'made'
        self._graph()
        v, a = self._outputs()
        return self._assemble(v, a)

    def _graph(self):
        g = self.call['global']
        text = g.get('-filter_complex') or g.get('-lavfi')
        script = g.get('-filter_complex_script') or g.get('-/filter_complex')
        if script and not text:
            p = _find_media(script, self.dirs)
            text = Path(p).read_text(encoding='utf-8-sig') if p else None
            if not p:
                raise ValueError(f'filter script {script} not found')
        self.nodes, self.unlabeled = _parse_graph(text, tag='g') if text else ([], [])
        self._bind_unlabeled_inputs(self.nodes)
        for n in self.nodes:
            _absolute_files(n, self.dirs)
        self.prod = {lab: n for n in self.nodes for lab in n.outs}
        self.memo = {}
        self._dropped = {}

    def _bind_unlabeled_inputs(self, nodes):
        named = {int(m.group(1)) for n in nodes for r in n.ins for m in [_INREF.fullmatch(r)] if m}
        for n in nodes:
            for k, r in enumerate(n.ins):
                if r != '?':
                    continue
                want_audio = _is_audio_filter(n.name)
                for inp in self.inputs:
                    if inp.idx in named:
                        continue
                    if (want_audio and inp.has_audio()) or (not want_audio and inp.has_video()):
                        n.ins[k] = f'{inp.idx}:{"a" if want_audio else "v"}'
                        named.add(inp.idx)
                        break
                else:
                    n.ins[k] = '0:a' if want_audio else '0:v'

    def _ltype(self, lab):
        m = _INREF.fullmatch(lab)
        if m and lab not in self.prod:
            return (m.group(2) or 'v').lower()
        node = self.prod.get(lab)
        if node is None:
            return 'v'
        if node.name == 'concat':
            nv = int(node.kw.get('v', 1))
            return 'v' if node.outs.index(lab) < nv else 'a'
        if node.name in ('showwaves', 'showspectrum', 'showcqt', 'avectorscope', 'showvolume', 'showfreqs',
                         'ahistogram', 'aphasemeter', 'showwavespic', 'showspectrumpic', 'color', 'testsrc',
                         'testsrc2', 'smptebars', 'nullsrc'):
            return 'v'
        if _is_audio_filter(node.name):
            return 'a'
        return self._ltype(node.ins[0]) if node.ins else 'v'

    def _outputs(self):
        o = self.out['opts']
        maps = [str(v).strip() for k, v in o if k == '-map']
        vref = aref = None
        if maps:
            for m in maps:
                if m.startswith('-'):
                    continue
                lab = re.fullmatch(r'\[(.+)\]', m)
                if lab or m in self.prod:
                    name = lab.group(1) if lab else m
                    if self._ltype(name) == 'v' and vref is None:
                        vref = name
                    elif self._ltype(name) == 'a' and aref is None:
                        aref = name
                    continue
                mm = _INREF.fullmatch(m)
                if mm and int(mm.group(1)) < len(self.inputs):
                    k, t = int(mm.group(1)), (mm.group(2) or '').lower()
                    if t in ('', 'v') and vref is None and self.inputs[k].has_video():
                        vref = f'{k}:v'
                    if t in ('', 'a') and aref is None and self.inputs[k].has_audio():
                        aref = f'{k}:a'
        else:
            for lab in self.unlabeled:
                t = self._ltype(lab)
                if t == 'v' and vref is None:
                    vref = lab
                elif t == 'a' and aref is None:
                    aref = lab
            if vref is None:
                vref = next((f'{i.idx}:v' for i in self.inputs if i.has_video()), None)
            if aref is None:
                aref = next((f'{i.idx}:a' for i in self.inputs if i.has_audio()), None)
        if _has(o, '-vn'):
            vref = None
        if _has(o, '-an'):
            aref = None
        vf = _opt(o, '-vf', '-filter:v', '-filter:v:0')
        af = _opt(o, '-af', '-filter:a', '-filter:a:0')
        if vf and vref and vref not in self.prod:
            nodes, _ = _parse_graph(vf, first_in=vref, last_out='_vf', tag='vf')
            self._add_nodes(nodes)
            vref = '_vf'
        if af and aref and aref not in self.prod:
            nodes, _ = _parse_graph(af, first_in=aref, last_out='_af', tag='af')
            self._add_nodes(nodes)
            aref = '_af'
        self.vref, self.aref = vref, aref
        v = self._val(vref) if vref else None
        a = self._val(aref) if aref else None
        return v, a

    def _add_nodes(self, nodes):
        for n in nodes:
            _absolute_files(n, self.dirs)
            for lab in n.outs:
                self.prod[lab] = n
        self.nodes += nodes

    # -------------------------------------------------------------- values of labels
    def _val(self, ref):
        m = _INREF.fullmatch(ref)
        if m and ref not in self.prod:
            return self._input_value(int(m.group(1)), (m.group(2) or 'v').lower())
        if ref not in self.memo:
            node = self.prod.get(ref)
            if node is None:
                raise ValueError(f'the filter graph reads [{ref}] but nothing makes it')
            self._eval(node)
        return copy.deepcopy(self.memo[ref])

    def _eval(self, node):
        try:
            outs = self._apply(node)
            if len(outs) != len(node.outs):
                raise _Fallback(f'{node.name} has {len(node.outs)} outputs')
        except _Fallback as why:
            outs = [self._made_value(lab, str(why)) for lab in node.outs]
        for lab, val in zip(node.outs, outs):
            self.memo[lab] = val

    def _input_value(self, k, t):
        if k >= len(self.inputs):
            raise ValueError(f'the graph reads input {k}, but there are {len(self.inputs)} inputs')
        inp = self.inputs[k]
        if inp.kind == 'intermediate':
            v, a = self._intermediate(inp)
            got = v if t == 'v' else a
            if got is None:
                raise ValueError(f'{os.path.basename(inp.path)} has no {"picture" if t == "v" else "sound"}')
            return got
        if t == 'v':
            if inp.kind == 'video':
                p = _Piece('clip', inp, a=inp.ss, b=inp.ss + inp.length())
                return _V([p] + [copy.deepcopy(p) for _ in range(self._repeats(inp))], pts0=inp.itsoffset,
                          size=inp.size)
            if inp.kind == 'image':
                return _V([_Piece('image', inp, dur=inp.length())], pts0=inp.itsoffset, size=inp.size)
            if inp.kind == 'missing':
                p = _Piece('color', color='#ff000000', dur=inp.t or 5.0)
                p.what = f'missing: {os.path.basename(str(inp.path))}'
                return _V([p])
            if inp.kind == 'concat':
                return _V(self._concat_pieces(inp, 'v'))
            if inp.kind == 'lavfi':
                return self._source(_parse_graph(inp.lavfi, tag='lv')[0][0], inp)
            raise ValueError(f'input {k} ({os.path.basename(str(inp.path))}) has no picture')
        if inp.kind in ('video', 'audio') and inp.has_audio():
            p = _Piece('clip', inp, a=inp.ss, b=inp.ss + inp.length())
            return _A([_Lane([p] + [copy.deepcopy(p) for _ in range(self._repeats(inp))], at=inp.itsoffset)])
        if inp.kind == 'concat':
            return _A([_Lane(self._concat_pieces(inp, 'a'))])
        if inp.kind == 'lavfi':
            return self._source(_parse_graph(inp.lavfi, tag='la')[0][0], inp)
        if inp.kind in ('missing', 'image', 'video'):
            return _A([])
        raise ValueError(f'input {k} ({os.path.basename(str(inp.path))}) has no sound')

    def _repeats(self, inp):
        """Extra plays of an input with -stream_loop (-1: enough to outlast every other input; later cuts trim it)."""
        if inp.stream_loop >= 0:
            return inp.stream_loop
        one = inp.length()
        others = [i.length() for i in self.inputs if i is not inp and i.kind in ('video', 'audio', 'concat')]
        horizon = max([x for x in others if x not in (None, INF)] or [one])
        n = max(0, math.ceil(horizon / one) - 1) if one and one != INF else 0
        self.notes.append(f'input {inp.idx} loops (-stream_loop -1): read as {n + 1} plays, cut where the edit ends')
        return n

    def _concat_pieces(self, inp, t):
        out = []
        for e in inp.entries:
            if e.get('call'):
                v, a = self._intermediate_call(*e['call'], ss=e['in'],
                                               t=(e['out'] - e['in']) if e.get('out') else e.get('dur'),
                                               name=os.path.basename(e['path']))
                if t == 'v' and v is not None:
                    out += v.pieces
                elif t == 'a' and a is not None and len(a.lanes) == 1 and abs(a.lanes[0].at) < 1e-3:
                    out += a.lanes[0].pieces
                elif t == 'a':
                    out.append(_Piece('silence', dur=v.dur() if v is not None else 0.0))
                continue
            if not e.get('found'):
                p = _Piece('color', color='#ff000000', dur=e.get('dur') or 5.0)
                p.what = f"missing: {os.path.basename(e['path'])}"
                out.append(p)
                continue
            info = _probe(e['path'])
            if t == 'a' and not info.get('audio'):
                out.append(_Piece('silence', dur=(e.get('out') or info.get('duration') or 0) - e['in']))
                continue
            end = e.get('out') or (e['in'] + e['dur'] if e.get('dur') else info.get('duration') or e['in'])
            src = copy.copy(inp)
            src.path, src.info = e['path'], info
            src.size = (info.get('width'), info.get('height'))
            src.kind = 'video' if info.get('video') else 'audio'
            out.append(_Piece('clip', src, a=e['in'], b=end, path=e['path']))
        return out

    def _intermediate(self, inp):
        return self._intermediate_call(*inp.call, ss=inp.ss, t=inp.t, name=os.path.basename(inp.path))

    def _intermediate_call(self, c, o, ss=0.0, t=None, name=''):
        sub = _FFImport(None, None, self.base_dir, None, self.notes, self.media_dir, _parent=self)
        sub.calls, sub.lists, sub.style = self.calls, self.lists, self.style
        sub._use(c, o)
        sub.W, sub.H, sub.fps, sub.made_dir = self.W, self.H, self.fps, self.made_dir
        sub._graph()
        v, a = sub._outputs()
        ss, end = sub._out_window()
        if v is not None and (ss or end != INF):
            v = _vwindow(v, ss, end)
        if a is not None and (ss or end != INF):
            a = _awindow(a, ss, end)
        if ss or t is not None:
            e = ss + t if t is not None else INF
            v = _vwindow(v, ss, e) if v is not None else None
            a = _awindow(a, ss, e) if a is not None else None
        self.notes.append(f'{name} is made by the ffmpeg call on line {c["line"]}; read through it')
        return v, a

    def _dummy(self):
        for i in self.inputs:
            if i.kind in ('video', 'audio', 'image') and i.path and os.path.isfile(i.path):
                d = {'clip': i.path, 'in': 0.0}
                if i.kind != 'image':
                    d['out'] = 0.1
                return d
        raise ValueError('a made clip needs at least one input file')

    def _source(self, node, inp=None):
        nm = node.name
        if nm == 'color':
            c = _rgba(node.opt(['c', 'color'], 0, 'black')) or (0, 0, 0, 1.0)
            d = node.opt(['d', 'duration'], 2)
            dur = _time(d) if d else (inp.t if inp is not None and inp.t is not None else INF)
            p = _Piece('color', color=_hex(c), dur=dur)
            return _V([p], size=_size_opt(node.opt(['s', 'size'], 1)) or (self.W, self.H))
        if nm == 'anullsrc':
            return _A([])
        d = node.opt(['d', 'duration'])
        dur = _time(d) if d else (inp.t if inp is not None and inp.t is not None else INF)
        audio = _is_audio_filter(nm)
        if audio:
            graph = (f'color=c=black:s=16x16:r={self.fps:g}:d={dur if dur != INF else 3600:.4f}[v];'
                     f'{node.raw},asetpts=PTS-STARTPTS[a]')
        else:
            graph = f'{node.raw},setpts=PTS-STARTPTS[v]'
        item = {'ffmpeg': {'inputs': [self._dummy()], 'video': graph, 'audio': bool(audio)}}
        p = _Piece('made', dur=dur, item=item)
        p.what = node.raw
        p.desc = f'{node.raw[:90]} (a source filter)'
        return _A([_Lane([p])]) if audio else _V([p])

    # -------------------------------------------------------------- fallback: a made clip
    def _subgraph(self, label, out, finish=True):
        """(made inputs, graph text) of everything upstream of `label`, ending in [out]."""
        order, seen, refs = [], set(), []

        def visit(ref):
            m = _INREF.fullmatch(ref)
            if m and ref not in self.prod:
                refs.append(ref)
                return
            node = self.prod.get(ref)
            if node is None:
                raise ValueError(f'[{ref}] is not made by any filter')
            if id(node) in seen:
                return
            seen.add(id(node))
            for r in node.ins:
                visit(r)
            order.append(node)
        visit(label)
        inputs, remap, pre = [], {}, []
        counts = {}
        for r in refs:
            counts[r] = counts.get(r, 0) + 1
        for k in sorted({int(_INREF.fullmatch(r).group(1)) for r in refs}):
            inp = self.inputs[k]
            if inp.kind in ('video', 'audio', 'image') or (inp.kind == 'intermediate' and os.path.isfile(str(inp.path))):
                remap[k] = len(inputs)
                inputs.append(inp.recipe_input())
            elif inp.kind == 'lavfi':
                remap[k] = f'mlv{k}'
                pre.append((k, inp.lavfi))
            else:
                raise _Fallback(f'input {k} ({inp.kind}) cannot go into a made clip')
        if not inputs:
            inputs.append(self._dummy())
        chains = []
        for k, src in pre:
            uses = sum(c for r, c in counts.items() if int(_INREF.fullmatch(r).group(1)) == k)
            if uses > 1:
                chains.append(f'{src},split={uses}' + ''.join(f'[mlv{k}_{j}]' for j in range(uses)))
            else:
                chains.append(f'{src}[mlv{k}_0]')
        used_lv = {}

        def ref_of(r):
            m = _INREF.fullmatch(r)
            if m and r not in self.prod:
                k = int(m.group(1))
                t = (m.group(2) or 'v').lower()
                if isinstance(remap[k], str):
                    j = used_lv.get(k, 0)
                    used_lv[k] = j + 1
                    return f'mlv{k}_{j}'
                inp = self.inputs[k]
                if inp.kind == 'image' and inp.loop and t == 'v':
                    lab = f'mloop{k}_{len(chains)}'
                    chains.append(f'[{remap[k]}:v]loop=loop=-1:size=1:start=0,setpts=N/({self.fps:g}*TB)[{lab}]')
                    return lab
                return f'{remap[k]}:{t}'
            return 'm_' + re.sub(r'[^\w]', '_', r)
        consumed = set()
        for node in order:
            ins = [ref_of(r) for r in node.ins]
            consumed |= set(node.ins)
            outs = ['m_' + re.sub(r'[^\w]', '_', o) for o in node.outs]
            chains.append(node.text(ins, outs))
        for node in order:
            for o in node.outs:
                if o != label and o not in consumed:
                    chains.append(f'[m_{re.sub(r"[^\w]", "_", o)}]{"anullsink" if self._ltype(o) == "a" else "nullsink"}')
        last = 'm_' + re.sub(r'[^\w]', '_', label)
        if finish:
            chains.append(f'[{last}]{"asetpts" if out == "a" else "setpts"}=PTS-STARTPTS[{out}]')
        else:
            chains.append(f'[{last}]null[{out}]' if self._ltype(label) == 'v' else f'[{last}]anull[{out}]')
        return inputs, ';'.join(chains)

    def _node_dur(self, node):
        ds = []
        for r in node.ins:
            try:
                ds.append(self._val(r).dur())
            except Exception:  # noqa: BLE001
                ds.append(None)
        nm = node.name
        fin = [d for d in ds if d is not None and d != INF]
        try:
            if nm == 'xfade' and len(ds) == 2 and ds[1] is not None:
                return float(node.opt(['offset'], 2, '0')) + ds[1]
            if nm == 'acrossfade' and len(ds) == 2 and None not in ds:
                return ds[0] + ds[1] - _time(node.opt(['d', 'duration'], None) or 1)
            if nm == 'concat':
                per = int(node.kw.get('v', 1)) + int(node.kw.get('a', 0))
                return sum(ds[i] for i in range(0, len(ds), per) if ds[i] is not None)
            if nm in ('amix', 'amerge', 'hstack', 'vstack', 'xstack', 'blend', 'maskedmerge', 'overlay'):
                mode = node.kw.get('duration', 'longest' if nm != 'overlay' else 'first')
                if mode == 'first' and ds and ds[0] is not None:
                    return ds[0]
                if mode == 'shortest' and fin:
                    return min(fin)
                return max(fin) if fin else None
            if nm == 'tpad' and ds and ds[0] is not None:
                return ds[0] + _time(node.kw.get('start_duration') or 0) + _time(node.kw.get('stop_duration') or 0)
            if nm in DURATION_CHANGING or nm in ('trim', 'atrim', 'setpts', 'asetpts', 'atempo', 'loop', 'aloop'):
                return None
        except (TypeError, ValueError):
            return None
        return ds[0] if ds else None

    def _made_value(self, label, why):
        node = self.prod[label]
        kind = self._ltype(label)
        inputs, graph = self._subgraph(label, 'a' if kind == 'a' else 'v')
        dur = self._node_dur(node)
        if kind == 'a':
            vlen = dur if dur not in (None, INF) else 3600
            graph = f'color=c=black:s=16x16:r={self.fps:g}:d={vlen:.4f}[v];' + graph
        item = {'ffmpeg': {'inputs': inputs, 'video': graph, 'audio': kind == 'a'}}
        if dur in (None, INF):
            dur = self._measure(item, inputs)
        item['len'] = _r(dur)
        p = _Piece('made', dur=dur, item=item)
        p.what = node.raw
        used = ', '.join(sorted({os.path.basename(i['clip']) for i in inputs}))
        p.desc = f'{node.raw[:90]} ({why}; inputs: {used})'
        return _A([_Lane([p])]) if kind == 'a' else _V([p], size=(self.W, self.H))

    def _measure(self, item, inputs):
        """Render a made clip whose length the graph decides, and keep that length (the render is reused)."""
        bound = sum(_probe(i['clip']).get('duration') or 0 for i in inputs) or 600.0
        trial = dict(item, len=_r(bound))
        rec = made.recipe_of(trial)
        rendered = made.render(rec, self.W, self.H, self.fps, out_dir=self.made_dir)
        d = _probe(rendered['path']).get('duration') or bound
        _probe_cache.pop(rendered['path'], None)
        final = dict(item, len=_r(d))
        rec2 = made.recipe_of(final)
        ext = Path(rendered['path']).suffix
        target = Path(self.made_dir) / f"{rec2['kind']}-{made._digest(rec2, self.W, self.H, self.fps)}{ext}"
        if not target.exists():
            os.replace(rendered['path'], target)
        return d

    # -------------------------------------------------------------- filters
    def _apply(self, node):
        nm = node.name
        if nm in _SOURCES and not node.ins:
            return [self._source(node)]
        ins = [self._val(r) for r in node.ins]
        h = getattr(self, '_f_' + nm, None)
        if h is not None:
            return h(node, ins)
        if len(ins) != 1 or len(node.outs) != 1:
            raise _Fallback(f'{nm} joins {len(ins)} streams')
        x = ins[0]
        if isinstance(x, _V):
            return [self._v_generic(node, x)]
        return [self._a_generic(node, x)]

    def _origin(self, v, p):
        for q, s, e in v.spans():
            if q is p:
                return v.pts0 + s
        return v.pts0

    def _v_generic(self, node, v):
        nm = node.name
        if nm in DURATION_CHANGING:
            raise _Fallback(f'{nm} changes the length')
        if nm in NOOP_V or (nm == 'scale' and v.layers and _scale_size(self._size(v), node) == self._size(v)):
            if nm in ('fps', 'format'):
                self._dropped[nm] = self._dropped.get(nm, 0) + 1
            return v
        if v.layers:
            if nm in PIXELWISE and not _time_dependent(node):
                for p in v.pieces:
                    self._piece_filter(p, node, self._origin(v, p), 'v')
                for L in v.layers:
                    if L.kind == 'clip':
                        L.item.setdefault('effects', []).insert(0, {'ffmpeg': node.raw})
                self.notes.append(f'{nm} after the overlays went on the main clips and video overlays; pictures '
                                  'and text over them are not changed by it')
                return v
            raise _Fallback(f'{nm} on the picture with its overlays')
        for p in v.pieces:
            self._piece_filter(p, node, self._origin(v, p), 'v')
        return v

    def _a_generic(self, node, a):
        nm = node.name
        if nm in DURATION_CHANGING:
            raise _Fallback(f'{nm} changes the length')
        if nm in NOOP_A:
            return a
        for lane in a.lanes:
            for p, s, e in lane.spans():
                self._piece_filter(p, node, a.pts0 + s, 'a')
        if len(a.lanes) > 1 and nm not in ('pan', 'aformat'):
            self.notes.append(f'{nm} on the mixed sound went on each sound on its own')
        return a

    def _piece_filter(self, p, node, origin, kind):
        timed = _time_dependent(node) or node.name in TIME_DEPENDENT
        if kind == 'v':
            if p.kind in ('clip', 'image', 'freeze') and not timed and not p.reverse:
                p.vchain.append(node)
            else:
                self._piece_made(p, node, origin, 'v')
        else:
            if p.kind == 'clip' and not timed:
                p.achain.append(node)
            elif p.kind == 'silence':
                pass
            else:
                self._piece_made(p, node, origin, 'a')

    def _piece_made(self, p, node, origin, kind):
        """The piece becomes a made clip that runs `node` (time expressions see the same t as in the command)."""
        shift = f'setpts=PTS+{origin:.6g}/TB,' if origin and kind == 'v' else (
            f'asetpts=PTS+{origin:.6g}/TB,' if origin else '')
        tail = 'setpts=PTS-STARTPTS' if kind == 'v' else 'asetpts=PTS-STARTPTS'
        dur = p.dur()
        if p.kind == 'made':
            f = dict(p.item['ffmpeg'])
            g = f['video']
            if kind == 'v':
                if '[' in g:
                    f['video'] = g.replace('[v]', '[mpre]') + f';[mpre]{shift}{node.raw},{tail}[v]'
                else:
                    f['video'] = (g + ',' if g else '') + f'{shift}{node.raw},{tail}'
            else:
                if '[a]' in g:
                    f['video'] = g.replace('[a]', '[mapre]') + f';[mapre]{shift}{node.raw},{tail}[a]'
                else:
                    f['audio'] = (f['audio'] + ',' if isinstance(f.get('audio'), str) else '') + f'{shift}{node.raw},{tail}'
            p.item = dict(p.item, ffmpeg=f)
            return
        vchain = ','.join(n.raw for n in p.vchain)
        achain = ','.join(n.raw for n in p.achain)
        if p.kind == 'clip' and kind == 'v':
            inp = {'clip': p.path, 'in': _r(p.a), 'out': _r(p.b)}
            if abs(p.speed - 1) > 1e-6:
                inp['speed'] = _r(p.speed, 6)
            video = ','.join(x for x in (shift.rstrip(','), vchain, node.raw, tail) if x)
            if p.reverse:
                video = 'reverse,' + video
            p.item = {'ffmpeg': {'inputs': [inp], 'video': video, 'audio': None}}
            p.vchain = []
            p.reverse = False
        elif p.kind == 'clip' and kind == 'a':
            sp = ','.join(f'atempo={x:g}' for x in made._atempo(p.speed)) if abs(p.speed - 1) > 1e-6 else ''
            chain = ','.join(x for x in (sp, shift.rstrip(','), achain, node.raw, tail) if x)
            graph = f'color=c=black:s=16x16:r={self.fps:g}:d={dur:.4f}[v];[0:a]{chain}[a]'
            p.item = {'ffmpeg': {'inputs': [{'clip': p.path, 'in': _r(p.a), 'out': _r(p.b)}], 'video': graph,
                                 'audio': True}}
            p.achain = []
            p.audio_only = True
        elif p.kind == 'image' and kind == 'v':
            video = (f'loop=loop=-1:size=1:start=0,setpts=N/({self.fps:g}*TB),{shift}' +
                     ','.join(x for x in (vchain, node.raw, tail) if x))
            p.item = {'ffmpeg': {'inputs': [{'clip': p.path, 'in': 0.0}], 'video': video, 'audio': False}}
        elif p.kind == 'freeze' and kind == 'v':
            video = (f'loop=loop=-1:size=1:start=0,setpts=N/({self.fps:g}*TB),{shift}' +
                     ','.join(x for x in (vchain, node.raw, tail) if x))
            p.item = {'ffmpeg': {'inputs': [{'clip': p.path, 'in': _r(p.freeze_at), 'out': _r(p.freeze_at + 0.1)}],
                                 'video': video, 'audio': False}}
        elif p.kind == 'color' and kind == 'v':
            r, g, b, al = _mlt_rgba(p.color)
            graph = (f'color=c=0x{r:02x}{g:02x}{b:02x}@{al:.3f}:s={self.W}x{self.H}:r={self.fps:g}:d={dur:.4f},'
                     f'{shift}{node.raw},{tail}[v]')
            p.item = {'ffmpeg': {'inputs': [self._dummy()], 'video': graph, 'audio': False}}
        else:
            raise _Fallback(f'{node.name} on a {p.kind}')
        p.kind = 'made'
        p._dur = dur
        p.what = node.raw
        name = os.path.basename(str(p.path)) if p.path else 'a stretch'
        span = f' {p.a:.2f}-{p.b:.2f} s' if p.a is not None and p.b is not None else ''
        p.desc = f'{name}{span} through {node.raw[:90]} (a filter that changes over time, rendered with its clip)'

    # each handler takes (node, input values) and returns the output values
    def _f_split(self, node, ins):
        return [ins[0]] + [copy.deepcopy(ins[0]) for _ in node.outs[1:]]

    _f_asplit = _f_split

    def _f_setpts(self, node, ins):
        x = ins[0]
        e = re.sub(r'\s+', '', node.opt(['expr'], 0, 'PTS'))
        E = e.upper()
        reset = 'PTS-STARTPTS' in E
        base = E.replace('(PTS-STARTPTS)', 'P').replace('PTS-STARTPTS', 'P').replace('PTS', 'P')
        audio = isinstance(x, _A)
        if base == 'P':
            x.pts0 = 0.0 if reset else x.pts0
            return [x]
        m = re.fullmatch(r'P\+\(?([\d.]+)\)?/TB', base)
        if m:
            x.pts0 = (0.0 if reset else x.pts0) + float(m.group(1))
            return [x]
        if re.fullmatch(r'N/\(?(FRAME_RATE|FR|SR)(\*TB)?\)?(/TB)?', base):
            x.pts0 = 0.0
            return [x]
        m = re.fullmatch(r'(?:P\*([\d.]+)|([\d.]+)\*P|P/([\d.]+))', base)
        if m and not audio:
            f = float(m.group(1) or m.group(2)) if (m.group(1) or m.group(2)) else 1 / float(m.group(3))
            if x.layers:
                raise _Fallback('a speed change of a picture with overlays')
            for p in x.pieces:
                if p.kind == 'clip':
                    p.speed /= f
                elif p.kind in ('image', 'color', 'freeze'):
                    p._dur = p._dur * f if p._dur not in (None, INF) else p._dur
                else:
                    raise _Fallback('a speed change of a made clip')
            x.pts0 = 0.0 if reset else x.pts0 * f
            return [x]
        raise _Fallback(f'setpts={e}')

    _f_asetpts = _f_setpts

    def _trim(self, node, x):
        def g(names, idx=None):
            v = node.opt(names, idx)
            return _time(v) if v not in (None, '') else None
        if any(k in node.kw for k in ('start_pts', 'end_pts', 'start_sample', 'end_sample')):
            raise _Fallback('trim in timebase units')
        start, end, dur = g(['start', 'starti'], 0), g(['end', 'endi'], 1), g(['duration', 'durationi'])
        sf, ef = node.kw.get('start_frame'), node.kw.get('end_frame')
        if sf is not None or ef is not None:
            p0 = x.pieces[0] if isinstance(x, _V) and x.pieces else None
            rate = (p0.src.info.get('fps') if p0 is not None and p0.src is not None else None) or self.fps
            start = int(sf) / rate if sf is not None else start
            end = int(ef) / rate if ef is not None else end
        rs = max(0.0, (start - x.pts0) if start is not None else 0.0)
        re_ = (end - x.pts0) if end is not None else INF
        if dur is not None:
            re_ = min(re_, rs + dur)
        return _vwindow(x, rs, re_) if isinstance(x, _V) else _awindow(x, rs, re_)

    def _f_trim(self, node, ins):
        return [self._trim(node, ins[0])]

    _f_atrim = _f_trim

    def _fade(self, node, x, audio):
        t = str(node.opt(['t', 'type'], 0, 'in')).lower()
        kind = 'in' if t.startswith('i') else 'out'
        st, d = node.opt(['st', 'start_time']), node.opt(['d', 'duration'])
        p0 = None
        if audio:
            ss, ns = node.opt(['ss', 'start_sample'], 1), node.opt(['ns', 'nb_samples'], 2)
            start = _time(st) if st is not None else (int(ss) / 44100 if ss else 0.0)
            dur = _time(d) if d is not None else (int(ns) / 44100 if ns else 44100 / 44100)
        else:
            sf, nf = node.opt(['s', 'start_frame'], 1), node.opt(['n', 'nb_frames'], 2)
            p0 = x.pieces[0] if x.pieces else None
            rate = (p0.src.info.get('fps') if p0 is not None and p0.src is not None else None) or self.fps
            start = _time(st) if st is not None else (int(sf) / rate if sf else 0.0)
            dur = _time(d) if d is not None else (int(nf) / rate if nf else 25 / rate)
            col = node.opt(['c', 'color'])
            if col and (_rgba(col) or (0, 0, 0, 1))[:3] != (0, 0, 0) and node.opt(['alpha']) not in ('1', 'true'):
                raise _Fallback('a fade to a colour')
        alpha = node.opt(['alpha']) in ('1', 'true')
        rel = start - x.pts0
        eps = 1.5 / self.fps
        lanes = x.lanes if audio else [x]
        hit = False
        for lane in lanes:
            for p, s, e in lane.spans():
                fx = p.afx if audio else p.vfx
                key = ('fade_in_audio' if kind == 'in' else 'fade_out_audio') if audio else ('fade_in' if kind == 'in' else 'fade_out')
                if kind == 'in' and abs(rel - s) <= eps and dur <= e - s + eps:
                    fx.append({key: _r(dur)} if not alpha else {key: _r(dur), 'opacity': True})
                    hit = True
                elif kind == 'out' and abs(rel + dur - e) <= eps and dur <= e - s + eps:
                    fx.append({key: _r(dur)} if not alpha else {key: _r(dur), 'opacity': True})
                    hit = True
        if not hit:
            raise _Fallback(f'a fade {kind} at {start:g} s that is not at the start or end of a clip')
        if not audio and x.layers:
            for L in x.layers:
                if kind == 'out' and abs(L.at + L.len - (rel + dur)) <= eps:
                    L.item.setdefault('effects', []).append({'fade_out': _r(dur), 'opacity': True})
                elif kind == 'in' and abs(L.at - rel) <= eps:
                    L.item.setdefault('effects', []).append({'fade_in': _r(dur), 'opacity': True})
                elif L.at < rel + dur and L.at + L.len > rel:
                    self.notes.append(f'the fade {kind} at {start:g} s is on the main clip; {L.what or "a layer"} over '
                                      'it is not faded')
        return x

    def _f_fade(self, node, ins):
        return [self._fade(node, ins[0], False)]

    def _f_afade(self, node, ins):
        return [self._fade(node, ins[0], True)]

    def _f_concat(self, node, ins):
        n, nv, na = int(node.kw.get('n', 2)), int(node.kw.get('v', 1)), int(node.kw.get('a', 0))
        per = nv + na
        if len(ins) != n * per:
            raise _Fallback(f'concat with {len(ins)} inputs for n={n}')
        segs = [ins[i * per:(i + 1) * per] for i in range(n)]
        seg_durs = [s[0].dur() if nv else max(x.dur() for x in s) for s in segs]
        outs = []
        for j in range(nv):
            pieces, layers, off = [], [], 0.0
            for i in range(n):
                v = segs[i][j]
                for L in v.layers:
                    L.at += off
                    layers.append(L)
                pieces += v.pieces
                off += seg_durs[i]
            outs.append(_V(pieces, layers, pts0=0.0, size=segs[0][j].size))
        eps = 1.5 / self.fps
        for j in range(na):
            lanes, off, cur = [], 0.0, None
            for i in range(n):
                av = segs[i][nv + j]
                if len(av.lanes) == 1 and abs(av.lanes[0].at) <= eps:
                    lane = av.lanes[0]
                    if cur is not None and abs(cur.end() - off) <= eps:
                        if abs(cur.gain - lane.gain) > 1e-6:
                            for p in lane.pieces:
                                p.afx.append({'gain': _r(lane.gain - cur.gain, 3)})
                        cur.pieces += lane.pieces
                        off += seg_durs[i]
                        continue
                    lane.at = off
                    lanes.append(lane)
                    cur = lane
                else:
                    for lane in av.lanes:
                        lane.at += off
                        lanes.append(lane)
                    cur = None
                off += seg_durs[i]
            outs.append(_A(lanes))
        return outs

    def _size(self, v):
        p = v.pieces[0] if v.pieces else None
        if p is None:
            return v.size or (self.W, self.H)
        if p.kind in ('clip', 'image') and p.src is not None and p.src.size and p.src.size[0]:
            base = p.src.size
        elif p.kind == 'freeze' and p.src is not None and p.src.size:
            base = p.src.size
        else:
            base = v.size or (self.W, self.H)
        return _chain_size(base, p.vchain)

    def _rect(self, x, y, w, h, Wb, Hb):
        f = min(self.W / Wb, self.H / Hb)
        ox, oy = (self.W - Wb * f) / 2, (self.H - Hb * f) / 2
        vals = [ox + x * f, oy + y * f, w * f, h * f]
        return ' '.join(f'{round(v, 2):g}' for v in vals)

    def _layer_effects(self, p):
        """(effects for an overlay item, needs a made layer) from the top's own filters."""
        keep, opacity = [], None
        nodes = p.vchain
        for i, n in enumerate(nodes):
            if n.name in NOOP_V:
                continue
            if n.name == 'colorchannelmixer' and set(n.kw) == {'aa'} and not n.pos:
                try:
                    opacity = float(n.kw['aa'])
                    continue
                except ValueError:
                    pass
            if n.name == 'scale' and not any(m.name in GEOMETRY for m in nodes[i + 1:]):
                continue
            keep.append(n)
        alpha_img = p.kind == 'image' and _has_alpha(p.path)
        if keep and (alpha_img or any(n.name in ('colorkey', 'chromakey', 'colorhold', 'alphamerge', 'geq') for n in keep)):
            return None, True
        effects = []
        if keep:
            if any(m.name in GEOMETRY for m in keep):
                effects.append({'ffmpeg': ','.join(n.raw for n in nodes if n.name not in NOOP_V)})
            else:
                effects.append({'ffmpeg': ','.join(n.raw for n in keep)})
        if opacity is not None:
            effects.append({'opacity': _r(opacity, 3)})
        effects += [dict(e) for e in p.vfx]
        return effects, False

    def _piece_item(self, p):
        if p.kind == 'clip':
            it = {'clip': p.path, 'in': _r(p.a), 'out': _r(p.b)}
            if abs(p.speed - 1) > 1e-6:
                it['speed'] = _r(p.speed, 6)
            if p.reverse:
                it['reverse'] = True
                it.pop('speed', None)
        elif p.kind == 'image':
            it = {'clip': p.path, 'in': 0.0, 'out': _r(p.dur())}
        elif p.kind == 'color':
            it = {'color': p.color, 'len': _r(p.dur())}
            if p.what:
                it['name'] = p.what
        elif p.kind == 'freeze':
            it = {'freeze': {'clip': p.path, 'at': _r(p.freeze_at)}, 'len': _r(p.dur())}
        elif p.kind == 'made':
            it = copy.deepcopy(p.item)
            it['len'] = _r(p.dur())
            if it['ffmpeg'].get('audio') is None:
                it['ffmpeg']['audio'] = False
        else:
            raise ValueError(f'cannot place a {p.kind}')
        return it

    def _f_overlay(self, node, ins):
        base, top = ins
        if not isinstance(base, _V) or not isinstance(top, _V):
            raise _Fallback('overlay of sound')
        xe, ye = node.opt(['x'], 0, '0'), node.opt(['y'], 1, '0')
        eof = node.opt(['eof_action'], 2, 'repeat')
        if node.kw.get('repeatlast') in ('0', 'false'):
            eof = 'pass'
        shortest = node.kw.get('shortest') in ('1', 'true')
        en = node.kw.get('enable')
        win = (0.0, INF) if en is None else _enable_window(en)
        Wb, Hb = self._size(base)
        wt, ht = self._size(top)
        names = {'W': Wb, 'H': Hb, 'main_w': Wb, 'main_h': Hb, 'w': wt, 'h': ht, 'overlay_w': wt, 'overlay_h': ht}
        try:
            x, y = _calc(xe, names), _calc(ye, names)
            fixed = win is not None
        except NameError:
            fixed = False
        rs = top.pts0 - base.pts0
        still = len(top.pieces) == 1 and top.pieces[0].kind == 'image'
        top_end = rs + top.dur()
        bd = base.dur()
        if win is None:
            S, E = max(0.0, rs), bd
        else:
            S, E = max(0.0, win[0] - base.pts0, rs), min(bd, win[1] - base.pts0)
        if eof == 'pass' and not still:
            E = min(E, top_end)
        repeat_tail = (not still) and eof == 'repeat' and top_end < E - 1e-6
        if shortest or eof == 'endall':
            base = _vwindow(base, 0, min(bd, top_end))
            E = min(E, top_end)
            self.notes.append('overlay shortest/endall: the picture ends with the overlay')
        if E <= S + 1e-6:
            self.notes.append(f'{node.raw[:60]}: the overlay never shows; left out')
            return [base]
        if not fixed or top.layers:
            return [self._made_layer(node, base, S, E, 'its position or timing changes over time' if not fixed
                                     else 'an overlay of a picture with its own overlays')]
        for p in top.pieces:
            fx, need = self._layer_effects(p)
            if need:
                return [self._made_layer(node, base, S, E, 'filters on a transparent picture')]
        rect = self._rect(x, y, wt, ht, Wb, Hb)
        full = abs(x) < 0.5 and abs(y) < 0.5 and abs(wt - Wb) < 1 and abs(ht - Hb) < 1
        last = None
        for p, s, e in top.spans():
            s, e = s + rs, e + rs
            a, b = max(s, S), min(e, E)
            if b <= a + 1e-6:
                continue
            q = p.cut(a - s, b - s) if p.dur() == INF or a > s + 1e-9 or b < e - 1e-9 else p
            if q.kind == 'image':
                q._dur = b - a
            it = self._piece_item(q)
            fx, _ = self._layer_effects(q)
            if not full:
                fx.insert(0, {'size_position': rect})
            if fx:
                it['effects'] = fx
            kind = 'image' if q.kind == 'image' else 'clip' if q.kind == 'clip' else q.kind
            base.layers.append(_Layer(it, a, b - a, kind, what=os.path.basename(str(q.path or ''))))
            last = (q, it)
        if repeat_tail and last is not None and last[0].kind == 'clip':
            q, it = last
            fz = {'freeze': {'clip': q.path, 'at': _r(max(q.a, q.b - 1.0 / (q.src.info.get('fps') or self.fps)))},
                  'len': _r(E - top_end)}
            if it.get('effects'):
                fz['effects'] = [e for e in it['effects']]
            base.layers.append(_Layer(fz, top_end, E - top_end, 'freeze', what='last frame'))
            self.notes.append(f'{os.path.basename(q.path)} ends before its overlay does; its last frame holds '
                              '(overlay repeats the last frame)')
        return [base]

    def _made_layer(self, node, base, S, E, why):
        """A transparent made clip: the overlay drawn over nothing, from S to E on the base."""
        Wb, Hb = self._size(base)
        inputs, sub = self._subgraph(node.ins[1], 'mtop', finish=False)
        args = node.args if 'format' in node.kw else (node.args + ':format=auto' if node.args else 'format=auto')
        args = re.sub(r':?\bshortest=\w+', '', args)
        canvas = f'color=c=black@0.0:s={Wb}x{Hb}:r={self.fps:g}:d={E + base.pts0:.4f},format=yuva420p[mcv]'
        graph = (f'{canvas};{sub};[mcv][mtop]{node.full}={args},trim=start={S + base.pts0:.4f},'
                 f'setpts=PTS-STARTPTS[v]')
        item = {'ffmpeg': {'inputs': inputs, 'video': graph, 'audio': False, 'alpha': True}, 'len': _r(E - S)}
        L = _Layer(item, S, E - S, 'made', what=node.raw[:60])
        L.desc = f'{node.raw[:90]} ({why}; a transparent layer)'
        base.layers.append(L)
        return base

    def _f_xfade(self, node, ins):
        A, B = ins
        trans = node.opt(['transition'], 0, 'fade')
        d = _time(node.opt(['duration'], 1, '1'))
        off = _time(node.opt(['offset'], 2, '0'))
        if A.layers or B.layers:
            raise _Fallback('xfade of pictures with overlays')
        A2 = _vwindow(A, 0, off + d)
        if not A2.pieces or not B.pieces:
            raise _Fallback('xfade of an empty picture')
        pa, pb = A2.pieces[-1], B.pieces[0]
        if pa.dur() <= d + 1e-6 or pb.dur() <= d + 1e-6:
            raise _Fallback('xfade longer than the clips it joins')
        if trans in ('fade', 'dissolve'):
            B.pieces[0].transition = _r(d)
            return [_V(A2.pieces + B.pieces, pts0=0.0, size=A.size)]
        if pa.kind != 'clip' or pb.kind != 'clip':
            raise _Fallback(f'xfade {trans} between made pictures')
        sa = A2.spans()[-1][1]
        head = pa.cut(0, off - sa)
        tail = pa.cut(off - sa, pa.dur())
        bh, rest = pb.cut(0, d), pb.cut(d, pb.dur())

        def src(p):
            i = {'clip': p.path, 'in': _r(p.a), 'out': _r(p.b)}
            if abs(p.speed - 1) > 1e-6:
                i['speed'] = _r(p.speed, 6)
            return i
        ca = ','.join(['setpts=PTS-STARTPTS'] + ([f'setpts=PTS/{tail.speed:g}'] if tail.speed != 1 else []) +
                      [n.raw for n in tail.vchain] + [f'fps={self.fps:g}', 'settb=AVTB'])
        cb = ','.join(['setpts=PTS-STARTPTS'] + ([f'setpts=PTS/{bh.speed:g}'] if bh.speed != 1 else []) +
                      [n.raw for n in bh.vchain] + [f'fps={self.fps:g}', 'settb=AVTB'])
        graph = (f'[0:v]{ca}[xa];[1:v]{cb}[xb];[xa][xb]xfade=transition={trans}:duration={d:g}:offset=0,'
                 f'setpts=PTS-STARTPTS[v]')
        ins_ = [src(tail), src(bh)]
        for i in ins_:
            i.pop('speed', None)
        mp = _Piece('made', dur=tail.dur(), item={'ffmpeg': {'inputs': ins_, 'video': graph, 'audio': False}, 'len': _r(tail.dur())})
        mp.what = node.raw
        mp.desc = (f'{node.raw[:90]} (only the {d:g} s overlap; {os.path.basename(pa.path)} and '
                   f'{os.path.basename(pb.path)} stay clips on both sides)')
        pieces = A2.pieces[:-1] + ([head] if head.dur() > 1e-6 else []) + [mp] + [rest] + B.pieces[1:]
        return [_V(pieces, pts0=0.0, size=A.size)]

    def _f_acrossfade(self, node, ins):
        A, B = ins
        d = _time(node.opt(['d', 'duration'], None) or (int(node.kw['ns']) / 44100 if 'ns' in node.kw else 1))
        if len(A.lanes) != 1 or len(B.lanes) != 1:
            raise _Fallback('acrossfade of mixed sounds')
        la, lb = A.lanes[0], B.lanes[0]
        lb.pieces[0].transition = _r(d)
        if abs(la.gain - lb.gain) > 1e-6:
            for p in lb.pieces:
                p.afx.append({'gain': _r(lb.gain - la.gain, 3)})
        return [_A([_Lane(la.pieces + lb.pieces, at=la.at, gain=la.gain)])]

    def _text_layer(self, v, doc, what):
        length = v.dur()
        if v.pts0:
            doc = _shift_ass(doc, v.pts0)
        item = {'ass': doc, 'len': _r(length)}
        v.layers.append(_Layer(item, 0.0, length, 'text', what=what))
        return v

    def _f_subtitles(self, node, ins):
        v = ins[0]
        fname = node.opt(['filename', 'f'], 0)
        path = _find_media(fname, self.dirs) if fname else None
        if not path:
            self.notes.append(f'{node.name}: file {fname} not found; left out')
            return [v]
        text = Path(path).read_text(encoding='utf-8-sig', errors='replace')
        doc = text if '[Events]' in text else _srt_to_ass(text)
        if '[Events]' in text and 'PlayResX' not in text:
            doc = text.replace('[Script Info]', '[Script Info]\nPlayResX: 384\nPlayResY: 288', 1)
        if node.kw.get('force_style'):
            doc = _force_style(doc, node.kw['force_style'])
        self.notes.append(f'{node.name} {os.path.basename(path)}: a text layer (.ass) over the whole timeline')
        return [self._text_layer(v, doc, os.path.basename(path))]

    _f_ass = _f_subtitles

    def _drawtext_ass(self, node, v):
        kw = node.kw
        text = kw.get('text')
        if text is None and kw.get('textfile'):
            p = _find_media(kw['textfile'], self.dirs)
            text = Path(p).read_text(encoding='utf-8-sig').rstrip('\n') if p else None
        if text is None or '%{' in text or kw.get('expansion') == 'strftime' or 'timecode' in kw or 'reload' in kw:
            return None
        Wb, Hb = self._size(v)
        names = {'w': Wb, 'h': Hb, 'W': Wb, 'H': Hb, 'main_w': Wb, 'main_h': Hb}
        try:
            fs = _calc(kw.get('fontsize', '16'), names)

            def lin(expr, var_names):
                n0 = dict(names, **{k: 0 for k in var_names})
                n1 = dict(names, **{k: 1000 for k in var_names})
                a0 = _calc(expr, n0)
                return a0, (_calc(expr, n1) - a0) / 1000.0
            x0, kx = lin(kw.get('x', '0'), ('tw', 'text_w', 'max_glyph_w'))
            y0, ky = lin(kw.get('y', '0'), ('th', 'text_h', 'max_glyph_h', 'lh', 'line_h', 'max_glyph_a', 'ascent',
                                            'max_glyph_d', 'descent'))
        except (NameError, ZeroDivisionError, TypeError):
            return None

        def pick(k):
            for want, code in ((0.0, 0), (-0.5, 1), (-1.0, 2)):
                if abs(k - want) < 0.02:
                    return code
            return None
        hx, vy = pick(kx), pick(ky)
        if hx is None or vy is None:
            return None
        an = {0: 7, 1: 4, 2: 1}[vy] + hx
        en = kw.get('enable')
        win = (0.0, INF) if en is None else _enable_window(en)
        if win is None:
            return None
        S, E = max(0.0, win[0] - v.pts0), min(v.dur(), win[1] - v.pts0)
        if E <= S:
            return 'never'
        f = min(self.W / Wb, self.H / Hb)
        ox, oy = (self.W - Wb * f) / 2, (self.H - Hb * f) / 2
        family, ratio, fstyle = None, None, ''
        if kw.get('fontfile'):
            family, ratio, fstyle = _font_info(_unquote(kw['fontfile']))
        family = family or (kw.get('font') or 'Arial').split(':')[0]
        if ratio is None:
            _, ratio, _ = _font_info(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'arial.ttf')
        ratio = ratio or 1.15
        bold = -1 if re.search(r'bold|black|heavy', fstyle, re.I) else 0
        italic = -1 if re.search(r'italic|oblique', fstyle, re.I) else 0
        prim = _rgba(kw.get('fontcolor', 'black')) or (0, 0, 0, 1.0)
        if kw.get('alpha'):
            try:
                prim = prim[:3] + (prim[3] * float(kw['alpha']),)
            except ValueError:
                return None
        border = float(kw.get('borderw', 0) or 0)
        outline_c = _rgba(kw.get('bordercolor', 'black')) or (0, 0, 0, 1.0)
        bs = 1
        if kw.get('box') in ('1', 'true'):
            bs = 3
            outline_c = _rgba(kw.get('boxcolor', 'white')) or (255, 255, 255, 1.0)
            try:
                border = float(str(kw.get('boxborderw', '0')).split('|')[0])
            except ValueError:
                border = 0.0
        shx, shy = float(kw.get('shadowx', 0) or 0), float(kw.get('shadowy', 0) or 0)
        back = _rgba(kw.get('shadowcolor', 'black')) or (0, 0, 0, 1.0)
        shadow = max(abs(shx), abs(shy))
        size = fs * ratio * f
        style = (f'Style: T,{family},{size:.2f},{_ass_colour(prim)},&H000000FF,{_ass_colour(outline_c)},{_ass_colour(back)},'
                 f'{bold},{italic},0,0,100,100,0,0,{bs},{border * f:.2f},{shadow * f:.2f},{an},0,0,0,1')
        body = _ass_escape(text)
        px, py = ox + x0 * f, oy + y0 * f
        doc = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {self.W}\nPlayResY: {self.H}\nWrapStyle: 2\n'
               f'ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n{_ASS_STYLE_FORMAT}\n{style}\n\n'
               f'[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
               f'Dialogue: 0,{_ass_time(0)},{_ass_time(E - S)},T,,0,0,0,,{{\\an{an}\\pos({px:.1f},{py:.1f})}}{body}\n')
        return {'ass': doc, 'len': _r(E - S)}, S, E - S

    def _f_drawtext(self, node, ins):
        v = ins[0]
        got = self._drawtext_ass(node, v)
        if got == 'never':
            self.notes.append(f'{node.raw[:60]}: never shows; left out')
            return [v]
        if got:
            item, S, L = got
            v.layers.append(_Layer(item, S, L, 'text', what=f"drawtext {node.kw.get('text', '')[:30]!r}"))
            self.notes.append(f"drawtext {node.kw.get('text', '')[:40]!r}: a text layer (.ass) at {S:.2f}-{S + L:.2f} s "
                              '(font size and placement as libass draws them' +
                              ('; no fontfile given, so ffmpeg uses its default font and the layer uses Arial)'
                               if not node.kw.get('fontfile') and not node.kw.get('font') else ')'))
            return [v]
        en = node.kw.get('enable')
        win = _enable_window(en) if en else (0.0, INF)
        S, E = (0.0, v.dur()) if win is None else (max(0.0, win[0] - v.pts0), min(v.dur(), win[1] - v.pts0))
        Wb, Hb = self._size(v)
        graph = (f'color=c=black@0.0:s={Wb}x{Hb}:r={self.fps:g}:d={E + v.pts0:.4f},format=rgba,{node.raw},'
                 f'trim=start={S + v.pts0:.4f},setpts=PTS-STARTPTS[v]')
        item = {'ffmpeg': {'inputs': [self._dummy()], 'video': graph, 'audio': False, 'alpha': True}, 'len': _r(E - S)}
        L = _Layer(item, S, E - S, 'made', what='drawtext')
        L.desc = f'{node.raw[:90]} (text that changes over time; a transparent layer)'
        v.layers.append(L)
        return [v]

    def _f_amix(self, node, ins):
        n = len(ins)
        ws = [float(w) for w in str(node.kw.get('weights', '')).split()] if node.kw.get('weights') else []
        ws = (ws + [ws[-1] if ws else 1.0] * n)[:n]
        normalize = node.name == 'amix' and str(node.kw.get('normalize', '1')).lower() not in ('0', 'false')
        total = sum(abs(w) for w in ws) or 1.0
        lanes = []
        gains = []
        for i, av in enumerate(ins):
            scale = abs(ws[i]) / total if normalize else abs(ws[i])
            g = _db(scale) if scale > 0 else -96.0
            gains.append(g)
            for lane in av.lanes:
                lane.at += av.pts0
                lane.gain += g
                lanes.append(lane)
        if normalize and n > 1:
            self.notes.append(f'amix scales each input by its weight over the sum of the weights while all play '
                              f'({", ".join(f"{g:g} dB" for g in gains)}); the sounds carry that as gain')
        if node.name == 'amerge':
            self.notes.append('amerge (channels joined into one stream) read as the sounds playing together')
        out = _A(lanes)
        mode = node.kw.get('duration', 'longest')
        if mode in ('first', 'shortest') and ins:
            end = ins[0].dur() if mode == 'first' else min(x.dur() for x in ins)
            out = _awindow(out, 0, end)
        return [out]

    _f_amerge = _f_amix

    def _f_adelay(self, node, ins):
        a = ins[0]
        d = str(node.opt(['delays'], 0, '0')).split('|')[0].strip()
        if d.lower().endswith('s') and not d.endswith('S'):
            sec = float(d[:-1])
        elif d.endswith('S'):
            sec = float(d[:-1]) / 48000.0
        else:
            sec = float(d or 0) / 1000.0
        for lane in a.lanes:
            lane.at += sec
        return [a]

    def _f_volume(self, node, ins):
        a = ins[0]
        v = str(node.opt(['volume', 'vol'], 0, '1')).strip()
        if node.kw.get('eval') == 'frame' or _time_dependent(node):
            return [self._a_generic(node, a)]
        try:
            if v.lower().endswith('db'):
                g = float(v[:-2])
            else:
                f = _calc(v, {})
                g = _db(f) if f > 0 else -96.0
        except (NameError, ValueError):
            return [self._a_generic(node, a)]
        for lane in a.lanes:
            lane.gain += g
        return [a]

    def _f_atempo(self, node, ins):
        a = ins[0]
        tempo = float(node.opt(['tempo'], 0, '1'))
        for lane in a.lanes:
            for p in lane.pieces:
                if p.kind == 'clip':
                    p.speed *= tempo
                elif p.kind == 'silence':
                    p._dur /= tempo
                else:
                    raise _Fallback('atempo on a made sound')
        return [a]

    def _f_tpad(self, node, ins):
        v = ins[0]
        if v.layers or not v.pieces:
            raise _Fallback('tpad of a picture with overlays')
        p0 = v.pieces[0]
        rate = (p0.src.info.get('fps') if p0.src is not None else None) or self.fps

        def secs(dkey, fkey):
            if node.kw.get(dkey):
                return _time(node.kw[dkey])
            if node.kw.get(fkey):
                return int(node.kw[fkey]) / rate
            return 0.0
        start, stop = secs('start_duration', 'start'), secs('stop_duration', 'stop')
        col = _hex(_rgba(node.kw.get('color', 'black')) or (0, 0, 0, 1.0))

        def pad(p, at, dur, mode):
            if mode == 'clone' and p.kind == 'clip':
                q = _Piece('freeze', p.src, dur=dur)
                q.freeze_at = at
                q.vchain = list(p.vchain)
                return q
            if mode == 'clone' and p.kind == 'image':
                q = copy.deepcopy(p)
                q._dur = dur
                return q
            return _Piece('color', color=col, dur=dur)
        if stop:
            last = v.pieces[-1]
            fr = 1.0 / ((last.src.info.get('fps') if last.src is not None else None) or self.fps)
            v.pieces.append(pad(last, max(last.a or 0, (last.b or 0) - fr), stop, node.kw.get('stop_mode', 'add')))
        if start:
            v.pieces.insert(0, pad(p0, p0.a or 0, start, node.kw.get('start_mode', 'add')))
        return [v]

    def _f_reverse(self, node, ins):
        v = ins[0]
        if len(v.pieces) == 1 and v.pieces[0].kind == 'clip' and not v.layers and v.pieces[0].dur() <= made.MAX_REVERSE_S \
                and not v.pieces[0].vchain and abs(v.pieces[0].speed - 1) < 1e-6:
            v.pieces[0].reverse = True
            return [v]
        for p in v.pieces:
            self._piece_made(p, node, 0.0, 'v')
        return [v]

    # -------------------------------------------------------------- the project's tracks
    def _out_window(self):
        o = self.out['opts']
        ss = _time(_opt(o, '-ss')) if _opt(o, '-ss') is not None else 0.0
        t, to = _opt(o, '-t'), _opt(o, '-to')
        end = ss + _time(t) if t is not None else (_time(to) if to is not None else INF)
        return ss, end

    def _matches(self, v, lane):
        eps = 1.5 / self.fps
        if abs(lane.at) > eps or len(lane.pieces) != len(v.pieces):
            return False
        for p, q in zip(v.pieces, lane.pieces):
            if p.path is None or q.path is None or os.path.normcase(str(p.path)) != os.path.normcase(str(q.path)):
                return False
            if p.a is None or q.a is None or abs(p.a - q.a) > eps * max(1, p.speed) or abs(p.b - q.b) > eps * max(1, p.speed):
                return False
            if abs(p.speed - q.speed) > 1e-3 or q.kind != 'clip' or p.kind not in ('clip', 'made'):
                return False
            if p.kind == 'made' and len(p.item['ffmpeg']['inputs']) != 1:
                return False
        return True

    def _audio_fx(self, q, gain):
        fx = []
        if q.achain:
            fx.append({'ffmpeg': {'audio': ','.join(n.raw for n in q.achain)}})
        g = gain
        rest = []
        for e in q.afx:
            if isinstance(e, dict) and set(e) == {'gain'}:
                g += e['gain']
            else:
                rest.append(e)
        if abs(g) > 1e-3:
            fx.append({'gain': _r(g, 3)} if g > -90 else 'mute')
        return fx + rest

    def _assemble(self, v, a):
        o = self.out['opts']
        ss, end = self._out_window()
        if v is not None and (ss or end != INF):
            v = _vwindow(v, ss, end)
        if a is not None and (ss or end != INF):
            a = _awindow(a, ss, end)
        vd = v.dur() if v is not None else 0.0
        ad = a.dur() if a is not None else 0.0
        if _has(o, '-shortest') and v is not None and a is not None and a.lanes:
            short = min(vd, ad)
            if short < max(vd, ad) - 1e-3:
                self.notes.append(f'-shortest: everything ends at {short:.2f} s')
            v, a = _vwindow(v, 0, short), _awindow(a, 0, short)
            vd = ad = short
        if v is not None and vd == INF:
            if a is not None and ad not in (0.0, INF):
                v = _vwindow(v, 0, ad)
                self.notes.append(f'the picture has no end of its own (a looped image); it ends with the sound at {ad:.2f} s')
            else:
                raise ValueError('the picture never ends (a looped image or a source without -t)')
        tracks = [{'name': 'V1', 'kind': 'video', 'items': [], 'main': True}]
        lanes = list(a.lanes) if a is not None else []
        main_lane = None
        if v is not None:
            main_lane = next((ln for ln in lanes if self._matches(v, ln)), None)
            if main_lane is not None:
                lanes.remove(main_lane)
            for k, p in enumerate(v.pieces):
                it = self._piece_item(p)
                fx = []
                chain = self._conform(p)
                if chain and p.kind in ('clip', 'freeze', 'image'):
                    fx.append({'ffmpeg': ','.join(n.raw for n in chain)})
                fx += [dict(e) if isinstance(e, dict) else e for e in p.vfx]
                if main_lane is not None:
                    q = main_lane.pieces[k]
                    afx = self._audio_fx(q, main_lane.gain)
                    if p.kind == 'made':
                        aud = [e for e in afx if isinstance(e, dict) and 'ffmpeg' in e]
                        it['ffmpeg']['audio'] = aud[0]['ffmpeg']['audio'] if aud else True
                        afx = [e for e in afx if not (isinstance(e, dict) and 'ffmpeg' in e)]
                    elif fx and isinstance(fx[0], dict) and isinstance(fx[0].get('ffmpeg'), str) and afx and \
                            isinstance(afx[0], dict) and 'ffmpeg' in afx[0]:
                        fx[0] = {'ffmpeg': {'video': fx[0]['ffmpeg'], 'audio': afx[0]['ffmpeg']['audio']}}
                        afx = afx[1:]
                    fx += afx
                elif p.kind in ('clip', 'freeze') and p.src is not None and p.src.has_audio() and p.kind == 'clip':
                    fx.append('mute')
                if fx:
                    it['effects'] = fx
                if k and p.transition:
                    it['transition'] = p.transition
                tracks[0]['items'].append(it)
            if a is not None and main_lane is None and any(p.kind == 'clip' and p.src is not None and p.src.has_audio()
                                                           for p in v.pieces):
                self.notes.append('the sound is not the main clips\' own sound cut the same way, so the main clips '
                                  'play muted and the sound is on audio tracks')
            # layers over the picture: each on the lowest track above every earlier layer it overlaps
            layers = v.layers
            for k, L in enumerate(layers):
                over = [M.level for M in layers[:k] if M.at < L.at + L.len - 1e-6 and L.at < M.at + M.len - 1e-6]
                L.level = (max(over) + 1) if over else 1
            levels = sorted({L.level for L in layers})
            vcount = 1
            text_count = 0
            for lv in levels:
                ls = [L for L in layers if L.level == lv]
                if all(L.kind == 'text' for L in ls):
                    text_count += 1
                    name = 'Text' if text_count == 1 else f'Text {text_count}'
                else:
                    vcount += 1
                    name = f'V{vcount}'
                items = []
                for L in ls:
                    it = dict(L.item)
                    it['at'] = _r(L.at)
                    items.append(it)
                tracks.append({'name': name, 'kind': 'video', 'items': items})
        # other sounds: packed onto audio tracks without overlaps
        atracks = []
        for lane in lanes:
            items = []
            sp = lane.spans()
            for k, (q, s, e) in enumerate(sp):
                if q.kind == 'silence':
                    continue
                if q.kind == 'made':
                    it = copy.deepcopy(q.item)
                    it['len'] = _r(q.dur())
                    it['_desc'] = getattr(q, 'desc', None) or q.what
                else:
                    it = {'clip': q.path, 'in': _r(q.a), 'out': _r(q.b)}
                    if abs(q.speed - 1) > 1e-6:
                        it['speed'] = _r(q.speed, 6)
                fx = self._audio_fx(q, lane.gain) if q.kind != 'made' else (
                    [{'gain': _r(lane.gain, 3)}] if abs(lane.gain) > 1e-3 else [])
                if q.transition and k:
                    fx.append({'fade_in_audio': _r(_tlen(q))})
                    prev = items[-1] if items else None
                    if prev is not None:
                        prev.setdefault('effects', []).append({'fade_out_audio': _r(_tlen(q))})
                if fx:
                    it['effects'] = fx
                it['at'] = _r(s)
                items.append(it)
            if not items:
                continue
            spans = [(float(it['at']), float(it['at']) + item_len(it)) for it in items]
            for t in atracks:
                if all(e <= s2 + 1e-3 or s >= e2 - 1e-3 for s, e in spans for s2, e2 in t['spans']):
                    t['items'] += items
                    t['spans'] += spans
                    break
            else:
                atracks.append({'items': items, 'spans': spans})
        for k, t in enumerate(atracks):
            tracks.append({'name': f'A{k + 1}', 'kind': 'audio', 'items': t['items']})
        if self._dropped_notes():
            self.notes.append(self._dropped_notes())
        self.made[:] = self._made_report(v, tracks)
        return {'tracks': tracks, 'notes': self.notes, 'made': self.made}

    def _made_report(self, v, tracks):
        """Where each made clip that reached the timeline sits, and what it carries."""
        out = []
        if v is not None:
            for p, s, e in v.spans():
                if p.kind == 'made':
                    out.append(f"V1 {s:.2f}-{e:.2f} s: {getattr(p, 'desc', None) or p.what}")
            for L in v.layers:
                if getattr(L, 'desc', None):
                    name = next((t['name'] for t in tracks for it in t['items'] if it is L.item or
                                 (isinstance(it, dict) and it.get('ffmpeg') is L.item.get('ffmpeg') and 'ffmpeg' in it)), '?')
                    out.append(f'{name} {L.at:.2f}-{L.at + L.len:.2f} s: {L.desc}')
        for t in tracks:
            if t['kind'] != 'audio':
                continue
            for it in t['items']:
                if it.get('_desc'):
                    out.append(f"{t['name']} {it['at']:.2f}-{it['at'] + float(it.get('len', 0)):.2f} s: {it.pop('_desc')}")
        return out

    def _dropped_notes(self):
        d = getattr(self, '_dropped', {})
        if not d:
            return ''
        return ('left out (the project does this itself): ' +
                ', '.join(f'{k} x{v}' for k, v in sorted(d.items())))

    def _conform(self, p):
        """A piece's filters without the ones that only fit it to the project (Shotcut fits clips itself)."""
        if p.src is not None and p.src.size and p.src.size[0]:
            size = p.src.size
        else:
            size = (self.W, self.H)
        out = []
        nodes = p.vchain
        pa = self.W / self.H
        for i, n in enumerate(nodes):
            nm = n.name
            if nm in NOOP_V or (nm == 'setpts' and 'STARTPTS' in n.raw.upper()):
                self._dropped[nm] = self._dropped.get(nm, 0) + 1
                continue
            if nm == 'scale':
                new = _scale_size(size, n)
                same_aspect = size[1] and abs(size[0] / size[1] - pa) < 0.01
                contain = n.kw.get('force_original_aspect_ratio') in ('decrease', '1')
                nxt = nodes[i + 1] if i + 1 < len(nodes) else None
                padded = nxt is not None and nxt.name == 'pad' and _chain_size(new, [nxt]) == (self.W, self.H)
                if (new == (self.W, self.H) and same_aspect) or (contain and padded and not out) or (
                        same_aspect and new[1] and abs(new[0] / new[1] - pa) < 0.01 and not any(
                            m.name in GEOMETRY for m in nodes[i + 1:])):
                    self._dropped['scale'] = self._dropped.get('scale', 0) + 1
                    size = new
                    continue
            if nm == 'pad':
                new = _chain_size(size, [n])
                xe, ye = n.opt(['x'], 2, '0'), n.opt(['y'], 3, '0')
                names = {'iw': size[0], 'ih': size[1], 'ow': new[0], 'oh': new[1], 'in_w': size[0], 'in_h': size[1],
                         'out_w': new[0], 'out_h': new[1], 'a': size[0] / size[1], 'sar': 1, 'dar': size[0] / size[1]}
                try:
                    cx = abs(_calc(xe, names) - (new[0] - size[0]) / 2) < 1.5
                    cy = abs(_calc(ye, names) - (new[1] - size[1]) / 2) < 1.5
                except NameError:
                    cx = cy = False
                colr = _rgba(n.opt(['color'], 4, 'black')) or (0, 0, 0, 1)
                if new == (self.W, self.H) and cx and cy and colr[:3] == (0, 0, 0) and not out:
                    self._dropped['pad'] = self._dropped.get('pad', 0) + 1
                    size = new
                    continue
            out.append(n)
            size = _chain_size(size, [n])
        return out

    # -------------------------------------------------------------- the command as written, rendered
    def reference_argv(self, out_path, cap=None):
        argv = list(self.call['argv'])
        if any('<?>' in a for a in argv):
            raise ValueError('the call has arguments that could not be read without running the script')
        k = max(i for i, a in enumerate(argv) if a == self.out['path'])
        argv[k] = str(out_path)
        for i in range(k - 1, 0, -1):
            if argv[i - 1] == '-f' and argv[i] in ('null', 'nut', 'matroska', 'rawvideo', 'image2'):
                argv[i] = 'mp4'
                break
        if cap:
            argv[k:k] = ['-t', f'{cap:.3f}']
        return [str(made.ffmpeg_exe()), '-y', '-hide_banner', '-v', 'error'] + [a for a in argv if a not in ('-y', '-n')]



# ============================================================================ an ffmpeg command from tracks

def _layout(track, main):
    """[(item, start, end)] for a track's items (order and gaps; `at` on tracks other than the main one)."""
    out, pos, prev = [], 0.0, False
    for it in track['items']:
        if 'gap' in it:
            pos += es.to_seconds(it['gap'])
            prev = False
            continue
        if main:
            if prev and it.get('transition'):
                tr = it['transition']
                pos -= es.to_seconds(tr['len'] if isinstance(tr, dict) else tr)
        elif it.get('at') is not None:
            pos = es.to_seconds(it['at'])
        L = item_len(it)
        out.append((it, pos, pos + L))
        pos += L
        prev = True
    return out


class _NeedRender(Exception):
    pass


def _ff_path(p):
    return str(p).replace('\\', '/')
