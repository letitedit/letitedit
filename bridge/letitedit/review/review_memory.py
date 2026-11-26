"""What a video's reviews remember, and who can fix what (T50). Kept in the video's side folder, so it survives a restart.

who_fixes(finding, said)         'ai' or 'person'. The critic's word is checked: only what truly needs something from the
                                 person may be theirs, and a cut through a word never is.
ensure_fix(finding)              every finding says how to fix it, in terms of the tools.
load(project, video), save(mem)  the memory: {'rounds': [...], 'items': [...], 'last_review': path}.
rounds_done(mem)                 how many full critic rounds this video has had. ROUND_LIMIT is what the bundle enforces.
start_revision(project, of)      a revision's rounds start again; the earlier ones are kept in 'earlier', the items stay.
for_critic(mem)                  the short list the next reviewer reads, or ''.
update(mem, findings, review, full_round, video)   brings the list up to date; returns the findings to judge, with the items
                                 still open that this review didn't repeat.
looks, seen_cuts, cut_unseen, can_look_cut, record_look   past the round limit, a cut no reviewer saw gets a look of its
                                 own: LOOKS_PER_CUT per changed cut, LOOK_LIMIT in all for one edit.
gone_quotes, without_gone_quotes, rewrite   a note quoting words the cut no longer has is rewritten or says so.
same_defect(items, words)        the open item a look's words about a changed cut name again (one finding per defect).
same_moment, fold_same           two open notes naming the same moment (within a few frames) and kind of problem are one:
                                 the later joins the earlier (status 'merged', merged_into).
                                 An item a revision's note settled (note_targets.against) has status 'note'.
hand_over, unattended, edit_after_handover   after the last review says hand over, an edit in an unattended run gets its
                                 look or is refused.
"""
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

ROUND_LIMIT = 2
TURBO_ROUND_LIMIT = 1   # Turbo (T70): the brief's `turbo` is true on the first run through only; the one round's findings are shown

# Only something the person alone can provide. An illustration or a recut the AI can make is not on this list.
NEEDS_PERSON = re.compile(
    r"(real|actual|genuine|true|short|readable)[- ]+(\w+[- ]+){0,3}(capture|recording|footage|demo|demonstration)|"
    r"(screen|product|software)[- ]+(capture|recording|footage|demo\b|demonstration)|"
    r"show(ing)?( a| the)? (real |actual )?(software|product|tool|app)\b|"
    r"(follower|analytics|account|milestone|dashboard|subscriber)[^.]{0,40}(capture|screenshot|proof|result|milestone|example)|"
    r"(capture|screenshot|proof)[^.]{0,40}(follower|analytics|account|subscriber)|"
    r"(sign[- ]?up|beta|join)[^.]{0,80}(url|link|destination|route|handle|where)|link in bio|"
    r"(url|link|destination|route|handle)[^.]{0,60}(sign[- ]?up|beta)|"
    r"verified (fact|figure|number|source)|the (person|creator|founder) (must|needs to|has to|should) (decide|provide|confirm)",
    re.I)
# Never only a person's, whatever anyone says: the AI has the tools for these.
NEVER_PERSON = re.compile(
    r"cut (through|into|off)|clip(s|ped)? (a |the )?(word|sound)|mid[- ]?(word|sentence)|ends while|middle of (the |a )?(word|sound)|"
    r"(caption|text|title|label)[^.]{0,50}(cover|over|overlap|on top of|hide|hides|obscure|ghost|compete)|"
    r"(cover|over|overlap|hide|hides|obscure)[^.]{0,40}(face|mouth)|"
    r"loudness|too (loud|quiet)|music|repeat|repetition|said twice|blurred (border|background)|reading (speed|time)|"
    r"characters a second|misspell|spelled|too small|hard to read|unreadable|stays? (nearly )?(the same|unchanged)|static shot|longest shot",
    re.I)
AI_KINDS = {'pacing', 'sound', 'technical'}
# (what the finding says, how to fix it): measured findings say what's wrong; this says what to do, in the tools' terms.
FIXES = (
    (r'^Look camera:',
     "Change the clips it names: for a plain stretch, as many of its plainest shots as it says out and the footage's "
     "fuller moments in at the same length (the stretches it lists, with how much of each is unused), in one change; "
     "the footage's nearer or foreground-framed shots of the same moments first, then a crop toward the subject "
     "(letitedit_fix with {kind: punch} follows it; a {zoom, focus} effect for a light crop), and a move where a "
     "stretch is static; export again and check with letitedit_look_check(video=...)."),
    (r'^Look pace:',
     "Recut the stretch it names to the reference's pace: shorter shots and more of them (about as many as it says), "
     "with uneven lengths (one, two and three beats on a beat grid, not one length repeated), the camera finding's "
     "fuller moments as the material; or make the stretch shorter. Export again and check with "
     "letitedit_look_check(video=...)."),
    (r'^Look sound:.*opens quiet',
     "Open as quietly as the reference: keep the sound plan's quiet first section (letitedit_learn(action='sound_plan') "
     "on the current anchors, then letitedit_soundtrack with its sections); with another song, its own quiet start or "
     "the music brought up over those seconds, not a hard entry at full level. Export again and read "
     "letitedit_export_job's loudness over time."),
    (r'^Look sound:.*main level',
     "Bring the music to its main level as fast as the reference: letitedit_learn(action='sound_plan') on the current "
     "anchors and letitedit_soundtrack with its sections (or a part of the song already full there); export again and "
     "read letitedit_export_job's loudness over time."),
    (r'keep a restart|begun and begun again',
     "letitedit_hear has what's said there. A restart: keep the last try and cut the first with {op: trim}, on the sound where the last try begins. Said twice on purpose: name it in fine_pass.md on a line that says kept on purpose and quotes the words, with why, and say so in the closing message."),
    (r'ends while a sound|middle of (the word|a sound)|word.*cut|cut.*word|starts? (on|in) a',
     "Move the clip's edge past the sound with letitedit_timeline_apply {op: trim}; letitedit_hear and letitedit_words show where it ends."),
    (r'caption covers the face', "Move this caption off the face with {op: set}. letitedit_caption_fit(project, faces='hard') can plan it: "
                                 "apply a plan only if its summary shows fewer covers_face after than before."),
    (r'caption reads at|dangling word', 'Rebuild the captions with {op: captions, chunk} so each line has fewer words or more time, or hold the line longer with {op: trim}.'),
    (r'blurred border', 'Fill the frame: {op: set} on the clip, or letitedit_reframe.'),
    (r'graphic|over captions', 'Move the graphic or the caption with {op: set} so they no longer share the time or the place.'),
    (r'project changed', 'letitedit_export again, then review the new file.'),
    (r'loudness_lufs|true_peak', 'letitedit_export(project, loudness=...) sets the finish; {op: score} and {op: level} change the mix.'),
    (r'cuts_per_min|longest_static_s|picture (setups|stays)', 'Change the picture at a sentence boundary with {op: fx} (a zoom punch or crop reset) or a cutaway, or mark a deliberate hold with letitedit_bin.'),
    (r'visual_change_first3s', 'Add a change in the first 3 s with {op: fx}, or open on a different moment with {op: hook}.'),
    (r'duration_vs_target|tiktok_just_under|^length', "Change the length with {op: trim} and {op: delete}, or update the brief's target_s if the target moved."),
    (r'silence_first3s|silent_share|first_speech', 'Close the gaps with {op: tighten}, or move the first line earlier with {op: trim}.'),
    (r'tail_silence', 'Shorten the last clip with {op: trim}.'),
    (r'frame0', 'Start on a picture: {op: trim} the first clip or remove the fade in.'),
    (r'vertical_1080', 'Export at the size the brief asks for: letitedit_export, or letitedit_reframe first.'),
    (r'expected_words', 'Compare letitedit_words with the render at that time and restore what was lost with {op: trim}.'),
    (r'^protected base picture',
     "An inset, split screen, blur or grade on the speaker's picture stays when the Look or the person calls for it; "
     "otherwise take that effect off the clip with {op: effects} or {op: set} and find room for graphics around the "
     "face. letitedit's own live lighting is measured by letitedit_learn(action='kit_check') with its face test."),
    (r'^must_keep|^narration|^protected', 'Put the required moment back with {op: insert} from its source range, shown by letitedit_find_ranges.'),
    (r'^must_avoid', 'Take the material out with {op: delete}.'),
    (r'^claim', 'Say it from a clip where it is said ({op: insert}), and spell it the same in the captions with {op: captions}.'),
    (r'^ending', 'Change the last clips with {op: trim} and {op: move}.'),
    (r'mix was never measured', 'letitedit_check_audio(project, stems=True).'),
    (r'voice clean-up', "letitedit_fix(project, item=<clip>, fix='voice') on the talking clips, or say why not in finish_pass.md."),
)
DEFAULT_FIX = 'Look at that moment with letitedit_check_frames and change it with letitedit_timeline_apply, then export again.'


def who_fixes(finding, said=None):
    """'person' only for what truly needs them. A critic can't wave something through by calling it a person's job."""
    source, what = finding.get('source'), str(finding.get('what') or '')
    if source == 'brief' and what.startswith('claim to confirm'):
        return 'person'
    if source != 'critic':
        return 'ai'         # measured: its check will read clean once it's fixed, and the tools can do that
    text = f"{what} {finding.get('fix') or ''}"
    kind = what.split(':', 1)[0].strip().lower()
    if kind in AI_KINDS or NEVER_PERSON.search(what):
        return 'ai'
    if not NEEDS_PERSON.search(text):
        return 'ai'
    return 'ai' if str(said or '').lower() == 'ai' else 'person'


# A reviewer asking for a shot to be added: "cut in the clip of...", "b-roll of...", "search the folder for...". Read
# in the finding's fix (what it asks for): re-cutting, re-pacing, swapping or regrading shots already in the edit is not
# an ask for footage, even though such notes say "shot" and "clip" too.
ASKS_FOR_FOOTAGE = re.compile(
    r"\b(add|insert|put|cut (it )?in|find|use|search|bring in|include|film|get|need)\b[^.]{0,60}?"
    r"\b(shot|clip|footage|b-?roll|cutaway|take|video)s?\b|"
    r"\b(b-?roll|cutaways?|pickups?)\b|\b(shot|clip|footage|video) of\b|\bsearch the [\w ]{0,30}folder\b", re.I)
PICKUP_TIME_S = 3.0          # a shots-to-film line naming a time this close is about the same moment
PICKUP_WORDS = 4             # ... or one sharing this many words, its subject among them (the line's bold heading)
# Words every editing note uses: two notes sharing them are not about the same shot.
PICKUP_GENERIC = set("about after before then next time cut cuts shot shots clip clips take takes film filmed footage "
                     "frame frames line look look's section video scene still would".split())


def _times(text):
    return [int(m.group(1)) * 60 + int(m.group(2)) for m in re.finditer(r'\b(\d{1,2}):(\d\d)\b', text)]


def footage_pickups(findings, pickups_text):
    """A reviewer's request for footage the folder doesn't have can't be met by the editor, and the verdict can't clear
    it: when the editor has put that shot on the shots-to-film list (pickups.md: it looked and the clip isn't there),
    the finding is the person's (for_you), with the list's line as the reason. Only a finding whose fix asks for a shot
    to be added (ASKS_FOR_FOOTAGE) can move. Matched by a time named in the line within PICKUP_TIME_S of the finding,
    or PICKUP_WORDS words in common that aren't everyday editing words, one of them from the line's bold heading when it
    has one (its subject). Returns how many moved."""
    lines = []                   # one per list item, its wrapped lines joined
    for raw in str(pickups_text or '').splitlines():
        line = raw.strip()
        if line.startswith(('-', '*')):
            lines.append(re.sub(r'^[-*]\s+|^-', '', line))     # the bullet off, a bold heading kept
        elif line and not line.startswith('#') and lines:
            lines[-1] += ' ' + line
    moved = 0
    for finding in findings:
        if finding.get('source') != 'critic' or finding.get('owner') == 'person':
            continue
        text = f"{finding.get('what') or ''} {finding.get('fix') or ''}"
        if not ASKS_FOR_FOOTAGE.search(str(finding.get('fix') or '') or text):
            continue
        at = finding.get('at_s')
        words = _topic(text) - PICKUP_GENERIC
        for line in lines:
            near = at is not None and any(abs(t - at) <= PICKUP_TIME_S for t in _times(line))
            heading = re.match(r'\s*\*\*(.+?)\*\*', line)
            subject = (_topic(heading.group(1)) - PICKUP_GENERIC) if heading else None
            shared = (_topic(line) - PICKUP_GENERIC) & words
            if near or (len(shared) >= PICKUP_WORDS and (subject is None or shared & subject)):
                finding['owner'] = 'person'
                finding['fix'] = ('Not in the footage: it is on the shots to film next time (pickups.md): '
                                  + re.sub(r'\*\*', '', line).strip(' *')[:300])
                moved += 1
                break
    return moved


def ensure_fix(finding):
    """Every finding says how to fix it. A measured one's own text is often the reason, so the tools' steps go after it."""
    if finding.get('source') == 'critic' and finding.get('fix'):
        return finding
    what = str(finding.get('what') or '')
    steps = next((fix for pattern, fix in FIXES if re.search(pattern, what, re.I)), DEFAULT_FIX)
    old = str(finding.get('fix') or '').strip()
    if steps not in old:
        finding['fix'] = f'{old} {steps}'.strip() if old and 'letitedit_' not in old and '{op:' not in old else (old or steps)
    return finding


# ---------------------------------------------------------------------------- the memory

def _file(project, video):
    import letitedit.timeline.project_journal as project_journal
    folder = project_journal.folder(project or video)
    Path(folder).mkdir(parents=True, exist_ok=True)
    return Path(folder) / 'review_memory.json'


def load(project, video):
    f = _file(project, video)
    try:
        mem = json.loads(f.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        mem = {}
    mem.setdefault('rounds', [])
    mem.setdefault('items', [])
    mem['_file'] = str(f)
    return mem


def save(mem):
    data = {k: v for k, v in mem.items() if not k.startswith('_')}
    Path(mem['_file']).write_text(json.dumps(data, indent=1), encoding='utf-8')


def rounds_done(mem):
    return len(mem.get('rounds') or [])


def start_revision(project, revision_of=None):
    """A revision of a finished video, made from the person's notes, is a new edit with review rounds of its own: the
    count starts again at 0 (the brief's limit applies to the revision), and the earlier edit's rounds and targeted
    look move to `earlier`, one entry per earlier edit (a revision of a revision adds one more). The items stay, so the
    next reviewer reads them as what earlier rounds found and says in `previously` what is fixed. Returns the memory."""
    mem = load(project, None)
    earlier = list(mem.get('earlier') or [])
    if mem.get('rounds') or mem.get('targeted_look') or mem.get('looks'):
        entry = {'revision_of': revision_of, 'rounds': mem.get('rounds') or [], 'targeted_look': mem.get('targeted_look'),
                 'text_look': mem.get('text_look'), 'looks': mem.get('looks'), 'handed_over': mem.get('handed_over')}
        earlier.append({k: v for k, v in entry.items() if v})
    mem['earlier'] = earlier
    mem['rounds'] = []
    for key in ('targeted_look', 'text_look', 'looks', 'handed_over', 'unattended'):
        mem.pop(key, None)            # the earlier edit's looks and hand-over: this revision has its own
    mem.pop('last_review', None)      # the earlier edit's review: never reused as this revision's
    save(mem)
    return mem


def hand_over(mem, project_hash):
    """The last review of a run said hand the video over: kept, so an edit after it is decided by code
    (edit_after_handover), not by what the editing AI remembers."""
    mem['handed_over'] = {'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'project_hash': project_hash,
                          'looks_left': looks_left(mem)}
    return mem['handed_over']


def unattended(project, on=True):
    """An unattended run (a Studio job, no person at the window) starts (on) or ends: while it runs, an edit after the
    review said hand over is refused when no reviewer look is left for the changed cut."""
    mem = load(project, None)
    if on:
        import os
        mem['unattended'] = {'since': time.strftime('%Y-%m-%dT%H:%M:%S'), 'pid': os.getpid()}
    else:
        mem.pop('unattended', None)
    save(mem)


def _run_gone(run):
    """True when the unattended run that set `run` has ended without lifting it (its process is gone): a crashed run
    never keeps refusing edits afterwards."""
    pid = run.get('pid')
    if not isinstance(pid, int):
        return False
    from letitedit.core import render_lock
    return not render_lock.pid_alive(pid)


def edit_after_handover(project):
    """None, or why an edit to this project is refused: an unattended run's last review said hand the video over, and
    no reviewer look is left for a changed cut, so the edit would go out unseen by any reviewer. A person's own edits,
    and every edit outside an unattended run, are never refused here."""
    try:
        mem = load(project, None)
    except (OSError, ValueError, TypeError):
        return None
    run, done = mem.get('unattended'), mem.get('handed_over')
    if not (isinstance(run, dict) and isinstance(done, dict)) or str(done.get('when') or '') < str(run.get('since') or ''):
        return None
    if _run_gone(run) or looks_left(mem):
        return None
    return (f"Refused: the last review said hand the video over, and the {LOOK_LIMIT} reviewer looks this edit may have "
            "past its review rounds are used, so no reviewer would see a changed cut. The video stays as it was "
            "reviewed: hand it over now, with what is left listed in the closing message.")


def round_limit(brief=None):
    """How many full critic rounds this video may have: ROUND_LIMIT, or one while the brief says `turbo`."""
    turbo = (brief or {}).get('turbo') if isinstance(brief, dict) else None
    if isinstance(turbo, str):
        turbo = turbo.strip().lower() in ('1', 'true', 'yes', 'on')
    return TURBO_ROUND_LIMIT if turbo else ROUND_LIMIT


def _words(text):
    return re.findall(r"[a-z0-9']+", str(text).lower())


def _similar(a, b):
    return SequenceMatcher(None, _words(a), _words(b)).ratio()


STOP = set('a an and are as at be but by for from has have in is it its no not of on only or that the their there this to was with without'.split())


def _topic(text):
    return {w for w in _words(text) if w not in STOP and len(w) > 2}


def _same_topic(item, finding):
    """A reviewer raising the person's item again in other words: most of the shorter note's words are in the other."""
    a, b = _topic(item['what']), _topic(finding['what'])
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.3


def _same(item, finding):
    if item['source'] != finding['source']:
        return False
    likeness = _similar(item['what'], finding['what'])
    if item.get('status') == 'person' and finding['source'] == 'critic' and _same_topic(item, finding):
        return True
    near = item.get('at_s') is not None and finding.get('at_s') is not None and abs(item['at_s'] - finding['at_s']) <= 2
    return likeness >= 0.6 or (near and likeness >= 0.3)


LOOK_CHANGE = 'look: after the last change, '     # the start of a finding a look's answer about a changed cut raised
SAME_DEFECT = 0.4       # a look's words and an open note share this share of the longer one's words (quotes aside)


def _core(text):
    """A note's words for telling one defect from another: its kind ('story:') and quoted words left out (two notes
    about different things often quote the same caption), plurals folded."""
    text = str(text or '')
    if text.startswith(LOOK_CHANGE):
        text = text[len(LOOK_CHANGE):]
    elif re.match(r'^[a-z]+:\s', text):
        text = text.split(':', 1)[1]
    text = QUOTE.sub(' ', text)
    return {w[:-1] if len(w) > 4 and w.endswith('s') else w for w in _topic(text)}


def same_defect(items, words, at_s=None):
    """The open item a look's words about a changed cut name again, or None: the same defect when most of their own
    words are shared (SAME_DEFECT of the longer one's, quotes and kinds aside) and, when both have a time, within
    2 s. The closest one wins."""
    said = _core(words)
    best, score = None, 0.0
    for item in items:
        if item.get('status') != 'open' or item.get('source') != 'critic':
            continue
        if at_s is not None and item.get('at_s') is not None and abs(float(item['at_s']) - float(at_s)) > 2:
            continue
        theirs = _core(item.get('now') or item.get('what'))
        if not (said and theirs):
            continue
        share = len(said & theirs) / max(len(said), len(theirs))
        if share >= SAME_DEFECT and share > score:
            best, score = item, share
    return best


MOMENT_S = 0.15         # "the same moment": two times within a few frames (about 4 at 30 fps)
SAME_MOMENT = 0.3       # ...and the same kind of problem: the same kind ('shots:') and this share of the longer note's words
SEVERITY_RANK = {'critical': 3, 'major': 2, 'minor': 1}
TIMECODE = re.compile(r'(?<![\d.:])(\d+):(\d{2}(?:\.\d+)?)(?![\d:])')
GONE_WORDS = 'words this cut no longer has'


def _kind(text):
    found = re.match(r'^([a-z]+):\s', str(text or ''))
    return found.group(1) if found else None


def moments(item):
    """Every time a note names: its own `at_s` and each m:ss(.s) in its words and fix."""
    times = set()
    if item.get('at_s') is not None:
        try:
            times.add(round(float(item['at_s']), 3))
        except (TypeError, ValueError):
            pass
    for field in ('what', 'fix'):
        for m, s in TIMECODE.findall(str(item.get(field) or '')):
            times.add(round(int(m) * 60 + float(s), 3))
    return times


def same_moment(a, b):
    """Two open critic notes that are one defect: they name the same moment (within MOMENT_S, any of their times) and
    the same kind of problem (the same kind and SAME_MOMENT of the longer one's own words, quotes aside)."""
    if a.get('source') != 'critic' or b.get('source') != 'critic':
        return False
    kind = _kind(a.get('what'))
    if not kind or kind != _kind(b.get('what')):
        return False
    if not any(abs(x - y) <= MOMENT_S for x in moments(a) for y in moments(b)):
        return False
    one, two = _core(a.get('now') or a.get('what')), _core(b.get('now') or b.get('what'))
    return bool(one and two) and len(one & two) / max(len(one), len(two)) >= SAME_MOMENT


def _joined(first, later):
    """first's note with later's words joined on (one note for one defect): its own words first, the later note's
    after 'Also:'; the earlier time, the graver severity. Joining again replaces the later part, never stacks it."""
    base = first.get('joined_from') or {'what': first.get('now') or first.get('what') or '', 'fix': first.get('fix') or ''}
    what, fix = later.get('now') or later.get('what') or '', later.get('fix') or ''
    out = {'joined_from': base,
           'what': base['what'] + (' Also: ' + what if what and what != base['what'] else ''),
           'fix': base['fix'] + (' Also: ' + fix if fix and fix != base['fix'] else ''),
           'severity': max((first.get('severity'), later.get('severity')), key=lambda s: SEVERITY_RANK.get(s, 0))}
    times = [(first.get('at_s'), first.get('at')), (later.get('at_s'), later.get('at'))]
    times = [t for t in times if t[0] is not None]
    if times:
        out['at_s'], out['at'] = min(times, key=lambda t: float(t[0]))
    return out


def fold_same(mem, out):
    """One defect counted once: an open critic note in `out` that names the same moment and kind of problem as an
    earlier one joins it (_joined); the later item keeps its id with status 'merged' and `merged_into`. Returns out
    without the joined ones."""
    listed = mem.get('items') or []
    items = {i['id']: i for i in listed}
    order = {i['id']: n for n, i in enumerate(listed)}
    kept = []
    for f in out:
        item = items.get(f.get('id'))
        if item is None or item.get('status') != 'open' or f.get('owner') == 'person':
            kept.append(f)
            continue
        item.pop('merged_into', None)
        at = next((n for n, k in enumerate(kept) if k.get('id') in items and items[k['id']].get('status') == 'open'
                   and k.get('owner') != 'person' and same_moment(k, f)), None)
        if at is None:
            kept.append(f)
            continue
        older, newer = (kept[at], f) if order[kept[at]['id']] <= order[f['id']] else (f, kept[at])
        first, later = items[older['id']], items[newer['id']]
        joined = _joined(first, later)
        first.update(joined)
        first.pop('now', None)
        older.update({k: v for k, v in joined.items() if k != 'joined_from'})
        later.update(status='merged', merged_into=first['id'])
        kept[at] = older
    return kept


RERATE = ("Their earlier severities are left out on purpose: rate each one that is still open afresh from what this "
          "cut shows, by the bar for each severity, and put it in `problems` again with that severity (its id in the "
          "evidence), as you would a problem seen for the first time.")


def for_critic(mem):
    """The short list for the next reviewer, or '' before the first round. With review_craft_checks on (T349), the items
    the editor was to fix are listed without their earlier severity, and the reviewer rates each open one again from
    the evidence (RERATE): a first rating never carries itself into later rounds."""
    if not mem.get('items'):
        return ''
    import letitedit.review.craft_checks as craft_checks
    rerate = craft_checks.enabled()

    def line(i, severity=True):
        return (f"[{i['id']}] {i.get('at') or '-'}{' ' + i['severity'] if severity else ''}: "
                f"{(i.get('now') or i['what'])[:170]}")
    groups = {s: [i for i in mem['items'] if i['status'] == s] for s in ('open', 'person', 'fixed', 'note')}
    judged = [i for i in groups['open'] if i['source'] == 'critic']
    measured = [i for i in groups['open'] if i['source'] != 'critic']
    before = sum(len(e.get('rounds') or []) for e in mem.get('earlier') or [])
    if before:
        parts = [f"This is review round {rounds_done(mem) + 1} of a revision: the video was changed from the person's "
                 f"notes after {before} earlier review round(s). What earlier rounds found:"]
    else:
        parts = [f"This is review round {rounds_done(mem) + 1} of this video. What earlier rounds found:"]
    if judged and rerate:
        parts += ['The editor was to fix these. Look at each and say in `previously` whether it is really fixed. '
                  + RERATE] + [line(i, severity=False) for i in judged]
    elif judged:
        parts += ['The editor was to fix these. Look at each and say in `previously` whether it is really fixed:'] + [line(i) for i in judged]
    if measured:
        parts += ['Measured by the tools, which check them again themselves. Do not raise these or answer for them:'] + [line(i) for i in measured]
    if groups['person']:
        parts += ['Waiting on the person (a recording, proof or a fact only they have). Do not raise these again:'] + [line(i) for i in groups['person']]
    if groups['note']:
        parts += ["Settled by the person's own notes for this revision (changing it would undo a note). Do not raise "
                  'these again:'] + [line(i) for i in groups['note']]
    if groups['fixed']:
        parts += ['Fixed earlier. Raise one again only if it is back:'] + [line(i) for i in groups['fixed'][:12]]
    parts.append('Add a new problem only if it clears the bar for its severity and you can point to it. Do not reword an older note, '
                 'and do not raise as new something that was there in the earlier round and not raised, unless it clearly matters.')
    return '\n'.join(parts)


def open_for_look(mem):
    """The reviewer's items the AI can fix that are still open: what a targeted look is about."""
    return [i for i in mem['items'] if i.get('status') == 'open' and i.get('source') == 'critic' and i.get('owner') != 'person']


def can_look(mem, project_hash, project_mtime, review_mtime):
    """One targeted look per video, after the rounds have ended, and only if the project has changed since the last one."""
    if mem.get('targeted_look') or not open_for_look(mem):
        return False
    then = (mem.get('rounds') or [{}])[-1].get('project_hash')
    return project_hash != then if then else project_mtime > review_mtime + 2


# Past the round limit, a cut no reviewer has seen gets a look of its own: LOOKS_PER_CUT for each changed cut, and
# LOOK_LIMIT in all for one edit (a revision starts again). A look reads the open notes and the pictures around them,
# about a half to two thirds of a full round's tokens; three cover a final, one edit after it and one more, at about
# the cost of one and a half rounds. A look that gave no answer counts towards both caps, so a failing reviewer can't
# be asked again and again.
LOOK_LIMIT = 3
LOOKS_PER_CUT = 1


def looks(mem):
    """Every look this edit has taken, oldest first: mem['looks'], plus a single 'targeted_look' or 'text_look' an
    older memory kept without the list."""
    out = [dict(entry) for entry in mem.get('looks') or [] if isinstance(entry, dict)]
    for key in ('targeted_look', 'text_look'):
        rec = mem.get(key)
        if isinstance(rec, dict) and not any(e.get('key', 'targeted_look') == key and e.get('when') == rec.get('when')
                                             for e in out):
            out.append({**rec, 'key': key})
    return out


def seen_cuts(mem):
    """The project states a reviewer saw: every round's, and every answered look's."""
    seen = {r.get('project_hash') for r in mem.get('rounds') or []}
    seen |= {e.get('project_hash') for e in looks(mem) if not e.get('failed')}
    seen.discard(None)
    return seen


def cut_unseen(mem, project_hash, project_mtime=None, review_mtime=None):
    """True when no reviewer saw this cut: neither a round nor an answered look read this project state. A state with
    no hash (a window that gives no revision) is never taken for seen. An older memory whose rounds kept no hash goes
    by the file times, as can_look does."""
    if not mem.get('rounds'):
        return False
    if not project_hash:
        return True
    if not any(r.get('project_hash') for r in mem['rounds']) and project_mtime is not None and review_mtime is not None:
        return project_mtime > review_mtime + 2 and project_hash not in seen_cuts(mem)
    return project_hash not in seen_cuts(mem)


def looks_left(mem):
    return max(0, LOOK_LIMIT - len(looks(mem)))


def can_look_cut(mem, project_hash):
    """(True, '') when a cut no reviewer saw may have its look now; else (False, why not, in plain words)."""
    if not looks_left(mem):
        return False, (f'the {LOOK_LIMIT} reviewer looks this edit may have past its review rounds are used '
                       '(one for each changed cut)')
    if project_hash and sum(1 for e in looks(mem) if e.get('project_hash') == project_hash) >= LOOKS_PER_CUT:
        return False, "this cut's one reviewer look was tried and gave no answer"
    return True, ''


def record_look(mem, key, entry):
    """Keeps a look (answered or failed) in mem['looks']; the first answered one of each key also under that key."""
    entry = {'key': key, **entry}
    mem.setdefault('looks', []).append(entry)
    if not entry.get('failed') and not mem.get(key):
        mem[key] = {k: v for k, v in entry.items() if k != 'key'}
    return entry


def gone_quotes(text, shown_text):
    """The quoted passages of a note (quotes()) that shown_text no longer shows or says; [] when there's no text."""
    shown = f" {' '.join(_words(str(shown_text or '').replace('/', ' ')))} "
    if not shown.strip():
        return []
    return [q for q in quotes(text) if not _shows(q, shown)]


def without_gone_quotes(text, shown_text):
    """text with every quoted passage this cut no longer shows replaced by a plain mention, so a note never stands
    quoting words that are gone."""
    gone = {tuple(q) for q in gone_quotes(text, shown_text)}
    if not gone:
        return text
    return QUOTE.sub(lambda m: f'({GONE_WORDS})' if tuple(_words(m.group(1).replace('/', ' '))) in gone
                     else m.group(0), str(text))


def rewrite(item, now, shown_text):
    """A note whose quoted words are gone, rewritten from a look's words about this cut (kept as item['now'] beside
    the reviewer's own words, which the next round's matching still reads). Returns the new text."""
    kind = str(item.get('what') or '').split(':', 1)[0].strip() if ':' in str(item.get('what') or '') else ''
    body = without_gone_quotes(str(now or '').strip(), shown_text) or 'the words it quoted are no longer in this cut'
    item['now'] = f'{kind}: {body}' if kind and not body.lower().startswith(kind.lower() + ':') else body
    return item['now']


QUOTE = re.compile(r"""(?:^|(?<=[\s(\[:]))['‘"“]([^"“”\n]{3,}?)['’"”](?=[\s,.;:)\]!?]|$)""")
QUOTE_WORDS = 3     # a quote this long names words on screen; a shorter one ('um', 'here') is too common to place


def quotes(text):
    """The quoted passages in a reviewer's note ('...', "...", ‘...’ or “...”), each as its words, QUOTE_WORDS or more."""
    out = []
    for m in QUOTE.finditer(str(text or '')):
        words = _words(m.group(1).replace('/', ' '))
        if len(words) >= QUOTE_WORDS:
            out.append(words)
    return out


def _shows(words, shown):
    return f" {' '.join(words)} " in shown


def text_gone(mem, shown_text):
    """The ids of the reviewer's open items (open_for_look) that quote words this cut no longer shows or says:
    a quote of QUOTE_WORDS words or more found nowhere in shown_text (its captions, on-screen words and what is
    heard, in order). [] when there is no text to compare with."""
    shown = f" {' '.join(_words(str(shown_text or '').replace('/', ' ')))} "
    if not shown.strip():
        return []
    gone = []
    for i in open_for_look(mem):
        if any(not _shows(q, shown) for q in quotes(i.get('what')) + quotes(i.get('evidence'))):
            gone.append(i['id'])
    return gone


def can_look_text(mem, project_hash, gone):
    """The one look past the round limit is spent (or can't be taken), but the reviewer's notes quote text this cut no
    longer shows and the project changed since the last round: one more look, at those notes only, so no note about
    text that is gone stands unchecked. Once per video."""
    if not gone or mem.get('text_look'):
        return False
    then = (mem.get('rounds') or [{}])[-1].get('project_hash')
    return bool(project_hash and then and project_hash != then)


def look_answers(mem, look, only=None):
    """{id: 'fixed' | 'still_open'} for every open item (or those in only); an item it didn't answer clearly stays open."""
    said = {str(p.get('id')): str(p.get('status') or '').lower() for p in (look or {}).get('previously') or [] if isinstance(p, dict)}
    return {i['id']: 'fixed' if said.get(i['id']) == 'fixed' else 'still_open' for i in open_for_look(mem)
            if only is None or i['id'] in only}


def update(mem, findings, review=None, full_round=False, video=None, looked=None, project_hash=None, round_facts=None):
    """Matches this review's findings against the list and returns what to judge now: this review's findings, plus any item the
    reviewer says is still open, plus everything waiting on the person. Also fills mem['_fixed_now'] for the plain report.
    looked: a targeted look's answers {id: status}; they come after the review, so they win over it. round_facts: what
    a full round also records (review_order.round_facts: the export's hash, the brief's, the cut), for the next call."""
    said = {str(p.get('id')): str(p.get('status') or '').lower() for p in (review or {}).get('previously') or [] if isinstance(p, dict)}
    said.update(looked or {})
    out, matched = [], set()
    for f in findings:
        item = next((i for i in mem['items'] if i['id'] not in matched and _same(i, f)), None)
        if item is not None and f.get('source') == 'critic' and (looked or {}).get(item['id']) == 'fixed':
            continue        # the last review's words about something the look has since seen fixed: the loop below closes it
        if item is None:
            item = {'id': f"r{len(mem['items']) + 1}", 'source': f['source'], 'round_found': rounds_done(mem) + (1 if full_round else 0)}
            mem['items'].append(item)
        was_person = item.get('status') == 'person'
        joined = item.get('joined_from')
        if joined and not _same(dict(item, what=joined['what'], fix=joined['fix']), f):
            # the later note of a joined pair, raised again: it replaces that part, the first note's words stay
            j = _joined(item, f)
            f = dict(f, what=j['what'], fix=j['fix'], severity=j['severity'], at=j.get('at', f.get('at', '')),
                     at_s=j.get('at_s', f.get('at_s')))
        else:
            item.pop('joined_from', None)   # this review's own words for it (fold_same joins any twin again below)
        if full_round:
            item.pop('now', None)       # a reviewer read this cut whole: its own words are the note now
        item.update(what=f['what'], at=f.get('at', ''), at_s=f.get('at_s'), severity=f['severity'], fix=f.get('fix', ''),
                    owner=f['owner'], status='person' if f['owner'] == 'person' or was_person else 'open')
        if item.get('now'):
            f['what'] = item['now']     # a look rewrote it for this cut: the last round's quote is gone
        if was_person:
            f['owner'] = 'person'
        f['id'] = item['id']
        matched.add(item['id'])
        out.append(f)
    fixed_now = []
    for item in mem['items']:
        if item['id'] in matched:
            continue
        state = said.get(item['id'])
        if item['status'] == 'person' and state != 'fixed':
            out.append(_carried(item))
        elif item['status'] == 'open' and item['source'] == 'critic' and state != 'fixed' and (state == 'still_open' or not full_round):
            # no reviewer has looked since (past the round limit, say): it stays open, or a video reads ready with it unfixed
            out.append(_carried(item))
        elif item['status'] == 'open' and (item['source'] != 'critic' or full_round or state == 'fixed'):
            item['status'] = 'fixed'       # measured checks read clean, or the reviewer looked again and didn't raise it
            fixed_now.append(item)
        elif item['status'] == 'person':
            item['status'] = 'fixed'
            fixed_now.append(item)
    mem['_fixed_now'] = fixed_now
    if full_round:
        mem['rounds'].append({'round': rounds_done(mem) + 1, 'when': time.strftime('%Y-%m-%dT%H:%M:%S'), 'video': str(video or ''),
                              'engine': (review or {}).get('engine'), 'verdict': (review or {}).get('verdict'),
                              **({'project_hash': project_hash} if project_hash else {}), **(round_facts or {})})
    return fold_same(mem, out)


def _carried(item):
    return {'source': item['source'], 'severity': item['severity'], 'at_s': item.get('at_s'), 'at': item.get('at', ''),
            'what': item.get('now') or item['what'], 'evidence': "from the reviewer's last round; critic='again' has a reviewer look again" if item['source'] == 'critic' and item.get('status') != 'person' else '',
            'fix': item.get('fix', ''), 'owner': item.get('owner', 'ai'), 'id': item['id'],
            'carried': True}
