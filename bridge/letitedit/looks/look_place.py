"""Where a learned Look sits in letitedit, the format it follows and what it needs from a new video; the fit check.

A reference is a look and a format. Learn writes a `place` (letitedit-look-place/1) with the Look: the general pattern
(never the reference's subject) and the range of content it could dress, the kinds of video (Styles) it fits, Short
or long, Look or Theme, the format's sections with what each needs, what the footage and the words must supply, and
which devices are the style and which are content-shaped. Everything here is local and measured: no AI runs.

    validate(place, known_styles=None, reference_names=())  -> the checked place
    measure(paths=None, words=None, seconds=None, footage=None, transcribe=False) -> what a video or clips supply
    fit(place, measured)        -> {fit: fits|partly|no|unknown, line, found, missing, unchecked, sections}
    plan_check(place, plan)     -> problems with a first cut's format plan (story_plan.json's `format`)
    python look_place.py fit --look <id | place.json> <clips or folder...> [--transcribe] [--budget 4]
    python look_place.py measure <video...>
Each command prints one JSON line.
"""
from __future__ import annotations

import json
import copy
import math
import re
import sys
from pathlib import Path

FORMAT = 'letitedit-look-place/1'
FOOTAGE_KINDS = ('talking-head', 'conversation', 'activity', 'screen', 'none')
FOOTAGE_WORDS = {'talking-head': 'one person talking to the camera', 'conversation': 'two or more people talking',
                 'activity': 'action or activity', 'screen': 'a screen recording', 'none': 'no footage (made pictures)'}
SPEECH = ('needed', 'optional', 'none')
QUIET_TALK = 0.4   # a format without speech: clips that talk this share of the time or more don't fit it as filmed

# What the fit check can count on any video's words or footage. The categories of video are never a fixed list
# (Learn names them from the video); these are only the measures a need can point at.
SIGNALS = {
    'list_items': ('a list of {n} items', 'items said one after another: "first", "number two", "another one", '
                   'a count announced ("five things"), or named things each given a verdict'),
    'named_things': ('{n} named things', 'distinct names said: products, apps, books, people, places, brands'),
    'numbers': ('{n} numbers', 'figures said: prices, counts, years, percentages'),
    'questions': ('{n} questions', 'questions asked out loud'),
    'steps': ('{n} steps', 'instructions said one after another ("open", "add", "then you", "step two")'),
    'groups': ('{n} group names said for the items', 'the same few verdict or group words given to several items '
               '("skip", "read", "study")'),
    'contrast': ('{n} before-and-after or then-and-now contrasts', 'a then/now, before/after, old/new or instead-of'),
    'story': ('{n} story moments', 'things told as they happened ("I was", "one day", "so I", "years ago")'),
    'cta': ('{n} calls to action', 'an ask of the viewer: follow, subscribe, sign up, comment, join, link'),
    'talk': ('talk {n:.0%} of the time', 'the share of the time someone talks'),
    'words': ('{n} words said', 'how many words are said'),
    'people': ('{n} people', 'how many people the footage shows talking (from the faces)'),
}
SIGNAL_IDS = tuple(SIGNALS) + ('ai',)
TEXT_FIELDS_LIMIT = 60

_NUMBER_WORDS = ('two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
                 'seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand '
                 'million billion percent dozen half').split()
_COUNT_NOUNS = ('things tips ways reasons books mistakes steps rules habits signs lessons tools apps ideas questions '
                'secrets hacks facts products places types kinds levels stages options myths lies truths items '
                'foods exercises moves tricks features changes problems red flags truths movies games songs').split()
_ORDINALS = ('first|firstly|second|secondly|third|thirdly|fourth|fifth|sixth|seventh|eighth|ninth|tenth|'
             'next|lastly|finally')
_SMALL = {'of', 'to', 'and', 'the', 'a', 'an', 'for', 'in', 'on', '&', 'de', 'von', 'van'}
_NOT_NAMES = {'i', "i'm", "i've", "i'd", "i'll", 'ok', 'okay', 'oh', 'um', 'uh', 'yes', 'no', 'yeah', 'hey', 'hi'}
_STOP = set(("a an the and or but so if then than that this these those it its it's is are was were be been being "
             "to of in on at for with by from up down out over under again further once here there when where why "
             "how all any both each few more most other some such only own same too very can will just don't "
             "should now you your yours he him his she her they them their we us our me my mine what which who whom "
             "i do does did doing have has had having not no yes yeah okay ok oh um uh like really well also even "
             "about into through during before after above below off get got go going thank thanks please much "
             "many one ones as because since while although though until unless whether").split())
_IMPERATIVE = set(('add open click take put go make use press cut pour mix turn set place select choose type drag '
                   'drop start stop grab hold pull push find check write draw film record upload download install '
                   'run save copy paste move apply remove try tap swipe connect plug fill heat bake boil stir fold '
                   'slice chop measure sand screw drill glue paint wipe wash rinse season flip clamp tighten loosen '
                   'attach insert enter paste export import drag').split())
_CONTRAST_PAIRS = (('before', 'after'), ('old', 'new'), ('then', 'now'), ('past', 'now'), ('used to', 'now'),
                   ('worst', 'best'), ('wrong', 'right'))
_CONTRAST_PHRASES = ('instead of', 'versus', ' vs ', 'compared to', 'but now', 'in the past', 'used to',
                     'turns out', 'rather than')
_STORY = ('i was', 'we were', 'one day', 'when i was', 'i remember', 'yesterday', 'last week', 'last year',
          'last month', 'last night', 'years ago', 'i decided', 'so i ', 'then i ', 'i went', 'we went',
          'i realized', 'i started', 'i tried', 'i found', 'i ended up', 'this morning')
_CTA = ('subscribe', 'follow me', 'follow for', 'follow along', 'sign up', 'link in', 'in the description',
        'comment', 'join the', 'join us', 'download', 'check out', 'hit the', 'share this', 'dm me',
        'click the link', 'pre-order', 'preorder', 'buy now', 'get yours', 'book a call', 'save this',
        'let me know', 'support me')


# ---------------------------------------------------------------------------- the saved place

def _text(value, label, low=1, high=TEXT_FIELDS_LIMIT):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'place {label} must be nonempty plain words')
    words = len(value.split())
    if not low <= words <= high:
        raise ValueError(f'place {label}: {words} words; keep it to {low}-{high}')
    return ' '.join(value.split())


def _pair(value, label, whole=False, minimum=0):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)
            or not minimum <= value[0] <= value[1]):
        raise ValueError(f'place {label} must be [minimum, maximum] with {minimum} <= minimum <= maximum')
    if whole and any(int(item) != item for item in value):
        raise ValueError(f'place {label} counts whole occurrences')
    return [int(item) if whole else float(item) for item in value]


def _slug(value):
    return re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-')[:48]


def _names_in(text, names):
    """The names said in the reference that `text` repeats: a whole name, or the first two words of a longer one."""
    lowered = ' ' + ' '.join(re.sub(r'[^a-z0-9 ]+', ' ', text.lower()).split()) + ' '
    out = set()
    for name in names:
        words = name.split()
        if len(name) > 2 and (f' {name} ' in lowered or (len(words) > 2 and f' {words[0]} {words[1]} ' in lowered)):
            out.add(name)
    return sorted(out)


def _check_styles(place, out, known_styles, reference_names):
    """The kinds of video it fits: known Style ids, or new Styles whose titles are general words."""
    styles = place.get('styles')
    if not isinstance(styles, list) or not 1 <= len(styles) <= 6:
        raise ValueError('place styles lists the kinds of video it fits (1-6), its main one first')
    known = dict(known_styles or {})
    titles = {str(title).lower(): identity for identity, title in known.items()}
    out['styles'] = []
    for style in styles:
        if isinstance(style, str):
            if known_styles is not None and style not in known:
                raise ValueError(f'place style {style} is not a Style; reuse one of {", ".join(sorted(known))} '
                                 'or give a new one as {"new": {"title", "filmed", "blurb"}}')
            out['styles'].append(style)
            continue
        new = style.get('new') if isinstance(style, dict) else None
        if not isinstance(new, dict) or set(new) - {'title', 'filmed', 'blurb'}:
            raise ValueError('a new Style is {"new": {"title", "filmed", "blurb"}}')
        title = _text(new.get('title'), 'new Style title', 1, 5)
        if title.lower() in titles:
            out['styles'].append(titles[title.lower()])
            continue
        clash = _names_in(title, reference_names)
        if clash:
            raise ValueError(f'new Style title "{title}" names the reference\'s subject ({", ".join(clash)}); '
                             'name the kind of video in general words')
        out['styles'].append({'new': {'title': title, 'filmed': _text(new.get('filmed'), 'new Style filmed', 2, 16),
                                      'blurb': _text(new.get('blurb'), 'new Style blurb', 3, 30)}})


def _check_footage(place, out):
    """The footage the format needs: its kinds, its speech, how many people and what it shows."""
    footage = place.get('footage')
    if not isinstance(footage, dict) or set(footage) - {'kinds', 'speech', 'people', 'what'}:
        raise ValueError('place footage is {kinds, speech, people?, what}')
    kinds = footage.get('kinds')
    if not isinstance(kinds, list) or not kinds or any(kind not in FOOTAGE_KINDS for kind in kinds):
        raise ValueError(f'place footage kinds are some of {", ".join(FOOTAGE_KINDS)}')
    if footage.get('speech') not in SPEECH:
        raise ValueError('place footage speech is needed, optional or none')
    out['footage'] = {'kinds': list(dict.fromkeys(kinds)), 'speech': footage['speech'],
                      'what': _text(footage.get('what'), 'footage what (the footage it needs, plain words)', 3, 40)}
    if footage.get('people') is not None:
        out['footage']['people'] = _pair(footage['people'], 'footage people', whole=True)


def _check_needs(place, out):
    """What the words or pictures must supply, each with its measure and limits."""
    needs = place.get('needs', [])
    if not isinstance(needs, list) or len(needs) > 16:
        raise ValueError('place needs is a list of up to 16 things the words or pictures must supply')
    out['needs'] = []
    for need in needs:
        if not isinstance(need, dict) or set(need) - {'id', 'what', 'signal', 'min', 'max', 'must', 'why',
                                                     'kind', 'without'}:
            raise ValueError('a need is {id, what, signal, min, max?, must, why, kind?, without?}')
        identity = need.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', identity):
            raise ValueError('a need id is lowercase words with hyphens')
        if need.get('signal') not in SIGNAL_IDS:
            raise ValueError(f'need {identity}: signal is one of {", ".join(SIGNAL_IDS)} ("ai" when no measure fits: '
                             'the AI checks it during the cut)')
        entry = {'id': identity, 'what': _text(need.get('what'), f'need {identity} what', 2, 24),
                 'signal': need['signal'], 'must': need.get('must') is True,
                 'why': _text(need.get('why'), f'need {identity} why', 2, 30)}
        if 'kind' in need:
            if need['kind'] not in ('content', 'format'):
                raise ValueError(f'need {identity}: kind is content or format')
            entry['kind'] = need['kind']
        if 'without' in need or need.get('kind') == 'content':
            entry['without'] = _text(need.get('without'), f'need {identity} without', 3, 40)
        if need.get('kind') == 'content':
            entry['must'] = False
        if need['signal'] != 'ai':
            minimum = need.get('min')
            if type(minimum) not in (int, float) or not math.isfinite(minimum) or minimum < 0:
                raise ValueError(f'need {identity}: min is the smallest measured value that meets it')
            entry['min'] = minimum
            if need.get('max') is not None:
                if type(need['max']) not in (int, float) or need['max'] < minimum:
                    raise ValueError(f'need {identity}: max is at least min')
                entry['max'] = need['max']
        out['needs'].append(entry)
    if len({need['id'] for need in out['needs']}) != len(out['needs']):
        raise ValueError('need ids are unique')


def _check_structure(place, out):
    """The arc, opening, ending and sections in order, each section using needs from the place."""
    need_ids = {need['id'] for need in out['needs']}
    structure = place.get('structure')
    if not isinstance(structure, dict) or set(structure) - {'arc', 'opening', 'ending', 'sections', 'chapters'}:
        raise ValueError('place structure is {arc, opening, ending, sections, chapters?}')
    sections = structure.get('sections')
    if not isinstance(sections, list) or not 1 <= len(sections) <= 16:
        raise ValueError('place structure sections lists 1-16 sections in order')
    out['structure'] = {'arc': _text(structure.get('arc'), 'structure arc', 3, 40),
                        'opening': _text(structure.get('opening'), 'structure opening', 3, 40),
                        'ending': _text(structure.get('ending'), 'structure ending', 3, 40), 'sections': []}
    if structure.get('chapters') is not None:
        out['structure']['chapters'] = _text(structure['chapters'], 'structure chapters', 3, 40)
    for section in sections:
        if not isinstance(section, dict) or set(section) - {'id', 'job', 'does', 'needs', 'seconds', 'repeats',
                                                             'optional'}:
            raise ValueError('a section is {id, job, does, needs, seconds, repeats, optional}')
        identity = section.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', identity):
            raise ValueError('a section id is lowercase words with hyphens')
        uses_needs = section.get('needs', [])
        if not isinstance(uses_needs, list) or set(uses_needs) - need_ids:
            raise ValueError(f'section {identity}: needs are ids from the place needs')
        out['structure']['sections'].append({
            'id': identity, 'job': _text(section.get('job'), f'section {identity} job', 1, 4),
            'does': _text(section.get('does'), f'section {identity} does', 3, 40), 'needs': list(uses_needs),
            'seconds': _pair(section.get('seconds'), f'section {identity} seconds'),
            'repeats': _pair(section.get('repeats', [1, 1]), f'section {identity} repeats', whole=True),
            'optional': section.get('optional') is True})
    if len({s['id'] for s in out['structure']['sections']}) != len(out['structure']['sections']):
        raise ValueError('section ids are unique')


def _check_devices(place, out):
    """The devices, each the style (any video can wear it) or content-shaped (only when the words call for it)."""
    devices = place.get('devices')
    if not isinstance(devices, list) or not 1 <= len(devices) <= 24:
        raise ValueError('place devices lists 1-24 devices, each the style (any video can wear it) or content-shaped')
    out['devices'] = []
    for device in devices:
        if not isinstance(device, dict) or set(device) - {'name', 'kind', 'when', 'why'}:
            raise ValueError('a device is {name, kind: style|content, when?, why}')
        if device.get('kind') not in ('style', 'content'):
            raise ValueError('a device kind is style (any video can wear it) or content (only when the words have it)')
        entry = {'name': _text(device.get('name'), 'device name', 1, 10), 'kind': device['kind'],
                 'why': _text(device.get('why'), 'device why', 2, 30)}
        if device['kind'] == 'content':
            entry['when'] = _text(device.get('when'), f'device {entry["name"]} when (the words that call for it)', 3, 30)
        out['devices'].append(entry)


def validate(place, known_styles=None, reference_names=()):
    """The checked place. `known_styles` maps Style ids to titles (catalogue and the person's learned Styles); a
    Style that isn't known must be a new one ({"new": {title, filmed, blurb}}). `reference_names` are the names
    said in the reference (its subject's proper nouns): the pattern, the uses and a new Style's title never carry
    them. Raises ValueError with what to fix."""
    if not isinstance(place, dict):
        raise ValueError('place must be an object')
    allowed = {'format', 'subject', 'pattern', 'uses', 'not_for', 'length', 'seconds', 'role', 'styles', 'footage',
               'structure', 'needs', 'devices'}
    extra = set(place) - allowed
    if extra:
        raise ValueError(f'place has unknown fields: {", ".join(sorted(extra))}')
    out = {'format': FORMAT}
    out['subject'] = _text(place.get('subject'), 'subject (what the reference itself is about, one line)', 2, 30)
    out['pattern'] = _text(place.get('pattern'), 'pattern (the general pattern in plain words, never the subject)', 6, 50)
    uses = place.get('uses')
    if not isinstance(uses, list) or not 4 <= len(uses) <= 16:
        raise ValueError('place uses lists 4-16 kinds of content the pattern could dress, as wide as it honestly goes')
    out['uses'] = list(dict.fromkeys(_text(item, 'use', 1, 14) for item in uses))
    if len(out['uses']) < 4:
        raise ValueError('place uses needs 4 or more different kinds of content')
    not_for = place.get('not_for', [])
    if not isinstance(not_for, list) or len(not_for) > 8:
        raise ValueError('place not_for is a list of up to 8 plain lines')
    out['not_for'] = [_text(item, 'not_for', 1, 20) for item in not_for]
    if place.get('length') not in ('short', 'long', 'both'):
        raise ValueError('place length is short (a vertical Short), long (a YouTube video) or both')
    out['length'] = place['length']
    out['seconds'] = _pair(place.get('seconds'), 'seconds (the length the format works at)', minimum=1)
    if place.get('role') not in ('look', 'theme', 'both'):
        raise ValueError('place role is look (a layout and format), theme (how it is drawn) or both')
    out['role'] = place['role']
    _check_styles(place, out, known_styles, reference_names)
    for label, text in [('pattern', out['pattern'])] + [('use', use) for use in out['uses']]:
        clash = _names_in(text, reference_names)
        if clash:
            raise ValueError(f'place {label} "{text}" names the reference\'s own subject ({", ".join(clash)}); '
                             'say what kind of content it could be, in general words')
    _check_footage(place, out)
    _check_needs(place, out)
    _check_structure(place, out)
    _check_devices(place, out)
    from letitedit.looks.product_knowledge import validate as knowledge
    knowledge(json.dumps(out, ensure_ascii=False), 'place')
    return content_needs(out)


def warnings(place):
    """Soft checks the save reply carries: words the pattern shares with the reference's subject."""
    subject = {w for w in re.findall(r"[a-z']+", place.get('subject', '').lower()) if w not in _STOP and len(w) > 3}
    shared = sorted(subject & {w for w in re.findall(r"[a-z']+", place.get('pattern', '').lower())})
    out = []
    if shared:
        out.append(f'the pattern repeats the subject\'s words ({", ".join(shared)}): check it names the general '
                   'pattern, not what this reference is about')
    return out


def new_styles(place):
    return [style['new'] for style in place['styles'] if isinstance(style, dict)]


# ---------------------------------------------------------------------------- what a video supplies

def _core(token):
    return re.sub(r"^[\"'(\[“‘-]+|[\"')\].,!?;:”’-]+$", '', token)


def sentences(words):
    """[{text, s, e, tokens:[core]}]: the words split at . ? ! and at pauses over a second."""
    out, current, previous = [], [], None
    for word in words or []:
        token = str(word.get('w', '')).strip()
        if not token:
            continue
        if current and previous is not None and float(word['s']) - previous > 1.0:
            out.append(current)
            current = []
        current.append((token, float(word['s']), float(word['e'])))
        previous = float(word['e'])
        if token[-1] in '.?!':
            out.append(current)
            current = []
    if current:
        out.append(current)
    return [{'text': ' '.join(t for t, _, _ in group), 's': group[0][1], 'e': group[-1][2],
             'tokens': [_core(t) for t, _, _ in group], 'question': group[-1][0].endswith('?'),
             'starts': {0} | {k + 1 for k, (t, _, _) in enumerate(group) if t[-1] in ',;:'}}
            for group in out if any(_core(t) for t, _, _ in group)]


def _capital(token):
    return bool(token) and (token[0].isupper() or (any(c.isdigit() for c in token) and any(c.isalpha() for c in token)))


def _lead(tokens):
    """The sentence's tokens without leading fillers ("oh", "and", "so", "okay")."""
    index = 0
    while index < len(tokens) and tokens[index].lower() in ('oh', 'and', 'so', 'okay', 'ok', 'also', 'um', 'uh',
                                                              'alright', 'right', 'now'):
        index += 1
    return tokens[index:]


def _runs(sentence, capital_elsewhere):
    """Named runs in a sentence: (start, end) token spans of capitalised words, small words allowed inside."""
    tokens, runs, index = sentence['tokens'], [], 0
    while index < len(tokens):
        if _capital(tokens[index]) and tokens[index].lower() not in _NOT_NAMES:
            end = index + 1
            while end < len(tokens):
                if _capital(tokens[end]) and tokens[end].lower() not in _NOT_NAMES:
                    end += 1
                elif (tokens[end].lower() in _SMALL and end + 1 < len(tokens) and _capital(tokens[end + 1])
                      and tokens[end + 1].lower() not in _NOT_NAMES):
                    end += 2
                else:
                    break
            start = index
            while end - start > 1 and tokens[start].lower() in _STOP and not (
                    tokens[start].lower() in ('the', 'a') and end - start > 2):
                start += 1                              # "As LLMs" is LLMs; "The Pathless Path" keeps its The
            single = end - start == 1
            word = tokens[start]
            acronym = len(word) > 1 and word.isupper() and word.isalpha()
            opener = start in sentence.get('starts', {0})
            if single and not acronym and not any(c.isdigit() for c in word) and (
                    len(word) < 2 or word.lower() in _STOP or (opener and capital_elsewhere.get(word.lower(), 0) < 2)):
                pass                                    # an ordinary word that starts a sentence or follows a comma
            else:
                runs.append((start, end))
            index = end
        else:
            index += 1
    return runs


def _number(token):
    lowered = token.lower().replace(',', '')
    return bool(re.search(r'\d', lowered)) or lowered in _NUMBER_WORDS or lowered.rstrip('s') in _NUMBER_WORDS


def analyse(words):
    """Counts and evidence for each transcript signal: {signal: {n, evidence: [{text, s}]}} plus `names`."""
    said = sentences(words)
    capital_elsewhere = {}
    for sentence in said:
        for k, token in enumerate(sentence['tokens']):
            if k not in sentence['starts'] and _capital(token):
                capital_elsewhere[token.lower()] = capital_elsewhere.get(token.lower(), 0) + 1
    lowered = [' '.join(sentence['tokens']).lower() for sentence in said]
    evidence = {key: [] for key in SIGNALS}

    def note(key, sentence, text=None):
        if len(evidence[key]) < 8:
            evidence[key].append({'text': (text or sentence['text'])[:120], 's': round(sentence['s'], 2)})

    # named things (runs), with trailing verdict words split off afterwards
    runs = [(i, start, end) for i, sentence in enumerate(said) for start, end in _runs(sentence, capital_elsewhere)]
    # verdict words: short sentences, the first word after a name-only sentence, a word right after a name
    verdict_spots = []
    name_only = set()
    for i, sentence in enumerate(said):
        tokens = [t for t in sentence['tokens'] if t]
        spans = [(start, end) for j, start, end in runs if j == i
                 if end - start > 1 or tokens[start].isupper() or any(c.isdigit() for c in tokens[start])]
        if spans and sum(end - start for start, end in spans) >= len(tokens) - 1:
            name_only.add(i)
    plain_spots = set()                         # a verdict said on its own: a short sentence, or after a name
    for i, sentence in enumerate(said):
        tokens = [t for t in sentence['tokens'] if t]
        content = [t.lower() for t in tokens if t.lower() not in ('or', 'and', 'it', 'then', 'just', 'a', 'the')]
        if 1 <= len(content) <= 3 and i not in name_only:
            verdict_spots += [(i, word) for word in content]
            plain_spots.update(content)
        if i - 1 in name_only and tokens:
            word = _lead(tokens)[0].lower() if _lead(tokens) else tokens[0].lower()
            verdict_spots.append((i, word))
            plain_spots.add(word)
    for i, start, end in runs:
        tokens = said[i]['tokens']
        if end < len(tokens):
            verdict_spots.append((i, tokens[end].lower()))
        verdict_spots.append((i, tokens[end - 1].lower()))
    counts = {}
    for _, word in verdict_spots:
        if len(word) >= 3 and word.isalpha() and word not in _STOP and not _number(word):
            counts[word] = counts.get(word, 0) + 1
    labels = {word for word, count in counts.items() if count >= 2 and word in plain_spots}
    names, sorted_items = {}, 0
    for i, start, end in runs:
        tokens = said[i]['tokens']
        stop = end
        while stop > start and tokens[stop - 1].lower() in labels:
            stop -= 1
        if stop == start:
            continue
        name = ' '.join(tokens[start:stop])
        key = name.lower()
        if key in labels or key in _STOP:
            continue
        verdict = (stop < end or (end < len(tokens) and tokens[end].lower() in labels)
                   or (i in name_only and i + 1 < len(said) and _lead(said[i + 1]['tokens'])
                       and _lead(said[i + 1]['tokens'])[0].lower() in labels))
        if key not in names:
            names[key] = name
            note('named_things', said[i], name)
            if verdict:
                sorted_items += 1
    groups = sorted(labels, key=lambda word: -counts[word]) if sorted_items >= 2 else []
    for word in groups:
        for i, spot in verdict_spots:
            if spot == word:
                note('groups', said[i], f'{word}: {said[i]["text"]}')
                break

    # list markers
    markers, announced = 0, 0
    for i, sentence in enumerate(said):
        lead = ' '.join(t.lower() for t in _lead(sentence['tokens']) if t)
        text = lowered[i]
        hit = (re.match(rf'^(?:{_ORDINALS})\b', lead) or re.match(r'^number (?:\d+|one|' + '|'.join(_NUMBER_WORDS[:9])
                                                                   + r')\b', lead)
               or re.match(r'^(?:another|one more|last but not least|the last one|the next one)\b', lead)
               or re.search(r'\b(?:another|one more|the next|the last|the first|the second|the third|the fourth|'
                            r'the fifth) (?:thing|tip|reason|way|one|step|mistake|book|point|rule|habit|sign|'
                            r'lesson|tool|app|idea|question|secret|hack|fact|product|place|option|myth)s?\b', text))
        if hit:
            markers += 1
            note('list_items', sentence)
        count = re.search(r'\b(\d+|' + '|'.join(_NUMBER_WORDS[:19]) + r') (?:\w+ )?(?:' + '|'.join(_COUNT_NOUNS)
                          + r')\b', text)
        if count:
            value = count.group(1)
            number = int(value) if value.isdigit() else _NUMBER_WORDS.index(value) + 2
            if 2 <= number <= 100 and number > announced:
                announced = number
                note('list_items', sentence, f'announced: {sentence["text"]}')
    list_items = max(markers, sorted_items, announced)

    numbers = sum(1 for sentence in said for k, token in enumerate(sentence['tokens'])
                  if _number(token) and not (k and _number(sentence['tokens'][k - 1])))
    for sentence in said:
        if any(_number(token) for token in sentence['tokens']):
            note('numbers', sentence)
    questions = [sentence for sentence in said if sentence['question']]
    for sentence in questions:
        note('questions', sentence)
    steps = 0
    for i, sentence in enumerate(said):
        lead = [t.lower() for t in _lead(sentence['tokens']) if t]
        text = lowered[i]
        if (lead and lead[0] in _IMPERATIVE) or re.search(r'\b(?:step (?:\d+|one|two|three|four|five)|first you|'
                                                         r'then you|next you|now you)\b', text):
            steps += 1
            note('steps', sentence)
    whole = ' ' + ' '.join(lowered) + ' '
    contrast = 0
    for first, second in _CONTRAST_PAIRS:
        if re.search(rf'\b{first}\b', whole) and re.search(rf'\b{second}\b', whole):
            contrast += 1
            hit = next((s for s, text in zip(said, lowered) if re.search(rf'\b{first}\b', text)), None)
            if hit:
                note('contrast', hit)
    for phrase in _CONTRAST_PHRASES:
        found = [s for s, text in zip(said, lowered) if phrase in f' {text} ']
        if found:
            contrast += 1 if phrase not in ('used to', 'in the past') else 0
            note('contrast', found[0])
    story = 0
    for sentence, text in zip(said, lowered):
        hits = sum(1 for marker in _STORY if marker in f' {text} ')
        if hits:
            story += hits
            note('story', sentence)
    cta = 0
    for sentence, text in zip(said, lowered):
        if any(marker in text for marker in _CTA):
            cta += 1
            note('cta', sentence)
    counts_out = {'list_items': list_items, 'named_things': len(names), 'numbers': numbers,
                  'questions': len(questions), 'steps': steps, 'groups': len(groups), 'contrast': contrast,
                  'story': story, 'cta': cta}
    return {'signals': counts_out, 'evidence': {k: v for k, v in evidence.items() if v},
            'names': sorted(names.values(), key=str.lower), 'group_words': groups,
            'list': {'markers': markers, 'sorted': sorted_items, 'announced': announced},
            'opening': said[0]['text'][:160] if said else '', 'ending': said[-1]['text'][:160] if said else '',
            'sentences': len(said)}


def reference_names(words):
    """Lower-case names said in a reference (its subject's proper nouns), for the place's topic guard."""
    names = analyse(words)['names'] if words else []
    out = set()
    for name in names:
        lowered = name.lower()
        if len(lowered) > 2 and lowered not in _STOP and not lowered.isupper():
            out.add(re.sub(r'[^a-z0-9 ]+', ' ', lowered).strip())
    return sorted(n for n in out if n)


def _duration(path):
    try:
        import letitedit.footage.speech as speech
        return float(speech._duration(str(path)))
    except Exception:  # noqa: BLE001 - unreadable: unknown
        return None


def _frame(path):
    """vertical, wide or square, from the first video stream's shown size (rotation counted); None if unreadable."""
    try:
        import subprocess
        import letitedit.footage.speech as speech
        probe = subprocess.run([str(speech.FFPROBE), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=width,height:stream_side_data=rotation:stream_tags=rotate', '-of', 'json',
                                str(path)], capture_output=True, text=True, timeout=20)
        stream = json.loads(probe.stdout)['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
        rotation = abs(int(float((stream.get('tags') or {}).get('rotate', 0) or next(
            (item.get('rotation', 0) for item in stream.get('side_data_list', []) if 'rotation' in item), 0))))
        if rotation % 180 == 90:
            width, height = height, width
        return 'vertical' if height > width * 1.05 else 'wide' if width > height * 1.05 else 'square'
    except Exception:  # noqa: BLE001 - not a video, or no ffprobe: unknown
        return None


def measure(paths=None, words=None, seconds=None, footage=None, transcribe=False, budget_s=4.0):
    """What a video, or a set of clips, supplies: total seconds, the footage kind (what_was_filmed), the talk share
    and each transcript signal with evidence. `words` (a list, or a list per clip) skips reading transcripts;
    `transcribe` makes missing transcripts (local whisper, cached) instead of leaving speech unknown."""
    files = []
    if paths:
        import letitedit.app.what_was_filmed as what_was_filmed
        files = what_was_filmed.media_files(paths)
    per_clip, missing = [], []
    if words is not None:
        per_clip = [words] if words and isinstance(words[0], dict) else list(words)
    else:
        import letitedit.footage.speech as speech
        for path in files:
            if Path(path).suffix.lower() in what_was_filmed.PHOTO:
                continue
            got = speech.cached_words(path)
            if got is None and transcribe:
                try:
                    got = speech.words(path)
                except Exception:  # noqa: BLE001 - no sound track
                    got = []
            if got is None:
                missing.append(Path(path).name)
            else:
                per_clip.append(got)
    if seconds is None and files:
        lengths = [_duration(path) for path in files]
        seconds = sum(value for value in lengths if value) if any(lengths) else None
    if footage is None and files:
        import letitedit.app.what_was_filmed as what_was_filmed
        try:
            detected = what_was_filmed.detect(files, budget_s=budget_s)
            footage = {'style': detected.get('style'), 'label': detected.get('label'), 'why': detected.get('why'),
                       'people': max((sorted(clip['faces'])[len(clip['faces']) // 2] for clip in detected.get('clips', [])
                                      if clip.get('faces')), default=None)}   # the middle frame count, per clip
        except Exception as error:  # noqa: BLE001 - no face model, unreadable clips: unknown
            footage = {'style': None, 'why': str(error)}
    if isinstance(footage, str):
        footage = {'style': footage}
    joined, offset = [], 0.0
    for clip in per_clip:
        for word in clip:
            joined.append({**word, 's': float(word['s']) + offset, 'e': float(word['e']) + offset})
        if clip:
            offset = joined[-1]['e'] + 2.0
    frames = list(dict.fromkeys(shape for path in files if (shape := _frame(path))))
    frame = frames[0] if len(frames) == 1 else 'mixed' if frames else None
    result = {'seconds': round(seconds, 2) if seconds else seconds, 'footage': footage or {}, 'frame': frame,
              'frames': frames,
              'transcribed': not missing, 'not_transcribed': missing, 'clips': len(files) or len(per_clip)}
    speech_known = words is not None or (files and not missing)
    if speech_known:
        analysis = analyse(joined)
        talk = sum(max(0.0, w['e'] - w['s']) for w in joined)
        signals = dict(analysis['signals'])
        signals['words'] = len(joined)
        signals['talk'] = round(min(1.0, talk / seconds), 3) if seconds else None
        result.update(signals=signals, evidence=analysis['evidence'], names=analysis['names'],
                      group_words=analysis['group_words'], list=analysis['list'], opening=analysis['opening'],
                      ending=analysis['ending'])
    else:
        result['signals'] = {}
    if (footage or {}).get('people') is not None:
        result['signals']['people'] = footage['people']
    return result


# ---------------------------------------------------------------------------- the fit check

def _plain_count(signal, value):
    if signal == 'people' and value == 1:
        return 'one person'
    if signal == 'list_items' and value == 1:
        return 'one item'
    try:
        return SIGNALS[signal][0].format(n=value)
    except (KeyError, ValueError):
        return f'{signal} {value}'


def content_needs(place):
    place = copy.deepcopy(place)
    for need in place['needs']:
        sections = [section for section in place['structure']['sections'] if need['id'] in section['needs']]
        chapter_content = (not need.get('kind') and need['signal'] in ('list_items', 'steps')
                           and any(section['job'] == 'chapter' for section in sections)
                           and all(section['job'] in ('chapter', 'setup', 'agenda') for section in sections))
        if need.get('kind') == 'content' or chapter_content:
            need['must'] = False
            need['kind'] = 'content'
            need.setdefault('without', 'Keep the spoken explanation and its visual style without an agenda or numbered chapters.')
    return place


def framing(place, measured, output_format=None):
    if output_format not in (None, 'short', 'long'):
        raise ValueError('fit format is short or long')
    length = output_format or place['length']
    targets = ['vertical', 'wide'] if length == 'both' else ['vertical' if length == 'short' else 'wide']
    sources = measured.get('frames') or ([measured['frame']] if measured.get('frame') else [])
    sources = [shape for shape in sources if shape in ('vertical', 'wide', 'square')]
    mismatch = bool(sources and any(shape not in targets for shape in sources))
    options = ['subject_crop', 'own_room_blur'] if mismatch else []
    if mismatch and place['length'] == 'both':
        options.append('short_format')
    names = {'vertical': 'upright', 'wide': 'landscape', 'square': 'square'}
    target_line = ' or '.join(names[shape] for shape in targets)
    source_line = ' and '.join(names[shape] for shape in sources) or 'unknown shape'
    line = f'Footage shape: {source_line}; Look format: {target_line}.'
    if mismatch:
        line += (' A crop around the person or their own blurred room behind the full-height picture can fill '
                 'the canvas; the layout and face framing decide which fits.')
        if 'short_format' in options:
            line += ' This Look also has a Short format.'
    return {'sources': sources, 'targets': targets, 'mismatch': mismatch, 'options': options, 'line': line}


def fit(place, measured, output_format=None):
    """Whether the clips fit the Look's format: fits (every must-have met; optional content the clips lack, listed in
    `leaves`, is left out of the cut), maybe (nothing measured is missing but a must-have only the AI can judge),
    partly (the footage falls short another way: too short, or talking where the format has none), no (a must-have
    is missing: the footage kind, speech, or a must need) or unknown (nothing could be measured yet). Each found,
    missing and unchecked entry says what it is in plain words; `sections` says which parts of the format the
    clips can fill."""
    place = content_needs(place)
    found, missing, unchecked = [], [], []
    if output_format and place['length'] not in ('both', output_format):
        missing.append({'need': 'format', 'must': True,
                        'text': f'This Look has a {place["length"]} format, not the selected {output_format} format.'})
    shape = framing(place, measured, output_format)
    if shape['mismatch']:
        missing.append({'need': 'orientation', 'must': False, 'text': shape['line']})
    footage = place['footage']
    got = (measured.get('footage') or {}).get('style')
    kinds = footage['kinds']
    if kinds != ['none']:
        if got in kinds:
            found.append({'need': 'footage', 'text': f'footage: {FOOTAGE_WORDS.get(got, got)}'})
        elif got in (None, 'all'):
            unchecked.append({'need': 'footage', 'text': f'whether the clips are {footage["what"]}'})
        else:
            missing.append({'need': 'footage', 'must': True,
                            'text': f'{footage["what"]} (your clips look like {FOOTAGE_WORDS.get(got, got)})'})
    signals = measured.get('signals') or {}
    if footage['speech'] == 'needed':
        words = signals.get('words')
        if words is None:
            unchecked.append({'need': 'speech', 'text': 'what is said (the clips are not transcribed yet)'})
        elif words >= 40 or (signals.get('talk') or 0) >= 0.3:
            found.append({'need': 'speech', 'text': f'{words} words said'})
        else:
            missing.append({'need': 'speech', 'must': True, 'text': f'someone talking (only {words} words said)'})
    elif footage['speech'] == 'none' and signals.get('talk') is not None:
        if signals['talk'] >= QUIET_TALK:
            missing.append({'need': 'speech', 'must': False,
                            'text': f"footage without talking: the format has none (your clips talk "
                                    f"{signals['talk']:.0%} of the time; the cut would have to mute it)"})
        else:
            found.append({'need': 'speech', 'text': f"little talking ({signals['talk']:.0%} of the time)"})
    people = footage.get('people')
    if people and signals.get('people') is not None:
        if people[0] <= signals['people'] <= max(people[1], people[0]):
            found.append({'need': 'people', 'text': _plain_count('people', signals['people'])})
        elif signals['people'] < people[0]:
            missing.append({'need': 'people', 'must': True,
                            'text': f'{people[0]} or more people on camera (the clips show {signals["people"]})'})
    low, high = place['seconds']
    have = measured.get('seconds')
    if have:
        if have < low * 0.75:
            missing.append({'need': 'length', 'must': have < low * 0.4,
                            'text': f'enough footage: the clips run {have:.0f} s; the format runs {low:.0f}-{high:.0f} s'})
        else:
            found.append({'need': 'length', 'text': f'{have:.0f} s of footage'})
    status = {}
    for need in place['needs']:
        if need['signal'] == 'ai':
            unchecked.append({'need': need['id'], 'text': need['what']})
            status[need['id']] = None
            continue
        value = signals.get(need['signal'])
        if value is None:
            unchecked.append({'need': need['id'], 'text': need['what']})
            status[need['id']] = None
        elif value >= need['min'] and (need.get('max') is None or value <= need['max']):
            entry = {'need': need['id'], 'text': _plain_count(need['signal'], value), 'what': need['what']}
            examples = (measured.get('evidence') or {}).get(need['signal'])
            if examples:
                entry['examples'] = examples[:3]
            found.append(entry)
            status[need['id']] = True
        else:
            got = 'none found' if not value else f'only {_plain_count(need["signal"], value)}'
            missing.append({'need': need['id'], 'must': need['must'], 'what': need['what'],
                            'text': f'{need["what"]} ({got})', 'why': need['why']})
            if need.get('without'):
                missing[-1]['without'] = need['without']
            status[need['id']] = False
    sections = []
    must_needs = {need['id'] for need in place['needs'] if need['must']}
    for section in place['structure']['sections']:
        states = [status.get(identity) for identity in section['needs']]
        lacking = [identity for identity in section['needs'] if status.get(identity) is False]
        # a section can be built without an optional need it lacks (the items without their pictures), unless that
        # leaves it nothing at all (a header made only of group words)
        has = (False if any(identity in must_needs for identity in lacking) or (lacking and len(lacking) == len(states))
               else None if any(state is None for state in states) else True)
        entry = {'id': section['id'], 'job': section['job'], 'has': has, 'optional': section['optional']}
        if lacking and has is not False:
            entry['without'] = lacking
        sections.append(entry)
    musts = must_needs | {'footage', 'speech'}
    # an optional need the clips lack is content the format can do without (a number card, a then-and-now, a closing
    # question): the cut leaves that part out, which doesn't stop it fitting; footage that would have to be muted or is
    # too short is a real gap
    optional = {need['id'] for need in place['needs'] if not need['must']}
    leaves = [entry for entry in missing if entry['need'] in optional and not entry.get('must')]
    gaps = [entry for entry in missing if entry not in leaves]
    if any(entry.get('must') for entry in missing):
        verdict = 'no'
    elif gaps:
        verdict = 'partly'
    elif any(entry['need'] in ('footage', 'speech') for entry in unchecked) or not found:
        verdict = 'unknown'
    elif any(entry['need'] in musts for entry in unchecked):
        verdict = 'maybe'                       # nothing measured is missing; a must-have only the AI can judge
    else:
        verdict = 'fits'
    line = fit_line(verdict, found, missing, unchecked, leaves)
    if _clause(shape['line']) not in line:
        line += ' ' + shape['line']
    for entry in leaves:
        if entry.get('without'):
            line += ' ' + entry['without']
    return {'fit': verdict, 'line': line, 'found': found, 'framing': shape,
            'missing': missing, 'unchecked': unchecked, 'leaves': leaves, 'sections': sections}


def _clause(text):
    """A need or a finding as a piece of one sentence: no full stop of its own, and a lower-case start unless its first
    word keeps its capitals (AI, NASA, YouTube). Needs are written in general words, so a name rarely leads one."""
    text = str(text).strip().rstrip('.').strip()
    first = text.split(' ')[0]
    if first[:1].isupper() and not any(letter.isupper() for letter in first[1:]):
        text = text[0].lower() + text[1:]
    return text


def fit_line(verdict, found, missing, unchecked, leaves=()):
    """The plain words New video shows on the Look step."""
    shown = [_clause(entry['text']) for entry in found if entry['need'] not in ('length', 'speech')][:4]
    lacking = [_clause(entry['text']) for entry in missing if entry not in leaves][:3]
    left = [_clause(entry.get('what') or entry['text']) for entry in leaves][:3]
    without = (" The AI leaves out the optional parts your clips don't have: " + '; '.join(left) + '.') if left else ''
    if verdict == 'fits':
        return 'Fits your clips: ' + '; '.join(shown or [_clause(entry['text']) for entry in found][:3]) + '.' + without
    if verdict == 'partly':
        return ('Partly fits: ' + ('; '.join(shown) + '. ' if shown else '') + 'Missing: ' + '; '.join(lacking)
                + '. The cut adapts the format and says what it left out.' + without)
    if verdict == 'no':
        return ("Doesn't fit your clips: it needs " + '; '.join(lacking)
                + '. You can still make it with only the look, or choose another Look.')
    if verdict == 'maybe':
        judged = [_clause(entry['text']) for entry in unchecked][:2]
        return ('Might fit: ' + '; '.join(shown or [_clause(entry['text']) for entry in found][:3])
                + '. While it cuts, the AI checks for ' + '; '.join(judged)
                + '. It says if it had to leave a part out.' + without)
    waiting = [_clause(entry['text']) for entry in unchecked][:2]
    return 'Could not fully check your clips' + (': ' + '; '.join(waiting) if waiting else '') + '.'


# ---------------------------------------------------------------------------- the first cut's plan

def plan_check(place, plan):
    """Problems with a first cut's format plan (story_plan.json's `format`): every section of the Look's format is
    built (with the person's own content, its count inside the format's repeats) or left out with a reason, built
    sections keep the format's order, and a partial fit says what was left out and why."""
    fmt = (plan or {}).get('format')
    if not isinstance(fmt, dict):
        return ['story_plan.json has no format: map each section of the Look\'s format to what the cut builds from '
                'this footage, or why it is left out']
    problems = []
    if fmt.get('fit') not in ('fits', 'partly', 'no', 'look-only'):
        problems.append('format.fit is fits, partly, no or look-only (the fit check\'s answer, or look-only when '
                        'only the look is used)')
    planned = fmt.get('sections')
    if not isinstance(planned, list):
        return problems + ['format.sections lists the Look\'s sections, each built or left out']
    by_id = {entry.get('id'): entry for entry in planned if isinstance(entry, dict)}
    order = []
    for section in place['structure']['sections']:
        entry = by_id.get(section['id'])
        if entry is None:
            problems.append(f'format section {section["id"]} ({section["job"]}) is neither built nor left out')
            continue
        if entry.get('built') is True:
            count = entry.get('count', 1)
            low, high = section['repeats']
            if type(count) is not int or not low <= count <= max(high, low):
                problems.append(f'format section {section["id"]} is built {count} times; the format has {low}-{high}')
            content = entry.get('content')
            if section['needs'] and (not isinstance(content, list) or not content
                                     or not all(isinstance(item, str) and item.strip() for item in content)):
                problems.append(f'format section {section["id"]} needs its content from this footage (the items, '
                                'names or lines it uses)')
            at = entry.get('at')
            if type(at) in (int, float):
                order.append((at, section['id']))
        elif entry.get('built') is False:
            if not str(entry.get('why', '')).strip():
                problems.append(f'format section {section["id"]} is left out without a reason')
        else:
            problems.append(f'format section {section["id"]}: built is true or false')
    ids = [identity for _, identity in sorted(order)]
    expected = [s['id'] for s in place['structure']['sections'] if s['id'] in ids]
    if ids != expected:
        problems.append('built sections are out of the format\'s order: ' + ' > '.join(ids))
    # a section the format always has, left out (a fit without its optional content), is said in plain words too
    left = any(not section['optional'] and (by_id.get(section['id']) or {}).get('built') is False
               for section in place['structure']['sections'])
    if (fmt.get('fit') in ('partly', 'no', 'look-only') or left) and not str(fmt.get('left_out', '')).strip():
        problems.append('format.left_out says in plain words what was left out of the format and why')
    used = fmt.get('content_devices') or []
    content_devices = {d['name'].lower(): d for d in place['devices'] if d['kind'] == 'content'}
    for item in used if isinstance(used, list) else []:
        name = str((item or {}).get('name', '')).lower() if isinstance(item, dict) else str(item).lower()
        if name in content_devices and not (isinstance(item, dict) and str(item.get('because', '')).strip()):
            problems.append(f'content device {name} is used without the words that call for it '
                            f'({content_devices[name]["when"]})')
    return problems


# ---------------------------------------------------------------------------- reading a saved place

class NoPlace(ValueError):
    """A Look saved before places (or a catalogue Look): it still works, its fit just can't be checked."""


NO_PLACE_LINE = ("This Look was saved before letitedit worked out where Looks fit, so whether your clips fit it "
                 "can't be checked. You can still use it.")


def no_place(look):
    """The fit check's answer for a Look without a saved place."""
    return {'fit': 'unknown', 'line': NO_PLACE_LINE, 'no_place': True, 'look': str(look), 'found': [], 'missing': [],
            'unchecked': [], 'sections': []}


def load(look):
    """A saved place: a place.json path, a recipe path (its sibling), or a Look id (catalogue or My Looks). A Look
    without one raises NoPlace."""
    path = Path(str(look))
    if path.suffix.lower() == '.json' and path.is_file():
        return json.loads(path.read_text(encoding='utf-8-sig'))
    if path.suffix.lower() == '.md':
        if not path.with_name('place.json').is_file():
            raise NoPlace(f'{path} has no saved place (format and needs) beside it')
        return json.loads(path.with_name('place.json').read_text(encoding='utf-8-sig'))
    import letitedit.looks.looks as looks
    card = looks.read(str(look))
    sibling = Path(card['recipe']).with_name('place.json')
    if not sibling.is_file():
        raise NoPlace(f'Look {look} has no saved place (format and needs) yet')
    return json.loads(sibling.read_text(encoding='utf-8-sig'))


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='The fit check: does a set of clips fit a learned Look?')
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('fit')
    one.add_argument('--look', required=True)
    one.add_argument('paths', nargs='+')
    one.add_argument('--transcribe', action='store_true')
    one.add_argument('--budget', type=float, default=4.0)
    one.add_argument('--format', choices=('short', 'long'))
    two = commands.add_parser('measure')
    two.add_argument('paths', nargs='+')
    two.add_argument('--transcribe', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'fit':
            try:
                place = load(args.look)
            except NoPlace:
                out = no_place(args.look)
            else:
                measured = measure(args.paths, transcribe=args.transcribe, budget_s=args.budget)
                out = {'look': args.look, **fit(place, measured, args.format),
                       'measured': {key: measured.get(key) for key in ('seconds', 'footage', 'signals',
                                                                       'not_transcribed')}}
        else:
            out = measure(args.paths, transcribe=args.transcribe)
    except (OSError, ValueError, KeyError) as error:
        out = {'error': str(error)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
