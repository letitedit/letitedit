"""Hook candidates: distinct ways to open a video, proposed in about a second from what the server already knows
(the cached transcripts of the cut's own source files, cached emotion graphs and picture facts when they exist, and
the cut itself), kept in a file beside the project so the app's Regenerate button can show the next one at once and
the AI can add or refine candidates.

    candidates(project, count=8, exclude=(), refresh=False, more=False, mark_shown=True) -> next unseen candidates
                                    (the tools list with mark_shown=False: only mark() changes a status)
    preview(project, candidate_id)  -> a cached low-res MP4 (and frame strip) of the opening with that hook
    apply_op(script, op)            -> {op: hook, candidate, text?, mode?}: the project's opening swapped, one undo
    mark(project, ids, status)      -> 'shown' | 'rejected' | 'new' | 'applied'

The file: <project folder>/<project stem>.letitedit/hooks.json (the contract is in STYLES.md, "Hooks file"); every
read-change-write of it holds hooks.json.lock beside it (locked()), so the app's background calls, its apply and the
AI never lose each other's changes:

    {format: letitedit-hooks/1, project, made, cut_sig, style, rules: {max_s, max_words}, depth, applied,
     candidates: [{id, approach, label, source: {clip, in, out}, timeline: {start, end} | null, in_cut, item_id,
                   said, text: [2-3 options], why, score, signals, effects, by, status, order, preview, preview_sheet}],
     requests: [{at, count, by}]}

Approaches: result_first (the payoff first, a flash-forward), question, stakes (the problem in one breath), number
(a concrete figure), quote (the strongest line: emotion and energy), mid_action (a moment without words), current
(the cut's own opening, kept for going back). Scores are rules over the words and the cached signals (each candidate
lists them): a ranking for choosing what to show first, not a judgement of quality. Text options are drafts in the
speaker's own words; the AI may rewrite them in the file (by: claude | codex) or add candidates.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import contextlib
from collections import Counter
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

FILE = 'hooks.json'
FORMAT = 'letitedit-hooks/1'
GENERATOR = 4
APPROACHES = ('result_first', 'question', 'stakes', 'number', 'quote', 'mid_action')
LABELS = {'result_first': 'Result first', 'question': 'A question', 'stakes': 'The problem', 'number': 'A number',
          'quote': 'Strongest line', 'mid_action': 'Mid-action', 'current': 'The current opening'}
HOOK_PREFIX = 'hook-'
TEXT_TRACK = 'Hook text'
PAD_IN, PAD_OUT = 0.12, 0.28

STOP = set('''a an the and or but so if then than that this these those there here it its it's i i'm im me my we
we're our you you're your he she they them their is are was were be been being am do does did doing done have has
had having to of in on at by for with from up down out over under again further once just very really pretty
kind sort like um uh uhm umm hmm er ah oh yeah yes no not can could would should will shall may might must gonna
wanna gotta got get gets getting go goes going went come came take took make made see saw look looking all any
some more most other such only own same too also about into through during before after above below off
what which who whom why how when where because as until while one thing things stuff guys okay ok right well
know think thought mean actually basically little bit lot lots maybe probably let's lets let want need'''.split())
FILLERS = {'um', 'uh', 'uhm', 'umm', 'uhh', 'hmm', 'er', 'erm', 'ah', 'eh', 'mm'}
LEAD_TRIM = {'and', 'so', 'but', 'um', 'uh', 'yeah', 'oh', 'okay', 'ok', 'well', 'like', 'alright', 'right', 'now',
             'then', 'all'}
QUESTION_START = ('what', 'why', 'how', 'who', 'where', 'when', 'which', 'did', 'does', 'do', 'can', 'could', 'would',
                  'will', 'is', 'are', 'was', 'were', 'have', 'has', 'should', 'ever', 'guess')
STAKES = {'fail', 'failing', 'failed', 'broken', 'broke', 'break', 'breaking', 'problem', 'problems', 'issue', 'wrong',
          'danger', 'dangerous', 'stuck', 'worst', 'mistake', "can't", 'cannot', "won't", 'died', 'dead', 'leak',
          'leaking', 'grind', 'grinding', 'noise', 'noisy', 'smoke', 'fire', 'crack', 'cracked', 'risk', 'scary',
          'afraid', 'expensive', 'lost', 'losing', 'emergency', 'bad', 'terrible', 'horrible', 'disaster', 'ruined',
          'diagnose', 'cavitating', 'rattling', 'squeak', 'squeaking', 'hot', 'overheating', 'flat', 'stranded'}
RESULT = {'works', 'worked', 'working', 'fixed', 'finally', 'accomplished', 'success', 'perfect', 'better', 'gone',
          'quiet', 'silent', 'smooth', 'finished', 'solved', 'beautiful', 'amazing', 'awesome', 'nailed', 'win',
          'won', 'done', 'cool', 'cold', 'clean', 'new'}
RESULT_PHRASES = ('no longer', 'sounds good', 'sounds pretty good', 'all gone', 'mission accomplished', 'it works',
                  'we did it', 'good to go', 'back in', 'like new', 'problem solved')
GREETING = re.compile(r"\b(hey|hi|hello|what'?s up)\b.{0,12}\b(guys|everyone|everybody|y'?all|folks|friends)\b"
                      r"|\bwelcome (back|to)\b|\bin (this|today'?s) (video|episode)\b|\bmy name is\b"
                      r"|\bit'?s \w+ here\b|\btoday (i|we)\b|\blet'?s get (started|into)\b|\bwithout further ado\b"
                      r"|\bso today\b|\btake you (guys )?along\b|\bsubscribe\b", re.I)
BAD_OPEN = re.compile(r"^(?:and|or|but|because|which|that|so)\b|\b(?:that's all i got|thanks for listening|"
                      r"sign up for the beta|join the beta|does far more than this)\b", re.I)
NUM_WORDS = {'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'fifteen',
             'twenty', 'thirty', 'forty', 'fifty', 'hundred', 'thousand', 'million', 'half', 'dozen'}
UNITS = {'bucks', 'dollars', 'dollar', 'cents', 'percent', 'hours', 'hour', 'minutes', 'minute', 'days', 'day',
         'weeks', 'months', 'years', 'miles', 'degrees', 'feet', 'inches', 'pounds', 'times', 'screws', 'bolts'}
MOOD_FOR = {'result_first': ('satisfaction', 'relief', 'joy'), 'question': ('surprise', 'tension'),
            'stakes': ('tension', 'frustration', 'awkwardness'), 'number': ('surprise', 'excitement'),
            'quote': ('humor', 'surprise', 'excitement', 'awe', 'joy'),
            'mid_action': ('excitement', 'surprise', 'awe', 'tension')}


# ------------------------------------------------------------------ files

def folder(project):
    import letitedit.timeline.project_journal as pj
    return pj.folder(Path(project).resolve())


def path_for(project):
    return folder(project) / FILE


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


LOCK_TIMEOUT_S = 30.0
_held = threading.local()


@contextlib.contextmanager
def locked(project):
    """The project's hooks.json write lock: an OS lock on hooks.json.lock beside it (as style_pack.update() locks a
    pack's style.yaml), held for each read-change-write, so background next / more / mark / request / preview, the
    app's apply and the AI's letitedit_hooks never interleave a read and a write. Re-entrant in a thread; Windows lets
    it go when its process ends (a helper killed with its window never leaves it held)."""
    import msvcrt
    lock = path_for(project).with_name(FILE + '.lock')
    key = os.path.normcase(str(lock))
    held = _held.__dict__.setdefault('paths', {})
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, 'a+b') as fh:
        if fh.tell() == 0:
            fh.write(b'0')
            fh.flush()
        end = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > end:
                    raise TimeoutError(f'{path_for(project)} is being written by another letitedit process; '
                                       f'try again') from None
                time.sleep(0.03)
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _retry(fn, timeout_s=3.0):
    """Windows refuses to replace or read a file while another process opens it without sharing (the app reading
    hooks.json at that moment): try again for a moment."""
    end = time.monotonic() + timeout_s
    while True:
        try:
            return fn()
        except PermissionError:
            if time.monotonic() > end:
                raise
            time.sleep(0.02)


def load(project):
    f = path_for(project)
    if not f.exists():
        return None
    try:
        data = json.loads(_retry(lambda: f.read_text(encoding='utf-8-sig')))
    except (ValueError, FileNotFoundError):
        return None
    return data if isinstance(data, dict) and data.get('format') == FORMAT else None


def save(project, data):
    """Write hooks.json in one step (a reader never sees half a file). Callers that read, change and write it hold
    locked(project) around all three."""
    f = path_for(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f'{FILE}.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    _retry(lambda: os.replace(tmp, f))
    return str(f)


# ------------------------------------------------------------------ reading the material

def _norm(w):
    return re.sub(r"[^0-9a-z']+", '', str(w).lower().replace('’', "'")).strip("'")


def _sentences(words, max_gap=0.9, max_words=40):
    """Words -> thought runs: punctuation wins; a long pause may separate complete thoughts."""
    out, cur = [], []
    for w in words:
        if cur and (float(w['s']) - float(cur[-1]['e']) > max_gap or len(cur) >= max_words):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r'[.?!]["\')\]]*$', str(w['w']).strip()):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _clauses(sent, max_s=4.5):
    """A long sentence -> clauses (at commas and at and/but/so after a pause), each up to about max_s seconds."""
    if float(sent[-1]['e']) - float(sent[0]['s']) <= max_s:
        return [sent]
    parts, cur = [], []
    for k, w in enumerate(sent):
        tok = _norm(w['w'])
        gap = float(w['s']) - float(sent[k - 1]['e']) if k else 0
        if cur and (tok in ('but', 'so', 'and', 'because') and gap > 0.15 or
                    float(w['e']) - float(cur[0]['s']) > max_s):
            parts.append(cur)
            cur = []
        cur.append(w)
        if str(w['w']).strip().endswith(','):
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    return [p for p in parts if p]


def _cached_words(path, transcribe=False):
    import letitedit.footage.speech as speech
    if not transcribe and speech._cached(speech._identity(path)) is None:
        return None
    return speech.words(path)


def _emotion(path):
    try:
        import letitedit.footage.emotion_graph as emotion_graph
        return emotion_graph.cached(path)
    except Exception:  # noqa: BLE001 - no graph: the words alone decide
        return None


def _facts(path):
    try:
        import letitedit.footage.factlog as factlog
        return factlog.facts(path, build=False)
    except Exception:  # noqa: BLE001
        return None


def _moods_at(graph, a, b):
    """The strongest score per mood over the graph's stretches that overlap [a, b] (source seconds)."""
    out = {}
    for u in (graph or {}).get('units') or []:
        if float(u.get('t1', 0)) <= a or float(u.get('t0', 0)) >= b:
            continue
        for k, v in (u.get('scores') or {}).items():
            try:
                out[k] = max(out.get(k, 0.0), float(v))
            except (TypeError, ValueError):
                pass
    return out


def _facts_at(facts, a, b):
    out = {}
    for st in (facts or {}).get('stretches') or []:
        if float(st.get('to', 0)) <= a or float(st.get('from', 0)) >= b:
            continue
        fa = st.get('facts') or {}
        for k in ('camera', 'face', 'shot', 'moments'):
            if fa.get(k) and k not in out:
                out[k] = fa[k]
    return out


def cut_signature(script):
    rows = [(it.get('clip'), round(float(it.get('in', 0)), 2), round(float(it.get('out', 0)), 2), it.get('id'))
            for it, s, e in _main_items(script, hooks=False)]
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:12]


def _main_items(script, hooks=True):
    """(item, start, end) of the clips on the main track (hooks=False: without a hook placed by {op: hook})."""
    from letitedit.timeline.edit_sync import layout, main_track
    m = main_track(script)
    return [(it, s, e) for it, s, e in (layout(m) if m else []) if 'clip' in it
            and (hooks or not str(it.get('id', '')).startswith(HOOK_PREFIX))]


def _where_in_cut(items, clip, a, b):
    """(item, timeline start, timeline end) of the main-track item that plays most of source [a, b] of clip."""
    best = None
    for it, s, e in items:
        if os.path.normcase(str(it['clip'])) != os.path.normcase(str(clip))                 or str(it.get('id', '')).startswith(HOOK_PREFIX):
            continue
        i0, i1 = float(it['in']), float(it['out'])
        cover = max(0.0, min(b, i1) - max(a, i0))
        if cover >= 0.7 * (b - a) and (best is None or cover > best[0]):
            sp = float(it.get('speed', 1.0))
            best = (cover, it, s + (max(a, i0) - i0) / sp, s + (min(b, i1) - i0) / sp)
    return best[1:] if best else None


# ------------------------------------------------------------------ scoring

def _features(ws, topic):
    toks = [_norm(w['w']) for w in ws]
    text = _sentence_case([str(w['w']).strip() for w in ws])
    if text and text[-1] not in '.?!':
        text += '.'
    low = ' '.join(toks)
    dur = max(0.2, float(ws[-1]['e']) - float(ws[0]['s']))
    content = [t for t in toks if t and t not in STOP and t not in FILLERS]
    nums = [t for t in toks if re.fullmatch(r'\d+(\.\d+)?', t) or t in NUM_WORDS]
    money = '$' in text or any(t in ('bucks', 'dollars', 'dollar', 'cents') for t in toks)
    return {
        'text': text, 'dur': dur, 'n': len(ws), 'wps': len(ws) / dur,
        'question': text.rstrip().endswith('?') or (toks[0] if toks else '') in QUESTION_START
        or low.startswith('you hear') or ' you hear ' in f' {low} ',
        'stakes': sum(1 for t in toks if t in STAKES),
        'result': sum(1 for t in toks if t in RESULT) + sum(2 for p in RESULT_PHRASES if p in low),
        'numbers': nums, 'units': [t for t in toks if t in UNITS], 'money': money,
        'greeting': bool(GREETING.search(text)), 'fillers': sum(1 for t in toks if t in FILLERS) / max(1, len(toks)),
        'topic': sum(topic.get(t, 0) for t in set(content)), 'content': content,
    }


def _scores(f, moods, pos, facts):
    m = lambda *ks: max((moods.get(k, 0.0) for k in ks), default=0.0) / 2.0   # noqa: E731 - graph scale 0-2
    energy = min(1.0, max(0.0, (f['wps'] - 1.6) / 2.0))
    looks = 0.1 if str(facts.get('camera')) == 'yes' else 0.0
    s = {
        'result_first': 0.55 * min(1.0, f['result'] / 2) + 0.25 * m(*MOOD_FOR['result_first'])
        + (0.2 if pos is not None and pos > 0.6 else 0.0),
        'question': 0.6 * f['question'] + 0.2 * m(*MOOD_FOR['question']) + 0.2 * min(1, f['stakes']),
        'stakes': 0.5 * min(1.0, f['stakes'] / 1.5) + 0.3 * m(*MOOD_FOR['stakes'])
        + (0.2 if pos is not None and pos < 0.5 else 0.0),
        'number': (0.5 if f['numbers'] else 0.0) + (0.2 if f['money'] else 0.0) + (0.15 if f['units'] else 0.0)
        + 0.15 * energy,
        'quote': 0.45 * m(*MOOD_FOR['quote']) + 0.25 * energy + 0.15 * min(1.0, f['topic'] / 6) + looks,
    }
    if not f['numbers']:
        s['number'] = 0.0
    return s


def _len_factor(dur):
    if dur < 0.8:
        return 0.4
    if dur <= 4.5:
        return 1.0
    return max(0.3, 1.0 - (dur - 4.5) / 6)


# ------------------------------------------------------------------ text options

def _clean(ws):
    toks = [str(w['w']).strip() for w in ws]
    out = []
    for t in toks:
        n = _norm(t)
        if n in FILLERS:
            continue
        out.append(t)
    while out and _norm(out[0]) in LEAD_TRIM:
        out.pop(0)
    # "I don't I don't think" -> "I don't think"
    k = 1
    while k <= 3:
        i, changed = 0, False
        while i + 2 * k <= len(out):
            if [_norm(x) for x in out[i:i + k]] == [_norm(x) for x in out[i + k:i + 2 * k]]:
                del out[i + k:i + 2 * k]
                changed = True
            else:
                i += 1
        if not changed:
            k += 1
    return out


def _sentence_case(words):
    s = ' '.join(words).strip().strip(',;:')
    # Whisper sometimes gives a hyphen its own word ("frame -by -frame").
    s = re.sub(r'\s+-\s*', '-', s)
    s = re.sub(r'\s+([,.?!])', r'\1', s)
    return (s[:1].upper() + s[1:]) if s else s


NOT_TOPIC = set("""diagnose pull take took look looking want need think got get put make going gonna turn turned
sounds sound closed back everything something anything nothing really actually pretty little right here there today
good great thing things guys stuff kind sort way time bit lot start started work working works worked show see""".split())


def _text_options(f, approach, topic, max_words, case):
    """On-screen words from a complete spoken thought. Never carve a high-scoring word fragment out of it."""
    words = _clean([{'w': t} for t in f['text'].split()]) or f['text'].split()
    if not 2 <= len(words) <= 30 or (BAD_OPEN.search(f['text'].strip())
                                      and not re.match(r"^(?:and here's|so all)\b", f['text'], re.I)):
        return []
    if _norm(words[-1]) in {'the', 'a', 'an', 'to', 'of', 'for', 'with', 'and', 'or', 'but',
                            'going', 'gonna', 'will', 'can', 'would', 'is', 'are', 'try', 'trying', 'longer'}:
        return []
    if [_norm(w) for w in words[-2:]] == ['allows', 'you']:
        return []
    if _norm(words[0]) in {'or', 'because', 'which', 'who', 'that', 'is', 'are', 'for', 'simply'}:
        return []
    said = _sentence_case(words)
    if f['question']:
        said = said.rstrip('.!?') + '?'
    if len(words) > max_words + 4:
        return _titles_for({'said': said}, max_words)
    return [said.upper() if case == 'upper' else said]


def _titles_for(c, max_words):
    """Short contiguous phrases from the complete thought; never join unrelated words."""
    said = c.get('said', '')
    words = re.findall(r"[\w]+(?:[-'’][\w]+)*", said)
    options = []
    for n in range(2, min(4, max_words) + 1):
        for i in range(len(words) - n + 1):
            span = words[i:i + n]
            content = sum(_norm(w) not in STOP for w in span)
            if content < 2 or _norm(span[0]) in {'a', 'an', 'and', 'or', 'but', 'because'} or _norm(span[-1]) in {'a', 'an', 'the', 'and', 'or', 'but', 'to', 'of',
                                                   'for', 'with', 'is', 'are', 'was', 'were', "that's"}:
                continue
            title = ' '.join(span).upper()
            if _norm(title) == _norm(said):
                continue
            score = content * 2 + (n - 2) * 0.2 + (1 if i == 0 else 0)
            options.append((score, i, title, {_norm(w) for w in span}))
    options.sort(key=lambda row: (-row[0], row[1]))
    picked = []
    for _, _, title, tokens in options:
        if all(len(tokens & old) / max(1, len(tokens | old)) < 0.65 for _, old in picked):
            picked.append((title, tokens))
        if len(picked) == 1:
            break
    return [title for title, _ in picked]


def _why(approach, f, moods, in_cut, at):
    said = f.get('text', '')
    said = said if len(said) <= 90 else said[:87] + '...'
    mood = ', '.join(f'{k} {v:g}/2' for k, v in sorted(moods.items(), key=lambda kv: -kv[1])
                     if k in MOOD_FOR.get(approach, ()) and v >= 1)[:60]
    mood = f' (emotion graph: {mood})' if mood else ''
    return {
        'result_first': f'Opens on the payoff ("{said}"){mood}: the viewer knows there is a result and stays to see '
                        'how.',
        'question': f'Opens on a question the video answers ("{said}"){mood}: curiosity carries the first seconds; '
                    'the answer follows.',
        'stakes': f'Opens on the problem ("{said}"){mood}: what is at stake in one breath, before any setup.',
        'number': f'Opens on a concrete figure ("{said}"): specifics read as real and make a clear promise.',
        'quote': f'Opens on a strong line ("{said}"){mood}: energy and personality before any setup.',
        'mid_action': f'Opens mid-action{mood} without words: it works muted, and the text says what is going on; '
                      'the story follows.',
    }.get(approach, '')


# ------------------------------------------------------------------ candidates

def _pool(script, kit, depth=0, transcribe=False):
    """Every candidate the material allows at this depth (0: sentences and clauses that score; 1: weaker ones and
    shorter cuts of good lines; 2: anything said), best first, with the files that had no transcript."""
    items = _main_items(script, hooks=False)
    total = max((e for _, _, e in items), default=0.0)
    files = []
    for it, s, e in items:
        if it['clip'] not in files:
            files.append(it['clip'])
    import letitedit.timeline.edit_script as es
    words_by, durations, skipped = {}, {}, []
    for f in files:
        try:
            durations[f] = float(es.probe(f)['duration'])
        except (OSError, ValueError, KeyError):
            durations[f] = 0.0
        try:
            ws = _cached_words(f, transcribe)
        except Exception:  # noqa: BLE001 - no audio, unreadable
            ws = None
        if ws is None:
            skipped.append(f)
        else:
            # A word aligned across a long silence is usually a transcript timing
            # artifact. Keep its start, but do not make an entire hook wait on it.
            words_by[f] = [dict(w, e=min(float(w['e']), float(w['s']) + 1.0))
                           for w in ws if str(w.get('w', '')).strip()
                           and (not durations[f] or float(w['e']) <= durations[f] + 0.05)]
    topic = {}
    for ws in words_by.values():
        for w in ws:
            n = _norm(w['w'])
            if n and n not in STOP and n not in FILLERS and len(n) > 2:
                topic[n] = topic.get(n, 0) + 1
    hook = kit.get('hook') or {}
    max_words = int((hook.get('text') or {}).get('max_words') or 6)
    case = (hook.get('text') or {}).get('case') or 'as_said'
    min_score = (0.22, 0.15, 0.08)[min(depth, 2)]
    out = []
    for f in files:
        ws = words_by.get(f)
        if not ws:
            continue
        at = {id(w): k for k, w in enumerate(ws)}
        graph, facts = _emotion(f), _facts(f)
        sentences = _sentences(ws, max_gap=4.0)
        for si, sent in enumerate(sentences):
            complete = bool(re.search(r'[.?!]["\')\]]*$', str(sent[-1]['w']).strip()))
            windows = [sent] if complete else []
            # A pause can split one complete thought in two. Keep the words together
            # when the next run finishes it, instead of offering a dangling clause.
            if not complete and si + 1 < len(sentences):
                joined = sent + sentences[si + 1]
                if (len(joined) <= 30 and float(joined[-1]['e']) - float(joined[0]['s']) <= 11
                        and re.search(r'[.?!]["\')\]]*$', str(joined[-1]['w']).strip())):
                    windows.append(joined)
            if depth >= 1 and float(sent[-1]['e']) - float(sent[0]['s']) > 8:
                # A long sentence can contain a useful, self-contained clause.
                # Only natural comma boundaries are used; arbitrary time cuts make
                # fragments that sound like a broken opening.
                windows.extend(part for part in _clauses(sent, max_s=7.5)
                               if len(part) >= 6 and str(part[-1]['w']).strip().endswith(','))
                for wi, word in enumerate(sent):
                    if _norm(word['w']) in {'without', 'while'} and wi >= 6:
                        windows.append(sent[:wi])
                        break
            for win in windows:
                a, b = float(win[0]['s']), float(win[-1]['e'])
                feat = _features(win, topic)
                if float(feat['dur']) > 11 or _norm(win[0]['w']) in {'as', 'if', 'when', 'while'}:
                    continue
                if feat['n'] < 2 and depth < 2:
                    continue
                where = _where_in_cut(items, f, a, b)
                pos = (where[1] / total) if where and total else None
                moods = _moods_at(graph, a, b)
                fa = _facts_at(facts, a, b)
                sc = _scores(feat, moods, pos, fa)
                approach = max(sc, key=sc.get)
                base = sc[approach] * _len_factor(feat['dur']) * (1 - 0.7 * feat['greeting']) \
                    * (1 - min(0.5, feat['fillers'] * 2)) + (0.08 if where else 0.0)
                if base < min_score:
                    continue
                text = _text_options(feat, approach, topic, max_words, case)
                if not text:
                    continue
                i, j = at[id(win[0])], at[id(win[-1])]
                prev_e = float(ws[i - 1]['e']) if i > 0 else 0.0
                next_s = float(ws[j + 1]['s']) if j + 1 < len(ws) else b + 1.0
                src_in = max(0.0, max(a - PAD_IN, min(a, prev_e + 0.03)))
                src_out = min(b + PAD_OUT, max(b, next_s - 0.03))
                if durations.get(f):
                    src_out = min(src_out, durations[f] - 1.0 / float((script.get('profile') or {}).get('fps', 30)))
                if src_out - src_in < 0.3:
                    continue
                out.append({
                    'approach': approach, 'label': LABELS[approach],
                    'source': {'clip': f, 'in': round(src_in, 3), 'out': round(src_out, 3)},
                    'timeline': {'start': round(where[1], 3), 'end': round(where[2], 3)} if where else None,
                    'in_cut': bool(where), 'item_id': where[0].get('id') if where else None,
                    'said': feat['text'], 'score': round(base, 3),
                    'signals': {'words_per_s': round(feat['wps'], 2), 'question': feat['question'],
                                'stakes_words': feat['stakes'], 'result_words': feat['result'],
                                'numbers': feat['numbers'], 'greeting': feat['greeting'],
                                'position_in_cut': round(pos, 3) if pos is not None else None,
                                'moods': {k: v for k, v in moods.items() if v >= 1 and k not in ('energy',
                                                                                                  'positivity')},
                                'facts': fa, 'scores': {k: round(v, 3) for k, v in sc.items()}},
                    'text': text,
                    'why': _why(approach, feat, moods, bool(where),
                                _clock(where[1]) if where else None),
                    'effects': _effects_for(items, where, f),
                })
        # moments without words that the emotion graph scored high (picture units)
        for u in (graph or {}).get('units') or []:
            if u.get('kind') != 'picture':
                continue
            sc = u.get('scores') or {}
            strength = max((float(sc.get(k, 0)) for k in MOOD_FOR['mid_action']), default=0.0) / 2
            if strength < (0.5 if depth == 0 else 0.25):
                continue
            a, b = float(u['t0']), min(float(u['t1']), float(u['t0']) + 3.0)
            where = _where_in_cut(items, f, a, b)
            nxt = next((s for s in _sentences(ws) if float(s[0]['s']) >= b), None)
            feat = _features(nxt, topic) if nxt else {'text': '', 'question': False, 'numbers': [], 'units': []}
            text = _text_options(feat, 'mid_action', topic, max_words, case) if nxt else []
            if not text:
                continue
            out.append({
                'approach': 'mid_action', 'label': LABELS['mid_action'],
                'source': {'clip': f, 'in': round(a, 3), 'out': round(b, 3)},
                'timeline': {'start': round(where[1], 3), 'end': round(where[2], 3)} if where else None,
                'in_cut': bool(where), 'item_id': where[0].get('id') if where else None, 'said': '',
                'score': round(0.6 * strength + (0.08 if where else 0), 3),
                'signals': {'moods': {k: v for k, v in sc.items() if isinstance(v, (int, float)) and v >= 1},
                            'measured': u.get('measured')},
                'text': text,
                'why': _why('mid_action', {'text': ''}, sc, bool(where), _clock(where[1]) if where else None),
                'effects': _effects_for(items, where, f),
            })
    out.sort(key=lambda c: -c['score'])
    return out, skipped


def _effects_for(items, where, clip):
    """Effects a cold-open copy of this moment should carry so it looks like the cut (blur pad, zoom, grade...)."""
    src = where[0] if where else next((it for it, s, e in items if os.path.normcase(str(it['clip']))
                                       == os.path.normcase(str(clip))), None)
    keep = []
    for e in (src or {}).get('effects') or []:
        if '"keys"' in json.dumps(e, default=str):
            continue
        if e == 'blur_pad' or (isinstance(e, dict) and set(e) & {'blur_pad', 'zoom', 'size_position', 'filter',
                                                                  'gain', 'opacity', 'ffmpeg', 'fix'}
                               and not set(e) & {'split_mute', 'keep'}):
            keep.append(e)
    return keep


def _overlap(a, b):
    if os.path.normcase(a['source']['clip']) != os.path.normcase(b['source']['clip']):
        return 0.0
    lo = max(a['source']['in'], b['source']['in'])
    hi = min(a['source']['out'], b['source']['out'])
    short = min(a['source']['out'] - a['source']['in'], b['source']['out'] - b['source']['in'])
    return max(0.0, hi - lo) / max(0.05, short)


def _diverse(pool, keep=()):
    """Best complete thoughts first, with distinct source moments and on-screen words."""
    chosen = list(keep)
    used_text = {_norm(' '.join(c.get('text') or [])) for c in chosen}
    for c in sorted(pool, key=lambda x: -x['score']):
        key = _norm(' '.join(c.get('text') or []))
        if (key and key in used_text) or any(_overlap(c, x) >= 0.3 for x in chosen):
            continue
        chosen.append(c)
        if key:
            used_text.add(key)
    return chosen[len(keep):]


def _current(script):
    items = _main_items(script, hooks=False)
    if not items:
        return None
    it, s, e = items[0]
    a = float(it['in'])
    return {'id': 'h0', 'approach': 'current', 'label': LABELS['current'],
            'source': {'clip': it['clip'], 'in': round(a, 3), 'out': round(min(float(it['out']), a + 3.0), 3)},
            'timeline': {'start': round(s, 3), 'end': round(min(e, s + 3.0), 3)}, 'in_cut': True,
            'item_id': it.get('id'), 'said': '', 'text': [], 'score': None, 'signals': {},
            'why': 'The cut as it opens now (kept so the opening can go back to it).', 'effects': [],
            'by': 'letitedit', 'status': 'current', 'order': 0}


def _key(c):
    s = c['source']
    return (f"{os.path.normcase(s['clip'])}|{float(s['in']):.2f}|{float(s['out']):.2f}|"
            f"{c['approach']}|{_norm((c.get('text') or [''])[0])}|{json.dumps(c.get('lead'), sort_keys=True)}")


def _moment_key(c):
    s = c['source']
    return (os.path.normcase(s['clip']), round(float(s['in']), 2), round(float(s['out']), 2),
            c['approach'], json.dumps(c.get('lead'), sort_keys=True))


def _variants(pool, max_words):
    """New spoken moments first, then other pictures; only a few title changes."""
    bases = _diverse(pool)
    ordered = bases + _picture_variants(bases[:6])
    for base in bases[:4]:
        claim = re.match(r'^.+? is the reason ((?:most )?people|we|you|they) (.+)\.$',
                         base.get('said', ''), re.I)
        if claim:
            question = f"Why do {claim.group(1)} {claim.group(2)}?"
            ordered.append(dict(base, approach='question', text=[question],
                                label='Question on screen',
                                why=f"The on-screen question is answered by “{base['said']}”."))
            continue
        for title in _titles_for(base, max_words):
            if _norm(title) == _norm((base.get('text') or [''])[0]):
                continue
            c = dict(base, text=[title], label=f"{base['label']} · title",
                     why=f"Opens on “{base['said']}” with the title “{title}”.")
            ordered.append(c)
    for base in bases[:2]:
        ordered.append(dict(base, text=[], label=f"{base['label']} · just the moment",
                            why=f"Opens on “{base['said']}” with no words over the picture."))
    return ordered


def _picture_variants(pool):
    """Lead with a measured picture unit or a silent shot from another take."""
    leads = []
    for clip in {c['source']['clip'] for c in pool}:
        graph = _emotion(clip) or {}
        for unit in graph.get('units') or []:
            if unit.get('kind') != 'picture':
                continue
            strength = max((float(v) for v in (unit.get('scores') or {}).values()
                            if isinstance(v, (int, float))), default=0)
            a, b = float(unit.get('t0', 0)), float(unit.get('t1', 0))
            if strength >= 1 and b - a >= 0.7:
                leads.append((strength + 2.0, {'clip': clip, 'in': round(a, 3),
                                                 'out': round(min(b, a + 1.0), 3)}))
        ws = _cached_words(clip) or []
        for left, right in zip(ws, ws[1:]):
            a, b = float(left['e']) + 0.12, float(right['s']) - 0.12
            if b - a >= 0.75:
                leads.append((min(1.0, b - a), {'clip': clip, 'in': round(a, 3),
                                                 'out': round(min(b, a + 1.0), 3)}))
    leads.sort(key=lambda row: -row[0])
    out = []
    used = set()
    for base in pool:
        lead = next((s for strength, s in leads
                     if (s['clip'] != base['source']['clip']
                         or (strength >= 2 and abs(s['in'] - base['source']['in']) > 1.5))
                     and (s['clip'], s['in']) not in used), None)
        if lead:
            used.add((lead['clip'], lead['in']))
            out.append(dict(base, lead=lead, text=[], label=f"{base['label']} · picture first",
                            why=f"Opens on a quiet shot from another take, then “{base['said']}”."))
    return out


def _look_signature(script, kit=None):
    import letitedit.timeline.edit_script as es
    kit = kit if kit is not None else es.kit_for(script)
    data = {'id': getattr(kit, 'source', script.get('look')), 'values': dict(kit),
            'references': getattr(kit, 'references', {})}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _up_to_date(old, sig, want, look_signature):
    return (bool(old) and old.get('generator') == GENERATOR and old.get('cut_sig') == sig
            and old.get('depth', 0) >= want and old.get('look_settings') == look_signature)


def build(project, refresh=False, depth=None, transcribe=False):
    """hooks.json for the project, made or brought up to date: re-scored when the cut changed (marks kept), deeper
    when asked. Returns the data (also written)."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    script = es.read(path)
    kit = es.kit_for(script)
    look_signature = _look_signature(script, kit)
    old = load(path)
    sig = cut_signature(script)
    want = depth if depth is not None else max(2, (old or {}).get('depth') or 0)
    if not refresh and _up_to_date(old, sig, want, look_signature):
        return old
    # worked out outside the lock (about a second; longer when it transcribes), then merged with what the file holds
    # by then, so marks and candidates written meanwhile (by the app or the AI) are kept
    pool, skipped = _pool(script, kit, want, transcribe)
    with locked(path):
        old = load(path)
        if not refresh and _up_to_date(old, sig, want, look_signature):
            return old
        data = _merged(path, script, kit, old, sig, want, pool, skipped)
        save(path, data)
    return data


def _merged(path, script, kit, old, sig, want, pool, skipped):
    marks = {_key(c): c for c in (old or {}).get('candidates', [])}
    ai, ai_text = [], set()
    for c in (old or {}).get('candidates', []):
        if c.get('by') in (None, 'letitedit'):
            continue
        key = _norm(' '.join(c.get('text') or []))
        if key and key in ai_text:
            continue
        ai.append(c)
        if key:
            ai_text.add(key)
    cur = _current(script)
    ordered = _variants(pool, int((kit.get('hook') or {}).get('text', {}).get('max_words') or 6))
    existing = {_key(c) for c in ai}
    ai_moments = {_moment_key(c) for c in ai}
    distinct = []
    for c in ordered:
        key = _key(c)
        if key not in existing and _moment_key(c) not in ai_moments:
            distinct.append(c)
            existing.add(key)
    ordered = distinct
    cands = []
    if cur:
        cands.append(cur)
    used = {c['id'] for c in ai}
    n = 1
    for c in ai + ordered:
        prev = marks.get(_key(c))
        if c in ai:
            cands.append(c)
            continue
        while f'h{n}' in used:
            n += 1
        c = dict(c, id=prev['id'] if prev and prev['id'] not in used else f'h{n}', by='letitedit',
                 status=(prev or {}).get('status', 'new') if (prev or {}).get('status') != 'current' else 'new')
        if prev and prev.get('preview') and prev.get('preview_key') == _preview_key(c, script, kit=kit):
            c.update(preview=prev['preview'], preview_sheet=prev.get('preview_sheet'), preview_key=prev['preview_key'])
        used.add(c['id'])
        cands.append(c)
    for k, c in enumerate(cands):
        c['order'] = k
    hook = kit.get('hook') or {}
    return {'format': FORMAT, 'generator': GENERATOR, 'project': str(path), 'made': _now(), 'cut_sig': sig,
            'look': script.get('look'), 'look_settings': _look_signature(script, kit),
            'rules': {'max_s': float(hook.get('max_s') or 3.0),
                      'max_words': int((hook.get('text') or {}).get('max_words') or 6),
                      'approaches': list(hook.get('approaches') or [])},
            'depth': want, 'applied': (old or {}).get('applied'), 'candidates': cands,
            'requests': (old or {}).get('requests', []), 'no_transcript': skipped}


def candidates(project, count=8, exclude=(), refresh=False, more=False, mark_shown=True, transcribe=False):
    """The next `count` candidates not shown yet (status 'new') and not in `exclude` (ids), in showing order; goes one
    depth deeper by itself when fewer than `count` are left (more: always one deeper). `left`: the unshown ones after
    these. mark_shown: mark the returned ones 'shown'; the app's command line and letitedit_hooks pass False (listing
    changes nothing: only mark() does), so the app's New hook still finds them as 'new' in the file."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    data = build(path, refresh=refresh, transcribe=transcribe)
    ex = set(exclude or ())
    fresh = lambda d: [c for c in d['candidates'] if c.get('status') == 'new' and c['id'] not in ex]   # noqa: E731
    if more or len(fresh(data)) < count:
        for depth in range(int(data.get('depth') or 0) + 1, 3):
            data = build(path, depth=depth, transcribe=transcribe)
            if len(fresh(data)) >= count:
                break
    unshown = fresh(data)
    picked = unshown[:max(0, int(count))]
    if mark_shown and picked:
        ids = {c['id'] for c in picked}
        with locked(path):
            data = load(path) or data
            for c in data['candidates']:
                if c['id'] in ids:
                    c['status'] = 'shown'
            save(path, data)
        picked = [dict(c, status='shown') for c in picked]
    return {'file': str(path_for(path)), 'candidates': picked, 'left': len(unshown) - len(picked),
            'depth': data.get('depth'), 'applied': data.get('applied'), 'rules': data.get('rules'),
            'no_transcript': data.get('no_transcript'),
            'current': next((c for c in data['candidates'] if c.get('approach') == 'current'), None)}


def mark(project, ids, status):
    if status not in ('new', 'shown', 'rejected', 'applied'):
        raise ValueError("status is new, shown, rejected or applied")
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    ids = set([ids] if isinstance(ids, str) else ids)
    with locked(path):
        data = load(path)
        if data is None:
            raise ValueError('no hooks.json for this project yet (letitedit_hooks makes it)')
        for c in data['candidates']:
            if c['id'] in ids:
                c['status'] = status
        if status == 'applied' and len(ids) == 1:
            data['applied'] = next(iter(ids))
        save(path, data)
    return {'file': str(path_for(path)), 'marked': sorted(ids), 'status': status}


def request_more(project, count=8, by='app'):
    """The app's 'running low' note: adds a request the AI can answer by adding candidates (by: claude | codex)."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    build(path)
    with locked(path):
        data = load(path) or build(path)
        data.setdefault('requests', []).append({'at': _now(), 'count': int(count), 'by': by})
        save(path, data)
    return {'file': str(path_for(path)), 'requests': len(data['requests'])}


def _ai_titles(project, source, count):
    """Ask the chat's selected engine in an isolated, tool-free turn; its answer is data, never code."""
    mock = os.environ.get('LETITEDIT_QA_HOOK_REFILL')
    if mock:
        return json.loads(Path(mock).read_text(encoding='utf-8-sig')), 'mock'
    import letitedit.app.ai_clis as ai_clis
    settings = ai_clis.chat_settings()      # no file until the person has changed a choice
    if not ai_clis.background_allowed(settings):
        raise RuntimeError("Background runs of your AI are off (Connect Your AI), so new openings aren't being written.")
    first = os.environ.get('LETITEDIT_HOOK_ENGINE') or settings.get('engine') or 'claude'
    prompt = ("Return only JSON: {\"titles\":[{\"source_id\":\"h1\",\"title\":\"...\"}]}. "
              f"Give up to {count} fresh, striking on-screen titles for these complete spoken thoughts. "
              "Each title is 1-6 words, made ONLY from words in that same source's 'said' line. "
              "Reorder or omit words, but do not add words, claims, numbers, or questions. "
              "Vary the title and source; avoid the existing titles. The spoken line itself opens the video.\n"
              + json.dumps(source, ensure_ascii=False))
    problem = 'No AI is set up on this PC to write new openings.'
    picked = {e: ai_clis.choice(e, 'plan', settings) for e in ('claude', 'codex')}    # a saved "auto" is Auto's plan
    commands = {'codex': lambda exe: [str(exe), 'exec', '--ephemeral', '--ignore-rules', '--skip-git-repo-check',
                                      '-s', 'read-only', '-m', picked['codex']['model'],
                                      '-c', f'model_reasoning_effort="{picked["codex"]["effort"]}"', '-'],
                # no tools, no MCP servers and none of the person's settings files (as the critic): the request is a
                # short JSON answer, and the person's own connectors would make it a 300k-token prompt; JSON output
                # carries the call's token use for the run's cost line
                'claude': lambda exe: [str(exe), '-p', '--tools', '', '--setting-sources', 'local', '--strict-mcp-config',
                                       '--no-session-persistence', '--model', picked['claude']['model'],
                                       '--effort', picked['claude']['effort'], '--output-format', 'json']}
    for engine in sorted(ai_clis.ENGINES, key=lambda e: e != first):    # the chat's AI, then the others that are here
        exe = ai_clis.find(engine, settings)
        if not exe or ai_clis.signed_in(engine, exe) is False:
            continue
        cmd = commands[engine](exe)
        if engine == 'claude':
            cmd += ai_clis.claude_instruction_args()
        try:
            model = picked[engine]['model']
            run = ai_clis.run_with_speed(cmd, engine, model, settings, input=prompt, text=True, encoding='utf-8', errors='replace',
                                 capture_output=True, timeout=180, cwd=str(Path(project).parent),
                                 env=ai_clis.child_env(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError) as e:
            problem = f'{ai_clis.NAMES[engine]} could not write new openings: {e}'
            continue
        if run.returncode:
            problem = f'{ai_clis.NAMES[engine]} could not write new openings: {run.stderr[-400:] or run.stdout[-400:]}'
            continue
        answer, used = _claude_answer(run.stdout) if engine == 'claude' else (run.stdout, None)
        record_background_call(project, 'New hook titles', engine, model, used)
        answer = answer.strip()
        if answer.startswith('```'):
            answer = re.sub(r'^```(?:json)?\s*|\s*```$', '', answer, flags=re.I)
        try:
            return json.loads(answer), engine
        except ValueError:
            problem = f'{ai_clis.NAMES[engine]} gave no usable opening titles.'
    raise RuntimeError(problem)


BACKGROUND_FILE = 'background-ai.jsonl'    # in the project's working folder; run_cost.py reads it
COST_REFRESH_S = 600                       # a cost line written this recently is written again to count a new call


def _claude_answer(stdout):
    """(the answer's text, {usage, total_cost_usd, modelUsage} or None) from `claude -p --output-format json`; any other
    output comes back as it was, with None."""
    try:
        wrapped = json.loads(stdout)
    except (TypeError, ValueError):
        return stdout or '', None
    if isinstance(wrapped, dict) and 'result' in wrapped:
        return str(wrapped.get('result') or ''), {k: wrapped[k] for k in ('usage', 'total_cost_usd', 'modelUsage')
                                                  if wrapped.get(k) is not None}
    return stdout, None


def record_background_call(project, what, engine, model, used):
    """One line in the project's working folder for its cost line (run_cost.py): a call of the person's AI outside the
    run's conversation, with its token use when the AI gave one (Claude's JSON output; Codex's plain answer has none).
    A cost line written in the last COST_REFRESH_S seconds is written again in its own process, so a call made just
    after the run ended is counted too. Never fails the call it records."""
    try:
        work = folder(project)
        work.mkdir(parents=True, exist_ok=True)
        used = used or {}
        models = [m for m in (used.get('modelUsage') or {}) if m]
        row = {'time': _now(), 'what': what, 'engine': engine, 'model': models[0] if len(models) == 1 else model,
               'usage': used.get('usage'), 'usd': used.get('total_cost_usd')}
        with open(work / BACKGROUND_FILE, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row) + '\n')
        cost = work / 'run-cost.json'
        if cost.is_file() and time.time() - cost.stat().st_mtime < COST_REFRESH_S:
            import sys
            script = Path(__file__).resolve().parents[1] / 'app' / 'run_cost.py'
            import letitedit.core.render_lock as render_lock
            render_lock.start_independent([sys.executable, str(script), '--refresh', str(work)],
                                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                          | getattr(subprocess, 'DETACHED_PROCESS', 0))
    except (OSError, TypeError, ValueError):
        pass


def refill(project, count=8):
    """Add checked AI title variants while the panel continues serving its ready queue."""
    import letitedit.timeline.edit_script as es
    path = es._resolve(project)
    data = build(path)
    ready = sum(c.get('status') == 'new' for c in data['candidates'])
    if ready >= 10:
        return {'added': 0, 'ready': ready, 'engine': None}
    source = []
    seen = set()
    for c in sorted(data['candidates'], key=lambda x: -float(x.get('score') or 0)):
        if c.get('id') == 'h0' or not c.get('said'):
            continue
        src = c['source']
        key = (src['clip'], src['in'], src['out'])
        if key in seen:
            continue
        seen.add(key)
        titles = [(x.get('text') or [''])[0] for x in data['candidates']
                  if x.get('source') == src]
        source.append({'source_id': c['id'], 'said': c['said'], 'existing_titles': titles})
    if not source:
        return {'added': 0, 'ready': ready, 'engine': None}
    answer, engine = _ai_titles(path, source[:40], count)
    proposals = answer.get('titles', []) if isinstance(answer, dict) else []
    with locked(path):
        data = load(path) or data
        by_id = {c['id']: c for c in data['candidates']}
        keys = {_key(c) for c in data['candidates']}
        n = max((int(c['id'][1:]) for c in data['candidates'] if re.fullmatch(r'h\d+', c['id'])), default=0) + 1
        added = 0
        for proposal in proposals[:count * 3]:
            if not isinstance(proposal, dict):
                continue
            base = by_id.get(str(proposal.get('source_id', '')))
            title = re.sub(r'\s+', ' ', str(proposal.get('title', '')).strip())
            if (not base or not base.get('said') or not 2 <= len(title.split()) <= 6
                    or _norm(title.split()[-1]) in {'a', 'an', 'the', 'and', 'or', 'but', 'to', 'of',
                                                     'for', 'with', 'created'}):
                continue
            said_words = Counter(_norm(w) for w in base['said'].split())
            title_words = Counter(_norm(w) for w in title.split())
            if not all(w and amount <= said_words[w] for w, amount in title_words.items()):
                continue
            c = dict(base, id=f'h{n}', text=[title], by=engine, status='new',
                     label=f"{base['label'].split(' · ')[0]} · new title",
                     why=f"Opens on “{base['said']}” with the title “{title}”.")
            if _key(c) in keys:
                continue
            c.pop('preview', None)
            c.pop('preview_sheet', None)
            c.pop('preview_key', None)
            c['order'] = len(data['candidates'])
            data['candidates'].append(c)
            keys.add(_key(c))
            n += 1
            added += 1
            if added >= count:
                break
        if added:
            save(path, data)
        ready = sum(c.get('status') == 'new' for c in data['candidates'])
    return {'added': added, 'ready': ready, 'engine': engine}


def candidate(project, cid):
    import letitedit.timeline.edit_script as es
    data = load(es._resolve(project)) or build(project)
    c = next((x for x in data['candidates'] if x['id'] == cid), None)
    if c is None:
        raise ValueError(f'no hook candidate {cid!r} in {path_for(es._resolve(project))} '
                         f'(ids: {", ".join(x["id"] for x in data["candidates"][:30])})')
    return c


def _clock(s):
    import letitedit.timeline.edit_script as es
    return es.clock(s)


# ------------------------------------------------------------------ the {op: hook} edit

def text_item(kit, text, length):
    """The on-screen hook text as a timeline item, in the pack's hook.text look (a pop-up sticker by default)."""
    look = (kit.get('hook') or {}).get('text') or {}
    tpl = look.get('item')
    if isinstance(tpl, dict):
        filled = json.loads(json.dumps(tpl).replace('{text}', json.dumps(text)[1:-1]))
        if 'graphic' in filled:
            filled['len'] = round(length, 3)
        elif 'motion' in filled and isinstance(filled['motion'], dict):
            filled['motion']['duration'] = round(length, 3)
        return filled
    import letitedit.looks.style_pack as style_pack
    x, y = style_pack.position_xy(look.get('position') or 'top')
    params = {'text': text, 'x': x, 'y': y, 'size': float(look.get('size') or 0.82), 'in': look.get('in') or 'pop',
              'out': look.get('out') or 'fade', 'in_s': 0.25, 'out_s': 0.25,
              'fill': look.get('fill') or 'secondary', 'stroke': look.get('stroke') or 'dark',
              'stroke_width': look.get('stroke_width', 12), 'font': look.get('font') or 'heading',
              'shadow': look.get('shadow', True)}
    return {'graphic': {'template': 'popup', 'params': params}, 'len': round(length, 3)}


def _remove_previous(script):
    from letitedit.timeline.edit_sync import main_track
    m = main_track(script)
    n = 0
    if m:
        keep = []
        for it in m['items']:
            if str(it.get('id', '')).startswith(HOOK_PREFIX):
                n += 1
            else:
                keep.append(it)
        m['items'] = keep
    t = next((x for x in script['tracks'] if x['name'] == TEXT_TRACK), None)
    if t:
        t['items'] = [it for it in t['items'] if not str(it.get('id', '')).startswith(HOOK_PREFIX)]
        while t['items'] and 'gap' in t['items'][-1]:
            t['items'].pop()
    return n


def apply_op(script, op):
    """{op: hook, candidate: <id> (resolved by the tool layer) | {source: {clip, in, out}, text?, effects?, timeline?},
    text?: <index into the candidate's text> | '<your own words>' | null, mode?: cold_open | start_here, len?}.
    cold_open (default): the moment goes first on the main track (an earlier hook it placed is replaced), its text
    over it on the 'Hook text' track. start_here: the cut starts at the moment (only for a moment in the cut; the
    material before it is cut, undo brings it back)."""
    import letitedit.timeline.edit_script as es
    from letitedit.timeline.edit_sync import layout, main_track
    c = op.get('candidate')
    if isinstance(c, str):
        raise ValueError(f'hook candidate {c!r} was not found: pass one from letitedit_hooks (the edit tool reads '
                         f'it from hooks.json beside the project), or the candidate itself')
    if not isinstance(c, dict) or not isinstance(c.get('source'), dict):
        raise ValueError('hook: candidate is an id from letitedit_hooks or {source: {clip, in, out}, text?}')
    kit = es.kit_for(script)
    mode = op.get('mode') or 'cold_open'
    m = main_track(script)
    if m is None:
        raise ValueError('hook: the project has no picture track')
    if c.get('approach') != 'current' and not any(
            item.get('clip') and not str(item.get('id', '')).startswith(HOOK_PREFIX) for item in m['items']):
        raise ValueError('hook: a footage opening needs footage on the main picture track. '
                         'For a generated scene video, edit its opening scene instead; nothing was changed.')
    removed = _remove_previous(script)
    if c.get('approach') == 'current':
        op['_result'] = (f"{c.get('id') or 'h0'}: back to the cut's own opening"
                         + ('' if removed else ' (no hook had been added)'))
        script.pop('hook', None)      # the cut's own opening: nothing swapped in (letitedit_ai:hook goes)
        return script
    src = c['source']
    text = op.get('text')
    if isinstance(text, bool):
        text = 0 if text else None
    # the opening now in the video, on the project itself, so Undo and Redo carry it with the picture (the app's
    # Opening panel and Versions menu read it): '<id>|<index of its words>', '<id>|none' or '<id>|custom'
    script['hook'] = f"{c.get('id') or 'custom'}|{text if isinstance(text, int) else ('none' if not text else 'custom')}"
    if isinstance(text, int):
        opts = c.get('text') or []
        if not 0 <= text < len(opts):
            raise ValueError(f'hook: text {text} is not one of the candidate\'s {len(opts)} text options')
        text = opts[text]
    note = []
    if mode == 'cold_open':
        a, b = float(src['in']), float(src['out'])
        if op.get('len'):
            b = min(b, a + float(op['len']))
        import math
        fps = float((script.get('profile') or {}).get('fps', 30))     # whole frames, so nothing drifts on a swap
        a, b = math.floor(a * fps + 1e-6) / fps, math.ceil(b * fps - 1e-6) / fps
        if b - a < 0.3:
            raise ValueError('hook: the moment is shorter than 0.3 s')
        item = {'id': f'{HOOK_PREFIX}clip', 'clip': src['clip'], 'in': round(a, 4), 'out': round(b, 4)}
        if c.get('effects'):
            item['effects'] = list(c['effects'])
        m['items'].insert(0, item)
        length = b - a
        lead = c.get('lead')
        if isinstance(lead, dict) and lead.get('clip') and float(lead.get('out', 0)) > float(lead.get('in', 0)):
            la, lb = float(lead['in']), float(lead['out'])
            la, lb = math.floor(la * fps + 1e-6) / fps, math.ceil(lb * fps - 1e-6) / fps
            m['items'].insert(0, {'id': f'{HOOK_PREFIX}lead', 'clip': lead['clip'],
                                  'in': round(la, 4), 'out': round(lb, 4), 'effects': ['mute']})
            length += lb - la
            note.append(f"starts with a picture from {os.path.basename(lead['clip'])}")
        note.append(f"opens on {os.path.basename(src['clip'])} {es.clock(a)}-{es.clock(b)} ({length:.1f} s)"
                    + (', shown again later in place' if c.get('in_cut') else ''))
    elif mode == 'start_here':
        tl = c.get('timeline')
        if not tl:
            raise ValueError('hook: start_here needs a moment that is in the cut (its timeline start)')
        start = float(tl['start'])
        if c.get('item_id'):
            hit = next(((it, s, e) for it, s, e in layout(m) if it.get('id') == c['item_id']), None)
            if hit:
                start = hit[1] + (float(src['in']) - float(hit[0]['in'])) / float(hit[0].get('speed', 1.0))
        spans = {id(it): (s, e) for it, s, e in layout(m)}
        cut, new, pos = 0, [], 0.0
        for it in m['items']:
            if 'gap' in it:
                gs, pos = pos, pos + float(es.to_seconds(it['gap']))
                if pos > start + 1e-4:
                    new.append({'gap': round(pos - max(gs, start), 4)})
                continue
            s, e = spans.get(id(it), (pos, pos))
            pos = e
            if e <= start + 1e-4:
                cut += 1
                continue
            if s < start - 1e-4 and 'clip' in it:
                it['in'] = round(float(it['in']) + (start - s) * float(it.get('speed', 1.0)), 4)
                it.pop('transition', None)
            new.append(it)
        while new and 'gap' in new[0]:
            new.pop(0)
        m['items'] = new
        length = float(op.get('len') or (kit.get('hook') or {}).get('max_s') or 3.0)
        note.append(f'starts at {es.clock(start)} of the old cut ({cut} item(s) before it cut)')
    else:
        raise ValueError("hook: mode is cold_open or start_here")
    if text:
        t = next((x for x in script['tracks'] if x['name'] == TEXT_TRACK), None)
        if t is None:
            t = {'name': TEXT_TRACK, 'kind': 'video', 'items': []}
            script['tracks'].append(t)
        it = text_item(kit, str(text), max(0.8, length))
        it['id'] = f'{HOOK_PREFIX}text'
        sub = {'op': 'insert', 'track': TEXT_TRACK, 'at': 0, 'item': it}
        es._place_at(script, sub)
        op['_pinned'] = it['id']
        note.append(f'text "{text}" on {TEXT_TRACK}')
    if removed:
        note.append('the earlier hook replaced')
    if script.get('captions'):
        note.append('captions made from speech before this change: run {op: captions, from_speech: true} again to '
                    'caption the new opening')
    op['_result'] = f"{c.get('id') or 'hook'} ({c.get('approach', 'custom')}): " + '; '.join(note)
    return script


def resolve_ops(project, changes):
    """For the tool layer: hook ops naming a candidate by id get the candidate itself from hooks.json."""
    for op in changes or []:
        if isinstance(op, dict) and op.get('op') == 'hook' and isinstance(op.get('candidate'), str):
            op['candidate'] = dict(candidate(project, op['candidate']))
    return changes


def after_apply(project, changes):
    """For the tool layer, after a successful apply: the applied candidate is marked in hooks.json."""
    for op in changes or []:
        if isinstance(op, dict) and op.get('op') == 'hook' and isinstance(op.get('candidate'), dict) \
                and op['candidate'].get('id'):
            try:
                mark(project, op['candidate']['id'], 'applied')
            except Exception:  # noqa: BLE001 - a note in a file, never a reason to fail an edit
                pass


# ------------------------------------------------------------------ previews

PREVIEW_VERSION = 3          # bump when the hook text's drawing changes, so cached previews are made again


def _wait_for_a_free_pc(timeout_s, poll_s=5.0):
    """A preview is a nicety: it joins the queue for the PC lock only when nothing holds the lock and nobody waits for it,
    so no edit, export or model job ever waits behind one that started before it."""
    import letitedit.core.render_lock as render_lock
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        i = render_lock.info()
        if (not i.get('held') or i.get('stale')) and not i.get('waiting'):
            return
        time.sleep(poll_s)
    raise TimeoutError('the PC was busy the whole time, so this preview was not made')


_RENDERING = threading.Event()      # a melt of ours is running: the watcher waits for it, so nothing is left behind


def _end_with_window(pid):
    """A helper a window started doesn't outlive it: this one queued for the PC lock and took its turn long after the window
    had closed (T90: seven leftovers held up everyone for about 80 minutes)."""
    import letitedit.core.render_lock as render_lock

    def watch():
        while render_lock.pid_alive(pid):
            time.sleep(2)
        while _RENDERING.is_set():
            time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()


def _preview_key(c, script, text=0, kit=None):
    opts = c.get('text') or []
    shown = opts[text] if isinstance(text, int) and 0 <= text < len(opts) else text
    s = json.dumps({'src': c['source'], 'lead': c.get('lead'), 'text': shown,
                    'fx': c.get('effects'), 'v': PREVIEW_VERSION,
                    'look_settings': _look_signature(script, kit) if script else None}, sort_keys=True, default=str)
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def preview(project, cid, text=0, width=360, seconds=None, timeout_s=1800):
    """A low-res MP4 of the opening with this hook (its first seconds rendered by the export engine from a scratch
    copy of the project with {op: hook} applied), under the PC render lock; cached in the project's hooks folder.
    Returns {'clip', 'sheet', 'cached', 'seconds'}."""
    import letitedit.timeline.edit_script as es
    import letitedit.core.render_lock as render_lock
    path = es._resolve(project)
    data = load(path) or build(path)
    c = next((x for x in data['candidates'] if x['id'] == cid), None)
    if c is None:
        raise ValueError(f'no hook candidate {cid!r}')
    script = es.read(path)
    key = _preview_key(c, script, text)
    out_dir = folder(path) / 'hooks'
    clip, sheet = out_dir / f'{cid}-{key}.mp4', out_dir / f'{cid}-{key}.jpg'
    if clip.exists() and sheet.exists():
        _store_preview(path, cid, clip, sheet, key)
        return {'clip': str(clip), 'sheet': str(sheet), 'cached': True}
    t0 = time.monotonic()
    work = out_dir / 'work' / f'{cid}-{key}'
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    scratch = work / Path(path).name
    shutil.copy2(path, scratch)
    op = {'op': 'hook', 'candidate': c}
    if c.get('approach') != 'current' and c.get('text') and text is not None:
        op['text'] = text
    if c.get('approach') == 'current':
        dur = float(seconds or 5.0)
    else:
        # Give the scratch copy its own graphics directory. A preview and a live
        # New hook can compile the same title at once; sharing the project's
        # temporary .mov name makes one of them fail on Windows.
        graphics_dir = work / 'graphics'
        # Its finished graphics and made clips are named by their content and don't need drawing again: without this
        # every caption of the whole video was redrawn for each preview (T59: 279 s of a 337 s preview). Links only:
        # across drives there is no link, and those are drawn as before.
        for name in ('graphics', 'made'):
            source = Path(path).parent / name
            if source.is_dir():
                (work / name).mkdir(exist_ok=True)
                for f in source.iterdir():
                    try:
                        if f.is_file():
                            os.link(f, work / name / f.name)
                    except OSError:
                        pass
        before = es.read(scratch)
        after, _ = es.edit(before, [op])
        after['base'] = before['base']
        after.pop('_frames_at', None)
        es.compile_script(after, base=scratch, out=scratch, graphics_dir=graphics_dir)
        dur = float(seconds or min(8.0, float(c['source']['out']) - float(c['source']['in']) + 2.0))
    import letitedit.review.checks as checks
    _wait_for_a_free_pc(timeout_s)
    with render_lock.slot(f'letitedit hook preview {cid}', timeout_s=timeout_s,
                          caller_pids=render_lock.ancestors()):
        _RENDERING.set()
        try:
            jpeg, info = checks.range_clip(str(scratch), 0.0, dur, width=width, strip=4)
        finally:
            _RENDERING.clear()
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(info['clip'], clip)
    sheet.write_bytes(jpeg)
    shutil.rmtree(work, ignore_errors=True)
    _store_preview(path, cid, clip, sheet, key)
    return {'clip': str(clip), 'sheet': str(sheet), 'cached': False, 'seconds': round(time.monotonic() - t0, 1)}


def _store_preview(path, cid, clip, sheet, key):
    with locked(path):
        data = load(path)
        if not data:
            return
        for c in data['candidates']:
            if c['id'] == cid:
                c.update(preview=str(clip), preview_sheet=str(sheet), preview_key=key)
        save(path, data)


# ------------------------------------------------------------------ the app's command line

def started_by_window(live):
    """True when the letitedit window that has the project open (live: a row of letitedit_instances.list_instances,
    with the editor's pid) started this process: the app's own button, not an AI session or a script."""
    import letitedit.core.render_lock as render_lock
    pid = int((live or {}).get('pid') or 0)
    return bool(pid) and pid in render_lock.ancestors()


def apply_for_person(project, op, label, from_app=False):
    """The app's hook button: the person's own edit. Open in a letitedit window: straight into that window as ONE
    native undo step named `label` (the window's revision guards against a clash; AI edit leases don't apply to the
    person, as with any edit made in the window), journalled as the person's. Not open: the saved file is changed
    (keeping an undo copy), waiting up to 30 s for an AI's edit lease.
    from_app (the app passes --from-app): the window's own button, so the swap is no AI session: it neither checks
    nor takes the window's AI ownership (an AI that edited the window keeps it). Only honoured when that window
    started this process; from anywhere else it is refused, and AI-vs-AI ownership applies as to every edit."""
    import letitedit.timeline.edit_script as es
    import letitedit.app.letitedit_instances as inst
    import letitedit.timeline.project_journal as pj
    import letitedit.server.timeline_tools as tt
    path = es._resolve(project)
    changes = tt._resolve_refs(path, [op])
    live = tt._live_state(path)
    if from_app and live and not started_by_window(live):
        raise RuntimeError(f"--from-app is for the letitedit window's own buttons, and the window that has this "
                           f"project open ({live['instance_id']}) did not start this command. An AI swaps the opening "
                           f"with letitedit_timeline_apply {{op: hook, candidate}}; nothing was changed.")
    with (inst.app_edit() if from_app and live else contextlib.nullcontext()):
        if live:
            import letitedit.app.live_edit as live_edit
            result = live_edit.apply(live['instance_id'], changes, label=label)
            result.pop('preview_project', None)
            pj.record(path, 'apply', 'person', label, result.get('changes'),
                      where=f"letitedit window {live['instance_id']}")
            tt._after_apply(path, changes)
        else:
            result, _ = tt.apply_project(path, changes, check=False, label=label, actor='person', wait_s=30)
    return {'applied': (op.get('candidate') or {}).get('id') if isinstance(op.get('candidate'), dict)
            else op.get('candidate'), 'live': bool(live), 'changes': result.get('changes'), 'notes': result.get('notes'),
            'undo_label': result.get('undo_label') or label}


def _main(argv):
    """python hooks.py next <project> [--count N] [--exclude h1,h2] | more <project> [--count N]
    | preview <project> <id> [--text N] | apply <project> <id> [--text N|--no-text] [--mode cold_open|start_here]
    [--from-app] | mark <project> <id[,id]> <status> | request <project> [--count N]   -> JSON on stdout.
    next and more list candidates without marking them (only mark changes a status); --from-app is the letitedit
    window's own button (see apply_for_person)."""
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default
    cmd = argv[0] if argv else ''
    if cmd in ('preview', 'refill') and opt('--window-pid'):     # the long ones; a quick write finishes what it started
        _end_with_window(int(opt('--window-pid')))
    if cmd in ('next', 'more') and len(argv) > 1:
        ex = [x for x in (opt('--exclude') or '').split(',') if x]
        return candidates(argv[1], count=int(opt('--count', 3)), exclude=ex, more=cmd == 'more', mark_shown=False)
    if cmd == 'preview' and len(argv) > 2:
        return preview(argv[1], argv[2], text=int(opt('--text', 0)))
    if cmd == 'apply' and len(argv) > 2:
        op = {'op': 'hook', 'candidate': argv[2], 'mode': opt('--mode', 'cold_open')}
        if '--no-text' not in argv:
            op['text'] = int(opt('--text', 0))
        return apply_for_person(argv[1], op, label=f'letitedit: opening {argv[2]}', from_app='--from-app' in argv)
    if cmd == 'mark' and len(argv) > 3:
        return mark(argv[1], argv[2].split(','), argv[3])
    if cmd == 'request' and len(argv) > 1:
        return request_more(argv[1], int(opt('--count', 8)))
    if cmd == 'refill' and len(argv) > 1:
        return refill(argv[1], int(opt('--count', 8)))
    raise SystemExit(_main.__doc__)


if __name__ == '__main__':
    import sys
    # the app reads this as UTF-8 whatever the Windows code page is (accents, other scripts, emoji in hook text)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    print(json.dumps(_main(sys.argv[1:]), ensure_ascii=False, indent=1, default=str))
