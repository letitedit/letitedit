"""The v2 reference (toolset.txt 'v2'): an index by default; any tool's full description, or one section, on request.

    letitedit_guide()              the index: what a project is, every tool in a line, the section names
    letitedit_guide('look')        that tool's full description (with or without the 'letitedit_' prefix)
    letitedit_guide('edits')       one section of C:\\LetItEdit\\GUIDE_V2.md
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
FILE = _paths.CODE_ROOT / 'GUIDE_V2.md'


def _split(text):
    """(index text, {section key: section text}) for a guide whose sections are '## key: title' headings."""
    parts = text.split('\n## ')
    index, sections = parts[0].rstrip() + '\n', {}
    for part in parts[1:]:
        head, _, body = part.partition('\n')
        if ':' not in head:                       # '## Tools' and other headings without a key stay in the index
            index += f'\n## {head}\n{body}'.rstrip() + '\n'
            continue
        key = head.split(':', 1)[0].strip().lower()
        sections[key] = f'## {head}\n{body}'.rstrip() + '\n'
    return index, sections


def text(topic=None, long_docs=None, without=()):
    import letitedit.server.toolset as toolset
    guide = toolset.filter_guide(FILE.read_text(encoding='utf-8'), set(without or ()))
    index, sections = _split(guide)
    if not topic:
        return index
    t = str(topic).strip().lower()
    if t in sections:
        return sections[t]
    import letitedit.timeline.op_specs as op_specs
    if t in ('ops', 'op'):
        return op_specs.text()
    if t in op_specs.OPS or (t.startswith('op ') and t[3:] in op_specs.OPS):
        return op_specs.text(t[3:] if t.startswith('op ') else t)
    long_docs = long_docs or {}
    name = t if t.startswith('letitedit_') else f'letitedit_{t}'
    if name in long_docs and name not in set(without or ()):
        return f'{name}\n\n' + textwrap.dedent(long_docs[name]).strip() + '\n'
    names = sorted(n[len('letitedit_'):] for n in long_docs if n not in set(without or ()))
    # anything else: every paragraph of the guide and of the tool descriptions that mentions it
    import re
    word = re.compile(r'(?<![a-z0-9_])' + re.escape(t) + r'(?![a-z0-9_])')
    hits = []
    for key, body in sections.items():
        for para in body.split('\n- '):
            if word.search(para.lower()):
                hits.append(f'[{key}] - {para.strip()}')
    for n in names:
        doc = textwrap.dedent(long_docs.get(f'letitedit_{n}', ''))
        for para in doc.split('\n\n'):
            if word.search(para.lower()):
                hits.append(f'[{n}] {para.strip()}')
    head = (f"'{topic}' is not a section or a tool name (sections: {', '.join(sorted(sections))}; tools: "
            f"{', '.join(names)}).")
    if not hits:
        raise ValueError(head + ' Nothing in the guide mentions it.')
    def around(h, room=500):           # long paragraphs: the part around the first mention
        if len(h) <= room:
            return h
        m = word.search(h.lower())
        a = max(0, (m.start() if m else 0) - room // 3)
        return ('...' if a else '') + h[a:a + room].strip() + '...'
    hits = [around(h) for h in hits]
    more = f'\n\n({len(hits) - 8} more mentions not shown)' if len(hits) > 8 else ''
    return head + ' Where the guide mentions it:\n\n' + '\n\n'.join(hits[:8]) + more + '\n'
