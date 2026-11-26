"""Caption layers and cues, line breaks and grouping.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import copy
import difflib
import itertools
import math
import re
import statistics
from dataclasses import dataclass, field
import letitedit.timeline.edit_script as es
from letitedit.pictures.caption_layout_frame import (  # noqa: E402
    INF
)
from letitedit.pictures.caption_layout_words import (  # noqa: E402
    ARTICLES, CONJ, PREPS, break_cost, lost_stop, norm, sentence_end
)


# ============================================================================ layers and cues

@dataclass
class Cue:
    key: str
    start: float
    end: float
    tokens: list
    times: list
    text: str = ''
    item_id: str | None = None
    params: dict | None = None
    shot: int = 0
    timing: str = 'words'         # words | estimated | unknown
    src: str | None = None        # native: the split-off caption track it is on now (None: the layer's own)
    src_style: dict | None = None


@dataclass
class Layer:
    kind: str                     # native | words
    track: str
    cues: list
    style: dict
    fit: bool = True
    notes: list = field(default_factory=list)
    siblings: list = field(default_factory=list)   # caption tracks an earlier fit split off: '<track> (top)'


def _shots(script):
    """[(start, end)] of the main picture track's items: where shots begin and end."""
    from letitedit.timeline.edit_sync import layout, main_track
    mt = main_track(script)
    return [(s, e) for _, s, e in layout(mt)] if mt else []


def _shot_at(shots, t):
    for k, (s, e) in enumerate(shots):
        if s <= t < e:
            return k
    return len(shots)


def find_layers(script, tracks=None):
    """Caption layers of a project: native caption tracks and word-caption graphic tracks. Only visible ones (burned
    in, track shown) with cues are laid out; `tracks` limits which."""
    from letitedit.timeline.edit_sync import layout
    shots = _shots(script)
    layers = []
    for cap in script.get('captions', []):
        style = dict(cap.get('style') or {})
        cues = []
        for k, q in enumerate(sorted(cap['cues'], key=lambda q: es.to_seconds(q['start']))):
            s, e = es.to_seconds(q['start']), es.to_seconds(q['end'])
            toks = q['text'].split()
            cues.append(Cue(f"{cap['track']}#{k + 1}", s, e, toks, [None] * len(toks), q['text'],
                            shot=_shot_at(shots, (s + e) / 2), timing='unknown'))
        lay = Layer('native', cap['track'], cues, style)
        if not style or cap.get('burn_in') is False:
            lay.fit = False
            lay.notes.append('not burned into the picture (no Subtitle Burn In filter): not laid out')
        elif not cues:
            lay.fit = False
            lay.notes.append('no cues')
        layers.append(lay)
    # a caption track an earlier fit split off ('Captions (top)') is part of its track's layer again
    by_name = {l.track: l for l in layers}
    for l in list(layers):
        m = re.fullmatch(r'(.+) \((top|high|middle|low|bottom)\)', l.track)
        base = by_name.get(m.group(1)) if m else None
        if base is not None and base is not l and base.style:
            for c in l.cues:
                c.src, c.src_style = l.track, dict(l.style)
            base.cues = sorted(base.cues + l.cues, key=lambda c: c.start)
            for k, c in enumerate(base.cues):
                c.key = f'{base.track}#{k + 1}'
            base.siblings.append(l.track)
            base.fit = base.fit or bool(base.cues)
            layers.remove(l)
    for t in script['tracks']:
        if t.get('kind') != 'video':
            continue
        cues = []
        for it, s, e in layout(t):
            g = it.get('graphic') or {}
            if g.get('template') != 'word_captions':
                continue
            p = dict(g.get('params') or {})
            words = p.get('words') or []
            toks = [str(w[0]) for w in words]
            times = [(round(s + float(w[1]), 3), round(s + float(w[2]), 3)) for w in words]
            cues.append(Cue(it.get('id') or f"{t['name']}@{s:.2f}", s, e, toks, times, ' '.join(toks),
                            item_id=it.get('id'), params=p, shot=_shot_at(shots, (s + e) / 2)))
        if cues:
            lay = Layer('words', t['name'], cues, dict(cues[0].params))
            if t.get('hide') in ('video', 'both'):
                lay.fit = False
                lay.notes.append('track is hidden: not laid out')
            layers.append(lay)
    if tracks:
        sib = {n: l.track for l in layers for n in l.siblings}
        want = list(dict.fromkeys(sib.get(str(x), str(x)) for x in tracks))
        names = [l.track for l in layers]
        missing = [w for w in want if w not in names]
        if missing:
            raise ValueError(f"no caption track named {', '.join(missing)}; caption tracks: {', '.join(names) or 'none'}")
        for l in layers:
            if l.track not in want:
                l.fit = False
        layers.sort(key=lambda l: want.index(l.track) if l.track in want else len(want))
    return layers


def cached_timeline_words(script):
    """Words said on the timeline, from transcripts already cached (no transcription is started here). Returns
    (words, files without a cached transcript)."""
    import letitedit.footage.speech as speech
    from letitedit.timeline.edit_sync import item_len
    from letitedit.timeline.timeline_speech import timeline_words
    sc = copy.deepcopy(script)
    missing = set()
    for t in sc['tracks']:
        items = []
        for it in t['items']:
            if 'clip' in it:
                try:
                    a, b = es.to_seconds(it.get('in', 0)), es.to_seconds(it.get('out', 0))
                    cached = speech.cached_words(it['clip'], a, b) is not None
                except Exception:  # noqa: BLE001
                    cached = False
                if not cached:
                    missing.add(it['clip'])
                    try:
                        items.append({'gap': item_len(it)})
                    except Exception:  # noqa: BLE001
                        pass
                    continue
            items.append(it)
        t['items'] = items
    try:
        return timeline_words(sc), sorted(missing)
    except Exception:  # noqa: BLE001 - captions are still laid out, without word timing
        return [], sorted(missing)


def align_native(layer, words):
    """Word times for a native layer's cue tokens: each cue's tokens matched to the words said around it (a token that
    matches nothing gets a time shared out between its neighbours: 'estimated'). Returns the tokens that are two
    transcript words without the space between them: [(cue index, token index, [word, word])]."""
    joins = []
    for ci, cue in enumerate(layer.cues):
        win = [w for w in words if w['t1'] > cue.start - 1.0 and w['t0'] < cue.end + 1.0]
        a = [norm(t) for t in cue.tokens]
        b = [norm(w['w']) for w in win]
        if not a or not b:
            continue
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        matched = 0
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                w = win[blk.b + k]
                cue.times[blk.a + k] = (float(w['t0']), float(w['t1']))
                matched += 1
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == 'replace' and i2 - i1 == 1 and j2 - j1 >= 2 and a[i1] == ''.join(b[j1:j2]):
                joins.append((ci, i1, [win[j]['w'].strip() for j in range(j1, j2)]))
        if matched >= max(1, 0.6 * len(a)):
            cue.timing = 'words'
            _fill_times(cue)
        else:
            cue.times = [None] * len(cue.tokens)
    return joins


def _fill_times(cue):
    """Times for tokens the transcript didn't match, shared out between the matched neighbours."""
    n = len(cue.times)
    if not any(cue.times):
        cue.timing = 'unknown'
        return
    i = 0
    while i < n:
        if cue.times[i]:
            i += 1
            continue
        j = i
        while j < n and not cue.times[j]:
            j += 1
        a = cue.times[i - 1][1] if i > 0 else min(cue.start, cue.times[j][0])
        b = cue.times[j][0] if j < n else max(cue.end, a)
        k = j - i
        for q in range(k):
            t0 = a + (b - a) * q / k
            cue.times[i + q] = (t0, max(t0, a + (b - a) * (q + 1) / k))
        cue.timing = 'estimated'
        i = j


def split_join(token, parts):
    """The token split where the transcript shows a missing space: ('itWithout', ['it', 'Without']) -> ['it',
    'Without'] (letters exactly as the caption has them), or None when it can't be split cleanly."""
    if len(parts) != 2:
        return None
    for k in range(1, len(token)):
        if norm(token[:k]) == norm(parts[0]) and norm(token[k:]) == norm(parts[1]):
            return [token[:k], token[k:]]
    return None


# ============================================================================ line breaks and grouping

def best_lines(widths, space, max_w, max_lines, bcosts):
    """Break a cue's tokens into at most max_lines lines no wider than max_w. widths: each token's width; bcosts[k]:
    cost of a line break before token k. A cue that fits on one line stays on one line. Returns (bounds, line widths,
    feasible, score)."""
    n = len(widths)
    if n == 0:
        return (0, 0), [0.0], True, 0.0
    best = None
    for k in range(1, min(max_lines, n) + 1):
        for cuts in itertools.combinations(range(1, n), k - 1):
            b = (0,) + cuts + (n,)
            ws = [sum(widths[b[m]:b[m + 1]]) + space * (b[m + 1] - b[m] - 1) for m in range(k)]
            over = max(0.0, max(ws) - max_w)
            score = 0.6 * (k - 1) + sum(0.6 * bcosts[c] for c in cuts)
            if k > 1:
                score += 0.8 * (max(ws) - min(ws)) / max(1.0, max_w)
                if ws[-1] < 0.35 * max(ws):
                    score += 0.8           # a lone short word on the last line
            feasible = over <= 0
            key = (not feasible, over if not feasible else 0.0, score)
            if best is None or key < best[0]:
                best = (key, b, ws, feasible, score)
        if best and best[3] and k == 1:
            break
    _, b, ws, feasible, score = best
    return b, ws, feasible, score


@dataclass
class Rules:
    max_lines: int
    max_cps: float
    min_dur: float
    max_dur: float
    target_words: int
    max_words: int
    hold: float = 0.15
    lead: float = 0.2             # a cue may come up this much before its first word (half the pause at most)
    pause_break: float = 1.2
    vocab: set = field(default_factory=set)


def _target_words(layer):
    counts = sorted(len(c.tokens) for c in layer.cues if c.tokens)
    return max(2, min(12, int(round(statistics.median(counts))))) if counts else 6


def cue_issues(tokens, times, rules, lines_needed=None, display=None):
    """Grouping problems of a cue (regroup='auto' regroups a run that has one): text that runs on past a sentence end
    or a lost full stop, a cue ending on an article or 'to'/'of', more lines than allowed, reading too fast, or one
    short word on its own."""
    out = []
    for k in range(len(tokens) - 1):
        a, b = tokens[k], tokens[k + 1]
        if sentence_end(a) or lost_stop(a, b, rules.vocab):
            out.append(f'runs on past a sentence end ("{a} {b}")')
            break
    if len(tokens) > 1 and norm(tokens[-1]) in ARTICLES | {'to', 'of'} and not sentence_end(tokens[-1]):
        out.append(f'ends on "{tokens[-1]}"')
    if lines_needed and lines_needed > rules.max_lines:
        out.append(f'needs {lines_needed} lines')
    if display is not None and display < rules.min_dur - 0.01:
        out.append(f'on screen {display:.2f} s')
    if times and times[0] and times[-1]:
        d = times[-1][1] - times[0][0] + rules.hold
        if d > 0 and len(' '.join(tokens)) / max(d, rules.min_dur) > rules.max_cps * 1.15:
            out.append('reads too fast')
        if len(tokens) == 1 and d < rules.min_dur * 0.6:
            out.append('one short word on its own')
    return out


def regroup_run(tokens, times, widths, space, max_w, rules, keep_spans, end_limit=None, cuts_at=(), hard_end=False):
    """Best cue boundaries for a run of tokens (dynamic programming over where cues start). Costs: lines needed at
    the pixel width, words per cue near the layer's own habit, reading speed, duration, sentence ends inside a cue,
    and the break where each cue ends (a cut in the picture between two words is a strong place to end a cue).
    Returns [(i, j)]."""
    n = len(tokens)
    bc = [0.0] * (n + 1)
    for k in range(1, n):
        gap = times[k][0] - times[k - 1][1] if times[k] and times[k - 1] else None
        bc[k] = break_cost(tokens[k - 1], tokens[k], gap, rules.vocab) + (6.0 if k in keep_spans else 0.0)
        if k in cuts_at:
            bc[k] -= 3.0

    def lead(k):
        """How early cue k's first word may come up: up to rules.lead, half the pause before it."""
        if k == 0:
            return rules.lead
        return max(0.0, min(rules.lead, (times[k][0] - times[k - 1][1]) / 2))

    def cue_cost(i, j):
        m = j - i
        if m > rules.max_words:
            return INF
        if any(sentence_end(tokens[q]) for q in range(i, j - 1)):
            return INF
        lb = [0.0] + [bc[i + q] for q in range(1, m)] + [0.0]
        _, _, feasible, lscore = best_lines(widths[i:j], space, max_w, rules.max_lines, lb)
        c = lscore
        if not feasible:
            if m > 1:
                return INF
            c += 50.0                         # one word wider than any line: unavoidable, reported
        c += 0.15 * (m - rules.target_words) ** 2 / max(1.0, rules.target_words)
        if m == 1:
            alone = (i == 0 or sentence_end(tokens[i - 1])) and sentence_end(tokens[i])
            if not alone and len(norm(tokens[i])) < 8:
                c += 1.0                      # one word cut off from its phrase
            if norm(tokens[i]) in ARTICLES | PREPS | CONJ or len(norm(tokens[i])) <= 3:
                c += 1.5                      # a little word on its own
        start = times[i][0] - lead(i)
        nat_end = _wanted_end(start, times[j - 1][1], len(' '.join(tokens[i:j])), rules)
        if j < n:                             # the next cue comes up then: this one can't stay longer
            disp_end = min(nat_end, times[j][0] - lead(j) - 0.04)
        else:
            disp_end = max(nat_end, start + rules.min_dur)
            if end_limit is not None and end_limit > disp_end and end_limit - disp_end < 1.5:
                disp_end = end_limit
            if hard_end and end_limit is not None:
                disp_end = min(disp_end, end_limit)     # a kept cue comes up there
        d = max(0.05, disp_end - start)
        if d < rules.min_dur:
            c += 20.0 * (rules.min_dur - d)       # too short to read: weighs more than the words-per-cue habit
        if d > rules.max_dur:
            c += 1.0 * (d - rules.max_dur)
        cps = len(' '.join(tokens[i:j])) / d
        if cps > rules.max_cps:
            c += 8.0 * (cps - rules.max_cps)
        for q in range(i, j - 1):
            if sentence_end(tokens[q]) or lost_stop(tokens[q], tokens[q + 1], rules.vocab):
                c += 1.8
        if j < n:
            c += bc[j]
        return c

    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(max(0, j - rules.max_words), j):
            if best[i] == INF:
                continue
            c = best[i] + cue_cost(i, j)
            if c < best[j]:
                best[j], back[j] = c, i
    if best[n] == INF:
        return [(i, i + 1) for i in range(n)]
    cuts, j = [], n
    while j > 0:
        cuts.append((back[j], j))
        j = back[j]
    return list(reversed(cuts))


def _runs(cues, rules, shots):
    """Neighbouring cues without a long pause or a cut between them: the stretches regrouping may move words across.
    (A cue that already runs across a cut stays in one run; the cut is then a strong place for a cue to end.)"""
    runs, cur = [], []
    for c in cues:
        if c.timing == 'unknown' or not c.times or not all(c.times):
            if cur:
                runs.append(cur)
                cur = []
            runs.append([c])
            continue
        if cur:
            prev = cur[-1]
            gap = c.times[0][0] - prev.times[-1][1]
            cut = _shot_at(shots, sum(prev.times[-1]) / 2) != _shot_at(shots, sum(c.times[0]) / 2)
            if cut or gap > rules.pause_break:
                runs.append(cur)
                cur = []
        cur.append(c)
    if cur:
        runs.append(cur)
    return runs


def _cuts_inside(times, shots):
    """Positions k where the picture cuts between word k-1 and word k."""
    return {k for k in range(1, len(times)) if times[k] and times[k - 1]
            and _shot_at(shots, sum(times[k - 1]) / 2) != _shot_at(shots, sum(times[k]) / 2)}


def _windows(flags, regroup):
    """Stretches of a run to regroup: each problem cue with its neighbours on either side (regroup='auto'), or the
    whole run ('all'). flags: one bool per cue. Returns [(first, last + 1)]."""
    n = len(flags)
    if regroup == 'all':
        return [(0, n)] if n else []
    out = []
    for k, bad in enumerate(flags):
        if bad:
            a, b = max(0, k - 1), min(n, k + 2)
            if out and a <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
    return out


def regroup_cues(cues, rules, regroup, shots, keep_spans, has_issue, widths_of, space, max_w):
    """Groups of tokens for a layer: cues kept as they are, except around problem cues (regroup='auto': the cue and
    its neighbours) or everywhere ('all'), where words are regrouped (regroup_run) and retimed (_group_times). Only
    cues with word timing are regrouped. Returns [{tokens, times, start, end, regrouped, cue (kept) | sources}]."""
    out, flat = [], 0
    for run in _runs(cues, rules, shots):
        n_tok = sum(len(c.tokens) for c in run)
        timed = all(c.timing != 'unknown' and c.times and all(c.times) for c in run)
        wins = _windows([bool(has_issue(c)) for c in run], regroup) if timed and regroup != 'none' else []
        offs = [0]
        for c in run:
            offs.append(offs[-1] + len(c.tokens))
        groups, fixed, pos = [], {}, 0

        def kept(c, groups=groups, fixed=fixed):
            fixed[len(groups)] = (c.start, c.end)
            groups.append({'tokens': list(c.tokens), 'times': list(c.times), 'regrouped': False, 'cue': c,
                           'start': c.start, 'end': c.end})
        for a, b in wins:
            for c in run[pos:a]:
                kept(c)
            sub = run[a:b]
            toks = [t for c in sub for t in c.tokens]
            times = [t for c in sub for t in c.times]
            pos = b
            if len(toks) < 2:
                for c in sub:
                    kept(c)
                continue
            base = flat + offs[a]
            spans = {k - base for k in keep_spans if base < k < base + len(toks)}
            end_limit = run[b].start if b < len(run) else run[-1].end
            cuts = regroup_run(toks, times, widths_of(toks), space, max_w, rules, spans, end_limit,
                               _cuts_inside(times, shots), hard_end=b < len(run))
            bounds = [(offs[q] - offs[a], offs[q + 1] - offs[a]) for q in range(a, b)]
            for i, j in cuts:
                same = next((c for c, bb in zip(sub, bounds) if bb == (i, j)), None)
                if same is not None:
                    kept(same)
                    continue
                groups.append({'tokens': toks[i:j], 'times': times[i:j], 'regrouped': True,
                               'sources': [c for c, (x, y) in zip(sub, bounds) if x < j and y > i]})
        for c in run[pos:]:
            kept(c)
        _group_times(groups, run, rules, fixed)
        out += groups
        flat += n_tok
    for a, b in zip(out, out[1:]):            # never run into the next cue; a kept cue keeps its times
        if a['end'] > b['start']:
            if a['regrouped']:
                a['end'] = round(max(a['start'] + 0.1, b['start']), 3)
            elif b['regrouped']:
                b['start'] = a['end']
    return out


def _wanted_end(start, last_word_end, chars, rules):
    """When a cue would like to leave the screen: `hold` after its last word, and at least min_dur and long enough to
    read at max_cps, staying up to a second into the pause after the words for that."""
    nat = last_word_end + rules.hold
    want = max(start + rules.min_dur, start + chars / max(1.0, rules.max_cps))
    return max(nat, min(nat + 1.0, want))


def _group_times(groups, run, rules, fixed=None):
    """Start and end of regrouped cues: each comes up with its first word (up to `lead` early, half the pause at
    most), stays `hold` after its last word and at least min_dur, never over the next, small gaps closed; the run
    keeps its first start (when within a second of the first word) and its last end. fixed: {index: (start, end)}
    of kept cues among them, which keep their times."""
    fixed = fixed or {}
    starts = []
    for gi, g in enumerate(groups):
        if gi in fixed:
            starts.append(fixed[gi][0])
            continue
        t0 = g['times'][0][0]
        prev = groups[gi - 1]['times'][-1][1] if gi > 0 else None
        s = t0 - (rules.lead if prev is None else max(0.0, min(rules.lead, (t0 - prev) / 2)))
        if gi == 0 and t0 - 1.0 <= run[0].start <= t0:
            s = run[0].start
        if gi - 1 in fixed:
            s = max(s, fixed[gi - 1][1])           # after a kept cue: not before it ends
        starts.append(max(0.0, s))
    for gi, g in enumerate(groups):
        if gi in fixed:
            g['start'], g['end'] = fixed[gi]
            continue
        s = starts[gi]
        nat = _wanted_end(s, g['times'][-1][1], len(' '.join(g['tokens'])), rules)
        if gi + 1 < len(groups):
            nxt = starts[gi + 1] - 0.04 if gi + 1 not in fixed else starts[gi + 1]
            e = min(nat, nxt)
            if nxt - e < 0.3:
                e = nxt
        else:
            e = nat
            if run[-1].end > e and run[-1].end - e < 1.5:
                e = run[-1].end
        e = max(e, s + 0.2)
        g['start'] = math.ceil(s * 1000 - 1e-6) / 1000         # rounded inwards: never over a neighbour
        g['end'] = math.floor(e * 1000 + 1e-6) / 1000
        if gi + 1 < len(groups) and gi + 1 in fixed:
            g['end'] = min(g['end'], math.floor(fixed[gi + 1][0] * 1000) / 1000)
