"""Words and break points: what may end a line, what must stay together, words run together.

Part of `caption_layout` (letitedit/pictures/caption_layout.py), which imports every name here back,
so `caption_layout.X` is the same object it always was.
"""
from __future__ import annotations
import re


# ============================================================================ words and break points

ARTICLES = {'a', 'an', 'the', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'this', 'these', 'those', 'some',
            'any', 'each', 'every', 'no'}
PREPS = {'of', 'to', 'in', 'on', 'at', 'for', 'from', 'with', 'by', 'into', 'onto', 'about', 'over', 'under',
         'through', 'between', 'without', 'within', 'off', 'per', 'via', 'than', 'as'}
CONJ = {'and', 'but', 'or', 'so', 'because', 'then', 'if', 'when', 'while', 'although', 'though', 'since', 'until',
        'unless', 'which', 'who', 'where', 'whether', 'nor', 'yet', 'after', 'before', 'once'}
UNITS = {'percent', '%', 'volt', 'volts', 'amp', 'amps', 'inch', 'inches', 'foot', 'feet', 'ft', 'mm', 'cm', 'm', 'km',
         'mile', 'miles', 'mph', 'kph', 'buck', 'bucks', 'dollar', 'dollars', 'cent', 'cents', 'minute', 'minutes',
         'min', 'second', 'seconds', 'sec', 'hour', 'hours', 'hrs', 'day', 'days', 'week', 'weeks', 'year', 'years',
         'degree', 'degrees', 'psi', 'lb', 'lbs', 'pound', 'pounds', 'kg', 'g', 'watt', 'watts', 'w', 'v',
         'gallon', 'gallons', 'liter', 'liters', 'litre', 'litres', 'btu', 'rpm', 'k', 'grand', 'times', 'x'}
PRONOUN_I = {'i', "i'm", "i've", "i'll", "i'd"}
SUBJECTS = {'i', 'you', 'we', 'they', 'he', 'she', 'it', 'there', 'who'}
NAME_JOINERS = {'with', 'of', 'and', '&', 'de', 'la', 'le', 'van', 'von', 'der', 'del', 'da', 'the', 'on'}
ABBREV = {'mr.', 'mrs.', 'ms.', 'dr.', 'st.', 'vs.', 'etc.', 'e.g.', 'i.e.', 'u.s.', 'no.', 'approx.'}
# words that are capitalised mid-line only because a sentence starts there ("it Without hitting": a lost full stop)
COMMON_WORDS = set("""a about after again all alright also am an and another any anyway are around as at back be
because been before being both but by can could did do does doing done down each else even ever every everything
first for from get gets getting go goes going gonna good got gotta had has have having here how however i if in into
is it its it's just keep kind know last let let's like look looks maybe me more most much must my need never new
next no not now of off ok okay on once one only or other our out over pretty probably put really right same see
should so some something still such sure take than thank thanks that that's the their them then there there's these
they they're thing things think this those though through time to today too try turn um uh under up us very
was way we we're well were what what's when where which while who why will with without would yeah yes yet you
you're your actually basically obviously finally anyway alright hey oh wow nope yep stuck start started stop
stopped spin turned turns hear heard hearing see saw seen check checking fix fixed fixing went came come comes""".split())
CAMEL_OK = {'iphone', 'ipad', 'ipod', 'imac', 'youtube', 'tiktok', 'ebay', 'ios', 'macos', 'mcdonald', "mcdonald's",
            'playstation', 'powerpoint', 'javascript', 'gopro', 'wifi', 'dewalt', 'linkedin', 'facebook', 'instagram',
            'openai', 'chatgpt', 'airbnb', 'airpods', 'macbook', 'whatsapp', 'paypal', 'onedrive', 'github'}


def norm(tok):
    """A word for matching: lower case, curly quotes straightened, punctuation at either end removed."""
    t = str(tok).lower().strip().replace('’', "'").replace('‘', "'")
    t = re.sub(r"^[^\w$€£#@%]+", '', t)
    t = re.sub(r"[^\w%°]+$", '', t)
    return t


def _core(tok):
    return re.sub(r"[\"'“”‘’)\]]+$", '', str(tok))


def sentence_end(tok):
    t = _core(tok)
    return t.endswith(('.', '?', '!', '…')) and t.lower() not in ABBREV


def clause_end(tok):
    return _core(tok).endswith((',', ';', ':', '—', '–'))


def capitalised(tok):
    t = re.sub(r"^[^\w]+", '', str(tok))
    return bool(t) and t[0].isupper() and norm(tok) not in PRONOUN_I


def numeric(tok):
    t = str(tok).strip().strip('.,;:!?')
    return bool(re.fullmatch(r"[\$€£#~±+-]?\d[\d.,:/x×%°-]*(st|nd|rd|th|k|m|s|mm|cm|in|ft|v|a|w)?", t, re.I))


def lost_stop(a, b, vocab=None):
    """True when b starts a sentence whose full stop was lost: a common word capitalised right after a word that
    ends in a small letter ("it Without", "hearing Stuck"). Names ("it's Alex") are not common words."""
    na, nb = norm(a), norm(b)
    if not capitalised(b) or not str(a)[-1:].isalpha() or not str(a)[-1:].islower():
        return False
    if na in ARTICLES | PREPS | CONJ:
        return False
    return nb in COMMON_WORDS or bool(vocab and nb in vocab)


def break_cost(a, b, gap_s=None, vocab=None):
    """What a break between word a and word b costs (lower is a better place; negative: a good place). Sentence and
    clause ends, pauses and conjunctions are good places; after an article or preposition, inside a name (two
    capitalised words) or between a number and its unit are bad."""
    na, nb = norm(a), norm(b)
    c = 0.0
    if sentence_end(a):
        c -= 2.5
    elif clause_end(a):
        c -= 1.2
    if gap_s is not None:
        c -= 2.0 if gap_s >= 0.7 else 1.0 if gap_s >= 0.35 else 0.0
    if not sentence_end(a) and not clause_end(a):
        if na in ARTICLES:
            c += 2.5
        elif na in PREPS:
            c += 1.2
        elif na in CONJ:
            c += 0.6
        elif na in SUBJECTS and not capitalised(b):
            c += 1.0                                         # "you | hear that": the subject leaves its verb
        if nb in CONJ:
            c -= 0.6
        elif nb in PREPS:
            c -= 0.3
        if capitalised(a) and capitalised(b) and not lost_stop(a, b, vocab):
            c += 3.0                                         # a name: Alex Rivera, Golden Gate
        elif lost_stop(a, b, vocab):
            c -= 1.8                                         # "it Without": a sentence that lost its full stop
        if numeric(a) and (nb in UNITS or numeric(b)):
            c += 3.0                                         # 12 volts, 3/8 inch
        if str(a).strip() in ('$', '€', '£', '#') or (numeric(b) and na in ('about', 'like', 'over', 'under', 'only')):
            c += 1.5
    return c


def name_spans(tokens):
    """Break positions inside names joined by a small word ('Statue of Liberty', 'Bank of America')."""
    out = set()
    for i in range(len(tokens) - 2):
        a, j, b = tokens[i], tokens[i + 1], tokens[i + 2]
        if capitalised(a) and not sentence_end(a) and not clause_end(a) and norm(j) in NAME_JOINERS \
                and str(j)[:1].islower() and capitalised(b) and not lost_stop(j, b):
            out.update((i + 1, i + 2))
    return out


def keep_together_spans(tokens, phrases):
    """Break positions k (between tokens[k-1] and tokens[k]) that fall inside one of the phrases, or inside a name
    joined by a small word."""
    out = name_spans(tokens)
    nt = [norm(t) for t in tokens]
    for ph in phrases or []:
        pw = [norm(x) for x in str(ph).split() if norm(x)]
        if len(pw) < 2:
            continue
        for i in range(len(nt) - len(pw) + 1):
            if nt[i:i + len(pw)] == pw:
                out.update(range(i + 1, i + len(pw)))
    return out


def suspected_join(tok):
    """True for a token that looks like two words that lost the space between them ('itWithout', 'wall.Then')."""
    t = str(tok).strip()
    if norm(t) in CAMEL_OK or re.search(r'https?:|www\.|@|\.(com|org|net|io)\b', t, re.I):
        return False
    core = re.sub(r"^[^\w]+|[^\w]+$", '', t)
    if re.fullmatch(r'[a-z]{2,}[A-Z][a-z]+', core):
        return True
    return bool(re.search(r'[a-z]{2,}[.?!,;][A-Za-z]{2,}', core)) and not re.fullmatch(r'([a-zA-Z]\.)+[a-zA-Z]?', core)


def vocab_lower(tokens):
    """Words seen in small letters mid-sentence: their capitalised form elsewhere is a sentence start."""
    return {norm(t) for t in tokens if str(t)[:1].islower()}
