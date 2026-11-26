"""The groups of takes built, and the shapes of the result.

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import difflib
from letitedit.footage.takes_words import (  # noqa: E402
    CLAIM_KINDS, DISCOURSE, _content, _is_filler
)
from letitedit.footage.takes_sources import (  # noqa: E402
    _abs_time, _tok_text, _words_text, clock
)
from letitedit.footage.takes_match import (  # noqa: E402
    SAME_AUDIO_NCC, _align_ok, _classify, _covered, _features, _same_audio, _same_moment, _take_part, audio_match
)


# ------------------------------------------------------------------ building the groups

def _extend(nd, st):
    """A node's token range widened over the small words that open or close its clause ('if that thing | needs any
    more work'): up to 4 tokens back and 3 forward, never over so/and/then/okay, a sentence end or a long pause."""
    u, ws = nd.unit, nd.unit.doc.ws
    lo, hi = nd.lo, nd.hi
    if nd.frag or getattr(nd, 'fixed', False):    # false starts and restarted attempts keep their exact words
        return lo, hi

    def joined(a, b):        # tokens a and b (a before b) are in one stretch of talk, no punctuation between
        return (float(ws[u.tw0[b]]['s']) - float(ws[u.tw1[a]]['e']) < st['long_pause_s']
                and str(ws[u.tw1[a]]['w']).rstrip()[-1:] not in '.?!,;:')
    n = 0
    while lo > 0 and n < 4 and not _content(u.toks[lo - 1]) and u.toks[lo - 1] not in DISCOURSE and joined(lo - 1, lo):
        lo -= 1
        n += 1
    # forward only over small words that close the clause ('...get this | off.'): they end a sentence or the talk
    k = hi
    while k < len(u.toks) and k - hi < 2 and not _content(u.toks[k]) and u.toks[k] not in DISCOURSE \
            and joined(k - 1, k):
        k += 1
        closes = k == len(u.toks) or str(ws[u.tw1[k - 1]]['w']).rstrip()[-1:] in '.?!' or (
            float(ws[u.tw0[k]]['s']) - float(ws[u.tw1[k - 1]]['e']) >= st['long_pause_s'])
        if closes:
            hi = k
            break
    return lo, hi


def _take_from_node(nd, st, lo=None, hi=None):
    """The take's word range and times; the so/and/okay words opening its line (and small words closing it) are kept
    with it."""
    u = nd.unit
    lo = nd.lo if lo is None else lo
    hi = nd.hi if hi is None else hi
    if lo <= 3 and all(not _content(t) for t in u.toks[:lo]) and not getattr(nd, 'fixed', False):
        lo_ext = 0
    else:
        lo_ext = lo
    if len(u.toks) - hi <= 2 and all(not _content(t) for t in u.toks[hi:]):
        hi_ext = len(u.toks)
    else:
        hi_ext = hi
    k0 = u.w0 if lo_ext == 0 else u.tw0[lo_ext]
    k1 = u.w1 - 1 if hi_ext == len(u.toks) else u.tw1[hi_ext - 1]
    ws = u.doc.ws
    while k0 < k1 and _is_filler(ws[k0]['w']):
        k0 += 1
    while k1 > k0 and _is_filler(ws[k1]['w']):
        k1 -= 1
    return {'node': nd, 'unit': u, 'doc': u.doc, 'tlo': lo, 'thi': hi, 'k0': k0, 'k1': k1,
            'start': round(float(ws[k0]['s']), 3), 'end': round(float(ws[k1]['e']), 3), 'frag': nd.frag}


def _between_words(ta, tb, units_sorted, pos):
    """Words said between take ta and the later take tb (all lines in recording order)."""
    ua, ub = ta['unit'], tb['unit']
    if ua is ub:
        return max(0, tb['tlo'] - ta['thi'])
    ia, ib = pos.get(getattr(ua, 'last_uid', ua.uid)), pos.get(ub.uid)
    if ia is None or ib is None:
        return None
    n = len(ua.toks) - ta['thi'] + tb['tlo']
    for u in units_sorted[ia + 1:ib]:
        n += len(u.toks)
    return max(0, n)


def _group_recording_copies(takes, copies_log):
    # copies of the same recording (two files of the same moment)
    keep, copies = [], []
    for t in sorted(takes, key=lambda t: (t['doc'].fi, t['start'])):
        dup = None
        at = _abs_time(t['doc'], t['start'])
        for k in keep:
            if k['doc'] is t['doc']:
                # an edit (an export) can use the same recording twice, e.g. as a hook and again later
                if (k['doc'].exists and k['unit'] is not t['unit'] and max(k['end'] - k['start'],
                                                                          t['end'] - t['start']) <= 30
                        and difflib.SequenceMatcher(None, k['ttoks'], t['ttoks'], autojunk=False).ratio() >= 0.6):
                    ncc = audio_match(k['doc'].file, k['start'], k['end'], t['doc'].file, t['start'], t['end'])
                    if ncc is not None and ncc >= SAME_AUDIO_NCC:
                        dup = k
                        break
                continue
            ak = _abs_time(k['doc'], k['start'])
            if at is not None and ak is not None:
                if abs((at - ak).total_seconds()) <= 1.5 and abs((t['end'] - t['start']) - (k['end'] - k['start'])) <= 1.5:
                    dup = k
                    break
            sm = difflib.SequenceMatcher(None, k['ttoks'], t['ttoks'], autojunk=False)
            blocks = [b for b in sm.get_matching_blocks() if b.size]
            if (_same_audio(k['node'].unit, k['tlo'], t['node'].unit, t['tlo'], blocks)
                    or _same_moment(k['node'].unit, k['tlo'], t['node'].unit, t['tlo'], blocks)):
                dup = k
                break
            # one recording in two files whose times and rhythm differ (two edits of the same footage): the
            # waveforms themselves match
            if (sm.ratio() >= 0.6 and k['doc'].exists and t['doc'].exists and max(k['end'] - k['start'],
                                                                                 t['end'] - t['start']) <= 30):
                ncc = audio_match(k['doc'].file, k['start'], k['end'], t['doc'].file, t['start'], t['end'])
                if ncc is not None and ncc >= SAME_AUDIO_NCC:
                    dup = k
                    break
        if dup is not None:
            dup.setdefault('copies', []).append({'file': t['doc'].file, 'start': t['start'], 'end': t['end']})
            copies.append(t)
            if copies_log is not None:
                copies_log.add(tuple(sorted((dup['doc'].file, t['doc'].file))))
        else:
            keep.append(t)
    takes = keep
    return takes, copies


def _claim_value(f, kinds):
    val = []
    if 'number' in kinds:
        val.append(('number', tuple(sorted(f['nums']) or ['1'] * f['soft'])))
    if 'negation' in kinds:
        val.append(('negation', f['neg']))
    if 'name' in kinds:
        val.append(('name', tuple(sorted(f['names']))))
    if 'opposite' in kinds:
        val.append(('opposite', tuple(sorted(f['opp']))))
    return tuple(val)


def _group_claims(is_query, rnames, rtoks, takes):
    # claims: slots where a take differs in a number, negation, name or opposite word
    slots = []
    for t in takes:
        if t.get('is_ref') or t['cov_lo'] is None:
            continue
        for tag, i1, i2, j1, j2 in t['ops']:
            if tag == 'equal':
                continue
            if ((i2 <= t['cov_lo'] or i1 > t['cov_hi']) if tag != 'insert'
                    else not (t['cov_lo'] < i1 <= t['cov_hi'])):
                continue                             # outside what this take says
            A = _features(rtoks, i1, i2, rnames)
            B = _features(t['ttoks'], j1, j2, t['tnames'])
            kinds = [k for k in _classify(A, B, rtoks[i1:i2], t['ttoks'][j1:j2]) if k in CLAIM_KINDS]
            if kinds:
                slots.append([i1, i2, set(kinds)])
    merged = []
    for lo, hi, kinds in sorted(slots, key=lambda s: (s[0], s[1])):
        if merged and lo <= merged[-1][1] and (hi > merged[-1][0] or lo == hi == merged[-1][0]):
            merged[-1][1] = max(merged[-1][1], hi)
            merged[-1][2] |= kinds
        else:
            merged.append([lo, hi, set(kinds)])

    def slot_value(t, lo, hi, kinds):
        if t.get('is_ref'):
            f = _features(rtoks, lo, hi, rnames)
            toks_ = rtoks[max(0, lo - 1):hi + 1]
        else:
            if t['cov_lo'] is None:
                return None
            if lo == hi:
                if not (t['cov_lo'] < lo <= t['cov_hi'] + 1):
                    return None
            elif not (t['cov_lo'] <= lo and hi - 1 <= t['cov_hi']):
                return None
            parts = _take_part(t['ops'], lo, hi)
            idx = sorted({j for a, b in parts for j in range(a, b)})
            toks_ = [t['ttoks'][j] for j in idx]
            nm = [t['tnames'][j] for j in idx]
            f = _features(toks_, 0, len(toks_), nm)
            around = _take_part(t['ops'], max(0, lo - 1), min(len(rtoks), hi + 1))
            ctx_idx = sorted({j for a, b in around for j in range(a, b)} | set(idx))
            toks_ = [t['ttoks'][j] for j in ctx_idx] if ctx_idx else toks_
        return _claim_value(f, kinds), ' '.join(toks_)
    keys = {id(t): [slot_value(t, lo, hi, kinds) for lo, hi, kinds in merged] for t in takes}
    ref_vals = None
    if is_query:
        ref_vals = []
        for lo, hi, kinds in merged:
            f = _features(rtoks, lo, hi, rnames)
            ref_vals.append((_claim_value(f, kinds), ' '.join(rtoks[max(0, lo - 1):hi + 1])))
    variants = []                                    # [{'key': [values], 'takes': [...]}]

    def compatible(vals, key):
        return all(v is None or k is None or v[0] == k[0] for v, k in zip(vals, key))
    full = [t for t in takes if all(v is not None for v in keys[id(t)])]
    partial = [t for t in takes if t not in full]
    if is_query:
        variants.append({'key': ref_vals, 'takes': [], 'script': True})
    for t in sorted(full, key=lambda t: (not t.get('is_ref'), t['unit'].order)):
        vals = keys[id(t)]
        for v in variants:
            if all(a is not None and b is not None and a[0] == b[0] for a, b in zip(vals, v['key'])):
                v['takes'].append(t)
                break
        else:
            variants.append({'key': vals, 'takes': [t]})
    for t in partial:
        vals = keys[id(t)]
        fits = [v for v in variants if compatible(vals, v['key'])]
        if fits:
            fits[0]['takes'].append(t)
            t['compatible'] = [variants.index(v) for v in fits]
        else:
            variants.append({'key': vals, 'takes': [t]})
    variants = [v for v in variants if v['takes'] or v.get('script')]
    for vi, v in enumerate(variants):
        for t in v['takes']:
            t['variant'] = chr(65 + vi) if vi < 26 else f'V{vi}'
    return variants, merged


def _group_differences(is_query, ref_take, ref_unit, rlo, rnames, rtoks, takes):
    # differences (each take against the reference)
    diffs = []
    for t in takes:
        if t.get('is_ref'):
            continue
        for tag, i1, i2, j1, j2 in t['ops']:
            if tag == 'equal':
                continue
            if t['cov_lo'] is None:
                continue
            outside = (i2 <= t['cov_lo'] or i1 > t['cov_hi']) if tag != 'insert' else not (
                t['cov_lo'] < i1 <= t['cov_hi'])
            if outside:
                continue                             # a partial take not saying that part is not a difference
            A = _features(rtoks, i1, i2, rnames)
            B = _features(t['ttoks'], j1, j2, t['tnames'])
            kinds = _classify(A, B, rtoks[i1:i2], t['ttoks'][j1:j2])
            nd, tl = t['node'], t['tlo']
            tws = nd.unit.doc.ws
            d = {'take': t['label'], 'vs': 'script' if is_query else ref_take['label'], 'kinds': kinds,
                 'op': {'replace': 'says instead', 'delete': 'leaves out', 'insert': 'adds'}[tag],
                 'text': _tok_text(nd.unit, tl + j1, tl + j2) if j2 > j1 else '',
                 'vs_text': (' '.join(ref_unit.doc.ws[k]['w'] for k in range(ref_unit.tw0[rlo + i1],
                                                                              ref_unit.tw1[rlo + i2 - 1] + 1))
                             if i2 > i1 else ''),
                 'context': _tok_text(nd.unit, tl + max(0, j1 - 2), tl + min(len(t['ttoks']), j2 + 2))}
            if j2 > j1:
                d['at'] = round(float(tws[nd.unit.tw0[tl + j1]]['s']), 2)
            elif j1 < len(t['ttoks']):
                d['at'] = round(float(tws[nd.unit.tw0[tl + j1]]['s']), 2)     # where the left-out words would be
            elif j1 > 0:
                d['at'] = round(float(tws[nd.unit.tw1[tl + j1 - 1]]['e']), 2)
            if not is_query and i2 > i1:
                d['vs_at'] = round(float(ref_unit.doc.ws[ref_unit.tw0[rlo + i1]]['s']), 2)
            diffs.append(d)
            t.setdefault('diff_kinds', []).extend(kinds)
            t.setdefault('diff_spans', []).append((j1, j2, kinds, d['vs_text'] if tag == 'delete' else None))
    return diffs


def _group(ref, members, query, st, units_sorted, pos, copies_log=None, revalidate=False):
    """One group from a reference (a node, or the query unit) and member nodes; compares and classifies.
    revalidate: the reference was replaced (the first one was a copy), so members must still match the new one."""
    if revalidate and query is None:
        members = [m for m in members if m.frag or _align_ok(ref, m, st)]
        if not members:
            return None
    is_query = query is not None
    ref_unit = ref if is_query else ref.unit
    rlo, rhi = (0, len(ref_unit.toks)) if is_query else _extend(ref, st)
    rtoks = ref_unit.toks[rlo:rhi]
    rnames = ref_unit.tname[rlo:rhi]
    takes = []
    for nd in ([] if is_query else [ref]) + list(members):
        lo, hi = (rlo, rhi) if (not is_query and nd is ref) else _extend(nd, st)
        t = _take_from_node(nd, st, lo, hi)
        t['is_ref'] = (not is_query) and nd is ref
        ttoks = nd.unit.toks[lo:hi]
        sm = difflib.SequenceMatcher(None, rtoks, ttoks, autojunk=False)
        t['ops'] = sm.get_opcodes()
        t['ttoks'] = ttoks
        t['tnames'] = nd.unit.tname[lo:hi]
        matched = sum(i2 - i1 for tag, i1, i2, _, _ in t['ops'] if tag == 'equal')
        t['coverage'] = round(matched / max(1, len(rtoks)), 3)
        t['similarity'] = round(sm.ratio(), 3)
        t['cov_lo'], t['cov_hi'] = _covered(t['ops'], len(rtoks))
        takes.append(t)
    takes, copies = _group_recording_copies(takes, copies_log)
    # duration limits
    dropped = []
    out = []
    for t in takes:
        d = t['end'] - t['start']
        if (st['min_take_s'] is not None and d < st['min_take_s']) or (st['max_take_s'] is not None and d > st['max_take_s']):
            dropped.append(t)
        else:
            out.append(t)
    takes = out
    if not is_query and (len(takes) < 2 or not any(t['is_ref'] for t in takes)):
        if len(takes) >= 2:
            best = max(takes, key=lambda t: (t['coverage'], t['similarity']))
            for t in takes:
                t['is_ref'] = t is best
            return _group(best['node'], [t['node'] for t in takes if t is not best], None, st, units_sorted, pos,
                          copies_log, revalidate=True)
        return None
    takes.sort(key=lambda t: (t['unit'].order, t['start']))
    variants, merged = _group_claims(is_query, rnames, rtoks, takes)
    # labels in recording order
    for i, t in enumerate(takes, 1):
        t['label'] = f'T{i}'
    ref_take = next((t for t in takes if t.get('is_ref')), None)
    # completeness
    for i, t in enumerate(takes):
        if t['coverage'] >= 0.8:
            t['completeness'] = 'complete'
        else:
            later = takes[i + 1] if i + 1 < len(takes) else None
            gap_ok = later is not None and (_rec_gap_takes(t, later) is not None and
                                            _rec_gap_takes(t, later) <= st['restart_gap_s'])
            t['completeness'] = 'false_start' if (t['frag'] or (gap_ok and later['coverage'] > t['coverage']
                                                                 and t['cov_lo'] is not None and t['cov_lo'] <= 2)) \
                else 'partial'
    diffs = _group_differences(is_query, ref_take, ref_unit, rlo, rnames, rtoks, takes)
    # gaps and the pattern
    gaps = []
    for a, b in zip(takes, takes[1:]):
        gaps.append({'from': a['label'], 'to': b['label'], 'seconds': _round(_rec_gap_takes(a, b)),
                     'words_between': _between_words(a, b, units_sorted, pos), 'same_file': a['doc'] is b['doc']})
    retake_like = []
    for g in gaps:
        w_ok = g['words_between'] is not None and g['words_between'] <= st['retake_gap_words']
        s_ok = g['seconds'] is None or g['seconds'] <= st['retake_gap_s']
        retake_like.append(w_ok and s_ok)
    pattern = 'single' if not gaps else ('retakes' if all(retake_like) else 'recurring' if not any(retake_like)
                                          else 'mixed')
    if gaps and all(getattr(t['node'], 'inline', False) for t in takes):
        pattern = 'restart'                         # started over inside one line, no pause
    return {'ref': ref_take, 'query': query, 'ref_unit': ref_unit, 'rlo': rlo, 'rhi': rhi, 'rtoks': rtoks,
            'takes': takes, 'variants': variants, 'slots': merged, 'diffs': diffs, 'gaps': gaps,
            'pattern': pattern, 'copies': copies, 'dropped': dropped}


def _round(x, nd=2):
    return None if x is None else round(float(x), nd)


def _notable(g):
    """A recurring group worth listing: its takes differ in a claim, or it repeats a whole line (one take covers 80%+
    of its line) with 3+ content words. Stock phrases ('take a look at that') are not."""
    if any(k in CLAIM_KINDS for d in g['diffs'] for k in d['kinds']):
        return True
    if sum(1 for t in g['rtoks'] if _content(t)) < 3:
        return False
    return any(t['thi'] - t['tlo'] >= 0.8 * len(t['unit'].toks) for t in g['takes'])


def _rec_gap_takes(a, b):
    if a['doc'] is b['doc']:
        return b['start'] - a['end']
    ta, tb = _abs_time(a['doc'], a['end']), _abs_time(b['doc'], b['start'])
    if ta is None or tb is None:
        return None
    return (tb - ta).total_seconds()


# ------------------------------------------------------------------ result shapes

def _variant_out(g, v, vi):
    out = {'variant': chr(65 + vi) if vi < 26 else f'V{vi}', 'takes': [t['label'] for t in v['takes']]}
    if v.get('script'):
        out['script'] = True
    says = []
    for (lo, hi, kinds), val in zip(g['slots'], v['key']):
        if val is None:
            continue
        says.append({'kinds': sorted(kinds), 'says': val[1],
                     'script' if g['query'] is not None else 'reference': ' '.join(g['rtoks'][max(0, lo - 1):hi + 1])})
    out['says'] = says
    return out


def _take_out(t, g, measures):
    doc = t['doc']
    out = {'take': t['id'], 'label': t['label'], 'file': doc.file, 'name': doc.name,
           'start': t['start'], 'end': t['end'], 'clock': f"{clock(t['start'])}-{clock(t['end'])}",
           'text': _words_text(doc.ws, t['k0'], t['k1']),
           'line': [round(t['unit'].start, 3), round(t['unit'].end, 3)],
           'recorded_at': None if doc.rec is None else _abs_time(doc, t['start']).isoformat(timespec='seconds'),
           'reference': bool(t.get('is_ref')), 'variant': t.get('variant'),
           'completeness': t['completeness'], 'coverage': t['coverage'], 'similarity': t['similarity'],
           'differences': _kind_counts(t.get('diff_kinds') or [])}
    if g['query'] is not None:
        out['matches_script'] = t.get('variant') == 'A' and not [k for k in (t.get('diff_kinds') or [])
                                                                  if k in CLAIM_KINDS]
    if t.get('compatible') and len(t['compatible']) > 1:
        out['compatible_variants'] = [chr(65 + i) for i in t['compatible']]
    if t.get('copies'):
        out['copies'] = t['copies']
    if t['unit'].speaker:
        out['speaker'] = t['unit'].speaker
    out['components'] = t.get('components') or {}
    if t.get('edit_item'):
        out['edit_item'] = t['edit_item']
    out['context'] = t.get('context')
    for k in ('frames', 'clip'):
        if t.get(k):
            out[k] = t[k]
    return out


def _kind_counts(kinds):
    out = {}
    for k in kinds:
        out[k] = out.get(k, 0) + 1
    return out


def brief_take(t):
    """One line per take for reading: label, file, times, completeness and the main measurements."""
    head = [f"{t['label']}{'*' if t.get('reference') else ''} {t['name']} {t['clock']}", t['completeness'],
            f"variant {t['variant']}" if t.get('variant') else '', f"cov {t['coverage']:.2f}",
            f"sim {t['similarity']:.2f}"]
    return ' | '.join(b for b in head + _measure_bits(t) if b)


def _measure_bits(t):
    c = t.get('components') or {}
    bits = []
    d = c.get('delivery') or {}
    if d:
        p = d.get('pauses') or {}
        bits.append(f"{d.get('words')} words {d.get('duration_s')} s, pauses {p.get('count', 0)}"
                    + (f" (longest {p.get('longest_s')} s)" if p.get('count') else '')
                    + f", restarts {d.get('restart_count', 0)}, fillers {(d.get('fillers') or {}).get('count', 0)}")
    e = c.get('edges') or {}
    if e:
        cut = []
        if e.get('first_word_cut_by_recording_start'):
            cut.append('FIRST WORD CUT')
        if e.get('last_word_cut_by_recording_end'):
            cut.append('LAST WORD CUT')
        tail = e.get('tail_out_s')
        bits.append(f"room before {e.get('lead_in_s')} s / after {'?' if tail is None else tail} s"
                    + (' ' + ' '.join(cut) if cut else ''))
    a = c.get('audio') or {}
    if a.get('available'):
        bits.append(f"peak {a['peak_dbfs']} dBFS, {a['clipped_samples']} clipped samples"
                    + (f" ({a['clip_runs']} flat runs)" if a.get('clip_runs') else '')
                    + (f", speech-noise {a['snr_db']} dB" if a.get('snr_db') is not None else ''))
    n = c.get('noise') or {}
    if n.get('available'):
        parts = [f"{n['impact_count']} impact(s)"] if n.get('impact_count') else []
        parts += [f"{s['desc']} {int(round(s['share_of_take'] * 100))}%" for s in (n.get('sustained') or [])[:2]]
        if parts:
            bits.append('noise: ' + ', '.join(parts))
    p = c.get('picture') or {}
    if p.get('available'):
        faults = [f"{k} {int(p[k] * 100)}%" for k in ('dark', 'blown_out', 'blurry', 'shaky') if p.get(k)]
        bits.append('picture: ' + (', '.join(faults) if faults else 'no faults found') +
                    (f", {len(p['cuts_inside'])} cut(s)" if p.get('cuts_inside') else ''))
    tr = c.get('transcript') or {}
    if tr.get('available') and tr.get('unsure_count'):
        bits.append(f"{tr['unsure_count']} unsure word(s)")
    dk = t.get('differences') or {}
    if dk:
        bits.append('differs: ' + ', '.join(f'{k} {v}' for k, v in sorted(dk.items())))
    return [b for b in bits if b]
