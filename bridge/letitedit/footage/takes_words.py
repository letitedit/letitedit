"""The settings, the word lists (fillers, negations, numbers) and names.

Part of `takes` (letitedit/footage/takes.py), which imports every name here back,
so `takes.X` is the same object it always was.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
import os
import re
import subprocess
import unicodedata
from pathlib import Path
import letitedit.timeline.cutpoints as cutpoints  # noqa: E402
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache')))
OUT = CACHE / 'takes'
APP = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app')))
FFMPEG = APP / 'ffmpeg.exe'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

SCHEMA_VERSION = 1
ALGO_VERSION = 1          # bump when grouping or measuring changes, so cached results are not reused
TOOL = 'letitedit_find_takes'

DEFAULTS = {
    'min_words': 4,            # matched words (in order) two lines must share to count as one passage
    'min_similarity': 0.6,     # difflib similarity of the shared region (0-1) to count as one passage
    'split_pause_s': 1.0,      # a pause this long ends a line
    'long_pause_s': 0.6,       # pauses inside a take at least this long are listed
    'retake_gap_words': 40,    # takes count as retakes when at most this many words are said between them...
    'retake_gap_s': 300.0,     # ...and at most this much recording time passes (when the files' times are known)
    'restart_gap_s': 120.0,    # a false start is followed by its full take within this much recording time
    'query_join_s': 3.0,       # script/phrase mode: lines this close together are searched as one
    'context_s': 1.0,          # previews and clips show this much before and after a take
    'min_take_s': None,        # takes shorter than this are left out
    'max_take_s': 120.0,       # takes longer than this are left out
    'max_groups': 40,          # groups returned (the full count is in the summary)
    'preview_groups': 12,      # sheets (and clips) for at most this many groups
    'frames': 3,               # frames per take on a sheet (aligned to the same words)
    'clip_height': 360,        # the short side of preview clips, px
}
MEASURES = ('text', 'delivery', 'edges', 'audio', 'noise', 'picture', 'transcript', 'speaker')
PREVIEWS = ('sheets', 'clips', 'both', 'none')
CLAIM_KINDS = ('number', 'negation', 'name', 'opposite')

# ------------------------------------------------------------------ word lists (English; see 'unsupported')

FILLERS = {'um', 'umm', 'uh', 'uhh', 'uhm', 'er', 'erm', 'ah', 'eh', 'hmm', 'hm', 'mm', 'mmm', 'mhm'}
STOP = set("""a an the and or but so of to in on at for with by from up down out off over into onto about as is are was
were be been being am it its it's this that these those there here i me my we us our you your he him his she her they
them their what which who whom whose when where why how all any both each few more most other some such only own same
than too very can will just should now do does did doing have has had having i'm i've i'll i'd you're you've you'll
we're we've we'll they're that's there's here's what's let's if then else also yeah yes okay oh well like right got
get go going one gotta want kind sort thing things""".split())
DISCOURSE = {'so', 'and', 'but', 'okay', 'all', 'right', 'well', 'yeah', 'yes', 'now', 'then', 'oh', 'hey', 'anyway',
             'anyways', 'alright'}
NEGATIONS = {'not', 'no', 'never', 'none', 'nothing', 'nobody', 'nowhere', 'neither', 'nor', 'cannot', 'without',
             'dont', 'doesnt', 'didnt', 'isnt', 'arent', 'wasnt', 'werent', 'wont', 'wouldnt', 'cant', 'couldnt',
             'shouldnt', 'havent', 'hasnt', 'hadnt', 'aint', 'mustnt', 'neednt'}
_OPPOSITE_PAIRS = """left/right up/down on/off in/out open/closed open/close opened/closed tighten/loosen tight/loose
tightened/loosened tightening/loosening before/after more/less hot/cold warm/cool warmer/cooler start/stop
started/stopped always/never increase/decrease increased/decreased high/low higher/lower positive/negative true/false
add/remove added/removed push/pull front/back inside/outside first/last top/bottom plus/minus max/min
maximum/minimum forward/backward forwards/backwards clockwise/counterclockwise big/small bigger/smaller long/short
longer/shorter early/late good/bad better/worse best/worst fast/slow faster/slower easy/hard easier/harder
cheap/expensive full/empty wet/dry enable/disable enabled/disabled connect/disconnect connected/disconnected
plug/unplug plugged/unplugged lock/unlock locked/unlocked install/uninstall installed/uninstalled north/south
east/west above/below over/under heavy/light thick/thin wide/narrow lefty/righty win/lose""".split()
OPPOSITE = {}
for _p in _OPPOSITE_PAIRS:
    _a, _b = _p.split('/')
    OPPOSITE.setdefault(_a, set()).add(_b)
    OPPOSITE.setdefault(_b, set()).add(_a)
CANON = {'gonna': ('going', 'to'), 'wanna': ('want', 'to'), 'gotta': ('got', 'to'), 'alright': ('all', 'right'),
         'ok': ('okay',), 'kinda': ('kind', 'of'), 'sorta': ('sort', 'of'), 'lemme': ('let', 'me'),
         'cuz': ('because',), 'coz': ('because',), 'yep': ('yeah',), 'yup': ('yeah',), 'yea': ('yeah',),
         'nope': ('no',), 'nah': ('no',)}
ONES = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9}
TEENS = {'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
         'seventeen': 17, 'eighteen': 18, 'nineteen': 19}
TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
BIG = {'thousand': 1000, 'million': 10 ** 6, 'billion': 10 ** 9}
NUMWORDS = set(ONES) | set(TEENS) | set(TENS) | {'hundred'} | set(BIG)
ORDINALS = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5, 'sixth': 6, 'seventh': 7, 'eighth': 8,
            'ninth': 9, 'tenth': 10, 'eleventh': 11, 'twelfth': 12, 'thirteenth': 13, 'fourteenth': 14,
            'fifteenth': 15, 'sixteenth': 16, 'seventeenth': 17, 'eighteenth': 18, 'nineteenth': 19,
            'twentieth': 20, 'thirtieth': 30, 'fortieth': 40, 'fiftieth': 50, 'hundredth': 100}
ORD_WORD = {str(v): k for k, v in ORDINALS.items()}
ORD_BEFORE = {'the', 'my', 'our', 'your', 'his', 'her', 'their', 'its', 'every', 'each'}   # 'the second' = 2nd
FRACTIONS = {'half': '0.5', 'quarter': '0.25'}
PRONOUN_I = {'i', "i'm", "i've", "i'll", "i'd"}
DOUBLES = {'bang', 'boom', 'very', 'no', 'yeah', 'yes', 'bye', 'ha', 'knock', 'tick', 'beep', 'really', 'well',
           'go', 'come', 'hey', 'okay'}
_PUNCT_EDGE = ' \t.,!?;:"\'()[]{}<>\u2026-\u2014\u2013_*/\\\u00bf\u00a1\u300c\u300d\u3002\u3001\uff0c\uff01\uff1f'
_NUM = re.compile(r'^[$\u20ac\u00a3\u00a5\u20b9]?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%|[a-z]{1,4})?$')
_ISNUM = re.compile(r'^\d+(?:\.\d+)?$')
_CLOCK = re.compile(r'^\d{1,2}:\d{2}$')
ORD_SUFFIX = {'st', 'nd', 'rd', 'th'}


def _nospace(ch):
    """True for characters of scripts written without spaces between words (Chinese, Japanese, Thai, Lao, Khmer,
    Myanmar): those are compared one character at a time."""
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0x20000 <= o <= 0x2FFFF or 0x0E00 <= o <= 0x0EFF or 0x1780 <= o <= 0x17FF or 0x1000 <= o <= 0x109F)


def _fmt_num(v):
    v = float(v)
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f'{v:g}'


def _norm_word(raw):
    """The comparison tokens of one transcript word: usually one; a number with a unit or %, a hyphenated pair or a
    word in a script without spaces gives several; punctuation alone gives none. Unicode-aware."""
    s = unicodedata.normalize('NFKC', str(raw)).lower().replace('\u2019', "'").strip()
    core = s.strip(_PUNCT_EDGE)
    if not core:
        return []
    if _CLOCK.match(core):
        return [core]
    m = _NUM.match(core)
    if m:
        num = _fmt_num(m.group(1).replace(',', '') + ('.' + m.group(2) if m.group(2) else ''))
        suf = m.group(3) or ''
        if suf in ORD_SUFFIX:
            return [ORD_WORD.get(num, num + 'th')]
        if suf == '%':
            return [num, 'percent']
        return [num] + ([suf] if suf else [])
    if '-' in core:
        parts = [p for p in core.split('-') if p]
        if len(parts) > 1 and all(len(p) >= 2 for p in parts):
            return [t for p in parts for t in _norm_word(p)]
    tok = cutpoints._tok(core)
    if not tok:
        return []
    if tok in CANON:
        return list(CANON[tok])
    if any(_nospace(c) for c in tok):
        out, run = [], ''
        for c in tok:
            if _nospace(c):
                if run:
                    out.append(run)
                    run = ''
                out.append(c)
            else:
                run += c
        return out + ([run] if run else [])
    return [tok]


def _is_filler(raw):
    return cutpoints._tok(raw) in FILLERS


def _number_run(toks, i):
    """(canonical number, end index) for number words starting at toks[i] ('twenty five' -> '25', 'a hundred and
    five' -> '105', 'two point five' -> '2.5', '5 hundred' -> '500'), or None. A lone 'one' stays a word."""
    n = len(toks)
    t = toks[i]
    if _ISNUM.match(t):
        if i + 1 < n and (toks[i + 1] == 'hundred' or toks[i + 1] in BIG):
            return _fmt_num(float(t) * (100 if toks[i + 1] == 'hundred' else BIG[toks[i + 1]])), i + 2
        return None
    if t in ('a', 'an') and i + 1 < n and (toks[i + 1] == 'hundred' or toks[i + 1] in BIG):
        total, current, last, j = 0, 1, 'unit', i + 1
    elif t in NUMWORDS:
        total, current, last, j = 0, 0, None, i
    else:
        return None
    while j < n:
        w = toks[j]
        if w in ONES:
            if last in ('unit', 'teen'):
                break
            current += ONES[w]
            last = 'unit'
        elif w in TEENS:
            if last in ('unit', 'teen', 'tens'):
                break
            current += TEENS[w]
            last = 'teen'
        elif w in TENS:
            if last in ('unit', 'teen', 'tens'):
                break
            current += TENS[w]
            last = 'tens'
        elif w == 'hundred':
            if last in (None, 'hundred'):
                break
            current = (current or 1) * 100
            last = 'hundred'
        elif w in BIG:
            if last is None:
                break
            total += (current or 1) * BIG[w]
            current = 0
            last = 'big'
        elif w == 'and' and last in ('hundred', 'big') and j + 1 < n and (toks[j + 1] in ONES or toks[j + 1] in TEENS
                                                                         or toks[j + 1] in TENS):
            j += 1
            continue
        elif w == 'point' and last in ('unit', 'teen', 'tens', 'hundred', 'big') and j + 1 < n and toks[j + 1] in ONES:
            digits, k = [], j + 1
            while k < n and toks[k] in ONES:
                digits.append(str(ONES[toks[k]]))
                k += 1
            return _fmt_num(total + current + float('0.' + ''.join(digits))), k
        else:
            break
        j += 1
    if j <= i or (t in ('a', 'an') and j == i + 1 and last == 'unit'):
        return None
    if toks[i:j] == ['one']:
        return None
    return _fmt_num(total + current), j


def _number_pass(toks, tw):
    """Number-word runs replaced by one numeric token. Returns (tokens, first word index, last word index)."""
    out, w0s, w1s = [], [], []
    i, n = 0, len(toks)
    while i < n:
        got = _number_run(toks, i)
        if got:
            val, j = got
            out.append(val)
            w0s.append(tw[i])
            w1s.append(tw[j - 1])
            i = j
            continue
        out.append(toks[i])
        w0s.append(tw[i])
        w1s.append(tw[i])
        i += 1
    return out, w0s, w1s


def tokenize(ws, w0=0, w1=None):
    """Comparison tokens of words ws[w0:w1]: (tokens, first word index per token, last word index per token)."""
    w1 = len(ws) if w1 is None else w1
    toks, tw = [], []
    for k in range(w0, w1):
        raw = ws[k]['w']
        if _is_filler(raw):
            continue
        for t in _norm_word(raw):
            toks.append(t)
            tw.append(k)
    return _number_pass(toks, tw)


def _content(t):
    return bool(t) and t not in STOP and t not in FILLERS and (len(t) >= 2 or t.isdigit() or _nospace(t[0]))


def _num_value(t, prev):
    if _ISNUM.match(t) or _CLOCK.match(t):
        return t
    if t in ORDINALS and (t != 'second' or prev in ORD_BEFORE):
        return f'#{ORDINALS[t]}'
    if t.endswith('th') and t[:-2].isdigit():
        return f'#{t[:-2]}'
    if t in FRACTIONS:
        return FRACTIONS[t]
    return None


def _is_neg(t):
    return t in NEGATIONS or t.endswith("n't")


# ------------------------------------------------------------------ names

def _lower_seen(docs):
    seen = set()
    for d in docs:
        for w in d.ws:
            raw = str(w['w']).strip(_PUNCT_EDGE)
            if raw[:1].islower():
                seen.add(cutpoints._tok(raw))
    return seen


def name_mask(ws, names=(), lower_seen=frozenset()):
    """For each word, True when it reads as a name or identifier: a name you passed, letters mixed with digits
    (R22), an acronym (AC), or a capitalised word mid-sentence (at a sentence start only when the word is never
    written in lowercase in these transcripts). Scripts without letter case have no names found this way."""
    user = {cutpoints._tok(n) for x in (names or ()) for n in str(x).split()}
    out = []
    for k, w in enumerate(ws):
        raw = unicodedata.normalize('NFKC', str(w['w'])).strip()
        letters = raw.strip(_PUNCT_EDGE)
        low = cutpoints._tok(letters)
        hit = False
        if low:
            if low in user:
                hit = True
            elif re.search(r'\d', letters) and re.search(r'[^\W\d_]', letters) and not _NUM.match(letters.lower()):
                hit = True
            elif len(letters) >= 2 and letters.isalpha() and letters.isupper() and low not in ('ok', 'i'):
                hit = True
            elif letters[:1].isupper() and low not in PRONOUN_I:
                prev = ws[k - 1] if k else None
                initial = (prev is None or str(prev['w']).rstrip()[-1:] in '.?!'
                           or float(w['s']) - float(prev['e']) >= 0.7)
                if not initial:
                    hit = True
                elif low not in lower_seen and low not in STOP and low not in DISCOURSE:
                    hit = True
        out.append(hit)
    return out
