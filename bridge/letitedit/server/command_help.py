"""The app's How to reference: command-reference.json at the install root, the same entries the editor's AI > How to /
Command Finder shows. Searched here without an editor window, the way the window searches (an entry matches when the
query appears anywhere in it, any case); a question that matches no entry as a whole is answered with the entries that
mention most of its words.

    search(query)           [entry, ...] (at most 10; every entry for an empty query)
    register(mcp, Image)    letitedit_command_help

An entry: id, title, action (the editor command it runs, when it has one), selection (what to open or select and
where the button is), behavior (what it does and how to undo it), shortcut, example (something a person might say),
limits, also_called (older names and other words for it: not shown, but searching for one finds the entry).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.environ.get('LETITEDIT_ROOT') or _paths.CODE_ROOT)
FILE = ROOT / 'command-reference.json'
STOP = {'how', 'do', 'does', 'can', 'the', 'a', 'an', 'to', 'of', 'in', 'on', 'i', 'my', 'me', 'is', 'what', 'and',
        'or', 'for', 'with', 'it', 'this', 'that', 'from', 'at', 'by', 'you', 'your', 'want', 'make', 'use', 'using',
        'way', 'into', 'out', 'up', 'be', 'get', 'should', 'where', 'there', 'find', 'button'}
SYNONYMS = {'part': ['section', 'range'], 'piece': ['section'], 'chunk': ['section'], 'bit': ['section'],
            'remove': ['delete'], 'erase': ['delete'], 'cut': ['split', 'delete', 'cut'], 'captions': ['caption'],
            'subtitles': ['caption', 'subtitle'], 'subtitle': ['caption'], 'song': ['music'], 'sound': ['audio', 'sound'],
            'louder': ['volume', 'level'], 'quieter': ['volume', 'level'], 'opening': ['hook', 'opening'],
            'intro': ['hook', 'opening'], 'start': ['opening', 'new video'], 'begin': ['new video'],
            'notes': ['review', 'notes'], 'draw': ['review'], 'mark': ['review'], 'feedback': ['review'],
            'look': ['look'], 'brand': ['my looks', 'look'], 'emoji': ['elements', 'emoji'],
            'sticker': ['elements', 'sticker'], 'effects': ['effect', 'elements'], 'sfx': ['sound effect'],
            'vertical': ['short', 'vertical'], 'tiktok': ['short', 'sizes'], 'reels': ['short', 'sizes'],
            'size': ['sizes'], 'resize': ['sizes'], 'ai': ['ai'], 'chat': ['ask the ai'],
            'claude': ['connect your ai', 'ask the ai'], 'codex': ['connect your ai', 'ask the ai'],
            'credit': ['credit', 'licence'], 'license': ['licence'], 'pauses': ['pause'], 'silence': ['pause'],
            'translate': ['translate'], 'language': ['translate'], 'example': ['learn a look']}


def entries(path=None):
    p = Path(path or FILE)
    if not p.is_file():
        raise FileNotFoundError(f'The How to reference is not installed ({p})')
    data = json.loads(p.read_text(encoding='utf-8-sig'))
    return [e for e in data if isinstance(e, dict)]


def _text(e):
    return json.dumps(e, ensure_ascii=False).lower()


def search(query='', path=None, limit=10):
    """Entries for a query: every entry that holds the query as written (those with it in their title first);
    otherwise the ones mentioning the most of its words (and their usual synonyms), best first."""
    all_ = entries(path)
    q = (query or '').strip().lower()
    if not q:
        return all_
    exact = [e for e in all_ if q in _text(e)]
    if exact:       # the window's own order, entries with the words in their title first
        return sorted(exact, key=lambda e: q not in str(e.get('title', '')).lower())[:limit]
    words = [w for w in re.findall(r"[a-z0-9']+", q) if w not in STOP and len(w) > 2]
    words = list(dict.fromkeys(words + [s for w in words for s in SYNONYMS.get(w, [])]
                               + [w[:-1] for w in words if w.endswith('s') and len(w) > 4]))

    def score(e):
        text, title = _text(e), str(e.get('title', '')).lower()
        return sum(1 for w in words if w in text) + sum(1.5 for w in words if w in title)
    ranked = sorted((e for e in all_ if score(e) > 0), key=score, reverse=True)
    return ranked[:limit]


def register(mcp, Image):  # noqa: ARG001 - the shared register(mcp, Image) form
    @mcp.tool()
    def letitedit_command_help(query: str = '') -> list:
        """The app's How to reference, the same one the person sees under AI > How to / Command Finder: for a feature
        (New video, New hook, Review, My Looks, Captions, Remove pauses, Add music, Other sizes,
        styles, the Elements panel...) where its button is, what to open or select first, what it does, how to undo
        it, a shortcut and its limits. query: words or a plain question ("how do I change the opening"); empty: every
        entry. Each entry: id, title, action (the editor command, when there is one), selection, behavior, shortcut,
        example, limits. Works without an editor window."""
        return search(query)

    return letitedit_command_help
