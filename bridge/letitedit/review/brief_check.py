"""Does the edit keep what the person asked for? Checks a brief's hard requirements against a render (its own
transcript) and, when given, the project timeline. Editorial wishes (tone, the viewer's reaction) are listed as
'needs review': code never passes them.

Brief fields this reads (all optional; the letitedit router's brief.json plus these):
  goal, genre or mode, audience, tone, desired_response   editorial, reported for the reviewer
  deliverables: [{kind: short|long, target_s, tolerance}] length within tolerance seconds (tolerance_s also accepted),
                                                        else +/- max(5% of target, 2 s)
  required_lines / must_keep: ["line", {"line": ...}, {"source": file, "from": s, "to": s}, ...]
  must_avoid: ["line", {"source": file, "from": s, "to": s}, ...]
  claims: ["$12", "Wanderlodge", ...]                      exact names and numbers that must be said (and spelled
                                                            right in captions)
  ending: "line" | {"line": ...} | {"source": file, "from": s, "to": s} | free text (needs review)
  narration: "none" | "own voice" | "ai voice ok"
  wordless: true | speech: "none" | "wordless"            no spoken dialogue intended
  required_moments: [{kind: visual|sound|audiovisual, description: text}]
  ending also accepts a typed moment, judged by the reviewer rather than the transcript
  protected: [{"source": file, "from": s, "to": s}]        source ranges that, when used, stay whole
Results: {requirements: [{id, kind, requirement, state: pass|fail|unknown, evidence, why}], counts}.
"""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

_UNITS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen '
                                     'fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * i for i, w in enumerate('_ _ twenty thirty forty fifty sixty seventy eighty ninety'.split()) if w != '_'}
LINE_MATCH = 0.8          # share of a line's words that must be heard, in order
NAME_NEAR = 0.8           # a claim without digits heard this close (character similarity) is 'listen to confirm'
AI_VOICE = re.compile(r'(^|[\\/_. -])(tts|voice[-_ ]?over|ai[-_ ]?voice|narration|dots-tts|chatterbox)', re.I)


# ---------------------------------------------------------------- brief loading

def _journal_brief_time(journal):
    """When the newest brief note in the journal was written (seconds since 1970), or 0."""
    import calendar
    import time as _time
    newest = 0
    for line in journal.read_text(encoding='utf-8-sig', errors='replace').splitlines():
        try:
            entry = json.loads(line)
            text = entry.get('text') or ''
            body = text.split(':', 1)[1] if text.lower().startswith('brief:') else text
            if body.strip().startswith('{') and any(k in json.loads(body) for k in ('goal', 'deliverables', 'required_lines', 'must_keep')):
                newest = max(newest, calendar.timegm(_time.strptime(entry['time'], '%Y-%m-%dT%H:%M:%SZ')))
        except (ValueError, KeyError, AttributeError, TypeError):
            continue
    return newest


def load(brief=None, project=None):
    """The brief as a dict: a dict, JSON text, a brief.json path, brief.json next to the project, or the newest
    project-journal note that is a brief (JSON with goal/deliverables/required_lines, optionally after 'brief:')."""
    if isinstance(brief, dict):
        return brief
    if isinstance(brief, str) and brief.strip().startswith('{'):
        return json.loads(brief)
    if brief:
        return json.loads(Path(brief).read_text(encoding='utf-8-sig'))
    if project:
        p = Path(project)
        import letitedit.timeline.project_journal as project_journal
        side = Path(project_journal.folder(p))
        # the brief as it stands now: the newest file, unless a brief noted in the journal is newer still
        files = [c for c in (p.parent / 'brief.json', p.with_suffix('') / 'brief.json', side / 'brief.json') if c.is_file()]
        newest = max(files, key=lambda c: c.stat().st_mtime) if files else None
        journal = side / 'journal.jsonl'
        if newest and not (journal.is_file() and _journal_brief_time(journal) > newest.stat().st_mtime):
            return json.loads(newest.read_text(encoding='utf-8-sig'))
        if journal.is_file():
            for line in reversed(journal.read_text(encoding='utf-8-sig', errors='replace').splitlines()):
                try:
                    text = json.loads(line).get('text') or ''
                except ValueError:
                    continue
                body = text.split(':', 1)[1] if text.lower().startswith('brief:') else text
                if body.strip().startswith('{'):
                    try:
                        data = json.loads(body)
                    except ValueError:
                        continue
                    if any(k in data for k in ('goal', 'deliverables', 'required_lines', 'must_keep')):
                        return data
    return None


# ---------------------------------------------------------------- words

def _numbers(tokens):
    """Spelled-out numbers to digits ("twelve" -> "12", "twenty five" -> "25", "two hundred" -> "200")."""
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in _UNITS or t in _TENS:
            value = _UNITS.get(t, _TENS.get(t, 0))
            i += 1
            if t in _TENS and i < len(tokens) and tokens[i] in _UNITS and _UNITS[tokens[i]] < 10:
                value += _UNITS[tokens[i]]
                i += 1
            while i < len(tokens) and tokens[i] in ('hundred', 'thousand'):
                value *= 100 if tokens[i] == 'hundred' else 1000
                i += 1
            out.append(str(value))
        else:
            out.append(t)
            i += 1
    return out


SAME_WORD = {'bucks': 'dollars', 'buck': 'dollars', 'dollar': 'dollars', 'percent': '%', 'per cent': '%'}


def words(text):
    """Normalised words for matching: lower case, Unicode letters and digits, $12 -> 12 dollars ("12 bucks" too),
    numbers as digits."""
    text = re.sub(r'\$\s?(\d[\d,.]*)', r'\1 dollars', str(text))
    text = re.sub(r'(\d),(\d{3})', r'\1\2', text)
    return [SAME_WORD.get(w, w) for w in _numbers(re.findall(r"[^\W_]+(?:'[^\W_]+)?", text.lower()))]


def squashed(text):
    """Lower case with spaces and punctuation removed: "Let It Edit" and "letitedit" are the same name."""
    return re.sub(r'[\W_]+', '', str(text).lower())


def spelled_in(claim, text):
    """A name is on screen when the captions carry it in any case or with other spacing."""
    return bool(text) and (claim.lower() in text.lower() or (bool(squashed(claim)) and squashed(claim) in squashed(text)))


def find_line(line, cues):
    """Best place a line is heard: (score 0-1, start_s, end_s, heard text). cues = [(start, end, text)]."""
    want = words(line)
    if not want:
        return 0.0, None, None, ''
    stream = []          # (word, cue index)
    for ci, (_, _, text) in enumerate(cues):
        stream += [(w, ci) for w in words(text)]
    if not stream:
        return 0.0, None, None, ''
    best = (0.0, None, None, '')
    n = len(want)
    for size in {max(1, n - 2), n, n + 3}:
        for i in range(0, max(1, len(stream) - size + 1)):
            window = stream[i:i + size]
            got = [w for w, _ in window]
            m = SequenceMatcher(None, want, got, autojunk=False)
            score = sum(b.size for b in m.get_matching_blocks()) / n
            if score > best[0]:
                a, b = window[0][1], window[-1][1]
                best = (score, cues[a][0], cues[b][1], ' '.join(got))
    return best


def find_split_name(claim, cues):
    """Recognise a one-word name transcribed as adjacent ordinary words.

    Speech has no spaces or capitals: Whisper writes "let it edit" for
    LetItEdit. This checks only literal concatenation, not fuzzy matches.
    """
    target = words(claim)
    if len(target) != 1 or len(target[0]) < 5 or not target[0].isalpha():
        return None
    stream = [(word, ci) for ci, (_, _, line) in enumerate(cues) for word in words(line)]
    for i in range(len(stream)):
        joined = ''
        for j in range(i, min(i + 4, len(stream))):
            if stream[j][1] != stream[i][1]:
                break
            joined += stream[j][0]
            if len(joined) >= len(target[0]):
                if j > i and joined == target[0]:
                    return (1.0, cues[stream[i][1]][0], cues[stream[j][1]][1],
                            ' '.join(word for word, _ in stream[i:j + 1]))
                break
    return None


# ---------------------------------------------------------------- the timeline

def _same_file(a, b):
    if not a or not b:
        return False
    a, b = str(a).replace('/', '\\').lower(), str(b).replace('/', '\\').lower()
    return a == b or (('\\' not in b) and a.endswith('\\' + b)) or (('\\' not in a) and b.endswith('\\' + a))


def uses(timeline):
    """[(resource, source_from_s, source_to_s, timeline_from_s, timeline_to_s, track name)] for every media item."""
    out = []
    fps = timeline.fps
    for t in timeline.tracks:
        for it in t.items:
            if not it.resource or it.service in ('color', 'transition'):
                continue
            speed = it.speed or 1.0
            out.append((it.resource, it.in_ / fps * abs(speed), (it.out + 1) / fps * abs(speed), it.start / fps,
                        it.end / fps, t.name))
    return out


def _range_req(req):
    return isinstance(req, dict) and req.get('source') and req.get('from') is not None and req.get('to') is not None


def speech_cues(cues):
    from letitedit.review.checks import SOUND_LABEL
    return [(start, end, said) for start, end, text in (cues or [])
            if words(said := SOUND_LABEL.sub(" ", str(text)).strip())]


def wordless(brief):
    return (brief or {}).get("wordless") is True or (brief or {}).get("speech") in ("none", "wordless")


def moment_description(entry):
    if isinstance(entry, dict) and entry.get("kind") in ("visual", "picture", "sound", "audiovisual"):
        description = entry.get("description")
        if isinstance(description, str) and description.strip():
            return description.strip()
    return None


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


# ---------------------------------------------------------------- hearing the render

CONFIDENT_P = 0.7       # the editing transcript's own confidence in a word: sounds it reads as words score far lower
HEAR_SLACK_S = 0.75     # a word counts as heard when the render's transcript has speech this close to it
TALK_SHARE = 0.2        # confident words over at least this share of the video: it talks (not a few voices under music)
UNHEARD_MIN_S = 5.0     # talk the render's transcript heard nothing in: at least this long ...
UNHEARD_SHARE = 0.25    # ... and this share of the talk, to call the video partly heard
NOT_HEARD = "the review couldn't hear the video's speech, so this wasn't checked: listen to confirm"


def said_cues(said, least=CONFIDENT_P):
    """The timeline's words (timeline_speech.timeline_words rows, in render time) the editing transcript is at least
    `least` sure of, as one cue each: [(t0, t1, word)]."""
    out = []
    for w in said or ():
        try:
            if float(w.get('p', 1.0)) >= least and words(w.get('w', '')):
                out.append((float(w['t0']), float(w['t1']), str(w['w'])))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def heard_near(cues, a, b, slack=HEAR_SLACK_S):
    """True when the render's transcript has speech within slack seconds of a-b."""
    return any(s - slack < b and e + slack > a for s, e, _ in speech_cues(cues))


def _stretches(said_c, gap=1.0):
    out = []
    for a, b, _ in said_c:
        if out and a - out[-1][1] < gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _unheard(stretches, cues, slack=HEAR_SLACK_S):
    """The parts of the stretches that no speech cue of the render's transcript is within slack seconds of."""
    heard = sorted((s - slack, e + slack) for s, e, _ in speech_cues(cues))
    out = []
    for a, b in stretches:
        at = a
        for s, e in heard:
            if e <= at:
                continue
            if s >= b:
                break
            if s > at:
                out.append([at, s])
            at = max(at, e)
            if at >= b:
                break
        if at < b:
            out.append([at, b])
    return [[round(a, 2), round(b, 2)] for a, b in out if b - a > 0.05]


def _clock(t):
    t = max(0.0, float(t))
    return f'{int(t // 60)}:{t % 60:04.1f}'


def hearing(cues, said=None, duration_s=None, audio=True, wordless=False, why='', said_complete=False, plain=''):
    """Whether the render's own transcript heard its speech. None when it did, or when there is no speech to hear (no
    sound, a wordless brief, a timeline whose own words have no talk, a video whose talk is a few voices under music).
    Otherwise {'whole', 'why', 'plain', 'unheard'}: whole when nothing said can be judged from it (it didn't run, or
    heard no speech in a video that talks), else the stretches of talk it heard nothing in ([[start, end], ...], also
    given when whole). why is technical (it may name a folder); plain is one sentence for the person, with no path.
    cues: the render's transcript, None when it didn't run (why says why; plain, in plain words). said: the timeline's
    words in render time (timeline_speech.timeline_words rows), or None without a project; only the words the editing
    transcript is confident of count as talk. said_complete: every clip with sound on a speech track had its words
    transcribed, so no talk in said means the timeline has none."""
    if not audio or wordless:
        return None
    stretches = _stretches(said_cues(said))
    talk_s = sum(b - a for a, b in stretches)
    if cues is None:
        if said is not None and said_complete and not stretches:
            return None         # the timeline's own words, all of them known, have no talk: there was nothing to hear
        return {'whole': True, 'unheard': [[round(a, 2), round(b, 2)] for a, b in stretches],
                'why': "the review's transcript didn't run" + (f': {why}' if why else ''),
                'plain': "The review couldn't hear the speech in this video, so what is said wasn't checked"
                         + (f': {plain}.' if plain else '.')}
    if not stretches or (duration_s and talk_s < TALK_SHARE * float(duration_s)):
        return None
    missed = _unheard(stretches, cues)
    missed_s = sum(b - a for a, b in missed)
    if not speech_cues(cues):
        return {'whole': True, 'unheard': missed,
                'why': f"the review's transcript heard no speech, where the timeline's own words have {talk_s:.0f} s of it",
                'plain': "The review couldn't hear the speech in this video (its speech check heard no words, though "
                         "the video talks), so what is said wasn't checked."}
    if missed_s >= UNHEARD_MIN_S and missed_s >= UNHEARD_SHARE * talk_s:
        where = ', '.join(f'{_clock(a)}-{_clock(b)}' for a, b in missed[:6]) + (' and more' if len(missed) > 6 else '')
        return {'whole': False, 'unheard': missed,
                'why': f"the review's transcript heard nothing at {where} ({missed_s:.0f} s of the {talk_s:.0f} s of "
                       "speech the timeline's own words have)",
                'plain': f"The review couldn't hear the speech at {where}, so what is said there wasn't checked."}
    return None


def _inside(at, gaps):
    """True when at least half of at (start, end) falls in the gaps."""
    a, b = at
    span = max(0.1, b - a)
    return sum(_overlap(a, b, float(x), float(y)) for x, y in gaps or ()) >= 0.5 * span


class _Hearing:
    """What the brief check can say of a spoken requirement the render's transcript didn't hear. Only where hearing()
    found it couldn't hear (the whole video, or the stretch the requirement is in) is that 'listen to confirm': in a
    video the review heard, a line it didn't hear is a problem with the edit (cut, or lost under music)."""

    def __init__(self, cues, said, deaf, said_complete=False, ran=True):
        self.cues, self.deaf = cues, deaf
        self.said = said_cues(said, least=0.0)        # every word, to find a requirement by
        self.whole = bool(deaf and deaf.get('whole'))
        self.gaps = [] if not deaf or self.whole else list(deaf.get('unheard') or [])
        self.complete = bool(said is not None and said_complete)
        self.talks = bool(said_cues(said))
        # no transcript, and hearing() found nothing to hear (the timeline's own words, all known, have no talk): a
        # spoken requirement is judged from the timeline's words, never worded as if the render were heard
        self.unrun = not ran and not self.whole
        self.unheard = []

    def unrun_evidence(self, line, exact=False, tail_from=None):
        at = self.where_said(line, exact, tail_from)
        return "the review's transcript didn't run; " + (
            _missed_evidence(at) if at else
            "the timeline's own words have no talk" if self.complete and not self.talks else
            "the timeline's own words don't have it" if self.complete else "the edit's words aren't all known")

    def unrun_why(self):
        return ("the review's transcript didn't run, and the timeline's own words don't have it" if self.complete
                else "the review's transcript didn't run, and nothing shows it in the edit")

    def where_said(self, line, exact=False, tail_from=None):
        """(start, end) where the timeline's own words have line (ending after tail_from, if given), or None."""
        # one cue a word: the words just before tail_from stay in, so a line that ends in the tail is found whole
        since = None if tail_from is None else tail_from - 1.0 - 0.6 * len(words(line))
        said = [c for c in self.said if since is None or c[1] >= since]
        if not said:
            return None
        score, s, e, _ = find_line(line, said)
        if score < (1.0 if exact else LINE_MATCH):
            split = find_split_name(line, said) if exact else None
            if not split:
                return None
            score, s, e, _ = split
        if s is None or (tail_from is not None and e < tail_from):
            return None
        return s, e

    def evidence(self, line, exact=False, tail_from=None):
        at = self.where_said(line, exact, tail_from)
        if at:
            return _missed_evidence(at)
        return "not in the timeline's own words either" if self.said else ''

    def by_ear(self, line, exact=False, tail_from=None):
        """{'by_ear': [start, end]} where the timeline's own words have line, for a finding to confirm it by ear; else {}."""
        at = self.where_said(line, exact, tail_from)
        return {'by_ear': [round(at[0], 2), round(at[1], 2)]} if at else {}

    def cut(self, line):
        """True when the timeline's own words, known for every clip with sound, don't have line: it was cut."""
        return self.complete and self.where_said(line) is None

    def missed(self, kind, line, exact=False, tail_from=None):
        """Where the timeline's own words have line inside a stretch hearing() found the render's transcript heard
        nothing in (a partly heard video): (start, end), recorded in unheard. Else None."""
        if not self.gaps:
            return None
        at = self.where_said(line, exact, tail_from)
        if at and _inside(at, self.gaps):
            self.unheard.append({'kind': kind, 'requirement': line, 'at': [round(at[0], 2), round(at[1], 2)]})
            return at
        return None


def said_at(line, said):
    """(start, end) where the timeline's own words (timeline_speech rows) have line, else None."""
    return _Hearing(None, said, None).where_said(line)


def unheard_at(line, said, deaf):
    """(start, end) where the timeline's own words have line inside a stretch hearing() found unheard, else None."""
    return _Hearing(None, said, deaf).missed('line', line)


def ends_unheard(said, deaf, slack=1.0):
    """True when hearing() found the last of the timeline's talk unheard: the render's last heard words aren't its end."""
    if not deaf or deaf.get('whole') or not deaf.get('unheard'):
        return False
    stretches = _stretches(said_cues(said))
    return bool(stretches) and float(deaf['unheard'][-1][1]) >= stretches[-1][1] - slack


def _missed_why(at):
    return (f"the review's transcript heard nothing at {at[0]:.1f}-{at[1]:.1f} s, where the timeline's own words "
            "have it: listen to confirm")


def _missed_evidence(at):
    return f"the timeline's own words have it at {at[0]:.1f}-{at[1]:.1f} s"


CUT_WHY = "the timeline's own words don't have it: cut from the edit"
UNRUN_WHY = "the review's transcript didn't run, so this wasn't checked: listen to confirm"


# ---------------------------------------------------------------- the check

def _check_required(brief, used, add, cues, written_from, hear):
    """Check required words and source moments without treating visual wishes as speech."""
    required_lines = list(brief.get('required_lines') or [])
    for entry in required_lines + list(brief.get('must_keep') or []) + list(brief.get('required_moments') or []):
        if _range_req(entry):
            label = f"{Path(entry['source']).name} {entry['from']}-{entry['to']} s"
            if used is None:
                add('must_keep', label, 'unknown', why='needs the project to see which source ranges are used')
                continue
            span = float(entry['to']) - float(entry['from'])
            got = sum(_overlap(a, b, float(entry['from']), float(entry['to'])) for r, a, b, *_ in used
                      if _same_file(r, entry['source']))
            share = got / span if span > 0 else 0
            where = [f'{ta:.1f}-{tb:.1f} s' for r, a, b, ta, tb, _ in used
                     if _same_file(r, entry['source']) and _overlap(a, b, float(entry['from']), float(entry['to'])) > 0]
            add('must_keep', label, 'pass' if share >= 0.8 else 'fail',
                f"{share:.0%} of it is in the edit" + (f" at {', '.join(where)}" if where else ''),
                '' if share >= 0.8 else 'the moment is missing or cut short')
            continue
        moment = moment_description(entry)
        if (hear.whole and isinstance(entry, str) and entry not in required_lines and not wordless(brief)
                and hear.where_said(entry)):
            add('must_keep', entry, 'unknown', hear.evidence(entry), NOT_HEARD,     # said on the timeline: a line
                **hear.by_ear(entry))
            continue
        if (moment and entry not in required_lines) or (isinstance(entry, str) and entry not in required_lines
                      and (wordless(brief) or not speech_cues(cues))):
            add('must_keep', moment or entry, 'unknown',
                why='picture or sound moment: the reviewer must judge it in the export')
            continue
        line = entry.get('line') if isinstance(entry, dict) else str(entry)
        if hear.whole:
            if hear.cut(line) and not (written_from is not None
                                       and find_line(line, [(0, 0, written_from)])[0] < LINE_MATCH):
                add('must_keep', line, 'fail', hear.evidence(line), CUT_WHY)
            else:
                add('must_keep', line, 'unknown', hear.evidence(line), NOT_HEARD, **hear.by_ear(line))
            continue
        if hear.unrun:
            if hear.where_said(line):
                add('must_keep', line, 'unknown', hear.unrun_evidence(line), UNRUN_WHY, **hear.by_ear(line))
            elif written_from is not None and find_line(line, [(0, 0, written_from)])[0] < LINE_MATCH:
                add('must_keep', line, 'unknown', hear.unrun_evidence(line),
                    "not the person's own words: the reviewer judges whether the video delivers it")
            else:
                add('must_keep', line, 'fail', hear.unrun_evidence(line), CUT_WHY if hear.complete else hear.unrun_why())
            continue
        score, s, e, heard = find_line(line, cues)
        if score >= LINE_MATCH:
            add('must_keep', line, 'pass', f'heard at {s:.1f}-{e:.1f} s: "{heard}"')
        elif written_from is not None and find_line(line, [(0, 0, written_from)])[0] < LINE_MATCH:
            add('must_keep', line, 'unknown', f'closest ({score:.0%}): "{heard}"',
                "not the person's own words and not said as written: the reviewer judges whether the video delivers it")
        elif at := hear.missed('must_keep', line):
            add('must_keep', line, 'unknown', _missed_evidence(at), _missed_why(at), **hear.by_ear(line))
        else:
            add('must_keep', line, 'fail', f'closest ({score:.0%}): "{heard}"' + (f' at {s:.1f} s' if s is not None else ''),
                'not heard in the render (cut, or lost under music)')


def _check_avoided(brief, used, add, cues, hear):
    """Check excluded words and source ranges."""
    for entry in brief.get('must_avoid') or []:
        if _range_req(entry):
            label = f"{Path(entry['source']).name} {entry['from']}-{entry['to']} s"
            if used is None:
                add('must_avoid', label, 'unknown', why='needs the project to see which source ranges are used')
                continue
            hits = [(ta, tb) for r, a, b, ta, tb, _ in used
                    if _same_file(r, entry['source']) and _overlap(a, b, float(entry['from']), float(entry['to'])) > 0.2]
            add('must_avoid', label, 'fail' if hits else 'pass',
                ', '.join(f'used at {a:.1f}-{b:.1f} s' for a, b in hits) or 'not used')
            continue
        line = entry.get('line') if isinstance(entry, dict) else str(entry)
        if hear.whole:          # never 'not heard', so kept out
            add('must_avoid', line, 'unknown', hear.evidence(line), NOT_HEARD, **hear.by_ear(line))
            continue
        if hear.unrun:          # kept out only when the timeline's own words, all known, don't have it
            at = hear.where_said(line)
            add('must_avoid', line, 'pass' if hear.complete and not at else 'unknown', hear.unrun_evidence(line),
                UNRUN_WHY if at else '', **hear.by_ear(line))
            continue
        score, s, e, heard = find_line(line, cues)
        if score < LINE_MATCH and (at := hear.missed('must_avoid', line)):
            add('must_avoid', line, 'unknown', _missed_evidence(at), _missed_why(at), **hear.by_ear(line))
            continue
        add('must_avoid', line, 'fail' if score >= LINE_MATCH else 'pass',
            f'heard at {s:.1f}-{e:.1f} s: "{heard}"' if score >= LINE_MATCH else 'not heard')


def _check_claims(brief, cues, captions, editor_words, written_from, add, hear):
    """Check exact claims and caption spelling with transcription uncertainty intact."""
    for claim in brief.get('claims') or []:
        if hear.whole:
            add('claim', claim, 'unknown', hear.evidence(claim, exact=True), NOT_HEARD, **hear.by_ear(claim, exact=True))
            continue
        if hear.unrun:
            at = hear.where_said(claim, exact=True)
            add('claim', claim, 'unknown' if at else 'fail', hear.unrun_evidence(claim, exact=True),
                UNRUN_WHY if at else hear.unrun_why(), **hear.by_ear(claim, exact=True))
            continue
        score, s, e, heard = find_line(claim, cues)
        if score < 1.0:
            split = find_split_name(claim, cues)
            if split:
                score, s, e, heard = split
        if score < 1.0:
            # a name heard almost right ("let it add it" for LetItEdit) is probably the transcriber's mistake: listen to it;
            # a number must match exactly
            near = (heard and not re.search(r'\d', claim) and SequenceMatcher(
                None, ' '.join(words(claim)), ' '.join(words(heard))).ratio() >= NAME_NEAR)
            if near:
                add('claim', claim, 'unknown', f'heard as "{heard}" at {s:.1f} s',
                    'probably said: the transcriber may have misheard the name; listen to confirm')
            elif not re.search(r'\d', claim) and any(spelled_in(claim, t) for t in (captions, editor_words)):
                add('claim', claim, 'unknown', f'closest in the review\'s transcript: "{heard}"' if heard else '',
                    'the captions or the editing transcript have it; the review\'s smaller speech model did not hear it; listen to confirm')
            elif at := hear.missed('claim', claim, exact=True):
                add('claim', claim, 'unknown', _missed_evidence(at), _missed_why(at), **hear.by_ear(claim, exact=True))
            else:
                add('claim', claim, 'fail', f'closest: "{heard}"' if heard else '', 'not said exactly in the render')
            continue
        evidence = f'said at {s:.1f} s'
        if captions is not None and written_from is not None and not spelled_in(claim, captions):
            pass      # no footage: this Look's words on screen are few and chosen, so a claim said and not shown is kept
        elif captions is not None and re.search(r'\d', claim):
            # a number: the captions show the same amount, in any form ("$12", "12 dollars", "twelve bucks"); a
            # missing or different number fails
            if claim not in captions:
                want, have = words(claim), words(captions)
                if not any(have[i:i + len(want)] == want for i in range(len(have) - len(want) + 1)):
                    add('claim', claim, 'fail', evidence, 'said, but missing from the captions or written as another '
                                                          'number')
                    continue
                evidence += f'; on screen in other words than "{claim}"'
        elif captions is not None:
            if not spelled_in(claim, captions):
                add('claim', claim, 'fail', evidence, 'said, but missing or misspelled in the captions')
                continue
        add('claim', claim, 'pass', evidence)


def _check_ending(brief, used, duration_s, add, cues, tail_from, hear):
    """Check the requested final range, line or visual moment."""
    ending = brief.get('ending')
    if ending:
        if _range_req(ending):
            label = f"end on {Path(ending['source']).name} {ending['from']}-{ending['to']} s"
            if used is None or not duration_s:
                add('ending', label, 'unknown', why='needs the project')
            else:
                last = [u for u in used if u[4] >= duration_s - 0.5 and _same_file(u[0], ending['source'])
                        and _overlap(u[1], u[2], float(ending['from']), float(ending['to'])) > 0]
                add('ending', label, 'pass' if last else 'fail',
                    'the last shot is that range' if last else 'the video ends on something else')
        else:
            moment = moment_description(ending)
            if moment or (isinstance(ending, str) and (wordless(brief) or not speech_cues(cues))):
                add('ending', moment or ending, 'unknown',
                    why='picture or sound ending: the reviewer must judge its final action and release in the export')
                line = None
            else:
                line = ending.get('line') if isinstance(ending, dict) else str(ending)
            if line is None:
                pass
            elif hear.whole and (isinstance(ending, dict) or len(words(line)) <= 14):
                at = hear.where_said(line, tail_from=tail_from)
                if not at and isinstance(ending, dict) and hear.complete:
                    elsewhere = hear.where_said(line)
                    add('ending', line, 'fail', (f"the timeline's own words have it at {elsewhere[0]:.1f} s, not in the "
                                                 'last 15 %') if elsewhere else hear.evidence(line),
                        "the timeline's own words don't end on it")
                else:
                    add('ending', line, 'unknown', hear.evidence(line, tail_from=tail_from), NOT_HEARD,
                        **hear.by_ear(line, tail_from=tail_from))
            elif hear.unrun and isinstance(ending, dict):
                at = hear.where_said(line, tail_from=tail_from)
                add('ending', line, 'unknown' if at else 'fail', hear.unrun_evidence(line, tail_from=tail_from),
                    UNRUN_WHY if at else "the review's transcript didn't run, and the timeline's own words don't end on it",
                    **hear.by_ear(line, tail_from=tail_from))
            elif isinstance(ending, dict) or len(words(line)) <= 14:
                score, s, e, heard = find_line(line, [c for c in cues if tail_from is None or c[1] >= tail_from])
                if score >= LINE_MATCH:
                    add('ending', line, 'pass', f'heard at {s:.1f} s, in the last 15 %')
                elif isinstance(ending, dict) and (at := hear.missed('ending', line, tail_from=tail_from)):
                    add('ending', line, 'unknown', _missed_evidence(at), _missed_why(at),
                        **hear.by_ear(line, tail_from=tail_from))
                else:
                    add('ending', line, 'unknown' if not isinstance(ending, dict) else 'fail',
                        f'not heard in the last 15 % (closest {score:.0%})',
                        'if this describes a picture rather than a line, the reviewer must judge it')
            else:
                add('ending', line, 'unknown', why='describes the ending in words: the reviewer must judge it')


def check(brief, cues, duration_s=None, kind=None, timeline=None, captions=None, editor_words=None, written_from=None,
          fps=30.0, said=None, deaf=None, said_complete=False, transcript_ran=True):
    """brief: dict. cues: the render's transcript [(start_s, end_s, text)]. duration_s/kind: of the render.
    timeline: a timeline_model.Timeline of the project (for source-range requirements and narration), or None.
    captions: the caption text of the project (for spelling of claims), or None.
    editor_words: what the better speech model heard in the project's sources, or None. The transcript in cues comes from a small model,
    so a name it can't find but the captions or these words have is something to confirm by ear, not a claim that wasn't said.
    written_from: for a video with no footage, the person's own description. Such a video has nothing to cut a line out of, so its
    must-keep is held to what the person said: their own words, unheard, are broken; the AI's summary of the story, which no render
    would say word for word, goes to the reviewer. Nor does such a video owe captions: a claim said aloud stands without them.
    said: the timeline's words in render time (timeline_speech.timeline_words rows), or None. deaf: hearing()'s answer,
    or None. said_complete: said has every clip with sound (no clip's words unknown). When the render's transcript can't
    be relied on at all (deaf whole), nothing said is judged from it: claims, lines to keep or avoid and a spoken ending
    are 'unknown', with where the timeline's own words have them ('by_ear': [start, end], to confirm by ear); a required
    line or a spoken ending the timeline's own words, all of them known, don't have fails as cut. When deaf names
    stretches it heard nothing in, a spoken requirement the timeline's own words place there is 'unknown' the same way,
    and listed in the result's 'unheard'. A video the review heard (deaf None) is judged from its transcript alone, as
    always: a required line it didn't hear fails. transcript_ran False with deaf None (no transcript, and nothing to
    hear: the timeline's own words, all known, have no talk): a spoken requirement is judged from the timeline's words,
    in words that say the transcript didn't run."""
    reqs = []
    hear = _Hearing(cues, said, deaf, said_complete, ran=transcript_ran)

    def add(kind_, requirement, state, evidence='', why='', by_ear=None):
        reqs.append({'id': f'{kind_}-{sum(1 for r in reqs if r["kind"] == kind_) + 1}', 'kind': kind_,
                     'requirement': requirement, 'state': state, 'evidence': evidence, 'why': why,
                     **({'by_ear': by_ear} if by_ear else {})})

    used = uses(timeline) if timeline is not None else None
    tail_from = (duration_s or 0) * 0.85 if duration_s else None

    _check_required(brief, used, add, cues, written_from, hear)

    _check_avoided(brief, used, add, cues, hear)

    _check_claims(brief, cues, captions, editor_words, written_from, add, hear)

    _check_ending(brief, used, duration_s, add, cues, tail_from, hear)

    narration = str(brief.get('narration') or '').lower()
    if narration:
        if timeline is None:
            add('narration', narration, 'unknown', why='needs the project')
        elif narration in ('none', 'no', 'no voiceover', 'no narration'):
            voice = [(r, ta) for r, a, b, ta, tb, tname in used if AI_VOICE.search(os.path.basename(r))
                     or AI_VOICE.search(tname) or '\\cache\\models\\' in r.lower().replace('/', '\\')]
            add('narration', 'no voiceover', 'fail' if voice else 'pass',
                ', '.join(f'{Path(r).name} at {t:.1f} s' for r, t in voice[:5]) or
                'no generated voice or voiceover track found (file names and the voice cache checked)')
        elif 'own' in narration:
            voice = [(r, ta) for r, a, b, ta, tb, tname in used if '\\cache\\models\\' in r.lower().replace('/', '\\')]
            add('narration', 'own voice only', 'fail' if voice else 'pass',
                ', '.join(f'{Path(r).name} at {t:.1f} s' for r, t in voice[:5]) or 'no generated voice found')

    for entry in brief.get('protected') or []:
        if not _range_req(entry):
            continue
        label = f"{Path(entry['source']).name} {entry['from']}-{entry['to']} s whole"
        if used is None:
            add('protected', label, 'unknown', why='needs the project')
            continue
        a0, a1 = float(entry['from']), float(entry['to'])
        parts = [u for u in used if _same_file(u[0], entry['source']) and _overlap(u[1], u[2], a0, a1) > 0]
        cut = [u for u in parts if u[1] > a0 + 0.1 or u[2] < a1 - 0.1]
        add('protected', label, 'fail' if cut else 'pass',
            ', '.join(f'only {max(u[1], a0):.1f}-{min(u[2], a1):.1f} s used at {u[3]:.1f} s' for u in cut)
            or ('used whole' if parts else 'not used'))

    for d in brief.get('deliverables') or []:
        if not d.get('target_s') or not duration_s or (kind and d.get('kind') and d['kind'] != kind):
            continue
        target = float(d['target_s'])
        tolerance = d.get('tolerance')
        if tolerance is None:
            tolerance = d.get('tolerance_s')
        tolerance = float(tolerance) if tolerance is not None else max(2.0, .05 * target)
        ok = target - tolerance <= duration_s <= target + tolerance
        add('length', f"{d.get('kind', 'video')} length {duration_s} s; target {target:g} s; "
            f'window {target - tolerance:g}-{target + tolerance:g} s', 'pass' if ok else 'fail',
            f'{duration_s} s', '' if ok else 'length outside the requested window')

    for key in ('goal', 'tone', 'desired_response', 'audience'):
        if brief.get(key):
            add('editorial', f"{key}: {brief[key]}", 'unknown', why='editorial: the reviewer must judge it')

    counts = {s: sum(1 for r in reqs if r['state'] == s) for s in ('pass', 'fail', 'unknown')}
    return {'requirements': reqs, 'counts': counts, **({'unheard': hear.unheard} if hear.unheard else {})}
