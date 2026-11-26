"""Which `##` sections of each letitedit skill a New video sub-step's copy carries: the data of stage_start's
`substep_scoped_skills` switch (on by default; letitedit.app.stage_start reads it, on sub-step starts only).

SKILLS, per skill:
- body_sha1: the SKILL.md body (after its frontmatter, LF line ends) the entries were checked against. When the file
  says anything else, none of the skill's entries act and it is attached in full: an edited skill is never scoped by
  entries written for its old text. After editing a skill, check its entries against the new text, then set the new
  hash (stage_start.body_sha1 prints it; test_session_side_cuts names each skill that no longer matches);
- assessed: the sub-steps whose need of each section was checked. A sub-step outside this list keeps every section;
- sections: per section heading (matched by its name: its number and a closing parenthesis left out), the sub-steps
  that need it. Each assessed sub-step not named gets the heading and one line instead, saying why and where the whole
  section is. A section not listed is attached wherever the skill is, and so is the text before the first `##`.

Widening the scoping is adding entries here; stage_start's code stays as it is. The entries came from reading every
section against what each sub-step does (the sub-steps' work in letitedit.app.substeps, the skills' own When and
Check lines); a section was listed only where no sub-step left out could need it, and kept wherever unsure. Rules
that hold to the export, honesty, faces, licences, safety, the brief's must-keep and claims stay everywhere.

WHY: an optional line, per skill and section, a sub-step without it reads; without one the line names the sub-steps
that use the section.

ATTACH: skills a sub-step's start adds with the switch on, where its work needs them and the route didn't attach
them: letitedit-story at the rough cut (it restructures on evidence and updates story_plan.json and the pickups), and
letitedit-fine at both review sub-steps (their fixes retime cuts, joins and holds). Each is attached in full there
(every section applies) and is assessed there.
"""

SKILLS = {
    'letitedit': {
        'body_sha1': '9eb2fb812c3d9576a136cea5b66d5b969da54729',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 1. Fix the brief': ('log_plan',),
        },
    },
    'letitedit-craft': {
        'body_sha1': 'bfcccd1605d65df9afecaa73e0469ed5b1630dbd',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 9. Before a render is shown': ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-modes': {
        'body_sha1': 'f7c1cd1fbbd200a89e0ed3a78adec04761b00b83',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 1. Pick the mode': ('log_plan', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-firstcut': {
        'body_sha1': '31ed0cdeca88b57cdc131a0ba730454a683a1df1',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 1. Build it, one stage at a time': ('log_plan', 'rough_cut'),
            '## 1a. Building the cut': ('log_plan', 'rough_cut', 'fine_cut', 'finishing'),
            '## 4. Review it, then show it': ('fine_cut', 'finishing', 'review_rounds', 'final_look'),
            '## 5. Plain-language fixes': ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-log': {
        'body_sha1': '791ee944ecbff08ee165e701b210df6ad980efcf',
        'assessed': ('log_plan',),
        'sections': {},
    },
    'letitedit-story': {
        'body_sha1': '2a4421ce4d39bf30557925c27abe04cd50fb5ba1',
        'assessed': ('log_plan', 'rough_cut'),
        'sections': {},
    },
    'letitedit-rough': {
        'body_sha1': '066948359e4ac872ab74fa5ffb9aeffc942bc085',
        'assessed': ('rough_cut',),
        'sections': {},
    },
    'letitedit-fine': {
        'body_sha1': 'b21112511a889b985eaf12e153dd6e67151b77ce',
        'assessed': ('fine_cut', 'review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-finish': {
        'body_sha1': '9edc9cf46f45d75c9fe5d60bb5da5e89dec6c6f4',
        'assessed': ('finishing',),
        'sections': {},
    },
    'letitedit-gate': {
        'body_sha1': '100728b6b3d2ea9b3e9869f472b00ddcc18c78ba',
        'assessed': ('review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-review': {
        'body_sha1': 'fbb4ca3bd0c3d839757e71d08a5000eb55c1b72d',
        'assessed': ('review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-shorts': {
        'body_sha1': '45c12458fc42f8c57fe9d47a56a10e9ddd80d566',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 11. Export per platform': ('finishing', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-broll': {
        'body_sha1': 'cdf1f0661219ac11c00d9e452567226b5cdbf081',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 4. Sound under b-roll': ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-graphics': {
        'body_sha1': 'cde65ed4121b0ee28a6b1528b26db9742a5d2aa8',
        'assessed': ('log_plan', 'rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 7. Hand-off': ('finishing', 'review_rounds', 'final_look'),
        },
    },
    'letitedit-layers': {
        'body_sha1': '72c2e5ff7cf5765f6371ead0d6575c61944f2e7d',
        'assessed': ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-motion': {
        'body_sha1': 'bd30cee34904fbf7bb8fdf42ccfcfbfd322d6a89',
        'assessed': ('rough_cut', 'fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-captions': {
        'body_sha1': '92afd69284b473dbc923312f12f79b2ab32c767d',
        'assessed': ('fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {},
    },
    'letitedit-sound': {
        'body_sha1': 'ac50a111e6f17b6292f038871385524adfebae58',
        'assessed': ('fine_cut', 'finishing', 'review_rounds', 'final_look'),
        'sections': {
            '## 9. Loudness by deliverable (the one table)': ('finishing', 'review_rounds', 'final_look'),
        },
    },
}

WHY = {
    'letitedit': {
        'Fix the brief': 'brief.json was written in the log-and-plan sub-step; it is attached, and the hand-off '
                         'carries its requirements word for word',
    },
    'letitedit-craft': {
        'Before a render is shown': 'the log-and-plan sub-step makes no edit and no render',
    },
    'letitedit-modes': {
        'Pick the mode': "the mode was chosen in the log-and-plan sub-step (the `modes:` note), and the lead mode's "
                         "playbook comes attached from the brief's mode",
    },
    'letitedit-firstcut': {
        'Build it, one stage at a time': 'the log, story and rough-cut steps are done',
        'Building the cut': 'the cut is built: the review fixes what the review finds, and the rules that hold to the '
                            'export are in their own section',
        'Review it, then show it': 'nothing is reviewed or shown before the fine cut',
        'Plain-language fixes': 'there is no cut yet to fix',
    },
    'letitedit-shorts': {
        'Export per platform': 'the exports per platform come at the finish; earlier sub-steps render previews only',
    },
    'letitedit-broll': {
        'Sound under b-roll': 'the log-and-plan sub-step makes no edit and no mix',
    },
    'letitedit-graphics': {
        'Hand-off': 'the graphics pass runs at the finish',
    },
    'letitedit-sound': {
        'Loudness by deliverable': 'the fine cut runs no score and makes no deliverable export; levels and the master '
                                   'come at the finish',
    },
}

ATTACH = {
    'rough_cut': ('letitedit-story',),
    'review_rounds': ('letitedit-fine',),
    'final_look': ('letitedit-fine',),
}
