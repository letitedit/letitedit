"""Matching passages said again, the script or phrase mode, and a take compared with the reference.

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import difflib
import subprocess
import threading
import numpy as np
from letitedit.footage.takes_words import (  # noqa: E402
    FFMPEG, NO_WINDOW, OPPOSITE, STOP, _content, _is_neg, _num_value, name_mask
)
from letitedit.footage.takes_sources import (  # noqa: E402
    _Doc, _Unit, _abs_time, _skip_discourse
)


# ------------------------------------------------------------------ matching

def _regions(ta, tb, gap=4):
    """Shared regions of two token lists: [{'a': (lo, hi), 'b': (lo, hi), 'm', 'mc', 'ratio', 'blocks'}]. difflib
    matching blocks (single words only when they are content words) joined when at most `gap` tokens apart."""
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size and (b.size >= 2 or _content(ta[b.a]))]
    groups, cur = [], []
    for b in blocks:
        if cur and (b.a - (cur[-1].a + cur[-1].size) > gap or b.b - (cur[-1].b + cur[-1].size) > gap):
            groups.append(cur)
            cur = []
        cur.append(b)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        a_lo, a_hi = g[0].a, g[-1].a + g[-1].size
        b_lo, b_hi = g[0].b, g[-1].b + g[-1].size
        m = sum(x.size for x in g)
        mc = sum(1 for x in g for k in range(x.size) if _content(ta[x.a + k]))
        out.append({'a': (a_lo, a_hi), 'b': (b_lo, b_hi), 'm': m, 'mc': mc,
                    'ratio': 2.0 * m / max(1, (a_hi - a_lo) + (b_hi - b_lo)), 'blocks': g})
    return out


def _pairs(units):
    """Candidate pairs of lines that share at least two informative word pairs (one when a line is short)."""
    index = {}
    for u in units:
        seen = set()
        for x, y in zip(u.toks, u.toks[1:]):
            if (x in STOP and y in STOP) or (x, y) in seen:
                continue
            seen.add((x, y))
            index.setdefault((x, y), []).append(u.uid)
    cap = max(6, int(0.25 * len(units)))
    shared = {}
    for big, ids in index.items():
        if len(ids) < 2 or len(ids) > cap:
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                shared[(a, b)] = shared.get((a, b), 0) + 1
    by = {u.uid: u for u in units}
    out = []
    for (a, b), n in shared.items():
        ua, ub = by[a], by[b]
        if n >= 2 or min(len(ua.toks), len(ub.toks)) <= 6:
            out.append((ua, ub))
    return out


def _accept(r, la, lb, st):
    """A shared region is one passage: enough matched words (2+ content words), similar enough, covering half the
    shorter line (or 10+ words), and more than a stock phrase: min_words + 2 words, or 3 content words, or most
    (60%+) of both lines."""
    short = min(la, lb)
    strong = (r['m'] >= st['min_words'] + 2 or r['mc'] >= 3
              or min(r['m'] / max(1, la), r['m'] / max(1, lb)) >= 0.6)
    return (r['m'] >= st['min_words'] and r['mc'] >= 2 and r['ratio'] >= st['min_similarity']
            and (r['m'] >= 0.5 * short or r['m'] >= 10) and strong)


class _Node:
    """A take candidate: tokens [lo, hi) of a line."""

    def __init__(self, unit, lo, hi, frag=False):
        self.unit, self.lo, self.hi, self.frag = unit, lo, hi, frag

    @property
    def toks(self):
        return self.unit.toks[self.lo:self.hi]

    def key(self):
        return (self.unit.uid, self.lo, self.hi)


def _merge_spans(spans, join=2):
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + join:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [tuple(x) for x in out]


def _align_ok(na, nb, st):
    rs = [r for r in _regions(na.toks, nb.toks) if r['m'] >= max(3, st['min_words'] - 1)]
    return any(r['ratio'] >= 0.8 * st['min_similarity'] and r['mc'] >= 1 for r in rs)


def _same_speaker(ua, ub):
    return not (ua.speaker and ub.speaker and ua.speaker != ub.speaker)


def _same_moment(ua, a_lo, ub, b_lo, blocks):
    """True when matched words of two files were recorded at the same moment (copies or trims of one recording, or
    two cameras): by the files' recording clocks the matched words are, in the median, within 3 s of each other."""
    if ua.doc is ub.doc or ua.doc.rec is None or ub.doc.rec is None:
        return False
    diffs = []
    for blk in blocks:
        for k in range(blk.size):
            ta = _abs_time(ua.doc, ua.doc.ws[ua.tw0[a_lo + blk.a + k]]['s'])
            tb = _abs_time(ub.doc, ub.doc.ws[ub.tw0[b_lo + blk.b + k]]['s'])
            diffs.append(abs((ta - tb).total_seconds()))
    return bool(diffs) and float(np.median(diffs)) <= 3.0


def _same_audio(ua, a_lo, ub, b_lo, blocks):
    """True when matched words keep the same rhythm: 6+ words with 80% of them at one constant time offset (within
    0.05 s), or 3+ words all within 0.02 s of it. That is one recording transcribed twice (a copy, a trim, a second
    camera), never a retake: nobody says a line again with every word at the same spacing."""
    offs = []
    for blk in blocks:
        for k in range(blk.size):
            ta = float(ua.doc.ws[ua.tw0[a_lo + blk.a + k]]['s'])
            tb = float(ub.doc.ws[ub.tw0[b_lo + blk.b + k]]['s'])
            offs.append(tb - ta)
    if len(offs) < 3:
        return False
    med = float(np.median(offs))
    if all(abs(o - med) <= 0.02 for o in offs):
        return True
    return len(offs) >= 6 and sum(1 for o in offs if abs(o - med) <= 0.05) >= 0.8 * len(offs)


_PCM = {}
_PCM_LOCK = threading.Lock()
SAME_AUDIO_NCC = 0.5        # waveform match above this: one recording (copies 0.78-1.0, retakes 0.03-0.22 measured)


def _pcm(path, a, b, sr=16000):
    key = (str(path), round(a, 2), round(b, 2))
    with _PCM_LOCK:
        if key in _PCM:
            return _PCM[key]
    try:
        r = subprocess.run([str(FFMPEG), '-v', 'error', '-nostdin', '-ss', f'{max(0.0, a):.3f}', '-t',
                            f'{max(0.05, b - max(0.0, a)):.3f}', '-i', str(path), '-vn', '-ac', '1', '-ar', str(sr),
                            '-f', 'f32le', '-'], capture_output=True, creationflags=NO_WINDOW, timeout=120)
        x = np.frombuffer(r.stdout[:len(r.stdout) // 4 * 4], np.float32).astype(np.float64)
    except (OSError, subprocess.SubprocessError):
        x = np.zeros(0)
    with _PCM_LOCK:
        if len(_PCM) > 64:
            _PCM.clear()
        _PCM[key] = x
    return x


def audio_match(path_a, a0, a1, path_b, b0, b1, margin=0.6):
    """Peak normalised cross-correlation (0-1) of two stretches' waveforms, the shorter slid along the other (with
    `margin` s on each side). One recording, even re-encoded or in another edit, scores near 1; the same words
    said again score near 0. None when either has no sound."""
    if (a1 - a0) > (b1 - b0):
        path_a, a0, a1, path_b, b0, b1 = path_b, b0, b1, path_a, a0, a1
    x = _pcm(path_a, a0, a1)
    y = _pcm(path_b, b0 - margin, b1 + margin)
    if len(x) < 1600 or len(y) < len(x):
        return None
    x = x - x.mean()
    ex = float((x ** 2).sum())
    if ex <= 1e-9:
        return None
    n = 1 << int(np.ceil(np.log2(len(x) + len(y))))
    num = np.fft.irfft(np.fft.rfft(y, n) * np.conj(np.fft.rfft(x, n)), n)[:len(y) - len(x) + 1]
    L = len(x)
    y2 = np.concatenate([[0.0], np.cumsum(y ** 2)])
    ys = np.concatenate([[0.0], np.cumsum(y)])
    var_y = np.maximum((y2[L:] - y2[:-L]) - (ys[L:] - ys[:-L]) ** 2 / L, 1e-9)
    return round(float(np.max(num / np.sqrt(var_y * ex))), 3)


def _discover(units, st, prog, copies=None):
    """Groups of nodes: [[reference node, member nodes...]] (fragments flagged). Pairs from the same moment of two
    files are copies, not takes: they are left out and noted in `copies` (a set of file pairs)."""
    found = []                                     # (unit a, span a, unit b, span b, ratio, m)
    pairs = _pairs(units)
    for n, (ua, ub) in enumerate(pairs):
        if n % 200 == 0:
            prog.check()
        if not _same_speaker(ua, ub):
            continue
        for r in _regions(ua.toks, ub.toks):
            if _accept(r, len(ua.toks), len(ub.toks), st):
                if ua.doc is not ub.doc and (_same_moment(ua, 0, ub, 0, r['blocks'])
                                             or _same_audio(ua, 0, ub, 0, r['blocks'])):
                    if copies is not None:
                        copies.add(tuple(sorted((ua.doc.file, ub.doc.file))))
                    continue
                found.append((ua, r['a'], ub, r['b'], r['ratio'], r['m']))
    spans = {}
    for ua, sa, ub, sb, _, _ in found:
        spans.setdefault(ua.uid, []).append(sa)
        spans.setdefault(ub.uid, []).append(sb)
    by = {u.uid: u for u in units}
    nodes = {}
    for uid, ss in spans.items():
        nodes[uid] = [_Node(by[uid], lo, hi) for lo, hi in _merge_spans(ss)]

    def node_of(u, span):
        for nd in nodes[u.uid]:
            if nd.lo <= span[0] and span[1] <= nd.hi:
                return nd
        return nodes[u.uid][0]
    adj = {}
    for ua, sa, ub, sb, ratio, m in found:
        a, b = node_of(ua, sa), node_of(ub, sb)
        if a is b:
            continue
        for x, y in ((a, b), (b, a)):
            w0, m0 = adj.setdefault(x, {}).get(y, (0.0, 0))
            adj[x][y] = (max(w0, ratio), max(m0, m))
    # connected components, then stars around the best-connected node
    seen, comps = set(), []
    for nd in adj:
        if nd in seen:
            continue
        comp, stack = [], [nd]
        seen.add(nd)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in adj.get(x, {}):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        comps.append(comp)
    clusters = []
    for comp in comps:
        remaining = set(comp)
        while len(remaining) >= 2:
            prog.check()
            center = max(remaining, key=lambda x: (sum(w * m for y, (w, m) in adj.get(x, {}).items()
                                                       if y in remaining), x.hi - x.lo, -x.unit.order))
            members = [center]
            for x in sorted(remaining - {center}, key=lambda x: x.unit.order):
                if x in adj.get(center, {}) or (_same_speaker(center.unit, x.unit) and _align_ok(center, x, st)):
                    members.append(x)
            if len(members) < 2:
                remaining.discard(center)
                continue
            clusters.append(members)
            remaining -= set(members)
    # false starts: a short line, then (next) a line opening the same way
    in_cluster = {nd.unit.uid: (ci, nd) for ci, c in enumerate(clusters) for nd in c}
    ordered = sorted(units, key=lambda u: u.order)
    for i, u in enumerate(ordered):
        frag = _fragment_of(u, ordered, i, st)
        if frag is None or u.uid in in_cluster:
            continue
        v, n_shared = frag
        hit = None
        for ci, c in enumerate(clusters):
            for nd in c:
                if nd.unit is v and nd.lo < _head_len(v, st):
                    hit = ci
        node = _Node(u, 0, len(u.toks), frag=True)
        if hit is not None:
            clusters[hit].append(node)
        else:
            head = _Node(v, 0, _head_len(v, st))
            clusters.append([head, node])
            in_cluster[v.uid] = (len(clusters) - 1, head)
        in_cluster[u.uid] = (hit, node)
    # attempts started over inside a line: the dropped attempts are false starts of the last one
    for u in ordered:
        for chain, final in _inline_restarts(u):
            last = _Node(u, final, final + _head_len(u, st, final))
            last.fixed = True
            last.inline = True
            busy = [(ci, nd) for ci, c in enumerate(clusters) for nd in c if nd.unit is u]
            hit = next((ci for ci, nd in busy if nd.lo < last.hi and last.lo < nd.hi), None)
            frags = [_Node(u, i, k, frag=True) for i, k in chain]
            for f in frags:
                f.inline = True
            frags = [f for f in frags if not any(nd.lo < f.hi and f.lo < nd.hi for _, nd in busy)]
            if not frags:
                continue
            if hit is not None:
                clusters[hit].extend(frags)
            elif not any(nd.lo < last.hi and last.lo < nd.hi for _, nd in busy):
                clusters.append([last] + frags)
    return clusters


def _head_len(v, st, start=0):
    """Tokens from `start` to the first sentence end or long pause after 4+ tokens (at most 16): the opening of a
    line, or of a new attempt inside it."""
    ws = v.doc.ws
    for k in range(start, len(v.toks)):
        n = k + 1 - start
        if n >= 16:
            return n
        if n >= 4:
            w = ws[v.tw1[k]]
            nxt = v.tw0[k + 1] if k + 1 < len(v.toks) else None
            if str(w['w']).rstrip()[-1:] in '.?!' or (nxt is not None and float(ws[nxt]['s']) - float(w['e'])
                                                      >= st['long_pause_s']):
                return n
    return len(v.toks) - start


CONJ = {'and', 'or', 'but', 'so', 'then', 'also', 'plus', 'because', 'nor'}
COPULA = {'is', 'was', 'are', 'were'}


def _inline_restarts(u):
    """Attempts started over inside one line, without a pause: [([(i, k), ...], final start)]. Tokens [i, k) are an
    attempt dropped and started again at k ('I don't | I don't even think | I don't think I need to...'): the new
    attempt opens with the same 2+ words (one of them a content word) or 3+ words, the dropped one is at most 6 words
    and is 60%+ like the new opening. Not a restart: parallel phrases joined by and/or/but ('this vent and this
    vent'), 'what I'll do is, I'll...' (the first part ends in is/was), single-word stutters ('now now') and 'so the
    so the' (those stay in delivery.restarts)."""
    T = u.toks
    chains, cur, used, k = [], [], 0, 1
    while k < len(T):
        found = None
        for L in range(min(6, k - used), 1, -1):
            i = k - L
            n = 0
            while k + n < len(T) and i + n < k and T[i + n] == T[k + n]:
                n += 1
            if not ((n >= 2 and any(_content(t) for t in T[k:k + n])) or n >= 3):
                continue
            if T[i] in CONJ or T[k - 1] in CONJ or T[k - 1] in COPULA or any(t in ('and', 'or', 'but', 'nor')
                                                                              for t in T[i:k]):
                continue
            a, b = T[i:k], T[k:k + L + 1]
            if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.6:
                continue
            post = [t for t in T[i + n:k] if _content(t)]          # what the first try said after the shared start
            if post and sum(1 for t in post if t in T[k:k + L + 3]) < 0.5 * len(post):
                continue                    # a list ('I got my tools, I got my new motor'), not a restart
            found = (i, k)
            break
        if found:
            cur.append(found)
            used = k
        elif cur and k - used > 8:
            chains.append((cur, used))
            cur = []
        k += 1
    if cur:
        chains.append((cur, used))
    return chains


def _fragment_of(u, ordered, i, st):
    """(the line u is a false start of, tokens shared) or None: u is short (2-12 tokens) and a line starting within
    restart_gap_s after it (only short lines in between) opens with u's words (after so/and/okay...)."""
    T = u.toks
    a0 = _skip_discourse(T)
    core = T[a0:]
    if not (2 <= len(core) <= 12) or not any(_content(t) for t in core):
        return None
    between = 0
    for v in ordered[i + 1:i + 4]:
        if not _same_speaker(u, v):
            return None
        gap = _rec_gap(u, v)
        if gap is not None and gap > st['restart_gap_s']:
            return None
        b0 = _skip_discourse(v.toks)
        n = 0
        while n < len(core) and b0 + n < len(v.toks) and v.toks[b0 + n] == core[n]:
            n += 1
        if n >= 2 and n >= 0.75 * len(core) and len(v.toks) - b0 >= n + 2:
            same_file = v.doc is u.doc
            pause = v.start - u.end if same_file else None
            stop = str(u.doc.ws[u.w1 - 1]['w']).rstrip()[-1:] in '.?!'
            if not same_file or (pause is not None and pause >= 0.5) or not stop:
                return v, n
        between += len(v.toks)
        if between > 6:
            return None
    return None


def _rec_gap(u, v):
    """Recording seconds from the end of line u to the start of line v (None when not known)."""
    if u.doc is v.doc:
        return v.start - u.end
    if u.doc.rec is not None and v.doc.rec is not None:
        return (v.doc.rec - u.doc.rec).total_seconds() + v.start - u.end
    return None


# ------------------------------------------------------------------ script / phrase mode

def _query_doc(text, names, lower_seen):
    ws = [{'w': w, 's': float(k), 'e': float(k) + 0.9} for k, w in enumerate(str(text).split())]
    d = _Doc(-1, '(script)', ws, False)
    d.names = name_mask(ws, names, lower_seen)
    return d


def _query_hits(q, toks, need, st, base=0, depth=0):
    """Every place tokens q are said in toks: [(coverage of q, similarity, lo, hi)]. The best match, then the same
    search on each side of it (a line can say a phrase more than once)."""
    if len(toks) < need or depth > 40:
        return []
    rs = [r for r in _regions(q, toks) if r['m'] >= need and r['m'] / len(q) >= 0.5
          and r['ratio'] >= 0.8 * st['min_similarity']]
    if not rs:
        return []
    r = max(rs, key=lambda r: (r['m'], r['ratio']))
    lo, hi = r['b']
    return ([(r['m'] / len(q), r['ratio'], base + lo, base + hi)]
            + _query_hits(q, toks[:lo], need, st, base, depth + 1)
            + _query_hits(q, toks[hi:], need, st, base + hi, depth + 1))


def _query_groups(queries, docs, st, names, lower_seen, prog):
    """For each script line / phrase: [query unit, nodes of every place it is said]."""
    out = []
    paras = []
    for d in docs:                                  # lines this close together are searched as one
        cur = None
        for u in d.units:
            if cur is not None and u.start - cur[-1].end <= st['query_join_s'] and _same_speaker(cur[-1], u):
                cur.append(u)
            else:
                cur = [u]
                paras.append(cur)
    joined = []
    for p in paras:
        if len(p) == 1:
            joined.append(p[0])
        else:
            j = _Unit(p[0].doc, p[0].w0, p[-1].w1)
            j.order = p[0].order
            j.uid = p[0].uid
            j.last_uid = p[-1].uid
            j.speaker = p[0].speaker
            joined.append(j)
    for qi, q in enumerate(queries):
        prog.check()
        qd = _query_doc(q, names, lower_seen)
        qu = _Unit(qd, 0, len(qd.ws))
        if not qu.toks:
            out.append({'query': q, 'qunit': qu, 'nodes': []})
            continue
        need = max(1, min(len(qu.toks), 2))
        cands = []
        for u in joined:
            for cover, ratio, lo, hi in _query_hits(qu.toks, u.toks, need, st):
                cands.append((cover, ratio, u, (lo, hi)))
        cands.sort(key=lambda c: (-c[0], -c[1]))
        nodes = []
        for cover, ratio, u, (lo, hi) in cands:
            if any(n.unit.doc is u.doc and not (u.tw1[hi - 1] < n.unit.tw0[n.lo] or u.tw0[lo] > n.unit.tw1[n.hi - 1])
                   for n in nodes):
                continue
            nodes.append(_Node(u, lo, hi))
        nodes.sort(key=lambda n: (n.unit.order, n.lo))
        out.append({'query': q, 'qunit': qu, 'nodes': nodes})
    return out


# ------------------------------------------------------------------ comparing a take with the reference

def _features(toks, lo, hi, tname):
    nums, soft, neg, nms, opp = [], 0, 0, set(), set()
    for k in range(lo, hi):
        t = toks[k]
        v = _num_value(t, toks[k - 1] if k > 0 else '')
        if v is not None:
            nums.append(v)
        elif t == 'one':
            soft += 1
        if _is_neg(t):
            neg += 1
        if tname[k]:
            nms.add(t)
        if t in OPPOSITE:
            opp.add(t)
    return {'nums': nums, 'soft': soft, 'neg': neg, 'names': nms, 'opp': opp}


def _classify(A, B, a_toks, b_toks):
    """Kinds of one difference between aligned token runs (features A of the reference side, B of the take)."""
    kinds = []
    na, nb = sorted(A['nums']), sorted(B['nums'])
    if na or nb:
        if not na and A['soft']:
            na = ['1'] * A['soft']
        if not nb and B['soft']:
            nb = ['1'] * B['soft']
    if na != nb:
        kinds.append('number')
    elif na and a_toks != b_toks:
        kinds.append('number_format')
    if A['neg'] != B['neg']:
        kinds.append('negation')
    if A['names'] != B['names']:
        kinds.append('name')
    if any(OPPOSITE[x] & B['opp'] for x in A['opp']):
        kinds.append('opposite')
    if not kinds or kinds == ['number_format']:
        changed = [t for t in a_toks + b_toks if _content(t)]
        if changed and not (set(a_toks) == set(b_toks)):
            kinds.append('wording')
        elif not kinds:
            kinds.append('function')
    return kinds


def _take_part(opcodes, lo, hi):
    """Take token ranges aligned to reference tokens [lo, hi) (hi == lo: what the take has inserted at lo)."""
    parts = []
    for tag, i1, i2, j1, j2 in opcodes:
        if lo == hi:
            if tag == 'insert' and i1 == lo:
                parts.append((j1, j2))
            elif tag in ('replace', 'delete') and i1 < lo < i2:
                parts.append((j1, j2))
            continue
        if tag == 'insert':
            if lo < i1 < hi:
                parts.append((j1, j2))
            continue
        if i2 <= lo or i1 >= hi:
            continue
        if tag == 'equal':
            a, b = max(i1, lo), min(i2, hi)
            parts.append((j1 + a - i1, j1 + b - i1))
        else:
            parts.append((j1, j2))
    return parts


def _covered(opcodes, ref_len):
    """First and last reference index the take matches ((None, None) when nothing matches)."""
    eq = [(i1, i2) for tag, i1, i2, _, _ in opcodes if tag == 'equal']
    if not eq:
        return None, None
    return eq[0][0], eq[-1][1] - 1
