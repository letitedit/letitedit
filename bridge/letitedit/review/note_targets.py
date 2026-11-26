"""A revision note's measurable target, kept: the length, the music's level or the captions' size a note asks for,
measured on the cut the review reads and compared with what the note asked.

parse(text)                       the targets one note names: [{kind, change_s | wanted_s | change_db | ratio, ...}].
measure(timeline, duration)       {length_s, music_db, caption_px} of a timeline (edit_script.read) as it stands.
plan(notes, timeline, duration)   each note's targets with their wanted values from the cut before the revision.
keep(project, notes)              plan() on the project as it is now (before the revision), written to its side folder.
check(project, timeline, duration)  each kept target against the cut now: [{note, kind, wanted, delivered, met, line}].
findings(checked)                 a missed target as a measured finding (major): the AI fixes it like a clipped word.
against(finding, checked, duration)  why a finding would undo a note (its fix moves a note's value away from the target,
                                  or it is about the part a note cut), or None.

Tolerances: a length within TOLERANCE_S seconds (or TOLERANCE_SHARE of the change asked, whichever is larger) of its
target; a level within TOLERANCE_DB dB; a size within TOLERANCE_SIZE of the asked size. A join fixed at the clean cut
point nearest the target lands inside them; a join fixed by giving the cut time back doesn't.
"""
import json
import re
from pathlib import Path

FILE = 'note-targets.json'
TOLERANCE_S = 0.25          # about six frames: the distance between the asked cut and the nearest clean pause
TOLERANCE_SHARE = 0.1       # ... or a tenth of a long change ("cut 30 seconds" may land 3 s either side)
TOLERANCE_DB = 1.0          # a level change heard as the one asked
TOLERANCE_SIZE = 0.05       # a size within 5% of the asked size

_NUM = r'(\d+(?:\.\d+)?)'
_SECONDS = r'\s*(?:s|secs?|seconds?)\b'
_CUT = r'\b(?:cut|trim|remove|drop|lose|take off|chop|delete)\b'
LENGTH_CUT = re.compile(_CUT + r"[^.;]{0,30}?\b(last|final|ending|first|opening)\s+" + _NUM + _SECONDS, re.I)
LENGTH_SHORTER = re.compile(r'(?:\b' + _NUM + _SECONDS + r'\s+shorter\b|\bshorter\s+by\s+' + _NUM + _SECONDS + ')', re.I)
LENGTH_WANTED = re.compile(r'\b(?:(under|at most|no (?:more|longer) than|max(?:imum)?)\s+)?' + _NUM + _SECONDS +
                           r'(?:\s+long\b)?', re.I)
LENGTH_CONTEXT = re.compile(r'\b(make|keep|get|bring|cut)\b[^.;]{0,25}\b(it|the video|the short|this|down|to)\b|'
                            r'\b(long|under|at most|no (?:more|longer) than)\b', re.I)
LEVEL = re.compile(r'\b(lower|reduce|drop|turn down|duck|quieter|raise|boost|turn up|louder|increase)\b[^.;]{0,30}?'
                   r'\bmusic\b[^.;]{0,25}?\bby\s+' + _NUM + r'\s*db\b|\bmusic\b[^.;]{0,25}?\b' + _NUM +
                   r'\s*db\s+(quieter|lower|softer|louder|higher|up|down)\b', re.I)
SIZE = re.compile(r'\b(captions?|subtitles?)\b[^.;]{0,40}?\b' + _NUM + r'\s*%\s*(larger|bigger|smaller)\b|'
                  r'\b' + _NUM + r'\s*%\s*(larger|bigger|smaller)\b[^.;]{0,20}?\b(captions?|subtitles?)\b', re.I)
DOWN = {'lower', 'reduce', 'drop', 'turn down', 'duck', 'quieter', 'softer', 'down'}


def seconds(value):
    """A time as a script writes it ('0:24.300', '1:02:03.5', 24.3) in seconds, or None."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value or '').strip().split(':')
    try:
        total = 0.0
        for p in parts:
            total = total * 60 + float(p)
        return total
    except ValueError:
        return None


def parse(text):
    """The measurable targets one note names, in the order found. A note with none gives []."""
    text = str(text or '')
    out = []
    for m in LENGTH_CUT.finditer(text):
        out.append({'kind': 'length', 'change_s': -float(m.group(2)),
                    'part': 'start' if m.group(1).lower() in ('first', 'opening') else 'end',
                    'asked': m.group(0).strip()})
    if not out:
        for m in LENGTH_SHORTER.finditer(text):
            out.append({'kind': 'length', 'change_s': -float(m.group(1) or m.group(2)), 'asked': m.group(0).strip()})
    if not out and LENGTH_CONTEXT.search(text) and not LEVEL.search(text):
        m = LENGTH_WANTED.search(text)
        if m:
            out.append({'kind': 'length', 'wanted_s': float(m.group(2)), 'at_most': bool(m.group(1)),
                        'asked': m.group(0).strip()})
    for m in LEVEL.finditer(text):
        word = (m.group(1) or m.group(4) or '').lower()
        db = float(m.group(2) or m.group(3))
        out.append({'kind': 'music_level', 'change_db': -db if word in DOWN else db, 'asked': m.group(0).strip()})
    for m in SIZE.finditer(text):
        pct = float(m.group(2) or m.group(4))
        word = (m.group(3) or m.group(5)).lower()
        out.append({'kind': 'caption_size', 'ratio': 1 - pct / 100 if word == 'smaller' else 1 + pct / 100,
                    'asked': m.group(0).strip()})
    return out


def _main_level(effects):
    """A clip's own level in dB from its gain effect: the number, or the median of its keyframes (a ramp at the end
    or the start is the fade, not the level). None without a gain."""
    for e in effects or []:
        if isinstance(e, dict) and 'gain' in e:
            g = e['gain']
            if isinstance(g, (int, float)):
                return float(g)
            keys = [k[1] for k in (g or {}).get('keys') or [] if isinstance(k, (list, tuple)) and len(k) > 1
                    and isinstance(k[1], (int, float))]
            if keys:
                keys.sort()
                return float(keys[len(keys) // 2])
    return None


def _ass_sizes(ass):
    sizes, fields = [], None
    for line in str(ass or '').splitlines():
        if line.startswith('Format:') and fields is None and 'Fontsize' in line:
            fields = [f.strip() for f in line[7:].split(',')]
        elif line.startswith('Style:') and fields:
            values = [v.strip() for v in line[6:].split(',')]
            try:
                sizes.append(float(values[fields.index('Fontsize')]))
            except (ValueError, IndexError):
                pass
    return sizes


def measure(timeline, duration=None):
    """{length_s, music_db, caption_px} of a timeline (edit_script.read): its length (the export's duration when
    given), the median level of the clips on its music tracks (0 dB for a clip with no gain) and the median caption
    font size its caption layers draw. A value it can't find is None."""
    timeline = timeline or {}
    levels, sizes = [], []
    for track in timeline.get('tracks') or []:
        music = 'music' in str(track.get('name') or '').lower() or 'song' in str(track.get('name') or '').lower()
        for item in track.get('items') or []:
            if not isinstance(item, dict):
                continue
            if music and track.get('kind') == 'audio' and item.get('clip'):
                level = _main_level(item.get('effects'))
                levels.append(0.0 if level is None else level)
            if item.get('ass'):
                sizes += _ass_sizes(item['ass'])
    levels.sort()
    sizes.sort()
    return {'length_s': round(float(duration), 3) if duration else seconds(timeline.get('length')),
            'music_db': levels[len(levels) // 2] if levels else None,
            'caption_px': sizes[len(sizes) // 2] if sizes else None}


def plan(notes, timeline, duration=None):
    """Each note's measurable targets, with the value before the revision and the one wanted."""
    before = measure(timeline, duration)
    out = []
    for i, note in enumerate(notes or []):
        text = note.get('text') if isinstance(note, dict) else note
        for t in parse(text):
            entry = {'note': i, 'text': str(text)[:300], 'kind': t['kind'], 'asked': t['asked']}
            if t['kind'] == 'length' and before['length_s']:
                wanted = t['wanted_s'] if 'wanted_s' in t else before['length_s'] + t['change_s']
                change = abs(wanted - before['length_s'])
                entry.update(before=before['length_s'], wanted=round(wanted, 3), unit='s',
                             tolerance=round(max(TOLERANCE_S, TOLERANCE_SHARE * change), 3),
                             at_most=bool(t.get('at_most')))
            elif t['kind'] == 'music_level' and before['music_db'] is not None:
                entry.update(before=before['music_db'], wanted=round(before['music_db'] + t['change_db'], 2), unit='dB',
                             tolerance=TOLERANCE_DB)
            elif t['kind'] == 'caption_size' and before['caption_px']:
                wanted = before['caption_px'] * t['ratio']
                entry.update(before=before['caption_px'], wanted=round(wanted, 2), unit='px',
                             tolerance=round(wanted * TOLERANCE_SIZE, 2))
            else:
                continue            # nothing to measure it against on this cut
            out.append(entry)
    return out


def _file(project):
    import letitedit.timeline.project_journal as project_journal
    return Path(project_journal.folder(project)) / FILE


def keep(project, notes):
    """plan() on the project as it is now (the cut before the revision), kept in its side folder for every review of
    the revision. Returns the targets ([] when no note names one; the file is then removed)."""
    import letitedit.timeline.edit_script as es
    f = _file(project)
    targets = plan(notes, es.read(project)) if notes else []
    if targets:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'targets': targets}, indent=1), encoding='utf-8')
    else:
        f.unlink(missing_ok=True)
    return targets


def kept(project):
    try:
        return json.loads(_file(project).read_text(encoding='utf-8-sig')).get('targets') or []
    except (OSError, ValueError, AttributeError):
        return []


def _fmt(value, unit):
    return f"{value:g} {unit}" if unit != 'px' else f"{value:g} px"


def check(project, timeline, duration=None, targets=None):
    """Each kept target against the cut now: [{note, kind, asked, before, wanted, delivered, tolerance, missed_by,
    met, line}]; [] without targets. A length asked as 'at most' is met anywhere under it."""
    targets = kept(project) if targets is None else targets
    if not targets:
        return []
    now = measure(timeline, duration)
    key = {'length': 'length_s', 'music_level': 'music_db', 'caption_size': 'caption_px'}
    out = []
    for t in targets:
        got = now.get(key.get(t['kind']))
        if got is None:
            out.append({**t, 'delivered': None, 'met': None,
                        'line': f"note {t['note'] + 1} ({t['asked']}): nothing on this cut to measure it on"})
            continue
        off = got - t['wanted']
        missed = 0.0 if (t.get('at_most') and off <= 0) else abs(off)
        met = missed <= t['tolerance'] + 1e-6
        unit = t['unit']
        line = (f"note {t['note'] + 1} ({t['asked']}): {_fmt(round(got, 2), unit)} delivered against "
                f"{_fmt(t['wanted'], unit)} asked ({_fmt(t['before'], unit)} before)")
        line += ', within the target' if met else f", {_fmt(round(missed, 2), unit)} {'over' if off > 0 else 'under'}"
        out.append({**t, 'delivered': round(got, 3), 'missed_by': round(missed, 3), 'met': met, 'line': line})
    return out


FIX = {
    'length': ("Bring the length back to the note's target. Fix the joins within it: the clean cut point nearest the "
               "target (letitedit_words and letitedit_hear show the pauses), and time a repaired join needs taken from "
               "a pause or a repeat elsewhere ({op: tighten}, {op: trim}), never by giving the note's cut back. If no "
               "clean cut point is near enough, take the nearest one that breaks no word and say by how much in the "
               "note's outcome."),
    'music_level': ("Set the music to the note's level: {op: effects} with {gain} on the music clips, or {op: track} "
                    "with gain on its track; then letitedit_check_audio(stems=True)."),
    'caption_size': "Set the captions to the note's size: {op: captions} with style size, or {op: set} on the caption layer.",
}


def findings(checked):
    """A missed target as a measured finding (major, the AI's to fix before hand-over, like a clipped word)."""
    return [{'source': 'note', 'severity': 'major', 'at': '', 'at_s': None,
             'what': f"note target: {c['line']} (the note: \"{c['text'][:160]}\")",
             'evidence': f"tolerance {_fmt(c['tolerance'], c['unit'])}", 'fix': FIX[c['kind']]}
            for c in checked if c.get('met') is False]


# A finding's fix, read for the way it would move a note's measured value: +1 up (longer, louder, bigger), -1 down.
_LONGER = re.compile(
    r"\b(?:extend|lengthen)(?:s|ed|ing)?\b[^.;]{0,30}?\b(?:last|final|end|ending|closing|tail|video|cut)\b|"
    r"\b(?:last|final|closing)\s+(?:clip|shot)\b[^.;]{0,30}?\b(?:longer|past|beyond|through|later)\b|"
    r"\bbring(?:s|ing)?\s+the\s+(?:video'?s?\s+)?length\s+(?:back\s+)?(?:up\s+)?to\b|"
    r"\bmake\s+(?:it|the\s+(?:video|short|cut))\s+longer\b|\bpast\s+the\s+end\b|\blonger\s+ending\b|"
    r"\bput\s+(?:the|that|this)\s+(?:payoff|line|ending|end|words?|sentence|beat)\s+back\b", re.I)
_SHORTER = re.compile(
    r"\b(?:shorten|trim|cut|tighten)(?:s|ed|ing)?\b[^.;]{0,20}?\b(?:the\s+)?(?:video|short|ending|end|last)\b|"
    r"\bbring(?:s|ing)?\s+the\s+(?:video'?s?\s+)?length\s+down\s+to\b|\bmake\s+(?:it|the\s+(?:video|short|cut))\s+shorter\b",
    re.I)
_WINDOW = re.compile(r'\b(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*s(?:econds?)?\s+(?:window|range|target)\b|'
                     r'\bwindow\s+(\d+(?:\.\d+)?)\s*(?:-|–)\s*(\d+(?:\.\d+)?)\s*s\b|'
                     r'\btarget\s+(\d+(?:\.\d+)?)\s*s\b', re.I)
_MUSIC = r'(?:music|bed|song|score|soundtrack)'
_LOUDER = re.compile(r'\b(?:raise|boost|turn\s+up|bring\s+up|lift|increase|push\s+up)\b[^.;]{0,30}?\b' + _MUSIC + r'\b|'
                     r'\b' + _MUSIC + r'\b[^.;]{0,25}?\b(?:louder|higher|up\s+by)\b', re.I)
_QUIETER = re.compile(r'\b(?:lower|reduce|duck|turn\s+down|pull\s+down|drop)\b[^.;]{0,30}?\b' + _MUSIC + r'\b|'
                      r'\b' + _MUSIC + r'\b[^.;]{0,25}?\b(?:quieter|softer|lower|down\s+by)\b', re.I)
_TEXT = r'(?:captions?|subtitles?|text|font|words)'
_BIGGER = re.compile(r'\b(?:enlarge|bigger|larger|increase\s+the\s+(?:font\s+)?size|scale\s+up)\b[^.;]{0,30}?\b' + _TEXT +
                     r'\b|\b' + _TEXT + r'\b[^.;]{0,30}?\b(?:bigger|larger|enlarge|scale\s+up)\b', re.I)
_SMALLER = re.compile(r'\b(?:smaller|shrink|reduce\s+the\s+(?:font\s+)?size|scale\s+down)\b[^.;]{0,30}?\b' + _TEXT +
                      r'\b|\b' + _TEXT + r'\b[^.;]{0,30}?\b(?:smaller|shrink|scale\s+down)\b', re.I)
# the project's ending check (the last line running on in the source): its fix moves the last clip's end later
_ENDING_RUNS_ON = re.compile(r'thought may not be finished|carries on past the cut|left out just after the cut', re.I)
END_S = 0.3             # a finding this close to the delivered end is about the ending
PAST_END_S = 0.1        # ... and one later than the end by this much is about time this cut no longer has
LABEL = {'length': 'the length', 'music_level': "the music's level", 'caption_size': "the captions' size"}


def _length_way(finding, delivered):
    """+1 when a finding's fix lengthens the video, -1 when it shortens it, 0 when it doesn't say."""
    fix = str(finding.get('fix') or '')
    if _LONGER.search(fix):
        return 1
    if _SHORTER.search(fix):
        return -1
    named = fix + (' ' + str(finding.get('what') or '') if finding.get('source') in ('gate', 'brief') else '')
    for m in _WINDOW.finditer(named):
        nums = [float(x) for x in m.groups() if x is not None]
        if delivered is not None and delivered < min(nums) - 0.05:
            return 1
        if delivered is not None and delivered > max(nums) + 0.05:
            return -1
    at = finding.get('at_s')
    if delivered and at is not None and abs(float(at) - delivered) <= END_S and \
            _ENDING_RUNS_ON.search(str(finding.get('what') or '')):
        return 1
    return 0


def _way(kind, finding, delivered):
    fix = str(finding.get('fix') or '')
    if kind == 'length':
        return _length_way(finding, delivered)
    if kind == 'music_level':
        return 1 if _LOUDER.search(fix) else -1 if _QUIETER.search(fix) else 0
    if kind == 'caption_size':
        return 1 if _BIGGER.search(fix) else -1 if _SMALLER.search(fix) else 0
    return 0


def _part(target):
    """Which end a length note cut ('end', 'start') or None; a kept target from before T338 has no 'part'."""
    if target.get('part'):
        return target['part']
    parsed = [t for t in parse(target.get('asked')) if t['kind'] == 'length']
    return parsed[0].get('part') if parsed else None


def fmt_time(s):
    s = float(s)
    return f'{int(s // 60)}:{s % 60:04.1f}'


def against(finding, checked, duration=None):
    """Why a finding would undo one of the person's notes, or None. checked: check()'s list for this cut.
    - Its fix moves a note's measured value away from the target: the other way from the note while the target is
      met (a longer ending against "cut the last 2 seconds", louder music against "lower the music by 6 dB"), or
      further off while it is missed. A length window or target the fix names moves the length too, so a note's
      length stands over the brief's range for the revision.
    - It is about the part a note cut: a time past the delivered end, after a note cut the end.
    A note target's own finding (source 'note') never is. Returns {note, asked, kind, why}."""
    if not checked or finding.get('source') == 'note':
        return None
    for c in checked:
        if c.get('wanted') is None or c.get('before') is None:
            continue
        note = {'note': c['note'], 'asked': c.get('asked') or '', 'kind': c['kind']}
        delivered = c.get('delivered')
        if c['kind'] == 'length' and delivered is None:
            delivered = duration
        at = finding.get('at_s')
        if c['kind'] == 'length' and c['wanted'] < c['before'] and _part(c) == 'end' and at is not None and \
                delivered and delivered + PAST_END_S < float(at) <= c['before'] + 0.5:
            return {**note, 'why': f"it is about {fmt_time(at)}, in the part note {c['note'] + 1} cut"}
        way = _way(c['kind'], finding, delivered)
        if not way:
            continue
        noted = 1 if c['wanted'] > c['before'] else -1
        off = (delivered - c['wanted']) if delivered is not None else None
        within = off is None or abs(off) <= c.get('tolerance', 0) + 1e-6 or bool(c.get('at_most') and off <= 0)
        if (within and way != noted) or (not within and way * off > 0):
            return {**note, 'why': f"its fix would move {LABEL[c['kind']]} away from note {c['note'] + 1}'s target"}
    return None
