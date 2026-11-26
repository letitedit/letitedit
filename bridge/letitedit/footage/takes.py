"""Take finder: repeated takes of the same passage in a creator's own footage, grouped, compared and measured.

    find(files | archive | words, script | phrase, ...)  -> result dict (the contract is in takes_tools.py)
    job(ctx)                                             -> find() as a background job: jobs.submit('takes:job', ...)

Data in, data out. The software finds and organises candidate takes; the AI or the person chooses the performance.
It never picks a winner, never edits a timeline and never deletes or moves anything.

How (deterministic unless marked otherwise):
  words     cached transcripts (speech.py). transcribe=True fills missing ones, one file at a time (GPU worker).
  lines     a file's words split at pauses >= split_pause_s, at speaker changes, and where a line starts over
            (a short opening said again within the line).
  tokens    cutpoints._tok (Unicode letters, digits and marks of any script), fillers (um, uh...) left out, number
            words read as numbers ('fifteen' = '15'), a few spoken forms joined ('gonna' = 'going to'); scripts
            written without spaces (Chinese, Japanese, Thai...) compared character by character.
  matching  a word-pair index picks candidate line pairs; difflib aligns them; a shared region counts when it has at
            least min_words matched words (2 of them content words) and its similarity is at least min_similarity,
            and it covers at least half of the shorter line (or 10+ words).
  groups    star clusters around the take that shares the most words with the others; every member is aligned to
            that reference take (or to the script line). A short line followed at once by a line that starts the
            same way (the next recording, or after a pause) is that line's false start.
  claims    within a group, differences in numbers, negation, names (capitalised words, identifiers like R22, names
            you pass) and opposite words (left/right, tighten/loosen...) split the takes into claim variants: such
            takes are never reported as the same claim.
  measures  separate components, never one score: text (coverage, similarity, differences), delivery (pauses,
            restarts, fillers, rate), edges (room before/after, words cut by the recording's start/end, audio-snapped
            cut points), audio (peak, clipped samples, speech and noise level), noise (perception.sounds events),
            picture (perception.picture: dark, blown out, blurry, shaky, cuts), transcript (the transcriber's word
            probabilities: a model score, not calibrated), speaker (a cached letitedit_speakers assignment).
  previews  a comparison sheet per group (frames at the same words of every take, a loudness strip with the words,
            the text with its differences coloured) and, on request, a short clip per take with context before and
            after plus a reel of the group's takes back to back.

Results, previews and clips go to C:\\LetItEdit\\cache\\takes\\<result_id>\\ (or out_dir). A result is reused when
the same inputs, settings and source fingerprints (file size/time, transcript variant and hash, which analyses are
cached) come again; anything that changes them gives a new result_id.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)


# ---- this module's parts: every name in them imported back, so each is the same object as before
# the settings, the word lists (fillers, negations, numbers) and names
from letitedit.footage.takes_words import (  # noqa: E402,F401
    _SAI_ROOT, CACHE, OUT, APP, FFMPEG, NO_WINDOW, SCHEMA_VERSION, ALGO_VERSION, TOOL, DEFAULTS, MEASURES,
    PREVIEWS, CLAIM_KINDS, FILLERS, STOP, DISCOURSE, NEGATIONS, _OPPOSITE_PAIRS, OPPOSITE, _p, _a, _b, CANON, ONES,
    TEENS, TENS, BIG, NUMWORDS, ORDINALS, ORD_WORD, ORD_BEFORE, FRACTIONS, PRONOUN_I, DOUBLES, _PUNCT_EDGE, _NUM,
    _ISNUM, _CLOCK, ORD_SUFFIX, _nospace, _fmt_num, _norm_word, _is_filler, _number_run, _number_pass, tokenize,
    _content, _num_value, _is_neg, _lower_seen, name_mask
)
# the sources: transcripts and media loaded, with the text and time helpers
from letitedit.footage.takes_sources import (  # noqa: E402,F401
    _Doc, _Unit, _runs, _skip_discourse, _leading_restart, _units, clock, _words_text, _tok_text, _short_id,
    _Progress, _transcript, _archive_files, _given_words, _media_info, _speaker_words, _cached_flags, _load,
    _abs_time
)
# matching passages said again, the script or phrase mode, and a take compared with the reference
from letitedit.footage.takes_match import (  # noqa: E402,F401
    _regions, _pairs, _accept, _Node, _merge_spans, _align_ok, _same_speaker, _same_moment, _same_audio, _PCM,
    _PCM_LOCK, SAME_AUDIO_NCC, _pcm, audio_match, _discover, _head_len, CONJ, COPULA, _inline_restarts,
    _fragment_of, _rec_gap, _query_doc, _query_hits, _query_groups, _features, _classify, _take_part, _covered
)
# the measurements of each take (sound, picture, speech)
from letitedit.footage.takes_measure import (  # noqa: E402,F401
    _overlap, _CHANNELS, _sound_format, _decode, CLIP_LEVEL, CLIP_RUN, HOP_S, _audio_measures, _edges, _restarts,
    _delivery, _transcript_conf, _noise, _picture, _voice, _FileCache
)
# the groups of takes built, and the shapes of the result
from letitedit.footage.takes_groups import (  # noqa: E402,F401
    _extend, _take_from_node, _between_words, _group, _round, _notable, _rec_gap_takes, _variant_out, _take_out,
    _kind_counts, brief_take, _measure_bits
)
# the previews: comparison sheets, clips and reels
from letitedit.footage.takes_previews import (  # noqa: E402,F401
    _FONT_CACHE, _font, COLORS, _PRIORITY, _grab, _anchor_times, _word_styles, _draw_words, _env_strip, _sheet,
    _label_png, _card_png, _ENC, _clip, _reel
)


import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import letitedit.timeline.cutpoints as cutpoints  # noqa: E402
import letitedit.footage.speech as speech  # noqa: E402


# ------------------------------------------------------------------ weights (an ordering only when asked)

def _component_value(c, path):
    cur = c
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if isinstance(cur, bool):
        return 1.0 if cur else 0.0
    if isinstance(cur, (int, float)):
        return float(cur)
    if isinstance(cur, list):
        return float(len(cur))
    return None


def _weighted(takes, weights):
    """{'order': [take ids], 'values': {...}} by the caller's weights: each component min-max scaled within the group
    (0-1), times its weight, summed. An ordering by your weights, not a verdict."""
    comps = {t['take']: dict(t['components'], text={'coverage': t['coverage'], 'similarity': t['similarity'],
                                                    **(t['components'].get('text') or {})}) for t in takes}
    scaled = {t['take']: {} for t in takes}
    missing = {}
    for path, w in weights.items():
        try:
            w = float(w)
        except (TypeError, ValueError):
            raise ValueError(f'weights: {path!r} needs a number') from None
        vals = {tid: _component_value(c, path) for tid, c in comps.items()}
        have = [v for v in vals.values() if v is not None]
        if not have:
            missing[path] = 'no take has this component (check the path, e.g. audio.snr_db)'
            continue
        lo, hi = min(have), max(have)
        for tid, v in vals.items():
            if v is None:
                missing.setdefault(path, []).append(tid)
                continue
            s = 0.5 if hi - lo < 1e-12 else (v - lo) / (hi - lo)
            scaled[tid][path] = round(w * s, 4)
    total = {tid: round(sum(v.values()), 4) for tid, v in scaled.items()}
    order = sorted(total, key=lambda k: -total[k])
    return {'order': order, 'totals': total, 'parts': scaled, 'missing': missing,
            'how': 'each component min-max scaled to 0-1 within the group, times your weight, summed; '
                   'an ordering by your weights, not a quality verdict'}


# ------------------------------------------------------------------ the main entry

def _settings(params, settings):
    st, defaulted = {}, []
    given = dict(settings or {})
    bad = sorted(set(given) - set(DEFAULTS))
    if bad:
        raise ValueError(f"unknown settings {', '.join(bad)}; settings takes {', '.join(sorted(DEFAULTS))}")
    for k, v in DEFAULTS.items():
        if params.get(k) is not None:
            st[k] = params[k]
        elif k in given and given[k] is not None:
            st[k] = given[k]
        else:
            st[k] = v
            defaulted.append(k)
    for k in ('min_words', 'max_groups', 'preview_groups', 'frames', 'clip_height', 'retake_gap_words'):
        st[k] = int(st[k])
    for k in ('min_similarity', 'split_pause_s', 'long_pause_s', 'retake_gap_s', 'restart_gap_s', 'query_join_s',
              'context_s'):
        st[k] = float(st[k])
    if not 0 < st['min_similarity'] <= 1:
        raise ValueError('min_similarity is a share between 0 and 1 (default 0.6)')
    if st['min_words'] < 2:
        raise ValueError('min_words must be at least 2')
    return st, defaulted


UNSUPPORTED = [
    {'case': 'overlapping speech', 'detail': 'two people talking at once are one word stream in the transcript; such '
                                             'takes are not separated and their measurements mix both voices'},
    {'case': 'languages other than English', 'detail': 'the local transcriber runs in English; number words, '
     'negation, opposite words, fillers and small-word lists are English. Unicode letters and digits of any script are '
     'compared; scripts written without spaces are compared character by character; names are found by capital '
     'letters only (none in scripts without case)'},
    {'case': 'paraphrases', 'detail': 'takes that say the same thing in different words are grouped only when enough '
                                      'words match (min_words, min_similarity)'},
    {'case': 'intentional repeats', 'detail': 'a joke, catchphrase or callback repeated on purpose cannot be told from '
     'a retake by text alone: such groups have pattern "recurring" (far apart, other talk between)'},
    {'case': 'disfluencies the transcriber dropped', 'detail': 'false starts and repeats the transcriber left out are '
     'not seen; delivery.voice_without_words_s shows talking that has no words'},
    {'case': 'meaning changes beyond the word lists', 'detail': 'claims are compared by numbers, negation, names and a '
     'fixed list of opposite words; other wording changes are listed as "wording" for you to read'},
    {'case': 'audio clipping', 'detail': 'measured on the decoded (usually AAC) sound: samples at or above 0.99 of full '
                                         'scale in runs of 3+; clipping hidden by the encoder is not seen'},
    {'case': 'picture faults', 'detail': 'from the cached footage analysis (dark, blown out, blurry, shaky, cuts) '
     'only; without it the picture is "unknown", not a pass; focus on the speaker and framing are not judged'},
]


def _find_take_groups(docs, st, names, queries, recurring, restarts, prog, warnings):
    lower_seen = _lower_seen(docs)
    for d in docs:
        d.names = name_mask(d.ws, names, lower_seen)
    all_rec = bool(docs) and all(d.rec is not None for d in docs)
    order = sorted(docs, key=lambda d: (d.rec.timestamp(), d.fi) if all_rec else (d.fi, 0))
    units = []
    for d in order:
        d.units = _units(d, st)
        units += d.units
    for i, u in enumerate(units):
        u.order = i
        u.uid = i
    pos = {u.uid: i for i, u in enumerate(units)}
    prog(0.25, f'comparing {len(units)} lines')
    raw_groups = []
    copies_seen = set()
    if queries:
        for qg in _query_groups(queries, order, st, names, lower_seen, prog):
            g = _group(qg['qunit'], qg['nodes'], qg['query'], st, units, pos, copies_seen) if qg['nodes'] else None
            raw_groups.append((qg['query'], g))
    else:
        for c in _discover(units, st, prog, copies_seen):
            g = _group(c[0], c[1:], None, st, units, pos, copies_seen)
            if g is not None:
                raw_groups.append((None, g))
    if copies_seen:
        short = lambda f: f'{Path(f).parent.name}/{Path(f).name}'
        pairs_ = sorted(p for p in copies_seen if p[0] != p[1])
        self_ = sorted({p[0] for p in copies_seen if p[0] == p[1]})
        if pairs_:
            warnings.append(f'{len(pairs_)} file pair(s) hold the same recording (a copy, a trim, another edit of the '
                            'same footage or a second camera: their recording clocks, word rhythm or waveforms agree); '
                            'what they share is not a second take and was left out: '
                            + '; '.join(f'{short(a)} = {short(b)}' for a, b in pairs_))
        if self_:
            warnings.append('these files use the same recording twice (an edit repeating a moment, e.g. as a hook; '
                            'the waveforms match), so those repeats are not takes: ' + '; '.join(map(short, self_)))
        # the same restart or false start found again in the copy of a file: keep the original's group only
        fi = {d.file: d.fi for d in docs}
        copy_of = {}
        for a, b in copies_seen:
            first, second = (a, b) if fi.get(a, 0) <= fi.get(b, 0) else (b, a)
            copy_of.setdefault(second, set()).add(first)
        sig = lambda g: (g['pattern'], tuple(sorted(_words_text(t['doc'].ws, t['k0'], t['k1']).lower()
                                                     for t in g['takes'])))
        seen_sig = {}
        for q, g in raw_groups:
            files_ = {t['doc'].file for t in g['takes']} if g is not None else set()
            if len(files_) == 1:
                seen_sig.setdefault(sig(g), set()).update(files_)
        keep, dup_n = [], 0
        for q, g in raw_groups:
            files_ = {t['doc'].file for t in g['takes']} if g is not None else set()
            if len(files_) == 1:
                f = next(iter(files_))
                if copy_of.get(f, set()) & seen_sig.get(sig(g), set()):
                    dup_n += 1
                    continue
            keep.append((q, g))
        raw_groups = keep
        if dup_n:
            warnings.append(f'{dup_n} group(s) found again in a copy of a file were left out (the original is listed)')
    recurring_left = 0
    if recurring != 'all' and not queries:
        keep = []
        for q, g in raw_groups:
            if g['pattern'] == 'recurring' and (not recurring or not _notable(g)):
                recurring_left += 1
                continue
            keep.append((q, g))
        raw_groups = keep
        if recurring_left:
            warnings.append(f'{recurring_left} recurring group(s) left out: ' + (
                'recurring=False' if not recurring else
                'stock phrases said again far apart, with no claim difference and fewer than 3 content words or no '
                'whole line repeated (recurring="all" lists them)'))
    # order: script order; else retakes first, more takes first, then recording order
    if not restarts and not queries:
        n0 = len(raw_groups)
        raw_groups = [(q, g) for q, g in raw_groups if g['pattern'] != 'restart']
        if n0 > len(raw_groups):
            warnings.append(f'{n0 - len(raw_groups)} restart group(s) left out (restarts=False)')
    if not queries:
        rank = {'retakes': 0, 'mixed': 1, 'restart': 2, 'recurring': 3, 'single': 4}
        raw_groups.sort(key=lambda qg: (rank.get(qg[1]['pattern'], 3), -len(qg[1]['takes']),
                                        qg[1]['takes'][0]['unit'].order))
    total_groups = sum(1 for _, g in raw_groups if g is not None and g['takes'])
    kept = raw_groups if queries else raw_groups[:st['max_groups']]
    if not queries and total_groups > len(kept):
        warnings.append(f"{total_groups} groups found; the first {len(kept)} are returned (max_groups)")
    # ids
    groups = []
    for q, g in kept:
        if g is None:
            groups.append({'query': q, 'group': None})
            continue
        for t in g['takes']:
            t['id'] = 't' + _short_id(t['doc'].ident, f"{t['start']:.2f}", f"{t['end']:.2f}")
        g['group_id'] = 'g' + _short_id(*(sorted(t['id'] for t in g['takes']) + [q or '']))
        groups.append({'query': q, 'group': g})
    return units, groups, total_groups, recurring_left


def _measure_take_groups(groups, analyze, want, st, prog, warnings):
    all_takes = [t for x in groups if x['group'] for t in x['group']['takes']]
    fcache = _FileCache(analyze)
    envs = {}
    lock = threading.Lock()
    done = [0]

    def measure(t):
        prog.check()                                  # a cancel stops the whole run
        try:
            measure_one(t)
        except Exception as e:  # noqa: BLE001 - one unreadable take must not lose the others
            t['components'] = {'error': f'{type(e).__name__}: {e}'[:300],
                               'text': {'coverage': t['coverage'], 'similarity': t['similarity']}}
            with lock:
                warnings.append(f"{t['doc'].name} {clock(t['start'])}: measurements failed ({type(e).__name__})")
                done[0] += 1

    def measure_one(t):
        doc = t['doc']
        comps = {}
        path_ok = doc.exists and os.path.exists(doc.file)
        envd = None
        if 'delivery' in want:
            comps['delivery'] = _delivery(t, t['unit'], t['tlo'], t['thi'], doc, st)
        if 'audio' in want or 'edges' in want:
            if path_ok:
                ctx = [w for w in doc.ws if float(w['e']) >= t['start'] - st['context_s'] - 0.6
                       and float(w['s']) <= t['end'] + st['context_s'] + 0.6]
                aud, envd = _audio_measures(doc.file, t, doc, st, ctx)
            else:
                aud = {'available': False, 'why': 'not a media file on this PC (given words only)'}
            if 'audio' in want:
                comps['audio'] = aud
                if path_ok:
                    v = _voice(t, doc, fcache.get('voice', doc.file))
                    if v:
                        comps['audio'].update(v)
            if 'edges' in want:
                comps['edges'] = _edges(t, doc, envd, aud.get('speech_db') if aud.get('available') else None, st,
                                        path_ok)
        if 'noise' in want:
            comps['noise'] = _noise(t, fcache.get('sounds', doc.file) if path_ok else None) if path_ok else {
                'available': False, 'why': 'not a media file on this PC'}
        if 'picture' in want:
            comps['picture'] = _picture(t, fcache.get('motion', doc.file)) if path_ok else {
                'available': False, 'why': 'not a media file on this PC'}
        if 'transcript' in want:
            comps['transcript'] = _transcript_conf(t, doc)
        if 'speaker' in want:
            spk = sorted({str(doc.ws[k].get('speaker')) for k in range(t['k0'], t['k1'] + 1) if doc.ws[k].get('speaker')})
            comps['speaker'] = ({'available': True, 'speakers': spk, 'mixed': len(spk) > 1,
                                 'name': doc.ws[t['k0']].get('speaker_name')} if spk else
                                {'available': False, 'why': 'no speaker assignment (letitedit_speakers makes one)'})
        comps['text'] = {'coverage': t['coverage'], 'similarity': t['similarity'],
                         'differences': _kind_counts(t.get('diff_kinds') or []),
                         'claim_differences': sum(1 for k in (t.get('diff_kinds') or []) if k in CLAIM_KINDS)}
        t['components'] = comps
        e = comps.get('edges') or {}
        if path_ok:
            t['edit_item'] = {'clip': doc.file, 'in': e.get('cut_in', round(max(0.0, t['start'] - 0.03), 3)),
                              'out': e.get('cut_out', round(t['end'] + 0.06, 3))}
        dur = doc.duration
        t['context'] = [round(max(0.0, t['start'] - st['context_s']), 3),
                        round(t['end'] + st['context_s'] if not dur else min(dur, t['end'] + st['context_s']), 3)]
        with lock:
            envs[t['id']] = envd
            done[0] += 1
            prog(0.3 + 0.45 * done[0] / max(1, len(all_takes)), f'measuring takes ({done[0]}/{len(all_takes)})')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(measure, all_takes))
    return fcache, envs


def _assemble_take_groups(groups, want, weights):
    out_groups, artifacts = [], []
    kinds_total = {}
    claim_groups = 0
    unmatched = []
    for gi, x in enumerate(groups, 1):
        g = x['group']
        if g is None:
            unmatched.append(x['query'])
            continue
        takes_out = []
        for t in g['takes']:
            to = _take_out(t, g, want)
            to['_raw'] = t
            to['_info'] = {'media': t['doc'].media if t['doc'].exists else None, 'width': t['doc'].width,
                           'height': t['doc'].height}
            to['_gid'] = g['group_id']
            takes_out.append(to)
        claim_kinds = sorted({k for t in g['takes'] for k in (t.get('diff_kinds') or []) if k in CLAIM_KINDS})
        variants = [_variant_out(g, v, vi) for vi, v in enumerate(g['variants'])]
        same = len([v for v in g['variants'] if v['takes']]) <= 1 and not (
            g['query'] is not None and any(not v.get('script') for v in g['variants'] if v['takes']))
        if not same:
            claim_groups += 1
        for d in g['diffs']:
            for k in d['kinds']:
                kinds_total[k] = kinds_total.get(k, 0) + 1
        ref = g['ref']
        passage = (g['query'] if g['query'] is not None else
                   _tok_text(g['ref_unit'], g['rlo'], g['rhi']))
        og = {'group_id': g['group_id'], 'pattern': g['pattern'], 'query': g['query'],
              'passage': {'text': passage, 'reference': None if ref is None else ref['label'],
                          'tokens': len(g['rtoks'])},
              'same_claim': same, 'claim_kinds': claim_kinds, 'claim_variants': variants,
              'differences': g['diffs'][:40], 'differences_total': len(g['diffs']),
              'gaps': g['gaps'], 'takes': takes_out}
        if g['copies']:
            og['copies_left_out'] = [{'file': t['doc'].file, 'start': t['start'], 'end': t['end']} for t in g['copies']]
        if g['dropped']:
            og['outside_duration_limits'] = [{'file': t['doc'].file, 'start': t['start'], 'end': t['end']}
                                             for t in g['dropped']]
        if weights:
            og['ordered_by_weights'] = _weighted(takes_out, weights)
        og['look_items'] = [{'file': t['file'], 'range': t['context'], 'count': 6, 'label': f"{t['label']} {t['name']}",
                             'lanes': ['waveform', 'words']} for t in takes_out if t['_info'].get('media') == 'video'][:8]
        out_groups.append(og)
    return out_groups, artifacts, kinds_total, claim_groups, unmatched


def _make_take_previews(clips_for, previews, out_groups, groups, st, prog, folder, envs, artifacts, warnings):
    clips_for = [clips_for] if isinstance(clips_for, str) else list(clips_for or [])
    if (previews != 'none' or clips_for) and out_groups:
        prog(0.78, 'drawing comparison sheets')
        n_prev = st['preview_groups']
        want_clips = previews in ('clips', 'both')
        for gi, og in enumerate(out_groups, 1):
            prog.check()
            sheet_this = previews in ('sheets', 'both') and gi <= n_prev
            clip_this = (og['group_id'] in clips_for) if clips_for else (want_clips and gi <= n_prev)
            if not (sheet_this or clip_this):
                continue
            g = next(x['group'] for x in groups if x['group'] and x['group']['group_id'] == og['group_id'])
            g['takes_out'] = og['takes']
            g['same_claim'] = og['same_claim']
            g['claim_kinds'] = og['claim_kinds']
            g['passage'] = og['passage']
            if sheet_this:
                prog(0.78 + 0.2 * gi / max(1, min(n_prev, len(out_groups))), f'drawing sheet {gi}')
                try:
                    og['sheet'] = _sheet(g, gi, folder, st, envs, st['frames'])
                    artifacts.append({'kind': 'sheet', 'group': og['group_id'], 'path': og['sheet']})
                except Exception as e:  # noqa: BLE001 - a picture that fails is reported, not fatal
                    warnings.append(f"{og['group_id']}: sheet failed ({type(e).__name__}: {e})"[:300])
            if clip_this:
                prog(0.78 + 0.2 * gi / max(1, len(out_groups)), f'cutting preview clips for {og["group_id"]}')
                vertical = sum(1 for t in og['takes'] if (t['_info'].get('height') or 0) > (t['_info'].get('width') or 0))
                short = st['clip_height'] // 2 * 2
                W, H = ((short, short * 16 // 9 // 2 * 2) if vertical * 2 >= len(og['takes']) else
                        (short * 16 // 9 // 2 * 2, short))
                clips = []
                for t in og['takes']:
                    if not t['_raw']['doc'].exists:
                        clips.append((t, None))
                        continue
                    try:
                        c = _clip(t, W, H, folder, st)
                    except (OSError, subprocess.SubprocessError) as e:
                        warnings.append(f"{og['group_id']} {t['label']}: clip failed ({type(e).__name__})")
                        c = None
                    if c:
                        t['clip'] = c
                        artifacts.append({'kind': 'clip', 'group': og['group_id'], 'take': t['take'], 'path': c})
                    clips.append((t, c))
                try:
                    reel = _reel(g, clips, W, H, folder)
                except (OSError, subprocess.SubprocessError) as e:
                    warnings.append(f"{og['group_id']}: reel failed ({type(e).__name__})")
                    reel = None
                if reel:
                    og['reel'] = reel
                    artifacts.append({'kind': 'reel', 'group': og['group_id'], 'path': reel})
        if clips_for:
            known = {og['group_id'] for og in out_groups}
            for gid in clips_for:
                if gid not in known:
                    warnings.append(f'clips_for: no group {gid} in this result')
    for og in out_groups:
        for t in og['takes']:
            t.pop('_raw', None)
            t.pop('_info', None)
            t.pop('_gid', None)
            t.pop('_frames', None)


def find(files=None, archive=None, words=None, script=None, phrase=None, ranges=None, speaker=None,
         speakers='cached', min_take_s=None, max_take_s=None, measures=None, weights=None, names=None,
         min_words=None, min_similarity=None, recurring=True, restarts=True, previews='sheets', clips_for=None,
         context_s=None, transcribe=False, analyze=False, max_groups=None, out_dir=None, settings=None, reuse=True,
         progress=None, check=None):
    """Find repeated takes. See takes_tools.letitedit_find_takes for every input and output."""
    t_start = time.monotonic()
    prog = _Progress(progress, check)
    params = {'min_take_s': min_take_s, 'max_take_s': max_take_s, 'min_words': min_words,
              'min_similarity': min_similarity, 'context_s': context_s, 'max_groups': max_groups}
    st, defaulted = _settings(params, settings)
    previews = (previews or 'none') if previews is not False else 'none'
    if previews is True:
        previews = 'sheets'
    if previews not in PREVIEWS:
        raise ValueError(f"previews: {', '.join(PREVIEWS)}")
    if speakers not in ('cached', 'run', 'off'):
        raise ValueError("speakers: 'cached' (use a stored letitedit_speakers result), 'run' (make one) or 'off'")
    want = list(MEASURES) if measures is None else [m for m in ([measures] if isinstance(measures, str) else measures)]
    bad = [m for m in want if m not in MEASURES]
    if bad:
        raise ValueError(f"measures: any of {', '.join(MEASURES)}; not {', '.join(bad)}")
    if 'text' not in want:
        want = ['text'] + want
    if weights is not None and not isinstance(weights, dict):
        raise ValueError("weights: {component path: weight}, e.g. {'audio.snr_db': 1, 'delivery.pauses.count': -1}")
    queries = []
    if script:
        queries = [s.strip() for s in (script.splitlines() if isinstance(script, str) else script) if str(s).strip()]
    if phrase:
        queries.append(str(phrase).strip())
    warnings, unchecked = [], []
    prog(0.01, 'reading transcripts')
    docs, prints = _load(files, archive, words, ranges, speaker, speakers, transcribe, st, prog, warnings, unchecked)
    # the result id: inputs, settings and what the sources are now
    ident = {'schema': SCHEMA_VERSION, 'algo': ALGO_VERSION, 'settings': st, 'queries': queries, 'speaker': speaker,
             'speakers': speakers, 'measures': want, 'weights': weights, 'names': names, 'recurring': recurring,
             'restarts': bool(restarts), 'previews': previews, 'clips_for': clips_for, 'analyze': bool(analyze),
             'sources': [{k: p.get(k) for k in ('file', 'size', 'mtime_ns', 'identity', 'transcript', 'analysis',
                                                'speakers')} for p in prints],
             'ranges': ranges}
    result_id = _short_id(json.dumps(ident, sort_keys=True, default=str), n=12)
    folder = Path(out_dir) if out_dir else OUT / result_id
    rfile = folder / 'result.json'
    if reuse and rfile.exists():
        try:
            old = json.loads(rfile.read_text(encoding='utf-8-sig'))
            if old.get('result_id') == result_id and all(os.path.exists(a['path'])
                                                         for a in old.get('preview_artifacts') or []):
                old['reused'] = True
                return old
        except (OSError, ValueError):
            pass
    folder.mkdir(parents=True, exist_ok=True)
    units, groups, total_groups, recurring_left = _find_take_groups(docs, st, names, queries, recurring, restarts, prog, warnings)
    # measurements
    fcache, envs = _measure_take_groups(groups, analyze, want, st, prog, warnings)
    # assemble
    out_groups, artifacts, kinds_total, claim_groups, unmatched = _assemble_take_groups(groups, want, weights)
    # previews
    _make_take_previews(clips_for, previews, out_groups, groups, st, prog, folder, envs, artifacts, warnings)
    # coverage of the check
    checked = []
    rng_by = {}
    if ranges:
        import letitedit.footage.index_tools as it
        try:
            rng_by = it._ranges(ranges, [d.file for d in docs]) or {}
        except ValueError:
            rng_by = {}
    for d in docs:
        span = rng_by.get(d.file) or ([[0.0, d.duration]] if d.duration else (
            [[float(d.ws[0]['s']), float(d.ws[-1]['e'])]] if d.ws else []))
        checked.append({'file': d.file, 'ranges': [[round(float(a), 2), round(float(b), 2)] for a, b in span],
                        'words': len(d.ws), 'lines': len(d.units)})
        if d.exists:
            voice = fcache.get('voice', d.file)
            if voice:
                miss = []
                for x, y in voice:
                    if y - x < 1.0:
                        continue
                    cov = _overlap(x, y, [(float(w['s']) - 0.2, float(w['e']) + 0.2) for w in d.ws
                                          if float(w['e']) >= x - 1 and float(w['s']) <= y + 1])
                    if cov < 0.2 * (y - x):
                        miss.append([round(x, 2), round(y, 2)])
                if miss:
                    unchecked.append({'file': d.file, 'ranges': miss[:20],
                                      'reason': 'voice detected but no words transcribed there (missed speech, '
                                                'another language, or singing)'})
    unsupported = list(UNSUPPORTED)
    if not any(d.speakers_known for d in docs):
        unsupported.insert(0, {'case': 'speaker unknown', 'detail': 'no letitedit_speakers assignment for these files: '
                               'takes are compared without knowing who speaks, so another person saying the same words '
                               'could be grouped as a take (speakers="run" makes an assignment)'})
    non_ascii = sum(1 for d in docs for w in d.ws if not str(w['w']).isascii())
    n_words = sum(len(d.ws) for d in docs)
    if n_words and non_ascii / n_words > 0.1:
        warnings.append(f'{non_ascii} of {n_words} words are not plain English letters: number words, negation and '
                        'names are judged with English rules (see unsupported)')
    summary = {'files': len(prints), 'files_with_words': sum(1 for d in docs if d.ws), 'words': n_words,
               'lines': len(units), 'groups': total_groups, 'groups_returned': len(out_groups),
               'takes': sum(len(og['takes']) for og in out_groups),
               'retake_groups': sum(1 for og in out_groups if og['pattern'] == 'retakes'),
               'restart_groups': sum(1 for og in out_groups if og['pattern'] == 'restart'),
               'recurring_groups': sum(1 for og in out_groups if og['pattern'] == 'recurring'),
               'mixed_groups': sum(1 for og in out_groups if og['pattern'] == 'mixed'),
               'groups_with_different_claims': claim_groups, 'recurring_left_out': recurring_left,
               'differences': kinds_total,
               'false_starts': sum(1 for og in out_groups for t in og['takes'] if t['completeness'] == 'false_start')}
    if queries:
        summary['script_lines'] = len(queries)
        summary['script_lines_not_found'] = len(unmatched)
    res = {'schema_version': SCHEMA_VERSION, 'tool': TOOL, 'result_id': result_id, 'plan_id': result_id,
           'project_revision': None, 'source_fingerprints': prints, 'summary': summary,
           'groups': out_groups, 'checked_ranges': checked, 'unchecked_ranges': unchecked,
           'warnings': warnings, 'unsupported': unsupported, 'preview_artifacts': artifacts,
           'changes': [], 'note': 'analysis only: nothing was cut, moved or deleted. Place a chosen take with its '
                                  'edit_item ({clip, in, out}) in letitedit_timeline_apply.',
           'settings': {**st, 'measures': want, 'previews': previews, 'speakers': speakers, 'speaker': speaker,
                        'recurring': recurring, 'transcribe': bool(transcribe), 'analyze': bool(analyze)},
           'defaults': defaulted, 'measures_info': MEASURES_INFO, 'folder': str(folder)}
    if queries:
        res['script_lines_not_found'] = unmatched
    res['text'] = report_text(res)
    res['seconds'] = round(time.monotonic() - t_start, 2)
    res['result_file'] = str(rfile)
    tmp = rfile.with_name(f'result.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(res, indent=1, default=str), encoding='utf-8')
    os.replace(tmp, rfile)
    prog(1.0, 'done')
    return res


MEASURES_INFO = {
    'text': 'deterministic: coverage = share of the reference passage (or script line) this take says; similarity = '
            'difflib ratio of the two token lists; differences by kind',
    'delivery': 'deterministic, from word timings: duration_s, words, words_per_s; pauses (gaps between words >= '
                'long_pause_s: count, longest_s, total_s, at [[time, length]]); restarts (a word or phrase said twice '
                'in a row, or again within 3 words); fillers (um, uh...)',
    'edges': 'lead_in_s / tail_out_s: silence between this take and the word before / after it (or the recording '
             'start / end); first_word_cut_by_recording_start / last_word_cut_by_recording_end: the recording starts '
             '/ stops while the sound is at talking level (None = unknown); cut_in / cut_out: cut points snapped to '
             'the audio (cutpoints.snap); tight_in / tight_out: under 0.1 s of room; first/last_word_p: the '
             "transcriber's probability for the edge words (a model score)",
    'audio': 'measured on the decoded sound of the take: peak_dbfs, clipped_samples (|x| >= 0.99), clip_runs and '
             'clipped_ms (runs of 3+ such samples); speech_db = median 10 ms level during its words, noise_db = 15th '
             'percentile of the level away from words (take + context), snr_db = their difference; '
             'voice_without_words_s / words_without_voice_s against the cached voice detector. Loudness is not '
             'delivery quality',
    'noise': 'the cached sound analysis (perception.sounds): impacts (bang, clank, thud, click) inside the take, '
             'sustained sounds overlapping it with their share of the take, loud_background for the file',
    'picture': 'the cached footage analysis (perception.picture), shares of the take: dark, blown_out, blurry, shaky '
               '(shaky handheld or fast whip); camera (the main motion label); cuts_inside; sharpness_vs_clip = '
               "median sharpness over the take / the clip's median",
    'transcript': "the transcriber's word probabilities (a model score, not calibrated): mean_p, min_p, unsure_words "
                  '(under 0.45)',
    'speaker': 'a cached letitedit_speakers assignment (voice clusters): the speaker ids in the take, mixed = more than one',
}


def report_text(res):
    """A compact reading of the result: one block per group, one line per take."""
    s = res['summary']
    lines = [f"{s['groups']} group(s) in {s['files']} file(s) ({s['words']} words, {s['lines']} lines): "
             f"{s['retake_groups']} retakes, {s.get('restart_groups', 0)} restarts inside a line, "
             f"{s['recurring_groups']} recurring, {s.get('mixed_groups', 0)} mixed; "
             f"{s['takes']} takes; {s['false_starts']} false starts; "
             f"{s['groups_with_different_claims']} group(s) with different claims; differences "
             + (', '.join(f'{k} {v}' for k, v in sorted(s['differences'].items())) or 'none')]
    for g in res['groups']:
        claim = 'same claim' if g['same_claim'] else 'DIFFERENT CLAIMS: ' + ', '.join(g['claim_kinds'] or ['vs script'])
        head = f"\n{g['group_id']} {g['pattern']} ({len(g['takes'])} takes, {claim})"
        if g.get('query'):
            head += f" script: \"{g['query']}\""
        else:
            head += f" \"{g['passage']['text'][:160]}\""
        lines.append(head)
        for t in g['takes']:
            lines.append('  ' + brief_take(t))
        for v in g['claim_variants']:
            if len(g['claim_variants']) > 1 and v.get('says'):
                lines.append(f"  variant {v['variant']} ({', '.join(v['takes']) or 'script'}): " + '; '.join(
                    f"{'/'.join(x['kinds'])} \"{x['says']}\"" for x in v['says']))
        crit = [d for d in g['differences'] if set(d['kinds']) & set(CLAIM_KINDS)]
        for d in crit[:6]:
            lines.append(f"  ! {d['take']} vs {d['vs']}: {'/'.join(d['kinds'])} \"{d['text']}\" vs \"{d['vs_text']}\"")
        if g.get('sheet'):
            lines.append(f"  sheet: {g['sheet']}")
        if g.get('reel'):
            lines.append(f"  reel: {g['reel']}")
    if res.get('script_lines_not_found'):
        lines.append('\nnot found: ' + ' | '.join(res['script_lines_not_found']))
    if res['unchecked_ranges']:
        lines.append(f"\nunchecked: {len(res['unchecked_ranges'])} file range set(s) (see unchecked_ranges)")
    return '\n'.join(lines)


def compact(res, detail='brief'):
    """The result as the MCP tool returns it. 'full': everything. 'brief': the text report plus groups with their
    takes' ranges, text, variants and edit items; every measurement stays in result_file."""
    if detail == 'full':
        return res
    keep = ('schema_version', 'tool', 'result_id', 'plan_id', 'project_revision', 'summary', 'text', 'warnings',
            'unchecked_ranges', 'changes', 'note', 'result_file', 'folder', 'seconds', 'reused',
            'script_lines_not_found')
    out = {k: res[k] for k in keep if k in res}
    out['unsupported'] = [u['case'] for u in res.get('unsupported') or []]
    out['checked'] = {'files': len(res.get('checked_ranges') or []),
                      'words': sum(c.get('words') or 0 for c in res.get('checked_ranges') or [])}
    out['preview_artifacts'] = res.get('preview_artifacts') or []
    groups = []
    for g in res.get('groups') or []:
        gg = {k: g[k] for k in ('group_id', 'pattern', 'query', 'passage', 'same_claim', 'claim_kinds',
                                 'claim_variants', 'gaps', 'sheet', 'reel', 'copies_left_out', 'look_items')
              if g.get(k) is not None}
        diffs = g.get('differences') or []
        crit = [d for d in diffs if set(d['kinds']) & set(CLAIM_KINDS)]
        rest = [d for d in diffs if d not in crit]
        gg['differences'] = crit + rest[:max(0, 8 - len(crit))]
        if (g.get('differences_total') or 0) > len(gg['differences']):
            gg['differences_more'] = g['differences_total'] - len(gg['differences'])
        gg['takes'] = []
        for t in g['takes']:
            tt = {k: t[k] for k in ('take', 'label', 'name', 'file', 'start', 'end', 'text', 'reference', 'variant',
                                     'completeness', 'coverage', 'similarity', 'matches_script', 'compatible_variants',
                                     'edit_item', 'context', 'frames', 'clip', 'copies') if t.get(k) is not None}
            gg['takes'].append(tt)
        if g.get('ordered_by_weights'):
            w = g['ordered_by_weights']
            gg['ordered_by_weights'] = {'order': w['order'], 'totals': w['totals'], 'missing': w['missing'],
                                        'how': w['how']}
        groups.append(gg)
    out['groups'] = groups
    out['detail'] = ("brief: the measurements per take are in 'text' (one line each) and in full in result_file "
                     "(components, measures_info, source_fingerprints, checked_ranges); detail='full' returns all")
    return out


# ------------------------------------------------------------------ background job

def job(ctx):
    """jobs.py kind 'takes:job': find(**ctx.inputs) with progress and cancel; outputs the result file."""
    inputs = dict(ctx.inputs or {})
    inputs.pop('background', None)
    res = find(**inputs, progress=ctx.progress, check=ctx.check)
    return {'result_file': res['result_file'], 'result_id': res['result_id'], 'summary': res['summary'],
            'sheets': [a['path'] for a in res['preview_artifacts'] if a['kind'] == 'sheet'],
            'warnings': res['warnings'][:10]}


def submit(inputs, root=None):
    """Queue find(**inputs) as a background job (jobs.py); returns the job status (job_id)."""
    import letitedit.core.jobs as jobs
    return jobs.submit('takes:job', inputs=inputs, label='find takes', root=root, timeout_s=4 * 3600)
