"""What is said on the timeline, in timeline time: words for any range, and captions made from them.

    timeline_words(script, start_s, end_s) -> [{'w', 't0', 't1', 'id', 'track'}]  (timeline seconds)
    captions_from_speech(script, chunk='sentence') -> [{'start', 'end', 'text'}]
    caption_fixes(style, given, use_style=True) -> the spelling fixes captions use (the style's captions.corrections,
                                                   e.g. from My Looks, with the call's own on top)
    align_cues_to_words(script, cues) -> (cues, report): given cues with each start and end moved to the words they
                                         show on this timeline (cached word times; text and grouping unchanged)

Speech comes from every track whose sound is on (not music or effects tracks, not muted clips, not fast-forwarded
clips), using the cached word timings of each source file (speech.words). Captions never run across a cut.
"""
from __future__ import annotations

import difflib
import re

import letitedit.timeline.edit_script as es
import letitedit.core.render_lock as render_lock
from letitedit.timeline.edit_sync import layout

NOT_SPEECH = re.compile(r'music|song|score|bed|sfx|effect|sound|foley|ambien', re.I)


def _muted(item):
    return any(e == 'mute' or (isinstance(e, dict) and 'mute' in e) for e in item.get('effects', []))


def _effect_file(item):
    import letitedit.sound.music as music
    return music.is_sound_library_file(item.get('clip'))


def _voice(clip):
    try:
        import letitedit.sound.music as music
        return music.voice_times(clip)
    except Exception:  # noqa: BLE001 - no voice detection: words by their recognised times
        return None


def _word_span(w, voice):
    """Bound a recognizer's implausibly long word by the first following voice pause.

    Whisper occasionally gives the last word of a phrase the silence and even the
    next phrase's time. That must not make a clearly heard clip-edge word disappear.
    """
    ws, we = float(w['s']), float(w['e'])
    if we - ws > 2.0:
        pause = next((y for x, y in (voice or []) if x <= ws + 0.2 and y > ws + 0.05), None)
        we = min(we, pause if pause is not None else ws + 1.5)
    return ws, we


def heard_in(w, a, b, voice):
    """True when a recognised word is heard inside the source range a-b: most of its voiced sound is inside (voice
    detection), or, where no voice is detected on it, most of its recognised time span."""
    ws, we = _word_span(w, voice)
    if voice:
        total = sum(max(0.0, min(we, y) - max(ws, x)) for x, y in voice)
        if total > 0.05:
            inside = sum(max(0.0, min(we, b, y) - max(ws, a, x)) for x, y in voice)
            return inside >= 0.5 * total
    if we - ws < 1e-3:
        return a <= ws <= b
    return max(0.0, min(we, b) - max(ws, a)) >= 0.5 * (we - ws)


def played_clip(it):
    """The item as the footage it plays: a clip lit by the lighting effect is its source clip, range and speed."""
    v = it.get('vfx')
    if isinstance(v, dict) and v.get('effect') == 'lighting' and isinstance(v.get('source'), dict) and v['source'].get('clip'):
        src = v['source']
        return {**it, 'clip': src['clip'], 'in': src.get('in', 0), 'out': src.get('out', src.get('in', 0)),
                **({'speed': src['speed']} if src.get('speed') else {})}
    return it


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff', '.svg'}


def _has_sound(clip):
    """True when the file has an audio stream (a still or a silent video has none; an unreadable file counts as none)."""
    from pathlib import Path
    if Path(str(clip)).suffix.lower() in IMAGE_SUFFIXES:
        return False
    try:
        import letitedit.core.media as media
        return media.audio_streams(clip) > 0
    except Exception:  # noqa: BLE001 - unreadable: nothing on it can be transcribed
        return False


def timeline_words(script, start_s=None, end_s=None, cached_only=False, heard=False, missing=None):
    """Spoken words on the timeline between start_s and end_s (timeline seconds), each with its clip id. With
    cached_only and a `missing` list, the ids of the audible clips (an audio stream, not muted, on a speech track) whose
    words aren't transcribed yet are added to it, so no words can be told apart from words not yet known."""
    import letitedit.footage.speech as speech
    lo = float(start_s) if start_s is not None else 0.0
    hi = float(end_s) if end_s is not None else float('inf')
    out, seen = [], set()
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            it = played_clip(it)
            if 'clip' not in it or it.get('reverse') or _muted(it) or e <= lo or s >= hi or _effect_file(it):
                continue
            speed = float(it.get('speed', 1.0))
            if speed > 1.5:
                continue
            a, b = float(it['in']), float(it['out'])
            try:
                # The source query filters by word start. Fetch before the in-point so a
                # word that begins just before it but is mostly heard survives the cut.
                query_a = max(0.0, a - 1.0)
                ws = (speech.cached_words(it['clip'], query_a, b) if cached_only
                      else speech.words(it['clip'], query_a, b))
                if ws is None and cached_only and missing is not None and _has_sound(it['clip']):
                    missing.append(it.get('id'))
                if not ws:
                    continue
                if heard:
                    import letitedit.footage.word_reheard as word_reheard
                    ws = word_reheard.overlay(it['clip'], ws, query_a, b, hear=not cached_only)
            except render_lock.Busy:
                raise                       # the speech model waited behind a render: say so, never a caption with gaps
            except Exception:  # noqa: BLE001 - no audio stream, unreadable file
                continue
            voice = _voice(it['clip'])
            for w in ws:
                if not heard_in(w, a, b, voice):
                    continue
                word_start, word_end = _word_span(w, voice)
                t0 = max(s, s + (word_start - a) / speed)
                t1 = min(e, s + (word_end - a) / speed)
                if t1 <= lo or t0 >= hi or t0 >= e:
                    continue
                key = (round(t0, 1), w['w'].lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append({'w': w['w'], 't0': round(t0, 3), 't1': round(t1, 3), 'id': it.get('id'), 'track': t['name'],
                            'p': w.get('p', 1.0), **({'reheard': True} if w.get('reheard') else {})})
    out.sort(key=lambda x: x['t0'])
    # pieces of a word the transcriber split ("two" "-hand", "it" "'s") join their word; one whose word was cut off
    # loses its hyphen
    joined = []
    for w in out:
        piece = w['w'].strip()
        if piece[:1] in "-'" and len(piece) > 1:
            prev = joined[-1] if joined else None
            if prev and prev['id'] == w['id'] and w['t0'] - prev['t1'] < 0.15:
                prev['w'] = prev['w'].rstrip() + piece
                prev['t1'] = w['t1']
                continue
            if piece[0] == '-':
                w = dict(w, w=piece.lstrip('-'))
        joined.append(w)
    return joined


def add_said(script, limit=400):
    """Give every clip whose words are already transcribed a `said` field: the words heard in it (words mostly
    inside the clip's in/out), for reading a cut like a script. Untranscribed files are skipped, so reads stay fast.
    Every video clip with a recording time also gets `recorded` (core_tools.add_recorded)."""
    import letitedit.footage.speech as speech
    try:
        import letitedit.server.core_tools as core_tools
        core_tools.add_recorded(script)
    except Exception:  # noqa: BLE001 - recording times are a convenience for reads
        pass
    for t in script.get('tracks', []):
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it in t.get('items', []):
            if 'clip' not in it or it.get('reverse') or _muted(it) or float(it.get('speed', 1.0)) > 1.5:
                continue
            a, b = float(it['in']), float(it['out'])
            ws = speech.cached_words(it['clip'], max(0.0, a - 1.0), b)
            if not ws:
                continue
            import letitedit.footage.word_reheard as word_reheard
            ws = word_reheard.overlay(it['clip'], ws, max(0.0, a - 1.0), b)     # what's already been heard; nothing is heard here
            voice = _voice(it['clip'])
            keep = [w for w in ws if heard_in(w, a, b, voice)]
            text = ' '.join(w['w'].strip() for w in keep).strip()
            if text:
                it['said'] = text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0] + ' ...'
    return script


def _lines(words, max_chars, max_lines):
    """Split a cue's words into at most max_lines balanced lines of at most max_chars."""
    text = ' '.join(words)
    if len(text) <= max_chars or max_lines == 1:
        return text
    best = None
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        if len(a) <= max_chars and len(b) <= max_chars:
            score = abs(len(a) - len(b)) + (20 if _dangling(words[k - 1]) else 0)
            if best is None or score < best[0]:
                best = (score, a + '\n' + b)
    return best[1] if best else text


_DEPENDENT = {'a', 'an', 'the', 'my', 'our', 'your', 'this', 'that', "that's", 'these', 'those', 'to', 'of', 'for',
              'with', 'from', 'in', 'on', 'at', 'and', 'or', 'but', 'because', 'if', 'i', "i'm", 'we',
              'you', 'he', 'she', 'it', 'they', 'is', 'are', 'was', 'were', 'will', 'would', 'can'}


def _dangling(token):
    """A word that leans on the next one ("the", "of", "was"), unless it ends a sentence: "what a Wanderlodge was."
    is finished, so the caption ends there."""
    if str(token).rstrip().rstrip('"\'”’)').endswith(SENTENCE_END):
        return False
    return _said(token) in _DEPENDENT


SENTENCE_END = ('.', '?', '!', '…')
# Words the recogniser capitalises only where it hears a new sentence begin. Its word timings sometimes lose the full
# stop before them ("so here we are My name is Ellie"), so a capital on one of these marks the sentence end. "I" and
# names are capitalised anywhere, so they don't count.
_SENTENCE_STARTERS = {'my', 'we', "we're", "we've", "we'll", 'so', 'and', 'but', 'this', 'that', "that's", 'the', 'it',
                      "it's", 'there', "there's", 'they', "they're", 'he', 'she', "she's", 'you', "you're", 'our',
                      'what', 'when', 'then', 'now', 'yeah', 'yep', 'okay', 'ok', 'well', 'oh', 'if', 'because', 'also',
                      'just', 'a', 'an', 'in', 'on', 'thanks', 'thank', 'here', 'how', 'why', 'let', "let's", 'no', 'yes'}


_I_FORMS = {'i', "i'm", "i've", "i'll", "i'd"}


def _titled(token):
    """A capitalised word that could be part of a name or title ("Let It Edit", "The Open Road"): "I" is
    capitalised anywhere, so it doesn't count."""
    text = str(token).strip().lstrip('"\'“‘(')
    return text[:1].isupper() and _said(text) not in _I_FORMS


def _in_title_run(words, i):
    """Whether words[i] sits in a run of three or more capitalised words in one clip (a name or title such as "Let It
    Edit." or "The Open Road"), counting through a word that ends a sentence but not past it."""
    if not _titled(words[i]['w']):
        return False
    run, j = 1, i - 1
    while (j >= 0 and words[j]['id'] == words[i]['id'] and _titled(words[j]['w'])
           and not str(words[j]['w']).rstrip().endswith(SENTENCE_END)):
        run, j = run + 1, j - 1
    j = i
    while (not str(words[j]['w']).rstrip().endswith(SENTENCE_END) and j + 1 < len(words)
           and words[j + 1]['id'] == words[i]['id'] and _titled(words[j + 1]['w'])):
        run, j = run + 1, j + 1
    return run >= 3


def _sentence_starts(words):
    """Words with the recogniser's lost full stops put back: a word that has no end punctuation, followed by a
    capitalised sentence starter (_SENTENCE_STARTERS), ends a sentence. Across a cut too: the next clip's capital comes
    from its own source, where a sentence began. Not inside a name or title of three or more capitalised words ("I
    created Let It Edit." keeps "Let It Edit." whole, with no full stop added before "Let" or "It")."""
    out = [dict(w) for w in words]
    for k, (prev, nxt) in enumerate(zip(out, out[1:])):
        text, following = str(prev['w']).rstrip(), str(nxt['w']).strip()
        if (not text or not following or not following[0].isupper()
                or text.endswith(SENTENCE_END + (',', ';', ':', '-', '—'))):
            continue
        if _said(following) in _SENTENCE_STARTERS and not _in_title_run(out, k + 1):
            prev['w'] = text + '.'
    return out


def tidy_caption_cues(cues, max_chars=42, max_lines=2, max_cps=20):
    """Repair dependent phrase endings and lend display time to fast manually timed native captions.

    This is also safe on speech-generated cues. The caption-fit solver's own proposals keep their exact boundaries.
    """
    out = [dict(c) for c in cues]
    i = 0
    while i + 1 < len(out):
        left, right = out[i], out[i + 1]
        words = str(left.get('text', '')).split()
        a, b = es.to_seconds(left['start']), es.to_seconds(left['end'])
        c, d = es.to_seconds(right['start']), es.to_seconds(right['end'])
        joined = ' '.join((str(left.get('text', '')).replace('\n', ' '),
                           str(right.get('text', '')).replace('\n', ' '))).strip()
        if (words and _dangling(words[-1]) and 0 <= c - b <= 0.12 and d - a <= 7.0
                and len(joined) <= max_chars * max_lines):
            left['text'] = _lines(joined.split(), max_chars, max_lines)
            left['end'] = right['end']
            if 'words' in left and 'words' in right:
                left['words'] = list(left['words']) + list(right['words'])
            else:
                left.pop('words', None)
            out.pop(i + 1)
            continue
        i += 1
    for i in range(1, len(out)):
        prev, cue = out[i - 1], out[i]
        ps, pe = es.to_seconds(prev['start']), es.to_seconds(prev['end'])
        cs, ce = es.to_seconds(cue['start']), es.to_seconds(cue['end'])
        if cs - pe > .15 or ce <= cs:
            continue
        needed = len(str(cue.get('text', '')).replace('\n', ' ')) / max_cps - (ce - cs)
        slack = pe - ps - len(str(prev.get('text', '')).replace('\n', ' ')) / max_cps
        shift = min(.5, max(0.0, needed), max(0.0, slack - .03))
        if shift > .005:
            cue['start'] = es.clock(cs - shift)
            prev['end'] = es.clock(min(pe, cs - shift - .02))
    return out


def _keep_pair(a, b):
    """Do not break a name or a number from its unit."""
    x, y = _said(a), _said(b)
    units = {'day', 'days', 'hour', 'hours', 'minute', 'minutes', 'dollar', 'dollars', 'bucks',
             'mile', 'miles', 'percent', 'degree', 'degrees'}
    return ((x.isdigit() or x in {'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
                                  'nine', 'ten', 'twelve', 'twenty'}) and y in units) or (
        a[:1].isupper() and b[:1].isupper() and not a.endswith(('.', '?', '!')))


FILLERS = {'um', 'uh', 'umm', 'uhh', 'er', 'erm', 'hmm', 'mm', 'mhm', 'ah'}


def _parts(token):
    """(lead punctuation, the word, trail punctuation)."""
    m = re.match(r"^(\W*)(.*?)(\W*)$", str(token))
    return m.group(1), m.group(2), m.group(3)


def _said(token):
    """A word as heard, for matching fixes: lower case, letters, digits and apostrophes only ('A/C.' -> 'ac')."""
    return re.sub(r"[^\w']+", '', str(token).lower().replace('’', "'")).strip("'")


def _fix_table(fix):
    """{'heard': 'Written'} -> {('heard',): 'Written', ('wonder', 'lodge'): 'Wanderlodge'}: a key may be several
    words; matched in any case, punctuation aside."""
    table = {}
    for k, v in (fix or {}).items():
        said = tuple(_said(x) for x in str(k).split() if _said(x))
        if said and v is not None and str(v).strip():
            table[said] = str(v).strip()
    return table


def apply_fixes(words, fix, key='w', end='t1', group='id', counts=None):
    """Spelling fixes on recognised words: whole words or phrases ({'jamy': 'Jamie', 'ac': 'A/C', 'wonder lodge':
    'Wanderlodge'}), any case, punctuation kept. A phrase becomes one word spanning its words' time (never across a
    cut: words with different `group` values). counts (a dict) gets {written: times fixed}."""
    table = _fix_table(fix)
    longest = max((len(k) for k in table), default=0)
    out, i = [], 0
    while i < len(words):
        for n in range(min(longest, len(words) - i), 0, -1):
            span = words[i:i + n]
            if n > 1 and group and len({x.get(group) for x in span}) > 1:
                continue
            written = table.get(tuple(_said(x[key]) for x in span))
            if written is None:
                continue
            fixed = {**span[0], key: _parts(span[0][key])[0] + written + _parts(span[-1][key])[2]}
            if n > 1 and end in span[-1]:
                fixed[end] = span[-1][end]
            out.append(fixed)
            if counts is not None:
                counts[written] = counts.get(written, 0) + 1
            i += n
            break
        else:
            out.append(words[i])
            i += 1
    return out


def fix_words(words, fix=None, fillers=True, counts=None):
    """Spelling fixes (apply_fixes: words or phrases, any case, punctuation kept) and, unless fillers is true,
    without filler sounds (um, uh...). words: [{'w', 't0', 't1', 'id', ...}]."""
    if not fillers:
        words = [w for w in words if _parts(w['w'])[1].lower() not in FILLERS]
    return apply_fixes(list(words), fix, counts=counts)


def style_fixes(style):
    """A style's caption spelling list (its captions.corrections, e.g. from My Looks: {heard: written}), or {}.
    style: a pack name, a Kit, or None (no style)."""
    if not style:
        return {}
    try:
        import letitedit.looks.look_library as look_library
        kit = look_library.kit(style) if isinstance(style, str) else style
    except Exception:  # noqa: BLE001 - a missing or broken pack: no fixes from it (the edit tools report packs)
        return {}
    got = (kit.get('captions') or {}).get('corrections') or {}
    if isinstance(got, list):     # [{heard, written}] or ["heard -> written"], should a pack be written that way
        rows = {}
        for r in got:
            if isinstance(r, dict) and r.get('heard'):
                rows[r['heard']] = r.get('written')
            elif isinstance(r, str) and '->' in r:
                a, b = r.split('->', 1)
                rows[a.strip()] = b.strip()
        got = rows
    return {str(k): str(v) for k, v in got.items() if k and v} if isinstance(got, dict) else {}


def caption_fixes(style, given=None, use_style=True):
    """The spelling fixes captions use: the style's list (style_fixes) unless use_style is false, with the ones given
    to the call on top (they win on the same words)."""
    out = dict(style_fixes(style)) if use_style else {}
    given = {str(k): str(v) for k, v in (given or {}).items() if k and v is not None}
    low = {k.lower(): k for k in out}
    for k, v in given.items():
        out.pop(low.get(k.lower(), k), None)
        out[k] = v
    return out


def captions_from_speech(script, chunk='sentence', max_chars=42, max_lines=2, pause=0.6, min_len=0.8, max_len=6.0,
                         with_words=False, fix=None, fillers=False, counts=None):
    """Caption cues for everything said on the timeline. chunk: 'sentence' (up to two lines, broken at pauses and
    sentence ends) or 'short' (a short spoken phrase on one line). with_words adds each cue's words with their
    timeline times: 'words': [[text, start, end], ...]. fix: {'heard': 'Written'} spelling fixes (words or phrases;
    caption_fixes() adds a style's list); counts gets {written: times}; fillers: keep um/uh (left out by default)."""
    words = _sentence_starts(fix_words(timeline_words(script), fix, fillers, counts))
    if chunk == 'short':
        max_chars, max_lines, max_words = min(int(max_chars), 22), 1, 6
    else:
        max_words = 99
    limit = max_chars * max_lines
    cues, cur = [], []

    from letitedit.footage.speech import PRONOUNS

    def flush():
        if cur:
            texts = [PRONOUNS.get(w['w'].lower(), w['w']) for w in cur]
            prev = cues[-1] if cues else None
            if prev is None or prev['id'] != cur[0]['id'] or prev['text'][-1:] in '.?!' or cur[0]['t0'] - prev['e'] > pause:
                texts[0] = texts[0][:1].upper() + texts[0][1:]
            cues.append({'s': cur[0]['t0'], 'e': cur[-1]['t1'], 'id': cur[0]['id'],
                         'text': _lines(texts, max_chars, max_lines),
                         'words': [[x, w['t0'], w['t1']] for x, w in zip(texts, cur)]})
            cur.clear()
    for w in words:
        if cur:
            prev = cur[-1]
            text_len = len(' '.join(x['w'] for x in cur)) + 1 + len(w['w'])
            hard = w['id'] != prev['id'] or w['t0'] - prev['t1'] > pause or prev['w'].rstrip().endswith(('.', '?', '!'))
            full = text_len > limit or len(cur) >= max_words or w['t1'] - cur[0]['t0'] > max_len
            if hard or (full and not _keep_pair(prev['w'], w['w'])):
                # Pull a dependent word into the next phrase when the current cue has room to give it up.
                carry = None
                if not hard and len(cur) > 1 and _dangling(prev['w']) and not _keep_pair(cur[-2]['w'], prev['w']):
                    carry = cur.pop()
                flush()
                if carry is not None:
                    cur.append(carry)
        cur.append(w)
    flush()
    # A lone word joins only within its clip and sentence. Keeping the spoken words wins over a soft line limit.
    k = 0
    while k < len(cues):
        c = cues[k]
        if len(c['words']) == 1 and len(cues) > 1:
            nxt = cues[k + 1] if k + 1 < len(cues) else None
            prv = cues[k - 1] if k > 0 else None
            to = None
            if (nxt and nxt['id'] == c['id'] and nxt['s'] - c['e'] <= pause and len(nxt['words']) < max_words
                    and c['text'][-1:] not in '.?!'):
                to = 'next'
            elif (prv and prv['id'] == c['id'] and c['s'] - prv['e'] <= pause and len(prv['words']) < max_words
                    and prv['text'][-1:] not in '.?!'):
                to = 'prev'
            if to:
                a, b = (c, nxt) if to == 'next' else (prv, c)
                words = a['words'] + b['words']
                merged = {'s': a['s'], 'e': b['e'], 'id': b['id'], 'words': words,
                          'text': _lines([x for x, _, _ in words], max_chars, max_lines)}
                lo = k if to == 'next' else k - 1
                cues[lo:lo + 2] = [merged]
                k = lo + 1
                continue
        k += 1
    # timing: hold each cue a little after its last word, at least min_len, never over the next cue or past its clip
    ends = {}
    for t in script['tracks']:
        for it, s, e in layout(t):
            if it.get('id'):
                ends[it['id']] = e
    out = []
    for k, c in enumerate(cues):
        nxt = cues[k + 1]['s'] if k + 1 < len(cues) else float('inf')
        end = max(c['e'] + 0.15, c['s'] + min_len)
        end = min(end, nxt - 0.04, ends.get(c['id'], end))
        if end - c['s'] >= 0.15:
            cue = {'start': es.clock(c['s']), 'end': es.clock(end), 'text': c['text']}
            if with_words:
                cue['words'] = [[x, round(a, 3), round(min(b, end), 3)] for x, a, b in c['words']]
            out.append(cue)
    # Lend a little display time across a phrase boundary when the next cue would read too fast.
    # The text may appear slightly ahead of its first word; the preceding cue keeps its own reading time.
    for k in range(1, len(out)):
        prev, cur_cue = out[k - 1], out[k]
        ps, pe = es.to_seconds(prev['start']), es.to_seconds(prev['end'])
        cs, ce = es.to_seconds(cur_cue['start']), es.to_seconds(cur_cue['end'])
        gap = cs - pe
        if gap > 0.25 or ce <= cs:
            continue
        need = ce - len(cur_cue['text']) / 20.0
        slack = (pe - ps) - len(prev['text']) / 20.0
        shift = min(0.15, max(0.0, cs - need), max(0.0, gap - 0.02) + max(0.0, slack - 0.02))
        if shift > 0.005:
            cur_cue['start'] = es.clock(cs - shift)
            prev['end'] = es.clock(min(pe, cs - shift - 0.02))
    return out


# ---------------------------------------------------------------- given cues on the timeline's words

def _letters(text):
    return ''.join(ch for ch in str(text).lower() if ch.isalnum())


def timeline_voice(script):
    """Voiced stretches on the timeline [(t0, t1)], from each speech clip's voice detection, cut to what plays."""
    spans = []
    for t in script['tracks']:
        if NOT_SPEECH.search(t['name']) or t.get('hide') in ('audio', 'both'):
            continue
        for it, s, e in layout(t):
            it = played_clip(it)
            if 'clip' not in it or it.get('reverse') or _muted(it) or _effect_file(it):
                continue
            speed = float(it.get('speed', 1.0))
            if speed > 1.5:
                continue
            a, b = float(it['in']), float(it['out'])
            for x, y in _voice(it['clip']) or []:
                if y > a and x < b:
                    spans.append((s + (max(x, a) - a) / speed, s + (min(y, b) - a) / speed))
    return sorted(spans)


ALIGN_WINDOW_S = 1.5    # a cue's words are looked for this far around its given times
ALIGN_MIN_SHARE = 0.6   # share of a cue's letters heard there for it to move (or ALIGN_MIN_WORDS of its words, and half)
ALIGN_MIN_WORDS = 2
TOUCHING_S = 0.045      # given cues this close (about a frame) were meant to follow each other


def _match(letters, tokens, words, lo, hi):
    """Words lo..hi heard in a cue's letters: (first, last, cue position of first's first letter, cue position of
    last's last letter), or None when under ALIGN_MIN_SHARE of the letters are heard and fewer than ALIGN_MIN_WORDS
    (and half) of its words are heard whole (a long word the transcript lost, as across a cut)."""
    chars, owner = [], []
    for i in range(lo, hi + 1):
        for ch in _letters(words[i]['w']):
            chars.append(ch)
            owner.append(i)
    blocks = [b for b in difflib.SequenceMatcher(None, letters, ''.join(chars), autojunk=False).get_matching_blocks()
              if b.size >= 2]
    near = {_letters(words[i]['w']) for i in range(lo, hi + 1)}
    whole = sum(t in near for t in tokens)
    if (sum(b.size for b in blocks) < ALIGN_MIN_SHARE * len(letters)
            and not (whole >= ALIGN_MIN_WORDS and 2 * whole >= len(tokens))):
        return None
    hit, first_pos, last_pos = {}, {}, {}
    for b in blocks:
        for j in range(b.size):
            i = owner[b.b + j]
            hit[i] = hit.get(i, 0) + 1
            first_pos.setdefault(i, b.a + j)
            last_pos[i] = b.a + j
    heard = [i for i in sorted(hit) if hit[i] >= max(1, len(_letters(words[i]['w'])) // 2)]
    if not heard:
        return None
    return heard[0], heard[-1], first_pos[heard[0]], last_pos[heard[-1]]


def align_cues_to_words(script, cues, words=None, voice=None):
    """Given caption cues ({start, end, text}) with each start and end moved to the words they show, as said on this
    timeline (the cached word times of its clips, so after every cut). Text, grouping and order are kept.

    - start: the first word's start; when the cue's first words are not in the transcript, the voice's onset between
      the word before and the first word heard (else the given start, kept between those two);
    - end: the next cue's new start when the given cues touched; otherwise the given end, never before the last
      word's voiced end, never past the next cue's start;
    - a cue with timed words, with under 60% of its letters heard near its given times (unless two or more of its
      words, and half, are heard whole), or that would get shorter than 0.15 s keeps its given times.
    Returns (cues, {'aligned', 'moved', 'kept', 'largest_move_s'})."""
    if words is None:
        words = timeline_words(script, cached_only=True)
    out = [dict(c) for c in cues]
    report = {'aligned': 0, 'moved': 0, 'kept': len(out), 'largest_move_s': 0.0}
    if not words or not out:
        return out, report
    given = [(es.to_seconds(c['start']), es.to_seconds(c['end'])) for c in out]
    plan, cursor = [], 0
    for c, (s, e) in zip(out, given):
        letters = _letters(c.get('text', ''))
        tokens = [_letters(x) for x in str(c.get('text', '')).split() if _letters(x)]
        near = [i for i in range(cursor, len(words))
                if words[i]['t1'] > s - ALIGN_WINDOW_S and words[i]['t0'] < e + ALIGN_WINDOW_S]
        found = (_match(letters, tokens, words, near[0], near[-1])
                 if 'words' not in c and len(letters) >= 2 and tokens and near else None)
        if found is None:
            plan.append(None)
            continue
        first, last, first_at, last_at = found
        plan.append((first, last, first_at < len(tokens[0]), last_at >= len(letters) - len(tokens[-1])))
        cursor = last + 1
    if voice is None and any(p and not p[2] for p in plan):
        voice = timeline_voice(script)
    starts = [s for s, _ in given]
    for k, p in enumerate(plan):
        if not p:
            continue
        first, _, lead_heard, _ = p
        w0 = words[first]['t0']
        if lead_heard:
            starts[k] = w0
            continue
        before = words[first - 1]['t1'] if first > 0 else 0.0
        onsets = [x for x, _ in voice or [] if before <= x < w0]
        starts[k] = onsets[-1] if onsets else min(max(given[k][0], before), w0)
    result = []
    for k, (c, p) in enumerate(zip(out, plan)):
        s0, e0 = given[k]
        nxt = starts[k + 1] if k + 1 < len(out) else None
        touching = k + 1 < len(out) and abs(given[k + 1][0] - e0) <= TOUCHING_S
        if p:
            last = words[p[1]]
            voiced = next((y for x, y in voice or [] if x <= last['t0'] + 0.05 <= y), None)
            word_end = min(last['t1'], voiced) if voiced is not None else last['t1']
            end = nxt if touching and nxt is not None else max(e0, word_end)
        else:
            end = nxt if touching and nxt is not None else e0
        if nxt is not None:
            end = min(end, nxt)
        start = starts[k]
        if end - start < 0.15:
            starts[k], start, end = s0, s0, e0
            if p:
                p = None
        moved = max(abs(start - s0), abs(end - e0))
        if p:
            report['aligned'] += 1
        if moved > 0.0005:
            c['start'], c['end'] = es.clock(round(start, 3)), es.clock(round(end, 3))
            report['moved'] += 1
            report['largest_move_s'] = max(report['largest_move_s'], round(moved, 3))
        result.append(c)
    for prev, cue in zip(result, result[1:]):       # a cue that kept its times never runs under the next one
        if es.to_seconds(prev['end']) > es.to_seconds(cue['start']) >= es.to_seconds(prev['start']) + 0.15:
            prev['end'] = cue['start']
    report['kept'] = len(result) - report['aligned']
    return result, report
