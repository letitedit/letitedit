"""A review panel (LETITEDIT_CRITIC_DEPTH=panel, for comparing review designs): one strong critic for story and pacing on
the person's own model, cheaper reviewers in parallel each on one area (captions and on-screen words, sound, motion
and graphics) with that area's skills read in full, and one merger on the person's model that de-duplicates, drops what
has no evidence and gives one prioritised list in review.json's usual shape.

The panel's size follows the video: the motion and graphics reviewer joins when anything arrives on top of the picture
and gets every frame around each arrival in a dense video; a long video's area reviewers each take a slice of it at a
frame a second. The code's measured checks are given to every reviewer as done: they add what the pictures, the words
and the measurements show beyond them, never redo them.

Cheaper models: Claude Sonnet, Codex GPT-6-Luna (CHEAP); the strong critic and the merger use the person's model and
effort, as today's critic does. With only one AI on the PC, every member runs on it.
"""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CHEAP = {'claude': ('sonnet', 'medium'), 'codex': ('gpt-6-luna', 'medium')}
SKILLS = Path(__file__).resolve().parents[2]
AREA_SKILLS = {'story': ['letitedit-craft'], 'captions': ['letitedit-captions'], 'sound': ['letitedit-sound'],
               'motion': ['letitedit-motion', 'letitedit-graphics']}
AREA_JOB = {
    'story': 'story and pacing: can you retell it, does it keep its promise, does each section start, develop and end, '
             'where does it drag or rush, shot choice and order, the opening and the ending',
    'captions': 'captions and every word on screen: correct words and spelling, chunking, reading time, placement clear '
                'of faces, action and the apps\' buttons, one kind of caption through the video, legible at feed size',
    'sound': 'sound, from the level graph, the measurements and the words (you cannot hear it): music in and out on story '
             'moments, music against speech, words clipped at cuts, silences, loudness steps between shots',
    'motion': 'motion and graphics: how each element arrives, settles, holds and leaves, its timing against the words, '
              'one focal point at a time, nothing covering a caption, a face covered only when the Look or the moment '
              'calls for it, moves that look cheap or stiff',
}
# The references/ files an area's skills keep for some videos: each reviewer gets the ones whose route applies to this
# video (letitedit.app.stage_start's routes, read from the brief and the Look's recipe), as the editor did. The motion
# reviewer judges real and generated pictures on screen, so it gets those two whenever it sits.
AREA_REFS = {'sound': [('letitedit-sound', n) for n in ('music-choice', 'written-music', 'learned-sound',
                                                         'song-when-posting')],
             'captions': [('letitedit-captions', 'look-captions')],
             'motion': [('letitedit-graphics', n) for n in ('real-pictures', 'images')]}
SLICE_S = {'normal': 300.0, 'dense': 120.0}      # a long video's area reviewers each take a slice this long
MAX_SLICES = 3
WORKERS = 4                # reviewers asked at once (each is a program on this PC: light)
SKILL_MAX = 60000          # characters of one skill file


def area_refs(area, ctx):
    """(skill, reference name) pairs for an area on this video: AREA_REFS filtered by the video's routes. Without the
    route reader (an older bridge), every one of the area's references comes, as a safe superset."""
    pairs = AREA_REFS.get(area, [])
    try:
        from letitedit.app import stage_start
        brief = json.loads(ctx.get('brief_text') or '{}') if str(ctx.get('brief_text') or '').strip().startswith('{') \
            else {}
        active = stage_start.text_routes(brief, ctx.get('look_recipe') or '')
    except Exception:  # noqa: BLE001 - no route reader: give them all
        return list(pairs)
    out = []
    for skill, name in pairs:
        rule = stage_start.REFERENCES.get(f'{skill}/references/{name}.md')
        if rule is None or set(rule['routes']) & active:      # not a routed file (pictures): always for its reviewer
            out.append((skill, name))
    return out


def skill_text(names, modes=(), refs=()):
    """The area's skills in full (SKILL.md), then the area's references for this video, plus the mode playbooks for
    the story critic."""
    parts = []
    for name in names:
        f = SKILLS / name / 'SKILL.md'
        if f.is_file():
            parts.append(f'=== {name} ===\n' + f.read_text(encoding='utf-8', errors='replace')[:SKILL_MAX])
    for skill, name in refs:
        f = SKILLS / skill / 'references' / f'{name}.md'
        if f.is_file():
            parts.append(f'=== {skill} references/{name}.md ===\n'
                         + f.read_text(encoding='utf-8', errors='replace')[:SKILL_MAX])
    for path in modes:
        if Path(path).is_file():
            parts.append(f'=== {Path(path).stem} (the playbook for this kind of video) ===\n'
                         + Path(path).read_text(encoding='utf-8', errors='replace')[:SKILL_MAX])
    return '\n\n'.join(parts)


def theme_text(brief):
    """The chosen Theme's recipe, when the brief names one."""
    theme = (brief or {}).get('theme')
    if not theme or theme in ('auto', 'none', 'freestyle'):
        return ''
    root = SKILLS.parent / 'looks'
    try:
        entries = json.loads((root / 'themes.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return ''
    entries = entries if isinstance(entries, list) else entries.get('themes') or []
    entry = next((e for e in entries if e.get('id') == theme), None)
    if not entry:
        return ''
    text = [f"Theme: {entry.get('title') or theme}. {entry.get('blurb') or ''}"]
    for key in ('recipe', 'recipe_shared'):
        f = root / str(entry.get(key) or '')
        if entry.get(key) and f.is_file():
            text.append(f.read_text(encoding='utf-8', errors='replace')[:SKILL_MAX])
    return '\n'.join(text)


def plan(duration, motion, has_words_on_screen=True):
    """The panel for a video: [{id, area, tier, slice}]. Size by length and density."""
    dense = bool(motion.get('dense'))
    arrivals = bool(motion.get('arrivals'))
    members = [{'id': 'story', 'area': 'story', 'tier': 'person', 'slice': None}]
    areas = (['captions'] if has_words_on_screen else []) + ['sound'] + (['motion'] if arrivals or dense else [])
    for area in areas:
        span = SLICE_S['dense' if dense and area in ('motion', 'captions') else 'normal']
        n = 1 if area == 'sound' or duration <= span * 1.25 else min(MAX_SLICES, math.ceil(duration / span))
        for k in range(n):
            a, b = duration * k / n, duration * (k + 1) / n
            members.append({'id': area if n == 1 else f'{area}-{k + 1}', 'area': area, 'tier': 'cheap',
                            'slice': None if n == 1 else (round(a, 2), round(b, 2))})
    return members


def _mmss(t):
    return f'{int(t // 60)}:{int(t % 60):02d}'


def slice_pages(video, a, b, out, portrait):
    """Contact pages of a slice at a frame a second (denser than the whole video's)."""
    import review_bundle
    gate = review_bundle._gate()
    folder = Path(out) / f'panel-slice-{int(a)}-{int(b)}'
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('*.jpg'):
        old.unlink()
    review_bundle._run([gate.FFMPEG, '-v', 'error', '-y', '-ss', f'{a:.2f}', '-t', f'{b - a:.2f}', '-i', video, '-vf',
                        f"fps=1,scale={160 if portrait else 256}:-2", '-q:v', '4', str(folder / 'f_%05d.jpg')], heavy=True)
    frames = [(a + i, p) for i, p in enumerate(sorted(folder.glob('f_*.jpg')))]
    return [p['file'] for p in review_bundle.pages(frames, folder, portrait)]


def member_prompt(member, ctx):
    area = member['area']
    span = member['slice']
    where = (f'You review ONLY {_mmss(span[0])} to {_mmss(span[1])} of the video (another reviewer has the rest); '
             'judge what happens in that stretch.' if span else 'You review the whole video.')
    skills = skill_text(AREA_SKILLS[area], ctx.get('mode_files') if area == 'story' else (), area_refs(area, ctx))
    code = ctx.get('code_findings') or []
    measured = ('The code has already measured these and they are in the review: '
                + '; '.join(f"{c.get('at') if c.get('at') is not None else ''} {c.get('what')}"[:160] for c in code[:80])
                + '. Do not repeat them or re-measure what they measure (lengths, loudness, cut rates, caption reading '
                'speed, words cut at clip edges, landing on the word); add only what the pictures, words and '
                'measurements show beyond them.') if code else ''
    story_bits = ''
    if area == 'story':
        story_bits = ((f"The editor's story plan (where it differs from the brief, the brief wins):\n{ctx['plan_text']}\n\n"
                       if ctx.get('plan_text') else '')
                      + (f"Answer these questions for this kind of video, each with evidence: {ctx['questions']}\n\n"
                         if ctx.get('questions') else ''))
    schema = ('{"verdict": "' + ('block|revise|ok-with-notes|ok' if area == 'story' else 'area') + '", '
              + ('"retell": "what it is about and what it leaves the viewer with, in one sentence, or \'cannot\'", '
                 '"promise_paid": true|false, ' if area == 'story' else '')
              + '"checked": "which images and times you looked at", "problems": [{"t": "m:ss", "severity": '
              '"critical|major|minor", "kind": "story|pacing|shots|sound|text|technical|brief", "owner": "ai|person", '
              '"evidence": "the image file and tile time, or the transcript line, that shows it", "fix": "..."}], '
              '"previously": [{"id": "r1", "status": "fixed|still_open"}]}')
    return (f"You are one reviewer on a panel reviewing a {ctx['kind']} video edit for a creator. Your area: "
            f"{AREA_JOB[area]}. Other reviewers cover the other areas: stay in yours. {where} Judge only what you can "
            f"point to: every problem needs a time and evidence (an image file and tile time, or a transcript line).\n\n"
            f"Read these editing skills first; they are the standard you judge against (outside evidence is tagged in "
            f"them):\n{skills}\n\n"
            f"The brief:\n{ctx['brief_text']}\n\n"
            + (f"The Look the person chose (what it asks for is intended; flag where the render breaks it):\n"
               f"{ctx['look_recipe']}\n\n" if ctx.get('look_recipe') else '')
            + (f"{ctx['theme']}\n\n" if ctx.get('theme') else '')
            + (f"{ctx['memory_text']}\n\n" if ctx.get('memory_text') else '')
            + story_bits + (measured + '\n\n' if measured else '')
            + f"{ctx['material'][area]}\n\n"
            + f"The transcript of the render, with times, from a small speech model that mishears names (a misheard word "
            f"is at most a minor 'confirm by ear'):\n{ctx['words']}\n\n"
            + (f"{ctx['unheard_note']}\n\n" if ctx.get('unheard_note') else '')
            + f"Measurements: {json.dumps(ctx.get('numbers') or {})}\n\n"
            + "Severity: critical = should not be published as it is; major = a viewer would notice and it hurts the "
            "video; minor = polish. owner = \"person\" only for what needs something only the person has. Finding none is "
            f"a valid answer. Return JSON only: {schema}. `previously` answers the earlier findings in your area, if any.")


def merger_prompt(ctx, answers):
    listed = []
    for member, answer in answers:
        for k, p in enumerate((answer or {}).get('problems') or []):
            listed.append({'from': member['id'], 'n': k + 1, **{x: p.get(x) for x in
                           ('t', 'severity', 'kind', 'owner', 'evidence', 'fix')}})
    code = ctx.get('code_findings') or []
    return ("You merge a review panel's findings on a video edit into one list for the editor. You do not see the video. "
            "Rules: (1) one finding per problem: merge findings about the same moment and the same fault, keeping the "
            "clearest evidence and the higher severity; (2) drop a finding with no time or no evidence that names an "
            "image and tile time or a transcript line; (3) drop a finding that repeats what the code already measured "
            "(listed below), and one outside its reviewer's area that another reviewer contradicts; (4) keep owner as "
            "given unless the fix plainly needs only the edit (then ai); (5) rank them, the most damaging first. "
            "Give the verdict from what is left: block for any critical, revise for any major, else ok-with-notes or ok.\n\n"
            f"The brief:\n{ctx['brief_text'][:4000]}\n\n"
            + ("Measured by code already (in the review): "
               + '; '.join(f"{c.get('what')}"[:140] for c in code[:80]) + '\n\n' if code else '')
            + f"The panel's findings:\n{json.dumps(listed, indent=0)}\n\n"
            "Return JSON only: {\"verdict\": \"block|revise|ok-with-notes|ok\", \"problems\": [{\"rank\": 1, \"t\": "
            "\"m:ss\", \"severity\": \"critical|major|minor\", \"kind\": \"...\", \"owner\": \"ai|person\", \"evidence\": "
            "\"...\", \"fix\": \"...\", \"from\": [\"story\", ...]}], \"dropped\": [{\"from\": \"captions\", \"n\": 2, "
            "\"why\": \"no evidence | repeats the code | duplicate | contradicted\"}]}")


def _previously(answers):
    """One status per earlier finding: still open if any reviewer says so, else fixed if one says fixed."""
    status = {}
    for _, answer in answers:
        for p in (answer or {}).get('previously') or []:
            if not isinstance(p, dict) or not p.get('id'):
                continue
            if p.get('status') == 'still_open' or p['id'] not in status:
                status[p['id']] = p.get('status')
    return [{'id': k, 'status': v} for k, v in status.items()]


def run(ctx, ask, out):
    """The panel's review in review.json's shape. ask(prompt, pages, tier) -> (answer dict, info dict)."""
    t0 = time.monotonic()
    members = plan(ctx['duration'], ctx.get('motion') or {}, ctx.get('has_words_on_screen', True))
    jobs = []
    for m in members:
        pages = list(ctx['pages_for'][m['area']])
        if m['slice']:
            try:
                pages = slice_pages(ctx['video'], *m['slice'], out, ctx['portrait']) + ctx['extra_for'].get(m['area'], [])
            except Exception:  # noqa: BLE001 - the whole video's pages stand in
                pass
        jobs.append((m, member_prompt(m, ctx), pages))

    def one(job):
        m, prompt, pages = job
        start = time.monotonic()
        answer, info = ask(prompt, pages, m['tier'])
        return m, answer, {**info, 'seconds': round(time.monotonic() - start, 1), 'pages': len(pages)}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(one, jobs))
    reviewed = time.monotonic()
    answers = [(m, a if a and not a.get('error') else None) for m, a, _ in results]
    story = next((a for m, a in answers if m['area'] == 'story'), None) or {}
    merged, merge_info = ask(merger_prompt(ctx, answers), [], 'person')
    review = {'verdict': (merged or {}).get('verdict') or story.get('verdict'),
              'retell': story.get('retell'), 'promise_paid': story.get('promise_paid'),
              'checked': '; '.join(f"{m['id']}: {(a or {}).get('checked') or 'no answer'}" for m, a in answers)[:3000],
              'problems': (merged or {}).get('problems') if merged and not merged.get('error') else
              [p for _, a in answers for p in (a or {}).get('problems') or []],
              'previously': _previously(answers),
              'panel': [{'id': m['id'], 'area': m['area'], 'tier': m['tier'], 'slice': m['slice'],
                         'answered': bool(a and not a.get('error')), 'problems': len((a or {}).get('problems') or []),
                         **info} for m, a, info in results],
              'merger': {**merge_info, 'answered': bool(merged and not merged.get('error')),
                         'dropped': (merged or {}).get('dropped')},
              'panel_seconds': {'reviewers': round(reviewed - t0, 1), 'merger': round(time.monotonic() - reviewed, 1)}}
    if not review['verdict']:
        review = {'error': 'The review panel gave no usable answer. Run it again.', 'error_kind': 'no_answer',
                  'engine': None, 'attempts': [], 'panel': review['panel']}
    for key in ('engine', 'model', 'effort', 'same_vendor'):
        review.setdefault(key, next((i.get(key) for m, a, i in results if m['area'] == 'story'), None))
    return review
