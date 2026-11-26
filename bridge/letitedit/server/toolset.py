"""Which letitedit tools a run gets, from toolset.txt next to bridge\\ (read when a server or script starts; the one
switch: LETITEDIT_TOOLS is not read):

    v2                        first line: the tool set (v2 is the only one; the server offers it whatever this says)
    without: letitedit_qc     optional: tools left out (comma-separated), from the server, the guide and letitedit_ai

Tools left out are not offered as MCP tools, not reachable through letitedit_ai.tool() or their letitedit_ai function,
and their rows and mentions are taken out of the guide.

A tool profile (tool_profiles.py, on by default) narrows one tool server further, to a New video or Studio phase's
tools: the others stay in the guide and in letitedit_ai. Tools left out here are left out of every profile too.
"""
from __future__ import annotations

import re
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
FILE = _paths.CODE_ROOT / 'toolset.txt'


def read():
    """(name or None, set of tool names left out)."""
    try:
        lines = [ln.strip() for ln in FILE.read_text(encoding='utf-8').splitlines() if ln.strip()]
    except OSError:
        return None, set()
    name = lines[0].lower() if lines and ':' not in lines[0] else None
    without = set()
    for ln in lines:
        if ln.lower().startswith('without:'):
            without |= {t.strip() for t in ln.split(':', 1)[1].split(',') if t.strip()}
    return name, without


def without():
    return read()[1]


# what each tool's Python function is called in letitedit_ai
SA_NAMES = {'letitedit_qc': 'qc', 'letitedit_check_audio': 'audio', 'letitedit_check_range': 'check_range',
            'letitedit_footage': 'footage', 'letitedit_words': 'words', 'letitedit_export': 'export'}


def filter_guide(text, left_out=None):
    """The guide without the rows, sentences and letitedit_ai functions of tools left out."""
    left_out = without() if left_out is None else left_out
    for tool in left_out:
        out = []
        for ln in text.splitlines():
            if ln.startswith(f'| `{tool}('):
                continue
            out.append(ln)
        text = '\n'.join(out) + ('\n' if text.endswith('\n') else '')
        sa = SA_NAMES.get(tool)
        if sa:
            text = re.sub(r'`sa\.' + re.escape(sa) + r'\([^`]*\)`,\s*', '', text)
    return text
