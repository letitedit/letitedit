"""The letitedit skills by section: an index of each skill (its sections, each with its job and size) and any
sections read in one call, from the skills' own SKILL.md files, unchanged (tests/t194/sections-plan.md).

    index(skills)      text: per skill its description and sections, `<skill>#<id>  <job>  (~N tokens)`
    read(refs)         text: the sections asked for (`<skill>#<id>`), or a whole skill (`<skill>`), in the skill's order
    sections(skill)    [{id, job, text}] covering the whole SKILL.md body, in order, nothing left out

A section is a `## ` heading's text; one longer than SPLIT_AT characters is split at its `### ` headings and its tagged
rules (`**FIRST-3c Batch checks ...**`), the text before the first of them staying with the heading. A skill's text
before its first `## ` is split where ANCHORS say (lines that start a part, with its job), else kept as `intro`.
Joined in order the sections are the body exactly; an anchor whose line is gone keeps the part with the one before it
(bridge/tests/app/test_skill_sections.py catches that).

The switch: settings.json `skill_sections` (default true; the environment variable LETITEDIT_SKILL_SECTIONS, 1 or 0,
wins). Off, letitedit_skill isn't offered and the server's instructions are as before.
"""
import os
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[3] / 'skills'
SETTING = 'skill_sections'
ENV = 'LETITEDIT_SKILL_SECTIONS'
WHOLE = ('letitedit', 'letitedit-craft')       # read whole, with the Skill tool, every time
SPLIT_AT = 5000                                 # characters; a longer `## ` section is split further
CHARS_PER_TOKEN = 3.6
RULE = re.compile(r'^\*\*([A-Z]+-[0-9][0-9A-Za-z]*) ([^*]+?)\*\*')
# a skill's text before its first `## `: (the line it starts with, id, job)
ANCHORS = {
    'letitedit-learned-look': [
        ('Measured Look devices are placed', 'look-devices', 'a measured Look: every device placed or declined with '
         'evidence; speaker lighting on every clip; punch-ins and sound accents'),
        ("A person's words about their face", 'own-face', 'what a person asks for their own face; synced sounds, camera '
         'moves, cutaway slots and cut flashes from a measured Look; how to decline a device'),
        ('For an inverted-then-white caption Look', 'inverted-captions', 'inverted-then-white captions'),
        ('For a measured Look,', 'look-check', 'before export, what letitedit_look_check needs of a measured Look: '
         'its receipts and source units'),
        ('When the Look catalog exposes graphic_kit', 'graphic-kit', "a Look's graphic kit: placing, the frozen "
         'layout, the face, kit_check and repairs'),
        ('A learned Look whose card has `place`', 'look-format', "a learned Look that is also a format: fit, building "
         'its sections, plan_check'),
        ("Without a saved kit, keep the Look's", 'sources', "typography without a kit; a Look's sources.json, shot "
         'sources receipt and provenance'),
        ("For b-roll, record each shot's", 'broll-receipt', "a measured Look's b-roll: the receipt, cutaways per "
         'minute and spread, inverted Looks, relevant share'),
        ('Lighting that exceeds the face limit', 'export-checks', 'lighting limits; checks on the '
         'exported bytes; review findings'),
    ],
}


def enabled():
    """Whether the skills are offered by section on this install (on by default)."""
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def _slug(text):
    text = text.strip().lower()
    number = re.match(r'^(\d+[a-z]?)\.\s', text)
    if number:
        return number.group(1)
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:40] or 'part'


def _source(skill):
    path = SKILLS / skill / 'SKILL.md'
    if not re.fullmatch(r'letitedit(-[a-z0-9]+)*', skill or '') or not path.is_file():
        raise ValueError(f'no letitedit skill named {skill!r}; the skills: {", ".join(names())}')
    return path.read_text(encoding='utf-8')


def names():
    return sorted(p.parent.name for p in SKILLS.glob('letitedit*/SKILL.md'))


def _front(text):
    """(description, body): the frontmatter's description and the text after the frontmatter."""
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            head, body = text[:end], text[text.index('\n', end + 1) + 1:]
            found = re.search(r'^description:\s*(.+)$', head, re.MULTILINE)
            return (found.group(1).strip() if found else ''), body
    return '', text


def _cut(lines, starts):
    """Split lines into parts at the given (index, id, job) starts; the lines before the first start stay with
    `lead` (id, job)."""
    parts = []
    for n, (at, sid, job) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        parts.append({'id': sid, 'job': job, 'text': ''.join(lines[at:end])})
    return parts


def sections(skill):
    """[{id, job, text}], in order; joined they are the SKILL.md body exactly."""
    _, body = _front(_source(skill))
    lines = body.splitlines(keepends=True)
    heads = [i for i, ln in enumerate(lines) if ln.startswith('## ')]
    blocks = [(0, heads[0] if heads else len(lines))] + [(h, heads[n + 1] if n + 1 < len(heads) else len(lines))
                                                        for n, h in enumerate(heads)]
    out, used = [], set()
    for b, (a, z) in enumerate(blocks):
        chunk = lines[a:z]
        if not chunk:
            continue
        if b == 0:                                   # before the first `## `
            starts = [(0, 'intro', (chunk[0].lstrip('# ').strip() if chunk[0].startswith('#') else 'the opening'))]
            for line_start, sid, job in ANCHORS.get(skill, []):
                at = next((i for i, ln in enumerate(chunk) if ln.startswith(line_start)), None)
                if at is not None and at > starts[-1][0]:
                    starts.append((at, sid, job))
            parts = _cut(chunk, starts)
            if len(parts) > 1 and len(parts[0]['text']) < 200:   # only the title: it goes with the next part
                parts[1]['text'] = parts[0]['text'] + parts[1]['text']
                parts = parts[1:]
        else:
            head = chunk[0][3:].strip()
            sid = _slug(head)
            parts = [{'id': sid, 'job': head, 'text': ''.join(chunk)}]
            if len(parts[0]['text']) > SPLIT_AT:
                starts = [(0, sid, head)]
                for i, ln in enumerate(chunk[1:], 1):
                    rule = RULE.match(ln)
                    if ln.startswith('### '):
                        starts.append((i, f'{sid}/{_slug(ln[4:])}', ln[4:].strip()))
                    elif rule:
                        starts.append((i, f'{sid}/{rule.group(1)}', f'{rule.group(1)} {rule.group(2).strip()}'))
                parts = _cut(chunk, starts)
        for part in parts:
            base, k = part['id'], 2
            while part['id'] in used:                # two headings with the same words
                part['id'] = f'{base}-{k}'
                k += 1
            used.add(part['id'])
            out.append(part)
    return out


def _tokens(text):
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def index(skills):
    """Each skill's description and sections, one line each: `<skill>#<id>  <job>  (~N tokens)`."""
    blocks = []
    for skill in skills:
        description, _ = _front(_source(skill))
        parts = sections(skill)
        lines = [f'## {skill} (~{_tokens("".join(p["text"] for p in parts))} tokens whole)', description, '']
        lines += [f'{skill}#{p["id"]}  {p["job"]}  (~{_tokens(p["text"])} tokens)' for p in parts]
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def read(refs):
    """The sections asked for, each under a line naming it, in each skill's own order; `<skill>` alone is the whole
    skill. Unknown ids are named in the reply, with the skill's ids."""
    wanted, order = {}, []
    for ref in refs:
        skill, _, sid = str(ref).strip().partition('#')
        if skill not in wanted:
            wanted[skill] = set()
            order.append(skill)
        wanted[skill].add(sid or '*')
    out = []
    for skill in order:
        parts = sections(skill)
        ids = {p['id'] for p in parts}
        ask = wanted[skill]
        unknown = sorted(s for s in ask if s != '*' and s not in ids and not any(i.startswith(s + '/') for i in ids))
        if unknown:
            out.append(f'(no section {", ".join(unknown)} in {skill}; its sections: {", ".join(sorted(ids))})')
        for p in parts:
            if '*' in ask or p['id'] in ask or any(p['id'].startswith(s + '/') for s in ask):
                out.append(f'--- {skill}#{p["id"]}\n{p["text"].rstrip()}\n')
    return '\n'.join(out)


INSTRUCTIONS = (
    " On this install the letitedit skills are read by section: the `letitedit` router and letitedit-craft whole, with "
    "the Skill tool; of every other letitedit-* skill a step needs, its index (letitedit_skill(index=[those skills]), "
    "one call) and then every section the step needs, in one call (letitedit_skill(sections=['<skill>#<id>', ...])), "
    "or the whole skill ('<skill>') when most of it applies. Where a skill says to load or read another skill, this is "
    "how it is read.")
LOAD = ("the `letitedit` router and letitedit-craft whole (the Skill tool); of each other skill, its index and then "
        "every section the stage needs, through letitedit_skill (each in one call)")
