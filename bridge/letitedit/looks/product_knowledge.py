"""Limits for reusable editing instructions, separate from private evidence."""
import re

LEARNED_RECIPE_WORDS = 1000
BUILTIN_RECIPE_WORDS = 3000
HISTORY_PATTERNS = (
    ("task number", r"\bT\d{2,4}\b"),
    ("development evidence tag", r"\[OURS\s*[:,]"),
    ("development archive reference", r"dev[-_]history"),
    # the owner's first name is split in two so this shipped file never holds it whole (the guard still matches it)
    ("development participant", r"\b(?:" + "Ran" + r"som|orchestrator|Luna)\b"),
    ("owner instruction", r"\b(?:the owner(?:['\u2019]s)? (?:request|quote|feedback|test|window)|owner['\u2019]s (?:request|quote|feedback|test))\b"),
    ("test anecdote", r"\b(?:test|trial)[ -](?:run|round)\b"),
    ("model run anecdote", r"\b(?:Sonnet|Opus|Claude|Codex)\b[^\n.]{0,90}\b(?:run|scored|judge)\b"),
    ("local run anecdote", r"\b(?:a real|our|the strongest) (?:\w+[ -]){0,6}run\b"),
    ("sample review history", r"\b(?:current (?:private )?sample|internal proof|local demonstration|combined reviews? (?:say|says))\b"),
    ("local comparison history", r"\b(?:our (?:own |earlier |viewer )?(?:tests?|rounds?)|own test renders|loop \d+ round \d+)\b"),
    ("earlier test history", r"\b(?:earlier small tests|the real \d{1,2} \w+ beta first cut|earlier gate pass still needed)\b"),
    ("private study placeholder", r"the team['\u2019]s internal study"),
    ("local sample anecdote", r"\b(?:on the sample|the first local .*? sample|measured on the sample|our comparisons|sample result, his)\b"),
    ("private audit pointer", r"(?:audit-existing-skills|CHANGELOG-(?:craft|shorts-gate))\.md"),
    ("local sample history", r"\b(?:local sample (?:boundary|revision)|first sample (?:had|preserved))\b"),
    ("test artifact reference", r"(?:tests|tasks)[/\\]t?\d{2,4}\b"),
)


def issues(text):
    return [label for label, pattern in HISTORY_PATTERNS if re.search(pattern, text, re.I)]


def validate(text, label, limit=None):
    problems = issues(text)
    words = len(text.split())
    if limit is not None and words > limit:
        problems.append(f"{words} words exceeds the {limit}-word limit")
    if problems:
        raise ValueError(f"{label}: " + "; ".join(problems) +
                         ". Keep instructions and key numbers here; keep raw evidence in data files.")
    return words
